"""WADL → canonical model normalizer — MFI-17.2.

Maps a parsed :class:`~app.wadl_parser.WadlDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.
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
from .wadl_parser import WadlDocument, WadlField, WadlOperation, WadlParameter

__all__ = ["WadlNormalizer"]

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
}

_PARAM_LOCATIONS = {
    "path": ParameterLocation.PATH,
    "query": ParameterLocation.QUERY,
    "header": ParameterLocation.HEADER,
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
    field: WadlField,
    *,
    type_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    type_ref = _type_ref_from_expr(field.type_expr, namespace=namespace, type_names=type_names)
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=type_ref,
        field_number=field_number,
        extras={"wadl_type": field.type_expr},
    )


def _parameter(
    param: WadlParameter,
    *,
    operation_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> Parameter:
    location = _PARAM_LOCATIONS.get(param.location, ParameterLocation.QUERY)
    return Parameter(
        key=Keys.parameter(operation_key, param.location, param.name),
        name=param.name,
        location=location,
        required=param.required,
        type=_type_ref_from_expr(param.type_expr, namespace=namespace, type_names=type_names),
        extras={"wadl_type": param.type_expr},
    )


class WadlNormalizer(Normalizer, register=True):
    """Normalize a parsed WADL document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, WadlDocument):
            raise ValueError("WADL source must be a WadlDocument (see app.wadl_parser.parse_wadl)")

        namespace = source.target_namespace
        type_names = frozenset(t.name for t in source.complex_types)
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
                    extras={"wadl_kind": "complexType"},
                )
            )

        operations: List[Operation] = []
        for endpoint in source.operations:
            op_key = Keys.operation_http(endpoint.method.upper(), endpoint.path)
            op_name = endpoint.operation_id or f"{endpoint.method.upper()} {endpoint.path}"
            messages: List[Message] = []
            if endpoint.request_type:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=_type_ref_from_expr(
                            endpoint.request_type,
                            namespace=namespace,
                            type_names=type_names,
                        ),
                    )
                )
            for status, response_type in endpoint.response_types:
                payload = (
                    _type_ref_from_expr(
                        response_type,
                        namespace=namespace,
                        type_names=type_names,
                    )
                    if response_type
                    else None
                )
                messages.append(
                    Message(
                        key=Keys.response_message(op_key, status),
                        role=MessageRole.RESPONSE,
                        payload=payload,
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
            },
        )
        return normalize_ordering(api)
