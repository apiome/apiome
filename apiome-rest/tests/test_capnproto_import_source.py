"""Tests for Cap'n Proto catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.capnproto_import_source import CapnpImportSource
from app.capnproto_normalizer import CapnpNormalizer
from app.capnproto_parser import is_capnproto, parse_capnproto
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_ADDRESS_BOOK = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/capnproto/01-address-book.capnp"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> CapnpImportSource:
    return CapnpImportSource()


def test_is_capnproto_recognizes_address_book():
    assert is_capnproto(_ADDRESS_BOOK) is True
    assert is_capnproto("openapi: 3.0.0") is False
    assert is_capnproto("module Demo { interface Ping { long echo(in long value); }; };") is False


def test_parse_collects_structs_enums_interfaces():
    doc = parse_capnproto(_ADDRESS_BOOK)
    assert doc.file_id == "0xbf5147cbbecf40c1"
    assert {s.qualified_name for s in doc.structs} >= {"Person", "Date", "AddressBook", "Person.PhoneNumber"}
    assert any(e.qualified_name == "Person.PhoneNumber.Type" for e in doc.enums)
    assert {i.name for i in doc.interfaces} == {"Directory"}


def test_normalizer_maps_rpc_schema():
    doc = parse_capnproto(_ADDRESS_BOOK)
    api = CapnpNormalizer().normalize(doc)
    assert api.format == "capnproto"
    assert api.paradigm is ApiParadigm.RPC
    assert api.extras.get("capnp_file_id") == "0xbf5147cbbecf40c1"
    person = next(t for t in api.types if t.name == "Person")
    assert any(f.name == "email" and f.field_number == 2 for f in person.fields)
    directory = next(s for s in api.services if s.name == "Directory")
    assert any(op.name == "lookup" for op in directory.operations)


def test_adapter_detect_parse_normalize(adapter: CapnpImportSource):
    detected = adapter.detect(DetectionInput(text=_ADDRESS_BOOK, filename="01-address-book.capnp"))
    assert detected.matched
    assert detected.format == "capnproto"
    doc = adapter.parse(_ADDRESS_BOOK, source_label="01-address-book.capnp")
    api = adapter.normalize(doc)
    assert any(t.kind is TypeKind.ENUM and t.name == "Type" for t in api.types)


def test_adapter_invalid_source_raises(adapter: CapnpImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not capnproto")


def test_emitter_round_trips_core_constructs():
    doc = parse_capnproto(_ADDRESS_BOOK)
    api = CapnpNormalizer().normalize(doc)
    emitter = get_emitter("capnproto")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "struct Person" in text
    assert "interface Directory" in text
    assert "@0xbf5147cbbecf40c1" in text


def test_catalog_conversion_resolves_capnproto_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("capnproto", _ADDRESS_BOOK).key == "capnproto"
