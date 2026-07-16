"""Tests for POST /v1/diff/{tenant_slug}/classified (CTG-1.2 / #4468)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.classified_diff_routes import INLINE_SPEC_MAX_BYTES
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "tenant-1",
    "user_id": "user-1",
    "auth_method": "jwt",
}

_FAKE_PROJECT = {
    "id": "proj-1",
    "tenant_id": "tenant-1",
    "slug": "pets",
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

_BASE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}

_HEAD_REMOVED_PATH = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.1.0"},
    "paths": {
        "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
    },
}

_HEAD_ADDED_PATH_YAML = yaml.dump(
    {
        "openapi": "3.1.0",
        "info": {"title": "Pets", "version": "1.1.0"},
        "paths": {
            "/pets": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/pets/{id}": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/stores": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
    }
)


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture
def mock_auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_classified_diff_requires_auth():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(
        "/v1/diff/acme/classified",
        json={
            "base": {"project": "pets", "version": "1.0.0"},
            "head": {"project": "pets", "version": "1.1.0"},
        },
    )
    assert r.status_code == 401


def test_classified_diff_stored_vs_stored_breaking(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            side_effect=[_BASE_SPEC, _HEAD_REMOVED_PATH],
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.side_effect = lambda pid, ver, tid: (
            _FAKE_BASE_VER
            if ver == "1.0.0"
            else _FAKE_HEAD_VER
            if ver == "1.1.0"
            else None
        )
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"project": "pets", "version": "1.1.0"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["maxSeverity"] == "breaking"
    assert data["counts"]["breaking"] >= 1
    assert data["counts"]["total"] >= 1
    assert any(c["ruleId"] == "ctg.path_removed" for c in data["changes"])
    assert data["base"]["projectSlug"] == "pets"
    assert data["base"]["versionLabel"] == "1.0.0"
    assert data["head"]["source"] == "stored"
    assert data["head"]["versionLabel"] == "1.1.0"


def test_classified_diff_inline_vs_stored(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"inline": _HEAD_ADDED_PATH_YAML},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["head"]["source"] == "inline"
    assert data["head"]["projectId"] is None
    assert data["maxSeverity"] == "non-breaking"
    assert any(c["ruleId"] == "ctg.path_added" for c in data["changes"])
    assert data["counts"]["non-breaking"] >= 1


def test_classified_diff_inline_over_10mb_rejected(mock_auth):
    oversized = "x" * (INLINE_SPEC_MAX_BYTES + 1)
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        with patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ):
            r = client.post(
                "/v1/diff/acme/classified",
                json={
                    "base": {"project": "pets", "version": "1.0.0"},
                    "head": {"inline": oversized},
                },
                headers={"Authorization": "Bearer x"},
            )
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert str(INLINE_SPEC_MAX_BYTES) in detail
    assert "exceeds" in detail.lower()


def test_classified_diff_unknown_project_404(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = None
        mock_db.get_project_by_id.return_value = None
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "missing", "version": "1.0.0"},
                "head": {"project": "missing", "version": "1.1.0"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 404
    assert "Project not found" in r.json()["detail"]


def test_classified_diff_unknown_version_404(mock_auth):
    with patch("app.classified_diff_routes.db") as mock_db:
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = None
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "9.9.9"},
                "head": {"inline": _HEAD_ADDED_PATH_YAML},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 404
    assert "9.9.9" in r.json()["detail"]


def test_classified_diff_invalid_inline_400(mock_auth):
    with (
        patch("app.classified_diff_routes.db") as mock_db,
        patch(
            "app.classified_diff_routes.openapi_for_revision",
            return_value=_BASE_SPEC,
        ),
    ):
        mock_db.user_has_permission.return_value = True
        mock_db.get_project_by_slug.return_value = _FAKE_PROJECT
        mock_db.get_version_by_version_id.return_value = _FAKE_BASE_VER
        r = client.post(
            "/v1/diff/acme/classified",
            json={
                "base": {"project": "pets", "version": "1.0.0"},
                "head": {"inline": "not: valid: [yaml"},
            },
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 400
    assert "not valid" in r.json()["detail"].lower() or "yaml" in r.json()["detail"].lower()
