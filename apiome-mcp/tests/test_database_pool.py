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


# ==================================================================================================
# DBP-1.21 (#7204): connection configuration, role sizing, the audit writer in the lifespan
# ==================================================================================================
def _settings(**overrides: object):
    from apiome_mcp.settings import Settings

    values: dict[str, object] = {
        "database_url": "postgresql://u:p@localhost:5432/apiome",
        "internal_secret": "x" * 32,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_connection_kwargs_name_the_app_and_set_both_session_timeouts() -> None:
    from apiome_mcp.database_pool import connection_kwargs

    kwargs = connection_kwargs(
        _settings(database_statement_timeout_ms=1500, database_idle_in_transaction_timeout_ms=9000), "agent"
    )
    assert kwargs["application_name"] == "apiome-mcp-agent"
    assert kwargs["options"] == "-c statement_timeout=1500 -c idle_in_transaction_session_timeout=9000"


def test_connection_kwargs_skip_zero_timeouts_and_respect_url_options() -> None:
    from apiome_mcp.database_pool import connection_kwargs

    off = connection_kwargs(
        _settings(database_statement_timeout_ms=0, database_idle_in_transaction_timeout_ms=0), "catalog"
    )
    assert off == {"application_name": "apiome-mcp-catalog"}
    own = connection_kwargs(
        _settings(database_url="postgresql://u:p@localhost:5432/apiome?options=-c%20statement_timeout%3D5"), "catalog"
    )
    assert "options" not in own


def test_create_async_pool_sizes_each_role_from_its_own_settings() -> None:
    from apiome_mcp.database_pool import configure_connection, create_async_pool

    settings = _settings(
        database_pool_min_size=2,
        database_pool_max_size=7,
        agent_database_pool_min_size=1,
        agent_database_pool_max_size=3,
    )
    catalog = create_async_pool(settings)
    agent = create_async_pool(settings, role="agent")
    assert (catalog.min_size, catalog.max_size, catalog.name) == (2, 7, "apiome-mcp-catalog")
    assert (agent.min_size, agent.max_size, agent.name) == (1, 3, "apiome-mcp-agent")
    assert agent._configure is configure_connection
    assert agent.kwargs["application_name"] == "apiome-mcp-agent"


def test_the_agent_pool_bounds_are_validated() -> None:
    with pytest.raises(ValueError, match="agent_database_pool_max_size"):
        _settings(agent_database_pool_min_size=5, agent_database_pool_max_size=2)


def test_configure_connection_sets_autocommit_and_registers_pgvector_once() -> None:
    from unittest.mock import AsyncMock

    from apiome_mcp import database_pool

    class _Conn:
        def __init__(self) -> None:
            self.set_autocommit = AsyncMock()

    conn = _Conn()
    register = AsyncMock()
    with patch("pgvector.psycopg.register_vector_async", new=register):
        asyncio.run(database_pool.configure_connection(conn))  # type: ignore[arg-type]
        asyncio.run(database_pool.ensure_vector_registered(conn))  # type: ignore[arg-type]
    conn.set_autocommit.assert_awaited_once_with(True)
    register.assert_awaited_once_with(conn)


def test_configure_connection_tolerates_a_database_without_pgvector() -> None:
    from unittest.mock import AsyncMock

    from apiome_mcp import database_pool

    class _Conn:
        def __init__(self) -> None:
            self.set_autocommit = AsyncMock()

    conn = _Conn()
    with patch("pgvector.psycopg.register_vector_async", new=AsyncMock(side_effect=RuntimeError("no vector type"))):
        asyncio.run(database_pool.configure_connection(conn))  # type: ignore[arg-type]
    conn.set_autocommit.assert_awaited_once_with(True)
    assert conn not in database_pool._VECTOR_READY


def test_database_lifespan_runs_the_audit_writer_and_embedding_client(mock_pool: MagicMock) -> None:
    from apiome_mcp.audit_writer import AuditWriter, audit_writer_for
    from apiome_mcp.spec_semantic_search_tool import EMBEDDING_HTTP_CLIENT_KEY

    async def run() -> None:
        with patch("apiome_mcp.server.create_async_pool", return_value=mock_pool):
            async with database_lifespan(mcp) as ctx:
                assert isinstance(audit_writer_for(mock_pool), AuditWriter)
                assert ctx[EMBEDDING_HTTP_CLIENT_KEY] is not None
        assert audit_writer_for(mock_pool) is None
        mock_pool.close.assert_awaited_once()

    asyncio.run(run())
