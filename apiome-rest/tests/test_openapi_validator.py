"""Tests for the OpenAPI 3.1 document validator — MFI-22.1 (#4002).

Confirms the bundled OpenAPI 3.1 meta-schema loads and that the shared validator
accepts well-formed documents (including components-only ones) and reports the
structural faults the emitter must avoid.
"""

import pytest

from app.openapi_validator import (
    OPENAPI_30_META_SCHEMA_ID,
    OPENAPI_31_META_SCHEMA_ID,
    OPENAPI_32_META_SCHEMA_ID,
    OpenApiValidationError,
    assert_valid_openapi_document,
    load_openapi_31_meta_schema,
    load_openapi_32_meta_schema,
    validate_openapi_document,
)


def _valid_doc() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": {
            "/pets/{id}": {
                "get": {
                    "operationId": "getPet",
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Pet"}
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {"schemas": {"Pet": {"type": "object"}}},
    }


def test_bundled_meta_schema_loads() -> None:
    meta = load_openapi_31_meta_schema()
    assert meta["$id"] == OPENAPI_31_META_SCHEMA_ID
    # It is itself a draft 2020-12 schema (OAS 3.1 schemas *are* JSON Schema).
    assert meta["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_bundled_openapi_32_meta_schema_loads() -> None:
    meta = load_openapi_32_meta_schema()
    assert meta["$id"] == OPENAPI_32_META_SCHEMA_ID
    assert meta["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_openapi_32_document_validates() -> None:
    doc = {
        "openapi": "3.2.0",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": {
            "/x": {
                "query": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    assert validate_openapi_document(doc) == []


def test_valid_document_has_no_errors() -> None:
    assert validate_openapi_document(_valid_doc()) == []
    # Does not raise.
    assert_valid_openapi_document(_valid_doc())


def test_components_only_document_is_valid() -> None:
    # A data-schema conversion emits no operations — components alone is valid.
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "T", "version": "1.0.0"},
        "paths": {},
        "components": {"schemas": {"User": {"type": "object"}}},
    }
    assert validate_openapi_document(doc) == []


def test_missing_info_is_reported() -> None:
    errors = validate_openapi_document({"openapi": "3.1.0", "paths": {}})
    assert any("info" in e["message"] for e in errors)
    assert all({"path", "message", "keyword"} <= e.keys() for e in errors)


def test_response_without_description_is_reported() -> None:
    doc = _valid_doc()
    doc["paths"]["/pets/{id}"]["get"]["responses"]["200"] = {}
    errors = validate_openapi_document(doc)
    offending = [e for e in errors if e["path"].endswith("responses/200")]
    assert offending and offending[0]["keyword"] == "required"
    assert "description" in offending[0]["message"]


def test_assert_raises_with_error_payload() -> None:
    with pytest.raises(OpenApiValidationError) as excinfo:
        assert_valid_openapi_document({"openapi": "3.1.0"})
    assert excinfo.value.errors  # non-empty structured errors
    assert isinstance(excinfo.value.errors[0]["message"], str)


# ---------------------------------------------------------------------------
# COA-2.2 (#7045) — 3.0, Swagger 2.0 and 3.1.x patch coverage
# ---------------------------------------------------------------------------

from app.openapi_validator import (
    OPENAPI_30_META_SCHEMA_ID,  # noqa: E402
    INVALID,
    NOT_VALIDATED,
    VALIDATED,
    has_meta_schema,
    load_openapi_30_meta_schema,
    load_swagger_20_meta_schema,
    validation_status,
)


def _doc_30() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "properties": {
                        # 3.0 spellings: nullable + boolean exclusiveMinimum.
                        "age": {"type": "integer", "minimum": 0, "exclusiveMinimum": True},
                        "nick": {"type": "string", "nullable": True},
                    },
                }
            }
        },
    }


def _doc_20() -> dict:
    return {
        "swagger": "2.0",
        "info": {"title": "Pets", "version": "1.0.0"},
        "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }


def test_valid_30_document_passes_with_draft4_spellings() -> None:
    assert validate_openapi_document(_doc_30()) == []
    assert validation_status(_doc_30()) == VALIDATED


@pytest.mark.parametrize("version", ["3.0.0", "3.0.1", "3.0.2", "3.0.3", "3.0.4"])
def test_every_30_patch_release_is_covered(version: str) -> None:
    doc = _doc_30()
    doc["openapi"] = version
    assert has_meta_schema(doc)
    assert validate_openapi_document(doc) == []


def test_invalid_30_document_fails_with_located_errors() -> None:
    doc = _doc_30()
    del doc["paths"]["/pets"]["get"]["responses"]["200"]["description"]
    doc["components"]["schemas"]["Pet"]["properties"]["age"]["type"] = "bogus"
    errors = validate_openapi_document(doc)
    paths = {e["path"] for e in errors}
    assert "paths//pets/get/responses/200" in paths
    # The 3.0 meta-schema is a Schema|Reference union, so the fault is located at the
    # schema object that matched neither branch.
    assert "components/schemas/Pet" in paths
    assert validation_status(doc) == INVALID


def test_30_is_not_judged_against_the_31_meta_schema() -> None:
    # ``paths`` is required in 3.0 but optional in 3.1: the same document differs by
    # the meta-schema selected from its declared version.
    doc = _doc_30()
    del doc["paths"]
    assert validate_openapi_document(doc) != []
    doc["openapi"] = "3.1.0"
    assert validate_openapi_document(doc) == []


def test_valid_20_document_passes() -> None:
    assert validate_openapi_document(_doc_20()) == []
    assert validation_status(_doc_20()) == VALIDATED


def test_invalid_20_document_fails_with_located_errors() -> None:
    doc = _doc_20()
    doc["paths"]["/pets"]["get"]["responses"]["200"] = {}
    doc["info"].pop("version")
    errors = validate_openapi_document(doc)
    paths = {e["path"] for e in errors}
    assert "info" in paths
    assert "paths//pets/get/responses/200" in paths
    assert validation_status(doc) == INVALID


def test_20_marker_must_be_exactly_two_point_zero() -> None:
    doc = _doc_20()
    doc["swagger"] = "1.2"
    assert not has_meta_schema(doc)
    assert validation_status(doc) == NOT_VALIDATED


@pytest.mark.parametrize("version", ["3.1.0", "3.1.1", "3.1.2"])
def test_every_31_patch_release_validates_against_the_31_meta_schema(version: str) -> None:
    doc = _valid_doc()
    doc["openapi"] = version
    assert validate_openapi_document(doc) == []
    assert validation_status(doc) == VALIDATED
    del doc["info"]
    assert validation_status(doc) == INVALID


@pytest.mark.parametrize(
    "document",
    [{"openapi": "4.0.0", "info": {}, "paths": {}}, {"info": {}}, {"openapi": 3.1}, [], "text"],
)
def test_a_document_without_a_covered_version_is_not_validated_never_valid(document) -> None:
    assert not has_meta_schema(document)
    assert validation_status(document) == NOT_VALIDATED


def test_vendored_schemas_load_and_identify_themselves() -> None:
    assert load_openapi_30_meta_schema()["id"] == OPENAPI_30_META_SCHEMA_ID
    assert load_swagger_20_meta_schema()["required"] == ["swagger", "info", "paths"]
