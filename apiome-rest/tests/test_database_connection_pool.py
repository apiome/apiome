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
