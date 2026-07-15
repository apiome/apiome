"""Tests for Connect-RPC catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.connectrpc_import_source import ConnectRpcImportSource
from app.connectrpc_normalizer import ConnectRpcNormalizer
from app.emitter import get_emitter
from app.grpc_import_source import GrpcImportSource
from app.import_source import DetectionInput, ImportSourceError, detect_import_source

_CONNECT_GREETER = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/connectrpc/01-greeter.proto"
).read_text(encoding="utf-8")

_GENERIC_PROTO = """
syntax = "proto3";
package demo.v1;
service Demo { rpc Ping(PingRequest) returns (PingResponse); }
message PingRequest { string id = 1; }
message PingResponse { string ok = 1; }
"""


@pytest.fixture()
def adapter() -> ConnectRpcImportSource:
    return ConnectRpcImportSource()


def test_detect_prefers_connect_markers_over_generic_proto(adapter: ConnectRpcImportSource):
    detected = adapter.detect(
        DetectionInput(text=_CONNECT_GREETER, filename="connectrpc/01-greeter.proto")
    )
    assert detected.matched
    assert detected.format == "connectrpc"


def test_detect_does_not_claim_generic_proto(adapter: ConnectRpcImportSource):
    assert adapter.detect(DetectionInput(text=_GENERIC_PROTO, filename="demo.proto")).matched is False


def test_auto_detect_ranks_connect_above_grpc_for_connect_proto():
    matched = detect_import_source(
        DetectionInput(text=_CONNECT_GREETER, filename="connectrpc/01-greeter.proto")
    )
    assert matched is not None
    adapter, result = matched
    assert adapter.key == "connectrpc"
    assert result.format == "connectrpc"


@pytest.mark.skipif(
    not GrpcImportSource().descriptor().available,
    reason="buf toolchain unavailable",
)
def test_normalizer_relabels_format():
    grpc = GrpcImportSource()
    compiled = grpc.parse(_CONNECT_GREETER, source_label="greeter.proto")
    api = ConnectRpcNormalizer().normalize(compiled)
    assert api.format == "connectrpc"
    assert api.paradigm is ApiParadigm.RPC
    assert api.extras.get("rpc_stack") == "connect"
    assert any(t.name == "GreetRequest" for t in api.types)


@pytest.mark.skipif(
    not GrpcImportSource().descriptor().available,
    reason="buf toolchain unavailable",
)
def test_adapter_parse_normalize_round_trip(adapter: ConnectRpcImportSource):
    compiled = adapter.parse(_CONNECT_GREETER, source_label="greeter.proto")
    api = adapter.normalize(compiled)
    assert api.format == "connectrpc"
    assert api.services[0].name == "GreetService"


def test_adapter_invalid_source_raises(adapter: ConnectRpcImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not a proto")


@pytest.mark.skipif(
    not GrpcImportSource().descriptor().available,
    reason="buf toolchain unavailable",
)
def test_emitter_produces_proto_bundle():
    grpc = GrpcImportSource()
    compiled = grpc.parse(_CONNECT_GREETER, source_label="greeter.proto")
    api = ConnectRpcNormalizer().normalize(compiled)
    emitter = get_emitter("connectrpc")
    assert emitter is not None
    result = emitter().emit(api)
    text = "\n".join(f.content for f in result.files)
    assert "Connect-RPC" in text
    assert "service GreetService" in text


def test_catalog_conversion_resolves_connect_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("connectrpc", _CONNECT_GREETER).key == "connectrpc"
