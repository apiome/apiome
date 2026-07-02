"""End-to-end tests for the reference OpenAPI normalizer (MFI-2.3, #3740).

Exercises the acceptance criterion's "reference normalizer implemented and
tested": a representative OpenAPI 3.1 document maps cleanly into the canonical
model with the load-bearing REST fields intact (verb/route, parameters,
request/response messages, payload refs, component types), the output is
deterministically ordered and idempotent, and OpenAPI 3.0-specific forms and
error paths behave.
"""

import json

import pytest

from app.canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    OperationKind,
    ParameterLocation,
    TypeKind,
)
from app.normalizer import get_normalizer
from app.openapi_normalizer import OpenApiNormalizer


def _petstore() -> dict:
    """A small but representative OpenAPI 3.1 document."""
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
        "tags": [{"name": "pets", "description": "Pet operations"}],
        "paths": {
            "/pets/{id}": {
                "parameters": [
                    {
                        "name": "id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }
                ],
                "get": {
                    "operationId": "getPet",
                    "summary": "Get a pet",
                    "tags": ["pets"],
                    "parameters": [
                        {"name": "verbose", "in": "query", "schema": {"type": "boolean"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "headers": {
                                "X-Rate-Limit": {"schema": {"type": "integer"}}
                            },
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
                            "application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}
                        }
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
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
                        "id": {"type": "string", "format": "uuid"},
                        "name": {"type": "string", "minLength": 1},
                        "status": {"$ref": "#/components/schemas/Status"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "Status": {"type": "string", "enum": ["active", "inactive"]},
            }
        },
    }


def test_artifact_identity_and_servers() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    assert isinstance(api, CanonicalApi)
    assert api.paradigm is ApiParadigm.REST
    assert api.format == "openapi-3.1"
    assert api.protocol == "http"
    assert api.identity.name == "Pet Store"
    assert api.version == "1.4.0"
    assert len(api.servers) == 1
    server = api.servers[0]
    assert server.url == "https://api.example.com/{ver}"
    assert server.variables[0].name == "ver"
    assert server.variables[0].default == "v1"
    assert server.variables[0].enum == ["v1", "v2"]


def test_operations_grouped_by_tag_with_verb_route() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    assert [s.key for s in api.services] == ["pets"]
    assert api.services[0].description == "Pet operations"
    ops = {o.key: o for o in api.operations()}
    assert set(ops) == {"GET /pets/{id}", "POST /pets/{id}"}
    get_op = ops["GET /pets/{id}"]
    assert get_op.kind is OperationKind.REQUEST_RESPONSE
    assert (get_op.http_method, get_op.http_path) == ("GET", "/pets/{id}")
    assert get_op.name == "getPet"
    assert get_op.extras["operationId"] == "getPet"
    assert get_op.extras["summary"] == "Get a pet"


def test_parameters_merge_path_and_operation_level() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    get_op = {o.key: o for o in api.operations()}["GET /pets/{id}"]
    params = {p.name: p for p in get_op.parameters}
    assert set(params) == {"id", "verbose"}
    assert params["id"].location is ParameterLocation.PATH
    assert params["id"].required is True
    assert params["id"].type.nullable is False
    assert params["id"].constraints is not None and params["id"].constraints.format == "uuid"
    assert params["verbose"].location is ParameterLocation.QUERY
    assert params["verbose"].required is False


def test_response_and_request_messages() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    ops = {o.key: o for o in api.operations()}

    get_msgs = {m.key: m for m in ops["GET /pets/{id}"].messages}
    ok = get_msgs["GET /pets/{id}#response.200"]
    assert ok.role is MessageRole.RESPONSE
    assert ok.status_code == "200"
    assert ok.content_types == ["application/json"]
    assert ok.payload is not None and ok.payload.name == "Pet"
    assert [h.name for h in ok.headers] == ["X-Rate-Limit"]

    not_found = get_msgs["GET /pets/{id}#response.404"]
    assert not_found.role is MessageRole.ERROR
    assert not_found.payload is None and not_found.payload_schema is None

    post_msgs = {m.key: m for m in ops["POST /pets/{id}"].messages}
    request = post_msgs["POST /pets/{id}#request"]
    assert request.role is MessageRole.REQUEST
    assert request.payload is not None and request.payload.name == "Pet"


def test_component_types_coerced() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    pet = api.type_by_key("Pet")
    assert pet is not None and pet.kind is TypeKind.RECORD
    fields = {f.name: f for f in pet.fields}
    assert fields["id"].type.nullable is False  # required
    assert fields["status"].type.name == "Status"  # ref by key
    assert fields["tags"].type.is_list()
    status = api.type_by_key("Status")
    assert status is not None and status.kind is TypeKind.ENUM
    assert [e.name for e in status.enum_values] == ["active", "inactive"]


def test_raw_preserved_and_toggle() -> None:
    doc = _petstore()
    with_raw = OpenApiNormalizer().normalize(doc)
    assert with_raw.raw == doc
    without_raw = OpenApiNormalizer().normalize(doc, include_raw=False)
    assert without_raw.raw is None


def test_output_is_deterministic_and_round_trips() -> None:
    api = OpenApiNormalizer().normalize(_petstore())
    again = OpenApiNormalizer().normalize(_petstore())
    assert api.model_dump() == again.model_dump()  # idempotent
    # Lossless JSONB round-trip, as the persistence layer (MFI-2.2) requires.
    reloaded = CanonicalApi.model_validate(json.loads(json.dumps(api.model_dump())))
    assert reloaded == api


def test_ordering_invariant_to_source_path_order() -> None:
    doc = _petstore()
    shuffled = _petstore()
    # Reverse the components ordering; canonical output must be identical.
    shuffled["components"]["schemas"] = dict(
        reversed(list(shuffled["components"]["schemas"].items()))
    )
    a = OpenApiNormalizer().normalize(doc, include_raw=False)
    b = OpenApiNormalizer().normalize(shuffled, include_raw=False)
    assert a.model_dump() == b.model_dump()


def test_format_detection_30_vs_31() -> None:
    doc = _petstore()
    doc["openapi"] = "3.0.3"
    api = OpenApiNormalizer().normalize(doc)
    assert api.format == "openapi-3.0"
    # The 3.0 alias resolves to the same implementation.
    assert issubclass(get_normalizer("openapi-3.0"), OpenApiNormalizer)


def test_openapi_30_nullable_and_boolean_exclusive() -> None:
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {
            "schemas": {
                "Thing": {
                    "type": "object",
                    "required": ["score"],
                    "properties": {
                        "label": {"type": "string", "nullable": True},
                        "score": {"type": "integer", "minimum": 0, "exclusiveMinimum": True},
                    },
                }
            }
        },
    }
    api = OpenApiNormalizer().normalize(doc)
    thing = api.type_by_key("Thing")
    fields = {f.name: f for f in thing.fields}
    # nullable:true overrides required-ness for that level.
    assert fields["label"].type.nullable is True
    # required, non-nullable scalar.
    assert fields["score"].type.nullable is False
    assert fields["score"].constraints is not None
    assert fields["score"].constraints.exclusive_minimum == 0
    assert fields["score"].constraints.minimum is None


def test_untagged_operations_land_in_default_service() -> None:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    api = OpenApiNormalizer().normalize(doc)
    assert [s.key for s in api.services] == ["default"]
    assert api.services[0].operations[0].key == "GET /ping"


def test_inline_object_body_kept_as_payload_schema() -> None:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {
            "/echo": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"msg": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    api = OpenApiNormalizer().normalize(doc)
    op = {o.key: o for o in api.operations()}["POST /echo"]
    request = {m.key: m for m in op.messages}["POST /echo#request"]
    assert request.payload is None
    assert request.payload_schema == {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
    }


def test_rejects_non_openapi_and_non_dict() -> None:
    with pytest.raises(ValueError, match="parsed mapping"):
        OpenApiNormalizer().normalize("not a dict")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="not an OpenAPI 3.x"):
        OpenApiNormalizer().normalize({"swagger": "2.0", "info": {}})
