"""Tests for FlatBuffers catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.flatbuffers_import_source import FlatBuffersImportSource
from app.flatbuffers_normalizer import FlatBuffersNormalizer
from app.flatbuffers_parser import is_flatbuffers, parse_flatbuffers
from app.import_source import DetectionInput, ImportSourceError

_MONSTER_FBS = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/flatbuffers/01-monster.fbs"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> FlatBuffersImportSource:
    return FlatBuffersImportSource()


def test_is_flatbuffers_recognizes_monster_schema():
    assert is_flatbuffers(_MONSTER_FBS) is True
    assert is_flatbuffers("openapi: 3.0.0") is False


def test_parse_collects_tables_structs_enums():
    doc = parse_flatbuffers(_MONSTER_FBS)
    assert doc.namespace == "example.game"
    assert doc.root_type == "Monster"
    assert {t.name for t in doc.types} == {"Vec3", "Weapon", "Monster"}
    assert {e.name for e in doc.enums} == {"Color"}


def test_normalizer_maps_data_schema():
    doc = parse_flatbuffers(_MONSTER_FBS)
    api = FlatBuffersNormalizer().normalize(doc)
    assert api.format == "flatbuffers"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.extras.get("fbs_root_type") == "Monster"
    monster = next(t for t in api.types if t.name == "Monster")
    assert monster.extras.get("fbs_kind") == "table"
    assert any(f.name == "hp" and f.field_number == 3 for f in monster.fields)


def test_adapter_detect_parse_normalize(adapter: FlatBuffersImportSource):
    detected = adapter.detect(DetectionInput(text=_MONSTER_FBS, filename="01-monster.fbs"))
    assert detected.matched
    assert detected.format == "flatbuffers"
    doc = adapter.parse(_MONSTER_FBS, source_label="01-monster.fbs")
    api = adapter.normalize(doc)
    assert any(t.kind is TypeKind.ENUM and t.name == "Color" for t in api.types)


def test_adapter_invalid_source_raises(adapter: FlatBuffersImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not flatbuffers")


def test_emitter_round_trips_core_constructs():
    doc = parse_flatbuffers(_MONSTER_FBS)
    api = FlatBuffersNormalizer().normalize(doc)
    emitter = get_emitter("flatbuffers")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "table Monster" in text
    assert "enum Color" in text
    assert "root_type Monster" in text


def test_catalog_conversion_resolves_flatbuffers_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("flatbuffers", _MONSTER_FBS).key == "flatbuffers"
