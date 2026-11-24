"""Validate tenant REST API keys for private draft mocks (#4446, SIM-2.5).

Only **workspace** keys qualify. An AGX-3.1 agent key (``api_keys.kind = 'agent'``, V269, #4537) is
an MCP credential bound to one toolset and a tool allowlist; it must not open a tenant's private
draft mocks, so the lookup never selects one.

Verified results are cached in process (#7207, DBP-1.24), keyed by ``sha256(key)`` and the tenant
slug — the raw key is never held. A valid key is remembered for
``APIOME_MOCK_API_KEY_CACHE_TTL_SECONDS`` (default 30 s) and a rejected one for
``APIOME_MOCK_API_KEY_NEGATIVE_CACHE_TTL_SECONDS`` (default 10 s); a revoked or expired key stops
opening private mocks within that window. ``bcrypt.checkpw`` runs in a worker thread so a burst of
uncached keys cannot stall the event loop of the single-worker server.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import bcrypt
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.ttl_cache import TtlCache

_API_KEY_LOOKUP = """
    SELECT ak.id, ak.tenant_id, ak.key_hash, ak.expires_at, ak.enabled,
           t.slug AS tenant_slug
    FROM apiome.api_keys ak
    JOIN apiome.tenants t ON ak.tenant_id = t.id
    WHERE ak.key_prefix = %(key_prefix)s
      AND ak.kind = 'workspace'
      AND ak.deleted_at IS NULL
      AND ak.enabled IS TRUE
      AND t.deleted_at IS NULL
      AND t.enabled IS TRUE
      AND (ak.expires_at IS NULL OR ak.expires_at > CURRENT_TIMESTAMP)
"""


@dataclass(frozen=True)
class ValidatedApiKey:
    """A verified tenant API key suitable for private draft mock access."""

    id: UUID
    tenant_id: UUID
    tenant_slug: str


def _key_prefix(api_key: str) -> str | None:
    if not api_key or len(api_key) < 12:
        return None
    return api_key[:12] + "..."


DEFAULT_KEY_CACHE_TTL_SECONDS = 30.0
DEFAULT_KEY_NEGATIVE_CACHE_TTL_SECONDS = 10.0

_KEY_CACHE: TtlCache[ValidatedApiKey] = TtlCache(
    ttl_seconds=DEFAULT_KEY_CACHE_TTL_SECONDS,
    negative_ttl_seconds=DEFAULT_KEY_NEGATIVE_CACHE_TTL_SECONDS,
)


def configure_api_key_cache(*, ttl_seconds: float, negative_ttl_seconds: float) -> None:
    """Set the verified / rejected key TTLs from settings and empty the cache."""
    _KEY_CACHE.ttl_seconds = ttl_seconds
    _KEY_CACHE.negative_ttl_seconds = negative_ttl_seconds
    _KEY_CACHE.clear()


def clear_api_key_cache() -> None:
    """Forget every cached key verdict (tests)."""
    _KEY_CACHE.clear()


def _cache_key(api_key: str, tenant_slug: str) -> tuple[str, str]:
    return (hashlib.sha256(api_key.encode("utf-8")).hexdigest(), tenant_slug)


def _verify_rows(api_key: str, tenant_slug: str, rows: list[dict[str, Any]]) -> ValidatedApiKey | None:
    """Return the first row whose bcrypt hash matches ``api_key`` (CPU-bound; runs in a thread)."""
    api_key_bytes = api_key.encode("utf-8")
    for row in rows:
        if row.get("tenant_slug") != tenant_slug:
            continue
        key_hash = row.get("key_hash")
        if isinstance(key_hash, str):
            key_hash = key_hash.encode("utf-8")
        try:
            if key_hash and bcrypt.checkpw(api_key_bytes, key_hash):
                return ValidatedApiKey(
                    id=UUID(str(row["id"])),
                    tenant_id=UUID(str(row["tenant_id"])),
                    tenant_slug=str(row["tenant_slug"]),
                )
        except (ValueError, TypeError):
            continue
    return None


async def _lookup_and_verify(
    pool: AsyncConnectionPool, *, api_key: str, prefix: str, tenant_slug: str
) -> ValidatedApiKey | None:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_API_KEY_LOOKUP, {"key_prefix": prefix})
            rows = await cur.fetchall()
    if not rows:
        return None
    return await asyncio.to_thread(_verify_rows, api_key, tenant_slug, [dict(r) for r in rows])


async def validate_api_key_for_tenant(
    pool: AsyncConnectionPool,
    *,
    api_key: str | None,
    tenant_slug: str,
) -> ValidatedApiKey | None:
    """Return key metadata when ``api_key`` is valid for ``tenant_slug``, else ``None``.

    Args:
        pool: Database pool used when the verdict is not cached.
        api_key: The raw key from ``X-Api-Key`` (or gRPC metadata), if any.
        tenant_slug: Tenant slug from the URL.

    Returns:
        The validated key, or ``None`` (no key, malformed, unknown, revoked, other tenant).
    """
    prefix = _key_prefix(api_key) if api_key else None
    if prefix is None or api_key is None:
        return None
    return await _KEY_CACHE.get_or_load(
        _cache_key(api_key, tenant_slug),
        lambda: _lookup_and_verify(pool, api_key=api_key, prefix=prefix, tenant_slug=tenant_slug),
    )


def parse_mock_settings(raw: Any) -> dict[str, Any]:
    """Normalize ``versions.mock_settings`` JSONB to a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def is_private_mock_mode(mock_settings: Any, *, published: bool) -> bool:
    """True when the version is configured as a key-gated draft mock."""
    if published:
        return False
    settings = parse_mock_settings(mock_settings)
    return settings.get("mode") == "private"
