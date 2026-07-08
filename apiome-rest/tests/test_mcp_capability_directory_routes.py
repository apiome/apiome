"""API tests for the capability directory (V2-MCP-35.4 / MCAT-21.4, #4663)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import mcp_capability_directory_response_from_rows

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _directory_row(**overrides):
    row = {
        "kind": "tool",
        "item_id": "item-1",
        "item_name": "geocode",
        "item_title": "Geocode",
        "description": "Convert an address to coordinates",
        "ordinal": 0,
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Geo",
        "endpoint_slug": "acme-geo",
        "endpoint_url": "https://mcp.acme.example/sse",
        "category": "geo",
        "visibility": "private",
        "current_version_id": "ver-1",
        "score": 90,
        "grade": "A",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_mcp_capability_directory_response_from_rows_projects_owner_links():
    wire = mcp_capability_directory_response_from_rows(
        rows=[_directory_row()],
        total=1,
        limit=50,
        offset=0,
    )
    assert wire.total == 1
    assert wire.count == 1
    item = wire.items[0]
    assert item.endpoint_id == "ep-1"
    assert item.endpoint_slug == "acme-geo"
    assert item.host == "mcp.acme.example"
    assert item.item_name == "geocode"


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_returns_items(mdb):
    mdb.list_mcp_capability_directory.return_value = ([_directory_row()], 1)
    r = client.get("/v1/mcp/acme/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["endpoint_slug"] == "acme-geo"
    mdb.list_mcp_capability_directory.assert_called_once()
    _, kwargs = mdb.list_mcp_capability_directory.call_args
    assert kwargs["name_pattern"] is None
    assert kwargs["limit"] == 50


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_passes_filters(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    r = client.get(
        "/v1/mcp/acme/capabilities",
        params={
            "name": "geo",
            "type": "tool",
            "endpoint_id": "ep-1",
            "host": "mcp.acme.example",
            "visibility": "private",
            "sort": "name",
            "limit": 10,
            "offset": 5,
        },
    )
    assert r.status_code == 200
    _, kwargs = mdb.list_mcp_capability_directory.call_args
    assert kwargs["name_pattern"] == "geo"
    assert kwargs["item_type"] == "tool"
    assert kwargs["endpoint_id"] == "ep-1"
    assert kwargs["host"] == "mcp.acme.example"
    assert kwargs["visibility"] == "private"
    assert kwargs["sort"] == "name"
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 5


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_scopes_by_token_tenant(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    client.get("/v1/mcp/other/capabilities")
    args, _ = mdb.list_mcp_capability_directory.call_args
    assert args[0] == "t1"


@patch("app.mcp_catalog_routes.db")
def test_list_capability_directory_empty_page(mdb):
    mdb.list_mcp_capability_directory.return_value = ([], 0)
    r = client.get("/v1/mcp/acme/capabilities", params={"name": "zzz"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_capability_directory_invalid_sort():
    r = client.get("/v1/mcp/acme/capabilities", params={"sort": "bogus"})
    assert r.status_code == 422
