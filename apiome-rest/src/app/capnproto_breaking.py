"""Cap'n Proto breaking-change classifier — MFI-19.4 (#3982).

Cap'n Proto identifies every struct field, interface method and enumerant by its ``@N``
**ordinal**; names never reach the wire. Its evolution rules follow: a member may be **renamed**
freely, a new member may be **added** at the next ordinal, but a member may never be **removed** or
**renumbered** — the schema keeps an obsolete member (renamed, say, ``obsoleteName``) instead. The
format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) pairs by
name, so it grades a harmless rename as a breaking removal; this classifier pairs by ordinal
(:mod:`app.numbered_field_breaking`). Everything else falls back to the baseline.

Rule ids (all ``capnp.*``):

==============================  ===========  ===============================================
Rule                            Severity     When
==============================  ===========  ===============================================
``capnp.field-renamed``         safe         same ordinal and type, new name
``capnp.method-renamed``        safe         same ordinal and signature, new name (its request
                                             and response messages move with it)
``capnp.ordinal-reused``        breaking     same ordinal, a different type or signature
``capnp.ordinal-changed``       breaking     same name, a new ordinal
``capnp.field-removed``         breaking     a field removed
``capnp.method-removed``        breaking     a method removed
``capnp.field-added``           safe         a new field at an ordinal no field had
``capnp.method-added``          safe         a new method at an ordinal no method had
``capnp.enum-value-changed``    breaking     an enumerant's ordinal changed
``capnp.enum-value-removed``    breaking     an enumerant removed
==============================  ===========  ===============================================
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi, Operation, Type
from .diff import ChangeKind, EntityCategory, EntityChange
from .numbered_field_breaking import (
    NumberedField,
    enum_value_changes,
    id_counterpart,
    is_enum,
    numbered_field_index,
    type_shape,
)

__all__ = ["CapnProtoBreakingChangeClassifier"]

_FORMAT_KEY = "capnproto"

Grade = Tuple[Severity, str, str]


def _field_ordinals(type_: Type, _api: CanonicalApi) -> Mapping[str, Optional[int]]:
    return {field.key: field.field_number for field in type_.fields}


def _fields(api: CanonicalApi) -> Dict[str, NumberedField]:
    return numbered_field_index(api, _field_ordinals)


def _operations(api: CanonicalApi) -> Dict[str, Tuple[str, Operation]]:
    """Operation key → ``(service key, operation)``."""
    return {op.key: (service.key, op) for service in api.services for op in service.operations}


def _ordinal(op: Operation) -> Optional[int]:
    slot = op.extras.get("capnp_slot")
    return slot if isinstance(slot, int) else None


def _signature(op: Operation) -> Any:
    """What a method sends and returns, without the keys its name is part of."""
    return [
        (m.role.value, m.payload.model_dump(exclude={"nullable"}) if m.payload else None, m.extras)
        for m in sorted(op.messages, key=lambda m: m.role.value)
    ]


def _method_counterpart(
    op_key: str, *, own: Mapping[str, Tuple[str, Operation]], other: Mapping[str, Tuple[str, Operation]]
) -> Tuple[Optional[Operation], Optional[Operation]]:
    """The method and, on the other side, a *different* method of the same interface and ordinal."""
    entry = own.get(op_key)
    if entry is None:
        return None, None
    service_key, op = entry
    ordinal = _ordinal(op)
    if ordinal is None:
        return op, None
    for other_key, (other_service, candidate) in other.items():
        same_slot = other_service == service_key and _ordinal(candidate) == ordinal
        if same_slot and other_key != op_key and other_key not in own:
            return op, candidate
    return op, None


class CapnProtoBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a Cap'n Proto diff by ordinal (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "capnproto-ordinal"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; changes no rule speaks for use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.FIELD:
            graded = self._grade_field(change, base, target)
        elif change.category is EntityCategory.OPERATION:
            graded = self._grade_method(change, base, target)
        elif change.category is EntityCategory.MESSAGE and change.kind is not ChangeKind.MODIFIED:
            graded = self._grade_renamed_methods_message(change, base, target)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            graded = self._grade_enum(change)
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

    # -- fields -------------------------------------------------------------------------------

    @staticmethod
    def _grade_field(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
        base_fields, target_fields = _fields(base), _fields(target)
        if change.kind in (ChangeKind.REMOVED, ChangeKind.ADDED):
            removed = change.kind is ChangeKind.REMOVED
            own, other = (base_fields, target_fields) if removed else (target_fields, base_fields)
            entry, counterpart = id_counterpart(change.key, own=own, other=other)
            if entry is None:
                return None
            if counterpart is not None:
                old, new = (entry, counterpart) if removed else (counterpart, entry)
                if type_shape(old.field) == type_shape(new.field):
                    return (
                        Severity.SAFE,
                        "capnp.field-renamed",
                        f"field @{old.wire_id} was renamed from {old.field.name!r} to "
                        f"{new.field.name!r}; names are not on the wire",
                    )
                return (
                    Severity.BREAKING,
                    "capnp.ordinal-reused",
                    f"ordinal @{old.wire_id} now carries {new.field.name!r} of another type than "
                    f"{old.field.name!r}; old messages are read as the wrong type",
                )
            if removed:
                return (
                    Severity.BREAKING,
                    "capnp.field-removed",
                    f"field {change.key!r} (@{entry.wire_id}) was removed; Cap'n Proto never removes "
                    "a field — keep it and rename it (obsolete…) instead",
                )
            return (
                Severity.SAFE,
                "capnp.field-added",
                f"field {change.key!r} was added at @{entry.wire_id}; old readers ignore it",
            )
        before, after = base_fields.get(change.key), target_fields.get(change.key)
        if before is not None and after is not None and before.wire_id != after.wire_id:
            return (
                Severity.BREAKING,
                "capnp.ordinal-changed",
                f"field {change.key!r} moved from @{before.wire_id} to @{after.wire_id}; old "
                "messages hold another field (or nothing) at its new ordinal",
            )
        return None

    # -- methods ------------------------------------------------------------------------------

    @staticmethod
    def _grade_method(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
        base_ops, target_ops = _operations(base), _operations(target)
        if change.kind in (ChangeKind.REMOVED, ChangeKind.ADDED):
            removed = change.kind is ChangeKind.REMOVED
            own, other = (base_ops, target_ops) if removed else (target_ops, base_ops)
            op, counterpart = _method_counterpart(change.key, own=own, other=other)
            if op is None or _ordinal(op) is None:
                return None
            if counterpart is not None:
                old, new = (op, counterpart) if removed else (counterpart, op)
                if _signature(old) == _signature(new):
                    return (
                        Severity.SAFE,
                        "capnp.method-renamed",
                        f"method @{_ordinal(old)} was renamed from {old.name!r} to {new.name!r}; "
                        "names are not on the wire",
                    )
                return (
                    Severity.BREAKING,
                    "capnp.ordinal-reused",
                    f"method ordinal @{_ordinal(old)} now carries {new.name!r} with another "
                    f"signature than {old.name!r}; old callers send the wrong parameters",
                )
            if removed:
                return (
                    Severity.BREAKING,
                    "capnp.method-removed",
                    f"method {op.name!r} (@{_ordinal(op)}) was removed; callers on the old schema "
                    "get an unimplemented-method error",
                )
            return (
                Severity.SAFE,
                "capnp.method-added",
                f"method {op.name!r} was added at @{_ordinal(op)}",
            )
        before, after = base_ops.get(change.key), target_ops.get(change.key)
        if before is not None and after is not None and _ordinal(before[1]) != _ordinal(after[1]):
            return (
                Severity.BREAKING,
                "capnp.ordinal-changed",
                f"method {change.key!r} moved from @{_ordinal(before[1])} to @{_ordinal(after[1])}; "
                "old callers invoke another method",
            )
        return None

    @staticmethod
    def _grade_renamed_methods_message(
        change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Grade]:
        """A renamed method's request / response move to new keys; that is the rename, not a removal."""
        op_key = change.key.split("#", 1)[0]
        base_ops, target_ops = _operations(base), _operations(target)
        removed = change.kind is ChangeKind.REMOVED
        own, other = (base_ops, target_ops) if removed else (target_ops, base_ops)
        if op_key in other:
            return None
        op, counterpart = _method_counterpart(op_key, own=own, other=other)
        if op is None or counterpart is None:
            return None
        old, new = (op, counterpart) if removed else (counterpart, op)
        if _signature(old) != _signature(new):
            return None
        return (
            Severity.SAFE,
            "capnp.method-renamed",
            f"a message of method @{_ordinal(old)}, renamed from {old.name!r} to {new.name!r}",
        )

    # -- enums --------------------------------------------------------------------------------

    @staticmethod
    def _grade_enum(change: EntityChange) -> Optional[Grade]:
        moved = {field_change.field for field_change in change.fields}
        if not is_enum(change.before) or "enum_values" not in moved:
            return None
        changed, removed = enum_value_changes(change.before, change.after)
        if removed:
            return (
                Severity.BREAKING,
                "capnp.enum-value-removed",
                f"enum {change.key!r} lost {', '.join(removed)}; Cap'n Proto never removes an "
                "enumerant — keep it and rename it instead",
            )
        if changed:
            return (
                Severity.BREAKING,
                "capnp.enum-value-changed",
                f"enum {change.key!r} renumbered {', '.join(changed)}; old messages read as "
                "another value",
            )
        return None
