"""One long-lived database handle per background sweep (DBP-1.2, #7185).

The lifespan sweeps in ``app.main`` used to build a ``Database()`` on every tick and close it at
the end, so every tick of every sweep opened a fresh PostgreSQL connection (TCP, TLS, auth,
backend fork). Now each sweep builds one handle with :func:`sweep_database` before its loop and
runs each tick through :func:`sweep_tick` (work on a worker thread) or :func:`async_sweep_tick`
(work on the event loop)::

    sweep_db = sweep_database()
    while True:
        await asyncio.sleep(tick_seconds)

        def _run() -> int:
            with sweep_tick(sweep_db) as thread_db:
                return process_something(thread_db)

        await asyncio.to_thread(_run)

When a tick ends its connections go back to the handle's idle pool
(:meth:`app.database.Database.release_connections`) instead of being closed, and the next tick
reuses them; a serial sweep holds one connection across ticks. Releasing also drops any session
advisory lock the tick forgot (``pg_advisory_unlock_all``), as closing used to.

A tick runs under :func:`app.db_timeouts.long_statements`: sweeps roll up, prune and re-derive
whole tables, so they keep the long statement ceiling rather than the 30-second request one.

:func:`close_sweep_databases` closes every handle at shutdown.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator, List

from .db_timeouts import long_statements

__all__ = ["async_sweep_tick", "close_sweep_databases", "sweep_database", "sweep_tick"]

_handles: List[Any] = []
_handles_lock = threading.Lock()


def sweep_database() -> Any:
    """A new :class:`~app.database.Database` for one sweep, closed by :func:`close_sweep_databases`.

    Returns:
        The handle; build it once, before the sweep's loop.
    """
    from .database import Database

    handle = Database()
    with _handles_lock:
        _handles.append(handle)
    return handle


@contextmanager
def sweep_tick(db: Any) -> Iterator[Any]:
    """Run one tick's blocking work on ``db``, in the calling worker thread.

    Args:
        db: The sweep's handle from :func:`sweep_database`.

    Yields:
        ``db``, for the tick's work.
    """
    with long_statements():
        try:
            yield db
        finally:
            db.release_connections()


@asynccontextmanager
async def async_sweep_tick(db: Any) -> AsyncIterator[Any]:
    """Run one tick whose work is async and pushes its database calls to worker threads.

    The context's long statement ceiling follows those calls into ``asyncio.to_thread``. When the
    tick ends, every connection it leased on any worker thread goes back to the idle pool.

    Args:
        db: The sweep's handle from :func:`sweep_database`.

    Yields:
        ``db``, for the tick's work.
    """
    with long_statements():
        try:
            yield db
        finally:
            await asyncio.to_thread(db.release_connections)


def close_sweep_databases() -> None:
    """Close every sweep handle's connections (at shutdown, after the sweeps are cancelled)."""
    with _handles_lock:
        handles, _handles[:] = list(_handles), []
    for handle in handles:
        try:
            handle.release_connections()
            handle.close()
        except Exception:
            pass
