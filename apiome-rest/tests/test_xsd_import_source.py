"""Tests for XSD catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.xsd_import_source import XsdImportSource
from app.xsd_normalizer import XsdNormalizer
from app.xsd_parser import is_xsd, parse_xsd

_PURCHASE_ORDER_XSD = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/xsd/01-purchase-order.xsd"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> XsdImportSource:
    return XsdImportSource()


def test_is_xsd_recognizes_purchase_order():
    assert is_xsd(_PURCHASE_ORDER_XSD) is True
    assert is_xsd('{"openapi":"3.0.0"}') is False
    assert is_xsd(
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"></wsdl:definitions>'
    ) is False


def test_parse_collects_types_and_root_element():
    doc = parse_xsd(_PURCHASE_ORDER_XSD)
    assert doc.target_namespace == "http://example.com/po"
    assert doc.root_element == "purchaseOrder"
    assert {t.name for t in doc.complex_types} == {"PurchaseOrder", "Address", "Item"}
    status = next(t for t in doc.simple_types if t.name == "Status")
    assert status.enum_values == ("pending", "shipped", "delivered", "cancelled")
    purchase_order = next(t for t in doc.complex_types if t.name == "PurchaseOrder")
    assert any(f.name == "orderDate" and f.kind == "attribute" for f in purchase_order.fields)
    items_field = next(f for f in purchase_order.fields if f.name == "items")
    assert items_field.max_occurs == "unbounded"


def test_normalizer_maps_data_schema_types():
    doc = parse_xsd(_PURCHASE_ORDER_XSD)
    api = XsdNormalizer().normalize(doc)
    assert api.format == "xsd"
    assert api.paradigm is ApiParadigm.DATA_SCHEMA
    assert api.identity.namespace == "http://example.com/po"
    assert api.title == "purchaseOrder"
    purchase_order = next(t for t in api.types if t.name == "PurchaseOrder")
    assert purchase_order.kind is TypeKind.RECORD
    assert any(f.name == "shipTo" for f in purchase_order.fields)
    status = next(t for t in api.types if t.name == "Status")
    assert status.kind is TypeKind.ENUM
    assert api.services == []


def test_adapter_detect_parse_normalize(adapter: XsdImportSource):
    detected = adapter.detect(
        DetectionInput(text=_PURCHASE_ORDER_XSD, filename="01-purchase-order.xsd")
    )
    assert detected.matched
    assert detected.format == "xsd"
    doc = adapter.parse(_PURCHASE_ORDER_XSD, source_label="01-purchase-order.xsd")
    api = adapter.normalize(doc)
    assert len(api.types) >= 4
    assert api.extras.get("xsd_root_element") == "purchaseOrder"


def test_adapter_invalid_source_raises(adapter: XsdImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("<note><to>you</to></note>")


def test_emitter_round_trips_core_constructs():
    doc = parse_xsd(_PURCHASE_ORDER_XSD)
    api = XsdNormalizer().normalize(doc)
    emitter = get_emitter("xsd")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "complexType" in text
    assert "PurchaseOrder" in text
    assert "Address" in text
    assert "simpleType" in text
    assert "Status" in text
    assert 'name="purchaseOrder"' in text
    assert 'maxOccurs="unbounded"' in text
    assert 'name="orderDate"' in text


def test_catalog_conversion_resolves_xsd_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("xsd", _PURCHASE_ORDER_XSD).key == "xsd"
