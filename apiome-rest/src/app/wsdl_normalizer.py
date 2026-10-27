"""WSDL → canonical model normalizer — MFI-15.2, WSDL 2.0 taught by FMT-3.3 (#5428).

Maps a parsed :class:`~app.wsdl_parser.WsdlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`. XSD complex types become
:class:`~app.canonical_model.Type` records; portType operations become
:class:`~app.canonical_model.Service` / :class:`~app.canonical_model.Operation` pairs.

The parser hands both WSDL grammars over in the same AST, so this module is version-blind
in all but two places, and both are additive:

* an operation's payload is reached through a named ``message`` (1.1) or straight from the
  payload element (2.0) — :func:`_operation_payload` takes whichever the document used and
  produces the same :class:`~app.canonical_model.TypeRef`;
* an operation's kind comes from its message exchange pattern when the document states one.
  WSDL 1.1 has no MEP vocabulary at all, so a 1.1 operation keeps the
  ``REQUEST_RESPONSE`` this normalizer has always produced and its canonical shape is
  untouched.

MFI-13.2 (#3789) completes the projection:

* **faults** — a 1.1 ``wsdl:fault`` and a 2.0 ``outfault`` both become an ``error``-role message
  keyed ``<operation>#fault.<name>``, its payload resolved like any other message's;
* **multi-part messages** — a 1.1 message with several parts (rpc style) becomes a synthesized
  record type (``extras["wsdl_kind"] == "message"``) with one field per part, instead of only its
  first part;
* **ports and bindings** — each port with an address is a :class:`~app.canonical_model.Server`
  named after the port, whose ``protocol`` is its binding's (``soap11`` / ``soap12`` / ``http``)
  and whose extras name the WSDL service, binding, port type and transport.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .wsdl_parser import WsdlDocument, WsdlField, WsdlMessage, WsdlOperation
from .wsdl_versions import VERSION_2_0, operation_kind_for_pattern

__all__ = ["WsdlNormalizer"]

_FORMAT_KEY = "wsdl"

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
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> TypeRef:
    mapped = _XSD_BASE_TO_CANONICAL.get(type_expr.lower())
    if mapped:
        return TypeRef(name=mapped)
    if type_expr in type_names:
        return TypeRef(name=_type_key(type_expr, namespace))
    return TypeRef(name=type_expr)


def _canonical_field(
    field: WsdlField,
    *,
    type_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=_type_ref_from_expr(field.type_expr, namespace=namespace, type_names=type_names),
        field_number=field_number,
        extras={"xsd_type": field.type_expr, **xsd_field_extras(field)},
    )


def xsd_facet_map(facets: Any) -> Dict[str, Any]:
    """Restriction facets as ``{facet: value}``; ``enumeration`` and ``pattern`` collect lists."""
    mapped: Dict[str, Any] = {}
    for facet, value in facets:
        if facet in ("enumeration", "pattern"):
            mapped.setdefault(facet, []).append(value)
        else:
            mapped[facet] = value
    return mapped


def xsd_field_extras(field: WsdlField) -> Dict[str, Any]:
    """The XSD details a field's element declares (MFI-13.5), keyed ``xsd_*``.

    Only details the document states are recorded, so a schema that states none keeps the model it
    always had; the WSDL emitter writes each one back (:mod:`app.wsdl_emitter`).
    """
    extras: Dict[str, Any] = {}
    for key, value in (
        ("xsd_min_occurs", field.min_occurs),
        ("xsd_max_occurs", field.max_occurs),
        ("xsd_nillable", field.nillable),
        ("xsd_default", field.default),
        ("xsd_simple_type", field.simple_type),
        ("xsd_base", field.base),
    ):
        if value is not None:
            extras[key] = value
    if field.facets:
        extras["xsd_facets"] = xsd_facet_map(field.facets)
    return extras


def soap_operation_extras(operation: WsdlOperation) -> Dict[str, Any]:
    """An operation's SOAP binding details (MFI-13.5): ``wsdl_soap_action`` when stated, and
    ``wsdl_soap_style`` only for ``rpc`` (``document`` is the SOAP default)."""
    extras: Dict[str, Any] = {}
    if operation.soap_action:
        extras["wsdl_soap_action"] = operation.soap_action
    if operation.soap_style == "rpc":
        extras["wsdl_soap_style"] = "rpc"
    return extras


def _element_payload(
    element_name: Optional[str],
    *,
    namespace: Optional[str],
    element_to_type: Dict[str, str],
    type_names: frozenset[str],
) -> Optional[TypeRef]:
    """Resolve a global element declaration to the type it carries.

    Args:
        element_name: The element's local name, or ``None``.
        namespace: The document's target namespace.
        element_to_type: Global element name -> declared type expression.
        type_names: Names of the document's complex types.

    Returns:
        The payload reference, or ``None`` when the element is unknown. An element
        declared with a built-in XSD type resolves to the canonical scalar it maps to,
        not to a type key nothing declares.
    """
    if not element_name or element_name not in element_to_type:
        return None
    return _type_ref_from_expr(
        element_to_type[element_name], namespace=namespace, type_names=type_names
    )


def _operation_payload(
    message: Optional[WsdlMessage],
    element_name: Optional[str],
    *,
    namespace: Optional[str],
    element_to_type: Dict[str, str],
    type_names: frozenset[str],
    message_types: Optional[Dict[str, str]] = None,
) -> Optional[TypeRef]:
    """Resolve one side of an operation to its canonical payload reference.

    WSDL 1.1 points at a ``message`` whose first part names an element or a type; WSDL 2.0
    has no ``message`` element and names the payload element on the operation itself.
    Both arrive here and leave as the same kind of reference.

    Args:
        message: The 1.1 message, or ``None``.
        element_name: The 2.0 payload element's local name, or ``None``.
        namespace: The document's target namespace.
        element_to_type: Global element name -> declared type expression.
        type_names: Names of the document's complex types.
        message_types: Multi-part message name -> its synthesized type key (MFI-13.2).

    Returns:
        The payload reference, or ``None`` when this side carries no resolvable payload.
    """
    if message is not None and len(message.parts) > 1 and message_types and message.name in message_types:
        return TypeRef(name=message_types[message.name])
    if message is not None and message.parts:
        part = message.parts[0]
        resolved = _element_payload(
            part.element,
            namespace=namespace,
            element_to_type=element_to_type,
            type_names=type_names,
        )
        if resolved is not None:
            return resolved
        if part.type_name:
            return _type_ref_from_expr(part.type_name, namespace=namespace, type_names=type_names)
        return None
    return _element_payload(
        element_name,
        namespace=namespace,
        element_to_type=element_to_type,
        type_names=type_names,
    )


def _identity_name(source: WsdlDocument, service_names: List[str]) -> str:
    """Pick the API identity name for a parsed document.

    Args:
        source: The parsed document.
        service_names: Canonical service names, in order.

    Returns:
        The 1.1 ``definitions/@name`` when present. A WSDL 2.0 ``description`` has no name
        attribute, so a 2.0 document is named after its ``service`` element — the thing an
        operator would call the service — falling back to the first interface.
    """
    if source.name:
        return source.name
    if source.version == VERSION_2_0 and source.services:
        return source.services[0].name
    return service_names[0] if service_names else "WSDL service"


def _live_fetch_extras(source: WsdlDocument) -> Dict[str, Any]:
    """Where a live description came from (MFI-13.3); empty for an uploaded document."""
    if not source.source_url:
        return {}
    extras: Dict[str, Any] = {
        "wsdl_source_url": source.source_url,
        "wsdl_single_wsdl": source.single_wsdl,
        "wsdl_fetched_documents": [dict(document) for document in source.fetched_documents],
    }
    if source.fetch_notes:
        extras["wsdl_fetch_notes"] = list(source.fetch_notes)
    return extras


def _wsi_extras(source: WsdlDocument) -> Dict[str, Any]:
    """WS-I Basic Profile issues (MFI-13.4); empty when there are none, so a clean model is unchanged."""
    if not source.wsi_issue_count:
        return {}
    return {
        "wsdl_wsi_issues": [dict(issue) for issue in source.wsi_issues],
        "wsdl_wsi_issue_count": source.wsi_issue_count,
    }


def _version_extras(source: WsdlDocument) -> Dict[str, Any]:
    """Provenance keys recording which WSDL grammar the document was written in.

    Only a 2.0 document contributes a key. WSDL 1.1 is the format's original grammar and
    what the bare ``wsdl`` key has always meant, so stamping ``wsdl_version: "1.1"`` onto
    every existing import would move every 1.1 fingerprint and golden without telling a
    reader anything the format key did not already say.

    Args:
        source: The parsed document.

    Returns:
        ``{"wsdl_version": "2.0"}`` for a 2.0 document; an empty mapping otherwise.
    """
    if source.version != VERSION_2_0:
        return {}
    return {"wsdl_version": source.version}


def _message_types(
    source: WsdlDocument,
    *,
    namespace: Optional[str],
    element_to_type: Dict[str, str],
    type_names: frozenset[str],
) -> Tuple[List[Type], Dict[str, str]]:
    """A synthesized record type for every multi-part 1.1 message (MFI-13.2).

    Each part is one field: an ``element`` part takes the element's type (``wsdl_part_element``
    names the element), a ``type`` part its type (``wsdl_part_type``). The type is named after the
    message (``<Message>Message`` when a complex type already has that name).

    Returns:
        ``(types, message name → type key)``.
    """
    types: List[Type] = []
    keys: Dict[str, str] = {}
    for message in source.messages:
        if len(message.parts) < 2:
            continue
        name = message.name if message.name not in type_names else f"{message.name}Message"
        type_key = _type_key(name, namespace)
        fields = []
        for index, part in enumerate(message.parts, start=1):
            if part.element:
                ref = _element_payload(
                    part.element, namespace=namespace, element_to_type=element_to_type, type_names=type_names
                ) or _type_ref_from_expr(part.element, namespace=namespace, type_names=type_names)
                extras: Dict[str, Any] = {"wsdl_part_element": part.element}
            else:
                ref = _type_ref_from_expr(part.type_name or "string", namespace=namespace, type_names=type_names)
                extras = {"wsdl_part_type": part.type_name}
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, part.name), name=part.name, type=ref, field_number=index, extras=extras
                )
            )
        types.append(
            Type(
                key=type_key,
                name=name,
                kind=TypeKind.RECORD,
                namespace=namespace,
                fields=fields,
                extras={"wsdl_kind": "message", "wsdl_message": message.name},
            )
        )
        keys[message.name] = type_key
    return types, keys


def _fault_messages(
    operation: WsdlOperation,
    op_key: str,
    *,
    messages_by_name: Dict[str, WsdlMessage],
    namespace: Optional[str],
    element_to_type: Dict[str, str],
    type_names: frozenset[str],
    message_types: Dict[str, str],
) -> List[Message]:
    """An operation's faults as ``error`` messages keyed ``<operation>#fault.<name>`` (MFI-13.2)."""
    faults: List[Message] = []
    for fault in operation.faults:
        payload = _operation_payload(
            messages_by_name.get(fault.message or ""),
            fault.element,
            namespace=namespace,
            element_to_type=element_to_type,
            type_names=type_names,
            message_types=message_types,
        )
        faults.append(
            Message(key=f"{op_key}#fault.{fault.name}", role=MessageRole.ERROR, name=fault.name, payload=payload)
        )
    return faults


def _servers(source: WsdlDocument) -> List[Server]:
    """Each port with an address, named after it, with its binding's protocol and topology (MFI-13.2)."""
    bindings = {binding.name: binding for binding in source.bindings}
    servers: List[Server] = []
    for service in source.services:
        for port in service.ports:
            if not port.location:
                continue
            binding = bindings.get(port.binding)
            extras: Dict[str, Any] = {"wsdl_service": service.name, "wsdl_binding": port.binding}
            if binding is not None:
                extras["wsdl_port_type"] = binding.port_type
                if binding.transport:
                    extras["wsdl_transport"] = binding.transport
            servers.append(
                Server(
                    url=port.location,
                    name=port.name,
                    description=f"{service.name}/{port.name}",
                    protocol=binding.protocol if binding is not None else None,
                    extras=extras,
                )
            )
    return servers


class WsdlNormalizer(Normalizer, register=True):
    """Normalize a parsed WSDL document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, WsdlDocument):
            raise ValueError("WSDL source must be a WsdlDocument (see app.wsdl_parser.parse_wsdl)")

        namespace = source.target_namespace
        type_names = frozenset(t.name for t in source.complex_types)
        element_to_type = {element.name: element.type_expr for element in source.elements}
        messages_by_name = {message.name: message for message in source.messages}

        types: List[Type] = []
        for complex_type in source.complex_types:
            type_key = _type_key(complex_type.name, namespace)
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    type_names=type_names,
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
                    extras={"wsdl_kind": "complexType"},
                )
            )

        message_type_list, message_types = _message_types(
            source, namespace=namespace, element_to_type=element_to_type, type_names=type_names
        )
        types.extend(message_type_list)

        services: List[Service] = []
        for port_type in source.port_types:
            service_key = Keys.type(port_type.name, namespace)
            operations: List[Operation] = []
            for operation in port_type.operations:
                op_key = Keys.operation_rpc(service_key, operation.name)
                messages: List[Message] = []
                input_message = messages_by_name.get(operation.input_message or "")
                output_message = messages_by_name.get(operation.output_message or "")
                request_payload = _operation_payload(
                    input_message,
                    operation.input_element,
                    namespace=namespace,
                    element_to_type=element_to_type,
                    type_names=type_names,
                    message_types=message_types,
                )
                if request_payload is not None:
                    messages.append(
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            payload=request_payload,
                            required=True,
                        )
                    )
                response_payload = _operation_payload(
                    output_message,
                    operation.output_element,
                    namespace=namespace,
                    element_to_type=element_to_type,
                    type_names=type_names,
                    message_types=message_types,
                )
                if response_payload is not None:
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=response_payload,
                        )
                    )
                messages.extend(
                    _fault_messages(
                        operation,
                        op_key,
                        messages_by_name=messages_by_name,
                        namespace=namespace,
                        element_to_type=element_to_type,
                        type_names=type_names,
                        message_types=message_types,
                    )
                )
                operations.append(
                    Operation(
                        key=op_key,
                        name=operation.name,
                        kind=operation_kind_for_pattern(operation.pattern),
                        streaming=StreamingMode.NONE,
                        messages=messages,
                        extras=soap_operation_extras(operation),
                    )
                )
            services.append(Service(key=service_key, name=port_type.name, operations=operations))

        servers = _servers(source)

        identity_name = _identity_name(source, [service.name for service in services])
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="soap",
            identity=ApiIdentity(name=identity_name, namespace=namespace),
            servers=servers,
            services=services,
            types=types,
            raw={"wsdl": source.raw} if include_raw else None,
            extras={
                "wsdl_target_namespace": source.target_namespace,
                **_version_extras(source),
                **_live_fetch_extras(source),
                **_wsi_extras(source),
            },
        )
        return normalize_ordering(api)
