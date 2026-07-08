"""API tests for MCP catalog freshness reporting (V2-MCP-36.2 / MCAT-22.2, #4665)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _candidate(**overrides):
    now = datetime.now(timezone.utc)
    row = {
        "id": "ep-1",
        "tenant_id": "t1",
        "name": "Weather",
        "slug": "weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "transport": "streamable_http",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "discovery_cadence_seconds": None,
        "last_discovered_at": now - timedelta(hours=4),
        "last_discovery_status": "unchanged",
        "consecutive_failures": 0,
        "next_discovery_after": None,
        "quarantined_at": None,
        "quarantine_reason": None,
        "current_version_id": "ver-1",
        "last_known_good_at": now - timedelta(hours=4),
    }
    row.update(overrides)
    return row


@patch("app.mcp_catalog_routes.db")
def test_freshness_report_flags_stale_endpoint(mdb):
    mdb.list_mcp_freshness_candidates.return_value = [_candidate()]
    with patch("app.mcp_catalog_routes.settings") as mock_settings:
        mock_settings.mcp_discovery_default_cadence_seconds = 3600
        r = client.get("/v1/mcp/acme/data-quality/freshness")
    assert r.status_code == 200
    body = r.json()
    assert body["flagged_endpoint_count"] == 1
    assert body["endpoints"][0]["freshness"] == "stale"
    assert body["endpoints"][0]["last_known_good_at"] is not None
    mdb.list_mcp_freshness_candidates.assert_called_once_with("t1")


@patch("app.mcp_catalog_routes.db")
def test_freshness_report_empty_when_all_healthy(mdb):
    now = datetime.now(timezone.utc)
    mdb.list_mcp_freshness_candidates.return_value = [
        _candidate(
            last_discovered_at=now - timedelta(minutes=10),
            last_known_good_at=now - timedelta(minutes=10),
        )
    ]
    with patch("app.mcp_catalog_routes.settings") as mock_settings:
        mock_settings.mcp_discovery_default_cadence_seconds = 3600
        r = client.get("/v1/mcp/acme/data-quality/freshness")
    assert r.status_code == 200
    assert r.json()["flagged_endpoint_count"] == 0
    assert r.json()["endpoints"] == []


@patch("app.mcp_catalog_routes.db")
def test_freshness_report_scopes_by_token_tenant(mdb):
    mdb.list_mcp_freshness_candidates.return_value = []
    with patch("app.mcp_catalog_routes.settings") as mock_settings:
        mock_settings.mcp_discovery_default_cadence_seconds = 3600
        client.get("/v1/mcp/acme/data-quality/freshness")
    mdb.list_mcp_freshness_candidates.assert_called_once_with("t1")
