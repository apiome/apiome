"""WSDL → canonical model normalizer — MFI-15.2.

Maps a parsed :class:`~app.wsdl_parser.WsdlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`. XSD complex types become
:class:`~app.canonical_model.Type` records; portType operations become
:class:`~app.canonical_model.Service` / :class:`~app.canonical_model.Operation` pairs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .wsdl_parser import WsdlDocument, WsdlField, WsdlMessage

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
        extras={"xsd_type": field.type_expr},
    )


def _message_payload(
    message: Optional[WsdlMessage],
    *,
    namespace: Optional[str],
    element_to_type: Dict[str, str],
    type_names: frozenset[str],
) -> Optional[TypeRef]:
    if message is None or not message.parts:
        return None
    part = message.parts[0]
    if part.element and part.element in element_to_type:
        type_name = element_to_type[part.element]
        return TypeRef(name=_type_key(type_name, namespace))
    if part.type_name:
        return _type_ref_from_expr(part.type_name, namespace=namespace, type_names=type_names)
    return None


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

        services: List[Service] = []
        for port_type in source.port_types:
            service_key = Keys.type(port_type.name, namespace)
            operations: List[Operation] = []
            for operation in port_type.operations:
                op_key = Keys.operation_rpc(service_key, operation.name)
                messages: List[Message] = []
                input_message = messages_by_name.get(operation.input_message or "")
                output_message = messages_by_name.get(operation.output_message or "")
                request_payload = _message_payload(
                    input_message,
                    namespace=namespace,
                    element_to_type=element_to_type,
                    type_names=type_names,
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
                response_payload = _message_payload(
                    output_message,
                    namespace=namespace,
                    element_to_type=element_to_type,
                    type_names=type_names,
                )
                if response_payload is not None:
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=response_payload,
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
            services.append(Service(key=service_key, name=port_type.name, operations=operations))

        servers: List[Server] = []
        for service in source.services:
            for port in service.ports:
                if port.location:
                    servers.append(
                        Server(
                            url=port.location,
                            description=f"{service.name}/{port.name}",
                        )
                    )

        identity_name = source.name or (services[0].name if services else "WSDL service")
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
            },
        )
        return normalize_ordering(api)
