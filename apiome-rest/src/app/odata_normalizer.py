"""OData CSDL / EDMX → canonical model normalizer — MFI-22.1.

Maps a parsed :class:`~app.odata_parser.ODataDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

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
from .odata_parser import (
    ODataComplexType,
    ODataDocument,
    ODataEntitySet,
    ODataEntityType,
    ODataEnumType,
    ODataProperty,
)

__all__ = ["ODataNormalizer"]

_FORMAT_KEY = "odata"

_EDM_BASE_TO_CANONICAL: Dict[str, str] = {
    "Edm.String": "string",
    "Edm.Boolean": "bool",
    "Edm.Byte": "uint8",
    "Edm.SByte": "int8",
    "Edm.Int16": "i16",
    "Edm.Int32": "i32",
    "Edm.Int64": "i64",
    "Edm.Single": "float",
    "Edm.Double": "double",
    "Edm.Decimal": "double",
    "Edm.Guid": "string",
    "Edm.Date": "string",
    "Edm.DateTimeOffset": "string",
    "Edm.TimeOfDay": "string",
    "Edm.Binary": "bytes",
    "Edm.Stream": "bytes",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _qualified_name(namespace: str, name: str) -> str:
    return f"{namespace}.{name}"


def _split_qualified(type_expr: str) -> tuple[Optional[str], str]:
    if "." in type_expr:
        namespace, name = type_expr.rsplit(".", 1)
        return namespace, name
    return None, type_expr


def _type_ref_from_expr(
    type_expr: str,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
    qualified_names: frozenset[str],
) -> TypeRef:
    collection_match = re.fullmatch(r"Collection\((.+)\)", type_expr.strip())
    if collection_match:
        inner = _type_ref_from_expr(
            collection_match.group(1).strip(),
            namespace=namespace,
            type_names=type_names,
            qualified_names=qualified_names,
        )
        return TypeRef(name=inner.name, item=inner, nullable=False)

    mapped = _EDM_BASE_TO_CANONICAL.get(type_expr)
    if mapped:
        return TypeRef(name=mapped, nullable=True)
    if type_expr in qualified_names:
        _, local = _split_qualified(type_expr)
        return TypeRef(name=_type_key(local, namespace), nullable=True)
    if type_expr in type_names:
        return TypeRef(name=_type_key(type_expr, namespace), nullable=True)
    local = type_expr.split(".")[-1]
    return TypeRef(name=_type_key(local, namespace), nullable=True)


def _constraints_for_property(prop: ODataProperty) -> Optional[Constraints]:
    return None


def _canonical_field(
    prop: ODataProperty,
    *,
    parent_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    qualified_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    type_ref = _type_ref_from_expr(
        prop.type_expr,
        namespace=namespace,
        type_names=type_names,
        qualified_names=qualified_names,
    )
    if prop.nullable is not None:
        type_ref = type_ref.model_copy(update={"nullable": prop.nullable})
    return CanonicalField(
        key=Keys.field(parent_key, prop.name),
        name=prop.name,
        type=type_ref,
        field_number=field_number,
        constraints=_constraints_for_property(prop),
        extras={"odata_type": prop.type_expr},
    )


def _entity_set_operations(
    entity_set: ODataEntitySet,
    *,
    namespace: Optional[str],
    entity_types_by_qualified: Dict[str, ODataEntityType],
) -> List[Operation]:
    entity_type = entity_types_by_qualified.get(entity_set.entity_type)
    if entity_type is None:
        _, local = _split_qualified(entity_set.entity_type)
        entity_type = entity_types_by_qualified.get(local)
    payload = TypeRef(name=_type_key(entity_type.name, namespace)) if entity_type else None
    service_key = Keys.type(entity_set.name, namespace)
    operations: List[Operation] = []

    list_key = Keys.operation_http("GET", f"/{entity_set.name}")
    operations.append(
        Operation(
            key=list_key,
            name=f"list{entity_set.name}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="GET",
            http_path=f"/{entity_set.name}",
            parameters=[
                Parameter(
                    key=Keys.parameter(list_key, "query", "$top"),
                    name="$top",
                    location=ParameterLocation.QUERY,
                    type=TypeRef(name="i32"),
                )
            ],
            messages=[
                Message(
                    key=f"{list_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="200",
                    content_types=["application/json"],
                    payload=payload,
                )
            ],
            extras={"odata_entity_set": entity_set.name, "odata_operation": "list"},
        )
    )

    get_key = Keys.operation_http("GET", f"/{entity_set.name}({{key}})")
    operations.append(
        Operation(
            key=get_key,
            name=f"get{entity_set.name.rstrip('s')}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="GET",
            http_path=f"/{entity_set.name}({{key}})",
            messages=[
                Message(
                    key=f"{get_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="200",
                    content_types=["application/json"],
                    payload=payload,
                )
            ],
            extras={"odata_entity_set": entity_set.name, "odata_operation": "get"},
        )
    )

    create_key = Keys.operation_http("POST", f"/{entity_set.name}")
    operations.append(
        Operation(
            key=create_key,
            name=f"create{entity_set.name.rstrip('s')}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="POST",
            http_path=f"/{entity_set.name}",
            messages=[
                Message(
                    key=f"{create_key}#request",
                    role=MessageRole.REQUEST,
                    content_types=["application/json"],
                    payload=payload,
                    required=True,
                ),
                Message(
                    key=f"{create_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="201",
                    content_types=["application/json"],
                    payload=payload,
                ),
            ],
            extras={"odata_entity_set": entity_set.name, "odata_operation": "create"},
        )
    )

    return operations


class ODataNormalizer(Normalizer, register=True):
    """Normalize a parsed OData document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, ODataDocument):
            raise ValueError(
                "OData source must be an ODataDocument (see app.odata_parser.parse_odata)"
            )

        primary_schema = source.schemas[0]
        namespace = primary_schema.namespace
        type_names = frozenset(
            entity.name for schema in source.schemas for entity in schema.entity_types
        ) | frozenset(
            complex_type.name for schema in source.schemas for complex_type in schema.complex_types
        ) | frozenset(enum_type.name for schema in source.schemas for enum_type in schema.enum_types)
        qualified_names = frozenset(
            _qualified_name(schema.namespace, entity.name)
            for schema in source.schemas
            for entity in schema.entity_types
        ) | frozenset(
            _qualified_name(schema.namespace, complex_type.name)
            for schema in source.schemas
            for complex_type in schema.complex_types
        ) | frozenset(
            _qualified_name(schema.namespace, enum_type.name)
            for schema in source.schemas
            for enum_type in schema.enum_types
        )

        types: List[Type] = []
        entity_types_by_qualified: Dict[str, ODataEntityType] = {}

        for schema in source.schemas:
            for enum_type in schema.enum_types:
                type_key = _type_key(enum_type.name, namespace)
                types.append(self._enum_type(enum_type, type_key=type_key))

            for complex_type in schema.complex_types:
                type_key = _type_key(complex_type.name, namespace)
                types.append(
                    self._record_type(
                        complex_type,
                        type_key=type_key,
                        namespace=namespace,
                        type_names=type_names,
                        qualified_names=qualified_names,
                        kind="complex",
                    )
                )

            for entity_type in schema.entity_types:
                qualified = _qualified_name(schema.namespace, entity_type.name)
                entity_types_by_qualified[qualified] = entity_type
                entity_types_by_qualified[entity_type.name] = entity_type
                type_key = _type_key(entity_type.name, namespace)
                nav_extras = [
                    {
                        "name": nav.name,
                        "type": nav.type_expr,
                        "partner": nav.partner,
                    }
                    for nav in entity_type.navigation_properties
                ]
                types.append(
                    Type(
                        key=type_key,
                        name=entity_type.name,
                        kind=TypeKind.RECORD,
                        namespace=namespace,
                        fields=tuple(
                            _canonical_field(
                                prop,
                                parent_key=type_key,
                                namespace=namespace,
                                type_names=type_names,
                                qualified_names=qualified_names,
                                field_number=index,
                            )
                            for index, prop in enumerate(entity_type.properties, start=1)
                        ),
                        extras={
                            "odata_kind": "entity",
                            "odata_key_properties": list(entity_type.key_properties),
                            "odata_navigation_properties": nav_extras,
                        },
                    )
                )

        services: List[Service] = []
        entity_sets: List[Dict[str, str]] = []
        for schema in source.schemas:
            container = schema.entity_container
            if container is None:
                continue
            for entity_set in container.entity_sets:
                entity_sets.append(
                    {
                        "name": entity_set.name,
                        "entity_type": entity_set.entity_type,
                    }
                )
                service_key = Keys.type(entity_set.name, namespace)
                services.append(
                    Service(
                        key=service_key,
                        name=entity_set.name,
                        operations=_entity_set_operations(
                            entity_set,
                            namespace=namespace,
                            entity_types_by_qualified=entity_types_by_qualified,
                        ),
                    )
                )

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=namespace, namespace=namespace),
            version=source.version,
            services=services,
            types=types,
            raw={"odata": source.raw} if include_raw else None,
            extras={
                "odata_version": source.version,
                "odata_schemas": [
                    {
                        "namespace": schema.namespace,
                        "entity_container": (
                            {
                                "name": schema.entity_container.name,
                                "entity_sets": [
                                    {
                                        "name": entity_set.name,
                                        "entity_type": entity_set.entity_type,
                                    }
                                    for entity_set in schema.entity_container.entity_sets
                                ],
                            }
                            if schema.entity_container
                            else None
                        ),
                        "entity_types": [
                            {
                                "name": entity.name,
                                "key_properties": list(entity.key_properties),
                                "properties": [
                                    {
                                        "name": prop.name,
                                        "type": prop.type_expr,
                                        "nullable": prop.nullable,
                                    }
                                    for prop in entity.properties
                                ],
                                "navigation_properties": [
                                    {
                                        "name": nav.name,
                                        "type": nav.type_expr,
                                        "partner": nav.partner,
                                    }
                                    for nav in entity.navigation_properties
                                ],
                            }
                            for entity in schema.entity_types
                        ],
                        "complex_types": [
                            {
                                "name": complex_type.name,
                                "properties": [
                                    {
                                        "name": prop.name,
                                        "type": prop.type_expr,
                                        "nullable": prop.nullable,
                                    }
                                    for prop in complex_type.properties
                                ],
                            }
                            for complex_type in schema.complex_types
                        ],
                        "enum_types": [
                            {
                                "name": enum_type.name,
                                "members": [
                                    {"name": member.name, "value": member.value}
                                    for member in enum_type.members
                                ],
                            }
                            for enum_type in schema.enum_types
                        ],
                    }
                    for schema in source.schemas
                ],
                "odata_entity_sets": entity_sets,
            },
        )
        return normalize_ordering(api)

    def _enum_type(self, enum_type: ODataEnumType, *, type_key: str) -> Type:
        return Type(
            key=type_key,
            name=enum_type.name,
            kind=TypeKind.ENUM,
            enum_values=tuple(
                EnumValue(
                    key=Keys.enum_value(type_key, member.name),
                    name=member.name,
                    value=member.value if member.value is not None else index,
                )
                for index, member in enumerate(enum_type.members)
            ),
            extras={"odata_kind": "enum"},
        )

    def _record_type(
        self,
        complex_type: ODataComplexType,
        *,
        type_key: str,
        namespace: Optional[str],
        type_names: frozenset[str],
        qualified_names: frozenset[str],
        kind: str,
    ) -> Type:
        return Type(
            key=type_key,
            name=complex_type.name,
            kind=TypeKind.RECORD,
            namespace=namespace,
            fields=tuple(
                _canonical_field(
                    prop,
                    parent_key=type_key,
                    namespace=namespace,
                    type_names=type_names,
                    qualified_names=qualified_names,
                    field_number=index,
                )
                for index, prop in enumerate(complex_type.properties, start=1)
            ),
            extras={"odata_kind": kind},
        )
