"""Unit tests for MCP discovery sweep observability (V2-MCP-19.4 / MCAT-5.4, #3676).

Covers the four layers without a database:

* **Payload** — :func:`app.mcp_sweep_status.sweep_status_payload` shapes recent run rows and the
  sweep's settings into ``config`` / ``last_run`` / ``runs`` / ``totals``.
* **Route** — ``GET /v1/ops/mcp-discovery-sweep`` is platform-admin only, bounds ``limit`` and
  returns the payload.
* **Sweep** — every tick records a run (completed, halted, or failed when the tick raises), counts
  due / dispatched / coalesced / enqueue failures, links each job it creates to the run, and keeps
  discovering when the run row cannot be written.
* **Database** — the SQL that links jobs, prunes and records runs, and aggregates outcomes from jobs.

``test_mcp_sweep_runs_db.py`` proves the reconciliation with the job rows on a real database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_discovery_sweep
from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.mcp_sweep_status import MAX_RUN_LIMIT, sweep_run_view, sweep_status_payload

client = TestClient(app)

_AUTH = {"user_id": "u1", "tenant_id": "t1", "auth_type": "jwt"}

STARTED = datetime(2026, 11, 8, 14, 0, 0, tzinfo=timezone.utc)
FINISHED = datetime(2026, 11, 8, 14, 0, 42, tzinfo=timezone.utc)


def _settings(**overrides: Any) -> SimpleNamespace:
    base = {
        "mcp_discovery_enabled": True,
        "mcp_discovery_min_interval_seconds": 60,
        "mcp_discovery_default_cadence_seconds": 86400,
        "mcp_discovery_max_concurrency": 4,
        "mcp_discovery_endpoint_timeout_seconds": 300,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _row(**overrides: Any) -> Dict[str, Any]:
    """A run row as :meth:`Database.list_mcp_discovery_sweep_runs` returns it."""
    base = {
        "id": "run-1",
        "status": "completed",
        "started_at": STARTED,
        "finished_at": FINISHED,
        "duration_ms": 42000,
        "max_concurrency": 4,
        "endpoint_timeout_seconds": 300,
        "due_count": 5,
        "dispatched_count": 4,
        "deduplicated_count": 1,
        "enqueue_failed_count": 0,
        "jobs": 4,
        "changed": 1,
        "unchanged": 2,
        "failed": 1,
        "in_flight": 0,
        "avg_job_ms": 900,
        "max_job_ms": 2100,
    }
    base.update(overrides)
    return base


# ===========================================================================
# Payload
# ===========================================================================


def test_a_run_reports_its_timing_tick_counters_and_job_outcomes() -> None:
    assert sweep_run_view(_row()) == {
        "id": "run-1",
        "status": "completed",
        "started_at": "2026-11-08T14:00:00+00:00",
        "finished_at": "2026-11-08T14:00:42+00:00",
        "duration_ms": 42000,
        "max_concurrency": 4,
        "endpoint_timeout_seconds": 300,
        "due": 5,
        "dispatched": 4,
        "coalesced": 1,
        "enqueue_failed": 0,
        "checked": 4,
        "changed": 1,
        "unchanged": 2,
        "failed": 1,
        "in_flight": 0,
        "avg_job_ms": 900,
        "max_job_ms": 2100,
    }


def test_a_run_still_draining_or_without_jobs_reads_cleanly() -> None:
    view = sweep_run_view(
        _row(
            status="running",
            finished_at=None,
            duration_ms=None,
            jobs=None,
            changed=None,
            unchanged=None,
            failed=None,
            in_flight=None,
            avg_job_ms=None,
            max_job_ms=None,
        )
    )
    assert view["finished_at"] is None
    assert view["duration_ms"] is None
    assert (view["checked"], view["changed"], view["failed"], view["in_flight"]) == (0, 0, 0, 0)
    assert view["avg_job_ms"] is None


def test_the_payload_has_config_last_run_runs_and_totals() -> None:
    rows = [
        _row(id="run-3"),
        _row(id="run-2", status="halted", due_count=0, dispatched_count=0, deduplicated_count=0,
             jobs=0, changed=0, unchanged=0, failed=0, max_concurrency=None, endpoint_timeout_seconds=None),
        _row(id="run-1", status="failed", jobs=2, changed=0, unchanged=1, failed=0, in_flight=1,
             dispatched_count=2, due_count=2, deduplicated_count=0, enqueue_failed_count=1),
    ]
    payload = sweep_status_payload(rows, _settings(), retention_days=30)

    assert payload["config"] == {
        "enabled": True,
        "tick_seconds": 60,
        "default_cadence_seconds": 86400,
        "max_concurrency": 4,
        "endpoint_timeout_seconds": 300,
        "run_retention_days": 30,
    }
    assert payload["last_run"]["id"] == "run-3"
    assert [run["id"] for run in payload["runs"]] == ["run-3", "run-2", "run-1"]
    totals = payload["totals"]
    assert totals["runs"] == 3
    assert totals["halted_runs"] == 1
    assert totals["failed_runs"] == 1
    assert totals["due"] == 7
    assert totals["dispatched"] == 6
    assert totals["checked"] == 6
    assert totals["changed"] == 1
    assert totals["unchanged"] == 3
    assert totals["failed"] == 1
    assert totals["in_flight"] == 1
    assert totals["enqueue_failed"] == 1
    assert totals["checked"] == totals["changed"] + totals["unchanged"] + totals["failed"] + totals["in_flight"]


def test_before_the_first_run_there_is_no_last_run() -> None:
    payload = sweep_status_payload([], _settings(mcp_discovery_enabled=False), retention_days=30)
    assert payload["last_run"] is None
    assert payload["runs"] == []
    assert payload["config"]["enabled"] is False
    assert payload["totals"]["runs"] == 0
    assert payload["totals"]["checked"] == 0


# ===========================================================================
# Route
# ===========================================================================


@pytest.fixture
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_the_route_requires_a_platform_admin(_auth_override) -> None:
    with patch("app.ops_routes.db") as mdb:
        mdb.is_platform_admin.return_value = False
        response = client.get("/v1/ops/mcp-discovery-sweep")
    assert response.status_code == 403
    mdb.list_mcp_discovery_sweep_runs.assert_not_called()


def test_the_route_returns_sweep_health(_auth_override) -> None:
    with patch("app.ops_routes.db") as mdb:
        mdb.is_platform_admin.return_value = True
        mdb.list_mcp_discovery_sweep_runs.return_value = [_row()]
        response = client.get("/v1/ops/mcp-discovery-sweep?limit=5")
    assert response.status_code == 200
    mdb.list_mcp_discovery_sweep_runs.assert_called_once_with(5)
    body = response.json()
    assert set(body) == {"config", "last_run", "runs", "totals"}
    assert body["last_run"]["checked"] == 4
    assert body["config"]["run_retention_days"] == mcp_discovery_sweep.SWEEP_RUN_RETENTION_DAYS


def test_the_route_defaults_limit_to_twenty(_auth_override) -> None:
    with patch("app.ops_routes.db") as mdb:
        mdb.is_platform_admin.return_value = True
        mdb.list_mcp_discovery_sweep_runs.return_value = []
        client.get("/v1/ops/mcp-discovery-sweep")
    mdb.list_mcp_discovery_sweep_runs.assert_called_once_with(20)


@pytest.mark.parametrize("limit", [0, MAX_RUN_LIMIT + 1, -3])
def test_the_route_rejects_an_out_of_range_limit(_auth_override, limit: int) -> None:
    with patch("app.ops_routes.db") as mdb:
        mdb.is_platform_admin.return_value = True
        response = client.get(f"/v1/ops/mcp-discovery-sweep?limit={limit}")
    assert response.status_code == 422


# ===========================================================================
# The sweep records its runs
# ===========================================================================


def _endpoint(endpoint_id: str) -> Dict[str, Any]:
    return {"id": endpoint_id, "tenant_id": "t1", "endpoint_url": "https://x/mcp"}


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch):
    """Patch the sweep's settings, enqueue and run so a tick can be driven without a network."""
    settings = _settings()
    monkeypatch.setattr("app.config.settings", settings)
    calls: Dict[str, List[Any]] = {"enqueued": [], "ran": []}
    outcomes: Dict[str, Any] = {}

    async def fake_enqueue(tenant_id, endpoint, *, trigger="manual", sweep_run_id=None):
        calls["enqueued"].append((endpoint["id"], trigger, sweep_run_id))
        outcome = outcomes.get(endpoint["id"], "new")
        if outcome == "raise":
            raise RuntimeError("enqueue blew up")
        return {"id": f"job-{endpoint['id']}"}, outcome == "dedup"

    async def fake_run(job_id, endpoint, *, timeout_seconds=None):
        calls["ran"].append(job_id)

    monkeypatch.setattr(mcp_discovery_sweep, "enqueue_discovery_job", fake_enqueue)
    monkeypatch.setattr(mcp_discovery_sweep, "run_discovery_job", fake_run)
    db = MagicMock()
    db.start_mcp_discovery_sweep_run.return_value = {"id": "run-9"}
    return SimpleNamespace(db=db, settings=settings, calls=calls, outcomes=outcomes)


async def test_a_tick_records_its_counters_and_links_its_jobs(sweep) -> None:
    sweep.db.list_due_mcp_endpoints.return_value = [_endpoint("a"), _endpoint("b"), _endpoint("c"), _endpoint("d")]
    sweep.outcomes.update({"b": "dedup", "c": "raise"})

    dispatched = await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db)

    assert dispatched == 2
    sweep.db.start_mcp_discovery_sweep_run.assert_called_once_with(
        max_concurrency=4,
        endpoint_timeout_seconds=300,
        retention_days=mcp_discovery_sweep.SWEEP_RUN_RETENTION_DAYS,
    )
    assert {run_id for _, _, run_id in sweep.calls["enqueued"]} == {"run-9"}
    assert sorted(sweep.calls["ran"]) == ["job-a", "job-d"]
    sweep.db.finish_mcp_discovery_sweep_run.assert_called_once_with(
        "run-9",
        status="completed",
        due_count=4,
        dispatched_count=2,
        deduplicated_count=1,
        enqueue_failed_count=1,
    )


async def test_a_tick_with_nothing_due_is_still_recorded(sweep) -> None:
    sweep.db.list_due_mcp_endpoints.return_value = []

    assert await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db) == 0

    sweep.db.finish_mcp_discovery_sweep_run.assert_called_once_with(
        "run-9", status="completed", due_count=0, dispatched_count=0,
        deduplicated_count=0, enqueue_failed_count=0,
    )


async def test_a_halted_tick_is_recorded_as_halted(sweep) -> None:
    sweep.settings.mcp_discovery_enabled = False

    assert await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db) == 0

    sweep.db.list_due_mcp_endpoints.assert_not_called()
    sweep.db.start_mcp_discovery_sweep_run.assert_called_once_with(
        max_concurrency=None,
        endpoint_timeout_seconds=None,
        retention_days=mcp_discovery_sweep.SWEEP_RUN_RETENTION_DAYS,
    )
    assert sweep.db.finish_mcp_discovery_sweep_run.call_args.kwargs["status"] == "halted"


async def test_a_tick_that_raises_is_recorded_as_failed_and_reraises(sweep) -> None:
    sweep.db.list_due_mcp_endpoints.side_effect = RuntimeError("due-selection failed")

    with pytest.raises(RuntimeError, match="due-selection failed"):
        await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db)

    assert sweep.db.finish_mcp_discovery_sweep_run.call_args.kwargs["status"] == "failed"


async def test_discovery_continues_when_the_run_cannot_be_recorded(sweep) -> None:
    sweep.db.start_mcp_discovery_sweep_run.side_effect = RuntimeError("table missing")
    sweep.db.list_due_mcp_endpoints.return_value = [_endpoint("a")]

    assert await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db) == 1

    assert sweep.calls["enqueued"] == [("a", "sweep", None)]
    assert sweep.calls["ran"] == ["job-a"]
    sweep.db.finish_mcp_discovery_sweep_run.assert_not_called()


async def test_a_failure_to_record_the_end_does_not_fail_the_tick(sweep) -> None:
    sweep.db.finish_mcp_discovery_sweep_run.side_effect = RuntimeError("write failed")
    sweep.db.list_due_mcp_endpoints.return_value = [_endpoint("a")]

    assert await mcp_discovery_sweep.process_mcp_discovery_sweep(sweep.db) == 1


# ===========================================================================
# Database SQL
# ===========================================================================


def _capturing_db(monkeypatch: pytest.MonkeyPatch, rows: Any = None) -> SimpleNamespace:
    db = Database()
    seen: Dict[str, List[Any]] = {"query": [], "write": []}

    def fake_query(query, params=None):
        seen["query"].append((" ".join(query.split()), params))
        return rows if rows is not None else [{"id": "run-1"}]

    def fake_write(query, params=None):
        seen["write"].append((" ".join(query.split()), params))
        return 1

    monkeypatch.setattr(db, "execute_query", fake_query)
    monkeypatch.setattr(db, "_execute_write", fake_write)
    return SimpleNamespace(db=db, seen=seen)


def test_starting_a_run_prunes_old_runs_then_inserts(monkeypatch) -> None:
    cap = _capturing_db(monkeypatch)
    row = cap.db.start_mcp_discovery_sweep_run(
        max_concurrency=4, endpoint_timeout_seconds=300, retention_days=30
    )
    assert row == {"id": "run-1"}
    (delete_sql, delete_params), = cap.seen["write"]
    assert delete_sql.startswith("DELETE FROM apiome.mcp_discovery_sweep_runs WHERE started_at <")
    assert delete_params == (30,)
    (insert_sql, insert_params), = cap.seen["query"]
    assert "INSERT INTO apiome.mcp_discovery_sweep_runs (started_at, max_concurrency, endpoint_timeout_seconds) VALUES (clock_timestamp(), %s, %s)" in insert_sql
    assert insert_params == (4, 300)


def test_a_retention_below_one_day_is_refused(monkeypatch) -> None:
    cap = _capturing_db(monkeypatch)
    with pytest.raises(ValueError):
        cap.db.start_mcp_discovery_sweep_run(max_concurrency=1, endpoint_timeout_seconds=1, retention_days=0)
    assert cap.seen["write"] == []


def test_finishing_a_run_records_status_and_counters(monkeypatch) -> None:
    cap = _capturing_db(monkeypatch)
    cap.db.finish_mcp_discovery_sweep_run(
        "run-1", status="completed", due_count=5, dispatched_count=4,
        deduplicated_count=1, enqueue_failed_count=0,
    )
    (sql, params), = cap.seen["write"]
    assert sql.startswith("UPDATE apiome.mcp_discovery_sweep_runs SET finished_at = clock_timestamp()")
    assert params == ("completed", 5, 4, 1, 0, "run-1")


def test_an_unknown_run_status_is_refused(monkeypatch) -> None:
    cap = _capturing_db(monkeypatch)
    with pytest.raises(ValueError):
        cap.db.finish_mcp_discovery_sweep_run("run-1", status="running")


def test_listing_aggregates_outcomes_from_the_linked_jobs(monkeypatch) -> None:
    cap = _capturing_db(monkeypatch, rows=[])
    cap.db.list_mcp_discovery_sweep_runs(7)
    (sql, params), = cap.seen["query"]
    assert params == (7,)
    assert "LEFT JOIN LATERAL" in sql
    assert "FROM apiome.mcp_discovery_jobs WHERE sweep_run_id = r.id" in sql
    assert "ORDER BY r.started_at DESC LIMIT %s" in sql
    for alias in ("AS jobs", "AS changed", "AS unchanged", "AS failed", "AS in_flight", "AS duration_ms"):
        assert alias in sql


def test_enqueue_links_the_job_to_its_sweep_run(monkeypatch) -> None:
    db = Database()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, {"id": "job-1"}]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(db, "connect", lambda: conn)

    result = db.enqueue_mcp_discovery_job("ep-1", "t1", "sweep", sweep_run_id="run-9")

    assert result == {"job": {"id": "job-1"}, "deduplicated": False}
    insert_sql, insert_params = cursor.execute.call_args_list[-1].args
    assert "sweep_run_id" in insert_sql
    assert insert_params == ("ep-1", "t1", "sweep", "run-9")
