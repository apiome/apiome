"""Tests for GET/POST /v1/versions/{tenant_slug}/{project_id}/version-branches."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_PROJECT_ID = "660e8400-e29b-41d4-a716-446655440010"
_USER_ID = "660e8400-e29b-41d4-a716-446655440001"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "jwt",
        "user_id": _USER_ID,
        "tenant_id": _TENANT_ID,
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_list_version_branches():
    rows = [
        {
            "id": "b1",
            "project_id": _PROJECT_ID,
            "name": "main",
            "tip_version_id": "v1",
            "tip_version_string": "1.0.0",
        }
    ]
    with patch("app.version_merge_routes.db") as m:
        m.get_project_by_id.return_value = {"id": _PROJECT_ID}
        m.list_version_branches_detailed_for_project.return_value = rows
        r = client.get(f"/v1/versions/acme/{_PROJECT_ID}/version-branches")
    assert r.status_code == 200
    assert r.json()[0]["name"] == "main"


def test_create_version_branch():
    created = {
        "id": "b2",
        "project_id": _PROJECT_ID,
        "name": "feature",
        "tip_version_id": "v2",
    }
    with patch("app.version_merge_routes.db") as m, patch(
        "app.version_merge_routes.enforce_permission"
    ), patch("app.version_merge_routes.get_authenticated_user_id", return_value=_USER_ID):
        m.create_version_branch_from_revision.return_value = {
            "success": True,
            "branch": created,
        }
        r = client.post(
            f"/v1/versions/acme/{_PROJECT_ID}/version-branches",
            json={"name": "feature", "fromVersionId": "v2"},
        )
    assert r.status_code == 200
    assert r.json()["name"] == "feature"
