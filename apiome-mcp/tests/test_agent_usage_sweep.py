"""AGX-3.3 usage sweep (#4539): rollups and per-tier retention on a schedule.

The rollup/retention rules are SQL in V271 (``rollup_agent_invocation_days`` finalizes a day before
``purge_agent_invocations`` may prune it, so rollups always match raw counts). These tests pin what
the apiome-mcp side owns: the steps run in order, in one transaction, behind the advisory lock;
a held lock skips the tick; a failed tick never stops the loop; and the lifespan / CLI wiring.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent_invocation_fakes import RecordingPool
from apiome_mcp import agent_usage_sweep
from apiome_mcp.agent_usage_sweep import (
    SWEEP_LOCK_KEY,
    AgentUsageSweepResult,
    agent_usage_sweep_loop,
    run_agent_usage_sweep,
    run_agent_usage_sweep_with_settings,
    start_agent_usage_sweep,
    stop_agent_usage_sweep,
)
from apiome_mcp.settings import Settings

#: What each sweep step "deletes" in the fake.
COUNTS = {
    "rollup_agent_invocation_days": 3,
    "purge_agent_invocations(": 120,
    "purge_agent_invocation_samples": 4,
    "purge_agent_invocation_rollups": 7,
    "purge_upstream_credential_uses": 9,
}


def _responder(locked: bool = True) -> Any:
    def respond(sql: str, params: Any) -> Any:
        if "pg_try_advisory_xact_lock" in sql:
            return (locked,)
        for needle, count in COUNTS.items():
            if needle in sql:
                return (count,)
        return None

    return respond


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://u:p@localhost:5432/apiome",
        "internal_secret": "x" * 32,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_tick_runs_every_step_in_order_under_the_lock() -> None:
    pool = RecordingPool(_responder())
    result = asyncio.run(
        run_agent_usage_sweep(
            pool,
            batch_size=500,
            finalize_grace=timedelta(hours=2),
            credential_use_retention_days=30,
        )
    )
    assert result == AgentUsageSweepResult(
        days_rolled_up=3,
        invocations_purged=120,
        samples_purged=4,
        rollups_purged=7,
        credential_uses_purged=9,
    )
    assert pool.transactions == 1
    sqls = [sql for sql, _ in pool.statements]
    order = [
        "pg_try_advisory_xact_lock",
        "rollup_agent_invocation_days",
        "purge_agent_invocations(",
        "purge_agent_invocation_samples",
        "purge_agent_invocation_rollups",
        "purge_upstream_credential_uses",
    ]
    assert [next(i for i, sql in enumerate(sqls) if needle in sql) for needle in order] == list(range(6))
    params = [p for _, p in pool.statements]
    assert params[0] == (SWEEP_LOCK_KEY,)
    assert params[1] == (timedelta(hours=2),)
    assert params[2] == params[3] == params[4] == (500,)
    assert params[5] == (30,)


def test_rollup_runs_before_any_purge() -> None:
    """Pruning only finalized days is safe only if this tick's rollup already ran."""
    pool = RecordingPool(_responder())
    asyncio.run(run_agent_usage_sweep(pool))
    sqls = [sql for sql, _ in pool.statements]
    rollup = next(i for i, sql in enumerate(sqls) if "rollup_agent_invocation_days" in sql)
    purges = [i for i, sql in enumerate(sqls) if "purge_" in sql]
    assert purges and rollup < min(purges)


def test_held_lock_skips_the_tick() -> None:
    pool = RecordingPool(_responder(locked=False))
    assert asyncio.run(run_agent_usage_sweep(pool)) is None
    assert [sql for sql, _ in pool.statements if "apiome." in sql] == []


def test_batch_and_retention_are_floored_at_one() -> None:
    pool = RecordingPool(_responder())
    asyncio.run(run_agent_usage_sweep(pool, batch_size=0, credential_use_retention_days=-3))
    params = [p for _, p in pool.statements]
    assert params[2] == (1,)
    assert params[5] == (1,)


def test_failed_step_rolls_back_and_raises() -> None:
    pool = RecordingPool(_responder(), fail_on="purge_agent_invocation_rollups")
    with pytest.raises(RuntimeError):
        asyncio.run(run_agent_usage_sweep(pool))
    assert pool.rollbacks == 1


def test_settings_drive_the_one_shot(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = AsyncMock(return_value=None)
    monkeypatch.setattr(agent_usage_sweep, "run_agent_usage_sweep", runner)
    settings = _settings(
        agent_usage_sweep_batch_size=25,
        agent_usage_finalize_grace_hours=12,
        agent_upstream_use_retention_days=45,
    )
    pool = RecordingPool()
    asyncio.run(run_agent_usage_sweep_with_settings(pool, settings))  # type: ignore[arg-type]
    runner.assert_awaited_once_with(
        pool,
        batch_size=25,
        finalize_grace=timedelta(hours=12),
        credential_use_retention_days=45,
    )


def test_loop_survives_a_failed_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def flaky(pool: Any, **kwargs: Any) -> None:
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
    for field, bad in (
        ("agent_usage_sweep_interval_seconds", -1),
        ("agent_usage_sweep_batch_size", 0),
        ("agent_usage_finalize_grace_hours", 0),
        ("agent_upstream_use_retention_days", 0),
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
            ),
            "Rolled up 2 day(s); purged 5 invocation(s), 1 sample(s), 0 rollup row(s), 3 credential use(s).",
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
