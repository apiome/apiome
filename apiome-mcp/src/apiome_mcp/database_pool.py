"""Shared async Postgres pools for MCP tools (psycopg 3 + psycopg_pool).

A process serving HTTP holds two pools, one per app (DBP-1.21, #7204):

* ``catalog`` — the ``/mcp`` catalog server, sized by ``database_pool_min_size`` /
  ``database_pool_max_size``;
* ``agent`` — the ``/agent/mcp`` agent runtime, sized by ``agent_database_pool_min_size`` /
  ``agent_database_pool_max_size``.

Every connection is configured once, when the pool opens it (:func:`configure_connection`):

* **autocommit** — a read is one round trip, without ``BEGIN`` / ``COMMIT``. Writes that must be
  atomic use ``conn.transaction()``, which still opens a real transaction;
* ``application_name`` ``apiome-mcp-<role>``, so ``pg_stat_activity`` shows which app a session
  belongs to;
* ``statement_timeout`` and ``idle_in_transaction_session_timeout`` from settings (skipped when the
  database URL carries its own ``options``);
* the pgvector adapter, registered once per connection instead of once per semantic search.
"""

from __future__ import annotations

import weakref
from typing import Any, Literal, cast

import structlog
from fastmcp import Context
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

MCP_DB_POOL_KEY = "db_pool"

#: Which app a pool serves; also the suffix of its ``application_name``.
PoolRole = Literal["catalog", "agent"]

#: Connections the pgvector adapter is registered on (see :func:`ensure_vector_registered`).
_VECTOR_READY: weakref.WeakSet[Any] = weakref.WeakSet()


def connection_kwargs(settings: Settings, role: PoolRole) -> dict[str, Any]:
    """Connection keywords for one pool: session name and the two session timeouts.

    Args:
        settings: Validated settings.
        role: The app the pool serves.

    Returns:
        Keyword arguments for ``psycopg.AsyncConnection.connect``. ``options`` is left out when the
        database URL already sets it, so an operator's own session settings win.
    """
    kwargs: dict[str, Any] = {"application_name": f"apiome-mcp-{role}"}
    session = [
        f"-c {name}={int(value)}"
        for name, value in (
            ("statement_timeout", settings.database_statement_timeout_ms),
            ("idle_in_transaction_session_timeout", settings.database_idle_in_transaction_timeout_ms),
        )
        if int(value) > 0
    ]
    if session and "options=" not in str(settings.database_url):
        kwargs["options"] = " ".join(session)
    return kwargs


async def ensure_vector_registered(conn: AsyncConnection[Any]) -> None:
    """Register the pgvector adapter on ``conn`` unless that was already done.

    Args:
        conn: A pooled connection.

    Raises:
        Exception: Whatever ``register_vector_async`` raises (for example, no ``vector`` extension).
    """
    if conn in _VECTOR_READY:
        return
    from pgvector.psycopg import register_vector_async  # type: ignore[import-untyped]

    await register_vector_async(conn)
    _VECTOR_READY.add(conn)


async def configure_connection(conn: AsyncConnection[Any]) -> None:
    """The pool's ``configure`` hook: autocommit, then pgvector when the extension exists.

    A database without the ``vector`` extension still serves every tool but semantic search, so a
    failed registration is logged and not raised (raising would discard the connection).

    Args:
        conn: A connection the pool just opened.
    """
    await conn.set_autocommit(True)
    try:
        await ensure_vector_registered(conn)
    except Exception as exc:
        _log.debug("database_vector_adapter_unavailable", error=str(exc))


def create_async_pool(settings: Settings, *, open: bool = False, role: PoolRole = "catalog") -> AsyncConnectionPool:
    """Build a connection pool from validated settings (not opened unless ``open=True``).

    Args:
        settings: Validated settings.
        open: Open the pool now.
        role: ``catalog`` (``database_pool_*`` sizes) or ``agent`` (``agent_database_pool_*``).

    Returns:
        The pool, named after ``role``.
    """
    if role == "agent":
        min_size, max_size = settings.agent_database_pool_min_size, settings.agent_database_pool_max_size
    else:
        min_size, max_size = settings.database_pool_min_size, settings.database_pool_max_size
    return AsyncConnectionPool(
        conninfo=str(settings.database_url),
        min_size=min_size,
        max_size=max_size,
        timeout=settings.database_pool_timeout,
        kwargs=connection_kwargs(settings, role),
        configure=configure_connection,
        name=f"apiome-mcp-{role}",
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
