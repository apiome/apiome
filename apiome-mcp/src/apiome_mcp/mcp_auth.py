"""MCP API key extraction and validation (#2999).

Credentials may arrive on streamable HTTP via ``Authorization: Bearer <secret>`` or,
for stdio (no HTTP request), via ``tools/call`` JSON-RPC ``params._meta``:

- ``authorization`` / ``apiome_authorization``: optional Bearer prefix
- ``apiome_api_key`` / ``api_key``: raw secret

Stored secrets use **SHA-256 of the UTF-8 secret, then bcrypt**, matching the planned
``mcp keys issue`` workflow (long secrets safe for bcrypt's 72-byte limit).

Tools opt in with::

    from fastmcp.dependencies import Depends

    from apiome_mcp.mcp_auth import McpAuthContext, require_mcp_auth

    @mcp.tool
    async def example(auth: McpAuthContext = Depends(require_mcp_auth)) -> str:
        ...

Scoped reads combine :meth:`apiome_mcp.scope.Scope.allows` with revision
visibility via :func:`apiome_mcp.spec_authorization.authorize_spec` (and
parameterized SQL via
:func:`apiome_mcp.spec_authorization.build_authorized_spec_sql_predicate`).
Tools that accept anonymous callers but upgrade when a secret is present use
:func:`resolve_optional_mcp_auth`.
See :class:`apiome_mcp.scope.Scope` for ``scope_json``.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import bcrypt
import structlog
from fastmcp import Context
from fastmcp.dependencies import CurrentHeaders, Depends
from fastmcp.exceptions import AuthorizationError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.http_credential_middleware import get_http_bearer_from_context
from apiome_mcp.scope import Scope, parse_scope_json

_log = structlog.get_logger(__name__)

MIN_SECRET_LEN = 12
_PREFIX_CHARS = 12

_BEARER_PREFIX = re.compile(r"(?i)^Bearer\s+")


class McpAuthContext(BaseModel):
    """Authenticated MCP caller derived from ``apiome.mcp_api_keys``."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key_id: str
    tenant_id: str
    label: str
    scope: Scope = Field(default_factory=Scope)


def mcp_key_prefix(secret: str) -> str:
    """Indexed lookup prefix; aligns with dashboard-style ``first12 + '...'``."""
    if len(secret) < _PREFIX_CHARS:
        return secret + "..."
    return secret[:_PREFIX_CHARS] + "..."


def normalize_stored_prefix(user_input: str) -> str:
    """Normalize CLI or human input to the ``apiome.mcp_api_keys.prefix`` format.

    Raises :exc:`ValueError` if the bare prefix (after stripping a trailing
    ``...``) is shorter than :data:`_PREFIX_CHARS` characters, because such a
    string can never match any stored key and ``keys revoke`` would silently
    do nothing.
    """
    s = user_input.strip()
    if not s:
        raise ValueError("Prefix must be non-empty.")
    if s.endswith("..."):
        s = s[:-3].strip()
    if not s:
        raise ValueError("Prefix is invalid.")
    if len(s) < _PREFIX_CHARS:
        raise ValueError(
            f"Prefix is too short ({len(s)} chars); "
            f"supply at least {_PREFIX_CHARS} characters (the first {_PREFIX_CHARS} of the key)."
        )
    return s[:_PREFIX_CHARS] + "..."


def hash_mcp_api_key_secret(plain: str) -> bytes:
    """Return bcrypt bytes for storing ``key_hash`` (ASCII utf-8 safe for VARCHAR)."""
    digest = hashlib.sha256(plain.encode("utf-8")).digest()
    return bcrypt.hashpw(digest, bcrypt.gensalt())


def _strip_bearer(value: str) -> str:
    value = value.strip()
    if _BEARER_PREFIX.match(value):
        return value.split(None, 1)[1].strip()
    return value


def meta_as_dict(meta: Any) -> dict[str, Any]:
    if meta is None:
        return {}
    if isinstance(meta, dict):
        base = dict(meta)
    else:
        dump = getattr(meta, "model_dump", None)
        base = dump(mode="python") if callable(dump) else {}
    inner = base.get("_meta")
    if isinstance(inner, dict):
        merged = {**base, **inner}
        return merged
    return base


def extract_raw_mcp_api_key(*, http_headers: dict[str, str], request_meta: Any) -> str | None:
    """Resolve secret from HTTP headers first, then MCP request meta."""
    auth = http_headers.get("authorization")
    if isinstance(auth, str) and auth.strip():
        stripped = _strip_bearer(auth)
        if stripped:
            return stripped

    meta = meta_as_dict(request_meta)
    for key in ("authorization", "apiome_authorization"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return _strip_bearer(val)
    for key in ("apiome_api_key", "api_key"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _verify_hash(secret: str, key_hash: Any) -> bool:
    if isinstance(key_hash, memoryview):
        key_hash = key_hash.tobytes()
    elif isinstance(key_hash, str):
        key_hash = key_hash.encode("utf-8")
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    try:
        return bool(bcrypt.checkpw(digest, key_hash))
    except (ValueError, TypeError):
        return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def validate_mcp_api_key(pool: AsyncConnectionPool, raw_secret: str) -> McpAuthContext:
    """Load key row by prefix, enforce lifecycle, verify bcrypt(SHA256(secret))."""
    if not raw_secret or len(raw_secret) < MIN_SECRET_LEN:
        raise AuthorizationError("Invalid or unknown MCP API key.")

    prefix = mcp_key_prefix(raw_secret)
    query = """
        SELECT id, tenant_id, scope_json, label, key_hash, expires_at, revoked_at
        FROM apiome.mcp_api_keys
        WHERE prefix = %s
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (prefix,))
            rows = await cur.fetchall()

    if not rows:
        _log.debug("mcp_api_key_unknown_prefix")
        raise AuthorizationError("Invalid or unknown MCP API key.")

    now = _utc_now()
    eligible: list[dict[str, Any]] = []
    for row in rows:
        if row.get("revoked_at") is not None:
            continue
        exp = row.get("expires_at")
        if exp is not None and _as_utc_aware(exp) <= now:
            continue
        eligible.append(row)

    for row in eligible:
        if _verify_hash(raw_secret, row.get("key_hash")):
            key_id = str(row["id"])
            schedule_mcp_key_last_used_touch(pool, key_id)
            return McpAuthContext(
                key_id=key_id,
                tenant_id=str(row["tenant_id"]),
                label=str(row["label"]),
                scope=parse_scope_json(row.get("scope_json")),
            )

    if not eligible:
        if any(r.get("revoked_at") is not None for r in rows):
            raise AuthorizationError("This MCP API key has been revoked.")
        if any(r.get("expires_at") is not None and _as_utc_aware(r["expires_at"]) <= now for r in rows):
            raise AuthorizationError("This MCP API key has expired.")

    _log.debug("mcp_api_key_hash_mismatch")
    raise AuthorizationError("Invalid or unknown MCP API key.")


async def resolve_optional_mcp_auth(
    ctx: Context,
    pool: AsyncConnectionPool,
    *,
    headers: dict[str, str],
) -> McpAuthContext | None:
    """Return validated :class:`McpAuthContext` when a credential is present, else ``None``.

    Checks HTTP headers and JSON-RPC ``meta`` like :func:`require_mcp_auth`, then the
    Bearer secret stashed from streamable HTTP middleware when headers omit it (#3011).
    """
    rc = ctx.request_context
    meta = rc.meta if rc else None
    raw = extract_raw_mcp_api_key(http_headers=headers, request_meta=meta)
    if raw is None:
        raw = await get_http_bearer_from_context(ctx)
    if raw is None:
        return None
    return await validate_mcp_api_key(pool, raw)


async def require_mcp_auth(
    ctx: Context,
    headers: dict[str, str] = CurrentHeaders(),
) -> McpAuthContext:
    """FastMCP dependency: bearer / meta credential → ``McpAuthContext``.

    Like :func:`resolve_optional_mcp_auth`, falls back to the HTTP Bearer stash when headers
    and meta omit the secret (#3011).
    """
    rc = ctx.request_context
    meta = rc.meta if rc else None
    raw = extract_raw_mcp_api_key(http_headers=headers, request_meta=meta)
    if raw is None:
        raw = await get_http_bearer_from_context(ctx)
    if raw is None:
        raise AuthorizationError(
            "MCP authentication required: send Authorization: Bearer <api_key> over HTTP, "
            "or pass the same secret in tools/call params._meta "
            "(authorization, apiome_authorization, apiome_api_key, or api_key)."
        )
    pool = get_db_pool(ctx)
    return await validate_mcp_api_key(pool, raw)


McpAuthDependency = Depends(require_mcp_auth)


async def touch_mcp_key_last_used(pool: AsyncConnectionPool, key_id: str) -> None:
    """Persist ``last_used_at`` for a successfully authenticated key."""
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE apiome.mcp_api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
            (key_id,),
        )
        await conn.commit()


def schedule_mcp_key_last_used_touch(pool: AsyncConnectionPool, key_id: str) -> None:
    """Fire-and-forget ``last_used_at`` update so auth latency stays low."""

    async def _run() -> None:
        try:
            await touch_mcp_key_last_used(pool, key_id)
        except Exception:
            _log.warning("mcp_api_key_last_used_update_failed", key_id=key_id, exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug("mcp_api_key_last_used_skip_no_event_loop", key_id=key_id)
