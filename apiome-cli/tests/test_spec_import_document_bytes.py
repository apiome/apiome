"""Unit tests for ``document_bytes_from_spec`` serialization.

The import worker parses uploaded documents with a strict JS YAML reader, and re-serializing a parsed
spec back to YAML can emit constructs that reader rejects (e.g. a description line beginning
``- **field**:`` becomes an ambiguous block sequence), even when the original parsed cleanly. So the
CLI always uploads JSON regardless of the source filename — JSON is unambiguous and is itself valid
YAML.
"""

from __future__ import annotations

import json
import datetime

from yaml12 import parse_yaml

from apiome_cli.import_.spec_import import document_bytes_from_spec

_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Apiome REST API", "version": "1.0.63"},
    "paths": {},
}


def test_yaml_filename_serializes_to_json():
    # A `.yaml` source still uploads as JSON (which is valid YAML, so it round-trips through the YAML
    # reader too) — never re-serialized YAML, which can be ambiguous to the worker's strict parser.
    out = document_bytes_from_spec(_SPEC, filename="openapi.yaml")
    assert isinstance(out, bytes)
    assert json.loads(out.decode("utf-8")) == _SPEC
    assert parse_yaml(out.decode("utf-8")) == _SPEC


def test_yml_extension_serializes_to_json():
    out = document_bytes_from_spec(_SPEC, filename="spec.YML")
    assert json.loads(out.decode("utf-8")) == _SPEC


def test_json_filename_serializes_to_json():
    out = document_bytes_from_spec(_SPEC, filename="openapi.json")
    assert json.loads(out.decode("utf-8")) == _SPEC


def test_default_filename_serializes_to_json():
    out = document_bytes_from_spec(_SPEC)
    assert json.loads(out.decode("utf-8")) == _SPEC


def test_non_json_scalars_are_coerced_not_fatal():
    """A YAML loader can yield bare dates; serialization must not crash (default=str coerces them)."""
    spec = {"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "x-released": datetime.date(2021, 1, 1)}
    out = document_bytes_from_spec(spec, filename="openapi.yaml")
    parsed = json.loads(out.decode("utf-8"))
    assert parsed["x-released"] == "2021-01-01"
