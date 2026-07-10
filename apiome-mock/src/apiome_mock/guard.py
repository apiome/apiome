"""Rate-limit and quota enforcement for mock data-plane requests (#4420, SIM-1.5)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from fastapi import Request, WebSocket
from fastapi.responses import Response
from psycopg_pool import AsyncConnectionPool

from apiome_mock.audit import schedule_mock_access_audit
from apiome_mock.problems import too_many_requests
from apiome_mock.rate_limit import TokenBucketRateLimiter
from apiome_mock.settings import Settings, get_settings
from apiome_mock.tenant_limits import (
    TenantLimits,
    bump_monthly_usage_cache,
    resolve_monthly_usage,
    resolve_tenant_limits,
)
from apiome_mock.usage import schedule_mock_usage

_limiter = TokenBucketRateLimiter()


class _ClientHostSource(Protocol):
    @property
    def client(self) -> object | None: ...


def _client_ip(source: Request | WebSocket | _ClientHostSource) -> str:
    client = source.client
    return client.host if client and client.host else "unknown"


def _rate_limit_key(tenant_slug: str, client_ip: str) -> str:
    return f"{tenant_slug}:{client_ip}"


async def _check_mock_limits(
    *,
    client_ip: str,
    tenant: str,
    project: str,
    version: str,
    pool: AsyncConnectionPool,
    settings: Settings,
) -> Response | None:
    if not settings.rate_limit_enabled:
        return None

    limits = await resolve_tenant_limits(pool, tenant_slug=tenant, settings=settings)
    if limits is None:
        return None

    monthly_count = await resolve_monthly_usage(pool, tenant_id=limits.tenant_id, settings=settings)
    if limits.mock_requests_per_month > 0 and monthly_count >= limits.mock_requests_per_month:
        return too_many_requests(
            "Monthly mock request quota exceeded for this tenant.",
            instance=f"/{tenant}/{project}/{version}",
            retry_after=_seconds_until_next_utc_month(),
            limit_type="monthly",
        )

    allowed, retry_after = _limiter.check(
        _rate_limit_key(tenant, client_ip),
        limits.mock_rps,
        time.monotonic(),
    )
    if not allowed:
        return too_many_requests(
            "Mock request rate limit exceeded.",
            instance=f"/{tenant}/{project}/{version}",
            retry_after=retry_after,
            limit_type="rps",
        )

    return None


async def enforce_mock_limits(
    request: Request | WebSocket,
    *,
    tenant: str,
    project: str,
    version: str,
    pool: AsyncConnectionPool,
    settings: Settings | None = None,
    transport: str = "http",
) -> Response | None:
    """Return a 429 problem response when limits are exceeded, else ``None``."""
    cfg = settings or get_settings()
    return await _check_mock_limits(
        client_ip=_client_ip(request),
        tenant=tenant,
        project=project,
        version=version,
        pool=pool,
        settings=cfg,
    )


async def enforce_mock_limits_for_context(
    *,
    client_host: str,
    tenant: str,
    project: str,
    version: str,
    pool: AsyncConnectionPool,
    settings: Settings | None = None,
    transport: str = "grpc",
) -> Response | None:
    """Return a 429 problem response for non-HTTP transports when limits are exceeded."""
    cfg = settings or get_settings()
    return await _check_mock_limits(
        client_ip=client_host,
        tenant=tenant,
        project=project,
        version=version,
        pool=pool,
        settings=cfg,
    )


def _seconds_until_next_utc_month() -> int:
    """Return seconds until 00:00:00 UTC on the first day of next month."""
    now = datetime.now(tz=timezone.utc)
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return max(1, int((next_month_start - now).total_seconds()))


def record_mock_transport_event(
    *,
    pool: AsyncConnectionPool,
    tenant: str,
    project: str,
    version: str,
    transport: str,
    channel: str,
    direction: str,
    tenant_id: UUID | None = None,
    api_key_id: UUID | None = None,
    settings: Settings | None = None,
) -> None:
    """Fire-and-forget usage rollup and sampled audit for a multi-protocol mock event."""
    cfg = settings or get_settings()
    if tenant_id is None:
        return

    schedule_mock_usage(
        pool,
        tenant_id=tenant_id,
        project_slug=project,
        version_label=version,
    )
    bump_monthly_usage_cache(tenant_id)

    schedule_mock_access_audit(
        pool,
        tenant_id=tenant_id,
        client_ip="transport",
        project_slug=project,
        version_label=version,
        method=transport.upper(),
        path=f"{channel}:{direction}",
        status_code=200,
        sample_rate=cfg.audit_sample_rate,
        api_key_id=api_key_id,
    )


def record_mock_request(
    *,
    pool: AsyncConnectionPool,
    request: Request,
    tenant: str,
    project: str,
    version: str,
    path: str,
    status_code: int,
    tenant_id: UUID | None = None,
    api_key_id: UUID | None = None,
    settings: Settings | None = None,
) -> None:
    """Fire-and-forget usage rollup and sampled audit for a served mock request."""
    cfg = settings or get_settings()
    if tenant_id is None:
        return

    schedule_mock_usage(
        pool,
        tenant_id=tenant_id,
        project_slug=project,
        version_label=version,
    )
    bump_monthly_usage_cache(tenant_id)

    schedule_mock_access_audit(
        pool,
        tenant_id=tenant_id,
        client_ip=_client_ip(request),
        project_slug=project,
        version_label=version,
        method=request.method,
        path="/" + path.strip("/") if path.strip("/") else "/",
        status_code=status_code,
        sample_rate=cfg.audit_sample_rate,
        api_key_id=api_key_id,
    )


async def resolve_limits_for_tenant(
    pool: AsyncConnectionPool,
    tenant_slug: str,
    *,
    settings: Settings | None = None,
) -> TenantLimits | None:
    cfg = settings or get_settings()
    return await resolve_tenant_limits(pool, tenant_slug=tenant_slug, settings=cfg)
