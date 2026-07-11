"""Cap'n Proto ``.capnp`` → canonical model normalizer — MFI-14.2.

Maps a parsed :class:`~app.capnproto_parser.CapnpDocument` into a
:class:`~app.canonical_model.CanonicalApi`. Structs and enums become
:class:`~app.canonical_model.Type` entries; interface methods become
:class:`~app.canonical_model.Service` / :class:`~app.canonical_model.Operation` pairs
with Cap'n Proto slot numbers preserved on fields.
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
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .capnproto_parser import CapnpDocument, CapnpField
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["CapnpNormalizer"]

_FORMAT_KEY = "capnproto"

_CAPNP_BASE_TO_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "int8": "int8",
    "int16": "i16",
    "int32": "i32",
    "int64": "i64",
    "uint8": "uint8",
    "uint16": "uint16",
    "uint32": "uint32",
    "uint64": "uint64",
    "float32": "float",
    "float64": "double",
    "text": "string",
    "data": "bytes",
    "void": "void",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _short_name_aliases(qualified_names: frozenset[str]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for qual in qualified_names:
        short = qual.split(".")[-1]
        if short in aliases and aliases[short] != qual:
            aliases[short] = ""
        else:
            aliases[short] = qual
    return {k: v for k, v in aliases.items() if v}


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
    short_enum_names: Dict[str, str],
    short_struct_names: Dict[str, str],
) -> TypeRef:
    t = type_expr.strip()
    list_match = re.fullmatch(r"List\s*\(\s*([^)]+)\s*\)", t, re.IGNORECASE)
    if list_match:
        return TypeRef(
            item=_type_ref_from_expr(
                list_match.group(1),
                namespace=namespace,
                enum_names=enum_names,
                struct_names=struct_names,
                short_enum_names=short_enum_names,
                short_struct_names=short_struct_names,
            )
        )

    mapped = _CAPNP_BASE_TO_CANONICAL.get(t.lower())
    if mapped:
        return TypeRef(name=mapped)

    if t in enum_names or t in struct_names:
        return TypeRef(name=_type_key(t, namespace))

    short_enum = short_enum_names.get(t)
    if short_enum:
        return TypeRef(name=_type_key(short_enum, namespace))
    short_struct = short_struct_names.get(t)
    if short_struct:
        return TypeRef(name=_type_key(short_struct, namespace))

    short = t.split(".")[-1]
    if short in enum_names or short in struct_names:
        return TypeRef(name=_type_key(short, namespace))

    return TypeRef(name=t)


def _canonical_field(
    field: CapnpField,
    *,
    type_key: str,
    namespace: Optional[str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
    short_enum_names: Dict[str, str],
    short_struct_names: Dict[str, str],
) -> CanonicalField:
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=_type_ref_from_expr(
            field.type_expr,
            namespace=namespace,
            enum_names=enum_names,
            struct_names=struct_names,
            short_enum_names=short_enum_names,
            short_struct_names=short_struct_names,
        ),
        field_number=field.slot,
        extras={"capnp_slot": field.slot},
    )


class CapnpNormalizer(Normalizer, register=True):
    """Normalize a parsed Cap'n Proto document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, CapnpDocument):
            raise ValueError(
                "Cap'n Proto source must be a CapnpDocument "
                "(see app.capnproto_parser.parse_capnproto)"
            )

        namespace: Optional[str] = None
        enum_names = frozenset(e.qualified_name for e in source.enums)
        struct_names = frozenset(s.qualified_name for s in source.structs)
        short_enum_names = _short_name_aliases(enum_names)
        short_struct_names = _short_name_aliases(struct_names)

        types: List[Type] = []

        for enum in source.enums:
            type_key = _type_key(enum.qualified_name, namespace)
            values = [
                EnumValue(
                    key=Keys.enum_value(type_key, name),
                    name=name,
                    value=slot,
                )
                for name, slot in enum.values
            ]
            extras: Dict[str, Any] = {"capnp_kind": "enum"}
            if "." in enum.qualified_name:
                extras["capnp_qualified_name"] = enum.qualified_name
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

        for struct in source.structs:
            type_key = _type_key(struct.qualified_name, namespace)
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    enum_names=enum_names,
                    struct_names=struct_names,
                    short_enum_names=short_enum_names,
                    short_struct_names=short_struct_names,
                )
                for field in struct.fields
            ]
            extras = {"capnp_kind": "struct"}
            if "." in struct.qualified_name:
                extras["capnp_qualified_name"] = struct.qualified_name
            types.append(
                Type(
                    key=type_key,
                    name=struct.name,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    fields=fields,
                    extras=extras,
                )
            )

        services: List[Service] = []
        for iface in source.interfaces:
            service_key = Keys.type(iface.name, namespace)
            operations: List[Operation] = []
            for method in iface.methods:
                op_key = Keys.operation_rpc(service_key, method.name)
                messages: List[Message] = []
                if method.parameters:
                    if len(method.parameters) == 1:
                        param = method.parameters[0]
                        messages.append(
                            Message(
                                key=Keys.request_message(op_key),
                                role=MessageRole.REQUEST,
                                payload=_type_ref_from_expr(
                                    param.type_expr,
                                    namespace=namespace,
                                    enum_names=enum_names,
                                    struct_names=struct_names,
                                    short_enum_names=short_enum_names,
                                    short_struct_names=short_struct_names,
                                ),
                                required=True,
                                extras={"capnp_param_name": param.name},
                            )
                        )
                    else:
                        messages.append(
                            Message(
                                key=Keys.request_message(op_key),
                                role=MessageRole.REQUEST,
                                required=True,
                                extras={
                                    "capnp_parameters": [
                                        {
                                            "slot": p.slot,
                                            "name": p.name,
                                            "type": p.type_expr,
                                        }
                                        for p in method.parameters
                                    ]
                                },
                            )
                        )
                if method.results:
                    if len(method.results) == 1:
                        result = method.results[0]
                        messages.append(
                            Message(
                                key=f"{op_key}#response",
                                role=MessageRole.RESPONSE,
                                payload=_type_ref_from_expr(
                                    result.type_expr,
                                    namespace=namespace,
                                    enum_names=enum_names,
                                    struct_names=struct_names,
                                    short_enum_names=short_enum_names,
                                    short_struct_names=short_struct_names,
                                ),
                                extras={"capnp_result_name": result.name},
                            )
                        )
                    else:
                        messages.append(
                            Message(
                                key=f"{op_key}#response",
                                role=MessageRole.RESPONSE,
                                extras={
                                    "capnp_results": [
                                        {
                                            "slot": r.slot,
                                            "name": r.name,
                                            "type": r.type_expr,
                                        }
                                        for r in method.results
                                    ]
                                },
                            )
                        )
                operations.append(
                    Operation(
                        key=op_key,
                        name=method.name,
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        messages=messages,
                        extras={"capnp_slot": method.slot},
                    )
                )
            services.append(Service(key=service_key, name=iface.name, operations=operations))

        identity_name = (
            services[0].name
            if services
            else (source.structs[0].qualified_name if source.structs else "Cap'n Proto schema")
        )
        paradigm = ApiParadigm.RPC if services else ApiParadigm.DATA_SCHEMA
        api = CanonicalApi(
            paradigm=paradigm,
            format=self.format,
            identity=ApiIdentity(name=identity_name, namespace=namespace),
            services=services,
            types=types,
            raw={"capnproto": source.raw} if include_raw else None,
            extras={
                "capnp_file_id": source.file_id,
                "capnp_imports": list(source.imports),
            },
        )
        return normalize_ordering(api)
