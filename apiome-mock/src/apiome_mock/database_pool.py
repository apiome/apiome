"""Shared async Postgres pool for the mock runtime (psycopg 3 + psycopg_pool)."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from apiome_mock.settings import Settings


def create_async_pool(settings: Settings, *, open: bool = False) -> AsyncConnectionPool:
    """Build a connection pool from validated settings (not opened unless ``open=True``)."""
    return AsyncConnectionPool(
        conninfo=str(settings.database_url),
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        timeout=settings.database_pool_timeout,
        open=open,
    )


async def ping_pool(pool: AsyncConnectionPool) -> None:
    """Lightweight health probe used at startup and for tooling/tests."""
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
