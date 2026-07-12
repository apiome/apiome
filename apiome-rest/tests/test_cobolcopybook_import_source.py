"""Tests for COBOL copybook catalog import/export adapters — MFI-22.7 / MFX-31.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.cobolcopybook_emitter import validate_cobolcopybook_document
from app.cobolcopybook_import_source import CobolCopybookImportSource
from app.cobolcopybook_normalizer import CobolCopybookNormalizer
from app.cobolcopybook_parser import is_cobolcopybook, parse_cobolcopybook
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_CUSTOMER_RECORD = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/cobol-copybook/01-customer-record.cpy"
).read_text(encoding="utf-8")
_ORDER_LINE = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/cobol-copybook/02-order-line.cpy"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> CobolCopybookImportSource:
    return CobolCopybookImportSource()


def test_is_cobolcopybook_recognizes_customer_record():
    assert is_cobolcopybook(_CUSTOMER_RECORD) is True
    assert is_cobolcopybook('{"mti":"0100","dataElements":{}}') is False


def test_parse_customer_record_builds_nested_groups():
    doc = parse_cobolcopybook(_CUSTOMER_RECORD)
    assert doc.root.name == "CUSTOMER-RECORD"
    assert doc.root.level == 1
    child_names = {child.name for child in doc.root.children}
    assert "CUST-NAME" in child_names
    assert "CUST-PHONES" in child_names
    cust_name = next(child for child in doc.root.children if child.name == "CUST-NAME")
    assert {grandchild.name for grandchild in cust_name.children} == {
        "CUST-FIRST-NAME",
        "CUST-LAST-NAME",
    }
    cust_status = next(child for child in doc.root.children if child.name == "CUST-STATUS")
    assert len(cust_status.conditions) == 3


def test_parse_order_line_fixture_covers_comp3_fields():
    doc = parse_cobolcopybook(_ORDER_LINE)
    assert doc.root.name == "ORDER-LINE"
    unit_price = next(child for child in doc.root.children if child.name == "ORDER-UNIT-PRICE")
    assert unit_price.picture == "S9(7)V99"
    assert unit_price.usage == "COMP-3"


def test_normalizer_maps_data_schema_types():
    doc = parse_cobolcopybook(_CUSTOMER_RECORD)
    api = CobolCopybookNormalizer().normalize(doc)
    assert api.format == "cobolcopybook"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    root_type = next(type_ for type_ in api.types if type_.name == "CUSTOMER-RECORD")
    assert root_type.kind is TypeKind.RECORD
    assert any(field.name == "CUST-ID" for field in root_type.fields)
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: CobolCopybookImportSource):
    detected = adapter.detect(
        DetectionInput(text=_CUSTOMER_RECORD, filename="01-customer-record.cpy")
    )
    assert detected.matched
    assert detected.format == "cobolcopybook"
    doc = adapter.parse(_CUSTOMER_RECORD)
    api = adapter.normalize(doc)
    assert api.extras.get("cobolcopybook_tree")


def test_adapter_invalid_source_raises(adapter: CobolCopybookImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("       01 RECORD.")


def test_emitter_round_trips_customer_record():
    doc = parse_cobolcopybook(_CUSTOMER_RECORD)
    api = CobolCopybookNormalizer().normalize(doc)
    emitter = get_emitter("cobolcopybook")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "CUSTOMER-RECORD" in text
    assert "CUST-PHONES OCCURS 1 TO 5 TIMES" in text
    assert "88  CUST-ACTIVE" in text
    validate_cobolcopybook_document(text)


def test_emitter_round_trips_order_line_fixture():
    doc = parse_cobolcopybook(_ORDER_LINE)
    api = CobolCopybookNormalizer().normalize(doc)
    emitter = get_emitter("cobolcopybook")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "ORDER-LINE" in text
    assert "ORDER-UNIT-PRICE PIC S9(7)V99 COMP-3" in text
    validate_cobolcopybook_document(text)


def test_catalog_conversion_resolves_cobolcopybook_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("cobolcopybook", _CUSTOMER_RECORD).key == "cobolcopybook"
