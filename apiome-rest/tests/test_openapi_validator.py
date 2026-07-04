"""Tests for the OpenAPI 3.1 document validator — MFI-22.1 (#4002).

Confirms the bundled OpenAPI 3.1 meta-schema loads and that the shared validator
accepts well-formed documents (including components-only ones) and reports the
structural faults the emitter must avoid.
"""

import pytest

from app.openapi_validator import (
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
