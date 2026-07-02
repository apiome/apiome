"""Tests for the periodic MCP re-discovery sweep (V2-MCP-19.1/19.2 / MCAT-5.1+5.2, #3673/#3674).

All DB-free, four layers:

* **DB layer** — ``Database.list_due_mcp_endpoints`` builds the right due-selection SQL (enabled
  filter, ``COALESCE`` cadence with the global default, oldest-first ordering) and clamps a
  non-positive default cadence.
* **Sweep** — ``process_mcp_discovery_sweep`` enqueues a ``trigger='sweep'`` job per due endpoint
  and drives the freshly-created ones under a concurrency cap with a per-endpoint timeout; it
  honours the global kill switch, does not count/drive de-duplicated runs, isolates a single
  endpoint's enqueue failure, and never lets one run's crash abort the tick (MCAT-5.2).
* **Engine seam** — ``enqueue_discovery_job`` threads the ``trigger`` label through to the enqueue
  without scheduling a run; ``trigger_discovery`` still enqueues *and* schedules the manual run;
  ``run_discovery_job`` records a ``budget_exceeded`` failure when a run overruns its timeout.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app import mcp_discovery_engine, mcp_discovery_sweep
from app.database import Database
from app.mcp_client.errors import DiscoveryError, DiscoveryErrorCode, classify_exception
from app.mcp_client.transport_http import McpRateLimitedError

_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)
_EP1 = "11111111-1111-1111-1111-111111111111"
_EP2 = "22222222-2222-2222-2222-222222222222"


def _endpoint(endpoint_id: str, *, tenant_id: str = "t1") -> dict:
    return {
        "id": endpoint_id,
        "tenant_id": tenant_id,
        "name": "Acme Weather",
        "slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/mcp",
        "transport": "streamable_http",
    }


# ===========================================================================
# DB LAYER — due-selection SQL
# ===========================================================================


def test_list_due_endpoints_builds_due_selection_sql(monkeypatch):
    db = Database()
    captured = {}

    def _fake_execute(query, params=None):
        captured["query"] = query
        captured["params"] = params
        return [_endpoint(_EP1), _endpoint(_EP2)]

    monkeypatch.setattr(db, "execute_query", _fake_execute)

    rows = db.list_due_mcp_endpoints(default_cadence_seconds=3600)

    assert [r["id"] for r in rows] == [_EP1, _EP2]
    q = captured["query"]
    # Only live, enabled endpoints are candidates.
    assert "deleted_at IS NULL" in q
    assert "enabled = TRUE" in q
    # Never-discovered endpoints are always due; otherwise compare against the effective cadence.
    assert "last_discovered_at IS NULL" in q
    # Per-endpoint override falls back to the global default via COALESCE.
    assert "COALESCE(discovery_cadence_seconds, %s)" in q
    # Recency is evaluated in the database (no app clock).
    assert "now() - make_interval" in q
    # Failure handling (MCAT-5.3): quarantined endpoints and ones still inside their backoff
    # window are excluded so a flaky/dead endpoint never wedges the sweep.
    assert "quarantined_at IS NULL" in q
    assert "next_discovery_after IS NULL OR next_discovery_after <= now()" in q
    # Fair scheduling: oldest first, never-discovered first.
    assert "ORDER BY last_discovered_at ASC NULLS FIRST" in q
    # The global default cadence is the bound parameter.
    assert captured["params"] == (3600,)


def test_list_due_endpoints_clamps_non_positive_default_cadence(monkeypatch):
    db = Database()
    captured = {}

    def _fake_execute(query, params=None):
        captured["params"] = params
        return []

    monkeypatch.setattr(db, "execute_query", _fake_execute)

    db.list_due_mcp_endpoints(default_cadence_seconds=0)

    # A non-positive default would make make_interval(secs => 0) treat everything as due forever;
    # it is clamped up to a 1-second floor.
    assert captured["params"] == (1,)


# ===========================================================================
# SWEEP — process_mcp_discovery_sweep
# ===========================================================================


def _settings(**overrides):
    base = {
        "mcp_discovery_enabled": True,
        "mcp_discovery_default_cadence_seconds": 3600,
        "mcp_discovery_min_interval_seconds": 60,
        "mcp_discovery_max_concurrency": 4,
        "mcp_discovery_endpoint_timeout_seconds": 150,
        "mcp_discovery_quarantine_threshold": 5,
        "mcp_discovery_backoff_base_seconds": 60,
        "mcp_discovery_backoff_max_seconds": 21600,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_settings(monkeypatch, **overrides):
    monkeypatch.setattr(
        "app.config.settings", _settings(**overrides), raising=False
    )


async def test_sweep_enqueues_and_runs_discovery_per_due_endpoint(monkeypatch):
    _patch_settings(monkeypatch)
    db = MagicMock()
    db.list_due_mcp_endpoints.return_value = [_endpoint(_EP1), _endpoint(_EP2)]

    enqueued = []

    async def _fake_enqueue(tenant_id, endpoint, *, trigger="manual"):
        enqueued.append((tenant_id, endpoint["id"], trigger))
        return {"id": f"job-{endpoint['id']}"}, False

    runs = []

    async def _fake_run(job_id, endpoint, *, timeout_seconds=None):
        runs.append((job_id, endpoint["id"], timeout_seconds))

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", _fake_run)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    assert dispatched == 2
    # The global default cadence is forwarded to due-selection.
    db.list_due_mcp_endpoints.assert_called_once_with(default_cadence_seconds=3600)
    # Each due endpoint is enqueued under the sweep trigger...
    assert enqueued == [("t1", _EP1, "sweep"), ("t1", _EP2, "sweep")]
    # ...and its freshly-created job is driven with the configured per-endpoint timeout.
    assert sorted(r[1] for r in runs) == [_EP1, _EP2]
    assert all(r[2] == 150.0 for r in runs)


async def test_sweep_halts_on_global_kill_switch(monkeypatch):
    _patch_settings(monkeypatch, mcp_discovery_enabled=False)
    db = MagicMock()

    async def _fake_enqueue(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("enqueue must not run when the kill switch is off")

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    assert dispatched == 0
    # The kill switch short-circuits before any selection or enqueue.
    db.list_due_mcp_endpoints.assert_not_called()


async def test_sweep_does_not_drive_deduplicated_runs(monkeypatch):
    _patch_settings(monkeypatch)
    db = MagicMock()
    db.list_due_mcp_endpoints.return_value = [_endpoint(_EP1), _endpoint(_EP2)]

    # EP1 creates a fresh job; EP2 coalesces onto an already-active job.
    outcomes = {_EP1: ({"id": "job1"}, False), _EP2: ({"id": "job2"}, True)}

    async def _fake_enqueue(_tenant_id, endpoint, *, trigger="manual"):
        return outcomes[endpoint["id"]]

    runs = []

    async def _fake_run(job_id, endpoint, *, timeout_seconds=None):
        runs.append(job_id)

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", _fake_run)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    # Only the freshly-created job is counted and driven; the de-duplicated one is left alone.
    assert dispatched == 1
    assert runs == ["job1"]


async def test_sweep_isolates_single_endpoint_enqueue_failure(monkeypatch):
    _patch_settings(monkeypatch)
    db = MagicMock()
    db.list_due_mcp_endpoints.return_value = [_endpoint(_EP1), _endpoint(_EP2)]

    seen = []

    async def _fake_enqueue(_tenant_id, endpoint, *, trigger="manual"):
        seen.append(endpoint["id"])
        if endpoint["id"] == _EP1:
            raise RuntimeError("enqueue boom")
        return {"id": "job2"}, False

    runs = []

    async def _fake_run(job_id, endpoint, *, timeout_seconds=None):
        runs.append(job_id)

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", _fake_run)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    # EP1 failed to enqueue, but EP2 was still enqueued and driven.
    assert seen == [_EP1, _EP2]
    assert dispatched == 1
    assert runs == ["job2"]


async def test_sweep_run_crash_does_not_abort_tick(monkeypatch):
    _patch_settings(monkeypatch)
    db = MagicMock()
    db.list_due_mcp_endpoints.return_value = [_endpoint(_EP1), _endpoint(_EP2)]

    async def _fake_enqueue(_tenant_id, endpoint, *, trigger="manual"):
        return {"id": f"job-{endpoint['id']}"}, False

    ran = []

    async def _fake_run(job_id, endpoint, *, timeout_seconds=None):
        ran.append(job_id)
        if endpoint["id"] == _EP1:
            raise RuntimeError("unexpected run crash")

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", _fake_run)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    # Both runs were attempted (gather return_exceptions); one crashing did not abort the other.
    assert sorted(ran) == [f"job-{_EP1}", f"job-{_EP2}"]
    assert dispatched == 2


async def test_sweep_bounds_concurrency(monkeypatch):
    _patch_settings(monkeypatch, mcp_discovery_max_concurrency=2)
    db = MagicMock()
    ids = [f"endpoint-{i}" for i in range(6)]
    db.list_due_mcp_endpoints.return_value = [_endpoint(i) for i in ids]

    async def _fake_enqueue(_tenant_id, endpoint, *, trigger="manual"):
        return {"id": f"job-{endpoint['id']}"}, False

    active = 0
    peak = 0

    async def _fake_run(job_id, endpoint, *, timeout_seconds=None):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        # Hold the slot briefly so overlap (or its absence) is observable.
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", _fake_run)

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(db)

    assert dispatched == 6
    # The semaphore never let more than the cap run simultaneously...
    assert peak <= 2
    # ...yet it did run them concurrently up to the cap (not serially).
    assert peak == 2


async def test_sweep_no_due_endpoints_is_a_noop(monkeypatch):
    _patch_settings(monkeypatch)
    db = MagicMock()
    db.list_due_mcp_endpoints.return_value = []

    async def _fake_enqueue(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("enqueue should not run with no due endpoints")

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", _fake_enqueue)

    assert await mcp_discovery_sweep.process_mcp_discovery_sweep(db) == 0


# ===========================================================================
# ENGINE SEAM — enqueue / trigger / bounded run
# ===========================================================================


async def test_enqueue_discovery_job_threads_label_without_running(monkeypatch):
    mdb = MagicMock()
    mdb.enqueue_mcp_discovery_job.return_value = {
        "job": {"id": "job", "trigger": "sweep"},
        "deduplicated": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    scheduled = []

    def _capture(coro):  # pragma: no cover - asserted empty below
        scheduled.append(coro)
        coro.close()

    monkeypatch.setattr(mcp_discovery_engine.asyncio, "create_task", _capture)

    job, deduplicated = await mcp_discovery_engine.enqueue_discovery_job(
        "t1", _endpoint(_EP1), trigger="sweep"
    )

    assert deduplicated is False
    assert job["id"] == "job"
    # The trigger label reaches the enqueue DAO unchanged.
    mdb.enqueue_mcp_discovery_job.assert_called_once_with(_EP1, "t1", "sweep")
    # enqueue must NOT start a run — driving is the caller's responsibility (bounded sweep).
    assert scheduled == []


async def test_trigger_discovery_passes_sweep_label_and_schedules_run(monkeypatch):
    mdb = MagicMock()
    mdb.enqueue_mcp_discovery_job.return_value = {
        "job": {"id": "job", "trigger": "sweep"},
        "deduplicated": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    scheduled = []

    def _capture(coro):
        scheduled.append(coro)
        coro.close()  # only assert a task was scheduled; don't run it

    monkeypatch.setattr(mcp_discovery_engine.asyncio, "create_task", _capture)

    job, deduplicated = await mcp_discovery_engine.trigger_discovery(
        "t1", _endpoint(_EP1), trigger="sweep"
    )

    assert deduplicated is False
    assert job["trigger"] == "sweep"
    # The trigger label reaches the enqueue DAO unchanged...
    mdb.enqueue_mcp_discovery_job.assert_called_once_with(_EP1, "t1", "sweep")
    # ...and a fresh job's run is scheduled in the background.
    assert len(scheduled) == 1


async def test_trigger_discovery_defaults_to_manual_label(monkeypatch):
    mdb = MagicMock()
    mdb.enqueue_mcp_discovery_job.return_value = {
        "job": {"id": "job", "trigger": "manual"},
        "deduplicated": True,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    await mcp_discovery_engine.trigger_discovery("t1", _endpoint(_EP1))

    mdb.enqueue_mcp_discovery_job.assert_called_once_with(_EP1, "t1", "manual")


async def test_run_discovery_job_drives_without_timeout(monkeypatch):
    ran = []

    async def _fast_drive(job_id, endpoint):
        ran.append(job_id)

    failures = []

    def _fake_persist_failure(*args):  # pragma: no cover - must not be called
        failures.append(args)

    monkeypatch.setattr(mcp_discovery_engine, "_drive_discovery_job", _fast_drive)
    monkeypatch.setattr(mcp_discovery_engine, "_persist_failure", _fake_persist_failure)

    # None timeout takes the unbounded path; a generous finite timeout completes normally.
    await mcp_discovery_engine.run_discovery_job("jobA", _endpoint(_EP1), timeout_seconds=None)
    await mcp_discovery_engine.run_discovery_job("jobB", _endpoint(_EP1), timeout_seconds=5)

    assert ran == ["jobA", "jobB"]
    assert failures == []


async def test_run_discovery_job_records_budget_failure_on_timeout(monkeypatch):
    async def _slow_drive(job_id, endpoint):
        await asyncio.sleep(5)  # far longer than the timeout below

    captured = {}

    def _fake_persist_failure(job_id, endpoint, error, discovered_at):
        captured["job_id"] = job_id
        captured["endpoint"] = endpoint
        captured["error"] = error

    monkeypatch.setattr(mcp_discovery_engine, "_drive_discovery_job", _slow_drive)
    monkeypatch.setattr(mcp_discovery_engine, "_persist_failure", _fake_persist_failure)

    await mcp_discovery_engine.run_discovery_job(
        "job-slow", _endpoint(_EP1), timeout_seconds=0.01
    )

    # The overrun is recorded as a terminal budget_exceeded failure on the right job/endpoint.
    assert captured["job_id"] == "job-slow"
    assert captured["endpoint"]["id"] == _EP1
    assert captured["error"].code == DiscoveryErrorCode.BUDGET_EXCEEDED


# ===========================================================================
# DB LAYER — record_mcp_discovery_failure (backoff + quarantine, fake cursor)
# ===========================================================================


class _FakeCursor:
    """Cursor double serving a queue of fetchone results and recording statements."""

    def __init__(self, fetchone_results=None):
        self._fetchone_results = list(fetchone_results or [])
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None


class _FakeInfo:
    transaction_status = 0  # psycopg2 TRANSACTION_STATUS_IDLE


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.autocommit = True
        self.info = _FakeInfo()

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _failure_db(monkeypatch, *, new_count, was_quarantined):
    """A Database whose record_mcp_discovery_failure runs against a fake connection."""
    cur = _FakeCursor(
        fetchone_results=[
            {"consecutive_failures": new_count, "was_quarantined": was_quarantined}
        ]
    )
    conn = _FakeConn(cur)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    return db, cur, conn


def test_record_failure_increments_and_sets_backoff(monkeypatch):
    db, cur, conn = _failure_db(monkeypatch, new_count=2, was_quarantined=False)

    out = db.record_mcp_discovery_failure(
        _EP1,
        discovered_at=_NOW,
        status="connect_error",
        backoff_base_seconds=60,
        backoff_max_seconds=21600,
        quarantine_threshold=5,
        quarantine_reason="connect_error: boom",
    )

    # Second consecutive failure → 2 * base = 120s backoff, not yet quarantined.
    assert out == {
        "consecutive_failures": 2,
        "backoff_seconds": 120.0,
        "quarantined": False,
        "newly_quarantined": False,
    }
    # The first UPDATE increments the counter and stamps the specific status.
    inc_sql, inc_params = cur.executed[0]
    assert "consecutive_failures = consecutive_failures + 1" in inc_sql
    assert inc_params == (_NOW, "connect_error", _EP1)
    # The second UPDATE writes the backoff anchor and does NOT trip quarantine.
    backoff_sql, backoff_params = cur.executed[1]
    assert "next_discovery_after = %s + make_interval(secs => %s)" in backoff_sql
    assert backoff_params[0] == _NOW
    assert backoff_params[1] == 120.0
    assert backoff_params[2] is False  # should_quarantine
    assert conn.committed is True


def test_record_failure_trips_quarantine_at_threshold(monkeypatch):
    db, cur, conn = _failure_db(monkeypatch, new_count=5, was_quarantined=False)

    out = db.record_mcp_discovery_failure(
        _EP1,
        discovered_at=_NOW,
        status="connect_error",
        backoff_base_seconds=60,
        backoff_max_seconds=21600,
        quarantine_threshold=5,
        quarantine_reason="connect_error: dead",
    )

    assert out["consecutive_failures"] == 5
    assert out["quarantined"] is True
    assert out["newly_quarantined"] is True
    # The quarantine UPDATE carries the should_quarantine flag and the reason text.
    _backoff_sql, backoff_params = cur.executed[1]
    assert backoff_params[2] is True  # should_quarantine
    assert "connect_error: dead" in backoff_params


def test_record_failure_already_quarantined_is_not_newly(monkeypatch):
    db, cur, conn = _failure_db(monkeypatch, new_count=9, was_quarantined=True)

    out = db.record_mcp_discovery_failure(
        _EP1,
        discovered_at=_NOW,
        status="connect_error",
        backoff_base_seconds=60,
        backoff_max_seconds=21600,
        quarantine_threshold=5,
        quarantine_reason="connect_error: still dead",
    )

    # Already quarantined: stays quarantined but does not re-emit the transition event.
    assert out["quarantined"] is True
    assert out["newly_quarantined"] is False


def test_record_failure_threshold_disabled_never_quarantines(monkeypatch):
    db, cur, conn = _failure_db(monkeypatch, new_count=50, was_quarantined=False)

    out = db.record_mcp_discovery_failure(
        _EP1,
        discovered_at=_NOW,
        status="connect_error",
        backoff_base_seconds=60,
        backoff_max_seconds=21600,
        quarantine_threshold=0,  # disabled
        quarantine_reason="x",
    )

    assert out["quarantined"] is False
    assert out["newly_quarantined"] is False
    # Backoff is still clamped to the ceiling even with quarantine disabled.
    assert out["backoff_seconds"] == 21600.0


def test_record_failure_returns_none_when_endpoint_gone(monkeypatch):
    db, cur, conn = _failure_db(monkeypatch, new_count=1, was_quarantined=False)
    cur._fetchone_results = [None]  # the UPDATE matched no row

    out = db.record_mcp_discovery_failure(
        _EP1,
        discovered_at=_NOW,
        backoff_base_seconds=60,
        backoff_max_seconds=21600,
        quarantine_threshold=5,
        quarantine_reason="x",
    )

    assert out is None
    # Only the increment UPDATE ran; the backoff UPDATE was skipped.
    assert len(cur.executed) == 1


# ===========================================================================
# ENGINE — _persist_failure routes through record_mcp_discovery_failure
# ===========================================================================


def test_persist_failure_routes_to_record_failure(monkeypatch):
    _patch_settings(monkeypatch)
    mdb = MagicMock()
    mdb.record_mcp_discovery_failure.return_value = {
        "consecutive_failures": 1,
        "backoff_seconds": 60.0,
        "quarantined": False,
        "newly_quarantined": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    error = DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, "refused")
    mcp_discovery_engine._persist_failure("job-1", _endpoint(_EP1), error, _NOW)

    kwargs = mdb.record_mcp_discovery_failure.call_args.kwargs
    # last_discovery_status carries the specific error code, and config thresholds are threaded in.
    assert kwargs["status"] == "connect_error"
    assert kwargs["backoff_base_seconds"] == 60.0
    assert kwargs["backoff_max_seconds"] == 21600.0
    assert kwargs["quarantine_threshold"] == 5
    assert kwargs["retry_after_seconds"] is None
    # The job is still finished as failed with the structured error payload.
    finish = mdb.finish_mcp_discovery_job.call_args
    assert finish.args[1] == "failed"
    assert "error" in finish.kwargs["result"]


def test_persist_failure_threads_retry_after_for_rate_limit(monkeypatch):
    _patch_settings(monkeypatch)
    mdb = MagicMock()
    mdb.record_mcp_discovery_failure.return_value = {
        "consecutive_failures": 1,
        "backoff_seconds": 300.0,
        "quarantined": False,
        "newly_quarantined": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    error = classify_exception(McpRateLimitedError(retry_after=300))
    mcp_discovery_engine._persist_failure("job-1", _endpoint(_EP1), error, _NOW)

    kwargs = mdb.record_mcp_discovery_failure.call_args.kwargs
    assert kwargs["status"] == "rate_limited"
    # The server's Retry-After is forwarded so the backoff respects the rate limit.
    assert kwargs["retry_after_seconds"] == 300.0


def test_persist_failure_emits_quarantine_event(monkeypatch, caplog):
    _patch_settings(monkeypatch)
    mdb = MagicMock()
    mdb.record_mcp_discovery_failure.return_value = {
        "consecutive_failures": 5,
        "backoff_seconds": 960.0,
        "quarantined": True,
        "newly_quarantined": True,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    error = DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, "dead")
    with caplog.at_level("WARNING"):
        mcp_discovery_engine._persist_failure("job-1", _endpoint(_EP1), error, _NOW)

    assert any(
        "mcp endpoint quarantined" in r.message and _EP1 in r.message
        for r in caplog.records
    )


def test_persist_failure_no_quarantine_event_when_not_tripped(monkeypatch, caplog):
    _patch_settings(monkeypatch)
    mdb = MagicMock()
    mdb.record_mcp_discovery_failure.return_value = {
        "consecutive_failures": 2,
        "backoff_seconds": 120.0,
        "quarantined": False,
        "newly_quarantined": False,
    }
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)

    error = DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, "flaky")
    with caplog.at_level("WARNING"):
        mcp_discovery_engine._persist_failure("job-1", _endpoint(_EP1), error, _NOW)

    assert not any("mcp endpoint quarantined" in r.message for r in caplog.records)
