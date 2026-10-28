"""Unit tests for export job health — X8 (#6229).

The contract: success and failure rates over completed + failed jobs (canceled counts in
neither), per-target failure counts with their codes, a whole-job duration histogram whose
p95 is a bucket bound, and a rolling-window failure-rate alert that needs enough jobs, honours
its threshold, forgets jobs older than the window, can be turned off, and logs once per change
of state.
"""

from __future__ import annotations

import logging

import pytest

from app.export_job_health import (
    ALERT_FIRING,
    ALERT_NO_DATA,
    ALERT_OFF,
    ALERT_OK,
    JOB_DURATION_BUCKET_UPPER_MS,
    MAX_WINDOW_JOBS,
    ExportJobHealth,
    export_job_health,
)
from app.import_export_metrics import ImportExportMetrics


class _Clock:
    """A settable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock() -> _Clock:
    return _Clock()


@pytest.fixture()
def health(clock: _Clock) -> ExportJobHealth:
    """A registry with explicit thresholds: 20% over 10+ jobs in 15 minutes."""
    return ExportJobHealth(rate=0.2, min_jobs=10, window_seconds=900, clock=clock)


@pytest.fixture()
def registry() -> ImportExportMetrics:
    return ImportExportMetrics()


def _record(registry: ImportExportMetrics, target: str, outcome: str, times: int = 1) -> None:
    for _ in range(times):
        registry.record_job(kind="export", adapter_or_target=target, format_key=target, outcome=outcome)


# ===========================================================================
# Rates and per-target counts
# ===========================================================================


def test_empty_summary_has_no_rates_and_no_targets(health: ExportJobHealth) -> None:
    summary = health.summary({})
    assert summary["totals"] == {"completed": 0, "failed": 0, "canceled": 0}
    assert summary["success_rate"] is None
    assert summary["failure_rate"] is None
    assert summary["per_target"] == []
    assert summary["job_duration_ms"]["p95_upper_ms"] is None
    assert summary["alert"]["state"] == ALERT_NO_DATA


def test_rates_count_completed_and_failed_but_not_canceled(health, registry) -> None:
    _record(registry, "openapi-3.1", "completed", 6)
    _record(registry, "openapi-3.1", "failed", 2)
    _record(registry, "openapi-3.1", "canceled", 5)
    summary = health.summary(registry.snapshot())
    assert summary["totals"] == {"completed": 6, "failed": 2, "canceled": 5}
    assert summary["success_rate"] == 0.75
    assert summary["failure_rate"] == 0.25


def test_imports_never_reach_the_export_summary(health, registry) -> None:
    registry.record_job(kind="import", adapter_or_target="openapi", format_key="openapi", outcome="failed")
    assert health.summary(registry.snapshot())["totals"]["failed"] == 0


def test_per_target_lists_most_failures_first_with_codes(health, registry) -> None:
    _record(registry, "openapi-3.1", "completed", 4)
    _record(registry, "avro", "completed", 1)
    _record(registry, "avro", "failed", 3)
    _record(registry, "graphql", "failed", 1)
    for code in ("EMIT_FAILED", "EMIT_FAILED", "SOURCE_LOAD_FAILED"):
        registry.record_failure(kind="export", code=code, adapter_or_target="avro")

    targets = health.summary(registry.snapshot())["per_target"]
    assert [entry["target"] for entry in targets] == ["avro", "graphql", "openapi-3.1"]
    avro = targets[0]
    assert (avro["completed"], avro["failed"], avro["canceled"]) == (1, 3, 0)
    assert avro["failure_rate"] == 0.75
    assert avro["failure_codes"] == [
        {"code": "EMIT_FAILED", "count": 2},
        {"code": "SOURCE_LOAD_FAILED", "count": 1},
    ]
    assert targets[2]["failure_rate"] == 0.0


def test_a_failure_code_without_a_job_total_still_lists_its_target(health, registry) -> None:
    """A failure recorded before its terminal job total (the counters are separate)."""
    registry.record_failure(kind="export", code="EMIT_FAILED", adapter_or_target="avro")
    (entry,) = health.summary(registry.snapshot())["per_target"]
    assert entry["target"] == "avro"
    assert entry["failure_rate"] is None
    assert entry["failure_codes"] == [{"code": "EMIT_FAILED", "count": 1}]


# ===========================================================================
# Job duration and p95
# ===========================================================================


def test_buckets_reach_the_job_cap() -> None:
    """The last bound is the 30-minute default job cap, so a capped job is still bucketed."""
    assert JOB_DURATION_BUCKET_UPPER_MS[-1] == 1_800_000
    assert list(JOB_DURATION_BUCKET_UPPER_MS) == sorted(JOB_DURATION_BUCKET_UPPER_MS)


def test_p95_is_the_bound_of_the_bucket_holding_the_95th_job(health) -> None:
    for _ in range(19):
        health.observe(outcome="completed", duration_ms=800)  # ≤ 1 s
    health.observe(outcome="completed", duration_ms=45_000)  # ≤ 60 s
    duration = health.summary({})["job_duration_ms"]
    assert duration["count"] == 20
    assert duration["buckets"]["1000"] == 19
    assert duration["buckets"]["60000"] == 1
    # 0.95 × 20 = 19 jobs, all in the first bucket.
    assert duration["p50_upper_ms"] == 1000
    assert duration["p95_upper_ms"] == 1000
    assert duration["p95_over_last_bucket"] is False

    health.observe(outcome="failed", duration_ms=45_000)
    assert health.summary({})["job_duration_ms"]["p95_upper_ms"] == 60_000


def test_p95_past_the_last_bucket_says_so(health) -> None:
    health.observe(outcome="completed", duration_ms=2_000_000)
    duration = health.summary({})["job_duration_ms"]
    assert duration["buckets"]["inf"] == 1
    assert duration["p95_upper_ms"] == JOB_DURATION_BUCKET_UPPER_MS[-1]
    assert duration["p95_over_last_bucket"] is True


def test_canceled_and_unstarted_jobs_add_no_duration(health) -> None:
    health.observe(outcome="canceled", duration_ms=5_000)
    health.observe(outcome="failed", duration_ms=None)
    duration = health.summary({})["job_duration_ms"]
    assert duration["count"] == 0
    # The unstarted failure still counts toward the alert window.
    assert health.summary({})["alert"]["window_jobs"] == 1


# ===========================================================================
# The failure-rate alert
# ===========================================================================


def _observe(health: ExportJobHealth, completed: int, failed: int) -> None:
    for _ in range(completed):
        health.observe(outcome="completed", duration_ms=500)
    for _ in range(failed):
        health.observe(outcome="failed", duration_ms=500)


def test_alert_waits_for_enough_jobs(health) -> None:
    _observe(health, completed=0, failed=9)
    alert = health.summary({})["alert"]
    assert alert["state"] == ALERT_NO_DATA
    assert alert["window_jobs"] == 9
    assert alert["window_failure_rate"] == 1.0


def test_alert_fires_at_the_threshold_and_not_below(health) -> None:
    _observe(health, completed=9, failed=1)  # 10%
    assert health.summary({})["alert"]["state"] == ALERT_OK
    _observe(health, completed=0, failed=2)  # 3 of 12 = 25%
    alert = health.summary({})["alert"]
    assert alert["state"] == ALERT_FIRING
    assert alert["window_failed"] == 3
    assert alert["threshold_rate"] == 0.2
    assert alert["min_jobs"] == 10


def test_canceled_jobs_do_not_count_toward_the_alert(health) -> None:
    _observe(health, completed=8, failed=2)
    for _ in range(50):
        health.observe(outcome="canceled", duration_ms=500)
    alert = health.summary({})["alert"]
    assert alert["window_jobs"] == 10
    assert alert["state"] == ALERT_FIRING


def test_alert_forgets_jobs_older_than_the_window(health, clock) -> None:
    _observe(health, completed=0, failed=10)
    assert health.summary({})["alert"]["state"] == ALERT_FIRING
    clock.now += 901
    _observe(health, completed=10, failed=0)
    alert = health.summary({})["alert"]
    assert alert["window_jobs"] == 10
    assert alert["window_failed"] == 0
    assert alert["state"] == ALERT_OK


def test_a_zero_rate_turns_the_alert_off(clock) -> None:
    health = ExportJobHealth(rate=0, min_jobs=1, window_seconds=900, clock=clock)
    _observe(health, completed=0, failed=20)
    assert health.summary({})["alert"]["state"] == ALERT_OFF


def test_the_window_is_bounded(clock) -> None:
    health = ExportJobHealth(rate=0.5, min_jobs=1, window_seconds=10**9, clock=clock)
    _observe(health, completed=MAX_WINDOW_JOBS + 5, failed=0)
    assert health.summary({})["alert"]["window_jobs"] == MAX_WINDOW_JOBS


def test_alert_logs_once_when_it_fires_and_once_when_it_clears(health, clock, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.export_job_health"):
        _observe(health, completed=0, failed=12)  # fires on the 10th job, stays firing
        health.summary({})  # reading never logs again while the state holds
        clock.now += 901
        health.summary({})  # the window empties: the alert clears
    lines = [record for record in caplog.records if "export.failure_rate_alert" in record.getMessage()]
    assert len(lines) == 2
    assert lines[0].levelno == logging.WARNING
    assert ALERT_FIRING in lines[0].getMessage()
    assert lines[1].levelno == logging.INFO
    assert ALERT_NO_DATA in lines[1].getMessage()


def test_thresholds_come_from_settings_by_default(monkeypatch, clock) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "export_failure_alert_rate", 0.5)
    monkeypatch.setattr(settings, "export_failure_alert_min_jobs", 2)
    monkeypatch.setattr(settings, "export_failure_alert_window_seconds", 60)
    health = ExportJobHealth(clock=clock)
    _observe(health, completed=1, failed=1)
    alert = health.summary({})["alert"]
    assert (alert["threshold_rate"], alert["min_jobs"], alert["window_seconds"]) == (0.5, 2, 60)
    assert alert["state"] == ALERT_FIRING


def test_reset_clears_everything(health) -> None:
    _observe(health, completed=0, failed=12)
    health.reset()
    summary = health.summary({})
    assert summary["job_duration_ms"]["count"] == 0
    assert summary["alert"]["state"] == ALERT_NO_DATA


def test_the_process_wide_registry_exists() -> None:
    assert isinstance(export_job_health, ExportJobHealth)
