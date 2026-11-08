"""MCP discovery sweep health, as the ops endpoint reports it (V2-MCP-19.4 / MCAT-5.4, #3676).

The periodic re-discovery sweep (:mod:`app.mcp_discovery_sweep`) records one
``mcp_discovery_sweep_runs`` row per tick and links each job it creates to that row.
:func:`sweep_status_payload` turns the recent runs — read with
:meth:`app.database.Database.list_mcp_discovery_sweep_runs`, which aggregates each run's outcome
counts from its jobs — and the sweep's settings into the response of
``GET /v1/ops/mcp-discovery-sweep``:

* ``config`` — whether the sweep is enabled and the bounds it runs under;
* ``last_run`` — the most recent tick (``None`` before the first one);
* ``runs`` — the recent ticks, newest first;
* ``totals`` — the same counters summed over those runs.

Per run, the counters mean:

* ``due`` — endpoints selected as due; ``dispatched`` — discovery runs the tick started;
  ``coalesced`` — due endpoints whose job joined one already in progress; ``enqueue_failed`` —
  due endpoints whose job could not be created;
* ``checked`` — the tick's jobs still in the job log, and of those ``changed`` (created a
  version), ``unchanged`` (same surface), ``failed`` (including per-endpoint timeouts) and
  ``in_flight`` (still queued or running). ``checked = changed + unchanged + failed + in_flight``
  always, because all five come from the same job rows. ``checked`` equals ``dispatched`` unless
  an endpoint — and with it its jobs — was deleted since.

Durations are milliseconds: ``duration_ms`` for the tick (``None`` while it drains) and
``avg_job_ms`` / ``max_job_ms`` over its finished jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

#: How many recent runs the endpoint returns by default, and at most.
DEFAULT_RUN_LIMIT = 20
MAX_RUN_LIMIT = 200

#: The per-run counters summed into ``totals``.
_TOTALLED = (
    "due",
    "dispatched",
    "coalesced",
    "enqueue_failed",
    "checked",
    "changed",
    "unchanged",
    "failed",
    "in_flight",
)


def sweep_status_payload(
    rows: Sequence[Mapping[str, Any]],
    settings: Any,
    *,
    retention_days: int,
) -> Dict[str, Any]:
    """Build the sweep-health response from recent run rows and the sweep's settings.

    Args:
        rows: Run rows from :meth:`Database.list_mcp_discovery_sweep_runs`, newest first.
        settings: The application settings (``mcp_discovery_*``).
        retention_days: How long run rows are kept.

    Returns:
        ``{"config", "last_run", "runs", "totals"}`` as described in the module docstring.
    """
    runs = [sweep_run_view(row) for row in rows]
    totals: Dict[str, Any] = {key: sum(run[key] for run in runs) for key in _TOTALLED}
    totals["runs"] = len(runs)
    totals["halted_runs"] = sum(1 for run in runs if run["status"] == "halted")
    totals["failed_runs"] = sum(1 for run in runs if run["status"] == "failed")
    return {
        "config": {
            "enabled": bool(settings.mcp_discovery_enabled),
            "tick_seconds": max(1, int(settings.mcp_discovery_min_interval_seconds)),
            "default_cadence_seconds": int(settings.mcp_discovery_default_cadence_seconds),
            "max_concurrency": max(1, int(settings.mcp_discovery_max_concurrency)),
            "endpoint_timeout_seconds": int(settings.mcp_discovery_endpoint_timeout_seconds),
            "run_retention_days": retention_days,
        },
        "last_run": runs[0] if runs else None,
        "runs": runs,
        "totals": totals,
    }


def sweep_run_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    """One run row as the endpoint reports it.

    Args:
        row: A row from :meth:`Database.list_mcp_discovery_sweep_runs`.

    Returns:
        The run with ISO timestamps, integer counters (absent aggregates read as 0) and
        millisecond durations (``None`` when unknown).
    """
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
        "duration_ms": _int_or_none(row.get("duration_ms")),
        "max_concurrency": _int_or_none(row.get("max_concurrency")),
        "endpoint_timeout_seconds": _int_or_none(row.get("endpoint_timeout_seconds")),
        "due": _int(row.get("due_count")),
        "dispatched": _int(row.get("dispatched_count")),
        "coalesced": _int(row.get("deduplicated_count")),
        "enqueue_failed": _int(row.get("enqueue_failed_count")),
        "checked": _int(row.get("jobs")),
        "changed": _int(row.get("changed")),
        "unchanged": _int(row.get("unchanged")),
        "failed": _int(row.get("failed")),
        "in_flight": _int(row.get("in_flight")),
        "avg_job_ms": _int_or_none(row.get("avg_job_ms")),
        "max_job_ms": _int_or_none(row.get("max_job_ms")),
    }


def _iso(value: Any) -> Optional[str]:
    """An ISO-8601 string for a timestamp, or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _int(value: Any) -> int:
    """An integer counter; a missing aggregate is 0."""
    return int(value) if value is not None else 0


def _int_or_none(value: Any) -> Optional[int]:
    """An integer, or ``None`` when the value is unknown."""
    return int(value) if value is not None else None


__all__: List[str] = [
    "DEFAULT_RUN_LIMIT",
    "MAX_RUN_LIMIT",
    "sweep_run_view",
    "sweep_status_payload",
]
