"""OpenAPI 3.2 support — MFI-30.3 (#4396).

Covers detection, normalization (QUERY/additionalOperations/tag hierarchy),
publishability, meta-schema validation, and the 3.2→3.1 fidelity note.
"""

from __future__ import annotations

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi
from app.fidelity import Coverage, analyze_fidelity
from app.import_routing import PUBLISHABLE_FORMATS, decide_import_routing
from app.import_source import DetectionInput, ImportSourceError, LintReport
from app.openapi_emitter import OpenApiEmitter, X_ADDITIONAL_OPERATIONS, X_QUERY_OPERATION
from app.openapi_import_source import OpenApiImportSource
from app.openapi_validator import (
    OPENAPI_32_META_SCHEMA_ID,
    load_openapi_32_meta_schema,
    validate_openapi_document,
)


def _openapi_32_with_query() -> dict:
    return {
        "openapi": "3.2.0",
        "info": {"title": "Search API", "version": "1.0.0"},
        "tags": [
            {"name": "pets", "summary": "Pet ops", "parent": "store", "kind": "nav"},
            {"name": "store"},
        ],
        "paths": {
            "/pets/search": {
                "query": {
                    "operationId": "searchPets",
                    "tags": ["pets"],
                    "responses": {"200": {"description": "results"}},
                }
            },
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "tags": ["pets"],
                    "responses": {"200": {"description": "ok"}},
                },
                "additionalOperations": {
                    "PURGE": {
                        "operationId": "purgePets",
                        "responses": {"204": {"description": "purged"}},
                    }
                },
            },
        },
        "components": {"schemas": {"Pet": {"type": "object"}}},
    }


@pytest.fixture()
def adapter() -> OpenApiImportSource:
    return OpenApiImportSource()


def test_openapi_32_is_publishable() -> None:
    assert "openapi-3.2" in PUBLISHABLE_FORMATS


def test_detect_openapi_32(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(DetectionInput(document=_openapi_32_with_query()))
    assert result.format == "openapi-3.2"
    assert result.confidence > 0.9


def test_detect_openapi_31_unchanged(adapter: OpenApiImportSource) -> None:
    result = adapter.detect(
        DetectionInput(document={"openapi": "3.1.0", "info": {"title": "T"}, "paths": {}})
    )
    assert result.format == "openapi-3.1"


def test_openapi_32_formats_advertised(adapter: OpenApiImportSource) -> None:
    assert "openapi-3.2" in adapter.descriptor().formats


def test_normalize_openapi_32_query_and_additional_operations(
    adapter: OpenApiImportSource,
) -> None:
    model = adapter.normalize(_openapi_32_with_query())
    assert model.format == "openapi-3.2"
    assert model.paradigm is ApiParadigm.REST

    query = next(op for op in model.operations() if op.http_method == "QUERY")
    assert query.key == "QUERY /pets/search"
    assert query.http_path == "/pets/search"

    purge = next(op for op in model.operations() if op.http_method == "PURGE")
    assert purge.key == "PURGE /pets"
    assert purge.http_path == "/pets"

    assert model.extras["tagHierarchy"]["pets"] == {
        "parent": "store",
        "summary": "Pet ops",
        "kind": "nav",
    }


def test_openapi_32_routes_to_publishable_project(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_openapi_32_with_query())
    decision = decide_import_routing(adapter, model)
    assert decision.publishable is True


def test_openapi_32_lints(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(_openapi_32_with_query())
    report = adapter.lint(model)
    assert isinstance(report, LintReport)
    assert report.score is not None
    assert report.grade is not None


def test_bundled_openapi_32_meta_schema_loads() -> None:
    meta = load_openapi_32_meta_schema()
    assert meta["$id"] == OPENAPI_32_META_SCHEMA_ID


def test_openapi_32_document_validates_against_meta_schema() -> None:
    assert validate_openapi_document(_openapi_32_with_query()) == []


def test_emit_openapi_32_stashes_non_oas31_methods() -> None:
    adapter = OpenApiImportSource()
    model = adapter.normalize(_openapi_32_with_query())
    result = OpenApiEmitter().emit(model)
    search_item = result.document["paths"]["/pets/search"]
    assert "query" not in search_item
    assert X_QUERY_OPERATION in search_item
    assert search_item[X_QUERY_OPERATION]["operationId"] == "searchPets"

    pets_item = result.document["paths"]["/pets"]
    assert X_ADDITIONAL_OPERATIONS in pets_item
    assert pets_item[X_ADDITIONAL_OPERATIONS]["PURGE"]["operationId"] == "purgePets"


def test_fidelity_preview_notes_openapi_32_to_31_conversion() -> None:
    adapter = OpenApiImportSource()
    model = adapter.normalize(_openapi_32_with_query())
    result = OpenApiEmitter().emit(model)
    report = analyze_fidelity(model, result)

    version_item = next(item for item in report.items if item.key == "source.openapi-version")
    assert version_item.coverage is Coverage.PARTIAL
    assert "3.2" in version_item.reason and "3.1" in version_item.reason

    assert any(loss.subject == "openapi-3.2-http-method" for loss in report.losses)


def test_openapi_31_fidelity_version_row_is_na(adapter: OpenApiImportSource) -> None:
    model = adapter.normalize(
        {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": {}}
    )
    report = analyze_fidelity(model, OpenApiEmitter().emit(model))
    version_item = next(item for item in report.items if item.key == "source.openapi-version")
    assert version_item.coverage is Coverage.NA


def test_openapi_31_normalization_unchanged(adapter: OpenApiImportSource) -> None:
    doc = {
        "openapi": "3.1.0",
        "info": {"title": "Pet Store", "version": "1.0.0"},
        "paths": {
            "/pets": {
                "get": {
                    "operationId": "listPets",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    model = adapter.normalize(doc)
    assert model.format == "openapi-3.1"
    assert len(list(model.operations())) == 1
    assert model.extras.get("tagHierarchy") is None
