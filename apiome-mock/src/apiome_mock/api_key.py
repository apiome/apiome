"""Validate tenant REST API keys for private draft mocks (#4446, SIM-2.5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import bcrypt
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_API_KEY_LOOKUP = """
    SELECT ak.id, ak.tenant_id, ak.key_hash, ak.expires_at, ak.enabled,
           t.slug AS tenant_slug
    FROM apiome.api_keys ak
    JOIN apiome.tenants t ON ak.tenant_id = t.id
    WHERE ak.key_prefix = %(key_prefix)s
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


async def validate_api_key_for_tenant(
    pool: AsyncConnectionPool,
    *,
    api_key: str | None,
    tenant_slug: str,
) -> ValidatedApiKey | None:
    """Return key metadata when ``api_key`` is valid for ``tenant_slug``, else ``None``."""
    prefix = _key_prefix(api_key) if api_key else None
    if prefix is None:
        return None

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_API_KEY_LOOKUP, {"key_prefix": prefix})
            rows = await cur.fetchall()

    if not rows:
        return None

    api_key_bytes = api_key.encode("utf-8")  # type: ignore[union-attr]
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
