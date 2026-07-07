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
* :func:`compute_trust_profile` — the five-axis composite "trust profile" (quality, safety,
  documentation, stability, responsiveness), each normalized to 0-100 (or an explicit *gap* when
  its input is missing), synthesized from the metric layers above (V2-MCP-31.4 / MCAT-17.4).
* :func:`compute_tool_count_histogram` — fold a tenant catalog's per-endpoint tool counts into the
  fixed tool-count distribution buckets the catalog analytics dashboard renders (V2-MCP-32.1 /
  MCAT-18.1).
* :func:`compute_peer_percentiles` — rank one endpoint against its category cohort on four axes,
  reusing the trust-axis derivations (V2-MCP-32.3 / MCAT-18.3).
* :func:`compute_capability_overlap` / :func:`rank_embedding_neighbors` — "similar servers" from
  capability-name Jaccard overlap and semantic-embedding cosine nearest-neighbour, the latter
  no-opping to an empty list when embeddings are absent (V2-MCP-32.4 / MCAT-18.4).

Every function is total: an empty sample yields zero counts and ``None`` statistics rather than
raising or dividing by zero, so an endpoint with no history produces an empty (not a 500) series.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .mcp_client.normalize import ITEM_TYPE_TOOL

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


# --- Composite trust profile (V2-MCP-31.4 / MCAT-17.4) --------------------------------------
#
# The capstone of the single-server insight view: a radar across five normalized 0-100 axes that
# synthesizes the scattered reliability/safety signals into one "trust" glance. It is deliberately a
# *heuristic composite* — a synthesized glance, not an official rating — and the panel labels it so.
#
# Each axis reads one already-computed metric layer:
#   * quality        — the snapshot's stored lint score (:mod:`app.mcp_score`).
#   * safety         — behavioural-annotation coverage (:mod:`app.mcp_surface_metrics`) crossed with
#                      the endpoint's auth posture and its destructive-tool count.
#   * documentation  — documentation coverage (:mod:`app.mcp_surface_metrics`).
#   * stability      — the breaking-change rate across the evolution series' snapshot transitions.
#   * responsiveness — test-invocation error rate + p95 latency (:func:`compute_invocation_reliability`).
#
# The single hard rule (the ticket's acceptance criterion): a *missing* input renders as an explicit
# gap (``value is None``, ``available is False``), never a zero — a never-tested server has no
# responsiveness score, not a responsiveness score of zero.

#: The safety axis is half behavioural-annotation transparency, half guardedness against
#: destructive-and-unauthenticated tools.
_SAFETY_TRANSPARENCY_WEIGHT = 0.5
_SAFETY_GUARDEDNESS_WEIGHT = 0.5

#: The responsiveness axis blends the invocation success rate with a p95-latency score, evenly.
_RESPONSIVENESS_RELIABILITY_WEIGHT = 0.5
_RESPONSIVENESS_LATENCY_WEIGHT = 0.5

#: p95 latency at or below the floor scores a full latency component; at or above the ceiling it
#: scores zero, interpolating linearly between. Chosen so a snappy tool (≤200 ms) is "full marks"
#: and a multi-second one (≥5 s) is "poor".
RESPONSIVENESS_LATENCY_FLOOR_MS = 200.0
RESPONSIVENESS_LATENCY_CEILING_MS = 5000.0


def _clamp_score(value: float) -> float:
    """Clamp a raw axis value into ``[0, 100]`` and round to one decimal (deterministic output)."""
    return round(max(0.0, min(100.0, value)), 1)


def mcp_auth_posture(auth_type: Optional[str]) -> str:
    """Resolve an endpoint ``auth_type`` to a coarse posture: ``anonymous`` or ``authenticated``.

    Mirrors the UI ``mcpSafetyAuth`` bands over what the server can actually know: a blank or
    ``none`` auth type is ``anonymous`` (the server is reachable with no credential); any other
    scheme (``bearer`` / ``header`` / ``oauth2`` / ``env``) is ``authenticated``. The UI's third
    ``unknown`` band models a *failed credential fetch* and has no server-side analogue — the
    aggregator always reads the stored credential, so the posture is never unknown here.

    Args:
        auth_type: The endpoint's configured auth scheme, or ``None`` when it has no credential.

    Returns:
        ``"anonymous"`` for a no-auth surface, else ``"authenticated"``.
    """
    value = (auth_type or "").strip().lower()
    return "anonymous" if value in ("", "none") else "authenticated"


def _latency_score(p95_ms: float) -> float:
    """Map a p95 latency (ms) to a 0-100 responsiveness component (fast → 100, slow → 0).

    A p95 at or below :data:`RESPONSIVENESS_LATENCY_FLOOR_MS` scores ``100.0``; at or above
    :data:`RESPONSIVENESS_LATENCY_CEILING_MS` scores ``0.0``; between the two it interpolates
    linearly. The mapping is monotone and total (no divide-by-zero, since floor < ceiling).
    """
    if p95_ms <= RESPONSIVENESS_LATENCY_FLOOR_MS:
        return 100.0
    if p95_ms >= RESPONSIVENESS_LATENCY_CEILING_MS:
        return 0.0
    span = RESPONSIVENESS_LATENCY_CEILING_MS - RESPONSIVENESS_LATENCY_FLOOR_MS
    return 100.0 * (RESPONSIVENESS_LATENCY_CEILING_MS - p95_ms) / span


@dataclass(frozen=True)
class TrustAxis:
    """One normalized 0-100 axis of the composite trust profile.

    ``value`` is the axis score in ``[0, 100]`` when ``available`` is true, or ``None`` when the
    input the axis needs is missing — a never-scored server has no quality axis, a never-tested one
    has no responsiveness axis, and so on. A missing axis is an explicit *gap* the radar renders as
    such, never a zero (which would read as "measured, and bad"). ``detail`` is the always-shown
    one-line basis for the score; ``methodology`` is the longer "how this is computed" text the panel
    reveals on hover (the ticket's "methodology shown on hover").
    """

    key: str
    label: str
    value: Optional[float]
    available: bool
    detail: str
    methodology: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "available": self.available,
            "detail": self.detail,
            "methodology": self.methodology,
        }


@dataclass(frozen=True)
class TrustProfile:
    """The five-axis composite trust profile for one MCP endpoint (a heuristic, not a rating).

    ``axes`` are the five normalized dimensions in canonical (clockwise) radar order: quality,
    safety, documentation, stability, responsiveness. ``overall`` is the mean of the *available*
    axis values (the gaps are excluded, so a partially-measured server is not dragged down by the
    signals it is simply missing), or ``None`` when no axis could be computed at all.
    ``available_count`` / ``axis_count`` let the panel say "3 of 5 signals measured".
    """

    axes: List[TrustAxis]
    overall: Optional[float]
    available_count: int
    axis_count: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "axes": [axis.as_dict() for axis in self.axes],
            "overall": self.overall,
            "available_count": self.available_count,
            "axis_count": self.axis_count,
        }


def _quality_axis(score: Optional[float], grade: Optional[str]) -> TrustAxis:
    """Build the quality axis from the snapshot's stored lint score (a gap when never scored)."""
    methodology = (
        "The server's latest automated quality grade (0–100) from the MCP lint scorer, which "
        "checks naming, structure, annotations, security, and hygiene."
    )
    if score is None:
        return TrustAxis("quality", "Quality", None, False, "Not yet scored", methodology)
    value = _clamp_score(float(score))
    shown = int(round(value))
    detail = f"Grade {grade} · {shown}/100" if grade else f"{shown}/100"
    return TrustAxis("quality", "Quality", value, True, detail, methodology)


def _safety_axis(
    annotation_coverage: Mapping[str, Any], destructive_tool_count: int, auth_posture: str
) -> TrustAxis:
    """Build the safety axis from annotation coverage crossed with the destructive/auth posture.

    Half the score is *transparency* — the share of tools that declare any behavioural hint — and
    half is *guardedness* — full unless destructive tools are reachable with no auth, in which case
    it drops in proportion to how many. Authenticated (or any non-anonymous) access never triggers
    the unguarded-destructive penalty, mirroring the UI's conservative cross-reference. A surface
    with no tools has nothing to assess, so the axis is a gap rather than a misleading score.
    """
    methodology = (
        "Half from behavioural-annotation coverage (the share of tools that declare their "
        "read-only / destructive / idempotent / open-world hints), half from guardedness — "
        "destructive tools reachable with no auth lower the score. Required auth never triggers "
        "the unguarded-destructive penalty."
    )
    tool_count = int(annotation_coverage.get("tool_count", 0) or 0)
    if tool_count <= 0:
        return TrustAxis("safety", "Safety", None, False, "No tools to assess", methodology)

    annotated = int(annotation_coverage.get("annotated_tools", 0) or 0)
    transparency = annotated / tool_count
    if auth_posture == "anonymous":
        guardedness = 1.0 - (max(0, destructive_tool_count) / tool_count)
    else:
        guardedness = 1.0
    value = _clamp_score(
        100.0
        * (transparency * _SAFETY_TRANSPARENCY_WEIGHT + guardedness * _SAFETY_GUARDEDNESS_WEIGHT)
    )
    if auth_posture == "anonymous" and destructive_tool_count > 0:
        detail = (
            f"{annotated}/{tool_count} tools annotated · "
            f"{destructive_tool_count} destructive with no auth"
        )
    else:
        detail = f"{annotated}/{tool_count} tools annotated · {auth_posture}"
    return TrustAxis("safety", "Safety", value, True, detail, methodology)


def _documentation_axis(documentation_coverage: Mapping[str, Any]) -> TrustAxis:
    """Build the documentation axis from item- and parameter-level documentation coverage.

    Averages the item-description and item-title coverage percentages, plus — only when the tools
    take parameters — the tool-parameter documentation percentage, so a parameter-less resource
    server is not unfairly dragged down by a vacuous 0% parameter-doc figure. A surface with no
    capabilities is a gap.
    """
    methodology = (
        "The average of how documented the surface is: the share of items with a description, the "
        "share with a title, and (when the tools take parameters) the share of tool parameters "
        "that are documented."
    )
    item_count = int(documentation_coverage.get("item_count", 0) or 0)
    if item_count <= 0:
        return TrustAxis(
            "documentation", "Documentation", None, False, "No capabilities to assess", methodology
        )

    description_pct = float(documentation_coverage.get("description_pct", 0.0) or 0.0)
    title_pct = float(documentation_coverage.get("title_pct", 0.0) or 0.0)
    components = [description_pct, title_pct]
    if int(documentation_coverage.get("tool_param_count", 0) or 0) > 0:
        components.append(float(documentation_coverage.get("tool_param_description_pct", 0.0) or 0.0))
    value = _clamp_score(sum(components) / len(components))
    detail = f"{round(description_pct)}% described · {round(title_pct)}% titled"
    return TrustAxis("documentation", "Documentation", value, True, detail, methodology)


def _stability_axis(change_severities: Sequence[Mapping[str, Any]]) -> TrustAxis:
    """Build the stability axis from the breaking-change rate across snapshot transitions.

    Each entry in ``change_severities`` is the ``{breaking, additive, review, total}`` classification
    of one snapshot transition (V2-MCP-30.3). Stability is the share of transitions that carried no
    breaking change; a single breaking release in a short history therefore weighs heavily, as it
    should. Fewer than one transition (a brand-new endpoint with one snapshot) is a gap — there is no
    change history to judge yet.
    """
    methodology = (
        "The share of surface changes across discovery snapshots that were non-breaking. Breaking "
        "changes (removed or incompatibly-changed capabilities) lower stability; purely additive "
        "changes do not. Needs at least two snapshots to assess."
    )
    total = len(change_severities)
    if total <= 0:
        return TrustAxis("stability", "Stability", None, False, "Not enough history", methodology)

    breaking = sum(1 for sev in change_severities if int(sev.get("breaking", 0) or 0) > 0)
    value = _clamp_score(100.0 * (1.0 - breaking / total))
    noun = "change" if total == 1 else "changes"
    detail = f"{total - breaking}/{total} snapshot {noun} non-breaking"
    return TrustAxis("stability", "Stability", value, True, detail, methodology)


def _responsiveness_axis(invocation: Mapping[str, Any]) -> TrustAxis:
    """Build the responsiveness axis from test-invocation error rate + p95 latency (a gap if never tested).

    Half the score is the invocation success rate (``1 - error_rate``); half is a p95-latency score
    (see :func:`_latency_score`). When no call recorded a latency the latency half is dropped and the
    axis is the success rate alone. A never-tested endpoint (no calls) is the canonical gap.
    """
    methodology = (
        "Half from the test-invocation success rate, half from p95 latency "
        f"(≤{int(RESPONSIVENESS_LATENCY_FLOOR_MS)} ms scores full, "
        f"≥{RESPONSIVENESS_LATENCY_CEILING_MS / 1000:.0f} s scores zero). Needs the server to have "
        "been tested at least once."
    )
    call_count = int(invocation.get("call_count", 0) or 0)
    if call_count <= 0:
        return TrustAxis(
            "responsiveness", "Responsiveness", None, False, "Never tested", methodology
        )

    error_rate = float(invocation.get("error_rate", 0.0) or 0.0)
    reliability_component = (1.0 - error_rate) * 100.0
    latency = invocation.get("latency") or {}
    p95 = latency.get("p95_ms")
    if p95 is not None:
        value = _clamp_score(
            reliability_component * _RESPONSIVENESS_RELIABILITY_WEIGHT
            + _latency_score(float(p95)) * _RESPONSIVENESS_LATENCY_WEIGHT
        )
        detail = f"{round(error_rate * 100, 1)}% errors · p95 {int(round(float(p95)))} ms"
    else:
        value = _clamp_score(reliability_component)
        detail = f"{round(error_rate * 100, 1)}% errors"
    return TrustAxis("responsiveness", "Responsiveness", value, True, detail, methodology)


def compute_trust_profile(
    *,
    quality_score: Optional[float],
    quality_grade: Optional[str],
    annotation_coverage: Mapping[str, Any],
    documentation_coverage: Mapping[str, Any],
    destructive_tool_count: int,
    auth_posture: str,
    change_severities: Sequence[Mapping[str, Any]],
    invocation: Mapping[str, Any],
) -> TrustProfile:
    """Synthesize the five-axis composite :class:`TrustProfile` from the metric layers.

    Pure and total: every axis is computed independently, and any missing input yields an explicit
    *gap* (``value is None``) rather than a zero. The ``overall`` composite is the mean of only the
    available axes, so it never conflates "not measured" with "measured poorly".

    Args:
        quality_score: The current snapshot's stored 0-100 lint score, or ``None`` when unscored.
        quality_grade: The score's A-F letter (for the axis detail line), or ``None``.
        annotation_coverage: An :class:`~app.mcp_surface_metrics.AnnotationCoverage` ``as_dict()``
            (needs ``tool_count`` / ``annotated_tools``); ``{}`` when there is no surface.
        documentation_coverage: A :class:`~app.mcp_surface_metrics.DocumentationCoverage`
            ``as_dict()`` (needs ``item_count`` and the coverage percentages); ``{}`` when none.
        destructive_tool_count: How many tools assert ``destructiveHint: true`` on the surface.
        auth_posture: ``"anonymous"`` or ``"authenticated"`` (see :func:`mcp_auth_posture`).
        change_severities: One ``{breaking, additive, review, total}`` classification per snapshot
            *transition* (i.e. every snapshot after the first); empty for ≤1 snapshot.
        invocation: An :class:`InvocationReliability` ``as_dict()`` (needs ``call_count`` /
            ``error_rate`` / ``latency.p95_ms``).

    Returns:
        The rolled-up :class:`TrustProfile` — five axes (some possibly gaps) plus the mean of the
        available ones.
    """
    axes = [
        _quality_axis(quality_score, quality_grade),
        _safety_axis(annotation_coverage, destructive_tool_count, auth_posture),
        _documentation_axis(documentation_coverage),
        _stability_axis(change_severities),
        _responsiveness_axis(invocation),
    ]
    available = [axis.value for axis in axes if axis.available and axis.value is not None]
    overall = round(sum(available) / len(available), 1) if available else None
    return TrustProfile(
        axes=axes,
        overall=overall,
        available_count=len(available),
        axis_count=len(axes),
    )


# --- Catalog-wide tool-count histogram (V2-MCP-32.1 / MCAT-18.1) --------------------------------

#: The tool-count buckets the catalog dashboard's distribution bar chart renders, in display order.
#: Each entry is ``(label, upper)`` where ``upper`` is the *inclusive* top of the range, or ``None``
#: for the open-ended final bucket. The first bucket is the exact-zero ("no tools") column so a
#: catalog full of never-discovered or empty servers is visible rather than folded into "1–5".
_TOOL_COUNT_BUCKETS: Tuple[Tuple[str, Optional[int]], ...] = (
    ("0", 0),
    ("1–5", 5),
    ("6–20", 20),
    ("21–50", 50),
    ("50+", None),
)


@dataclass(frozen=True)
class CatalogCountBucket:
    """One bar of the catalog tool-count distribution: a labelled range and how many endpoints fell in it."""

    label: str
    count: int

    def as_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "count": self.count}


def compute_tool_count_histogram(
    per_endpoint_tool_counts: Iterable[Optional[int]],
) -> List[CatalogCountBucket]:
    """Fold each endpoint's tool count into the fixed :data:`_TOOL_COUNT_BUCKETS` histogram.

    Every endpoint contributes exactly one to the first bucket whose *inclusive* ``upper`` its tool
    count does not exceed; the open-ended final bucket catches everything above the last boundary. A
    missing / ``None`` count is treated as zero tools (an endpoint that was never discovered has no
    surface, hence no tools), so it lands in the ``"0"`` column rather than being dropped. Buckets
    with no members are still returned (``count=0``) so the chart always has the same, stable set of
    bars — including for an empty catalog, where every bucket is zero.

    Args:
        per_endpoint_tool_counts: One tool count per live endpoint (``None`` → treated as ``0``).

    Returns:
        One :class:`CatalogCountBucket` per :data:`_TOOL_COUNT_BUCKETS` entry, in display order.
    """
    counts = [0] * len(_TOOL_COUNT_BUCKETS)
    for raw in per_endpoint_tool_counts:
        value = int(raw) if raw is not None else 0
        for index, (_label, upper) in enumerate(_TOOL_COUNT_BUCKETS):
            if upper is None or value <= upper:
                counts[index] += 1
                break
    return [
        CatalogCountBucket(label=label, count=counts[index])
        for index, (label, _upper) in enumerate(_TOOL_COUNT_BUCKETS)
    ]


# --- Peer percentile & category ranking (V2-MCP-32.3 / MCAT-18.3) -------------------------------
#
# "Is this a good weather server?" needs a *peer baseline*, not an absolute grade — a documentation
# score of 70 means one thing in a category where everyone documents thoroughly and another where no
# one does. This section ranks one endpoint against the other live endpoints in its **category** on
# four axes (grade, safety, documentation, latency), so the UI can render "top 10% for documentation"
# badges.
#
# The axis *values* reuse the exact single-server derivations the composite trust profile uses
# (:func:`_quality_axis`, :func:`_safety_axis`, :func:`_documentation_axis`, :func:`_latency_score`),
# so a server's rank is computed from the same numbers its own Insight tab shows. The ranking itself
# is a pure, deterministic percentile over the cohort's values — computed in Python (mirroring the
# rest of this module) so it is unit-testable against a hand-seeded cohort without a live database.
#
# Two hard rules (the ticket's acceptance criteria): a **single-member** category is handled (the sole
# server is trivially the category leader, ``percentile=100``), and an axis a server does not have
# measured (never scored, no tools, never tested) is an explicit *gap* (``value=None``), never ranked.

#: The four ranked axes, in display order, as ``(key, label)``. ``grade`` is the stored lint score,
#: ``latency`` is the p95-latency component of responsiveness (fast → high). Each maps to a value the
#: trust axes already derive, so a rank never disagrees with the server's own Insight numbers.
_PEER_AXES: Tuple[Tuple[str, str], ...] = (
    ("grade", "Grade"),
    ("safety", "Safety"),
    ("documentation", "Documentation"),
    ("latency", "Latency"),
)


def percentile_rank(values: Sequence[float], target: float) -> Optional[float]:
    """The percentile rank of ``target`` within ``values`` — the share at or below it, as 0-100.

    Defined as ``100 * (count of values <= target) / n`` over the cohort ``values`` (which must
    *include* the target's own value), rounded to one decimal. Higher is better: the category leader
    scores ``100`` (every peer is at or below it), and a lone member scores ``100`` (it is trivially
    the top of its one-member cohort — the single-member acceptance case). Ties count toward the
    rank, so equally-good servers share the same percentile.

    Args:
        values: The cohort's axis values, *including* the target's own; must be non-empty.
        target: The target server's value on this axis.

    Returns:
        The percentile in ``[0, 100]``, or ``None`` when ``values`` is empty.
    """
    if not values:
        return None
    at_or_below = sum(1 for v in values if float(v) <= target)
    return round(100.0 * at_or_below / len(values), 1)


def compute_endpoint_percentile_axes(
    *,
    score: Optional[float],
    grade: Optional[str],
    annotation_coverage: Mapping[str, Any],
    documentation_coverage: Mapping[str, Any],
    destructive_tool_count: int,
    auth_posture: str,
    invocation: Mapping[str, Any],
) -> Dict[str, Optional[float]]:
    """Compute one endpoint's four ranked axis values (``grade`` / ``safety`` / ``documentation`` /
    ``latency``), reusing the trust-profile axis derivations.

    Each value is the same 0-100 number the corresponding trust axis carries, or ``None`` when the
    input is missing (never scored → no grade, no tools → no safety, no capabilities → no docs, never
    tested → no latency). ``latency`` is the p95-latency component alone (fast → 100), so the axis
    ranks *speed* specifically, as the ticket names it.

    Args:
        score: The current snapshot's stored 0-100 lint score, or ``None``.
        grade: The score's A-F letter (unused in the value, kept for signature parity), or ``None``.
        annotation_coverage: An ``AnnotationCoverage.as_dict()`` (``{}`` when there is no surface).
        documentation_coverage: A ``DocumentationCoverage.as_dict()`` (``{}`` when none).
        destructive_tool_count: How many tools assert ``destructiveHint: true``.
        auth_posture: ``"anonymous"`` or ``"authenticated"`` (see :func:`mcp_auth_posture`).
        invocation: An ``InvocationReliability.as_dict()`` (needs ``latency.p95_ms``).

    Returns:
        A ``{axis_key: value_or_None}`` map over the four :data:`_PEER_AXES` keys.
    """
    latency = invocation.get("latency") or {}
    p95 = latency.get("p95_ms")
    return {
        "grade": _quality_axis(score, grade).value,
        "safety": _safety_axis(annotation_coverage, destructive_tool_count, auth_posture).value,
        "documentation": _documentation_axis(documentation_coverage).value,
        "latency": _latency_score(float(p95)) if p95 is not None else None,
    }


@dataclass(frozen=True)
class PeerAxisPercentile:
    """One axis of a server's peer ranking within its category.

    ``value`` is the server's own 0-100 axis value; ``percentile`` is its :func:`percentile_rank`
    within the cohort (higher = better); ``rank`` is its ordinal position (``1`` = best); ``top_percent``
    is the "top N%" the badge renders (``ceil(100 * rank / cohort_size)``); ``cohort_size`` is how many
    servers in the category have this axis measured (so a rank reads "3 of 8"). An axis the server does
    not have measured is a *gap*: ``available`` is false, ``value`` / ``percentile`` / ``rank`` /
    ``top_percent`` are ``None``, and ``cohort_size`` counts the peers that *do* have it.
    """

    key: str
    label: str
    value: Optional[float]
    percentile: Optional[float]
    rank: Optional[int]
    top_percent: Optional[int]
    cohort_size: int
    available: bool
    detail: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "percentile": self.percentile,
            "rank": self.rank,
            "top_percent": self.top_percent,
            "cohort_size": self.cohort_size,
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PeerPercentileProfile:
    """A server's peer ranking across the four axes within its catalog category.

    ``category`` is the cohort's category (``None`` for the uncategorized cohort); ``cohort_size`` is
    the total number of live endpoints in the category (including this one), independent of how many
    have any given axis measured. ``axes`` are the four rankings in :data:`_PEER_AXES` order, some of
    which may be gaps.
    """

    category: Optional[str]
    cohort_size: int
    axes: List[PeerAxisPercentile]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "cohort_size": self.cohort_size,
            "axes": [axis.as_dict() for axis in self.axes],
        }


def _peer_axis_detail(*, label: str, rank: int, cohort_size: int, top_percent: int) -> str:
    """The one-line basis a ranked axis shows (e.g. "Rank 2 of 8 · top 25%")."""
    if cohort_size <= 1:
        return f"Only server with a {label.lower()} score in this category"
    return f"Rank {rank} of {cohort_size} · top {top_percent}%"


def compute_peer_percentiles(
    *,
    category: Optional[str],
    cohort_size: int,
    target_axis_values: Mapping[str, Optional[float]],
    cohort_axis_values: Mapping[str, Sequence[float]],
) -> PeerPercentileProfile:
    """Rank one server against its category cohort on each of the four :data:`_PEER_AXES`.

    For every axis, the server's percentile is its :func:`percentile_rank` within the cohort's values
    on that axis (which must include the server's own). ``rank`` counts how many peers score strictly
    higher, plus one (so ties share a rank and ``1`` is best); ``top_percent`` is
    ``ceil(100 * rank / n)`` — the "top N%" badge. An axis with no target value, or an empty cohort on
    that axis, is an explicit gap. Pure and deterministic: identical cohorts yield identical output.

    Args:
        category: The cohort's category (``None`` / blank for the uncategorized cohort).
        cohort_size: Total live endpoints in the category, including the target.
        target_axis_values: The target server's ``{axis_key: value_or_None}`` map.
        cohort_axis_values: Per axis, the list of *all* cohort members' non-``None`` values on that
            axis (including the target's). Missing/short lists simply yield gaps.

    Returns:
        The :class:`PeerPercentileProfile` — four rankings (some possibly gaps) within the category.
    """
    axes: List[PeerAxisPercentile] = []
    for key, label in _PEER_AXES:
        target = target_axis_values.get(key)
        values = [float(v) for v in cohort_axis_values.get(key, []) if v is not None]
        if target is None or not values:
            axes.append(
                PeerAxisPercentile(
                    key=key,
                    label=label,
                    value=None,
                    percentile=None,
                    rank=None,
                    top_percent=None,
                    cohort_size=len(values),
                    available=False,
                    detail="Not measured",
                )
            )
            continue
        target_value = float(target)
        percentile = percentile_rank(values, target_value)
        rank = 1 + sum(1 for v in values if v > target_value)
        axis_cohort = len(values)
        top_percent = math.ceil(100.0 * rank / axis_cohort)
        axes.append(
            PeerAxisPercentile(
                key=key,
                label=label,
                value=round(target_value, 1),
                percentile=percentile,
                rank=rank,
                top_percent=top_percent,
                cohort_size=axis_cohort,
                available=True,
                detail=_peer_axis_detail(
                    label=label, rank=rank, cohort_size=axis_cohort, top_percent=top_percent
                ),
            )
        )
    return PeerPercentileProfile(category=category, cohort_size=cohort_size, axes=axes)


# --- Similar servers: capability overlap + semantic embeddings (V2-MCP-32.4 / MCAT-18.4) ---------
#
# "Servers like this one" from two independent signals, both computed here as pure functions so each
# is unit-testable against a hand-built fixture without a live database:
#
# * **Capability overlap** — a Jaccard set-overlap over an endpoint's capability *names* (its tools,
#   resources, resource-templates, and prompts). Two servers that expose the same-named capabilities
#   are similar regardless of any embedding model; this signal is always available (it reads the
#   already-normalized ``mcp_capability_items``), which is why it is the fallback when embeddings are
#   off. :func:`compute_capability_overlap` ranks candidates by Jaccard (the acceptance fixture).
# * **Semantic embeddings** — a cosine nearest-neighbour over a per-snapshot capability embedding
#   (reusing the pgvector setup, V102/V060). :func:`rank_embedding_neighbors` ranks candidates by
#   cosine similarity to the target's vector; an absent target vector (or no candidate vectors — the
#   embeddings-disabled / not-yet-backfilled case) yields an empty list, never an error, so the route
#   falls back to overlap only.
#
# :func:`build_capability_embedding_text` derives the deterministic text a snapshot's embedding is
# computed from, so the backfill step and any test seed agree on the input.


def normalize_capability_name(name: Optional[str]) -> str:
    """Fold a capability name to its comparison form (trimmed, lower-cased); ``""`` when empty."""
    return (name or "").strip().lower()


def capability_name_set(names: Iterable[Optional[str]]) -> frozenset:
    """The set of non-empty, normalized capability names — the unit the Jaccard overlap compares."""
    return frozenset(n for n in (normalize_capability_name(x) for x in names) if n)


def jaccard_similarity(a: "frozenset | set", b: "frozenset | set") -> float:
    """The Jaccard index of two sets: ``|a ∩ b| / |a ∪ b|``, in ``[0, 1]`` (``0`` when both empty)."""
    if not a and not b:
        return 0.0
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def build_capability_embedding_text(
    items: Iterable[Tuple[Optional[str], Optional[str]]],
) -> str:
    """Build the deterministic text a snapshot's capability embedding is computed from.

    Folds the surface's ``(name, description)`` pairs into a stable, de-duplicated, sorted document
    (one ``"name: description"`` line per distinct capability) so re-embedding an unchanged surface
    yields identical input — the backfill step and any test seed derive the same text. Order-independent
    by construction (sorted), so two discoveries that list the same capabilities in a different order
    embed to the same text.

    Args:
        items: The surface's capabilities as ``(name, description)`` pairs; blank names are dropped and
            a missing description contributes just the name.

    Returns:
        A newline-joined document, or ``""`` when there are no named capabilities.
    """
    lines = set()
    for name, description in items:
        clean_name = (name or "").strip()
        if not clean_name:
            continue
        clean_desc = (description or "").strip()
        lines.add(f"{clean_name}: {clean_desc}" if clean_desc else clean_name)
    return "\n".join(sorted(lines))


@dataclass(frozen=True)
class OverlapNeighbor:
    """One capability-overlap similar server — a peer ranked by shared capability names.

    ``similarity`` is the Jaccard index (``|shared| / |union|``, ``0``-``1``) of the two servers'
    capability-name sets; ``shared_capabilities`` lists the names in common (normalized, sorted), with
    ``shared_count`` its length; ``target_capability_count`` / ``candidate_capability_count`` are the
    two servers' distinct-name counts, so the UI can render "8 of 12 shared".
    """

    endpoint_id: str
    name: str
    slug: Optional[str]
    category: Optional[str]
    similarity: float
    shared_count: int
    target_capability_count: int
    candidate_capability_count: int
    shared_capabilities: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "similarity": self.similarity,
            "shared_count": self.shared_count,
            "target_capability_count": self.target_capability_count,
            "candidate_capability_count": self.candidate_capability_count,
            "shared_capabilities": list(self.shared_capabilities),
        }


@dataclass(frozen=True)
class EmbeddingNeighbor:
    """One semantic-embedding similar server — a peer ranked by cosine similarity of capability text.

    ``similarity`` is the cosine similarity (``-1``-``1``, higher = nearer) of the two snapshots'
    capability embeddings.
    """

    endpoint_id: str
    name: str
    slug: Optional[str]
    category: Optional[str]
    similarity: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "slug": self.slug,
            "category": self.category,
            "similarity": self.similarity,
        }


def compute_capability_overlap(
    target_names: Iterable[Optional[str]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = 10,
) -> List[OverlapNeighbor]:
    """Rank ``candidates`` by capability-name overlap (Jaccard) with the target server.

    The target's and each candidate's capability names are folded to normalized sets
    (:func:`capability_name_set`); a candidate's similarity is the :func:`jaccard_similarity` of the two
    sets. Only candidates that actually share a capability (``similarity > 0``) are returned — a server
    with nothing in common is not "similar" — ordered by similarity (descending), then by the number of
    shared capabilities, then by name, so ties are stable. A target with no capabilities yields an empty
    list (there is nothing to be similar to).

    Args:
        target_names: The target server's capability names (any item type).
        candidates: Peer servers, each a mapping with ``endpoint_id``, ``name``, optional ``slug`` /
            ``category``, and ``capability_names`` (an iterable of names). Callers exclude the target
            itself upstream, so a server is never ranked as its own neighbour.
        limit: Maximum neighbours to return (the highest-similarity ``limit``).

    Returns:
        The ranked :class:`OverlapNeighbor` list (at most ``limit``), possibly empty.
    """
    target_set = capability_name_set(target_names)
    if not target_set:
        return []

    neighbors: List[OverlapNeighbor] = []
    for candidate in candidates:
        candidate_set = capability_name_set(candidate.get("capability_names") or [])
        similarity = jaccard_similarity(target_set, candidate_set)
        if similarity <= 0.0:
            continue
        shared = sorted(target_set & candidate_set)
        neighbors.append(
            OverlapNeighbor(
                endpoint_id=str(candidate["endpoint_id"]),
                name=str(candidate.get("name") or ""),
                slug=candidate.get("slug"),
                category=candidate.get("category"),
                similarity=round(similarity, 4),
                shared_count=len(shared),
                target_capability_count=len(target_set),
                candidate_capability_count=len(candidate_set),
                shared_capabilities=shared,
            )
        )

    neighbors.sort(key=lambda n: (-n.similarity, -n.shared_count, n.name.lower()))
    return neighbors[: max(0, limit)]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """Cosine similarity of two equal-length vectors, or ``None`` when it is undefined.

    Returns ``dot(a, b) / (‖a‖·‖b‖)``. ``None`` when the vectors differ in length or either is a zero
    vector (an undefined direction), so the caller drops that candidate rather than dividing by zero.
    """
    if len(a) != len(b) or not a:
        return None
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    if norm_a <= 0.0 or norm_b <= 0.0:
        return None
    return dot / math.sqrt(norm_a * norm_b)


def rank_embedding_neighbors(
    target_embedding: Optional[Sequence[float]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    limit: int = 10,
    min_similarity: float = 0.0,
) -> List[EmbeddingNeighbor]:
    """Rank ``candidates`` by cosine nearest-neighbour to the target's capability embedding.

    Each candidate carrying an ``embedding`` of the same dimension as ``target_embedding`` is scored by
    :func:`cosine_similarity`; results are ordered by similarity (descending), then by name, and capped
    at ``limit``. Candidates below ``min_similarity``, of a mismatched dimension, or with an undefined
    similarity (a zero vector) are dropped. An absent ``target_embedding`` — or simply no candidate
    vectors, which is the embeddings-disabled / not-yet-backfilled state — yields an empty list, so the
    route falls back to overlap-only without erroring (the "gracefully no-ops if embeddings are disabled"
    acceptance criterion).

    Args:
        target_embedding: The target snapshot's capability embedding, or ``None`` when it has none.
        candidates: Peer servers, each a mapping with ``endpoint_id``, ``name``, optional ``slug`` /
            ``category``, and ``embedding`` (a vector, or ``None`` when that peer has none).
        limit: Maximum neighbours to return.
        min_similarity: Drop neighbours whose cosine similarity is strictly below this floor.

    Returns:
        The ranked :class:`EmbeddingNeighbor` list (at most ``limit``), empty when embeddings are absent.
    """
    if not target_embedding:
        return []
    target_vec = [float(x) for x in target_embedding]

    neighbors: List[EmbeddingNeighbor] = []
    for candidate in candidates:
        embedding = candidate.get("embedding")
        if not embedding:
            continue
        similarity = cosine_similarity(target_vec, [float(x) for x in embedding])
        if similarity is None or similarity < min_similarity:
            continue
        neighbors.append(
            EmbeddingNeighbor(
                endpoint_id=str(candidate["endpoint_id"]),
                name=str(candidate.get("name") or ""),
                slug=candidate.get("slug"),
                category=candidate.get("category"),
                similarity=round(similarity, 4),
            )
        )

    neighbors.sort(key=lambda n: (-n.similarity, n.name.lower()))
    return neighbors[: max(0, limit)]


# ===================================================================================================
# Schema-driven example synthesis for the natural-language server digest (V2-MCP-32.5 / MCAT-18.5).
#
# The digest feature pairs a short AI-written summary of a server ("this server lets you …") with one
# *example call per tool*. The example arguments are synthesized **deterministically from each tool's
# ``input_schema``** — never by executing the tool and never by asking the model to invent values — so
# the "no tool is executed to produce examples" acceptance criterion holds by construction, and the
# examples are pure, unit-testable, and stable across regenerations of the same surface. The AI step
# (the prose digest) lives in :mod:`app.mcp_digest_service`; everything below is plain, offline data
# shaping over the already-normalized ``mcp_capability_items`` rows.
# ===================================================================================================

#: Recursion ceiling for :func:`synthesize_example_value` — guards against a pathologically deep or
#: self-referential ``input_schema`` producing unbounded nesting. Beyond it, a placeholder is emitted.
_EXAMPLE_MAX_DEPTH = 6

#: Per-``format`` sample strings, so an example argument reads like a plausible value of that format
#: rather than a bare placeholder. Only formats an MCP tool schema realistically declares are listed.
_EXAMPLE_FORMAT_SAMPLES: Dict[str, str] = {
    "date-time": "2026-01-01T00:00:00Z",
    "date": "2026-01-01",
    "time": "00:00:00",
    "duration": "PT1H",
    "email": "user@example.com",
    "hostname": "example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "ipv4": "192.0.2.1",
    "ipv6": "2001:db8::1",
}


def synthesize_example_value(schema: Any, *, _depth: int = 0) -> Any:
    """Deterministically synthesize a sample value for a JSON-Schema fragment.

    Produces a single plausible example value for the given schema, used to fill in the arguments of a
    tool's example call in the server digest (MCAT-18.5). The synthesis is **schema-driven and offline**
    — it inspects the declared shape (``type``, ``enum``, ``const``, ``default``, ``examples``, string
    ``format``, object ``properties`` / ``required``, array ``items``) and returns a matching literal.
    It never calls the tool or the network, so it can be exercised in isolation and can never trigger a
    side effect.

    Resolution order for each node: an explicit ``const`` or first ``examples`` / ``default`` wins; then
    a declared ``enum``'s first member; then the first branch of a ``oneOf`` / ``anyOf`` / ``allOf``;
    otherwise a value shaped by ``type`` (objects recurse over ``required`` first then remaining declared
    ``properties``; arrays yield a single synthesized element; strings honour ``format``). An unknown or
    missing type falls back to a ``"string"`` placeholder. Recursion is bounded by
    :data:`_EXAMPLE_MAX_DEPTH` so a cyclic ``$ref``-style schema (already de-referenced upstream) or a
    deeply nested object cannot loop forever.

    Args:
        schema: A JSON-Schema fragment (typically a Python ``dict`` decoded from ``input_schema`` JSONB);
            a non-mapping ``schema`` yields the generic string placeholder.

    Returns:
        A JSON-serializable sample value (``str`` / ``int`` / ``float`` / ``bool`` / ``list`` / ``dict``
        / ``None``) consistent with ``schema``.
    """
    if _depth > _EXAMPLE_MAX_DEPTH or not isinstance(schema, Mapping):
        return "example"

    # An explicit constant or author-provided sample is always the most faithful example.
    if "const" in schema:
        return schema["const"]
    examples = schema.get("examples")
    if isinstance(examples, (list, tuple)) and examples:
        return examples[0]
    if "default" in schema:
        return schema["default"]

    enum = schema.get("enum")
    if isinstance(enum, (list, tuple)) and enum:
        return enum[0]

    for combiner in ("oneOf", "anyOf", "allOf"):
        branches = schema.get(combiner)
        if isinstance(branches, (list, tuple)) and branches:
            return synthesize_example_value(branches[0], _depth=_depth + 1)

    schema_type = schema.get("type")
    if isinstance(schema_type, (list, tuple)):
        # A union type (e.g. ["string", "null"]) — use the first non-null member.
        schema_type = next((t for t in schema_type if t != "null"), None)

    if schema_type == "object" or (schema_type is None and "properties" in schema):
        return _synthesize_example_object(schema, _depth=_depth)
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, Mapping):
            return [synthesize_example_value(items, _depth=_depth + 1)]
        return []
    if schema_type == "boolean":
        return True
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1.0
    if schema_type == "null":
        return None

    # Strings and anything untyped: honour a declared format, else a titled/named placeholder.
    fmt = schema.get("format")
    if isinstance(fmt, str) and fmt in _EXAMPLE_FORMAT_SAMPLES:
        return _EXAMPLE_FORMAT_SAMPLES[fmt]
    return "example"


def _synthesize_example_object(schema: Mapping[str, Any], *, _depth: int) -> Dict[str, Any]:
    """Synthesize a sample object, emitting ``required`` properties first then remaining declared ones.

    Ordering ``required`` fields ahead of optional ones keeps the example focused on what a caller must
    supply, and preserves declaration order within each group so the output is deterministic.
    """
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        return {}

    required = schema.get("required")
    required_names = [r for r in required if r in properties] if isinstance(required, (list, tuple)) else []
    ordered = list(required_names) + [name for name in properties if name not in required_names]

    result: Dict[str, Any] = {}
    for name in ordered:
        result[str(name)] = synthesize_example_value(properties[name], _depth=_depth + 1)
    return result


@dataclass(frozen=True)
class ToolExample:
    """One tool's schema-derived example call for the server digest (MCAT-18.5).

    ``arguments`` is the deterministic sample-argument object synthesized from the tool's ``input_schema``
    by :func:`synthesize_example_value` — a suggested payload a caller *could* send, never the result of
    actually invoking the tool. ``arguments`` is ``{}`` for a tool that declares no input schema (or a
    non-object one), which is a valid "no arguments" example.
    """

    name: str
    title: Optional[str]
    description: Optional[str]
    arguments: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "arguments": self.arguments,
        }


def build_tool_examples(items: Iterable[Mapping[str, Any]]) -> List[ToolExample]:
    """Build one schema-derived example call per **tool** in a capability-item set (MCAT-18.5).

    Filters the version snapshot's capability items to tools (resources and prompts are not "called" with
    arguments) and, preserving their discovery order, synthesizes a deterministic example-argument object
    for each from its ``input_schema``. Tools without a name are skipped; a tool whose ``input_schema`` is
    absent or not an object yields an empty ``arguments`` (a legitimate no-argument call). No tool is
    executed — the arguments are pure schema shaping, satisfying the "no tool is executed to produce
    examples" acceptance criterion.

    Args:
        items: The version's normalized ``mcp_capability_items`` rows (each a mapping with ``item_type``,
            ``name``, optional ``title`` / ``description`` / ``input_schema``).

    Returns:
        One :class:`ToolExample` per named tool, in discovery order; empty when the surface has no tools.
    """
    examples: List[ToolExample] = []
    for item in items:
        if item.get("item_type") != ITEM_TYPE_TOOL:
            continue
        name = item.get("name")
        if not name:
            continue
        arguments = synthesize_example_value(item.get("input_schema"))
        if not isinstance(arguments, dict):
            arguments = {}
        examples.append(
            ToolExample(
                name=str(name),
                title=item.get("title"),
                description=item.get("description"),
                arguments=arguments,
            )
        )
    return examples
