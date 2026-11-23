"""The per-tenant MCP catalog insight cache and the route that reads through it (DBP-1.17, #7200)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_catalog_insight_cache as cache
from app.auth import validate_authentication
from app.config import settings
from app.main import app

client = TestClient(app)


def _insight(endpoints: int = 2) -> dict:
    """A row as ``Database.get_mcp_catalog_insight`` returns it."""
    return {
        "endpoint_count": endpoints,
        "published_count": 1,
        "public_count": 1,
        "private_count": endpoints - 1,
        "discovered_count": endpoints,
        "tool_count": 5,
        "resource_count": 1,
        "resource_template_count": 0,
        "prompt_count": 0,
        "avg_score": 80,
        "scored_count": endpoints,
        "grade_distribution": {"B": endpoints},
        "category_rows": [{"label": "weather", "count": endpoints}],
        "transport_rows": [{"label": "sse", "count": endpoints}],
        "protocol_rows": [],
        "discovery_rows": [{"label": "changed", "count": endpoints}],
        "change_leader_rows": [],
        "top_capability_rows": [],
        "tool_count_rows": [{"tool_count": 5}] + [{"tool_count": 0}] * (endpoints - 1),
    }


@pytest.fixture
def as_tenant():
    """Authenticate requests as a tenant; yields a function that switches the tenant."""

    def use(tenant_id: str) -> None:
        app.dependency_overrides[validate_authentication] = lambda: {
            "tenant_id": tenant_id,
            "tenant_slug": "acme",
            "user_id": "u1",
        }

    use("t1")
    yield use
    app.dependency_overrides.pop(validate_authentication, None)


# ───────────────────────────── the cache ─────────────────────────────


def test_an_insight_is_read_once_per_tenant_and_interval():
    calls = []

    def load():
        calls.append(1)
        return _insight()

    assert cache.cached_insight("t1", load) == _insight()
    assert cache.cached_insight("t1", load) == _insight()
    assert len(calls) == 1 and cache.cache_size() == 1


def test_tenants_never_share_an_insight():
    assert cache.cached_insight("t1", lambda: _insight(2))["endpoint_count"] == 2
    assert cache.cached_insight("t2", lambda: _insight(7))["endpoint_count"] == 7
    assert cache.cached_insight("t1", lambda: _insight(99))["endpoint_count"] == 2


def test_a_caller_cannot_change_what_the_next_caller_gets():
    first = cache.cached_insight("t1", _insight)
    first["category_rows"].append({"label": "injected", "count": 1})
    first["grade_distribution"]["Z"] = 9
    second = cache.cached_insight("t1", _insight)
    assert second == _insight()
    second["tool_count_rows"].clear()
    assert cache.cached_insight("t1", _insight) == _insight()


def test_a_failed_read_is_not_stored():
    def boom():
        raise RuntimeError("database is down")

    with pytest.raises(RuntimeError):
        cache.cached_insight("t1", boom)
    assert cache.cache_size() == 0
    assert cache.cached_insight("t1", _insight) == _insight()


@pytest.mark.parametrize(
    "configured,expected", [(30, 30.0), (0, 0.0), (-1, 0.0), (10_000, 300.0), ("soon", 0.0), (None, 0.0)]
)
def test_the_interval_is_clamped_to_zero_through_five_minutes(monkeypatch, configured, expected):
    monkeypatch.setattr(settings, "mcp_catalog_insight_cache_ttl_seconds", configured)
    assert cache.ttl_seconds() == expected


def test_the_default_interval_is_thirty_seconds():
    assert settings.mcp_catalog_insight_cache_ttl_seconds == 30.0


def test_an_interval_of_zero_turns_the_cache_off(monkeypatch):
    monkeypatch.setattr(settings, "mcp_catalog_insight_cache_ttl_seconds", 0)
    calls = []
    for _ in range(3):
        cache.cached_insight("t1", lambda: calls.append(1) or _insight())
    assert len(calls) == 3 and cache.cache_size() == 0


def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "mcp_catalog_insight_cache_max_entries", 3)
    for i in range(10):
        cache.cached_insight(f"t{i}", _insight)
    assert cache.cache_size() <= 3


# ───────────────────────────── the route ─────────────────────────────


def test_a_repeated_dashboard_load_reads_the_catalog_once(as_tenant):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_catalog_insight.return_value = _insight()
        first = client.get("/v1/mcp/acme/insight/catalog")
        second = client.get("/v1/mcp/acme/insight/catalog")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["endpoint_count"] == 2
    mdb.get_mcp_catalog_insight.assert_called_once_with("t1")


def test_the_cache_key_is_the_token_tenant_not_the_url_slug(as_tenant):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_catalog_insight.side_effect = lambda tenant_id: _insight(2 if tenant_id == "t1" else 9)
        mine = client.get("/v1/mcp/acme/insight/catalog").json()
        as_tenant("t2")
        # Same URL, another tenant's token: its own catalog, never the cached one.
        theirs = client.get("/v1/mcp/acme/insight/catalog").json()
    assert mine["endpoint_count"] == 2 and theirs["endpoint_count"] == 9
    assert mdb.get_mcp_catalog_insight.call_count == 2


def test_with_the_cache_off_every_load_reads_the_catalog(as_tenant, monkeypatch):
    monkeypatch.setattr(settings, "mcp_catalog_insight_cache_ttl_seconds", 0)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_catalog_insight.return_value = _insight()
        client.get("/v1/mcp/acme/insight/catalog")
        client.get("/v1/mcp/acme/insight/catalog")
    assert mdb.get_mcp_catalog_insight.call_count == 2
