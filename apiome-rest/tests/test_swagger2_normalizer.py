"""End-to-end tests for the Swagger 2.0 normalizer (MFI-30.1, #4394)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.canonical_model import ApiParadigm, MessageRole, ParameterLocation, TypeKind
from app.diff import diff
from app.fingerprint import canonical_fingerprint
from app.import_source import DetectionInput
from app.normalizer import get_normalizer
from app.openapi_import_source import OpenApiImportSource
from app.openapi_normalizer import OpenApiNormalizer
from app.swagger2_normalizer import Swagger2Normalizer

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "apiome-ui"
    / "examples"
    / "swagger"
    / "01-swagger-2-petstore.yaml"
)


def _swagger_fixture() -> dict:
    return {
        "swagger": "2.0",
        "info": {"title": "Pet Store", "version": "1.0.0", "description": "Pets."},
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https", "http"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "tags": [{"name": "pets", "description": "Pet operations"}],
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "summary": "Get a pet",
                    "tags": ["pets"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "type": "string"},
                        {"name": "verbose", "in": "query", "required": False, "type": "boolean"},
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "schema": {"$ref": "#/definitions/Pet"},
                            "headers": {
                                "X-Rate-Limit": {"type": "integer"},
                            },
                        },
                        "404": {"description": "not found"},
                    },
                },
                "post": {
                    "operationId": "createPet",
                    "tags": ["pets"],
                    "parameters": [
                        {
                            "name": "body",
                            "in": "body",
                            "required": True,
                            "schema": {"$ref": "#/definitions/Pet"},
                        }
                    ],
                    "responses": {
                        "201": {
                            "description": "created",
                            "schema": {"$ref": "#/definitions/Pet"},
                        }
                    },
                },
            }
        },
        "definitions": {
            "Pet": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string", "minLength": 1},
                },
            }
        },
    }


def _openapi_equivalent() -> dict:
    """OpenAPI 3.1 document with the same semantic contract as :func:`_swagger_fixture`."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.0.0", "description": "Pets."},
        "servers": [
            {"url": "https://api.example.com/v1"},
            {"url": "http://api.example.com/v1"},
        ],
        "tags": [{"name": "pets", "description": "Pet operations"}],
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "summary": "Get a pet",
                    "tags": ["pets"],
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "verbose", "in": "query", "schema": {"type": "boolean"}},
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "headers": {
                                "X-Rate-Limit": {"schema": {"type": "integer"}},
                            },
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"},
                                }
                            },
                        },
                        "404": {"description": "not found"},
                    },
                },
                "post": {
                    "operationId": "createPet",
                    "tags": ["pets"],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"},
                            }
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"},
                                }
                            },
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string", "minLength": 1},
                    },
                }
            }
        },
    }


@pytest.fixture()
def adapter() -> OpenApiImportSource:
    return OpenApiImportSource()


def test_swagger2_normalizer_registers() -> None:
    cls = get_normalizer("swagger-2.0")
    assert cls is Swagger2Normalizer
    assert cls.format == "swagger-2.0"


def test_normalize_identity_servers_and_types() -> None:
    api = Swagger2Normalizer().normalize(_swagger_fixture())
    assert api.paradigm is ApiParadigm.REST
    assert api.format == "swagger-2.0"
    assert api.identity.name == "Pet Store"
    assert api.version == "1.0.0"
    assert [server.url for server in api.servers] == [
        "https://api.example.com/v1",
        "http://api.example.com/v1",
    ]
    pet = api.type_by_key("Pet")
    assert pet is not None
    assert pet.kind is TypeKind.RECORD


def test_normalize_operations_parameters_and_messages() -> None:
    api = Swagger2Normalizer().normalize(_swagger_fixture())
    get_op = next(op for op in api.operations() if op.key == "GET /pets/{id}")
    assert get_op.extras["operationId"] == "getPet"
    assert any(p.location is ParameterLocation.PATH and p.name == "id" for p in get_op.parameters)
    assert any(p.location is ParameterLocation.QUERY and p.name == "verbose" for p in get_op.parameters)

    response_200 = next(
        msg for msg in get_op.messages if msg.role is MessageRole.RESPONSE and msg.status_code == "200"
    )
    assert response_200.content_types == ["application/json"]
    assert response_200.payload is not None
    assert response_200.payload.name == "Pet"
    assert any(header.name == "X-Rate-Limit" for header in response_200.headers)

    post_op = next(op for op in api.operations() if op.key == "POST /pets/{id}")
    request = next(msg for msg in post_op.messages if msg.role is MessageRole.REQUEST)
    assert request.content_types == ["application/json"]
    assert request.payload is not None
    assert request.payload.name == "Pet"


def test_normalize_is_deterministic() -> None:
    normalizer = Swagger2Normalizer()
    a = normalizer.normalize(_swagger_fixture(), include_raw=False)
    b = normalizer.normalize(_swagger_fixture(), include_raw=False)
    assert canonical_fingerprint(a) == canonical_fingerprint(b)


def test_diff_against_openapi_equivalent_has_no_entity_changes() -> None:
    swagger_model = Swagger2Normalizer().normalize(_swagger_fixture(), include_raw=False)
    openapi_model = OpenApiNormalizer().normalize(_openapi_equivalent(), include_raw=False)
    result = diff(swagger_model, openapi_model)
    assert result.is_empty()
    assert swagger_model.format == "swagger-2.0"
    assert openapi_model.format == "openapi-3.1"
    assert not result.identical


def test_example_petstore_yaml_normalizes() -> None:
    if not _FIXTURE_PATH.is_file():
        pytest.skip(f"missing fixture: {_FIXTURE_PATH}")
    document = yaml.safe_load(_FIXTURE_PATH.read_text(encoding="utf-8"))
    api = Swagger2Normalizer().normalize(document)
    assert api.format == "swagger-2.0"
    assert api.type_by_key("Pet") is not None
    assert any(op.key == "GET /pets" for op in api.operations())


@pytest.mark.parametrize(
    "document",
    [
        _swagger_fixture(),
        {"swagger": "2.0", "info": {"title": "Minimal", "version": "0.1.0"}, "paths": {}},
    ],
)
def test_detect_and_normalize_agree(adapter: OpenApiImportSource, document: dict) -> None:
    detection = adapter.detect(DetectionInput(document=document))
    assert detection.format == "swagger-2.0"
    model = adapter.normalize(document)
    assert model.format == "swagger-2.0"


def test_adapter_normalize_swagger_produces_canonical_model(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_swagger_fixture())
    assert model.format == "swagger-2.0"
    assert adapter.fingerprint(model)


def test_invalid_source_raises() -> None:
    with pytest.raises(ValueError, match="parsed mapping"):
        Swagger2Normalizer().normalize("not a dict")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Swagger 2.0"):
        Swagger2Normalizer().normalize({"openapi": "3.1.0", "info": {}})
