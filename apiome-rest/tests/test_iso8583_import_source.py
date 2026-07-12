"""Tests for ISO 8583 catalog import/export adapters — MFI-22.6 / MFX-30.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.iso8583_emitter import validate_iso8583_document
from app.iso8583_import_source import Iso8583ImportSource
from app.iso8583_normalizer import Iso8583Normalizer
from app.iso8583_parser import is_iso8583, parse_iso8583

_AUTH_0100 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/iso8583/01-authorization-0100.json"
).read_text(encoding="utf-8")
_AUTH_0110 = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/iso8583/02-authorization-response-0110.json"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> Iso8583ImportSource:
    return Iso8583ImportSource()


def test_is_iso8583_recognizes_authorization_request():
    assert is_iso8583(_AUTH_0100) is True
    assert is_iso8583('{"type": "record", "name": "User", "fields": []}') is False


def test_parse_authorization_request_collects_data_elements():
    doc = parse_iso8583(_AUTH_0100)
    assert doc.mti == "0100"
    assert doc.name == "Authorization Request"
    assert {element.number for element in doc.data_elements} == {
        "2", "3", "4", "7", "11", "12", "13", "18", "32", "41", "49"
    }
    pan = next(element for element in doc.data_elements if element.number == "2")
    assert pan.value == "4111111111111111"


def test_parse_response_fixture_covers_response_code():
    doc = parse_iso8583(_AUTH_0110)
    assert doc.mti == "0110"
    response_code = next(element for element in doc.data_elements if element.number == "39")
    assert response_code.value == "00"


def test_normalizer_maps_data_schema_types():
    doc = parse_iso8583(_AUTH_0100)
    api = Iso8583Normalizer().normalize(doc)
    assert api.format == "iso8583"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "0100"
    message = next(type_ for type_ in api.types if type_.name == "Message0100")
    assert message.kind is TypeKind.RECORD
    assert any(field.name == "DE2" for field in message.fields)
    de2 = next(type_ for type_ in api.types if type_.name == "DE2")
    assert de2.kind is TypeKind.RECORD
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: Iso8583ImportSource):
    detected = adapter.detect(
        DetectionInput(text=_AUTH_0100, filename="01-authorization-0100.json")
    )
    assert detected.matched
    assert detected.format == "iso8583"
    doc = adapter.parse(_AUTH_0100)
    api = adapter.normalize(doc)
    assert api.extras.get("iso8583_data_elements")
    assert api.extras.get("iso8583_mti") == "0100"


def test_adapter_invalid_source_raises(adapter: Iso8583ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"mti":"0100"}')


def test_emitter_round_trips_authorization_request():
    doc = parse_iso8583(_AUTH_0100)
    api = Iso8583Normalizer().normalize(doc)
    emitter = get_emitter("iso8583")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert '"mti": "0100"' in text
    assert '"DE2"' not in text
    assert '"2"' in text
    assert "4111111111111111" in text
    validate_iso8583_document(text)


def test_emitter_round_trips_response_fixture():
    doc = parse_iso8583(_AUTH_0110)
    api = Iso8583Normalizer().normalize(doc)
    emitter = get_emitter("iso8583")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert '"mti": "0110"' in text
    assert '"39"' in text
    validate_iso8583_document(text)


def test_catalog_conversion_resolves_iso8583_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("iso8583", _AUTH_0100).key == "iso8583"
