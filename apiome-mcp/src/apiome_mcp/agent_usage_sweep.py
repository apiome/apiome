"""AGX-3.3 usage sweep — daily rollups and retention for agent invocations and MCP audit rows.

One tick, behind a Postgres session advisory lock (so with several apiome-mcp instances only one
does the work and the rest skip), commits after every step (DBP-1.23, #7206):

1. **Rollups**, one UTC day per transaction: ``agent_invocation_open_days`` lists the open days
   (from the day after the newest finalized one, reaching back to any raw day not finalized), and
   ``rollup_agent_invocation_day`` recomputes each — only the groups with a call since the day's
   previous rollup minus the grace period — and finalizes days that ended more than the grace
   period ago;
2. **Purges**, one batch per transaction, each repeated until a batch comes back short or the tick's
   time budget runs out (every purge still runs at least one batch):

   * ``purge_agent_invocations`` — raw rows past each tenant's tier retention
     (``licenses.seats.agent_invocation_retention_days``), only on finalized days, so every pruned
     row is already counted in a rollup;
   * ``purge_agent_invocation_samples`` — body samples older than 7 days;
   * ``purge_agent_invocation_rollups`` — rollups past the tier's ``agent_usage_rollup_retention_days``;
   * ``purge_upstream_credential_uses`` — the AGX-2.2 credential-use ledger retention;
   * ``purge_mcp_access_audit`` and ``purge_mcp_capability_denials`` — the MCP audit tables.

The SQL lives in migrations V271 and V429, so the rules are the same whoever runs them.
:func:`agent_usage_sweep_loop` runs a tick every ``agent_usage_sweep_interval_seconds`` from the
server lifespan; ``apiome-mcp agent-usage sweep`` runs one tick from cron.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

__all__ = [
    "PURGE_STEPS",
    "SWEEP_LOCK_KEY",
    "AgentUsageSweepConfig",
    "AgentUsageSweepResult",
    "agent_usage_sweep_loop",
    "run_agent_usage_sweep",
    "run_agent_usage_sweep_with_settings",
    "start_agent_usage_sweep",
    "stop_agent_usage_sweep",
]

#: Advisory lock key shared by every instance (``hashtext`` of the sweep name). The session lock
#: taken here and the transaction lock of earlier versions conflict, so mixed versions never overlap.
SWEEP_LOCK_KEY = "apiome.agent_usage_sweep"


@dataclass(frozen=True)
class AgentUsageSweepConfig:
    """How one tick runs.

    Attributes:
        batch_size: Most rows one purge batch deletes (floored at 1).
        time_budget: How long a tick may keep repeating purge batches.
        finalize_grace: How long after a UTC day ends before it is final. Must exceed the longest
            possible call, or a late row could land on a final day and miss its rollup; the
            incremental rollup relies on the same bound.
        credential_use_retention_days: Age at which AGX-2.2 credential-use records are deleted.
        access_audit_retention_days: Age at which ``mcp_access_audit`` rows are deleted.
        capability_denial_retention_days: Age at which ``mcp_capability_denials`` rows are deleted.
    """

    batch_size: int = 10_000
    time_budget: timedelta = timedelta(minutes=5)
    finalize_grace: timedelta = timedelta(hours=6)
    credential_use_retention_days: int = 90
    access_audit_retention_days: int = 365
    capability_denial_retention_days: int = 90

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentUsageSweepConfig:
        """Build the config from the process settings (``agent_usage_*`` and the retention days).

        Args:
            settings: The process settings.

        Returns:
            The matching config.
        """
        return cls(
            batch_size=settings.agent_usage_sweep_batch_size,
            time_budget=timedelta(seconds=settings.agent_usage_sweep_time_budget_seconds),
            finalize_grace=timedelta(hours=settings.agent_usage_finalize_grace_hours),
            credential_use_retention_days=settings.agent_upstream_use_retention_days,
            access_audit_retention_days=settings.access_audit_retention_days,
            capability_denial_retention_days=settings.capability_denial_retention_days,
        )


@dataclass(frozen=True)
class AgentUsageSweepResult:
    """What one tick did.

    Attributes:
        days_rolled_up: UTC days recomputed into ``agent_invocation_daily``.
        invocations_purged: Raw ``agent_invocations`` rows deleted.
        samples_purged: ``agent_invocation_samples`` rows deleted.
        rollups_purged: ``agent_invocation_daily`` rows deleted.
        credential_uses_purged: ``upstream_credential_uses`` rows deleted.
        access_audit_purged: ``mcp_access_audit`` rows deleted.
        capability_denials_purged: ``mcp_capability_denials`` rows deleted.
        budget_exhausted: ``True`` when a purge stopped on the time budget with a full last batch,
            so rows past retention remain for the next tick.
    """

    days_rolled_up: int
    invocations_purged: int
    samples_purged: int
    rollups_purged: int
    credential_uses_purged: int
    access_audit_purged: int = 0
    capability_denials_purged: int = 0
    budget_exhausted: bool = False


#: Each purge step: the result field it counts into, and its statement. Parameters are always
#: ``(now, batch, retention)`` positions picked by :func:`_purge_params`.
PURGE_STEPS: tuple[tuple[str, str], ...] = (
    ("invocations_purged", "SELECT apiome.purge_agent_invocations(%s, %s)"),
    ("samples_purged", "SELECT apiome.purge_agent_invocation_samples(%s, INTERVAL '7 days', %s)"),
    ("rollups_purged", "SELECT apiome.purge_agent_invocation_rollups(%s, %s)"),
    ("credential_uses_purged", "SELECT apiome.purge_upstream_credential_uses(%s, %s, %s)"),
    ("access_audit_purged", "SELECT apiome.purge_mcp_access_audit(%s, %s, %s)"),
    ("capability_denials_purged", "SELECT apiome.purge_mcp_capability_denials(%s, %s, %s)"),
)


def _purge_params(field: str, now: datetime, batch: int, config: AgentUsageSweepConfig) -> tuple[object, ...]:
    """Parameters for one purge step's statement.

    Args:
        field: The step's result field (see :data:`PURGE_STEPS`).
        now: The tick's instant.
        batch: Rows per batch.
        config: The tick's config.

    Returns:
        ``(now, batch)`` for the tier-based purges; ``(retention_days, batch, now)`` for the fixed ones.
    """
    retention = {
        "credential_uses_purged": config.credential_use_retention_days,
        "access_audit_purged": config.access_audit_retention_days,
        "capability_denials_purged": config.capability_denial_retention_days,
    }.get(field)
    if retention is None:
        return (now, batch)
    return (max(1, retention), batch, now)


async def _scalar(conn: Any, sql: str, params: tuple[object, ...]) -> Any:
    """Run ``sql`` in its own transaction (no statement timeout) and return the first column.

    Args:
        conn: An autocommit connection.
        sql: One statement returning one row.
        params: Its parameters.

    Returns:
        The first column of the first row, or ``None``.
    """
    async with conn.transaction():
        # DBP-1.21: pooled sessions carry statement_timeout; sweep steps may run longer.
        await conn.execute("SET LOCAL statement_timeout = 0")
        row = await (await conn.execute(sql, params)).fetchone()
    return row[0] if row else None


async def run_agent_usage_sweep(
    pool: AsyncConnectionPool,
    config: AgentUsageSweepConfig | None = None,
    *,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> AgentUsageSweepResult | None:
    """Run one sweep tick.

    Args:
        pool: The shared Postgres pool (autocommit connections).
        config: How the tick runs (defaults: :class:`AgentUsageSweepConfig`).
        now: The instant the tick acts at; ``None`` reads the database's ``CURRENT_TIMESTAMP``
            once. Tests and load simulations pass their own clock.
        clock: Monotonic seconds, for the time budget (tests pass a fake).

    Returns:
        What the tick did, or ``None`` when another instance holds the sweep lock.

    Raises:
        Exception: Database errors propagate; steps committed before the error stay committed (each
            is safe on its own) and :func:`agent_usage_sweep_loop` retries next interval.
    """
    cfg = config or AgentUsageSweepConfig()
    batch = max(1, cfg.batch_size)
    deadline = clock() + max(0.0, cfg.time_budget.total_seconds())
    async with pool.connection() as conn:
        locked = await (await conn.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (SWEEP_LOCK_KEY,))).fetchone()
        if not locked or not locked[0]:
            return None
        try:
            at: datetime = now if now is not None else await _scalar(conn, "SELECT CURRENT_TIMESTAMP", ())

            days = await (await conn.execute("SELECT d FROM apiome.agent_invocation_open_days(%s) d", (at,))).fetchall()
            for (day,) in days:
                await _scalar(
                    conn,
                    "SELECT apiome.rollup_agent_invocation_day(%s, %s, %s)",
                    (day, at, cfg.finalize_grace),
                )

            counts: dict[str, int] = {}
            exhausted = False
            for field, sql in PURGE_STEPS:
                params = _purge_params(field, at, batch, cfg)
                total = 0
                while True:
                    deleted = int(await _scalar(conn, sql, params) or 0)
                    total += deleted
                    if deleted < batch:
                        break
                    if clock() >= deadline:
                        exhausted = True
                        break
                counts[field] = total
        finally:
            with contextlib.suppress(Exception):
                await conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (SWEEP_LOCK_KEY,))
    result = AgentUsageSweepResult(days_rolled_up=len(days), budget_exhausted=exhausted, **counts)
    _log.info("agent_usage_sweep_done", **asdict(result))
    return result


async def agent_usage_sweep_loop(
    pool: AsyncConnectionPool,
    *,
    interval_seconds: float,
    config: AgentUsageSweepConfig | None = None,
) -> None:
    """Run :func:`run_agent_usage_sweep` every ``interval_seconds`` until cancelled.

    A failed tick is logged and retried on the next interval; it never ends the loop.

    Args:
        pool: The shared Postgres pool.
        interval_seconds: Pause between ticks (the first tick runs after one interval).
        config: See :func:`run_agent_usage_sweep`.
    """
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await run_agent_usage_sweep(pool, config)
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
        settings: The process settings.

    Returns:
        :func:`run_agent_usage_sweep`'s result.
    """
    return await run_agent_usage_sweep(pool, AgentUsageSweepConfig.from_settings(settings))


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
            config=AgentUsageSweepConfig.from_settings(settings),
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
