"""Avro breaking-change classifier — MFI-12.4 (#3785).

Avro compatibility is not a property of a change on its own: it is whether data written with one
schema can be read with the other (:mod:`app.avro_compatibility`). This classifier runs that check
both ways over the two versions' schemas and grades each canonical change by Confluent's
compatibility modes, with ``BACKWARD`` — a Confluent registry's default level — as the line between
breaking and not:

=================================================  ==========  ===============================
The Avro check                                     Severity    Modes the change breaks
=================================================  ==========  ===============================
The new schema cannot read data the old one wrote  breaking    BACKWARD, FULL (+ TRANSITIVE)
Only the old schema cannot read the new one's      dangerous   FORWARD, FULL (+ TRANSITIVE)
Both read each other                               safe        none
=================================================  ==========  ===============================

So adding a field without a ``default`` is breaking (new readers have nothing to fill it with),
removing one is dangerous (old readers miss it), and adding or removing a field that has a
``default`` is safe — which the format-agnostic baseline cannot tell apart.

Each problem joins the canonical change on the same entity: the named type it is about (an enum
missing symbols, a renamed record), else the record field it is on, else its record. A record or
field change no problem joins is graded safe — the check read it both ways — when the check
covered it: every type of a ``.avsc`` document (its root schema reaches them all, so a namespace
move or a renamed record with an alias is judged by Avro, not by its changed keys), and the types
both versions of an IDL protocol declare. Changes outside the schemas (a protocol's operations and
messages), protocol types only one version declares, and the whole diff when either schema cannot
be read keep the baseline grade. A problem that joins no change is kept in ``unattributed``.

The schemas compared are the ones kept on :attr:`CanonicalApi.raw
<app.canonical_model.CanonicalApi.raw>` (``avro``): for a ``.avsc`` document its root schema, for
an IDL protocol every named type both versions declare.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .avro_compatibility import AvroCompatibilityError, Incompatibility, can_read, describe, schema_of_document
from .avro_parser import AvroDocument
from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    UnattributedFinding,
    _assemble_result,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import EntityCategory, ModelDiff

__all__ = ["AvroBreakingChangeClassifier", "compatibility_findings"]

_RULE_PREFIX = "avro-compatibility."
_COMPATIBLE_RULE = f"{_RULE_PREFIX}compatible"

#: Direction → (severity, the modes a problem in that direction breaks).
_DIRECTIONS: Dict[str, Tuple[Severity, str]] = {
    "backward": (Severity.BREAKING, "breaks BACKWARD and FULL: the new schema cannot read data written with the old"),
    "forward": (Severity.DANGEROUS, "breaks FORWARD and FULL: the old schema cannot read data written with the new"),
}

Finding = Tuple[str, Incompatibility]


def _document(model: CanonicalApi) -> Optional[AvroDocument]:
    """Parse the Avro text a model kept on ``raw``, or ``None`` when there is none or it fails."""
    from .avro_import_source import AvroImportSource
    from .import_source import ImportSourceError

    raw = model.raw if isinstance(model.raw, dict) else {}
    text = raw.get("avro")
    if not isinstance(text, str):
        return None
    label = "schema.avdl" if model.extras.get("avro_syntax") == "avdl" else "schema.avsc"
    try:
        return AvroImportSource().parse(text, source_label=label)
    except ImportSourceError:
        return None


def _declared(document: AvroDocument) -> Set[str]:
    return {f"{t.namespace}.{t.name}" if t.namespace else t.name for t in document.types}


def compatibility_findings(
    base: CanonicalApi, target: CanonicalApi
) -> Optional[Tuple[List[Finding], Optional[Set[str]]]]:
    """Run the Avro compatibility check both ways between two versions.

    Args:
        base: The old version.
        target: The new version.

    Returns:
        ``(findings, compared types)``: each finding as ``(direction, incompatibility)`` —
        ``backward`` when the new schema cannot read the old one's data, ``forward`` when the old
        cannot read the new one's — and, for IDL protocols, the full names of the named types both
        versions declare (the ones compared); ``None`` in that place when the two root schemas were
        compared, which reaches every type. ``None`` overall when either schema cannot be read.
    """
    old, new = _document(base), _document(target)
    if old is None or new is None:
        return None
    shared: Optional[Set[str]] = None
    if old.protocol is None and new.protocol is None:
        pairs: List[Tuple[Optional[str], Optional[str]]] = [(None, None)]  # the roots reach every type
    else:
        shared = _declared(old) & _declared(new)
        pairs = [(name, name) for name in sorted(shared)]
    findings: List[Finding] = []
    try:
        for old_name, new_name in pairs:
            old_schema, new_schema = schema_of_document(old, old_name), schema_of_document(new, new_name)
            findings += [("backward", found) for found in can_read(new_schema, old_schema)]
            findings += [("forward", found) for found in can_read(old_schema, new_schema)]
    except AvroCompatibilityError:
        return None
    return findings, shared


def _join_keys(found: Incompatibility) -> List[Tuple[EntityCategory, str]]:
    """The canonical changes a problem may join, most specific first."""
    keys: List[Tuple[EntityCategory, str]] = []
    if found.schema:
        keys.append((EntityCategory.TYPE, found.schema))
    if found.record and found.field:
        keys.append((EntityCategory.FIELD, f"{found.record}.{found.field}"))
    if found.record:
        keys.append((EntityCategory.TYPE, found.record))
    return keys


def _owner(key: str, type_keys: Set[str]) -> Optional[str]:
    """The type a field key belongs to (the longest type key it extends)."""
    owners = [t for t in type_keys if key.startswith(t + ".")]
    return max(owners, key=len) if owners else None


def _graded(baseline: ChangeClassification, findings: List[Finding]) -> ChangeClassification:
    severities = [_DIRECTIONS[direction][0] for direction, _ in findings]
    worst = _worst(severities)
    direction, first = next((d, f) for (d, f), s in zip(findings, severities) if s is worst)
    reasons = list(dict.fromkeys(f"{_DIRECTIONS[d][1]} — {describe(d, f)}" for d, f in findings))
    return ChangeClassification(
        category=baseline.category,
        kind=baseline.kind,
        key=baseline.key,
        severity=worst,
        rule_id=f"{_RULE_PREFIX}{first.type.lower().replace('_', '-')}",
        rationale="; ".join(reasons),
    )


def _compatible(baseline: ChangeClassification) -> ChangeClassification:
    return baseline.model_copy(
        update={
            "severity": Severity.SAFE,
            "rule_id": _COMPATIBLE_RULE,
            "rationale": "Avro schema resolution reads it both ways (FULL compatible).",
        }
    )


class AvroBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an Avro diff by Avro schema resolution and Confluent's modes (see the module docstring)."""

    format = "avro"
    classifier_id = "avro-compatibility"

    def classify(self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
        """Grade every change with the baseline, then by the Avro compatibility check.

        Args:
            model_diff: The diff to grade.
            base: The old version (its ``raw`` Avro text is the old schema).
            target: The new version.

        Returns:
            The result, 1:1 with ``model_diff.changes``, with unjoined problems in ``unattributed``.
        """
        baseline = [self.classify_change(change, base, target) for change in model_diff.changes]
        result = compatibility_findings(base, target)
        if result is None:
            return _assemble_result(self, target, baseline)
        findings, shared = result

        index: Dict[Tuple[EntityCategory, str], List[int]] = {}
        for position, classification in enumerate(baseline):
            index.setdefault((classification.category, classification.key), []).append(position)
        joined: Dict[int, List[Finding]] = {}
        unattributed: List[UnattributedFinding] = []
        for direction, found in findings:
            positions = next((index[key] for key in _join_keys(found) if key in index), [])
            for position in positions:
                joined.setdefault(position, []).append((direction, found))
            if not positions:
                severity, modes = _DIRECTIONS[direction]
                unattributed.append(
                    UnattributedFinding(
                        severity=severity,
                        rule_id=f"{_RULE_PREFIX}{found.type.lower().replace('_', '-')}",
                        rationale=f"{modes} — {describe(direction, found)}",
                        shape=found.schema or found.record,
                    )
                )

        type_keys = {t.key for t in base.types} | {t.key for t in target.types}
        declared_somewhere = {t.key for t in base.types if t.extras.get("avro_kind") != "union"} | {
            t.key for t in target.types if t.extras.get("avro_kind") != "union"
        }

        def covered(classification: ChangeClassification) -> bool:
            if classification.category not in (EntityCategory.TYPE, EntityCategory.FIELD):
                return False
            if shared is None:
                return True
            if classification.category is EntityCategory.TYPE:
                key = classification.key
                return key in shared or key not in declared_somewhere
            if classification.category is EntityCategory.FIELD:
                owner = _owner(classification.key, type_keys)
                return owner is not None and owner in shared
            return False

        graded = [
            _graded(c, joined[p]) if p in joined else (_compatible(c) if covered(c) else c)
            for p, c in enumerate(baseline)
        ]
        return _assemble_result(self, target, graded, unattributed)
