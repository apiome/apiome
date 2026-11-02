"""ONC RPC / XDR breaking-change classifier — MFI-21.6 (#3996).

An ONC RPC program is dispatched by **number** — program, version and procedure (RFC 5531
§8) — and XDR encodes a struct **positionally**, each field by its declared type and bound
(RFC 4506). The format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`)
grades a moved attribute as "something changed"; this classifier grades the wire facts and
leaves everything else to the baseline.

Rule ids (all ``oncrpc.*``):

======================================  ===========  ============================================
Rule                                    Severity     When
======================================  ===========  ============================================
``oncrpc.program-renumbered``           breaking     the program's number changed: rpcbind
                                                     routes old callers to nothing
``oncrpc.version-renumbered``           breaking     a version's number changed
``oncrpc.version-removed``              breaking     a version is gone
``oncrpc.version-added``                safe         a version was added
``oncrpc.procedure-renumbered``         breaking     a procedure's number changed: the wire
                                                     carries the number
``oncrpc.procedure-signature-changed``  breaking     a procedure's argument or result type
                                                     changed
``oncrpc.procedure-removed``            breaking     a procedure is gone
``oncrpc.procedure-added``              safe         a procedure was added
``oncrpc.field-added``                  breaking     a struct field was added: XDR is
                                                     positional, old senders omit it
``oncrpc.field-removed``                breaking     a struct field is gone
``oncrpc.field-reordered``              breaking     a struct field moved: it is cut from the
                                                     wire at another offset
``oncrpc.field-type-changed``           breaking     a field's XDR type changed
``oncrpc.bound-narrowed``               breaking     a ``<N>`` bound shrank: old senders
                                                     overflow it
``oncrpc.bound-widened``                dangerous    a ``<N>`` bound grew or was dropped:
                                                     old receivers reject the longer values
``oncrpc.union-discriminant-changed``   breaking     a union's switch type or field changed
``oncrpc.union-arm-removed``            breaking     a union arm is gone
``oncrpc.union-arm-added``              dangerous    a union arm was added: old receivers
                                                     without a default cannot decode it
``oncrpc.enum-value-removed``           breaking     an enumerator is gone
``oncrpc.enum-value-renumbered``        breaking     an enumerator's number changed
``oncrpc.enum-value-added``             safe         an enumerator was added
======================================  ===========  ============================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange
from .oncrpc_lint import type_shape

__all__ = ["OncRpcBreakingChangeClassifier"]

_FORMAT_KEY = "oncrpc"


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of a self-projection dict."""
    extras = projection.get("extras") if isinstance(projection, Mapping) else None
    return extras if isinstance(extras, Mapping) else {}


def _enum_values(projection: Any) -> Dict[str, Any]:
    """``name → value`` for a type projection's enumerators."""
    listed = projection.get("enum_values") if isinstance(projection, Mapping) else None
    if not isinstance(listed, list):
        return {}
    return {str(v.get("name")): v.get("value") for v in listed if isinstance(v, Mapping)}


def _union_labels(projection: Any) -> List[str]:
    cases = _extras(projection).get("oncrpc_union_cases")
    if not isinstance(cases, list):
        return []
    return [str(c.get("label")) for c in cases if isinstance(c, Mapping)]


class OncRpcBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an ONC RPC diff by program, version and procedure numbers and XDR layout."""

    format = _FORMAT_KEY
    classifier_id = "oncrpc-procedure"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the ONC RPC rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The definition the diff starts from.
            target: The definition the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded: Optional[Tuple[Severity, str, str]] = None
        if change.category is EntityCategory.SERVICE:
            graded = self._grade_program(change)
        elif change.category is EntityCategory.OPERATION:
            graded = self._grade_procedure(change)
        elif change.category is EntityCategory.FIELD:
            graded = self._grade_field(change)
        elif change.category is EntityCategory.TYPE:
            graded = self._grade_type(change)
        if graded is None:
            return super().classify_change(change, base, target)
        severity, rule_id, rationale = graded
        return ChangeClassification(
            category=change.category,
            kind=change.kind,
            key=change.key,
            severity=severity,
            rule_id=rule_id,
            rationale=rationale,
        )

    @staticmethod
    def _grade_program(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """A program (service) whose number or version numbers moved."""
        if change.kind is not ChangeKind.MODIFIED:
            return None
        before, after = _extras(change.before), _extras(change.after)
        if "oncrpc_program_number" not in before and "oncrpc_program_number" not in after:
            return None
        if before.get("oncrpc_program_number") != after.get("oncrpc_program_number"):
            return (
                Severity.BREAKING,
                "oncrpc.program-renumbered",
                f"program {change.key!r} changed its number from {before.get('oncrpc_program_number')!r} "
                f"to {after.get('oncrpc_program_number')!r}; rpcbind routes callers on the old number "
                "to nothing",
            )
        old_versions = before.get("oncrpc_versions") if isinstance(before.get("oncrpc_versions"), Mapping) else {}
        new_versions = after.get("oncrpc_versions") if isinstance(after.get("oncrpc_versions"), Mapping) else {}
        for name in sorted(set(old_versions) | set(new_versions)):
            if name not in new_versions:
                return (
                    Severity.BREAKING,
                    "oncrpc.version-removed",
                    f"version {name} of program {change.key!r} was removed; callers on it get PROG_MISMATCH",
                )
            if name not in old_versions:
                continue
            if old_versions[name] != new_versions[name]:
                return (
                    Severity.BREAKING,
                    "oncrpc.version-renumbered",
                    f"version {name} of program {change.key!r} changed its number from "
                    f"{old_versions[name]!r} to {new_versions[name]!r}; callers on the old number "
                    "get PROG_MISMATCH",
                )
        if set(new_versions) - set(old_versions):
            added = ", ".join(sorted(set(new_versions) - set(old_versions)))
            return (
                Severity.SAFE,
                "oncrpc.version-added",
                f"program {change.key!r} gained version {added}; existing callers keep theirs",
            )
        return None

    @staticmethod
    def _grade_procedure(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """A procedure (operation) added, removed, renumbered or re-typed."""
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        if "oncrpc_procedure_number" not in _extras(projection):
            return None
        number = _extras(projection).get("oncrpc_procedure_number")
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "oncrpc.procedure-removed",
                f"procedure {change.key!r} (number {number}) was removed; callers get PROC_UNAVAIL",
            )
        if change.kind is ChangeKind.ADDED:
            return (
                Severity.SAFE,
                "oncrpc.procedure-added",
                f"procedure {change.key!r} (number {number}) was added; existing callers are unaffected",
            )
        before, after = _extras(change.before), _extras(change.after)
        if before.get("oncrpc_procedure_number") != after.get("oncrpc_procedure_number"):
            return (
                Severity.BREAKING,
                "oncrpc.procedure-renumbered",
                f"procedure {change.key!r} changed its number from {before.get('oncrpc_procedure_number')!r} "
                f"to {after.get('oncrpc_procedure_number')!r}; the wire carries the number",
            )
        if before.get("oncrpc_version_number") != after.get("oncrpc_version_number"):
            return (
                Severity.BREAKING,
                "oncrpc.version-renumbered",
                f"procedure {change.key!r} moved from version {before.get('oncrpc_version_number')!r} "
                f"to {after.get('oncrpc_version_number')!r}; callers on the old version get PROG_MISMATCH",
            )
        for attribute, label in (("oncrpc_arg_type", "argument"), ("oncrpc_return_type", "result")):
            if before.get(attribute) != after.get(attribute):
                return (
                    Severity.BREAKING,
                    "oncrpc.procedure-signature-changed",
                    f"procedure {change.key!r} changed its {label} type from {before.get(attribute)!r} "
                    f"to {after.get(attribute)!r}; the old encoding no longer decodes",
                )
        return None

    @staticmethod
    def _grade_field(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """A struct field added, removed, moved or re-typed."""
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        if "oncrpc_type_expr" not in _extras(projection):
            return None
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "oncrpc.field-removed",
                f"field {change.key!r} was removed; XDR is positional, so every field after it "
                "is cut from the wire at the wrong offset",
            )
        if change.kind is ChangeKind.ADDED:
            return (
                Severity.BREAKING,
                "oncrpc.field-added",
                f"field {change.key!r} was added; XDR is positional and carries no tags, so "
                "senders on the old definition omit it and the receiver misreads the struct",
            )
        moved = {field_change.field for field_change in change.fields}
        before, after = change.before or {}, change.after or {}
        if "field_number" in moved:
            return (
                Severity.BREAKING,
                "oncrpc.field-reordered",
                f"field {change.key!r} moved from position {before.get('field_number')!r} to "
                f"{after.get('field_number')!r}; it is cut from the wire at another offset",
            )
        old_expr, new_expr = _extras(before).get("oncrpc_type_expr"), _extras(after).get("oncrpc_type_expr")
        if old_expr == new_expr:
            return None
        old_shape, new_shape = type_shape(str(old_expr)), type_shape(str(new_expr))
        same_base = (
            old_shape["base"] == new_shape["base"]
            and old_shape["pointer"] == new_shape["pointer"]
            and old_shape["variable"] == new_shape["variable"]
            and old_shape["fixed"] == new_shape["fixed"]
        )
        if same_base and old_shape["variable"]:
            old_bound, new_bound = old_shape["bound"], new_shape["bound"]
            if new_bound is not None and (old_bound is None or new_bound < old_bound):
                return (
                    Severity.BREAKING,
                    "oncrpc.bound-narrowed",
                    f"field {change.key!r} narrowed its bound from {old_expr} to {new_expr}; "
                    "values senders on the old definition emit overflow it",
                )
            return (
                Severity.DANGEROUS,
                "oncrpc.bound-widened",
                f"field {change.key!r} widened its bound from {old_expr} to {new_expr}; receivers "
                "on the old definition reject the longer values",
            )
        return (
            Severity.BREAKING,
            "oncrpc.field-type-changed",
            f"field {change.key!r} changed its XDR type from {old_expr} to {new_expr}; the old "
            "encoding no longer decodes",
        )

    @staticmethod
    def _grade_type(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """A union whose arms or discriminant moved, or an enum whose enumerators moved."""
        if change.kind is not ChangeKind.MODIFIED:
            return None
        kind = _extras(change.before).get("oncrpc_kind")
        if kind == "union":
            before, after = _extras(change.before), _extras(change.after)
            if before.get("oncrpc_switch_type") != after.get("oncrpc_switch_type") or before.get(
                "oncrpc_switch_field"
            ) != after.get("oncrpc_switch_field"):
                return (
                    Severity.BREAKING,
                    "oncrpc.union-discriminant-changed",
                    f"union {change.key!r} changed its discriminant from "
                    f"{before.get('oncrpc_switch_type')} {before.get('oncrpc_switch_field')} to "
                    f"{after.get('oncrpc_switch_type')} {after.get('oncrpc_switch_field')}; "
                    "nothing on the old definition decodes",
                )
            old_arms, new_arms = _union_labels(change.before), _union_labels(change.after)
            removed = [arm for arm in old_arms if arm not in new_arms]
            if removed:
                return (
                    Severity.BREAKING,
                    "oncrpc.union-arm-removed",
                    f"union {change.key!r} lost the arm(s) {', '.join(removed)}; senders on the old "
                    "definition still emit that discriminant",
                )
            added = [arm for arm in new_arms if arm not in old_arms]
            if added:
                return (
                    Severity.DANGEROUS,
                    "oncrpc.union-arm-added",
                    f"union {change.key!r} gained the arm(s) {', '.join(added)}; a receiver on the old "
                    "definition without a default arm cannot decode them",
                )
            return None
        if kind == "enum":
            old_values, new_values = _enum_values(change.before), _enum_values(change.after)
            removed = sorted(set(old_values) - set(new_values))
            if removed:
                return (
                    Severity.BREAKING,
                    "oncrpc.enum-value-removed",
                    f"enum {change.key!r} lost {', '.join(removed)}; senders on the old definition "
                    "still emit it",
                )
            for name in sorted(set(old_values) & set(new_values)):
                if old_values[name] != new_values[name]:
                    return (
                        Severity.BREAKING,
                        "oncrpc.enum-value-renumbered",
                        f"enum {change.key!r} renumbered {name} from {old_values[name]!r} to "
                        f"{new_values[name]!r}; the wire carries the number",
                    )
            added = sorted(set(new_values) - set(old_values))
            if added:
                return (
                    Severity.SAFE,
                    "oncrpc.enum-value-added",
                    f"enum {change.key!r} gained {', '.join(added)}; existing values are unchanged",
                )
        return None
