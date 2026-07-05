"""Unit tests for the OpenAPI 3.1 → 3.0 / Swagger 2.0 downgrades — MFX-9.1 (#3866).

Exercises :mod:`app.openapi_downgrade` directly on hand-built 3.1 documents so every
downgrade branch — each rewritten construct and each recorded loss — is covered
without depending on what a normalize/emit round trip happens to preserve. Two
invariants are asserted throughout: the input document is never mutated, and every
3.1-only construct the older dialect cannot carry produces a :class:`~app.emitter.Loss`
(the "downgrades flagged as lossy" acceptance criterion).
"""

import copy

from app.emitter import LossKind, LossTracker
from app.openapi_downgrade import (
    OPENAPI_30_VERSION,
    SWAGGER_20_VERSION,
    downgrade_to_openapi_30,
    downgrade_to_swagger_2,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _rich_31_document() -> dict:
    """A 3.1 document touching every construct the downgrades must handle."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Pet Store",
            "version": "1.0.0",
            "summary": "A 3.1-only info summary",
            "license": {"name": "MIT", "identifier": "MIT"},
        },
        "servers": [
            {
                "url": "https://api.example.com/{ver}",
                "variables": {"ver": {"default": "v2"}},
            },
            {"url": "http://staging.example.com/api"},
        ],
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "summary": "Get a pet",
                    "tags": ["pets"],
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer", "exclusiveMinimum": 1},
                        },
                        {
                            "name": "session",
                            "in": "cookie",
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "filter",
                            "in": "query",
                            "schema": {"$ref": "#/components/schemas/Pet"},
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                },
                                "application/xml": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                },
                            },
                            "headers": {
                                "X-Rate": {
                                    "description": "limit",
                                    "schema": {"type": "integer"},
                                }
                            },
                        }
                    },
                },
                "put": {
                    "operationId": "putPet",
                    "requestBody": {
                        "description": "the pet",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            },
                            "application/xml": {
                                "schema": {"$ref": "#/components/schemas/Pet"}
                            },
                        },
                    },
                    "responses": {"204": {"description": "updated"}},
                },
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        "name": {"type": ["string", "null"]},
                        "nickname": {"type": "null"},
                        "scalarOrInt": {"type": ["string", "integer", "null"]},
                        "status": {"const": "active"},
                        "tag": {
                            "type": "string",
                            "examples": ["a", "b"],
                            "patternProperties": {"^x-": {"type": "string"}},
                        },
                        "kind": {
                            "oneOf": [
                                {"$ref": "#/components/schemas/Pet"},
                                {"type": "string"},
                            ]
                        },
                    },
                    "required": ["name"],
                }
            }
        },
    }


def _loss_subjects(losses: LossTracker) -> set:
    return {loss.subject for loss in losses.records()}


# ---------------------------------------------------------------------------
# OpenAPI 3.0 downgrade
# ---------------------------------------------------------------------------


def test_downgrade_30_sets_version_and_leaves_input_unmutated() -> None:
    source = _rich_31_document()
    original = copy.deepcopy(source)
    losses = LossTracker()

    result = downgrade_to_openapi_30(source, losses)

    assert result["openapi"] == OPENAPI_30_VERSION
    assert source == original  # input never mutated


def test_downgrade_30_drops_31_only_info_fields() -> None:
    losses = LossTracker()
    result = downgrade_to_openapi_30(_rich_31_document(), losses)

    assert "summary" not in result["info"]
    assert "identifier" not in result["info"]["license"]
    assert result["info"]["license"]["name"] == "MIT"
    assert "openapi-30-info-summary" in _loss_subjects(losses)
    assert "openapi-30-license-identifier" in _loss_subjects(losses)


def test_downgrade_30_rewrites_nullability() -> None:
    losses = LossTracker()
    result = downgrade_to_openapi_30(_rich_31_document(), losses)
    props = result["components"]["schemas"]["Pet"]["properties"]

    # `type: ["string", "null"]` → `{type: "string", nullable: true}`.
    assert props["name"] == {"type": "string", "nullable": True}
    # A bare `type: "null"` keeps only `nullable` (no concrete 3.0 type).
    assert props["nickname"] == {"nullable": True}
    # A genuine multi-type union keeps the first type and flags the rest lost.
    assert props["scalarOrInt"]["type"] == "string"
    assert props["scalarOrInt"]["nullable"] is True

    subjects = _loss_subjects(losses)
    assert "openapi-30-null-type" in subjects
    assert "openapi-30-multitype" in subjects


def test_downgrade_30_rewrites_exclusive_bounds_const_and_examples() -> None:
    losses = LossTracker()
    result = downgrade_to_openapi_30(_rich_31_document(), losses)
    props = result["components"]["schemas"]["Pet"]["properties"]
    id_param = result["paths"]["/pets/{id}"]["get"]["parameters"][0]

    # Numeric exclusiveMinimum → draft-4 boolean pair.
    assert id_param["schema"] == {"type": "integer", "minimum": 1, "exclusiveMinimum": True}
    # const → single-value enum; examples → first example.
    assert props["status"] == {"enum": ["active"]}
    assert props["tag"]["example"] == "a"
    assert "examples" not in props["tag"]
    # patternProperties has no 3.0 representation and is dropped.
    assert "patternProperties" not in props["tag"]

    subjects = _loss_subjects(losses)
    assert "openapi-30-exclusive-bound" in subjects
    assert "openapi-30-const" in subjects
    assert "openapi-30-examples" in subjects
    assert "downgrade-unsupported-keyword" in subjects


def test_downgrade_30_keeps_oneof_and_refs() -> None:
    losses = LossTracker()
    result = downgrade_to_openapi_30(_rich_31_document(), losses)
    kind = result["components"]["schemas"]["Pet"]["properties"]["kind"]

    # 3.0 retains oneOf; refs are unchanged (still #/components/schemas).
    assert "oneOf" in kind
    assert kind["oneOf"][0] == {"$ref": "#/components/schemas/Pet"}


def test_downgrade_30_is_deterministic() -> None:
    losses_a, losses_b = LossTracker(), LossTracker()
    a = downgrade_to_openapi_30(_rich_31_document(), losses_a)
    b = downgrade_to_openapi_30(_rich_31_document(), losses_b)

    assert a == b
    assert losses_a.records() == losses_b.records()


# ---------------------------------------------------------------------------
# Swagger 2.0 downgrade
# ---------------------------------------------------------------------------


def test_downgrade_swagger2_sets_version_and_structure() -> None:
    source = _rich_31_document()
    original = copy.deepcopy(source)
    losses = LossTracker()

    result = downgrade_to_swagger_2(source, losses)

    assert result["swagger"] == SWAGGER_20_VERSION
    assert "openapi" not in result
    assert "definitions" in result and "Pet" in result["definitions"]
    assert "components" not in result
    assert source == original  # input never mutated


def test_downgrade_swagger2_projects_servers_to_host() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)

    assert result["schemes"] == ["https"]
    assert result["host"] == "api.example.com"
    # Server-variable default substituted into the concrete basePath.
    assert result["basePath"] == "/v2"

    subjects = _loss_subjects(losses)
    assert "swagger2-multiple-servers" in subjects
    assert "swagger2-server-variables" in subjects


def test_downgrade_swagger2_rewrites_refs_to_definitions() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)

    response = result["paths"]["/pets/{id}"]["get"]["responses"]["200"]
    assert response["schema"] == {"$ref": "#/definitions/Pet"}
    assert result["paths"]["/pets/{id}"]["get"]["produces"] == [
        "application/json",
        "application/xml",
    ]
    # Two response media types collapse to one schema — an approximation.
    assert "swagger2-response-media-types" in _loss_subjects(losses)


def test_downgrade_swagger2_request_body_becomes_body_parameter() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)

    put = result["paths"]["/pets/{id}"]["put"]
    body_params = [p for p in put["parameters"] if p["in"] == "body"]
    assert len(body_params) == 1
    assert body_params[0]["schema"] == {"$ref": "#/definitions/Pet"}
    assert body_params[0]["description"] == "the pet"
    assert put["consumes"] == ["application/json", "application/xml"]
    assert "swagger2-request-media-types" in _loss_subjects(losses)


def test_downgrade_swagger2_inlines_and_drops_parameters() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)

    params = result["paths"]["/pets/{id}"]["get"]["parameters"]
    by_name = {p["name"]: p for p in params}

    # Cookie parameters have no Swagger 2.0 representation → dropped.
    assert "session" not in by_name
    assert "swagger2-cookie-parameter" in _loss_subjects(losses)

    # Path parameter carries its type inline (no `schema` wrapper).
    assert by_name["id"]["in"] == "path"
    assert by_name["id"]["required"] is True
    assert by_name["id"]["type"] == "integer"
    assert "schema" not in by_name["id"]

    # A $ref-typed non-body parameter is approximated as a string.
    assert by_name["filter"]["type"] == "string"
    assert "swagger2-non-primitive-parameter" in _loss_subjects(losses)


def test_downgrade_swagger2_drops_unsupported_schema_keywords() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)
    props = result["definitions"]["Pet"]["properties"]

    # 2.0 cannot express oneOf; it is dropped.
    assert "oneOf" not in props["kind"]
    # No nullable flag in 2.0: a null-union collapses to the plain type.
    assert props["name"]["type"] == "string"
    assert "nullable" not in props["name"]

    subjects = _loss_subjects(losses)
    assert "downgrade-unsupported-keyword" in subjects  # oneOf / patternProperties
    assert "swagger2-nullable" in subjects


def test_downgrade_swagger2_response_headers_inlined() -> None:
    losses = LossTracker()
    result = downgrade_to_swagger_2(_rich_31_document(), losses)

    headers = result["paths"]["/pets/{id}"]["get"]["responses"]["200"]["headers"]
    assert headers["X-Rate"] == {"description": "limit", "type": "integer"}


def test_downgrade_swagger2_is_deterministic() -> None:
    losses_a, losses_b = LossTracker(), LossTracker()
    a = downgrade_to_swagger_2(_rich_31_document(), losses_a)
    b = downgrade_to_swagger_2(_rich_31_document(), losses_b)

    assert a == b
    assert losses_a.records() == losses_b.records()


def test_downgrade_swagger2_drops_trace_operation() -> None:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1"},
        "paths": {
            "/p": {"trace": {"operationId": "traceP", "responses": {"200": {"description": "ok"}}}}
        },
    }
    losses = LossTracker()
    result = downgrade_to_swagger_2(doc, losses)

    assert "trace" not in result["paths"]["/p"]
    assert "swagger2-trace-method" in _loss_subjects(losses)


def test_all_downgrade_losses_use_known_kinds() -> None:
    losses = LossTracker()
    downgrade_to_openapi_30(_rich_31_document(), losses)
    downgrade_to_swagger_2(_rich_31_document(), losses)
    for loss in losses.records():
        assert loss.kind in (LossKind.NA, LossKind.INFERRED)
        assert loss.detail  # every loss carries a human explanation
