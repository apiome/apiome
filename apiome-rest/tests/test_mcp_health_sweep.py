"""Tests for the MCP endpoint reachability / latency probe sweep (V2-MCP-27.3 / MCAT-13.3, #3713).

All DB-free, three layers:

* **DB layer** — the due-selection, record, history and prune methods build the right SQL (live,
  enabled, non-stdio endpoints; quarantined ones included; least recently probed first) and guard
  their inputs.
* **Probe** — :func:`probe_endpoint` runs the ``initialize`` handshake only, times it, and turns every
  failure (classified error, timeout, credential-read crash) into a ``down`` result, never a raise.
* **Sweep** — :func:`process_mcp_health_sweep` honours the kill switch, records one row per due
  endpoint, bounds concurrency, and isolates a failed write or a failed prune.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import mcp_health_sweep
from app.database import Database
from app.mcp_client.transport_http import McpHttpStatusError, McpTransportError
from app.mcp_health_sweep import (
    HEALTH_CHECK_RETENTION_DAYS,
    ProbeResult,
    probe_endpoint,
    process_mcp_health_sweep,
)

_EP1 = "11111111-1111-1111-1111-111111111111"
_EP2 = "22222222-2222-2222-2222-222222222222"
_EP3 = "33333333-3333-3333-3333-333333333333"


def _endpoint(endpoint_id: str, transport: str = "streamable_http") -> dict:
    return {
        "id": endpoint_id,
        "tenant_id": "t1",
        "slug": f"ep-{endpoint_id[:4]}",
        "endpoint_url": "https://mcp.example.com/mcp",
        "transport": transport,
    }


# ===========================================================================
# DB LAYER
# ===========================================================================


def _capture(monkeypatch, db: Database, method: str, result):
    captured = {}

    def _fake(query, params=None):
        captured["query"] = query
        captured["params"] = params
        return result

    monkeypatch.setattr(db, method, _fake)
    return captured


def test_list_due_health_endpoints_sql(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "execute_query", [_endpoint(_EP1)])

    rows = db.list_due_mcp_health_endpoints(cadence_seconds=300, limit=50)

    assert [r["id"] for r in rows] == [_EP1]
    q = captured["query"]
    assert "deleted_at IS NULL" in q
    assert "enabled = TRUE" in q
    # A stdio server has no URL to probe.
    assert "transport <> 'stdio'" in q
    # Quarantine pauses discovery, not monitoring: a down server must be seen coming back.
    where = q.split("WHERE deleted_at IS NULL", 1)[1]
    assert "quarantined_at" not in where
    assert "next_discovery_after" not in where
    assert "apiome.mcp_endpoint_health_checks" in q
    assert "hc.last_checked_at IS NULL" in q
    assert "now() - make_interval(secs => %s)" in q
    assert "ORDER BY hc.last_checked_at ASC NULLS FIRST" in q
    assert "LIMIT %s" in q
    assert captured["params"] == (300, 50)


def test_list_due_health_endpoints_clamps_cadence_and_limit(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "execute_query", [])
    db.list_due_mcp_health_endpoints(cadence_seconds=0, limit=-3)
    assert captured["params"] == (1, 1)


def test_record_health_check_uses_wall_clock_and_drops_error_for_up(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "execute_query", [{"id": "h1", "status": "up"}])

    row = db.record_mcp_health_check(_EP1, status="up", latency_ms=42, error_code="ignored")

    assert row == {"id": "h1", "status": "up"}
    assert "clock_timestamp()" in captured["query"]
    assert "RETURNING" in captured["query"]
    assert captured["params"] == (_EP1, "up", 42, None)


def test_record_health_check_keeps_error_for_down(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "execute_query", [{"id": "h2"}])
    db.record_mcp_health_check(_EP1, status="down", latency_ms=5, error_code="timeout")
    assert captured["params"] == (_EP1, "down", 5, "timeout")


@pytest.mark.parametrize(
    "kwargs", [{"status": "flaky", "latency_ms": 1}, {"status": "up", "latency_ms": -1}]
)
def test_record_health_check_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        Database().record_mcp_health_check(_EP1, error_code=None, **kwargs)


def test_list_health_checks_sql(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "execute_query", [])
    db.list_mcp_health_checks(_EP1, window_hours=0, limit=0)
    q = captured["query"]
    assert "WHERE endpoint_id = %s::uuid" in q
    assert "make_interval(hours => %s)" in q
    assert "ORDER BY checked_at DESC" in q
    assert captured["params"] == (_EP1, 1, 1)


def test_prune_health_checks(monkeypatch):
    db = Database()
    captured = _capture(monkeypatch, db, "_execute_write", 7)
    assert db.prune_mcp_health_checks(retention_days=30) == 7
    assert "DELETE FROM apiome.mcp_endpoint_health_checks" in captured["query"]
    assert captured["params"] == (30,)
    with pytest.raises(ValueError):
        db.prune_mcp_health_checks(retention_days=0)


# ===========================================================================
# PROBE
# ===========================================================================


class _FakeTransport:
    def __init__(self, fail_close: bool = False) -> None:
        self.closed = False
        self.fail_close = fail_close

    async def aclose(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("close failed")


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.setattr(mcp_health_sweep, "load_endpoint_auth_headers", lambda _id: {})


async def test_probe_up_runs_initialize_only_and_closes(monkeypatch, no_credentials):
    transport = _FakeTransport()
    calls = []

    async def _open(url, **kwargs):
        calls.append((url, kwargs))
        return transport, object()

    monkeypatch.setattr(mcp_health_sweep, "open_session", _open)

    result = await probe_endpoint(_endpoint(_EP1, transport="sse"), 5.0)

    assert result.status == "up"
    assert result.error_code is None
    assert result.latency_ms >= 0
    assert transport.closed
    url, kwargs = calls[0]
    assert url == "https://mcp.example.com/mcp"
    assert kwargs["transport"] == "sse"
    assert kwargs["timeout"] == 5.0


async def test_probe_sends_stored_credentials(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        mcp_health_sweep, "load_endpoint_auth_headers", lambda _id: {"Authorization": "Bearer t"}
    )

    async def _open(url, **kwargs):
        seen.update(kwargs["headers"])
        return _FakeTransport(), object()

    monkeypatch.setattr(mcp_health_sweep, "open_session", _open)
    assert (await probe_endpoint(_endpoint(_EP1), 5.0)).status == "up"
    assert seen == {"Authorization": "Bearer t"}


async def test_probe_messy_close_is_still_up(monkeypatch, no_credentials):
    async def _open(url, **kwargs):
        return _FakeTransport(fail_close=True), object()

    monkeypatch.setattr(mcp_health_sweep, "open_session", _open)
    assert (await probe_endpoint(_endpoint(_EP1), 5.0)).status == "up"


@pytest.mark.parametrize(
    "exc, code",
    [
        (McpTransportError("connection refused"), None),
        (McpHttpStatusError(503, "unavailable"), "http_status"),
    ],
)
async def test_probe_failure_is_down_with_classified_code(monkeypatch, no_credentials, exc, code):
    async def _open(url, **kwargs):
        raise exc

    monkeypatch.setattr(mcp_health_sweep, "open_session", _open)
    result = await probe_endpoint(_endpoint(_EP1), 5.0)
    assert result.status == "down"
    assert result.error_code
    if code:
        assert result.error_code == code


async def test_probe_overrun_is_down_with_timeout(monkeypatch, no_credentials):
    async def _open(url, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(mcp_health_sweep, "open_session", _open)
    result = await probe_endpoint(_endpoint(_EP1), 0.05)
    assert result == ProbeResult("down", result.latency_ms, "timeout")


async def test_probe_credential_crash_is_down_unknown_not_a_raise(monkeypatch):
    def _boom(_id):
        raise RuntimeError("credential store down")

    monkeypatch.setattr(mcp_health_sweep, "load_endpoint_auth_headers", _boom)
    result = await probe_endpoint(_endpoint(_EP1), 5.0)
    assert result.status == "down"
    assert result.error_code == "unknown"


async def test_probe_runner_seam_bypasses_the_network(monkeypatch, no_credentials):
    async def _runner(endpoint, headers, timeout):
        return ProbeResult("up", 7)

    monkeypatch.setattr(mcp_health_sweep, "_probe_runner", _runner)
    assert await probe_endpoint(_endpoint(_EP1), 5.0) == ProbeResult("up", 7)


# ===========================================================================
# SWEEP
# ===========================================================================


def _settings(**overrides):
    base = {
        "mcp_health_enabled": True,
        "mcp_health_cadence_seconds": 300,
        "mcp_health_min_interval_seconds": 60,
        "mcp_health_max_concurrency": 4,
        "mcp_health_timeout_seconds": 10,
        "mcp_health_max_per_tick": 200,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeDb:
    def __init__(self, due, *, fail_record_for=(), fail_prune=False) -> None:
        self.due = due
        self.fail_record_for = set(fail_record_for)
        self.fail_prune = fail_prune
        self.recorded = []
        self.due_kwargs = None
        self.pruned_with = None

    def prune_mcp_health_checks(self, *, retention_days):
        self.pruned_with = retention_days
        if self.fail_prune:
            raise RuntimeError("prune failed")
        return 0

    def list_due_mcp_health_endpoints(self, **kwargs):
        self.due_kwargs = kwargs
        return self.due

    def record_mcp_health_check(self, endpoint_id, **kwargs):
        if endpoint_id in self.fail_record_for:
            raise RuntimeError("write failed")
        self.recorded.append((endpoint_id, kwargs))
        return {"id": "h"}


@pytest.fixture
def probes(monkeypatch):
    """Replace the probe with a canned result per endpoint id."""
    results = {}

    async def _probe(endpoint, timeout_seconds):
        return results.get(endpoint["id"], ProbeResult("up", 50))

    monkeypatch.setattr(mcp_health_sweep, "probe_endpoint", _probe)
    return results


def _patch_settings(monkeypatch, **overrides):
    monkeypatch.setattr("app.config.settings", _settings(**overrides), raising=False)


async def test_sweep_records_one_probe_per_due_endpoint(monkeypatch, probes):
    _patch_settings(monkeypatch, mcp_health_cadence_seconds=120, mcp_health_max_per_tick=10)
    probes[_EP2] = ProbeResult("down", 900, "connect_error")
    db = _FakeDb([_endpoint(_EP1), _endpoint(_EP2)])

    assert await process_mcp_health_sweep(db) == 2

    assert db.due_kwargs == {"cadence_seconds": 120, "limit": 10}
    assert db.pruned_with == HEALTH_CHECK_RETENTION_DAYS
    assert sorted(db.recorded) == [
        (_EP1, {"status": "up", "latency_ms": 50, "error_code": None}),
        (_EP2, {"status": "down", "latency_ms": 900, "error_code": "connect_error"}),
    ]


async def test_sweep_halts_on_kill_switch(monkeypatch, probes):
    _patch_settings(monkeypatch, mcp_health_enabled=False)
    db = _FakeDb([_endpoint(_EP1)])
    assert await process_mcp_health_sweep(db) == 0
    assert db.due_kwargs is None
    assert db.recorded == []


async def test_sweep_with_nothing_due_records_nothing(monkeypatch, probes):
    _patch_settings(monkeypatch)
    db = _FakeDb([])
    assert await process_mcp_health_sweep(db) == 0
    assert db.recorded == []


async def test_sweep_isolates_a_failed_write(monkeypatch, probes):
    _patch_settings(monkeypatch)
    db = _FakeDb([_endpoint(_EP1), _endpoint(_EP2), _endpoint(_EP3)], fail_record_for={_EP2})
    assert await process_mcp_health_sweep(db) == 2
    assert sorted(r[0] for r in db.recorded) == [_EP1, _EP3]


async def test_sweep_keeps_probing_when_prune_fails(monkeypatch, probes):
    _patch_settings(monkeypatch)
    db = _FakeDb([_endpoint(_EP1)], fail_prune=True)
    assert await process_mcp_health_sweep(db) == 1


async def test_sweep_bounds_concurrency(monkeypatch):
    _patch_settings(monkeypatch, mcp_health_max_concurrency=2)
    in_flight = 0
    peak = 0

    async def _probe(endpoint, timeout_seconds):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return ProbeResult("up", 1)

    monkeypatch.setattr(mcp_health_sweep, "probe_endpoint", _probe)
    db = _FakeDb([_endpoint(f"{i:08d}-0000-0000-0000-000000000000") for i in range(6)])

    assert await process_mcp_health_sweep(db) == 6
    assert peak == 2


async def test_sweep_passes_configured_timeout(monkeypatch):
    _patch_settings(monkeypatch, mcp_health_timeout_seconds=3)
    seen = []

    async def _probe(endpoint, timeout_seconds):
        seen.append(timeout_seconds)
        return ProbeResult("up", 1)

    monkeypatch.setattr(mcp_health_sweep, "probe_endpoint", _probe)
    await process_mcp_health_sweep(_FakeDb([_endpoint(_EP1)]))
    assert seen == [3.0]
