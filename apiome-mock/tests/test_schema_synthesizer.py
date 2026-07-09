"""Unit tests for schema-driven mock data synthesis (SIM-1.3, #4418)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import jsonschema
import pytest
import yaml

from apiome_mock.schema_synthesizer import generate_example, parse_mock_seed, validate_value

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "openapi"


def _valid(value: object, schema: dict, root: dict | None = None) -> None:
    error = validate_value(value, schema, root)
    assert error is None, error


def test_explicit_example_wins() -> None:
    assert generate_example({"type": "string", "example": "hello"}) == "hello"


def test_const_and_default_and_enum() -> None:
    assert generate_example({"const": 42}) == 42
    assert generate_example({"type": "string", "default": "d"}) == "d"
    assert generate_example({"type": "string", "enum": ["a", "b"]}) == "a"


def test_integer_respects_bounds() -> None:
    schema = {"type": "integer", "minimum": 10, "maximum": 12}
    for seed in range(20):
        value = generate_example(schema, seed=seed)
        assert 10 <= value <= 12
        assert isinstance(value, int)


def test_string_format_email_uuid_and_timestamp_heuristics() -> None:
    email = generate_example({"type": "string", "format": "email"}, field="contactEmail")
    _valid(email, {"type": "string", "format": "email"})
    assert "@" in email

    uid = generate_example({"type": "string", "format": "uuid"}, field="resourceId")
    jsonschema.validate(uid, {"type": "string", "format": "uuid"})

    created = generate_example({"type": "string", "format": "date-time"}, field="createdAt")
    updated = generate_example({"type": "string", "format": "date-time"}, field="updatedAt")
    assert created.endswith("Z")
    assert updated.endswith("Z")


def test_pattern_generation() -> None:
    schema = {"type": "string", "pattern": "^[A-Z]{2}$"}
    value = generate_example(schema, field="country", seed=3)
    assert len(value) == 2 and value.isupper()
    _valid(value, schema)


def test_object_includes_required_properties() -> None:
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
    assert {"id", "name", "email"}.issubset(value.keys())
    _valid(value, schema)


def test_recursive_schema_terminates_under_100ms() -> None:
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
    started = time.perf_counter()
    value = generate_example({"$ref": "#/components/schemas/Node"}, root, seed=1)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert "value" in value
    assert elapsed_ms < 100


def test_deterministic_same_seed_same_output() -> None:
    schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }
    first = generate_example(schema, seed=99)
    second = generate_example(schema, seed=99)
    assert first == second


def test_parse_mock_seed_accepts_integers_and_strings() -> None:
    assert parse_mock_seed("42") == 42
    assert parse_mock_seed("alpha") == parse_mock_seed("alpha")
    assert parse_mock_seed(None) == 0


def test_seed_query_produces_byte_identical_json() -> None:
    schema = {
        "type": "object",
        "properties": {
            "email": {"type": "string", "format": "email"},
            "id": {"type": "string", "format": "uuid"},
        },
    }
    first = json.dumps(generate_example(schema, seed=parse_mock_seed("suite"), field="payload"))
    second = json.dumps(generate_example(schema, seed=parse_mock_seed("suite"), field="payload"))
    assert first == second


@pytest.mark.parametrize("yaml_path", sorted(EXAMPLES_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_examples_corpus_generates_schema_valid_bodies(yaml_path: Path) -> None:
    spec = yaml.safe_load(yaml_path.read_text())
    root = spec
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        value = generate_example(schema, root, seed=42, field=name)
        _valid(value, schema, root)

    for path_item in spec.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                if not isinstance(response, dict):
                    continue
                for media in response.get("content", {}).values():
                    schema = media.get("schema")
                    if isinstance(schema, dict):
                        value = generate_example(schema, root, seed=42, field="response")
                        _valid(value, schema, root)
