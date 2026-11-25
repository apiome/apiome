"""Provider schemas as the cross-contract comparison reads them — PFX-2.2 (#6926)."""

from __future__ import annotations

import copy
from typing import Any, Dict

from app.pact_oas_schema import (
    MAX_SITE_FINDINGS,
    REQUEST,
    RESPONSE,
    ProviderSchemas,
    pointer_tokens,
)

BODY = "/paths/~1pets/get/responses/200/content/application~1json/schema"


def _document(
    schema: Dict[str, Any], *, version: str = "3.0.3", **components: Any
) -> Dict[str, Any]:
    """A provider document whose one response body has the given schema."""
    return {
        "openapi": version,
        "paths": {
            "/pets": {
                "get": {
                    "responses": {
                        "200": {
                            "headers": {
                                "schema": {"schema": {"type": "integer", "nullable": True}}
                            },
                            "content": {
                                "application/json": {
                                    "schema": schema,
                                    "example": {"schema": {"nullable": True, "required": ["x"]}},
                                }
                            },
                        }
                    }
                }
            }
        },
        "components": {"schemas": components},
    }


PET = {
    "type": "object",
    "required": ["id"],
    "properties": {
        "id": {"type": "integer", "minimum": 0, "exclusiveMinimum": True},
        "tag": {"type": "string", "nullable": True},
        "weight": {"type": "number", "maximum": 100, "exclusiveMaximum": False},
        "owner": {"$ref": "#/components/schemas/Owner"},
    },
}
OWNER = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}


def _keywords(schemas: ProviderSchemas, side: str, value: Any, pointer: str = BODY) -> list:
    outcome = schemas.validate(side, pointer, value)
    assert outcome is not None
    return [(finding.keyword, finding.pointer) for finding in outcome[0]]


def test_pointer_tokens() -> None:
    assert pointer_tokens("") == []
    assert pointer_tokens("/paths/~1pets~1{id}/a~0b") == ["paths", "/pets/{id}", "a~b"]


def test_published_document_is_never_modified() -> None:
    document = _document({"$ref": "#/components/schemas/Pet"}, Pet=PET, Owner=OWNER)
    before = copy.deepcopy(document)

    schemas = ProviderSchemas(document)
    schemas.validate(REQUEST, BODY, {"id": 1})
    schemas.validate(RESPONSE, BODY, {"id": 1})
    schemas.one_of_applies(BODY, {"id": 1})

    assert document == before


def test_request_view_holds_the_schema_as_written() -> None:
    schemas = ProviderSchemas(_document({"$ref": "#/components/schemas/Pet"}, Pet=PET, Owner=OWNER))

    assert _keywords(schemas, REQUEST, {"id": 1, "tag": None, "weight": 100, "extra": True}) == []
    assert _keywords(schemas, REQUEST, {"tag": "a"}) == [("required", "")]
    assert _keywords(schemas, REQUEST, {"id": 1, "owner": {}}) == [("required", "/owner")]


def test_openapi_3_0_keywords_are_read_as_2020_12() -> None:
    schemas = ProviderSchemas(_document({"$ref": "#/components/schemas/Pet"}, Pet=PET, Owner=OWNER))

    # nullable: true admits null; a property without it does not.
    assert _keywords(schemas, REQUEST, {"id": 1, "tag": None}) == []
    assert _keywords(schemas, REQUEST, {"id": None}) == [("type", "/id")]
    # exclusiveMinimum: true excludes the bound; exclusiveMaximum: false keeps it.
    assert _keywords(schemas, REQUEST, {"id": 0}) == [("exclusiveMinimum", "/id")]
    assert _keywords(schemas, REQUEST, {"id": 1, "weight": 100}) == []
    assert _keywords(schemas, REQUEST, {"id": 1, "weight": 101}) == [("maximum", "/weight")]
    assert schemas.node("/components/schemas/Pet/properties/tag", normalized=True) == {
        "type": ["string", "null"]
    }
    assert schemas.node("/components/schemas/Pet/properties/tag") == {
        "type": "string",
        "nullable": True,
    }


def test_openapi_3_1_document_is_not_rewritten_for_requests() -> None:
    schema = {
        "type": "object",
        "properties": {"nullable": {"type": "boolean"}, "n": {"exclusiveMinimum": 3}},
    }
    schemas = ProviderSchemas(_document(schema, version="3.1.0"))

    assert schemas.oas30 is False
    assert schemas.node(BODY, normalized=True) == schema
    assert _keywords(schemas, REQUEST, {"nullable": True, "n": 3}) == [("exclusiveMinimum", "/n")]


def test_response_view_lifts_required_and_closes_objects() -> None:
    schemas = ProviderSchemas(_document({"$ref": "#/components/schemas/Pet"}, Pet=PET, Owner=OWNER))

    # A consumer may read fewer properties than the provider requires ...
    assert _keywords(schemas, RESPONSE, {"tag": "a", "owner": {}}) == []
    # ... but never one the provider does not declare, at any depth.
    assert _keywords(schemas, RESPONSE, {"id": 1, "colour": "red"}) == [
        ("unevaluatedProperties", "")
    ]
    assert _keywords(schemas, RESPONSE, {"owner": {"name": "a", "age": 3}}) == [
        ("unevaluatedProperties", "/owner")
    ]
    # Type mistakes are still type mistakes.
    assert _keywords(schemas, RESPONSE, {"id": "1"}) == [("type", "/id")]


def test_response_view_respects_objects_the_provider_opened() -> None:
    schema = {
        "type": "object",
        "properties": {
            "open": {"type": "object", "additionalProperties": True},
            "typed": {"type": "object", "additionalProperties": {"type": "integer"}},
            "closed": {"type": "object", "properties": {"a": {"type": "string"}}},
        },
    }
    schemas = ProviderSchemas(_document(schema))

    assert _keywords(schemas, RESPONSE, {"open": {"x": 1}, "typed": {"y": 2}}) == []
    # A value that fails its own schema also leaves its object "unevaluated"; the engine
    # reports the first and recognises the second as its echo.
    assert _keywords(schemas, RESPONSE, {"typed": {"y": "2"}}) == [
        ("unevaluatedProperties", "/typed"),
        ("type", "/typed/y"),
    ]
    assert _keywords(schemas, RESPONSE, {"closed": {"b": 1}}) == [
        ("unevaluatedProperties", "/closed")
    ]


def test_response_view_sees_properties_across_all_of_branches() -> None:
    schema = {
        "allOf": [
            {"$ref": "#/components/schemas/Owner"},
            {"type": "object", "required": ["rank"], "properties": {"rank": {"type": "integer"}}},
        ]
    }
    schemas = ProviderSchemas(_document(schema, Owner=OWNER))

    assert _keywords(schemas, RESPONSE, {"name": "a", "rank": 1}) == []
    assert _keywords(schemas, RESPONSE, {"name": "a"}) == []
    assert _keywords(schemas, RESPONSE, {"name": "a", "x": 1}) == [("unevaluatedProperties", "")]
    assert schemas.declared_properties(BODY) == {"name", "rank"}


def test_one_of_is_read_as_any_of_in_a_response_and_says_where_it_applied() -> None:
    cat = {"type": "object", "required": ["meow"], "properties": {"meow": {"type": "boolean"}}}
    dog = {"type": "object", "required": ["bark"], "properties": {"bark": {"type": "boolean"}}}
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "pet": {"oneOf": [{"$ref": "#/components/schemas/Cat"}, {"$ref": "#/components/schemas/Dog"}]},
        },
    }
    schemas = ProviderSchemas(_document(schema, Cat=cat, Dog=dog))

    # As a request the oneOf is exact.
    assert _keywords(schemas, REQUEST, {"pet": {"meow": True}}) == []
    assert _keywords(schemas, REQUEST, {"pet": {}}) == [("oneOf", "/pet")]
    # As a response, required is lifted, so an empty pet fits both branches: read as anyOf.
    assert _keywords(schemas, RESPONSE, {"pet": {}}) == []
    assert _keywords(schemas, RESPONSE, {"pet": {"meow": True}}) == []
    # A property with the wrong type fails the branch that declares it; the other branch
    # does not declare it at all, so the object is refused as a whole.
    assert _keywords(schemas, RESPONSE, {"pet": {"meow": "loud"}}) == [
        ("unevaluatedProperties", "/pet")
    ]
    assert _keywords(schemas, RESPONSE, {"pet": 3}) == [("anyOf", "/pet")]
    # The weaker reading is reported only for a body the oneOf actually describes.
    assert schemas.uses_one_of(BODY) is True
    assert schemas.one_of_applies(BODY, {"pet": {"meow": True}}) is True
    assert schemas.one_of_applies(BODY, {"name": "Rex"}) is False
    assert schemas.uses_one_of("/components/schemas/Cat") is False
    assert schemas.one_of_applies("/components/schemas/Cat", {"meow": True}) is False


def test_required_inside_not_and_if_keeps_its_meaning() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "not": {"required": ["a", "b"]},
    }
    schemas = ProviderSchemas(_document(schema))

    assert _keywords(schemas, RESPONSE, {"a": 1}) == []
    assert _keywords(schemas, RESPONSE, {"a": 1, "b": 2}) == [("not", "")]


def test_example_data_and_name_maps_are_not_read_as_schemas() -> None:
    document = _document(
        {"type": "object", "properties": {"schema": {"type": "string", "nullable": True}}}
    )
    schemas = ProviderSchemas(document)
    response = "/paths/~1pets/get/responses/200"

    # A header *named* "schema" is a header, and its own schema is still normalized.
    assert schemas.node(f"{response}/headers/schema/schema", normalized=True) == {
        "type": ["integer", "null"]
    }
    # An example that happens to look like a schema is left exactly as written.
    example = schemas.node(f"{response}/content/application~1json/example", normalized=True)
    assert example == {"schema": {"nullable": True, "required": ["x"]}}
    # A property *named* "schema" is a property.
    assert _keywords(schemas, RESPONSE, {"schema": None}) == []


def test_unusable_schemas_are_reported_as_not_checked() -> None:
    schemas = ProviderSchemas(
        _document(
            {"$ref": "./other.yaml#/Thing"},
            Broken={"type": 17},
            Loop={"$ref": "#/components/schemas/Loop"},
        )
    )

    assert schemas.validate(RESPONSE, BODY, {}) is None
    assert schemas.validate(REQUEST, "/components/schemas/Broken", 1) is None
    assert schemas.validate(REQUEST, "/components/schemas/Missing", 1) is None


def test_findings_are_capped_per_site() -> None:
    schema = {"type": "array", "items": {"type": "integer"}}
    schemas = ProviderSchemas(_document(schema))

    findings, total = schemas.validate(REQUEST, BODY, ["x"] * (MAX_SITE_FINDINGS + 5))  # type: ignore[misc]

    assert len(findings) == MAX_SITE_FINDINGS
    assert total == MAX_SITE_FINDINGS + 5


def test_locate_walks_a_validator_path_through_references() -> None:
    schemas = ProviderSchemas(_document({"$ref": "#/components/schemas/Pet"}, Pet=PET, Owner=OWNER))

    assert schemas.locate(BODY, ["properties", "owner", "properties", "name", "type"]) == (
        "/components/schemas/Owner/properties/name/type"
    )
    assert schemas.locate(BODY, ["required"]) == "/components/schemas/Pet/required"
    # A keyword the view added is placed on the schema that would have to change.
    assert (
        schemas.locate(BODY, ["properties", "owner", "unevaluatedProperties"])
        == "/components/schemas/Owner"
    )
    assert schemas.locate(BODY, []) == BODY
    assert schemas.follow(BODY) == "/components/schemas/Pet"
    assert schemas.follow("/components/schemas/Pet") == "/components/schemas/Pet"


def test_locate_names_one_of_where_the_view_reads_any_of() -> None:
    schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    schemas = ProviderSchemas(_document(schema))

    assert schemas.locate(BODY, ["anyOf", "1", "type"]) == f"{BODY}/oneOf/1/type"
    assert schemas.locate(BODY, ["anyOf", "7", "type"]) == f"{BODY}/oneOf"


def test_reference_loops_terminate() -> None:
    schemas = ProviderSchemas(
        _document(
            {"$ref": "#/components/schemas/A"},
            A={"$ref": "#/components/schemas/B"},
            B={"$ref": "#/components/schemas/A"},
            Node={"type": "object", "properties": {"next": {"$ref": "#/components/schemas/Node"}}},
        )
    )

    assert schemas.follow(BODY) in ("/components/schemas/A", "/components/schemas/B")
    assert schemas.declared_properties(BODY) == set()
    assert schemas.uses_one_of("/components/schemas/Node") is False
    assert schemas.declared_properties("/components/schemas/Node") == {"next"}
    assert schemas.descend("/components/schemas/Node", ["next", "next", "next"]) == (
        "/components/schemas/Node",
        None,
    )


def test_declared_properties_is_unknown_for_an_open_object() -> None:
    schemas = ProviderSchemas(
        _document(
            {"type": "object", "properties": {"a": {}}, "additionalProperties": {"type": "string"}},
            Patterned={"type": "object", "patternProperties": {"^x-": {}}},
            Closed={"type": "object", "properties": {"a": {}}, "additionalProperties": False},
        )
    )

    assert schemas.declared_properties(BODY) is None
    assert schemas.declared_properties("/components/schemas/Patterned") is None
    assert schemas.declared_properties("/components/schemas/Closed") == {"a"}


def test_descend_finds_the_schema_of_a_value() -> None:
    schema = {
        "type": "object",
        "properties": {
            "lines": {"type": "array", "items": {"$ref": "#/components/schemas/Owner"}},
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
            "either": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
        },
    }
    schemas = ProviderSchemas(_document(schema, Owner=OWNER))

    assert schemas.descend(BODY, ["lines", 0, "name"]) == (
        "/components/schemas/Owner/properties/name",
        None,
    )
    assert schemas.descend(BODY, ["lines", None]) == ("/components/schemas/Owner", None)
    assert schemas.descend(BODY, ["labels", "anything"]) == (
        f"{BODY}/properties/labels/additionalProperties",
        None,
    )
    assert schemas.descend(BODY, ["either"]) == (None, "composition")
    assert schemas.descend(BODY, ["either", "x"]) == (None, "composition")
    assert schemas.descend(BODY, ["missing"]) == (None, "path-not-declared")
    assert schemas.descend(BODY, ["lines", "name"]) == (None, "path-not-declared")
    assert schemas.descend(BODY, []) == (BODY, None)
