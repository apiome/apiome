"""Trust-manifest drift, shadowing, and regression detection for MCP servers (CLX-3.4, #4858).

A point-in-time score cannot tell you a server *changed for the worse* after you approved it.
This module builds a **trust manifest** — a single, comparable fingerprint over everything that
makes an MCP server trustworthy — and diffs each rediscovery/release against an operator-approved
**baseline**, classifying every material change so a rug pull, a silent permission escalation, or a
lost capability is caught rather than blessed by a stale green badge.

The manifest is deliberately composed from evidence that already exists rather than recomputed:

* **identity** — server name/title/version and the negotiated protocol version.
* **transport** — the transport kind plus a *stable* projection of the observed transport metadata
  (TLS/host facts), with volatile timing fields dropped so a slow connection is not a "change".
* **capabilities / tool-resource-prompt metadata / normalized schemas** — carried whole by the
  existing ``surface_fingerprint`` (:meth:`app.mcp_client.normalize.DiscoverySurface.fingerprint`);
  this module reuses that hash rather than minting a second one.
* **policy-relevant permissions** — the authority-bearing tool annotations (``readOnlyHint`` /
  ``destructiveHint`` / ``openWorldHint`` / ``idempotentHint``), projected out so a tool that
  quietly becomes destructive or open-world is a first-class, separately classifiable delta.
* **source digest** — the linked source/artifact digests and SBOM fingerprints
  (``mcp_endpoint_sources`` / ``mcp_source_sboms``), so a swapped-out release behind an unchanged URL
  is visible.

Two comparisons live here, both pure (no DB, no network):

1. :func:`diff_trust_manifests` — baseline manifest + surface vs. current manifest + surface. Every
   change is classified into exactly one of :data:`DRIFT_CATEGORIES` (normal change, quality
   regression, security regression, coverage loss) and carries an old→new evidence reference, then a
   :class:`DriftGate` decides pass/warn/blocked over the *configured* gating categories.
2. :func:`detect_shadowed_names` — duplicate/shadowed tool/resource/prompt names across the enabled
   endpoints of a host scope, the cross-endpoint sibling of the single-server surface diff.

Both the surface diff and the additive/review/breaking severity of a modified capability are taken
from the canonical engines (:func:`app.mcp_client.diff.diff_surfaces`,
:func:`app.mcp_change_severity.classify_change`) so "what changed" and "how bad is a schema edit"
have a single source of truth.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .mcp_change_severity import (
    SEVERITY_BREAKING,
    SEVERITY_REVIEW,
    classify_change,
)
from .mcp_client.diff import (
    CHANGE_ADDED,
    CHANGE_REMOVED,
    ITEM_TYPE_SERVER,
    ItemChange,
    SurfaceDiff,
    diff_surfaces,
)
from .mcp_client.normalize import DiscoverySurface, ITEM_TYPE_TOOL
from .models import mcp_endpoint_host

# ===========================================================================
# Drift categories — the four buckets AC4 requires.
# ===========================================================================

#: A benign, expected change: a new capability, a description tweak, a routine version bump, a new
#: source link. Worth recording in the feed, never worth blocking.
DRIFT_NORMAL = "normal_change"

#: The offering got *worse* without losing coverage or authority: a breaking schema edit, a lost
#: output schema, a dependency inventory that disappeared. Not a security event, but a quality
#: regression a reviewer should see.
DRIFT_QUALITY_REGRESSION = "quality_regression"

#: The server's *authority* or *provenance* regressed: a tool became destructive/open-world, a
#: read-only tool is no longer read-only, a pinned source digest became unverified, the transport
#: changed underneath a stable URL, or a tool name now shadows another enabled server's. The reason
#: baselines exist.
DRIFT_SECURITY_REGRESSION = "security_regression"

#: Something that was covered is gone: a tool/resource/prompt was removed, or a whole source link was
#: retired with nothing replacing it. Coverage loss is how a rug pull *hides* — the risky surface is
#: simply withdrawn from view.
DRIFT_COVERAGE_LOSS = "coverage_loss"

#: All four, ordered least→most severe. The index is each category's rank, so
#: :func:`_max_category` folds a set of changes into the worst one and the alert severity is stable.
DRIFT_CATEGORIES: Tuple[str, ...] = (
    DRIFT_NORMAL,
    DRIFT_QUALITY_REGRESSION,
    DRIFT_COVERAGE_LOSS,
    DRIFT_SECURITY_REGRESSION,
)
_CATEGORY_RANK: Dict[str, int] = {name: rank for rank, name in enumerate(DRIFT_CATEGORIES)}

#: The categories that are regressions (everything except a normal change). Used to decide whether a
#: drift is worth an alert at all.
REGRESSION_CATEGORIES: Tuple[str, ...] = (
    DRIFT_QUALITY_REGRESSION,
    DRIFT_COVERAGE_LOSS,
    DRIFT_SECURITY_REGRESSION,
)

#: The default set of categories that *gate* (block) when present. Security regressions and coverage
#: loss are the dangerous deltas; a quality regression warns but does not block by default. An
#: operator can widen or narrow this per call ("configured risk deltas", AC).
DEFAULT_GATING_CATEGORIES: Tuple[str, ...] = (
    DRIFT_SECURITY_REGRESSION,
    DRIFT_COVERAGE_LOSS,
)

# The gate's three outcomes.
GATE_PASS = "pass"
GATE_WARN = "warn"
GATE_BLOCKED = "blocked"

#: Tool annotation keys that carry *authority* — the policy-relevant permissions the manifest tracks
#: distinctly from the rest of the surface. A change to any of these is judged for escalation.
AUTHORITY_ANNOTATIONS: Tuple[str, ...] = (
    "readOnlyHint",
    "destructiveHint",
    "openWorldHint",
    "idempotentHint",
)

#: Verification states of a source digest, weakest→strongest. A move *down* this ladder (e.g. a
#: previously ``digest_pinned`` source now ``unverified``) is a provenance regression.
_VERIFICATION_ORDER: Tuple[str, ...] = ("unverified", "digest_pinned", "attested")
_VERIFICATION_RANK: Dict[str, int] = {
    name: rank for rank, name in enumerate(_VERIFICATION_ORDER)
}

# Transport-metadata keys are kept in the manifest only if they are *stable* identity facts. Any key
# whose (lowercased) name contains one of these fragments is a timing/observation artifact and is
# dropped, so a slower handshake or a fresh ``observed_at`` never reads as drift.
_VOLATILE_TRANSPORT_FRAGMENTS: Tuple[str, ...] = (
    "latency",
    "elapsed",
    "duration",
    "timing",
    "observed_at",
    "checked_at",
    "measured_at",
    "_at",
    "rtt",
    "ms",
    "seconds",
    "millis",
)

#: The manifest fingerprint algorithm id, stored beside the digest so the composition can evolve
#: without silently invalidating older baselines.
MANIFEST_ALGORITHM = "sha256-trust-manifest-v1"


# ===========================================================================
# Small pure helpers.
# ===========================================================================


def _canonical_json(value: Any) -> str:
    """Byte-stable canonical JSON: keys sorted recursively, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    """SHA-256 over the canonical JSON of ``value``."""
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _max_category(categories: Sequence[str]) -> str:
    """Fold a set of drift categories into the most severe one (``normal_change`` if empty)."""
    worst = DRIFT_NORMAL
    for category in categories:
        if _CATEGORY_RANK.get(category, 0) > _CATEGORY_RANK[worst]:
            worst = category
    return worst


def _authority_projection(annotations: Any) -> Dict[str, Any]:
    """Extract the authority-bearing subset of a capability item's ``annotations``.

    Returns only the keys in :data:`AUTHORITY_ANNOTATIONS` that are present, so two tools that differ
    only in cosmetic annotations project identically and a change here is unambiguously about
    authority.
    """
    if not isinstance(annotations, Mapping):
        return {}
    return {
        key: annotations[key] for key in AUTHORITY_ANNOTATIONS if key in annotations
    }


def _transport_projection(
    transport_kind: Optional[str], transport_metadata: Any
) -> Dict[str, Any]:
    """Project an endpoint's transport to its stable identity facts.

    The transport *kind* is always kept (a stdio→http switch is a material change). The observed
    ``transport_metadata`` is kept only for its non-volatile keys — TLS issuer/subject, host, header
    facts — with any timing/observation key dropped (see :data:`_VOLATILE_TRANSPORT_FRAGMENTS`), so
    the projection is stable across re-observations of an unchanged endpoint.
    """
    projection: Dict[str, Any] = {"kind": transport_kind or None}
    if isinstance(transport_metadata, Mapping):
        stable: Dict[str, Any] = {}
        for key, value in transport_metadata.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in _VOLATILE_TRANSPORT_FRAGMENTS):
                continue
            stable[str(key)] = value
        if stable:
            projection["metadata"] = stable
    return projection


def _source_projection(source_row: Mapping[str, Any], sbom_fingerprint: Optional[str]) -> Dict[str, Any]:
    """Project one ``mcp_endpoint_sources`` row (+ its SBOM fingerprint) to its trust facts."""
    return {
        "source_kind": source_row.get("source_kind"),
        "locator": source_row.get("locator"),
        "purl": source_row.get("purl"),
        "revision": source_row.get("revision"),
        "digest": source_row.get("digest"),
        "digest_algorithm": source_row.get("digest_algorithm"),
        "provenance": source_row.get("provenance"),
        "verification_state": source_row.get("verification_state"),
        "sbom_fingerprint": sbom_fingerprint,
    }


def _source_key(projection: Mapping[str, Any]) -> Tuple[str, str]:
    """The stable identity of a source projection: (kind, locator)."""
    return (str(projection.get("source_kind") or ""), str(projection.get("locator") or ""))


# ===========================================================================
# Trust manifest.
# ===========================================================================


@dataclass(frozen=True)
class TrustManifest:
    """The composed, comparable trust fingerprint of one MCP endpoint snapshot.

    Every field is a deterministic projection of persisted evidence; :meth:`fingerprint` folds them
    into a single stable digest and :meth:`component_fingerprints` gives one per component so a diff
    can attribute a change to identity, transport, surface, permissions, or source without re-diffing
    the whole manifest.

    Attributes:
        identity: Server name/title/version and negotiated protocol version.
        transport: The transport kind plus its stable metadata projection.
        surface_fingerprint: The reused ``surface_fingerprint`` covering capabilities, tool/resource/
            prompt metadata, and normalized schemas (``None`` when the endpoint was never discovered).
        permissions: Per-tool authority-annotation projections, sorted by tool name.
        sources: Per-source digest/SBOM projections, sorted by (kind, locator).
    """

    identity: Dict[str, Any] = field(default_factory=dict)
    transport: Dict[str, Any] = field(default_factory=dict)
    surface_fingerprint: Optional[str] = None
    permissions: Tuple[Dict[str, Any], ...] = ()
    sources: Tuple[Dict[str, Any], ...] = ()

    def canonical_dict(self) -> Dict[str, Any]:
        """The manifest's semantic projection as a plain, JSON-ready dict (the fingerprint input)."""
        return {
            "identity": self.identity,
            "transport": self.transport,
            "surfaceFingerprint": self.surface_fingerprint,
            "permissions": list(self.permissions),
            "sources": list(self.sources),
        }

    def component_fingerprints(self) -> Dict[str, str]:
        """A stable digest per component, so a diff can name *which* facet moved."""
        return {
            "identity": _digest(self.identity),
            "transport": _digest(self.transport),
            "surface": _digest(self.surface_fingerprint),
            "permissions": _digest(list(self.permissions)),
            "sources": _digest(list(self.sources)),
        }

    def fingerprint(self) -> str:
        """The single SHA-256 trust-manifest fingerprint over :meth:`canonical_dict`."""
        return _digest(self.canonical_dict())

    def as_dict(self) -> Dict[str, Any]:
        """The full manifest envelope stored on an approved baseline (fingerprint + components)."""
        return {
            "algorithm": MANIFEST_ALGORITHM,
            "fingerprint": self.fingerprint(),
            "components": self.component_fingerprints(),
            **self.canonical_dict(),
        }


def _tool_permission_projections(
    capability_rows: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], ...]:
    """Project every tool's authority annotations, sorted by name (stable, empty when no tools)."""
    projections: List[Dict[str, Any]] = []
    for row in capability_rows:
        if str(row.get("item_type")) != ITEM_TYPE_TOOL:
            continue
        authority = _authority_projection(row.get("annotations"))
        projections.append({"name": row.get("name"), "annotations": authority})
    projections.sort(key=lambda item: str(item.get("name") or ""))
    return tuple(projections)


def build_trust_manifest(
    *,
    endpoint_row: Mapping[str, Any],
    version_row: Optional[Mapping[str, Any]],
    capability_rows: Sequence[Mapping[str, Any]],
    source_rows: Sequence[Mapping[str, Any]] = (),
    sbom_fingerprints: Optional[Mapping[str, Optional[str]]] = None,
) -> TrustManifest:
    """Compose the trust manifest for one endpoint snapshot from its persisted rows.

    Args:
        endpoint_row: The ``mcp_endpoints`` row (transport, transport metadata).
        version_row: The snapshot's ``mcp_endpoint_versions`` row (identity + ``surface_fingerprint``),
            or ``None`` when the endpoint has never been discovered.
        capability_rows: The snapshot's ``mcp_capability_items`` rows (for tool authority annotations).
        source_rows: The endpoint's live ``mcp_endpoint_sources`` rows.
        sbom_fingerprints: Optional map of source id → latest ``sbom_fingerprint`` (``None`` when a
            source has no inventory).

    Returns:
        The composed :class:`TrustManifest`.
    """
    sbom_fingerprints = sbom_fingerprints or {}
    identity: Dict[str, Any] = {}
    surface_fingerprint: Optional[str] = None
    if version_row is not None:
        identity = {
            "server_name": version_row.get("server_name"),
            "server_title": version_row.get("server_title"),
            "server_version": version_row.get("server_version"),
            "protocol_version": version_row.get("protocol_version"),
        }
        surface_fingerprint = version_row.get("surface_fingerprint")

    transport = _transport_projection(
        endpoint_row.get("transport"), endpoint_row.get("transport_metadata")
    )

    sources = [
        _source_projection(row, sbom_fingerprints.get(str(row.get("id"))))
        for row in source_rows
    ]
    sources.sort(key=_source_key)

    return TrustManifest(
        identity=identity,
        transport=transport,
        surface_fingerprint=surface_fingerprint,
        permissions=_tool_permission_projections(capability_rows),
        sources=tuple(sources),
    )


# ===========================================================================
# Drift changes + gate.
# ===========================================================================


@dataclass(frozen=True)
class DriftChange:
    """One classified difference between a baseline and current trust manifest.

    Attributes:
        category: One of :data:`DRIFT_CATEGORIES`.
        component: The manifest facet that moved (``capability`` / ``identity`` / ``permissions`` /
            ``source`` / ``transport``).
        path: A stable, human-readable locator (e.g. ``tool:search`` or ``source:git:github.com/x``).
        summary: A one-line description of the change.
        before: The value in the baseline (``None`` when newly present).
        after: The value now (``None`` when removed).
    """

    category: str
    component: str
    path: str
    summary: str
    before: Any = None
    after: Any = None

    def as_dict(self, *, baseline_ref: Mapping[str, Any], current_ref: Mapping[str, Any]) -> Dict[str, Any]:
        """Render with its old→new evidence references (AC1: every change links its evidence)."""
        return {
            "category": self.category,
            "component": self.component,
            "path": self.path,
            "summary": self.summary,
            "before": self.before,
            "after": self.after,
            "evidence": {"baseline": dict(baseline_ref), "current": dict(current_ref)},
        }


@dataclass(frozen=True)
class DriftGate:
    """The pass / warn / blocked decision over the configured gating categories.

    ``blocked`` when any change falls in a gating category; ``warn`` when there are regressions but
    none gate; ``pass`` when nothing regressed.
    """

    status: str
    blocking_categories: Tuple[str, ...]
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "blocking_categories": list(self.blocking_categories),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TrustDrift:
    """The full baseline-vs-current drift report for one endpoint.

    Attributes:
        baseline_fingerprint: The approved baseline's manifest fingerprint.
        current_fingerprint: The current snapshot's manifest fingerprint.
        changes: Every classified :class:`DriftChange`, most-severe category first then by path.
        category_counts: Count per drift category (all four keys always present).
        alert_severity: The most severe category present (``normal_change`` when unchanged).
        gate: The :class:`DriftGate` decision.
        baseline_ref: Evidence reference for the baseline side (version id/tag/timestamps).
        current_ref: Evidence reference for the current side.
    """

    baseline_fingerprint: Optional[str]
    current_fingerprint: Optional[str]
    changes: Tuple[DriftChange, ...]
    category_counts: Mapping[str, int]
    alert_severity: str
    gate: DriftGate
    baseline_ref: Mapping[str, Any]
    current_ref: Mapping[str, Any]

    @property
    def unchanged(self) -> bool:
        """Whether the manifests are identical (nothing drifted)."""
        return (
            self.baseline_fingerprint == self.current_fingerprint and not self.changes
        )

    @property
    def has_regression(self) -> bool:
        """Whether any change is a regression (quality, security, or coverage loss)."""
        return any(change.category in REGRESSION_CATEGORIES for change in self.changes)

    def as_dict(self) -> Dict[str, Any]:
        """Render the whole report as a JSON-ready dict, each change carrying its evidence links."""
        return {
            "baseline_fingerprint": self.baseline_fingerprint,
            "current_fingerprint": self.current_fingerprint,
            "unchanged": self.unchanged,
            "alert_severity": self.alert_severity,
            "has_regression": self.has_regression,
            "category_counts": dict(self.category_counts),
            "gate": self.gate.as_dict(),
            "changes": [
                change.as_dict(baseline_ref=self.baseline_ref, current_ref=self.current_ref)
                for change in self.changes
            ],
        }


# ===========================================================================
# Classification.
# ===========================================================================


def _permission_escalation(before: Any, after: Any) -> Optional[str]:
    """Return a summary when a tool's authority annotations *escalated*, else ``None``.

    Escalation is one-directional and conservative: a tool losing ``readOnlyHint: true``, or gaining
    ``destructiveHint: true`` / ``openWorldHint: true``, is an escalation. The reverse (a tool
    becoming *more* constrained) is not.
    """
    before_ann = _authority_projection(before.get("annotations") if isinstance(before, Mapping) else None)
    after_ann = _authority_projection(after.get("annotations") if isinstance(after, Mapping) else None)
    reasons: List[str] = []
    if before_ann.get("readOnlyHint") is True and after_ann.get("readOnlyHint") is not True:
        reasons.append("no longer declares readOnlyHint")
    if before_ann.get("destructiveHint") is not True and after_ann.get("destructiveHint") is True:
        reasons.append("now declares destructiveHint")
    if before_ann.get("openWorldHint") is not True and after_ann.get("openWorldHint") is True:
        reasons.append("now declares openWorldHint")
    return "; ".join(reasons) if reasons else None


def _classify_capability_change(change: ItemChange) -> Tuple[str, str]:
    """Classify one surface :class:`ItemChange` into a drift category with a summary.

    * A removed capability is :data:`DRIFT_COVERAGE_LOSS`.
    * An added capability is :data:`DRIFT_NORMAL`.
    * A modified capability is a :data:`DRIFT_SECURITY_REGRESSION` when its authority annotations
      escalate; otherwise its canonical severity decides — ``breaking`` →
      :data:`DRIFT_QUALITY_REGRESSION`, ``additive``/``review`` → :data:`DRIFT_NORMAL`.
    * A modified server-metadata field is :data:`DRIFT_NORMAL` (identity moves are expected;
      capability-capability drops are surfaced by the capability items themselves).
    """
    kind = change.item_type
    name = change.name
    if change.change_type == CHANGE_REMOVED:
        return DRIFT_COVERAGE_LOSS, f"{kind} '{name}' was removed"
    if change.change_type == CHANGE_ADDED:
        return DRIFT_NORMAL, f"{kind} '{name}' was added"

    # Modified.
    if kind == ITEM_TYPE_SERVER:
        return DRIFT_NORMAL, f"server metadata '{name}' changed"

    if kind == ITEM_TYPE_TOOL:
        escalation = _permission_escalation(change.before, change.after)
        if escalation is not None:
            return DRIFT_SECURITY_REGRESSION, f"tool '{name}' {escalation}"

    severity = classify_change(change.to_change_row(None))
    if severity == SEVERITY_BREAKING:
        return DRIFT_QUALITY_REGRESSION, f"{kind} '{name}' changed incompatibly"
    if severity == SEVERITY_REVIEW:
        return DRIFT_NORMAL, f"{kind} '{name}' changed (review)"
    return DRIFT_NORMAL, f"{kind} '{name}' changed"


def _capability_path(change: ItemChange) -> str:
    """Stable locator for a capability/server change (e.g. ``tool:search`` / ``server:instructions``)."""
    return f"{change.item_type}:{change.name}"


def _classify_source_changes(
    baseline_sources: Sequence[Mapping[str, Any]],
    current_sources: Sequence[Mapping[str, Any]],
) -> List[DriftChange]:
    """Classify the difference between the baseline and current source projections.

    A retired source (present in baseline, gone now) is :data:`DRIFT_COVERAGE_LOSS`; a new source is
    :data:`DRIFT_NORMAL`. For a source present in both: a *drop* in verification state (e.g.
    ``digest_pinned`` → ``unverified``) or a digest that changed while unpinned is a
    :data:`DRIFT_SECURITY_REGRESSION`; a lost SBOM fingerprint is a :data:`DRIFT_QUALITY_REGRESSION`;
    any other digest change is :data:`DRIFT_NORMAL` (a legitimate release).
    """
    baseline_by_key = {_source_key(s): s for s in baseline_sources}
    current_by_key = {_source_key(s): s for s in current_sources}
    changes: List[DriftChange] = []

    for key, base in baseline_by_key.items():
        path = f"source:{key[0]}:{key[1]}"
        if key not in current_by_key:
            changes.append(
                DriftChange(
                    category=DRIFT_COVERAGE_LOSS,
                    component="source",
                    path=path,
                    summary=f"source '{key[1]}' was retired",
                    before=dict(base),
                    after=None,
                )
            )
            continue
        cur = current_by_key[key]
        base_state = str(base.get("verification_state") or "unverified")
        cur_state = str(cur.get("verification_state") or "unverified")
        if _VERIFICATION_RANK.get(cur_state, 0) < _VERIFICATION_RANK.get(base_state, 0):
            changes.append(
                DriftChange(
                    category=DRIFT_SECURITY_REGRESSION,
                    component="source",
                    path=path,
                    summary=f"source '{key[1]}' verification regressed {base_state} → {cur_state}",
                    before=dict(base),
                    after=dict(cur),
                )
            )
            continue
        digest_changed = base.get("digest") != cur.get("digest")
        if digest_changed and cur_state == "unverified":
            changes.append(
                DriftChange(
                    category=DRIFT_SECURITY_REGRESSION,
                    component="source",
                    path=path,
                    summary=f"source '{key[1]}' digest changed while unverified",
                    before=dict(base),
                    after=dict(cur),
                )
            )
            continue
        if base.get("sbom_fingerprint") and not cur.get("sbom_fingerprint"):
            changes.append(
                DriftChange(
                    category=DRIFT_QUALITY_REGRESSION,
                    component="source",
                    path=path,
                    summary=f"source '{key[1]}' lost its dependency inventory",
                    before=dict(base),
                    after=dict(cur),
                )
            )
            continue
        if digest_changed or base.get("sbom_fingerprint") != cur.get("sbom_fingerprint"):
            changes.append(
                DriftChange(
                    category=DRIFT_NORMAL,
                    component="source",
                    path=path,
                    summary=f"source '{key[1]}' released a new artifact",
                    before=dict(base),
                    after=dict(cur),
                )
            )

    for key, cur in current_by_key.items():
        if key not in baseline_by_key:
            changes.append(
                DriftChange(
                    category=DRIFT_NORMAL,
                    component="source",
                    path=f"source:{key[0]}:{key[1]}",
                    summary=f"source '{key[1]}' was linked",
                    before=None,
                    after=dict(cur),
                )
            )
    return changes


def _classify_transport_change(
    baseline_transport: Mapping[str, Any], current_transport: Mapping[str, Any]
) -> Optional[DriftChange]:
    """A transport *kind* change under a stable endpoint is a security regression; metadata-only is normal."""
    base_kind = baseline_transport.get("kind")
    cur_kind = current_transport.get("kind")
    if base_kind != cur_kind:
        return DriftChange(
            category=DRIFT_SECURITY_REGRESSION,
            component="transport",
            path="transport:kind",
            summary=f"transport changed {base_kind} → {cur_kind}",
            before=base_kind,
            after=cur_kind,
        )
    if baseline_transport.get("metadata") != current_transport.get("metadata"):
        return DriftChange(
            category=DRIFT_NORMAL,
            component="transport",
            path="transport:metadata",
            summary="transport metadata changed",
            before=baseline_transport.get("metadata"),
            after=current_transport.get("metadata"),
        )
    return None


def diff_trust_manifests(
    *,
    baseline_manifest: Mapping[str, Any],
    baseline_surface: DiscoverySurface,
    baseline_ref: Mapping[str, Any],
    current_manifest: TrustManifest,
    current_surface: DiscoverySurface,
    current_ref: Mapping[str, Any],
    gating_categories: Sequence[str] = DEFAULT_GATING_CATEGORIES,
) -> TrustDrift:
    """Diff an approved baseline manifest against the current snapshot and classify every change.

    Capability/identity changes come from the canonical :func:`app.mcp_client.diff.diff_surfaces`
    over the two reconstructed surfaces; source and transport changes come from the manifest
    projections. Each change is classified into one of :data:`DRIFT_CATEGORIES` and carries an
    old→new evidence reference; a :class:`DriftGate` then decides pass/warn/blocked over
    ``gating_categories`` (the configured risk deltas).

    Args:
        baseline_manifest: The stored baseline manifest envelope (from :meth:`TrustManifest.as_dict`).
        baseline_surface: The baseline snapshot's reconstructed surface.
        baseline_ref: Evidence reference for the baseline (e.g. version id/tag/approved_at).
        current_manifest: The freshly composed current :class:`TrustManifest`.
        current_surface: The current snapshot's reconstructed surface.
        current_ref: Evidence reference for the current snapshot.
        gating_categories: Categories that block the gate; defaults to
            :data:`DEFAULT_GATING_CATEGORIES`.

    Returns:
        The classified :class:`TrustDrift` report.
    """
    changes: List[DriftChange] = []

    surface_diff: SurfaceDiff = diff_surfaces(baseline_surface, current_surface)
    for item_change in surface_diff.changes:
        category, summary = _classify_capability_change(item_change)
        changes.append(
            DriftChange(
                category=category,
                component="capability" if item_change.item_type != ITEM_TYPE_SERVER else "identity",
                path=_capability_path(item_change),
                summary=summary,
                before=item_change.before,
                after=item_change.after,
            )
        )

    changes.extend(
        _classify_source_changes(
            list(baseline_manifest.get("sources") or ()),
            list(current_manifest.sources),
        )
    )

    transport_change = _classify_transport_change(
        baseline_manifest.get("transport") or {}, current_manifest.transport
    )
    if transport_change is not None:
        changes.append(transport_change)

    changes.sort(
        key=lambda c: (-_CATEGORY_RANK.get(c.category, 0), c.component, c.path)
    )

    counts = {category: 0 for category in DRIFT_CATEGORIES}
    for change in changes:
        counts[change.category] = counts.get(change.category, 0) + 1

    alert_severity = _max_category([c.category for c in changes])
    gate = _decide_gate(changes, gating_categories)

    baseline_fp = baseline_manifest.get("fingerprint")
    return TrustDrift(
        baseline_fingerprint=baseline_fp,
        current_fingerprint=current_manifest.fingerprint(),
        changes=tuple(changes),
        category_counts=counts,
        alert_severity=alert_severity,
        gate=gate,
        baseline_ref=baseline_ref,
        current_ref=current_ref,
    )


def _decide_gate(
    changes: Sequence[DriftChange], gating_categories: Sequence[str]
) -> DriftGate:
    """Resolve the gate: blocked on a gating-category change, warn on any regression, else pass."""
    gating = tuple(gating_categories)
    blocking = tuple(sorted({c.category for c in changes if c.category in gating}))
    if blocking:
        return DriftGate(
            status=GATE_BLOCKED,
            blocking_categories=blocking,
            reason="A configured risk delta was detected against the approved baseline.",
        )
    if any(c.category in REGRESSION_CATEGORIES for c in changes):
        return DriftGate(
            status=GATE_WARN,
            blocking_categories=(),
            reason="A regression was detected but no configured gating category applies.",
        )
    return DriftGate(
        status=GATE_PASS,
        blocking_categories=(),
        reason="No regression against the approved baseline.",
    )


# ===========================================================================
# Shadowing detection (AC3) — duplicate/shadowed names in an enabled host scope.
# ===========================================================================


@dataclass(frozen=True)
class ShadowGroup:
    """A tool/resource/prompt name exposed by more than one enabled endpoint.

    Two enabled servers exposing the same tool name is *tool shadowing* (OWASP MCP09): an agent
    routing by name can be steered to the wrong server. When all colliding endpoints share a host the
    signal is strongest (``same_host``), but a cross-host collision is still advisory.

    Attributes:
        item_type: The capability kind whose name collides (``tool``/``resource``/``prompt``/...).
        name: The colliding name (as advertised; comparison is case-insensitive).
        host_scope: ``same_host`` when every endpoint shares a host, else ``cross_host``.
        endpoints: The colliding endpoints (id/name/slug/host), sorted by name.
    """

    item_type: str
    name: str
    host_scope: str
    endpoints: Tuple[Dict[str, Any], ...]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "item_type": self.item_type,
            "name": self.name,
            "host_scope": self.host_scope,
            "endpoint_count": len(self.endpoints),
            "endpoints": [dict(e) for e in self.endpoints],
        }


def detect_shadowed_names(
    capability_rows: Sequence[Mapping[str, Any]],
) -> List[ShadowGroup]:
    """Group capability names that more than one enabled endpoint exposes (tool shadowing).

    Each input row is one capability item of one *enabled* endpoint's current snapshot and must carry
    ``endpoint_id``, ``endpoint_name``, ``endpoint_slug``, ``endpoint_url`` (for host derivation),
    ``item_type``, and ``name``. Names are grouped case-insensitively per ``item_type``; a group is
    a shadowing collision only when it spans ≥2 *distinct* endpoints (the same server listing a name
    once is not shadowing). Groups are ordered most-collided first, then by name.

    Args:
        capability_rows: Capability items across the enabled endpoints of a host scope.

    Returns:
        The shadowing groups (empty when no name is exposed by two or more endpoints).
    """
    buckets: Dict[Tuple[str, str], Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for row in capability_rows:
        item_type = str(row.get("item_type") or "")
        name = str(row.get("name") or "")
        if not item_type or not name:
            continue
        endpoint_id = str(row.get("endpoint_id") or "")
        if not endpoint_id:
            continue
        key = (item_type, name.lower())
        # De-dupe within an endpoint: one endpoint exposing a name (even twice) counts once.
        buckets[key][endpoint_id] = {
            "id": endpoint_id,
            "name": row.get("endpoint_name"),
            "slug": row.get("endpoint_slug"),
            "host": mcp_endpoint_host(str(row.get("endpoint_url") or "")),
            "advertised_name": row.get("name"),
        }

    groups: List[ShadowGroup] = []
    for (item_type, _lowered), endpoints_by_id in buckets.items():
        if len(endpoints_by_id) < 2:
            continue
        endpoints = sorted(
            endpoints_by_id.values(), key=lambda e: str(e.get("name") or e.get("id"))
        )
        hosts = {str(e.get("host")) for e in endpoints}
        host_scope = "same_host" if len(hosts) == 1 else "cross_host"
        # The advertised spelling of the first endpoint is representative for display.
        display_name = str(endpoints[0].get("advertised_name") or _lowered)
        groups.append(
            ShadowGroup(
                item_type=item_type,
                name=display_name,
                host_scope=host_scope,
                endpoints=tuple(endpoints),
            )
        )

    groups.sort(key=lambda g: (-len(g.endpoints), g.item_type, g.name.lower()))
    return groups


def shadow_report(capability_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Assemble the advisory shadowing report envelope for the enabled host scope."""
    groups = detect_shadowed_names(capability_rows)
    same_host = sum(1 for g in groups if g.host_scope == "same_host")
    return {
        "advisory": True,
        "group_count": len(groups),
        "same_host_count": same_host,
        "cross_host_count": len(groups) - same_host,
        "groups": [g.as_dict() for g in groups],
    }
