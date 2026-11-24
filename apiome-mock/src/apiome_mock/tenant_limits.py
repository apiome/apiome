"""Resolve mock rate/quota limits from the tenant license tier (#4420, SIM-1.5).

Both lookups are cached in process with **single flight** (#7207, DBP-1.24): when a cache entry
expires under load, one request reloads it and the rest wait for that load instead of each taking a
pooled connection. An unknown tenant slug is cached too (a negative entry), so a stream of 404s for
a tenant that does not exist costs one query per TTL, not one per request.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.settings import Settings
from apiome_mock.ttl_cache import TtlCache

_RESOLVE_TENANT_LIMITS = """
    SELECT
      t.id AS tenant_id,
      COALESCE(
        (
          SELECT l.seats
          FROM apiome.tenant_administrators ta
          INNER JOIN apiome.user_entitlements ue ON ue.user_id = ta.user_id
          INNER JOIN apiome.licenses l ON l.id = ue.license_id AND l.enabled IS TRUE
          WHERE ta.tenant_id = t.id
          ORDER BY
            CASE l.license_type
              WHEN 'sponsor' THEN 3
              WHEN 'paid' THEN 2
              WHEN 'free' THEN 1
              ELSE 0
            END DESC,
            l.created_at ASC
          LIMIT 1
        ),
        (
          SELECT l.seats
          FROM apiome.licenses l
          WHERE l.license_type = 'free' AND l.enabled IS TRUE
          ORDER BY l.created_at ASC
          LIMIT 1
        ),
        '{}'::jsonb
      ) AS seats
    FROM apiome.tenants t
    WHERE t.slug = %(tenant)s
      AND t.deleted_at IS NULL
      AND t.enabled IS TRUE
    LIMIT 1
"""

_MONTHLY_USAGE = """
    SELECT COALESCE(SUM(request_count), 0)::bigint AS monthly_count
    FROM apiome.mock_usage
    WHERE tenant_id = %(tenant_id)s
      AND usage_date >= date_trunc('month', (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))::date
      AND usage_date < (
        date_trunc('month', (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')) + interval '1 month'
      )::date
"""


@dataclass(frozen=True)
class TenantLimits:
    tenant_id: UUID
    mock_rps: float
    mock_requests_per_month: int


@dataclass
class _MonthlyCount:
    """A cached monthly total, bumped in place as requests are served."""

    count: int


_limits_cache: TtlCache[TenantLimits] = TtlCache(ttl_seconds=60.0)
_monthly_cache: TtlCache[_MonthlyCount] = TtlCache(ttl_seconds=30.0)


def _int_from_seats(seats: object, key: str, default: int) -> int:
    if not isinstance(seats, dict):
        return default
    raw = seats.get(key)
    if isinstance(raw, bool) or raw is None:
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def _float_from_seats(seats: object, key: str, default: float) -> float:
    if not isinstance(seats, dict):
        return default
    raw = seats.get(key)
    if isinstance(raw, bool) or raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return default


def limits_from_seats(
    *,
    tenant_id: UUID,
    seats: object,
    settings: Settings,
) -> TenantLimits:
    return TenantLimits(
        tenant_id=tenant_id,
        mock_rps=_float_from_seats(seats, "mock_rps", settings.default_mock_rps),
        mock_requests_per_month=_int_from_seats(
            seats,
            "mock_requests_per_month",
            settings.default_mock_requests_per_month,
        ),
    )


async def resolve_tenant_limits(
    pool: AsyncConnectionPool,
    *,
    tenant_slug: str,
    settings: Settings,
) -> TenantLimits | None:
    """Return license-tier mock limits for ``tenant_slug``, or ``None`` when unknown.

    Args:
        pool: Database pool used on a cache miss.
        tenant_slug: Tenant slug from the URL.
        settings: Mock settings (defaults and ``limits_cache_ttl_seconds``).

    Returns:
        The tenant's limits; ``None`` (also cached) when no enabled tenant has the slug.
    """
    _limits_cache.ttl_seconds = settings.limits_cache_ttl_seconds
    _limits_cache.negative_ttl_seconds = settings.limits_cache_ttl_seconds

    async def _load() -> TenantLimits | None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_RESOLVE_TENANT_LIMITS, {"tenant": tenant_slug})
                row = await cur.fetchone()
        if row is None:
            return None
        return limits_from_seats(tenant_id=row["tenant_id"], seats=row.get("seats"), settings=settings)

    return await _limits_cache.get_or_load(tenant_slug, _load)


async def resolve_monthly_usage(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    settings: Settings,
) -> int:
    """Return the tenant's mock request count for the current UTC calendar month.

    Args:
        pool: Database pool used on a cache miss.
        tenant_id: Tenant id.
        settings: Mock settings (``monthly_usage_cache_ttl_seconds``).

    Returns:
        The stored monthly total plus the requests this process served since it was read.
    """
    _monthly_cache.ttl_seconds = settings.monthly_usage_cache_ttl_seconds

    async def _load() -> _MonthlyCount:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_MONTHLY_USAGE, {"tenant_id": tenant_id})
                row = await cur.fetchone()
        return _MonthlyCount(count=int(row["monthly_count"]) if row else 0)

    cached = await _monthly_cache.get_or_load(str(tenant_id), _load)
    return cached.count if cached is not None else 0


def bump_monthly_usage_cache(tenant_id: UUID, *, delta: int = 1) -> None:
    """Optimistically bump the in-process monthly counter after a served request."""
    hit, cached = _monthly_cache.peek(str(tenant_id))
    if not hit or cached is None:
        return
    cached.count = max(0, cached.count + delta)


def clear_limits_caches_for_tests() -> None:
    """Reset process-wide caches (tests only)."""
    _limits_cache.clear()
    _monthly_cache.clear()
