"""Tests for WADL catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.wadl_import_source import WadlImportSource
from app.wadl_normalizer import WadlNormalizer
from app.wadl_parser import is_wadl, parse_wadl

_BOOKSTORE_WADL = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/wadl/01-bookstore.wadl"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> WadlImportSource:
    return WadlImportSource()


def test_is_wadl_recognizes_bookstore_service():
    assert is_wadl(_BOOKSTORE_WADL) is True
    assert is_wadl("openapi: 3.0.0") is False


def test_parse_collects_types_and_resources():
    doc = parse_wadl(_BOOKSTORE_WADL)
    assert doc.target_namespace == "http://example.com/bookstore"
    assert doc.base_uri == "https://api.example.com/"
    assert {t.name for t in doc.complex_types} == {"Book"}
    assert {e.name for e in doc.elements} == {"book"}
    methods = {(op.method, op.path) for op in doc.operations}
    assert ("GET", "/books") in methods
    assert ("POST", "/books") in methods
    assert ("GET", "/books/{bookId}") in methods


def test_normalizer_maps_rest_http_service():
    doc = parse_wadl(_BOOKSTORE_WADL)
    api = WadlNormalizer().normalize(doc)
    assert api.format == "wadl"
    assert api.paradigm is ApiParadigm.REST
    assert api.protocol == "http"
    assert api.extras.get("wadl_target_namespace") == "http://example.com/bookstore"
    book = next(t for t in api.types if t.name == "Book")
    assert any(f.name == "title" for f in book.fields)
    service = api.services[0]
    assert any(op.http_path == "/books" and op.http_method == "GET" for op in service.operations)
    assert api.servers and api.servers[0].url == "https://api.example.com/"


def test_adapter_detect_parse_normalize(adapter: WadlImportSource):
    detected = adapter.detect(DetectionInput(text=_BOOKSTORE_WADL, filename="01-bookstore.wadl"))
    assert detected.matched
    assert detected.format == "wadl"
    doc = adapter.parse(_BOOKSTORE_WADL, source_label="01-bookstore.wadl")
    api = adapter.normalize(doc)
    assert len(api.types) >= 1
    assert len(api.services) == 1
    assert len(api.services[0].operations) >= 3


def test_adapter_invalid_source_raises(adapter: WadlImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not wadl")


def test_emitter_round_trips_core_constructs():
    doc = parse_wadl(_BOOKSTORE_WADL)
    api = WadlNormalizer().normalize(doc)
    emitter = get_emitter("wadl")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "application" in text
    assert "wadl.dev.java.net" in text
    assert "Book" in text
    assert 'path="books"' in text or "path=\"books\"" in text


def test_catalog_conversion_resolves_wadl_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("wadl", _BOOKSTORE_WADL).key == "wadl"
