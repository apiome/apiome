"""FlatBuffers ``.fbs`` → canonical model normalizer — MFI-13.2.

Maps a parsed :class:`~app.flatbuffers_parser.FlatBuffersDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`. ``table`` / ``struct`` / ``union`` and
``enum`` definitions become :class:`~app.canonical_model.Type` entries with declaration-order
field numbers preserved on :class:`~app.canonical_model.CanonicalField.field_number`.

Field ids (MFX-30.1): a ``(deprecated)`` field is a slot kept only for its id, so it is not a field of
the model; a table records ``{id: name}`` of those in ``extras["fbs_deprecated"]``. A field whose id is
not the one its position implies (``(id: N)`` out of order, or after a deprecated slot) keeps it in
``extras["fbs_id"]``, so the FlatBuffers export writes the same ids.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .flatbuffers_identity import compact_field_ids
from .flatbuffers_parser import FbsField, FbsTypeDef, FlatBuffersDocument
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["FlatBuffersNormalizer"]

_FORMAT_KEY = "flatbuffers"

_FBS_BASE_TO_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "byte": "int8",
    "ubyte": "uint8",
    "short": "i16",
    "ushort": "uint16",
    "int": "i32",
    "uint": "uint32",
    "long": "i64",
    "ulong": "uint64",
    "float": "float",
    "double": "double",
    "string": "string",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    enum_names: frozenset[str],
    type_names: frozenset[str],
) -> TypeRef:
    t = type_expr.strip()
    vector_match = re.fullmatch(r"\[([\w.]+)\]", t)
    if vector_match:
        inner = vector_match.group(1)
        return TypeRef(
            item=_type_ref_from_expr(
                inner,
                namespace=namespace,
                enum_names=enum_names,
                type_names=type_names,
            )
        )

    base = _FBS_BASE_TO_CANONICAL.get(t)
    if base:
        return TypeRef(name=base)

    if t in enum_names or t in type_names:
        return TypeRef(name=_type_key(t, namespace))

    return TypeRef(name=t)


def _canonical_field(
    field: FbsField,
    *,
    type_key: str,
    namespace: Optional[str],
    enum_names: frozenset[str],
    type_names: frozenset[str],
    field_number: int,
    field_id: Optional[int] = None,
) -> CanonicalField:
    extras: Dict[str, Any] = {}
    if field.default is not None:
        extras["fbs_default"] = field.default
    if field_id is not None:
        extras["fbs_id"] = field_id
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=_type_ref_from_expr(
            field.type_expr,
            namespace=namespace,
            enum_names=enum_names,
            type_names=type_names,
        ),
        field_number=field_number,
        default=field.default,
        extras=extras,
    )


class FlatBuffersNormalizer(Normalizer, register=True):
    """Normalize a parsed FlatBuffers document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, FlatBuffersDocument):
            raise ValueError(
                "FlatBuffers source must be a FlatBuffersDocument "
                "(see app.flatbuffers_parser.parse_flatbuffers)"
            )

        namespace = source.namespace
        enum_names = frozenset(e.name for e in source.enums)
        type_names = frozenset(t.name for t in source.types)

        types: List[Type] = []

        for enum in source.enums:
            type_key = _type_key(enum.name, namespace)
            values = [
                EnumValue(
                    key=Keys.enum_value(type_key, name),
                    name=name,
                    value=number if number is not None else index,
                )
                for index, (name, number) in enumerate(enum.values)
            ]
            extras: Dict[str, Any] = {"fbs_kind": "enum"}
            if enum.base_type:
                extras["fbs_base_type"] = enum.base_type
            types.append(
                Type(
                    key=type_key,
                    name=enum.name,
                    kind=TypeKind.ENUM,
                    namespace=namespace,
                    enum_values=values,
                    extras=extras,
                )
            )

        for typedef in source.types:
            type_key = _type_key(typedef.name, namespace)
            if typedef.kind == "union":
                members = [_type_key(field.name, namespace) for field in typedef.fields]
                types.append(
                    Type(
                        key=type_key,
                        name=typedef.name,
                        kind=TypeKind.UNION,
                        namespace=namespace,
                        union_members=members,
                        extras={"fbs_kind": "union"},
                    )
                )
                continue

            union_names = frozenset(t.name for t in source.types if t.kind == "union")
            kept, moved_ids, deprecated = _field_ids(typedef, union_names)
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    enum_names=enum_names,
                    type_names=type_names,
                    field_number=index + 1,
                    field_id=moved_ids.get(index),
                )
                for index, field in enumerate(kept)
            ]
            type_extras: Dict[str, Any] = {"fbs_kind": typedef.kind}
            if deprecated:
                type_extras["fbs_deprecated"] = deprecated
            types.append(
                Type(
                    key=type_key,
                    name=typedef.name,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    fields=fields,
                    extras=type_extras,
                )
            )

        identity_name = namespace or source.root_type or (
            types[0].name if types else "FlatBuffers schema"
        )
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=identity_name, namespace=namespace),
            types=types,
            raw={"flatbuffers": source.raw} if include_raw else None,
            extras={
                "fbs_root_type": source.root_type,
                "fbs_includes": list(source.includes),
            },
        )
        return normalize_ordering(api)


def _field_ids(
    typedef: FbsTypeDef, union_names: frozenset[str]
) -> tuple[List[FbsField], Dict[int, int], Dict[str, str]]:
    """Split a table's fields into the model's and its deprecated slots, keeping ids that move.

    Args:
        typedef: The parsed table or struct.
        union_names: Names of the schema's unions (a union field takes two ids).

    Returns:
        ``(kept fields, {kept index: id} for each field whose id is not the compact one,
        {"<id>": name} of the deprecated slots)``. A struct has no ids: everything is kept as is.
    """
    if typedef.kind != "table":
        return list(typedef.fields), {}, {}
    widths = [2 if f.type_expr in union_names else 1 for f in typedef.fields]
    implied = compact_field_ids(widths)
    actual = [f.field_id if f.field_id is not None else implied[i] for i, f in enumerate(typedef.fields)]
    kept = [i for i, f in enumerate(typedef.fields) if not f.deprecated]
    compact = compact_field_ids([widths[i] for i in kept])
    moved = {n: actual[i] for n, i in enumerate(kept) if actual[i] != compact[n]}
    deprecated = {str(actual[i]): f.name for i, f in enumerate(typedef.fields) if f.deprecated}
    return [typedef.fields[i] for i in kept], moved, deprecated
