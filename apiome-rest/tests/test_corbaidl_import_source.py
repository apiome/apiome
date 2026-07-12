"""Tests for CORBA IDL catalog import/export adapters — MFI-21.7."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, MessageRole, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.corbaidl_emitter import validate_corbaidl_document
from app.corbaidl_import_source import CorbaIdlImportSource
from app.corbaidl_normalizer import CorbaIdlNormalizer
from app.corbaidl_parser import is_corbaidl, parse_corbaidl

_BANK_IDL = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/corba-idl/01-bank.idl"
).read_text(encoding="utf-8")
_INVENTORY_IDL = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/corba-idl/02-inventory.idl"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> CorbaIdlImportSource:
    return CorbaIdlImportSource()


def test_is_corbaidl_recognizes_bank_fixture():
    assert is_corbaidl(_BANK_IDL) is True
    assert is_corbaidl('namespace demo "example"') is False
    assert is_corbaidl("program DEMO { version VERS { int PING(void) = 1; } = 1; } = 1;") is False


def test_parse_collects_module_types_and_interface():
    doc = parse_corbaidl(_BANK_IDL)
    assert doc.module == "Banking"
    assert doc.typedefs[0].name == "AccountId"
    assert {struct.name for struct in doc.structs} == {
        "Account",
        "InsufficientFunds",
        "AccountNotFound",
    }
    assert doc.interfaces[0].name == "Bank"
    assert len(doc.interfaces[0].operations) == 4
    withdraw = next(op for op in doc.interfaces[0].operations if op.name == "withdraw")
    assert withdraw.raises == ("AccountNotFound", "InsufficientFunds")


def test_parse_second_fixture_covers_inventory():
    doc = parse_corbaidl(_INVENTORY_IDL)
    assert doc.module == "Inventory"
    assert doc.typedefs[0].type_expr == "sequence<string>"
    lookup = doc.interfaces[0].operations[0]
    assert lookup.name == "lookup"
    assert lookup.raises == ("ItemNotFound",)


def test_normalizer_maps_rpc_types_and_operations():
    doc = parse_corbaidl(_BANK_IDL)
    api = CorbaIdlNormalizer().normalize(doc)
    assert api.format == "corbaidl"
    assert api.paradigm is ApiParadigm.RPC
    assert api.services[0].name == "Bank"
    assert len(api.services[0].operations) == 4
    account = next(t for t in api.types if t.name == "Account")
    assert account.kind is TypeKind.RECORD
    withdraw = next(op for op in api.services[0].operations if op.name == "withdraw")
    errors = [m for m in withdraw.messages if m.role is MessageRole.ERROR]
    assert {m.name for m in errors} == {"AccountNotFound", "InsufficientFunds"}


def test_adapter_detect_parse_normalize(adapter: CorbaIdlImportSource):
    detected = adapter.detect(
        DetectionInput(text=_BANK_IDL, filename="01-bank.idl")
    )
    assert detected.matched
    assert detected.format == "corbaidl"
    doc = adapter.parse(_BANK_IDL, source_label="01-bank.idl")
    api = adapter.normalize(doc)
    assert api.extras.get("corbaidl_interfaces")


def test_adapter_invalid_source_raises(adapter: CorbaIdlImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("struct Only { int x; };")


def test_emitter_round_trips_bank_fixture():
    doc = parse_corbaidl(_BANK_IDL)
    api = CorbaIdlNormalizer().normalize(doc)
    emitter = get_emitter("corbaidl")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "module Banking" in text
    assert "interface Bank" in text
    assert "raises (AccountNotFound, InsufficientFunds)" in text
    validate_corbaidl_document(text)


def test_emitter_round_trips_inventory_fixture():
    doc = parse_corbaidl(_INVENTORY_IDL)
    api = CorbaIdlNormalizer().normalize(doc)
    emitter = get_emitter("corbaidl")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "module Inventory" in text
    assert "typedef sequence<string> StringList" in text
    assert "lookup(in string sku) raises (ItemNotFound)" in text
    validate_corbaidl_document(text)


def test_catalog_conversion_resolves_corbaidl_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("corbaidl", _BANK_IDL).key == "corbaidl"
