"""Apache Thrift IDL → canonical model normalizer — MFI-11.2.

Maps a parsed :class:`~app.thrift_parser.ThriftDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`. Structs, unions, exceptions and enums become
:class:`~app.canonical_model.Type` definitions; service methods become
:class:`~app.canonical_model.Service` / :class:`~app.canonical_model.Operation` pairs with
field numbers preserved on :class:`~app.canonical_model.CanonicalField.field_number`.
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
from .normalizer import Keys, Normalizer, normalize_ordering
from .thrift_parser import ThriftDocument, ThriftField

__all__ = ["ThriftNormalizer"]

_FORMAT_KEY = "thrift"

_THRIFT_BASE_TO_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "byte": "int8",
    "i8": "int8",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "double": "double",
    "string": "string",
    "binary": "bytes",
    "uuid": "uuid",
}


def _primary_namespace(document: ThriftDocument) -> Optional[str]:
    if not document.namespaces:
        return None
    # Prefer a stable language key when present.
    for lang in ("java", "py", "go", "cpp", "rb"):
        if lang in document.namespaces:
            return document.namespaces[lang]
    return next(iter(document.namespaces.values()))


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
    map_types: Dict[str, Type],
) -> TypeRef:
    t = type_expr.strip()
    base = _THRIFT_BASE_TO_CANONICAL.get(t)
    if base:
        return TypeRef(name=base)

    list_match = re.fullmatch(r"list\s*<\s*([\w.<>,]+)\s*>", t)
    if list_match:
        return TypeRef(
            item=_type_ref_from_expr(
                list_match.group(1),
                namespace=namespace,
                enum_names=enum_names,
                struct_names=struct_names,
                map_types=map_types,
            )
        )

    set_match = re.fullmatch(r"set\s*<\s*([\w.<>,]+)\s*>", t)
    if set_match:
        return TypeRef(
            item=_type_ref_from_expr(
                set_match.group(1),
                namespace=namespace,
                enum_names=enum_names,
                struct_names=struct_names,
                map_types=map_types,
            ),
            extras={"thrift_container": "set"},
        )

    map_match = re.fullmatch(r"map\s*<\s*([\w.<>,]+)\s*,\s*([\w.<>,]+)\s*>", t)
    if map_match:
        key_expr = map_match.group(1).strip()
        value_expr = map_match.group(2).strip()
        map_key = f"map<{key_expr},{value_expr}>"
        if map_key not in map_types:
            map_types[map_key] = Type(
                key=Keys.type(map_key.replace("<", "_").replace(">", "_").replace(",", "_"), namespace),
                name=map_key,
                kind=TypeKind.MAP,
                key_type=_type_ref_from_expr(
                    key_expr,
                    namespace=namespace,
                    enum_names=enum_names,
                    struct_names=struct_names,
                    map_types=map_types,
                ),
                value_type=_type_ref_from_expr(
                    value_expr,
                    namespace=namespace,
                    enum_names=enum_names,
                    struct_names=struct_names,
                    map_types=map_types,
                ),
                extras={"thrift_map": True},
            )
        return TypeRef(name=map_types[map_key].key)

    if t in enum_names or t in struct_names:
        return TypeRef(name=_type_key(t, namespace))

    return TypeRef(name=t)


def _canonical_field(
    thrift_field: ThriftField,
    *,
    type_key: str,
    namespace: Optional[str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
    map_types: Dict[str, Type],
) -> CanonicalField:
    ref = _type_ref_from_expr(
        thrift_field.type_expr,
        namespace=namespace,
        enum_names=enum_names,
        struct_names=struct_names,
        map_types=map_types,
    )
    extras: Dict[str, Any] = {}
    if thrift_field.default is not None:
        extras["thrift_default"] = thrift_field.default
    extras["thrift_required"] = thrift_field.required
    return CanonicalField(
        key=Keys.field(type_key, thrift_field.name),
        name=thrift_field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=not thrift_field.required,
            extras=ref.extras,
        ),
        field_number=thrift_field.id,
        extras=extras,
    )


class ThriftNormalizer(Normalizer, register=True):
    """Normalize a parsed Thrift document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, ThriftDocument):
            raise ValueError("Thrift source must be a ThriftDocument (see app.thrift_parser.parse_thrift)")

        namespace = _primary_namespace(source)
        enum_names = frozenset(e.name for e in source.enums)
        struct_names = frozenset(s.name for s in source.structs)
        map_types: Dict[str, Type] = {}

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
            types.append(
                Type(
                    key=type_key,
                    name=enum.name,
                    kind=TypeKind.ENUM,
                    namespace=namespace,
                    enum_values=values,
                    extras={"thrift_kind": "enum"},
                )
            )

        for struct in source.structs:
            type_key = _type_key(struct.name, namespace)
            kind = TypeKind.UNION if struct.kind == "union" else TypeKind.RECORD
            extras: Dict[str, Any] = {"thrift_kind": struct.kind}
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    enum_names=enum_names,
                    struct_names=struct_names,
                    map_types=map_types,
                )
                for field in struct.fields
            ]
            types.append(
                Type(
                    key=type_key,
                    name=struct.name,
                    kind=kind,
                    namespace=namespace,
                    fields=fields,
                    extras=extras,
                )
            )

        types.extend(map_types.values())

        services: List[Service] = []
        for svc in source.services:
            service_key = Keys.type(svc.name, namespace)
            operations: List[Operation] = []
            for method in svc.methods:
                op_key = Keys.operation_rpc(service_key, method.name)
                messages: List[Message] = []
                if method.parameters:
                    # Thrift positional args are modeled as a synthetic request struct ref
                    # when there is exactly one parameter, otherwise inline parameters in extras.
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
                                    map_types=map_types,
                                ),
                                required=param.required,
                            )
                        )
                    else:
                        messages.append(
                            Message(
                                key=Keys.request_message(op_key),
                                role=MessageRole.REQUEST,
                                required=True,
                                extras={
                                    "thrift_parameters": [
                                        {
                                            "id": p.id,
                                            "name": p.name,
                                            "type": p.type_expr,
                                            "required": p.required,
                                        }
                                        for p in method.parameters
                                    ]
                                },
                            )
                        )
                if method.return_type != "void":
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=_type_ref_from_expr(
                                method.return_type,
                                namespace=namespace,
                                enum_names=enum_names,
                                struct_names=struct_names,
                                map_types=map_types,
                            ),
                        )
                    )
                for field_id, exc_type, alias in method.throws:
                    messages.append(
                        Message(
                            key=f"{op_key}#error.{alias}",
                            role=MessageRole.ERROR,
                            name=alias,
                            payload=TypeRef(name=_type_key(exc_type, namespace)),
                            extras={"thrift_throw_id": field_id},
                        )
                    )
                kind = OperationKind.ONE_WAY if method.oneway or method.return_type == "void" else OperationKind.REQUEST_RESPONSE
                operations.append(
                    Operation(
                        key=op_key,
                        name=method.name,
                        kind=kind,
                        streaming=StreamingMode.NONE,
                        messages=messages,
                        extras={"thrift_oneway": method.oneway},
                    )
                )
            services.append(Service(key=service_key, name=svc.name, operations=operations))

        identity_name = namespace or (services[0].name if services else "Thrift API")
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=identity_name, namespace=namespace),
            services=services,
            types=types,
            raw={"thrift": source.raw} if include_raw else None,
            extras={
                "thrift_namespaces": dict(source.namespaces),
                "thrift_includes": list(source.includes),
                "thrift_typedefs": dict(source.typedefs),
            },
        )
        return normalize_ordering(api)
