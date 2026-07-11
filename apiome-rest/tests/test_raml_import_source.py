"""Tests for RAML catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.raml_import_source import RamlImportSource
from app.raml_normalizer import RamlNormalizer
from app.raml_parser import is_raml, parse_raml

_SIMPLE_API_RAML = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/raml/01-simple-api.raml"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> RamlImportSource:
    return RamlImportSource()


def test_is_raml_recognizes_simple_api():
    assert is_raml(_SIMPLE_API_RAML) is True
    assert is_raml("openapi: 3.0.0") is False


def test_parse_collects_types_and_resources():
    doc = parse_raml(_SIMPLE_API_RAML)
    assert doc.title == "Bookstore API"
    assert doc.version == "v1"
    assert doc.base_uri == "https://api.example.com/{version}"
    assert {t.name for t in doc.types} == {"Book", "NewBook"}
    methods = {(op.method, op.path) for op in doc.operations}
    assert ("get", "/books") in methods
    assert ("post", "/books") in methods
    assert ("get", "/books/{bookId}") in methods


def test_normalizer_maps_rest_http_service():
    doc = parse_raml(_SIMPLE_API_RAML)
    api = RamlNormalizer().normalize(doc)
    assert api.format == "raml"
    assert api.paradigm is ApiParadigm.REST
    assert api.protocol == "http"
    book = next(t for t in api.types if t.name == "Book")
    assert any(f.name == "title" for f in book.fields)
    service = api.services[0]
    assert any(op.http_path == "/books" and op.http_method == "GET" for op in service.operations)
    assert api.servers and "api.example.com" in api.servers[0].url


def test_adapter_detect_parse_normalize(adapter: RamlImportSource):
    detected = adapter.detect(DetectionInput(text=_SIMPLE_API_RAML, filename="01-simple-api.raml"))
    assert detected.matched
    assert detected.format == "raml"
    doc = adapter.parse(_SIMPLE_API_RAML, source_label="01-simple-api.raml")
    api = adapter.normalize(doc)
    assert len(api.types) >= 2
    assert len(api.services) == 1
    assert len(api.services[0].operations) >= 3


def test_adapter_invalid_source_raises(adapter: RamlImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse("not raml")


def test_emitter_round_trips_core_constructs():
    doc = parse_raml(_SIMPLE_API_RAML)
    api = RamlNormalizer().normalize(doc)
    emitter = get_emitter("raml")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "#%RAML" in text
    assert "title: Bookstore API" in text
    assert "types:" in text
    assert "Book:" in text
    assert "/books:" in text


def test_catalog_conversion_resolves_raml_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("raml", _SIMPLE_API_RAML).key == "raml"
