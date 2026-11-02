"""CORBA / OMG IDL → canonical model normalizer — MFI-21.7, extended by MFI-21.4 (#3994).

Maps a parsed :class:`~app.corbaidl_parser.CorbaIdlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`:

* each ``interface`` → a :class:`~app.canonical_model.Service`; its operations → operations
  keyed ``<module>.<Interface>.<operation>`` with a request message (the ``in`` / ``inout``
  parameters), a response (the return value) and an error message per ``raises`` exception;
* a ``oneway`` operation → :attr:`~app.canonical_model.OperationKind.ONE_WAY` with no response;
* an attribute → the operations CORBA's GIOP mapping gives it: ``_get_<name>`` returning its
  type and, unless ``readonly``, ``_set_<name>`` taking it;
* the operations and attributes an interface **inherits** are flattened into its service (a
  client calls them on the derived object); ``extras["corbaidl_bases"]`` lists the bases and
  ``extras["corbaidl_inherited"]`` which base each inherited operation comes from;
* each ``struct`` / ``exception`` → a RECORD, each ``enum`` → an ENUM.

``extras["corbaidl_interfaces"]`` keeps every interface as declared (own operations with their
signatures and ``oneway`` flag, attributes, bases) — the lint pack (:mod:`app.corbaidl_lint`),
the breaking-change classifier (:mod:`app.corbaidl_breaking`) and the IDL emitter read it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
from .corbaidl_parser import CorbaIdlDocument, CorbaIdlField, CorbaIdlInterface, CorbaIdlParameter
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["CorbaIdlNormalizer", "attribute_operations", "inherited_members", "member_sources"]

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
    "long long": "i64",
    "unsigned long long": "uint64",
    "long double": "double",
    "float": "float",
    "double": "double",
    "string": "string",
    "wstring": "string",
    "any": "bytes",
    "Object": "string",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


#: A bounded string, ``string<40>`` / ``wstring<40>`` (MFX-28.2: the writer bounds a ``max_length``).
_BOUNDED_STRING_RE = re.compile(r"^w?string\s*<\s*(\d+)\s*>$")
#: A bounded sequence's bound, ``sequence<T, 5>`` (the writer bounds a ``max_items``).
_SEQUENCE_BOUND_RE = re.compile(r"^sequence\s*<.*,\s*(\d+)\s*>$", re.DOTALL)


def _bound_constraints(type_expr: str) -> Optional[Constraints]:
    """The constraints an IDL bound states: ``string<N>`` → ``max_length``, ``sequence<T, N>`` → ``max_items``.

    Args:
        type_expr: A member's resolved type expression.

    Returns:
        The constraints, or ``None`` for an unbounded type.
    """
    expr = type_expr.strip()
    string_match = _BOUNDED_STRING_RE.match(expr)
    if string_match:
        return Constraints(max_length=int(string_match.group(1)))
    sequence_match = _SEQUENCE_BOUND_RE.match(expr)
    if sequence_match:
        return Constraints(max_items=int(sequence_match.group(1)))
    return None


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
    if _BOUNDED_STRING_RE.match(resolved):
        return TypeRef(name="string", nullable=False)
    seq_match = re.fullmatch(r"sequence\s*<\s*([\w.<>, \t]+?)(?:\s*,\s*\d+)?\s*>", resolved)
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
        constraints=_bound_constraints(resolved),
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


def member_sources(entry: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """An interface entry's operations, then each attribute's accessors as operation entries.

    ``_get_<name>`` returns the attribute's type; ``_set_<name>`` takes it as its one ``in``
    parameter and returns nothing.
    """
    sources: List[Dict[str, Any]] = [dict(op) for op in entry.get("operations") or []]
    for attribute in entry.get("attributes") or []:
        name, type_expr = str(attribute.get("name")), str(attribute.get("type"))
        for accessor in attribute_operations(name, bool(attribute.get("readonly"))):
            if accessor.startswith("_get_"):
                sources.append({"name": accessor, "return_type": type_expr, "parameters": [], "raises": []})
            else:
                sources.append(
                    {
                        "name": accessor,
                        "return_type": "void",
                        "parameters": [{"name": name, "type": type_expr, "direction": "in"}],
                        "raises": [],
                    }
                )
    return sources


def _operation(service_key: str, entry: Mapping[str, Any], refs: Mapping[str, Any]) -> Operation:
    """One operation (declared or an attribute accessor) of a service.

    Args:
        service_key: The owning service's key.
        entry: The operation entry (``name`` / ``return_type`` / ``parameters`` / ``raises`` /
            ``oneway``).
        refs: The keyword arguments :func:`_type_ref_from_expr` resolves names with.

    Returns:
        The operation: a ``oneway`` one is ONE_WAY with no response message.
    """
    op_key = Keys.operation_rpc(service_key, str(entry["name"]))
    parameters = tuple(
        CorbaIdlParameter(name=str(p["name"]), type_expr=str(p["type"]), direction=str(p.get("direction", "in")))
        for p in entry.get("parameters") or []
    )
    messages = _parameter_messages(op_key, parameters, **refs)
    oneway = bool(entry.get("oneway"))
    return_type = str(entry.get("return_type") or "void")
    if return_type != "void" and not oneway:
        messages.append(
            Message(
                key=f"{op_key}#response",
                role=MessageRole.RESPONSE,
                payload=_type_ref_from_expr(return_type, **refs),
            )
        )
    for index, exc_name in enumerate(entry.get("raises") or [], start=1):
        messages.append(
            Message(
                key=f"{op_key}#error.{exc_name}",
                role=MessageRole.ERROR,
                name=exc_name,
                payload=TypeRef(name=_type_key(exc_name, refs["namespace"])),
                extras={"corbaidl_raise_index": index},
            )
        )
    return Operation(
        key=op_key,
        name=str(entry["name"]),
        kind=OperationKind.ONE_WAY if oneway else OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        messages=messages,
    )


def attribute_operations(name: str, readonly: bool) -> List[str]:
    """The GIOP operation names of an attribute: ``_get_<name>`` and, unless read-only, ``_set_<name>``.

    Args:
        name: The attribute name.
        readonly: Whether it is ``readonly``.

    Returns:
        The accessor operation names, getter first.
    """
    return [f"_get_{name}"] if readonly else [f"_get_{name}", f"_set_{name}"]


def inherited_members(
    interface: str, interfaces: Mapping[str, Mapping[str, Any]]
) -> List[Tuple[str, str]]:
    """``(member name, base)`` for every operation and attribute accessor ``interface`` inherits.

    Bases are walked depth-first in declaration order; a member already reached (its own, or
    from an earlier base — the diamond case) is not repeated, and an inheritance cycle or an
    undeclared base stops the walk on that branch rather than looping (``corbaidl.inheritance-*``
    lint rules report them).

    Args:
        interface: The interface's name.
        interfaces: Interface name → its ``corbaidl_interfaces`` entry (``operations`` /
            ``attributes`` / ``bases``).

    Returns:
        The inherited members in walk order, each with the base that declares it.
    """
    seen = set(_own_members(interfaces.get(interface) or {}))
    found: List[Tuple[str, str]] = []
    visited = {interface}

    def walk(name: str) -> None:
        for base in (interfaces.get(name) or {}).get("bases") or []:
            if base in visited or base not in interfaces:
                continue
            visited.add(base)
            for member in _own_members(interfaces[base]):
                if member not in seen:
                    seen.add(member)
                    found.append((member, base))
            walk(base)

    walk(interface)
    return found


def _own_members(entry: Mapping[str, Any]) -> List[str]:
    """The operation names an interface entry declares itself (attribute accessors included)."""
    names = [str(op.get("name")) for op in entry.get("operations") or []]
    for attribute in entry.get("attributes") or []:
        names.extend(attribute_operations(str(attribute.get("name")), bool(attribute.get("readonly"))))
    return names


def _interface_entry(interface: CorbaIdlInterface) -> Dict[str, Any]:
    """An interface as declared, for ``extras["corbaidl_interfaces"]``."""
    entry: Dict[str, Any] = {
        "name": interface.name,
        "operations": [
            {
                "name": operation.name,
                "return_type": operation.return_type,
                "parameters": [
                    {"name": param.name, "type": param.type_expr, "direction": param.direction}
                    for param in operation.parameters
                ],
                "raises": list(operation.raises),
                **({"oneway": True} if operation.oneway else {}),
            }
            for operation in interface.operations
        ],
    }
    if interface.bases:
        entry["bases"] = list(interface.bases)
    if interface.attributes:
        entry["attributes"] = [
            {"name": a.name, "type": a.type_expr, **({"readonly": True} if a.readonly else {})}
            for a in interface.attributes
        ]
    return entry


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

        refs = dict(namespace=namespace, typedefs=typedefs, enum_names=enum_names, struct_names=struct_names)
        entries = {interface.name: _interface_entry(interface) for interface in source.interfaces}
        services: List[Service] = []
        for interface in source.interfaces:
            service_key = Keys.type(interface.name, namespace)
            members = [(entry, None) for entry in member_sources(entries[interface.name])]
            inherited: Dict[str, str] = {}
            for member, base in inherited_members(interface.name, entries):
                inherited[member] = base
                members.extend(
                    (entry, base) for entry in member_sources(entries[base]) if entry["name"] == member
                )
            operations: List[Operation] = []
            for entry, _ in members:
                operation = _operation(service_key, entry, refs)
                # IDL forbids overloading (`corbaidl.operation-names-unique`); keep the first.
                if all(existing.key != operation.key for existing in operations):
                    operations.append(operation)
            extras: Dict[str, Any] = {}
            if interface.bases:
                extras["corbaidl_bases"] = list(interface.bases)
            if inherited:
                extras["corbaidl_inherited"] = inherited
            services.append(Service(key=service_key, name=interface.name, operations=operations, extras=extras))

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
                "corbaidl_interfaces": [entries[interface.name] for interface in source.interfaces],
            },
        )
        return normalize_ordering(api)
