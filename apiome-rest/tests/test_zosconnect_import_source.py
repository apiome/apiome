"""Tests for z/OS Connect catalog import/export adapters — MFI-22.9 / MFX-33.1."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, OperationKind, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.zosconnect_emitter import validate_zosconnect_document
from app.zosconnect_import_source import ZosConnectImportSource
from app.zosconnect_normalizer import ZosConnectNormalizer
from app.zosconnect_parser import is_zosconnect, parse_zosconnect

_API_REQUESTER = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/zos-connect/01-api-requester.json"
).read_text(encoding="utf-8")
_API_PROVIDER = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/zos-connect/02-api-provider.json"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> ZosConnectImportSource:
    return ZosConnectImportSource()


def test_is_zosconnect_recognizes_requester_fixture():
    assert is_zosconnect(_API_REQUESTER) is True
    assert is_zosconnect('{"info":{"schema":"https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},"item":[]}') is False
    assert is_zosconnect('{"openapi":"3.1.0","info":{"title":"x"}}') is False


def test_parse_requester_collects_operations_and_metadata():
    doc = parse_zosconnect(_API_REQUESTER)
    assert doc.descriptor.kind == "requester"
    assert doc.descriptor.name == "InventoryRequester"
    assert doc.api.title == "Inventory API"
    assert doc.language.type_expr == "cobol"
    assert len(doc.operations) == 2
    reserve = next(op for op in doc.operations if op.operation_id == "reserveStock")
    assert reserve.method == "POST"
    assert reserve.request_structure == "RESERVE-REQUEST"
    assert reserve.path_parameters[0].field == "RES-SKU"


def test_parse_provider_fixture_covers_program_binding():
    doc = parse_zosconnect(_API_PROVIDER)
    assert doc.descriptor.kind == "provider"
    get_customer = next(op for op in doc.operations if op.operation_id == "getCustomer")
    assert get_customer.program == "CUSTGET"
    assert get_customer.path == "/customers/{customerId}"


def test_normalizer_maps_rest_service_and_structures():
    doc = parse_zosconnect(_API_REQUESTER)
    api = ZosConnectNormalizer().normalize(doc)
    assert api.format == "zosconnect"
    assert api.paradigm is ApiParadigm.REST
    assert api.services
    operation = api.services[0].operations[0]
    assert operation.kind is OperationKind.REQUEST_RESPONSE
    assert operation.http_method == "GET"
    request_type = next(type_ for type_ in api.types if type_.name == "GET-STOCK-REQUEST")
    assert request_type.kind is TypeKind.RECORD
    assert any(field.name == "REQ-SKU" for field in request_type.fields)


def test_adapter_detect_parse_normalize(adapter: ZosConnectImportSource):
    detected = adapter.detect(
        DetectionInput(text=_API_REQUESTER, filename="01-api-requester.json")
    )
    assert detected.matched
    assert detected.format == "zosconnect"
    doc = adapter.parse(_API_REQUESTER)
    api = adapter.normalize(doc)
    assert api.extras.get("zosconnect_kind") == "requester"
    assert len(api.extras.get("zosconnect_operations", [])) == 2


def test_adapter_invalid_source_raises(adapter: ZosConnectImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"apiRequester":{"name":"X"},"operations":[]}')


def test_emitter_round_trips_requester_fixture():
    doc = parse_zosconnect(_API_REQUESTER)
    api = ZosConnectNormalizer().normalize(doc)
    emitter = get_emitter("zosconnect")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "apiRequester" in text
    assert "getStockLevel" in text
    assert "RESERVE-REQUEST" in text
    validate_zosconnect_document(text)


def test_emitter_round_trips_provider_fixture():
    doc = parse_zosconnect(_API_PROVIDER)
    api = ZosConnectNormalizer().normalize(doc)
    emitter = get_emitter("zosconnect")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "apiProvider" in text
    assert "CUSTGET" in text
    validate_zosconnect_document(text)


def test_catalog_conversion_resolves_zosconnect_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("zosconnect", _API_REQUESTER).key == "zosconnect"
