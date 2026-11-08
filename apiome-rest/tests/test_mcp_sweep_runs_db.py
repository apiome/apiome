"""MCP discovery sweep observability against a migrated database — V2-MCP-19.4 / MCAT-5.4 (#3676).

The unit tests (``test_mcp_sweep_status.py``) pin the SQL and the payload. What only a real schema
can show is the ticket's acceptance criterion — **metrics queryable; counts reconcile with job
rows** — so this module runs real sweep ticks (:func:`process_mcp_discovery_sweep`, with only the
MCP network replaced by canned outcomes) through the real :class:`~app.database.Database` on a
database migrated from empty by apiome-db, then reads the status payload back and checks:

* every counter of every run equals a direct count of that run's job rows;
* ``checked = changed + unchanged + failed + in_flight`` and ``dispatched = checked``;
* a coalesced endpoint is counted as coalesced and gets no job from the tick;
* a halted tick is recorded with no jobs;
* pruning removes runs past the retention window but keeps their jobs (``ON DELETE SET NULL``).

Everything runs inside one transaction on a dedicated connection that is always rolled back, so the
database is left exactly as it was found. Skipped without a reachable database migrated to V363.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_discovery_engine, mcp_discovery_sweep
from app.config import settings
from app.database import Database
from app.mcp_client import DiscoveryListings, DiscoverySurface, InitializeResult, McpHttpStatusError, ServerInfo
from app.mcp_sweep_status import sweep_status_payload

pytestmark = pytest.mark.requires_db

#: The engine's clock for the first tick; far enough back that every endpoint is due again later.
FIRST_TICK = datetime(2020, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _NoCommitConnection:
    """A real connection whose commits and rollbacks are swallowed, so one test is one transaction."""

    closed = False

    class _Info:
        transaction_status = TRANSACTION_STATUS_IDLE

    info = _Info()

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    @property
    def autocommit(self) -> bool:
        return False

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        pass


def _surface(*tool_names: str) -> DiscoverySurface:
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="srv", title="Srv", version="1.0"),
        capabilities={"tools": {}},
        instructions=None,
        raw={},
    )
    tools = [{"name": n, "description": "d", "inputSchema": {"type": "object"}} for n in tool_names]
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=tools))


class Sweep:
    """A tenant with MCP endpoints, and sweep ticks run against them."""

    def __init__(self, db: Database, conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db = db
        self.conn = conn
        self.monkeypatch = monkeypatch
        self.outcomes: Dict[str, Any] = {}
        suffix = uuid.uuid4().hex[:8]
        with conn.cursor() as cursor:
            # Other endpoints in the database must not be swept by these ticks.
            cursor.execute("UPDATE apiome.mcp_endpoints SET enabled = false WHERE enabled")
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"Sweep {suffix}", f"sweep-{suffix}"),
            )
            self.tenant_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', %s, 'x') "
                "RETURNING id::text AS id",
                (f"ada-{suffix}@example.com",),
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoints: Dict[str, Dict[str, Any]] = {}

        async def runner(endpoint: Dict[str, Any], _headers: Dict[str, str]) -> Any:
            outcome = self.outcomes[endpoint["slug"]]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", runner)
        monkeypatch.setattr(mcp_discovery_engine, "load_endpoint_auth_headers", lambda _id: {})

    def add(self, slug: str) -> Dict[str, Any]:
        """Catalog an endpoint (never discovered, so it is due)."""
        row = self.db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name=slug,
            base_slug=slug,
            endpoint_url=f"https://{slug}.example.com/mcp",
            transport="streamable_http",
        )
        self.endpoints[slug] = row
        return row

    def tick(self, at: datetime) -> int:
        """Run one sweep tick with the engine's clock at ``at``."""
        self.monkeypatch.setattr(mcp_discovery_engine, "_utcnow", lambda: at)
        return asyncio.run(mcp_discovery_sweep.process_mcp_discovery_sweep(self.db))

    def status(self) -> Dict[str, Any]:
        """The status payload, as ``GET /v1/ops/mcp-discovery-sweep`` builds it."""
        return sweep_status_payload(
            self.db.list_mcp_discovery_sweep_runs(50),
            settings,
            retention_days=mcp_discovery_sweep.SWEEP_RUN_RETENTION_DAYS,
        )

    def job_counts(self, run_id: str) -> Dict[str, int]:
        """Direct counts of a run's job rows — the ground truth the payload must match."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) AS checked,
                       count(*) FILTER (WHERE state = 'completed' AND result->>'changed' = 'true') AS changed,
                       count(*) FILTER (WHERE state = 'completed' AND result->>'changed' = 'false') AS unchanged,
                       count(*) FILTER (WHERE state = 'failed') AS failed,
                       count(*) FILTER (WHERE state IN ('queued', 'running')) AS in_flight
                FROM apiome.mcp_discovery_jobs WHERE sweep_run_id = %s::uuid
                """,
                (run_id,),
            )
            return {key: int(value) for key, value in cursor.fetchone().items()}

    def run_jobs(self, run_id: str) -> List[str]:
        """The slugs of the endpoints a run created jobs for."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT e.slug FROM apiome.mcp_discovery_jobs j "
                "JOIN apiome.mcp_endpoints e ON e.id = j.endpoint_id "
                "WHERE j.sweep_run_id = %s::uuid ORDER BY e.slug",
                (run_id,),
            )
            return [row["slug"] for row in cursor.fetchall()]


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch) -> Iterator[Sweep]:
    """A sweep wired to a real, migrated database inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_discovery_sweep_runs') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("V363 (mcp_discovery_sweep_runs) is not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(mcp_discovery_engine, "db", db)
    monkeypatch.setattr(settings, "mcp_discovery_enabled", True)
    monkeypatch.setattr(settings, "mcp_discovery_max_concurrency", 2)
    try:
        yield Sweep(db, conn, monkeypatch)
    finally:
        conn.rollback()
        conn.close()


def _assert_reconciles(sweep: Sweep, run: Dict[str, Any]) -> None:
    """A run's reported counters equal a direct count of its job rows."""
    truth = sweep.job_counts(run["id"])
    for key in ("checked", "changed", "unchanged", "failed", "in_flight"):
        assert run[key] == truth[key], (key, run, truth)
    assert run["checked"] == run["changed"] + run["unchanged"] + run["failed"] + run["in_flight"]
    assert run["dispatched"] == run["checked"]


# ===========================================================================
# Reconciliation
# ===========================================================================


def test_each_run_reconciles_with_its_job_rows(sweep: Sweep) -> None:
    for slug in ("alpha", "bravo", "charlie", "delta"):
        sweep.add(slug)
    sweep.outcomes.update(
        alpha=_surface("forecast"),
        bravo=_surface("radar"),
        charlie=McpHttpStatusError(503, "down"),
        delta=_surface("alerts"),
    )
    # delta already has an active manual job, so the first tick coalesces onto it.
    manual = sweep.db.enqueue_mcp_discovery_job(str(sweep.endpoints["delta"]["id"]), sweep.tenant_id, "manual")

    assert sweep.tick(FIRST_TICK) == 3

    status = sweep.status()
    first = status["last_run"]
    assert first["status"] == "completed"
    assert (first["due"], first["dispatched"], first["coalesced"], first["enqueue_failed"]) == (4, 3, 1, 0)
    assert (first["changed"], first["unchanged"], first["failed"], first["in_flight"]) == (2, 0, 1, 0)
    assert sweep.run_jobs(first["id"]) == ["alpha", "bravo", "charlie"]
    _assert_reconciles(sweep, first)
    assert first["duration_ms"] is not None and first["max_job_ms"] is not None

    # The coalesced manual job was not created by the tick and is not linked to it.
    with sweep.conn.cursor() as cursor:
        cursor.execute(
            "SELECT sweep_run_id FROM apiome.mcp_discovery_jobs WHERE id = %s::uuid",
            (str(manual["job"]["id"]),),
        )
        assert cursor.fetchone()["sweep_run_id"] is None

    # Second tick, a day later on the engine clock: alpha and bravo are unchanged, bravo changes.
    sweep.db.finish_mcp_discovery_job(str(manual["job"]["id"]), "failed", error="abandoned")
    sweep.outcomes.update(bravo=_surface("radar", "storms"), charlie=_surface("tides"))
    with sweep.conn.cursor() as cursor:
        # Make every endpoint due again and clear charlie's failure backoff.
        cursor.execute(
            "UPDATE apiome.mcp_endpoints SET last_discovered_at = %s, next_discovery_after = NULL "
            "WHERE tenant_id = %s::uuid",
            (datetime(2019, 1, 1, tzinfo=timezone.utc), sweep.tenant_id),
        )
    sweep.tick(datetime(2020, 1, 2, 12, 0, 0, tzinfo=timezone.utc))

    status = sweep.status()
    second, first_again = status["runs"][0], status["runs"][1]
    assert first_again["id"] == first["id"]
    assert (second["changed"], second["unchanged"], second["failed"]) == (3, 1, 0)
    for run in status["runs"]:
        _assert_reconciles(sweep, run)

    totals = status["totals"]
    assert totals["runs"] == 2
    assert totals["checked"] == sum(run["checked"] for run in status["runs"])
    assert totals["checked"] == totals["changed"] + totals["unchanged"] + totals["failed"] + totals["in_flight"]


def test_a_halted_tick_is_recorded_with_no_jobs(sweep: Sweep, monkeypatch: pytest.MonkeyPatch) -> None:
    sweep.add("alpha")
    sweep.outcomes["alpha"] = _surface("forecast")
    monkeypatch.setattr(settings, "mcp_discovery_enabled", False)

    assert sweep.tick(FIRST_TICK) == 0

    run = sweep.status()["last_run"]
    assert run["status"] == "halted"
    assert run["finished_at"] is not None
    assert (run["due"], run["dispatched"], run["checked"]) == (0, 0, 0)
    assert run["max_concurrency"] is None


def test_pruning_drops_old_runs_but_keeps_their_jobs(sweep: Sweep) -> None:
    sweep.add("alpha")
    sweep.outcomes["alpha"] = _surface("forecast")
    sweep.tick(FIRST_TICK)
    old_run = sweep.status()["last_run"]["id"]
    with sweep.conn.cursor() as cursor:
        cursor.execute(
            "UPDATE apiome.mcp_discovery_sweep_runs SET started_at = CURRENT_TIMESTAMP - interval '%s days' "
            "WHERE id = %s::uuid",
            (mcp_discovery_sweep.SWEEP_RUN_RETENTION_DAYS + 1, old_run),
        )
        cursor.execute(
            "SELECT id::text AS id FROM apiome.mcp_discovery_jobs WHERE sweep_run_id = %s::uuid",
            (old_run,),
        )
        (job,) = cursor.fetchall()

    sweep.tick(FIRST_TICK)

    run_ids = [run["id"] for run in sweep.status()["runs"]]
    assert old_run not in run_ids
    with sweep.conn.cursor() as cursor:
        cursor.execute(
            "SELECT sweep_run_id FROM apiome.mcp_discovery_jobs WHERE id = %s::uuid", (job["id"],)
        )
        row = cursor.fetchone()
    assert row is not None
    assert row["sweep_run_id"] is None
