"""Shared SessionStore contract, run against both backends (#7209, DBP-1.26).

The memory backend always runs. The Postgres backend runs when ``APIOME_MOCK_TEST_DATABASE_URL``
names a database migrated with apiome-db (V430 or later); otherwise its cases skip. Each Postgres
case starts from empty ``mock_session`` tables, so do not point it at a database in use.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mock.memory_session_store import InMemorySessionStore
from apiome_mock.postgres_session_store import PostgresSessionStore
from apiome_mock.scenarios import Scenario, _sequence_call_number
from apiome_mock.session_store import SessionCapacityError, SessionCaps, SessionKey, SessionStore

DB_URL = os.environ.get("APIOME_MOCK_TEST_DATABASE_URL")

BACKENDS = [
    "memory",
    pytest.param(
        "postgres",
        marks=pytest.mark.skipif(not DB_URL, reason="APIOME_MOCK_TEST_DATABASE_URL not set"),
    ),
]

KEY = SessionKey("demo", "petstore", "1.0.0", "s1")
OTHER = SessionKey("demo", "petstore", "1.0.0", "s2")


class FakeClock:
    """One adjustable clock for both backends (monotonic seconds and UTC datetimes)."""

    def __init__(self) -> None:
        self.seconds = 1_000.0
        self._epoch = datetime(2026, 11, 23, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.seconds += seconds

    def monotonic(self) -> float:
        return self.seconds

    def utc(self) -> datetime:
        return self._epoch + timedelta(seconds=self.seconds)


def _caps(**overrides: Any) -> SessionCaps:
    values: dict[str, Any] = {
        "ttl_seconds": 100.0,
        "max_resources": 10,
        "max_bytes": 10_000,
        "max_sessions": 10,
    }
    values.update(overrides)
    return SessionCaps(**values)


async def reset_postgres_tables(pool: AsyncConnectionPool) -> None:
    """Empty the session tables (DELETE, so the slot trigger keeps the count at zero)."""
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM apiome.mock_session")
        await conn.execute("UPDATE apiome.mock_session_slots SET session_count = 0")


@asynccontextmanager
async def open_store(
    backend: str,
    caps: SessionCaps,
    clock: FakeClock,
) -> AsyncIterator[tuple[SessionStore, AsyncConnectionPool | None]]:
    """Yield a fresh store of ``backend`` (and the pool for Postgres)."""
    if backend == "memory":
        yield InMemorySessionStore(caps, clock=clock.monotonic), None
        return
    assert DB_URL is not None
    pool = AsyncConnectionPool(DB_URL, min_size=1, max_size=8, open=False, kwargs={"autocommit": True})
    await pool.open()
    try:
        await reset_postgres_tables(pool)
        yield PostgresSessionStore(pool, caps, clock=clock.utc), pool
        await reset_postgres_tables(pool)
    finally:
        await pool.close()


def run_case(
    backend: str,
    body: Callable[[SessionStore, FakeClock], Awaitable[None]],
    **caps: Any,
) -> None:
    """Run one async contract case against ``backend``."""
    clock = FakeClock()

    async def _main() -> None:
        async with open_store(backend, _caps(**caps), clock) as (store, _):
            await body(store, clock)

    asyncio.run(_main())


@pytest.mark.parametrize("backend", BACKENDS)
def test_put_get_list_delete_roundtrip(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1, "name": "Rex"}, replace=False)
        await store.put_resource(KEY, "/pets", "2", {"id": 2, "name": "Bella"}, replace=False)
        assert await store.get_resource(KEY, "/pets", "1") == {"id": 1, "name": "Rex"}
        assert await store.list_resources(KEY, "/pets") == [
            {"id": 1, "name": "Rex"},
            {"id": 2, "name": "Bella"},
        ]
        assert await store.list_resources(OTHER, "/pets") == []
        assert await store.delete_resource(KEY, "/pets", "1") is True
        assert await store.delete_resource(KEY, "/pets", "1") is False
        assert await store.delete_resource(OTHER, "/pets", "2") is False
        assert await store.get_resource(KEY, "/pets", "1") is None

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_resource_and_byte_caps(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        await store.put_resource(KEY, "/pets", "2", {"id": 2}, replace=False)
        with pytest.raises(SessionCapacityError):
            await store.put_resource(KEY, "/pets", "3", {"id": 3}, replace=False)
        # Overwriting an existing id does not count as a new resource.
        await store.put_resource(KEY, "/pets", "2", {"id": 2, "n": "x"}, replace=True)
        # Deleting frees room.
        assert await store.delete_resource(KEY, "/pets", "1")
        await store.put_resource(KEY, "/pets", "3", {"id": 3}, replace=False)
        with pytest.raises(SessionCapacityError):
            await store.put_resource(KEY, "/pets", "2", {"id": 2, "blob": "x" * 2_000}, replace=True)

    run_case(backend, body, max_resources=2, max_bytes=1_024)


@pytest.mark.parametrize("backend", BACKENDS)
def test_session_cap_and_reset_frees_slot(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        await store.put_resource(OTHER, "/pets", "1", {"id": 1}, replace=False)
        third = SessionKey("demo", "petstore", "1.0.0", "s3")
        with pytest.raises(SessionCapacityError):
            await store.put_resource(third, "/pets", "1", {"id": 1}, replace=False)
        # Existing sessions keep writing at the cap.
        await store.put_resource(KEY, "/pets", "2", {"id": 2}, replace=False)
        assert await store.replace_session(OTHER, {}) == (0, 0)
        await store.put_resource(third, "/pets", "1", {"id": 1}, replace=False)

    run_case(backend, body, max_sessions=2)


@pytest.mark.parametrize("backend", BACKENDS)
def test_expiry_and_sliding_ttl(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        # Reads keep the session alive past its first TTL.
        clock.advance(60)
        assert await store.get_resource(KEY, "/pets", "1") == {"id": 1}
        clock.advance(60)
        assert await store.list_resources(KEY, "/pets") == [{"id": 1}]
        # Idle for longer than the TTL: gone, and a new write starts from nothing.
        clock.advance(101)
        assert await store.get_resource(KEY, "/pets", "1") is None
        assert await store.list_resources(KEY, "/pets") == []
        assert await store.delete_resource(KEY, "/pets", "1") is False
        assert await store.next_integer_id(KEY, "/pets") == 1
        assert await store.list_resources(KEY, "/pets") == []

    run_case(backend, body, ttl_seconds=100.0)


@pytest.mark.parametrize("backend", BACKENDS)
def test_expired_session_does_not_hold_back_its_own_namespace(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        clock.advance(101)
        # The cap counts sessions; reusing the same token after expiry is always allowed.
        await store.put_resource(KEY, "/pets", "9", {"id": 9}, replace=False)
        assert await store.list_resources(KEY, "/pets") == [{"id": 9}]

    run_case(backend, body, ttl_seconds=100.0, max_sessions=1)


@pytest.mark.parametrize("backend", BACKENDS)
def test_next_integer_id_advances_and_follows_numeric_ids(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        assert await store.next_integer_id(KEY, "/pets") == 1
        assert await store.next_integer_id(KEY, "/pets") == 2
        assert await store.next_integer_id(KEY, "/pets") == 3
        assert await store.next_integer_id(KEY, "/owners") == 1
        await store.put_resource(KEY, "/pets", "10", {"id": 10}, replace=False)
        await store.put_resource(KEY, "/pets", "abc", {"id": "abc"}, replace=False)
        assert await store.next_integer_id(KEY, "/pets") == 11
        assert await store.next_integer_id(OTHER, "/pets") == 1

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_create_resource_allocates_and_stores(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        def build(next_int: int) -> tuple[str, dict[str, Any]]:
            return str(next_int), {"id": next_int, "name": "Rex"}

        first = await store.create_resource(KEY, "/pets", build)
        second = await store.create_resource(KEY, "/pets", build)
        assert first == {"id": 1, "name": "Rex"}
        assert second["id"] == 2
        # A client-supplied id wins; the next allocation still moves past it.
        await store.create_resource(KEY, "/pets", lambda _n: ("7", {"id": 7}))
        assert (await store.create_resource(KEY, "/pets", build))["id"] == 8
        assert len(await store.list_resources(KEY, "/pets")) == 4

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_create_resource_cap_failure_stores_nothing(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.create_resource(KEY, "/pets", lambda n: (str(n), {"id": n}))
        with pytest.raises(SessionCapacityError):
            await store.create_resource(KEY, "/pets", lambda n: (str(n), {"id": n}))
        assert await store.list_resources(KEY, "/pets") == [{"id": 1}]

    run_case(backend, body, max_resources=1)


@pytest.mark.parametrize("backend", BACKENDS)
def test_update_resource_reads_current(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        seen: list[dict[str, Any] | None] = []

        def merge(current: dict[str, Any] | None) -> dict[str, Any]:
            seen.append(current)
            return {**(current or {"id": 1}), "name": "Max"}

        assert await store.update_resource(KEY, "/pets", "1", merge) == {"id": 1, "name": "Max"}
        assert await store.update_resource(KEY, "/pets", "1", merge) == {"id": 1, "name": "Max"}
        assert seen == [None, {"id": 1, "name": "Max"}]

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_replace_session_swaps_state_and_counters(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        await store.put_resource(KEY, "/pets", "1", {"id": 1}, replace=False)
        for _ in range(5):
            await store.next_integer_id(KEY, "/pets")
        await store.put_resource(OTHER, "/pets", "1", {"id": 1, "who": "other"}, replace=False)
        count, size = await store.replace_session(
            KEY,
            {
                "/pets": [("1", {"id": 1, "name": "Seed"}), ("2", {"id": 2}), ("2", {"id": 2, "dup": True})],
                "/owners": [("a", {"id": "a"})],
            },
        )
        assert count == 3
        assert size > 0
        assert await store.list_resources(KEY, "/pets") == [{"id": 1, "name": "Seed"}, {"id": 2, "dup": True}]
        assert await store.list_resources(KEY, "/owners") == [{"id": "a"}]
        # Counters were discarded: the next id follows the seeded ids.
        assert await store.next_integer_id(KEY, "/pets") == 3
        # Another session is untouched.
        assert await store.list_resources(OTHER, "/pets") == [{"id": 1, "who": "other"}]
        # Caps still apply after a seed.
        with pytest.raises(SessionCapacityError):
            await store.replace_session(KEY, {"/pets": [(str(i), {"id": i}) for i in range(11)]})
        assert len(await store.list_resources(KEY, "/pets")) == 2

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_sequence_scenario_advances(backend: str) -> None:
    # The call number only depends on the scenario's name and the operation key.
    scenario = Scenario(name="flaky", description="", operations={})

    async def body(store: SessionStore, clock: FakeClock) -> None:
        calls = [
            await _sequence_call_number(
                scenario=scenario,
                operation_key="GET /pets",
                rule_index=None,
                tenant="demo",
                project="petstore",
                version="1.0.0",
                session_token="seq",
                client_ip="127.0.0.1",
                store=store,
            )
            for _ in range(3)
        ]
        assert calls == [1, 2, 3]

    run_case(backend, body)


@pytest.mark.parametrize("backend", BACKENDS)
def test_concurrent_creates_get_distinct_ids(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        results = await asyncio.gather(
            *(store.create_resource(KEY, "/pets", lambda n: (str(n), {"id": n})) for _ in range(20)),
        )
        ids = sorted(item["id"] for item in results)
        assert ids == list(range(1, 21))
        assert len(await store.list_resources(KEY, "/pets")) == 20

    run_case(backend, body, max_resources=50)


@pytest.mark.parametrize("backend", BACKENDS)
def test_session_cap_holds_under_concurrency(backend: str) -> None:
    async def body(store: SessionStore, clock: FakeClock) -> None:
        async def attempt(index: int) -> bool:
            key = SessionKey("demo", "petstore", "1.0.0", f"burst-{index}")
            try:
                await store.put_resource(key, "/pets", "1", {"id": 1}, replace=False)
            except SessionCapacityError:
                return False
            return True

        outcomes = await asyncio.gather(*(attempt(i) for i in range(16)))
        assert sum(outcomes) == 3

    run_case(backend, body, max_sessions=3)
