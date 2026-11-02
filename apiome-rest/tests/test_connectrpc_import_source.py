"""Tests for Connect-RPC catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm
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


# --- MFI-19.5: Buf config detection and the Connect HTTP/JSON binding ---------------------

_BUF_GEN_CONNECT = """
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: gen
  - remote: buf.build/connectrpc/go
    out: gen
"""

_BUF_GEN_PLAIN = """
version: v2
plugins:
  - remote: buf.build/protocolbuffers/go
    out: gen
  - remote: buf.build/grpc/go
    out: gen
"""


def test_buf_config_evidence_names_the_connect_config():
    from app.connectrpc_import_source import buf_config_connect_evidence

    members = {
        "proto/demo.proto": _GENERIC_PROTO,
        "buf.yaml": "version: v2\nmodules:\n  - path: proto\n",
        "buf.gen.yaml": _BUF_GEN_CONNECT,
    }
    assert buf_config_connect_evidence(members) == "buf.gen.yaml"


@pytest.mark.parametrize(
    "members",
    [
        None,
        {},
        {"proto/demo.proto": _GENERIC_PROTO, "buf.gen.yaml": _BUF_GEN_PLAIN},
        # Connect mentioned in a file that is not a Buf config does not count.
        {"proto/demo.proto": _GENERIC_PROTO, "README.md": "uses buf.build/connectrpc/go"},
    ],
)
def test_buf_config_evidence_ignores_non_connect_modules(members):
    from app.connectrpc_import_source import buf_config_connect_evidence

    assert buf_config_connect_evidence(members) is None


def test_detect_claims_proto_next_to_a_connect_buf_config(adapter: ConnectRpcImportSource):
    members = {"proto/demo.proto": _GENERIC_PROTO, "buf.gen.yaml": _BUF_GEN_CONNECT}
    detected = adapter.detect(
        DetectionInput(text=_GENERIC_PROTO, filename="proto/demo.proto", siblings=members)
    )
    assert detected.matched
    assert detected.format == "connectrpc"
    assert "buf.gen.yaml" in (detected.reason or "")


def test_detect_leaves_proto_next_to_a_plain_buf_config_to_grpc(adapter: ConnectRpcImportSource):
    members = {"proto/demo.proto": _GENERIC_PROTO, "buf.gen.yaml": _BUF_GEN_PLAIN}
    detected = adapter.detect(
        DetectionInput(text=_GENERIC_PROTO, filename="proto/demo.proto", siblings=members)
    )
    assert detected.matched is False


def test_archive_root_ranking_prefers_connect_when_buf_config_targets_connect():
    from app.archive_intake import rank_root_candidates

    members = {"proto/demo.proto": _GENERIC_PROTO, "buf.gen.yaml": _BUF_GEN_CONNECT}
    leader = rank_root_candidates(members)[0]
    assert leader.path == "proto/demo.proto"
    assert leader.format == "connectrpc"

    plain = rank_root_candidates({"proto/demo.proto": _GENERIC_PROTO, "buf.gen.yaml": _BUF_GEN_PLAIN})
    assert plain[0].path == "proto/demo.proto"
    assert plain[0].format == "protobuf"


def test_connect_route_is_post_package_service_method():
    from app.connectrpc_normalizer import connect_route

    assert connect_route("greet.v1.GreetService", "Greet") == "/greet.v1.GreetService/Greet"


@pytest.mark.skipif(
    not GrpcImportSource().descriptor().available,
    reason="buf toolchain unavailable",
)
def test_normalizer_exposes_the_connect_http_json_binding():
    from app.canonical_model import StreamingMode
    from app.connectrpc_normalizer import (
        CONNECT_ROUTE_TEMPLATE,
        CONNECT_STREAMING_CONTENT_TYPES,
        CONNECT_UNARY_CONTENT_TYPES,
    )

    compiled = GrpcImportSource().parse(_CONNECT_GREETER, source_label="greeter.proto")
    api = ConnectRpcNormalizer().normalize(compiled)

    assert api.extras["rpc_stack"] == "connect"
    assert api.extras["connect"]["route_template"] == CONNECT_ROUTE_TEMPLATE
    assert api.extras["connect"]["unary_content_types"] == list(CONNECT_UNARY_CONTENT_TYPES)

    service = api.services[0]
    by_name = {op.name: op for op in service.operations}
    unary = by_name["Greet"]
    assert unary.streaming is StreamingMode.NONE
    assert unary.extras["http"] == {"method": "post", "path": "/greet.v1.GreetService/Greet"}
    assert unary.extras["connect"] == {
        "content_types": list(CONNECT_UNARY_CONTENT_TYPES),
        "streaming": False,
    }
    stream = by_name["GreetStream"]
    assert stream.streaming is StreamingMode.SERVER
    assert stream.extras["http"] == {"method": "post", "path": "/greet.v1.GreetService/GreetStream"}
    assert stream.extras["connect"] == {
        "content_types": list(CONNECT_STREAMING_CONTENT_TYPES),
        "streaming": True,
    }
    # The gRPC view of the same contract carries no binding: the tag is what Connect adds.
    plain = GrpcImportSource().normalize(compiled)
    assert "http" not in plain.services[0].operations[0].extras


@pytest.mark.skipif(
    not GrpcImportSource().descriptor().available,
    reason="buf toolchain unavailable",
)
def test_projection_honours_the_connect_binding_instead_of_synthesizing_one():
    from app.emitter import LossTracker
    from app.projection import RpcProjection

    compiled = GrpcImportSource().parse(_CONNECT_GREETER, source_label="greeter.proto")
    api = ConnectRpcNormalizer().normalize(compiled)
    service = api.services[0]
    unary = next(op for op in service.operations if op.name == "Greet")

    losses = LossTracker()
    binding = RpcProjection().route(unary, service, losses)
    assert binding is not None
    assert (binding.method, binding.path, binding.from_source) == (
        "post",
        "/greet.v1.GreetService/Greet",
        True,
    )
    assert not any(loss.subject == "synthesized-http-binding" for loss in losses.records())


def test_archive_intake_routes_a_buf_connect_module_to_the_connect_adapter():
    """End to end through archive intake: a zipped Buf module whose ``buf.gen.yaml`` names a
    Connect plugin resolves to a ``connectrpc`` root, while the same module without it stays
    ``protobuf``."""
    import io
    import zipfile

    from app.archive_intake import unpack_archive

    def zipped(gen_yaml: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("buf.yaml", "version: v2\nmodules:\n  - path: proto\n")
            archive.writestr("buf.gen.yaml", gen_yaml)
            archive.writestr("proto/demo/v1/demo.proto", _GENERIC_PROTO)
        return buffer.getvalue()

    connect = unpack_archive(zipped(_BUF_GEN_CONNECT), source_label="demo-connect.zip")
    assert connect.root_path == "proto/demo/v1/demo.proto"
    assert connect.detection.detected is not None
    assert connect.detection.detected.format == "connectrpc"

    plain = unpack_archive(zipped(_BUF_GEN_PLAIN), source_label="demo-grpc.zip")
    assert plain.root_path == "proto/demo/v1/demo.proto"
    assert plain.detection.detected is not None
    assert plain.detection.detected.format == "protobuf"
