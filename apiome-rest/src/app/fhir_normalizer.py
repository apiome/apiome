"""HL7 FHIR → canonical model normalizer — MFI-22.2, extended by MFI-20.1.

Maps a parsed :class:`~app.fhir_parser.FhirDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.

A **CapabilityStatement** (MFI-20.1) becomes the server's API: one service per resource type, with
an operation for each interaction the server *declares* (read, vread, search-type with its search
parameters, create, update, patch, delete, history) and each ``$operation``; the resource payloads
are placeholder types naming the profile they conform to, since profiles are imported as their own
StructureDefinitions. Every FHIR model records the FHIR version it targets and its release
(``fhir_version`` / ``fhir_release`` extras, R4 / R4B / R5 / R6), which the fingerprint hashes —
so a profile or server moving between releases is a new version with a change report.
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
    FhirCapabilityResource,
    FhirCapabilityStatement,
    FhirDocument,
    FhirElement,
    FhirInferredField,
    FhirResourceProfile,
    FhirStructureDefinition,
    fhir_release,
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


#: FHIR search-parameter types → canonical scalars (a token, reference or quantity is a string on the wire).
_SEARCH_PARAM_TYPES: Dict[str, str] = {"number": "double"}

_FHIR_JSON = ["application/fhir+json"]


def _version_extras(version: Optional[str]) -> Dict[str, Any]:
    """The ``fhir_version`` / ``fhir_release`` extras a FHIR model records (MFI-20.1).

    Empty when the document names no ``fhirVersion``: extras are hashed into the fingerprint, so a
    ``null`` key would change the fingerprint of every profile imported before MFI-20.1 and mint
    a version on its next identical re-import.
    """
    if not version:
        return {}
    return {"fhir_version": version, "fhir_release": fhir_release(version)}


def _response(key: str, status: str, payload: Optional[TypeRef]) -> Message:
    return Message(key=f"{key}#response", role=MessageRole.RESPONSE, status_code=status,
                   content_types=list(_FHIR_JSON), payload=payload)


def _request(key: str, payload: Optional[TypeRef]) -> Message:
    return Message(key=f"{key}#request", role=MessageRole.REQUEST, content_types=list(_FHIR_JSON),
                   payload=payload, required=True)


def _path_params(key: str, names: List[str]) -> List[Parameter]:
    return [
        Parameter(key=Keys.parameter(key, "path", name), name=name, location=ParameterLocation.PATH,
                  type=TypeRef(name="string"), required=True)
        for name in names
    ]


#: Interaction code → (method, path suffix, path parameters, request body, response status).
_INTERACTIONS: Dict[str, tuple] = {
    "read": ("GET", "/{id}", ["id"], False, "200"),
    "vread": ("GET", "/{id}/_history/{vid}", ["id", "vid"], False, "200"),
    "update": ("PUT", "/{id}", ["id"], True, "200"),
    "patch": ("PATCH", "/{id}", ["id"], True, "200"),
    "delete": ("DELETE", "/{id}", ["id"], False, "204"),
    "history-instance": ("GET", "/{id}/_history", ["id"], False, "200"),
    "history-type": ("GET", "/_history", [], False, "200"),
    "create": ("POST", "", [], True, "201"),
    "search-type": ("GET", "", [], False, "200"),
}

_INTERACTION_NAMES = {
    "read": "read", "vread": "vread", "update": "update", "patch": "patch", "delete": "delete",
    "history-instance": "history", "history-type": "historyAll", "create": "create", "search-type": "search",
}


def _capability_operations(
    resource: FhirCapabilityResource, *, payload: TypeRef
) -> List[Operation]:
    """The operations a server declares for one resource type, in declaration order."""
    base = f"/{resource.type}"
    operations: List[Operation] = []
    for code in resource.interactions:
        shape = _INTERACTIONS.get(code)
        if shape is None:
            continue  # an unknown interaction code is the server's own extension; nothing to map
        method, suffix, path_names, has_body, status = shape
        path = base + suffix
        key = Keys.operation_http(method, path)
        parameters = _path_params(key, path_names)
        if code == "search-type":
            parameters += [
                Parameter(
                    key=Keys.parameter(key, "query", param.name),
                    name=param.name,
                    location=ParameterLocation.QUERY,
                    type=TypeRef(name=_SEARCH_PARAM_TYPES.get(param.type, "string")),
                    description=param.documentation,
                    extras={"fhir_search_type": param.type},
                )
                for param in resource.search_params
            ]
        messages = ([_request(key, payload)] if has_body else []) + [
            _response(key, status, None if status == "204" else payload)
        ]
        operations.append(
            Operation(
                key=key,
                name=f"{_INTERACTION_NAMES[code]}{resource.type}",
                kind=OperationKind.REQUEST_RESPONSE,
                streaming=StreamingMode.NONE,
                http_method=method,
                http_path=path,
                parameters=parameters,
                messages=messages,
                extras={"fhir_interaction": code},
            )
        )
    for op in resource.operations:
        operations.append(_dollar_operation(f"{base}/${op.name}", op.name, op.definition))
    return operations


def _dollar_operation(path: str, name: str, definition: Optional[str]) -> Operation:
    """A ``$operation`` invoked with ``POST`` and a ``Parameters`` resource."""
    key = Keys.operation_http("POST", path)
    return Operation(
        key=key,
        name=f"${name}",
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        http_method="POST",
        http_path=path,
        messages=[_request(key, None), _response(key, "200", None)],
        extras={"fhir_interaction": "operation", "fhir_operation_definition": definition},
    )


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

        if source.kind == "logical" and source.logical is not None:
            from .fhir_logical import logical_resources, normalize_logical

            return normalize_logical(source.logical, logical_resources(source.logical) or [], raw=source.raw,
                                     include_raw=include_raw)
        if source.kind == "structure_definition" and source.structure_definition is not None:
            return self._normalize_structure_definition(source, include_raw=include_raw)
        if source.kind == "capability_statement" and source.capability_statement is not None:
            return self._normalize_capability_statement(source, include_raw=include_raw)
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
                **_version_extras(structure.fhir_version),
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
                            # Only when present, so pre-MFI-20.1 fingerprints stay put.
                            **({"definition": element.definition} if element.definition else {}),
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

    def _normalize_capability_statement(
        self,
        source: FhirDocument,
        *,
        include_raw: bool,
    ) -> CanonicalApi:
        """A server's CapabilityStatement → one service per resource type (MFI-20.1)."""
        statement: FhirCapabilityStatement = source.capability_statement  # type: ignore[assignment]
        namespace = statement.name
        types: List[Type] = []
        services: List[Service] = []
        for resource in statement.resources:
            type_key = _type_key(resource.type, namespace)
            types.append(
                Type(
                    key=type_key,
                    name=resource.type,
                    kind=TypeKind.RECORD,
                    namespace=namespace,
                    description=resource.documentation,
                    extras={
                        "fhir_kind": "resource",
                        "fhir_placeholder": True,
                        "fhir_profile": resource.profile,
                        "fhir_supported_profiles": list(resource.supported_profiles),
                    },
                )
            )
            services.append(
                Service(
                    key=type_key,
                    name=resource.type,
                    operations=_capability_operations(resource, payload=TypeRef(name=type_key)),
                )
            )
        if statement.system_operations:
            services.append(
                Service(
                    key=Keys.type("system", namespace),
                    name="system",
                    operations=[_dollar_operation(f"/${op.name}", op.name, op.definition)
                                for op in statement.system_operations],
                )
            )

        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=statement.name, namespace=namespace),
            title=statement.name,
            version=statement.version,
            services=services,
            types=types,
            raw={"fhir": source.raw} if include_raw else None,
            extras={
                "fhir_kind": "capability_statement",
                **_version_extras(statement.fhir_version),
                "fhir_capability_statement": {
                    "url": statement.url,
                    "version": statement.version,
                    "status": statement.status,
                    "software": statement.software,
                    "baseUrl": statement.base_url,
                    "formats": list(statement.formats),
                    "systemInteractions": list(statement.system_interactions),
                    "resources": [
                        {
                            "type": r.type,
                            "profile": r.profile,
                            "supportedProfiles": list(r.supported_profiles),
                            "interactions": list(r.interactions),
                            "searchParams": [p.name for p in r.search_params],
                            "operations": [o.name for o in r.operations],
                        }
                        for r in statement.resources
                    ],
                },
            },
        )
        return normalize_ordering(api)
