"""Tests for POST /v1/versions/{tenant}/{project}/compatibility."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.auth import validate_authentication

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "tenant-1",
    "user_id": "user-1",
    "auth_method": "jwt",
}

_FAKE_PROJECT = {
    "id": "proj-1",
    "tenant_id": "tenant-1",
    "slug": "myproj",
    "description": "d",
    "metadata": "{}",
}

_FAKE_BASE_VER = {
    "id": "base-rev",
    "project_id": "proj-1",
    "version_id": "1.0.0",
}

_FAKE_HEAD_VER = {
    "id": "head-rev",
    "project_id": "proj-1",
    "version_id": "1.1.0",
}

_FAKE_BASE_VER_DEPRECATED = {
    **_FAKE_BASE_VER,
    "metadata": {
        "deprecated": True,
        "deprecationMessage": "Use head instead",
        "successorRevisionId": "head-rev",
        "sunsetDate": "2026-12-01",
    },
}

_MIN_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "t", "version": "1"},
    "paths": {},
    "components": {"schemas": {"A": {"type": "object"}}},
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture
def mock_auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_compatibility_requires_auth():
    app.dependency_overrides.pop(validate_authentication, None)
    try:
        r = client.post(
            "/v1/versions/t/proj/compatibility",
            json={"baseRevisionId": "a", "headRevisionId": "b"},
        )
        assert r.status_code == 401
    finally:
        pass


def test_compatibility_reports_breaking(mock_auth):
    removed_spec = {
        **_MIN_SPEC,
        "components": {"schemas": {}},
    }
    with (
        patch("src.app.compatibility_routes.db") as mock_db,
        patch("src.app.compatibility_engine.db") as mock_engine_db,
        patch(
            "src.app.compatibility_engine.generate_openapi_spec",
            side_effect=[_MIN_SPEC, removed_spec],
        ),
    ):
        mock_db.get_version_by_id.side_effect = lambda vid, tid: (
            _FAKE_BASE_VER if vid == "base-rev" else _FAKE_HEAD_VER if vid == "head-rev" else None
        )
        mock_engine_db.get_project_by_id.return_value = _FAKE_PROJECT
        mock_engine_db.get_classes_for_version.return_value = []
        r = client.post(
            "/v1/versions/t/proj-1/compatibility",
            json={"baseRevisionId": "base-rev", "headRevisionId": "head-rev"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["overall"] == "breaking"
    assert any(f["rule"] == "schema_removed" for f in data["findings"])
    assert data["ruleHits"].get("schema_removed", 0) >= 1
    assert data["breakingChangeDocumentationIssueUrl"].endswith("/issues/746")
    assert len(data["reportFingerprint"]) == 64


def test_compatibility_409_when_policy(mock_auth):
    removed_spec = {
        **_MIN_SPEC,
        "components": {"schemas": {}},
    }
    with (
        patch("src.app.compatibility_routes.db") as mock_db,
        patch("src.app.compatibility_engine.db") as mock_engine_db,
        patch(
            "src.app.compatibility_engine.generate_openapi_spec",
            side_effect=[_MIN_SPEC, removed_spec],
        ),
    ):
        mock_db.get_version_by_id.side_effect = lambda vid, tid: (
            _FAKE_BASE_VER if vid == "base-rev" else _FAKE_HEAD_VER if vid == "head-rev" else None
        )
        mock_engine_db.get_project_by_id.return_value = _FAKE_PROJECT
        mock_engine_db.get_classes_for_version.return_value = []
        r = client.post(
            "/v1/versions/t/proj-1/compatibility",
            json={
                "baseRevisionId": "base-rev",
                "headRevisionId": "head-rev",
                "policy": {"http409WhenBreaking": True},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 409
    body = r.json()
    assert body["detail"]["code"] == "COMPATIBILITY_BREAKING"


def test_compatibility_deprecation_warnings(mock_auth):
    with (
        patch("src.app.compatibility_routes.db") as mock_db,
        patch("src.app.compatibility_engine.db") as mock_engine_db,
        patch(
            "src.app.compatibility_engine.generate_openapi_spec",
            side_effect=[_MIN_SPEC, _MIN_SPEC],
        ),
    ):
        mock_db.get_version_by_id.side_effect = lambda vid, tid: (
            _FAKE_BASE_VER_DEPRECATED
            if vid == "base-rev"
            else _FAKE_HEAD_VER
            if vid == "head-rev"
            else None
        )
        mock_engine_db.get_project_by_id.return_value = _FAKE_PROJECT
        mock_engine_db.get_classes_for_version.return_value = []
        r = client.post(
            "/v1/versions/t/proj-1/compatibility",
            json={"baseRevisionId": "base-rev", "headRevisionId": "head-rev"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    data = r.json()
    assert len(data["deprecationWarnings"]) >= 1
    assert data["deprecationWarnings"][0]["revisionId"] == "base-rev"
    assert "deprecatedRevisionBlocked" in data


def test_compatibility_409_deprecated_policy(mock_auth):
    with (
        patch("src.app.compatibility_routes.db") as mock_db,
        patch("src.app.compatibility_engine.db") as mock_engine_db,
        patch(
            "src.app.compatibility_engine.generate_openapi_spec",
            side_effect=[_MIN_SPEC, _MIN_SPEC],
        ),
    ):
        mock_db.get_version_by_id.side_effect = lambda vid, tid: (
            _FAKE_BASE_VER_DEPRECATED
            if vid == "base-rev"
            else _FAKE_HEAD_VER
            if vid == "head-rev"
            else None
        )
        mock_engine_db.get_project_by_id.return_value = _FAKE_PROJECT
        mock_engine_db.get_classes_for_version.return_value = []
        r = client.post(
            "/v1/versions/t/proj-1/compatibility",
            json={
                "baseRevisionId": "base-rev",
                "headRevisionId": "head-rev",
                "policy": {"http409WhenDeprecatedRevision": True},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "DEPRECATED_REVISION"
