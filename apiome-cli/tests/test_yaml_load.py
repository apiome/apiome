"""Tests for JSON-safe YAML loading during import."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from apiome_cli.import_.yaml_load import safe_load_mapping


def test_safe_load_mapping_keeps_yaml_boolean_words_as_strings() -> None:
    text = """
parameters:
  - name: on
    in: path
    required: true
x-flag: yes
enabled: false
"""
    doc = safe_load_mapping(text)
    assert doc["parameters"][0]["name"] == "on"
    assert doc["x-flag"] == "yes"
    assert doc["enabled"] is False


def test_safe_load_mapping_keeps_rfc3339_timestamps_as_strings() -> None:
    """ISO-8601 example values must stay strings for JSON upload."""
    text = """
openapi: 3.0.0
info:
  title: Events API
  version: 1.0.0
components:
  schemas:
    DateTimeRFC3339:
      example: 2020-06-11T16:32:50Z
"""
    doc = safe_load_mapping(text)
    example = doc["components"]["schemas"]["DateTimeRFC3339"]["example"]
    assert isinstance(example, str)
    assert example == "2020-06-11T16:32:50Z"
    json.dumps(doc)


def test_safe_load_mapping_rejects_non_mapping() -> None:
    """Top-level YAML sequences raise ValueError."""
    with pytest.raises(ValueError, match="Expected a YAML mapping"):
        safe_load_mapping("- item\n")


def test_safe_load_mapping_does_not_use_datetime() -> None:
    """Nested timestamp-like values are never coerced to datetime."""
    text = """
root:
  nested:
    value: 2021-06-11T16:32:50Z
"""
    doc = safe_load_mapping(text)
    value = doc["root"]["nested"]["value"]
    assert not isinstance(value, datetime)


def test_safe_load_mapping_accepts_yaml_value_tag_scalars() -> None:
    """YAML 1.1 ``!!value`` list items such as ``- =`` decode as plain strings."""
    text = """
components:
  schemas:
    Operator:
      enum:
        - =
        - "!="
"""
    doc = safe_load_mapping(text)
    assert doc["components"]["schemas"]["Operator"]["enum"] == ["=", "!="]


def test_safe_load_mapping_replaces_unicode_line_separators() -> None:
    text = (
        "info:\n"
        "  description: |\n"
        "    before\u2028\u2028 after\n"
        "  title: Demo\n"
    )
    doc = safe_load_mapping(text)
    assert doc["info"]["description"] == "before   after\n"
