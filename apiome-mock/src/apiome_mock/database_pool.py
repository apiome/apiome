"""Shared async Postgres pool for the mock runtime (psycopg 3 + psycopg_pool).

The pool is **autocommit** (#7207, DBP-1.24): a read is one round trip instead of ``BEGIN`` /
statement / ``COMMIT``. Code that writes more than one statement atomically opens an explicit
``conn.transaction()`` (the audit ledger, the capture review queue, the Postgres session store).
Every connection carries a ``statement_timeout`` and an ``application_name``, and the wait queue is
bounded so a saturated pool fails fast instead of piling up requests.
"""

from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from apiome_mock.settings import Settings


def pool_connection_kwargs(settings: Settings) -> dict[str, Any]:
    """Return the per-connection keyword arguments the mock's pool connects with.

    Args:
        settings: Validated mock settings.

    Returns:
        ``autocommit``, ``application_name`` and (when enabled) a ``statement_timeout`` option.
    """
    kwargs: dict[str, Any] = {
        "autocommit": True,
        "application_name": settings.database_application_name,
    }
    if settings.database_statement_timeout_ms > 0:
        kwargs["options"] = f"-c statement_timeout={settings.database_statement_timeout_ms}"
    return kwargs


def create_async_pool(settings: Settings, *, open: bool = False) -> AsyncConnectionPool:
    """Build a connection pool from validated settings (not opened unless ``open=True``).

    Args:
        settings: Validated mock settings.
        open: Open the pool immediately.

    Returns:
        An autocommit pool with a bounded wait queue.
    """
    return AsyncConnectionPool(
        conninfo=str(settings.database_url),
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        timeout=settings.database_pool_timeout,
        max_waiting=settings.database_pool_max_waiting,
        kwargs=pool_connection_kwargs(settings),
        open=open,
    )


async def ping_pool(pool: AsyncConnectionPool) -> None:
    """Lightweight health probe used at startup and for tooling/tests."""
    async with pool.connection() as conn:
        await conn.execute("SELECT 1")
