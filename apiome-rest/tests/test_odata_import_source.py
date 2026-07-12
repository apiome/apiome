"""Tests for OData catalog import/export adapters — MFI-22.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.odata_emitter import validate_odata_document
from app.odata_import_source import ODataImportSource
from app.odata_normalizer import ODataNormalizer
from app.odata_parser import is_odata, parse_odata

_NORTHWIND_EDMX = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/odata/01-northwind.edmx"
).read_text(encoding="utf-8")
_ORDERS_EDMX = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/odata/02-orders.edmx"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> ODataImportSource:
    return ODataImportSource()


def test_is_odata_recognizes_northwind_fixture():
    assert is_odata(_NORTHWIND_EDMX) is True
    assert is_odata("<wsdl:definitions/>") is False


def test_parse_collects_entity_types_and_sets():
    doc = parse_odata(_NORTHWIND_EDMX)
    assert doc.version == "4.0"
    schema = doc.schemas[0]
    assert schema.namespace == "Example.Catalog"
    assert {entity.name for entity in schema.entity_types} == {"Product", "Category"}
    assert schema.entity_container is not None
    assert {entity_set.name for entity_set in schema.entity_container.entity_sets} == {
        "Products",
        "Categories",
    }


def test_parse_second_fixture_covers_enums_and_complex_types():
    doc = parse_odata(_ORDERS_EDMX)
    schema = doc.schemas[0]
    assert schema.namespace == "Example.Orders"
    assert schema.enum_types[0].name == "OrderStatus"
    assert schema.complex_types[0].name == "Address"
    assert schema.entity_types[0].name == "Order"


def test_normalizer_maps_rest_entity_sets_and_types():
    doc = parse_odata(_NORTHWIND_EDMX)
    api = ODataNormalizer().normalize(doc)
    assert api.format == "odata"
    assert api.paradigm is ApiParadigm.REST
    assert api.version == "4.0"
    product = next(t for t in api.types if t.name == "Product")
    assert product.kind is TypeKind.RECORD
    assert product.extras.get("odata_key_properties") == ["Id"]
    products = next(s for s in api.services if s.name == "Products")
    assert any(op.http_method == "GET" for op in products.operations)
    assert api.extras.get("odata_entity_sets")


def test_adapter_detect_parse_normalize(adapter: ODataImportSource):
    detected = adapter.detect(
        DetectionInput(text=_NORTHWIND_EDMX, filename="01-northwind.edmx")
    )
    assert detected.matched
    assert detected.format == "odata"
    doc = adapter.parse(_NORTHWIND_EDMX, source_label="01-northwind.edmx")
    api = adapter.normalize(doc)
    assert api.extras.get("odata_schemas")


def test_adapter_invalid_source_raises(adapter: ODataImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("<root/>")


def test_emitter_round_trips_northwind_fixture():
    doc = parse_odata(_NORTHWIND_EDMX)
    api = ODataNormalizer().normalize(doc)
    emitter = get_emitter("odata")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "edmx:Edmx" in text or "Edmx" in text
    assert "EntityType Name=\"Product\"" in text or 'Name="Product"' in text
    assert "NavigationProperty" in text
    validate_odata_document(text)


def test_emitter_round_trips_orders_fixture():
    doc = parse_odata(_ORDERS_EDMX)
    api = ODataNormalizer().normalize(doc)
    emitter = get_emitter("odata")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "EnumType" in text
    assert "ComplexType" in text
    assert "EntitySet" in text
    validate_odata_document(text)


def test_catalog_conversion_resolves_odata_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("odata", _NORTHWIND_EDMX).key == "odata"
