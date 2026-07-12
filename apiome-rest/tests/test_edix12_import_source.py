"""Tests for EDI X12 catalog import/export adapters — MFI-20.5 / MFX-24.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.edix12_emitter import validate_edix12_interchange
from app.edix12_import_source import EdiX12ImportSource
from app.edix12_normalizer import EdiX12Normalizer
from app.edix12_parser import is_edix12, parse_edix12
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_PO_850_EDI = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/edi-x12/01-850-purchase-order.edi"
).read_text(encoding="utf-8")
_INV_810_EDI = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/edi-x12/02-810-invoice.edi"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> EdiX12ImportSource:
    return EdiX12ImportSource()


def test_is_edix12_recognizes_purchase_order():
    assert is_edix12(_PO_850_EDI) is True
    assert is_edix12('{"openapi":"3.0.0"}') is False


def test_parse_collects_transaction_set_segments():
    doc = parse_edix12(_PO_850_EDI)
    transaction = doc.interchange.functional_groups[0].transaction_sets[0]
    assert transaction.set_id == "850"
    assert [segment.id for segment in transaction.segments] == [
        "BEG",
        "REF",
        "PER",
        "N1",
        "PO1",
        "PO1",
        "CTT",
    ]


def test_parse_second_fixture_covers_invoice():
    doc = parse_edix12(_INV_810_EDI)
    transaction = doc.interchange.functional_groups[0].transaction_sets[0]
    assert transaction.set_id == "810"
    assert any(segment.id == "IT1" for segment in transaction.segments)


def test_normalizer_maps_data_schema_types():
    doc = parse_edix12(_PO_850_EDI)
    api = EdiX12Normalizer().normalize(doc)
    assert api.format == "edix12"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "X12-850"
    transaction = next(t for t in api.types if t.name == "TransactionSet850")
    assert transaction.kind is TypeKind.RECORD
    assert any(field.name == "BEG01" for field in transaction.fields)
    po1 = next(t for t in api.types if t.name == "PO1")
    assert po1.kind is TypeKind.RECORD
    assert any(field.name == "PO1" for field in transaction.fields)
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: EdiX12ImportSource):
    detected = adapter.detect(
        DetectionInput(text=_PO_850_EDI, filename="01-850-purchase-order.edi")
    )
    assert detected.matched
    assert detected.format == "edix12"
    doc = adapter.parse(_PO_850_EDI, source_label="01-850-purchase-order.edi")
    api = adapter.normalize(doc)
    assert api.extras.get("x12_set_id") == "850"
    assert len(api.types) >= 2


def test_adapter_invalid_source_raises(adapter: EdiX12ImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("ISA*bad")


def test_emitter_round_trips_core_constructs():
    doc = parse_edix12(_PO_850_EDI)
    api = EdiX12Normalizer().normalize(doc)
    emitter = get_emitter("edix12")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert text.startswith("ISA*")
    assert "ST*850*" in text
    assert "PO1*" in text
    assert "IEA*" in text
    validate_edix12_interchange(text)


def test_emitter_round_trips_invoice_fixture():
    doc = parse_edix12(_INV_810_EDI)
    api = EdiX12Normalizer().normalize(doc)
    emitter = get_emitter("edix12")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "ST*810*" in text
    assert "IT1*" in text
    validate_edix12_interchange(text)


def test_catalog_conversion_resolves_edix12_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("edix12", _PO_850_EDI).key == "edix12"
