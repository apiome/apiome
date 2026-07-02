"""End-to-end tests for the OpenAPI 3.1 emitter — MFI-22.1 (#4002).

Exercises the acceptance criterion: a canonical model covering ``>= 1`` REST,
``>= 1`` RPC, and ``>= 1`` data-schema source emits a schema-valid OpenAPI 3.1
document (validated against the OpenAPI 3.1 meta-schema), emission is
deterministic, and every emitted value carries a provenance tag. The REST case is
additionally checked to be a *fixed point* of ``normalize ∘ emit`` — the tightest
statement that the emitter is the inverse of the reference normalizer.
"""

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind, Provenance
from app.openapi_emitter import OpenApiEmitter
from app.openapi_normalizer import OpenApiNormalizer
from app.openapi_validator import validate_openapi_document

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _petstore_openapi() -> dict:
    """A small but representative OpenAPI 3.1 document (REST source)."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.4.0", "description": "Pets API"},
        "servers": [
            {
                "url": "https://api.example.com/{ver}",
                "description": "prod",
                "variables": {"ver": {"default": "v1", "enum": ["v1", "v2"]}},
            }
        ],
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "summary": "Get a pet",
                    "tags": ["pets"],
                    "deprecated": True,
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                        },
                        {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "headers": {"X-Rate-Limit": {"schema": {"type": "integer"}}},
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        },
                        "404": {"description": "not found"},
                    },
                },
                "post": {
                    "operationId": "replacePet",
                    "tags": ["pets"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "name": {"type": "string", "minLength": 1},
                        "nick": {"type": "string"},
                        "status": {"$ref": "#/components/schemas/Status"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "Status": {"type": "string", "enum": ["active", "inactive"]},
            }
        },
    }


def _rpc_model() -> CanonicalApi:
    """A canonical model as a gRPC/RPC normalizer would produce (no HTTP binding)."""
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        protocol="grpc",
        identity=ApiIdentity(name="Pet Service"),
        services=[
            Service(
                key="acme.PetService",
                name="PetService",
                operations=[
                    Operation(
                        key="acme.PetService.GetPet",
                        name="GetPet",
                        kind=OperationKind.REQUEST_RESPONSE,
                        streaming=StreamingMode.NONE,
                        messages=[
                            Message(
                                key="acme.PetService.GetPet#request",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="GetPetRequest", nullable=False),
                            ),
                            Message(
                                key="acme.PetService.GetPet#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="Pet", nullable=False),
                            ),
                        ],
                    )
                ],
            )
        ],
        types=[
            Type(
                key="Pet",
                name="Pet",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="Pet.id",
                        name="id",
                        type=TypeRef(name="string", nullable=False),
                        field_number=1,
                    )
                ],
            ),
            Type(
                key="GetPetRequest",
                name="GetPetRequest",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="GetPetRequest.id",
                        name="id",
                        type=TypeRef(name="string", nullable=False),
                        field_number=1,
                    )
                ],
            ),
        ],
    )


def _data_schema_model() -> CanonicalApi:
    """A canonical model as a data-schema (Avro/JSON-Schema) normalizer would produce."""
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="avro",
        identity=ApiIdentity(name="User Record"),
        types=[
            Type(
                key="User",
                name="User",
                kind=TypeKind.RECORD,
                fields=[
                    CanonicalField(
                        key="User.email",
                        name="email",
                        type=TypeRef(name="string", nullable=False),
                        constraints=Constraints(format="email"),
                    )
                ],
            )
        ],
    )


def _emit_openapi(model: CanonicalApi):
    return OpenApiEmitter().emit(model)


# ---------------------------------------------------------------------------
# Acceptance criterion: schema-valid output for REST / RPC / data-schema
# ---------------------------------------------------------------------------


def test_rest_source_emits_schema_valid_document() -> None:
    model = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    doc = _emit_openapi(model).document
    assert validate_openapi_document(doc) == []
    assert doc["openapi"] == "3.1.0"
    assert doc["info"] == {"title": "Pet Store", "version": "1.4.0", "description": "Pets API"}
    # Path item carries both methods; the deprecated GET is preserved.
    get = doc["paths"]["/pets/{id}"]["get"]
    assert get["operationId"] == "getPet"
    assert get["summary"] == "Get a pet"
    assert get["tags"] == ["pets"]
    assert get["deprecated"] is True


def test_rpc_source_emits_schema_valid_best_effort_binding() -> None:
    result = _emit_openapi(_rpc_model())
    assert validate_openapi_document(result.document) == []
    # The method with no HTTP annotation gets a synthesized POST /{Service}/{Method}
    # binding (the gRPC-transcoding/JSON convention).
    assert list(result.document["paths"]) == ["/acme.PetService/GetPet"]
    operation = result.document["paths"]["/acme.PetService/GetPet"]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/GetPetRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Pet"
    }
    # The synthesized binding is flagged INFERRED for the fidelity analyzer.
    binding = next(
        r for r in result.provenance if r.pointer == "/paths/~1acme.PetService~1GetPet/post"
    )
    assert binding.provenance is Provenance.INFERRED
    # The RPC projection also reports the inferred binding in its loss set.
    assert any(
        loss.kind is LossKind.INFERRED and loss.pointer == "acme.PetService.GetPet"
        for loss in result.losses
    )


def test_data_schema_source_emits_components_only_document() -> None:
    result = _emit_openapi(_data_schema_model())
    assert validate_openapi_document(result.document) == []
    assert result.document["paths"] == {}
    assert result.document["components"]["schemas"]["User"] == {
        "type": "object",
        "properties": {"email": {"type": "string", "format": "email"}},
        "required": ["email"],
    }


# ---------------------------------------------------------------------------
# Determinism & round-trip fidelity
# ---------------------------------------------------------------------------


def test_emission_is_deterministic() -> None:
    model = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    first = _emit_openapi(model)
    second = _emit_openapi(model)
    assert first.document == second.document
    assert first.model_dump() == second.model_dump()  # provenance too


def test_rest_conversion_is_a_fixed_point() -> None:
    # normalize(emit(normalize(doc))) == normalize(doc): the emitter is the inverse
    # of the reference normalizer on the load-bearing REST fields.
    original = _petstore_openapi()
    once = OpenApiNormalizer().normalize(original, include_raw=False)
    emitted = _emit_openapi(once).document
    twice = OpenApiNormalizer().normalize(emitted, include_raw=False)
    assert once.model_dump() == twice.model_dump()


def test_component_schemas_round_trip_kinds() -> None:
    model = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    schemas = _emit_openapi(model).document["components"]["schemas"]
    # RECORD: required from non-nullable fields; optional scalar keeps its facets;
    # optional reference stays a bare $ref.
    assert schemas["Pet"]["required"] == ["id", "name"]
    assert schemas["Pet"]["properties"]["nick"] == {"type": "string"}
    assert schemas["Pet"]["properties"]["status"] == {"$ref": "#/components/schemas/Status"}
    assert schemas["Pet"]["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    # ENUM: base scalar type recovered from the member values.
    assert schemas["Status"] == {"type": "string", "enum": ["active", "inactive"]}


# ---------------------------------------------------------------------------
# info / servers defaults & provenance
# ---------------------------------------------------------------------------


def test_info_defaults_title_from_identity_and_version_fallback() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Nameless"),
    )
    result = _emit_openapi(model)
    assert result.document["info"] == {"title": "Nameless", "version": "0.0.0"}
    by_pointer = {r.pointer: r for r in result.provenance}
    assert by_pointer["/info/title"].provenance is Provenance.INFERRED
    assert by_pointer["/info/version"].provenance is Provenance.DEFAULT
    assert by_pointer["/openapi"].provenance is Provenance.DEFAULT


def test_server_variable_default_synthesized_when_missing() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        servers=[
            Server(url="https://x/{region}", variables=[ServerVariable(name="region")])
        ],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    variables = result.document["servers"][0]["variables"]
    assert variables == {"region": {"default": ""}}  # OAS requires a default
    default_prov = next(
        r for r in result.provenance if r.pointer.endswith("variables/region/default")
    )
    assert default_prov.provenance is Provenance.DEFAULT


def test_servers_round_trip_source_values() -> None:
    model = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    servers = _emit_openapi(model).document["servers"]
    assert servers == [
        {
            "url": "https://api.example.com/{ver}",
            "description": "prod",
            "variables": {"ver": {"default": "v1", "enum": ["v1", "v2"]}},
        }
    ]


# ---------------------------------------------------------------------------
# operationId synthesis & uniqueness
# ---------------------------------------------------------------------------


def test_operation_id_synthesized_and_unique() -> None:
    # Two operations on distinct routes, neither carrying an operationId.
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="GET /pets",
                        name="GET /pets",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/pets",
                    ),
                    Operation(
                        key="GET /pets/{id}",
                        name="GET /pets/{id}",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/pets/{id}",
                    ),
                ],
            )
        ],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    ids = {
        method_obj["operationId"]
        for path in result.document["paths"].values()
        for method_obj in path.values()
    }
    assert ids == {"getPets", "getPetsId"}
    synth = next(
        r for r in result.provenance if r.pointer.endswith("operationId")
    )
    assert synth.provenance is Provenance.INFERRED


def test_declared_operation_id_is_preserved_as_source() -> None:
    model = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    result = _emit_openapi(model)
    prov = {
        r.pointer: r.provenance
        for r in result.provenance
        if r.pointer.endswith("operationId")
    }
    assert prov["/paths/~1pets~1{id}/get/operationId"] is Provenance.SOURCE


# ---------------------------------------------------------------------------
# responses & requestBody edge cases
# ---------------------------------------------------------------------------


def test_operation_without_responses_gets_default_response() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="GET /ping",
                        name="ping",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/ping",
                    )
                ],
            )
        ],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    responses = result.document["paths"]["/ping"]["get"]["responses"]
    assert responses == {"default": {"description": ""}}
    default_prov = next(
        r for r in result.provenance if r.pointer.endswith("responses/default")
    )
    assert default_prov.provenance is Provenance.DEFAULT


def test_response_status_and_description_are_defaulted_when_absent() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="acme.Svc.Do",
                        name="Do",
                        kind=OperationKind.REQUEST_RESPONSE,
                        messages=[
                            Message(
                                key="acme.Svc.Do#response",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="string", nullable=False),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    responses = result.document["paths"]["/acme.Svc.Do"]["post"]["responses"]
    # No status_code on the message → success response defaults to 200.
    assert "200" in responses
    assert responses["200"]["description"] == ""
    pointers = {r.pointer: r for r in result.provenance}
    assert pointers["/paths/~1acme.Svc.Do/post/responses/200"].provenance is Provenance.INFERRED
    assert (
        pointers["/paths/~1acme.Svc.Do/post/responses/200/description"].provenance
        is Provenance.DEFAULT
    )


def test_error_message_without_status_maps_to_default_response() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="acme.Svc.Do",
                        name="Do",
                        kind=OperationKind.REQUEST_RESPONSE,
                        messages=[
                            Message(
                                key="acme.Svc.Do#error",
                                role=MessageRole.ERROR,
                                description="boom",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    responses = _emit_openapi(model).document["paths"]["/acme.Svc.Do"]["post"]["responses"]
    assert responses == {"default": {"description": "boom"}}


def test_request_body_and_response_headers_and_content_types() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="POST /things",
                        name="createThing",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="POST",
                        http_path="/things",
                        parameters=[
                            Parameter(
                                key="POST /things#query.dry",
                                name="dry",
                                location=ParameterLocation.QUERY,
                                type=TypeRef(name="boolean", nullable=True),
                            )
                        ],
                        messages=[
                            Message(
                                key="POST /things#request",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="Thing", nullable=False),
                                content_types=["application/json", "application/xml"],
                                description="the thing",
                            ),
                            Message(
                                key="POST /things#response.201",
                                role=MessageRole.RESPONSE,
                                status_code="201",
                                description="created",
                                headers=[
                                    CanonicalField(
                                        key="POST /things#response.201.Location",
                                        name="Location",
                                        type=TypeRef(name="string", nullable=False),
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
        types=[Type(key="Thing", name="Thing", kind=TypeKind.RECORD)],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    operation = result.document["paths"]["/things"]["post"]
    # Query parameter (optional → no `required`).
    assert operation["parameters"] == [
        {"name": "dry", "in": "query", "schema": {"type": "boolean"}}
    ]
    # requestBody lists both declared media types, sorted, each pointing at Thing.
    body_content = operation["requestBody"]["content"]
    assert sorted(body_content) == ["application/json", "application/xml"]
    assert body_content["application/json"]["schema"] == {"$ref": "#/components/schemas/Thing"}
    assert operation["requestBody"]["description"] == "the thing"
    # Response keeps its declared status code and header.
    response = operation["responses"]["201"]
    assert response["description"] == "created"
    assert response["headers"]["Location"] == {"schema": {"type": "string"}}


def test_parameter_constraints_and_path_required() -> None:
    model = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="S"),
        version="1",
        services=[
            Service(
                key="default",
                name="default",
                operations=[
                    Operation(
                        key="GET /items/{id}",
                        name="getItem",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/items/{id}",
                        parameters=[
                            Parameter(
                                key="GET /items/{id}#path.id",
                                name="id",
                                location=ParameterLocation.PATH,
                                type=TypeRef(name="integer", nullable=False),
                                required=True,
                                constraints=Constraints(minimum=1),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    result = _emit_openapi(model)
    assert validate_openapi_document(result.document) == []
    param = result.document["paths"]["/items/{id}"]["get"]["parameters"][0]
    assert param["required"] is True  # path params are always required
    assert param["schema"] == {"type": "integer", "minimum": 1}


# ---------------------------------------------------------------------------
# provenance completeness
# ---------------------------------------------------------------------------


def test_every_provenance_tag_is_used_across_a_mixed_model() -> None:
    # REST doc exercises SOURCE (declared values) and DEFAULT (/openapi); the RPC
    # and default-version paths exercise INFERRED and DEFAULT.
    rest = OpenApiNormalizer().normalize(_petstore_openapi(), include_raw=False)
    tags = {r.provenance for r in _emit_openapi(rest).provenance}
    assert Provenance.SOURCE in tags
    assert Provenance.DEFAULT in tags
    assert Provenance.INFERRED in {r.provenance for r in _emit_openapi(_rpc_model()).provenance}
