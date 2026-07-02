"""API + projection tests for MCP capability search (V2-MCP-23.2 / MCAT-9.2, #3692).

Covers the tenant-scoped ``GET /v1/mcp/{tenant_slug}/search`` route — free-text search over a
tenant's current capability surface (or its endpoints, ``scope=endpoint``) with composable
host/category/grade/visibility filters — plus the pure projection helper
(:func:`mcp_search_hit_from_row`) that shapes both kinds of hit. The DB layer's SQL is exercised
against a live database elsewhere; here ``app.mcp_catalog_routes.db`` is mocked so the suite stays
DB-free, asserting that the route dispatches to the right query with the right (token-scoped)
arguments and projects the rows it gets back.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import mcp_search_hit_from_row

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _capability_row(**overrides):
    """A :meth:`Database.search_mcp_capability_items` row with sane defaults, overridable per test."""
    row = {
        "kind": "tool",
        "item_id": "item-1",
        "item_name": "get_forecast",
        "item_title": "Get Forecast",
        "description": "Return the weather forecast for a location",
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Weather",
        "endpoint_slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "category": "weather",
        "visibility": "private",
        "current_version_id": "ver-1",
        "last_discovered_at": None,
        "score": 87,
        "grade": "B",
        "relevance": 0.42,
    }
    row.update(overrides)
    return row


def _endpoint_row(**overrides):
    """A :meth:`Database.search_mcp_endpoints_fts` row (``kind='endpoint'``, item_* NULL)."""
    row = {
        "kind": "endpoint",
        "item_id": None,
        "item_name": None,
        "item_title": None,
        "description": "Weather tools for forecasts and alerts",
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Weather",
        "endpoint_slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "category": "weather",
        "visibility": "public",
        "current_version_id": "ver-1",
        "last_discovered_at": None,
        "score": 87,
        "grade": "B",
        "relevance": 0.31,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Row projection helper
# ===========================================================================


def test_capability_hit_projection_derives_host_and_redacts():
    out = mcp_search_hit_from_row(
        _capability_row(endpoint_url="https://user:secret@mcp.acme.example/sse")
    )
    assert out.kind == "tool"
    assert out.item_id == "item-1"
    assert out.item_name == "get_forecast"
    assert out.item_title == "Get Forecast"
    assert out.description.startswith("Return the weather")
    # Host derived; userinfo redacted out of the wire URL but host kept.
    assert out.host == "mcp.acme.example"
    assert "secret" not in out.endpoint_url
    assert out.score == 87 and out.grade == "B"
    assert out.relevance == pytest.approx(0.42)


def test_endpoint_hit_projection_has_null_item_fields():
    out = mcp_search_hit_from_row(_endpoint_row())
    assert out.kind == "endpoint"
    assert out.item_id is None
    assert out.item_name is None
    assert out.item_title is None
    # An endpoint hit's description is the endpoint's own description.
    assert out.description.startswith("Weather tools")
    assert out.endpoint_name == "Acme Weather"
    assert out.visibility == "public"


def test_hit_projection_unscored_null_relevance():
    out = mcp_search_hit_from_row(
        _capability_row(score=None, grade=None, relevance=None, current_version_id=None)
    )
    assert out.score is None
    assert out.grade is None
    assert out.relevance == 0.0
    assert out.current_version_id is None


# ===========================================================================
# Route — dispatch & scoping
# ===========================================================================


def test_search_default_scope_searches_all_capability_kinds():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = [_capability_row()]
        r = client.get("/v1/mcp/acme/search", params={"q": "forecast"})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["query"] == "forecast"
    assert body["scope"] is None
    assert body["count"] == 1
    assert body["hits"][0]["kind"] == "tool"
    # No scope → item_type is None (search every capability kind), endpoint search untouched.
    _, kwargs = mdb.search_mcp_capability_items.call_args
    assert kwargs["item_type"] is None
    mdb.search_mcp_endpoints_fts.assert_not_called()


def test_search_scoped_to_token_tenant_not_url_slug():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get("/v1/mcp/some-other-slug/search", params={"q": "forecast"})
    args, _ = mdb.search_mcp_capability_items.call_args
    # First positional arg is the token tenant_id, never the URL slug.
    assert args[0] == "t1"


@pytest.mark.parametrize("scope", ["tool", "resource", "resource_template", "prompt"])
def test_search_capability_scope_passes_item_type(scope):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get("/v1/mcp/acme/search", params={"q": "x", "scope": scope})
    _, kwargs = mdb.search_mcp_capability_items.call_args
    assert kwargs["item_type"] == scope


def test_search_endpoint_scope_uses_endpoint_query():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_endpoints_fts.return_value = [_endpoint_row()]
        r = client.get("/v1/mcp/acme/search", params={"q": "weather", "scope": "endpoint"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "endpoint"
    assert body["hits"][0]["kind"] == "endpoint"
    mdb.search_mcp_endpoints_fts.assert_called_once()
    mdb.search_mcp_capability_items.assert_not_called()


def test_search_filters_compose_and_pass_through():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get(
            "/v1/mcp/acme/search",
            params={
                "q": "forecast",
                "host": "mcp.acme.example",
                "category": "weather",
                "grade": "B",
                "visibility": "private",
                "limit": 10,
                "offset": 5,
            },
        )
    _, kwargs = mdb.search_mcp_capability_items.call_args
    assert kwargs["host"] == "mcp.acme.example"
    assert kwargs["category"] == "weather"
    assert kwargs["grade"] == "B"
    assert kwargs["visibility"] == "private"
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 5


def test_search_blank_filters_become_none():
    """Whitespace-only host/category/grade are treated as absent, not as empty-string predicates."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.search_mcp_capability_items.return_value = []
        client.get(
            "/v1/mcp/acme/search",
            params={"q": "forecast", "host": "  ", "category": "", "grade": "  "},
        )
    _, kwargs = mdb.search_mcp_capability_items.call_args
    assert kwargs["host"] is None
    assert kwargs["category"] is None
    assert kwargs["grade"] is None


def test_search_whitespace_query_returns_empty_without_db():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get("/v1/mcp/acme/search", params={"q": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["hits"] == []
    mdb.search_mcp_capability_items.assert_not_called()
    mdb.search_mcp_endpoints_fts.assert_not_called()


# ===========================================================================
# Route — validation & auth
# ===========================================================================


def test_search_requires_query_param():
    r = client.get("/v1/mcp/acme/search")
    assert r.status_code == 422


def test_search_rejects_unknown_scope():
    r = client.get("/v1/mcp/acme/search", params={"q": "x", "scope": "widget"})
    assert r.status_code == 422


def test_search_rejects_unknown_visibility():
    r = client.get("/v1/mcp/acme/search", params={"q": "x", "visibility": "protected"})
    assert r.status_code == 422


@pytest.mark.parametrize("params", [{"q": "x", "limit": 0}, {"q": "x", "limit": 201}, {"q": "x", "offset": -1}])
def test_search_rejects_out_of_range_pagination(params):
    r = client.get("/v1/mcp/acme/search", params=params)
    assert r.status_code == 422


def test_search_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/mcp/acme/search", params={"q": "x"})
    assert r.status_code == 401
