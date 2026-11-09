"""MCP endpoint health / uptime summary — the pure layer behind the health badge (V2-MCP-27.3 / MCAT-13.3, #3713).

Catalog quality includes whether an endpoint is *reachable over time*, not just what it advertised at
its last discovery. The health sweep (:mod:`app.mcp_health_sweep`) runs a lightweight reachability
probe — the MCP ``initialize`` handshake only — on a short cadence and stores one
``mcp_endpoint_health_checks`` row per probe. This module folds a window of those rows into the
summary the REST route, the endpoint page and the public SVG badge all show:

* **status** — ``up``, ``degraded``, ``down`` or ``unknown`` (see :func:`derive_uptime_status`);
* **uptime_pct** — the share of probes in the window that succeeded;
* **latency** — the median (p50) and p95 handshake latency of the successful probes;
* **last probe** — when it ran, how it went and, for a failure, its stable error code.

Nothing here touches the database or the network, so every rule is unit-testable and the three
surfaces can never disagree about an endpoint's status.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

# --- Vocabulary ------------------------------------------------------------------------------------

#: A probe whose ``initialize`` handshake completed.
CHECK_UP = "up"
#: A probe that failed (unreachable, timed out, refused, protocol error, …).
CHECK_DOWN = "down"

#: Summary status: the latest probe succeeded and the window's uptime is at or above the threshold.
STATUS_UP = "up"
#: Summary status: the latest probe succeeded, but recent probes failed often enough to drop the
#: window's uptime below :data:`DEGRADED_UPTIME_PCT`.
STATUS_DEGRADED = "degraded"
#: Summary status: the latest probe failed.
STATUS_DOWN = "down"
#: Summary status: no probe in the window (never probed, a stdio server, or monitoring is off).
STATUS_UNKNOWN = "unknown"

#: Every summary status, in documentation order.
UPTIME_STATUSES = (STATUS_UP, STATUS_DEGRADED, STATUS_DOWN, STATUS_UNKNOWN)

#: Below this uptime percentage an endpoint whose latest probe succeeded reads ``degraded``.
DEGRADED_UPTIME_PCT = 99.0

#: The window the badge and the default REST read summarize: the last 24 hours.
DEFAULT_WINDOW_HOURS = 24
#: The longest window the REST route accepts: one week.
MAX_WINDOW_HOURS = 168
#: The most probe rows one summary reads — a week at a one-minute cadence. A window holding more is
#: summarized over its newest rows.
MAX_HEALTH_ROWS = MAX_WINDOW_HOURS * 60


@dataclass(frozen=True)
class UptimeSummary:
    """One endpoint's reachability over a window of probes.

    Attributes:
        status: ``up`` / ``degraded`` / ``down`` / ``unknown`` (:func:`derive_uptime_status`).
        window_hours: The window the summary covers.
        checks: How many probes ran in the window.
        up: How many of them succeeded.
        down: How many of them failed.
        uptime_pct: ``up / checks`` as a percentage rounded to two places; ``None`` with no probes.
        latency_p50_ms: Median latency of the successful probes; ``None`` when none succeeded.
        latency_p95_ms: 95th-percentile latency of the successful probes; ``None`` when none did.
        last_checked_at: When the latest probe ran; ``None`` with no probes.
        last_status: ``up`` / ``down`` of the latest probe; ``None`` with no probes.
        last_error_code: The latest probe's error code when it failed; otherwise ``None``.
    """

    status: str
    window_hours: int
    checks: int
    up: int
    down: int
    uptime_pct: Optional[float]
    latency_p50_ms: Optional[int]
    latency_p95_ms: Optional[int]
    last_checked_at: Optional[datetime]
    last_status: Optional[str]
    last_error_code: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        """Return the summary as a plain dict for a response model."""
        return {
            "status": self.status,
            "window_hours": self.window_hours,
            "checks": self.checks,
            "up": self.up,
            "down": self.down,
            "uptime_pct": self.uptime_pct,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "last_checked_at": self.last_checked_at,
            "last_status": self.last_status,
            "last_error_code": self.last_error_code,
        }


def percentile(values: Sequence[int], pct: float) -> Optional[int]:
    """Return the nearest-rank percentile of ``values`` (``None`` for an empty sequence).

    Nearest-rank keeps the result one of the observed latencies, so a badge never shows a value no
    probe actually measured.

    Args:
        values: Observed latencies in milliseconds, in any order.
        pct: The percentile, 0 < pct <= 100.

    Returns:
        The percentile value, or ``None`` when ``values`` is empty.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return int(ordered[min(rank, len(ordered)) - 1])


def derive_uptime_status(last_status: Optional[str], uptime_pct: Optional[float]) -> str:
    """Fold the latest probe and the window's uptime into one status.

    The latest probe decides first, because it is what a reader acts on: a server that is down right
    now reads ``down`` however good its history. A server that answered last time but failed recently
    reads ``degraded`` while its window uptime is below :data:`DEGRADED_UPTIME_PCT`.

    Args:
        last_status: ``up`` / ``down`` of the latest probe in the window, or ``None`` when there is none.
        uptime_pct: The window's uptime percentage, or ``None`` when there are no probes.

    Returns:
        One of :data:`UPTIME_STATUSES`.
    """
    if last_status is None or uptime_pct is None:
        return STATUS_UNKNOWN
    if last_status != CHECK_UP:
        return STATUS_DOWN
    if uptime_pct < DEGRADED_UPTIME_PCT:
        return STATUS_DEGRADED
    return STATUS_UP


def summarize_health_checks(
    rows: Sequence[Mapping[str, Any]], *, window_hours: int = DEFAULT_WINDOW_HOURS
) -> UptimeSummary:
    """Summarize a window of probe rows into an :class:`UptimeSummary`.

    Args:
        rows: ``mcp_endpoint_health_checks`` rows from the window, **newest first** (the order
            :meth:`Database.list_mcp_health_checks` returns); the first row is the latest probe.
        window_hours: The window the rows were read from, echoed on the summary.

    Returns:
        The summary; an empty ``rows`` yields ``status='unknown'`` with zero counts and ``None``
        statistics — never an error.
    """
    up_latencies: List[int] = []
    up = 0
    for row in rows:
        if row.get("status") == CHECK_UP:
            up += 1
            latency = row.get("latency_ms")
            if latency is not None:
                up_latencies.append(int(latency))
    checks = len(rows)
    uptime_pct = round(up * 100.0 / checks, 2) if checks else None
    latest = rows[0] if rows else None
    last_status = str(latest["status"]) if latest is not None else None
    return UptimeSummary(
        status=derive_uptime_status(last_status, uptime_pct),
        window_hours=int(window_hours),
        checks=checks,
        up=up,
        down=checks - up,
        uptime_pct=uptime_pct,
        latency_p50_ms=percentile(up_latencies, 50),
        latency_p95_ms=percentile(up_latencies, 95),
        last_checked_at=latest.get("checked_at") if latest is not None else None,
        last_status=last_status,
        last_error_code=(
            latest.get("error_code") if latest is not None and last_status == CHECK_DOWN else None
        ),
    )


def format_uptime_pct(uptime_pct: Optional[float]) -> str:
    """Render an uptime percentage compactly for a badge: ``100%``, ``99.9%``, ``87.5%``.

    Rounds *down* to one decimal so a 99.96% window never reads as a perfect ``100%``.

    Args:
        uptime_pct: The percentage, or ``None``.

    Returns:
        The rendered figure, or an empty string for ``None``.
    """
    if uptime_pct is None:
        return ""
    floored = math.floor(float(uptime_pct) * 10) / 10
    if floored >= 100:
        return "100%"
    return f"{floored:.1f}%"
