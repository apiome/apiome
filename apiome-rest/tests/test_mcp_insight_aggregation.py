"""Unit tests for the pure MCP insight aggregation layer (V2-MCP-28.2 / MCAT-14.2, #4628).

Exercises :mod:`app.mcp_insight_aggregation` in isolation (no database, no FastAPI): the
``percentile_cont`` port of PostgreSQL's continuous percentile against hand-computed fixtures, the
latency-statistics roll-up, and the discovery/invocation reliability aggregators — including the
empty-sample paths that must yield zero counts and ``None`` statistics rather than raising.
"""

import pytest

from app.mcp_insight_aggregation import (
    DISCOVERY_TIMELINE_WINDOW,
    compute_discovery_reliability,
    compute_discovery_timeline,
    compute_invocation_reliability,
    compute_latency_stats,
    percentile_cont,
)

# ---------------------------------------------------------------------------
# percentile_cont — hand-computed fixtures (must match SQL percentile_cont)
# ---------------------------------------------------------------------------

# sorted → [5, 7, 12, 15, 22, 30, 45, 60, 90, 100], n = 10
_SAMPLE = [12, 5, 30, 7, 100, 45, 22, 60, 15, 90]


def test_percentile_cont_matches_hand_computed_fixture():
    # rank = fraction * (n - 1) = fraction * 9, linearly interpolated between neighbours.
    assert percentile_cont(_SAMPLE, 0.5) == pytest.approx(26.0)  # rank 4.5: 22 + .5*(30-22)
    assert percentile_cont(_SAMPLE, 0.95) == pytest.approx(95.5)  # rank 8.55: 90 + .55*(100-90)
    assert percentile_cont(_SAMPLE, 0.99) == pytest.approx(99.1)  # rank 8.91: 90 + .91*(100-90)


def test_percentile_cont_endpoints_are_min_and_max():
    assert percentile_cont(_SAMPLE, 0.0) == 5.0
    assert percentile_cont(_SAMPLE, 1.0) == 100.0


def test_percentile_cont_single_value_and_empty():
    assert percentile_cont([42], 0.5) == 42.0
    assert percentile_cont([42], 0.99) == 42.0
    assert percentile_cont([], 0.5) is None


def test_percentile_cont_two_values_interpolates():
    # rank = fraction * 1; a straight interpolation between the two samples.
    assert percentile_cont([10, 20], 0.5) == pytest.approx(15.0)
    assert percentile_cont([10, 20], 0.95) == pytest.approx(19.5)


def test_percentile_cont_rejects_out_of_range_fraction():
    with pytest.raises(ValueError):
        percentile_cont(_SAMPLE, 1.5)
    with pytest.raises(ValueError):
        percentile_cont(_SAMPLE, -0.1)


# ---------------------------------------------------------------------------
# compute_latency_stats
# ---------------------------------------------------------------------------


def test_latency_stats_full_sample():
    stats = compute_latency_stats(_SAMPLE)
    assert stats.count == 10
    assert stats.min_ms == 5.0
    assert stats.max_ms == 100.0
    assert stats.avg_ms == pytest.approx(38.6)  # 386 / 10
    assert stats.p50_ms == pytest.approx(26.0)
    assert stats.p95_ms == pytest.approx(95.5)
    assert stats.p99_ms == pytest.approx(99.1)


def test_latency_stats_drops_none_values():
    stats = compute_latency_stats([10, None, 20, None, 40])
    assert stats.count == 3
    assert stats.min_ms == 10.0
    assert stats.max_ms == 40.0
    assert stats.avg_ms == pytest.approx(23.33, abs=0.01)


def test_latency_stats_empty_is_all_none():
    stats = compute_latency_stats([])
    assert stats.count == 0
    assert stats.as_dict() == {
        "count": 0,
        "avg_ms": None,
        "min_ms": None,
        "max_ms": None,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
    }


def test_latency_stats_all_none_sample_is_empty():
    stats = compute_latency_stats([None, None])
    assert stats.count == 0
    assert stats.p50_ms is None


# ---------------------------------------------------------------------------
# compute_discovery_reliability
# ---------------------------------------------------------------------------


def _job(state, duration_ms):
    return {"state": state, "duration_ms": duration_ms}


def test_discovery_reliability_tallies_states_and_success_rate():
    rows = [
        _job("completed", 100.0),
        _job("completed", 200.0),
        _job("failed", 50.0),
        _job("running", None),
        _job("queued", None),
    ]
    rel = compute_discovery_reliability(rows)
    assert rel.job_count == 5
    assert rel.completed_count == 2
    assert rel.failed_count == 1
    assert rel.running_count == 1
    assert rel.queued_count == 1
    # success over terminal jobs only: 2 / (2 + 1)
    assert rel.success_rate == pytest.approx(0.6667, abs=0.0001)
    # latency over the three recorded durations [50, 100, 200]
    assert rel.latency.count == 3
    assert rel.latency.min_ms == 50.0
    assert rel.latency.max_ms == 200.0
    assert rel.latency.p50_ms == pytest.approx(100.0)


def test_discovery_reliability_success_rate_zero_without_terminal_jobs():
    rel = compute_discovery_reliability([_job("queued", None), _job("running", None)])
    assert rel.success_rate == 0.0
    assert rel.latency.count == 0
    assert rel.latency.p95_ms is None


def test_discovery_reliability_empty():
    rel = compute_discovery_reliability([])
    assert rel.job_count == 0
    assert rel.success_rate == 0.0
    assert rel.latency.count == 0
    assert rel.as_dict()["latency"]["avg_ms"] is None


def test_discovery_reliability_ignores_unknown_state():
    rel = compute_discovery_reliability([_job("cancelled", 10.0)])
    assert rel.job_count == 1
    assert rel.completed_count == 0
    assert rel.failed_count == 0
    assert rel.success_rate == 0.0
    # the duration is still counted toward latency even for an unknown state
    assert rel.latency.count == 1


# ---------------------------------------------------------------------------
# compute_invocation_reliability
# ---------------------------------------------------------------------------


def _call(is_error, latency_ms):
    return {"is_error": is_error, "latency_ms": latency_ms}


def test_invocation_reliability_error_rate_and_latency():
    rows = [
        _call(False, 10),
        _call(True, 20),
        _call(False, None),
        _call(True, 40),
    ]
    rel = compute_invocation_reliability(rows)
    assert rel.call_count == 4
    assert rel.error_count == 2
    assert rel.success_count == 2
    assert rel.error_rate == pytest.approx(0.5)
    # latency over the three recorded latencies [10, 20, 40]
    assert rel.latency.count == 3
    assert rel.latency.min_ms == 10.0
    assert rel.latency.max_ms == 40.0
    assert rel.latency.p50_ms == pytest.approx(20.0)


def test_invocation_reliability_empty():
    rel = compute_invocation_reliability([])
    assert rel.call_count == 0
    assert rel.error_count == 0
    assert rel.error_rate == 0.0
    assert rel.latency.count == 0
    assert rel.as_dict()["latency"]["p99_ms"] is None


# ---------------------------------------------------------------------------
# compute_discovery_timeline (V2-MCP-31.1 / MCAT-17.1)
# ---------------------------------------------------------------------------


def _timeline_job(
    job_id,
    state,
    *,
    trigger="sweep",
    error_code=None,
    duration_ms=None,
    created_at="2026-07-06T12:00:00+00:00",
):
    return {
        "id": job_id,
        "state": state,
        "trigger": trigger,
        "error_code": error_code,
        "duration_ms": duration_ms,
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
    }


def test_discovery_timeline_outcomes_and_availability():
    # 3 ok, 1 failed → availability 3 / (3 + 1) = 75%; the running job is pending, not counted.
    rows = [
        _timeline_job("j5", "running"),
        _timeline_job("j4", "completed", duration_ms=120.0),
        _timeline_job("j3", "failed", error_code="connect_error"),
        _timeline_job("j2", "completed"),
        _timeline_job("j1", "completed"),
    ]
    tl = compute_discovery_timeline(rows)
    assert tl.event_count == 5
    assert tl.ok_count == 3
    assert tl.failed_count == 1
    assert tl.pending_count == 1
    assert tl.terminal_count == 4
    assert tl.availability_pct == pytest.approx(75.0)
    # Newest-first order is preserved and outcomes are derived per job.
    assert [e.outcome for e in tl.events] == ["pending", "ok", "connect_error", "ok", "ok"]
    assert tl.events[1].duration_ms == 120.0
    assert tl.events[2].error_code == "connect_error"
    assert tl.truncated is False


def test_discovery_timeline_failed_without_code_is_bare_failed():
    tl = compute_discovery_timeline([_timeline_job("j1", "failed", error_code=None)])
    assert tl.events[0].outcome == "failed"
    assert tl.events[0].error_code is None
    assert tl.failed_count == 1
    # A single failed terminal job → 0% availability, not None.
    assert tl.availability_pct == pytest.approx(0.0)


def test_discovery_timeline_empty_has_none_availability():
    tl = compute_discovery_timeline([])
    assert tl.event_count == 0
    assert tl.terminal_count == 0
    assert tl.availability_pct is None
    assert tl.as_dict()["events"] == []


def test_discovery_timeline_all_pending_has_none_availability():
    tl = compute_discovery_timeline(
        [_timeline_job("j2", "running"), _timeline_job("j1", "queued")]
    )
    assert tl.pending_count == 2
    assert tl.terminal_count == 0
    assert tl.availability_pct is None


def test_discovery_timeline_caps_to_window_and_flags_truncation():
    rows = [_timeline_job(f"j{i}", "completed") for i in range(5)]
    tl = compute_discovery_timeline(rows, window=3)
    assert tl.window == 3
    assert tl.event_count == 3
    assert tl.truncated is True
    # Availability is computed over the window only, not the dropped older jobs.
    assert tl.availability_pct == pytest.approx(100.0)


def test_discovery_timeline_default_window_is_the_module_constant():
    tl = compute_discovery_timeline([])
    assert tl.window == DISCOVERY_TIMELINE_WINDOW
