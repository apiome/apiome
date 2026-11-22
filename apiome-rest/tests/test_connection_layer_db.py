"""Connection layer against PostgreSQL — DBP-1.2 (#7185).

Uses real pooled connections (no pinned test transaction), because what is under test is the
connection itself: what a read sends, the statement ceiling, the snapshot of ``read_tx`` and an
advisory lock released from another thread. Every table it writes is a ``TEMP`` table. Skips
when no database is reachable.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Iterator, List

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

from app import database as database_module
from app.config import settings
from app.database import Database
from app.db_advisory_lock import SessionAdvisoryLock
from app.db_timeouts import StatementTimeout, long_statements
from app.statement_stats import capture
from app.sweep_runtime import close_sweep_databases, sweep_database, sweep_tick

pytestmark = pytest.mark.requires_db


@pytest.fixture
def db() -> Iterator[Database]:
    """A fresh handle on pooled connections; skips when the database is unreachable."""
    try:
        probe = psycopg2.connect(settings.effective_database_url, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    probe.close()
    handle = Database()
    try:
        yield handle
    finally:
        handle.close()


def _in_thread(fn: Any) -> Any:
    result: List[Any] = []
    errors: List[BaseException] = []

    def _run() -> None:
        try:
            result.append(fn())
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            errors.append(exc)

    thread = threading.Thread(target=_run)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0] if result else None


# ── One statement per read ──────────────────────────────────────────────────────────────────────


def test_a_read_sends_one_statement_with_no_begin_or_commit(db: Database) -> None:
    """``now()`` is the transaction's start; it equals the statement's only with no BEGIN before it."""
    with capture() as stats:
        rows = db.execute_query("SELECT now() = statement_timestamp() AS alone, 1 AS one")
    assert rows[0]["one"] == 1
    assert rows[0]["alone"] is True
    assert stats.count == 1
    # The connection is idle afterwards: nothing left "idle in transaction".
    assert db.connect().info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    assert db.connect().autocommit is False


def test_the_old_implicit_transaction_would_have_failed_the_spy(db: Database) -> None:
    """The spy is sound: under psycopg2's implicit BEGIN the two timestamps differ."""
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_sleep(0.01)")
        cur.execute("SELECT now() = statement_timestamp() AS alone")
        assert cur.fetchone()["alone"] is False
    conn.rollback()


def test_a_write_through_execute_write_commits_on_its_own(db: Database) -> None:
    db._execute_write("CREATE TEMP TABLE IF NOT EXISTS dbp12_w (id int)")
    assert db._execute_write("INSERT INTO dbp12_w VALUES (1), (2)") == 2
    conn = db.connect()
    assert conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    assert db.execute_query("SELECT count(*) AS n FROM dbp12_w")[0]["n"] == 2


def test_a_read_inside_an_open_transaction_still_commits_it(db: Database) -> None:
    """A caller that left a transaction open keeps the old behaviour (scoped autocommit)."""
    db._execute_write("CREATE TEMP TABLE IF NOT EXISTS dbp12_t (id int)")
    conn = db.connect()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO dbp12_t VALUES (7)")
    assert conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_INTRANS
    db.execute_query("SELECT 1 AS one")
    assert conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    conn.rollback()  # nothing to undo: the read committed the insert
    assert db.execute_query("SELECT count(*) AS n FROM dbp12_t WHERE id = 7")[0]["n"] == 1


# ── read_tx: one snapshot ───────────────────────────────────────────────────────────────────────


def test_read_tx_runs_reads_against_one_snapshot(db: Database) -> None:
    with db.read_tx():
        first = db.execute_query("SELECT now() AS t, current_setting('transaction_isolation') AS iso")[0]
        db.execute_query("SELECT pg_sleep(0.01)")
        second = db.execute_query("SELECT now() AS t, current_setting('transaction_read_only') AS ro")[0]
    assert first["t"] == second["t"]
    assert first["iso"] == "repeatable read"
    assert second["ro"] == "on"
    conn = db.connect()
    assert conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE
    # The session settings are back to their defaults afterwards.
    assert db.execute_query("SELECT current_setting('transaction_isolation') AS iso")[0]["iso"] == "read committed"


def test_read_tx_refuses_writes(db: Database) -> None:
    # READ ONLY still allows writes to temp tables, so the probe is DDL, which it never allows.
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        with db.read_tx():
            db.execute_query("CREATE TEMP TABLE dbp12_ro (id int); SELECT 1 AS one")
    assert db.execute_query("SELECT to_regclass('pg_temp.dbp12_ro') AS t")[0]["t"] is None
    assert db.connect().info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE


# ── Statement timeout ───────────────────────────────────────────────────────────────────────────


def test_a_statement_past_the_ceiling_fails_typed_and_long_statements_lets_it_finish(monkeypatch) -> None:
    try:
        probe = psycopg2.connect(settings.effective_database_url, connect_timeout=3)
    except psycopg2.OperationalError:
        pytest.skip("no database reachable")
    probe.close()
    monkeypatch.setattr(database_module.settings, "db_statement_timeout_ms", 200)
    handle = Database()
    try:
        assert handle.execute_query("SHOW statement_timeout")[0]["statement_timeout"] == "200ms"
        with pytest.raises(StatementTimeout) as caught:
            handle.execute_query("SELECT pg_sleep(1)")
        assert isinstance(caught.value, psycopg2.errors.QueryCanceled)
        # The connection is still usable, and idle.
        assert handle.execute_query("SELECT 1 AS one")[0]["one"] == 1
        with long_statements(5000):
            assert handle.execute_query("SHOW statement_timeout")[0]["statement_timeout"] == "5s"
            assert handle.execute_query("SELECT 1 AS one FROM pg_sleep(0.4)")[0]["one"] == 1
        # Out of the block the next statement is back under the request ceiling.
        assert handle.execute_query("SHOW statement_timeout")[0]["statement_timeout"] == "200ms"
    finally:
        handle.close()


def test_long_statements_reaches_a_to_thread_worker(db: Database) -> None:
    import asyncio

    async def _main() -> str:
        with long_statements(4321):
            return await asyncio.to_thread(lambda: db.execute_query("SHOW statement_timeout")[0]["statement_timeout"])

    assert asyncio.run(_main()) == "4321ms"


# ── Bulk writes ─────────────────────────────────────────────────────────────────────────────────


def test_bulk_insert_sends_one_statement_per_page_and_returns_rows(db: Database) -> None:
    db._execute_write("CREATE TEMP TABLE IF NOT EXISTS dbp12_b (id int PRIMARY KEY, name text)")
    rows = [(i, f"n{i}") for i in range(2500)]
    with capture() as stats:
        returned = db.bulk_insert("dbp12_b", ["id", "name"], rows, returning=["id"], page_size=1000)
    assert stats.count == 3  # 1000 + 1000 + 500
    assert [r["id"] for r in returned] == list(range(2500))
    assert db.execute_query("SELECT count(*) AS n FROM dbp12_b")[0]["n"] == 2500
    # An upsert through on_conflict.
    db.bulk_insert(
        "dbp12_b", ["id", "name"], [(1, "renamed")],
        on_conflict="ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name",
    )
    assert db.execute_query("SELECT name FROM dbp12_b WHERE id = 1")[0]["name"] == "renamed"


def test_a_failed_bulk_insert_writes_nothing(db: Database) -> None:
    db._execute_write("CREATE TEMP TABLE IF NOT EXISTS dbp12_f (id int PRIMARY KEY)")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        db.bulk_insert("dbp12_f", ["id"], [(1,), (2,), (1,)], page_size=2)
    assert db.execute_query("SELECT count(*) AS n FROM dbp12_f")[0]["n"] == 0


def test_bulk_upsert_is_one_statement_whatever_the_row_count(db: Database) -> None:
    db._execute_write(
        "CREATE TEMP TABLE IF NOT EXISTS dbp12_u (id uuid PRIMARY KEY, name text, size bigint)"
    )
    ids = [uuid.uuid4() for _ in range(3000)]
    cols = [("id", "uuid"), ("name", "text"), ("size", "bigint")]
    with capture() as stats:
        db.bulk_upsert("dbp12_u", cols, [(str(i), "a", 1) for i in ids], conflict_columns=["id"])
    assert stats.count == 1
    changed = db.bulk_upsert(
        "dbp12_u", cols, [(str(ids[0]), "b", 2)], conflict_columns=["id"], returning=["name", "size"]
    )
    assert changed == [{"name": "b", "size": 2}]
    db.bulk_upsert("dbp12_u", cols, [(str(ids[1]), "ignored", 9)], conflict_columns=["id"], update_columns=[])
    assert db.execute_query("SELECT name FROM dbp12_u WHERE id = %s", (str(ids[1]),))[0]["name"] == "a"
    assert db.execute_query("SELECT count(*) AS n FROM dbp12_u")[0]["n"] == 3000


# ── Sweeps and advisory locks ───────────────────────────────────────────────────────────────────


def _backends(application_name: str = "apiome-rest") -> int:
    conn = psycopg2.connect(settings.effective_database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM pg_stat_activity WHERE datname = current_database() "
                "AND application_name = %s",
                (application_name,),
            )
            return int(cur.fetchone()["n"])
    finally:
        conn.close()


def test_a_sweep_reuses_one_backend_across_ticks(db: Database) -> None:
    sweep_db = sweep_database()
    pids: List[int] = []

    def _tick() -> None:
        with sweep_tick(sweep_db) as thread_db:
            pids.append(thread_db.execute_query("SELECT pg_backend_pid() AS pid")[0]["pid"])

    try:
        for _ in range(4):
            _in_thread(_tick)
    finally:
        close_sweep_databases()
    assert len(set(pids)) == 1


def test_an_advisory_lock_taken_on_one_thread_is_released_from_another(db: Database) -> None:
    key = f"apiome.dbp12.{uuid.uuid4().hex}"
    lock = SessionAdvisoryLock(db, key)
    assert _in_thread(lock.acquire) is True

    other = SessionAdvisoryLock(Database(), key)
    assert other.acquire() is False  # held by the first session

    _in_thread(lock.release)
    assert not lock.held
    # Released for real: another session can take it now.
    assert other.acquire() is True
    other.release()


def test_the_old_two_thread_pattern_leaks_the_lock(db: Database) -> None:
    """Why the helper exists: lock and unlock through execute_query on two threads miss each other."""
    key = f"apiome.dbp12.{uuid.uuid4().hex}"
    take = "SELECT pg_try_advisory_lock(hashtext(%s)) AS locked"
    drop = "SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked"
    hold = threading.Event()
    done = threading.Event()

    def _locker() -> None:
        assert db.execute_query(take, (key,))[0]["locked"] is True
        hold.set()
        done.wait(timeout=5)
        db.execute_query(drop, (key,))

    thread = threading.Thread(target=_locker)
    thread.start()
    hold.wait(timeout=5)
    try:
        # Another thread, another pooled connection: its unlock does not release the lock.
        assert _in_thread(lambda: db.execute_query(drop, (key,))[0]["unlocked"]) is False
    finally:
        done.set()
        thread.join()


def test_release_connections_drops_a_forgotten_session_lock(db: Database) -> None:
    key = f"apiome.dbp12.{uuid.uuid4().hex}"
    sweep_db = sweep_database()

    def _forgetful_tick() -> None:
        with sweep_tick(sweep_db) as thread_db:
            thread_db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (key,))

    try:
        _in_thread(_forgetful_tick)
        probe = SessionAdvisoryLock(Database(), key)
        assert probe.acquire() is True
        probe.release()
    finally:
        close_sweep_databases()
