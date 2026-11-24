"""Statement-shape tests for PostgresSessionStore with a mocked pool (#4453, #7209).

Behaviour against a real database is covered by ``test_session_store_contract.py`` and
``test_postgres_session_store_db.py`` (both need ``APIOME_MOCK_TEST_DATABASE_URL``).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apiome_mock.postgres_session_store import (
    MAX_TOUCH_INTERVAL_SECONDS,
    PostgresSessionStore,
    sweep_expired_sessions,
    touch_interval_seconds,
)
from apiome_mock.session_store import SessionCapacityError, SessionCaps, SessionKey

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)
KEY = SessionKey("demo", "petstore", "1.0.0", "s1")


class _FakeCursor:
    """Records statements; every fetch returns the scripted row(s)."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.rowcount = 0
        self.execute = AsyncMock(return_value=None)

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    async def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)

    async def __aenter__(self) -> _FakeCursor:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _pool_with_cursor(rows: list[dict[str, Any]] | None = None) -> tuple[MagicMock, _FakeCursor]:
    """Build a mocked pool whose connections all yield one fake cursor."""
    cursor = _FakeCursor(rows)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    tx = AsyncMock()
    tx.__aenter__.return_value = None
    tx.__aexit__.return_value = None
    conn.transaction = MagicMock(return_value=tx)
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = None
    pool = MagicMock()
    pool.connection = MagicMock(return_value=cm)
    return pool, cursor


def _caps(max_resources: int = 10, max_bytes: int = 10_000) -> SessionCaps:
    return SessionCaps(ttl_seconds=3600, max_resources=max_resources, max_bytes=max_bytes, max_sessions=10)


def _store(pool: MagicMock, caps: SessionCaps | None = None) -> PostgresSessionStore:
    return PostgresSessionStore(pool, caps or _caps(), clock=lambda: NOW)


# A live, locked session row (also answers the other fetches harmlessly).
LIVE_SESSION = {
    "id": 7,
    "expires_at": NOW + timedelta(hours=1),
    "last_activity_at": NOW,
    "resource_count": 0,
    "total_bytes": 0,
    "byte_size": 0,
    "last_id": 1,
    "session_count": 1,
    "resource": {"id": 1},
}


def _statements(cursor: _FakeCursor) -> list[str]:
    return [call.args[0] for call in cursor.execute.await_args_list]


def _assert_scoped_to_session(sql: str) -> None:
    """A request-path statement must name the session (key or id), never sweep the table."""
    assert "session_token" in sql or "session_id" in sql or "WHERE id" in sql or "slot_id" in sql, sql
    assert "COUNT(DISTINCT" not in sql
    assert not ("DELETE" in sql and "expires_at" in sql), sql


def test_list_and_get_are_one_statement_each() -> None:
    pool, cursor = _pool_with_cursor([{"resource": {"id": 1, "name": "Rex"}}])
    store = _store(pool)

    async def _run() -> None:
        assert await store.list_resources(KEY, "/pets") == [{"id": 1, "name": "Rex"}]
        assert await store.get_resource(KEY, "/pets", "1") == {"id": 1, "name": "Rex"}

    asyncio.run(_run())
    statements = _statements(cursor)
    assert len(statements) == 2
    for sql in statements:
        _assert_scoped_to_session(sql)
        # The touch updates the session row only, and only when stale.
        assert "UPDATE apiome.mock_session m" in sql
        assert "stale_before" in sql
        assert "SKIP LOCKED" in sql
        assert "UPDATE apiome.mock_session_resource" not in sql


def test_writes_never_scan_other_sessions() -> None:
    pool, cursor = _pool_with_cursor([LIVE_SESSION])
    store = _store(pool)

    async def _run() -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        await store.create_resource(KEY, "/pets", lambda n: (str(n), {"id": n}))
        await store.update_resource(KEY, "/pets", "1", lambda cur: {**(cur or {}), "x": 1})
        await store.delete_resource(KEY, "/pets", "1")
        await store.next_integer_id(KEY, "/pets")
        await store.replace_session(KEY, {"/pets": [("1", {"id": 1})]})

    asyncio.run(_run())
    for sql in _statements(cursor):
        _assert_scoped_to_session(sql)


def test_each_write_is_one_transaction_on_one_connection() -> None:
    pool, _ = _pool_with_cursor([LIVE_SESSION])
    store = _store(pool)

    async def _run() -> None:
        await store.create_resource(KEY, "/pets", lambda n: (str(n), {"id": n}))

    asyncio.run(_run())
    assert pool.connection.call_count == 1


def test_replace_session_seeds_with_one_multi_row_insert() -> None:
    pool, cursor = _pool_with_cursor([LIVE_SESSION])
    store = _store(pool)

    async def _run() -> None:
        count, size = await store.replace_session(
            KEY,
            {"/pets": [("1", {"id": 1, "name": "Rex"}), ("2", {"id": 2, "name": "Bella"})]},
        )
        assert count == 2
        assert size > 0

    asyncio.run(_run())
    inserts = [
        call.args
        for call in cursor.execute.await_args_list
        if "INSERT INTO apiome.mock_session_resource" in call.args[0]
    ]
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "unnest" in sql
    assert params[0] == 7
    assert params[1] == ["/pets", "/pets"]
    assert params[2] == ["1", "2"]
    statements = _statements(cursor)
    assert any("DELETE FROM apiome.mock_session_resource WHERE session_id" in sql for sql in statements)
    assert any("DELETE FROM apiome.mock_session_counter WHERE session_id" in sql for sql in statements)


def test_replace_session_empty_seed_deletes_the_session_row() -> None:
    pool, cursor = _pool_with_cursor()
    store = _store(pool)

    async def _run() -> None:
        assert await store.replace_session(KEY, {}) == (0, 0)

    asyncio.run(_run())
    statements = _statements(cursor)
    assert len(statements) == 1
    assert "DELETE FROM apiome.mock_session WHERE" in statements[0]
    assert "session_token" in statements[0]


def test_replace_session_caps_fail_before_any_write() -> None:
    pool, cursor = _pool_with_cursor()
    store = _store(pool, _caps(max_resources=1))

    async def _run() -> None:
        with pytest.raises(SessionCapacityError):
            await store.replace_session(KEY, {"/pets": [("1", {"id": 1}), ("2", {"id": 2})]})

    asyncio.run(_run())
    cursor.execute.assert_not_awaited()


def test_replace_session_dedupes_duplicate_ids_last_wins() -> None:
    pool, cursor = _pool_with_cursor([LIVE_SESSION])
    store = _store(pool)

    async def _run() -> None:
        count, _ = await store.replace_session(
            KEY,
            {"/pets": [("1", {"id": 1, "name": "first"}), ("1", {"id": 1, "name": "second"})]},
        )
        assert count == 1

    asyncio.run(_run())
    params = next(
        call.args[1]
        for call in cursor.execute.await_args_list
        if "INSERT INTO apiome.mock_session_resource" in call.args[0]
    )
    assert params[2] == ["1"]
    assert '"second"' in params[3][0]


def test_new_session_over_the_cap_is_refused() -> None:
    # No existing row; the insert returns an id and the slot count is past the cap.
    pool, cursor = _pool_with_cursor([{"id": 9, "session_count": 11}])
    store = _store(pool)
    # The lock SELECT must see "no row" first: script fetchone per call.
    results = iter([None, {"id": 9}, {"session_count": 11}])

    async def fetchone() -> dict[str, Any] | None:
        return next(results)

    cursor.fetchone = fetchone  # type: ignore[method-assign]

    async def _run() -> None:
        with pytest.raises(SessionCapacityError, match="Session limit of 10"):
            await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)

    asyncio.run(_run())
    assert not any("INSERT INTO apiome.mock_session_resource" in sql for sql in _statements(cursor))


def test_touch_interval_is_a_minute_or_a_tenth_of_the_ttl() -> None:
    assert touch_interval_seconds(3600) == MAX_TOUCH_INTERVAL_SECONDS
    assert touch_interval_seconds(100) == 10.0


def test_sweep_repeats_full_batches_and_stops_on_a_short_one() -> None:
    store = MagicMock()
    store.purge_expired = AsyncMock(side_effect=[5, 5, 2, 5])

    total = asyncio.run(sweep_expired_sessions(store, batch_size=5, max_batches=10))
    assert total == 12
    assert store.purge_expired.await_count == 3


def test_sweep_stops_at_max_batches() -> None:
    store = MagicMock()
    store.purge_expired = AsyncMock(return_value=5)

    total = asyncio.run(sweep_expired_sessions(store, batch_size=5, max_batches=2))
    assert total == 10
    assert store.purge_expired.await_count == 2


def test_purge_is_batched_with_skip_locked() -> None:
    pool, cursor = _pool_with_cursor()
    cursor.rowcount = 3
    store = _store(pool)

    assert asyncio.run(store.purge_expired(50)) == 3
    sql, params = cursor.execute.await_args.args
    assert "LIMIT" in sql and "SKIP LOCKED" in sql
    assert params == (NOW, 50)
