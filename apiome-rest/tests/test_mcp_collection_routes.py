"""API tests for MCP catalog collections (V2-MCP-36.4 / MCAT-22.4, #4667)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_API_KEY_NO_USER = {"tenant_id": "t1", "auth_method": "api_key"}

_COLL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_EP = "11111111-2222-3333-4444-555555555555"
_NOW = datetime(2026, 7, 7, tzinfo=timezone.utc)

_ROW = {
    "id": _COLL,
    "tenant_id": "t1",
    "name": "Geo tools",
    "slug": "geo-tools",
    "description": "Approved geo MCP servers",
    "is_published": False,
    "member_count": 1,
    "created_by": "user-1",
    "created_at": _NOW,
    "updated_at": _NOW,
}

_MEMBER = {
    "collection_id": _COLL,
    "tenant_id": "t1",
    "endpoint_id": _EP,
    "position": 0,
    "added_at": _NOW,
    "name": "Weather",
    "slug": "weather",
    "host": "mcp.example.com",
    "grade": "B",
    "visibility": "public",
    "published": True,
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.clear()


def test_list_collections():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.list_mcp_collections.return_value = [_ROW]
        res = client.get("/v1/mcp/demo/collections")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["collections"][0]["slug"] == "geo-tools"
    mdb.list_mcp_collections.assert_called_once_with("t1")


def test_create_collection():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.create_mcp_collection.return_value = _ROW
        mdb.list_mcp_collection_members.return_value = [_MEMBER]
        res = client.post(
            "/v1/mcp/demo/collections",
            json={
                "name": "Geo tools",
                "endpointIds": [_EP],
            },
        )
    assert res.status_code == 200
    kwargs = mdb.create_mcp_collection.call_args.kwargs
    assert kwargs["name"] == "Geo tools"
    assert kwargs["endpoint_ids"] == [_EP]


def test_get_collection_with_members():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.get_mcp_collection.return_value = _ROW
        mdb.list_mcp_collection_members.return_value = [_MEMBER]
        res = client.get(f"/v1/mcp/demo/collections/{_COLL}")
    assert res.status_code == 200
    body = res.json()
    assert body["members"][0]["endpointId"] == _EP


def test_update_collection_publish():
    with patch("app.mcp_collection_routes.db") as mdb:
        published = {**_ROW, "is_published": True}
        mdb.update_mcp_collection.return_value = published
        mdb.list_mcp_collection_members.return_value = [_MEMBER]
        res = client.patch(
            f"/v1/mcp/demo/collections/{_COLL}",
            json={"isPublished": True},
        )
    assert res.status_code == 200
    assert res.json()["isPublished"] is True
    mdb.update_mcp_collection.assert_called_once()


def test_delete_collection():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.delete_mcp_collection.return_value = True
        res = client.delete(f"/v1/mcp/demo/collections/{_COLL}")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_add_collection_members():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.add_mcp_collection_members.return_value = [_MEMBER]
        mdb.get_mcp_collection.return_value = _ROW
        res = client.post(
            f"/v1/mcp/demo/collections/{_COLL}/members",
            json={"endpointIds": [_EP]},
        )
    assert res.status_code == 200
    mdb.add_mcp_collection_members.assert_called_once_with("t1", _COLL, [_EP])


def test_remove_collection_member():
    with patch("app.mcp_collection_routes.db") as mdb:
        mdb.remove_mcp_collection_member.return_value = True
        res = client.delete(
            f"/v1/mcp/demo/collections/{_COLL}/members/{_EP}",
        )
    assert res.status_code == 200
    mdb.remove_mcp_collection_member.assert_called_once_with("t1", _COLL, _EP)


def test_requires_user_for_collections():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    res = client.post(
        "/v1/mcp/demo/collections",
        json={"name": "Geo tools"},
    )
    assert res.status_code == 403
