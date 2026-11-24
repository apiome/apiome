"""Postgres-only session store checks against a real database (#7209, DBP-1.26).

Runs when ``APIOME_MOCK_TEST_DATABASE_URL`` names a database migrated with apiome-db (V430 or
later); skips otherwise. Each case empties the ``mock_session`` tables.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.postgres_session_store import (
    PostgresSessionStore,
    run_session_expiry_sweeper,
    sweep_expired_sessions,
    touch_interval_seconds,
)
from apiome_mock.session_store import SessionKey
from test_session_store_contract import DB_URL, KEY, FakeClock, _caps, open_store

pytestmark = pytest.mark.skipif(not DB_URL, reason="APIOME_MOCK_TEST_DATABASE_URL not set")


async def _fetch(pool: AsyncConnectionPool, sql: str, params: Any = None) -> list[dict[str, Any]]:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


async def _row_versions(pool: AsyncConnectionPool) -> tuple[list[str], list[str]]:
    """Return the ``xmin`` of every session row and every resource row (changes on each write)."""
    sessions = await _fetch(pool, "SELECT xmin::text AS v FROM apiome.mock_session ORDER BY id")
    resources = await _fetch(
        pool,
        "SELECT xmin::text AS v FROM apiome.mock_session_resource ORDER BY collection_path, resource_id",
    )
    return [r["v"] for r in sessions], [r["v"] for r in resources]


def _run(body: Any, **caps: Any) -> None:
    clock = FakeClock()

    async def _main() -> None:
        async with open_store("postgres", _caps(**caps), clock) as (store, pool):
            assert isinstance(store, PostgresSessionStore)
            assert pool is not None
            await body(store, pool, clock)

    asyncio.run(_main())


def test_reads_touch_at_most_the_session_row_and_not_every_time() -> None:
    async def body(store: PostgresSessionStore, pool: AsyncConnectionPool, clock: FakeClock) -> None:
        for i in range(5):
            await store.put_resource(KEY, "/pets", str(i), {"id": i}, replace=False)
        sessions_before, resources_before = await _row_versions(pool)

        # Within the touch interval: reads write nothing.
        clock.advance(touch_interval_seconds(3600.0) / 2)
        await store.get_resource(KEY, "/pets", "1")
        await store.list_resources(KEY, "/pets")
        assert await _row_versions(pool) == (sessions_before, resources_before)

        # Past the interval: one read rewrites the session row only, never a resource row.
        clock.advance(touch_interval_seconds(3600.0))
        await store.get_resource(KEY, "/pets", "1")
        sessions_after, resources_after = await _row_versions(pool)
        assert sessions_after != sessions_before
        assert resources_after == resources_before

        # The next read inside the new interval writes nothing again.
        await store.list_resources(KEY, "/pets")
        assert await _row_versions(pool) == (sessions_after, resources_after)

    _run(body, ttl_seconds=3600.0, max_resources=50)


def test_slot_count_tracks_session_rows() -> None:
    async def body(store: PostgresSessionStore, pool: AsyncConnectionPool, clock: FakeClock) -> None:
        for i in range(4):
            key = SessionKey("demo", "petstore", "1.0.0", f"s{i}")
            await store.put_resource(key, "/pets", "1", {"id": 1}, replace=False)
        await store.replace_session(SessionKey("demo", "petstore", "1.0.0", "s0"), {})
        slots = await _fetch(pool, "SELECT session_count FROM apiome.mock_session_slots")
        rows = await _fetch(pool, "SELECT COUNT(*) AS n FROM apiome.mock_session")
        assert int(slots[0]["session_count"]) == int(rows[0]["n"]) == 3
        stats = await _fetch(
            pool,
            "SELECT resource_count, total_bytes FROM apiome.mock_session WHERE session_token = 's1'",
        )
        assert stats[0]["resource_count"] == 1
        assert stats[0]["total_bytes"] > 0

    _run(body)


def test_sweep_deletes_expired_sessions_in_batches_and_cascades() -> None:
    async def body(store: PostgresSessionStore, pool: AsyncConnectionPool, clock: FakeClock) -> None:
        for i in range(7):
            key = SessionKey("demo", "petstore", "1.0.0", f"old-{i}")
            await store.put_resource(key, "/pets", "1", {"id": 1}, replace=False)
            await store.next_integer_id(key, "/pets")
        clock.advance(101)
        live = SessionKey("demo", "petstore", "1.0.0", "live")
        await store.put_resource(live, "/pets", "1", {"id": 1}, replace=False)

        assert await store.purge_expired(3) == 3
        assert await sweep_expired_sessions(store, batch_size=3, max_batches=10) == 4
        assert await sweep_expired_sessions(store, batch_size=3, max_batches=10) == 0

        sessions = await _fetch(pool, "SELECT session_token FROM apiome.mock_session")
        assert [s["session_token"] for s in sessions] == ["live"]
        orphans = await _fetch(
            pool,
            """
            SELECT (SELECT COUNT(*) FROM apiome.mock_session_resource) AS resources,
                   (SELECT COUNT(*) FROM apiome.mock_session_counter) AS counters,
                   (SELECT session_count FROM apiome.mock_session_slots) AS slots
            """,
        )
        assert orphans[0] == {"resources": 1, "counters": 0, "slots": 1}

    _run(body, ttl_seconds=100.0)


def test_sweeper_loop_runs_until_stopped() -> None:
    async def body(store: PostgresSessionStore, pool: AsyncConnectionPool, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        clock.advance(101)
        stop = asyncio.Event()
        task = asyncio.create_task(run_session_expiry_sweeper(store, stop, interval_seconds=0.05, batch_size=10))
        for _ in range(40):
            rows = await _fetch(pool, "SELECT COUNT(*) AS n FROM apiome.mock_session")
            if rows[0]["n"] == 0:
                break
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        assert rows[0]["n"] == 0

    _run(body, ttl_seconds=100.0)
