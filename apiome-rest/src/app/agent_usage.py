"""Agent usage rollups — AGX-3.4 (#4540).

A tenant's agent usage over a window of UTC days, read from the AGX-3.3 rollup table
``agent_invocation_daily`` (V271) and shaped for the Control Panel's usage charts: calls and
errors per day, per tool and per agent key, with latency.

**Rollups only.** Raw ``agent_invocations`` rows are never scanned. Today's partial day is
included: the apiome-mcp usage sweep refreshes the current day's rollup on every tick.

**Latency across groups is approximate by construction.** A rollup row carries percentiles for
one (day, key, toolset, tool, target) group, and percentiles cannot be merged exactly. Each
aggregate reports the calls-weighted mean (``latency_sum_ms / calls``, exact) and the worst p95
among the groups it covers (``latencyP95MaxMs``, an upper bound on the true p95).

**Error counts** are ``calls - success_calls``: upstream errors, validation failures, quota
rejections and internal errors together. The totals break them down.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .database import db

__all__ = [
    "AGENT_USAGE_SCHEMA_VERSION",
    "DEFAULT_DAYS",
    "MAX_DAYS",
    "AgentUsageAgent",
    "AgentUsageDay",
    "AgentUsageOut",
    "AgentUsageTool",
    "AgentUsageTotals",
    "build_agent_usage",
    "get_agent_usage",
    "usage_window",
]

#: The addressable shape of the usage projection.
AGENT_USAGE_SCHEMA_VERSION = "agx.agent-usage.v1"

#: Window used when the caller names none.
DEFAULT_DAYS = 30

#: Longest window accepted: one year plus a day, matching the longest rollup retention a tier
#: can be configured with without reaching for "forever".
MAX_DAYS = 366

#: Outcome columns of a rollup row that count as errors, in the order the totals report them.
_ERROR_COLUMNS = ("upstream_errors", "validation_failures", "quota_rejections", "internal_errors")


class _Metrics(BaseModel):
    """Calls, errors and latency for one slice of the window.

    Attributes:
        calls: ``tools/call`` invocations, including refused ones.
        errors: Calls that did not succeed.
        error_rate: ``errors / calls`` in ``[0, 1]``; ``0`` when there were no calls.
        latency_avg_ms: Calls-weighted mean latency; ``None`` when there were no calls.
        latency_p95_max_ms: Worst p95 among the rollup groups covered; ``None`` when there were
            no calls.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    calls: int
    errors: int
    error_rate: float = Field(serialization_alias="errorRate")
    latency_avg_ms: Optional[float] = Field(default=None, serialization_alias="latencyAvgMs")
    latency_p95_max_ms: Optional[int] = Field(default=None, serialization_alias="latencyP95MaxMs")


class AgentUsageDay(_Metrics):
    """One UTC day of the window. Days without calls are present, with zero calls.

    Attributes:
        day: The UTC day.
    """

    day: date


class AgentUsageTool(_Metrics):
    """One MCP tool's usage over the window.

    Attributes:
        tool_name: The MCP tool name.
    """

    tool_name: str = Field(serialization_alias="toolName")


class AgentUsageAgent(_Metrics):
    """One agent key's usage over the window.

    Attributes:
        key_id: The agent key.
        name: Its name, or ``None`` when the key row no longer exists.
        key_prefix: Its lookup prefix, or ``None`` when the key row no longer exists.
        revoked: Whether the key has been revoked since.
    """

    key_id: str = Field(serialization_alias="keyId")
    name: Optional[str] = None
    key_prefix: Optional[str] = Field(default=None, serialization_alias="keyPrefix")
    revoked: bool = False


class AgentUsageTotals(_Metrics):
    """The whole window, with the errors broken down by outcome.

    Attributes:
        success_calls: Calls that succeeded.
        upstream_errors: The upstream API answered with an error.
        validation_failures: Arguments failed the tool's input schema.
        quota_rejections: Refused by a rate limit or daily cap (AGX-3.2).
        internal_errors: Failed inside the MCP runtime.
    """

    success_calls: int = Field(serialization_alias="successCalls")
    upstream_errors: int = Field(serialization_alias="upstreamErrors")
    validation_failures: int = Field(serialization_alias="validationFailures")
    quota_rejections: int = Field(serialization_alias="quotaRejections")
    internal_errors: int = Field(serialization_alias="internalErrors")


class AgentUsageOut(BaseModel):
    """A tenant's agent usage over a window of UTC days.

    Attributes:
        schema_version: The projection's shape.
        start_day: First UTC day of the window (inclusive).
        end_day: Last UTC day of the window (inclusive; today).
        days: Window length in days.
        totals: The whole window.
        daily: One entry per day, oldest first, zero-filled.
        tools: One entry per tool that was called, most calls first.
        agents: One entry per agent key that called, most calls first.
        as_of: When this was computed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(default=AGENT_USAGE_SCHEMA_VERSION, serialization_alias="schemaVersion")
    start_day: date = Field(serialization_alias="startDay")
    end_day: date = Field(serialization_alias="endDay")
    days: int
    totals: AgentUsageTotals
    daily: List[AgentUsageDay]
    tools: List[AgentUsageTool]
    agents: List[AgentUsageAgent]
    as_of: datetime = Field(serialization_alias="asOf")


@dataclass
class _Accumulator:
    """Running sums for one slice; turned into a :class:`_Metrics` payload at the end."""

    calls: int = 0
    success_calls: int = 0
    latency_sum_ms: int = 0
    latency_p95_max_ms: Optional[int] = None
    outcomes: Dict[str, int] = field(default_factory=lambda: {c: 0 for c in _ERROR_COLUMNS})

    def add(self, row: Dict[str, Any]) -> None:
        """Fold one rollup row into the sums.

        Args:
            row: A row from :meth:`Database.list_agent_usage_rollups`.
        """
        calls = int(row.get("calls") or 0)
        self.calls += calls
        self.success_calls += int(row.get("success_calls") or 0)
        self.latency_sum_ms += int(row.get("latency_sum_ms") or 0)
        for column in _ERROR_COLUMNS:
            self.outcomes[column] += int(row.get(column) or 0)
        p95 = row.get("latency_p95_ms")
        if calls > 0 and p95 is not None:
            p95 = int(p95)
            if self.latency_p95_max_ms is None or p95 > self.latency_p95_max_ms:
                self.latency_p95_max_ms = p95

    def metrics(self) -> Dict[str, Any]:
        """Return the fields every :class:`_Metrics` subclass shares.

        Returns:
            ``calls``, ``errors``, ``error_rate``, ``latency_avg_ms``, ``latency_p95_max_ms``.
        """
        errors = max(0, self.calls - self.success_calls)
        has_calls = self.calls > 0
        return {
            "calls": self.calls,
            "errors": errors,
            "error_rate": (errors / self.calls) if has_calls else 0.0,
            "latency_avg_ms": (round(self.latency_sum_ms / self.calls, 1) if has_calls else None),
            "latency_p95_max_ms": self.latency_p95_max_ms if has_calls else None,
        }


def usage_window(days: int, now: datetime) -> tuple[date, date]:
    """Return the first and last UTC day of a window ending today.

    Args:
        days: Window length, at least 1.
        now: The reference instant.

    Returns:
        ``(start_day, end_day)``, both inclusive; ``end_day`` is ``now``'s UTC day.
    """
    end_day = now.astimezone(timezone.utc).date()
    return end_day - timedelta(days=max(1, days) - 1), end_day


def _by_calls(entry: Dict[str, Any], label: str) -> tuple[int, str]:
    """Sort key: most calls first, then by label so ties are stable."""
    return (-int(entry["calls"]), label)


def build_agent_usage(
    rows: Iterable[Dict[str, Any]],
    *,
    start_day: date,
    end_day: date,
    as_of: datetime,
) -> AgentUsageOut:
    """Aggregate rollup rows into the usage projection. Pure: no database access.

    Rows outside ``[start_day, end_day]`` are ignored, so a caller cannot widen the window by
    passing more than it asked for.

    Args:
        rows: Rollup rows (see :meth:`Database.list_agent_usage_rollups`), each with ``day``,
            ``key_id``, ``tool_name``, the outcome counts, ``latency_sum_ms``,
            ``latency_p95_ms`` and, optionally, ``key_name`` / ``key_prefix`` / ``key_revoked``.
        start_day: First day of the window (inclusive).
        end_day: Last day of the window (inclusive).
        as_of: When the projection is computed.

    Returns:
        The projection.
    """
    totals = _Accumulator()
    per_day: Dict[date, _Accumulator] = {}
    per_tool: Dict[str, _Accumulator] = {}
    per_agent: Dict[str, _Accumulator] = {}
    agent_meta: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        day = row.get("day")
        if isinstance(day, datetime):
            day = day.date()
        if not isinstance(day, date) or day < start_day or day > end_day:
            continue
        tool_name = str(row.get("tool_name") or "")
        key_id = str(row.get("key_id") or "")
        totals.add(row)
        per_day.setdefault(day, _Accumulator()).add(row)
        per_tool.setdefault(tool_name, _Accumulator()).add(row)
        per_agent.setdefault(key_id, _Accumulator()).add(row)
        agent_meta.setdefault(
            key_id,
            {
                "name": row.get("key_name"),
                "key_prefix": row.get("key_prefix"),
                "revoked": bool(row.get("key_revoked")),
            },
        )

    window = (end_day - start_day).days + 1
    daily = [
        AgentUsageDay(day=day, **per_day.get(day, _Accumulator()).metrics())
        for day in (start_day + timedelta(days=offset) for offset in range(window))
    ]
    tool_entries = [{"tool_name": name, **acc.metrics()} for name, acc in per_tool.items()]
    tool_entries.sort(key=lambda entry: _by_calls(entry, entry["tool_name"]))
    agent_entries = [{"key_id": key_id, **agent_meta[key_id], **acc.metrics()} for key_id, acc in per_agent.items()]
    agent_entries.sort(key=lambda entry: _by_calls(entry, entry["key_id"]))

    return AgentUsageOut(
        start_day=start_day,
        end_day=end_day,
        days=window,
        totals=AgentUsageTotals(**totals.metrics(), success_calls=totals.success_calls, **totals.outcomes),
        daily=daily,
        tools=[AgentUsageTool(**entry) for entry in tool_entries],
        agents=[AgentUsageAgent(**entry) for entry in agent_entries],
        as_of=as_of,
    )


def get_agent_usage(tenant_id: str, *, days: int = DEFAULT_DAYS, now: Optional[datetime] = None) -> AgentUsageOut:
    """Read and aggregate a tenant's agent usage over the last ``days`` UTC days.

    Args:
        tenant_id: The caller's tenant.
        days: Window length in days, ``1``–:data:`MAX_DAYS` (the route validates the range).
        now: The reference instant; defaults to now.

    Returns:
        The projection. A tenant with no usage gets zero totals, a zero-filled ``daily`` series
        and empty ``tools`` / ``agents``.
    """
    reference = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    start_day, end_day = usage_window(days, reference)
    rows = db.list_agent_usage_rollups(tenant_id, start_day, end_day)
    return build_agent_usage(rows, start_day=start_day, end_day=end_day, as_of=reference)
