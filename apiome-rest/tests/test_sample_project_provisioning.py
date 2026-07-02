"""Render contract for the seeded "Pet Store" sample project (#3614).

A fresh tenant is auto-provisioned a curated sample project by the shared
`apiome.provision_sample_project()` routine (apiome-db migration V122). Browse renders a version
by REGENERATING its OpenAPI spec live from `classes` + `class_properties` (see
`app.openapi_generator.build_class_openapi_schema`, consumed by `GET /v1/schema/...`), so the
sample's `class_properties.data` shapes are the contract that makes the seeded spec browsable.

These hermetic tests pin that contract: they feed the generator the exact class/property shapes the
migration inserts and assert the rendered schemas (titles, properties, required arrays, the status
enum) so drift in either the seed data shape or the generator is caught. The end-to-end render was
also verified live: `GET /v1/schema/<tenant>/petstore-sample/1.0.0` returns HTTP 200 with these
schemas.
"""

from app.openapi_generator import build_class_openapi_schema

# Mirrors the class_properties.data fragments inserted by V122 (id/name are required; status is an
# optional enum). parent_id=None marks them top-level (flat scalar fields).
_ID_FIELD = {
    "id": "cp-id",
    "name": "id",
    "parent_id": None,
    "data": {"type": "integer", "format": "int64", "description": "Unique identifier.", "required": True},
}
_NAME_FIELD = {
    "id": "cp-name",
    "name": "name",
    "parent_id": None,
    "data": {"type": "string", "description": "Display name.", "required": True},
}
_STATUS_FIELD = {
    "id": "cp-status",
    "name": "status",
    "parent_id": None,
    "data": {
        "type": "string",
        "enum": ["available", "pending", "sold"],
        "description": "Pet availability status.",
    },
}


def test_pet_class_renders_with_required_and_status_enum():
    schema = build_class_openapi_schema(
        {"name": "Pet", "description": "A pet available in the store.", "schema": {"type": "object"}},
        [_ID_FIELD, _NAME_FIELD, _STATUS_FIELD],
    )

    assert schema["type"] == "object"
    assert schema["title"] == "Pet"
    assert set(schema["properties"].keys()) == {"id", "name", "status"}
    # "required": true fragments promote into the class-level required array; status stays optional.
    assert sorted(schema["required"]) == ["id", "name"]
    assert "required" not in schema["properties"]["id"]  # flag moved up, not left on the field
    assert schema["properties"]["status"]["enum"] == ["available", "pending", "sold"]
    assert schema["properties"]["id"]["format"] == "int64"


def test_category_class_renders_two_required_fields():
    schema = build_class_openapi_schema(
        {"name": "Category", "description": "A grouping for pets.", "schema": {"type": "object"}},
        [_ID_FIELD, _NAME_FIELD],
    )
    assert schema["title"] == "Category"
    assert set(schema["properties"].keys()) == {"id", "name"}
    assert sorted(schema["required"]) == ["id", "name"]


def test_tag_class_matches_category_shape():
    schema = build_class_openapi_schema(
        {"name": "Tag", "description": "A label applied to a pet.", "schema": {"type": "object"}},
        [_ID_FIELD, _NAME_FIELD],
    )
    assert schema["title"] == "Tag"
    assert sorted(schema["required"]) == ["id", "name"]
    assert schema["properties"]["name"]["type"] == "string"
