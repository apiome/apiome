"""Unit tests for InMemorySessionStore (#4453)."""

from __future__ import annotations

import asyncio

import pytest

from apiome_mock.memory_session_store import InMemorySessionStore
from apiome_mock.session_store import SessionCapacityError, SessionCaps, SessionKey


@pytest.fixture
def caps() -> SessionCaps:
    return SessionCaps(
        ttl_seconds=3600.0,
        max_resources=3,
        max_bytes=10_000,
        max_sessions=2,
    )


@pytest.fixture
def key() -> SessionKey:
    return SessionKey("demo", "petstore", "1.0.0", "s1")


def test_put_list_get_delete(caps: SessionCaps, key: SessionKey) -> None:
    store = InMemorySessionStore(caps)

    async def _run() -> None:
        await store.put_resource(key, "/pets", "1", {"id": 1, "name": "Rex"}, replace=True)
        listed = await store.list_resources(key, "/pets")
        assert listed == [{"id": 1, "name": "Rex"}]
        got = await store.get_resource(key, "/pets", "1")
        assert got == {"id": 1, "name": "Rex"}
        assert await store.delete_resource(key, "/pets", "1") is True
        assert await store.get_resource(key, "/pets", "1") is None
        assert await store.list_resources(key, "/pets") == []

    asyncio.run(_run())


def test_session_isolation(caps: SessionCaps) -> None:
    store = InMemorySessionStore(caps)
    a = SessionKey("demo", "petstore", "1.0.0", "s1")
    b = SessionKey("demo", "petstore", "1.0.0", "s2")

    async def _run() -> None:
        await store.put_resource(a, "/pets", "1", {"id": 1, "name": "A"}, replace=True)
        await store.put_resource(b, "/pets", "1", {"id": 1, "name": "B"}, replace=True)
        assert await store.list_resources(a, "/pets") == [{"id": 1, "name": "A"}]
        assert await store.list_resources(b, "/pets") == [{"id": 1, "name": "B"}]

    asyncio.run(_run())


def test_sliding_ttl_expiry(key: SessionKey) -> None:
    clock = {"now": 1000.0}

    def now() -> float:
        return clock["now"]

    short = SessionCaps(
        ttl_seconds=10.0,
        max_resources=10,
        max_bytes=10_000,
        max_sessions=10,
    )
    store = InMemorySessionStore(short, clock=now)

    async def _run() -> None:
        await store.put_resource(key, "/pets", "1", {"id": 1, "name": "Rex"}, replace=True)
        clock["now"] = 1005.0
        assert await store.get_resource(key, "/pets", "1") is not None
        clock["now"] = 1020.0
        assert await store.get_resource(key, "/pets", "1") is None

    asyncio.run(_run())


def test_resource_cap(caps: SessionCaps, key: SessionKey) -> None:
    store = InMemorySessionStore(caps)

    async def _run() -> None:
        await store.put_resource(key, "/pets", "1", {"id": 1}, replace=True)
        await store.put_resource(key, "/pets", "2", {"id": 2}, replace=True)
        await store.put_resource(key, "/pets", "3", {"id": 3}, replace=True)
        with pytest.raises(SessionCapacityError):
            await store.put_resource(key, "/pets", "4", {"id": 4}, replace=True)

    asyncio.run(_run())


def test_next_integer_id(caps: SessionCaps, key: SessionKey) -> None:
    store = InMemorySessionStore(caps)

    async def _run() -> None:
        assert await store.next_integer_id(key, "/pets") == 1
        await store.put_resource(key, "/pets", "5", {"id": 5}, replace=True)
        assert await store.next_integer_id(key, "/pets") == 6

    asyncio.run(_run())
