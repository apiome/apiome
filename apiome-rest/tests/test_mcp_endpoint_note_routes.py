"""API tests for cataloger notes on MCP endpoints (V2-MCP-36.3 / MCAT-22.3, #4666)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_API_KEY_NO_USER = {"tenant_id": "t1", "auth_method": "api_key"}

_EP = "11111111-1111-1111-1111-111111111111"
_NOTE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

_ENDPOINT_ROW = {"id": _EP, "tenant_id": "t1", "name": "Weather"}

_ROW = {
    "id": _NOTE,
    "tenant_id": "t1",
    "endpoint_id": _EP,
    "body": "Use staging instead of prod for QA.",
    "created_by": "user-1",
    "updated_by": None,
    "created_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 7, 7, tzinfo=timezone.utc),
    "created_by_name": "Ada",
    "created_by_email": "ada@example.com",
    "updated_by_name": None,
    "updated_by_email": None,
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.clear()


def test_list_endpoint_notes():
    with patch("app.mcp_endpoint_note_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_endpoint_notes.return_value = [_ROW]
        res = client.get(f"/v1/mcp/demo/endpoints/{_EP}/notes")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["notes"]) == 1
    assert body["notes"][0]["body"] == _ROW["body"]
    mdb.list_mcp_endpoint_notes.assert_called_once_with("t1", _EP)


def test_create_endpoint_note():
    with patch("app.mcp_endpoint_note_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.create_mcp_endpoint_note.return_value = _ROW
        res = client.post(
            f"/v1/mcp/demo/endpoints/{_EP}/notes",
            json={"body": "New cataloger note"},
        )
    assert res.status_code == 200
    assert res.json()["body"] == _ROW["body"]
    kwargs = mdb.create_mcp_endpoint_note.call_args.kwargs
    assert kwargs["body"] == "New cataloger note"


def test_create_requires_user():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    with patch("app.mcp_endpoint_note_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        res = client.post(
            f"/v1/mcp/demo/endpoints/{_EP}/notes",
            json={"body": "note"},
        )
    assert res.status_code == 403


def test_delete_endpoint_note():
    with patch("app.mcp_endpoint_note_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.delete_mcp_endpoint_note.return_value = True
        res = client.delete(f"/v1/mcp/demo/endpoints/{_EP}/notes/{_NOTE}")
    assert res.status_code == 200
    assert res.json()["success"] is True
