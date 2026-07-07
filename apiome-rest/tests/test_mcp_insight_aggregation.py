"""Unit tests for the pure MCP insight aggregation layer (V2-MCP-28.2 / MCAT-14.2, #4628).

Exercises :mod:`app.mcp_insight_aggregation` in isolation (no database, no FastAPI): the
``percentile_cont`` port of PostgreSQL's continuous percentile against hand-computed fixtures, the
latency-statistics roll-up, and the discovery/invocation reliability aggregators — including the
empty-sample paths that must yield zero counts and ``None`` statistics rather than raising.
"""

import pytest

from app.mcp_insight_aggregation import (
    DISCOVERY_TIMELINE_WINDOW,
    RESPONSIVENESS_LATENCY_CEILING_MS,
    RESPONSIVENESS_LATENCY_FLOOR_MS,
    TOOL_LATENCY_WINDOW_DAYS,
    build_capability_embedding_text,
    capability_name_set,
    compute_capability_overlap,
    compute_discovery_reliability,
    compute_discovery_timeline,
    compute_invocation_reliability,
    compute_latency_stats,
    compute_endpoint_percentile_axes,
    compute_peer_percentiles,
    compute_tool_count_histogram,
    compute_tool_reliability,
    compute_trust_profile,
    cosine_similarity,
    jaccard_similarity,
    mcp_auth_posture,
    normalize_capability_name,
    percentile_cont,
    percentile_rank,
    rank_embedding_neighbors,
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


# ---------------------------------------------------------------------------
# compute_tool_reliability (V2-MCP-31.2 / MCAT-17.2)
# ---------------------------------------------------------------------------


def _tool_call(item_name, is_error, latency_ms):
    return {"item_name": item_name, "is_error": is_error, "latency_ms": latency_ms}


def test_tool_reliability_percentiles_and_error_rates_match_fixture():
    # search: 4 calls (1 error), latencies [10, 20, 30, 40] → p50 = 25.0, error_rate = 0.25
    # write:  2 calls (2 errors), latencies [100, 300]      → p50 = 200.0, error_rate = 1.0
    rows = [
        _tool_call("search", False, 10),
        _tool_call("search", False, 20),
        _tool_call("search", True, 30),
        _tool_call("search", False, 40),
        _tool_call("write", True, 100),
        _tool_call("write", True, 300),
    ]
    rel = compute_tool_reliability(rows, window_days=7)

    assert rel.window_days == 7
    assert rel.tool_count == 2
    assert rel.call_count == 6
    assert rel.error_count == 3
    assert rel.success_count == 3
    assert rel.error_rate == pytest.approx(0.5)

    # Busiest tool first (search has 4 calls, write has 2).
    by_name = {tool.tool_name: tool for tool in rel.tools}
    assert [tool.tool_name for tool in rel.tools] == ["search", "write"]

    search = by_name["search"]
    assert search.call_count == 4
    assert search.error_count == 1
    assert search.error_rate == pytest.approx(0.25)
    assert search.latency.p50_ms == pytest.approx(25.0)  # rank 1.5 → 20 + .5*(30-20)
    assert search.latency.min_ms == 10.0
    assert search.latency.max_ms == 40.0

    write = by_name["write"]
    assert write.error_rate == pytest.approx(1.0)
    assert write.latency.p50_ms == pytest.approx(200.0)


def test_tool_reliability_empty_is_no_data():
    rel = compute_tool_reliability([])
    assert rel.tools == []
    assert rel.tool_count == 0
    assert rel.call_count == 0
    assert rel.error_rate == 0.0
    assert rel.window_days == TOOL_LATENCY_WINDOW_DAYS
    # The distribution is still the full, all-zero bucket set (a stable chart shape).
    assert [bucket.count for bucket in rel.latency_distribution] == [0] * len(
        rel.latency_distribution
    )
    assert rel.as_dict()["tools"] == []


def test_tool_reliability_single_call_tool_has_no_divide_by_zero():
    rel = compute_tool_reliability([_tool_call("solo", False, 42)])
    assert rel.tool_count == 1
    solo = rel.tools[0]
    assert solo.call_count == 1
    assert solo.error_rate == 0.0
    # A one-sample percentile is that sample; no ZeroDivisionError anywhere.
    assert solo.latency.count == 1
    assert solo.latency.p50_ms == pytest.approx(42.0)
    assert solo.latency.p95_ms == pytest.approx(42.0)
    assert solo.latency.p99_ms == pytest.approx(42.0)


def test_tool_reliability_latency_distribution_buckets_by_range():
    # Boundaries are exclusive uppers: 40→[0-50), 50→[50-100), 250→[250-500), 3000→[2.5s+].
    rows = [
        _tool_call("t", False, 40),
        _tool_call("t", False, 50),
        _tool_call("t", False, 250),
        _tool_call("t", False, 3000),
        _tool_call("t", True, None),  # no latency → not in the distribution
    ]
    rel = compute_tool_reliability(rows)
    dist = {bucket.label: bucket.count for bucket in rel.latency_distribution}
    assert dist["0–50 ms"] == 1  # 40
    assert dist["50–100 ms"] == 1  # 50 (upper of the previous bucket is exclusive)
    assert dist["250–500 ms"] == 1  # 250
    assert dist["2.5 s+"] == 1  # 3000
    # Only the four calls with a recorded latency are bucketed.
    assert sum(dist.values()) == 4


def test_tool_reliability_missing_item_name_bucketed_as_unknown():
    rel = compute_tool_reliability([_tool_call(None, False, 5), _tool_call("", True, 6)])
    assert rel.tool_count == 1
    assert rel.tools[0].tool_name == "(unknown)"
    assert rel.tools[0].call_count == 2
    assert rel.call_count == 2  # totals never disagree with the per-tool breakdown


# ---------------------------------------------------------------------------
# compute_trust_profile — composite five-axis radar (V2-MCP-31.4 / MCAT-17.4)
# ---------------------------------------------------------------------------

# A fully-measured server: every axis has its input, so no axis is a gap.
_FULL_TRUST_INPUTS = dict(
    quality_score=84,
    quality_grade="B",
    annotation_coverage={"tool_count": 4, "annotated_tools": 3},
    documentation_coverage={
        "item_count": 5,
        "description_pct": 80.0,
        "title_pct": 60.0,
        "tool_param_count": 0,
        "tool_param_description_pct": 0.0,
    },
    destructive_tool_count=1,
    auth_posture="authenticated",
    change_severities=[{"breaking": 0}, {"breaking": 1}, {"breaking": 0}],
    invocation={"call_count": 20, "error_rate": 0.1, "latency": {"p95_ms": 200.0}},
)


def _trust(**overrides):
    """Compute a trust profile from the full-inputs baseline with per-test overrides."""
    inputs = {**_FULL_TRUST_INPUTS, **overrides}
    profile = compute_trust_profile(**inputs)
    return profile, {axis.key: axis for axis in profile.axes}


def test_trust_profile_all_axes_available_averages_the_five():
    profile, axes = _trust()
    assert profile.axis_count == 5
    assert profile.available_count == 5
    # quality 84, safety 87.5, documentation 70, stability 66.7, responsiveness 95.0
    assert axes["quality"].value == pytest.approx(84.0)
    assert axes["safety"].value == pytest.approx(87.5)
    assert axes["documentation"].value == pytest.approx(70.0)
    assert axes["stability"].value == pytest.approx(66.7)
    assert axes["responsiveness"].value == pytest.approx(95.0)
    assert all(axis.available for axis in profile.axes)
    # overall is the mean of the five available axes.
    assert profile.overall == pytest.approx(round((84.0 + 87.5 + 70.0 + 66.7 + 95.0) / 5, 1))
    # canonical clockwise order is stable.
    assert [axis.key for axis in profile.axes] == [
        "quality",
        "safety",
        "documentation",
        "stability",
        "responsiveness",
    ]
    # every axis carries a non-empty methodology (shown on hover) and a detail line.
    assert all(axis.methodology and axis.detail for axis in profile.axes)


def test_trust_profile_quality_reads_score_and_grade():
    _, axes = _trust(quality_score=91, quality_grade="A")
    assert axes["quality"].value == pytest.approx(91.0)
    assert axes["quality"].detail == "Grade A · 91/100"


def test_trust_profile_missing_quality_is_a_gap_not_a_zero():
    profile, axes = _trust(quality_score=None, quality_grade=None)
    assert axes["quality"].available is False
    assert axes["quality"].value is None
    assert axes["quality"].detail == "Not yet scored"
    # the gap is excluded from the composite (four axes remain).
    assert profile.available_count == 4


def test_trust_profile_safety_penalizes_destructive_without_auth():
    # 3/4 annotated → transparency 0.75; anonymous + 1 destructive → guardedness 0.75.
    _, axes = _trust(auth_posture="anonymous", destructive_tool_count=1)
    assert axes["safety"].value == pytest.approx(75.0)
    assert "destructive with no auth" in axes["safety"].detail


def test_trust_profile_safety_authenticated_ignores_destructive():
    # Same surface but authenticated → guardedness 1.0 regardless of destructive tools.
    _, axes = _trust(auth_posture="authenticated", destructive_tool_count=3)
    assert axes["safety"].value == pytest.approx(87.5)


def test_trust_profile_safety_gap_when_no_tools():
    _, axes = _trust(annotation_coverage={"tool_count": 0, "annotated_tools": 0})
    assert axes["safety"].available is False
    assert axes["safety"].value is None
    assert axes["safety"].detail == "No tools to assess"


def test_trust_profile_documentation_includes_params_only_when_present():
    # No params → mean of description/title only.
    _, axes = _trust()
    assert axes["documentation"].value == pytest.approx(70.0)
    # With params → the third component pulls the mean down.
    _, axes_params = _trust(
        documentation_coverage={
            "item_count": 5,
            "description_pct": 80.0,
            "title_pct": 60.0,
            "tool_param_count": 3,
            "tool_param_description_pct": 40.0,
        }
    )
    assert axes_params["documentation"].value == pytest.approx(60.0)


def test_trust_profile_documentation_gap_when_no_items():
    _, axes = _trust(documentation_coverage={"item_count": 0})
    assert axes["documentation"].available is False
    assert axes["documentation"].value is None


def test_trust_profile_stability_is_non_breaking_transition_rate():
    # 1 of 3 transitions breaking → 2/3 non-breaking.
    _, axes = _trust(change_severities=[{"breaking": 0}, {"breaking": 2}, {"breaking": 0}])
    assert axes["stability"].value == pytest.approx(66.7)
    assert axes["stability"].detail == "2/3 snapshot changes non-breaking"


def test_trust_profile_stability_gap_when_no_transitions():
    profile, axes = _trust(change_severities=[])
    assert axes["stability"].available is False
    assert axes["stability"].value is None
    assert axes["stability"].detail == "Not enough history"


def test_trust_profile_responsiveness_blends_error_rate_and_latency():
    # error_rate 0.1 → reliability 90; p95 200ms → latency 100; mean → 95.
    _, axes = _trust(invocation={"call_count": 5, "error_rate": 0.1, "latency": {"p95_ms": 200.0}})
    assert axes["responsiveness"].value == pytest.approx(95.0)
    assert "p95 200 ms" in axes["responsiveness"].detail


def test_trust_profile_responsiveness_without_latency_is_reliability_only():
    _, axes = _trust(invocation={"call_count": 5, "error_rate": 0.2, "latency": {"p95_ms": None}})
    assert axes["responsiveness"].value == pytest.approx(80.0)
    assert axes["responsiveness"].detail == "20.0% errors"


def test_trust_profile_responsiveness_gap_when_never_tested():
    profile, axes = _trust(invocation={"call_count": 0, "error_rate": 0.0, "latency": {}})
    assert axes["responsiveness"].available is False
    assert axes["responsiveness"].value is None
    assert axes["responsiveness"].detail == "Never tested"


def test_trust_profile_all_gaps_yields_none_overall():
    profile = compute_trust_profile(
        quality_score=None,
        quality_grade=None,
        annotation_coverage={},
        documentation_coverage={},
        destructive_tool_count=0,
        auth_posture="anonymous",
        change_severities=[],
        invocation={"call_count": 0, "error_rate": 0.0, "latency": {}},
    )
    assert profile.available_count == 0
    assert profile.overall is None
    assert all(axis.value is None and not axis.available for axis in profile.axes)


def test_trust_profile_latency_floor_and_ceiling():
    # p95 at/below the floor scores full; at/above the ceiling scores zero (reliability held at 100).
    _, fast = _trust(
        invocation={
            "call_count": 5,
            "error_rate": 0.0,
            "latency": {"p95_ms": RESPONSIVENESS_LATENCY_FLOOR_MS},
        }
    )
    assert fast["responsiveness"].value == pytest.approx(100.0)
    _, slow = _trust(
        invocation={
            "call_count": 5,
            "error_rate": 0.0,
            "latency": {"p95_ms": RESPONSIVENESS_LATENCY_CEILING_MS},
        }
    )
    # reliability 100 * 0.5 + latency 0 * 0.5 → 50.
    assert slow["responsiveness"].value == pytest.approx(50.0)


def test_mcp_auth_posture_bands():
    assert mcp_auth_posture(None) == "anonymous"
    assert mcp_auth_posture("") == "anonymous"
    assert mcp_auth_posture("none") == "anonymous"
    assert mcp_auth_posture("None") == "anonymous"
    assert mcp_auth_posture("bearer") == "authenticated"
    assert mcp_auth_posture("oauth2") == "authenticated"


# ---------------------------------------------------------------------------
# compute_tool_count_histogram — catalog tool-count distribution (18.1)
# ---------------------------------------------------------------------------

_TOOL_BUCKET_LABELS = ["0", "1–5", "6–20", "21–50", "50+"]


def test_tool_count_histogram_empty_catalog_is_all_zero_buckets():
    # An empty catalog still yields the full, stable set of bars — every bucket at zero.
    hist = compute_tool_count_histogram([])
    assert [b.label for b in hist] == _TOOL_BUCKET_LABELS
    assert [b.count for b in hist] == [0, 0, 0, 0, 0]


def test_tool_count_histogram_bucket_boundaries():
    # Boundary values land in the bucket whose *inclusive* upper bound they do not exceed:
    # 0→"0", 1&5→"1–5", 6&20→"6–20", 21&50→"21–50", 51+→"50+".
    counts = [0, 1, 5, 6, 20, 21, 50, 51, 1000]
    hist = compute_tool_count_histogram(counts)
    by_label = {b.label: b.count for b in hist}
    assert by_label == {"0": 1, "1–5": 2, "6–20": 2, "21–50": 2, "50+": 2}


def test_tool_count_histogram_none_counts_as_zero():
    # A never-discovered endpoint reports no surface (None) and must land in the "0" column, not drop.
    hist = compute_tool_count_histogram([None, None, 3])
    by_label = {b.label: b.count for b in hist}
    assert by_label["0"] == 2
    assert by_label["1–5"] == 1
    # the total across buckets always equals the number of endpoints supplied.
    assert sum(b.count for b in hist) == 3


def test_tool_count_histogram_as_dict_shape():
    hist = compute_tool_count_histogram([7])
    assert hist[2].as_dict() == {"label": "6–20", "count": 1}


# ---------------------------------------------------------------------------
# percentile_rank (peer percentile & category ranking — MCAT-18.3)
# ---------------------------------------------------------------------------


def test_percentile_rank_matches_hand_computed_cohort():
    # cohort of 5, sorted → [40, 55, 70, 80, 90]; each target's "share at or below".
    values = [70, 40, 90, 55, 80]
    assert percentile_rank(values, 90) == 100.0  # all 5 at or below → leader
    assert percentile_rank(values, 70) == 60.0  # 3 of 5 (40,55,70) at or below
    assert percentile_rank(values, 40) == 20.0  # 1 of 5 at or below → bottom


def test_percentile_rank_single_member_is_leader():
    # A one-member cohort: the sole server is trivially the top of its category.
    assert percentile_rank([73.0], 73.0) == 100.0


def test_percentile_rank_ties_count_toward_the_share():
    # Equal-valued peers all count as "at or below", so tied leaders both read 100.
    assert percentile_rank([80, 80, 80], 80) == 100.0
    assert percentile_rank([50, 80, 80], 80) == 100.0
    assert percentile_rank([50, 80, 80], 50) == pytest.approx(33.3, abs=0.05)


def test_percentile_rank_empty_cohort_is_none():
    assert percentile_rank([], 10.0) is None


# ---------------------------------------------------------------------------
# compute_endpoint_percentile_axes — reuses the trust axis derivations
# ---------------------------------------------------------------------------


def _annotation_coverage(tool_count, annotated_tools):
    return {"tool_count": tool_count, "annotated_tools": annotated_tools}


def _documentation_coverage(item_count, description_pct, title_pct, tool_param_count=0, tool_param_description_pct=0.0):
    return {
        "item_count": item_count,
        "description_pct": description_pct,
        "title_pct": title_pct,
        "tool_param_count": tool_param_count,
        "tool_param_description_pct": tool_param_description_pct,
    }


def test_endpoint_percentile_axes_all_measured():
    axes = compute_endpoint_percentile_axes(
        score=82,
        grade="B",
        annotation_coverage=_annotation_coverage(4, 4),  # fully annotated
        documentation_coverage=_documentation_coverage(10, 80.0, 60.0),  # mean 70
        destructive_tool_count=0,
        auth_posture="authenticated",
        invocation={"call_count": 5, "error_rate": 0.0, "latency": {"p95_ms": 200.0}},
    )
    assert axes["grade"] == 82.0
    # safety: transparency 1.0, guardedness 1.0 (authenticated) → 100
    assert axes["safety"] == 100.0
    # documentation: mean(80, 60) = 70 (no tool params)
    assert axes["documentation"] == 70.0
    # latency: p95 at the 200ms floor → full marks
    assert axes["latency"] == 100.0


def test_endpoint_percentile_axes_gaps_when_inputs_missing():
    # Never scored, no tools, no capabilities, never tested → every axis is a gap.
    axes = compute_endpoint_percentile_axes(
        score=None,
        grade=None,
        annotation_coverage={},
        documentation_coverage={},
        destructive_tool_count=0,
        auth_posture="anonymous",
        invocation={"call_count": 0, "error_rate": 0.0, "latency": {}},
    )
    assert axes == {"grade": None, "safety": None, "documentation": None, "latency": None}


def test_endpoint_percentile_axes_latency_gap_without_p95():
    axes = compute_endpoint_percentile_axes(
        score=50,
        grade="C",
        annotation_coverage={},
        documentation_coverage={},
        destructive_tool_count=0,
        auth_posture="authenticated",
        invocation={"call_count": 3, "error_rate": 0.0, "latency": {"p95_ms": None}},
    )
    assert axes["latency"] is None  # a call recorded but no completed latency → latency gap


# ---------------------------------------------------------------------------
# compute_peer_percentiles — the seeded-cohort acceptance criterion
# ---------------------------------------------------------------------------


def test_peer_percentiles_rank_target_within_seeded_cohort():
    # A four-member cohort; the target ("finance-a") leads on documentation, mid on grade.
    cohort_axis_values = {
        "grade": [90.0, 70.0, 60.0, 80.0],
        "safety": [100.0, 50.0, 75.0, 25.0],
        "documentation": [95.0, 40.0, 55.0, 70.0],
        "latency": [100.0, 20.0, 60.0, 80.0],
    }
    target = {"grade": 80.0, "safety": 100.0, "documentation": 95.0, "latency": 100.0}
    profile = compute_peer_percentiles(
        category="finance",
        cohort_size=4,
        target_axis_values=target,
        cohort_axis_values=cohort_axis_values,
    )
    assert profile.category == "finance"
    assert profile.cohort_size == 4
    by_key = {axis.key: axis for axis in profile.axes}

    # documentation: target 95 is the max of the cohort → rank 1, percentile 100, top 25%.
    docs = by_key["documentation"]
    assert docs.available is True
    assert docs.value == 95.0
    assert docs.rank == 1
    assert docs.percentile == 100.0
    assert docs.top_percent == 25  # ceil(100 * 1 / 4)
    assert docs.cohort_size == 4
    assert "top 25%" in docs.detail

    # grade: target 80 has 2 of 4 (70,80... actually {60,70,80} at or below) → percentile 75, rank 2.
    grade = by_key["grade"]
    assert grade.percentile == 75.0  # 3 of 4 (60,70,80) at or below
    assert grade.rank == 2  # only 90 is strictly above
    assert grade.top_percent == 50  # ceil(100 * 2 / 4)


def test_peer_percentiles_single_member_category():
    # A lone server in its category is trivially the leader on every measured axis.
    target = {"grade": 73.0, "safety": None, "documentation": 40.0, "latency": None}
    cohort_axis_values = {"grade": [73.0], "documentation": [40.0]}
    profile = compute_peer_percentiles(
        category="niche",
        cohort_size=1,
        target_axis_values=target,
        cohort_axis_values=cohort_axis_values,
    )
    by_key = {axis.key: axis for axis in profile.axes}
    assert by_key["grade"].percentile == 100.0
    assert by_key["grade"].rank == 1
    assert by_key["grade"].top_percent == 100
    assert "Only server" in by_key["grade"].detail
    # unmeasured axes are explicit gaps, not zeros.
    assert by_key["safety"].available is False
    assert by_key["safety"].value is None
    assert by_key["safety"].percentile is None


def test_peer_percentiles_gap_axis_when_target_missing_value():
    # The cohort has documentation values but the target itself was never measured on it → gap.
    profile = compute_peer_percentiles(
        category="weather",
        cohort_size=3,
        target_axis_values={"grade": 60.0, "documentation": None},
        cohort_axis_values={"grade": [60.0, 80.0], "documentation": [70.0, 90.0]},
    )
    by_key = {axis.key: axis for axis in profile.axes}
    assert by_key["documentation"].available is False
    assert by_key["documentation"].percentile is None
    # cohort_size on the axis still reflects the peers that DO have it measured.
    assert by_key["documentation"].cohort_size == 2
    assert by_key["documentation"].detail == "Not measured"


def test_peer_percentiles_as_dict_shape():
    profile = compute_peer_percentiles(
        category=None,
        cohort_size=1,
        target_axis_values={"grade": 50.0},
        cohort_axis_values={"grade": [50.0]},
    )
    payload = profile.as_dict()
    assert payload["category"] is None
    assert payload["cohort_size"] == 1
    assert [axis["key"] for axis in payload["axes"]] == [
        "grade",
        "safety",
        "documentation",
        "latency",
    ]
    grade_axis = payload["axes"][0]
    assert set(grade_axis) == {
        "key",
        "label",
        "value",
        "percentile",
        "rank",
        "top_percent",
        "cohort_size",
        "available",
        "detail",
    }


# ---------------------------------------------------------------------------
# Similar servers: capability overlap (Jaccard) — MCAT-18.4
# ---------------------------------------------------------------------------


def test_normalize_and_capability_name_set_fold_case_and_blanks():
    assert normalize_capability_name("  Get_Weather ") == "get_weather"
    assert normalize_capability_name(None) == ""
    # Case-folded, blank-dropped, de-duplicated into a set.
    assert capability_name_set(["Get", "get", " ", None, "List"]) == {"get", "list"}


def test_jaccard_similarity_matches_hand_computed_fixture():
    a = {"get_weather", "get_forecast", "list_cities"}
    b = {"get_weather", "get_forecast", "get_alerts"}
    # intersection {get_weather, get_forecast} = 2; union = 4 → 0.5.
    assert jaccard_similarity(a, b) == pytest.approx(0.5)
    # No overlap → 0; identical → 1; both empty → 0 (never a divide-by-zero).
    assert jaccard_similarity({"x"}, {"y"}) == 0.0
    assert jaccard_similarity(a, set(a)) == 1.0
    assert jaccard_similarity(set(), set()) == 0.0


# A small seeded catalog: the target shares 2 of its 3 tools with "near", 1 with "mid", 0 with "far".
_TARGET_NAMES = ["get_weather", "get_forecast", "list_cities"]
_OVERLAP_CANDIDATES = [
    {
        "endpoint_id": "near",
        "name": "Near Weather",
        "slug": "near-weather",
        "category": "weather",
        "capability_names": ["Get_Weather", "get_forecast", "get_alerts"],
    },
    {
        "endpoint_id": "mid",
        "name": "Mid Weather",
        "slug": "mid-weather",
        "category": "weather",
        "capability_names": ["get_weather", "unrelated_a", "unrelated_b", "unrelated_c"],
    },
    {
        "endpoint_id": "far",
        "name": "Far Finance",
        "slug": "far-finance",
        "category": "finance",
        "capability_names": ["pay_invoice", "list_accounts"],
    },
]


def test_capability_overlap_ranks_and_matches_fixture():
    result = compute_capability_overlap(_TARGET_NAMES, _OVERLAP_CANDIDATES, limit=10)
    # "far" shares nothing → excluded; ranked by descending Jaccard.
    assert [n.endpoint_id for n in result] == ["near", "mid"]

    near = result[0]
    # near: intersection {get_weather, get_forecast} = 2; union {get_weather, get_forecast,
    # list_cities, get_alerts} = 4 → 0.5. Name-match is case-insensitive ("Get_Weather").
    assert near.similarity == pytest.approx(0.5)
    assert near.shared_count == 2
    assert near.shared_capabilities == ["get_forecast", "get_weather"]
    assert near.target_capability_count == 3
    assert near.candidate_capability_count == 3

    mid = result[1]
    # mid: intersection {get_weather} = 1; union = 6 → 0.1667.
    assert mid.similarity == pytest.approx(0.1667, abs=0.0005)
    assert mid.shared_count == 1


def test_capability_overlap_empty_target_yields_no_neighbours():
    assert compute_capability_overlap([], _OVERLAP_CANDIDATES) == []
    assert compute_capability_overlap(["  ", None], _OVERLAP_CANDIDATES) == []


def test_capability_overlap_respects_limit_and_stable_tie_order():
    # Two candidates with identical overlap (0.5) tie on similarity and shared_count; ordered by name.
    cands = [
        {"endpoint_id": "b", "name": "Bravo", "capability_names": ["get_weather", "get_forecast"]},
        {"endpoint_id": "a", "name": "Alpha", "capability_names": ["get_weather", "get_forecast"]},
    ]
    ranked = compute_capability_overlap(_TARGET_NAMES, cands, limit=1)
    assert len(ranked) == 1
    assert ranked[0].endpoint_id == "a"  # "Alpha" < "Bravo"


def test_capability_overlap_as_dict_shape():
    neighbor = compute_capability_overlap(_TARGET_NAMES, _OVERLAP_CANDIDATES)[0]
    assert set(neighbor.as_dict()) == {
        "endpoint_id",
        "name",
        "slug",
        "category",
        "similarity",
        "shared_count",
        "target_capability_count",
        "candidate_capability_count",
        "shared_capabilities",
    }


# ---------------------------------------------------------------------------
# Similar servers: semantic embeddings (cosine NN) — MCAT-18.4
# ---------------------------------------------------------------------------


def test_cosine_similarity_matches_hand_computed_values():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)  # identical direction
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)  # orthogonal
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)  # opposite
    # Undefined cases → None (never a divide-by-zero): zero vector or mismatched dimensions.
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) is None
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0]) is None
    assert cosine_similarity([], []) is None


# Seeded vectors: "near" points almost exactly along the target, "mid" is off-axis, "far" is opposite.
_TARGET_VEC = [1.0, 0.0, 0.0]
_EMBEDDING_CANDIDATES = [
    {"endpoint_id": "mid", "name": "Mid", "embedding": [0.6, 0.8, 0.0]},
    {"endpoint_id": "near", "name": "Near", "embedding": [0.99, 0.14, 0.0]},
    {"endpoint_id": "far", "name": "Far", "embedding": [-1.0, 0.0, 0.0]},
    {"endpoint_id": "novec", "name": "NoVec", "embedding": None},
]


def test_rank_embedding_neighbors_orders_by_cosine_on_seeded_data():
    # A negative floor includes the opposite-direction vector so the full ordering is exercised.
    ranked = rank_embedding_neighbors(
        _TARGET_VEC, _EMBEDDING_CANDIDATES, limit=10, min_similarity=-1.0
    )
    # "novec" has no embedding → dropped. Ordered nearest-first: near > mid > far.
    assert [n.endpoint_id for n in ranked] == ["near", "mid", "far"]
    assert ranked[0].similarity == pytest.approx(0.99, abs=0.005)
    assert ranked[-1].similarity == pytest.approx(-1.0)


def test_rank_embedding_neighbors_default_floor_drops_dissimilar_neighbours():
    # The default 0.0 floor keeps only same-hemisphere (non-negative cosine) peers, so an
    # opposite-direction server ("far", cosine -1) is not surfaced as "similar".
    ranked = rank_embedding_neighbors(_TARGET_VEC, _EMBEDDING_CANDIDATES, limit=10)
    assert [n.endpoint_id for n in ranked] == ["near", "mid"]


def test_rank_embedding_neighbors_min_similarity_floor_and_limit():
    ranked = rank_embedding_neighbors(
        _TARGET_VEC, _EMBEDDING_CANDIDATES, limit=1, min_similarity=0.0
    )
    # far (-1.0) is below the 0.0 floor and would be dropped anyway; limit=1 keeps only the nearest.
    assert [n.endpoint_id for n in ranked] == ["near"]


def test_rank_embedding_neighbors_no_op_without_target_or_candidate_vectors():
    # No target embedding → empty (the embeddings-disabled path), never an error.
    assert rank_embedding_neighbors(None, _EMBEDDING_CANDIDATES) == []
    assert rank_embedding_neighbors([], _EMBEDDING_CANDIDATES) == []
    # Target present but no candidate carries a vector → empty (unbackfilled peers).
    assert rank_embedding_neighbors(_TARGET_VEC, [{"endpoint_id": "x", "name": "X", "embedding": None}]) == []


def test_rank_embedding_neighbors_skips_mismatched_dimensions():
    ranked = rank_embedding_neighbors(
        _TARGET_VEC,
        [
            {"endpoint_id": "good", "name": "Good", "embedding": [1.0, 0.0, 0.0]},
            {"endpoint_id": "wrongdim", "name": "WrongDim", "embedding": [1.0, 0.0]},
        ],
    )
    assert [n.endpoint_id for n in ranked] == ["good"]


# ---------------------------------------------------------------------------
# Similar servers: embedding text builder — MCAT-18.4
# ---------------------------------------------------------------------------


def test_build_capability_embedding_text_is_deterministic_and_order_independent():
    a = build_capability_embedding_text(
        [("get_weather", "Current weather"), ("list_cities", "Known cities")]
    )
    b = build_capability_embedding_text(
        [("list_cities", "Known cities"), ("get_weather", "Current weather")]
    )
    assert a == b  # sorted → order-independent
    assert a == "get_weather: Current weather\nlist_cities: Known cities"


def test_build_capability_embedding_text_drops_blank_names_and_dedupes():
    text = build_capability_embedding_text(
        [("", "no name"), (None, "still none"), ("solo", None), ("solo", None)]
    )
    # Blank/None names dropped; a missing description contributes just the name; duplicates collapse.
    assert text == "solo"


def test_build_capability_embedding_text_empty_when_no_named_capabilities():
    assert build_capability_embedding_text([]) == ""
    assert build_capability_embedding_text([("", ""), (None, "x")]) == ""
