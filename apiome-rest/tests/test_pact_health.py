"""The pure half of the contract health rollup — PFX-6.3 (#6955).

:mod:`app.pact_health` decides; these tests pin:

* the windows (7d / 30d / 90d), their whole buckets ending with today (UTC), and the refusals;
* each metric, with ``None`` where there is nothing to divide by;
* every component's outcomes and thresholds;
* the fused state: worst component wins, ``unknown`` never makes a pair worse;
* the trend: every bucket, oldest first, empty ones included, out-of-window indexes ignored.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.pact_health import (
    CODE_FLAKY,
    CODE_LATEST_FAILED,
    CODE_LATEST_PASSED,
    CODE_LOW_PASS_RATE,
    CODE_NO_RUNS,
    CODE_NO_WEBHOOK_FIRINGS,
    CODE_NOT_FLAKY,
    CODE_NOT_SWEPT,
    CODE_OVERDUE,
    CODE_PASS_RATE_OK,
    CODE_REPUBLISH_NONE,
    CODE_REPUBLISH_OPEN,
    CODE_SLIGHTLY_FLAKY,
    CODE_STATE_INVALID,
    CODE_TOO_FEW_RUNS,
    CODE_UNVERIFIED,
    CODE_UP_TO_DATE,
    CODE_WEBHOOKS_FAILING,
    CODE_WEBHOOKS_OK,
    CODE_WINDOW_INVALID,
    COMPONENT_KEYS,
    STATE_DEGRADED,
    STATE_FAILING,
    STATE_HEALTHY,
    STATE_UNKNOWN,
    STATUS_FAIL,
    STATUS_OK,
    STATUS_UNKNOWN,
    STATUS_WARN,
    WINDOWS,
    BucketCounts,
    HealthError,
    LatestVerdict,
    PactPairHealth,
    PairSignals,
    StalenessFact,
    WebhookFact,
    fuse,
    metrics_from,
    parse_state,
    resolve_window,
    sort_key,
    total,
    trend_from,
)

SHA = "a" * 64
NOW = datetime(2026, 11, 26, 15, 30, tzinfo=timezone.utc)
PASSED = LatestVerdict(success=True, created_at="2026-11-26T10:00:00+00:00", number=4)
FAILED = LatestVerdict(success=False, created_at="2026-11-26T10:00:00+00:00", number=4)
FRESH = StalenessFact(sha=SHA, stale=False, stale_since=None, checked_at="2026-11-26T12:00:00+00:00")


def _counts(runs: int, passed: int, flips: int = 0, timed: int = 0, total_ms: int = 0) -> BucketCounts:
    """Counts for ``runs`` consecutive results (``runs - 1`` transitions)."""
    return BucketCounts(
        runs=runs,
        passed=passed,
        transitions=max(0, runs - 1),
        flips=flips,
        timed_runs=timed,
        duration_total_ms=total_ms,
    )


def _component(signals: PairSignals, key: str):
    _, components, _ = fuse(signals)
    return next(component for component in components if component.key == key)


def _healthy(**changes) -> PairSignals:
    base = dict(
        pact_version_sha=SHA,
        latest=PASSED,
        counts=_counts(20, 20),
        staleness=FRESH,
        republish_request_id=None,
        webhooks=WebhookFact(webhooks=1, failing=0),
    )
    base.update(changes)
    return PairSignals(**base)


# ---------------------------------------------------------------------------
# Windows and filters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, days, buckets, since",
    [
        ("7d", 1, 7, "2026-11-20T00:00:00+00:00"),
        ("30d", 1, 30, "2026-10-28T00:00:00+00:00"),
        ("90d", 7, 13, "2026-08-28T00:00:00+00:00"),
    ],
)
def test_each_window_is_whole_buckets_ending_with_today(key: str, days: int, buckets: int, since: str) -> None:
    spec, start, until = resolve_window(key, NOW)
    assert (spec.bucket_days, spec.bucket_count) == (days, buckets)
    assert until.isoformat() == "2026-11-27T00:00:00+00:00"
    assert start.isoformat() == since


def test_no_window_is_thirty_days() -> None:
    assert resolve_window(None, NOW)[0].key == "30d"
    assert resolve_window("", NOW)[0].key == "30d"


def test_a_window_in_another_zone_is_cut_on_the_utc_day() -> None:
    from datetime import timedelta

    late = datetime(2026, 11, 26, 23, 30, tzinfo=timezone(timedelta(hours=-5)))  # 04:30 UTC on the 27th
    assert resolve_window("7d", late)[2].isoformat() == "2026-11-28T00:00:00+00:00"


@pytest.mark.parametrize("key", ["1d", "30", "30D", "week"])
def test_an_unknown_window_is_refused_naming_the_choices(key: str) -> None:
    with pytest.raises(HealthError) as caught:
        resolve_window(key, NOW)
    assert caught.value.code == CODE_WINDOW_INVALID
    assert all(choice in str(caught.value) for choice in WINDOWS)


def test_the_state_filter_accepts_only_states() -> None:
    assert parse_state(None) is None and parse_state("") is None
    assert parse_state("failing") == "failing"
    with pytest.raises(HealthError) as caught:
        parse_state("red")
    assert caught.value.code == CODE_STATE_INVALID


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_divide_only_where_there_is_something_to_divide_by() -> None:
    empty = metrics_from(BucketCounts())
    assert empty.runs == 0 and empty.pass_rate is None and empty.flakiness is None and empty.mean_duration_ms is None
    one = metrics_from(_counts(1, 1))
    assert one.pass_rate == 1.0 and one.flakiness is None


def test_metrics_count_failures_flips_and_the_mean_of_timed_runs_only() -> None:
    metrics = metrics_from(_counts(10, 7, flips=3, timed=4, total_ms=2000))
    assert (metrics.failed, metrics.pass_rate) == (3, 0.7)
    assert metrics.flakiness == pytest.approx(3 / 9)
    assert (metrics.timed_runs, metrics.mean_duration_ms) == (4, 500.0)


def test_total_sums_every_field() -> None:
    summed = total([_counts(3, 2, flips=1, timed=1, total_ms=10), _counts(2, 2, timed=2, total_ms=30)])
    assert summed == BucketCounts(runs=5, passed=4, transitions=3, flips=1, timed_runs=3, duration_total_ms=40)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def test_every_component_is_listed_in_a_fixed_order() -> None:
    _, components, _ = fuse(_healthy())
    assert tuple(component.key for component in components) == COMPONENT_KEYS


@pytest.mark.parametrize(
    "latest, status, code",
    [
        (PASSED, STATUS_OK, CODE_LATEST_PASSED),
        (FAILED, STATUS_FAIL, CODE_LATEST_FAILED),
        (None, STATUS_WARN, CODE_UNVERIFIED),
    ],
)
def test_the_latest_verdict(latest, status: str, code: str) -> None:
    component = _component(_healthy(latest=latest), "latest-verdict")
    assert (component.status, component.code) == (status, code)


@pytest.mark.parametrize(
    "runs, passed, status, code",
    [
        (0, 0, STATUS_UNKNOWN, CODE_NO_RUNS),
        (20, 19, STATUS_OK, CODE_PASS_RATE_OK),  # exactly 95%
        (20, 18, STATUS_WARN, CODE_LOW_PASS_RATE),  # 90%
        (10, 8, STATUS_WARN, CODE_LOW_PASS_RATE),  # exactly 80%
        (10, 7, STATUS_FAIL, CODE_LOW_PASS_RATE),
    ],
)
def test_the_pass_rate_thresholds(runs: int, passed: int, status: str, code: str) -> None:
    component = _component(_healthy(counts=_counts(runs, passed)), "pass-rate")
    assert (component.status, component.code) == (status, code)


def test_the_pass_rate_sentence_says_how_many_passed() -> None:
    assert "90% of 20 results passed" in _component(_healthy(counts=_counts(20, 18)), "pass-rate").summary


@pytest.mark.parametrize(
    "runs, flips, status, code",
    [
        (1, 0, STATUS_UNKNOWN, CODE_TOO_FEW_RUNS),
        (2, 1, STATUS_UNKNOWN, CODE_TOO_FEW_RUNS),  # one transition is too few
        (11, 1, STATUS_OK, CODE_NOT_FLAKY),  # exactly 10%
        (11, 3, STATUS_WARN, CODE_SLIGHTLY_FLAKY),  # exactly 30%
        (11, 4, STATUS_FAIL, CODE_FLAKY),
    ],
)
def test_the_flakiness_thresholds(runs: int, flips: int, status: str, code: str) -> None:
    component = _component(_healthy(counts=_counts(runs, runs, flips=flips)), "flakiness")
    assert (component.status, component.code) == (status, code)


def test_overdue_reads_the_sweep_only_for_the_newest_pact() -> None:
    stale = StalenessFact(sha=SHA, stale=True, stale_since="2026-11-20T00:00:00+00:00", checked_at=None)
    overdue = _component(_healthy(staleness=stale), "overdue")
    assert (overdue.status, overdue.code) == (STATUS_WARN, CODE_OVERDUE)
    assert "2026-11-20" in overdue.summary
    assert _component(_healthy(), "overdue").code == CODE_UP_TO_DATE
    older = StalenessFact(sha="b" * 64, stale=True, stale_since=None, checked_at=None)
    for staleness in (None, older):
        component = _component(_healthy(staleness=staleness), "overdue")
        assert (component.status, component.code) == (STATUS_UNKNOWN, CODE_NOT_SWEPT)


def test_an_open_republish_request_warns() -> None:
    assert _component(_healthy(republish_request_id="r-1"), "republish-request").code == CODE_REPUBLISH_OPEN
    assert _component(_healthy(), "republish-request").code == CODE_REPUBLISH_NONE


@pytest.mark.parametrize(
    "fact, status, code",
    [
        (WebhookFact(), STATUS_UNKNOWN, CODE_NO_WEBHOOK_FIRINGS),
        (WebhookFact(webhooks=3), STATUS_OK, CODE_WEBHOOKS_OK),
        (WebhookFact(webhooks=3, failing=1), STATUS_WARN, CODE_WEBHOOKS_FAILING),
    ],
)
def test_webhook_deliveries(fact: WebhookFact, status: str, code: str) -> None:
    component = _component(_healthy(webhooks=fact), "webhooks")
    assert (component.status, component.code) == (status, code)


# ---------------------------------------------------------------------------
# The fused state
# ---------------------------------------------------------------------------


def test_a_pair_with_every_signal_ok_is_healthy() -> None:
    assert fuse(_healthy())[0] == STATE_HEALTHY


def test_unknown_signals_never_make_a_pair_worse() -> None:
    signals = _healthy(staleness=None, webhooks=WebhookFact(), counts=_counts(1, 1))
    assert fuse(signals)[0] == STATE_HEALTHY


def test_a_warning_degrades_and_a_failure_fails() -> None:
    assert fuse(_healthy(republish_request_id="r-1"))[0] == STATE_DEGRADED
    assert fuse(_healthy(latest=FAILED, republish_request_id="r-1"))[0] == STATE_FAILING


def test_a_pair_never_verified_in_or_out_of_the_window_is_degraded_not_unknown() -> None:
    # Never verified is a warning in itself; the republish component is always known.
    signals = PairSignals(pact_version_sha=SHA, latest=None)
    state, components, _ = fuse(signals)
    assert state == STATE_DEGRADED
    assert [c.status for c in components].count(STATUS_UNKNOWN) == 4


def test_the_overview_sorts_worst_first_then_by_handles() -> None:
    def pair(state: str, provider: str, consumer: str) -> PactPairHealth:
        _, components, metrics = fuse(_healthy())
        return PactPairHealth(
            provider=provider,
            provider_name=provider,
            consumer=consumer,
            consumer_name=consumer,
            pact_version_sha=SHA,
            consumer_version="1",
            state=state,
            components=components,
            metrics=metrics,
        )

    pairs = [
        pair(STATE_HEALTHY, "a", "a"),
        pair(STATE_UNKNOWN, "a", "a"),
        pair(STATE_DEGRADED, "b", "a"),
        pair(STATE_DEGRADED, "a", "z"),
        pair(STATE_FAILING, "z", "z"),
    ]
    ordered = sorted(pairs, key=sort_key)
    assert [(p.state, p.provider, p.consumer) for p in ordered] == [
        (STATE_FAILING, "z", "z"),
        (STATE_DEGRADED, "a", "z"),
        (STATE_DEGRADED, "b", "a"),
        (STATE_UNKNOWN, "a", "a"),
        (STATE_HEALTHY, "a", "a"),
    ]


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------


def test_the_trend_has_every_bucket_oldest_first_with_empty_ones() -> None:
    spec, since, until = resolve_window("7d", NOW)
    trend = trend_from(spec, since, {0: _counts(2, 1, flips=1), 6: _counts(1, 1), 7: _counts(5, 5), -1: _counts(5, 0)})
    assert len(trend) == 7
    assert trend[0].start == since.isoformat() and trend[-1].end == until.isoformat()
    assert trend[0].metrics.runs == 2 and trend[0].metrics.pass_rate == 0.5
    assert all(bucket.metrics.runs == 0 and bucket.metrics.pass_rate is None for bucket in trend[1:6])
    assert trend[6].metrics.runs == 1  # index 7 and -1 are outside the window and ignored


def test_the_ninety_day_trend_is_weekly() -> None:
    spec, since, _ = resolve_window("90d", NOW)
    trend = trend_from(spec, since, {})
    assert len(trend) == 13
    first_start = datetime.fromisoformat(trend[0].start)
    first_end = datetime.fromisoformat(trend[0].end)
    assert (first_end - first_start).days == 7
