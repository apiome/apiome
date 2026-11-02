"""Smithy IDL → canonical model normalizer.

Maps a parsed :class:`~app.smithy_parser.SmithyDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.RPC`.

MFI-17.2 (#3809) maps services, operations, resources, shapes and traits as the JSON AST gives them
(:mod:`app.smithy_ast_mapper`):

* **traits** — a member's ``@documentation`` is its description, ``@default`` its default,
  ``@length`` / ``@range`` / ``@pattern`` its constraints (a list's ``@length`` bounds its items),
  ``@deprecated`` marks it deprecated, and every other trait value is kept in
  ``extras["smithy_trait_values"]``;
* **operations** — ``@http`` sets ``http_method`` / ``http_path`` and the ``extras["http"]`` binding
  the OpenAPI projection reads; the input's ``@httpLabel`` / ``@httpQuery`` / ``@httpHeader`` members
  are its path, query and header parameters; ``@readonly`` / ``@idempotent`` / ``@paginated`` /
  ``@deprecated`` are recorded; each declared error, and each of its service's, is an ``error``
  message (status from the error's ``@httpError``);
* **resources** — a resource type records its identifiers, properties, lifecycle and children, and an
  operation a resource binds is tagged with it;
* **enums** — an ``@enumValue`` is the value's wire value; an ``intEnum`` is marked so.

The IDL reader (no Smithy CLI) gives trait names only, so its models carry none of this.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Set

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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, Normalizer, normalize_ordering
from .smithy_parser import SmithyDocument, SmithyField, SmithyOperation, SmithyService, SmithyStructure

__all__ = ["SmithyNormalizer"]

_FORMAT_KEY = "smithy"

_SMITHY_PRIMITIVES: Dict[str, str] = {
    "String": "string",
    "Integer": "integer",
    "Float": "float",
    "Double": "double",
    "Boolean": "boolean",
    "Blob": "bytes",
    "Timestamp": "datetime",
    "Document": "object",
    "BigInteger": "integer",
    "BigDecimal": "number",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    # A shape from another namespace of an assembled model is named by its absolute id
    # (``example.common#Money``, MFI-17.1), which already carries its namespace.
    if "#" in name:
        return name.replace("#", ".")
    return Keys.type(name, namespace)


def _type_ref(
    type_name: str,
    *,
    namespace: Optional[str],
    structure_names: Set[str],
    enum_names: Set[str],
    list_names: Set[str],
    map_names: Set[str],
    list_types: Dict[str, Type],
    map_types: Dict[str, Type],
) -> TypeRef:
    primitive = _SMITHY_PRIMITIVES.get(type_name)
    if primitive:
        return TypeRef(name=primitive, nullable=False)

    if type_name in list_names:
        list_type = list_types.get(type_name)
        if list_type and list_type.aliased:
            return TypeRef(name=list_type.key, nullable=False)
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    if type_name in map_names:
        map_type = map_types.get(type_name)
        if map_type:
            return TypeRef(name=map_type.key, nullable=False)
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    if type_name in enum_names or type_name in structure_names:
        return TypeRef(name=_type_key(type_name, namespace), nullable=False)

    return TypeRef(name=type_name, nullable=False)


def _canonical_field(
    field: SmithyField,
    *,
    type_key: str,
    namespace: Optional[str],
    structure_names: Set[str],
    enum_names: Set[str],
    list_names: Set[str],
    map_names: Set[str],
    list_types: Dict[str, Type],
    map_types: Dict[str, Type],
) -> CanonicalField:
    ref = _type_ref(
        field.type_name,
        namespace=namespace,
        structure_names=structure_names,
        enum_names=enum_names,
        list_names=list_names,
        map_names=map_names,
        list_types=list_types,
        map_types=map_types,
    )
    extras: Dict[str, Any] = {}
    if field.traits:
        extras["smithy_traits"] = list(field.traits)
    recorded = _recorded_traits(field.trait_values)
    if recorded:
        extras["smithy_trait_values"] = recorded
    return CanonicalField(
        key=Keys.field(type_key, field.name),
        name=field.name,
        type=TypeRef(
            name=ref.name,
            item=ref.item,
            nullable=not field.required,
            extras=ref.extras,
        ),
        default=field.trait_values.get("default"),
        constraints=_constraints(field.trait_values, collection=field.type_name in list_names),
        description=field.documentation,
        deprecated="deprecated" in field.trait_values,
        extras=extras,
    )


#: Traits the canonical field models itself, so they are not repeated in ``smithy_trait_values``.
_MODELED_FIELD_TRAITS = frozenset({"required", "documentation", "default", "length", "range", "pattern"})


def _recorded_traits(values: Mapping[str, Any]) -> Dict[str, Any]:
    """The trait values a field keeps in extras: every one the canonical field does not model."""
    return {key: value for key, value in values.items() if key not in _MODELED_FIELD_TRAITS}


def _number(value: Any) -> Optional[float]:
    """A trait bound as a number (``range`` bounds may be written as strings for big numbers)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _constraints(values: Mapping[str, Any], *, collection: bool) -> Optional[Constraints]:
    """``@length`` / ``@range`` / ``@pattern`` as canonical constraints (MFI-17.2).

    Args:
        values: The member's trait values.
        collection: Whether the member is a list, whose ``@length`` counts items, not characters.

    Returns:
        The constraints, or ``None`` when the member declares none.
    """
    length = values.get("length") if isinstance(values.get("length"), Mapping) else {}
    bounds = values.get("range") if isinstance(values.get("range"), Mapping) else {}
    pattern = values.get("pattern") if isinstance(values.get("pattern"), str) else None
    if not length and not bounds and pattern is None:
        return None
    low, high = length.get("min"), length.get("max")
    return Constraints(
        min_length=None if collection else low,
        max_length=None if collection else high,
        min_items=low if collection else None,
        max_items=high if collection else None,
        minimum=_number(bounds.get("min")),
        maximum=_number(bounds.get("max")),
        pattern=pattern,
    )


def _http_extras(op: SmithyOperation) -> Dict[str, Any]:
    """An operation's ``@http`` binding as ``extras["http"]`` (the projection's shape) plus its code."""
    http = op.trait_values.get("http")
    if not isinstance(http, Mapping):
        return {}
    if not isinstance(http.get("method"), str) or not isinstance(http.get("uri"), str):
        return {}
    extras: Dict[str, Any] = {"http": {"method": http["method"].lower(), "path": http["uri"]}}
    if isinstance(http.get("code"), int):
        extras["smithy_http_code"] = http["code"]
    return extras


def _operation_trait_extras(op: SmithyOperation) -> Dict[str, Any]:
    """The operation traits recorded in extras: ``readonly``, ``idempotent``, ``paginated``, ``deprecated``."""
    values = op.trait_values
    extras: Dict[str, Any] = {}
    for flag in ("readonly", "idempotent"):
        if flag in values:
            extras[f"smithy_{flag}"] = True
    if isinstance(values.get("paginated"), Mapping):
        extras["smithy_paginated"] = dict(values["paginated"])
    deprecated = values.get("deprecated")
    if isinstance(deprecated, Mapping) and deprecated:
        extras["smithy_deprecated"] = dict(deprecated)
    return extras


#: ``@httpLabel`` / ``@httpQuery`` / ``@httpHeader`` → the parameter location they bind to.
_HTTP_PARAMETER_TRAITS = (
    ("httpLabel", ParameterLocation.PATH),
    ("httpQuery", ParameterLocation.QUERY),
    ("httpHeader", ParameterLocation.HEADER),
)


def _http_parameters(
    op_key: str, input_shape: Optional[SmithyStructure], field_ref: Any
) -> List[Parameter]:
    """The input members an operation binds to its path, query string or headers (MFI-17.2).

    Args:
        op_key: The operation's key.
        input_shape: Its input structure, or ``None``.
        field_ref: Resolves a member's type name to a :class:`TypeRef`.

    Returns:
        One parameter per bound member, named as the HTTP request names it (a query or header
        trait's value), with the member's documentation and requiredness.
    """
    if input_shape is None:
        return []
    parameters: List[Parameter] = []
    for member in input_shape.fields:
        for trait, location in _HTTP_PARAMETER_TRAITS:
            if trait not in member.trait_values:
                continue
            bound = member.trait_values[trait]
            name = bound if isinstance(bound, str) and bound else member.name
            parameters.append(
                Parameter(
                    key=Keys.parameter(op_key, location.value, name),
                    name=name,
                    location=location,
                    required=member.required or location is ParameterLocation.PATH,
                    description=member.documentation,
                    type=field_ref(member.type_name),
                    constraints=_constraints(member.trait_values, collection=False),
                    extras={"smithy_member": member.name},
                )
            )
            break
    return parameters


def _resource_of(source: SmithyDocument) -> Dict[str, str]:
    """``{operation name: resource name}`` for every operation a resource binds directly."""
    bound: Dict[str, str] = {}
    for shape in source.structures:
        info = shape.resource
        if not info:
            continue
        names = [
            *info.get("lifecycle", {}).values(),
            *info.get("operations", []),
            *info.get("collection_operations", []),
        ]
        for name in names:
            bound.setdefault(name, shape.name)
    return bound


def _structure_extras(shape: SmithyStructure) -> Dict[str, Any]:
    """An error structure's ``@error`` / ``@httpError`` / ``@retryable``, and a resource's shape."""
    values = shape.trait_values
    extras: Dict[str, Any] = {}
    if isinstance(values.get("error"), str):
        extras["smithy_error"] = values["error"]
    if isinstance(values.get("httpError"), int):
        extras["smithy_http_error"] = values["httpError"]
    if "retryable" in values:
        extras["smithy_retryable"] = True
    if shape.resource:
        extras["smithy_resource"] = {key: value for key, value in shape.resource.items() if value}
    return extras


def _service_extras(svc: SmithyService) -> Dict[str, Any]:
    """A service's errors, resources and trait ids (its protocols, such as ``aws.protocols#restJson1``)."""
    extras: Dict[str, Any] = {}
    if svc.errors:
        extras["smithy_errors"] = list(svc.errors)
    if svc.resources:
        extras["smithy_resources"] = list(svc.resources)
    if svc.trait_values:
        extras["smithy_service_traits"] = sorted(svc.trait_values)
    return extras



#: Most ``smithy validate`` events recorded on a catalog item (the rest are counted, not listed).
MAX_RECORDED_EVENTS = 50


def _raw(source: SmithyDocument) -> Dict[str, str]:
    """The model's raw text: the root file, plus the assembled JSON AST for a multi-file set.

    ``smithy diff`` (MFI-17.4, :mod:`app.smithy_breaking`) compares whole models, and the root file
    alone is not the whole model when the set has several files.
    """
    raw = {"smithy": source.raw}
    if source.ast is not None and len(source.source_files) > 1:
        raw["smithy_ast"] = json.dumps(source.ast, sort_keys=True, ensure_ascii=False)
    return raw


def _validation_extras(source: SmithyDocument) -> Dict[str, Any]:
    """The model's validation events (MFI-17.3); empty when there are none, so a clean model is unchanged."""
    if not source.validation_events:
        return {}
    return {
        "smithy_validation_events": [dict(e) for e in source.validation_events[:MAX_RECORDED_EVENTS]],
        "smithy_validation_event_count": len(source.validation_events),
    }

class SmithyNormalizer(Normalizer, register=True):
    """Normalize a parsed Smithy document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.RPC

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, SmithyDocument):
            raise ValueError(
                "Smithy source must be a SmithyDocument (see app.smithy_parser.parse_smithy)"
            )

        namespace = source.namespace
        structure_names = {shape.name for shape in source.structures}
        enum_names = {enum.name for enum in source.enums}
        list_names = {lst.name for lst in source.lists}
        map_names = {mp.name for mp in source.maps}
        list_types: Dict[str, Type] = {}
        map_types: Dict[str, Type] = {}
        types: List[Type] = []

        for enum in source.enums:
            type_key = _type_key(enum.name, namespace)
            explicit = list(enum.enum_values) + [None] * (len(enum.values) - len(enum.enum_values))
            values = [
                EnumValue(
                    key=Keys.enum_value(type_key, value),
                    name=value,
                    # MFI-17.2: an @enumValue is the wire value; without one the position stays.
                    value=explicit[index] if explicit[index] is not None else index,
                )
                for index, value in enumerate(enum.values)
            ]
            types.append(
                Type(
                    key=type_key,
                    name=enum.name,
                    kind=TypeKind.ENUM,
                    namespace=namespace,
                    description=enum.documentation,
                    enum_values=values,
                    extras={"smithy_kind": "intEnum" if enum.int_enum else "enum"},
                )
            )

        for lst in source.lists:
            type_key = _type_key(lst.name, namespace)
            member_ref = _type_ref(
                lst.member,
                namespace=namespace,
                structure_names=structure_names,
                enum_names=enum_names,
                list_names=list_names,
                map_names=map_names,
                list_types=list_types,
                map_types=map_types,
            )
            list_type = Type(
                key=type_key,
                name=lst.name,
                kind=TypeKind.ALIAS,
                namespace=namespace,
                description=lst.documentation,
                aliased=TypeRef(item=member_ref, nullable=False),
                extras={"smithy_kind": "list"},
            )
            list_types[lst.name] = list_type
            types.append(list_type)

        for mp in source.maps:
            type_key = _type_key(mp.name, namespace)
            map_type = Type(
                key=type_key,
                name=mp.name,
                kind=TypeKind.MAP,
                namespace=namespace,
                description=mp.documentation,
                key_type=_type_ref(
                    mp.key,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                ),
                value_type=_type_ref(
                    mp.value,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                ),
                extras={"smithy_kind": "map"},
            )
            map_types[mp.name] = map_type
            types.append(map_type)

        for shape in source.structures:
            type_key = _type_key(shape.name, namespace)
            kind = TypeKind.UNION if shape.kind == "union" else TypeKind.RECORD
            fields = [
                _canonical_field(
                    field,
                    type_key=type_key,
                    namespace=namespace,
                    structure_names=structure_names,
                    enum_names=enum_names,
                    list_names=list_names,
                    map_names=map_names,
                    list_types=list_types,
                    map_types=map_types,
                )
                for field in shape.fields
            ]
            types.append(
                Type(
                    key=type_key,
                    name=shape.name,
                    kind=kind,
                    namespace=namespace,
                    description=shape.documentation,
                    fields=fields,
                    extras={"smithy_kind": shape.kind, **_structure_extras(shape)},
                )
            )

        operations_by_name = {op.name: op for op in source.operations}
        structures_by_name = {shape.name: shape for shape in source.structures}
        resource_of = _resource_of(source)

        def ref(type_name: str) -> TypeRef:
            return _type_ref(
                type_name,
                namespace=namespace,
                structure_names=structure_names,
                enum_names=enum_names,
                list_names=list_names,
                map_names=map_names,
                list_types=list_types,
                map_types=map_types,
            )

        services: List[Service] = []
        for svc in source.services:
            service_key = _type_key(svc.name, namespace)
            service_operations: List[Operation] = []
            for op_name in svc.operations:
                op = operations_by_name.get(op_name)
                if op is None:
                    continue
                op_key = Keys.operation_rpc(service_key, op.name)
                messages: List[Message] = []
                if op.input_type:
                    messages.append(
                        Message(
                            key=Keys.request_message(op_key),
                            role=MessageRole.REQUEST,
                            payload=_type_ref(
                                op.input_type,
                                namespace=namespace,
                                structure_names=structure_names,
                                enum_names=enum_names,
                                list_names=list_names,
                                map_names=map_names,
                                list_types=list_types,
                                map_types=map_types,
                            ),
                            required=True,
                        )
                    )
                if op.output_type:
                    messages.append(
                        Message(
                            key=f"{op_key}#response",
                            role=MessageRole.RESPONSE,
                            payload=_type_ref(
                                op.output_type,
                                namespace=namespace,
                                structure_names=structure_names,
                                enum_names=enum_names,
                                list_names=list_names,
                                map_names=map_names,
                                list_types=list_types,
                                map_types=map_types,
                            ),
                        )
                    )
                # MFI-17.2: the operation's declared errors, then its service's, each once.
                for error_name in dict.fromkeys([*op.errors, *svc.errors]):
                    error_shape = structures_by_name.get(error_name)
                    status = error_shape.trait_values.get("httpError") if error_shape is not None else None
                    messages.append(
                        Message(
                            key=f"{op_key}#error.{error_name}",
                            role=MessageRole.ERROR,
                            name=error_name.split("#")[-1],
                            payload=ref(error_name),
                            status_code=str(status) if isinstance(status, int) else None,
                            description=error_shape.documentation if error_shape is not None else None,
                        )
                    )
                http = op.trait_values.get("http") if isinstance(op.trait_values.get("http"), Mapping) else {}
                resource = resource_of.get(op.name)
                service_operations.append(
                    Operation(
                        key=op_key,
                        name=op.name,
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        description=op.documentation,
                        deprecated="deprecated" in op.trait_values,
                        http_method=http.get("method").upper() if isinstance(http.get("method"), str) else None,
                        http_path=http.get("uri") if isinstance(http.get("uri"), str) else None,
                        parameters=_http_parameters(
                            op_key, structures_by_name.get(op.input_type or ""), ref
                        ),
                        messages=messages,
                        tags=[resource] if resource else [],
                        extras={
                            **_http_extras(op),
                            **_operation_trait_extras(op),
                            **({"smithy_resource": resource} if resource else {}),
                        },
                    )
                )
            services.append(
                Service(
                    key=service_key,
                    name=svc.name,
                    description=svc.documentation,
                    operations=service_operations,
                    extras={
                        "smithy_version": svc.version,
                        "smithy_operations": list(svc.operations),
                        **_service_extras(svc),
                    },
                )
            )

        title = (
            source.services[0].name
            if source.services
            else (namespace or "Smithy API")
        )
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            protocol="smithy",
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            services=services,
            types=types,
            raw=_raw(source) if include_raw else None,
            extras={
                "smithy_version": source.version,
                "smithy_namespace": namespace,
                # MFI-17.1: an assembled model's namespaces, AST hash and model files.
                **({"smithy_namespaces": list(source.namespaces)} if source.namespaces else {}),
                **({"smithy_ast_sha256": source.model_sha256} if source.model_sha256 else {}),
                **({"smithy_source_files": list(source.source_files)} if source.source_files else {}),
                # MFI-17.3: `smithy validate` events (smithy-linters included), for the `smithy` pack.
                **_validation_extras(source),
                # MFI-17.2: each shape's AST hash, keyed by absolute shape id.
                **({"smithy_shape_hashes": dict(source.shape_hashes)} if source.shape_hashes else {}),
            },
        )
        return normalize_ordering(api)
