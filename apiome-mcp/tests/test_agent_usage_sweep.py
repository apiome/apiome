"""AGX-3.3 usage sweep (#4539): rollups and per-tier retention on a schedule.

The rollup/retention rules are SQL in V271 and V429 (a day is finalized before
``purge_agent_invocations`` may prune it, so rollups always match raw counts; apiome-db's
``mcp-usage-sweep-retention.test.ts`` checks them on a database). These tests pin what the
apiome-mcp side owns (DBP-1.23, #7206): the steps run in order behind a session advisory lock,
one transaction per rollup day and per purge batch; each purge repeats until a batch comes back
short or the time budget runs out; a held lock skips the tick; a failed tick releases the lock and
never stops the loop; and the lifespan / CLI wiring.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_invocation_fakes import RecordingPool
from apiome_mcp import agent_usage_sweep
from apiome_mcp.agent_usage_sweep import (
    SWEEP_LOCK_KEY,
    AgentUsageSweepConfig,
    AgentUsageSweepResult,
    agent_usage_sweep_loop,
    run_agent_usage_sweep,
    run_agent_usage_sweep_with_settings,
    start_agent_usage_sweep,
    stop_agent_usage_sweep,
)
from apiome_mcp.settings import Settings

NOW = datetime(2026, 6, 16, 7, 0, tzinfo=UTC)
DAYS = [date(2026, 6, 15), date(2026, 6, 16)]

#: Needle of each purge statement, in the order the tick runs them.
PURGES = [
    "purge_agent_invocations(",
    "purge_agent_invocation_samples",
    "purge_agent_invocation_rollups",
    "purge_upstream_credential_uses",
    "purge_mcp_access_audit",
    "purge_mcp_capability_denials",
]


def _responder(locked: bool = True, deleted: dict[str, list[int]] | None = None) -> Any:
    """Answer the tick's statements; ``deleted`` lists what successive batches of a purge delete."""
    queues = {needle: list(counts) for needle, counts in (deleted or {}).items()}

    def respond(sql: str, params: Any) -> Any:
        if "pg_try_advisory_lock" in sql:
            return (locked,)
        if "CURRENT_TIMESTAMP" in sql:
            return (NOW,)
        if "agent_invocation_open_days" in sql:
            return [(day,) for day in DAYS]
        if "rollup_agent_invocation_day(" in sql:
            return (4,)
        for needle in PURGES:
            if needle in sql:
                queue = queues.get(needle)
                return (queue.pop(0) if queue else 0,)
        return None

    return respond


class FakeClock:
    """Monotonic seconds that advance ``step`` on every read."""

    def __init__(self, step: float) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://u:p@localhost:5432/apiome",
        "internal_secret": "x" * 32,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _calls(pool: RecordingPool, needle: str) -> list[Any]:
    return [params for sql, params in pool.statements if needle in sql]


def test_tick_rolls_up_each_open_day_then_runs_every_purge() -> None:
    pool = RecordingPool(
        _responder(
            deleted={
                "purge_agent_invocations(": [500, 500, 120],
                "purge_agent_invocation_samples": [4],
                "purge_agent_invocation_rollups": [7],
                "purge_upstream_credential_uses": [9],
                "purge_mcp_access_audit": [2],
                "purge_mcp_capability_denials": [3],
            }
        )
    )
    config = AgentUsageSweepConfig(
        batch_size=500,
        finalize_grace=timedelta(hours=2),
        credential_use_retention_days=30,
        access_audit_retention_days=200,
        capability_denial_retention_days=60,
    )
    result = asyncio.run(run_agent_usage_sweep(pool, config))
    assert result == AgentUsageSweepResult(
        days_rolled_up=2,
        invocations_purged=1120,
        samples_purged=4,
        rollups_purged=7,
        credential_uses_purged=9,
        access_audit_purged=2,
        capability_denials_purged=3,
        budget_exhausted=False,
    )
    sqls = [sql for sql, _ in pool.statements]
    order = [
        "pg_try_advisory_lock",
        "CURRENT_TIMESTAMP",
        "agent_invocation_open_days",
        "rollup_agent_invocation_day(",
        *PURGES,
        "pg_advisory_unlock",
    ]
    firsts = [next(i for i, sql in enumerate(sqls) if needle in sql) for needle in order]
    assert firsts == sorted(firsts)
    assert pool.statements[0][1] == (SWEEP_LOCK_KEY,)
    assert pool.statements[-1] == ("SELECT pg_advisory_unlock(hashtext(%s))", (SWEEP_LOCK_KEY,))
    assert _calls(pool, "rollup_agent_invocation_day(") == [(day, NOW, timedelta(hours=2)) for day in DAYS]
    assert _calls(pool, "purge_agent_invocations(") == [(NOW, 500)] * 3
    assert _calls(pool, "purge_upstream_credential_uses") == [(30, 500, NOW)]
    assert _calls(pool, "purge_mcp_access_audit") == [(200, 500, NOW)]
    assert _calls(pool, "purge_mcp_capability_denials") == [(60, 500, NOW)]


def test_every_rollup_day_and_purge_batch_is_its_own_transaction() -> None:
    """DBP-1.23: a commit per step, so a long tick never holds one transaction (or its locks) open."""
    pool = RecordingPool(_responder(deleted={"purge_agent_invocations(": [10, 10, 1]}))
    asyncio.run(run_agent_usage_sweep(pool, AgentUsageSweepConfig(batch_size=10)))
    # The clock read, two rollup days, three invocation batches and one batch of each other purge.
    assert pool.transactions == 1 + 2 + 3 + 5
    assert len(_calls(pool, "SET LOCAL statement_timeout = 0")) == pool.transactions
    # The lock is a session lock, taken outside every transaction.
    assert not _calls(pool, "pg_try_advisory_xact_lock")


def test_rollups_run_before_any_purge() -> None:
    """Pruning only finalized days is safe only if this tick's rollup already ran."""
    pool = RecordingPool(_responder())
    asyncio.run(run_agent_usage_sweep(pool))
    sqls = [sql for sql, _ in pool.statements]
    last_rollup = max(i for i, sql in enumerate(sqls) if "rollup_agent_invocation_day(" in sql)
    purges = [i for i, sql in enumerate(sqls) if "purge_" in sql]
    assert purges and last_rollup < min(purges)


def test_a_purge_repeats_until_a_batch_comes_back_short() -> None:
    pool = RecordingPool(_responder(deleted={"purge_upstream_credential_uses": [3, 3, 3, 0]}))
    result = asyncio.run(run_agent_usage_sweep(pool, AgentUsageSweepConfig(batch_size=3)))
    assert result is not None
    assert result.credential_uses_purged == 9
    assert len(_calls(pool, "purge_upstream_credential_uses")) == 4
    assert result.budget_exhausted is False


def test_the_time_budget_stops_repeats_but_every_purge_runs_once() -> None:
    full = [5] * 100
    pool = RecordingPool(_responder(deleted={needle: full for needle in PURGES}))
    clock = FakeClock(step=1.0)
    result = asyncio.run(
        run_agent_usage_sweep(
            pool,
            AgentUsageSweepConfig(batch_size=5, time_budget=timedelta(seconds=3)),
            clock=clock,
        )
    )
    assert result is not None
    assert result.budget_exhausted is True
    # The budget (3 s on a clock that ticks 1 s a read) ends the first purge after three batches.
    assert len(_calls(pool, "purge_agent_invocations(")) == 3
    for needle in PURGES[1:]:
        assert len(_calls(pool, needle)) == 1, needle


def test_a_given_instant_replaces_the_database_clock() -> None:
    pool = RecordingPool(_responder())
    at = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    asyncio.run(run_agent_usage_sweep(pool, now=at))
    assert not _calls(pool, "CURRENT_TIMESTAMP")
    assert _calls(pool, "agent_invocation_open_days") == [(at,)]
    assert _calls(pool, "purge_agent_invocations(") == [(at, 10_000)]


def test_held_lock_skips_the_tick() -> None:
    pool = RecordingPool(_responder(locked=False))
    assert asyncio.run(run_agent_usage_sweep(pool)) is None
    assert [sql for sql, _ in pool.statements if "apiome." in sql] == []
    assert not _calls(pool, "pg_advisory_unlock")


def test_batch_and_retention_are_floored_at_one() -> None:
    pool = RecordingPool(_responder())
    config = AgentUsageSweepConfig(
        batch_size=0,
        credential_use_retention_days=-3,
        access_audit_retention_days=0,
        capability_denial_retention_days=-1,
    )
    asyncio.run(run_agent_usage_sweep(pool, config))
    assert _calls(pool, "purge_agent_invocations(") == [(NOW, 1)]
    assert _calls(pool, "purge_upstream_credential_uses") == [(1, 1, NOW)]
    assert _calls(pool, "purge_mcp_access_audit") == [(1, 1, NOW)]
    assert _calls(pool, "purge_mcp_capability_denials") == [(1, 1, NOW)]


def test_a_failed_step_rolls_back_and_releases_the_lock() -> None:
    pool = RecordingPool(_responder(), fail_on="purge_agent_invocation_rollups")
    with pytest.raises(RuntimeError):
        asyncio.run(run_agent_usage_sweep(pool))
    assert pool.rollbacks == 1
    # Earlier steps committed on their own; the session lock is released.
    assert _calls(pool, "purge_agent_invocation_samples")
    assert pool.statements[-1][0] == "SELECT pg_advisory_unlock(hashtext(%s))"


def test_config_from_settings() -> None:
    settings = _settings(
        agent_usage_sweep_batch_size=25,
        agent_usage_sweep_time_budget_seconds=40,
        agent_usage_finalize_grace_hours=12,
        agent_upstream_use_retention_days=45,
        access_audit_retention_days=100,
        capability_denial_retention_days=30,
    )
    assert AgentUsageSweepConfig.from_settings(settings) == AgentUsageSweepConfig(
        batch_size=25,
        time_budget=timedelta(seconds=40),
        finalize_grace=timedelta(hours=12),
        credential_use_retention_days=45,
        access_audit_retention_days=100,
        capability_denial_retention_days=30,
    )


def test_settings_drive_the_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(agent_usage_sweep, "run_agent_usage_sweep", runner)
    settings = _settings(agent_usage_sweep_batch_size=25)
    pool = RecordingPool()
    asyncio.run(run_agent_usage_sweep_with_settings(pool, settings))  # type: ignore[arg-type]
    runner.assert_awaited_once_with(pool, AgentUsageSweepConfig.from_settings(settings))


def test_loop_survives_a_failed_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def flaky(pool: Any, *args: Any, **kwargs: Any) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db down")
        if len(calls) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(agent_usage_sweep, "run_agent_usage_sweep", flaky)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent_usage_sweep_loop(RecordingPool(), interval_seconds=0))  # type: ignore[arg-type]
    assert len(calls) == 3


def test_disabled_interval_starts_nothing() -> None:
    async def run() -> None:
        task = start_agent_usage_sweep(RecordingPool(), _settings(agent_usage_sweep_interval_seconds=0))  # type: ignore[arg-type]
        assert task is None
        await stop_agent_usage_sweep(None)

    asyncio.run(run())


def test_started_sweep_is_cancelled_cleanly() -> None:
    async def run() -> None:
        task = start_agent_usage_sweep(RecordingPool(), _settings(agent_usage_sweep_interval_seconds=3600))  # type: ignore[arg-type]
        assert task is not None and not task.done()
        await stop_agent_usage_sweep(task)
        assert task.cancelled()

    asyncio.run(run())


def test_settings_defaults_and_bounds() -> None:
    settings = _settings()
    assert settings.agent_usage_sweep_interval_seconds == 3600
    assert settings.agent_usage_sweep_batch_size == 10_000
    assert settings.agent_usage_finalize_grace_hours == 6
    assert settings.agent_upstream_use_retention_days == 90
    assert settings.agent_usage_sweep_time_budget_seconds == 300
    assert settings.access_audit_retention_days == 365
    assert settings.capability_denial_retention_days == 90
    for field, bad in (
        ("agent_usage_sweep_interval_seconds", -1),
        ("agent_usage_sweep_batch_size", 0),
        ("agent_usage_finalize_grace_hours", 0),
        ("agent_upstream_use_retention_days", 0),
        ("agent_usage_sweep_time_budget_seconds", 0),
        ("access_audit_retention_days", 0),
        ("capability_denial_retention_days", 0),
    ):
        with pytest.raises(ValueError):
            _settings(**{field: bad})


def test_cli_agent_usage_sweep_invokes_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp import cli
    from apiome_mcp.settings import get_settings

    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://u:p@localhost:5432/apiome")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 32)
    runner = AsyncMock(return_value=0)
    monkeypatch.setattr(cli, "_run_agent_usage_sweep", runner)
    monkeypatch.setattr(sys, "argv", ["apiome-mcp", "agent-usage", "sweep"])
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    runner.assert_awaited_once()


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            AgentUsageSweepResult(
                days_rolled_up=2,
                invocations_purged=5,
                samples_purged=1,
                rollups_purged=0,
                credential_uses_purged=3,
                access_audit_purged=4,
                capability_denials_purged=6,
            ),
            "Rolled up 2 day(s); purged 5 invocation(s), 1 sample(s), 0 rollup row(s), 3 credential use(s), "
            "4 access audit row(s), 6 capability denial(s).",
        ),
        (
            AgentUsageSweepResult(
                days_rolled_up=1,
                invocations_purged=10,
                samples_purged=0,
                rollups_purged=0,
                credential_uses_purged=0,
                budget_exhausted=True,
            ),
            "Time budget reached; the rest is purged on the next sweep.",
        ),
        (None, "Skipped: another instance is running the agent usage sweep."),
    ],
)
def test_cli_runner_opens_and_closes_the_pool(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mock_pool: Any,
    result: AgentUsageSweepResult | None,
    expected: str,
) -> None:
    from apiome_mcp import cli, database_pool
    from apiome_mcp.settings import get_settings

    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://u:p@localhost:5432/apiome")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 32)
    get_settings.cache_clear()
    monkeypatch.setattr(database_pool, "create_async_pool", lambda settings, open: mock_pool)
    monkeypatch.setattr(agent_usage_sweep, "run_agent_usage_sweep_with_settings", AsyncMock(return_value=result))
    assert asyncio.run(cli._run_agent_usage_sweep()) == 0
    mock_pool.open.assert_awaited_once()
    mock_pool.close.assert_awaited_once()
    assert expected in capsys.readouterr().out
    get_settings.cache_clear()
