"""RAML → canonical model normalizer — MFI-16.2.

Maps a parsed :class:`~app.raml_parser.RamlDocument` into a
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
from .raml_parser import RamlDocument, RamlOperation, RamlParameter, RamlTypeField

__all__ = ["RamlNormalizer"]

_FORMAT_KEY = "raml"

_RAMl_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "number": "double",
    "integer": "i32",
    "boolean": "bool",
    "object": "object",
    "array": "array",
    "date-only": "string",
    "time-only": "string",
    "datetime-only": "string",
    "datetime": "string",
    "file": "bytes",
    "nil": "null",
    "any": "string",
}

_PARAM_LOCATIONS = {
    "path": ParameterLocation.PATH,
    "query": ParameterLocation.QUERY,
    "header": ParameterLocation.HEADER,
}


def _type_key(name: str) -> str:
    return Keys.type(name, None)


def _type_ref_from_expr(type_expr: str, *, type_names: frozenset[str]) -> TypeRef:
    expr = type_expr.strip()
    if expr.endswith("[]"):
        inner = expr[:-2].strip()
        return TypeRef(item=_type_ref_from_expr(inner, type_names=type_names))
    mapped = _RAMl_TO_CANONICAL.get(expr)
    if mapped:
        return TypeRef(name=mapped)
    if expr in type_names:
        return TypeRef(name=_type_key(expr))
    return TypeRef(name=expr)


def _canonical_field(
    field: RamlTypeField,
    *,
    type_key: str,
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    type_ref = _type_ref_from_expr(field.type_expr, type_names=type_names)
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=TypeRef(
            name=type_ref.name,
            item=type_ref.item,
            nullable=not field.required,
        ),
        field_number=field_number,
        description=field.description,
        extras={"raml_type": field.type_expr},
    )


def _parameter(param: RamlParameter, *, operation_key: str, type_names: frozenset[str]) -> Parameter:
    location = _PARAM_LOCATIONS.get(param.location, ParameterLocation.QUERY)
    return Parameter(
        key=Keys.parameter(operation_key, param.location, param.name),
        name=param.name,
        location=location,
        required=param.required,
        description=param.description,
        type=_type_ref_from_expr(param.type_expr, type_names=type_names),
        extras={"raml_type": param.type_expr},
    )


class RamlNormalizer(Normalizer, register=True):
    """Normalize a parsed RAML document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, RamlDocument):
            raise ValueError("RAML source must be a RamlDocument (see app.raml_parser.parse_raml)")

        type_names = frozenset(t.name for t in source.types)
        types: List[Type] = []

        for raml_type in source.types:
            type_key = _type_key(raml_type.name)
            if raml_type.enum_values:
                values = [
                    EnumValue(
                        key=Keys.enum_value(type_key, value),
                        name=value,
                        value=index,
                    )
                    for index, value in enumerate(raml_type.enum_values)
                ]
                types.append(
                    Type(
                        key=type_key,
                        name=raml_type.name,
                        kind=TypeKind.ENUM,
                        description=raml_type.description,
                        enum_values=values,
                        extras={"raml_kind": "enum"},
                    )
                )
                continue
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    type_names=type_names,
                    field_number=index + 1,
                )
                for index, field in enumerate(raml_type.fields)
            ]
            types.append(
                Type(
                    key=type_key,
                    name=raml_type.name,
                    kind=TypeKind.RECORD,
                    description=raml_type.description,
                    fields=fields,
                    extras={"raml_kind": "object"},
                )
            )

        operations: List[Operation] = []
        for endpoint in source.operations:
            op_key = Keys.operation_http(endpoint.method.upper(), endpoint.path)
            messages: List[Message] = []
            if endpoint.request_type:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=_type_ref_from_expr(endpoint.request_type, type_names=type_names),
                    )
                )
            for status, response_type in endpoint.response_types:
                messages.append(
                    Message(
                        key=Keys.response_message(op_key, status),
                        role=MessageRole.RESPONSE,
                        payload=_type_ref_from_expr(response_type, type_names=type_names),
                        extras={"http_status": status},
                    )
                )
            operations.append(
                Operation(
                    key=op_key,
                    name=f"{endpoint.method.upper()} {endpoint.path}",
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    description=endpoint.description,
                    http_method=endpoint.method.upper(),
                    http_path=endpoint.path,
                    parameters=[
                        _parameter(param, operation_key=op_key, type_names=type_names)
                        for param in endpoint.parameters
                    ],
                    messages=messages,
                )
            )

        service_key = Keys.type(source.title, None)
        services = [Service(key=service_key, name=source.title, operations=operations)]

        servers: List[Server] = []
        if source.base_uri:
            url = source.base_uri
            if source.version:
                url = url.replace("{version}", source.version)
            servers.append(Server(url=url, description="From RAML baseUri"))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=source.title),
            title=source.title,
            description=source.description,
            version=source.version,
            servers=servers,
            services=services,
            types=types,
            raw={"raml": source.raw} if include_raw else None,
            extras={
                "raml_version": source.raml_version,
                "raml_media_type": source.media_type,
            },
        )
        return normalize_ordering(api)
