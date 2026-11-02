"""FlatBuffers breaking-change classifier — MFI-19.4 (#3982).

A FlatBuffers **table** stores each field under its **id** — the ``(id: N)`` attribute, or else its
position among the table's fields (a union field takes two) — and a field is never removed, only
marked ``(deprecated)`` so its id stays taken. A **struct** is a fixed in-line layout with no ids at
all, so any change to it moves every byte after it. The format-agnostic baseline
(:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) pairs fields by name and knows none of
this; this classifier pairs table fields by id (:mod:`app.numbered_field_breaking`) and applies the
FlatBuffers schema-evolution rules. Everything else falls back to the baseline.

Rule ids (all ``fbs.*``):

==============================  ===========  ===============================================
Rule                            Severity     When
==============================  ===========  ===============================================
``fbs.field-renamed``           dangerous    same id and type, new name (JSON and generated
                                             code see the name; the binary does not)
``fbs.field-id-reused``         breaking     same id, a different type
``fbs.field-id-changed``        breaking     same name, a new id (a field inserted before it)
``fbs.field-id-unchanged``      safe         the field moved in the model, its id did not
``fbs.field-deprecated``        safe         a removed field whose id is now a deprecated slot
``fbs.field-removed``           breaking     removed without ``(deprecated)``: its id is free
                                             and, without explicit ids, every later id shifts
``fbs.field-added``             safe         a new field at an id no field had
``fbs.default-changed``         dangerous    the default changed: readers of a buffer that
                                             omits the field now see another value
``fbs.struct-changed``          breaking     a struct field added, removed or changed
``fbs.enum-value-changed``      breaking     an enum value's number changed
``fbs.enum-value-removed``      breaking     an enum value was removed
``fbs.union-member-removed``    breaking     a union member removed or reordered (members are
                                             numbered by position)
==============================  ===========  ===============================================
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi, Type, TypeKind
from .diff import ChangeKind, EntityCategory, EntityChange
from .numbered_field_breaking import (
    NumberedField,
    enum_value_changes,
    flatbuffers_wire_ids,
    id_counterpart,
    is_enum,
    numbered_field_index,
    type_shape,
)

__all__ = ["FlatBuffersBreakingChangeClassifier"]

_FORMAT_KEY = "flatbuffers"

Grade = Tuple[Severity, str, str]


def _wire_ids(type_: Type, api: CanonicalApi) -> Mapping[str, Optional[int]]:
    union_keys = frozenset(t.key for t in api.types if t.kind is TypeKind.UNION)
    return flatbuffers_wire_ids(type_, union_keys)


def _index(api: CanonicalApi) -> Dict[str, NumberedField]:
    return numbered_field_index(api, _wire_ids)


def _is_struct(entry: Optional[NumberedField]) -> bool:
    return entry is not None and entry.type_.extras.get("fbs_kind") == "struct"


def _deprecated_ids(type_: Optional[Type]) -> frozenset:
    """The ids a table keeps as ``(deprecated)`` slots."""
    if type_ is None:
        return frozenset()
    slots = type_.extras.get("fbs_deprecated") or {}
    return frozenset(int(key) for key in slots if str(key).lstrip("-").isdigit())


def _extras(projection: Any) -> Dict[str, Any]:
    if isinstance(projection, Type):
        return dict(projection.extras)
    return dict((projection or {}).get("extras") or {}) if isinstance(projection, Mapping) else {}


def _only_deprecated_slots_changed(change: EntityChange) -> bool:
    """Whether a type change is only new ``(deprecated)`` slots (old slots all kept)."""
    before, after = _extras(change.before), _extras(change.after)
    old_slots, new_slots = before.pop("fbs_deprecated", {}) or {}, after.pop("fbs_deprecated", {}) or {}
    return before == after and set(old_slots) < set(new_slots)


def _members(projection: Any) -> list:
    """A union type's members, from its self-projection (dict) or model."""
    if isinstance(projection, Type):
        return list(projection.union_members)
    return list((projection or {}).get("union_members") or []) if isinstance(projection, Mapping) else []


class FlatBuffersBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a FlatBuffers diff with the schema-evolution rules (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "flatbuffers-field-id"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; changes no rule speaks for use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.FIELD:
            graded = self._grade_field(change, base, target)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
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

    # -- fields -------------------------------------------------------------------------------

    def _grade_field(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
        base_fields, target_fields = _index(base), _index(target)
        if change.kind is ChangeKind.REMOVED:
            entry = base_fields.get(change.key)
            if _is_struct(entry):
                return self._struct_changed(change.key, "removed")
            entry, counterpart = id_counterpart(change.key, own=base_fields, other=target_fields)
            if counterpart is not None:
                return self._pair(entry, counterpart)
            if entry is None or entry.wire_id is None:
                return None
            new_type = next((t for t in target.types if t.key == entry.type_key), None)
            if entry.wire_id in _deprecated_ids(new_type):
                return (
                    Severity.SAFE,
                    "fbs.field-deprecated",
                    f"field {change.key!r} (id {entry.wire_id}) is now a deprecated slot; old "
                    "buffers still read, and its id stays taken",
                )
            return (
                Severity.BREAKING,
                "fbs.field-removed",
                f"field {change.key!r} (id {entry.wire_id}) was removed rather than marked "
                "(deprecated); its id is free for reuse and, without explicit ids, later fields "
                "move to other ids",
            )
        if change.kind is ChangeKind.ADDED:
            entry = target_fields.get(change.key)
            if _is_struct(entry):
                return self._struct_changed(change.key, "added")
            entry, counterpart = id_counterpart(change.key, own=target_fields, other=base_fields)
            if counterpart is not None:
                return self._pair(counterpart, entry)
            if entry is None or entry.wire_id is None:
                return None
            return (
                Severity.SAFE,
                "fbs.field-added",
                f"field {change.key!r} was added at id {entry.wire_id}; old readers skip it",
            )
        return self._grade_modified_field(change, base_fields.get(change.key), target_fields.get(change.key))

    @staticmethod
    def _struct_changed(key: str, how: str) -> Grade:
        return (
            Severity.BREAKING,
            "fbs.struct-changed",
            f"struct field {key!r} was {how}; a struct is a fixed in-line layout, so every buffer "
            "written with the old definition is read wrongly",
        )

    @staticmethod
    def _pair(old: Optional[NumberedField], new: Optional[NumberedField]) -> Optional[Grade]:
        """Grade a removed field and an added one that share an id."""
        if old is None or new is None:
            return None
        if type_shape(old.field) == type_shape(new.field):
            return (
                Severity.DANGEROUS,
                "fbs.field-renamed",
                f"field id {old.wire_id} was renamed from {old.field.name!r} to {new.field.name!r}; "
                "binary buffers still read, JSON and generated code do not",
            )
        return (
            Severity.BREAKING,
            "fbs.field-id-reused",
            f"field id {old.wire_id} now carries {new.field.name!r} of another type than "
            f"{old.field.name!r}; old buffers are decoded as the wrong type",
        )

    def _grade_modified_field(
        self, change: EntityChange, before: Optional[NumberedField], after: Optional[NumberedField]
    ) -> Optional[Grade]:
        moved = {field_change.field for field_change in change.fields}
        if _is_struct(before) or _is_struct(after):
            return self._struct_changed(change.key, "changed")
        if before is not None and after is not None and before.wire_id != after.wire_id:
            return (
                Severity.BREAKING,
                "fbs.field-id-changed",
                f"field {change.key!r} moved from id {before.wire_id} to id {after.wire_id}; old "
                "buffers hold another field (or nothing) at its new id",
            )
        default_moved = "default" in moved or (
            before is not None and after is not None
            and before.field.extras.get("fbs_default") != after.field.extras.get("fbs_default")
        )
        if default_moved and moved <= {"default", "extras"}:
            return (
                Severity.DANGEROUS,
                "fbs.default-changed",
                f"field {change.key!r} changed its default; readers of a buffer that omits the "
                "field now see another value",
            )
        if moved and moved <= {"field_number", "extras"}:
            return (
                Severity.SAFE,
                "fbs.field-id-unchanged",
                f"field {change.key!r} moved in the table but kept its id; nothing changes on the wire",
            )
        return None

    # -- enums and unions ---------------------------------------------------------------------

    @staticmethod
    def _grade_type(change: EntityChange) -> Optional[Grade]:
        moved = {field_change.field for field_change in change.fields}
        if moved == {"extras"} and _only_deprecated_slots_changed(change):
            return (
                Severity.SAFE,
                "fbs.field-deprecated",
                f"table {change.key!r} gained deprecated slots; their ids stay taken",
            )
        if is_enum(change.before) and "enum_values" in moved:
            changed, removed = enum_value_changes(change.before, change.after)
            if removed:
                return (
                    Severity.BREAKING,
                    "fbs.enum-value-removed",
                    f"enum {change.key!r} lost {', '.join(removed)}; buffers holding "
                    f"{'it' if len(removed) == 1 else 'them'} no longer read as a known value",
                )
            if changed:
                return (
                    Severity.BREAKING,
                    "fbs.enum-value-changed",
                    f"enum {change.key!r} renumbered {', '.join(changed)}; old buffers read as "
                    "another value",
                )
            return None
        if "union_members" in moved:
            old, new = _members(change.before), _members(change.after)
            if new[: len(old)] != old:
                return (
                    Severity.BREAKING,
                    "fbs.union-member-removed",
                    f"union {change.key!r} lost or reordered members; a union member is numbered "
                    "by its position, so old buffers decode as another member",
                )
        return None
