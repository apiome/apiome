"""MCP endpoint health / uptime monitoring against a migrated database — V2-MCP-27.3 / MCAT-13.3 (#3713).

The unit tests pin the SQL. What only a real schema can show is the acceptance criterion —
**health/latency recorded per endpoint; the badge reflects recent status** — so this module runs real
sweep ticks (:func:`process_mcp_health_sweep`, with only the network probe replaced) through the real
:class:`~app.database.Database` on a database migrated by apiome-db, and checks that:

* each due endpoint gets one probe row with its status, latency and error code;
* disabled, deleted and stdio endpoints are never probed, quarantined ones are;
* a freshly probed endpoint is not due again until its cadence elapses;
* the history read is per endpoint, newest first and windowed, and its summary is the badge status;
* pruning removes probes past retention, and deleting an endpoint removes its history.

Everything runs inside one transaction on a dedicated connection that is always rolled back.
Skipped without a reachable database migrated to V364.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Iterator

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app import mcp_health_sweep
from app.config import settings
from app.database import Database
from app.mcp_health import summarize_health_checks
from app.mcp_health_sweep import ProbeResult

pytestmark = pytest.mark.requires_db


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


class Monitor:
    """A tenant with MCP endpoints, and health-sweep ticks run against them."""

    def __init__(self, db: Database, conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        self.db = db
        self.conn = conn
        self.results: Dict[str, ProbeResult] = {}
        suffix = uuid.uuid4().hex[:8]
        with conn.cursor() as cursor:
            # Other endpoints in the database must not be probed by these ticks.
            cursor.execute("UPDATE apiome.mcp_endpoints SET enabled = false WHERE enabled")
            cursor.execute(
                "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
                (f"Health {suffix}", f"health-{suffix}"),
            )
            self.tenant_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO apiome.users (name, email, password) VALUES ('Ada', %s, 'x') "
                "RETURNING id::text AS id",
                (f"ada-{suffix}@example.com",),
            )
            self.user_id = cursor.fetchone()["id"]
        self.endpoints: Dict[str, Dict[str, Any]] = {}

        async def _probe(endpoint: Dict[str, Any], _timeout: float) -> ProbeResult:
            return self.results.get(endpoint["slug"], ProbeResult("up", 40))

        monkeypatch.setattr(mcp_health_sweep, "probe_endpoint", _probe)

    def add(self, slug: str, *, transport: str = "streamable_http") -> Dict[str, Any]:
        row = self.db.insert_mcp_endpoint(
            tenant_id=self.tenant_id,
            creator_id=self.user_id,
            name=slug,
            base_slug=slug,
            endpoint_url=f"https://{slug}.example.com/mcp",
            transport=transport,
        )
        self.endpoints[slug] = row
        return row

    def sql(self, query: str, params: tuple = ()) -> None:
        with self.conn.cursor() as cursor:
            cursor.execute(query, params)

    def tick(self) -> int:
        return asyncio.run(mcp_health_sweep.process_mcp_health_sweep(self.db))

    def probed_slugs(self) -> list:
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT e.slug FROM apiome.mcp_endpoint_health_checks h "
                "JOIN apiome.mcp_endpoints e ON e.id = h.endpoint_id "
                "WHERE e.tenant_id = %s::uuid ORDER BY e.slug",
                (self.tenant_id,),
            )
            return [row["slug"] for row in cursor.fetchall()]

    def backdate(self, slug: str, hours: float) -> None:
        """Move every probe of ``slug`` ``hours`` into the past."""
        self.sql(
            "UPDATE apiome.mcp_endpoint_health_checks "
            "SET checked_at = checked_at - make_interval(secs => %s) WHERE endpoint_id = %s::uuid",
            (hours * 3600, self.endpoints[slug]["id"]),
        )


@pytest.fixture
def monitor(monkeypatch: pytest.MonkeyPatch) -> Iterator[Monitor]:
    """A health sweep wired to a real, migrated database inside one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(
            settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3
        )
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute("SELECT to_regclass('apiome.mcp_endpoint_health_checks') IS NOT NULL AS ok")
        ready = probe.fetchone()["ok"]
    if not ready:
        conn.close()
        pytest.skip("V364 (mcp_endpoint_health_checks) is not applied")

    db = Database()
    db.connection = _NoCommitConnection(conn)
    monkeypatch.setattr(settings, "mcp_health_enabled", True)
    monkeypatch.setattr(settings, "mcp_health_cadence_seconds", 300)
    monkeypatch.setattr(settings, "mcp_health_max_concurrency", 2)
    monkeypatch.setattr(settings, "mcp_health_max_per_tick", 200)
    try:
        yield Monitor(db, conn, monkeypatch)
    finally:
        conn.rollback()
        conn.close()


def test_tick_records_status_latency_and_error_per_endpoint(monitor: Monitor) -> None:
    monitor.add("alpha")
    beta = monitor.add("beta")
    monitor.results["beta"] = ProbeResult("down", 1500, "connect_error")

    assert monitor.tick() == 2

    rows = monitor.db.list_mcp_health_checks(str(beta["id"]), window_hours=24, limit=10)
    assert len(rows) == 1
    assert rows[0]["status"] == "down"
    assert rows[0]["latency_ms"] == 1500
    assert rows[0]["error_code"] == "connect_error"
    assert monitor.probed_slugs() == ["alpha", "beta"]


def test_only_live_enabled_network_endpoints_are_probed(monitor: Monitor) -> None:
    monitor.add("live")
    off = monitor.add("off")
    gone = monitor.add("gone")
    monitor.add("local", transport="stdio")
    held = monitor.add("held")
    monitor.sql("UPDATE apiome.mcp_endpoints SET enabled = false WHERE id = %s::uuid", (off["id"],))
    monitor.sql(
        "UPDATE apiome.mcp_endpoints SET deleted_at = now() WHERE id = %s::uuid", (gone["id"],)
    )
    monitor.sql(
        "UPDATE apiome.mcp_endpoints SET quarantined_at = now(), "
        "next_discovery_after = now() + interval '1 day' WHERE id = %s::uuid",
        (held["id"],),
    )

    monitor.tick()

    assert monitor.probed_slugs() == ["held", "live"]


def test_probed_endpoint_is_due_again_only_after_its_cadence(monitor: Monitor) -> None:
    monitor.add("alpha")
    assert monitor.tick() == 1
    assert monitor.tick() == 0  # just probed
    monitor.backdate("alpha", hours=0.1)  # 6 minutes > the 5-minute cadence
    assert monitor.tick() == 1


def test_history_is_windowed_newest_first_and_summarizes_to_the_badge_status(
    monitor: Monitor,
) -> None:
    alpha = monitor.add("alpha")
    endpoint_id = str(alpha["id"])
    for status in ("up", "up", "down"):
        monitor.db.record_mcp_health_check(endpoint_id, status=status, latency_ms=10, error_code=None)
    monitor.backdate("alpha", hours=30)  # outside the 24h window
    monitor.db.record_mcp_health_check(endpoint_id, status="up", latency_ms=20, error_code=None)
    monitor.db.record_mcp_health_check(
        endpoint_id, status="down", latency_ms=99, error_code="timeout"
    )

    day = monitor.db.list_mcp_health_checks(endpoint_id, window_hours=24, limit=100)
    assert [r["status"] for r in day] == ["down", "up"]
    assert summarize_health_checks(day).status == "down"
    assert summarize_health_checks(day).last_error_code == "timeout"

    week = monitor.db.list_mcp_health_checks(endpoint_id, window_hours=168, limit=100)
    assert len(week) == 5
    assert [r["checked_at"] for r in week] == sorted((r["checked_at"] for r in week), reverse=True)


def test_prune_and_cascade_remove_history(monitor: Monitor) -> None:
    alpha = monitor.add("alpha")
    beta = monitor.add("beta")
    monitor.tick()
    monitor.backdate("alpha", hours=24 * 40)

    assert monitor.db.prune_mcp_health_checks(retention_days=30) >= 1
    assert monitor.db.list_mcp_health_checks(str(alpha["id"]), window_hours=168 * 10, limit=10) == []

    monitor.sql("DELETE FROM apiome.mcp_endpoints WHERE id = %s::uuid", (beta["id"],))
    with monitor.conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) AS n FROM apiome.mcp_endpoint_health_checks WHERE endpoint_id = %s::uuid",
            (beta["id"],),
        )
        assert cursor.fetchone()["n"] == 0
