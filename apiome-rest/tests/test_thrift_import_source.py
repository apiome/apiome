"""Tests for the Apache Thrift parser, normalizer, import source, and emitter."""

from __future__ import annotations

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.thrift_import_source import ThriftImportSource
from app.thrift_normalizer import ThriftNormalizer
from app.thrift_parser import ThriftParseError, is_thrift, parse_thrift

_USER_SERVICE = """
namespace java com.example.user

enum Status {
  ACTIVE = 1,
  SUSPENDED = 2,
  DELETED = 3,
}

struct User {
  1: required string id,
  2: required string email,
  3: optional string displayName,
  4: Status status = Status.ACTIVE,
  5: list<string> roles,
  6: i64 createdAt,
}

struct CreateUserRequest {
  1: required string email,
  2: optional string displayName,
}

exception NotFound {
  1: string message,
}

service UserService {
  User getUser(1: string id) throws (1: NotFound nf),
  User createUser(1: CreateUserRequest request),
  void deleteUser(1: string id) throws (1: NotFound nf),
}
"""


@pytest.fixture()
def adapter() -> ThriftImportSource:
    return ThriftImportSource()


def test_is_thrift_recognizes_struct_and_service():
    assert is_thrift(_USER_SERVICE) is True
    assert is_thrift("openapi: 3.0.0") is False


def test_parse_thrift_collects_types_and_service():
    doc = parse_thrift(_USER_SERVICE)
    assert {e.name for e in doc.enums} == {"Status"}
    assert {s.name for s in doc.structs} == {"User", "CreateUserRequest", "NotFound"}
    assert len(doc.services) == 1
    assert doc.services[0].name == "UserService"
    assert {m.name for m in doc.services[0].methods} == {"getUser", "createUser", "deleteUser"}


def test_parse_thrift_empty_raises():
    with pytest.raises(ThriftParseError):
        parse_thrift("")


def test_normalizer_maps_rpc_surface():
    doc = parse_thrift(_USER_SERVICE)
    api = ThriftNormalizer().normalize(doc)
    assert api.format == "thrift"
    assert api.paradigm is ApiParadigm.RPC
    assert api.services
    assert any(t.kind is TypeKind.ENUM and t.name == "Status" for t in api.types)
    assert any(
        t.name == "User" and any(f.name == "id" and f.field_number == 1 for f in t.fields)
        for t in api.types
    )


def test_adapter_detect_parse_normalize(adapter: ThriftImportSource):
    detected = adapter.detect(DetectionInput(text=_USER_SERVICE, filename="user.thrift"))
    assert detected.matched
    assert detected.format == "thrift"
    doc = adapter.parse(_USER_SERVICE, source_label="user.thrift")
    api = adapter.normalize(doc)
    assert api.services[0].name == "UserService"


def test_adapter_invalid_source_raises(adapter: ThriftImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not thrift")


def test_emitter_round_trips_core_constructs():
    doc = parse_thrift(_USER_SERVICE)
    api = ThriftNormalizer().normalize(doc)
    emitter = get_emitter("thrift")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "enum Status" in text
    assert "struct User" in text
    assert "service UserService" in text
    assert "getUser" in text


def test_catalog_conversion_resolves_thrift_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("thrift", _USER_SERVICE).key == "thrift"
