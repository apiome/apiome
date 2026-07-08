"""API tests for saved catalog searches (V2-MCP-35.3 / MCAT-21.3, #4662)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_API_KEY_NO_USER = {"tenant_id": "t1", "auth_method": "api_key"}

_ROW = {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "tenant_id": "t1",
    "user_id": "user-1",
    "name": "Destructive ungraded",
    "filters": {
        "hosts": [],
        "grades": ["ungraded"],
        "transports": [],
        "visibilities": [],
        "auths": [],
        "categories": [],
        "safeties": ["has_destructive"],
        "complexities": [],
        "protocols": [],
        "healths": [],
    },
    "query": "weather",
    "sort": "grade",
    "is_pinned": True,
    "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.clear()


def _bundle():
    return {
        "endpoints": [],
        "total": 0,
        "grade_rows": [],
        "transport_rows": [],
        "category_rows": [],
        "safety_counts": {"has_destructive": 0, "read_only_only": 0},
        "complexity_rows": [],
        "protocol_rows": [],
        "health_rows": [],
    }


def test_list_saved_searches():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.list_mcp_saved_searches.return_value = [_ROW]
        res = client.get("/v1/mcp/acme/saved-searches")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["searches"]) == 1
    assert body["searches"][0]["name"] == "Destructive ungraded"
    assert body["searches"][0]["isPinned"] is True
    mdb.list_mcp_saved_searches.assert_called_once_with("t1", "user-1")


def test_create_saved_search():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.create_mcp_saved_search.return_value = _ROW
        res = client.post(
            "/v1/mcp/acme/saved-searches",
            json={
                "name": "Destructive ungraded",
                "filters": {"grades": ["ungraded"], "safeties": ["has_destructive"]},
                "query": "weather",
                "isPinned": True,
            },
        )
    assert res.status_code == 200
    kwargs = mdb.create_mcp_saved_search.call_args.kwargs
    assert kwargs["name"] == "Destructive ungraded"
    assert kwargs["filters"]["grades"] == ["ungraded"]
    assert kwargs["is_pinned"] is True


def test_create_duplicate_name_returns_409():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.create_mcp_saved_search.side_effect = pg_errors.UniqueViolation()
        res = client.post(
            "/v1/mcp/acme/saved-searches",
            json={"name": "Dup", "filters": {}},
        )
    assert res.status_code == 409


def test_delete_saved_search():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.delete_mcp_saved_search.return_value = True
        res = client.delete(
            "/v1/mcp/acme/saved-searches/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        )
    assert res.status_code == 200
    assert res.json()["success"] is True
    mdb.delete_mcp_saved_search.assert_called_once_with(
        "t1", "user-1", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    )


def test_delete_missing_returns_404():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.delete_mcp_saved_search.return_value = False
        res = client.delete(
            "/v1/mcp/acme/saved-searches/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        )
    assert res.status_code == 404


def test_run_saved_search_dispatches_facets():
    with patch("app.mcp_saved_search_routes.db") as mdb:
        mdb.get_mcp_saved_search.return_value = _ROW
        mdb.search_mcp_catalog_faceted.return_value = _bundle()
        res = client.get(
            "/v1/mcp/acme/saved-searches/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/run"
        )
    assert res.status_code == 200
    body = res.json()
    assert body["search"]["name"] == "Destructive ungraded"
    assert body["result"]["total"] == 0
    kwargs = mdb.search_mcp_catalog_faceted.call_args.kwargs
    assert kwargs["grades"] == ["ungraded"]
    assert kwargs["safety"] == ["has_destructive"]


def test_requires_user_for_saved_searches():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_NO_USER
    with patch("app.auth.db") as mdb:
        mdb.get_fallback_creator_user_id_for_tenant.return_value = None
        res = client.get("/v1/mcp/acme/saved-searches")
    assert res.status_code == 403
