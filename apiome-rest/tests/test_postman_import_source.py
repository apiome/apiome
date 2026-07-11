"""Tests for Postman catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError
from app.postman_import_source import PostmanImportSource
from app.postman_normalizer import PostmanNormalizer
from app.postman_parser import is_postman, parse_postman, postman_http_path

_TASKS_COLLECTION = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/postman/01-tasks-collection.postman_collection.json"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> PostmanImportSource:
    return PostmanImportSource()


def test_is_postman_recognizes_tasks_collection():
    assert is_postman(_TASKS_COLLECTION) is True
    assert is_postman('{"openapi":"3.0.0"}') is False


def test_parse_collects_requests_and_variables():
    doc = parse_postman(_TASKS_COLLECTION)
    assert doc.name == "Tasks API"
    assert doc.schema_url and "postman.com" in doc.schema_url
    assert any(variable.key == "baseUrl" for variable in doc.variables)
    methods = {(op.request.method, postman_http_path(op.request.url)) for op in doc.operations}
    assert ("GET", "/tasks") in methods
    assert ("POST", "/tasks") in methods
    assert ("GET", "/tasks/{id}") in methods


def test_normalizer_maps_rest_http_service():
    doc = parse_postman(_TASKS_COLLECTION)
    api = PostmanNormalizer().normalize(doc)
    assert api.format == "postman"
    assert api.paradigm is ApiParadigm.REST
    assert api.protocol == "http"
    assert api.title == "Tasks API"
    task = next(t for t in api.types if t.name == "Task")
    assert task.kind is TypeKind.RECORD
    assert {field.name for field in task.fields} == {"title", "dueDate", "done"}
    service = api.services[0]
    assert any(op.http_path == "/tasks" and op.http_method == "POST" for op in service.operations)
    assert api.servers and "api.example.com" in api.servers[0].url


def test_adapter_detect_parse_normalize(adapter: PostmanImportSource):
    detected = adapter.detect(
        DetectionInput(
            text=_TASKS_COLLECTION,
            filename="01-tasks-collection.postman_collection.json",
        )
    )
    assert detected.matched
    assert detected.format == "postman"
    doc = adapter.parse(_TASKS_COLLECTION, source_label="01-tasks-collection.postman_collection.json")
    api = adapter.normalize(doc)
    assert len(api.services) == 1
    assert len(api.services[0].operations) == 3
    assert len(api.types) >= 1


def test_adapter_invalid_source_raises(adapter: PostmanImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"title":"nope"}')


def test_emitter_round_trips_core_constructs():
    doc = parse_postman(_TASKS_COLLECTION)
    api = PostmanNormalizer().normalize(doc)
    emitter = get_emitter("postman")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert '"info"' in text
    assert "Tasks API" in text
    assert '"item"' in text
    assert "Create task" in text
    assert "Buy milk" in text
    assert "postman.com" in text


def test_catalog_conversion_resolves_postman_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("postman", _TASKS_COLLECTION).key == "postman"
