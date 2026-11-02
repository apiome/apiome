"""WADL → canonical model normalizer — MFI-17.2, extended by MFI-21.3 (#3993).

Maps a parsed :class:`~app.wadl_parser.WadlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`:

* each resource ``method`` → an :class:`~app.canonical_model.Operation` keyed ``VERB /path``
  (named by its ``id`` when it has one), its params → parameters, its request representation →
  a request message and each response status → a response message carrying the status code and
  the representations' media types;
* each grammar ``complexType`` → a RECORD; a sequence element's ``minOccurs="0"`` or
  ``nillable`` makes its type nullable (optional), a ``maxOccurs`` above one (or ``unbounded``)
  makes it a list with the occurrence bounds as ``min_items`` / ``max_items``;
* each named ``simpleType`` with ``enumeration`` s → an ENUM; one without → its base type,
  the simple type's name kept in ``wadl_type``;
* a param's ``option`` values → an ``enum`` constraint, ``repeating`` → a list, ``default`` →
  the default, and its WADL ``style`` in ``extras["wadl_style"]``.

References the parser could not resolve are kept in ``extras["wadl_unresolved_refs"]`` for the
lint pack (:mod:`app.wadl_lint`).
"""

from __future__ import annotations

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
    Parameter,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .wadl_parser import WadlDocument, WadlField, WadlParameter, WadlSimpleType

__all__ = ["CANONICAL_PRIMITIVES", "WadlNormalizer", "explicit_method_id"]

_FORMAT_KEY = "wadl"

_XSD_BASE_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "boolean": "bool",
    "double": "double",
    "float": "float",
    "decimal": "double",
    "int": "i32",
    "integer": "i32",
    "long": "i64",
    "short": "i16",
    "byte": "int8",
    "unsignedint": "uint32",
    "unsignedlong": "uint64",
    "unsignedshort": "uint16",
    "unsignedbyte": "uint8",
    "date": "string",
    "datetime": "string",
    "time": "string",
    "anytype": "string",
    "anysimpletype": "string",
    "anyuri": "string",
    "base64binary": "string",
    "hexbinary": "string",
    "duration": "string",
    "gyear": "string",
    "gyearmonth": "string",
    "gmonth": "string",
    "gmonthday": "string",
    "gday": "string",
    "token": "string",
    "normalizedstring": "string",
    "language": "string",
    "name": "string",
    "ncname": "string",
    "qname": "string",
    "id": "string",
    "idref": "string",
    "nonnegativeinteger": "uint64",
    "positiveinteger": "uint64",
    "nonpositiveinteger": "i64",
    "negativeinteger": "i64",
}

#: Every primitive name a WADL type reference can normalize to — anything else a reference
#: names must be a grammar type's key, or the reference is unresolved (``wadl.type-resolved``).
CANONICAL_PRIMITIVES = frozenset(_XSD_BASE_TO_CANONICAL.values())

_PARAM_LOCATIONS = {
    "path": ParameterLocation.PATH,
    "query": ParameterLocation.QUERY,
    "header": ParameterLocation.HEADER,
}


#: WADL param styles that share a canonical location with another style (``matrix`` reads as a
#: path parameter, ``plain`` as a query one), so the style is kept in ``extras["wadl_style"]``.
_STYLES_WITHOUT_LOCATION = frozenset({"matrix", "plain"})


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
    simple_bases: Optional[Dict[str, str]] = None,
    nullable: bool = True,
) -> TypeRef:
    """The canonical reference for an XSD type expression.

    Args:
        type_expr: The type, prefix stripped (``string``, ``Book``, ``Status``).
        namespace: The grammar's target namespace (part of a type key).
        type_names: Names that normalize to their own canonical type (complex types and
            enumerated simple types).
        simple_bases: Non-enumerated simple type name → its base type, which the reference
            resolves to.
        nullable: Whether the value may be absent / nil.

    Returns:
        A primitive, a type-key reference, or — for a name the grammar does not declare —
        a reference to the bare name (``wadl.type-resolved`` flags it).
    """
    base = (simple_bases or {}).get(type_expr)
    if base is not None and type_expr not in type_names:
        type_expr = base
    mapped = _XSD_BASE_TO_CANONICAL.get(type_expr.lower())
    if mapped:
        return TypeRef(name=mapped, nullable=nullable)
    if type_expr in type_names:
        return TypeRef(name=_type_key(type_expr, namespace), nullable=nullable)
    return TypeRef(name=type_expr, nullable=nullable)


def _occurrence_ref(field: WadlField, element: TypeRef) -> Tuple[TypeRef, Optional[Constraints]]:
    """Wrap a sequence element's type in its occurrence: optional, list, or bounded list.

    Args:
        field: The parsed element (``minOccurs`` / ``maxOccurs`` / ``nillable``).
        element: The element's own type, nullable as the element is.

    Returns:
        ``(type, constraints)`` — a repeated element is a list of non-null items whose bounds
        become ``min_items`` / ``max_items`` (``None`` when there are none to state).
    """
    if field.max_occurs is not None and field.max_occurs <= 1:
        return element, None
    item = element.model_copy(update={"nullable": False})
    min_items = field.min_occurs if field.min_occurs > 0 else None
    constraints = (
        Constraints(min_items=min_items, max_items=field.max_occurs)
        if min_items is not None or field.max_occurs is not None
        else None
    )
    return TypeRef(item=item, nullable=field.min_occurs == 0), constraints


def _canonical_field(
    field: WadlField,
    *,
    type_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    simple_bases: Dict[str, str],
    field_number: int,
) -> CanonicalField:
    optional = field.min_occurs == 0 or field.nillable
    element = _type_ref_from_expr(
        field.type_expr,
        namespace=namespace,
        type_names=type_names,
        simple_bases=simple_bases,
        nullable=optional,
    )
    type_ref, constraints = _occurrence_ref(field, element)
    # The occurrence lives in the type (nullable, list) and its bounds, not in extras: the XSD
    # writer re-states it from those, so extras would not survive a WADL → WADL round trip.
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=type_ref,
        field_number=field_number,
        constraints=constraints,
        extras={"wadl_type": field.type_expr},
    )


def _parameter(
    param: WadlParameter,
    *,
    operation_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    simple_bases: Dict[str, str],
) -> Parameter:
    location = _PARAM_LOCATIONS.get(param.location, ParameterLocation.QUERY)
    value = _type_ref_from_expr(
        param.type_expr, namespace=namespace, type_names=type_names, simple_bases=simple_bases
    )
    extras: Dict[str, Any] = {"wadl_type": param.type_expr}
    if param.style in _STYLES_WITHOUT_LOCATION:
        extras["wadl_style"] = param.style
    return Parameter(
        key=Keys.parameter(operation_key, param.location, param.name),
        name=param.name,
        location=location,
        required=param.required,
        type=TypeRef(item=value) if param.repeating else value,
        default=param.default,
        constraints=Constraints(enum=list(param.options)) if param.options else None,
        extras=extras,
    )


def _simple_type(simple: WadlSimpleType, namespace: Optional[str]) -> Type:
    """An enumerated ``simpleType`` as an ENUM type."""
    type_key = _type_key(simple.name, namespace)
    return Type(
        key=type_key,
        name=simple.name,
        kind=TypeKind.ENUM,
        namespace=namespace,
        enum_values=[
            EnumValue(key=Keys.enum_value(type_key, value), name=value) for value in simple.enumerations
        ],
        extras={"wadl_kind": "simpleType", "wadl_base": simple.base},
    )


def explicit_method_id(operation: Operation) -> Optional[str]:
    """The ``id`` a WADL method declared, or ``None``.

    The normalizer names a method by its ``id`` and an unnamed one ``"<VERB> <path>"``, so the
    id is the name whenever the name differs from that synthesized form.

    Args:
        operation: A normalized WADL method.

    Returns:
        The declared id, or ``None`` when the method had none.
    """
    synthesized = f"{(operation.http_method or '').upper()} {operation.http_path or ''}"
    if not operation.name or operation.name in (synthesized, operation.key):
        return None
    return operation.name


class WadlNormalizer(Normalizer, register=True):
    """Normalize a parsed WADL document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, WadlDocument):
            raise ValueError("WADL source must be a WadlDocument (see app.wadl_parser.parse_wadl)")

        namespace = source.target_namespace
        enums = [simple for simple in source.simple_types if simple.enumerations]
        type_names = frozenset(t.name for t in source.complex_types) | {simple.name for simple in enums}
        simple_bases = {simple.name: simple.base for simple in source.simple_types if not simple.enumerations}
        types: List[Type] = [_simple_type(simple, namespace) for simple in enums]

        for complex_type in source.complex_types:
            type_key = _type_key(complex_type.name, namespace)
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    type_names=type_names,
                    simple_bases=simple_bases,
                    field_number=index + 1,
                )
                for index, field in enumerate(complex_type.fields)
            ]
            types.append(
                Type(
                    key=type_key,
                    name=complex_type.name,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    fields=fields,
                    extras={"wadl_kind": "complexType"},
                )
            )

        operations: List[Operation] = []
        for endpoint in source.operations:
            op_key = Keys.operation_http(endpoint.method.upper(), endpoint.path)
            op_name = endpoint.operation_id or f"{endpoint.method.upper()} {endpoint.path}"
            messages: List[Message] = []
            if endpoint.request_type or endpoint.request_media_types:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=(
                            _type_ref_from_expr(
                                endpoint.request_type,
                                namespace=namespace,
                                type_names=type_names,
                                simple_bases=simple_bases,
                            )
                            if endpoint.request_type
                            else None
                        ),
                        content_types=list(endpoint.request_media_types),
                    )
                )
            seen_statuses: set[str] = set()
            for index, (status, response_type) in enumerate(endpoint.response_types):
                if status in seen_statuses:
                    # Two responses with one status share a message key; the first wins.
                    continue
                seen_statuses.add(status)
                payload = (
                    _type_ref_from_expr(
                        response_type,
                        namespace=namespace,
                        type_names=type_names,
                        simple_bases=simple_bases,
                    )
                    if response_type
                    else None
                )
                media = endpoint.response_media_types[index] if index < len(endpoint.response_media_types) else ()
                messages.append(
                    Message(
                        key=Keys.response_message(op_key, status),
                        role=MessageRole.RESPONSE,
                        payload=payload,
                        content_types=list(media),
                        status_code=status,
                        extras={"http_status": status},
                    )
                )
            operations.append(
                Operation(
                    key=op_key,
                    name=op_name,
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    description=endpoint.description,
                    http_method=endpoint.method.upper(),
                    http_path=endpoint.path,
                    parameters=[
                        _parameter(
                            param,
                            operation_key=op_key,
                            namespace=namespace,
                            type_names=type_names,
                            simple_bases=simple_bases,
                        )
                        for param in endpoint.parameters
                    ],
                    messages=messages,
                )
            )

        service_key = Keys.type(source.name, namespace)
        services = [Service(key=service_key, name=source.name, operations=operations)]

        servers: List[Server] = []
        if source.base_uri:
            servers.append(Server(url=source.base_uri, description="From WADL resources@base"))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=source.name, namespace=namespace),
            servers=servers,
            services=services,
            types=types,
            raw={"wadl": source.raw} if include_raw else None,
            extras={
                "wadl_target_namespace": source.target_namespace,
                **({"wadl_unresolved_refs": list(source.unresolved_refs)} if source.unresolved_refs else {}),
            },
        )
        return normalize_ordering(api)
