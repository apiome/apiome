"""Shared helpers for wire-id breaking-change classifiers — MFI-19.4 (#3982).

FlatBuffers and Cap'n Proto, like Thrift (:mod:`app.thrift_breaking`), identify a field on the wire
by a **number**, not its name: a FlatBuffers table field by its id (``(id: N)`` or its position), a
Cap'n Proto member by its ``@N`` ordinal. The format-agnostic baseline pairs fields by name, so a
rename reads as a removal plus an addition and a reused number is invisible. These helpers pair the
two sides of a diff by number instead; :mod:`app.flatbuffers_breaking` and
:mod:`app.capnproto_breaking` grade the pairs with their format's rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .canonical_model import CanonicalApi, CanonicalField, Type, TypeKind
from .flatbuffers_identity import compact_field_ids

__all__ = [
    "NumberedField",
    "enum_value_changes",
    "flatbuffers_wire_ids",
    "id_counterpart",
    "is_enum",
    "numbered_field_index",
    "type_shape",
]


@dataclass(frozen=True)
class NumberedField:
    """A field with its owning type and its wire number.

    Attributes:
        type_key: The key of the record type the field belongs to.
        type_: That type.
        field: The field.
        wire_id: Its number on the wire, or ``None`` when it has none (a FlatBuffers struct).
    """

    type_key: str
    type_: Type
    field: CanonicalField
    wire_id: Optional[int]


def type_shape(field: CanonicalField) -> Any:
    """A field's type with nullability left out, for comparing two fields."""
    return field.type.model_dump(exclude={"nullable"})


def flatbuffers_wire_ids(type_: Type, union_keys: frozenset) -> Dict[str, int]:
    """The wire id of every field of a FlatBuffers table.

    The FlatBuffers normalizer keeps a field's id in ``extras["fbs_id"]`` only when it is not the
    compact id ``flatc`` would give it; otherwise the id follows from the field's position
    (``field_number``) among the table's fields, a union field taking two ids.

    Args:
        type_: A FlatBuffers table (or struct, which has no ids).
        union_keys: The keys of the schema's union types.

    Returns:
        ``{field key: wire id}``; empty for a struct.
    """
    if type_.extras.get("fbs_kind") != "table":
        return {}
    ordered = sorted(type_.fields, key=lambda f: (f.field_number or 0, f.key))
    widths = [2 if f.type.name in union_keys else 1 for f in ordered]
    compact = compact_field_ids(widths)
    ids: Dict[str, int] = {}
    for position, field in enumerate(ordered):
        explicit = field.extras.get("fbs_id")
        ids[field.key] = explicit if isinstance(explicit, int) else compact[position]
    return ids


def numbered_field_index(
    api: CanonicalApi, wire_ids: Callable[[Type, CanonicalApi], Mapping[str, Optional[int]]]
) -> Dict[str, NumberedField]:
    """Field key → :class:`NumberedField` for every field of ``api``.

    Args:
        api: The model.
        wire_ids: ``(type, api) → {field key: wire id}`` for one type.

    Returns:
        The index.
    """
    index: Dict[str, NumberedField] = {}
    for api_type in api.types:
        numbers = wire_ids(api_type, api)
        for field in api_type.fields:
            index[field.key] = NumberedField(api_type.key, api_type, field, numbers.get(field.key))
    return index


def id_counterpart(
    field_key: str,
    *,
    own: Mapping[str, NumberedField],
    other: Mapping[str, NumberedField],
) -> Tuple[Optional[NumberedField], Optional[NumberedField]]:
    """The field and, on the other side of the diff, a *different* field with its wire number.

    Args:
        field_key: The removed (or added) field's key.
        own: The index of the side the field is on.
        other: The index of the other side.

    Returns:
        ``(field, counterpart)``; the counterpart is a field of the same type with the same wire
        number whose key does not exist on ``own``'s side (it was added / removed too).
    """
    entry = own.get(field_key)
    if entry is None:
        return None, None
    if entry.wire_id is None:
        return entry, None
    for other_key, candidate in other.items():
        if (
            candidate.type_key == entry.type_key
            and candidate.wire_id == entry.wire_id
            and other_key != field_key
            and other_key not in own
        ):
            return entry, candidate
    return entry, None


def _enum_values(projection: Any) -> Dict[str, Any]:
    """``{name: value}`` of an enum type's self-projection (dict) or model."""
    if isinstance(projection, Type):
        return {value.name: value.value for value in projection.enum_values}
    values = (projection or {}).get("enum_values") if isinstance(projection, Mapping) else None
    out: Dict[str, Any] = {}
    for value in values or []:
        if isinstance(value, Mapping) and value.get("name") is not None:
            out[str(value["name"])] = value.get("value")
    return out


def enum_value_changes(before: Any, after: Any) -> Tuple[List[str], List[str]]:
    """The enum values whose number changed, and those removed.

    Args:
        before: The enum type before (a self-projection dict or a :class:`Type`).
        after: The enum type after.

    Returns:
        ``(changed names, removed names)``, each sorted.
    """
    old, new = _enum_values(before), _enum_values(after)
    changed = sorted(name for name in old if name in new and old[name] != new[name])
    removed = sorted(name for name in old if name not in new)
    return changed, removed


def is_enum(projection: Any) -> bool:
    """Whether a type self-projection (dict) or model is an enum."""
    if isinstance(projection, Type):
        return projection.kind is TypeKind.ENUM
    return isinstance(projection, Mapping) and projection.get("kind") in (TypeKind.ENUM, TypeKind.ENUM.value)
