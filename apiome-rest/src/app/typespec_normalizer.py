"""Microsoft TypeSpec → canonical model normalizer — MFI-22.3.

Maps a parsed :class:`~app.typespec_parser.TypeSpecDocument` into a
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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .typespec_parser import (
    TypeSpecDocument,
    TypeSpecEnum,
    TypeSpecField,
    TypeSpecInterface,
    TypeSpecModel,
    TypeSpecOperation,
    TypeSpecParameter,
)

__all__ = ["TypeSpecNormalizer"]

_FORMAT_KEY = "typespec"

_TYPESPEC_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "boolean": "bool",
    "int32": "i32",
    "int64": "i64",
    "float32": "float",
    "float64": "double",
    "bytes": "bytes",
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
    is_array: bool = False,
) -> TypeRef:
    expr = type_expr.strip()
    if expr.endswith("[]"):
        inner = _type_ref_from_expr(
            expr[:-2].strip(),
            namespace=namespace,
            type_names=type_names,
        )
        return TypeRef(name=inner.name, item=inner, nullable=False)
    mapped = _TYPESPEC_TO_CANONICAL.get(expr)
    if mapped:
        ref = TypeRef(name=mapped, nullable=True)
    elif expr in type_names:
        ref = TypeRef(name=_type_key(expr, namespace), nullable=True)
    else:
        ref = TypeRef(name=_type_key(expr, namespace), nullable=True)
    if is_array:
        return TypeRef(name=ref.name, item=ref, nullable=False)
    return ref


def _canonical_field(
    field: TypeSpecField,
    *,
    parent_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    type_ref = _type_ref_from_expr(
        field.type_expr,
        namespace=namespace,
        type_names=type_names,
    )
    if not field.optional:
        type_ref = type_ref.model_copy(update={"nullable": False})
    key_decorators = [decorator for decorator in field.decorators if "@key" in decorator]
    return CanonicalField(
        key=Keys.field(parent_key, field.name),
        name=field.name,
        type=type_ref,
        field_number=field_number,
        description=field.documentation,
        extras={
            "typespec_type": field.type_expr,
            "typespec_optional": field.optional,
            "typespec_decorators": list(field.decorators),
            "typespec_key": bool(key_decorators),
        },
    )


def _parameter(
    param: TypeSpecParameter,
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
        required=param.location in {"path", "body"},
        type=_type_ref_from_expr(
            param.type_expr,
            namespace=namespace,
            type_names=type_names,
        ),
        extras={"typespec_type": param.type_expr, "typespec_location": param.location},
    )


def _operation_path(route_prefix: Optional[str], operation: TypeSpecOperation) -> str:
    base = route_prefix or ""
    path_params = [param.name for param in operation.parameters if param.location == "path"]
    if path_params:
        suffix = "/".join(f"{{{name}}}" for name in path_params)
        if base.endswith("/"):
            return f"{base}{suffix}"
        return f"{base}/{suffix}" if base else f"/{suffix}"
    return base or "/"


def _operation_messages(
    operation: TypeSpecOperation,
    *,
    operation_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> List[Message]:
    messages: List[Message] = []
    body_params = [param for param in operation.parameters if param.location == "body"]
    if body_params:
        body = body_params[0]
        messages.append(
            Message(
                key=Keys.request_message(operation_key),
                role=MessageRole.REQUEST,
                content_types=["application/json"],
                payload=_type_ref_from_expr(
                    body.type_expr,
                    namespace=namespace,
                    type_names=type_names,
                ),
                required=True,
            )
        )
    if operation.return_type and operation.return_type != "void":
        messages.append(
            Message(
                key=Keys.response_message(operation_key, "200"),
                role=MessageRole.RESPONSE,
                status_code="200",
                content_types=["application/json"],
                payload=_type_ref_from_expr(
                    operation.return_type,
                    namespace=namespace,
                    type_names=type_names,
                    is_array=operation.is_array_return,
                ),
            )
        )
    return messages


def _interface_operations(
    interface: TypeSpecInterface,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> List[Operation]:
    operations: List[Operation] = []
    for operation in interface.operations:
        http_path = _operation_path(interface.route_prefix, operation)
        op_key = Keys.operation_http(operation.verb.upper(), http_path)
        operations.append(
            Operation(
                key=op_key,
                name=operation.name,
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.NONE,
                description=operation.documentation,
                http_method=operation.verb.upper(),
                http_path=http_path,
                parameters=[
                    _parameter(
                        param,
                        operation_key=op_key,
                        namespace=namespace,
                        type_names=type_names,
                    )
                    for param in operation.parameters
                    if param.location != "body"
                ],
                messages=_operation_messages(
                    operation,
                    operation_key=op_key,
                    namespace=namespace,
                    type_names=type_names,
                ),
                extras={
                    "typespec_interface": interface.name,
                    "typespec_route_prefix": interface.route_prefix,
                    "typespec_verb": operation.verb,
                },
            )
        )
    return operations


def _enum_type(enum_type: TypeSpecEnum, *, type_key: str) -> Type:
    return Type(
        key=type_key,
        name=enum_type.name,
        kind=TypeKind.ENUM,
        description=enum_type.documentation,
        enum_values=tuple(
            EnumValue(
                key=Keys.enum_value(type_key, value),
                name=value,
                value=index,
            )
            for index, value in enumerate(enum_type.values)
        ),
        extras={"typespec_kind": "enum", "typespec_values": list(enum_type.values)},
    )


def _model_type(
    model: TypeSpecModel,
    *,
    type_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> Type:
    key_fields = [
        field.name
        for field in model.fields
        if any("@key" in decorator for decorator in field.decorators)
    ]
    return Type(
        key=type_key,
        name=model.name,
        kind=TypeKind.RECORD,
        namespace=namespace,
        description=model.documentation,
        fields=tuple(
            _canonical_field(
                field,
                parent_key=type_key,
                namespace=namespace,
                type_names=type_names,
                field_number=index,
            )
            for index, field in enumerate(model.fields, start=1)
        ),
        extras={
            "typespec_kind": "model",
            "typespec_key_fields": key_fields,
        },
    )


class TypeSpecNormalizer(Normalizer, register=True):
    """Normalize a parsed TypeSpec document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, TypeSpecDocument):
            raise ValueError(
                "TypeSpec source must be a TypeSpecDocument (see app.typespec_parser.parse_typespec)"
            )

        namespace = source.namespace
        type_names = frozenset(
            name
            for name in (
                *[enum_type.name for enum_type in source.enums],
                *[model.name for model in source.models],
            )
        )

        types: List[Type] = []
        for enum_type in source.enums:
            types.append(_enum_type(enum_type, type_key=_type_key(enum_type.name, namespace)))
        for model in source.models:
            types.append(
                _model_type(
                    model,
                    type_key=_type_key(model.name, namespace),
                    namespace=namespace,
                    type_names=type_names,
                )
            )

        services: List[Service] = []
        for interface in source.interfaces:
            service_key = Keys.type(interface.name, namespace)
            services.append(
                Service(
                    key=service_key,
                    name=interface.name,
                    description=interface.documentation,
                    operations=_interface_operations(
                        interface,
                        namespace=namespace,
                        type_names=type_names,
                    ),
                    extras={"typespec_route_prefix": interface.route_prefix},
                )
            )

        api_name = source.service_title or namespace or "TypeSpec API"
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=api_name, namespace=namespace),
            services=services,
            types=types,
            raw={"typespec": source.raw} if include_raw else None,
            extras={
                "typespec_namespace": namespace,
                "typespec_service_title": source.service_title,
                "typespec_imports": list(source.imports),
                "typespec_usings": list(source.usings),
                "typespec_enums": [
                    {
                        "name": enum_type.name,
                        "values": list(enum_type.values),
                        "documentation": enum_type.documentation,
                    }
                    for enum_type in source.enums
                ],
                "typespec_models": [
                    {
                        "name": model.name,
                        "documentation": model.documentation,
                        "fields": [
                            {
                                "name": field.name,
                                "type": field.type_expr,
                                "optional": field.optional,
                                "decorators": list(field.decorators),
                                "documentation": field.documentation,
                            }
                            for field in model.fields
                        ],
                    }
                    for model in source.models
                ],
                "typespec_interfaces": [
                    {
                        "name": interface.name,
                        "route_prefix": interface.route_prefix,
                        "documentation": interface.documentation,
                        "operations": [
                            {
                                "name": operation.name,
                                "verb": operation.verb,
                                "return_type": operation.return_type,
                                "is_array_return": operation.is_array_return,
                                "documentation": operation.documentation,
                                "parameters": [
                                    {
                                        "name": param.name,
                                        "type": param.type_expr,
                                        "location": param.location,
                                    }
                                    for param in operation.parameters
                                ],
                            }
                            for operation in interface.operations
                        ],
                    }
                    for interface in source.interfaces
                ],
            },
        )
        return normalize_ordering(api)
