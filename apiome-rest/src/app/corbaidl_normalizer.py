"""CORBA / OMG IDL → canonical model normalizer — MFI-21.7.

Maps a parsed :class:`~app.corbaidl_parser.CorbaIdlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.
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
from .corbaidl_parser import CorbaIdlDocument, CorbaIdlField, CorbaIdlParameter
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["CorbaIdlNormalizer"]

_FORMAT_KEY = "corbaidl"

_CORBA_BASE_TO_CANONICAL: Dict[str, str] = {
    "void": "void",
    "boolean": "bool",
    "char": "string",
    "wchar": "string",
    "octet": "bytes",
    "short": "i16",
    "unsigned short": "uint16",
    "long": "i32",
    "unsigned long": "uint32",
    "float": "float",
    "double": "double",
    "string": "string",
    "wstring": "string",
    "any": "bytes",
    "Object": "string",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _resolve_typedef(type_expr: str, typedefs: Dict[str, str]) -> str:
    seq_match = re.fullmatch(r"sequence\s*<\s*([\w.<>, \t]+)\s*>", type_expr.strip())
    if seq_match:
        inner = _resolve_typedef(seq_match.group(1).strip(), typedefs)
        return f"sequence<{inner}>"
    return typedefs.get(type_expr.strip(), type_expr.strip())


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    typedefs: Dict[str, str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
) -> TypeRef:
    resolved = _resolve_typedef(type_expr, typedefs)
    seq_match = re.fullmatch(r"sequence\s*<\s*([\w.<>, \t]+)\s*>", resolved)
    if seq_match:
        inner = _type_ref_from_expr(
            seq_match.group(1).strip(),
            namespace=namespace,
            typedefs=typedefs,
            enum_names=enum_names,
            struct_names=struct_names,
        )
        return TypeRef(name=inner.name, item=inner, nullable=False)

    mapped = _CORBA_BASE_TO_CANONICAL.get(resolved)
    if mapped:
        return TypeRef(name=mapped, nullable=False)
    if resolved in enum_names or resolved in struct_names:
        return TypeRef(name=_type_key(resolved, namespace), nullable=False)
    return TypeRef(name=resolved, nullable=False)


def _canonical_field(
    field: CorbaIdlField,
    *,
    parent_key: str,
    namespace: Optional[str],
    typedefs: Dict[str, str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    resolved = _resolve_typedef(field.type_expr, typedefs)
    return CanonicalField(
        key=Keys.field(parent_key, field.name),
        name=field.name,
        type=_type_ref_from_expr(
            resolved,
            namespace=namespace,
            typedefs=typedefs,
            enum_names=enum_names,
            struct_names=struct_names,
        ),
        field_number=field_number,
        extras={"corbaidl_type_expr": field.type_expr},
    )


def _parameter_messages(
    op_key: str,
    parameters: tuple[CorbaIdlParameter, ...],
    *,
    namespace: Optional[str],
    typedefs: Dict[str, str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
) -> List[Message]:
    if not parameters:
        return []
    if len(parameters) == 1:
        param = parameters[0]
        role = MessageRole.REQUEST
        if param.direction == "out":
            role = MessageRole.RESPONSE
        return [
            Message(
                key=Keys.request_message(op_key) if role is MessageRole.REQUEST else f"{op_key}#response",
                role=role,
                payload=_type_ref_from_expr(
                    param.type_expr,
                    namespace=namespace,
                    typedefs=typedefs,
                    enum_names=enum_names,
                    struct_names=struct_names,
                ),
                required=True,
                extras={"corbaidl_direction": param.direction},
            )
        ]
    return [
        Message(
            key=Keys.request_message(op_key),
            role=MessageRole.REQUEST,
            required=True,
            extras={
                "corbaidl_parameters": [
                    {
                        "name": param.name,
                        "type": param.type_expr,
                        "direction": param.direction,
                    }
                    for param in parameters
                ]
            },
        )
    ]


class CorbaIdlNormalizer(Normalizer, register=True):
    """Normalize a parsed CORBA IDL document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, CorbaIdlDocument):
            raise ValueError(
                "CORBA IDL source must be a CorbaIdlDocument (see app.corbaidl_parser.parse_corbaidl)"
            )

        typedefs = {item.name: item.type_expr for item in source.typedefs}
        enum_names = frozenset(item.name for item in source.enums)
        struct_names = frozenset(item.name for item in source.structs)
        namespace = source.module or (source.interfaces[0].name if source.interfaces else "CorbaIdl")

        types: List[Type] = []
        for enum in source.enums:
            type_key = _type_key(enum.name, namespace)
            types.append(
                Type(
                    key=type_key,
                    name=enum.name,
                    kind=TypeKind.ENUM,
                    enum_values=tuple(
                        EnumValue(
                            key=Keys.enum_value(type_key, name),
                            name=name,
                            value=number if number is not None else index,
                        )
                        for index, (name, number) in enumerate(enum.values)
                    ),
                    extras={"corbaidl_kind": "enum"},
                )
            )

        for struct in source.structs:
            type_key = _type_key(struct.name, namespace)
            fields = tuple(
                _canonical_field(
                    field,
                    parent_key=type_key,
                    namespace=namespace,
                    typedefs=typedefs,
                    enum_names=enum_names,
                    struct_names=struct_names,
                    field_number=index,
                )
                for index, field in enumerate(struct.fields, start=1)
            )
            types.append(
                Type(
                    key=type_key,
                    name=struct.name,
                    kind=TypeKind.RECORD,
                    fields=fields,
                    extras={"corbaidl_kind": struct.kind},
                )
            )

        services: List[Service] = []
        for interface in source.interfaces:
            service_key = Keys.type(interface.name, namespace)
            operations: List[Operation] = []
            for operation in interface.operations:
                op_key = Keys.operation_rpc(service_key, operation.name)
                messages = _parameter_messages(
                    op_key,
                    operation.parameters,
                    namespace=namespace,
                    typedefs=typedefs,
                    enum_names=enum_names,
                    struct_names=struct_names,
                )
                if operation.return_type != "void":
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=_type_ref_from_expr(
                                operation.return_type,
                                namespace=namespace,
                                typedefs=typedefs,
                                enum_names=enum_names,
                                struct_names=struct_names,
                            ),
                        )
                    )
                for index, exc_name in enumerate(operation.raises, start=1):
                    messages.append(
                        Message(
                            key=f"{op_key}#error.{exc_name}",
                            role=MessageRole.ERROR,
                            name=exc_name,
                            payload=TypeRef(name=_type_key(exc_name, namespace)),
                            extras={"corbaidl_raise_index": index},
                        )
                    )
                operations.append(
                    Operation(
                        key=op_key,
                        name=operation.name,
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        messages=messages,
                    )
                )
            services.append(Service(key=service_key, name=interface.name, operations=operations))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=namespace, namespace=namespace),
            services=services,
            types=types,
            raw={"corbaidl": source.raw} if include_raw else None,
            extras={
                "corbaidl_module": source.module,
                "corbaidl_typedefs": typedefs,
                "corbaidl_interfaces": [
                    {
                        "name": interface.name,
                        "operations": [
                            {
                                "name": operation.name,
                                "return_type": operation.return_type,
                                "parameters": [
                                    {
                                        "name": param.name,
                                        "type": param.type_expr,
                                        "direction": param.direction,
                                    }
                                    for param in operation.parameters
                                ],
                                "raises": list(operation.raises),
                            }
                            for operation in interface.operations
                        ],
                    }
                    for interface in source.interfaces
                ],
            },
        )
        return normalize_ordering(api)
