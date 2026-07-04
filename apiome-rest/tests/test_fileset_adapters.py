"""Adapter multi-document (fileset) intake — MFI-29.2 (#4389)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.asyncapi_fileset import bundle_asyncapi_fileset
from app.asyncapi_import_source import AsyncApiImportSource
from app.fileset import IntakeFileset
from app.graphql_import_source import GraphQlImportSource
from app.graphql_parser import GraphQlSource, parse_graphql_sources
from app.grpc_import_source import GrpcImportSource
from app.import_source import ImportSourceError, InputKind
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures"
_GRAPHQL = _FIXTURES / "graphql"
_ASYNCAPI_SUITE = _FIXTURES / "asyncapi" / "suite"
_PROTO = _FIXTURES / "proto"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _graphql_fileset() -> IntakeFileset:
    members = {
        "schema.query.graphql": _read(_GRAPHQL / "schema.query.graphql"),
        "schema.types.graphql": _read(_GRAPHQL / "schema.types.graphql"),
        "schema.mutation.graphql": _read(_GRAPHQL / "schema.mutation.graphql"),
    }
    return IntakeFileset.from_members(members, root="schema.query.graphql")


def _graphql_flattened_sdl() -> str:
    result = parse_graphql_sources(
        [
            GraphQlSource(label=name, text=text)
            for name, text in sorted(_graphql_fileset().members.items())
        ]
    )
    assert result.ok, result.errors
    assert result.sdl is not None
    return result.sdl


def _asyncapi_fileset() -> IntakeFileset:
    members = {
        "api.yaml": _read(_ASYNCAPI_SUITE / "api.yaml"),
        "components/messages.yaml": _read(_ASYNCAPI_SUITE / "components" / "messages.yaml"),
        "components/schemas.yaml": _read(_ASYNCAPI_SUITE / "components" / "schemas.yaml"),
    }
    return IntakeFileset.from_members(members, root="api.yaml")


def _proto_fileset(*, include_common: bool = True) -> IntakeFileset:
    members = {
        "user/user_service.proto": _read(_PROTO / "user" / "user_service.proto"),
    }
    if include_common:
        members["common/types.proto"] = _read(_PROTO / "common" / "types.proto")
    return IntakeFileset.from_members(members, root="user/user_service.proto")


# ===========================================================================
# SPI descriptor
# ===========================================================================


def test_mvp_adapters_advertise_fileset_input_kind() -> None:
    for adapter in (GrpcImportSource(), GraphQlImportSource(), AsyncApiImportSource()):
        assert InputKind.FILESET in adapter.descriptor().input_kinds


# ===========================================================================
# GraphQL
# ===========================================================================


def test_graphql_parse_fileset_builds_multi_file_schema() -> None:
    schema = GraphQlImportSource().parse_fileset(_graphql_fileset())
    assert schema.query_type is not None
    assert schema.mutation_type is not None
    assert "authors" in schema.query_type.fields


def test_graphql_fileset_fingerprint_matches_flattened_sdl() -> None:
    adapter = GraphQlImportSource()
    flattened = adapter.parse(_graphql_flattened_sdl(), source_label="merged.graphql")
    from_fileset = adapter.parse_fileset(_graphql_fileset())
    flat_model = adapter.normalize(flattened)
    fileset_model = adapter.normalize(from_fileset)
    assert adapter.fingerprint(flat_model) == adapter.fingerprint(fileset_model)


def test_graphql_fileset_missing_member_reports_unresolved_type() -> None:
    fileset = IntakeFileset.from_members(
        {"schema.query.graphql": "type Query { post: Post }"},
        root="schema.query.graphql",
    )
    with pytest.raises(ImportSourceError, match="Post"):
        GraphQlImportSource().parse_fileset(fileset)


# ===========================================================================
# AsyncAPI bundler (pure Python — always runs)
# ===========================================================================


def test_asyncapi_bundle_resolves_cross_file_refs() -> None:
    bundled = bundle_asyncapi_fileset(_asyncapi_fileset())
    assert "userId" in bundled
    assert "UserSignedUp" in bundled
    assert "./components/" not in bundled


def test_asyncapi_bundle_missing_member_names_unresolved_ref() -> None:
    fileset = IntakeFileset.from_members(
        {"api.yaml": _read(_ASYNCAPI_SUITE / "broken_api.yaml")},
        root="api.yaml",
    )
    with pytest.raises(ImportSourceError, match="missing\\.yaml"):
        bundle_asyncapi_fileset(fileset)


@pytest.mark.skipif(probe_tool("asyncapi-parser") is None, reason="asyncapi-parser unavailable")
def test_asyncapi_parse_fileset_matches_flattened_bundle() -> None:
    adapter = AsyncApiImportSource()
    fileset = _asyncapi_fileset()
    flattened = bundle_asyncapi_fileset(fileset)
    try:
        flat_model = adapter.normalize(adapter.parse(flattened, source_label="api.yaml"))
        fileset_model = adapter.normalize(adapter.parse_fileset(fileset))
    except ImportSourceError as exc:
        if "asyncapi" in str(exc).lower() or "parser" in str(exc).lower():
            pytest.skip("asyncapi-parser unavailable in this environment")
        raise
    assert adapter.fingerprint(flat_model) == adapter.fingerprint(fileset_model)


# ===========================================================================
# gRPC / Protobuf
# ===========================================================================


@pytest.mark.skipif(probe_tool("buf") is None, reason="buf unavailable")
def test_grpc_fileset_fingerprint_is_stable() -> None:
    adapter = GrpcImportSource()
    fileset = _proto_fileset()
    try:
        compiled = adapter.parse_fileset(fileset)
    except ImportSourceError as exc:
        if "buf" in str(exc).lower():
            pytest.skip("buf unavailable in this environment")
        raise
    model = adapter.normalize(compiled)
    again = adapter.normalize(adapter.parse_fileset(fileset))
    assert adapter.fingerprint(model) == adapter.fingerprint(again)


@pytest.mark.skipif(probe_tool("buf") is None, reason="buf unavailable")
def test_grpc_fileset_missing_import_member_surfaces_diagnostic() -> None:
    adapter = GrpcImportSource()
    with pytest.raises(ImportSourceError, match="import|exist|types\\.proto|unresolved"):
        adapter.parse_fileset(_proto_fileset(include_common=False))
