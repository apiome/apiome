"""Tests for the JSON Type Definition (JTD) import source."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.format_detection import DetectionInput as FDInput, detect_format
from app.import_routing import ImportTarget, decide_import_routing
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
)
from app.jtd_emitter import validate_jtd_document
from app.jtd_import_source import JTD_FORMAT, JtdImportSource

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/jtd"
_USER = (_EXAMPLES / "01-user.jtd.json").read_text(encoding="utf-8")
_ORDER = (_EXAMPLES / "02-order.jtd.json").read_text(encoding="utf-8")


@pytest.fixture
def adapter() -> JtdImportSource:
    return JtdImportSource()


def test_detect_optional_properties_high_confidence(adapter: JtdImportSource) -> None:
    result = adapter.detect(DetectionInput(text=_USER, filename="01-user.jtd.json"))
    assert result.confidence == pytest.approx(0.95)
    assert result.format == JTD_FORMAT


def test_detect_definitions_container(adapter: JtdImportSource) -> None:
    doc = {
        "definitions": {
            "Widget": {
                "properties": {"id": {"type": "string"}},
                "optionalProperties": {"label": {"type": "string"}},
            }
        },
        "properties": {"widget": {"ref": "Widget"}},
    }
    result = adapter.detect(DetectionInput(document=doc))
    assert result.matched
    assert result.format == JTD_FORMAT


def test_detect_declines_json_schema(adapter: JtdImportSource) -> None:
    doc = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"id": {"type": "string"}},
    }
    assert not adapter.detect(DetectionInput(document=doc)).matched


@pytest.mark.parametrize(
    "marker",
    [
        {"openapi": "3.1.0", "info": {}, "paths": {}},
        {"swagger": "2.0", "info": {}},
        {"asyncapi": "3.0.0"},
        {"type": "record", "name": "User", "fields": []},
    ],
)
def test_detect_declines_other_formats(adapter: JtdImportSource, marker: dict) -> None:
    assert not adapter.detect(DetectionInput(document=marker)).matched


def test_detect_via_registry_auto_detection(adapter: JtdImportSource) -> None:
    best = detect_import_source(DetectionInput(text=_USER, filename="01-user.jtd.json"))
    assert best is not None
    detected_adapter, result = best
    assert detected_adapter.key == "jtd"
    assert result.format == JTD_FORMAT


def test_detect_format_endpoint_ranks_jtd_importable() -> None:
    detection = detect_format(FDInput(text=_USER, filename="01-user.jtd.json"))
    assert detection.matched
    assert detection.detected.format == JTD_FORMAT
    assert detection.detected.importable is True
    assert detection.detected.source_key == "jtd"


def test_parse_requires_object(adapter: JtdImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse("[]")


def test_normalize_user_fixture(adapter: JtdImportSource) -> None:
    api = adapter.normalize(adapter.parse(_USER, source_label="01-user.jtd.json"))
    assert api.paradigm == ApiParadigm.DATA_SCHEMA
    assert api.format == JTD_FORMAT
    assert api.raw is not None
    assert "source" in api.raw

    root = next(type_ for type_ in api.types if type_.name == "User")
    assert root.kind == TypeKind.RECORD
    field_names = {field.name for field in root.fields}
    assert {"id", "email", "status", "createdAt", "displayName", "roles", "address"} <= field_names

    status = next(type_ for type_ in api.types if type_.name == "UserStatus")
    assert status.kind == TypeKind.ENUM

    address = next(type_ for type_ in api.types if type_.name == "UserAddress")
    assert address.kind == TypeKind.RECORD


def test_normalize_order_fixture_covers_definitions_and_union(adapter: JtdImportSource) -> None:
    api = adapter.normalize(adapter.parse(_ORDER, source_label="02-order.jtd.json"))
    assert api.title == "Order"

    order_line = next(type_ for type_ in api.types if type_.name == "OrderLine")
    assert order_line.kind == TypeKind.RECORD

    delivery = next(type_ for type_ in api.types if type_.name == "OrderDelivery")
    assert delivery.kind == TypeKind.UNION
    assert set(delivery.union_members) == {"DigitalDelivery", "PhysicalDelivery"}


def test_routes_to_non_publishable_schemas_only_catalog(adapter: JtdImportSource) -> None:
    model = adapter.normalize(adapter.parse(_USER))
    routing = decide_import_routing(adapter, model)
    assert routing.target == ImportTarget.CATALOG
    assert routing.publishable is False
    assert routing.schemas_only is True


def test_catalog_conversion_resolves_jtd_adapter() -> None:
    from app.catalog_conversion import resolve_conversion_adapter

    resolved = resolve_conversion_adapter("jtd", _USER)
    assert resolved.key == "jtd"


def test_emitter_round_trips_user_fixture(adapter: JtdImportSource) -> None:
    api = adapter.normalize(adapter.parse(_USER, source_label="01-user.jtd.json"))
    emitter = get_emitter("jtd")
    assert emitter is not None
    result = emitter().emit(api)
    text = str(result.files[0].content)
    validate_jtd_document(text)
    round_trip = adapter.normalize(adapter.parse(text))
    assert round_trip.format == JTD_FORMAT
    assert len(round_trip.types) == len(api.types)


def test_emitter_round_trips_order_fixture(adapter: JtdImportSource) -> None:
    api = adapter.normalize(adapter.parse(_ORDER, source_label="02-order.jtd.json"))
    emitter = get_emitter("jtd")
    assert emitter is not None
    result = emitter().emit(api)
    text = str(result.files[0].content)
    validate_jtd_document(text)
    round_trip = json.loads(text)
    assert "definitions" in round_trip
    assert "delivery" in round_trip["properties"]
