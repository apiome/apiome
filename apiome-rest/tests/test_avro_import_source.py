"""Tests for Avro catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.avro_emitter import validate_avro_schema
from app.avro_import_source import AvroImportSource
from app.avro_normalizer import AvroNormalizer
from app.avro_parser import is_avro, parse_avro
from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_USER_AVSC = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/avro/01-user-record.avsc"
).read_text(encoding="utf-8")
_ORDER_AVSC = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/avro/02-order-record.avsc"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> AvroImportSource:
    return AvroImportSource()


def test_is_avro_recognizes_user_record():
    assert is_avro(_USER_AVSC) is True
    assert is_avro('{"openapi":"3.0.0"}') is False


def test_parse_collects_root_and_nested_types():
    doc = parse_avro(_ORDER_AVSC)
    assert doc.root.name == "Order"
    assert doc.root.namespace == "com.example.order"
    assert {t.name for t in doc.types} == {"LineItem", "Order"}


def test_normalizer_maps_data_schema_types():
    doc = parse_avro(_USER_AVSC)
    api = AvroNormalizer().normalize(doc)
    assert api.format == "avro"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "com.example.user"
    user = next(t for t in api.types if t.name == "User")
    assert user.kind is TypeKind.RECORD
    assert any(f.name == "email" for f in user.fields)
    status = next(t for t in api.types if t.name == "Status")
    assert status.kind is TypeKind.ENUM
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: AvroImportSource):
    detected = adapter.detect(DetectionInput(text=_USER_AVSC, filename="01-user-record.avsc"))
    assert detected.matched
    assert detected.format == "avro"
    doc = adapter.parse(_USER_AVSC, source_label="01-user-record.avsc")
    api = adapter.normalize(doc)
    assert len(api.types) >= 2
    assert api.title == "User"


def test_adapter_invalid_source_raises(adapter: AvroImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"title":"nope"}')


def test_emitter_round_trips_core_constructs():
    doc = parse_avro(_USER_AVSC)
    api = AvroNormalizer().normalize(doc)
    emitter = get_emitter("avro")
    assert emitter is not None
    result = emitter().emit(api)
    assert result.files
    user_file = next(f for f in result.files if f.path.endswith("User.avsc"))
    named_schemas = {
        ".".join(
            part
            for part in (
                emitted.content.get("namespace"),
                emitted.content.get("name"),
            )
            if part
        ): emitted.content
        for emitted in result.files
        if emitted.path != user_file.path
        and isinstance(emitted.content, dict)
        and emitted.content.get("name")
    }
    validate_avro_schema(user_file.content, named_schemas=named_schemas)
    assert user_file.content["type"] == "record"
    assert user_file.content["name"] == "User"
    id_field = next(f for f in user_file.content["fields"] if f["name"] == "id")
    assert id_field["type"] == "string"
    display_field = next(f for f in user_file.content["fields"] if f["name"] == "displayName")
    assert display_field["type"] == ["null", "string"]


def test_catalog_conversion_resolves_avro_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("avro", _USER_AVSC).key == "avro"
