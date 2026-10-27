"""Unit tests for the OpenAPI 3.1 ``components/schemas`` importer (#3465)."""

import pytest

from app.primitives_openapi import OpenApiComponentsError, parse_openapi_components
from app.primitives_rewrite import rewrite_internal_ref, rewrite_import_schema


def _doc(schemas, **extra):
    """Build a minimal OpenAPI 3.1 document carrying the given component schemas."""
    doc = {"openapi": "3.1.0", "info": {"title": "Pets", "version": "1"}, "paths": {}}
    doc["components"] = {"schemas": schemas}
    doc.update(extra)
    return doc


def test_each_component_schema_is_one_definition_in_order():
    definitions, warnings = parse_openapi_components(
        _doc({"Pet": {"type": "object"}, "Tag": {"type": "string"}, "Owner": True})
    )
    assert list(definitions) == ["Pet", "Tag", "Owner"]
    assert definitions["Pet"] == {"type": "object"}
    assert definitions["Owner"] is True
    assert warnings == []


def test_paths_and_other_components_are_ignored():
    doc = _doc({"Pet": {"type": "object"}})
    doc["components"]["parameters"] = {"limit": {"name": "limit", "in": "query"}}
    doc["paths"] = {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}}
    definitions, _ = parse_openapi_components(doc)
    assert list(definitions) == ["Pet"]


def test_source_document_is_not_mutated():
    doc = _doc({"Pet": {"type": "object"}})
    definitions, _ = parse_openapi_components(doc)
    definitions["Extra"] = {}
    assert list(doc["components"]["schemas"]) == ["Pet"]


@pytest.mark.parametrize("version", ["3.1.0", "3.1.1", "3.2.0"])
def test_openapi_3_1_and_later_import_without_warnings(version):
    _, warnings = parse_openapi_components(_doc({"Pet": {}}, openapi=version))
    assert warnings == []


def test_openapi_3_0_imports_with_a_warning():
    definitions, warnings = parse_openapi_components(_doc({"Pet": {}}, openapi="3.0.3"))
    assert list(definitions) == ["Pet"]
    assert len(warnings) == 1
    assert "3.0.3" in warnings[0]


@pytest.mark.parametrize(
    "dialect",
    [
        "https://json-schema.org/draft/2020-12/schema",
        "https://spec.openapis.org/oas/3.1/dialect/base",
        "https://json-schema.org/draft/2020-12/schema#",
    ],
)
def test_2020_12_dialects_are_accepted(dialect):
    _, warnings = parse_openapi_components(_doc({"Pet": {}}, jsonSchemaDialect=dialect))
    assert warnings == []


def test_other_dialect_warns():
    _, warnings = parse_openapi_components(
        _doc({"Pet": {}}, jsonSchemaDialect="http://json-schema.org/draft-07/schema#")
    )
    assert len(warnings) == 1
    assert "draft-07" in warnings[0]


def test_swagger_2_is_named():
    with pytest.raises(OpenApiComponentsError) as exc:
        parse_openapi_components({"swagger": "2.0", "definitions": {"Pet": {}}})
    assert "Swagger 2.0" in exc.value.message


@pytest.mark.parametrize(
    "document, needle",
    [
        ({"components": {"schemas": {"Pet": {}}}}, "'openapi' version field is missing"),
        ({"openapi": "4.0.0", "components": {"schemas": {"Pet": {}}}}, "Unsupported"),
        ({"openapi": "latest", "components": {"schemas": {"Pet": {}}}}, "Unsupported"),
        ({"openapi": "3.1.0"}, "No components.schemas"),
        ({"openapi": "3.1.0", "components": {"schemas": {}}}, "No components.schemas"),
        ({"openapi": "3.1.0", "components": {"schemas": []}}, "No components.schemas"),
        ({"openapi": "3.1.0", "components": "x"}, "No components.schemas"),
    ],
)
def test_unimportable_documents_raise(document, needle):
    with pytest.raises(OpenApiComponentsError) as exc:
        parse_openapi_components(document)
    assert needle in exc.value.message


def test_non_object_document_raises():
    with pytest.raises(OpenApiComponentsError):
        parse_openapi_components(["openapi"])


# --------------------------------------------------------------------------- #
# Ref rewrite of component pointers (#3463 reuse)
# --------------------------------------------------------------------------- #


def test_component_ref_rewrites_to_relative_registry_ref():
    assert rewrite_internal_ref("#/components/schemas/Money") == "./money"
    assert (
        rewrite_internal_ref("#/components/schemas/Money/properties/amount")
        == "./money#/properties/amount"
    )
    assert rewrite_internal_ref("#/components/schemas/Pet%20Tag") == "./pet-tag"


def test_non_schema_component_refs_are_left_alone():
    assert rewrite_internal_ref("#/components/parameters/limit") is None
    assert rewrite_internal_ref("#/components/schemas/") is None


def test_rewrite_import_schema_logs_component_rewrites():
    schema = {
        "type": "object",
        "properties": {
            "price": {"$ref": "#/components/schemas/Money"},
            "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
        },
    }
    rewritten, rewrites = rewrite_import_schema(
        schema, base_uri="https://api.apiome.dev/types/tenant/acme/", map_core_formats=False
    )
    assert rewritten["properties"]["price"] == {"$ref": "./money"}
    assert rewritten["properties"]["tags"]["items"] == {"$ref": "./tag"}
    assert rewrites == [
        {"from": "#/components/schemas/Money", "to": "./money", "kind": "internal"},
        {"from": "#/components/schemas/Tag", "to": "./tag", "kind": "internal"},
    ]
