"""Tests for MCP endpoint health / uptime monitoring's read side (V2-MCP-27.3 / MCAT-13.3, #3713).

All DB-free, three layers:

* **Summary** — :func:`app.mcp_health.summarize_health_checks` folds probe rows into the status the
  badge shows (``up`` / ``degraded`` / ``down`` / ``unknown``), the uptime percentage and the
  latency percentiles; :func:`format_uptime_pct` never rounds a gap up to ``100%``.
* **Badge** — the ``uptime`` metric of the public SVG badge reflects the recent status, and the route
  reads the last day of probes only for that metric.
* **REST** — ``GET /v1/mcp/{tenant}/endpoints/{id}/uptime`` is tenant-scoped, summarizes the whole
  window, caps the listed probes at ``limit`` and validates its query.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_badge import BADGE_METRICS, METRIC_UPTIME, resolve_badge
from app.mcp_health import (
    DEFAULT_WINDOW_HOURS,
    MAX_HEALTH_ROWS,
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_UNKNOWN,
    STATUS_UP,
    derive_uptime_status,
    format_uptime_pct,
    percentile,
    summarize_health_checks,
)

client = TestClient(app)

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
_EP = "11111111-1111-1111-1111-111111111111"
_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_ENDPOINT_ROW = {"id": _EP, "tenant_id": "t1", "name": "Weather", "slug": "weather"}


def _check(minutes_ago: int, status: str = "up", latency_ms=100, error_code=None) -> dict:
    """One probe row as the DB layer returns it."""
    return {
        "id": f"00000000-0000-0000-0000-{minutes_ago:012d}",
        "endpoint_id": _EP,
        "checked_at": _NOW - timedelta(minutes=minutes_ago),
        "status": status,
        "latency_ms": latency_ms,
        "error_code": error_code,
    }


def _history(statuses: str) -> list:
    """Probe rows newest-first from a compact string: ``u`` = up, ``d`` = down."""
    return [
        _check(i * 5, "up" if s == "u" else "down", 100 + i, None if s == "u" else "connect_error")
        for i, s in enumerate(statuses)
    ]


# --- summary ---------------------------------------------------------------------------------------


def test_percentile_is_nearest_rank_and_none_when_empty():
    assert percentile([], 50) is None
    assert percentile([30, 10, 20], 50) == 20
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([7], 95) == 7


def test_status_latest_probe_decides_first():
    assert derive_uptime_status(None, None) == STATUS_UNKNOWN
    assert derive_uptime_status("down", 99.9) == STATUS_DOWN
    assert derive_uptime_status("up", 100.0) == STATUS_UP
    assert derive_uptime_status("up", 99.0) == STATUS_UP
    assert derive_uptime_status("up", 98.99) == STATUS_DEGRADED


def test_summary_of_no_probes_is_unknown_not_an_error():
    summary = summarize_health_checks([], window_hours=24)
    assert summary.status == STATUS_UNKNOWN
    assert (summary.checks, summary.up, summary.down) == (0, 0, 0)
    assert summary.uptime_pct is None
    assert summary.latency_p50_ms is None
    assert summary.last_checked_at is None
    assert summary.window_hours == 24


def test_summary_counts_uptime_and_latency_of_successful_probes_only():
    rows = [
        _check(0, "up", 100),
        _check(5, "up", 300),
        _check(10, "down", 9000, "timeout"),
        _check(15, "up", 200),
    ]
    summary = summarize_health_checks(rows)
    assert (summary.checks, summary.up, summary.down) == (4, 3, 1)
    assert summary.uptime_pct == 75.0
    # The 9s timeout is not a latency the server answered with.
    assert summary.latency_p50_ms == 200
    assert summary.latency_p95_ms == 300
    assert summary.status == STATUS_DEGRADED
    assert summary.last_status == "up"
    assert summary.last_checked_at == _NOW
    assert summary.last_error_code is None


def test_summary_latest_failure_reads_down_with_its_error_code():
    summary = summarize_health_checks(_history("d" + "u" * 99))
    assert summary.status == STATUS_DOWN
    assert summary.uptime_pct == 99.0
    assert summary.last_error_code == "connect_error"


def test_summary_all_up_is_up():
    summary = summarize_health_checks(_history("u" * 288))
    assert summary.status == STATUS_UP
    assert summary.uptime_pct == 100.0


def test_summary_tolerates_missing_latency():
    summary = summarize_health_checks([_check(0, "up", None)])
    assert summary.status == STATUS_UP
    assert summary.latency_p50_ms is None


def test_format_uptime_pct_floors_so_a_gap_never_reads_perfect():
    assert format_uptime_pct(None) == ""
    assert format_uptime_pct(100.0) == "100%"
    assert format_uptime_pct(99.96) == "99.9%"
    assert format_uptime_pct(87.5) == "87.5%"
    assert format_uptime_pct(0.0) == "0.0%"


# --- badge -----------------------------------------------------------------------------------------


def _badge_row(**uptime):
    return {"id": _EP, "slug": "weather", "enabled": True, "uptime": uptime or None}


def test_uptime_is_a_badge_metric():
    assert METRIC_UPTIME in BADGE_METRICS


def test_uptime_badge_reflects_recent_status():
    assert resolve_badge(_badge_row(status="up", uptime_pct=100.0), METRIC_UPTIME) == (
        "mcp uptime",
        "up · 100%",
        "#4c1",
    )
    assert resolve_badge(_badge_row(status="degraded", uptime_pct=97.25), METRIC_UPTIME) == (
        "mcp uptime",
        "degraded · 97.2%",
        "#dfb317",
    )
    assert resolve_badge(_badge_row(status="down", uptime_pct=99.5), METRIC_UPTIME) == (
        "mcp uptime",
        "down",
        "#e05d44",
    )


def test_uptime_badge_without_probes_is_unknown():
    assert resolve_badge(_badge_row(), METRIC_UPTIME) == ("mcp uptime", "unknown", "#9f9f9f")
    assert resolve_badge(_badge_row(status="bogus"), METRIC_UPTIME)[1] == "unknown"
    assert resolve_badge(None, METRIC_UPTIME) == ("mcp uptime", "unknown", "#9f9f9f")


def test_badge_route_uptime_reads_the_last_day_of_probes():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = {"id": _EP, "slug": "weather"}
        mdb.list_mcp_health_checks.return_value = _history("u" * 10)
        resp = client.get("/mcp/badge/acme/weather.svg", params={"metric": "uptime"})
    assert resp.status_code == 200
    assert "mcp uptime" in resp.text
    assert "up · 100%" in resp.text
    mdb.list_mcp_health_checks.assert_called_once_with(
        _EP, window_hours=DEFAULT_WINDOW_HOURS, limit=MAX_HEALTH_ROWS
    )


def test_badge_route_other_metrics_do_not_read_probes():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = {"id": _EP, "grade": "A"}
        resp = client.get("/mcp/badge/acme/weather.svg")
    assert resp.status_code == 200
    mdb.list_mcp_health_checks.assert_not_called()


def test_badge_route_uptime_for_hidden_endpoint_never_reads_probes():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = None
        resp = client.get("/mcp/badge/acme/private.svg", params={"metric": "uptime"})
    assert resp.status_code == 200
    assert "unknown" in resp.text
    mdb.list_mcp_health_checks.assert_not_called()


# --- REST route ------------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


_UPTIME_PATH = f"/v1/mcp/acme/endpoints/{_EP}/uptime"


def test_uptime_route_summarizes_window_and_lists_checks(authed):
    rows = [_check(0, "up", 120), _check(5, "down", 10000, "timeout"), _check(10, "up", 80)]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_health_checks.return_value = rows
        resp = client.get(_UPTIME_PATH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["endpoint_id"] == _EP
    summary = body["summary"]
    assert summary["status"] == "degraded"
    assert summary["checks"] == 3 and summary["up"] == 2 and summary["down"] == 1
    assert summary["uptime_pct"] == pytest.approx(66.67)
    assert summary["latency_p50_ms"] == 80
    assert summary["window_hours"] == 24
    assert [c["status"] for c in body["checks"]] == ["up", "down", "up"]
    assert body["checks"][1]["error_code"] == "timeout"
    assert body["truncated"] is False
    mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP)
    mdb.list_mcp_health_checks.assert_called_once_with(_EP, window_hours=24, limit=MAX_HEALTH_ROWS)


def test_uptime_route_limit_caps_listed_checks_but_not_the_summary(authed):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_health_checks.return_value = _history("uuuud")
        resp = client.get(_UPTIME_PATH, params={"limit": 2, "window_hours": 6})
    body = resp.json()
    assert len(body["checks"]) == 2
    assert body["truncated"] is True
    assert body["summary"]["checks"] == 5
    assert body["summary"]["window_hours"] == 6


def test_uptime_route_empty_history_is_unknown_not_500(authed):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_health_checks.return_value = []
        resp = client.get(_UPTIME_PATH)
    assert resp.status_code == 200
    assert resp.json()["summary"]["status"] == "unknown"
    assert resp.json()["checks"] == []


def test_uptime_route_other_tenants_endpoint_is_404(authed):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        resp = client.get(_UPTIME_PATH)
    assert resp.status_code == 404
    mdb.list_mcp_health_checks.assert_not_called()


@pytest.mark.parametrize(
    "params", [{"window_hours": 0}, {"window_hours": 169}, {"limit": 0}, {"limit": 1001}]
)
def test_uptime_route_validates_query(authed, params):
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        resp = client.get(_UPTIME_PATH, params=params)
    assert resp.status_code == 422


def test_uptime_route_requires_authentication():
    resp = client.get(_UPTIME_PATH)
    assert resp.status_code in (401, 403)
