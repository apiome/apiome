"""Tests for XML-RPC catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, MessageRole, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.xmlrpc_import_source import XmlRpcImportSource
from app.xmlrpc_normalizer import XmlRpcNormalizer
from app.xmlrpc_parser import is_xmlrpc, parse_xmlrpc

_METHOD_CALL = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/xml-rpc/01-method-call.xml"
).read_text(encoding="utf-8")
_METHOD_RESPONSE = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/xml-rpc/02-method-response.xml"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> XmlRpcImportSource:
    return XmlRpcImportSource()


def test_is_xmlrpc_recognizes_method_call():
    assert is_xmlrpc(_METHOD_CALL) is True
    assert is_xmlrpc(_METHOD_RESPONSE) is True
    assert is_xmlrpc("<wsdl:definitions xmlns:wsdl=\"http://schemas.xmlsoap.org/wsdl/\"></wsdl:definitions>") is False


def test_parse_collects_method_and_params():
    doc = parse_xmlrpc(_METHOD_CALL)
    assert doc.kind == "methodCall"
    assert doc.method_name == "inventory.reserveStock"
    assert len(doc.params) == 3
    assert doc.params[0].kind == "string"
    assert doc.params[1].kind == "int"
    assert doc.params[2].kind == "struct"
    assert {member.name for member in doc.params[2].members} == {"customerId", "priority"}


def test_parse_collects_method_response_struct():
    doc = parse_xmlrpc(_METHOD_RESPONSE)
    assert doc.kind == "methodResponse"
    assert len(doc.params) == 1
    assert doc.params[0].kind == "struct"
    assert {member.name for member in doc.params[0].members} == {
        "reservationId",
        "sku",
        "reserved",
        "remaining",
    }


def test_normalizer_maps_rpc_method_call():
    doc = parse_xmlrpc(_METHOD_CALL)
    api = XmlRpcNormalizer().normalize(doc)
    assert api.format == "xmlrpc"
    assert api.paradigm is ApiParadigm.RPC
    assert api.protocol == "xmlrpc"
    assert api.title == "inventory.reserveStock"
    service = api.services[0]
    assert service.operations[0].name == "inventory.reserveStock"
    struct_type = next(t for t in api.types if t.kind is TypeKind.RECORD)
    assert any(f.name == "customerId" for f in struct_type.fields)
    request = next(m for m in service.operations[0].messages if m.role is MessageRole.REQUEST)
    params = request.extras.get("xmlrpc_params")
    assert isinstance(params, list)
    assert len(params) == 3


def test_normalizer_maps_method_response():
    doc = parse_xmlrpc(_METHOD_RESPONSE)
    api = XmlRpcNormalizer().normalize(doc)
    assert api.format == "xmlrpc"
    assert api.paradigm is ApiParadigm.RPC
    assert len(api.types) == 1
    response = next(m for m in api.services[0].operations[0].messages if m.role is MessageRole.RESPONSE)
    assert response.payload is not None


def test_adapter_detect_parse_normalize(adapter: XmlRpcImportSource):
    detected = adapter.detect(
        DetectionInput(text=_METHOD_CALL, filename="01-method-call.xml")
    )
    assert detected.matched
    assert detected.format == "xmlrpc"
    doc = adapter.parse(_METHOD_CALL, source_label="01-method-call.xml")
    api = adapter.normalize(doc)
    assert len(api.services) == 1
    assert api.services[0].operations[0].name == "inventory.reserveStock"


def test_adapter_invalid_source_raises(adapter: XmlRpcImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("<note><to>you</to></note>")


def test_emitter_round_trips_core_constructs():
    doc = parse_xmlrpc(_METHOD_CALL)
    api = XmlRpcNormalizer().normalize(doc)
    emitter = get_emitter("xmlrpc")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "<methodCall>" in text
    assert "inventory.reserveStock" in text
    assert "customerId" in text
    assert "priority" in text
    assert "WIDGET-001" in text


def test_catalog_conversion_resolves_xmlrpc_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("xmlrpc", _METHOD_CALL).key == "xmlrpc"
