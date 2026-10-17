"""``PATCH /v1/version-tags/{tenant}/{project}/{tag}`` can change a tag's message (CLI 11.6, #3265).

``apiome tags update --description`` needs it. Omitting ``message`` keeps the current one (the
database layer is not told about it at all); ``null`` or ``""`` clears it.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_AUTH = {"tenant_id": "tenant-1", "user_id": "user-1", "auth_method": "jwt"}
_ROW = {"id": "t1", "project_id": "p1", "version_id": "v2", "name": "stable", "message": "GA"}


def _patch(body):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    try:
        with patch("app.version_tags_routes.db") as mock_db, patch(
            "app.version_tags_routes.enforce_permission"
        ), patch("app.version_tags_routes.get_authenticated_user_id", return_value="user-1"):
            mock_db.get_project_by_id.return_value = {"id": "p1"}
            mock_db.is_user_tenant_admin.return_value = False
            mock_db.update_version_tag.return_value = _ROW
            response = client.patch("/v1/version-tags/acme/p1/t1", json=body)
            return response, mock_db.update_version_tag.call_args
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_a_move_without_message_leaves_it_alone() -> None:
    response, call = _patch({"version_id": "v2"})
    assert response.status_code == 200, response.text
    assert call.args[5] == "v2"
    assert "set_message" not in call.kwargs


def test_a_message_is_passed_through() -> None:
    response, call = _patch({"version_id": "v2", "message": "Promoted for GA"})
    assert response.status_code == 200
    assert call.kwargs == {"set_message": "Promoted for GA"}


def test_null_clears_the_message() -> None:
    _, call = _patch({"message": None})
    assert call.kwargs == {"set_message": None}


def test_a_message_alone_is_a_valid_update() -> None:
    response, call = _patch({"message": "note"})
    assert response.status_code == 200
    assert call.args[5] is None and call.kwargs == {"set_message": "note"}


def test_an_overlong_message_is_a_422() -> None:
    response, call = _patch({"message": "x" * 2001})
    assert response.status_code == 422
    assert call is None
