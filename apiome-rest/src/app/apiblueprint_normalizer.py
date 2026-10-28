"""API Blueprint → canonical model normalizer.

Maps a parsed :class:`~app.apiblueprint_parser.ApiblueprintDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.

An ``array[T]`` body is an array of ``T``; a response's status is its ``status_code``. A
``+ Default:`` value is read as the member's type says (``5`` for a ``number``, ``true`` for a
``boolean``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .apiblueprint_parser import (
    ApiblueprintDocument,
    ApiblueprintField,
    ApiblueprintParameter,
)
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

__all__ = ["ApiblueprintNormalizer", "default_value"]

_FORMAT_KEY = "apiblueprint"

_APIB_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "number": "double",
    "boolean": "bool",
    "object": "object",
    "array": "array",
}


def _type_key(name: str) -> str:
    return Keys.type(name, None)


def _array_inner(type_expr: str) -> Optional[str]:
    match = re.fullmatch(r"array\[(.+)\]", type_expr.strip())
    return match.group(1).strip() if match else None


def _type_ref_from_expr(type_expr: str, *, type_names: frozenset[str]) -> TypeRef:
    expr = type_expr.strip()
    array_inner = _array_inner(expr)
    if array_inner:
        return TypeRef(item=_type_ref_from_expr(array_inner, type_names=type_names), nullable=False)
    mapped = _APIB_TO_CANONICAL.get(expr.lower())
    if mapped:
        return TypeRef(name=mapped, nullable=False)
    if expr in type_names:
        return TypeRef(name=_type_key(expr), nullable=False)
    return TypeRef(name=expr, nullable=False)


def default_value(raw: Optional[str], type_expr: str) -> Any:
    """A ``+ Default:`` value as its MSON type says: a number or boolean literal, else the text.

    Args:
        raw: The value as written, or ``None``.
        type_expr: The member's MSON type (``number``, ``boolean``, ``string`` …).

    Returns:
        ``None`` for no default; an ``int`` / ``float`` for a ``number``; a ``bool`` for a
        ``boolean`` written ``true`` / ``false``; else ``raw``.
    """
    if raw is None:
        return None
    kind = type_expr.strip().lower()
    if kind == "number":
        try:
            number = float(raw)
        except ValueError:
            return raw
        return int(number) if number.is_integer() and "." not in raw else number
    if kind == "boolean" and raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    return raw


def _canonical_field(
    field: ApiblueprintField,
    *,
    type_key: str,
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    ref = _type_ref_from_expr(field.type_expr, type_names=type_names)
    extras: Dict[str, Any] = {"apib_type": field.type_expr}
    if field.sample is not None:
        extras["apib_sample"] = field.sample
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=not field.required,
            extras=ref.extras,
        ),
        field_number=field_number,
        default=default_value(field.default, field.type_expr),
        description=field.description,
        extras=extras,
    )


def _parameter(
    param: ApiblueprintParameter,
    *,
    operation_key: str,
    type_names: frozenset[str],
) -> Parameter:
    location = ParameterLocation.QUERY if param.location == "query" else ParameterLocation.PATH
    return Parameter(
        key=Keys.parameter(operation_key, location.value, param.name),
        name=param.name,
        location=location,
        required=param.required,
        default=default_value(param.default, param.type_expr),
        description=param.description,
        type=_type_ref_from_expr(param.type_expr, type_names=type_names),
        extras={"apib_type": param.type_expr},
    )



#: Most drafter annotations recorded on a catalog item (the rest are counted, not listed).
MAX_RECORDED_ANNOTATIONS = 50


def _drafter_extras(source: ApiblueprintDocument) -> Dict[str, Any]:
    """drafter's annotations (MFI-16.3); empty when there are none, so a clean model is unchanged."""
    if not source.drafter_annotations:
        return {}
    return {
        "apib_drafter_annotations": [dict(a) for a in source.drafter_annotations[:MAX_RECORDED_ANNOTATIONS]],
        "apib_drafter_annotation_count": len(source.drafter_annotations),
    }

class ApiblueprintNormalizer(Normalizer, register=True):
    """Normalize a parsed API Blueprint document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, ApiblueprintDocument):
            raise ValueError(
                "API Blueprint source must be an ApiblueprintDocument "
                "(see app.apiblueprint_parser.parse_apiblueprint)"
            )

        type_names = frozenset(item.name for item in source.types)
        types: List[Type] = []

        for apib_type in source.types:
            type_key = _type_key(apib_type.name)
            if apib_type.kind == "enum" or apib_type.enum_values:
                values = [
                    EnumValue(
                        key=Keys.enum_value(type_key, value),
                        name=value,
                        value=index,
                    )
                    for index, value in enumerate(apib_type.enum_values)
                ]
                types.append(
                    Type(
                        key=type_key,
                        name=apib_type.name,
                        kind=TypeKind.ENUM,
                        description=apib_type.description,
                        enum_values=values,
                        extras={"apib_kind": "enum"},
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
                for index, field in enumerate(apib_type.fields)
            ]
            types.append(
                Type(
                    key=type_key,
                    name=apib_type.name,
                    kind=TypeKind.RECORD,
                    description=apib_type.description,
                    fields=fields,
                    extras={"apib_kind": apib_type.kind},
                )
            )

        operations: List[Operation] = []
        for endpoint in source.operations:
            op_key = Keys.operation_http(endpoint.method, endpoint.path)
            messages: List[Message] = []
            if endpoint.request_type:
                messages.append(
                    Message(
                        key=Keys.request_message(op_key),
                        role=MessageRole.REQUEST,
                        payload=_type_ref_from_expr(endpoint.request_type, type_names=type_names),
                        required=True,
                        content_types=[endpoint.request_media_type]
                        if endpoint.request_media_type
                        else [],
                    )
                )
            for status, media_type, response_type in endpoint.responses:
                messages.append(
                    Message(
                        key=Keys.response_message(op_key, status),
                        role=MessageRole.RESPONSE,
                        payload=_type_ref_from_expr(response_type, type_names=type_names) if response_type else None,
                        content_types=[media_type] if media_type else [],
                        status_code=status,
                    )
                )
            operations.append(
                Operation(
                    key=op_key,
                    name=endpoint.name,
                    kind=OperationKind.REQUEST_RESPONSE,
                    streaming=StreamingMode.NONE,
                    description=endpoint.description,
                    http_method=endpoint.method,
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
        if source.host:
            servers.append(Server(url=source.host, description="From API Blueprint HOST"))

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="http",
            identity=ApiIdentity(name=source.title),
            title=source.title,
            description=source.description,
            servers=servers,
            services=services,
            types=types,
            raw={"apiblueprint": source.raw} if include_raw else None,
            extras={
                "apib_format_version": source.format_version,
                "apib_host": source.host,
                # MFI-16.3: drafter's annotations, for the `apiblueprint` lint pack (omitted when none).
                **_drafter_extras(source),
            },
        )
        return normalize_ordering(api)
