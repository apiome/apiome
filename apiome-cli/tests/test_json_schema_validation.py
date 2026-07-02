"""Tests for JSON Schema 2020-12 structural validation (jsonschema).

Covers:
- Valid Draft 2020-12 property and composite schemas pass meta-schema validation
- OpenAPI payloads are rejected with a clear message
- Unsupported or invalid ``$schema`` values are rejected
- Invalid schema vocabulary raises JsonSchemaStructureError
- JsonSchemaStructureError uses EXIT_USAGE (2) for CLI mapping
- load_and_validate_json_schema_file integrates parse + validate
- load_json_schema_file parsing for JSON, YAML, and stdin
"""

from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.json_schema import (
    JsonSchemaStructureError,
    JsonSchemaTarget,
    detect_target,
    infer_name,
    load_and_validate_json_schema_file,
    load_json_schema_file,
    source_basename,
    validate_json_schema_structure,
)

_VALID_PROPERTY = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "string",
    "title": "Email",
    "format": "email",
}

_VALID_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "title": "User",
    "properties": {
        "email": {"type": "string"},
    },
}

_VALID_NO_META = {
    "type": "string",
    "title": "LegacyField",
}

_VALID_HYPER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/hyper-schema",
    "type": "object",
}


def test_detect_target_defaults_to_property() -> None:
    assert detect_target(_VALID_PROPERTY) == JsonSchemaTarget.property


def test_detect_target_detects_schema_from_properties() -> None:
    assert detect_target(_VALID_SCHEMA) == JsonSchemaTarget.schema


def test_infer_name_uses_title() -> None:
    assert infer_name(_VALID_PROPERTY, explicit_name=None, source_file=None) == "Email"


def test_infer_name_uses_filename_stem() -> None:
    document = {"type": "string"}
    assert (
        infer_name(document, explicit_name=None, source_file="contact-email.json")
        == "contact-email"
    )


def test_source_basename_returns_none_for_stdin() -> None:
    assert source_basename("-") is None


def test_validate_accepts_draft_2020_12_property() -> None:
    validate_json_schema_structure(_VALID_PROPERTY)


def test_validate_accepts_draft_2020_12_composite_schema() -> None:
    validate_json_schema_structure(_VALID_SCHEMA)


def test_validate_accepts_schema_without_meta_when_vocabulary_present() -> None:
    validate_json_schema_structure(_VALID_NO_META)


def test_validate_accepts_draft_2020_12_hyper_schema_uri() -> None:
    validate_json_schema_structure(_VALID_HYPER_SCHEMA)


def test_validate_rejects_openapi_payload() -> None:
    with pytest.raises(JsonSchemaStructureError, match="OpenAPI"):
        validate_json_schema_structure(
            {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}}
        )


def test_validate_rejects_non_string_schema_uri() -> None:
    with pytest.raises(JsonSchemaStructureError, match="string URI"):
        validate_json_schema_structure(
            {"$schema": 42, "type": "string", "title": "Bad"}
        )


def test_validate_rejects_empty_schema_uri() -> None:
    with pytest.raises(JsonSchemaStructureError, match="string URI"):
        validate_json_schema_structure(
            {"$schema": "   ", "type": "string", "title": "Blank"}
        )


def test_validate_rejects_unsupported_schema_uri() -> None:
    with pytest.raises(JsonSchemaStructureError, match="Unsupported"):
        validate_json_schema_structure(
            {
                "$schema": "https://example.com/meta/draft/2020-12/custom",
                "type": "string",
                "title": "Custom202012",
            }
        )


def test_validate_rejects_invalid_meta_schema() -> None:
    with pytest.raises(JsonSchemaStructureError):
        validate_json_schema_structure(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": "not-a-mapping",
            }
        )


def test_json_schema_structure_error_uses_exit_usage() -> None:
    assert JsonSchemaStructureError.exit_code == EXIT_USAGE
    err = JsonSchemaStructureError("invalid schema")
    assert err.message == "invalid schema"
    assert err.exit_code == EXIT_USAGE


def test_load_and_validate_json_schema_file(tmp_path: Path) -> None:
    path = tmp_path / "email.json"
    path.write_text(json.dumps(_VALID_PROPERTY), encoding="utf-8")
    assert load_and_validate_json_schema_file(str(path)) == _VALID_PROPERTY


def test_load_and_validate_rejects_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": "must-be-array",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(JsonSchemaStructureError):
        load_and_validate_json_schema_file(str(path))


def test_load_json_schema_file_json(tmp_path: Path) -> None:
    path = tmp_path / "field.json"
    path.write_text(json.dumps(_VALID_NO_META), encoding="utf-8")
    assert load_json_schema_file(str(path)) == _VALID_NO_META


def test_load_json_schema_file_invalid_json_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.json"):
        load_json_schema_file(str(path))


def test_load_json_schema_file_top_level_array_raises_value_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="top level"):
        load_json_schema_file(str(path))


def test_load_json_schema_file_yaml(tmp_path: Path) -> None:
    path = tmp_path / "field.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            $schema: https://json-schema.org/draft/2020-12/schema
            type: string
            title: FromYaml
            """
        ),
        encoding="utf-8",
    )
    document = load_json_schema_file(str(path))
    assert document["title"] == "FromYaml"


def test_load_json_schema_file_invalid_yaml_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("key: [\nunclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml"):
        load_json_schema_file(str(path))


def test_load_json_schema_file_top_level_list_raises_value_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="top level"):
        load_json_schema_file(str(path))


def test_load_json_schema_file_uppercase_json_extension(tmp_path: Path) -> None:
    path = tmp_path / "FIELD.JSON"
    path.write_text(json.dumps(_VALID_NO_META), encoding="utf-8")
    assert load_json_schema_file(str(path)) == _VALID_NO_META


def test_load_json_schema_file_uppercase_yaml_extension(tmp_path: Path) -> None:
    path = tmp_path / "FIELD.YAML"
    path.write_text("type: string\ntitle: UpperYaml\n", encoding="utf-8")
    assert load_json_schema_file(str(path))["title"] == "UpperYaml"


def test_load_json_schema_file_unsupported_extension(tmp_path: Path) -> None:
    path = tmp_path / "field.txt"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        load_json_schema_file(str(path))


def test_load_json_schema_file_missing_file_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_json_schema_file(str(tmp_path / "missing.yaml"))


def test_load_json_schema_file_stdin_json() -> None:
    payload = json.dumps(_VALID_PROPERTY)
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(payload)):
        assert load_json_schema_file("-") == _VALID_PROPERTY


def test_load_json_schema_file_stdin_yaml() -> None:
    payload = textwrap.dedent(
        """\
        type: string
        title: StdinYaml
        """
    )
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(payload)):
        document = load_json_schema_file("-")
    assert document["title"] == "StdinYaml"


def test_load_json_schema_file_stdin_invalid_raises_value_error() -> None:
    with patch("apiome_cli.import_.source.sys.stdin", StringIO("<<< not json nor yaml >>>")):
        with pytest.raises(ValueError, match="could not be parsed"):
            load_json_schema_file("-")


def test_load_json_schema_file_stdin_json_array_raises_value_error() -> None:
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(json.dumps([1, 2, 3]))):
        with pytest.raises(ValueError, match="Expected a JSON object"):
            load_json_schema_file("-")


def test_load_json_schema_file_stdin_yaml_list_raises_value_error() -> None:
    with patch("apiome_cli.import_.source.sys.stdin", StringIO("- item1\n- item2\n")):
        with pytest.raises(ValueError, match="top level"):
            load_json_schema_file("-")
