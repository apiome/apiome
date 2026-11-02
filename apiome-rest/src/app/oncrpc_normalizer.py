"""ONC RPC / XDR → canonical model normalizer — MFI-21.6.

Maps a parsed :class:`~app.oncrpc_parser.OncRpcDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

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
from .oncrpc_lint import migration_note
from .oncrpc_parser import OncRpcDocument, OncRpcField

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


#: A type expression as :mod:`app.oncrpc_parser` writes it: the base (``unsigned int``, a
#: typedef, enum or struct name), an optional ``*`` (optional-data), and an optional
#: variable-length ``<N>`` / ``<>`` or fixed-length ``[N]`` suffix.
_TYPE_EXPR = re.compile(r"^((?:unsigned )?[\w.]+)(\*)?(?:<(\d*)>|\[(\d+)\])?$")

#: The XDR types whose ``<N>`` bound is a byte / character length rather than an item count.
_LENGTH_BOUNDED = frozenset({"string", "opaque"})


class _TypeShape:
    """A decoded type expression: ``base``, ``pointer`` and the length suffix."""

    __slots__ = ("base", "pointer", "variable", "bound", "fixed")

    def __init__(self, type_expr: str) -> None:
        match = _TYPE_EXPR.match(type_expr.strip())
        if match is None:
            self.base, self.pointer, self.variable, self.bound, self.fixed = (
                type_expr.strip(), False, False, None, None,
            )
            return
        base, pointer, var_bound, fixed_size = match.groups()
        self.base = base
        self.pointer = pointer is not None
        self.variable = var_bound is not None
        self.bound = int(var_bound) if var_bound else None
        self.fixed = int(fixed_size) if fixed_size is not None else None

    @property
    def is_sequence(self) -> bool:
        """Whether the suffix makes an array (``<N>`` / ``<>`` on a non-length type, or ``[N]``)."""
        if self.fixed is not None:
            return True
        return self.variable and self.base not in _LENGTH_BOUNDED


def _resolve_typedef(type_expr: str, typedefs: Dict[str, str]) -> str:
    """Replace a typedef'd base with its definition, keeping the declaration's own suffix.

    ``kv_key`` (``typedef string kv_key<256>``) resolves to ``string<256>``; ``kv_key keys<10>``
    keeps its ``<10>`` on top of the resolved base — an array of ten bounded strings — so the
    suffix is only dropped when the typedef already carries one and the field adds none.
    """
    shape = _TypeShape(type_expr)
    resolved = typedefs.get(shape.base)
    if resolved is None:
        return type_expr.strip()
    suffix = type_expr.strip()[len(shape.base):]
    if not suffix:
        return resolved
    resolved_shape = _TypeShape(resolved)
    if resolved_shape.is_sequence or resolved_shape.variable or resolved_shape.pointer:
        return f"{resolved}{suffix}" if suffix.startswith(("<", "[")) else resolved
    return f"{resolved}{suffix}"


def _split_stacked(type_expr: str) -> Tuple[str, Optional[str]]:
    """Split a stacked expression (``string<256><10>``: ten bounded strings) into its parts.

    Returns:
        ``(inner, outer)``: the element expression and the outer ``<N>`` / ``<>`` / ``[N]``
        suffix, or ``(type_expr, None)`` when the expression carries at most one suffix.
    """
    text = type_expr.strip()
    match = re.search(r"(<\d*>|\[\d+\])$", text)
    if match is None:
        return text, None
    inner = text[: match.start()]
    inner_shape = _TypeShape(inner)
    if inner_shape.variable or inner_shape.fixed is not None:
        return inner, match.group(1)
    return text, None


def _constraints_for_type(type_expr: str) -> Optional[Constraints]:
    """The length / item-count bound a suffix declares, if any."""
    inner, outer = _split_stacked(type_expr)
    shape = _TypeShape(f"x{outer}" if outer else inner)
    if shape.fixed is not None:
        return Constraints(min_items=shape.fixed, max_items=shape.fixed)
    if shape.bound is None:
        return None
    if outer is None and shape.base in _LENGTH_BOUNDED:
        return Constraints(max_length=shape.bound)
    return Constraints(max_items=shape.bound)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    typedefs: Dict[str, str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
) -> TypeRef:
    resolved = _resolve_typedef(type_expr, typedefs)
    inner, outer = _split_stacked(resolved)
    if outer is not None:
        # A stacked expression: an array of the inner expression (ten bounded strings, say).
        element = _type_ref_from_expr(
            inner,
            namespace=namespace,
            typedefs=typedefs,
            enum_names=enum_names,
            struct_names=struct_names,
        )
        return TypeRef(item=element, nullable=False)
    shape = _TypeShape(inner)
    base_ref = _base_type_ref(
        shape.base, namespace=namespace, enum_names=enum_names, struct_names=struct_names
    )
    if shape.is_sequence:
        return TypeRef(item=base_ref, nullable=shape.pointer)
    if shape.pointer:
        return base_ref.model_copy(update={"nullable": True})
    return base_ref


def _base_type_ref(
    base: str,
    *,
    namespace: Optional[str],
    enum_names: frozenset[str],
    struct_names: frozenset[str],
) -> TypeRef:
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
                            extras={
                                "oncrpc_procedure_number": procedure.number,
                                "oncrpc_version_name": version.name,
                                "oncrpc_version_number": version.number,
                                "oncrpc_arg_type": procedure.arg_type,
                                "oncrpc_return_type": procedure.return_type,
                            },
                        )
                    )
            services.append(
                Service(
                    key=service_key,
                    name=program.name,
                    operations=operations,
                    extras={
                        "oncrpc_program_number": program.number,
                        "oncrpc_versions": {
                            version.name: version.number for version in program.versions
                        },
                    },
                )
            )

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=namespace, namespace=namespace),
            services=services,
            types=types,
            raw={"oncrpc": source.raw} if include_raw else None,
            extras={
                "oncrpc_typedefs": typedefs,
                # The migrate-to-gRPC note (MFI-21.6): where each XDR construct lands in proto3.
                "oncrpc_migration": migration_note(source),
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
