"""A revision with no captured source answers a typed error, never a bare 422 — E1-6 (#6221).

Pins the ``source-not-captured`` / ``source-withheld`` codes from the conversion loader through
:func:`app.export_source.load_export_source`, the export routes' structured ``detail``, and the
job engine's ``SOURCE_LOAD_FAILED`` context — each carrying ``reimport: true`` so the UI can offer
**Re-import**.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_conversion import SOURCE_NOT_CAPTURED, SOURCE_WITHHELD
from app.export_job_engine import _source_error_context
from app.export_source import ExportSourceError, load_export_source
from app.main import app

client = TestClient(app)

REV = "11111111-1111-4111-8111-111111111111"


def _projection(format_metadata: dict) -> dict:
    return {
        "id": "artifact-1", "project_slug": "orders", "source_format": "graphql", "protocol": "graph",
        "format_metadata": format_metadata, "tool_versions": {}, "metadata": {},
    }


def _load(format_metadata: dict):
    with patch("app.export_source.db.get_version_source_projection", return_value=_projection(format_metadata)):
        return load_export_source("tenant-1", "artifact-1", REV)


@pytest.mark.parametrize(
    ("format_metadata", "code"),
    [
        ({"sourceLabel": "schema.graphql"}, SOURCE_NOT_CAPTURED),
        ({"sourceContent": None, "sourceWithheld": "secrets-detected"}, SOURCE_WITHHELD),
    ],
)
def test_a_revision_without_a_source_raises_a_typed_error(format_metadata, code):
    with pytest.raises(ExportSourceError) as excinfo:
        _load(format_metadata)
    exc = excinfo.value
    assert exc.status_code == 422 and exc.code == code
    assert exc.http_detail() == {
        "code": code,
        "message": str(exc),
        "artifactId": "artifact-1",
        "versionId": REV,
        "reimport": True,
    }


def test_an_untyped_failure_keeps_its_plain_message():
    exc = ExportSourceError("Artifact 'x' was not found.", status_code=404)
    assert exc.http_detail() == "Artifact 'x' was not found."
    assert _source_error_context(exc) == {"status_code": 404}


def test_the_job_context_carries_the_code_and_reimport():
    exc = ExportSourceError("no source", status_code=422, code=SOURCE_NOT_CAPTURED, artifact_id="a-1")
    assert _source_error_context(exc) == {
        "status_code": 422, "source_code": SOURCE_NOT_CAPTURED, "reimport": True, "artifact_id": "a-1",
    }


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/v1/export/acme/targets?artifact=artifact-1", None),
        ("post", "/v1/export/acme/preview", {"artifact": "artifact-1", "target": "openapi"}),
        ("post", "/v1/export/acme/verify", {"artifact": "artifact-1", "target": "openapi"}),
        ("post", "/v1/export/acme/document", {"artifact": "artifact-1", "target": "openapi"}),
    ],
)
def test_the_export_routes_answer_the_typed_detail(method, path, body):
    error = ExportSourceError(
        "This catalog item has no captured source material to convert.",
        status_code=422, code=SOURCE_NOT_CAPTURED, artifact_id="artifact-1", version_record_id=REV,
    )
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "tenant-1", "user_id": "u"}
    try:
        with patch("app.export_routes.load_export_source", side_effect=error):
            response = getattr(client, method)(path, **({"json": body} if body else {}))
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == SOURCE_NOT_CAPTURED and detail["reimport"] is True
    assert detail["artifactId"] == "artifact-1"
