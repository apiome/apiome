"""Tests for HL7 v2 catalog import/export adapters — MFI-22.4 / MFX-28.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.hl7v2_emitter import validate_hl7v2_message
from app.hl7v2_import_source import Hl7V2ImportSource
from app.hl7v2_normalizer import Hl7V2Normalizer
from app.hl7v2_parser import is_hl7v2, parse_hl7v2
from app.import_source import DetectionInput, ImportSourceError

_ADT_A01 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/hl7v2/01-adt-a01.hl7"
).read_text(encoding="utf-8")
_ORU_R01 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/hl7v2/02-oru-r01.hl7"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> Hl7V2ImportSource:
    return Hl7V2ImportSource()


def test_is_hl7v2_recognizes_adt_message():
    assert is_hl7v2(_ADT_A01) is True
    assert is_hl7v2('{"resourceType":"Patient"}') is False


def test_parse_adt_collects_segments_and_msh_metadata():
    doc = parse_hl7v2(_ADT_A01)
    assert doc.message.message_type == "ADT^A01"
    assert doc.message.version_id == "2.5"
    assert [segment.id for segment in doc.message.segments] == ["MSH", "EVN", "PID", "NK1", "PV1"]
    pid = next(segment for segment in doc.message.segments if segment.id == "PID")
    assert any(field.value == "MRN-12345^^^GHH^MR" for field in pid.fields)


def test_parse_oru_fixture_covers_repeating_obx_segments():
    doc = parse_hl7v2(_ORU_R01)
    assert doc.message.message_type == "ORU^R01"
    assert sum(1 for segment in doc.message.segments if segment.id == "OBX") == 2


def test_normalizer_maps_data_schema_types():
    doc = parse_hl7v2(_ADT_A01)
    api = Hl7V2Normalizer().normalize(doc)
    assert api.format == "hl7v2"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "ADT-A01"
    message = next(type_ for type_ in api.types if type_.extras.get("hl7v2_kind") == "message")
    assert message.kind is TypeKind.RECORD
    assert any(field.name == "PID-03" for field in message.fields)
    msh = next(type_ for type_ in api.types if type_.name == "MSH")
    assert msh.kind is TypeKind.RECORD
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: Hl7V2ImportSource):
    detected = adapter.detect(DetectionInput(text=_ADT_A01, filename="01-adt-a01.hl7"))
    assert detected.matched
    assert detected.format == "hl7v2"
    doc = adapter.parse(_ADT_A01, source_label="01-adt-a01.hl7")
    api = adapter.normalize(doc)
    assert api.extras.get("hl7v2_message_type") == "ADT^A01"
    assert len(api.extras.get("hl7v2_segments", [])) == 5


def test_adapter_invalid_source_raises(adapter: Hl7V2ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("MSH|bad")


def test_emitter_round_trips_adt_message():
    doc = parse_hl7v2(_ADT_A01)
    api = Hl7V2Normalizer().normalize(doc)
    emitter = get_emitter("hl7v2")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert text.startswith("MSH|^~\\&|")
    assert "PID|" in text
    assert "PV1|" in text
    validate_hl7v2_message(text)


def test_emitter_round_trips_oru_fixture():
    doc = parse_hl7v2(_ORU_R01)
    api = Hl7V2Normalizer().normalize(doc)
    emitter = get_emitter("hl7v2")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "ORU^R01" in text
    assert text.count("OBX|") == 2
    validate_hl7v2_message(text)


def test_catalog_conversion_resolves_hl7v2_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("hl7v2", _ADT_A01).key == "hl7v2"
