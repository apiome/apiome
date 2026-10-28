"""Catalog item refresh sweep — the scheduler for per-item live re-discovery (MFI-31.1, #4398).

A background async loop (wired in :mod:`app.main`) that, every
``catalog_refresh_tick_seconds``, re-checks the catalog items whose refresh cadence has elapsed.
It generalizes the MCP re-discovery sweep (:mod:`app.mcp_discovery_sweep`) from MCP endpoints to
any import adapter with a live-discovery runner (:mod:`app.catalog_refresh`):

* **Due-selection** (:func:`app.catalog_refresh_store.list_due`) does the policy work: scheduled
  cadences only, not backing off, last check at least one cadence old, a live catalog item, and a
  tenant whose kill switch is on.
* **Single flight.** A session advisory lock (``apiome.catalog_refresh_sweep``) keeps two replicas
  or two overlapping ticks from checking the same items at once.
* **Concurrency cap.** At most ``catalog_refresh_max_concurrency`` checks run at once.
* **Per-host politeness.** Checks against the same host start at least
  ``catalog_refresh_host_delay_seconds`` apart (:class:`AsyncHostPoliteness`), so many items on
  one server never hit it in a burst.
* **Per-check timeout and backoff.** Each check is bounded by ``catalog_refresh_timeout_seconds``;
  a failure is recorded as ``failed`` and defers the item exponentially
  (:func:`app.catalog_refresh.run_refresh_check`). A failure never creates a version; a changed
  source adds one through the import pipeline, attributed to whoever last saved the setting, with
  ``refreshTrigger: sweep`` on its provenance (MFI-31.2).

The global ``catalog_refresh_enabled`` setting halts the whole tick.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

from . import catalog_refresh_store
from .catalog_refresh import TRIGGER_SWEEP, RefreshSettingsError, endpoint_host, run_refresh_check

_logger = logging.getLogger(__name__)

#: Session advisory-lock key that makes the sweep single-flight across replicas.
SWEEP_LOCK_KEY = "apiome.catalog_refresh_sweep"

#: Most items one tick will check; the rest stay due and are picked up next tick.
MAX_ITEMS_PER_TICK = 200


class AsyncHostPoliteness:
    """Space out calls to the same host by at least ``delay_seconds``.

    Calls to different hosts never wait for each other. Waiters for one host are served in
    arrival order.

    Args:
        delay_seconds: Minimum gap between two call starts against one host; ``0`` disables it.
        clock: Monotonic clock (injected by tests).
        sleep: Async sleep (injected by tests).
    """

    def __init__(
        self,
        delay_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._delay = max(0.0, float(delay_seconds))
        self._clock = clock
        self._sleep = sleep
        self._next_start: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    async def wait(self, host: str) -> None:
        """Return once a call to ``host`` may start, reserving the next slot for that host."""
        if self._delay <= 0:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = self._clock()
            start = max(now, self._next_start.get(host, now))
            if start > now:
                await self._sleep(start - now)
            self._next_start[host] = start + self._delay


def _host_for(row: Dict[str, Any]) -> str:
    """The politeness key for a row: its endpoint host, or the raw endpoint if unreadable."""
    try:
        return endpoint_host(str(row["adapter_key"]), str(row["endpoint"]))
    except RefreshSettingsError:
        return str(row["endpoint"])


def _try_lock(db: Any) -> bool:
    """Take the sweep's session advisory lock; ``False`` when another tick holds it."""
    rows = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (SWEEP_LOCK_KEY,))
    return bool(rows and rows[0].get("locked"))


async def _digests(db: Any, send_digests: Optional[Callable[[Any], int]]) -> None:
    """Send the due drift digests (MFI-31.3); a failure is logged, never raised."""
    if send_digests is None:
        from .catalog_drift_service import send_due_digests as send_digests
    try:
        sent = await asyncio.to_thread(send_digests, db)
        if sent:
            _logger.info("catalog refresh sweep sent %d drift digest(s)", sent)
    except Exception:  # noqa: BLE001 - digests never fail the tick
        _logger.warning("catalog drift digest pass failed", exc_info=True)


def _unlock(db: Any) -> None:
    """Release the sweep's session advisory lock."""
    db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (SWEEP_LOCK_KEY,))


async def process_catalog_refresh_sweep(
    db: Any,
    *,
    politeness: Optional[AsyncHostPoliteness] = None,
    store: Any = catalog_refresh_store,
    send_digests: Optional[Callable[[Any], int]] = None,
) -> Optional[int]:
    """Run one sweep tick: check every due catalog item, bounded, then send due drift digests.

    Args:
        db: Database handle for this tick. Blocking queries run in worker threads.
        politeness: The per-host gate (tests inject one with a fake clock); a fresh one per tick
            by default.
        store: The storage module (tests inject a fake).
        send_digests: Sends the tenants' due drift digests (MFI-31.3); defaults to
            :func:`app.catalog_drift_service.send_due_digests`. It runs under the sweep lock, after
            the checks, so a tick's breaking drift is in a digest no later than the next tick.

    Returns:
        The number of checks run, ``0`` when the global kill switch is off or nothing is due, or
        ``None`` when another tick holds the sweep lock.
    """
    from .config import settings

    if not settings.catalog_refresh_enabled:
        _logger.info("catalog refresh sweep halted: APIOME_CATALOG_REFRESH_ENABLED is off")
        return 0

    if not await asyncio.to_thread(_try_lock, db):
        return None
    try:
        due = await asyncio.to_thread(store.list_due, db, limit=MAX_ITEMS_PER_TICK)
        if not due:
            await _digests(db, send_digests)
            return 0

        gate = politeness or AsyncHostPoliteness(float(settings.catalog_refresh_host_delay_seconds))
        semaphore = asyncio.Semaphore(max(1, int(settings.catalog_refresh_max_concurrency)))

        async def _bounded(row: Dict[str, Any]) -> None:
            """Check one item while holding a concurrency slot and its host's politeness slot."""
            async with semaphore:
                await gate.wait(_host_for(row))
                await run_refresh_check(
                    db,
                    row,
                    timeout_seconds=float(settings.catalog_refresh_timeout_seconds),
                    backoff_base_seconds=float(settings.catalog_refresh_backoff_base_seconds),
                    backoff_max_seconds=float(settings.catalog_refresh_backoff_max_seconds),
                    store=store,
                    trigger=TRIGGER_SWEEP,
                )

        # run_refresh_check records its own failures; return_exceptions keeps one unexpected
        # error (say, a failed status write) from failing the rest of the tick.
        results = await asyncio.gather(*(_bounded(row) for row in due), return_exceptions=True)
        for row, result in zip(due, results):
            if isinstance(result, BaseException):
                _logger.error("catalog refresh check crashed project_id=%s", row.get("project_id"), exc_info=result)
        _logger.info("catalog refresh sweep checked %d due item(s)", len(due))
        await _digests(db, send_digests)
        return len(due)
    finally:
        await asyncio.to_thread(_unlock, db)
