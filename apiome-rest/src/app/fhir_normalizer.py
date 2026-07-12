"""HL7 FHIR R4 → canonical model normalizer — MFI-22.2.

Maps a parsed :class:`~app.fhir_parser.FhirDocument` into a
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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from .fhir_parser import (
    FhirDocument,
    FhirElement,
    FhirInferredField,
    FhirResourceProfile,
    FhirStructureDefinition,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["FhirNormalizer"]

_FORMAT_KEY = "fhir"

_FHIR_BASE_TO_CANONICAL: Dict[str, str] = {
    "string": "string",
    "code": "string",
    "id": "string",
    "uri": "string",
    "url": "string",
    "uuid": "string",
    "markdown": "string",
    "oid": "string",
    "canonical": "string",
    "boolean": "bool",
    "integer": "i32",
    "positiveInt": "i32",
    "unsignedInt": "i32",
    "decimal": "double",
    "date": "string",
    "dateTime": "string",
    "instant": "string",
    "time": "string",
    "base64Binary": "bytes",
}


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def _type_ref_from_fhir_code(
    code: str,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
    is_array: bool = False,
) -> TypeRef:
    mapped = _FHIR_BASE_TO_CANONICAL.get(code)
    if mapped:
        ref = TypeRef(name=mapped, nullable=True)
    elif code in type_names:
        ref = TypeRef(name=_type_key(code, namespace), nullable=True)
    else:
        ref = TypeRef(name=_type_key(code, namespace), nullable=True)
    if is_array:
        return TypeRef(name=ref.name, item=ref, nullable=False)
    return ref


def _canonical_field_from_element(
    element: FhirElement,
    *,
    parent_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    primary = element.types[0]
    is_array = element.max not in {"0", "1"}
    type_ref = _type_ref_from_fhir_code(
        primary.code,
        namespace=namespace,
        type_names=type_names,
        is_array=is_array,
    )
    if element.min > 0:
        type_ref = type_ref.model_copy(update={"nullable": False})
    return CanonicalField(
        key=Keys.field(parent_key, element.field_name),
        name=element.field_name,
        type=type_ref,
        field_number=field_number,
        description=element.short,
        extras={
            "fhir_type": primary.code,
            "fhir_path": element.path,
            "fhir_min": element.min,
            "fhir_max": element.max,
            "fhir_profiles": [item.profile for item in element.types if item.profile],
        },
    )


def _canonical_field_from_inferred(
    field: FhirInferredField,
    *,
    parent_key: str,
    namespace: Optional[str],
    type_names: frozenset[str],
    field_number: int,
) -> CanonicalField:
    type_ref = _type_ref_from_fhir_code(
        field.type_expr,
        namespace=namespace,
        type_names=type_names,
        is_array=field.is_array,
    )
    if not field.nullable:
        type_ref = type_ref.model_copy(update={"nullable": False})
    return CanonicalField(
        key=Keys.field(parent_key, field.name),
        name=field.name,
        type=type_ref,
        field_number=field_number,
        extras={"fhir_type": field.type_expr, "fhir_inferred": True},
    )


def _resource_operations(resource_type: str, *, namespace: Optional[str], payload: Optional[TypeRef]) -> List[Operation]:
    service_key = Keys.type(resource_type, namespace)
    operations: List[Operation] = []

    search_key = Keys.operation_http("GET", f"/{resource_type}")
    operations.append(
        Operation(
            key=search_key,
            name=f"search{resource_type}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="GET",
            http_path=f"/{resource_type}",
            parameters=[
                Parameter(
                    key=Keys.parameter(search_key, "query", "_count"),
                    name="_count",
                    location=ParameterLocation.QUERY,
                    type=TypeRef(name="i32"),
                )
            ],
            messages=[
                Message(
                    key=f"{search_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="200",
                    content_types=["application/fhir+json"],
                    payload=payload,
                )
            ],
            extras={"fhir_interaction": "search-type"},
        )
    )

    read_key = Keys.operation_http("GET", f"/{resource_type}/{{id}}")
    operations.append(
        Operation(
            key=read_key,
            name=f"read{resource_type}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="GET",
            http_path=f"/{resource_type}/{{id}}",
            messages=[
                Message(
                    key=f"{read_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="200",
                    content_types=["application/fhir+json"],
                    payload=payload,
                )
            ],
            extras={"fhir_interaction": "read"},
        )
    )

    create_key = Keys.operation_http("POST", f"/{resource_type}")
    operations.append(
        Operation(
            key=create_key,
            name=f"create{resource_type}",
            kind=OperationKind.REQUEST_RESPONSE,
            streaming=StreamingMode.NONE,
            http_method="POST",
            http_path=f"/{resource_type}",
            messages=[
                Message(
                    key=f"{create_key}#request",
                    role=MessageRole.REQUEST,
                    content_types=["application/fhir+json"],
                    payload=payload,
                    required=True,
                ),
                Message(
                    key=f"{create_key}#response",
                    role=MessageRole.RESPONSE,
                    status_code="201",
                    content_types=["application/fhir+json"],
                    payload=payload,
                ),
            ],
            extras={"fhir_interaction": "create"},
        )
    )
    return operations


def _structure_to_type(
    structure: FhirStructureDefinition,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> Type:
    type_key = _type_key(structure.resource_type, namespace)
    fields = tuple(
        _canonical_field_from_element(
            element,
            parent_key=type_key,
            namespace=namespace,
            type_names=type_names,
            field_number=index,
        )
        for index, element in enumerate(structure.elements, start=1)
    )
    return Type(
        key=type_key,
        name=structure.resource_type,
        kind=TypeKind.RECORD,
        namespace=namespace,
        fields=fields,
        extras={"fhir_kind": "resource"},
    )


def _profile_to_type(
    profile: FhirResourceProfile,
    *,
    namespace: Optional[str],
    type_names: frozenset[str],
) -> Type:
    type_key = _type_key(profile.resource_type, namespace)
    fields = tuple(
        _canonical_field_from_inferred(
            field,
            parent_key=type_key,
            namespace=namespace,
            type_names=type_names,
            field_number=index,
        )
        for index, field in enumerate(profile.fields, start=1)
    )
    return Type(
        key=type_key,
        name=profile.resource_type,
        kind=TypeKind.RECORD,
        namespace=namespace,
        fields=fields,
        extras={"fhir_kind": "resource", "fhir_inferred": True},
    )


class FhirNormalizer(Normalizer, register=True):
    """Normalize a parsed FHIR document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, FhirDocument):
            raise ValueError(
                "FHIR source must be a FhirDocument (see app.fhir_parser.parse_fhir)"
            )

        if source.kind == "structure_definition" and source.structure_definition is not None:
            return self._normalize_structure_definition(source, include_raw=include_raw)
        if source.kind == "resource_profile" and source.resource_profile is not None:
            return self._normalize_resource_profile(source, include_raw=include_raw)
        raise ValueError("FHIR document is missing structure or resource profile content")

    def _normalize_structure_definition(
        self,
        source: FhirDocument,
        *,
        include_raw: bool,
    ) -> CanonicalApi:
        structure = source.structure_definition
        assert structure is not None
        namespace = structure.name
        complex_codes = frozenset(
            element.types[0].code
            for element in structure.elements
            if element.types[0].code not in _FHIR_BASE_TO_CANONICAL
        )
        type_names = frozenset({structure.resource_type}) | complex_codes

        types: List[Type] = [_structure_to_type(structure, namespace=namespace, type_names=type_names)]
        for code in sorted(complex_codes):
            types.append(
                Type(
                    key=_type_key(code, namespace),
                    name=code,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    extras={"fhir_kind": "complex", "fhir_placeholder": True},
                )
            )

        payload = TypeRef(name=_type_key(structure.resource_type, namespace))
        services = [
            Service(
                key=Keys.type(structure.resource_type, namespace),
                name=structure.resource_type,
                operations=_resource_operations(
                    structure.resource_type,
                    namespace=namespace,
                    payload=payload,
                ),
            )
        ]

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=structure.name, namespace=namespace),
            title=structure.name,
            services=services,
            types=types,
            raw={"fhir": source.raw} if include_raw else None,
            extras={
                "fhir_kind": "structure_definition",
                "fhir_structure_definition": {
                    "id": structure.id,
                    "url": structure.url,
                    "name": structure.name,
                    "status": structure.status,
                    "kind": structure.kind,
                    "type": structure.resource_type,
                    "abstract": structure.abstract,
                    "baseDefinition": structure.base_definition,
                    "derivation": structure.derivation,
                    "elements": [
                        {
                            "path": element.path,
                            "field_name": element.field_name,
                            "min": element.min,
                            "max": element.max,
                            "types": [
                                {"code": item.code, "profile": item.profile}
                                for item in element.types
                            ],
                            "short": element.short,
                        }
                        for element in structure.elements
                    ],
                },
            },
        )
        return normalize_ordering(api)

    def _normalize_resource_profile(
        self,
        source: FhirDocument,
        *,
        include_raw: bool,
    ) -> CanonicalApi:
        profile = source.resource_profile
        assert profile is not None
        namespace = profile.resource_type
        complex_codes = frozenset(
            field.type_expr
            for field in profile.fields
            if field.type_expr not in _FHIR_BASE_TO_CANONICAL
        )
        type_names = frozenset({profile.resource_type}) | complex_codes

        types: List[Type] = [_profile_to_type(profile, namespace=namespace, type_names=type_names)]
        for code in sorted(complex_codes):
            types.append(
                Type(
                    key=_type_key(code, namespace),
                    name=code,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    extras={"fhir_kind": "complex", "fhir_placeholder": True},
                )
            )

        payload = TypeRef(name=_type_key(profile.resource_type, namespace))
        services = [
            Service(
                key=Keys.type(profile.resource_type, namespace),
                name=profile.resource_type,
                operations=_resource_operations(
                    profile.resource_type,
                    namespace=namespace,
                    payload=payload,
                ),
            )
        ]

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=profile.resource_type, namespace=namespace),
            title=profile.resource_type,
            services=services,
            types=types,
            raw={"fhir": source.raw} if include_raw else None,
            extras={
                "fhir_kind": "resource_profile",
                "fhir_resource_profile": {
                    "resource_type": profile.resource_type,
                    "fields": [
                        {
                            "name": field.name,
                            "type": field.type_expr,
                            "nullable": field.nullable,
                            "is_array": field.is_array,
                        }
                        for field in profile.fields
                    ],
                },
            },
        )
        return normalize_ordering(api)
