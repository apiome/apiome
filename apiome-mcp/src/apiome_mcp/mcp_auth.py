"""MCP API key extraction and validation (#2999).

Every catalog request needs a key (:mod:`apiome_mcp.catalog_key_gate`). Credentials may
arrive on streamable HTTP via ``Authorization: Bearer <secret>``, in a request's JSON-RPC
``params._meta``:

- ``authorization`` / ``apiome_authorization``: optional Bearer prefix
- ``apiome_api_key`` / ``api_key``: raw secret

or, on stdio only, from ``APIOME_MCP_API_KEY`` — stdio hosts such as Claude Desktop cannot
attach a credential to each request. Over HTTP that setting is never read, so a server-side
key cannot stand in for the caller's.

Stored secrets use **SHA-256 of the UTF-8 secret, then bcrypt**, matching the planned
``mcp keys issue`` workflow (long secrets safe for bcrypt's 72-byte limit).

**Per-call cost (DBP-1.21 / #7204).** bcrypt runs in a worker thread, never on the event loop.
A secret that verified in this process within ``key_cache_seconds`` skips bcrypt: one statement
re-reads the key row by id and hash together with the tenant policy and the called tool's policy
row (:func:`validate_mcp_api_key`), so a revoked or expired key is still refused on its next
call. ``last_used_at`` is written at most once a minute per key.

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
The gate verifies the key once per request and :func:`require_mcp_auth` /
:func:`resolve_optional_mcp_auth` reuse that verification (:func:`current_mcp_auth`).
See :class:`apiome_mcp.scope.Scope` for ``scope_json``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Literal

import bcrypt
import structlog
from fastmcp import Context
from fastmcp.dependencies import CurrentContext, CurrentHeaders, Depends
from fastmcp.exceptions import AuthorizationError
from fastmcp.server.dependencies import get_http_request
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from apiome_mcp.capability_policy import PrefetchedToolPolicy, prefetched_policy_from_row
from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.effective_policy import KeyCapabilitySnapshot
from apiome_mcp.http_credential_middleware import get_http_bearer_from_context
from apiome_mcp.key_cache import CachedKey, LastUsedThrottle, VerifiedKeyCache
from apiome_mcp.scope import Scope, parse_scope_json
from apiome_mcp.settings import get_settings

_log = structlog.get_logger(__name__)

MIN_SECRET_LEN = 12
_PREFIX_CHARS = 12

_BEARER_PREFIX = re.compile(r"(?i)^Bearer\s+")

CapabilityMode = Literal["inherit", "explicit"]

#: What a caller is told when it presents no key at all.
MCP_KEY_REQUIRED_MESSAGE = (
    "MCP API key required: send Authorization: Bearer <api_key> over HTTP, pass the secret in "
    "params._meta (authorization, apiome_authorization, apiome_api_key, or api_key), or set "
    "APIOME_MCP_API_KEY for stdio."
)


class McpAuthContext(BaseModel):
    """Authenticated MCP caller derived from ``apiome.mcp_api_keys``."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    key_id: str
    tenant_id: str
    label: str
    scope: Scope = Field(default_factory=Scope)
    capability_mode: CapabilityMode = "inherit"
    enabled_tools: frozenset[str] = Field(default_factory=frozenset)
    #: DBP-1.21: the called tool's tenant policy, read with the key (``tools/call`` only).
    call_policy: PrefetchedToolPolicy | None = None

    def key_capability_snapshot(self) -> KeyCapabilitySnapshot:
        """Return MTG-1.3 grants as the MTG-1.4 resolver snapshot."""
        return KeyCapabilitySnapshot(
            capability_mode=self.capability_mode,
            enabled_tools=self.enabled_tools,
        )


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


def _parse_capability_mode(raw: Any) -> CapabilityMode:
    if raw == "explicit":
        return "explicit"
    return "inherit"


def _parse_enabled_tools(raw: Any) -> frozenset[str]:
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(item).strip() for item in raw if str(item).strip())
    return frozenset()


#: The key columns plus the tenant policy row and the called tool's policy row (DBP-1.21): the
#: whole catalog gate in one statement. ``%(tool)s`` is ``NULL`` outside ``tools/call``.
KEY_AND_POLICY_COLUMNS = """
    SELECT k.id, k.tenant_id, k.scope_json, k.label, k.key_hash, k.expires_at, k.revoked_at,
           k.capability_mode, k.enabled_tools,
           (p.tenant_id IS NOT NULL) AS has_policy, p.default_mode, p.allow_anonymous_mcp,
           pt.tool_id AS policy_tool_id, pt.in_ceiling, pt.default_enabled, pt.anonymous_enabled
    FROM apiome.mcp_api_keys k
    LEFT JOIN apiome.tenant_mcp_policies p ON p.tenant_id = k.tenant_id
    LEFT JOIN apiome.tenant_mcp_policy_tools pt
           ON pt.tenant_id = k.tenant_id AND pt.tool_id = %(tool)s
"""

#: Cold path: every key with the presented prefix (then bcrypt picks the one that matches).
_KEY_BY_PREFIX = KEY_AND_POLICY_COLUMNS + "    WHERE k.prefix = %(prefix)s\n"

#: Warm path: the key the secret verified as earlier, re-read by id and hash (no bcrypt).
_KEY_BY_ID = KEY_AND_POLICY_COLUMNS + "    WHERE k.id = %(id)s::uuid AND k.key_hash = %(hash)s\n"

#: ``sha256(secret)`` → verified key id + hash, for this process (see :mod:`apiome_mcp.key_cache`).
MCP_KEY_CACHE = VerifiedKeyCache()

#: One ``last_used_at`` write per key per minute from this process.
_LAST_USED = LastUsedThrottle()


def _usable(row: dict[str, Any], now: datetime) -> bool:
    """Whether a key row is neither revoked nor expired at ``now``."""
    if row.get("revoked_at") is not None:
        return False
    exp = row.get("expires_at")
    return exp is None or _as_utc_aware(exp) > now


def _auth_from_row(row: dict[str, Any], tool_name: str | None) -> McpAuthContext:
    """Build the caller from a verified key row (with the tool's policy when it was joined)."""
    return McpAuthContext(
        key_id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        label=str(row["label"]),
        scope=parse_scope_json(row.get("scope_json")),
        capability_mode=_parse_capability_mode(row.get("capability_mode")),
        enabled_tools=_parse_enabled_tools(row.get("enabled_tools")),
        call_policy=prefetched_policy_from_row(row, tool_name) if tool_name else None,
    )


async def _fetch_key_rows(pool: AsyncConnectionPool, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one key statement on one checkout and return its rows."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return list(await cur.fetchall())


def _accepted(pool: AsyncConnectionPool, row: dict[str, Any], tool_name: str | None) -> McpAuthContext:
    """Return the caller for a usable row and stamp ``last_used_at`` when due."""
    key_id = str(row["id"])
    if _LAST_USED.due(key_id):
        schedule_mcp_key_last_used_touch(pool, key_id)
    return _auth_from_row(row, tool_name)


async def validate_mcp_api_key(
    pool: AsyncConnectionPool,
    raw_secret: str,
    *,
    tool_name: str | None = None,
) -> McpAuthContext:
    """Verify a presented secret and return the caller (with the tool's policy when asked).

    **Warm** (the secret verified in this process within ``key_cache_seconds``): one statement
    re-reads the key by id and stored hash, plus the tenant policy and ``tool_name``'s policy row —
    no bcrypt. A revoked, expired, regenerated or deleted key misses, drops the cache entry and
    takes the cold path, which reports why.

    **Cold**: one statement reads every key with the prefix (same policy columns), then
    bcrypt(SHA-256(secret)) runs **in a worker thread** so a slow hash never stalls the event loop.

    Args:
        pool: The catalog pool.
        raw_secret: The presented key.
        tool_name: The tool of a ``tools/call``; its policy row is read in the same statement and
            returned as :attr:`McpAuthContext.call_policy`.

    Returns:
        The verified caller.

    Raises:
        AuthorizationError: Unknown, wrong, revoked or expired key.
    """
    if not raw_secret or len(raw_secret) < MIN_SECRET_LEN:
        raise AuthorizationError("Invalid or unknown MCP API key.")

    cached = MCP_KEY_CACHE.get(raw_secret)
    if cached is not None:
        rows = await _fetch_key_rows(
            pool, _KEY_BY_ID, {"id": cached.key_id, "hash": cached.key_hash, "tool": tool_name}
        )
        if rows and _usable(rows[0], _utc_now()):
            return _accepted(pool, rows[0], tool_name)
        MCP_KEY_CACHE.invalidate(cached.key_id)

    rows = await _fetch_key_rows(pool, _KEY_BY_PREFIX, {"prefix": mcp_key_prefix(raw_secret), "tool": tool_name})
    if not rows:
        _log.debug("mcp_api_key_unknown_prefix")
        raise AuthorizationError("Invalid or unknown MCP API key.")

    now = _utc_now()
    eligible = [row for row in rows if _usable(row, now)]
    for row in eligible:
        if await asyncio.to_thread(_verify_hash, raw_secret, row.get("key_hash")):
            MCP_KEY_CACHE.put(raw_secret, CachedKey(key_id=str(row["id"]), key_hash=row.get("key_hash")))
            return _accepted(pool, row, tool_name)

    if not eligible:
        if any(r.get("revoked_at") is not None for r in rows):
            raise AuthorizationError("This MCP API key has been revoked.")
        if any(r.get("expires_at") is not None and _as_utc_aware(r["expires_at"]) <= now for r in rows):
            raise AuthorizationError("This MCP API key has expired.")

    _log.debug("mcp_api_key_hash_mismatch")
    raise AuthorizationError("Invalid or unknown MCP API key.")


#: The caller verified by the catalog key gate for the request in flight.
_CURRENT_AUTH: ContextVar[McpAuthContext | None] = ContextVar("apiome_mcp_catalog_auth", default=None)


def current_mcp_auth() -> McpAuthContext | None:
    """Return the caller the catalog key gate verified for this request, if any."""
    return _CURRENT_AUTH.get()


def bind_current_mcp_auth(auth: McpAuthContext) -> Token[McpAuthContext | None]:
    """Record ``auth`` as this request's caller; pass the token to :func:`reset_current_mcp_auth`."""
    return _CURRENT_AUTH.set(auth)


def reset_current_mcp_auth(token: Token[McpAuthContext | None]) -> None:
    """Undo :func:`bind_current_mcp_auth`."""
    _CURRENT_AUTH.reset(token)


def on_http_request() -> bool:
    """Whether an HTTP request is in flight (streamable HTTP), as opposed to stdio or in-process."""
    try:
        get_http_request()
    except RuntimeError:
        return False
    return True


def _configured_stdio_key() -> str | None:
    """``APIOME_MCP_API_KEY``, or ``None`` when unset or settings are unavailable."""
    try:
        configured = get_settings().api_key
    except Exception:
        return None
    if configured is None:
        return None
    secret = configured.get_secret_value().strip()
    return secret or None


async def presented_mcp_api_key(ctx: Context | None, *, headers: dict[str, str]) -> str | None:
    """Return the MCP key presented with this request, or ``None``.

    HTTP ``Authorization`` first, then ``params._meta``, then the Bearer stashed from
    streamable HTTP middleware when headers omit it (#3011). On stdio only, falls back to
    ``APIOME_MCP_API_KEY``.
    """
    rc = ctx.request_context if ctx is not None else None
    meta = rc.meta if rc else None
    raw = extract_raw_mcp_api_key(http_headers=headers, request_meta=meta)
    if raw is None and ctx is not None:
        try:
            raw = await get_http_bearer_from_context(ctx)
        except RuntimeError:
            # No MCP session (a direct in-process call): there is no stash to read.
            raw = None
    if raw is None and not on_http_request():
        raw = _configured_stdio_key()
    return raw


async def resolve_optional_mcp_auth(
    ctx: Context,
    pool: AsyncConnectionPool,
    *,
    headers: dict[str, str],
    tool_name: str | None = None,
) -> McpAuthContext | None:
    """Return validated :class:`McpAuthContext` when a credential is present, else ``None``.

    Reuses the verification already recorded for this request when there is one.

    Args:
        ctx: The request's FastMCP context.
        pool: The catalog pool.
        headers: HTTP headers (``Authorization`` only).
        tool_name: The tool of a ``tools/call``; its policy row is read with the key
            (:attr:`McpAuthContext.call_policy`).
    """
    verified = current_mcp_auth()
    if verified is not None:
        return verified
    raw = await presented_mcp_api_key(ctx, headers=headers)
    if raw is None:
        return None
    return await validate_mcp_api_key(pool, raw, tool_name=tool_name)


async def require_mcp_auth(
    ctx: Context = CurrentContext(),
    headers: dict[str, str] = CurrentHeaders(),
) -> McpAuthContext:
    """FastMCP dependency: bearer / meta / stdio-setting credential → ``McpAuthContext``.

    ``ctx`` needs its ``CurrentContext()`` default: FastMCP resolves a dependency's own
    parameters only from their dependency defaults, so a bare ``ctx: Context`` arrives
    missing and every keyed tool fails with "Failed to resolve dependency 'auth'".
    """
    verified = current_mcp_auth()
    if verified is not None:
        return verified
    raw = await presented_mcp_api_key(ctx, headers=headers)
    if raw is None:
        raise AuthorizationError(MCP_KEY_REQUIRED_MESSAGE)
    pool = get_db_pool(ctx)
    return await validate_mcp_api_key(pool, raw)


McpAuthDependency = Depends(require_mcp_auth)


#: ``last_used_at`` writes skip a row any process wrote in the last minute (DBP-1.21).
_TOUCH_LAST_USED = """
    UPDATE apiome.mcp_api_keys SET last_used_at = CURRENT_TIMESTAMP
    WHERE id = %s::uuid
      AND (last_used_at IS NULL OR last_used_at < CURRENT_TIMESTAMP - INTERVAL '1 minute')
"""

#: In-flight touches; the loop keeps only weak references to tasks.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


async def touch_mcp_key_last_used(pool: AsyncConnectionPool, key_id: str) -> None:
    """Persist ``last_used_at`` for a successfully authenticated key (at most once a minute)."""
    async with pool.connection() as conn:
        await conn.execute(_TOUCH_LAST_USED, (key_id,))
        await conn.commit()


def schedule_mcp_key_last_used_touch(pool: AsyncConnectionPool, key_id: str) -> None:
    """Fire-and-forget ``last_used_at`` update so auth latency stays low.

    :func:`validate_mcp_api_key` calls it at most once per key per minute
    (:class:`~apiome_mcp.key_cache.LastUsedThrottle`).
    """

    async def _run() -> None:
        try:
            await touch_mcp_key_last_used(pool, key_id)
        except Exception:
            _log.warning("mcp_api_key_last_used_update_failed", key_id=key_id, exc_info=True)

    try:
        task = asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug("mcp_api_key_last_used_skip_no_event_loop", key_id=key_id)
        return
    if isinstance(task, asyncio.Task):
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)


def reset_mcp_key_caches() -> None:
    """Forget every verified key and ``last_used_at`` stamp (tests; after bulk revocation)."""
    MCP_KEY_CACHE.clear()
    _LAST_USED.clear()
