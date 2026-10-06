"""AGX-3.2 quotas & rate limits — per-agent-key RPS and daily call caps (#4538).

An agent with no limits can retry in a tight loop and flood an upstream, and the tenant's bill,
within seconds. Every agent key therefore gets two limits, both set by the tenant's license tier
(``licenses.seats``, V272):

* ``agent_key_rps``: the sustained ``tools/call`` rate. It is a token bucket per key whose burst is
  one second's worth of calls (at least one), the same shape as the mock data plane's ``mock_rps``
  (apiome-mock ``rate_limit.TokenBucketRateLimiter``);
* ``agent_key_daily_calls``: calls per key per UTC day.

Free 2 rps / 1,000 a day, Paid 20 / 100,000, Sponsor 100 / 1,000,000. Zero or a negative value means
unlimited. The SQL function ``apiome.agent_key_quota(tenant)`` resolves both caps, so apiome-rest's
key management API reports the same caps that this module enforces.

**One count of calls made.** The daily counter is ``apiome.agent_key_call_count(key, day)``: the
key's AGX-3.3 ``agent_invocations`` rows that day, without ``quota_rejected`` refusals. The AGX-3.3
rollups read the same rows, so the counter always equals the day's rollup
``calls - quota_rejections``. Reading the table on every call would be too slow, so
:class:`AgentQuotaGuard` refreshes it every ``usage_cache_seconds`` and adds the calls it admitted
since then. Two limits follow from that:

* with several MCP instances, each instance learns about calls admitted elsewhere only on its next
  refresh, so a key can briefly go over its daily cap by roughly (instances - 1) x rps x refresh
  interval;
* the RPS bucket is per process, as on the mock data plane, so N instances allow up to N x rps.

**Tier changes apply within** ``limits_cache_seconds`` (default 60 s): the caps are cached per
tenant for that long.

**Refusals are MCP results with a retry hint.** :class:`AgentQuotaMiddleware` refuses a call over
either limit before the tool runs. The refusal is a ``tools/call`` result with ``isError: true``
(:class:`QuotaRefusalResult`):

* text that starts with the reason code and says when to retry, so an agent that reads only text
  still backs off;
* ``structuredContent`` with the 429-style details: ``reason``, ``limit`` (``rps`` or
  ``daily_calls``), ``cap``, ``used``, ``retryAfterSeconds``, ``retryAt`` and ``httpStatus: 429``.

A result is used, not a raised error, because the MCP SDK turns any error raised during
``tools/call`` into a text-only result and drops its data. Each refusal is recorded as one
``quota_rejected`` invocation (AGX-3.3), so the rollups count refusals as well.

**Mount order.** This middleware runs after :class:`~apiome_mcp.agent_access.AgentAccessMiddleware`
and reads the key that middleware verified (:func:`~apiome_mcp.agent_access.current_agent_access`).
Add it after the access middleware, so it is the inner one. Without a verified key it fails closed.
Like the access middleware, it belongs on the **AGX agent surface only** and never on the catalog
server.

**Database trouble does not stop calls.** If the caps cannot be read, the last known caps are used,
or the Free caps when none are known. If the counter cannot be refreshed, the last count is kept.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any

import mcp.types as mt
import structlog
from fastmcp import Context
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.agent_access import (
    AgentAccessDeniedError,
    AgentAccessReason,
    AgentKey,
    current_agent_access,
)
from apiome_mcp.agent_invocations import InvocationOutcome, Target, audit_invocation
from apiome_mcp.database_pool import get_db_pool

if TYPE_CHECKING:
    from apiome_mcp.settings import Settings

_log = structlog.get_logger(__name__)

__all__ = [
    "AGENT_QUOTA_EXCEEDED_CODE",
    "FREE_AGENT_KEY_DAILY_CALLS",
    "FREE_AGENT_KEY_RPS",
    "AgentQuotaGuard",
    "AgentQuotaLimits",
    "AgentQuotaMiddleware",
    "QuotaLimit",
    "QuotaReason",
    "QuotaRefusal",
    "QuotaRefusalResult",
    "TokenBuckets",
    "count_agent_key_calls",
    "load_agent_quota_limits",
    "record_quota_rejection",
    "seconds_until_next_utc_day",
]

#: Error code reported in a refusal's ``structuredContent``, next to the AGX-3.1 codes (-32010 key
#: rejected, -32011 toolset unavailable). It is in the implementation-defined server-error range and
#: is not used by the MCP SDKs.
AGENT_QUOTA_EXCEEDED_CODE = -32012

#: Free-tier caps (V272). Used when a tenant's caps cannot be read and none are cached.
FREE_AGENT_KEY_RPS = 2.0
FREE_AGENT_KEY_DAILY_CALLS = 1000

#: The HTTP status a refusal corresponds to (``Too Many Requests``).
_HTTP_TOO_MANY_REQUESTS = 429

#: Buckets idle this long are dropped, and at most this many are kept.
_BUCKET_TTL_SECONDS = 300.0
_MAX_BUCKETS = 50_000


class QuotaLimit(str, Enum):
    """Which limit refused a call (``structuredContent.limit``)."""

    RPS = "rps"
    DAILY_CALLS = "daily_calls"


class QuotaReason(str, Enum):
    """Why a call was refused: the result's text prefix and the invocation's ``error_code``."""

    RATE_LIMITED = "agent_rate_limited"
    DAILY_CAP_REACHED = "agent_daily_cap_reached"


_REASON_BY_LIMIT = {
    QuotaLimit.RPS: QuotaReason.RATE_LIMITED,
    QuotaLimit.DAILY_CALLS: QuotaReason.DAILY_CAP_REACHED,
}


@dataclass(frozen=True)
class AgentQuotaLimits:
    """A tenant's agent key caps (``apiome.agent_key_quota``).

    Attributes:
        rps: Sustained calls per second per key; ``None`` = unlimited.
        daily_calls: Calls per key per UTC day; ``None`` = unlimited.
        license_type: The tier they came from, or ``None`` when the tenant has no license.
    """

    rps: float | None
    daily_calls: int | None
    license_type: str | None = None


#: The Free caps, for a tenant whose caps cannot be read.
_FREE_LIMITS = AgentQuotaLimits(rps=FREE_AGENT_KEY_RPS, daily_calls=FREE_AGENT_KEY_DAILY_CALLS, license_type=None)


@dataclass(frozen=True)
class QuotaRefusal:
    """A refused call, with the hint an agent needs to back off.

    Attributes:
        limit: Which limit was hit.
        cap: That limit's value (calls per second, or calls per day).
        used: Calls already counted against the cap. For the RPS limit it is the burst size
            (``max(1, rps)`` rounded down): the bucket is empty.
        retry_after_seconds: Whole seconds to wait, like an HTTP ``Retry-After`` (at least 1).
        retry_at: When retrying can succeed (``now + retry_after_seconds``), UTC.
    """

    limit: QuotaLimit
    cap: float | int
    used: int
    retry_after_seconds: int
    retry_at: datetime

    @property
    def reason(self) -> QuotaReason:
        """The refusal's reason code."""
        return _REASON_BY_LIMIT[self.limit]

    def message(self) -> str:
        """The refusal as text that starts with the reason code and says when to retry."""
        when = f"retry after {self.retry_after_seconds} s ({_iso(self.retry_at)})"
        if self.limit is QuotaLimit.RPS:
            return f"{self.reason.value}: this agent key is limited to {_number(self.cap)} calls per second; {when}."
        return f"{self.reason.value}: this agent key has used its {_number(self.cap)} calls for today (UTC); {when}."

    def payload(self) -> dict[str, Any]:
        """The refusal as ``structuredContent``. Never contains the key, tenant or toolset."""
        return {
            "error": {"code": AGENT_QUOTA_EXCEEDED_CODE, "reason": self.reason.value, "message": self.message()},
            "reason": self.reason.value,
            "limit": self.limit.value,
            "cap": self.cap,
            "used": self.used,
            "retryAfterSeconds": self.retry_after_seconds,
            "retryAt": _iso(self.retry_at),
            "httpStatus": _HTTP_TOO_MANY_REQUESTS,
        }


def _iso(value: datetime) -> str:
    """``value`` as an ISO-8601 UTC timestamp with a ``Z`` suffix, to the second."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _number(value: float | int) -> str:
    """``value`` without a trailing ``.0`` (``2.0`` -> ``2``, ``0.5`` -> ``0.5``)."""
    return f"{value:g}"


class QuotaRefusalResult(ToolResult):
    """A refused ``tools/call``: ``isError: true`` with the retry hint as ``structuredContent``.

    FastMCP's own :class:`~fastmcp.tools.base.ToolResult` cannot set ``isError``, so this subclass
    returns a ready :class:`mcp.types.CallToolResult`. The low-level MCP server sends that result
    as it is, without output-schema validation, which a refusal would fail.
    """

    def __init__(self, refusal: QuotaRefusal) -> None:
        """Build the result for ``refusal``."""
        super().__init__(
            content=[mt.TextContent(type="text", text=refusal.message())],
            structured_content=refusal.payload(),
        )

    def to_mcp_result(self) -> mt.CallToolResult:
        """Return the refusal as an error ``CallToolResult``."""
        return mt.CallToolResult(content=self.content, structuredContent=self.structured_content, isError=True)


def seconds_until_next_utc_day(now: datetime) -> int:
    """Whole seconds from ``now`` until the next UTC midnight, at least 1."""
    utc = now.astimezone(UTC)
    midnight = datetime(utc.year, utc.month, utc.day, tzinfo=UTC) + timedelta(days=1)
    return max(1, math.ceil((midnight - utc).total_seconds()))


# --------------------------------------------------------------------------------------------------
# Database reads (V272 functions)
# --------------------------------------------------------------------------------------------------
_AGENT_KEY_QUOTA = "SELECT license_type, rps, daily_calls FROM apiome.agent_key_quota(%s::uuid)"

_AGENT_KEY_CALL_COUNT = "SELECT apiome.agent_key_call_count(%s::uuid, %s::date) AS calls"


def _positive_float(raw: Any) -> float | None:
    """A stored cap as a positive float, or ``None`` (unlimited) when it is missing or not positive."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float, Decimal)):
        return None
    value = float(raw)
    return value if value > 0 else None


async def load_agent_quota_limits(pool: AsyncConnectionPool, tenant_id: str) -> AgentQuotaLimits:
    """Read a tenant's caps through ``apiome.agent_key_quota``.

    Args:
        pool: The shared Postgres pool.
        tenant_id: The key's tenant.

    Returns:
        The caps (``None`` fields are unlimited). The function always returns one row; an empty
        result falls back to the Free caps.

    Raises:
        Exception: Database errors propagate; :class:`AgentQuotaGuard` catches them.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_AGENT_KEY_QUOTA, (tenant_id,))
            row = await cur.fetchone()
    if row is None:
        return _FREE_LIMITS
    rps = _positive_float(row.get("rps"))
    daily = _positive_float(row.get("daily_calls"))
    license_type = row.get("license_type")
    return AgentQuotaLimits(
        rps=rps,
        daily_calls=int(daily) if daily is not None else None,
        license_type=str(license_type) if license_type is not None else None,
    )


async def count_agent_key_calls(pool: AsyncConnectionPool, key_id: str, day: date) -> int:
    """Count the calls a key made on a UTC day, through ``apiome.agent_key_call_count``.

    Args:
        pool: The shared Postgres pool.
        key_id: The agent key.
        day: The UTC day.

    Returns:
        The key's ``agent_invocations`` that day, without ``quota_rejected`` refusals.

    Raises:
        Exception: Database errors propagate; :class:`AgentQuotaGuard` catches them.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_AGENT_KEY_CALL_COUNT, (key_id, day.isoformat()))
            row = await cur.fetchone()
    return int(row.get("calls") or 0) if row else 0


# --------------------------------------------------------------------------------------------------
# RPS: token buckets
# --------------------------------------------------------------------------------------------------
@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    """Thread-safe in-process token buckets, one per key.

    The same shape as apiome-mock's ``TokenBucketRateLimiter``: ``rate`` tokens per second, a burst
    of ``max(1, rate)``, one token per call. Buckets idle for 5 minutes are dropped, and at most
    50,000 are kept (the least recently used go first).
    """

    def __init__(self) -> None:
        """Start with no buckets."""
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._checks = 0

    def take(self, key: str, rate: float, now: float) -> int:
        """Take one token for ``key`` if one is available.

        Args:
            key: The bucket (an agent key id).
            rate: Tokens per second; must be positive.
            now: A monotonic clock reading, in seconds.

        Returns:
            ``0`` when a token was taken (the call may go ahead), else the whole seconds until one
            will be available (at least 1).
        """
        capacity = max(1.0, rate)
        with self._lock:
            self._checks += 1
            if self._checks >= 1000:
                self._checks = 0
                self._evict(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = self._buckets[key] = _Bucket(tokens=capacity, updated=now)
            bucket.tokens = min(capacity, bucket.tokens + max(0.0, now - bucket.updated) * rate)
            bucket.updated = now
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return 0
            return max(1, math.ceil((1.0 - bucket.tokens) / rate))

    def _evict(self, now: float) -> None:
        """Drop idle buckets, then the oldest beyond the cap. Called with the lock held."""
        for key in [k for k, b in self._buckets.items() if b.updated < now - _BUCKET_TTL_SECONDS]:
            del self._buckets[key]
        if len(self._buckets) > _MAX_BUCKETS:
            oldest = sorted(self._buckets, key=lambda k: self._buckets[k].updated)
            for key in oldest[: len(self._buckets) - _MAX_BUCKETS]:
                del self._buckets[key]


# --------------------------------------------------------------------------------------------------
# The guard: caps + counters for one process
# --------------------------------------------------------------------------------------------------
@dataclass
class _CachedLimits:
    limits: AgentQuotaLimits
    expires: float


@dataclass
class _DailyUsage:
    """One key's calls today, as far as this process knows.

    ``counted`` is the database count at the last refresh and ``admitted`` the calls this process
    admitted since then. ``admitted_today`` is every call this process admitted today; it keeps the
    cap working before the AGX-2.1 call path records invocations, and while recording lags.
    """

    day: date
    counted: int
    admitted: int
    admitted_today: int
    refresh_at: float

    @property
    def used(self) -> int:
        return max(self.counted + self.admitted, self.admitted_today)


#: Reads a tenant's caps; replaceable in tests.
LimitsLoader = Callable[[AsyncConnectionPool, str], Awaitable[AgentQuotaLimits]]

#: Counts a key's calls on a day; replaceable in tests.
CallCounter = Callable[[AsyncConnectionPool, str, date], Awaitable[int]]


class AgentQuotaGuard:
    """Decides, per call, whether an agent key is within its RPS limit and daily cap.

    One guard per process holds the token buckets and the caches. :meth:`admit` either counts the
    call and returns ``None``, or returns the :class:`QuotaRefusal` (and counts nothing).
    """

    def __init__(
        self,
        *,
        limits_cache_seconds: float = 60.0,
        usage_cache_seconds: float = 5.0,
        load_limits: LimitsLoader = load_agent_quota_limits,
        count_calls: CallCounter = count_agent_key_calls,
    ) -> None:
        """Configure the caches and data sources.

        Args:
            limits_cache_seconds: How long a tenant's caps are cached; a tier change applies within
                this time (``APIOME_MCP_AGENT_QUOTA_LIMITS_CACHE_SECONDS``).
            usage_cache_seconds: How often a key's daily count is re-read from
                ``agent_invocations`` (``APIOME_MCP_AGENT_QUOTA_USAGE_CACHE_SECONDS``).
            load_limits: Reads a tenant's caps (default :func:`load_agent_quota_limits`).
            count_calls: Counts a key's calls on a day (default :func:`count_agent_key_calls`).
        """
        self._limits_ttl = max(0.0, limits_cache_seconds)
        self._usage_ttl = max(0.0, usage_cache_seconds)
        self._load_limits = load_limits
        self._count_calls = count_calls
        self._limits: dict[str, _CachedLimits] = {}
        self._usage: dict[str, _DailyUsage] = {}
        self._buckets = TokenBuckets()

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentQuotaGuard:
        """Build a guard with the cache lifetimes from ``settings``.

        Args:
            settings: The process settings (``agent_quota_limits_cache_seconds``,
                ``agent_quota_usage_cache_seconds``).

        Returns:
            A new guard reading from the database.
        """
        return cls(
            limits_cache_seconds=settings.agent_quota_limits_cache_seconds,
            usage_cache_seconds=settings.agent_quota_usage_cache_seconds,
        )

    async def limits_for(self, pool: AsyncConnectionPool, tenant_id: str, now: float) -> AgentQuotaLimits:
        """Return a tenant's caps, cached for ``limits_cache_seconds``.

        Args:
            pool: The shared Postgres pool.
            tenant_id: The tenant.
            now: A monotonic clock reading.

        Returns:
            The caps. On a read failure: the last known caps, else the Free caps.
        """
        cached = self._limits.get(tenant_id)
        if cached is not None and now < cached.expires:
            return cached.limits
        try:
            limits = await self._load_limits(pool, tenant_id)
        except Exception:
            _log.warning("agent_quota_limits_unavailable", tenant_id=tenant_id, exc_info=True)
            limits = cached.limits if cached is not None else _FREE_LIMITS
        self._limits[tenant_id] = _CachedLimits(limits=limits, expires=now + self._limits_ttl)
        return limits

    async def _usage_for(self, pool: AsyncConnectionPool, key_id: str, today: date, now: float) -> _DailyUsage:
        """Return a key's usage today, re-reading the database count when it is due."""
        usage = self._usage.get(key_id)
        if usage is None or usage.day != today:
            usage = _DailyUsage(day=today, counted=0, admitted=0, admitted_today=0, refresh_at=0.0)
            self._usage[key_id] = usage
        if now >= usage.refresh_at:
            try:
                usage.counted = int(await self._count_calls(pool, key_id, today))
                usage.admitted = 0
            except Exception:
                _log.warning("agent_quota_usage_unavailable", key_id=key_id, exc_info=True)
            usage.refresh_at = now + self._usage_ttl
        return usage

    async def admit(
        self,
        pool: AsyncConnectionPool,
        key: AgentKey,
        *,
        wall_clock: datetime | None = None,
        monotonic: float | None = None,
    ) -> QuotaRefusal | None:
        """Admit one call by ``key``, or say why not.

        The daily cap is checked first, so a key that is out of calls for the day does not use up
        RPS tokens. A refused call is not counted against either limit.

        Args:
            pool: The shared Postgres pool.
            key: The verified agent key.
            wall_clock: The current time (tests); defaults to now, UTC.
            monotonic: A monotonic clock reading (tests); defaults to :func:`time.monotonic`.

        Returns:
            ``None`` when the call may go ahead (it is counted), else the refusal.
        """
        now_wall = wall_clock if wall_clock is not None else datetime.now(UTC)
        now = monotonic if monotonic is not None else time.monotonic()
        limits = await self.limits_for(pool, key.tenant_id, now)
        today = now_wall.astimezone(UTC).date()

        usage: _DailyUsage | None = None
        if limits.daily_calls is not None:
            usage = await self._usage_for(pool, key.key_id, today, now)
            if usage.used >= limits.daily_calls:
                wait = seconds_until_next_utc_day(now_wall)
                return QuotaRefusal(
                    limit=QuotaLimit.DAILY_CALLS,
                    cap=limits.daily_calls,
                    used=usage.used,
                    retry_after_seconds=wait,
                    retry_at=now_wall + timedelta(seconds=wait),
                )

        if limits.rps is not None:
            wait = self._buckets.take(key.key_id, limits.rps, now)
            if wait:
                return QuotaRefusal(
                    limit=QuotaLimit.RPS,
                    cap=limits.rps,
                    used=math.floor(max(1.0, limits.rps)),
                    retry_after_seconds=wait,
                    retry_at=now_wall + timedelta(seconds=wait),
                )

        if usage is not None:
            usage.admitted += 1
            usage.admitted_today += 1
        return None


# --------------------------------------------------------------------------------------------------
# Recording refusals (AGX-3.3)
# --------------------------------------------------------------------------------------------------
_TOOLSET_TARGET = "SELECT target FROM apiome.agent_toolsets WHERE id = %s::uuid AND tenant_id = %s::uuid"


async def _toolset_target(pool: AsyncConnectionPool, key: AgentKey) -> Target:
    """The key's toolset target (``prod`` when unknown or unreadable)."""
    try:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_TOOLSET_TARGET, (key.toolset_id, key.tenant_id))
                row = await cur.fetchone()
    except Exception:
        _log.warning("agent_quota_target_unavailable", key_id=key.key_id, exc_info=True)
        return "prod"
    return "mock" if row and row.get("target") == "mock" else "prod"


async def record_quota_rejection(
    pool: AsyncConnectionPool, key: AgentKey, tool_name: str, refusal: QuotaRefusal, *, request_bytes: int = 0
) -> None:
    """Write the ``quota_rejected`` invocation row for a refused call (never raises).

    Args:
        pool: The shared Postgres pool.
        key: The key whose call was refused.
        tool_name: The tool it called.
        refusal: Why it was refused; its reason is the row's ``error_code``.
        request_bytes: UTF-8 size of the call's arguments.
    """
    target = await _toolset_target(pool, key)
    async with audit_invocation(pool, key, tool_name=tool_name, target=target, request_bytes=request_bytes) as audit:
        audit.failed(InvocationOutcome.QUOTA_REJECTED, refusal.reason.value)


# --------------------------------------------------------------------------------------------------
# The middleware
# --------------------------------------------------------------------------------------------------
#: Returns the request's Postgres pool; replaceable in tests.
PoolSource = Callable[[Context], AsyncConnectionPool]


def _request_bytes(arguments: Any) -> int:
    """UTF-8 size of the call's arguments as JSON (0 when there are none)."""
    if not arguments:
        return 0
    try:
        return len(json.dumps(arguments, separators=(",", ":"), default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


class AgentQuotaMiddleware(Middleware):
    """Refuse agent ``tools/call`` requests over the key's RPS limit or daily cap.

    For the **AGX agent surface only**. Add it after
    :class:`~apiome_mcp.agent_access.AgentAccessMiddleware` (see the module docstring).
    """

    def __init__(self, *, guard: AgentQuotaGuard | None = None, pool_source: PoolSource = get_db_pool) -> None:
        """Configure the guard and the pool.

        Args:
            guard: The process's quota state. Build it once with
                :meth:`AgentQuotaGuard.from_settings`; the default is a guard with the default cache
                lifetimes.
            pool_source: Returns the request's Postgres pool (default: the lifespan pool).
        """
        self._guard = guard or AgentQuotaGuard()
        self._pool_source = pool_source

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        """Admit the call, or return a :class:`QuotaRefusalResult` and record the refusal."""
        access = current_agent_access()
        if access is None or context.fastmcp_context is None:
            raise AgentAccessDeniedError(AgentAccessReason.KEY_MISSING)
        pool = self._pool_source(context.fastmcp_context)
        refusal = await self._guard.admit(pool, access.key)
        if refusal is None:
            return await call_next(context)
        name = context.message.name
        _log.info(
            "agent_quota_rejected",
            reason=refusal.reason.value,
            tool=name,
            key_id=access.key.key_id,
            tenant_id=access.key.tenant_id,
            retry_after_seconds=refusal.retry_after_seconds,
        )
        await record_quota_rejection(
            pool, access.key, name, refusal, request_bytes=_request_bytes(context.message.arguments)
        )
        return QuotaRefusalResult(refusal)
