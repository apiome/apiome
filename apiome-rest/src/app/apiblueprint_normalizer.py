"""API Blueprint → canonical model normalizer.

Maps a parsed :class:`~app.apiblueprint_parser.ApiblueprintDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.

An ``array[T]`` body is an array of ``T``; a response's status is its ``status_code``. A
``+ Default:`` value is read as the member's type says (``5`` for a ``number``, ``true`` for a
``boolean``).

MFI-16.2 (#3805): a resource group is each of its operations' tag (and ``extras["apib_group"]``);
request and response ``+ Headers`` become the message's headers; an inline body is a type of its own
(``extras["apib_inline"]``); MSON inheritance and ``+ Include`` mixins are flattened — a type lists
its base's members, then each mixin's, then its own (a later member of the same name wins) — with
the base and mixins recorded in ``extras``; an inline enum member or parameter is a ``string`` with
``Constraints.enum``; ``nullable`` makes a reference nullable even when it is required.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .apiblueprint_parser import (
    ApiblueprintDocument,
    ApiblueprintField,
    ApiblueprintParameter,
    ApiblueprintType,
)
from .apiblueprint_refract import DRAFTER_VERSION, REFRACT_ALGORITHM, refract_sha256
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


def _enum_constraints(type_expr: str, values: tuple) -> Optional[Constraints]:
    """``Constraints.enum`` for an inline ``enum[…]`` member or parameter with ``+ Members``."""
    if not values:
        return None
    return Constraints(enum=list(values))


def _enum_ref(type_expr: str, values: tuple, ref: TypeRef) -> TypeRef:
    """An inline enum is its member type (``enum[string]`` → ``string``); anything else is ``ref``."""
    match = re.fullmatch(r"enum\[(.+)\]", type_expr.strip(), re.IGNORECASE)
    if not match:
        return TypeRef(name="string", nullable=False) if values and type_expr.strip().lower() == "enum" else ref
    inner = _APIB_TO_CANONICAL.get(match.group(1).strip().lower(), "string")
    return TypeRef(name=inner, nullable=False)


def _canonical_field(
    field: ApiblueprintField,
    *,
    type_key: str,
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    ref = _enum_ref(
        field.type_expr, field.enum_values, _type_ref_from_expr(field.type_expr, type_names=type_names)
    )
    extras: Dict[str, Any] = {"apib_type": field.type_expr}
    if field.sample is not None:
        extras["apib_sample"] = field.sample
    if field.nullable:
        extras["apib_nullable"] = True
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=field.nullable or not field.required,
            extras=ref.extras,
        ),
        field_number=field_number,
        default=default_value(field.default, field.type_expr),
        constraints=_enum_constraints(field.type_expr, field.enum_values),
        description=field.description,
        extras=extras,
    )


def flattened_fields(
    apib_type: ApiblueprintType, types_by_name: Dict[str, ApiblueprintType]
) -> List[ApiblueprintField]:
    """A type's members with its base's and its mixins' flattened in (MFI-16.2).

    MSON inheritance (``## Cat (Pet)``) and mixins (``+ Include Problem``) both give a type the
    members of another: the base's first, then each mixin's in order, then its own. A member named
    again later replaces the earlier one in place. A cycle (``A`` includes ``B`` includes ``A``) or a
    type the document does not define contributes nothing.

    Args:
        apib_type: The type.
        types_by_name: Every named type of the document.

    Returns:
        Its effective members, in order.
    """

    def collect(current: ApiblueprintType, seen: frozenset) -> List[ApiblueprintField]:
        members: Dict[str, ApiblueprintField] = {}
        parents = ([current.base] if current.base else []) + list(current.includes)
        for parent_name in parents:
            parent = types_by_name.get(parent_name)
            if parent is None or parent.name in seen:
                continue
            for member in collect(parent, seen | {parent.name}):
                members[member.name] = member
        for member in current.fields:
            members[member.name] = member
        return list(members.values())

    return collect(apib_type, frozenset({apib_type.name}))


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
        type=_enum_ref(
            param.type_expr, param.enum_values, _type_ref_from_expr(param.type_expr, type_names=type_names)
        ),
        constraints=_enum_constraints(param.type_expr, param.enum_values),
        extras={"apib_type": param.type_expr},
    )


def _headers(owner_key: str, headers: tuple) -> List[CanonicalField]:
    """``+ Headers`` lines as message headers: a ``string`` each, its example value in extras."""
    return [
        CanonicalField(
            key=Keys.field(owner_key, name),
            name=name,
            type=TypeRef(name="string", nullable=False),
            field_number=index + 1,
            extras={"apib_sample": value} if value else {},
        )
        for index, (name, value) in enumerate(headers)
    ]



#: Most drafter annotations recorded on a catalog item (the rest are counted, not listed).
MAX_RECORDED_ANNOTATIONS = 50


def _refract_extras(source: ApiblueprintDocument) -> Dict[str, Any]:
    """The Refract contract hash drafter's parse result yields (MFI-16.1); empty without drafter.

    Kept out of the version fingerprint (:data:`app.fingerprint.UNHASHED_EXTRAS`): a server with
    drafter and one without must mint the same version for the same blueprint.
    """
    digest = refract_sha256(source.refract)
    if digest is None:
        return {}
    return {
        "apib_refract_sha256": digest,
        "apib_refract_algorithm": REFRACT_ALGORITHM,
        "apib_drafter_version": DRAFTER_VERSION,
    }


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
        types_by_name = {item.name: item for item in source.types}
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
                for index, field in enumerate(flattened_fields(apib_type, types_by_name))
            ]
            extras: Dict[str, Any] = {"apib_kind": apib_type.kind}
            if apib_type.base:
                extras["apib_base"] = apib_type.base
            if apib_type.includes:
                extras["apib_includes"] = list(apib_type.includes)
            if apib_type.inline:
                extras["apib_inline"] = True
            types.append(
                Type(
                    key=type_key,
                    name=apib_type.name,
                    kind=TypeKind.RECORD,
                    description=apib_type.description,
                    fields=fields,
                    extras=extras,
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
                        headers=_headers(Keys.request_message(op_key), endpoint.request_headers),
                    )
                )
            for status, media_type, response_type, headers in endpoint.responses:
                response_key = Keys.response_message(op_key, status)
                messages.append(
                    Message(
                        key=response_key,
                        role=MessageRole.RESPONSE,
                        payload=_type_ref_from_expr(response_type, type_names=type_names) if response_type else None,
                        content_types=[media_type] if media_type else [],
                        status_code=status,
                        headers=_headers(response_key, headers),
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
                    tags=[endpoint.group] if endpoint.group else [],
                    extras={"apib_group": endpoint.group} if endpoint.group else {},
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
            raw=(
                {"apiblueprint": source.raw, **({"refract": source.refract} if source.refract else {})}
                if include_raw
                else None
            ),
            extras={
                "apib_format_version": source.format_version,
                "apib_host": source.host,
                # MFI-16.3: drafter's annotations, for the `apiblueprint` lint pack (omitted when none).
                **_drafter_extras(source),
                # MFI-16.1: the hash of drafter's Refract tree, without prose and examples.
                **_refract_extras(source),
            },
        )
        return normalize_ordering(api)
