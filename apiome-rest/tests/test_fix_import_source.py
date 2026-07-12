"""Tests for FIX catalog import/export adapters — MFI-22.8 / MFX-32.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.fix_emitter import validate_fix_message
from app.fix_import_source import FixImportSource
from app.fix_normalizer import FixNormalizer
from app.fix_parser import is_fix, parse_fix
from app.import_source import DetectionInput, ImportSourceError

_NEW_ORDER_SINGLE = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/fix/01-newordersingle.fix"
).read_text(encoding="utf-8")
_EXECUTION_REPORT = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/fix/02-executionreport.fix"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> FixImportSource:
    return FixImportSource()


def test_is_fix_recognizes_new_order_single():
    assert is_fix(_NEW_ORDER_SINGLE) is True
    assert is_fix("MSH|^~\\&|ADT1|GOOD HEALTH|") is False
    assert is_fix('{"mti":"0100","dataElements":{}}') is False


def test_parse_new_order_single_collects_tags():
    doc = parse_fix(_NEW_ORDER_SINGLE)
    assert doc.message.begin_string == "FIX.4.4"
    assert doc.message.msg_type == "D"
    assert doc.message.sender_comp_id == "BUYSIDE"
    assert doc.message.target_comp_id == "SELLSIDE"
    assert doc.delimiter == "|"
    tags = {field.tag: field.value for field in doc.message.fields}
    assert tags["55"] == "AAPL"
    assert tags["38"] == "100"
    assert tags["44"] == "185.50"


def test_parse_execution_report_fixture_covers_exec_fields():
    doc = parse_fix(_EXECUTION_REPORT)
    assert doc.message.msg_type == "8"
    tags = {field.tag: field.value for field in doc.message.fields}
    assert tags["39"] == "2"
    assert tags["150"] == "2"
    assert tags["17"] == "EXEC-0001"


def test_parse_supports_soh_delimiter():
    soh = "\x01"
    wire = soh.join(
        [
            "8=FIX.4.4",
            "9=100",
            "35=D",
            "49=BUY",
            "56=SELL",
            "55=IBM",
            "10=001",
        ]
    )
    doc = parse_fix(wire)
    assert doc.delimiter == soh
    assert doc.message.msg_type == "D"


def test_normalizer_maps_data_schema_types():
    doc = parse_fix(_NEW_ORDER_SINGLE)
    api = FixNormalizer().normalize(doc)
    assert api.format == "fix"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "FIX.4.4"
    message = next(type_ for type_ in api.types if type_.extras.get("fix_kind") == "message")
    assert message.kind is TypeKind.RECORD
    assert any(field.name == "Tag55" for field in message.fields)
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: FixImportSource):
    detected = adapter.detect(
        DetectionInput(text=_NEW_ORDER_SINGLE, filename="01-newordersingle.fix")
    )
    assert detected.matched
    assert detected.format == "fix"
    doc = adapter.parse(_NEW_ORDER_SINGLE, source_label="01-newordersingle.fix")
    api = adapter.normalize(doc)
    assert api.extras.get("fix_msg_type") == "D"
    assert len(api.extras.get("fix_fields", [])) >= 10


def test_adapter_invalid_source_raises(adapter: FixImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("8=NOTFIX|35=D|")


def test_emitter_round_trips_new_order_single():
    doc = parse_fix(_NEW_ORDER_SINGLE)
    api = FixNormalizer().normalize(doc)
    emitter = get_emitter("fix")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "8=FIX.4.4" in text
    assert "35=D" in text
    assert "55=AAPL" in text
    validate_fix_message(text)


def test_emitter_round_trips_execution_report_fixture():
    doc = parse_fix(_EXECUTION_REPORT)
    api = FixNormalizer().normalize(doc)
    emitter = get_emitter("fix")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "35=8" in text
    assert "150=2" in text
    validate_fix_message(text)


def test_catalog_conversion_resolves_fix_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("fix", _NEW_ORDER_SINGLE).key == "fix"
