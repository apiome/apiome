"""Size the request thread pool against the database connection cap (DBP-1.4, #7187).

Route handlers that touch the database are plain ``def`` functions, or ``async def`` functions that
hop to a worker thread with ``run_in_threadpool`` around each blocking call. Either way the blocking
work runs on the server's request thread pool, not on the event loop, so one slow query no longer
stalls every other request in the process.

Each worker thread that touches the database holds one connection while it lives
(:class:`app.database.Database`), so the size of that pool is also the most connections requests
can hold at once. This module keeps it below ``settings.db_pool_max_in_use``, leaving room for the
threads that are not request threads: background sweeps, import and export engines, and the event
loop's own executor (``asyncio.to_thread``).
"""

from __future__ import annotations

import logging
from typing import Optional

import anyio.to_thread

from .config import settings

#: Share of ``db_pool_max_in_use`` request threads may take; the rest stays free for background work.
REQUEST_SHARE_OF_CONNECTION_CAP = 0.5


def request_thread_limit(configured: int, max_in_use: int) -> int:
    """How many request worker threads to allow.

    Args:
        configured: ``settings.request_thread_pool_size``; values below ``1`` count as ``1``.
        max_in_use: ``settings.db_pool_max_in_use``; ``0`` or less means no connection cap.

    Returns:
        ``configured``, lowered to half of ``max_in_use`` when a cap is set (never below ``1``).
    """
    wanted = max(int(configured), 1)
    if int(max_in_use) <= 0:
        return wanted
    return min(wanted, max(int(int(max_in_use) * REQUEST_SHARE_OF_CONNECTION_CAP), 1))


def configure_request_thread_pool(log: Optional[logging.Logger] = None) -> int:
    """Apply :func:`request_thread_limit` to the running event loop's request thread pool.

    The pool belongs to the event loop, so call this from a coroutine on that loop (the service
    calls it at startup). Safe to call again; the last call wins.

    Args:
        log: Where to report the size, and a warning when the configured size was lowered.

    Returns:
        The number of request worker threads now allowed.
    """
    configured = int(settings.request_thread_pool_size)
    cap = int(settings.db_pool_max_in_use)
    limit = request_thread_limit(configured, cap)
    anyio.to_thread.current_default_thread_limiter().total_tokens = limit
    if log is not None:
        if limit < max(configured, 1):
            log.warning(
                "REQUEST_THREAD_POOL_SIZE (%d) lowered to %d: request threads may use at most half of "
                "DB_POOL_MAX_IN_USE (%d), so background jobs keep the rest. Raise DB_POOL_MAX_IN_USE "
                "to allow more request threads.",
                configured,
                limit,
                cap,
            )
        log.info("request thread pool: %d worker threads (DB_POOL_MAX_IN_USE=%d)", limit, cap)
    return limit
