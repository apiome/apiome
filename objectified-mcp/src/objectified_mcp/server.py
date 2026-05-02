"""FastMCP application instance (stdio / HTTP transports land in later tickets)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from objectified_mcp.database_pool import MCP_DB_POOL_KEY, create_async_pool, ping_pool
from objectified_mcp.settings import get_settings


@lifespan
async def database_lifespan(server: Any) -> Any:
    """Open the shared async pool at MCP startup; close it on shutdown (including cancellation)."""
    settings = get_settings()
    pool = create_async_pool(settings, open=False)
    try:
        await pool.open()
        await ping_pool(pool)
        yield {MCP_DB_POOL_KEY: pool}
    finally:
        await pool.close()


mcp = FastMCP("Objectified", lifespan=database_lifespan)
