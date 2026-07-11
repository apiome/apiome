"""Tests for OpenRPC catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.openrpc_import_source import OpenRpcImportSource
from app.openrpc_normalizer import OpenRpcNormalizer
from app.openrpc_parser import is_openrpc, parse_openrpc

_WALLET_OPENRPC = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/openrpc/01-wallet-api.json"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> OpenRpcImportSource:
    return OpenRpcImportSource()


def test_is_openrpc_recognizes_wallet_api():
    assert is_openrpc(_WALLET_OPENRPC) is True
    assert is_openrpc('{"openapi":"3.0.0"}') is False


def test_parse_collects_methods_and_schemas():
    doc = parse_openrpc(_WALLET_OPENRPC)
    assert doc.openrpc_version == "1.2.6"
    assert doc.title == "Wallet API"
    assert doc.version == "1.0.0"
    assert {name for name in doc.schemas} == {"Balance", "TransferReceipt"}
    assert {method.name for method in doc.methods} == {"getBalance", "transfer"}
    assert doc.servers and doc.servers[0].url == "https://api.example.com/rpc"


def test_normalizer_maps_rpc_service():
    doc = parse_openrpc(_WALLET_OPENRPC)
    api = OpenRpcNormalizer().normalize(doc)
    assert api.format == "openrpc"
    assert api.paradigm is ApiParadigm.RPC
    assert api.protocol == "jsonrpc"
    assert api.extras.get("openrpc_version") == "1.2.6"
    balance = next(t for t in api.types if t.name == "Balance")
    assert any(f.name == "accountId" for f in balance.fields)
    service = api.services[0]
    assert any(op.name == "getBalance" for op in service.operations)
    assert api.servers and "api.example.com" in api.servers[0].url


def test_adapter_detect_parse_normalize(adapter: OpenRpcImportSource):
    detected = adapter.detect(
        DetectionInput(text=_WALLET_OPENRPC, filename="01-wallet-api.json")
    )
    assert detected.matched
    assert detected.format == "openrpc"
    doc = adapter.parse(_WALLET_OPENRPC, source_label="01-wallet-api.json")
    api = adapter.normalize(doc)
    assert len(api.types) >= 2
    assert len(api.services) == 1
    assert len(api.services[0].operations) == 2


def test_adapter_invalid_source_raises(adapter: OpenRpcImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"title":"nope"}')


def test_emitter_round_trips_core_constructs():
    doc = parse_openrpc(_WALLET_OPENRPC)
    api = OpenRpcNormalizer().normalize(doc)
    emitter = get_emitter("openrpc")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert '"openrpc"' in text
    assert "Wallet API" in text
    assert "getBalance" in text
    assert "Balance" in text
    assert "components" in text


def test_catalog_conversion_resolves_openrpc_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("openrpc", _WALLET_OPENRPC).key == "openrpc"
