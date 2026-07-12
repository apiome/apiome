"""Tests for ONC RPC catalog import/export adapters — MFI-21.6."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.oncrpc_emitter import validate_oncrpc_document
from app.oncrpc_import_source import OncRpcImportSource
from app.oncrpc_normalizer import OncRpcNormalizer
from app.oncrpc_parser import is_oncrpc, parse_oncrpc

_KV_STORE_X = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/onc-rpc/01-key-value-store.x"
).read_text(encoding="utf-8")
_FILE_STAT_X = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/onc-rpc/02-file-stat.x"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> OncRpcImportSource:
    return OncRpcImportSource()


def test_is_oncrpc_recognizes_key_value_store():
    assert is_oncrpc(_KV_STORE_X) is True
    assert is_oncrpc('syntax = "proto3";') is False


def test_parse_collects_program_and_types():
    doc = parse_oncrpc(_KV_STORE_X)
    assert doc.programs[0].name == "KV_PROG"
    assert doc.programs[0].number == 0x20000001
    assert {struct.name for struct in doc.structs} == {"kv_entry", "kv_put_args", "kv_get_res"}
    assert doc.typedefs[0].name == "kv_key"


def test_parse_second_fixture_covers_file_stat():
    doc = parse_oncrpc(_FILE_STAT_X)
    assert doc.programs[0].name == "FILE_PROG"
    assert doc.programs[0].versions[0].procedures[0].name == "FILE_STAT"


def test_normalizer_maps_rpc_types_and_operations():
    doc = parse_oncrpc(_KV_STORE_X)
    api = OncRpcNormalizer().normalize(doc)
    assert api.format == "oncrpc"
    assert api.paradigm is ApiParadigm.RPC
    assert api.services[0].name == "KV_PROG"
    assert len(api.services[0].operations) == 3
    kv_entry = next(t for t in api.types if t.name == "kv_entry")
    assert kv_entry.kind is TypeKind.RECORD
    union = next(t for t in api.types if t.name == "kv_get_res")
    assert union.kind is TypeKind.UNION


def test_adapter_detect_parse_normalize(adapter: OncRpcImportSource):
    detected = adapter.detect(
        DetectionInput(text=_KV_STORE_X, filename="01-key-value-store.x")
    )
    assert detected.matched
    assert detected.format == "oncrpc"
    doc = adapter.parse(_KV_STORE_X, source_label="01-key-value-store.x")
    api = adapter.normalize(doc)
    assert api.extras.get("oncrpc_programs")


def test_adapter_invalid_source_raises(adapter: OncRpcImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("struct Only { int x; };")


def test_emitter_round_trips_core_constructs():
    doc = parse_oncrpc(_KV_STORE_X)
    api = OncRpcNormalizer().normalize(doc)
    emitter = get_emitter("oncrpc")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "program KV_PROG" in text
    assert "union kv_get_res switch" in text
    assert "KV_GET(kv_key)" in text
    validate_oncrpc_document(text)


def test_emitter_round_trips_file_stat_fixture():
    doc = parse_oncrpc(_FILE_STAT_X)
    api = OncRpcNormalizer().normalize(doc)
    emitter = get_emitter("oncrpc")
    assert emitter is not None
    text = emitter().emit(api).files[0].content
    assert "program FILE_PROG" in text
    assert "FILE_STAT(file_stat_args)" in text
    validate_oncrpc_document(text)


def test_catalog_conversion_resolves_oncrpc_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("oncrpc", _KV_STORE_X).key == "oncrpc"
