"""AGX-3.3 usage sweep — daily rollups and per-tier retention for agent invocations (#4539).

One tick, in one transaction, under a Postgres advisory lock (so with several apiome-mcp
instances only one does the work and the rest skip):

1. ``rollup_agent_invocation_days`` recomputes ``agent_invocation_daily`` for every open UTC day
   from the raw ``agent_invocations`` rows, and finalizes days that ended more than the grace
   period ago;
2. ``purge_agent_invocations`` deletes raw rows past each tenant's tier retention
   (``licenses.seats.agent_invocation_retention_days``) — only on finalized days, so every pruned
   row is already counted in a rollup;
3. ``purge_agent_invocation_samples`` deletes body samples older than 7 days;
4. ``purge_agent_invocation_rollups`` deletes rollups past the tier's
   ``agent_usage_rollup_retention_days``;
5. ``purge_upstream_credential_uses`` applies the AGX-2.2 credential-use ledger retention
   (V268 left its scheduling to this ticket).

The SQL lives in migration V271 (and V268), so the rules are the same whoever runs them.
:func:`agent_usage_sweep_loop` runs a tick every ``agent_usage_sweep_interval_seconds`` from the
server lifespan; ``apiome-mcp agent-usage sweep`` runs one tick from cron.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

import structlog
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

__all__ = [
    "SWEEP_LOCK_KEY",
    "AgentUsageSweepResult",
    "agent_usage_sweep_loop",
    "run_agent_usage_sweep",
    "run_agent_usage_sweep_with_settings",
    "start_agent_usage_sweep",
    "stop_agent_usage_sweep",
]

#: ``pg_try_advisory_xact_lock`` key shared by every instance (``hashtext`` of the sweep name).
SWEEP_LOCK_KEY = "apiome.agent_usage_sweep"


@dataclass(frozen=True)
class AgentUsageSweepResult:
    """What one tick did.

    Attributes:
        days_rolled_up: UTC days recomputed into ``agent_invocation_daily``.
        invocations_purged: Raw ``agent_invocations`` rows deleted.
        samples_purged: ``agent_invocation_samples`` rows deleted.
        rollups_purged: ``agent_invocation_daily`` rows deleted.
        credential_uses_purged: ``upstream_credential_uses`` rows deleted.
    """

    days_rolled_up: int
    invocations_purged: int
    samples_purged: int
    rollups_purged: int
    credential_uses_purged: int


async def run_agent_usage_sweep(
    pool: AsyncConnectionPool,
    *,
    batch_size: int = 10000,
    finalize_grace: timedelta = timedelta(hours=6),
    credential_use_retention_days: int = 90,
) -> AgentUsageSweepResult | None:
    """Run one sweep tick.

    Args:
        pool: The shared Postgres pool.
        batch_size: Most rows each purge step deletes per tick (the rest go on the next tick).
        finalize_grace: How long after a UTC day ends before it is final. Must exceed the longest
            possible call, or a late row could land on a final day and miss its rollup.
        credential_use_retention_days: Age at which AGX-2.2 credential-use records are deleted.

    Returns:
        What the tick did, or ``None`` when another instance holds the sweep lock.

    Raises:
        Exception: Database errors propagate (the transaction rolls back);
            :func:`agent_usage_sweep_loop` logs them and retries next interval.
    """
    batch = max(1, batch_size)
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (SWEEP_LOCK_KEY,))
            locked = await cur.fetchone()
            if not locked or not locked[0]:
                return None

            async def scalar(sql: str, params: tuple[object, ...]) -> int:
                row = await (await conn.execute(sql, params)).fetchone()
                return int(row[0]) if row and row[0] is not None else 0

            result = AgentUsageSweepResult(
                days_rolled_up=await scalar(
                    "SELECT apiome.rollup_agent_invocation_days(CURRENT_TIMESTAMP, %s)",
                    (finalize_grace,),
                ),
                invocations_purged=await scalar(
                    "SELECT apiome.purge_agent_invocations(CURRENT_TIMESTAMP, %s)",
                    (batch,),
                ),
                samples_purged=await scalar(
                    "SELECT apiome.purge_agent_invocation_samples(CURRENT_TIMESTAMP, INTERVAL '7 days', %s)",
                    (batch,),
                ),
                rollups_purged=await scalar(
                    "SELECT apiome.purge_agent_invocation_rollups(CURRENT_TIMESTAMP, %s)",
                    (batch,),
                ),
                credential_uses_purged=await scalar(
                    "SELECT apiome.purge_upstream_credential_uses(%s)",
                    (max(1, credential_use_retention_days),),
                ),
            )
    _log.info("agent_usage_sweep_done", **asdict(result))
    return result


async def agent_usage_sweep_loop(
    pool: AsyncConnectionPool,
    *,
    interval_seconds: float,
    batch_size: int = 10000,
    finalize_grace: timedelta = timedelta(hours=6),
    credential_use_retention_days: int = 90,
) -> None:
    """Run :func:`run_agent_usage_sweep` every ``interval_seconds`` until cancelled.

    A failed tick is logged and retried on the next interval; it never ends the loop.

    Args:
        pool: The shared Postgres pool.
        interval_seconds: Pause between ticks (the first tick runs after one interval).
        batch_size: See :func:`run_agent_usage_sweep`.
        finalize_grace: See :func:`run_agent_usage_sweep`.
        credential_use_retention_days: See :func:`run_agent_usage_sweep`.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await run_agent_usage_sweep(
                pool,
                batch_size=batch_size,
                finalize_grace=finalize_grace,
                credential_use_retention_days=credential_use_retention_days,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.warning("agent_usage_sweep_failed", exc_info=True)


async def run_agent_usage_sweep_with_settings(
    pool: AsyncConnectionPool, settings: Settings
) -> AgentUsageSweepResult | None:
    """Run one tick configured from ``settings`` (the CLI's ``agent-usage sweep``).

    Args:
        pool: The shared Postgres pool.
        settings: The process settings (``agent_usage_*`` / ``agent_upstream_use_retention_days``).

    Returns:
        :func:`run_agent_usage_sweep`'s result.
    """
    return await run_agent_usage_sweep(
        pool,
        batch_size=settings.agent_usage_sweep_batch_size,
        finalize_grace=timedelta(hours=settings.agent_usage_finalize_grace_hours),
        credential_use_retention_days=settings.agent_upstream_use_retention_days,
    )


def start_agent_usage_sweep(pool: AsyncConnectionPool, settings: Settings) -> asyncio.Task[None] | None:
    """Start :func:`agent_usage_sweep_loop` in the background, configured from ``settings``.

    Args:
        pool: The shared Postgres pool (must stay open while the task runs).
        settings: The process settings.

    Returns:
        The running task, or ``None`` when ``agent_usage_sweep_interval_seconds`` is 0.
    """
    if settings.agent_usage_sweep_interval_seconds <= 0:
        return None
    return asyncio.get_running_loop().create_task(
        agent_usage_sweep_loop(
            pool,
            interval_seconds=settings.agent_usage_sweep_interval_seconds,
            batch_size=settings.agent_usage_sweep_batch_size,
            finalize_grace=timedelta(hours=settings.agent_usage_finalize_grace_hours),
            credential_use_retention_days=settings.agent_upstream_use_retention_days,
        ),
        name="agent_usage_sweep",
    )


async def stop_agent_usage_sweep(task: asyncio.Task[None] | None) -> None:
    """Cancel a task from :func:`start_agent_usage_sweep` and wait for it (``None`` is a no-op)."""
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
