"""
Pure aggregation over MCP catalog telemetry for the insight endpoints (V2-MCP-28.2).

The insight aggregation REST endpoints (:mod:`app.mcp_catalog_routes`) turn an endpoint's
raw discovery/invocation history into pre-aggregated, cache-friendly series so the browser
never runs N queries per panel nor holds raw rows. The *fetching* of those rows is tenant-scoped
SQL in :class:`app.database.Database`; the *math* that rolls them up lives here, as a pure,
deterministic layer with no database or network access.

Keeping the roll-up pure (rather than only in SQL) mirrors the design of the sibling
:mod:`app.mcp_surface_metrics` (V2-MCP-28.1) and buys two things the ticket's acceptance criteria
need: the percentile computation is unit-testable against a hand-computed fixture without a live
Postgres, and there is a single source of truth for the numbers the route and its tests both read.

The module provides:

* :func:`percentile_cont` — a faithful Python port of PostgreSQL's continuous ``percentile_cont``
  aggregate (linear interpolation between the two surrounding sorted samples), so latency
  percentiles match what an equivalent SQL query would produce.
* :func:`compute_latency_stats` — count / avg / min / max / p50 / p95 / p99 over a latency sample.
* :func:`compute_discovery_reliability` — discovery-job success rate and run-latency stats from
  ``mcp_discovery_jobs`` rows.
* :func:`compute_invocation_reliability` — test-invocation error rate and latency stats from
  ``mcp_test_invocations`` rows.

Every function is total: an empty sample yields zero counts and ``None`` statistics rather than
raising or dividing by zero, so an endpoint with no history produces an empty (not a 500) series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- Percentile / latency primitives --------------------------------------------------------

#: The three latency percentiles every reliability panel renders, as continuous fractions.
_PERCENTILE_FRACTIONS = (("p50_ms", 0.5), ("p95_ms", 0.95), ("p99_ms", 0.99))


def percentile_cont(values: Sequence[float], fraction: float) -> Optional[float]:
    """Continuous percentile of ``values`` at ``fraction``, matching SQL ``percentile_cont``.

    Replicates PostgreSQL's ``percentile_cont(fraction) WITHIN GROUP (ORDER BY value)``: the
    values are sorted, a continuous rank ``fraction * (n - 1)`` is taken, and the result is the
    linear interpolation between the samples immediately below and above that rank. For a fraction
    that lands exactly on a sample (including ``0.0`` → min and ``1.0`` → max) the sample itself is
    returned; a single-element sample always returns that element.

    Args:
        values: The numeric sample (need not be pre-sorted; may be empty).
        fraction: The percentile as a fraction in ``[0.0, 1.0]``.

    Returns:
        The interpolated percentile as a float, or ``None`` when ``values`` is empty.

    Raises:
        ValueError: When ``fraction`` is outside ``[0.0, 1.0]``.
    """
    if not 0.0 <= fraction <= 1.0:
        raise ValueError(f"fraction must be in [0.0, 1.0], got {fraction!r}")
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    rank = fraction * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


@dataclass(frozen=True)
class LatencyStats:
    """Summary latency statistics over a sample of millisecond durations.

    All statistics are ``None`` for an empty sample (there is nothing to average or rank), and
    are rounded to two decimals so identical samples produce byte-identical output. ``count`` is
    the number of non-null values the statistics were computed from.
    """

    count: int
    avg_ms: Optional[float]
    min_ms: Optional[float]
    max_ms: Optional[float]
    p50_ms: Optional[float]
    p95_ms: Optional[float]
    p99_ms: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "avg_ms": self.avg_ms,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
        }


def _round(value: Optional[float]) -> Optional[float]:
    """Round a nullable statistic to two decimals (``None`` passes through)."""
    return None if value is None else round(value, 2)


def compute_latency_stats(values: Iterable[Optional[float]]) -> LatencyStats:
    """Compute count / avg / min / max / p50 / p95 / p99 over a latency sample.

    ``None`` values (e.g. a call that never completed, so it recorded no latency) are dropped
    before any statistic is computed. An empty sample — or one that is all ``None`` — yields
    ``count=0`` and all-``None`` statistics rather than raising.

    Args:
        values: The per-call/per-run latencies in milliseconds; ``None`` entries are ignored.

    Returns:
        The rolled-up :class:`LatencyStats`.
    """
    sample = [float(v) for v in values if v is not None]
    if not sample:
        return LatencyStats(
            count=0,
            avg_ms=None,
            min_ms=None,
            max_ms=None,
            p50_ms=None,
            p95_ms=None,
            p99_ms=None,
        )
    percentiles = {name: _round(percentile_cont(sample, frac)) for name, frac in _PERCENTILE_FRACTIONS}
    return LatencyStats(
        count=len(sample),
        avg_ms=_round(sum(sample) / len(sample)),
        min_ms=_round(min(sample)),
        max_ms=_round(max(sample)),
        p50_ms=percentiles["p50_ms"],
        p95_ms=percentiles["p95_ms"],
        p99_ms=percentiles["p99_ms"],
    )


# --- Discovery-job reliability --------------------------------------------------------------

#: The four ``mcp_discovery_jobs.state`` values; the two terminal states are the success-rate base.
_DISCOVERY_TERMINAL_STATES = ("completed", "failed")


@dataclass(frozen=True)
class DiscoveryReliability:
    """Discovery-job reliability for one endpoint: state tallies, success rate, run latency.

    ``success_rate`` is ``completed / (completed + failed)`` over *terminal* jobs only (a job still
    queued or running has not yet succeeded or failed), and is ``0.0`` when no job has reached a
    terminal state. ``latency`` covers the wall-clock run duration of every job that recorded both a
    start and a finish.
    """

    job_count: int
    completed_count: int
    failed_count: int
    running_count: int
    queued_count: int
    success_rate: float
    latency: LatencyStats

    def as_dict(self) -> Dict[str, Any]:
        return {
            "job_count": self.job_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "running_count": self.running_count,
            "queued_count": self.queued_count,
            "success_rate": self.success_rate,
            "latency": self.latency.as_dict(),
        }


def compute_discovery_reliability(rows: Iterable[Dict[str, Any]]) -> DiscoveryReliability:
    """Aggregate ``mcp_discovery_jobs`` rows into a :class:`DiscoveryReliability`.

    Each row is expected to carry a ``state`` (one of queued/running/completed/failed) and a
    ``duration_ms`` (the run's wall-clock duration in milliseconds, or ``None`` when the job never
    both started and finished). Unknown states are counted toward ``job_count`` but not toward any
    per-state tally, so a future state can never be silently miscategorised.

    Args:
        rows: The endpoint's discovery-job rows (any iterable; may be empty).

    Returns:
        The rolled-up :class:`DiscoveryReliability` (all zeros / empty latency for no jobs).
    """
    per_state = {state: 0 for state in ("queued", "running", "completed", "failed")}
    job_count = 0
    durations: List[Optional[float]] = []
    for row in rows:
        job_count += 1
        state = str(row.get("state"))
        if state in per_state:
            per_state[state] += 1
        durations.append(row.get("duration_ms"))

    terminal = per_state["completed"] + per_state["failed"]
    success_rate = round(per_state["completed"] / terminal, 4) if terminal else 0.0
    return DiscoveryReliability(
        job_count=job_count,
        completed_count=per_state["completed"],
        failed_count=per_state["failed"],
        running_count=per_state["running"],
        queued_count=per_state["queued"],
        success_rate=success_rate,
        latency=compute_latency_stats(durations),
    )


# --- Test-invocation reliability ------------------------------------------------------------


@dataclass(frozen=True)
class InvocationReliability:
    """Test-console invocation reliability for one endpoint: call/error tallies and latency.

    ``error_rate`` is ``error_count / call_count`` over every recorded call (an errored call is one
    whose ``mcp_test_invocations.is_error`` was set — either a tool-level error or a transport
    failure), and is ``0.0`` when there were no calls. ``latency`` covers every call that recorded a
    round-trip latency.
    """

    call_count: int
    error_count: int
    success_count: int
    error_rate: float
    latency: LatencyStats

    def as_dict(self) -> Dict[str, Any]:
        return {
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "error_rate": self.error_rate,
            "latency": self.latency.as_dict(),
        }


def compute_invocation_reliability(rows: Iterable[Dict[str, Any]]) -> InvocationReliability:
    """Aggregate ``mcp_test_invocations`` rows into an :class:`InvocationReliability`.

    Each row is expected to carry an ``is_error`` flag and a ``latency_ms`` (or ``None`` when the
    call never completed). The latency sample spans every call that recorded a latency, regardless
    of whether it errored, so "how slow is this endpoint" is not skewed by dropping error timings.

    Args:
        rows: The endpoint's test-invocation rows (any iterable; may be empty).

    Returns:
        The rolled-up :class:`InvocationReliability` (all zeros / empty latency for no calls).
    """
    call_count = 0
    error_count = 0
    latencies: List[Optional[float]] = []
    for row in rows:
        call_count += 1
        if bool(row.get("is_error")):
            error_count += 1
        latencies.append(row.get("latency_ms"))

    error_rate = round(error_count / call_count, 4) if call_count else 0.0
    return InvocationReliability(
        call_count=call_count,
        error_count=error_count,
        success_count=call_count - error_count,
        error_rate=error_rate,
        latency=compute_latency_stats(latencies),
    )
