"""API tests for MCP catalog duplicate detection (V2-MCP-36.1 / MCAT-22.1, #4664)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


def _candidate_row(**overrides):
    row = {
        "id": "ep-1",
        "tenant_id": "t1",
        "name": "Weather A",
        "slug": "weather-a",
        "endpoint_url": "https://mcp.acme.example/sse",
        "transport": "streamable_http",
        "visibility": "private",
        "published": False,
        "surface_fingerprint": None,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@patch("app.mcp_catalog_routes.db")
def test_duplicate_report_flags_exact_url_group(mdb):
    mdb.list_mcp_duplicate_candidates.return_value = [
        _candidate_row(id="ep-1", name="Weather A", slug="weather-a"),
        _candidate_row(
            id="ep-2",
            name="Weather B",
            slug="weather-b",
            endpoint_url="https://mcp.acme.example/sse/",
        ),
    ]
    mdb.list_published_mcp_duplicate_hints.return_value = []

    r = client.get("/v1/mcp/acme/data-quality/duplicates")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["advisory"] is True
    assert body["group_count"] == 1
    assert body["groups"][0]["kind"] == "exact_url"
    assert body["flagged_endpoint_count"] == 2
    mdb.list_mcp_duplicate_candidates.assert_called_once_with("t1")


@patch("app.mcp_catalog_routes.db")
def test_duplicate_report_empty_when_no_duplicates(mdb):
    mdb.list_mcp_duplicate_candidates.return_value = [
        _candidate_row(
            id="ep-1",
            endpoint_url="https://alpha.example/mcp",
            surface_fingerprint="fp-alpha",
        ),
        _candidate_row(
            id="ep-2",
            name="Beta",
            slug="beta",
            endpoint_url="https://beta.example/mcp",
            surface_fingerprint="fp-beta",
        ),
    ]
    mdb.list_published_mcp_duplicate_hints.return_value = []

    r = client.get("/v1/mcp/acme/data-quality/duplicates")
    assert r.status_code == 200
    body = r.json()
    assert body["group_count"] == 0
    assert body["groups"] == []


@patch("app.mcp_catalog_routes.db")
def test_duplicate_report_includes_cross_tenant_hints(mdb):
    mdb.list_mcp_duplicate_candidates.return_value = [
        _candidate_row(id="ep-1", published=True),
    ]
    mdb.list_published_mcp_duplicate_hints.return_value = [
        {
            "id": "ep-9",
            "tenant_id": "t2",
            "tenant_slug": "other",
            "name": "Foreign",
            "slug": "foreign",
            "endpoint_url": "https://mcp.acme.example/sse/",
            "transport": "streamable_http",
            "surface_fingerprint": None,
        }
    ]

    r = client.get("/v1/mcp/acme/data-quality/duplicates")
    assert r.status_code == 200
    hints = r.json()["cross_tenant_hints"]
    assert len(hints) == 1
    assert hints[0]["foreign_tenant_slug"] == "other"
    assert hints[0]["local_endpoint_ids"] == ["ep-1"]


@patch("app.mcp_catalog_routes.db")
def test_duplicate_report_scopes_by_token_tenant(mdb):
    mdb.list_mcp_duplicate_candidates.return_value = []
    mdb.list_published_mcp_duplicate_hints.return_value = []
    client.get("/v1/mcp/acme/data-quality/duplicates")
    mdb.list_mcp_duplicate_candidates.assert_called_once_with("t1")
    mdb.list_published_mcp_duplicate_hints.assert_called_once_with("t1")
