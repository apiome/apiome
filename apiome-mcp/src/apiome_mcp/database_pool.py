"""Shared async Postgres pool for MCP tools (psycopg 3 + psycopg_pool)."""

from __future__ import annotations

from typing import cast

from fastmcp import Context
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.settings import Settings

MCP_DB_POOL_KEY = "db_pool"


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
    """Lightweight health probe used at MCP startup and for tooling/tests."""
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")


def get_db_pool(ctx: Context) -> AsyncConnectionPool:
    """Resolve the shared pool from FastMCP lifespan context (tool dependency)."""
    raw = ctx.lifespan_context.get(MCP_DB_POOL_KEY)
    if raw is None:
        raise RuntimeError("Database pool is not available (lifespan not initialized?)")
    return cast(AsyncConnectionPool, raw)
