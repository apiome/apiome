"""``GET /v1/properties/{tenant}/{project}/{id}`` lists the class attributes that use it (CLI 6.2, #3224).

The single-property route asks the database for ``usage`` (``class_name``, ``attribute_name``,
``required``); the list route does not. The SQL was checked against a live database for the PR.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}


def _row(name):
    return {"id": f"id-{name}", "project_id": "p1", "name": name, "description": None, "data": {"type": "number"}}


def _get(path, *, prop=None, usage=None):
    """Call ``path`` with the database mocked; return the response and the mock."""
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.properties_routes.db") as mock_db:
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.get_property_by_id.return_value = prop
            mock_db.get_properties_for_project.return_value = [_row("amount")]
            mock_db.get_property_usage.return_value = usage or []
            return client.get(path), mock_db
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_a_single_property_returns_its_usage() -> None:
    usage = [
        {"class_name": "Charge", "attribute_name": "amount", "required": True},
        {"class_name": "Refund", "attribute_name": "refund_amount", "required": False},
    ]
    response, mock_db = _get("/v1/properties/acme/p1/id-amount", prop=_row("amount"), usage=usage)
    assert response.status_code == 200, response.text
    mock_db.get_property_usage.assert_called_once_with("id-amount")
    assert response.json()["usage"] == usage


def test_an_unused_property_returns_an_empty_usage_list() -> None:
    response, _ = _get("/v1/properties/acme/p1/id-amount", prop=_row("amount"))
    assert response.status_code == 200, response.text
    assert response.json()["usage"] == []


def test_a_missing_property_is_404_and_skips_the_usage_query() -> None:
    response, mock_db = _get("/v1/properties/acme/p1/nope", prop=None)
    assert response.status_code == 404
    mock_db.get_property_usage.assert_not_called()


def test_the_list_leaves_usage_null() -> None:
    response, mock_db = _get("/v1/properties/acme/p1")
    assert response.status_code == 200, response.text
    mock_db.get_property_usage.assert_not_called()
    assert response.json()[0]["usage"] is None
