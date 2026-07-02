"""Tests for the JSON Schema import source (MFI-26.7, #4102).

Exercises the adapter through the full SPI — detect → parse → normalize →
fingerprint/lint — plus the two behaviours the disambiguation prompt relies on:

* the adapter **declines** any API-description document (OpenAPI/Swagger/AsyncAPI/Arazzo),
  so JSON Schema detection never steals a real API import, and
* a normalized JSON Schema **routes to a non-publishable, schemas-only catalog item**
  (:func:`app.import_routing.decide_import_routing`), which is exactly what the "Import into
  Catalog" choice stores.

The adapter builds the canonical model directly (JSON Schema has no separate paradigm
normalizer), so every path runs pure-Python with nothing mocked.
"""

from __future__ import annotations

import json

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, TypeKind
from app.format_detection import DetectionInput as FDInput, detect_format
from app.import_ingestion import parse_document
from app.import_routing import ImportTarget, decide_import_routing
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    InputKind,
    detect_import_source,
    get_import_source,
)
from app.jsonschema_import_source import JSON_SCHEMA_FORMAT, JsonSchemaImportSource

# A JSON Schema 2020-12 object schema with a `$defs` enum and a required/optional split.
_SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://acme.test/user.schema.json",
        "title": "User",
        "type": "object",
        "required": ["id", "email"],
        "properties": {
            "id": {"type": "string"},
            "email": {"type": "string", "description": "contact address"},
            "roles": {"type": "array", "items": {"$ref": "#/$defs/Role"}},
        },
        "$defs": {"Role": {"type": "string", "enum": ["admin", "user"]}},
    }
)


@pytest.fixture
def adapter() -> JsonSchemaImportSource:
    return JsonSchemaImportSource()


# --- detection -------------------------------------------------------------


def test_detect_2020_12_marker_high_confidence(adapter: JsonSchemaImportSource) -> None:
    result = adapter.detect(DetectionInput(document=parse_document(_SCHEMA)))
    assert result.confidence == pytest.approx(0.95)
    assert result.format == "json-schema-2020-12"


def test_detect_defs_container_without_dialect(adapter: JsonSchemaImportSource) -> None:
    doc = {"$defs": {"Thing": {"type": "object"}}}
    result = adapter.detect(DetectionInput(document=doc))
    assert result.matched
    assert result.format == JSON_SCHEMA_FORMAT


def test_detect_bare_object_schema(adapter: JsonSchemaImportSource) -> None:
    doc = {"type": "object", "properties": {"name": {"type": "string"}}}
    assert adapter.detect(DetectionInput(document=doc)).matched


def test_detect_bare_scalar_schema(adapter: JsonSchemaImportSource) -> None:
    doc = {"type": "string", "maxLength": 5}
    assert adapter.detect(DetectionInput(document=doc)).matched


@pytest.mark.parametrize(
    "marker",
    [
        {"openapi": "3.1.0", "info": {}, "paths": {}},
        {"swagger": "2.0", "info": {}},
        {"asyncapi": "3.0.0"},
        {"arazzo": "1.0.0"},
    ],
)
def test_detect_declines_api_descriptions(adapter: JsonSchemaImportSource, marker: dict) -> None:
    # An OpenAPI/Swagger/AsyncAPI/Arazzo doc *is/contains* JSON Schema — the adapter must not steal it.
    assert not adapter.detect(DetectionInput(document=marker)).matched


def test_detect_from_text_only(adapter: JsonSchemaImportSource) -> None:
    # Standalone detection (no pre-parsed document) parses the text itself.
    result = adapter.detect(DetectionInput(text=_SCHEMA, filename="user.schema.json"))
    assert result.format == "json-schema-2020-12"


def test_detect_declines_non_schema_json(adapter: JsonSchemaImportSource) -> None:
    # A domain object with a `type` that is not a JSON Schema type keyword is not a schema.
    assert not adapter.detect(DetectionInput(document={"type": "user", "name": "x"})).matched
    assert not adapter.detect(DetectionInput(text="just some text")).matched


def test_detect_via_registry_auto_detection() -> None:
    best = detect_import_source(DetectionInput(document=parse_document(_SCHEMA)))
    assert best is not None
    adapter, result = best
    assert adapter.key == "json-schema"
    assert result.format == "json-schema-2020-12"


def test_detect_format_endpoint_ranks_json_schema_importable() -> None:
    detection = detect_format(FDInput(text=_SCHEMA, filename="user.schema.json"))
    assert detection.matched
    assert detection.detected is not None
    assert detection.detected.format == "json-schema-2020-12"
    assert detection.detected.importable is True
    assert detection.detected.source_key == "json-schema"


# --- parse -----------------------------------------------------------------


def test_parse_json(adapter: JsonSchemaImportSource) -> None:
    parsed = adapter.parse(_SCHEMA, source_label="user.schema.json")
    assert parsed["title"] == "User"


def test_parse_yaml(adapter: JsonSchemaImportSource) -> None:
    parsed = adapter.parse("type: object\nproperties:\n  id:\n    type: string\n")
    assert parsed["type"] == "object"


def test_parse_empty_raises(adapter: JsonSchemaImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse("   ")


# --- normalize -------------------------------------------------------------


def test_normalize_builds_data_schema_model(adapter: JsonSchemaImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SCHEMA))
    assert isinstance(model, CanonicalApi)
    assert model.paradigm == ApiParadigm.DATA_SCHEMA
    assert model.format == JSON_SCHEMA_FORMAT
    assert model.identity.name == "User"
    assert model.identity.id == "https://acme.test/user.schema.json"
    # No callable surface — pure data types.
    assert not model.operations()
    assert not model.channels


def test_normalize_maps_defs_and_root_types(adapter: JsonSchemaImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SCHEMA))
    by_name = {t.name: t for t in model.types}
    assert set(by_name) == {"Role", "User"}

    role = by_name["Role"]
    assert role.kind == TypeKind.ENUM
    assert [ev.name for ev in role.enum_values] == ["admin", "user"]

    user = by_name["User"]
    assert user.kind == TypeKind.RECORD
    fields = {f.name: f for f in user.fields}
    # Required fields are non-nullable; optional ones nullable.
    assert fields["id"].type.nullable is False
    assert fields["email"].type.nullable is False
    assert fields["email"].description == "contact address"
    # `roles` is a list of the referenced Role type and is optional.
    assert fields["roles"].type.is_list()
    assert fields["roles"].type.item is not None
    assert fields["roles"].type.item.name == "Role"
    assert fields["roles"].type.nullable is True


def test_normalize_bare_schema_derives_root_name(adapter: JsonSchemaImportSource) -> None:
    doc = {"$id": "https://acme.test/widget.schema.json", "type": "object", "properties": {}}
    model = adapter.normalize(doc)
    assert model.identity.name == "widget"
    assert [t.name for t in model.types] == ["widget"]


def test_normalize_rejects_non_mapping(adapter: JsonSchemaImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize(["not", "a", "schema"])


def test_normalize_is_deterministic(adapter: JsonSchemaImportSource) -> None:
    a = adapter.normalize(adapter.parse(_SCHEMA))
    b = adapter.normalize(adapter.parse(_SCHEMA))
    assert adapter.fingerprint(a) == adapter.fingerprint(b)


# --- routing + descriptor --------------------------------------------------


def test_routes_to_non_publishable_schemas_only_catalog(adapter: JsonSchemaImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SCHEMA))
    routing = decide_import_routing(adapter, model)
    assert routing.target == ImportTarget.CATALOG
    assert routing.publishable is False
    assert routing.schemas_only is True
    assert routing.type_count == 2


def test_import_as_current_routes_the_real_adapter_to_types(adapter: JsonSchemaImportSource) -> None:
    # The real adapter's emitted format ("json-schema") is recognized by the as-current routing:
    # the Types/Projects opt-in (MFI-26.8) sends the same document to the type registry instead
    # of the catalog, without minting a publishable Project.
    model = adapter.normalize(adapter.parse(_SCHEMA))
    for target in ("types", "project"):
        routing = decide_import_routing(adapter, model, requested_target=target)
        assert routing.target == ImportTarget.TYPES, target
        assert routing.publishable is False, target
        assert routing.as_dict()["target"] == "types", target


def test_adapter_registered_and_available() -> None:
    resolved = get_import_source("json-schema")
    assert isinstance(resolved, JsonSchemaImportSource)
    descriptor = JsonSchemaImportSource.descriptor()
    assert descriptor.available is True
    assert descriptor.paradigm == ApiParadigm.DATA_SCHEMA
    assert set(descriptor.input_kinds) == {InputKind.FILE, InputKind.URL, InputKind.PASTE}
    assert descriptor.supports_live_discovery is False


def test_lint_scores_the_model(adapter: JsonSchemaImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SCHEMA))
    report = adapter.lint(model)
    assert report.score is not None
