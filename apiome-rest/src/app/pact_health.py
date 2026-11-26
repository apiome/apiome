"""Contract health rollup and verification analytics — PFX-6.3 (#6955): the pure half.

Every consumer ↔ provider pair with a pact gets one **health state**, fused from the signals the
broker already records about it:

* **Latest verdict** — the newest result of the pair's newest pact: passed, failed, or none yet.
* **Pass rate** — the share of the pair's verification results in the window that passed.
* **Flakiness** — how often the verdict *flips* (passed → failed or failed → passed) between one
  result and the next, as a share of the window's consecutive result pairs.
* **Overdue** — whether the stale-pact sweep (PFX-6.2) marked the newest pact as not verified within
  its stale threshold.
* **Re-publish request** — whether a request to the consumer to re-publish the pact is open.
* **Webhooks** — whether the newest firing of a contract webhook for the pair failed for good.

Each signal is a :class:`PactHealthComponent` with a status — ``ok``, ``warn``, ``fail`` or ``unknown``
(no evidence either way) — a stable reason code and a sentence. The pair's state is the worst of
them: ``failing`` (any ``fail``), ``degraded`` (any ``warn``), ``healthy`` (at least one ``ok``) or
``unknown`` (no evidence at all). An ``unknown`` component never makes a pair worse; it is shown so
nothing is silently left out.

**Analytics.** A window — ``7d``, ``30d`` (the default) or ``90d`` — is cut into buckets (one day for
7 and 30 days, one week for 90 days) ending with today (UTC); each bucket carries its runs, pass
rate, flips, flakiness and mean duration, so the trend of each can be drawn.

Only Pact signals are fused here. SLA breaches, consent and disputes belong to CAG-10.4 (#7025),
which consumes this rollup.

This module decides; it reads no database (:mod:`app.pact_health_store`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BucketCounts",
    "CODE_FLAKY",
    "CODE_LATEST_FAILED",
    "CODE_LATEST_PASSED",
    "CODE_LOW_PASS_RATE",
    "CODE_NO_RUNS",
    "CODE_NOT_FLAKY",
    "CODE_NOT_SWEPT",
    "CODE_NO_WEBHOOK_FIRINGS",
    "CODE_OVERDUE",
    "CODE_PAIR_NOT_FOUND",
    "CODE_PASS_RATE_OK",
    "CODE_REPUBLISH_NONE",
    "CODE_REPUBLISH_OPEN",
    "CODE_SLIGHTLY_FLAKY",
    "CODE_STATE_INVALID",
    "CODE_TOO_FEW_RUNS",
    "CODE_UNVERIFIED",
    "CODE_UP_TO_DATE",
    "CODE_WEBHOOKS_FAILING",
    "CODE_WEBHOOKS_OK",
    "CODE_WINDOW_INVALID",
    "COMPONENT_FLAKINESS",
    "COMPONENT_KEYS",
    "COMPONENT_LATEST",
    "COMPONENT_OVERDUE",
    "COMPONENT_PASS_RATE",
    "COMPONENT_REPUBLISH",
    "COMPONENT_WEBHOOKS",
    "DEFAULT_WINDOW",
    "FLAKINESS_OK",
    "FLAKINESS_WARN",
    "PactHealthComponent",
    "PactHealthCounts",
    "HealthError",
    "PactHealthOverview",
    "LatestVerdict",
    "MAX_HEALTH_PAIRS",
    "MIN_TRANSITIONS_FOR_FLAKINESS",
    "PASS_RATE_OK",
    "PASS_RATE_WARN",
    "PactPairHealth",
    "PactPairHealthDetail",
    "PactPairMetrics",
    "PairSignals",
    "STATES",
    "STATE_DEGRADED",
    "STATE_FAILING",
    "STATE_HEALTHY",
    "STATE_UNKNOWN",
    "STATUS_FAIL",
    "STATUS_OK",
    "STATUS_UNKNOWN",
    "STATUS_WARN",
    "StalenessFact",
    "PactTrendBucket",
    "WINDOWS",
    "WebhookFact",
    "WindowSpec",
    "fuse",
    "metrics_from",
    "parse_state",
    "resolve_window",
    "sort_key",
    "total",
    "trend_from",
]

# ---------------------------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------------------------

#: The window is not one of :data:`WINDOWS` (HTTP 400).
CODE_WINDOW_INVALID = "pact-health-window-invalid"
#: The ``state`` filter is not one of :data:`STATES` (HTTP 400).
CODE_STATE_INVALID = "pact-health-state-invalid"
#: The consumer has published no pact for the provider (HTTP 404).
CODE_PAIR_NOT_FOUND = "pact-health-pair-not-found"

STATE_HEALTHY = "healthy"
STATE_DEGRADED = "degraded"
STATE_FAILING = "failing"
STATE_UNKNOWN = "unknown"
#: Every pair state, worst first (the order the overview sorts by).
STATES = (STATE_FAILING, STATE_DEGRADED, STATE_UNKNOWN, STATE_HEALTHY)

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_UNKNOWN = "unknown"

COMPONENT_LATEST = "latest-verdict"
COMPONENT_PASS_RATE = "pass-rate"
COMPONENT_FLAKINESS = "flakiness"
COMPONENT_OVERDUE = "overdue"
COMPONENT_REPUBLISH = "republish-request"
COMPONENT_WEBHOOKS = "webhooks"
#: Every component, in the order a pair lists them.
COMPONENT_KEYS = (
    COMPONENT_LATEST,
    COMPONENT_PASS_RATE,
    COMPONENT_FLAKINESS,
    COMPONENT_OVERDUE,
    COMPONENT_REPUBLISH,
    COMPONENT_WEBHOOKS,
)

# Reason codes, one per outcome of each component.
CODE_LATEST_PASSED = "pact-health-latest-passed"
CODE_LATEST_FAILED = "pact-health-latest-failed"
CODE_UNVERIFIED = "pact-health-unverified"
CODE_PASS_RATE_OK = "pact-health-pass-rate-ok"
CODE_LOW_PASS_RATE = "pact-health-pass-rate-low"
CODE_NO_RUNS = "pact-health-no-runs"
CODE_NOT_FLAKY = "pact-health-not-flaky"
CODE_SLIGHTLY_FLAKY = "pact-health-slightly-flaky"
CODE_FLAKY = "pact-health-flaky"
CODE_TOO_FEW_RUNS = "pact-health-too-few-runs"
CODE_UP_TO_DATE = "pact-health-up-to-date"
CODE_OVERDUE = "pact-health-overdue"
CODE_NOT_SWEPT = "pact-health-not-swept"
CODE_REPUBLISH_NONE = "pact-health-no-republish-request"
CODE_REPUBLISH_OPEN = "pact-health-republish-request-open"
CODE_WEBHOOKS_OK = "pact-health-webhooks-delivered"
CODE_WEBHOOKS_FAILING = "pact-health-webhooks-failing"
CODE_NO_WEBHOOK_FIRINGS = "pact-health-no-webhook-firings"

#: A pass rate at or above this is ``ok``.
PASS_RATE_OK = 0.95
#: A pass rate at or above this (and below :data:`PASS_RATE_OK`) is ``warn``; below it, ``fail``.
PASS_RATE_WARN = 0.80
#: A flakiness at or below this is ``ok``.
FLAKINESS_OK = 0.10
#: A flakiness at or below this (and above :data:`FLAKINESS_OK`) is ``warn``; above it, ``fail``.
FLAKINESS_WARN = 0.30
#: Flakiness is only judged with at least this many consecutive result pairs (three results).
MIN_TRANSITIONS_FOR_FLAKINESS = 2

#: The most pairs the overview lists (the rest are counted in ``truncated``).
MAX_HEALTH_PAIRS = 500


@dataclass(frozen=True)
class WindowSpec:
    """One selectable window.

    Attributes:
        key: The value of the ``window`` parameter (``7d``, ``30d``, ``90d``).
        days: The window's nominal length in days.
        bucket_days: The length of one trend bucket in days.
    """

    key: str
    days: int
    bucket_days: int

    @property
    def bucket_count(self) -> int:
        """How many buckets the window is cut into (the last one ends with today)."""
        return -(-self.days // self.bucket_days)


#: The windows the ``window`` parameter accepts.
WINDOWS: Dict[str, WindowSpec] = {
    "7d": WindowSpec("7d", 7, 1),
    "30d": WindowSpec("30d", 30, 1),
    "90d": WindowSpec("90d", 90, 7),
}
#: The window used when none is asked for.
DEFAULT_WINDOW = "30d"


class HealthError(ValueError):
    """A health read was refused, with a stable code.

    Attributes:
        code: One of :data:`CODE_WINDOW_INVALID`, :data:`CODE_STATE_INVALID`, :data:`CODE_PAIR_NOT_FOUND`.
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code.
            message: What was wrong, and what to do.
        """
        super().__init__(message)
        self.code = code


def resolve_window(key: Optional[str], now: datetime) -> Tuple[WindowSpec, datetime, datetime]:
    """The window a ``window`` parameter names, and the instants it spans.

    The window ends at the end of today (UTC) and starts ``bucket_count × bucket_days`` days earlier,
    so every bucket is whole: 7 days, 30 days, or 13 weeks (91 days) for ``90d``.

    Args:
        key: The parameter (``None`` or empty for :data:`DEFAULT_WINDOW`).
        now: The current time (timezone-aware).

    Returns:
        The window, its first instant (inclusive) and its end (exclusive).

    Raises:
        HealthError: :data:`CODE_WINDOW_INVALID` for a key that is not in :data:`WINDOWS`.
    """
    spec = WINDOWS.get(key or DEFAULT_WINDOW)
    if spec is None:
        raise HealthError(CODE_WINDOW_INVALID, f"window '{key}' is not one of {', '.join(WINDOWS)}")
    day = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    until = day + timedelta(days=1)
    since = until - timedelta(days=spec.bucket_count * spec.bucket_days)
    return spec, since, until


def parse_state(value: Optional[str]) -> Optional[str]:
    """Check a ``state`` filter.

    Args:
        value: The parameter, or ``None``.

    Returns:
        The state, or ``None`` when no filter was asked for.

    Raises:
        HealthError: :data:`CODE_STATE_INVALID` for a value not in :data:`STATES`.
    """
    if value is None or value == "":
        return None
    if value not in STATES:
        raise HealthError(CODE_STATE_INVALID, f"state '{value}' is not one of {', '.join(STATES)}")
    return value


# ---------------------------------------------------------------------------------------------
# Inputs (what the store reads)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BucketCounts:
    """What the window (or one bucket of it) recorded for a pair.

    Attributes:
        runs: Verification results.
        passed: Of those, the ones that passed.
        transitions: Results that have an earlier result of the same pair in the window.
        flips: Of those, the ones whose verdict differs from the result before.
        timed_runs: Results that carry a duration (published results from other verifiers may not).
        duration_total_ms: The sum of those durations.
    """

    runs: int = 0
    passed: int = 0
    transitions: int = 0
    flips: int = 0
    timed_runs: int = 0
    duration_total_ms: int = 0

    def __add__(self, other: "BucketCounts") -> "BucketCounts":
        """The counts of both, summed field by field."""
        return BucketCounts(
            runs=self.runs + other.runs,
            passed=self.passed + other.passed,
            transitions=self.transitions + other.transitions,
            flips=self.flips + other.flips,
            timed_runs=self.timed_runs + other.timed_runs,
            duration_total_ms=self.duration_total_ms + other.duration_total_ms,
        )


@dataclass(frozen=True)
class LatestVerdict:
    """The newest result of a pair's newest pact.

    Attributes:
        success: Whether it passed.
        created_at: When it was published (ISO 8601).
        number: Its number for the pact version.
    """

    success: bool
    created_at: Optional[str]
    number: int


@dataclass(frozen=True)
class StalenessFact:
    """What the stale-pact sweep last recorded for a pair.

    Attributes:
        sha: The pact version it looked at.
        stale: Whether it was overdue.
        stale_since: When it crossed the threshold, when ``stale`` (ISO 8601).
        checked_at: When the sweep last looked (ISO 8601).
    """

    sha: str
    stale: bool
    stale_since: Optional[str]
    checked_at: Optional[str]


@dataclass(frozen=True)
class WebhookFact:
    """The newest firing in the window of each contract webhook for a pair.

    Attributes:
        webhooks: How many webhooks fired for the pair in the window.
        failing: Of those, how many whose newest firing failed for good (dead-lettered).
    """

    webhooks: int = 0
    failing: int = 0


@dataclass(frozen=True)
class PairSignals:
    """Everything the rollup fuses for one pair.

    Attributes:
        pact_version_sha: The pair's newest pact version.
        latest: Its newest result, or ``None`` when it has none.
        counts: The window's counts.
        staleness: The sweep's record, or ``None`` when the sweep never looked at the pair.
        republish_request_id: The open re-publish request, or ``None``.
        webhooks: The webhook firings.
    """

    pact_version_sha: str
    latest: Optional[LatestVerdict]
    counts: BucketCounts = field(default_factory=BucketCounts)
    staleness: Optional[StalenessFact] = None
    republish_request_id: Optional[str] = None
    webhooks: WebhookFact = field(default_factory=WebhookFact)


# ---------------------------------------------------------------------------------------------
# Models (what the API answers)
# ---------------------------------------------------------------------------------------------


class PactPairMetrics(BaseModel):
    """A pair's (or the workspace's, or one bucket's) verification analytics."""

    model_config = ConfigDict(extra="forbid")

    runs: int = Field(description="Verification results.")
    passed: int = Field(description="Of those, the ones that passed.")
    failed: int = Field(description="Of those, the ones that failed.")
    pass_rate: Optional[float] = Field(default=None, description="`passed / runs` (0 … 1), or null with no runs.")
    flips: int = Field(description="Results whose verdict differs from the result before them.")
    flakiness: Optional[float] = Field(
        default=None,
        description="`flips` as a share of consecutive result pairs (0 … 1), or null with fewer than two results.",
    )
    timed_runs: int = Field(description="Results that carry a duration (verifiers outside Apiome may send none).")
    mean_duration_ms: Optional[float] = Field(
        default=None, description="The mean duration of the timed results, or null when none is timed."
    )


class PactHealthComponent(BaseModel):
    """One signal fused into a pair's health."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        description=("`latest-verdict`, `pass-rate`, `flakiness`, `overdue`, `republish-request` or `webhooks`.")
    )
    status: str = Field(description="`ok`, `warn`, `fail` or `unknown` (no evidence either way).")
    code: str = Field(description="A stable reason code (`pact-health-…`).")
    summary: str = Field(description="One sentence saying why.")


class PactPairHealth(BaseModel):
    """One consumer ↔ provider pair's health."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="The provider's handle.")
    provider_name: str = Field(description="The provider's display name.")
    consumer: str = Field(description="The consumer's handle.")
    consumer_name: str = Field(description="The consumer's display name.")
    pact_version_sha: str = Field(description="The pair's newest pact version.")
    consumer_version: str = Field(description="The consumer version that published it last.")
    published_at: Optional[str] = Field(default=None, description="When that version published it.")
    state: str = Field(description="`healthy`, `degraded`, `failing` or `unknown`.")
    components: List[PactHealthComponent] = Field(description="Every fused signal, in a fixed order.")
    metrics: PactPairMetrics = Field(description="The window's analytics.")
    latest_success: Optional[bool] = Field(default=None, description="The newest pact's newest verdict, if any.")
    latest_verified_at: Optional[str] = Field(default=None, description="When that result was published.")
    republish_request_id: Optional[str] = Field(default=None, description="The open re-publish request, if any.")


class PactHealthCounts(BaseModel):
    """How many pairs are in each state."""

    model_config = ConfigDict(extra="forbid")

    pairs: int = Field(description="Pairs with a pact (before the `state` filter).")
    healthy: int = Field(description="Pairs whose signals are all ok (or unknown).")
    degraded: int = Field(description="Pairs with a warning and no failure.")
    failing: int = Field(description="Pairs with a failing signal.")
    unknown: int = Field(description="Pairs with no evidence either way.")


class PactHealthOverview(BaseModel):
    """The workspace's contract health over a window."""

    model_config = ConfigDict(extra="forbid")

    window: str = Field(description="`7d`, `30d` or `90d`.")
    since: str = Field(description="The window's first instant (inclusive).")
    until: str = Field(description="The window's end (exclusive): the end of today, UTC.")
    bucket_days: int = Field(description="The length of one trend bucket, in days.")
    generated_at: str = Field(description="When this rollup was computed (it is computed on every read).")
    counts: PactHealthCounts = Field(description="Pairs per state.")
    totals: PactPairMetrics = Field(description="The analytics of every listed pair together.")
    pairs: List[PactPairHealth] = Field(
        default_factory=list, description="Worst first, then by provider and consumer handle."
    )
    truncated: bool = Field(
        default=False,
        description=f"True when more than {MAX_HEALTH_PAIRS} pairs match (the rest are left out and counted).",
    )
    omitted_pairs: int = Field(default=0, description="How many matching pairs were left out by the cap.")


class PactTrendBucket(BaseModel):
    """One bucket of a pair's trend."""

    model_config = ConfigDict(extra="forbid")

    start: str = Field(description="The bucket's first instant (inclusive).")
    end: str = Field(description="The bucket's end (exclusive).")
    metrics: PactPairMetrics = Field(description="What the bucket recorded.")


class PactPairHealthDetail(BaseModel):
    """One pair's health with its trend."""

    model_config = ConfigDict(extra="forbid")

    window: str = Field(description="`7d`, `30d` or `90d`.")
    since: str = Field(description="The window's first instant (inclusive).")
    until: str = Field(description="The window's end (exclusive).")
    bucket_days: int = Field(description="The length of one trend bucket, in days.")
    generated_at: str = Field(description="When this was computed.")
    pair: PactPairHealth = Field(description="The pair's health over the whole window.")
    trend: List[PactTrendBucket] = Field(description="Every bucket of the window, oldest first (empty ones included).")


# ---------------------------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------------------------


def _percent(value: float) -> str:
    """A share as a whole percentage, e.g. ``0.956`` → ``96%``."""
    return f"{round(value * 100)}%"


def metrics_from(counts: BucketCounts) -> PactPairMetrics:
    """The analytics of some counts.

    Args:
        counts: A window's, a bucket's or a sum of pairs' counts.

    Returns:
        The metrics; the rates are ``None`` where there is nothing to divide by.
    """
    return PactPairMetrics(
        runs=counts.runs,
        passed=counts.passed,
        failed=counts.runs - counts.passed,
        pass_rate=(counts.passed / counts.runs) if counts.runs else None,
        flips=counts.flips,
        flakiness=(counts.flips / counts.transitions) if counts.transitions else None,
        timed_runs=counts.timed_runs,
        mean_duration_ms=(counts.duration_total_ms / counts.timed_runs) if counts.timed_runs else None,
    )


def _latest_component(latest: Optional[LatestVerdict]) -> PactHealthComponent:
    """The newest pact's newest verdict."""
    if latest is None:
        return PactHealthComponent(
            key=COMPONENT_LATEST,
            status=STATUS_WARN,
            code=CODE_UNVERIFIED,
            summary="The newest pact has no verification result yet, so it cannot be deployed with confidence.",
        )
    if latest.success:
        return PactHealthComponent(
            key=COMPONENT_LATEST,
            status=STATUS_OK,
            code=CODE_LATEST_PASSED,
            summary="The newest pact passed verification.",
        )
    return PactHealthComponent(
        key=COMPONENT_LATEST,
        status=STATUS_FAIL,
        code=CODE_LATEST_FAILED,
        summary="The newest pact failed verification.",
    )


def _pass_rate_component(metrics: PactPairMetrics) -> PactHealthComponent:
    """The window's pass rate against :data:`PASS_RATE_OK` / :data:`PASS_RATE_WARN`."""
    if metrics.pass_rate is None:
        return PactHealthComponent(
            key=COMPONENT_PASS_RATE,
            status=STATUS_UNKNOWN,
            code=CODE_NO_RUNS,
            summary="No verification result was published in the window.",
        )
    detail = f"{_percent(metrics.pass_rate)} of {metrics.runs} results passed"
    if metrics.pass_rate >= PASS_RATE_OK:
        return PactHealthComponent(
            key=COMPONENT_PASS_RATE, status=STATUS_OK, code=CODE_PASS_RATE_OK, summary=f"{detail}."
        )
    status = STATUS_WARN if metrics.pass_rate >= PASS_RATE_WARN else STATUS_FAIL
    return PactHealthComponent(
        key=COMPONENT_PASS_RATE,
        status=status,
        code=CODE_LOW_PASS_RATE,
        summary=f"{detail}, below the {_percent(PASS_RATE_OK)} a healthy pair keeps.",
    )


def _flakiness_component(counts: BucketCounts, metrics: PactPairMetrics) -> PactHealthComponent:
    """The window's flakiness against :data:`FLAKINESS_OK` / :data:`FLAKINESS_WARN`."""
    if counts.transitions < MIN_TRANSITIONS_FOR_FLAKINESS or metrics.flakiness is None:
        return PactHealthComponent(
            key=COMPONENT_FLAKINESS,
            status=STATUS_UNKNOWN,
            code=CODE_TOO_FEW_RUNS,
            summary=(
                f"Fewer than {MIN_TRANSITIONS_FOR_FLAKINESS + 1} results in the window: too few to judge flakiness."
            ),
        )
    detail = f"The verdict changed {counts.flips} of {counts.transitions} times from one result to the next"
    if metrics.flakiness <= FLAKINESS_OK:
        return PactHealthComponent(
            key=COMPONENT_FLAKINESS,
            status=STATUS_OK,
            code=CODE_NOT_FLAKY,
            summary=f"{detail} ({_percent(metrics.flakiness)}).",
        )
    if metrics.flakiness <= FLAKINESS_WARN:
        return PactHealthComponent(
            key=COMPONENT_FLAKINESS,
            status=STATUS_WARN,
            code=CODE_SLIGHTLY_FLAKY,
            summary=f"{detail} ({_percent(metrics.flakiness)}): the verification is somewhat flaky.",
        )
    return PactHealthComponent(
        key=COMPONENT_FLAKINESS,
        status=STATUS_FAIL,
        code=CODE_FLAKY,
        summary=f"{detail} ({_percent(metrics.flakiness)}): the verification is flaky.",
    )


def _overdue_component(sha: str, staleness: Optional[StalenessFact]) -> PactHealthComponent:
    """Whether the stale-pact sweep found the newest pact overdue."""
    if staleness is None or staleness.sha != sha:
        return PactHealthComponent(
            key=COMPONENT_OVERDUE,
            status=STATUS_UNKNOWN,
            code=CODE_NOT_SWEPT,
            summary="The stale-pact sweep has not checked the newest pact yet.",
        )
    if staleness.stale:
        since = f" since {staleness.stale_since}" if staleness.stale_since else ""
        return PactHealthComponent(
            key=COMPONENT_OVERDUE,
            status=STATUS_WARN,
            code=CODE_OVERDUE,
            summary=f"The newest pact has not been verified within its stale threshold{since}.",
        )
    return PactHealthComponent(
        key=COMPONENT_OVERDUE,
        status=STATUS_OK,
        code=CODE_UP_TO_DATE,
        summary="The newest pact was verified within its stale threshold.",
    )


def _republish_component(request_id: Optional[str]) -> PactHealthComponent:
    """Whether a re-publish request is open."""
    if request_id:
        return PactHealthComponent(
            key=COMPONENT_REPUBLISH,
            status=STATUS_WARN,
            code=CODE_REPUBLISH_OPEN,
            summary="A re-publish request to the consumer is open.",
        )
    return PactHealthComponent(
        key=COMPONENT_REPUBLISH, status=STATUS_OK, code=CODE_REPUBLISH_NONE, summary="No re-publish request is open."
    )


def _webhooks_component(webhooks: WebhookFact) -> PactHealthComponent:
    """Whether the newest firing of a contract webhook for the pair failed for good."""
    if webhooks.webhooks == 0:
        return PactHealthComponent(
            key=COMPONENT_WEBHOOKS,
            status=STATUS_UNKNOWN,
            code=CODE_NO_WEBHOOK_FIRINGS,
            summary="No contract webhook fired for this pair in the window.",
        )
    if webhooks.failing:
        return PactHealthComponent(
            key=COMPONENT_WEBHOOKS,
            status=STATUS_WARN,
            code=CODE_WEBHOOKS_FAILING,
            summary=f"The newest delivery of {webhooks.failing} of {webhooks.webhooks} webhooks failed.",
        )
    return PactHealthComponent(
        key=COMPONENT_WEBHOOKS,
        status=STATUS_OK,
        code=CODE_WEBHOOKS_OK,
        summary=f"The newest delivery of each of {webhooks.webhooks} webhooks did not fail.",
    )


def _state(components: Iterable[PactHealthComponent]) -> str:
    """The worst of the components' statuses, as a pair state."""
    statuses = {component.status for component in components}
    if STATUS_FAIL in statuses:
        return STATE_FAILING
    if STATUS_WARN in statuses:
        return STATE_DEGRADED
    if STATUS_OK in statuses:
        return STATE_HEALTHY
    return STATE_UNKNOWN


def fuse(signals: PairSignals) -> Tuple[str, List[PactHealthComponent], PactPairMetrics]:
    """Fuse one pair's signals into its state.

    Args:
        signals: What the store read for the pair.

    Returns:
        The state, every component (in :data:`COMPONENT_KEYS` order) and the window's metrics.
    """
    metrics = metrics_from(signals.counts)
    components = [
        _latest_component(signals.latest),
        _pass_rate_component(metrics),
        _flakiness_component(signals.counts, metrics),
        _overdue_component(signals.pact_version_sha, signals.staleness),
        _republish_component(signals.republish_request_id),
        _webhooks_component(signals.webhooks),
    ]
    return _state(components), components, metrics


def sort_key(pair: PactPairHealth) -> Tuple[int, str, str]:
    """Worst state first, then provider and consumer handle."""
    return (STATES.index(pair.state), pair.provider, pair.consumer)


def trend_from(spec: WindowSpec, since: datetime, buckets: Dict[int, BucketCounts]) -> List[PactTrendBucket]:
    """Every bucket of a window, oldest first, empty ones included.

    Args:
        spec: The window.
        since: Its first instant.
        buckets: Counts by bucket index (0 is the oldest); indexes outside the window are ignored.

    Returns:
        :attr:`WindowSpec.bucket_count` buckets.
    """
    step = timedelta(days=spec.bucket_days)
    trend: List[PactTrendBucket] = []
    for index in range(spec.bucket_count):
        start = since + step * index
        trend.append(
            PactTrendBucket(
                start=start.isoformat(),
                end=(start + step).isoformat(),
                metrics=metrics_from(buckets.get(index, BucketCounts())),
            )
        )
    return trend


def total(counts: Sequence[BucketCounts]) -> BucketCounts:
    """The sum of several pairs' counts.

    Args:
        counts: The counts.

    Returns:
        Their field-by-field sum.
    """
    result = BucketCounts()
    for item in counts:
        result = result + item
    return result
