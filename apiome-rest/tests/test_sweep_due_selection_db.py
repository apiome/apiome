"""Indexed sweep due-selection against a live Postgres (DBP-1.18, #7201).

What only the real schema can prove:

* the V426 triggers keep each "next due" column current as the rows it depends on change —
  including a branch rule moving its repository's due instant;
* the rewritten due queries return exactly the rows the per-row interval predicates returned,
  most overdue first, at most one batch;
* a health probe advances ``last_health_checked_at`` and never moves it backwards;
* the discovery-job retention prune keeps live jobs and each endpoint's newest finished ones;
* the schema-suite prune keeps each suite's newest runs.

Everything runs inside one transaction that is always rolled back. Skipped when no database is
reachable or V426 is not applied.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple

import psycopg2
import pytest
from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import RealDictCursor

from app.config import settings
from app.database import Database

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


@pytest.fixture
def tx() -> Iterator[Tuple[Database, Any]]:
    """A :class:`Database` and a raw cursor over one always-rolled-back transaction."""
    try:
        conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    with conn.cursor() as probe:
        probe.execute(
            """SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome'
                              AND table_name = 'tenant_repositories' AND column_name = 'refresh_due_at') AS v426,
                      (SELECT id FROM apiome.users LIMIT 1) AS u"""
        )
        found = probe.fetchone()
    if not found["v426"] or not found["u"]:
        conn.close()
        pytest.skip("V426 not applied or no user to own the seed rows")
    db = Database()
    db.connection = _NoCommitConnection(conn)
    try:
        with conn.cursor() as cursor:
            # Rows of other tests' tenants must not leak into a due list: hide them by moving every
            # pre-existing row out of the sweep (rolled back with the transaction).
            cursor.execute("UPDATE apiome.mcp_endpoints SET enabled = false WHERE enabled")
            cursor.execute(
                "UPDATE apiome.tenant_repositories SET auto_refresh_enabled = false WHERE auto_refresh_enabled"
            )
            cursor.execute("UPDATE apiome.mcp_catalog_digest_configs SET enabled = false WHERE enabled")
            yield db, cursor
    finally:
        conn.rollback()
        conn.close()


def _tenant(cursor: Any) -> Tuple[str, str]:
    """A fresh tenant and a user id."""
    cursor.execute("SELECT id::text AS id FROM apiome.users LIMIT 1")
    user = cursor.fetchone()["id"]
    suffix = uuid.uuid4().hex[:10]
    cursor.execute(
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"sweep {suffix}", f"sweep-{suffix}"),
    )
    return cursor.fetchone()["id"], user


def _endpoint(
    cursor: Any,
    tenant: str,
    user: str,
    *,
    cadence: Optional[int] = None,
    last: Optional[str] = None,
    backoff: Optional[str] = None,
    transport: str = "streamable_http",
) -> str:
    """Insert one enabled endpoint; ``last`` / ``backoff`` are SQL interval offsets from now."""
    slug = f"ep-{uuid.uuid4().hex[:10]}"
    cursor.execute(
        f"""INSERT INTO apiome.mcp_endpoints
                (tenant_id, creator_id, name, slug, endpoint_url, transport, enabled,
                 discovery_cadence_seconds, last_discovered_at, next_discovery_after)
            VALUES (%s, %s, %s, %s, 'https://mcp.example/' || %s, %s, true, %s,
                    {f"now() - interval '{last}'" if last else "NULL"},
                    {f"now() + interval '{backoff}'" if backoff else "NULL"})
            RETURNING id::text AS id""",
        (tenant, user, slug, slug, slug, transport, cadence),
    )
    return cursor.fetchone()["id"]


def _due_ids(rows: List[Dict[str, Any]]) -> List[str]:
    return [str(row["id"]) for row in rows]


# ---------------------------------------------------------------------------------------------
# MCP discovery
# ---------------------------------------------------------------------------------------------


def test_discovery_due_at_follows_the_columns_it_depends_on(tx) -> None:
    _db, cursor = tx
    tenant, user = _tenant(cursor)
    ep = _endpoint(cursor, tenant, user, cadence=600, last="5 minutes")

    def due_at() -> Any:
        cursor.execute("SELECT discovery_due_at, last_discovered_at FROM apiome.mcp_endpoints WHERE id = %s", (ep,))
        return cursor.fetchone()

    row = due_at()
    assert row["discovery_due_at"] == row["last_discovered_at"] + timedelta(seconds=600)
    # The backoff pushes it back.
    cursor.execute(
        "UPDATE apiome.mcp_endpoints SET next_discovery_after = now() + interval '1 day' WHERE id = %s", (ep,)
    )
    cursor.execute(
        "SELECT discovery_due_at > now() + interval '23 hours' AS later FROM apiome.mcp_endpoints WHERE id = %s", (ep,)
    )
    assert cursor.fetchone()["later"] is True
    # Clearing the cadence hands the endpoint to the global default: no stored due instant.
    cursor.execute("UPDATE apiome.mcp_endpoints SET discovery_cadence_seconds = NULL WHERE id = %s", (ep,))
    assert due_at()["discovery_due_at"] is None
    # Never discovered with its own cadence: due at once.
    cursor.execute(
        "UPDATE apiome.mcp_endpoints SET discovery_cadence_seconds = 60, last_discovered_at = NULL, "
        "next_discovery_after = NULL WHERE id = %s",
        (ep,),
    )
    cursor.execute(
        "SELECT discovery_due_at = '-infinity'::timestamptz AS never FROM apiome.mcp_endpoints WHERE id = %s", (ep,)
    )
    assert cursor.fetchone()["never"] is True


def test_list_due_mcp_endpoints_matches_the_per_row_cadence_rule(tx) -> None:
    db, cursor = tx
    tenant, user = _tenant(cursor)
    never_default = _endpoint(cursor, tenant, user)
    overdue_default = _endpoint(cursor, tenant, user, last="2 hours")
    fresh_default = _endpoint(cursor, tenant, user, last="10 minutes")
    backed_off_default = _endpoint(cursor, tenant, user, last="2 hours", backoff="1 hour")
    never_own = _endpoint(cursor, tenant, user, cadence=300)
    overdue_own = _endpoint(cursor, tenant, user, cadence=300, last="30 minutes")
    fresh_own = _endpoint(cursor, tenant, user, cadence=7200, last="30 minutes")
    backed_off_own = _endpoint(cursor, tenant, user, cadence=300, last="30 minutes", backoff="1 hour")
    quarantined = _endpoint(cursor, tenant, user, last="2 hours")
    cursor.execute("UPDATE apiome.mcp_endpoints SET quarantined_at = now() WHERE id = %s", (quarantined,))

    rows = db.list_due_mcp_endpoints(default_cadence_seconds=3600)
    ids = _due_ids(rows)
    assert set(ids) == {never_default, overdue_default, never_own, overdue_own}
    assert not {fresh_default, backed_off_default, fresh_own, backed_off_own, quarantined} & set(ids)
    # Never-discovered first, then oldest discovery.
    assert set(ids[:2]) == {never_default, never_own}
    assert ids[2:] == [overdue_default, overdue_own]
    # One batch at most.
    assert len(db.list_due_mcp_endpoints(default_cadence_seconds=3600, limit=1)) == 1


def test_list_due_mcp_health_endpoints_reads_the_stored_latest_probe(tx) -> None:
    db, cursor = tx
    tenant, user = _tenant(cursor)
    never = _endpoint(cursor, tenant, user)
    probed = _endpoint(cursor, tenant, user)
    stdio = _endpoint(cursor, tenant, user, transport="stdio")
    db.record_mcp_health_check(probed, status="up", latency_ms=12, error_code=None)

    cursor.execute(
        "SELECT last_health_checked_at = (SELECT max(checked_at) FROM apiome.mcp_endpoint_health_checks "
        "WHERE endpoint_id = %s) AS stamped FROM apiome.mcp_endpoints WHERE id = %s",
        (probed, probed),
    )
    assert cursor.fetchone()["stamped"] is True
    due = _due_ids(db.list_due_mcp_health_endpoints(cadence_seconds=300, limit=10))
    assert never in due and probed not in due and stdio not in due

    # A probe written with an older timestamp never moves the stamp backwards.
    cursor.execute("SELECT last_health_checked_at FROM apiome.mcp_endpoints WHERE id = %s", (probed,))
    stamp = cursor.fetchone()["last_health_checked_at"]
    cursor.execute(
        "UPDATE apiome.mcp_endpoints SET last_health_checked_at = %s WHERE id = %s", (stamp + timedelta(days=1), probed)
    )
    db.record_mcp_health_check(probed, status="down", latency_ms=None, error_code="timeout")
    cursor.execute("SELECT last_health_checked_at FROM apiome.mcp_endpoints WHERE id = %s", (probed,))
    assert cursor.fetchone()["last_health_checked_at"] == stamp + timedelta(days=1)


# ---------------------------------------------------------------------------------------------
# Repository refresh
# ---------------------------------------------------------------------------------------------


def _repository(cursor: Any, tenant: str, *, interval: int = 300, last: Optional[str] = None) -> str:
    name = f"org/{uuid.uuid4().hex[:10]}"
    cursor.execute(
        f"""INSERT INTO apiome.tenant_repositories
                (tenant_id, source, provider, clone_url, clone_url_normalized, repository_full_name,
                 status, auto_refresh_enabled, refresh_interval_seconds, last_refreshed_at)
            VALUES (%s, 'public_url', 'github', 'https://github.com/' || %s, 'github.com/' || %s, %s,
                    'ready', true, %s, {f"now() - interval '{last}'" if last else "NULL"})
            RETURNING id::text AS id""",
        (tenant, name, name, name, interval),
    )
    return cursor.fetchone()["id"]


def test_refresh_due_at_folds_in_branch_rules(tx) -> None:
    _db, cursor = tx
    tenant, _user = _tenant(cursor)
    repo = _repository(cursor, tenant, interval=3600, last="10 minutes")

    def offset() -> float:
        cursor.execute(
            "SELECT extract(epoch FROM refresh_due_at - last_refreshed_at) AS s"
            " FROM apiome.tenant_repositories WHERE id = %s",
            (repo,),
        )
        return float(cursor.fetchone()["s"])

    assert offset() == 3600
    cursor.execute(
        """INSERT INTO apiome.repository_branch_refresh_rule
               (tenant_id, repository_id, branch_pattern, refresh_interval_seconds)
           VALUES (%s, %s, 'release/*', 600) RETURNING id::text AS id""",
        (tenant, repo),
    )
    rule = cursor.fetchone()["id"]
    assert offset() == 600
    cursor.execute("UPDATE apiome.repository_branch_refresh_rule SET refresh_enabled = false WHERE id = %s", (rule,))
    assert offset() == 3600
    cursor.execute("UPDATE apiome.repository_branch_refresh_rule SET refresh_enabled = true WHERE id = %s", (rule,))
    cursor.execute("DELETE FROM apiome.repository_branch_refresh_rule WHERE id = %s", (rule,))
    assert offset() == 3600
    cursor.execute("UPDATE apiome.tenant_repositories SET refresh_interval_seconds = 900 WHERE id = %s", (repo,))
    assert offset() == 900


def test_list_due_repositories_matches_the_per_row_cadence_rule(tx) -> None:
    db, cursor = tx
    tenant, _user = _tenant(cursor)
    never = _repository(cursor, tenant)
    overdue = _repository(cursor, tenant, interval=600, last="1 hour")
    fresh = _repository(cursor, tenant, interval=7200, last="1 hour")
    rule_due = _repository(cursor, tenant, interval=7200, last="1 hour")
    cursor.execute(
        """INSERT INTO apiome.repository_branch_refresh_rule
               (tenant_id, repository_id, branch_pattern, refresh_interval_seconds)
           VALUES (%s, %s, 'main', 900)""",
        (tenant, rule_due),
    )
    # Its own cadence (60 s) is below the floor: the floor still wins.
    under_floor = _repository(cursor, tenant, interval=60, last="5 minutes")
    backed_off = _repository(cursor, tenant, interval=600, last="1 hour")
    cursor.execute(
        "UPDATE apiome.tenant_repositories SET refresh_backoff_until = now() + interval '1 hour' WHERE id = %s",
        (backed_off,),
    )

    ids = _due_ids(db.list_due_repositories(floor_seconds=600))
    assert ids[0] == never
    assert set(ids) == {never, overdue, rule_due}
    assert not {fresh, under_floor, backed_off} & set(ids)
    assert len(db.list_due_repositories(floor_seconds=600, limit=2)) == 2


# ---------------------------------------------------------------------------------------------
# Catalog digests
# ---------------------------------------------------------------------------------------------


def test_list_due_mcp_catalog_digests_matches_the_per_tenant_cadence_rule(tx) -> None:
    db, cursor = tx
    tenants = [_tenant(cursor)[0] for _ in range(5)]
    rows = [
        (tenants[0], None, None),  # never sent, default cadence
        (tenants[1], None, "2 days"),  # default cadence, overdue
        (tenants[2], None, "1 hour"),  # default cadence, fresh
        (tenants[3], 600, "1 hour"),  # own cadence, overdue
        (tenants[4], 86400 * 7, "1 day"),  # own cadence, fresh
    ]
    for tenant, cadence, last in rows:
        cursor.execute(
            f"""INSERT INTO apiome.mcp_catalog_digest_configs (tenant_id, enabled, cadence_seconds, last_digest_at)
                VALUES (%s, true, %s, {f"now() - interval '{last}'" if last else "NULL"})""",
            (tenant, cadence),
        )
    due = [str(row["tenant_id"]) for row in db.list_due_mcp_catalog_digests(default_cadence_seconds=86400)]
    assert due == [tenants[0], tenants[1], tenants[3]]
    assert len(db.list_due_mcp_catalog_digests(default_cadence_seconds=86400, limit=1)) == 1


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


def test_discovery_job_prune_keeps_live_jobs_and_each_endpoints_newest(tx) -> None:
    db, cursor = tx
    tenant, user = _tenant(cursor)
    busy = _endpoint(cursor, tenant, user)
    quiet = _endpoint(cursor, tenant, user)
    now = datetime.now(timezone.utc)

    def job(endpoint: str, state: str, days_ago: int) -> str:
        cursor.execute(
            """INSERT INTO apiome.mcp_discovery_jobs (endpoint_id, tenant_id, state, trigger, created_at)
               VALUES (%s, %s, %s, 'sweep', %s) RETURNING id::text AS id""",
            (endpoint, tenant, state, now - timedelta(days=days_ago)),
        )
        return cursor.fetchone()["id"]

    busy_old = [job(busy, "completed", 60 + n) for n in range(5)]
    busy_recent = job(busy, "failed", 1)
    busy_queued_old = job(busy, "queued", 90)
    quiet_old = [job(quiet, "completed", 100 + n) for n in range(2)]

    # Other tenants' expired jobs may share the table: walk every window to the end.
    deleted, after = 0, None
    while True:
        result = db.prune_mcp_discovery_jobs(retention_days=30, keep_per_endpoint=2, limit=3, after=after)
        deleted += result["deleted"]
        after = result["next"]
        if after is None:
            break
    cursor.execute("SELECT id::text AS id FROM apiome.mcp_discovery_jobs WHERE tenant_id = %s", (tenant,))
    left = {row["id"] for row in cursor.fetchall()}
    # busy keeps its two newest finished jobs (the recent one and the newest old one) and its queued job.
    assert left == {busy_recent, busy_old[0], busy_queued_old, *quiet_old}
    assert deleted >= 4
    assert db.prune_mcp_discovery_jobs(retention_days=0, keep_per_endpoint=0, limit=100)["deleted"] == 0


def test_schema_suite_prune_keeps_each_suites_newest_runs(tx) -> None:
    db, cursor = tx
    cursor.execute(
        "SELECT count(*) AS n FROM information_schema.columns"
        " WHERE table_schema = 'apiome' AND table_name = 'schema_test_suite_runs'"
    )
    if not cursor.fetchone()["n"]:
        pytest.skip("schema suites not migrated")
    # The behaviour is covered by tests/test_schema_suite_retention.py; here the statement runs on
    # the real schema and keeps its index-friendly shape: no window function over the whole table.
    captured: Dict[str, Any] = {}
    original = db._execute_write

    def _capture(sql: str, params: Any = None) -> int:
        captured["sql"] = sql
        return original(sql, params)

    db._execute_write = _capture  # type: ignore[method-assign]
    db.prune_schema_suite_runs_by_age(datetime.now(timezone.utc) - timedelta(days=30), keep_min=3)
    assert "ROW_NUMBER" not in captured["sql"]
    assert "OFFSET %s LIMIT 1" in captured["sql"]


def test_grade_movements_pair_each_window_snapshot_with_the_previous_scored_one(tx) -> None:
    db, cursor = tx
    tenant, user = _tenant(cursor)
    ep = _endpoint(cursor, tenant, user)
    now = datetime.now(timezone.utc)
    # seq: (days ago, grade or None for "not scored"). Seq 3 is unscored, so seq 4 pairs with seq 2.
    history = {1: (20, "B"), 2: (10, "C"), 3: (5, None), 4: (3, "A"), 5: (2, "A"), 6: (1, "B")}
    for seq, (days_ago, grade) in history.items():
        cursor.execute(
            """INSERT INTO apiome.mcp_endpoint_versions (endpoint_id, version_seq, version_tag, discovered_at)
               VALUES (%s, %s, %s, %s) RETURNING id::text AS id""",
            (ep, seq, f"v{seq}", now - timedelta(days=days_ago)),
        )
        version = cursor.fetchone()["id"]
        if grade is not None:
            cursor.execute(
                "INSERT INTO apiome.mcp_version_scores (version_id, grade) VALUES (%s, %s)", (version, grade)
            )

    rows = db.list_mcp_grade_movements_in_window(tenant, now - timedelta(days=7), now)
    # The window is the last 7 days: seq 4 (C -> A, previous scored snapshot predates the window),
    # seq 5 is unchanged (A -> A), seq 6 (A -> B). Newest first.
    assert [(r["version_seq"], r["prev_grade"], r["new_grade"]) for r in rows] == [(6, "A", "B"), (4, "C", "A")]
    assert all(r["endpoint_slug"] and r["endpoint_name"] for r in rows)
