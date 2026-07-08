"""Server report-card export — serialize an endpoint's Insight assessment (V2-MCP-33.1 / MCAT-19.1).

The Insight tab is only useful behind auth and inside the app. This module renders a
**self-contained one-page report** for a single endpoint version so a human can drop the
assessment into a ticket, a review, or a wiki. It serializes exactly the panels the in-app
Insight view already shows — identity (15.1), grade + score breakdown (17.3), capability
surface + safety posture (15.3/15.4), documentation coverage (15.5), license & terms signals
(20.3), deprecation & lifecycle signals (20.4), the composite trust radar (17.4), and the
change-since-previous summary — into **Markdown** and **HTML** (the HTML carries a print
stylesheet, so "PDF" is the browser's print-to-PDF of the same document).

Design rules:

* **No new computation.** The route hands this module the values the Insight endpoints already
  compute (surface metrics, trust profile, the stored lint report, the persisted change rows);
  the functions here only *shape and render*. Rendering is pure and deterministic — the same
  inputs always produce byte-identical output — so it is trivially testable without a database.
* **Never leaks a secret.** The report only ever receives an auth *posture* string
  (``"anonymous"`` / ``"authenticated"``) and the credential's ``auth_type`` label; the sealed
  credential payload never reaches this layer. There is no code path here that could emit one.
* **Graceful partial.** A never-discovered or never-scored endpoint still produces a coherent
  report — every section that has no data renders an explicit "not available yet" rather than
  raising — so the export works for any catalog row, not just fully-assessed ones.

The public surface is :func:`build_report_card` (assemble the immutable :class:`ReportCard` view
model) and the two renderers :func:`render_report_markdown` / :func:`render_report_html`.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlparse

#: Cap on the number of lint findings serialized into the report's score breakdown. The full
#: tally still shows in the per-severity/per-rule counts; only the itemized list is bounded so a
#: pathological surface cannot produce a multi-page "report card". Overflow is stated explicitly
#: (never silently dropped) — see :func:`_score_from_report`.
MAX_REPORT_FINDINGS = 20

#: Cap on the number of change rows itemized in the change-since-previous section, for the same
#: reason. The severity roll-up always reflects the full set; overflow is stated explicitly.
MAX_REPORT_CHANGES = 40

#: Canonical (clockwise) trust-axis order — mirrors :class:`app.mcp_insight_aggregation.TrustProfile`
#: so the report's radar table reads in the same order as the in-app panel.
_TRUST_AXIS_ORDER = ("quality", "safety", "documentation", "stability", "responsiveness")


# ===========================================================================================
# View model
# ===========================================================================================


@dataclass(frozen=True)
class ReportCard:
    """The immutable, render-ready view model for one endpoint's report card.

    Every section is optional: a section is ``None`` when the endpoint has no data for it (never
    discovered → no ``version``/``surface``; never scored → no ``score``; first version → no
    ``change``). The renderers treat a ``None`` section as "not available yet" and still emit a
    coherent document, so a partial catalog row exports as gracefully as a fully-assessed one.

    Attributes:
        generated_at: ISO-8601 timestamp the report was rendered (caller-supplied, so rendering
            stays pure/deterministic for a fixed input).
        identity: Always-present endpoint identity (name, host, transport, category, visibility,
            auth posture, discovery recency). See :func:`_identity`.
        version: The serialized version snapshot (seq, tag, server identity, protocol) or ``None``
            when the endpoint was never discovered.
        score: The lint score breakdown (score, grade, per-severity/per-rule tallies, top
            findings) or ``None`` when the snapshot has not been scored.
        surface: The capability-surface summary (per-kind counts, tool-complexity roll-up) or
            ``None`` when there is no discovered surface.
        safety: The safety/annotation posture (annotation coverage, destructive-tool count, auth
            posture) or ``None`` when there is no discovered surface.
        documentation: The documentation & schema coverage meters or ``None`` when undiscovered.
        license: The license & terms signal report (V2-MCP-34.3) or ``None`` when undiscovered.
            Note the asymmetry with the other sections: a discovered snapshot with *no* signal
            still has a section — its status is "not stated", which is a result, not missing data.
        lifecycle: The deprecation & lifecycle signal report (V2-MCP-34.4) or ``None`` when
            undiscovered. Same asymmetry as ``license``: a discovered snapshot with no flagged
            capability still has a section — "no signals" is a result, and it is deliberately
            never worded as a "stable" claim.
        trust: The five-axis composite trust profile or ``None`` when undiscovered.
        change: The change-since-previous summary (severity roll-up + itemized rows) or ``None``
            when the snapshot introduced no diff (the first version, or an unchanged re-discovery).
        provenance: How the catalog knows the server (V2-MCP-34.5) — how the endpoint was added
            and which discovery runs produced its versions — or ``None`` when the route did not
            supply it. A never-discovered endpoint still has a section (its ``added_via`` is a
            fact even before any snapshot exists).
    """

    generated_at: str
    identity: "ReportIdentity"
    version: Optional["ReportVersion"] = None
    score: Optional["ReportScore"] = None
    surface: Optional["ReportSurface"] = None
    safety: Optional["ReportSafety"] = None
    documentation: Optional[Dict[str, Any]] = None
    license: Optional["ReportLicense"] = None
    lifecycle: Optional["ReportLifecycle"] = None
    trust: Optional["ReportTrust"] = None
    change: Optional["ReportChange"] = None
    provenance: Optional["ReportProvenance"] = None
    cataloger_notes: Optional[List["ReportCatalogerNote"]] = None


@dataclass(frozen=True)
class ReportIdentity:
    """At-a-glance endpoint identity (serializes the 15.1 profile card)."""

    name: str
    slug: Optional[str]
    host: Optional[str]
    endpoint_url: Optional[str]
    transport: Optional[str]
    category: Optional[str]
    visibility: Optional[str]
    published: bool
    description: Optional[str]
    auth_posture: str
    auth_type: Optional[str]
    last_discovered_at: Optional[str]
    last_discovery_status: Optional[str]


@dataclass(frozen=True)
class ReportVersion:
    """The serialized version snapshot the report describes."""

    version_seq: Optional[int]
    version_tag: Optional[str]
    server_name: Optional[str]
    server_title: Optional[str]
    server_version: Optional[str]
    protocol_version: Optional[str]
    discovered_at: Optional[str]
    is_current: bool


@dataclass(frozen=True)
class ReportScore:
    """The lint score breakdown (serializes the 17.3 score & findings panel)."""

    score: Optional[int]
    grade: Optional[str]
    severity_counts: Dict[str, int]
    rule_hits: Dict[str, int]
    findings: List[Dict[str, str]]
    findings_truncated: int


@dataclass(frozen=True)
class ReportSurface:
    """The capability-surface summary (serializes the 15.3 shape/complexity cards)."""

    type_counts: Dict[str, int]
    tool_count: int
    avg_property_count: Optional[float]
    max_nesting_depth: int
    tools_using_enum: int
    tools_with_output_schema: int
    output_schema_count: int


@dataclass(frozen=True)
class ReportSafety:
    """The safety & annotation posture (serializes the 15.4 panel)."""

    annotation_coverage: Dict[str, int]
    destructive_tool_count: int
    auth_posture: str
    auth_type: Optional[str]


@dataclass(frozen=True)
class ReportLicense:
    """The license & terms signal report (serializes the 20.3 detector result).

    ``status`` is ``"detected"`` or ``"not_stated"`` — the latter is the careful wording for
    "the server's text states nothing", never a claim that no license exists. ``statement``
    carries the detector's pre-worded one-line summary so every renderer states absence the
    same way. Signal rows are the detector's JSON-ready dicts (``kind`` / ``source`` /
    ``matched`` / ``excerpt``), already bounded and deterministically ordered upstream.
    """

    status: str
    statement: str
    signals: List[Dict[str, str]]
    signals_truncated: int
    sources_scanned: List[str]


@dataclass(frozen=True)
class ReportLifecycle:
    """The deprecation & lifecycle signal report (serializes the 20.4 detector result).

    ``status`` is ``"detected"`` or ``"none_detected"`` — the latter is the careful wording
    for "no capability said anything about its lifecycle", never a claim that the surface is
    stable. ``statement`` carries the detector's pre-worded one-line summary so every
    renderer states absence the same way. ``stage_counts`` covers **all** capabilities;
    ``flagged`` rows are the detector's JSON-ready per-capability dicts (``item_type`` /
    ``name`` / ``stage`` / ``signals``), already bounded and deterministically ordered
    upstream.
    """

    status: str
    statement: str
    stage_counts: Dict[str, int]
    flagged: List[Dict[str, Any]]
    flagged_truncated: int
    capabilities_scanned: int


@dataclass(frozen=True)
class ReportProvenance:
    """The discovery-provenance report (serializes the 20.5 assembly result).

    Mirrors :meth:`app.mcp_provenance.EndpointProvenance.as_dict`: how the endpoint entered
    the catalog (``added_via`` + its label), when it was first/last discovered, the number of
    snapshots per origin (``origin_counts`` always carries every bucket, including
    ``unrecorded`` — an unattributed snapshot is stated, never hidden), the completed
    discovery runs per trigger (``run_counts``, including unchanged re-runs), the current
    snapshot's origin, and the newest-first per-version origin rows (already bounded and
    labeled upstream; ``origins_truncated`` counts the overflow).
    """

    added_via: str
    added_via_label: str
    added_at: Optional[str]
    first_discovered_at: Optional[str]
    last_discovered_at: Optional[str]
    version_count: int
    origin_counts: Dict[str, int]
    run_counts: Dict[str, int]
    current_origin: Optional[Dict[str, Any]]
    origins: List[Dict[str, Any]]
    origins_truncated: int


@dataclass(frozen=True)
class ReportCatalogerNote:
    """One human cataloger note included in an opted-in report export (MCAT-22.3).

    These are tenant-authored commentary kept separate from server-reported discovery data.
    """

    body: str
    author_label: str
    created_at: str
    updated_at: Optional[str]


@dataclass(frozen=True)
class ReportTrust:
    """The composite trust profile (serializes the 17.4 radar)."""

    axes: List[Dict[str, Any]]
    overall: Optional[float]
    available_count: int
    axis_count: int


@dataclass(frozen=True)
class ReportChange:
    """The change-since-previous summary (severity roll-up + itemized rows)."""

    severity_counts: Dict[str, int]
    rows: List[Dict[str, Optional[str]]] = field(default_factory=list)
    rows_truncated: int = 0


# ===========================================================================================
# Assembly
# ===========================================================================================


def build_report_card(
    *,
    endpoint: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    is_current: bool,
    score_report: Optional[Mapping[str, Any]],
    surface_metrics: Optional[Mapping[str, Any]],
    license_signals: Optional[Mapping[str, Any]] = None,
    lifecycle_signals: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    trust_profile: Optional[Mapping[str, Any]],
    change_rows: Sequence[Mapping[str, Any]],
    change_severity: Optional[Mapping[str, int]],
    auth_posture: str,
    auth_type: Optional[str],
    generated_at: str,
    cataloger_notes: Optional[Sequence[Mapping[str, Any]]] = None,
) -> ReportCard:
    """Assemble the immutable :class:`ReportCard` view model from already-computed inputs.

    This function performs **no** computation over raw surfaces or telemetry — the route passes in
    the exact values the Insight endpoints already produce (``surface_metrics`` from
    :func:`app.mcp_surface_metrics.compute_surface_metrics`, ``trust_profile`` from
    :func:`app.mcp_insight_aggregation.compute_trust_profile`, ``score_report`` from the persisted
    ``mcp_version_scores.report``, and the stored ``change_rows``). Every argument that can be
    absent is accepted as ``None`` / empty and yields a ``None`` section, so a never-discovered or
    never-scored endpoint assembles a coherent partial report.

    Args:
        endpoint: The ``mcp_endpoints`` row (identity columns).
        version: The version snapshot row being reported, or ``None`` when never discovered.
        is_current: Whether ``version`` is the endpoint's current snapshot.
        score_report: The persisted lint report dict (``score``/``grade``/``severity_counts``/
            ``rule_hits``/``findings``), or ``None`` when the snapshot is unscored.
        surface_metrics: The ``compute_surface_metrics`` ``as_dict()`` for the snapshot, or ``None``.
        license_signals: The :func:`app.mcp_license_signals.detect_license_signals`
            ``as_dict()`` for the snapshot, or ``None`` when never discovered. A "nothing
            found" result is *not* ``None`` — it is a report with status ``"not_stated"``,
            and it renders as a section (absence of a statement is itself reportable).
        lifecycle_signals: The :func:`app.mcp_lifecycle_signals.detect_lifecycle_signals`
            ``as_dict()`` for the snapshot's capability items, or ``None`` when never
            discovered. As with ``license_signals``, a "nothing found" result is *not*
            ``None`` — it renders as a section whose wording is never a "stable" claim.
        provenance: The :func:`app.mcp_provenance.build_endpoint_provenance` ``as_dict()``
            for the endpoint, or ``None`` when the caller did not assemble one. Unlike the
            surface sections it does not require a discovered snapshot — how the endpoint
            was added is a fact from registration.
        trust_profile: The ``compute_trust_profile`` ``as_dict()``, or ``None``.
        change_rows: The stored ``previous → this`` change rows (empty for a first/unchanged version).
        change_severity: The ``severity_counts`` roll-up over ``change_rows``, or ``None``.
        auth_posture: ``"anonymous"`` / ``"authenticated"`` — the endpoint's reachability posture.
        auth_type: The credential's auth-type *label* (never the secret), or ``None``.
        generated_at: ISO-8601 timestamp to stamp the report with (keeps rendering pure).
        cataloger_notes: Optional list of cataloger-note rows (from
            :meth:`Database.list_mcp_endpoint_notes`) to include when the export was opted in.
            ``None`` omits the section entirely; an empty list renders an explicit "none recorded"
            note.

    Returns:
        A fully-populated :class:`ReportCard`; sections with no data are ``None``.
    """
    identity = _identity(endpoint, auth_posture, auth_type)

    report_version = _version(version, is_current) if version is not None else None
    score = _score_from_report(score_report) if score_report else None
    surface = _surface(surface_metrics) if surface_metrics else None
    safety = (
        _safety(surface_metrics, auth_posture, auth_type) if surface_metrics else None
    )
    documentation = (
        dict(surface_metrics["documentation_coverage"])
        if surface_metrics and surface_metrics.get("documentation_coverage")
        else None
    )
    # Unlike the other sections, an *empty* license report still renders — "not stated" is a
    # result the reader needs, not missing data — so only a missing report yields None.
    license = _license(license_signals) if license_signals is not None else None
    lifecycle = _lifecycle(lifecycle_signals) if lifecycle_signals is not None else None
    trust = _trust(trust_profile) if trust_profile else None
    change = _change(change_rows, change_severity) if change_rows else None
    report_provenance = _provenance(provenance) if provenance is not None else None
    notes_section = (
        _cataloger_notes(cataloger_notes) if cataloger_notes is not None else None
    )

    return ReportCard(
        generated_at=generated_at,
        identity=identity,
        version=report_version,
        score=score,
        surface=surface,
        safety=safety,
        documentation=documentation,
        license=license,
        lifecycle=lifecycle,
        trust=trust,
        change=change,
        provenance=report_provenance,
        cataloger_notes=notes_section,
    )


def _iso(value: Any) -> Optional[str]:
    """Render a datetime-ish value as an ISO-8601 string, passing through ``None``/strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _identity(
    endpoint: Mapping[str, Any], auth_posture: str, auth_type: Optional[str]
) -> ReportIdentity:
    """Build the identity section from the endpoint row (never emits a secret)."""
    endpoint_url = endpoint.get("endpoint_url")
    host: Optional[str] = None
    if endpoint_url:
        # Best-effort host extraction; a malformed URL simply yields no host rather than raising.
        parsed = urlparse(str(endpoint_url))
        host = parsed.netloc or None
    return ReportIdentity(
        name=str(endpoint.get("name") or "Unnamed endpoint"),
        slug=endpoint.get("slug"),
        host=host,
        endpoint_url=str(endpoint_url) if endpoint_url else None,
        transport=endpoint.get("transport"),
        category=endpoint.get("category"),
        visibility=endpoint.get("visibility"),
        published=bool(endpoint.get("published")),
        description=endpoint.get("description"),
        auth_posture=auth_posture,
        auth_type=auth_type,
        last_discovered_at=_iso(endpoint.get("last_discovered_at")),
        last_discovery_status=endpoint.get("last_discovery_status"),
    )


def _version(version: Mapping[str, Any], is_current: bool) -> ReportVersion:
    """Serialize the version snapshot row."""
    return ReportVersion(
        version_seq=version.get("version_seq"),
        version_tag=version.get("version_tag"),
        server_name=version.get("server_name"),
        server_title=version.get("server_title"),
        server_version=version.get("server_version"),
        protocol_version=version.get("protocol_version"),
        discovered_at=_iso(version.get("discovered_at")),
        is_current=is_current,
    )


def _score_from_report(report: Mapping[str, Any]) -> ReportScore:
    """Shape the persisted lint report into the score section, capping the itemized findings.

    The per-severity and per-rule tallies always reflect the *full* finding set; only the itemized
    list is bounded to :data:`MAX_REPORT_FINDINGS`, and any overflow is reported in
    ``findings_truncated`` so the report can state it explicitly rather than silently dropping rows.
    """
    all_findings = list(report.get("findings") or [])
    shown = all_findings[:MAX_REPORT_FINDINGS]
    return ReportScore(
        score=report.get("score"),
        grade=report.get("grade"),
        severity_counts=dict(report.get("severity_counts") or {}),
        rule_hits=dict(report.get("rule_hits") or {}),
        findings=[
            {
                "rule": str(f.get("rule", "")),
                "severity": str(f.get("severity", "")),
                "message": str(f.get("message", "")),
                "path": str(f.get("path", "")),
            }
            for f in shown
        ],
        findings_truncated=max(0, len(all_findings) - len(shown)),
    )


def _surface(metrics: Mapping[str, Any]) -> ReportSurface:
    """Roll the surface metrics up into the report's capability-surface summary."""
    type_counts = dict(metrics.get("type_counts") or {})
    tools = list(metrics.get("tool_complexity") or [])
    tool_count = len(tools)
    avg_property_count: Optional[float] = None
    if tool_count:
        total_props = sum(int(t.get("property_count") or 0) for t in tools)
        avg_property_count = round(total_props / tool_count, 1)
    max_nesting = max((int(t.get("max_nesting_depth") or 0) for t in tools), default=0)
    tools_using_enum = sum(1 for t in tools if t.get("uses_enum"))
    tools_with_output = sum(1 for t in tools if t.get("has_output_schema"))
    return ReportSurface(
        type_counts=type_counts,
        tool_count=tool_count,
        avg_property_count=avg_property_count,
        max_nesting_depth=max_nesting,
        tools_using_enum=tools_using_enum,
        tools_with_output_schema=tools_with_output,
        output_schema_count=int(metrics.get("output_schema_count") or 0),
    )


def _safety(
    metrics: Mapping[str, Any], auth_posture: str, auth_type: Optional[str]
) -> ReportSafety:
    """Build the safety posture from the annotation coverage + auth posture."""
    coverage = dict(metrics.get("annotation_coverage") or {})
    return ReportSafety(
        annotation_coverage=coverage,
        destructive_tool_count=int(coverage.get("destructive_hint") or 0),
        auth_posture=auth_posture,
        auth_type=auth_type,
    )


#: Human labels for the license-signal ``kind`` values (unknown kinds fall back verbatim).
_LICENSE_KIND_LABELS: Mapping[str, str] = {
    "spdx_id": "SPDX id",
    "license_mention": "License mention",
    "terms_mention": "Terms mention",
    "usage_restriction": "Usage restriction",
    "license_url": "License URL",
    "terms_url": "Terms URL",
}


def _license(report: Mapping[str, Any]) -> ReportLicense:
    """Shape the license & terms detector report into its section (values pass through).

    The detector already bounds, orders, and words everything — including the "not stated"
    phrasing that must never read as a "no license" claim — so this only normalizes shapes.
    """
    return ReportLicense(
        status=str(report.get("status") or "not_stated"),
        statement=str(report.get("statement") or ""),
        signals=[
            {
                "kind": str(s.get("kind", "")),
                "source": str(s.get("source", "")),
                "matched": str(s.get("matched", "")),
                "excerpt": str(s.get("excerpt", "")),
            }
            for s in (report.get("signals") or [])
        ],
        signals_truncated=int(report.get("signals_truncated") or 0),
        sources_scanned=[str(s) for s in (report.get("sources_scanned") or [])],
    )


def _license_kind_label(kind: str) -> str:
    """Return the human label for a signal ``kind`` (verbatim when unknown)."""
    return _LICENSE_KIND_LABELS.get(kind, kind)


#: Human labels for the lifecycle ``stage`` values (unknown stages fall back verbatim).
_LIFECYCLE_STAGE_LABELS: Mapping[str, str] = {
    "deprecated": "Deprecated",
    "experimental": "Experimental",
    "beta": "Beta",
    "stable": "Stable (declared)",
    "unspecified": "Unspecified",
}

#: Human labels for the lifecycle signal ``kind`` values (unknown kinds fall back verbatim).
_LIFECYCLE_KIND_LABELS: Mapping[str, str] = {
    "annotation_flag": "Annotation flag",
    "annotation_status": "Annotation status",
    "name_token": "Name token",
    "description_phrase": "Description phrase",
}


def _lifecycle(report: Mapping[str, Any]) -> ReportLifecycle:
    """Shape the lifecycle detector report into its section (values pass through).

    The detector already bounds, orders, and words everything — including the "no signals"
    phrasing that must never read as a "stable" claim — so this only normalizes shapes.
    """
    return ReportLifecycle(
        status=str(report.get("status") or "none_detected"),
        statement=str(report.get("statement") or ""),
        stage_counts={
            str(stage): int(count or 0)
            for stage, count in (report.get("stage_counts") or {}).items()
        },
        flagged=[
            {
                "item_type": str(capability.get("item_type", "")),
                "name": str(capability.get("name", "")),
                "stage": str(capability.get("stage", "")),
                "signals": list(capability.get("signals") or []),
                "signals_truncated": int(capability.get("signals_truncated") or 0),
            }
            for capability in (report.get("flagged") or [])
        ],
        flagged_truncated=int(report.get("flagged_truncated") or 0),
        capabilities_scanned=int(report.get("capabilities_scanned") or 0),
    )


def _lifecycle_stage_label(stage: str) -> str:
    """Return the human label for a lifecycle ``stage`` (verbatim when unknown)."""
    return _LIFECYCLE_STAGE_LABELS.get(stage, stage)


def _lifecycle_kind_label(kind: str) -> str:
    """Return the human label for a lifecycle signal ``kind`` (verbatim when unknown)."""
    return _LIFECYCLE_KIND_LABELS.get(kind, kind)


def _lifecycle_signal_summary(capability: Mapping[str, Any]) -> str:
    """Summarize one flagged capability's signals as a single human-readable cell.

    Each signal reads "<kind label>: <matched>"; signals are joined with "; " and an
    overflow note is appended when the detector truncated the itemization.
    """
    parts = [
        f"{_lifecycle_kind_label(str(signal.get('kind', '')))}: {signal.get('matched', '')}"
        for signal in (capability.get("signals") or [])
    ]
    truncated = int(capability.get("signals_truncated") or 0)
    if truncated:
        parts.append(f"…and {truncated} more")
    return "; ".join(parts)


def _provenance(provenance: Mapping[str, Any]) -> ReportProvenance:
    """Shape the 20.5 provenance ``as_dict()`` into the report section.

    The upstream :func:`app.mcp_provenance.build_endpoint_provenance` already labels,
    bounds and orders everything; this only normalizes types for rendering.
    """
    current = provenance.get("current_origin")
    return ReportProvenance(
        added_via=str(provenance.get("added_via") or "manual"),
        added_via_label=str(provenance.get("added_via_label") or ""),
        added_at=provenance.get("added_at"),
        first_discovered_at=provenance.get("first_discovered_at"),
        last_discovered_at=provenance.get("last_discovered_at"),
        version_count=int(provenance.get("version_count") or 0),
        origin_counts={
            str(k): int(v or 0)
            for k, v in dict(provenance.get("origin_counts") or {}).items()
        },
        run_counts={
            str(k): int(v or 0)
            for k, v in dict(provenance.get("run_counts") or {}).items()
        },
        current_origin=dict(current) if isinstance(current, Mapping) else None,
        origins=[dict(origin) for origin in provenance.get("origins") or []],
        origins_truncated=int(provenance.get("origins_truncated") or 0),
    )


def _author_label(row: Mapping[str, Any]) -> str:
    """Build a human-readable author label from a note row's joined user columns."""
    name = row.get("created_by_name") or row.get("updated_by_name")
    email = row.get("created_by_email") or row.get("updated_by_email")
    if name and email:
        return f"{name} <{email}>"
    if name:
        return str(name)
    if email:
        return str(email)
    author_id = row.get("created_by") or row.get("updated_by")
    return str(author_id) if author_id else "Unknown author"


def _cataloger_notes(rows: Sequence[Mapping[str, Any]]) -> List[ReportCatalogerNote]:
    """Shape cataloger-note rows into the opted-in report section (MCAT-22.3)."""
    out: List[ReportCatalogerNote] = []
    for row in rows:
        body = str(row.get("body") or "").strip()
        if not body:
            continue
        created_at = _iso(row.get("created_at")) or ""
        updated_at = _iso(row.get("updated_at"))
        edited = (
            updated_at
            and row.get("updated_by")
            and updated_at != created_at
        )
        out.append(
            ReportCatalogerNote(
                body=body,
                author_label=_author_label(row),
                created_at=created_at,
                updated_at=updated_at if edited else None,
            )
        )
    return out


def _trust(profile: Mapping[str, Any]) -> ReportTrust:
    """Shape the trust profile, ordering axes canonically for a stable radar table."""
    axes = list(profile.get("axes") or [])
    order = {key: i for i, key in enumerate(_TRUST_AXIS_ORDER)}
    axes_sorted = sorted(axes, key=lambda a: order.get(a.get("key"), len(order)))
    return ReportTrust(
        axes=[dict(a) for a in axes_sorted],
        overall=profile.get("overall"),
        available_count=int(profile.get("available_count") or 0),
        axis_count=int(profile.get("axis_count") or 0),
    )


def _change(
    change_rows: Sequence[Mapping[str, Any]], severity: Optional[Mapping[str, int]]
) -> ReportChange:
    """Shape the change-since-previous section, capping the itemized rows.

    The severity roll-up always reflects the *full* change set; the itemized list is bounded to
    :data:`MAX_REPORT_CHANGES` with any overflow reported in ``rows_truncated``.
    """
    rows = list(change_rows)
    shown = rows[:MAX_REPORT_CHANGES]
    return ReportChange(
        severity_counts=dict(severity or {}),
        rows=[
            {
                "change_type": r.get("change_type"),
                "item_type": r.get("item_type"),
                "item_name": r.get("item_name"),
            }
            for r in shown
        ],
        rows_truncated=max(0, len(rows) - len(shown)),
    )


# ===========================================================================================
# Markdown renderer
# ===========================================================================================


def _pct(value: Any) -> str:
    """Format a percentage-ish number as ``NN%`` (``—`` when absent)."""
    if value is None:
        return "—"
    return f"{round(float(value))}%"


def _or_dash(value: Any) -> str:
    """Return ``value`` as a string, or an em dash when it is empty/None."""
    if value is None or value == "":
        return "—"
    return str(value)


def render_report_markdown(card: ReportCard) -> str:
    """Render a :class:`ReportCard` as a self-contained Markdown document.

    The output is deterministic for a fixed ``card`` (including its ``generated_at``), portable
    (plain CommonMark tables + headings, no HTML), and contains no secret — only the auth
    *posture* and ``auth_type`` label ever appear. Sections with no data render an explicit
    "not available" note rather than being omitted, so the reader can tell "no findings" from
    "not yet assessed".

    Args:
        card: The assembled report view model.

    Returns:
        The Markdown report as a single string.
    """
    ident = card.identity
    lines: List[str] = []
    lines.append(f"# MCP Server Report Card — {ident.name}")
    lines.append("")
    lines.append(f"_Generated {card.generated_at} · Apiome MCP catalog_")
    lines.append("")

    # --- Identity ---------------------------------------------------------------------------
    lines.append("## Identity")
    lines.append("")
    identity_rows = [
        ("Name", ident.name),
        ("Host", _or_dash(ident.host)),
        ("Endpoint URL", _or_dash(ident.endpoint_url)),
        ("Transport", _or_dash(ident.transport)),
        ("Category", _or_dash(ident.category)),
        ("Visibility", f"{_or_dash(ident.visibility)}"
         + (" · published" if ident.published else " · unpublished")),
        ("Auth posture", f"{ident.auth_posture}"
         + (f" ({ident.auth_type})" if ident.auth_type else "")),
        ("Last discovered", _or_dash(ident.last_discovered_at)),
        ("Discovery status", _or_dash(ident.last_discovery_status)),
    ]
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    for label, value in identity_rows:
        lines.append(f"| {label} | {_md_cell(value)} |")
    if ident.description:
        lines.append("")
        lines.append(f"> {ident.description}")
    lines.append("")

    if card.version is not None:
        v = card.version
        current = " (current)" if v.is_current else ""
        lines.append(
            f"**Snapshot:** version {(_or_dash(v.version_seq))}{current}"
            f" · tag {_or_dash(v.version_tag)} · protocol {_or_dash(v.protocol_version)}"
        )
        server_bits = " · ".join(
            b
            for b in (
                f"server {v.server_name}" if v.server_name else "",
                f"v{v.server_version}" if v.server_version else "",
            )
            if b
        )
        if server_bits:
            lines.append("")
            lines.append(server_bits)
        lines.append("")
    else:
        lines.append("_This endpoint has never been discovered — the sections below are"
                     " unavailable until a discovery run completes._")
        lines.append("")

    # --- Provenance ---------------------------------------------------------------------------
    lines.append("## Provenance")
    lines.append("")
    lines.append("_How the catalog knows this server — how the endpoint was added and which"
                 " discovery runs produced its version snapshots._")
    lines.append("")
    if card.provenance is not None:
        pv = card.provenance
        added = f"Added: **{pv.added_via_label}**"
        if pv.added_at:
            added += f" on {pv.added_at}"
        lines.append(added)
        lines.append("")
        if pv.current_origin is not None:
            co = pv.current_origin
            current_line = (
                f"Current snapshot: version {_or_dash(co.get('version_seq'))}"
                f" via **{_or_dash(co.get('trigger_label'))}**"
            )
            if co.get("discovered_at"):
                current_line += f" on {co['discovered_at']}"
            lines.append(current_line)
        else:
            lines.append("_Never discovered — no snapshot provenance yet._")
        lines.append("")
        rc = pv.run_counts
        lines.append(
            f"Completed discovery runs: **{int(rc.get('total', 0))}** total · "
            f"{int(rc.get('manual', 0))} manual · "
            f"{int(rc.get('sweep', 0))} sweep · "
            f"{int(rc.get('registry', 0))} registry"
        )
        if pv.origins:
            lines.append("")
            lines.append("| Version | Tag | Origin | Discovered |")
            lines.append("| --- | --- | --- | --- |")
            for origin in pv.origins:
                seq = _or_dash(origin.get("version_seq"))
                if origin.get("is_current"):
                    seq += " (current)"
                lines.append(
                    f"| {seq} | {_md_cell(origin.get('version_tag'))}"
                    f" | {_md_cell(origin.get('trigger_label'))}"
                    f" | {_md_cell(origin.get('discovered_at'))} |"
                )
            if pv.origins_truncated:
                lines.append("")
                lines.append(
                    f"_…and {pv.origins_truncated} earlier version(s) not shown._"
                )
        unrecorded = int(pv.origin_counts.get("unrecorded", 0))
        if unrecorded:
            lines.append("")
            lines.append(
                f"_{unrecorded} version(s) predate provenance tracking — their origin is"
                " unrecorded, not manual._"
            )
    else:
        lines.append("_Not available._")
    lines.append("")

    # --- Cataloger commentary (opt-in; never server-reported data) -------------------------
    if card.cataloger_notes is not None:
        lines.append("## Cataloger Commentary")
        lines.append("")
        lines.append(
            "_Human notes authored by catalog users in Apiome — **not** reported by the MCP"
            " server._"
        )
        lines.append("")
        if card.cataloger_notes:
            for note in card.cataloger_notes:
                edited = (
                    f" · edited {note.updated_at}" if note.updated_at else ""
                )
                lines.append(
                    f"**{note.author_label}** · {note.created_at}{edited}"
                )
                lines.append("")
                lines.append(note.body)
                lines.append("")
        else:
            lines.append("_No cataloger notes recorded._")
            lines.append("")

    # --- Grade & score ----------------------------------------------------------------------
    lines.append("## Grade & Score")
    lines.append("")
    if card.score is not None:
        s = card.score
        grade = _or_dash(s.grade)
        score = _or_dash(s.score)
        lines.append(f"**Grade {grade}** · {score}/100")
        lines.append("")
        sev = s.severity_counts
        lines.append("| Severity | Count |")
        lines.append("| --- | --- |")
        for key in ("error", "warning", "info"):
            lines.append(f"| {key.capitalize()} | {int(sev.get(key, 0))} |")
        lines.append("")
        if s.findings:
            lines.append("### Findings")
            lines.append("")
            lines.append("| Severity | Rule | Message |")
            lines.append("| --- | --- | --- |")
            for f in s.findings:
                lines.append(
                    f"| {f['severity']} | `{f['rule']}` | {_md_cell(f['message'])} |"
                )
            if s.findings_truncated:
                lines.append("")
                lines.append(f"_…and {s.findings_truncated} more finding(s) not shown._")
        else:
            lines.append("_No lint findings — a clean surface._")
    else:
        lines.append("_Not yet scored._")
    lines.append("")

    # --- Capability surface -----------------------------------------------------------------
    lines.append("## Capability Surface")
    lines.append("")
    if card.surface is not None:
        su = card.surface
        tc = su.type_counts
        lines.append("| Kind | Count |")
        lines.append("| --- | --- |")
        for key, label in (
            ("tools", "Tools"),
            ("resources", "Resources"),
            ("resource_templates", "Resource templates"),
            ("prompts", "Prompts"),
            ("total", "Total"),
        ):
            lines.append(f"| {label} | {int(tc.get(key, 0))} |")
        lines.append("")
        lines.append(
            f"Tool schema shape: **{su.tool_count}** tool(s), "
            f"avg **{_or_dash(su.avg_property_count)}** properties each, "
            f"max nesting depth **{su.max_nesting_depth}**, "
            f"**{su.tools_using_enum}** using enums, "
            f"**{su.tools_with_output_schema}** with an output schema."
        )
    else:
        lines.append("_No discovered surface._")
    lines.append("")

    # --- Safety posture ---------------------------------------------------------------------
    lines.append("## Safety Posture")
    lines.append("")
    if card.safety is not None:
        sa = card.safety
        ac = sa.annotation_coverage
        lines.append(f"Auth posture: **{sa.auth_posture}**"
                     + (f" ({sa.auth_type})" if sa.auth_type else ""))
        lines.append("")
        lines.append(f"Destructive-hint tools: **{sa.destructive_tool_count}**")
        lines.append("")
        lines.append("| Annotation | Tools |")
        lines.append("| --- | --- |")
        total_tools = int(ac.get("tool_count", 0))
        lines.append(f"| Annotated | {int(ac.get('annotated_tools', 0))} / {total_tools} |")
        for key, label in (
            ("read_only_hint", "Read-only hint"),
            ("destructive_hint", "Destructive hint"),
            ("idempotent_hint", "Idempotent hint"),
            ("open_world_hint", "Open-world hint"),
        ):
            lines.append(f"| {label} | {int(ac.get(key, 0))} |")
    else:
        lines.append("_No discovered surface._")
    lines.append("")

    # --- Documentation coverage -------------------------------------------------------------
    lines.append("## Documentation Coverage")
    lines.append("")
    if card.documentation is not None:
        doc = card.documentation
        lines.append("| Meter | Coverage |")
        lines.append("| --- | --- |")
        lines.append(
            f"| Described items | {_pct(doc.get('description_pct'))}"
            f" ({int(doc.get('described_items', 0))}/{int(doc.get('item_count', 0))}) |"
        )
        lines.append(
            f"| Titled items | {_pct(doc.get('title_pct'))}"
            f" ({int(doc.get('titled_items', 0))}/{int(doc.get('item_count', 0))}) |"
        )
        lines.append(
            f"| Documented tool params | {_pct(doc.get('tool_param_description_pct'))}"
            f" ({int(doc.get('documented_tool_params', 0))}/{int(doc.get('tool_param_count', 0))}) |"
        )
    else:
        lines.append("_No discovered surface._")
    lines.append("")

    # --- License & terms signals --------------------------------------------------------------
    lines.append("## License & Terms")
    lines.append("")
    lines.append("_Signals the server's own text mentions — informational, not a compliance"
                 " verdict._")
    lines.append("")
    if card.license is not None:
        lic = card.license
        lines.append(lic.statement)
        if lic.signals:
            lines.append("")
            lines.append("| Signal | Source | Matched | Context |")
            lines.append("| --- | --- | --- | --- |")
            for s in lic.signals:
                lines.append(
                    f"| {_license_kind_label(s['kind'])} | {_md_cell(s['source'])}"
                    f" | `{_md_cell(s['matched'])}` | {_md_cell(s['excerpt'])} |"
                )
            if lic.signals_truncated:
                lines.append("")
                lines.append(f"_…and {lic.signals_truncated} more signal(s) not shown._")
    else:
        lines.append("_Not scanned — no discovered snapshot._")
    lines.append("")

    # --- Deprecation & lifecycle signals ------------------------------------------------------
    lines.append("## Lifecycle Signals")
    lines.append("")
    lines.append("_Deprecated / experimental / beta markers the capabilities' own text and"
                 " annotations carry — absence of a signal is not a stability claim._")
    lines.append("")
    if card.lifecycle is not None:
        lc = card.lifecycle
        lines.append(lc.statement)
        if lc.flagged:
            lines.append("")
            lines.append("| Capability | Kind | Stage | Signals |")
            lines.append("| --- | --- | --- | --- |")
            for capability in lc.flagged:
                lines.append(
                    f"| `{_md_cell(capability['name'])}` | {_md_cell(capability['item_type'])}"
                    f" | {_lifecycle_stage_label(capability['stage'])}"
                    f" | {_md_cell(_lifecycle_signal_summary(capability))} |"
                )
            if lc.flagged_truncated:
                lines.append("")
                lines.append(
                    f"_…and {lc.flagged_truncated} more flagged capability(ies) not shown._"
                )
    else:
        lines.append("_Not scanned — no discovered snapshot._")
    lines.append("")

    # --- Trust radar ------------------------------------------------------------------------
    lines.append("## Trust Profile")
    lines.append("")
    lines.append("_A heuristic composite across five axes, not an official rating._")
    lines.append("")
    if card.trust is not None:
        tr = card.trust
        overall = "—" if tr.overall is None else f"{round(float(tr.overall))}/100"
        lines.append(f"**Overall: {overall}** · {tr.available_count} of {tr.axis_count}"
                     " signals measured")
        lines.append("")
        lines.append("| Axis | Score | Basis |")
        lines.append("| --- | --- | --- |")
        for axis in tr.axes:
            if axis.get("available") and axis.get("value") is not None:
                value = f"{round(float(axis['value']))}/100"
            else:
                value = "n/a"
            lines.append(
                f"| {axis.get('label', axis.get('key'))} | {value}"
                f" | {_md_cell(axis.get('detail', ''))} |"
            )
    else:
        lines.append("_No trust signals available yet._")
    lines.append("")

    # --- Change since previous --------------------------------------------------------------
    lines.append("## Change Since Previous Version")
    lines.append("")
    if card.change is not None:
        ch = card.change
        sev = ch.severity_counts
        lines.append(
            f"**{int(sev.get('total', 0))}** change(s): "
            f"{int(sev.get('breaking', 0))} breaking · "
            f"{int(sev.get('additive', 0))} additive · "
            f"{int(sev.get('review', 0))} review"
        )
        lines.append("")
        if ch.rows:
            lines.append("| Change | Kind | Item |")
            lines.append("| --- | --- | --- |")
            for r in ch.rows:
                lines.append(
                    f"| {_or_dash(r['change_type'])} | {_or_dash(r['item_type'])}"
                    f" | {_md_cell(r['item_name'])} |"
                )
            if ch.rows_truncated:
                lines.append("")
                lines.append(f"_…and {ch.rows_truncated} more change(s) not shown._")
    else:
        lines.append("_No changes recorded for this snapshot (first version, or unchanged)._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _md_cell(value: Any) -> str:
    """Escape a value for a Markdown table cell (pipes and newlines break table rows)."""
    text = _or_dash(value)
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


# ===========================================================================================
# HTML renderer
# ===========================================================================================

#: The self-contained report stylesheet. Screen styles plus a ``@media print`` block so the same
#: HTML prints cleanly to PDF (the ticket's "PDF via the same HTML / print stylesheet"). Classes,
#: not inline styles, so the single embedded sheet is the one source of visual truth.
_REPORT_CSS = """
:root { --ink: #1a1a2e; --muted: #6b7280; --line: #e5e7eb; --bg: #ffffff;
        --accent: #0e8a16; --warn: #b45309; --err: #b91c1c; --chip: #f3f4f6; }
* { box-sizing: border-box; }
body.report { color: var(--ink); background: var(--bg); font: 15px/1.5 -apple-system,
        BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        margin: 0; padding: 2rem; max-width: 900px; }
.report h1 { font-size: 1.7rem; margin: 0 0 .25rem; }
.report h2 { font-size: 1.2rem; margin: 1.75rem 0 .6rem; padding-bottom: .3rem;
        border-bottom: 2px solid var(--line); }
.report h3 { font-size: 1rem; margin: 1rem 0 .4rem; }
.report .subtitle { color: var(--muted); margin: 0 0 1rem; font-size: .9rem; }
.report .note { color: var(--muted); font-style: italic; }
.report .note.cataloger { border-left: 3px solid #d97706; padding-left: .75rem; }
.report .cataloger-note { border: 1px solid #fcd34d; background: #fffbeb; border-radius: 8px;
        padding: .75rem 1rem; margin: .75rem 0; }
.report .cataloger-note .meta { font-size: .85rem; color: var(--muted); margin: 0 0 .5rem;
        font-style: normal; }
.report .cataloger-note p { white-space: pre-wrap; margin: 0; }
.report .desc { border-left: 3px solid var(--line); padding: .25rem .75rem; color: var(--muted); }
.report table { border-collapse: collapse; width: 100%; margin: .5rem 0; }
.report th, .report td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--line);
        vertical-align: top; }
.report th { font-weight: 600; background: var(--chip); }
.report code { background: var(--chip); padding: .05rem .3rem; border-radius: 4px;
        font-size: .85em; }
.report .grade { display: inline-block; font-weight: 700; font-size: 1.1rem;
        padding: .15rem .6rem; border-radius: 6px; color: #fff; background: var(--muted); }
.report .grade-a { background: var(--accent); }
.report .grade-b { background: #4d7c0f; }
.report .grade-c { background: var(--warn); }
.report .grade-d, .report .grade-f { background: var(--err); }
.report .sev-error { color: var(--err); font-weight: 600; }
.report .sev-warning { color: var(--warn); font-weight: 600; }
.report .sev-info { color: var(--muted); }
.report .chip { display: inline-block; background: var(--chip); border-radius: 999px;
        padding: .1rem .55rem; font-size: .82rem; margin-right: .3rem; }
.report .metric { font-weight: 700; }
@media print {
  body.report { padding: 0; max-width: none; font-size: 12px; }
  .report h2 { page-break-after: avoid; }
  .report table, .report tr { page-break-inside: avoid; }
  .report h1 { page-break-before: avoid; }
}
""".strip()


def _e(value: Any) -> str:
    """HTML-escape a value, rendering empty/None as an em dash."""
    return html.escape(_or_dash(value))


def _grade_class(grade: Optional[str]) -> str:
    """Map an A–F grade to its badge CSS class (neutral when absent/unknown)."""
    if not grade:
        return "grade"
    letter = str(grade).strip().upper()[:1].lower()
    if letter in ("a", "b", "c", "d", "f"):
        return f"grade grade-{letter}"
    return "grade"


def render_report_html(card: ReportCard) -> str:
    """Render a :class:`ReportCard` as a self-contained HTML document.

    The document embeds the whole stylesheet (:data:`_REPORT_CSS`, including a ``@media print``
    block), references no external asset, and — like the Markdown renderer — is pure/deterministic
    and never emits a secret. Because the print stylesheet is bundled, the file *is* the PDF
    export: opening it and printing to PDF yields the one-page report ("PDF via the same HTML").
    Absent sections render an explicit "not available" note rather than being dropped.

    Args:
        card: The assembled report view model.

    Returns:
        A complete ``<!doctype html>`` document as a single string.
    """
    ident = card.identity
    p: List[str] = []
    p.append("<!doctype html>")
    p.append('<html lang="en"><head><meta charset="utf-8">')
    p.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    p.append(f"<title>Report Card — {_e(ident.name)}</title>")
    p.append(f"<style>{_REPORT_CSS}</style>")
    p.append('</head><body class="report">')

    p.append(f"<h1>MCP Server Report Card — {_e(ident.name)}</h1>")
    p.append(f'<p class="subtitle">Generated {_e(card.generated_at)} · Apiome MCP catalog</p>')

    # --- Identity ---------------------------------------------------------------------------
    p.append("<h2>Identity</h2>")
    visibility = _e(ident.visibility) + (
        " · published" if ident.published else " · unpublished"
    )
    auth = _e(ident.auth_posture) + (f" ({_e(ident.auth_type)})" if ident.auth_type else "")
    p.append("<table>")
    for label, value in (
        ("Host", _e(ident.host)),
        ("Endpoint URL", _e(ident.endpoint_url)),
        ("Transport", _e(ident.transport)),
        ("Category", _e(ident.category)),
        ("Visibility", visibility),
        ("Auth posture", auth),
        ("Last discovered", _e(ident.last_discovered_at)),
        ("Discovery status", _e(ident.last_discovery_status)),
    ):
        p.append(f"<tr><th>{label}</th><td>{value}</td></tr>")
    p.append("</table>")
    if ident.description:
        p.append(f'<p class="desc">{_e(ident.description)}</p>')

    if card.version is not None:
        v = card.version
        current = " <span class='chip'>current</span>" if v.is_current else ""
        p.append(
            f"<p>Snapshot: version <span class='metric'>{_e(v.version_seq)}</span>{current}"
            f" · tag {_e(v.version_tag)} · protocol {_e(v.protocol_version)}</p>"
        )
    else:
        p.append('<p class="note">This endpoint has never been discovered — the sections'
                 " below are unavailable until a discovery run completes.</p>")

    # --- Provenance ---------------------------------------------------------------------------
    p.append("<h2>Provenance</h2>")
    p.append("<p class='note'>How the catalog knows this server — how the endpoint was added"
             " and which discovery runs produced its version snapshots.</p>")
    if card.provenance is not None:
        pv = card.provenance
        added = f"Added: <span class='metric'>{_e(pv.added_via_label)}</span>"
        if pv.added_at:
            added += f" on {_e(pv.added_at)}"
        p.append(f"<p>{added}</p>")
        if pv.current_origin is not None:
            co = pv.current_origin
            current_bits = (
                f"Current snapshot: version <span class='metric'>"
                f"{_e(co.get('version_seq'))}</span> via"
                f" <span class='metric'>{_e(co.get('trigger_label'))}</span>"
            )
            if co.get("discovered_at"):
                current_bits += f" on {_e(co['discovered_at'])}"
            p.append(f"<p>{current_bits}</p>")
        else:
            p.append("<p class='note'>Never discovered — no snapshot provenance yet.</p>")
        rc = pv.run_counts
        p.append(
            f"<p>Completed discovery runs: <span class='metric'>{int(rc.get('total', 0))}"
            f"</span> total · {int(rc.get('manual', 0))} manual ·"
            f" {int(rc.get('sweep', 0))} sweep · {int(rc.get('registry', 0))} registry</p>"
        )
        if pv.origins:
            p.append("<table><tr><th>Version</th><th>Tag</th><th>Origin</th>"
                     "<th>Discovered</th></tr>")
            for origin in pv.origins:
                seq = _e(origin.get("version_seq"))
                if origin.get("is_current"):
                    seq += " <span class='chip'>current</span>"
                p.append(
                    f"<tr><td>{seq}</td><td>{_e(origin.get('version_tag'))}</td>"
                    f"<td>{_e(origin.get('trigger_label'))}</td>"
                    f"<td>{_e(origin.get('discovered_at'))}</td></tr>"
                )
            p.append("</table>")
            if pv.origins_truncated:
                p.append(f"<p class='note'>…and {pv.origins_truncated} earlier version(s)"
                         " not shown.</p>")
        unrecorded = int(pv.origin_counts.get("unrecorded", 0))
        if unrecorded:
            p.append(f"<p class='note'>{unrecorded} version(s) predate provenance tracking"
                     " — their origin is unrecorded, not manual.</p>")
    else:
        p.append("<p class='note'>Not available.</p>")

    # --- Cataloger commentary (opt-in; never server-reported data) -------------------------
    if card.cataloger_notes is not None:
        p.append("<h2>Cataloger Commentary</h2>")
        p.append(
            "<p class='note cataloger'>Human notes authored by catalog users in Apiome"
            " — <strong>not</strong> reported by the MCP server.</p>"
        )
        if card.cataloger_notes:
            for note in card.cataloger_notes:
                edited = (
                    f" · edited {_e(note.updated_at)}" if note.updated_at else ""
                )
                p.append(
                    f"<div class='cataloger-note'><p class='meta'><strong>"
                    f"{_e(note.author_label)}</strong> · {_e(note.created_at)}{edited}</p>"
                    f"<p>{_e(note.body)}</p></div>"
                )
        else:
            p.append("<p class='note'>No cataloger notes recorded.</p>")

    # --- Grade & score ----------------------------------------------------------------------
    p.append("<h2>Grade &amp; Score</h2>")
    if card.score is not None:
        s = card.score
        p.append(
            f"<p><span class='{_grade_class(s.grade)}'>{_e(s.grade)}</span>"
            f" &nbsp; <span class='metric'>{_e(s.score)}</span>/100</p>"
        )
        sev = s.severity_counts
        p.append("<table><tr><th>Severity</th><th>Count</th></tr>")
        for key in ("error", "warning", "info"):
            p.append(
                f"<tr><td class='sev-{key}'>{key.capitalize()}</td>"
                f"<td>{int(sev.get(key, 0))}</td></tr>"
            )
        p.append("</table>")
        if s.findings:
            p.append("<h3>Findings</h3>")
            p.append("<table><tr><th>Severity</th><th>Rule</th><th>Message</th></tr>")
            for f in s.findings:
                p.append(
                    f"<tr><td class='sev-{_e(f['severity'])}'>{_e(f['severity'])}</td>"
                    f"<td><code>{_e(f['rule'])}</code></td>"
                    f"<td>{_e(f['message'])}</td></tr>"
                )
            p.append("</table>")
            if s.findings_truncated:
                p.append(f"<p class='note'>…and {s.findings_truncated} more finding(s)"
                         " not shown.</p>")
        else:
            p.append("<p class='note'>No lint findings — a clean surface.</p>")
    else:
        p.append("<p class='note'>Not yet scored.</p>")

    # --- Capability surface -----------------------------------------------------------------
    p.append("<h2>Capability Surface</h2>")
    if card.surface is not None:
        su = card.surface
        tc = su.type_counts
        p.append("<table><tr><th>Kind</th><th>Count</th></tr>")
        for key, label in (
            ("tools", "Tools"),
            ("resources", "Resources"),
            ("resource_templates", "Resource templates"),
            ("prompts", "Prompts"),
            ("total", "Total"),
        ):
            p.append(f"<tr><td>{label}</td><td>{int(tc.get(key, 0))}</td></tr>")
        p.append("</table>")
        p.append(
            f"<p>Tool schema shape: <span class='metric'>{su.tool_count}</span> tool(s), avg"
            f" <span class='metric'>{_e(su.avg_property_count)}</span> properties each, max nesting"
            f" depth <span class='metric'>{su.max_nesting_depth}</span>,"
            f" <span class='metric'>{su.tools_using_enum}</span> using enums,"
            f" <span class='metric'>{su.tools_with_output_schema}</span> with an output schema.</p>"
        )
    else:
        p.append("<p class='note'>No discovered surface.</p>")

    # --- Safety posture ---------------------------------------------------------------------
    p.append("<h2>Safety Posture</h2>")
    if card.safety is not None:
        sa = card.safety
        ac = sa.annotation_coverage
        auth = _e(sa.auth_posture) + (f" ({_e(sa.auth_type)})" if sa.auth_type else "")
        p.append(f"<p>Auth posture: <span class='metric'>{auth}</span> ·"
                 f" destructive-hint tools: <span class='metric'>{sa.destructive_tool_count}</span></p>")
        total_tools = int(ac.get("tool_count", 0))
        p.append("<table><tr><th>Annotation</th><th>Tools</th></tr>")
        p.append(f"<tr><td>Annotated</td><td>{int(ac.get('annotated_tools', 0))}"
                 f" / {total_tools}</td></tr>")
        for key, label in (
            ("read_only_hint", "Read-only hint"),
            ("destructive_hint", "Destructive hint"),
            ("idempotent_hint", "Idempotent hint"),
            ("open_world_hint", "Open-world hint"),
        ):
            p.append(f"<tr><td>{label}</td><td>{int(ac.get(key, 0))}</td></tr>")
        p.append("</table>")
    else:
        p.append("<p class='note'>No discovered surface.</p>")

    # --- Documentation coverage -------------------------------------------------------------
    p.append("<h2>Documentation Coverage</h2>")
    if card.documentation is not None:
        doc = card.documentation
        p.append("<table><tr><th>Meter</th><th>Coverage</th></tr>")
        p.append(
            f"<tr><td>Described items</td><td>{_pct(doc.get('description_pct'))}"
            f" ({int(doc.get('described_items', 0))}/{int(doc.get('item_count', 0))})</td></tr>"
        )
        p.append(
            f"<tr><td>Titled items</td><td>{_pct(doc.get('title_pct'))}"
            f" ({int(doc.get('titled_items', 0))}/{int(doc.get('item_count', 0))})</td></tr>"
        )
        p.append(
            f"<tr><td>Documented tool params</td><td>{_pct(doc.get('tool_param_description_pct'))}"
            f" ({int(doc.get('documented_tool_params', 0))}"
            f"/{int(doc.get('tool_param_count', 0))})</td></tr>"
        )
        p.append("</table>")
    else:
        p.append("<p class='note'>No discovered surface.</p>")

    # --- License & terms signals --------------------------------------------------------------
    p.append("<h2>License &amp; Terms</h2>")
    p.append("<p class='note'>Signals the server's own text mentions — informational,"
             " not a compliance verdict.</p>")
    if card.license is not None:
        lic = card.license
        p.append(f"<p>{_e(lic.statement)}</p>")
        if lic.signals:
            p.append("<table><tr><th>Signal</th><th>Source</th><th>Matched</th>"
                     "<th>Context</th></tr>")
            for s in lic.signals:
                p.append(
                    f"<tr><td>{_e(_license_kind_label(s['kind']))}</td>"
                    f"<td>{_e(s['source'])}</td>"
                    f"<td><code>{_e(s['matched'])}</code></td>"
                    f"<td>{_e(s['excerpt'])}</td></tr>"
                )
            p.append("</table>")
            if lic.signals_truncated:
                p.append(f"<p class='note'>…and {lic.signals_truncated} more signal(s)"
                         " not shown.</p>")
    else:
        p.append("<p class='note'>Not scanned — no discovered snapshot.</p>")

    # --- Deprecation & lifecycle signals ------------------------------------------------------
    p.append("<h2>Lifecycle Signals</h2>")
    p.append("<p class='note'>Deprecated / experimental / beta markers the capabilities'"
             " own text and annotations carry — absence of a signal is not a stability"
             " claim.</p>")
    if card.lifecycle is not None:
        lc = card.lifecycle
        p.append(f"<p>{_e(lc.statement)}</p>")
        if lc.flagged:
            p.append("<table><tr><th>Capability</th><th>Kind</th><th>Stage</th>"
                     "<th>Signals</th></tr>")
            for capability in lc.flagged:
                p.append(
                    f"<tr><td><code>{_e(capability['name'])}</code></td>"
                    f"<td>{_e(capability['item_type'])}</td>"
                    f"<td>{_e(_lifecycle_stage_label(capability['stage']))}</td>"
                    f"<td>{_e(_lifecycle_signal_summary(capability))}</td></tr>"
                )
            p.append("</table>")
            if lc.flagged_truncated:
                p.append(f"<p class='note'>…and {lc.flagged_truncated} more flagged"
                         " capability(ies) not shown.</p>")
    else:
        p.append("<p class='note'>Not scanned — no discovered snapshot.</p>")

    # --- Trust radar ------------------------------------------------------------------------
    p.append("<h2>Trust Profile</h2>")
    p.append("<p class='note'>A heuristic composite across five axes, not an official rating.</p>")
    if card.trust is not None:
        tr = card.trust
        overall = "—" if tr.overall is None else f"{round(float(tr.overall))}/100"
        p.append(f"<p>Overall: <span class='metric'>{overall}</span> ·"
                 f" {tr.available_count} of {tr.axis_count} signals measured</p>")
        p.append("<table><tr><th>Axis</th><th>Score</th><th>Basis</th></tr>")
        for axis in tr.axes:
            if axis.get("available") and axis.get("value") is not None:
                value = f"{round(float(axis['value']))}/100"
            else:
                value = "n/a"
            p.append(
                f"<tr><td>{_e(axis.get('label', axis.get('key')))}</td>"
                f"<td>{value}</td><td>{_e(axis.get('detail', ''))}</td></tr>"
            )
        p.append("</table>")
    else:
        p.append("<p class='note'>No trust signals available yet.</p>")

    # --- Change since previous --------------------------------------------------------------
    p.append("<h2>Change Since Previous Version</h2>")
    if card.change is not None:
        ch = card.change
        sev = ch.severity_counts
        p.append(
            f"<p><span class='metric'>{int(sev.get('total', 0))}</span> change(s):"
            f" {int(sev.get('breaking', 0))} breaking · {int(sev.get('additive', 0))} additive ·"
            f" {int(sev.get('review', 0))} review</p>"
        )
        if ch.rows:
            p.append("<table><tr><th>Change</th><th>Kind</th><th>Item</th></tr>")
            for r in ch.rows:
                p.append(
                    f"<tr><td>{_e(r['change_type'])}</td><td>{_e(r['item_type'])}</td>"
                    f"<td>{_e(r['item_name'])}</td></tr>"
                )
            p.append("</table>")
            if ch.rows_truncated:
                p.append(f"<p class='note'>…and {ch.rows_truncated} more change(s)"
                         " not shown.</p>")
    else:
        p.append("<p class='note'>No changes recorded for this snapshot"
                 " (first version, or unchanged).</p>")

    p.append("</body></html>")
    return "\n".join(p)
