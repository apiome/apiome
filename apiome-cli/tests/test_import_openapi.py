"""Tests for OpenAPI document parsing (YAML, JSON, stdin).

Covers:
- .json file parsing (valid / invalid / non-object)
- .yaml and .yml file parsing (valid / invalid / non-object)
- stdin ("-") with JSON, YAML, and invalid content
- stdin auto-detection: JSON wins, YAML fallback
- Unsupported extension error
- File-not-found propagation (OSError)
"""

from __future__ import annotations

import json
import textwrap
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from apiome_cli.import_.openapi import load_openapi_file

# ---------------------------------------------------------------------------
# Fixtures — minimal but valid-enough OpenAPI snippets
# ---------------------------------------------------------------------------

_OPENAPI_JSON = json.dumps(
    {
        "openapi": "3.1.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "paths": {},
    }
)

_OPENAPI_YAML = textwrap.dedent(
    """\
    openapi: "3.1.0"
    info:
      title: Test API
      version: "1.0.0"
    paths: {}
    """
)

_OPENAPI_YML = _OPENAPI_YAML  # same content, different extension

_INVALID_JSON = "{ not valid json"

_INVALID_YAML = "key: [\nunot closed"

_ARRAY_JSON = json.dumps([1, 2, 3])  # top-level array, not an object

_ARRAY_YAML = "- item1\n- item2\n"  # top-level list, not a mapping


# ---------------------------------------------------------------------------
# JSON file tests
# ---------------------------------------------------------------------------


def test_load_json_file_returns_dict(tmp_path: Path) -> None:
    """Valid JSON file is parsed to a dict."""
    f = tmp_path / "spec.json"
    f.write_text(_OPENAPI_JSON, encoding="utf-8")

    result = load_openapi_file(str(f))

    assert isinstance(result, dict)
    assert result["openapi"] == "3.1.0"
    assert result["info"]["title"] == "Test API"


def test_load_json_file_invalid_syntax_raises_value_error(tmp_path: Path) -> None:
    """Malformed JSON raises ValueError with the file path in the message."""
    f = tmp_path / "bad.json"
    f.write_text(_INVALID_JSON, encoding="utf-8")

    with pytest.raises(ValueError, match="bad.json"):
        load_openapi_file(str(f))


def test_load_json_file_top_level_array_raises_value_error(tmp_path: Path) -> None:
    """JSON that is a top-level array (not an object) raises ValueError."""
    f = tmp_path / "array.json"
    f.write_text(_ARRAY_JSON, encoding="utf-8")

    with pytest.raises(ValueError, match="top level"):
        load_openapi_file(str(f))


# ---------------------------------------------------------------------------
# YAML file tests (.yaml)
# ---------------------------------------------------------------------------


def test_load_yaml_file_returns_dict(tmp_path: Path) -> None:
    """Valid .yaml file is parsed to a dict."""
    f = tmp_path / "spec.yaml"
    f.write_text(_OPENAPI_YAML, encoding="utf-8")

    result = load_openapi_file(str(f))

    assert isinstance(result, dict)
    assert result["openapi"] == "3.1.0"


def test_load_yaml_file_invalid_syntax_raises_value_error(tmp_path: Path) -> None:
    """Malformed YAML raises ValueError with the file path in the message."""
    f = tmp_path / "bad.yaml"
    f.write_text(_INVALID_YAML, encoding="utf-8")

    with pytest.raises(ValueError, match="bad.yaml"):
        load_openapi_file(str(f))


def test_load_yaml_file_top_level_list_raises_value_error(tmp_path: Path) -> None:
    """YAML that is a top-level list (not a mapping) raises ValueError."""
    f = tmp_path / "list.yaml"
    f.write_text(_ARRAY_YAML, encoding="utf-8")

    with pytest.raises(ValueError, match="top level"):
        load_openapi_file(str(f))


# ---------------------------------------------------------------------------
# YAML file tests (.yml)
# ---------------------------------------------------------------------------


def test_load_yml_file_returns_dict(tmp_path: Path) -> None:
    """Valid .yml file is parsed to a dict."""
    f = tmp_path / "spec.yml"
    f.write_text(_OPENAPI_YML, encoding="utf-8")

    result = load_openapi_file(str(f))

    assert isinstance(result, dict)
    assert result["openapi"] == "3.1.0"


def test_load_yml_file_invalid_syntax_raises_value_error(tmp_path: Path) -> None:
    """Malformed .yml file raises ValueError with the file path in the message."""
    f = tmp_path / "bad.yml"
    f.write_text(_INVALID_YAML, encoding="utf-8")

    with pytest.raises(ValueError, match="bad.yml"):
        load_openapi_file(str(f))


# ---------------------------------------------------------------------------
# Unsupported extension
# ---------------------------------------------------------------------------


def test_unsupported_extension_raises_value_error(tmp_path: Path) -> None:
    """Files with an unrecognised extension raise ValueError."""
    f = tmp_path / "spec.toml"
    f.write_text("openapi = '3.1.0'\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.toml"):
        load_openapi_file(str(f))


def test_no_extension_raises_value_error(tmp_path: Path) -> None:
    """Files with no extension raise ValueError."""
    f = tmp_path / "openapi"
    f.write_text(_OPENAPI_YAML, encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported"):
        load_openapi_file(str(f))


# ---------------------------------------------------------------------------
# File-not-found / OS errors
# ---------------------------------------------------------------------------


def test_missing_file_raises_oserror(tmp_path: Path) -> None:
    """A path that does not exist propagates an OSError (FileNotFoundError)."""
    missing = tmp_path / "nonexistent.yaml"

    with pytest.raises(OSError):
        load_openapi_file(str(missing))


# ---------------------------------------------------------------------------
# stdin ("-") tests
# ---------------------------------------------------------------------------


def test_stdin_json_returns_dict() -> None:
    """JSON piped to stdin is detected and parsed."""
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(_OPENAPI_JSON)):
        result = load_openapi_file("-")

    assert isinstance(result, dict)
    assert result["openapi"] == "3.1.0"


def test_stdin_yaml_returns_dict() -> None:
    """Pure YAML piped to stdin falls back from JSON and is parsed as YAML."""
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(_OPENAPI_YAML)):
        result = load_openapi_file("-")

    assert isinstance(result, dict)
    assert result["openapi"] == "3.1.0"


def test_stdin_invalid_raises_value_error() -> None:
    """Content that cannot be parsed as JSON or YAML raises ValueError."""
    garbage = "<<< not json nor yaml >>>"
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(garbage)):
        with pytest.raises(ValueError, match="could not be parsed"):
            load_openapi_file("-")


def test_stdin_top_level_array_json_raises_value_error() -> None:
    """JSON array (not object) on stdin raises the JSON top-level type error."""
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(_ARRAY_JSON)):
        with pytest.raises(ValueError, match="Expected a JSON object"):
            load_openapi_file("-")


def test_stdin_top_level_list_yaml_raises_value_error() -> None:
    """YAML list (not mapping) on stdin raises ValueError."""
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(_ARRAY_YAML)):
        with pytest.raises(ValueError):
            load_openapi_file("-")


def test_stdin_json_preferred_over_yaml() -> None:
    """JSON is attempted before YAML; valid JSON content wins."""
    # JSON that is also valid YAML — we want the JSON parser to win, which
    # means the returned dict is identical regardless, but we verify no error
    # occurs and the data is correct.
    content = '{"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": {}}'
    with patch("apiome_cli.import_.source.sys.stdin", StringIO(content)):
        result = load_openapi_file("-")

    assert result["openapi"] == "3.1.0"


# ---------------------------------------------------------------------------
# Case-insensitive extension detection
# ---------------------------------------------------------------------------


def test_uppercase_json_extension_is_supported(tmp_path: Path) -> None:
    """File extension matching is case-insensitive (.JSON, .YAML, .YML)."""
    f = tmp_path / "SPEC.JSON"
    f.write_text(_OPENAPI_JSON, encoding="utf-8")

    result = load_openapi_file(str(f))

    assert result["openapi"] == "3.1.0"


def test_uppercase_yaml_extension_is_supported(tmp_path: Path) -> None:
    """YAML extension matching is case-insensitive."""
    f = tmp_path / "SPEC.YAML"
    f.write_text(_OPENAPI_YAML, encoding="utf-8")

    result = load_openapi_file(str(f))

    assert result["openapi"] == "3.1.0"
