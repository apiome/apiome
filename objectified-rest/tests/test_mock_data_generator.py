"""Unit tests for the Mock Server schema-valid data generator (#3615, RC1-2.2)."""

import jsonschema
import pytest

from app.mock_data_generator import generate_example, validate_value


def _valid(value, schema, root=None):
    """Assert the generated value validates, surfacing the message on failure."""
    error = validate_value(value, schema, root)
    assert error is None, f"expected valid, got: {error}"


def test_explicit_example_wins():
    assert generate_example({"type": "string", "example": "hello"}) == "hello"


def test_const_and_default_and_enum():
    assert generate_example({"const": 42}) == 42
    assert generate_example({"type": "string", "default": "d"}) == "d"
    assert generate_example({"type": "string", "enum": ["a", "b"]}) == "a"


def test_examples_list_and_map():
    assert generate_example({"examples": ["x", "y"]}) == "x"
    schema = {"examples": {"primary": {"value": {"k": 1}}}}
    assert generate_example(schema) == {"k": 1}


def test_integer_respects_bounds():
    schema = {"type": "integer", "minimum": 10, "maximum": 12}
    for _ in range(20):
        value = generate_example(schema, seed=_)
        assert 10 <= value <= 12
        assert isinstance(value, int)


def test_number_multiple_of():
    schema = {"type": "number", "minimum": 0, "maximum": 100, "multipleOf": 5}
    value = generate_example(schema, seed=7)
    _valid(value, schema)


def test_string_min_max_length():
    schema = {"type": "string", "minLength": 5, "maxLength": 8}
    value = generate_example(schema, field="token", seed=3)
    assert 5 <= len(value) <= 8
    _valid(value, schema)


def test_string_format_email_and_uuid_validate():
    email = generate_example({"type": "string", "format": "email"}, field="x")
    _valid(email, {"type": "string", "format": "email"})
    uid = generate_example({"type": "string", "format": "uuid"}, field="x")
    jsonschema.validate(uid, {"type": "string", "format": "uuid"})


def test_object_includes_required_and_optional():
    schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "email": {"type": "string", "format": "email"},
        },
    }
    value = generate_example(schema, seed=1)
    assert set(["id", "name", "email"]).issubset(value.keys())
    _valid(value, schema)


def test_array_min_items():
    schema = {"type": "array", "minItems": 3, "items": {"type": "integer"}}
    value = generate_example(schema, seed=2)
    assert len(value) >= 3
    _valid(value, schema)


def test_ref_resolution_against_root():
    root = {
        "components": {
            "schemas": {
                "Pet": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
                }
            }
        }
    }
    schema = {"$ref": "#/components/schemas/Pet"}
    value = generate_example(schema, root, seed=5)
    assert "id" in value
    _valid(value, schema, root)


def test_all_of_merges_properties():
    schema = {
        "allOf": [
            {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
            {"type": "object", "required": ["b"], "properties": {"b": {"type": "integer"}}},
        ]
    }
    value = generate_example(schema, seed=1)
    assert "a" in value and "b" in value
    _valid(value, schema)


def test_one_of_picks_first_branch():
    schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
    assert isinstance(generate_example(schema, seed=1), str)


def test_recursive_schema_terminates():
    root = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {
                        "value": {"type": "integer"},
                        "child": {"$ref": "#/components/schemas/Node"},
                    },
                }
            }
        }
    }
    # Must not blow the stack; depth cap drops the optional self-reference eventually.
    value = generate_example({"$ref": "#/components/schemas/Node"}, root, seed=1)
    assert "value" in value


def test_deterministic_same_seed_same_output():
    schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }
    a = generate_example(schema, seed=99)
    b = generate_example(schema, seed=99)
    assert a == b


def test_validate_value_reports_error():
    schema = {"type": "integer"}
    assert validate_value("not-an-int", schema) is not None
