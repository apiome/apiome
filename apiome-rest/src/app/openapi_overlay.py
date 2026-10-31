"""OpenAPI Overlay 1.0 / 1.1 / 1.2 pre-processor — IXH-7.7 (#5132), GVM-4.1 (#5876).

The `Overlay Specification <https://spec.openapis.org/overlay/>`_ is the standard way teams apply
environment- or audience-specific modifications to a base OpenAPI document. Importing base and
overlay separately loses the relationship; importing only a hand-resolved output loses the
provenance of which values came from where. This module is the pure core the OpenAPI adapter
(:class:`app.openapi_import_source.OpenApiImportSource`) applies **before** normalization: given a
base document and one or more overlay documents, it applies each overlay's actions in order and
records, per changed value, which overlay contributed it.

**Revisions (GVM-4.1).** Each overlay is applied with the action semantics of the revision its
``overlay`` marker declares — ``major.minor``, the patch ignored as the specification asks — from
the declared table :data:`OVERLAY_READ_VERSIONS`. A marker outside the table (``1.3.0``,
``2.0.0``) is refused with ``FORMAT_VERSION_UNSUPPORTED``: still recognized as an overlay, so it
is a version rejection rather than a format mismatch. The per-revision rules, as implemented
(``apiome-rest/docs/overlay.md`` records them with the specification text they follow):

* **1.0** — ``target`` (JSONPath), ``update``, ``remove``. An object target is deep-merged
  (nested objects merge, any other value — arrays included — replaces); an array target gets the
  ``update`` value appended as one entry. The 1.0 text restricts targets to objects and arrays;
  Apiome still replaces a primitive target in place, as it always has and as 1.1 standardised.
* **1.1** — adds ``copy`` (a JSONPath selecting exactly one node of the document, whose value is
  merged like an ``update``) and primitive targets, and changes the merge: an array
  **concatenates** onto an array (inside an object merge and at an array target), a primitive
  replaces a primitive, an object merges into an object, and any other pairing is an error — the
  action leaves the node untouched and reports it. Nodes selected together must all be objects,
  all arrays or all primitives. ``remove`` wins over ``copy``, which wins over ``update``.
* **1.2** — adds reusable actions (``components.actions.<name>`` holding the action ``fields``,
  referenced from ``actions`` by ``{$ref: '#/components/actions/<name>', target}``) and ``$self``
  (the overlay's own URI, which must have no fragment, used to resolve ``extends``). An action
  with both ``update`` and ``copy`` is refused: the 1.2 text makes each one void the other.

Every revision: a target matching nothing changes nothing (the specification calls that success;
Apiome reports it, since it is almost always a mistake), and ``extends``, when given, is checked
against the base the overlay is applied to.

Everything observable is recorded rather than silently applied or dropped:

* **Provenance** — one :class:`OverlayProvenanceRecord` per changed value (JSON Pointer, kind,
  contributing overlay, action index, target expression). The import preview coverage ledger
  renders these as document-scoped rows (:mod:`app.import_preview_manifest`), and later overlays
  in a chain simply produce later records for the same pointer, so "last writer" is readable.
* **Findings** — each :class:`OverlayFinding` carries a stable code that
  :func:`overlay_lint_findings` maps onto the ``overlay`` rule pack
  (:mod:`app.overlay_lint_rules`), so findings ride the pre-flight report and a tenant style guide
  can raise them.

A bare overlay — no base to apply it to — is linted on its own by :func:`lint_bare_overlay`: the
structural rules run, and the rules that need the base are reported ``skipped: no-base``.

The module never mutates its inputs: :func:`apply_overlays` deep-copies the base document and
returns the resolved copy.
"""

from __future__ import annotations

import copy
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit

from .import_source import ImportSourceError

__all__ = [
    "BareOverlayReport",
    "FINDING_ACTION_INVALID",
    "FINDING_EXTENDS_UNRESOLVED",
    "FINDING_TARGET_EXPRESSION_INVALID",
    "FINDING_UNMATCHED_TARGET",
    "FINDING_VERSION_UNSUPPORTED",
    "MAX_MATCHES_PER_ACTION",
    "MAX_PROVENANCE_RECORDS",
    "OVERLAY_EXTRA_KEY",
    "OverlayApplication",
    "OverlayFinding",
    "OVERLAY_READ_VERSIONS",
    "OverlayProvenanceRecord",
    "OverlayRevision",
    "OverlayedOpenApiDocument",
    "SUPPORTED_REVISIONS",
    "apply_overlays",
    "is_overlay_document",
    "lint_bare_overlay",
    "overlay_lint_findings",
    "overlay_revision",
    "overlay_rule_for",
    "overlay_version",
]


#: Key under which the adapter records the overlay report on
#: :attr:`app.canonical_model.CanonicalApi.extras` (and the preview manifest reads it).
OVERLAY_EXTRA_KEY = "overlay"

#: Ceiling on retained provenance records. A pathological overlay (a wildcard update
#: over a huge document) must not bloat the canonical model's extras or the preview
#: manifest; the report declares the truncation (``provenance_truncated``) instead of
#: hiding it.
MAX_PROVENANCE_RECORDS = 500

#: Ceiling on nodes a single action may select. Matches beyond it are not modified;
#: the action gets an ``action-invalid`` finding naming the cap, so an unbounded
#: wildcard is a visible mistake rather than a silent partial application.
MAX_MATCHES_PER_ACTION = 1000

#: Finding codes (stable; :func:`overlay_lint_findings` maps them onto the ``overlay`` rule pack).
FINDING_UNMATCHED_TARGET = "unmatched-target"
FINDING_ACTION_INVALID = "action-invalid"
FINDING_TARGET_EXPRESSION_INVALID = "target-expression-invalid"
FINDING_EXTENDS_UNRESOLVED = "extends-unresolved"
FINDING_VERSION_UNSUPPORTED = "version-unsupported"


@dataclass(frozen=True)
class OverlayRevision:
    """One Overlay Specification revision Apiome reads (the GVM-4.1 declared table).

    Attributes:
        version: ``major.minor`` — the feature set the marker selects (``1.1``).
        spec_url: The published specification the semantics follow.
        note: What the revision adds, in one sentence (docs and the supported-formats page).
    """

    version: str
    spec_url: str
    note: str


#: The revisions Apiome reads, oldest first. Adding one is a four-file move, as for a format
#: version (FMT-3.8): this row, the semantics in :func:`_apply_action`, a corpus fileset whose
#: overlay declares it (``tests/test_openapi_overlay_revisions.py`` demands one per row), and the
#: regenerated supported-formats page.
OVERLAY_READ_VERSIONS: Tuple[OverlayRevision, ...] = (
    OverlayRevision(
        "1.0",
        "https://spec.openapis.org/overlay/v1.0.0.html",
        "target, update and remove; arrays get one appended entry.",
    ),
    OverlayRevision(
        "1.1",
        "https://spec.openapis.org/overlay/v1.1.0.html",
        "Adds copy and primitive targets; arrays concatenate when merged.",
    ),
    OverlayRevision(
        "1.2",
        "https://spec.openapis.org/overlay/v1.2.0.html",
        "Adds reusable actions (components.actions) and $self.",
    ),
)

#: The ``major.minor`` revisions of :data:`OVERLAY_READ_VERSIONS`.
SUPPORTED_REVISIONS: Tuple[str, ...] = tuple(r.version for r in OVERLAY_READ_VERSIONS)

_REVISION_ORDER = {version: index for index, version in enumerate(SUPPORTED_REVISIONS)}

#: The ``$ref`` prefix a 1.2 reusable-action reference must use.
_COMPONENT_ACTION_PREFIX = "#/components/actions/"


class OverlayedOpenApiDocument(dict):
    """A resolved OpenAPI document that carries its overlay application report.

    A plain ``dict`` subclass so every existing consumer (normalizers, the linter,
    ``CanonicalApi.raw``) treats it exactly like the parsed document it is; the
    adapter reads :attr:`overlay_report` off it after normalization to publish the
    report on the canonical model's extras.

    Attributes:
        overlay_report: The :meth:`OverlayApplication.report` dict for the
            application that produced this document (set per instance; read with
            ``getattr(doc, "overlay_report", None)``).
    """

    overlay_report: Dict[str, Any]


@dataclass(frozen=True)
class OverlayProvenanceRecord:
    """One value the overlay application changed, and which overlay changed it.

    Attributes:
        pointer: JSON Pointer (RFC 6901) of the affected value in the resolved
            document; for a removal, the pointer the node had before removal.
        kind: What happened to the value — ``set`` (a key the base did not have),
            ``replaced`` (an existing value overwritten), ``appended`` (an entry
            added to an array target), or ``removed``.
        overlay: Label (member path) of the contributing overlay document.
        action_index: 0-based index of the action inside that overlay's ``actions``.
        target: The action's JSONPath ``target`` expression, verbatim.
    """

    pointer: str
    kind: str
    overlay: str
    action_index: int
    target: str

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the extras report / preview manifest."""
        return {
            "pointer": self.pointer,
            "kind": self.kind,
            "overlay": self.overlay,
            "action_index": self.action_index,
            "target": self.target,
        }


@dataclass(frozen=True)
class OverlayFinding:
    """One overlay action that could not be applied as written.

    Attributes:
        code: One of the ``FINDING_*`` codes.
        overlay: Label (member path) of the overlay the action came from.
        action_index: 0-based index of the action inside that overlay's ``actions``; ``-1`` for a
            finding about the overlay document itself (its version, ``$self`` or ``extends``).
        target: The action's ``target`` expression (empty when the action had none).
        message: Human-readable explanation of what was wrong.
    """

    code: str
    overlay: str
    action_index: int
    target: str
    message: str

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the extras report / lint adaptation."""
        return {
            "code": self.code,
            "overlay": self.overlay,
            "action_index": self.action_index,
            "target": self.target,
            "message": self.message,
        }


@dataclass
class OverlayApplication:
    """The outcome of applying an overlay chain to a base document.

    Attributes:
        document: The resolved document (a deep copy; the base is never mutated).
        applied: Overlay labels in the order they were applied.
        provenance: Per-value records, in application order, capped at
            :data:`MAX_PROVENANCE_RECORDS`.
        findings: Actions that matched nothing or were structurally unusable.
        provenance_truncated: ``True`` when records beyond the cap were dropped.
        provenance_total: Total number of changes observed (including dropped ones).
        revisions: ``overlay label → revision`` (``1.1``) each overlay was applied with; the report
            lists only those other than ``1.0``.
    """

    document: Dict[str, Any]
    applied: List[str] = field(default_factory=list)
    provenance: List[OverlayProvenanceRecord] = field(default_factory=list)
    findings: List[OverlayFinding] = field(default_factory=list)
    provenance_truncated: bool = False
    provenance_total: int = 0

    revisions: Dict[str, str] = field(default_factory=dict)

    def report(self) -> Dict[str, Any]:
        """Build the deterministic ``overlay`` extras block the adapter publishes."""
        report: Dict[str, Any] = {"applied": list(self.applied)}
        # Only revisions other than 1.0 are recorded: the report is part of the model's extras, which
        # the fingerprint hashes, and every overlay imported before GVM-4.1 was applied as 1.0 — so
        # their fingerprints (and the versions they would mint on re-import) stay put.
        later = {label: revision for label, revision in self.revisions.items() if revision != "1.0"}
        if later:
            report["revisions"] = later
        return {
            **report,
            "provenance": [record.as_dict() for record in self.provenance],
            "findings": [finding.as_dict() for finding in self.findings],
            "provenance_truncated": self.provenance_truncated,
            "provenance_total": self.provenance_total,
        }


def overlay_version(document: Any) -> Optional[str]:
    """Return the document's ``overlay`` version marker, or ``None``.

    Args:
        document: Any parsed value.

    Returns:
        The version string when ``document`` is a mapping whose ``overlay`` key is a
        version-shaped string (``1.0.0``, ``2.0.0``, …); ``None`` otherwise.
    """
    if not isinstance(document, Mapping):
        return None
    version = document.get("overlay")
    if isinstance(version, str) and re.match(r"^\d+(\.\d+)*$", version.strip()):
        return version.strip()
    return None


def is_overlay_document(document: Any) -> bool:
    """Whether a parsed document is an Overlay Specification document.

    Recognition is by the top-level ``overlay`` version marker — the same "look at
    the version key" convention the adapter already uses for ``openapi``/``swagger``
    — so even a truncated overlay (marker present, ``actions`` cut off) is
    recognized and can be routed to overlay-specific guidance instead of a generic
    parse error.

    Args:
        document: Any parsed value.

    Returns:
        ``True`` when the document carries an ``overlay`` version marker.
    """
    return overlay_version(document) is not None


def overlay_revision(version: Optional[str]) -> Optional[str]:
    """The supported revision (``1.1``) a marker selects, or ``None`` when Apiome does not read it.

    The specification's ``major.minor`` designates the feature set and tooling "SHOULD NOT"
    consider the patch, so ``1.1.0`` and ``1.1.7`` both select ``1.1``; ``1`` alone, ``1.3.0`` and
    ``2.0.0`` select nothing.

    Args:
        version: The ``overlay`` marker (:func:`overlay_version`), or ``None``.

    Returns:
        One of :data:`SUPPORTED_REVISIONS`, or ``None``.
    """
    match = re.match(r"^(\d+)\.(\d+)(\.\d+)*$", (version or "").strip())
    if not match:
        return None
    revision = f"{int(match.group(1))}.{int(match.group(2))}"
    return revision if revision in _REVISION_ORDER else None


def _at_least(revision: str, minimum: str) -> bool:
    """Whether ``revision`` has the features of ``minimum``."""
    return _REVISION_ORDER[revision] >= _REVISION_ORDER[minimum]


def _unsupported_message(label: str, version: Optional[str]) -> str:
    supported = ", ".join(SUPPORTED_REVISIONS[:-1]) + f" and {SUPPORTED_REVISIONS[-1]}"
    return (
        f"Overlay {label!r} declares overlay version {version!r}, which Apiome does not read; "
        f"Apiome reads Overlay {supported}."
    )


def apply_overlays(
    base: Mapping[str, Any],
    overlays: Sequence[Tuple[str, Mapping[str, Any]]],
    *,
    base_path: Optional[str] = None,
) -> OverlayApplication:
    """Apply an ordered chain of Overlay 1.0 / 1.1 / 1.2 documents to a base OpenAPI document.

    Overlays are applied strictly in the given order, each seeing the result of the previous one,
    so a later overlay in the chain wins any conflict — and the provenance records show it doing
    so. Each overlay is applied with the semantics of the revision its marker declares.

    Args:
        base: The parsed base OpenAPI document. Never mutated.
        overlays: ``(label, overlay_document)`` pairs in application order; the label (typically
            the member path) is what provenance and findings name, and what a relative
            ``extends`` is resolved against.
        base_path: The base document's member path, when known, so each overlay's ``extends`` can
            be checked against it (``None`` skips that check).

    Returns:
        The :class:`OverlayApplication` with the resolved document, provenance, and findings.

    Raises:
        ImportSourceError: When an overlay declares a version Apiome does not read
            (``FORMAT_VERSION_UNSUPPORTED``) or has no usable ``actions`` array
            (``INPUT_SEMANTIC_INVALID``) — a structurally invalid overlay document is a failed
            import, unlike an individual action that misses.
    """
    result = OverlayApplication(document=copy.deepcopy(dict(base)))
    for label, overlay in overlays:
        version = overlay_version(overlay)
        revision = overlay_revision(version)
        if revision is None:
            raise ImportSourceError(_unsupported_message(label, version), code="FORMAT_VERSION_UNSUPPORTED")
        actions = overlay.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ImportSourceError(
                f"Overlay {label!r} has no `actions` array; an Overlay document must declare at least one action.",
                code="INPUT_SEMANTIC_INVALID",
            )
        result.revisions[label] = revision
        for finding in _document_findings(label, overlay, revision):
            result.findings.append(finding)
        if base_path is not None:
            unresolved = _extends_finding(label, overlay, revision, base_path, base)
            if unresolved is not None:
                result.findings.append(unresolved)
        for index, action in enumerate(actions):
            _apply_action(
                result, label, index, _expand_action(label, overlay, revision, index, action, result), revision
            )
        result.applied.append(label)

    result.provenance_total = len(result.provenance)
    if len(result.provenance) > MAX_PROVENANCE_RECORDS:
        result.provenance = result.provenance[:MAX_PROVENANCE_RECORDS]
        result.provenance_truncated = True
    return result


def _document_findings(label: str, overlay: Mapping[str, Any], revision: str) -> List[OverlayFinding]:
    """Findings about the overlay document itself: its ``$self`` (1.2) and reusable actions."""
    findings: List[OverlayFinding] = []

    def invalid(message: str) -> None:
        findings.append(OverlayFinding(FINDING_ACTION_INVALID, label, -1, "", message))

    self_uri = overlay.get("$self")
    if self_uri is not None:
        if not _at_least(revision, "1.2"):
            invalid(f"Overlay {label!r} declares `$self`, which Overlay {revision} does not have (1.2 added it).")
        elif not isinstance(self_uri, str) or not self_uri.strip():
            invalid(f"Overlay {label!r} has a `$self` that is not a URI reference.")
        elif urlsplit(self_uri).fragment or self_uri.strip().endswith("#"):
            invalid(f"Overlay {label!r} has a `$self` with a fragment ({self_uri!r}), which the specification forbids.")
    components = overlay.get("components")
    if components is not None and not _at_least(revision, "1.2"):
        invalid(
            f"Overlay {label!r} declares `components`, which Overlay {revision} does not have "
            "(1.2 added reusable actions); they are ignored."
        )
    elif isinstance(components, Mapping):
        reusable = components.get("actions")
        if reusable is not None and not isinstance(reusable, Mapping):
            invalid(f"Overlay {label!r} has a `components.actions` that is not a map of reusable actions.")
        for name, entry in reusable.items() if isinstance(reusable, Mapping) else []:
            fields = entry.get("fields") if isinstance(entry, Mapping) else None
            if not isinstance(fields, Mapping):
                invalid(f"Reusable action {name!r} of overlay {label!r} has no `fields` object.")
            elif "target" in fields:
                invalid(
                    f"Reusable action {name!r} of overlay {label!r} declares a `target`; a reusable "
                    "action's fields must not (the reference supplies it)."
                )
    return findings


def _expand_action(
    label: str,
    overlay: Mapping[str, Any],
    revision: str,
    index: int,
    action: Any,
    result: OverlayApplication,
) -> Any:
    """Resolve a 1.2 Reusable Action Reference into the action it stands for.

    A reference ``{$ref: '#/components/actions/<name>', target, description?}`` becomes the named
    component's ``fields`` plus the reference's ``target`` (and its ``description``, which wins
    over the component's). Any other action is returned unchanged. A reference that cannot be
    resolved — or any ``$ref`` before 1.2 — gets a finding and is replaced by ``None`` so
    :func:`_apply_action` skips it.
    """
    if not isinstance(action, Mapping) or "$ref" not in action:
        return action

    def invalid(message: str) -> None:
        result.findings.append(
            OverlayFinding(FINDING_ACTION_INVALID, label, index, str(action.get("target") or ""), message)
        )

    ref = action.get("$ref")
    if not _at_least(revision, "1.2"):
        invalid(
            f"Action #{index} of overlay {label!r} is a `$ref`, which Overlay {revision} does not have "
            "(1.2 added reusable actions); it was not applied."
        )
        return None
    if not isinstance(ref, str) or not ref.startswith(_COMPONENT_ACTION_PREFIX):
        invalid(
            f"Action #{index} of overlay {label!r} has `$ref` {ref!r}; a reusable-action reference must be "
            f"`{_COMPONENT_ACTION_PREFIX}<name>`."
        )
        return None
    name = ref[len(_COMPONENT_ACTION_PREFIX) :].replace("~1", "/").replace("~0", "~")
    components = overlay.get("components")
    reusable = components.get("actions") if isinstance(components, Mapping) else None
    entry = reusable.get(name) if isinstance(reusable, Mapping) else None
    fields = entry.get("fields") if isinstance(entry, Mapping) else None
    if not isinstance(fields, Mapping) or "target" in fields:
        invalid(f"Action #{index} of overlay {label!r} references {ref!r}, which names no usable reusable action.")
        return None
    expanded = dict(fields)
    expanded["target"] = action.get("target")
    if "description" in action:
        expanded["description"] = action["description"]
    return expanded


def _extends_finding(
    label: str,
    overlay: Mapping[str, Any],
    revision: str,
    base_path: str,
    base: Mapping[str, Any],
) -> Optional[OverlayFinding]:
    """An ``extends-unresolved`` finding when ``extends`` names a document other than the base.

    ``extends`` resolves to the base when, as a path relative to the overlay's member path, it
    names the base's member path; or when, resolved against the overlay's ``$self`` (1.2) or taken
    as an absolute URI, it equals the base's ``$self``. With no ``extends`` there is nothing to
    check (the specification leaves the choice of target to the tool).
    """
    extends = overlay.get("extends")
    if extends is None:
        return None
    if not isinstance(extends, str) or not extends.strip():
        return OverlayFinding(
            FINDING_EXTENDS_UNRESOLVED,
            label,
            -1,
            "",
            f"Overlay {label!r} has an `extends` that is not a URI reference.",
        )
    extends = extends.strip()
    base_self = base.get("$self") if isinstance(base.get("$self"), str) else None
    own_self = overlay.get("$self") if _at_least(revision, "1.2") and isinstance(overlay.get("$self"), str) else None
    candidates = []
    if urlsplit(extends).scheme:
        candidates.append(extends)
    elif own_self and urlsplit(own_self).scheme:
        candidates.append(urljoin(own_self, extends))
    if base_self and any(c.rstrip("/") == base_self.strip().rstrip("/") for c in candidates):
        return None
    if not urlsplit(extends).scheme:
        relative = posixpath.normpath(posixpath.join(posixpath.dirname(label), extends))
        if relative == posixpath.normpath(base_path):
            return None
    return OverlayFinding(
        FINDING_EXTENDS_UNRESOLVED,
        label,
        -1,
        "",
        f"Overlay {label!r} extends {extends!r}, but it was applied to {base_path!r}"
        + (f" (`$self` {base_self!r})" if base_self else "")
        + "; the overlay may have been written for a different document.",
    )


def overlay_lint_findings(report: Mapping[str, Any]) -> List[Any]:
    """Adapt an overlay report's findings into ``overlay`` pack lint findings.

    Returns SPI :class:`app.import_source.LintFinding` objects (imported lazily so this pure module
    stays off the SPI's import path), one per overlay finding, under the rule its code maps to in
    :mod:`app.overlay_lint_rules`, at that rule's default severity — promotable per tenant through
    the style guide like any registered rule.

    Args:
        report: The ``overlay`` extras block (:meth:`OverlayApplication.report`), or a
            :meth:`BareOverlayReport.as_dict` block.

    Returns:
        The lint findings; empty when the report carries no findings.
    """
    from .import_source import LintFinding
    from .overlay_lint_rules import OVERLAY_RULES

    findings: List[Any] = []
    for raw in report.get("findings") or []:
        if not isinstance(raw, Mapping):
            continue
        rule = _RULE_FOR_CODE.get(str(raw.get("code")), _RULE_FOR_CODE[FINDING_ACTION_INVALID])
        category, severity, _ = OVERLAY_RULES[rule]
        target = str(raw.get("target") or "")
        findings.append(
            LintFinding(
                path=target or str(raw.get("overlay") or "#"),
                rule=rule,
                severity=severity,
                category=category,
                message=str(raw.get("message") or "Overlay action could not be applied."),
            )
        )
    return findings


def _rule_for_code() -> Dict[str, str]:
    from .overlay_lint_rules import (
        RULE_OVERLAY_ACTION_INVALID,
        RULE_OVERLAY_EXTENDS_UNRESOLVED,
        RULE_OVERLAY_TARGET_EXPRESSION_INVALID,
        RULE_OVERLAY_UNMATCHED_TARGET,
        RULE_OVERLAY_VERSION_UNSUPPORTED,
    )

    return {
        FINDING_UNMATCHED_TARGET: RULE_OVERLAY_UNMATCHED_TARGET,
        FINDING_ACTION_INVALID: RULE_OVERLAY_ACTION_INVALID,
        FINDING_TARGET_EXPRESSION_INVALID: RULE_OVERLAY_TARGET_EXPRESSION_INVALID,
        FINDING_EXTENDS_UNRESOLVED: RULE_OVERLAY_EXTENDS_UNRESOLVED,
        FINDING_VERSION_UNSUPPORTED: RULE_OVERLAY_VERSION_UNSUPPORTED,
    }


#: Finding code → ``overlay`` pack rule id.
_RULE_FOR_CODE: Dict[str, str] = _rule_for_code()


def overlay_rule_for(code: str) -> str:
    """The ``overlay`` pack rule id a finding code maps to (unknown codes → ``action-invalid``)."""
    return _RULE_FOR_CODE.get(code, _RULE_FOR_CODE[FINDING_ACTION_INVALID])


# ---------------------------------------------------------------------------
# Bare-overlay lint
# ---------------------------------------------------------------------------


#: Why a base-dependent rule was not decided for a bare overlay.
SKIPPED_NO_BASE = "no-base"


@dataclass
class BareOverlayReport:
    """The lint of an overlay on its own, with no base document (GVM-4.1).

    Attributes:
        version: The ``overlay`` marker, or ``None`` when the document has none.
        revision: The supported revision it selects, or ``None``.
        findings: Findings of the rules that could run (version and structure).
        rules: One ``{rule_id, status, reason}`` per ``overlay`` rule: ``failed`` when it has a
            finding, ``passed`` when it ran clean, ``skipped`` (``reason: no-base``) for a rule that
            needs the base — never ``passed`` for those.
    """

    version: Optional[str]
    revision: Optional[str]
    findings: List[OverlayFinding] = field(default_factory=list)
    rules: List[Dict[str, Optional[str]]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        """Serialize (the shape :func:`overlay_lint_findings` also reads)."""
        return {
            "version": self.version,
            "revision": self.revision,
            "findings": [finding.as_dict() for finding in self.findings],
            "rules": [dict(rule) for rule in self.rules],
        }


def lint_bare_overlay(document: Any, *, label: str = "overlay") -> BareOverlayReport:
    """Lint an Overlay document on its own — no base to apply it to.

    Runs everything that does not need the base: the version check, the document-level checks
    (``$self``, reusable actions), each action's shape for its revision, and whether every
    ``target`` and ``copy`` expression parses. ``unmatched-target`` and ``extends-unresolved`` can
    only be decided against a base, so they are reported ``skipped`` with reason ``no-base`` —
    never ``passed``, which would claim a check that never ran.

    Args:
        document: The parsed overlay document.
        label: The name findings use for it (the file name, when known).

    Returns:
        The :class:`BareOverlayReport`.
    """
    from .overlay_lint_rules import BASE_DEPENDENT_RULES, OVERLAY_RULES

    version = overlay_version(document)
    revision = overlay_revision(version)
    report = BareOverlayReport(version=version, revision=revision)
    if revision is None:
        message = (
            _unsupported_message(label, version)
            if version is not None
            else f"{label!r} has no `overlay` version marker, so it is not an Overlay document."
        )
        report.findings.append(OverlayFinding(FINDING_VERSION_UNSUPPORTED, label, -1, "", message))
    else:
        report.findings.extend(_document_findings(label, document, revision))
        actions = document.get("actions")
        if not isinstance(actions, list) or not actions:
            report.findings.append(
                OverlayFinding(
                    FINDING_ACTION_INVALID,
                    label,
                    -1,
                    "",
                    f"Overlay {label!r} has no `actions` array; an Overlay document must declare at least one action.",
                )
            )
        else:
            probe = OverlayApplication(document={})
            for index, action in enumerate(actions):
                expanded = _expand_action(label, document, revision, index, action, probe)
                if expanded is not None:
                    _check_action(probe, label, index, expanded, revision)
            report.findings.extend(probe.findings)

    failed = {_RULE_FOR_CODE[finding.code] for finding in report.findings}
    for rule_id in OVERLAY_RULES:
        if rule_id in failed:
            report.rules.append({"rule_id": rule_id, "status": "failed", "reason": None})
        elif rule_id in BASE_DEPENDENT_RULES:
            report.rules.append({"rule_id": rule_id, "status": "skipped", "reason": SKIPPED_NO_BASE})
        elif revision is None:
            report.rules.append({"rule_id": rule_id, "status": "skipped", "reason": "version-unsupported"})
        else:
            report.rules.append({"rule_id": rule_id, "status": "passed", "reason": None})
    return report


# ---------------------------------------------------------------------------
# Action application
# ---------------------------------------------------------------------------


def _parse(expression: str):
    """Parse a JSONPath with the custom-rule DSL's Spectral-compatible parser (cached)."""
    from .custom_rule_dsl import parse_jsonpath_expression

    return parse_jsonpath_expression(expression)


def _check_action(
    result: OverlayApplication, overlay: str, index: int, action: Any, revision: str
) -> Optional[Tuple[str, bool, bool]]:
    """Validate one action's shape for ``revision``, recording findings on ``result``.

    Returns:
        ``(target, remove, uses_copy)`` when the action can be applied, else ``None``.
    """

    def _finding(code: str, target: str, message: str) -> None:
        result.findings.append(
            OverlayFinding(code=code, overlay=overlay, action_index=index, target=target, message=message)
        )

    if action is None:
        return None  # an unresolvable reusable-action reference, already reported
    if not isinstance(action, Mapping):
        _finding(FINDING_ACTION_INVALID, "", f"Action #{index} of overlay {overlay!r} is not an object.")
        return None
    target = action.get("target")
    if not isinstance(target, str) or not target.strip():
        _finding(FINDING_ACTION_INVALID, "", f"Action #{index} of overlay {overlay!r} has no `target` expression.")
        return None
    remove = action.get("remove", False)
    if not isinstance(remove, bool):
        _finding(
            FINDING_ACTION_INVALID, target, f"Action #{index} of overlay {overlay!r} has a non-boolean `remove` value."
        )
        return None
    has_copy = "copy" in action
    if has_copy and not _at_least(revision, "1.1"):
        _finding(
            FINDING_ACTION_INVALID,
            target,
            f"Action #{index} of overlay {overlay!r} uses `copy`, which Overlay {revision} does not have "
            "(1.1 added it); declare `overlay: 1.1.0` or later.",
        )
        return None
    if has_copy and "update" in action and not remove and _at_least(revision, "1.2"):
        _finding(
            FINDING_ACTION_INVALID,
            target,
            f"Action #{index} of overlay {overlay!r} has both `update` and `copy`; in Overlay 1.2 each voids "
            "the other, so the action is not applied. Split it into two actions.",
        )
        return None
    if has_copy and not remove and not (isinstance(action.get("copy"), str) and action["copy"].strip()):
        _finding(
            FINDING_ACTION_INVALID,
            target,
            f"Action #{index} of overlay {overlay!r} has a `copy` that is not a JSONPath expression.",
        )
        return None
    if not remove and "update" not in action and not has_copy:
        _finding(
            FINDING_ACTION_INVALID,
            target,
            f"Action #{index} of overlay {overlay!r} declares neither `update`"
            + (", `copy`" if _at_least(revision, "1.1") else "")
            + " nor `remove: true`, so it can have no effect.",
        )
        return None
    for label_name, expression in (
        ("Target", target),
        ("Copy source", action.get("copy") if has_copy and not remove else None),
    ):
        if expression is None:
            continue
        try:
            _parse(expression)
        except Exception as exc:  # noqa: BLE001 - jsonpath-ng raises bare Exception subclasses
            _finding(
                FINDING_TARGET_EXPRESSION_INVALID,
                target,
                f"{label_name} {expression!r} of overlay {overlay!r} is not a valid JSONPath expression: {exc}.",
            )
            return None
    return target, remove, has_copy and not remove


def _apply_action(result: OverlayApplication, overlay: str, index: int, action: Any, revision: str = "1.0") -> None:
    """Apply one Overlay action with ``revision``'s semantics, recording provenance and findings."""
    checked = _check_action(result, overlay, index, action, revision)
    if checked is None:
        return
    target, remove, uses_copy = checked

    def _finding(code: str, message: str) -> None:
        result.findings.append(
            OverlayFinding(code=code, overlay=overlay, action_index=index, target=target, message=message)
        )

    try:
        matches = _parse(target).find(result.document)
    except Exception as exc:  # noqa: BLE001 - evaluation faults must become findings
        _finding(
            FINDING_TARGET_EXPRESSION_INVALID,
            f"Target {target!r} of overlay {overlay!r} could not be evaluated: {exc}.",
        )
        return
    if not matches:
        _finding(
            FINDING_UNMATCHED_TARGET,
            f"Target {target!r} of overlay {overlay!r} (action #{index}) matched "
            "nothing in the document; the action was not applied.",
        )
        return
    if len(matches) > MAX_MATCHES_PER_ACTION:
        _finding(
            FINDING_ACTION_INVALID,
            f"Target {target!r} of overlay {overlay!r} selected {len(matches)} nodes, "
            f"above the {MAX_MATCHES_PER_ACTION}-node ceiling; only the first "
            f"{MAX_MATCHES_PER_ACTION} were modified.",
        )
        matches = matches[:MAX_MATCHES_PER_ACTION]

    def _record(pointer: str, kind: str) -> None:
        result.provenance.append(
            OverlayProvenanceRecord(pointer=pointer, kind=kind, overlay=overlay, action_index=index, target=target)
        )

    def _legacy_finding(code: str, _target: str, message: str) -> None:
        _finding(code, message)

    if remove:
        _remove_matches(matches, _record, _legacy_finding, target, overlay)
        return

    if uses_copy:
        source = action["copy"]
        try:
            sources = _parse(source).find(result.document)
        except Exception as exc:  # noqa: BLE001
            _finding(
                FINDING_TARGET_EXPRESSION_INVALID,
                f"Copy source {source!r} of overlay {overlay!r} could not be evaluated: {exc}.",
            )
            return
        if len(sources) != 1:
            _finding(
                FINDING_ACTION_INVALID,
                f"Copy source {source!r} of overlay {overlay!r} (action #{index}) selected {len(sources)} nodes; "
                "`copy` must select exactly one.",
            )
            return
        payload = copy.deepcopy(sources[0].value)
    else:
        payload = action.get("update")

    if _at_least(revision, "1.1"):
        shapes = {_shape(datum.value) for datum in matches}
        if len(shapes) > 1:
            _finding(
                FINDING_ACTION_INVALID,
                f"Target {target!r} of overlay {overlay!r} selected a mix of {', '.join(sorted(shapes))} nodes; "
                f"Overlay {revision} requires them to be all objects, all arrays or all primitives.",
            )
            return
    for datum in matches:
        _update_match(datum, payload, _record, _legacy_finding, target, overlay, revision)


def _shape(value: Any) -> str:
    """``object``, ``array`` or ``primitive`` — the node kinds Overlay 1.1 distinguishes."""
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return "primitive"


def _remove_matches(matches, record, finding, target: str, overlay: str) -> None:
    """Remove every matched node from its parent container.

    Dict members are deleted directly; list elements are collected per parent list
    and deleted in descending index order, since removing a lower index first would
    shift every later match's position.
    """
    list_removals: Dict[int, Tuple[list, List[Tuple[int, str]]]] = {}
    for datum in matches:
        parent = datum.context
        if parent is None:
            finding(
                FINDING_ACTION_INVALID,
                target,
                f"Target {target!r} of overlay {overlay!r} selects the document root, which cannot be removed.",
            )
            continue
        pointer = _pointer_for(datum)
        container = parent.value
        step = _path_step(datum)
        if isinstance(container, dict) and isinstance(step, str):
            if step in container:
                del container[step]
                record(pointer, "removed")
        elif isinstance(container, list) and isinstance(step, int):
            entry = list_removals.setdefault(id(container), (container, []))
            entry[1].append((step, pointer))
        else:  # pragma: no cover - jsonpath-ng only yields dict/list parents
            finding(
                FINDING_ACTION_INVALID,
                target,
                f"Target {target!r} of overlay {overlay!r} selects a node whose "
                "parent is not a container; it cannot be removed.",
            )
    for container, entries in list_removals.values():
        for step, pointer in sorted(entries, reverse=True):
            if 0 <= step < len(container):
                del container[step]
                record(pointer, "removed")


def _update_match(datum, update: Any, record, finding, target: str, overlay: str, revision: str = "1.0") -> None:
    """Apply one action's ``update`` (or ``copy``) value to one matched node, per ``revision``."""
    node = datum.value
    pointer = _pointer_for(datum)
    modern = _at_least(revision, "1.1")
    if isinstance(node, dict):
        if not isinstance(update, Mapping):
            finding(
                FINDING_ACTION_INVALID,
                target,
                f"Target {target!r} of overlay {overlay!r} selects an object, so its "
                f"`update` value must be an object to merge (Overlay {revision}).",
            )
            return
        if modern:
            conflict = _merge_conflict(node, update, pointer)
            if conflict is not None:
                finding(
                    FINDING_ACTION_INVALID,
                    target,
                    f"Target {target!r} of overlay {overlay!r}: the update cannot be merged at {conflict!r} — "
                    f"Overlay {revision} merges only object into object, array into array and primitive "
                    "into primitive. The node was left unchanged.",
                )
                return
        _merge_object(node, update, pointer, record, modern=modern)
        return
    if isinstance(node, list):
        if modern and isinstance(update, list):
            for item in update:
                node.append(copy.deepcopy(item))
                record(f"{pointer}/{len(node) - 1}", "appended")
            return
        node.append(copy.deepcopy(update))
        record(f"{pointer}/{len(node) - 1}", "appended")
        return
    if modern and isinstance(update, (Mapping, list)):
        finding(
            FINDING_ACTION_INVALID,
            target,
            f"Target {target!r} of overlay {overlay!r} selects a primitive, so its `update` must be a primitive "
            f"to replace it (Overlay {revision}).",
        )
        return
    parent = datum.context
    step = _path_step(datum)
    if parent is None or step is None:  # pragma: no cover - the root is always a mapping
        finding(
            FINDING_ACTION_INVALID,
            target,
            f"Target {target!r} of overlay {overlay!r} selects a value that cannot be replaced in place.",
        )
        return
    parent.value[step] = copy.deepcopy(update)
    record(pointer, "replaced")


def _merge_conflict(node: Mapping[str, Any], update: Mapping[str, Any], pointer: str) -> Optional[str]:
    """The pointer of the first incompatible pairing an Overlay 1.1 merge would hit, or ``None``.

    Checked before anything is written, so an incompatible update leaves the node untouched.
    """
    for key, value in update.items():
        if key not in node:
            continue
        existing = node[key]
        child = f"{pointer}/{_escape_pointer_token(str(key))}"
        if _shape(existing) != _shape(value):
            return child
        if isinstance(value, Mapping):
            nested = _merge_conflict(existing, value, child)
            if nested is not None:
                return nested
    return None


def _merge_object(
    node: Dict[str, Any], update: Mapping[str, Any], pointer: str, record, *, modern: bool = False
) -> None:
    """Deep-merge ``update`` into ``node``, recording one record per changed leaf.

    Overlay 1.0: nested objects merge recursively; every other value (primitives **and arrays**)
    replaces the existing value. Overlay 1.1+ (``modern``): additionally, an array concatenates
    onto an existing array (each new entry recorded ``appended``); incompatible pairings were
    refused by :func:`_merge_conflict` before this runs.
    """
    for key, value in update.items():
        child_pointer = f"{pointer}/{_escape_pointer_token(str(key))}"
        existing = node.get(key)
        if isinstance(value, Mapping) and isinstance(existing, dict):
            _merge_object(existing, value, child_pointer, record, modern=modern)
            continue
        if modern and isinstance(value, list) and isinstance(existing, list):
            for item in value:
                existing.append(copy.deepcopy(item))
                record(f"{child_pointer}/{len(existing) - 1}", "appended")
            continue
        kind = "set" if key not in node else "replaced"
        node[key] = copy.deepcopy(value)
        record(child_pointer, kind)


# ---------------------------------------------------------------------------
# JSON Pointer derivation
# ---------------------------------------------------------------------------


def _escape_pointer_token(token: str) -> str:
    """Escape one JSON Pointer reference token (RFC 6901: ``~`` → ``~0``, ``/`` → ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def _path_step(datum) -> Any:
    """The dict key (str) or list index (int) of a datum inside its parent, or ``None``."""
    from jsonpath_ng import Fields, Index

    path = datum.path
    if isinstance(path, Fields) and path.fields:
        return path.fields[0]
    if isinstance(path, Index):
        index = getattr(path, "index", None)
        if isinstance(index, int):
            return index
        # jsonpath-ng >= 1.7 stores a tuple in `indices`.
        indices = getattr(path, "indices", None)
        if isinstance(indices, (tuple, list)) and indices:
            return indices[0]
    return None


def _pointer_for(datum) -> str:
    """Build the RFC 6901 JSON Pointer for a jsonpath-ng match datum.

    Walks the datum's context chain to the root, collecting each step's dict key or
    list index. The root document itself yields ``""`` (the whole-document pointer).
    """
    tokens: List[str] = []
    current = datum
    while current is not None and current.context is not None:
        step = _path_step(current)
        if step is None:
            break
        tokens.append(_escape_pointer_token(str(step)))
        current = current.context
    return "".join(f"/{token}" for token in reversed(tokens))
