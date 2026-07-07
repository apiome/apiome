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
* :func:`compute_discovery_timeline` — the recent per-job outcome timeline + a windowed
  availability percentage from ``mcp_discovery_jobs`` rows (V2-MCP-31.1 / MCAT-17.1).
* :func:`compute_invocation_reliability` — test-invocation error rate and latency stats from
  ``mcp_test_invocations`` rows.
* :func:`compute_tool_reliability` — per-tool p50/p95/p99 latency + error rate, a latency
  distribution, and the endpoint-wide totals from ``mcp_test_invocations`` tool rows over a
  recent window (V2-MCP-31.2 / MCAT-17.2).

Every function is total: an empty sample yields zero counts and ``None`` statistics rather than
raising or dividing by zero, so an endpoint with no history produces an empty (not a 500) series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


# --- Discovery health timeline (V2-MCP-31.1 / MCAT-17.1) ------------------------------------

#: The default number of most-recent discovery jobs the health timeline spans. The caller's SQL
#: limits to this same bound, so the availability percentage is computed over one coherent window.
DISCOVERY_TIMELINE_WINDOW = 50


def _iso(value: Any) -> Optional[str]:
    """Return an ISO-8601 string for a datetime-like value, or ``None`` for a null.

    Discovery-job timestamps arrive as ``datetime`` objects from asyncpg; the wire wants strings.
    Anything already stringlike is returned unchanged so the function is safe over pre-serialized
    fixtures too.
    """
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _event_outcome(state: str, error_code: Optional[str]) -> str:
    """Collapse a job's ``state`` + failure ``error_code`` into a single timeline outcome.

    ``completed`` → ``ok``; ``failed`` → its specific discovery error code (``connect_error`` /
    ``auth_required`` / …) or a bare ``failed`` when no code was recorded; anything still in flight
    (``queued`` / ``running``) or otherwise non-terminal → ``pending``.
    """
    if state == "completed":
        return "ok"
    if state == "failed":
        return error_code or "failed"
    return "pending"


@dataclass(frozen=True)
class DiscoveryEvent:
    """One discovery-job outcome on the health timeline.

    ``outcome`` is what the timeline colours by (see :func:`_event_outcome`): ``ok`` for a completed
    run, the specific discovery error code for a failed one, or ``pending`` while the job has not
    reached a terminal state. ``error_code`` is the raw failure classification (``None`` unless the
    job failed with a recorded code). Timestamps are ISO-8601 strings (or ``None``); ``duration_ms``
    is the run's wall-clock duration when the job both started and finished.
    """

    job_id: str
    state: str
    trigger: str
    outcome: str
    error_code: Optional[str]
    created_at: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    duration_ms: Optional[float]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "trigger": self.trigger,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class DiscoveryTimeline:
    """An endpoint's discovery health over a recent window: per-job events + an availability %.

    ``events`` are newest-first (as the caller's SQL returns them), capped at ``window`` jobs.
    ``availability_pct`` is ``ok / (ok + failed)`` over the *terminal* jobs in the window, as a
    ``0``–``100`` percentage rounded to one decimal, or ``None`` when the window holds no terminal
    job (there is nothing to be "available" or not yet). ``pending_count`` covers still-in-flight
    jobs, which are excluded from availability. ``truncated`` is true when the window filled, so
    older jobs may exist beyond it.
    """

    events: List[DiscoveryEvent]
    window: int
    event_count: int
    ok_count: int
    failed_count: int
    pending_count: int
    terminal_count: int
    availability_pct: Optional[float]
    truncated: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "events": [event.as_dict() for event in self.events],
            "window": self.window,
            "event_count": self.event_count,
            "ok_count": self.ok_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "terminal_count": self.terminal_count,
            "availability_pct": self.availability_pct,
            "truncated": self.truncated,
        }


def compute_discovery_timeline(
    rows: Iterable[Dict[str, Any]], *, window: int = DISCOVERY_TIMELINE_WINDOW
) -> DiscoveryTimeline:
    """Fold recent ``mcp_discovery_jobs`` rows into a :class:`DiscoveryTimeline`.

    Each row is expected to carry the job ``id``, ``state``, ``trigger``, the ``created_at`` /
    ``started_at`` / ``finished_at`` timestamps, a ``duration_ms`` (or ``None``), and an
    ``error_code`` (the discovery failure classification pulled from the job's stored error, or
    ``None`` for a non-failed job). Rows must arrive **newest-first**; the function keeps only the
    first ``window`` of them and computes availability over that same window so the percentage
    always matches the events shown.

    Args:
        rows: The endpoint's recent discovery-job rows, newest-first (any iterable; may be empty).
        window: The maximum number of jobs the timeline spans (defaults to
            :data:`DISCOVERY_TIMELINE_WINDOW`; clamped to at least 1).

    Returns:
        The rolled-up :class:`DiscoveryTimeline` (empty events / ``None`` availability for no jobs).
    """
    limit = max(1, int(window))
    events: List[DiscoveryEvent] = []
    ok_count = 0
    failed_count = 0
    pending_count = 0
    for row in rows:
        if len(events) >= limit:
            break
        state = str(row.get("state"))
        raw_code = row.get("error_code")
        error_code = str(raw_code) if raw_code else None
        outcome = _event_outcome(state, error_code)
        if outcome == "ok":
            ok_count += 1
        elif state == "failed":
            failed_count += 1
        else:
            pending_count += 1
        events.append(
            DiscoveryEvent(
                job_id=str(row.get("id") or row.get("job_id") or ""),
                state=state,
                trigger=str(row.get("trigger") or ""),
                outcome=outcome,
                error_code=error_code,
                created_at=_iso(row.get("created_at")),
                started_at=_iso(row.get("started_at")),
                finished_at=_iso(row.get("finished_at")),
                duration_ms=_round(row.get("duration_ms")),
            )
        )

    terminal = ok_count + failed_count
    availability = round(ok_count / terminal * 100, 1) if terminal else None
    return DiscoveryTimeline(
        events=events,
        window=limit,
        event_count=len(events),
        ok_count=ok_count,
        failed_count=failed_count,
        pending_count=pending_count,
        terminal_count=terminal,
        availability_pct=availability,
        truncated=len(events) >= limit,
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


# --- Per-tool invocation reliability (V2-MCP-31.2 / MCAT-17.2) -------------------------------

#: The default trailing window (in days) the tool latency/error-rate panel aggregates over.
TOOL_LATENCY_WINDOW_DAYS = 30

#: Latency-distribution buckets as ``(label, upper_ms)`` in ascending order; the final bucket is
#: open-ended (``upper_ms is None``). A latency ``v`` falls in the first bucket whose ``upper_ms`` it
#: is strictly below (``v < upper_ms``), so the boundaries never double-count.
_LATENCY_DISTRIBUTION_BUCKETS: Tuple[Tuple[str, Optional[float]], ...] = (
    ("0–50 ms", 50.0),
    ("50–100 ms", 100.0),
    ("100–250 ms", 250.0),
    ("250–500 ms", 500.0),
    ("500 ms–1 s", 1000.0),
    ("1–2.5 s", 2500.0),
    ("2.5 s+", None),
)


@dataclass(frozen=True)
class LatencyBucket:
    """One bar of the latency distribution: a labelled range and how many calls fell in it.

    ``upper_ms`` is the exclusive upper bound of the range in milliseconds, or ``None`` for the
    open-ended top bucket.
    """

    label: str
    upper_ms: Optional[float]
    count: int

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "upper_ms": self.upper_ms, "count": self.count}


@dataclass(frozen=True)
class ToolReliability:
    """One tool's reliability over the window: call/error tallies, error rate, and latency stats.

    ``error_rate`` is ``error_count / call_count`` over every recorded call for this tool (``0.0``
    when — impossibly here — there were no calls). ``latency`` spans every call that recorded a
    round-trip latency, so a single call yields percentiles equal to that one sample (never a
    divide-by-zero).
    """

    tool_name: str
    call_count: int
    error_count: int
    success_count: int
    error_rate: float
    latency: LatencyStats

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "error_rate": self.error_rate,
            "latency": self.latency.as_dict(),
        }


@dataclass(frozen=True)
class ToolInvocationReliability:
    """Per-tool reliability roll-up for one endpoint over a recent window (MCAT-17.2).

    ``tools`` is the per-tool breakdown, sorted by call count (busiest first, ties broken by name)
    so the list is deterministic; the panel re-ranks it for its "slowest" (by p95) and "flakiest"
    (by error rate) views. The remaining fields are the endpoint-wide totals across every tool call
    in the window, plus ``latency_distribution`` — a histogram of every tool call's latency for the
    distribution chart. An endpoint with no tool calls yields an empty ``tools`` list, zero totals,
    an all-zero distribution, and a ``0.0`` error rate (never a divide-by-zero).
    """

    tools: List[ToolReliability]
    tool_count: int
    call_count: int
    error_count: int
    success_count: int
    error_rate: float
    latency_distribution: List[LatencyBucket]
    window_days: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tools": [tool.as_dict() for tool in self.tools],
            "tool_count": self.tool_count,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "error_rate": self.error_rate,
            "latency_distribution": [bucket.as_dict() for bucket in self.latency_distribution],
            "window_days": self.window_days,
        }


def _bucket_latencies(latencies: Sequence[float]) -> List[LatencyBucket]:
    """Fold a latency sample into the fixed :data:`_LATENCY_DISTRIBUTION_BUCKETS` histogram.

    Each latency lands in the first bucket whose exclusive ``upper_ms`` it is below; the open-ended
    final bucket catches everything at or above the last boundary. Buckets with no members are still
    returned (with ``count=0``) so the distribution chart always has the same, stable set of bars.
    """
    counts = [0] * len(_LATENCY_DISTRIBUTION_BUCKETS)
    for value in latencies:
        for index, (_label, upper) in enumerate(_LATENCY_DISTRIBUTION_BUCKETS):
            if upper is None or value < upper:
                counts[index] += 1
                break
    return [
        LatencyBucket(label=label, upper_ms=upper, count=counts[index])
        for index, (label, upper) in enumerate(_LATENCY_DISTRIBUTION_BUCKETS)
    ]


def compute_tool_reliability(
    rows: Iterable[Dict[str, Any]], *, window_days: int = TOOL_LATENCY_WINDOW_DAYS
) -> ToolInvocationReliability:
    """Aggregate an endpoint's tool ``mcp_test_invocations`` rows into per-tool reliability.

    Each row is one recorded *tool* call carrying an ``item_name`` (the tool), an ``is_error`` flag,
    and a ``latency_ms`` (``None`` when the call never completed). Rows are grouped by tool; each
    group yields call/error tallies, an error rate, and latency percentiles (over the calls that
    recorded a latency). The endpoint-wide totals and a latency distribution over every tool call
    accompany the per-tool list.

    Args:
        rows: The endpoint's tool test-invocation rows (any iterable; may be empty). A row missing
            or with an empty ``item_name`` is bucketed under ``"(unknown)"`` rather than dropped, so
            the totals never silently disagree with the per-tool breakdown.
        window_days: The trailing window (in days) the rows were selected over, echoed back for the
            panel's "over the last N days" caption.

    Returns:
        The rolled-up :class:`ToolInvocationReliability`; empty tools / zero totals for no calls.
    """
    per_tool_calls: Dict[str, int] = {}
    per_tool_errors: Dict[str, int] = {}
    per_tool_latencies: Dict[str, List[Optional[float]]] = {}
    all_latencies: List[float] = []
    total_calls = 0
    total_errors = 0

    for row in rows:
        name = row.get("item_name") or "(unknown)"
        latency = row.get("latency_ms")
        errored = bool(row.get("is_error"))
        total_calls += 1
        if errored:
            total_errors += 1
        per_tool_calls[name] = per_tool_calls.get(name, 0) + 1
        if errored:
            per_tool_errors[name] = per_tool_errors.get(name, 0) + 1
        per_tool_latencies.setdefault(name, []).append(latency)
        if latency is not None:
            all_latencies.append(float(latency))

    tools: List[ToolReliability] = []
    for name, calls in per_tool_calls.items():
        errors = per_tool_errors.get(name, 0)
        tools.append(
            ToolReliability(
                tool_name=name,
                call_count=calls,
                error_count=errors,
                success_count=calls - errors,
                error_rate=round(errors / calls, 4) if calls else 0.0,
                latency=compute_latency_stats(per_tool_latencies[name]),
            )
        )
    # Busiest tool first; ties broken alphabetically for a stable, deterministic order.
    tools.sort(key=lambda tool: (-tool.call_count, tool.tool_name))

    return ToolInvocationReliability(
        tools=tools,
        tool_count=len(tools),
        call_count=total_calls,
        error_count=total_errors,
        success_count=total_calls - total_errors,
        error_rate=round(total_errors / total_calls, 4) if total_calls else 0.0,
        latency_distribution=_bucket_latencies(all_latencies),
        window_days=window_days,
    )
