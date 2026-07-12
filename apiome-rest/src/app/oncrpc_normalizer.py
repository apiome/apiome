"""ONC RPC / XDR → canonical model normalizer — MFI-21.6.

Maps a parsed :class:`~app.oncrpc_parser.OncRpcDocument` into a
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
    Constraints,
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
from .oncrpc_parser import OncRpcDocument, OncRpcField, OncRpcStruct

__all__ = ["OncRpcNormalizer"]

_FORMAT_KEY = "oncrpc"

_XDR_BASE_TO_CANONICAL: Dict[str, str] = {
    "int": "i32",
    "unsigned int": "uint32",
    "short": "i16",
    "unsigned short": "uint16",
    "long": "i32",
    "unsigned long": "uint32",
    "hyper": "i64",
    "unsigned hyper": "uint64",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "string": "string",
    "opaque": "bytes",
    "void": "void",
    "char": "string",
    "wchar": "string",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _resolve_typedef(type_expr: str, typedefs: Dict[str, str]) -> str:
    bound_match = re.fullmatch(r"(\w+)<(\d+)>", type_expr.strip())
    if bound_match:
        base = bound_match.group(1)
        resolved = typedefs.get(base, base)
        if "<" not in resolved:
            return f"{resolved}<{bound_match.group(2)}>"
        return resolved
    return typedefs.get(type_expr.strip(), type_expr.strip())


def _constraints_for_type(type_expr: str) -> Optional[Constraints]:
    bound_match = re.fullmatch(r"(\w+)<(\d+)>", type_expr.strip())
    if not bound_match:
        return None
    base = bound_match.group(1)
    max_length = int(bound_match.group(2))
    if base in {"string", "opaque"}:
        return Constraints(max_length=max_length)
    return None


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    typedefs: Dict[str, str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
) -> TypeRef:
    resolved = _resolve_typedef(type_expr, typedefs)
    bound_match = re.fullmatch(r"(\w+)<(\d+)>", resolved)
    base = bound_match.group(1) if bound_match else resolved
    mapped = _XDR_BASE_TO_CANONICAL.get(base)
    if mapped:
        return TypeRef(name=mapped, nullable=False)
    if base in enum_names or base in struct_names:
        return TypeRef(name=_type_key(base, namespace), nullable=False)
    return TypeRef(name=base, nullable=False)


def _canonical_field(
    field: OncRpcField,
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
        constraints=_constraints_for_type(resolved),
        extras={"oncrpc_type_expr": field.type_expr},
    )


class OncRpcNormalizer(Normalizer, register=True):
    """Normalize a parsed ONC RPC / XDR document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, OncRpcDocument):
            raise ValueError(
                "ONC RPC source must be an OncRpcDocument (see app.oncrpc_parser.parse_oncrpc)"
            )

        typedefs = {item.name: item.type_expr for item in source.typedefs}
        enum_names = frozenset(item.name for item in source.enums)
        struct_names = frozenset(item.name for item in source.structs)
        namespace = source.programs[0].name if source.programs else "OncRpc"

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
                    extras={"oncrpc_kind": "enum"},
                )
            )

        for struct in source.structs:
            type_key = _type_key(struct.name, namespace)
            if struct.kind == "union":
                members: List[str] = []
                union_cases: List[Dict[str, object]] = []
                for case in struct.cases:
                    if not case.fields:
                        members.append("void")
                        union_cases.append({"label": case.label, "type": "void"})
                        continue
                    field = case.fields[0]
                    ref = _type_ref_from_expr(
                        _resolve_typedef(field.type_expr, typedefs),
                        namespace=namespace,
                        typedefs=typedefs,
                        enum_names=enum_names,
                        struct_names=struct_names,
                    )
                    members.append(ref.name)
                    union_cases.append(
                        {
                            "label": case.label,
                            "field": field.name,
                            "type": field.type_expr,
                            "canonical_type": ref.name,
                        }
                    )
                types.append(
                    Type(
                        key=type_key,
                        name=struct.name,
                        kind=TypeKind.UNION,
                        union_members=tuple(members),
                        extras={
                            "oncrpc_kind": "union",
                            "oncrpc_switch_type": struct.switch_type,
                            "oncrpc_switch_field": struct.switch_field,
                            "oncrpc_union_cases": union_cases,
                        },
                    )
                )
                continue

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
                    extras={"oncrpc_kind": "struct"},
                )
            )

        services: List[Service] = []
        for program in source.programs:
            service_key = Keys.type(program.name, namespace)
            operations: List[Operation] = []
            for version in program.versions:
                for procedure in version.procedures:
                    op_key = Keys.operation_rpc(service_key, procedure.name)
                    messages: List[Message] = []
                    if procedure.arg_type and procedure.arg_type != "void":
                        messages.append(
                            Message(
                                key=Keys.request_message(op_key),
                                role=MessageRole.REQUEST,
                                payload=_type_ref_from_expr(
                                    procedure.arg_type,
                                    namespace=namespace,
                                    typedefs=typedefs,
                                    enum_names=enum_names,
                                    struct_names=struct_names,
                                ),
                                required=True,
                            )
                        )
                    if procedure.return_type != "void":
                        messages.append(
                            Message(
                                key=f"{op_key}#response",
                                role=MessageRole.RESPONSE,
                                payload=_type_ref_from_expr(
                                    procedure.return_type,
                                    namespace=namespace,
                                    typedefs=typedefs,
                                    enum_names=enum_names,
                                    struct_names=struct_names,
                                ),
                            )
                        )
                    operations.append(
                        Operation(
                            key=op_key,
                            name=procedure.name,
                            kind=OperationKind.REQUEST_RESPONSE,
                            streaming=StreamingMode.NONE,
                            messages=messages,
                            extras={"oncrpc_procedure_number": procedure.number},
                        )
                    )
            services.append(Service(key=service_key, name=program.name, operations=operations))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=namespace, namespace=namespace),
            services=services,
            types=types,
            raw={"oncrpc": source.raw} if include_raw else None,
            extras={
                "oncrpc_typedefs": typedefs,
                "oncrpc_programs": [
                    {
                        "name": program.name,
                        "number": program.number,
                        "versions": [
                            {
                                "name": version.name,
                                "number": version.number,
                                "procedures": [
                                    {
                                        "name": procedure.name,
                                        "number": procedure.number,
                                        "arg_type": procedure.arg_type,
                                        "return_type": procedure.return_type,
                                    }
                                    for procedure in version.procedures
                                ],
                            }
                            for version in program.versions
                        ],
                    }
                    for program in source.programs
                ],
            },
        )
        return normalize_ordering(api)
