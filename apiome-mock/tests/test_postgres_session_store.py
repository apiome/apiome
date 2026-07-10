"""Unit tests for PostgresSessionStore with a mocked pool (#4453)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from apiome_mock.postgres_session_store import PostgresSessionStore
from apiome_mock.session_store import SessionCaps, SessionKey


class _FakeCursor:
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


def test_postgres_list_and_get_roundtrip() -> None:
    caps = SessionCaps(
        ttl_seconds=3600,
        max_resources=10,
        max_bytes=10_000,
        max_sessions=10,
    )
    key = SessionKey("demo", "petstore", "1.0.0", "s1")

    cursor = _FakeCursor([{"resource": {"id": 1, "name": "Rex"}}])
    # First two executes are purge + touch; third is SELECT.
    cursor.execute = AsyncMock(return_value=None)

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

    store = PostgresSessionStore(pool, caps)

    async def _run() -> None:
        listed = await store.list_resources(key, "/pets")
        assert listed == [{"id": 1, "name": "Rex"}]

    asyncio.run(_run())
