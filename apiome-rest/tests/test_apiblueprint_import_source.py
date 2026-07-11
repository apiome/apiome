"""Tests for API Blueprint catalog import/export adapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.apiblueprint_import_source import ApiblueprintImportSource
from app.apiblueprint_normalizer import ApiblueprintNormalizer
from app.apiblueprint_parser import is_apiblueprint, parse_apiblueprint
from app.canonical_model import ApiParadigm, TypeKind
from app.emitter import get_emitter
from app.import_source import DetectionInput, ImportSourceError

_TASKS_API = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/api-blueprint/01-simple-api.apib"
).read_text(encoding="utf-8")


@pytest.fixture()
def adapter() -> ApiblueprintImportSource:
    return ApiblueprintImportSource()


def test_is_apiblueprint_recognizes_tasks_api():
    assert is_apiblueprint(_TASKS_API) is True
    assert is_apiblueprint("#%RAML 1.0\ntitle: x") is False


def test_parse_collects_resources_and_types():
    doc = parse_apiblueprint(_TASKS_API)
    assert doc.format_version == "1A"
    assert doc.title == "Task API"
    assert doc.host == "https://api.example.com"
    assert {item.name for item in doc.types} == {"Task", "NewTask"}
    methods = {(op.method, op.path) for op in doc.operations}
    assert ("GET", "/tasks") in methods
    assert ("POST", "/tasks") in methods
    assert ("GET", "/tasks/{id}") in methods


def test_normalizer_maps_rest_http_service():
    doc = parse_apiblueprint(_TASKS_API)
    api = ApiblueprintNormalizer().normalize(doc)
    assert api.format == "apiblueprint"
    assert api.paradigm is ApiParadigm.REST
    assert api.protocol == "http"
    assert api.title == "Task API"
    task = next(t for t in api.types if t.name == "Task")
    assert task.kind is TypeKind.RECORD
    assert {field.name for field in task.fields} == {"id", "title", "done", "dueDate"}
    service = api.services[0]
    assert any(op.http_path == "/tasks" and op.http_method == "POST" for op in service.operations)
    assert api.servers and "api.example.com" in api.servers[0].url


def test_adapter_detect_parse_normalize(adapter: ApiblueprintImportSource):
    detected = adapter.detect(
        DetectionInput(
            text=_TASKS_API,
            filename="01-simple-api.apib",
        )
    )
    assert detected.matched
    assert detected.format == "api-blueprint"
    doc = adapter.parse(_TASKS_API, source_label="01-simple-api.apib")
    api = adapter.normalize(doc)
    assert len(api.services) == 1
    assert len(api.services[0].operations) == 3
    assert len(api.types) == 2


def test_adapter_invalid_source_raises(adapter: ApiblueprintImportSource):
    with pytest.raises(ImportSourceError):
        adapter.parse('{"openapi":"3.0.0"}')


def test_emitter_round_trips_core_constructs():
    doc = parse_apiblueprint(_TASKS_API)
    api = ApiblueprintNormalizer().normalize(doc)
    emitter = get_emitter("apiblueprint")
    assert emitter is not None
    result = emitter().emit(api)
    text = result.files[0].content
    assert "FORMAT: 1A" in text
    assert "# Task API" in text
    assert "## Tasks Collection [/tasks]" in text or "## Tasks [/tasks]" in text
    assert "### Create a task [POST]" in text
    assert "## Task (object)" in text
    assert "Buy milk" in text


def test_catalog_conversion_resolves_apiblueprint_adapter():
    from app.catalog_conversion import resolve_conversion_adapter

    assert resolve_conversion_adapter("api-blueprint", _TASKS_API).key == "apiblueprint"
