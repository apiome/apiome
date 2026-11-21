"""Lint-fix plans — GVM-3.2 (#5870).

GVM-3.1 (:mod:`app.lint_fix`) gave a rule a deterministic fix for **one** finding. This module
turns a whole document into a **plan**: every fixable finding, the RFC 6902 operations that would
repair it, and whether those operations may be applied. The plan is what the CLI, the UI, CI and
the Studio agent read, through ``GET …/lint/fixes``, ``POST /v1/lint/fixes/plan`` and
``POST …/lint/fixes/apply`` (:mod:`app.lint_fix_routes`).

Each entry carries a status:

``ready``
    The fix may be applied.
``conflict``
    Its operations touch a subtree another ``ready`` fix already touches (one pointer is the
    other or lies beneath it). Entries are ordered by finding path (and, for one node, by how
    shallow the fix's edit is), so the fix of the *outer* node wins: removing an unused schema
    beats re-spelling a keyword inside it. The loser names the winner in ``conflictsWith``.
    Planning again after the winner is applied re-plans the loser if its finding still stands.
``breaking``
    The fix's own delta — the document with only this fix applied, diffed against the original
    with the CTG classifier (:func:`app.change_taxonomy.classify_openapi_changes`) — contains a
    breaking change. The classification is attached. A breaking fix is never applied.
``excluded``
    Not selected: the caller's ``rules`` filter leaves it out (``not-selected``), the style guide
    turns the rule off (``guide-disabled``), it renames something and renames were not asked for
    (``renames-not-included``), or the rule's fix is off by default (``opt-in-required``). Naming
    a rule in ``rules`` selects it whatever the guide or its default says. The operations are
    still listed, so a reader sees what the fix would do.

A plan is a pure function of the document and the options: no clock, no I/O, deterministic
ordering, so the same request yields byte-identical output (an acceptance criterion).

Renderings (:data:`PLAN_FORMATS`): ``json`` (the plan itself), ``patch`` (the ready operations as
one RFC 6902 document, in application order), ``overlay`` (the same change as an Overlay 1.0
document, :func:`app.openapi_overlay.render_patch_overlay`) and ``diff`` (a unified diff of the
document before and after, as indented JSON).
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .change_taxonomy import classify_openapi_changes
from .lint_fix import (
    DEFAULT_OPERATION_ID_TEMPLATE,
    FixError,
    FixOptions,
    PatchOp,
    apply_fix_ops,
    plan_rule_fix,
    pointer_for_path,
    pointer_within,
    split_pointer,
)
from .arazzo_fix_rules import arazzo_fix_rule, arazzo_fix_rules, is_arazzo_document, lint_arazzo_fixable
from .openapi_fix_rules import lint_openapi_fixable, openapi_fix_rule, openapi_fix_rules
from .schema_lint import LintFinding

__all__ = [
    "EXCLUDED_GUIDE_DISABLED",
    "EXCLUDED_NOT_SELECTED",
    "EXCLUDED_OPT_IN_REQUIRED",
    "EXCLUDED_RENAMES_NOT_INCLUDED",
    "FORMAT_DIFF",
    "FORMAT_JSON",
    "FORMAT_OVERLAY",
    "FORMAT_PATCH",
    "FixPlan",
    "FixPlanEntry",
    "PLAN_FORMATS",
    "PLAN_STATUSES",
    "STATUS_BREAKING",
    "STATUS_CONFLICT",
    "STATUS_EXCLUDED",
    "STATUS_READY",
    "build_fix_plan",
    "compose_entries",
    "document_fingerprint",
    "fix_id_for",
    "parse_rules_param",
]

STATUS_READY = "ready"
STATUS_CONFLICT = "conflict"
STATUS_BREAKING = "breaking"
STATUS_EXCLUDED = "excluded"
#: Every entry status, in the order the documentation lists them.
PLAN_STATUSES: Tuple[str, ...] = (STATUS_READY, STATUS_CONFLICT, STATUS_BREAKING, STATUS_EXCLUDED)

#: Why an entry is ``excluded``.
EXCLUDED_NOT_SELECTED = "not-selected"
EXCLUDED_GUIDE_DISABLED = "guide-disabled"
EXCLUDED_RENAMES_NOT_INCLUDED = "renames-not-included"
EXCLUDED_OPT_IN_REQUIRED = "opt-in-required"

FORMAT_JSON = "json"
FORMAT_PATCH = "patch"
FORMAT_OVERLAY = "overlay"
FORMAT_DIFF = "diff"
#: The renderings a plan has.
PLAN_FORMATS: Tuple[str, ...] = (FORMAT_JSON, FORMAT_PATCH, FORMAT_OVERLAY, FORMAT_DIFF)

#: The fix class whose fixes need ``includeRenames`` (or the rule named in ``rules``).
_RENAME = "rename"


@dataclass(frozen=True)
class FixPlanEntry:
    """One fixable finding of a plan.

    Attributes:
        fix_id: Stable id of the fix (``fix-`` + the finding id's digest); what ``apply`` names.
        rule_id: The rule that reported the finding.
        fix_class: ``structural`` / ``removal`` / ``fill-in`` / ``rename``.
        wire_visible: Whether the fix changes what clients see on the wire or in generated code.
        path: The finding's dotted path.
        pointer: The finding's JSON Pointer.
        finding_id: The finding's id (``lint-…``).
        message: The finding's message.
        ops: The RFC 6902 operations that repair the finding, planned against the original
            document.
        status: One of :data:`PLAN_STATUSES`.
        reason: Why the entry is ``excluded`` (``EXCLUDED_*``), else ``None``.
        conflicts_with: For a ``conflict``, the fix id of the ready fix that wins the subtree.
        classification: The CTG classification of the fix's own delta —
            ``{"maxSeverity", "counts", "changes": [{"ruleId", "severity", "pointer"}]}`` — for
            every entry that was not excluded; ``None`` for excluded entries.
    """

    fix_id: str
    rule_id: str
    fix_class: str
    wire_visible: bool
    path: str
    pointer: str
    finding_id: str
    message: str
    ops: Tuple[PatchOp, ...]
    status: str
    reason: Optional[str] = None
    conflicts_with: Optional[str] = None
    classification: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        """The entry as the JSON object the plan endpoints return (camelCase keys)."""
        return {
            "fixId": self.fix_id,
            "ruleId": self.rule_id,
            "fixClass": self.fix_class,
            "wireVisible": self.wire_visible,
            "path": self.path,
            "pointer": self.pointer,
            "findingId": self.finding_id,
            "message": self.message,
            "ops": [op.as_dict() for op in self.ops],
            "status": self.status,
            "reason": self.reason,
            "conflictsWith": self.conflicts_with,
            "classification": self.classification,
        }


@dataclass(frozen=True)
class FixPlan:
    """A lint-fix plan over one document.

    Attributes:
        document_fingerprint: :func:`document_fingerprint` of the planned document.
        entries: Every fixable finding, ordered by finding pointer, the depth of what the fix
            touches, rule and fix id.
        applied_order: Fix ids of the ``ready`` entries in the order their operations apply
            (reverse document order, so removing an array element never shifts one a later
            fix addresses).
        fixed_document: The document with every ``ready`` fix applied.
        original_document: The planned document (a copy).
        include_renames: Whether renames were asked for.
        rules: The ``rules`` filter, or ``None`` for every rule.
        operation_id_template: The ``operationId`` template the fill-in fix rendered.
    """

    document_fingerprint: str
    entries: Tuple[FixPlanEntry, ...]
    applied_order: Tuple[str, ...]
    fixed_document: Dict[str, Any]
    original_document: Dict[str, Any] = field(repr=False)
    include_renames: bool = False
    rules: Optional[Tuple[str, ...]] = None
    operation_id_template: str = DEFAULT_OPERATION_ID_TEMPLATE

    def entry(self, fix_id: str) -> Optional[FixPlanEntry]:
        """The entry with ``fix_id``, or ``None``."""
        return next((entry for entry in self.entries if entry.fix_id == fix_id), None)

    def ready(self) -> List[FixPlanEntry]:
        """The ``ready`` entries, in application order."""
        by_id = {entry.fix_id: entry for entry in self.entries}
        return [by_id[fix_id] for fix_id in self.applied_order]

    def counts(self) -> Dict[str, int]:
        """How many entries have each status (every status present, zero included)."""
        tally = {status: 0 for status in PLAN_STATUSES}
        for entry in self.entries:
            tally[entry.status] += 1
        return tally

    def patch(self) -> List[Dict[str, Any]]:
        """The ready operations as one RFC 6902 JSON Patch document, in application order."""
        return [op.as_dict() for entry in self.ready() for op in entry.ops]

    def overlay(self) -> Dict[str, Any]:
        """The ready fixes as an Overlay 1.0 document; ``info.title`` names the rules."""
        from .openapi_overlay import render_patch_overlay

        ready = self.ready()
        rules = sorted({entry.rule_id for entry in ready})
        title = "Apiome lint fixes: " + (", ".join(rules) if rules else "none")
        groups = [(f"{entry.fix_id} ({entry.rule_id})", entry.ops) for entry in ready]
        return render_patch_overlay(self.original_document, groups, title=title)

    def unified_diff(self) -> str:
        """A unified diff of the document before and after the ready fixes, as indented JSON.

        Returns:
            The diff text (``a/openapi.json`` → ``b/openapi.json``); empty when nothing changes.
        """
        before = _pretty(self.original_document).splitlines()
        after = _pretty(self.fixed_document).splitlines()
        name = "arazzo.json" if is_arazzo_document(self.original_document) else "openapi.json"
        lines = list(difflib.unified_diff(before, after, f"a/{name}", f"b/{name}", lineterm=""))
        return "\n".join(lines) + "\n" if lines else ""

    def as_dict(self) -> Dict[str, Any]:
        """The plan as the JSON object ``format=json`` returns."""
        return {
            "documentFingerprint": self.document_fingerprint,
            "fixedDocumentFingerprint": document_fingerprint(self.fixed_document),
            "includeRenames": self.include_renames,
            "rules": list(self.rules) if self.rules is not None else None,
            "operationIdTemplate": self.operation_id_template,
            "counts": self.counts(),
            "appliedOrder": list(self.applied_order),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def _pretty(document: Any) -> str:
    """The document as indented JSON, keys in document order."""
    return json.dumps(document, indent=2, ensure_ascii=False)


def document_fingerprint(document: Any) -> str:
    """A stable content hash of a document (``sha256:`` + hex of its canonical JSON).

    Args:
        document: Any JSON-serializable value.

    Returns:
        The fingerprint; equal for documents that are equal as JSON, whatever their key order.
    """
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fix_id_for(finding: LintFinding) -> str:
    """The stable fix id of a finding: ``fix-`` + the digest of its ``lint-`` id."""
    digest = finding.id[len("lint-") :] if finding.id.startswith("lint-") else finding.id
    return f"fix-{digest}"


def parse_rules_param(raw: Optional[str]) -> Optional[Tuple[str, ...]]:
    """Parse a comma-separated ``rules`` query value.

    Args:
        raw: ``"structure.nullable-keyword, structure.empty-required"``, blank, or ``None``.

    Returns:
        The distinct rule ids in the given order, or ``None`` when nothing was given.
    """
    if raw is None:
        return None
    ids = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    return ids or None


def _sort_key(pointer: str) -> Tuple[Tuple[int, Any], ...]:
    """Order pointers by token, array indexes numerically (``/tags/9`` before ``/tags/10``)."""
    return tuple((0, int(token)) if token.isdigit() else (1, token) for token in split_pointer(pointer))


def _entry_key(entry: "FixPlanEntry") -> Tuple[Any, ...]:
    """Plan order of an entry: by finding pointer, then the shallowest pointer its fix touches.

    The second key breaks a tie between fixes of the same node in favour of the one that edits
    the larger subtree — removing a schema comes before re-spelling a keyword inside it, so the
    removal wins the conflict.
    """
    depth = min(len(split_pointer(pointer)) for pointer in _touched(entry.ops))
    return (_sort_key(entry.pointer), depth, entry.rule_id, entry.fix_id)


def _touched(ops: Sequence[PatchOp]) -> List[str]:
    """Every pointer an entry's operations write or read from."""
    pointers: List[str] = []
    for op in ops:
        pointers.append(op.path)
        if op.from_pointer is not None:
            pointers.append(op.from_pointer)
    return pointers


def _overlaps(left: Sequence[str], right: Sequence[str]) -> bool:
    """Whether any pointer of ``left`` is, contains or lies within a pointer of ``right``."""
    return any(pointer_within(a, b) or pointer_within(b, a) for a in left for b in right)


def _classification(document: Mapping[str, Any], ops: Sequence[PatchOp]) -> Optional[Dict[str, Any]]:
    """Classify one fix's own delta with the CTG classifier; ``None`` when it does not apply."""
    try:
        fixed = apply_fix_ops(document, ops)
    except FixError:
        return None
    if is_arazzo_document(document):
        # No Arazzo change taxonomy classifies a single fix's delta yet; the Arazzo fixes edit one
        # id, one criteria list or the version marker and are non-breaking by construction.
        return {"maxSeverity": None, "counts": {}, "changes": []}
    diff = classify_openapi_changes(dict(document), fixed)
    return {
        "maxSeverity": diff.max_severity,
        "counts": dict(diff.counts),
        "changes": [
            {"ruleId": change.rule_id, "severity": change.severity, "pointer": change.pointer}
            for change in diff.changes
        ],
    }


def _exclusion(
    rule: Any,
    rules: Optional[Tuple[str, ...]],
    include_renames: bool,
    enabled: Callable[[str], bool],
) -> Optional[str]:
    """Why a rule's fixes are excluded under these options, or ``None`` when they are selected."""
    if rules is not None:
        return None if rule.rule_id in rules else EXCLUDED_NOT_SELECTED
    if not enabled(rule.rule_id):
        return EXCLUDED_GUIDE_DISABLED
    if rule.fix_class == _RENAME:
        return None if include_renames else EXCLUDED_RENAMES_NOT_INCLUDED
    return None if rule.fix_default else EXCLUDED_OPT_IN_REQUIRED


def compose_entries(
    document: Mapping[str, Any], entries: Sequence[FixPlanEntry]
) -> Tuple[Dict[str, Any], List[FixPlanEntry], List[FixPlanEntry]]:
    """Apply entries' operations to a copy of ``document`` in reverse document order.

    Each entry's operations were planned against the original document. Applying the entries
    from the end of the document backwards keeps those pointers valid: removing ``/tags/2`` cannot
    shift ``/tags/5`` when ``/tags/5`` was handled first. Entries must not overlap (the plan's
    conflict pass guarantees it).

    Args:
        document: The original document. Not mutated.
        entries: The entries to apply, in any order.

    Returns:
        ``(fixed_document, applied, failed)`` — ``applied`` in application order; ``failed``
        holds entries whose operations no longer applied once the others had been.
    """
    ordered = sorted(entries, key=_entry_key, reverse=True)
    working: Dict[str, Any] = apply_fix_ops(document, ())
    applied: List[FixPlanEntry] = []
    failed: List[FixPlanEntry] = []
    for entry in ordered:
        try:
            working = apply_fix_ops(working, entry.ops)
        except FixError:
            failed.append(entry)
            continue
        applied.append(entry)
    return working, applied, failed


def build_fix_plan(
    document: Mapping[str, Any],
    *,
    rules: Optional[Sequence[str]] = None,
    include_renames: bool = False,
    operation_id_template: str = DEFAULT_OPERATION_ID_TEMPLATE,
    enabled: Optional[Callable[[str], bool]] = None,
) -> FixPlan:
    """Build the lint-fix plan of an OpenAPI 3.x or Arazzo 1.x document (GVM-4.5 adds Arazzo).

    Steps: evaluate the fixable rules (:func:`app.openapi_fix_rules.lint_openapi_fixable`), plan
    each finding's fix, mark the excluded ones, classify each remaining fix's own delta and mark
    the breaking ones, then walk the rest in document order marking any that overlaps an earlier
    ready fix as a conflict, and compose the ready set.

    Args:
        document: A parsed OpenAPI 3.x or Arazzo document. Not mutated.
        rules: Plan only these rule ids (naming a rule also selects a fix the guide turns off,
            a rename, or an off-by-default fix). ``None`` for every rule.
        include_renames: Select ``rename`` fixes (including the off-by-default ones).
        operation_id_template: The template the missing-``operationId`` fix renders.
        enabled: Whether the style guide enables a rule id; every rule when omitted.

    Returns:
        The :class:`FixPlan`.

    Raises:
        FixError: When ``operation_id_template`` is invalid, or ``rules`` names a rule that has
            no fix.
    """
    arazzo = is_arazzo_document(document)
    fix_rule = arazzo_fix_rule if arazzo else openapi_fix_rule
    fix_rules = arazzo_fix_rules if arazzo else openapi_fix_rules
    lint_fixable = lint_arazzo_fixable if arazzo else lint_openapi_fixable
    selected = tuple(dict.fromkeys(rules)) if rules else None
    if selected is not None:
        unknown = [rule_id for rule_id in selected if fix_rule(rule_id) is None]
        if unknown:
            raise FixError(f"no fixable rule {', '.join(repr(r) for r in unknown)}")
    is_enabled = enabled or (lambda _rule_id: True)
    # Plan every fix — off-by-default ones included — so excluded entries still show their ops.
    options = FixOptions(
        operation_id_template=operation_id_template,
        opt_in=frozenset(rule.rule_id for rule in fix_rules()),
    ).validate()

    candidates: List[FixPlanEntry] = []
    for finding in lint_fixable(document):
        rule = fix_rule(finding.rule)
        if rule is None:
            continue
        try:
            ops = plan_rule_fix(rule, document, finding, options)
            pointer = pointer_for_path(document, finding.path)
        except FixError:
            continue  # a finding the rule cannot repair deterministically is simply not planned
        if not ops:
            continue
        reason = _exclusion(rule, selected, include_renames, is_enabled)
        candidates.append(
            FixPlanEntry(
                fix_id=fix_id_for(finding),
                rule_id=rule.rule_id,
                fix_class=str(rule.fix_class),
                wire_visible=bool(rule.wire_visible),
                path=finding.path,
                pointer=pointer,
                finding_id=finding.id,
                message=finding.message,
                ops=ops,
                status=STATUS_EXCLUDED if reason else STATUS_READY,
                reason=reason,
            )
        )
    candidates.sort(key=_entry_key)

    entries: List[FixPlanEntry] = []
    winners: List[Tuple[FixPlanEntry, List[str]]] = []
    for entry in candidates:
        if entry.status == STATUS_EXCLUDED:
            entries.append(entry)
            continue
        classification = _classification(document, entry.ops)
        if classification is None:
            continue  # the fix does not apply to its own document: nothing to plan
        entry = replace(entry, classification=classification)
        if classification["maxSeverity"] == "breaking":
            entries.append(replace(entry, status=STATUS_BREAKING))
            continue
        touched = _touched(entry.ops)
        winner = next((w for w, pointers in winners if _overlaps(touched, pointers)), None)
        if winner is not None:
            entries.append(replace(entry, status=STATUS_CONFLICT, conflicts_with=winner.fix_id))
            continue
        winners.append((entry, touched))
        entries.append(entry)

    fixed, applied, failed = compose_entries(document, [w for w, _ in winners])
    if failed:
        failed_ids = {entry.fix_id for entry in failed}
        entries = [
            replace(e, status=STATUS_CONFLICT) if e.fix_id in failed_ids else e for e in entries
        ]

    return FixPlan(
        document_fingerprint=document_fingerprint(document),
        entries=tuple(entries),
        applied_order=tuple(entry.fix_id for entry in applied),
        fixed_document=fixed,
        original_document=apply_fix_ops(document, ()),
        include_renames=include_renames,
        rules=selected,
        operation_id_template=operation_id_template,
    )
