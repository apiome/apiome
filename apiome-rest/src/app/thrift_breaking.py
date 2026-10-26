"""Apache Thrift breaking-change classifier — MFI-19.3 (#3981).

Thrift identifies a struct field on the wire by its **field id**, not its name. The
format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`)
pairs fields by name and grades every removal breaking, so it misreads the two changes a
Thrift reviewer cares most about:

* a field **renamed** with its id kept shows as a removal plus an addition — yet the binary
  and compact protocols still read old messages (only the JSON protocol and generated code
  see the new name);
* a field id **reused** for a field of another type looks like any other removal plus
  addition — yet an old peer would decode the new field's bytes as the old type.

This classifier pairs a removed and an added field of the same type by field id and grades
those cases, and applies Thrift's requiredness rules: a ``required`` field may never be added
or removed (a peer that lacks it throws), while an optional field can be removed safely as long
as its id is not reused. Everything else falls back to the baseline.

Rule ids (all ``thrift.*``):

=============================  ===========  ==============================================
Rule                           Severity     When
=============================  ===========  ==============================================
``thrift.field-renamed``       dangerous    same id and type, new name
``thrift.field-id-reused``     breaking     same id, a different type
``thrift.field-id-changed``    breaking     same name, a new id
``thrift.required-field-added``  breaking   a new ``required`` field
``thrift.optional-field-added``  safe       a new optional / default field
``thrift.required-field-removed`` breaking  a ``required`` field removed
``thrift.optional-field-removed`` dangerous an optional field removed, id not reused
``thrift.made-required``       breaking     an optional field became ``required``
``thrift.made-optional``       dangerous    a ``required`` field became optional
=============================  ===========  ==============================================
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi, CanonicalField
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["ThriftBreakingChangeClassifier"]

_FORMAT_KEY = "thrift"


def _field_index(api: CanonicalApi) -> Dict[str, Tuple[str, CanonicalField]]:
    """Field key → ``(owning type key, field)`` for every field of ``api``."""
    return {field.key: (api_type.key, field) for api_type in api.types for field in api_type.fields}


def _is_required(field: Any) -> bool:
    """Whether a field (model or self-projection dict) is declared ``required``."""
    extras = field.extras if isinstance(field, CanonicalField) else (field or {}).get("extras") or {}
    return extras.get("thrift_required") is True


def _type_shape(field: CanonicalField) -> Any:
    """A field's type with nullability (requiredness) left out, for comparing two fields."""
    return field.type.model_dump(exclude={"nullable"})


def _without_nullable(type_ref: Any) -> Any:
    """A ``TypeRef`` self-projection dict without its outer ``nullable``."""
    return {k: v for k, v in type_ref.items() if k != "nullable"} if isinstance(type_ref, dict) else type_ref


def _counterpart(
    field_key: str,
    *,
    own: Mapping[str, Tuple[str, CanonicalField]],
    other: Mapping[str, Tuple[str, CanonicalField]],
) -> Tuple[Optional[CanonicalField], Optional[CanonicalField]]:
    """The field and, on the other side of the diff, a *different* field with its id.

    Args:
        field_key: The removed (or added) field's key.
        own: The field index of the side the field is on.
        other: The field index of the other side.

    Returns:
        ``(field, counterpart)``; the counterpart is a field of the same type with the same
        field id whose key does not exist on ``own``'s side (it was added / removed too).
    """
    entry = own.get(field_key)
    if entry is None:
        return None, None
    type_key, field = entry
    if field.field_number is None:
        return field, None
    for other_key, (other_type, candidate) in other.items():
        if (
            other_type == type_key
            and candidate.field_number == field.field_number
            and other_key != field_key
            and other_key not in own
        ):
            return field, candidate
    return field, None


class ThriftBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a Thrift diff with field-id and requiredness rules (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "thrift-field-id"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; non-field changes and unmatched cases use the baseline."""
        graded = self._grade_field(change, base, target) if change.category is EntityCategory.FIELD else None
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

    def _grade_field(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Tuple[Severity, str, str]]:
        """``(severity, rule_id, rationale)`` for a field change, or ``None`` for the baseline."""
        base_fields, target_fields = _field_index(base), _field_index(target)
        if change.kind is ChangeKind.REMOVED:
            field, counterpart = _counterpart(change.key, own=base_fields, other=target_fields)
            return self._grade_pair(change.key, field, counterpart, removed=True)
        if change.kind is ChangeKind.ADDED:
            field, counterpart = _counterpart(change.key, own=target_fields, other=base_fields)
            return self._grade_pair(change.key, field, counterpart, removed=False)
        return self._grade_modified_field(change)

    @staticmethod
    def _grade_pair(
        key: str,
        field: Optional[CanonicalField],
        counterpart: Optional[CanonicalField],
        *,
        removed: bool,
    ) -> Optional[Tuple[Severity, str, str]]:
        """Grade a removed / added field, paired by id with its counterpart when it has one."""
        if field is None:
            return None
        field_id = field.field_number
        if counterpart is not None:
            old, new = (field, counterpart) if removed else (counterpart, field)
            if _type_shape(old) == _type_shape(new):
                return (
                    Severity.DANGEROUS,
                    "thrift.field-renamed",
                    f"field id {field_id} was renamed from {old.name!r} to {new.name!r}; the "
                    "binary and compact protocols still read it, the JSON protocol and "
                    "generated code do not",
                )
            return (
                Severity.BREAKING,
                "thrift.field-id-reused",
                f"field id {field_id} now carries {new.name!r} of another type than "
                f"{old.name!r}; peers on the old definition decode it wrongly",
            )
        required = _is_required(field)
        if removed:
            if required:
                return (
                    Severity.BREAKING,
                    "thrift.required-field-removed",
                    f"required field {key!r} (id {field_id}) was removed; peers on the old "
                    "definition reject messages without it",
                )
            return (
                Severity.DANGEROUS,
                "thrift.optional-field-removed",
                f"optional field {key!r} (id {field_id}) was removed; peers skip it, but its id "
                "must never be reused",
            )
        if required:
            return (
                Severity.BREAKING,
                "thrift.required-field-added",
                f"required field {key!r} (id {field_id}) was added; peers on the old "
                "definition never send it and the new side rejects their messages",
            )
        return (
            Severity.SAFE,
            "thrift.optional-field-added",
            f"optional field {key!r} (id {field_id}) was added; peers on the old definition "
            "skip it",
        )

    @staticmethod
    def _grade_modified_field(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """Grade an id move or a requiredness flip on a field kept under its name."""
        moved = {field_change.field: field_change for field_change in change.fields}
        if "field_number" in moved:
            number = moved["field_number"]
            return (
                Severity.BREAKING,
                "thrift.field-id-changed",
                f"field {change.key!r} moved from id {number.before} to id {number.after}; "
                "peers on the old definition no longer find it",
            )
        was_required, is_required = _is_required(change.before), _is_required(change.after)
        if was_required == is_required:
            return None
        # Only requiredness may have moved for these rules to speak for the whole change.
        if set(moved) - {"type", "extras"}:
            return None
        if "type" in moved and _without_nullable(moved["type"].before) != _without_nullable(moved["type"].after):
            return None
        if is_required:
            return (
                Severity.BREAKING,
                "thrift.made-required",
                f"field {change.key!r} became required; peers that omit it are rejected",
            )
        return (
            Severity.DANGEROUS,
            "thrift.made-optional",
            f"field {change.key!r} is no longer required; peers on the old definition still "
            "expect it",
        )
