"""Avro → canonical model normalizer — MFI-19.2.

Maps a parsed :class:`~app.avro_parser.AvroDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .avro_parser import AvroDocument, AvroNamedSchema
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["AvroNormalizer"]

_FORMAT_KEY = "avro"

_AVRO_TO_CANONICAL: Dict[str, str] = {
    "null": "null",
    "boolean": "bool",
    "int": "integer",
    "long": "int64",
    "float": "float",
    "double": "double",
    "bytes": "bytes",
    "string": "string",
}

_LOGICAL_TO_FORMAT: Dict[str, str] = {
    "date": "date",
    "time-millis": "time",
    "time-micros": "time",
    "timestamp-millis": "date-time",
    "timestamp-micros": "date-time",
    "local-timestamp-millis": "date-time",
    "uuid": "uuid",
    "decimal": "decimal",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _qualified_name(name: str, namespace: Optional[str]) -> str:
    return f"{namespace}.{name}" if namespace else name


def _resolve_named_key(name: str, namespace: Optional[str], known: frozenset[str]) -> str:
    if name in known:
        return name
    if "." in name:
        return name
    qualified = _qualified_name(name, namespace)
    if qualified in known:
        return qualified
    return _type_key(name, namespace)


def _constraints_from_logical(logical_type: str) -> Optional[Constraints]:
    fmt = _LOGICAL_TO_FORMAT.get(logical_type)
    return Constraints(format=fmt) if fmt else None


def _type_ref_from_avro(
    schema: Any,
    *,
    namespace: Optional[str],
    known_types: frozenset[str],
    union_types: Dict[str, Type],
) -> TypeRef:
    if isinstance(schema, list):
        branches = list(schema)
        nullable = "null" in branches
        non_null = [branch for branch in branches if branch != "null"]
        if len(non_null) == 1:
            inner = _type_ref_from_avro(
                non_null[0],
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            )
            return TypeRef(
                name=inner.name,
                item=inner.item,
                nullable=nullable if nullable else False,
            )
        members: List[str] = []
        for branch in branches:
            if branch == "null":
                members.append("null")
                continue
            if isinstance(branch, str) and branch in _AVRO_TO_CANONICAL:
                members.append(_AVRO_TO_CANONICAL[branch])
                continue
            if isinstance(branch, dict):
                branch_name = branch.get("name")
                branch_ns = branch.get("namespace") or namespace
                branch_type = branch.get("type")
                if branch_type in {"record", "enum", "fixed"} and isinstance(branch_name, str):
                    members.append(_resolve_named_key(branch_name, branch_ns, known_types))
                    continue
            members.append("string")
        union_key = _type_key("Union_" + "_".join(m.replace(".", "_") for m in members), namespace)
        if union_key not in union_types:
            union_types[union_key] = Type(
                key=union_key,
                name=union_key.rsplit(".", 1)[-1],
                kind=TypeKind.UNION,
                namespace=namespace,
                union_members=members,
                extras={"avro_kind": "union"},
            )
        return TypeRef(name=union_key, nullable=nullable if nullable else False)

    if isinstance(schema, str):
        mapped = _AVRO_TO_CANONICAL.get(schema)
        if mapped:
            return TypeRef(name=mapped, nullable=False)
        return TypeRef(name=_resolve_named_key(schema, namespace, known_types), nullable=False)

    if not isinstance(schema, dict):
        return TypeRef(name="string", nullable=False)

    schema_type = schema.get("type")
    logical_type = schema.get("logicalType")

    if schema_type == "array":
        return TypeRef(
            item=_type_ref_from_avro(
                schema.get("items"),
                namespace=namespace,
                known_types=known_types,
                union_types=union_types,
            ),
            nullable=False,
        )

    if schema_type == "map":
        map_key = _type_key(
            f"Map_{schema.get('values', 'string')}".replace(".", "_"),
            namespace,
        )
        if map_key not in union_types:
            union_types[map_key] = Type(
                key=map_key,
                name=map_key.rsplit(".", 1)[-1],
                kind=TypeKind.MAP,
                namespace=namespace,
                value_type=_type_ref_from_avro(
                    schema.get("values"),
                    namespace=namespace,
                    known_types=known_types,
                    union_types=union_types,
                ),
                extras={"avro_kind": "map"},
            )
        return TypeRef(name=map_key, nullable=False)

    if schema_type in {"record", "enum", "fixed"}:
        name = schema.get("name")
        if isinstance(name, str):
            return TypeRef(
                name=_resolve_named_key(name, schema.get("namespace") or namespace, known_types),
                nullable=False,
            )

    if schema_type in _AVRO_TO_CANONICAL:
        return TypeRef(name=_AVRO_TO_CANONICAL[schema_type], nullable=False)

    return TypeRef(name="string", nullable=False)


def _field_constraints_and_extras(field_type: Any) -> Tuple[Optional[Constraints], Dict[str, Any]]:
    if not isinstance(field_type, dict):
        return None, {}
    logical_type = field_type.get("logicalType")
    if not isinstance(logical_type, str):
        return None, {}
    extras: Dict[str, Any] = {"logicalType": logical_type}
    schema_type = field_type.get("type")
    if isinstance(schema_type, str):
        extras["avro_type"] = schema_type
    if logical_type == "decimal":
        if isinstance(field_type.get("precision"), int):
            extras["precision"] = field_type["precision"]
        if isinstance(field_type.get("scale"), int):
            extras["scale"] = field_type["scale"]
    return _constraints_from_logical(logical_type), extras


def _canonical_field(
    field_schema: Dict[str, Any],
    *,
    type_key: str,
    namespace: Optional[str],
    known_types: frozenset[str],
    union_types: Dict[str, Type],
    field_number: int,
) -> CanonicalField:
    name = str(field_schema.get("name"))
    field_type = field_schema.get("type")
    type_ref = _type_ref_from_avro(
        field_type,
        namespace=namespace,
        known_types=known_types,
        union_types=union_types,
    )
    constraints, logical_extras = _field_constraints_and_extras(field_type)
    if constraints is not None and constraints.format in {"date", "date-time", "time", "uuid"}:
        type_ref = TypeRef(name="string", nullable=type_ref.nullable, item=type_ref.item)
    default = field_schema.get("default") if "default" in field_schema else None
    extras: Dict[str, Any] = dict(logical_extras)
    if "default" in field_schema:
        extras["has_default"] = True
    return CanonicalField(
        key=Keys.field(type_key, name),
        name=name,
        type=type_ref,
        field_number=field_number,
        default=default,
        constraints=constraints,
        description=field_schema.get("doc") if isinstance(field_schema.get("doc"), str) else None,
        extras=extras,
    )


def _canonical_type(
    named: AvroNamedSchema,
    *,
    known_types: frozenset[str],
    union_types: Dict[str, Type],
) -> Type:
    schema = named.schema
    type_key = _type_key(named.name, named.namespace)
    schema_type = schema.get("type")
    description = schema.get("doc") if isinstance(schema.get("doc"), str) else None

    if schema_type == "enum":
        symbols = schema.get("symbols") or []
        return Type(
            key=type_key,
            name=named.name,
            kind=TypeKind.ENUM,
            namespace=named.namespace,
            description=description,
            enum_values=[
                EnumValue(key=Keys.enum_value(type_key, symbol), name=str(symbol), value=index)
                for index, symbol in enumerate(symbols)
            ],
            extras={"avro_kind": "enum"},
        )

    if schema_type == "fixed":
        return Type(
            key=type_key,
            name=named.name,
            kind=TypeKind.SCALAR,
            namespace=named.namespace,
            description=description,
            extras={
                "avro_kind": "fixed",
                "avro_type": "fixed",
                "avro_size": schema.get("size"),
            },
        )

    fields = [
        _canonical_field(
            field,
            type_key=type_key,
            namespace=named.namespace,
            known_types=known_types,
            union_types=union_types,
            field_number=index + 1,
        )
        for index, field in enumerate(schema.get("fields") or [])
        if isinstance(field, dict) and field.get("name")
    ]
    return Type(
        key=type_key,
        name=named.name,
        kind=TypeKind.RECORD,
        namespace=named.namespace,
        description=description,
        fields=fields,
        extras={"avro_kind": "record"},
    )


class AvroNormalizer(Normalizer, register=True):
    """Normalize a parsed Avro document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, AvroDocument):
            raise ValueError("Avro source must be an AvroDocument (see app.avro_parser.parse_avro)")

        known_types = frozenset(
            _qualified_name(named.name, named.namespace) for named in source.types
        )
        union_types: Dict[str, Type] = {}
        types: List[Type] = [
            _canonical_type(named, known_types=known_types, union_types=union_types)
            for named in source.types
        ]
        types.extend(union_types.values())

        root = source.root
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=root.name, namespace=root.namespace),
            title=root.name,
            description=root.schema.get("doc") if isinstance(root.schema.get("doc"), str) else None,
            types=types,
            raw={"avro": source.raw} if include_raw else None,
            extras={
                "avro_root": _qualified_name(root.name, root.namespace),
            },
        )
        return normalize_ordering(api)
