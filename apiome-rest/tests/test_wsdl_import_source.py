"""Tests for WSDL catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.wsdl_import_source import WsdlImportSource
from app.wsdl_normalizer import WsdlNormalizer
from app.wsdl_parser import is_wsdl, parse_wsdl

_CALCULATOR_WSDL = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/wsdl/01-calculator.wsdl"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> WsdlImportSource:
    return WsdlImportSource()


def test_is_wsdl_recognizes_calculator_service():
    assert is_wsdl(_CALCULATOR_WSDL) is True
    assert is_wsdl("openapi: 3.0.0") is False


def test_parse_collects_types_messages_port_types():
    doc = parse_wsdl(_CALCULATOR_WSDL)
    assert doc.target_namespace == "http://example.com/calculator"
    assert {t.name for t in doc.complex_types} == {"AddRequest", "AddResponse"}
    assert {m.name for m in doc.messages} == {"AddInput", "AddOutput"}
    assert {p.name for p in doc.port_types} == {"CalculatorPort"}


def test_normalizer_maps_rest_soap_service():
    doc = parse_wsdl(_CALCULATOR_WSDL)
    api = WsdlNormalizer().normalize(doc)
    assert api.format == "wsdl"
    assert api.paradigm is ApiParadigm.REST
    assert api.protocol == "soap"
    assert api.extras.get("wsdl_target_namespace") == "http://example.com/calculator"
    add_request = next(t for t in api.types if t.name == "AddRequest")
    assert any(f.name == "a" and f.field_number == 1 for f in add_request.fields)
    calculator = next(s for s in api.services if s.name == "CalculatorPort")
    assert any(op.name == "Add" for op in calculator.operations)
    assert api.servers and api.servers[0].url == "https://api.example.com/calculator"


def test_adapter_detect_parse_normalize(adapter: WsdlImportSource):
    detected = adapter.detect(DetectionInput(text=_CALCULATOR_WSDL, filename="01-calculator.wsdl"))
    assert detected.matched
    assert detected.format == "wsdl"
    doc = adapter.parse(_CALCULATOR_WSDL, source_label="01-calculator.wsdl")
    api = adapter.normalize(doc)
    assert len(api.types) >= 2
    assert len(api.services) == 1


def test_adapter_invalid_source_raises(adapter: WsdlImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not wsdl")


def test_emitter_round_trips_core_constructs():
    doc = parse_wsdl(_CALCULATOR_WSDL)
    api = WsdlNormalizer().normalize(doc)
    emitter = get_emitter("wsdl")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "wsdl:definitions" in text
    assert "AddRequest" in text
    assert "CalculatorPort" in text
    assert "soap:address" in text


def test_catalog_conversion_resolves_wsdl_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("wsdl", _CALCULATOR_WSDL).key == "wsdl"
