"""OpenAPI emitter multi-version behaviour — MFX-9.1 (#3866).

The emitter's default target is the native OpenAPI 3.1 (covered by
``test_openapi_emitter``). These tests exercise the added ``openapi_version`` emit
option: that ``3.0`` and ``2.0`` (Swagger) select a downgrade, that the downgrade's
fidelity losses ride back on the :class:`~app.emitter.EmitResult`, that the emitted
file identity (path/media type/version key) matches the chosen dialect, and — the
strongest statement — that each downgrade re-imports cleanly through its own
normalizer, closing an emit → normalize round trip.
"""

import pytest

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
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitOptions
from app.openapi_emitter import OpenApiEmitOptions, OpenApiEmitter
from app.openapi_normalizer import OpenApiNormalizer
from app.openapi_validator import validate_openapi_document
from app.swagger2_normalizer import Swagger2Normalizer

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _rest_model() -> CanonicalApi:
    """A small REST canonical model with a server, params, body, and a named type."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pet Store"),
        version="1.4.0",
        title="Pet Store",
        description="Pets API",
        servers=[
            Server(
                url="https://api.example.com/{ver}",
                description="prod",
                variables=[ServerVariable(name="ver", default="v1", enum=["v1", "v2"])],
            )
        ],
        services=[
            Service(
                key="pets",
                name="pets",
                operations=[
                    Operation(
                        key="GET /pets/{id}",
                        name="getPet",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="GET",
                        http_path="/pets/{id}",
                        tags=["pets"],
                        parameters=[
                            Parameter(
                                key="GET /pets/{id}#path.id",
                                name="id",
                                location=ParameterLocation.PATH,
                                type=TypeRef(name="integer", nullable=False),
                                required=True,
                                # A numeric exclusive bound is a JSON-Schema-2020-12
                                # spelling 3.0 must re-express and 2.0 approximates —
                                # a 3.1-only construct the emitter actually produces.
                                constraints=Constraints(exclusive_minimum=1),
                            )
                        ],
                        messages=[
                            Message(
                                key="GET /pets/{id}#response.200",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="Pet"),
                                content_types=["application/json"],
                                status_code="200",
                                description="a pet",
                            )
                        ],
                    ),
                    Operation(
                        key="POST /pets",
                        name="createPet",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="POST",
                        http_path="/pets",
                        messages=[
                            Message(
                                key="POST /pets#request",
                                role=MessageRole.REQUEST,
                                payload=TypeRef(name="Pet"),
                                content_types=["application/json"],
                                description="the pet to create",
                            ),
                            Message(
                                key="POST /pets#response.201",
                                role=MessageRole.RESPONSE,
                                payload=TypeRef(name="Pet"),
                                content_types=["application/json"],
                                status_code="201",
                                description="created",
                            ),
                        ],
                    ),
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
                        key="Pet#id",
                        name="id",
                        type=TypeRef(name="integer", nullable=False),
                    ),
                    CanonicalField(
                        key="Pet#name",
                        name="name",
                        type=TypeRef(name="string", nullable=True),
                    ),
                ],
            )
        ],
    )


def _emit(version: str):
    return OpenApiEmitter().emit(
        _rest_model(), opts=OpenApiEmitOptions(openapi_version=version)
    )


# ---------------------------------------------------------------------------
# Option wiring & defaults
# ---------------------------------------------------------------------------


def test_default_version_is_native_31_and_lossless() -> None:
    result = OpenApiEmitter().emit(_rest_model())
    document = result.document

    assert document["openapi"] == "3.1.0"
    assert result.files[0].path == "openapi.json"
    # The native target validates against the 3.1 meta-schema and adds no losses.
    assert validate_openapi_document(document) == []
    assert result.losses == []


def test_base_emit_options_default_to_native_31() -> None:
    # A caller passing the base EmitOptions (no version field) still gets 3.1.
    result = OpenApiEmitter().emit(_rest_model(), opts=EmitOptions())
    assert result.document["openapi"] == "3.1.0"


def test_options_schema_advertises_version_choice() -> None:
    schema = OpenApiEmitter.options_schema()
    version = schema["properties"]["openapi_version"]
    assert version["default"] == "3.1"
    assert set(version["enum"]) == {"3.1", "3.0", "2.0"}


def test_unknown_version_is_rejected() -> None:
    with pytest.raises(ValueError):
        OpenApiEmitOptions(openapi_version="4.0")


# ---------------------------------------------------------------------------
# 3.0 downgrade
# ---------------------------------------------------------------------------


def test_emit_openapi_30_downgrade_identity_and_losses() -> None:
    result = _emit("3.0")
    document = result.document

    assert document["openapi"] == "3.0.3"
    assert result.files[0].path == "openapi.json"
    assert result.files[0].media_type == "application/vnd.oai.openapi+json"
    # The numeric exclusive bound re-expressed for 3.0 is a recorded downgrade loss.
    assert any(loss.subject == "openapi-30-exclusive-bound" for loss in result.losses)


def test_emit_openapi_30_round_trips_through_the_openapi_normalizer() -> None:
    document = _emit("3.0").document
    # OpenApiNormalizer accepts 3.0; a clean re-import is the round-trip check.
    api = OpenApiNormalizer().normalize(document, include_raw=False)
    assert api.format == "openapi-3.0"
    assert {t.key for t in api.types} == {"Pet"}
    assert any(op.http_path == "/pets/{id}" for s in api.services for op in s.operations)


def test_emit_openapi_30_exclusive_bound_uses_the_30_spelling() -> None:
    document = _emit("3.0").document
    param = document["paths"]["/pets/{id}"]["get"]["parameters"][0]
    # 3.1's numeric exclusiveMinimum becomes the draft-4 boolean pair for 3.0.
    assert param["schema"]["minimum"] == 1
    assert param["schema"]["exclusiveMinimum"] is True


# ---------------------------------------------------------------------------
# Swagger 2.0 downgrade
# ---------------------------------------------------------------------------


def test_emit_swagger_2_downgrade_identity_and_structure() -> None:
    result = _emit("2.0")
    document = result.document

    assert document["swagger"] == "2.0"
    assert "openapi" not in document
    assert result.files[0].path == "swagger.json"
    assert result.files[0].media_type == "application/json"
    assert "definitions" in document and "Pet" in document["definitions"]
    assert document["host"] == "api.example.com"
    assert result.losses != []


def test_emit_swagger_2_round_trips_through_the_swagger_normalizer() -> None:
    document = _emit("2.0").document
    api = Swagger2Normalizer().normalize(document, include_raw=False)

    assert api.format == "swagger-2.0"
    assert {t.key for t in api.types} == {"Pet"}
    # The POST body survives as a request message on the re-imported operation.
    create = next(
        op for s in api.services for op in s.operations if op.http_method == "POST"
    )
    assert any(m.role is MessageRole.REQUEST for m in create.messages)


def test_emit_swagger_2_body_becomes_a_body_parameter() -> None:
    document = _emit("2.0").document
    post = document["paths"]["/pets"]["post"]
    body_params = [p for p in post.get("parameters", []) if p["in"] == "body"]

    assert len(body_params) == 1
    assert body_params[0]["schema"] == {"$ref": "#/definitions/Pet"}
    assert post["consumes"] == ["application/json"]


# ---------------------------------------------------------------------------
# Determinism across versions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["3.1", "3.0", "2.0"])
def test_emit_is_deterministic_per_version(version: str) -> None:
    first = _emit(version)
    second = _emit(version)
    assert first.model_dump() == second.model_dump()
