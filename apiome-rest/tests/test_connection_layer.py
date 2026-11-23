"""Connection layer unit tests — DBP-1.2 (#7185).

Fakes only (no PostgreSQL): the in-use cap, long-lived sweep handles, the statement-timeout
context, the bulk-write argument checks, the pgvector registration cache and the 503 handlers.
The behaviour that needs a server (one statement per read, a real timeout, a lock released from
another thread) is in ``test_connection_layer_db.py``.
"""

from __future__ import annotations

import asyncio
import gc
import json
import threading
from typing import Any, List

import psycopg2
import pytest
from psycopg2 import errors as pg_errors
from starlette.requests import Request

from app import database as database_module
from app import db_timeouts
from app.database import ConnectionPoolExhausted, Database, connections_in_use
from app.db_advisory_lock import SessionAdvisoryLock
from app.db_bulk import bulk_insert, bulk_insert_arrays, bulk_upsert, new_ids
from app.db_timeouts import StatementTimeout, is_statement_timeout, long_statements, typed_timeout
from app.sweep_runtime import async_sweep_tick, close_sweep_databases, sweep_database, sweep_tick
from tests.advisory_lock_fakes import LockingDbMixin


class _FakeInfo:
    transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False
        self.autocommit = False
        self.info = _FakeInfo()

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        pass


@pytest.fixture
def opened(monkeypatch) -> List[_FakeConnection]:
    """Replace ``psycopg2.connect`` with a fake; return the connections it opened."""
    connections: List[_FakeConnection] = []

    def _connect(*_args: Any, **_kwargs: Any) -> _FakeConnection:
        conn = _FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(database_module.psycopg2, "connect", _connect)
    return connections


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
    gc.collect()
    if errors:
        raise errors[0]
    return result[0]


# ── The in-use cap ──────────────────────────────────────────────────────────────────────────────


def test_connections_past_the_cap_fail_with_a_clear_error(opened, monkeypatch) -> None:
    gc.collect()
    base = connections_in_use()
    monkeypatch.setattr(database_module.settings, "db_pool_max_in_use", base + 2)
    db = Database()
    held = threading.Event()
    release = threading.Event()
    ready = threading.Barrier(3)

    def _hold() -> None:
        db.connect()
        ready.wait(timeout=5)
        release.wait(timeout=5)

    threads = [threading.Thread(target=_hold) for _ in range(2)]
    for thread in threads:
        thread.start()
    ready.wait(timeout=5)
    try:
        assert connections_in_use() == base + 2
        with pytest.raises(ConnectionPoolExhausted) as caught:
            _in_thread(db.connect)
        assert caught.value.limit == base + 2
        assert "DB_POOL_MAX_IN_USE" in str(caught.value)
        assert isinstance(caught.value, psycopg2.OperationalError)
    finally:
        held.set()
        release.set()
        for thread in threads:
            thread.join()
        gc.collect()
    # The two threads ended, so their connections went back and the count fell.
    assert connections_in_use() == base
    assert _in_thread(db.connect) in opened


def test_a_zero_cap_means_no_cap(opened, monkeypatch) -> None:
    monkeypatch.setattr(database_module.settings, "db_pool_max_in_use", 0)
    db = Database()
    conns = [_in_thread(db.connect) for _ in range(3)]
    assert all(conn in opened for conn in conns)


def test_close_stops_counting_the_threads_connection(opened) -> None:
    gc.collect()
    base = connections_in_use()
    db = Database()
    db.connect()
    assert connections_in_use() == base + 1
    db.close()
    assert connections_in_use() == base


def test_checkout_counts_until_checkin(opened) -> None:
    gc.collect()
    base = connections_in_use()
    db = Database()
    conn = db.checkout()
    assert connections_in_use() == base + 1
    assert db.connect() is not conn  # not the thread's lease
    db.checkin(conn)
    assert connections_in_use() == base + 1  # only the thread's lease is left
    db.close()


# ── Long-lived sweep handles ────────────────────────────────────────────────────────────────────


def test_a_sweep_holds_one_connection_across_ticks(opened) -> None:
    """Every tick runs on a new thread, yet the sweep never opens a second connection."""
    sweep_db = sweep_database()
    seen: List[Any] = []

    def _tick() -> None:
        with sweep_tick(sweep_db) as thread_db:
            seen.append(thread_db.connect())

    for _ in range(5):
        _in_thread(_tick)
    assert len(opened) == 1
    assert all(conn is opened[0] for conn in seen)
    assert not opened[0].closed
    close_sweep_databases()
    assert opened[0].closed


def test_an_async_sweep_tick_releases_every_worker_threads_connection(opened) -> None:
    sweep_db = sweep_database()

    async def _tick() -> None:
        async with async_sweep_tick(sweep_db) as thread_db:
            await asyncio.gather(*(asyncio.to_thread(thread_db.connect) for _ in range(3)))

    asyncio.run(_tick())
    first = len(opened)
    asyncio.run(_tick())
    # The second tick reuses the pooled connections instead of opening new ones.
    assert len(opened) == first
    close_sweep_databases()


def test_a_sweep_tick_runs_under_the_long_ceiling(opened, monkeypatch) -> None:
    monkeypatch.setattr(database_module.settings, "db_long_statement_timeout_ms", 1234)
    sweep_db = sweep_database()
    with sweep_tick(sweep_db):
        assert db_timeouts.statement_timeout_override() == 1234
    assert db_timeouts.statement_timeout_override() is None
    close_sweep_databases()


def test_release_this_thread_only_leaves_other_threads_alone(opened) -> None:
    db = Database()
    other_ready = threading.Event()
    done = threading.Event()
    other: List[Any] = []

    def _other() -> None:
        other.append(db.connect())
        other_ready.set()
        done.wait(timeout=5)
        # Still this thread's connection: the other thread's release did not take it.
        other.append(db.connection)

    thread = threading.Thread(target=_other)
    thread.start()
    other_ready.wait(timeout=5)
    db.connect()
    assert db.release_connections(this_thread_only=True) == 1
    done.set()
    thread.join()
    assert other[0] is other[1]


# ── The advisory lock stays on one connection ───────────────────────────────────────────────────


class _LockDb(LockingDbMixin):
    def __init__(self, locked: bool = True) -> None:
        self.locked = locked
        self.queries: List[str] = []


def test_the_lock_is_taken_and_released_on_the_same_checked_out_connection() -> None:
    db = _LockDb()
    lock = SessionAdvisoryLock(db, "apiome.test")
    assert _in_thread(lock.acquire) is True
    assert lock.held and db.checked_out == 1
    _in_thread(lock.release)
    assert not lock.held and db.checked_out == 0
    assert ["pg_try_advisory_lock" in q for q in db.queries] == [True, False]
    assert "pg_advisory_unlock" in db.queries[1]


def test_a_held_lock_returns_its_connection_at_once() -> None:
    db = _LockDb(locked=False)
    lock = SessionAdvisoryLock(db, "apiome.test")
    assert lock.acquire() is False
    assert db.checked_out == 0
    lock.release()  # a no-op when not held
    assert len(db.queries) == 1


# ── Statement timeouts ──────────────────────────────────────────────────────────────────────────


def test_long_statements_sets_and_restores_the_override(monkeypatch) -> None:
    monkeypatch.setattr(database_module.settings, "db_long_statement_timeout_ms", 9000)
    assert db_timeouts.statement_timeout_override() is None
    with long_statements() as ceiling:
        assert ceiling == 9000
        with long_statements(5):
            assert db_timeouts.statement_timeout_override() == 5
        assert db_timeouts.statement_timeout_override() == 9000
    assert db_timeouts.statement_timeout_override() is None


def test_long_statements_follows_work_into_to_thread() -> None:
    async def _main() -> Any:
        with long_statements(777):
            return await asyncio.to_thread(db_timeouts.statement_timeout_override)

    assert asyncio.run(_main()) == 777


def test_a_negative_ceiling_is_refused() -> None:
    with pytest.raises(ValueError):
        with long_statements(-1):
            pass


def test_a_timeout_cancellation_is_typed_and_a_manual_cancel_is_not() -> None:
    timeout = pg_errors.QueryCanceled("canceling statement due to statement timeout")
    manual = pg_errors.QueryCanceled("canceling statement due to user request")
    assert is_statement_timeout(timeout) and not is_statement_timeout(manual)
    typed = typed_timeout(timeout)
    assert isinstance(typed, StatementTimeout) and isinstance(typed, pg_errors.QueryCanceled)
    assert typed_timeout(manual) is manual
    other = ValueError("x")
    assert typed_timeout(other) is other


def test_fakes_are_left_alone_by_the_timeout_housekeeping() -> None:
    conn = _FakeConnection()
    with long_statements(10):
        db_timeouts.apply_statement_timeout(conn)  # must not touch a non-psycopg2 object
    assert conn.autocommit is False


# ── Bulk writes: argument checks ────────────────────────────────────────────────────────────────


def test_bulk_insert_refuses_bad_identifiers_and_ragged_rows() -> None:
    with pytest.raises(ValueError):
        bulk_insert(object(), "apiome.t; DROP TABLE x", ["a"], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert(object(), "a.b.c", ["a"], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert(object(), "t", ['a"b'], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert(object(), "t", ["a", "a"], [(1, 2)])
    with pytest.raises(ValueError):
        bulk_insert(object(), "t", ["a", "b"], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert(object(), "t", ["a"], [(1,)], page_size=0)


def test_bulk_insert_of_no_rows_sends_nothing() -> None:
    assert bulk_insert(object(), "t", ["a"], []) == []


class _RecordingCursor:
    """Records ``execute`` calls; ``fetchall`` answers with the queued rows."""

    def __init__(self, rows=()):
        self.calls = []
        self._rows = list(rows)

    def execute(self, statement, params=None):
        self.calls.append((statement, params))

    def fetchall(self):
        return list(self._rows)


def test_bulk_insert_arrays_is_one_statement_whatever_the_row_count() -> None:
    """DBP-1.7 (#7190): each column travels as one array, so the statement text never changes."""
    columns = [("id", "uuid"), ("name", "text"), ("data", "jsonb")]
    small, large = _RecordingCursor(), _RecordingCursor()
    bulk_insert_arrays(small, "apiome.things", columns, [(i, "a", "{}") for i in new_ids(2)])
    bulk_insert_arrays(large, "apiome.things", columns, [(i, "a", "{}") for i in new_ids(5000)])
    assert len(small.calls) == len(large.calls) == 1
    assert small.calls[0][0] == large.calls[0][0] == (
        'INSERT INTO apiome.things ("id", "name", "data") '
        "SELECT * FROM unnest(%s::uuid[], %s::text[], %s::jsonb[])"
    )
    ids, names, data = large.calls[0][1]
    assert len(ids) == len(names) == len(data) == 5000 and len(set(ids)) == 5000


def test_bulk_insert_arrays_appends_the_conflict_clause_and_returning() -> None:
    cursor = _RecordingCursor(rows=[{"id": 1}])
    found = bulk_insert_arrays(
        cursor, "t", [("a", "integer")], [(1,)], on_conflict="ON CONFLICT (a) DO NOTHING", returning=["id"]
    )
    assert found == [{"id": 1}]
    assert cursor.calls[0][0].endswith('FROM unnest(%s::integer[]) ON CONFLICT (a) DO NOTHING RETURNING "id"')


def test_bulk_insert_arrays_of_no_rows_sends_nothing() -> None:
    cursor = _RecordingCursor()
    assert bulk_insert_arrays(cursor, "t", [("a", "integer")], []) == []
    assert cursor.calls == []


def test_bulk_insert_arrays_refuses_bad_identifiers_types_and_list_values() -> None:
    cursor = _RecordingCursor()
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "apiome.t; DROP TABLE x", [("a", "integer")], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "t", [('a"b', "integer")], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "t", [("a", "integer); DROP TABLE x; --")], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "t", [("a", "integer"), ("a", "integer")], [(1, 2)])
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "t", [("a", "integer"), ("b", "text")], [(1,)])
    with pytest.raises(ValueError):
        bulk_insert_arrays(cursor, "t", [], [()])
    # A Python list would become a nested array, which unnest flattens into extra rows.
    with pytest.raises(ValueError, match="is a list"):
        bulk_insert_arrays(cursor, "t", [("a", "jsonb")], [(["x"],)])
    assert cursor.calls == []


def test_new_ids_are_distinct_version_4_uuids() -> None:
    import uuid

    ids = new_ids(50)
    assert len(set(ids)) == 50 and all(uuid.UUID(value).version == 4 for value in ids)
    assert new_ids(0) == [] and new_ids(-3) == []


def test_bulk_upsert_refuses_bad_types_keys_and_repeated_keys() -> None:
    cols = [("id", "uuid"), ("name", "text")]
    with pytest.raises(ValueError):
        bulk_upsert(object(), "t", [("id", "uuid); DROP TABLE x; --")], [(1,)], conflict_columns=["id"])
    with pytest.raises(ValueError):
        bulk_upsert(object(), "t", [("id", "int[]")], [(1,)], conflict_columns=["id"])
    with pytest.raises(ValueError):
        bulk_upsert(object(), "t", cols, [(1, "a")], conflict_columns=["other"])
    with pytest.raises(ValueError):
        bulk_upsert(object(), "t", cols, [(1, "a")], conflict_columns=["id"], update_columns=["nope"])
    with pytest.raises(ValueError) as caught:
        bulk_upsert(object(), "t", cols, [(1, "a"), (1, "b")], conflict_columns=["id"])
    assert "repeat" in str(caught.value)


# ── pgvector registers once per connection ──────────────────────────────────────────────────────


def test_the_vector_adapter_registers_once_per_connection(monkeypatch) -> None:
    import pgvector.psycopg2 as pgvector_psycopg2

    calls: List[Any] = []
    monkeypatch.setattr(pgvector_psycopg2, "register_vector", lambda conn: calls.append(conn))
    db = Database()
    first, second = _FakeConnection(), _FakeConnection()
    db.vector_ready(first)
    db.vector_ready(first)
    db.vector_ready(second)
    assert calls == [first, second]


def test_a_failed_vector_registration_is_retried(monkeypatch) -> None:
    import pgvector.psycopg2 as pgvector_psycopg2

    calls: List[Any] = []

    def _fail(conn: Any) -> None:
        calls.append(conn)
        raise psycopg2.ProgrammingError("vector type not found in the database")

    monkeypatch.setattr(pgvector_psycopg2, "register_vector", _fail)
    db = Database()
    conn = _FakeConnection()
    for _ in range(2):
        with pytest.raises(psycopg2.ProgrammingError):
            db.vector_ready(conn)
    assert len(calls) == 2


# ── 503 handlers ────────────────────────────────────────────────────────────────────────────────


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/v1/x", "headers": [], "query_string": b""})


def test_a_statement_timeout_answers_503_statement_timeout() -> None:
    from app.main import statement_timeout_handler

    exc = StatementTimeout("canceling statement due to statement timeout")
    response = asyncio.run(statement_timeout_handler(_request(), exc))
    body = json.loads(response.body)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert body["error"]["type"] == "statement_timeout"


def test_an_exhausted_pool_answers_503_database_busy() -> None:
    from app.main import connection_pool_exhausted_handler

    response = asyncio.run(connection_pool_exhausted_handler(_request(), ConnectionPoolExhausted(80, 80)))
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["error"]["type"] == "database_busy"
    # The operator-facing detail (the setting's name) stays in the log, not the response.
    assert "DB_POOL_MAX_IN_USE" not in response.body.decode()
