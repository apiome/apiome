"""The usage index sweep — RDG-1.1 (#5759).

Unit tests over a recording fake database: the advisory lock gates the tick and is always
released, the V290 functions run in order with the configured grace and batch, and
``python -m app.usage_sweep`` prints the tick as JSON. ``test_usage_index_db.py`` runs the same
tick against the real schema.
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pytest

from app import usage_sweep
from app.config import Settings
from app.usage_sweep import SWEEP_LOCK_KEY, UsageSweepResult, main, run_usage_sweep, run_usage_sweep_with_settings

PURGED = {"hourly": 3, "samples": 1, "daily": 2, "fields": 4, "unmatched": 5, "batches": 6}


class FakeDb:
    """Answers the sweep's four statements and records every call."""

    def __init__(self, *, locked: bool = True, purged: Any = None, fail_on: Optional[str] = None) -> None:
        self.locked = locked
        self.purged = PURGED if purged is None else purged
        self.fail_on = fail_on
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []
        self.closed = False

    def execute_query(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        self.calls.append((query, params))
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("boom")
        if "pg_try_advisory_lock" in query:
            return [{"locked": self.locked}]
        if "rollup_usage_days" in query:
            return [{"days": 2}]
        if "purge_usage_unattributed" in query:
            return [{"purged": 7}]
        if "purge_usage" in query:
            return [{"purged": self.purged}]
        if "catalog_edges" in query:
            # CDG-3.5: the runtime-edge refresh lists tenants with usage; none here.
            return []
        if "pg_advisory_unlock" in query:
            return [{"unlocked": True}]
        raise AssertionError(f"unexpected query {query}")

    def close(self) -> None:
        self.closed = True

    def statements(self) -> List[str]:
        names = (
            "pg_try_advisory_lock",
            "rollup_usage_days",
            "purge_usage_unattributed",
            "purge_usage",
            "catalog_edges",
            "pg_advisory_unlock",
        )
        return [next(n for n in names if n in q) for q, _ in self.calls]


def test_a_tick_rolls_up_then_purges_under_the_lock() -> None:
    db = FakeDb()
    result = run_usage_sweep(db, finalize_grace=timedelta(hours=3), batch_size=50)
    assert db.statements() == [
        "pg_try_advisory_lock",
        "rollup_usage_days",
        "purge_usage",
        "purge_usage_unattributed",
        "catalog_edges",
        "pg_advisory_unlock",
    ]
    assert db.calls[0][1] == (SWEEP_LOCK_KEY,) and db.calls[-1][1] == (SWEEP_LOCK_KEY,)
    assert db.calls[1][1] == (timedelta(hours=3),)
    assert db.calls[2][1] == (50,) and db.calls[3][1] == (50,)
    assert result == UsageSweepResult(
        days_rolled_up=2,
        hourly_purged=3,
        samples_purged=1,
        daily_purged=2,
        fields_purged=4,
        unmatched_purged=5,
        batches_purged=6,
        unattributed_purged=7,
        runtime_tenants=0,
    )


def test_another_replica_holding_the_lock_skips_the_tick() -> None:
    db = FakeDb(locked=False)
    assert run_usage_sweep(db) is None
    assert db.statements() == ["pg_try_advisory_lock"]


@pytest.mark.parametrize("failing", ["rollup_usage_days", "purge_usage"])
def test_the_lock_is_released_when_a_step_fails(failing: str) -> None:
    db = FakeDb(fail_on=failing)
    with pytest.raises(RuntimeError):
        run_usage_sweep(db)
    assert db.statements()[-1] == "pg_advisory_unlock"


def test_a_json_string_result_and_missing_keys_are_read() -> None:
    db = FakeDb(purged=json.dumps({"hourly": 7}))
    result = run_usage_sweep(db)
    assert result is not None and result.hourly_purged == 7 and result.batches_purged == 0


def test_batch_size_is_at_least_one() -> None:
    db = FakeDb()
    run_usage_sweep(db, batch_size=0)
    assert db.calls[2][1] == (1,)


def test_negative_grace_is_refused_before_locking() -> None:
    db = FakeDb()
    with pytest.raises(ValueError):
        run_usage_sweep(db, finalize_grace=timedelta(hours=-1))
    assert db.calls == []


def test_settings_configure_the_tick() -> None:
    db = FakeDb()
    run_usage_sweep_with_settings(db, SimpleNamespace(usage_finalize_grace_hours=12, usage_sweep_batch_size=99))
    assert db.calls[1][1] == (timedelta(hours=12),)
    assert db.calls[2][1] == (99,)


def test_settings_defaults_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "APIOME_USAGE_SWEEP_INTERVAL_SECONDS",
        "APIOME_USAGE_FINALIZE_GRACE_HOURS",
        "APIOME_USAGE_SWEEP_BATCH_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings()
    assert (defaults.usage_sweep_interval_seconds, defaults.usage_finalize_grace_hours) == (3600, 6)
    assert defaults.usage_sweep_batch_size == 10000
    monkeypatch.setenv("APIOME_USAGE_SWEEP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("APIOME_USAGE_FINALIZE_GRACE_HOURS", "1.5")
    configured = Settings()
    assert configured.usage_sweep_interval_seconds == 0
    assert configured.usage_finalize_grace_hours == 1.5


def test_main_prints_the_tick(capsys: pytest.CaptureFixture[str]) -> None:
    db = FakeDb()
    assert main(["--grace-hours", "2", "--batch-size", "5"], database=db) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["skipped"] is False and printed["days_rolled_up"] == 2 and printed["unmatched_purged"] == 5
    assert db.calls[1][1] == (timedelta(hours=2),) and db.calls[2][1] == (5,)
    assert db.closed is False  # a handle the caller passed in is the caller's to close


def test_main_reports_a_skipped_tick(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], database=FakeDb(locked=False)) == 0
    assert json.loads(capsys.readouterr().out) == {"skipped": True}


def test_main_opens_and_closes_its_own_handle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: List[FakeDb] = []

    def _database() -> FakeDb:
        opened.append(FakeDb())
        return opened[-1]

    monkeypatch.setattr("app.database.Database", _database)
    assert main([]) == 0
    assert len(opened) == 1 and opened[0].closed is True
    capsys.readouterr()


def test_main_refuses_negative_grace() -> None:
    with pytest.raises(SystemExit):
        main(["--grace-hours", "-1"], database=FakeDb())


def test_the_module_is_runnable() -> None:
    """``python -m app.usage_sweep`` is the operator entry point."""
    assert usage_sweep.__name__ == "app.usage_sweep"
    source = open(usage_sweep.__file__, encoding="utf-8").read()
    assert 'if __name__ == "__main__":\n    raise SystemExit(main())' in source


def test_a_failed_runtime_edge_refresh_never_fails_the_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    """CDG-3.5: the graph refresh is a follow-on; the counters' rollup and pruning still report."""

    def boom(_db: Any) -> Dict[str, int]:
        raise RuntimeError("graph down")

    monkeypatch.setattr("app.runtime_graph.refresh_runtime_edges", boom)
    result = run_usage_sweep(FakeDb())
    assert result is not None and result.runtime_tenants == 0 and result.days_rolled_up == 2
