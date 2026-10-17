"""``GET /v1/version-tags/{tenant}/{project}`` carries the creator's email (CLI 11.4, #3263).

``apiome tags list`` shows who created each tag. The list query joins ``apiome.users`` for
``created_by_email``; a tag whose creator is unknown (or deleted) returns ``null``. Checked against a
live database for the PR; here the route passes the field through.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}


def test_the_list_returns_created_by_email() -> None:
    rows = [
        {"id": "t1", "project_id": "p1", "version_id": "v1", "name": "stable", "created_by": "u1",
         "created_by_email": "kenji@example.com", "target_version_string": "2.1.0"},
        {"id": "t2", "project_id": "p1", "version_id": "v1", "name": "orphan", "created_by": None,
         "created_by_email": None, "target_version_string": "2.1.0"},
    ]
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.version_tags_routes.db") as mock_db, patch("app.version_tags_routes.enforce_permission"):
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.list_version_tags_for_project.return_value = rows
            response = client.get("/v1/version-tags/acme/p1")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200, response.text
    assert [(t["name"], t["created_by_email"]) for t in response.json()] == [
        ("stable", "kenji@example.com"),
        ("orphan", None),
    ]
