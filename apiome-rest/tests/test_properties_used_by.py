"""``GET /v1/properties/{tenant}/{project}`` reports where each property is used (CLI 6.1, #3223).

The list route asks the database for usage (``with_usage=True``) and returns ``used_by`` (class
names) and ``used_by_count``; the single-property routes leave both ``null``. The SQL was checked
against a live database for the PR.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}


def _row(name, used_by=None, count=None):
    row = {"id": f"id-{name}", "project_id": "p1", "name": name, "description": None, "data": {"type": "string"}}
    if used_by is not None:
        row.update(used_by=used_by, used_by_count=count)
    return row


def test_the_list_returns_usage() -> None:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.properties_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_properties_for_project.return_value = [
                _row("amount", ["Charge", "Refund"], 3),
                _row("legacy", [], 0),
            ]
            response = client.get("/v1/properties/acme/p1")
            mock_db.get_properties_for_project.assert_called_once_with("p1", with_usage=True)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200, response.text
    assert [(p["name"], p["used_by"], p["used_by_count"]) for p in response.json()] == [
        ("amount", ["Charge", "Refund"], 3),
        ("legacy", [], 0),
    ]


def test_a_single_property_leaves_usage_null() -> None:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.properties_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_property_by_id.return_value = _row("amount")
            response = client.get("/v1/properties/acme/p1/id-amount")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200, response.text
    assert response.json()["used_by"] is None and response.json()["used_by_count"] is None
