"""Agent usage rollups — AGX-3.4 (#4540).

The aggregation (:func:`app.agent_usage.build_agent_usage`) is pure and tested directly; the route
is tested over HTTP with authentication overridden and the rollup accessor patched, so no test
reaches the database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent_usage import MAX_DAYS, build_agent_usage, get_agent_usage, usage_window
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt"}
_KEY_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_KEY_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
_URL = "/v1/tenants/acme/agent-usage"


def _row(day: date, key_id: str, tool: str, **counts: Any) -> Dict[str, Any]:
    """A rollup row as :meth:`Database.list_agent_usage_rollups` returns it."""
    calls = counts.pop("calls", 10)
    row: Dict[str, Any] = {
        "day": day,
        "key_id": key_id,
        "tool_name": tool,
        "calls": calls,
        "success_calls": calls,
        "upstream_errors": 0,
        "validation_failures": 0,
        "quota_rejections": 0,
        "internal_errors": 0,
        "latency_sum_ms": calls * 100,
        "latency_p95_ms": 150,
        "key_name": "claude-desktop" if key_id == _KEY_A else None,
        "key_prefix": "ak_abc123456..." if key_id == _KEY_A else None,
        "key_revoked": False,
    }
    row.update(counts)
    return row


# ============================================================================
# usage_window
# ============================================================================
def test_window_ends_today_and_counts_today():
    assert usage_window(7, _NOW) == (date(2026, 9, 30), date(2026, 10, 6))
    assert usage_window(1, _NOW) == (date(2026, 10, 6), date(2026, 10, 6))


def test_window_uses_the_utc_day():
    late_evening_west = datetime(2026, 10, 6, 23, 30, tzinfo=timezone.utc)
    assert usage_window(1, late_evening_west)[1] == date(2026, 10, 6)


def test_window_never_shorter_than_one_day():
    assert usage_window(0, _NOW) == (date(2026, 10, 6), date(2026, 10, 6))


# ============================================================================
# build_agent_usage
# ============================================================================
def _build(rows: List[Dict[str, Any]], days: int = 7):
    start, end = usage_window(days, _NOW)
    return build_agent_usage(rows, start_day=start, end_day=end, as_of=_NOW)


def test_no_rows_is_an_empty_but_complete_projection():
    usage = _build([])
    assert usage.days == 7
    assert [d.day for d in usage.daily][0] == date(2026, 9, 30)
    assert all(d.calls == 0 and d.latency_avg_ms is None for d in usage.daily)
    assert usage.tools == [] and usage.agents == []
    assert usage.totals.calls == 0
    assert usage.totals.error_rate == 0.0
    assert usage.totals.latency_p95_max_ms is None


def test_daily_series_is_zero_filled_and_ordered():
    usage = _build([_row(date(2026, 10, 2), _KEY_A, "listPets", calls=4)])
    assert len(usage.daily) == 7
    assert [d.calls for d in usage.daily] == [0, 0, 4, 0, 0, 0, 0]


def test_errors_are_calls_minus_successes_with_a_breakdown():
    rows = [
        _row(
            date(2026, 10, 6),
            _KEY_A,
            "createPet",
            calls=10,
            success_calls=6,
            upstream_errors=2,
            quota_rejections=1,
            internal_errors=1,
        )
    ]
    usage = _build(rows)
    assert usage.totals.errors == 4
    assert usage.totals.error_rate == pytest.approx(0.4)
    assert usage.totals.upstream_errors == 2
    assert usage.totals.quota_rejections == 1
    assert usage.totals.internal_errors == 1
    assert usage.totals.validation_failures == 0
    assert usage.tools[0].errors == 4


def test_latency_is_weighted_mean_and_worst_p95():
    rows = [
        _row(date(2026, 10, 5), _KEY_A, "listPets", calls=1, latency_sum_ms=100, latency_p95_ms=100),
        _row(date(2026, 10, 6), _KEY_A, "listPets", calls=3, latency_sum_ms=900, latency_p95_ms=400),
    ]
    tool = _build(rows).tools[0]
    assert tool.latency_avg_ms == pytest.approx(250.0)
    assert tool.latency_p95_max_ms == 400


def test_a_zero_call_group_does_not_raise_the_worst_p95():
    rows = [
        _row(date(2026, 10, 6), _KEY_A, "listPets", calls=2, latency_p95_ms=50),
        _row(date(2026, 10, 6), _KEY_A, "getPet", calls=0, success_calls=0, latency_p95_ms=9000),
    ]
    assert _build(rows).totals.latency_p95_max_ms == 50


def test_tools_and_agents_are_sorted_by_calls_with_metadata():
    rows = [
        _row(date(2026, 10, 6), _KEY_A, "listPets", calls=5),
        _row(date(2026, 10, 6), _KEY_B, "getPet", calls=9, key_revoked=True),
        _row(date(2026, 10, 5), _KEY_A, "getPet", calls=1),
    ]
    usage = _build(rows)
    assert [(t.tool_name, t.calls) for t in usage.tools] == [("getPet", 10), ("listPets", 5)]
    assert [(a.key_id, a.calls) for a in usage.agents] == [(_KEY_B, 9), (_KEY_A, 6)]
    assert usage.agents[0].name is None and usage.agents[0].revoked is True
    assert usage.agents[1].name == "claude-desktop"
    assert usage.agents[1].key_prefix == "ak_abc123456..."


def test_rows_outside_the_window_are_ignored():
    rows = [
        _row(date(2026, 9, 1), _KEY_A, "listPets", calls=100),
        _row(date(2026, 10, 7), _KEY_A, "listPets", calls=100),
        _row(date(2026, 10, 6), _KEY_A, "listPets", calls=1),
    ]
    assert _build(rows).totals.calls == 1


def test_datetime_days_are_accepted():
    rows = [_row(datetime(2026, 10, 6, 0, 0), _KEY_A, "listPets", calls=2)]
    assert _build(rows).daily[-1].calls == 2


def test_serialization_uses_camel_case():
    body = _build([_row(date(2026, 10, 6), _KEY_A, "listPets")]).model_dump(mode="json", by_alias=True)
    assert body["schemaVersion"] == "agx.agent-usage.v1"
    assert {"startDay", "endDay", "asOf", "totals", "daily", "tools", "agents"} <= set(body)
    assert {"toolName", "errorRate", "latencyAvgMs", "latencyP95MaxMs"} <= set(body["tools"][0])
    assert {"keyId", "keyPrefix", "revoked"} <= set(body["agents"][0])
    assert "quotaRejections" in body["totals"]


def test_get_agent_usage_reads_the_window_from_the_accessor(monkeypatch):
    calls: List[Any] = []

    def fake(tenant_id, start_day, end_day):
        calls.append((tenant_id, start_day, end_day))
        return [_row(end_day, _KEY_A, "listPets", calls=3)]

    monkeypatch.setattr(db, "list_agent_usage_rollups", fake)
    usage = get_agent_usage(_TENANT, days=30, now=_NOW)
    assert calls == [(_TENANT, date(2026, 9, 7), date(2026, 10, 6))]
    assert usage.totals.calls == 3


def test_accessor_returns_nothing_for_a_non_uuid_tenant():
    assert db.list_agent_usage_rollups("not-a-uuid", date(2026, 1, 1), date(2026, 1, 2)) == []


# ============================================================================
# Route
# ============================================================================
@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def rollups(monkeypatch) -> List[Any]:
    """Patch the accessor to return one row and record each call."""
    seen: List[Any] = []

    def fake(tenant_id, start_day, end_day):
        seen.append((tenant_id, start_day, end_day))
        return [_row(end_day, _KEY_A, "listPets", calls=2)]

    monkeypatch.setattr(db, "list_agent_usage_rollups", fake)
    return seen


def test_route_enforces_api_keys_view(rollups):
    with patch("app.agent_usage_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.get(_URL)
    assert response.status_code == 200, response.text
    assert guard.call_args.args[2:] == (Resource.API_KEYS, Action.VIEW)


def test_route_refuses_a_denied_caller_without_reading(rollups):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.agent_usage_routes.enforce_permission", side_effect=denied):
        response = client.get(_URL)
    assert response.status_code == 403
    assert rollups == []


def test_route_is_scoped_by_the_authenticated_tenant(rollups):
    with patch("app.agent_usage_routes.enforce_permission", return_value=_ACTOR):
        response = client.get("/v1/tenants/someone-else/agent-usage?days=7")
    assert response.status_code == 200
    assert rollups[0][0] == _TENANT
    body = response.json()
    assert body["days"] == 7 and len(body["daily"]) == 7
    assert body["totals"]["calls"] == 2


def test_route_defaults_to_thirty_days(rollups):
    with patch("app.agent_usage_routes.enforce_permission", return_value=_ACTOR):
        body = client.get(_URL).json()
    assert body["days"] == 30


@pytest.mark.parametrize("days", [0, -1, MAX_DAYS + 1, "abc"])
def test_route_rejects_an_out_of_range_window(rollups, days):
    with patch("app.agent_usage_routes.enforce_permission", return_value=_ACTOR):
        response = client.get(f"{_URL}?days={days}")
    assert response.status_code == 422
    assert rollups == []


def test_route_refuses_without_a_tenant(rollups):
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": _ACTOR}
    with patch("app.agent_usage_routes.enforce_permission", return_value=_ACTOR):
        response = client.get(_URL)
    assert response.status_code == 403
