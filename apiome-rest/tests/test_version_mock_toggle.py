"""Version mock toggle REST tests (#4422, SIM-2.1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

TENANT = "acme-corp"
PROJECT_ID = "proj-1"
VERSION_ID = "ver-1"
USER_ID = "user-1"
_AUTH = {"tenant_id": "t1", "user_id": USER_ID, "auth_method": "api_key"}


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield TestClient(app)
    app.dependency_overrides.clear()


def _version_row(*, published: bool = True, mock_enabled: bool = False) -> dict:
    return {
        "id": VERSION_ID,
        "project_id": PROJECT_ID,
        "creator_id": USER_ID,
        "version_id": "1.0.0",
        "description": "note",
        "change_log": None,
        "visibility": "public",
        "published": published,
        "published_at": "2026-01-01T00:00:00+00:00",
        "published_immutable": True,
        "mock_enabled": mock_enabled,
        "enabled": True,
        "parent_version_id": None,
        "merge_parent_version_id": None,
        "forked_from_revision_id": None,
        "upstream_project_id": None,
        "revision_locked": False,
        "metadata": None,
        "commit_author": None,
        "commit_message": None,
        "external_ref": None,
        "source_commit_sha": None,
        "source_committed_at": None,
        "fork_source_version_string": None,
        "fork_source_project_name": None,
        "upstream_project_name": None,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "creator_name": "Dev",
        "creator_email": "dev@example.com",
        "project_name": "Petstore",
        "project_slug": "petstore",
    }


def test_enable_mock_on_published_version(client: TestClient) -> None:
    row = _version_row(published=True, mock_enabled=True)
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row()), patch(
        "app.versions_routes.db.set_version_mock_enabled",
        return_value=row,
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock",
            json={"enabled": True},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mockEnabled"] is True
    assert body["mockBaseUrl"].endswith(f"/{TENANT}/petstore/1.0.0")


def test_enable_mock_rejects_unpublished(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row(published=False),
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock",
            json={"enabled": True},
        )
    assert resp.status_code == 400
    assert "published" in resp.json()["detail"].lower()


def test_disable_mock_persists(client: TestClient) -> None:
    row = _version_row(published=True, mock_enabled=False)
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row(mock_enabled=True)), patch(
        "app.versions_routes.db.set_version_mock_enabled",
        return_value=row,
    ), patch("app.versions_routes.enforce_permission"):
        resp = client.put(
            f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock",
            json={"enabled": False},
        )
    assert resp.status_code == 200
    assert resp.json()["mockEnabled"] is False
    assert resp.json().get("mockBaseUrl") is None
