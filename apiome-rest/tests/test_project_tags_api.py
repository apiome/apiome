"""Tests for /v1/project-tags endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_PROJECT_ID = "660e8400-e29b-41d4-a716-446655440010"
_TAG_ID = "770e8400-e29b-41d4-a716-446655440020"
_CLASS_ID = "880e8400-e29b-41d4-a716-446655440030"
_VERSION_ID = "990e8400-e29b-41d4-a716-446655440040"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "jwt",
        "user_id": "660e8400-e29b-41d4-a716-446655440001",
        "tenant_id": _TENANT_ID,
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_list_project_tags():
    rows = [
        {
            "id": _TAG_ID,
            "project_id": _PROJECT_ID,
            "name": "core",
            "color": "primary",
            "description": None,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    ]
    with patch("app.project_tags_routes.db") as m:
        m.get_project_by_id.return_value = {"id": _PROJECT_ID}
        m.get_tags_for_project.return_value = rows
        r = client.get(f"/v1/project-tags/acme/{_PROJECT_ID}")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "core"


def test_create_project_tag():
    created = {
        "id": _TAG_ID,
        "project_id": _PROJECT_ID,
        "name": "new-tag",
        "color": "default",
        "description": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    with patch("app.project_tags_routes.db") as m, patch(
        "app.project_tags_routes.enforce_permission"
    ):
        m.get_project_by_id.return_value = {"id": _PROJECT_ID}
        m.create_tag.return_value = created
        r = client.post(
            f"/v1/project-tags/acme/{_PROJECT_ID}",
            json={"name": "new-tag"},
        )
    assert r.status_code == 200
    assert r.json()["name"] == "new-tag"


def test_assign_tag_to_class():
    assigned = {
        "id": "aa0e8400-e29b-41d4-a716-446655440050",
        "class_id": _CLASS_ID,
        "tag_id": _TAG_ID,
        "created_at": "2024-01-01T00:00:00Z",
    }
    with patch("app.project_tags_routes.db") as m, patch(
        "app.project_tags_routes.enforce_permission"
    ):
        m.get_class_by_id.return_value = {"id": _CLASS_ID, "version_id": _VERSION_ID}
        m.get_tag_by_id.return_value = {"id": _TAG_ID, "project_id": _PROJECT_ID}
        m.get_project_by_id.return_value = {"id": _PROJECT_ID}
        m.get_version_by_id.return_value = {"id": _VERSION_ID, "project_id": _PROJECT_ID}
        m.assign_tag_to_class.return_value = assigned
        r = client.post(
            f"/v1/project-tags/acme/classes/{_CLASS_ID}",
            json={"tag_id": _TAG_ID},
        )
    assert r.status_code == 200
    assert r.json()["tag_id"] == _TAG_ID
