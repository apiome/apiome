from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.database_pool import MCP_DB_POOL_KEY, get_db_pool, ping_pool
from apiome_mcp.server import database_lifespan, mcp


@pytest.fixture(autouse=True)
def _settings_env_for_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 16)
    yield
    get_settings.cache_clear()


def test_ping_pool_runs_select_one(mock_pool: MagicMock) -> None:
    async def run() -> None:
        await ping_pool(mock_pool)

    asyncio.run(run())
    mock_pool.connection.assert_called_once()
    inner = mock_pool.connection.return_value.__aenter__.return_value
    inner.execute.assert_awaited_once()


def test_concurrent_ping_pool_acquires_release(mock_pool: MagicMock) -> None:
    async def run() -> None:
        await asyncio.gather(*[ping_pool(mock_pool) for _ in range(16)])

    asyncio.run(run())
    inner = mock_pool.connection.return_value.__aenter__.return_value
    assert inner.execute.await_count == 16


def test_get_db_pool_from_context() -> None:
    from fastmcp import Context

    pool = MagicMock(spec=AsyncConnectionPool)
    ctx = MagicMock(spec=Context)
    ctx.lifespan_context = {MCP_DB_POOL_KEY: pool}
    assert get_db_pool(ctx) is pool


def test_get_db_pool_missing_raises() -> None:
    from fastmcp import Context

    ctx = MagicMock(spec=Context)
    ctx.lifespan_context = {}
    with pytest.raises(RuntimeError, match="Database pool is not available"):
        get_db_pool(ctx)


def test_database_lifespan_opens_ping_closes(mock_pool: MagicMock) -> None:
    async def run() -> None:
        with patch("apiome_mcp.server.create_async_pool", return_value=mock_pool):
            async with database_lifespan(mcp) as ctx:
                assert MCP_DB_POOL_KEY in ctx
                assert ctx[MCP_DB_POOL_KEY] is mock_pool
        mock_pool.open.assert_awaited_once()
        mock_pool.close.assert_awaited_once()

    asyncio.run(run())


def test_database_lifespan_probe_failure_is_nonfatal(mock_pool: MagicMock) -> None:
    """A failed startup probe must not prevent the server from starting."""
    mock_pool.connection.side_effect = OSError("boom")

    async def run() -> None:
        with patch("apiome_mcp.server.create_async_pool", return_value=mock_pool):
            async with database_lifespan(mcp) as ctx:
                # Server still starts; pool is available for the ping tool to check
                assert MCP_DB_POOL_KEY in ctx
        mock_pool.open.assert_awaited_once()
        mock_pool.close.assert_awaited_once()

    asyncio.run(run())


def test_database_lifespan_closes_when_server_task_cancelled(mock_pool: MagicMock) -> None:
    """Pool ``close()`` runs when the MCP runner task is cancelled (e.g. SIGTERM-style shutdown)."""

    async def run() -> None:
        hang = asyncio.Event()

        async def blocked_inside_lifespan() -> None:
            async with database_lifespan(mcp):
                await hang.wait()

        with patch("apiome_mcp.server.create_async_pool", return_value=mock_pool):
            task = asyncio.create_task(blocked_inside_lifespan())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        mock_pool.close.assert_awaited_once()

    asyncio.run(run())
