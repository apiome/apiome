"""Per-thread pooled connections on ``Database`` (no shared connection across threads)."""

import gc
import threading

import psycopg2
import pytest

from app import database as database_module
from app.database import Database


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
def opened(monkeypatch):
    """Replace ``psycopg2.connect`` with a fake and return the list of connections it opened."""
    connections = []

    def _connect(*_args, **_kwargs):
        conn = _FakeConnection()
        connections.append(conn)
        return conn

    monkeypatch.setattr(database_module.psycopg2, "connect", _connect)
    return connections


def _in_thread(fn):
    result = []
    thread = threading.Thread(target=lambda: result.append(fn()))
    thread.start()
    thread.join()
    gc.collect()
    return result[0]


def test_a_thread_keeps_one_connection(opened) -> None:
    db = Database()
    assert db.connection is None
    first = db.connect()
    assert db.connect() is first
    assert db.connection is first
    assert len(opened) == 1


def test_concurrent_threads_get_separate_connections(opened) -> None:
    db = Database()
    barrier = threading.Barrier(4)
    seen = []

    def _work() -> None:
        conn = db.connect()
        barrier.wait(timeout=5)
        seen.append(conn)

    threads = [threading.Thread(target=_work) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len({id(conn) for conn in seen}) == 4


def test_a_finished_threads_connection_is_reused_not_closed(opened) -> None:
    db = Database()
    first = _in_thread(db.connect)
    assert not first.closed
    assert _in_thread(db.connect) is first
    assert len(opened) == 1


def test_idle_connections_past_the_bound_are_closed(opened, monkeypatch) -> None:
    monkeypatch.setattr(database_module.settings, "db_pool_max_idle", 0)
    db = Database()
    conn = _in_thread(db.connect)
    assert conn.closed


def test_a_connection_closed_while_idle_is_not_handed_out(opened) -> None:
    db = Database()
    first = _in_thread(db.connect)
    first.close()
    assert _in_thread(db.connect) is not first


def test_a_closed_connection_is_replaced(opened) -> None:
    db = Database()
    first = db.connect()
    first.close()
    assert db.connect() is not first


def test_assigning_connection_pins_it_for_every_thread(opened) -> None:
    db = Database()
    pinned = _FakeConnection()
    db.connection = pinned
    assert db.connect() is pinned
    assert _in_thread(db.connect) is pinned
    assert opened == []
    db.connection = None
    assert db.connect() is not pinned


def test_close_closes_this_threads_connection_and_the_idle_ones(opened) -> None:
    db = Database()
    idle = _in_thread(db.connect)
    mine = db.connect()
    db.close()
    assert mine.closed and idle.closed


def test_a_subclass_that_skips_init_still_connects(opened) -> None:
    class _Bare(Database):
        def __init__(self) -> None:
            pass

    assert _Bare().connect() is opened[0]


# ── Connection options: nothing may wait forever ────────────────────────────────────────────────


def _connect_kwargs(monkeypatch) -> dict:
    seen = {}

    def _connect(*_args, **kwargs):
        seen.update(kwargs)
        return _FakeConnection()

    monkeypatch.setattr(database_module.psycopg2, "connect", _connect)
    Database().connect()
    return seen


def test_new_connections_carry_timeouts_and_keepalives(monkeypatch) -> None:
    kwargs = _connect_kwargs(monkeypatch)
    assert kwargs["connect_timeout"] == 10
    assert kwargs["keepalives"] == 1
    assert kwargs["application_name"] == "apiome-rest"
    assert "-c lock_timeout=30000" in kwargs["options"]
    assert "-c idle_in_transaction_session_timeout=300000" in kwargs["options"]
    assert "statement_timeout" not in kwargs["options"].replace("idle_in_transaction_session_timeout", "")


def test_a_zero_timeout_is_left_unset(monkeypatch) -> None:
    monkeypatch.setattr(database_module.settings, "db_connect_timeout_seconds", 0)
    monkeypatch.setattr(database_module.settings, "db_lock_timeout_ms", 0)
    monkeypatch.setattr(database_module.settings, "db_idle_in_transaction_timeout_ms", 0)
    kwargs = _connect_kwargs(monkeypatch)
    assert "connect_timeout" not in kwargs
    assert "options" not in kwargs


def test_a_url_with_its_own_options_keeps_them() -> None:
    kwargs = database_module._connection_options("postgresql://u:p@h/db?options=-c%20lock_timeout%3D5")
    assert "options" not in kwargs


# ── db_cursor: a helper ends the transaction it starts ──────────────────────────────────────────


class _TxConnection(_FakeConnection):
    """A fake that tracks its transaction state the way psycopg2 does."""

    def __init__(self) -> None:
        super().__init__()
        self.info = type("Info", (), {"transaction_status": psycopg2.extensions.TRANSACTION_STATUS_IDLE})()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        conn = self

        class _Cursor:
            def __enter__(self):
                conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_INTRANS
                return self

            def __exit__(self, *_exc):
                return False

        return _Cursor()

    def commit(self) -> None:
        self.commits += 1
        self.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

    def rollback(self) -> None:
        self.rollbacks += 1
        self.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE


class _Handle:
    def __init__(self, conn) -> None:
        self.conn = conn

    def connect(self):
        return self.conn


def test_db_cursor_commits_the_transaction_it_started() -> None:
    from app.db_cursor import db_cursor

    conn = _TxConnection()

    def read():
        with db_cursor(_Handle(conn)):
            return "rows"

    assert read() == "rows"
    assert (conn.commits, conn.rollbacks) == (1, 0)
    assert conn.info.transaction_status == psycopg2.extensions.TRANSACTION_STATUS_IDLE


def test_db_cursor_rolls_back_when_the_block_raises() -> None:
    from app.db_cursor import db_cursor

    conn = _TxConnection()
    with pytest.raises(ValueError):
        with db_cursor(_Handle(conn)):
            raise ValueError("boom")
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_db_cursor_leaves_a_callers_open_transaction_alone() -> None:
    from app.db_cursor import db_cursor

    conn = _TxConnection()
    conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_INTRANS
    with db_cursor(_Handle(conn)):
        pass
    with pytest.raises(ValueError):
        with db_cursor(_Handle(conn)):
            raise ValueError("boom")
    assert (conn.commits, conn.rollbacks) == (0, 0)


def test_a_failed_rollback_does_not_hide_the_query_error(opened) -> None:
    db = Database()
    conn = db.connect()

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, *_args):
            raise psycopg2.OperationalError("server closed the connection unexpectedly")

    def _dead_rollback():
        raise psycopg2.InterfaceError("connection already closed")

    conn.cursor = lambda: _Cursor()
    conn.rollback = _dead_rollback
    with pytest.raises(psycopg2.OperationalError, match="server closed"):
        db.execute_query("SELECT 1")
