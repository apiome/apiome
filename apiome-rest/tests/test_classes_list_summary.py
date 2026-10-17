"""``GET /v1/classes/{tenant}?version_id=`` carries ``property_count`` and ``tags`` (CLI 7.1, #3229).

The version-filtered list asks the database for the summary (``with_summary=True``); the unfiltered
list does not. The SQL was checked against a scratch Postgres 16 for the PR.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_TAG = {"id": "t1", "project_id": "p1", "name": "financial", "color": "green", "description": None}


def _row(name, **extra):
    return {"id": f"id-{name}", "version_id": "v1", "name": name, "description": None, "schema": {}, **extra}


def _get(path):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.classes_routes.db") as mock_db:
            mock_db.get_version_for_tenant.return_value = {"id": "v1"}
            mock_db.get_versions_for_tenant.return_value = [{"id": "v1"}]
            mock_db.get_classes_for_tenant_version.return_value = [
                _row("Charge", property_count=11, tags=[_TAG]),
                _row("Refund", property_count=0, tags=[]),
            ]
            return client.get(path), mock_db
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_the_version_list_returns_counts_and_tags() -> None:
    response, mock_db = _get("/v1/classes/acme?version_id=v1")
    assert response.status_code == 200, response.text
    mock_db.get_classes_for_tenant_version.assert_called_once_with("tenant-1", "v1", with_summary=True)
    body = response.json()
    assert [(c["name"], c["property_count"], [t["name"] for t in c["tags"]]) for c in body] == [
        ("Charge", 11, ["financial"]),
        ("Refund", 0, []),
    ]


def test_the_unfiltered_list_does_not_ask_for_the_summary() -> None:
    response, mock_db = _get("/v1/classes/acme")
    assert response.status_code == 200, response.text
    mock_db.get_classes_for_tenant_version.assert_called_once_with("tenant-1", "v1")
