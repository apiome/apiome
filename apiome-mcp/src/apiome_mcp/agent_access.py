"""AGX-3.1 agent access — agent keys narrow the agent MCP surface to permitted tools (#4537).

An agent calling a tenant's API through a managed MCP toolset presents an **agent key**: an
``apiome.api_keys`` row with ``kind = 'agent'`` (V269), minted by apiome-rest's
``/v1/tenants/{t}/agent-keys``. The key is bound to one toolset and carries an explicit tool
allowlist. On every MCP request (except the ``initialize`` handshake) :class:`AgentAccessMiddleware`

1. reads the key (``Authorization: Bearer`` over HTTP, or ``params._meta`` like the catalog's
   :func:`~apiome_mcp.mcp_auth.extract_raw_mcp_api_key`);
2. resolves it — :func:`resolve_agent_key` — and refuses it when it is unknown, revoked, disabled
   or expired. The row is read on every request, so revocation and expiry take effect on the
   agent's next request, and an allowlist edit is visible on its next ``tools/list``;
3. asks the toolset for its enabled tools and computes :func:`permitted_tools`: the toolset's
   enabled tools **intersected with** the key's allowlist;
4. filters ``tools/list`` to that set — an agent cannot even see a tool it may not call — and
   refuses ``tools/call`` on anything outside it with FastMCP's own unknown-tool error, so a tool
   the key may not use is indistinguishable from one that does not exist.

**This is the AGX surface only.** The catalog server (``apiome_mcp.server``) must never mount this
middleware: its ``tools/list`` always returns the full registry (MTG-2.1, ``docs/LIST_ALWAYS.md``;
rules in ``docs/AGX_COORDINATION.md``). The agent runtime (AGX-2.1, #4533) builds its own FastMCP
app over a compiled toolset and adds :class:`AgentAccessMiddleware` to it.

**The toolset's enabled tools come from AGX-1.2 (#4530)**, which was still open when this shipped:
``agent_toolsets`` / ``agent_toolset_tools`` do not exist yet. The middleware therefore takes the
source as a parameter (:data:`EnabledToolsSource`) and defaults to :func:`toolset_curation_pending`,
which knows no toolset and so **fails closed** — every request is refused with
``agent_toolset_unavailable``. AGX-1.2 supplies the real source: the toolset's enabled operation
refs mapped to compiled tool names (``compile_mcp_tools``), or ``None`` for a missing or disabled
toolset.

**Errors are MCP errors.** A refusal is an :class:`AgentAccessDeniedError` (an :class:`mcp.McpError`):
on ``tools/list`` it is a JSON-RPC error with :data:`AGENT_KEY_REJECTED_CODE` (credential problems)
or :data:`AGENT_TOOLSET_UNAVAILABLE_CODE` and ``data.reason``; on ``tools/call`` the MCP SDK folds
any error into an ``isError`` tool result, whose text starts with the same reason. No message ever
contains the key, its hash or its prefix, and "expired" / "revoked" / "disabled" are only reported
to a caller who presented the key's real secret.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Any

import bcrypt
import mcp.types as mt
import structlog
from fastmcp import Context
from fastmcp.exceptions import NotFoundError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool
from mcp import McpError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.http_credential_middleware import get_http_bearer_from_context
from apiome_mcp.mcp_auth import extract_raw_mcp_api_key

_log = structlog.get_logger(__name__)

__all__ = [
    "AGENT_ACCESS_UNAVAILABLE_CODE",
    "AGENT_KEY_KIND",
    "AGENT_KEY_REJECTED_CODE",
    "AGENT_TOOLSET_UNAVAILABLE_CODE",
    "AgentAccess",
    "AgentAccessDeniedError",
    "AgentAccessMiddleware",
    "AgentAccessReason",
    "AgentKey",
    "AgentKeyResolver",
    "EnabledToolsSource",
    "current_agent_access",
    "permitted_tools",
    "resolve_agent_key",
    "resolve_agent_key_in_context",
    "toolset_curation_pending",
]

#: ``api_keys.kind`` of an agent key (V269). Workspace keys and catalog MCP keys never match.
AGENT_KEY_KIND = "agent"

#: JSON-RPC error code for a missing, unknown, revoked, disabled or expired agent key. In the
#: implementation-defined server-error range (-32000..-32099), clear of the codes the MCP SDKs use
#: (-32000 connection closed, -32001 request timeout, -32002 resource not found, -32042 URL
#: elicitation).
AGENT_KEY_REJECTED_CODE = -32010

#: JSON-RPC error code for a valid key whose toolset cannot be resolved (missing, disabled, or —
#: until AGX-1.2 — not curated at all).
AGENT_TOOLSET_UNAVAILABLE_CODE = -32011

#: JSON-RPC error code when access could not be decided (e.g. the database is unreachable).
AGENT_ACCESS_UNAVAILABLE_CODE = mt.INTERNAL_ERROR

#: The lookup prefix length, matching apiome-rest's ``first 12 characters + '...'``.
_PREFIX_CHARS = 12

#: Shortest secret worth a lookup; an agent key is ``ak_`` + 64 hex characters.
_MIN_SECRET_CHARS = 12

#: In-flight ``last_used_at`` touches. The event loop keeps only weak references to tasks, so an
#: unreferenced fire-and-forget task can be garbage-collected before it runs.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class AgentAccessReason(str, Enum):
    """Why an agent request was refused; the ``data.reason`` and message prefix of the error."""

    KEY_MISSING = "agent_key_missing"
    KEY_INVALID = "agent_key_invalid"
    KEY_REVOKED = "agent_key_revoked"
    KEY_DISABLED = "agent_key_disabled"
    KEY_EXPIRED = "agent_key_expired"
    TOOLSET_UNAVAILABLE = "agent_toolset_unavailable"
    ACCESS_UNAVAILABLE = "agent_access_unavailable"


#: Human sentence per reason. None names the key, its prefix or the tenant.
_MESSAGES: dict[AgentAccessReason, str] = {
    AgentAccessReason.KEY_MISSING: (
        "Agent key required: send Authorization: Bearer <agent key> over HTTP, or the key in "
        "params._meta (authorization, apiome_authorization, apiome_api_key or api_key)."
    ),
    AgentAccessReason.KEY_INVALID: "Invalid or unknown agent key.",
    AgentAccessReason.KEY_REVOKED: "This agent key has been revoked.",
    AgentAccessReason.KEY_DISABLED: "This agent key is disabled; ask a tenant administrator.",
    AgentAccessReason.KEY_EXPIRED: ("This agent key has expired; ask a tenant administrator for a new one."),
    AgentAccessReason.TOOLSET_UNAVAILABLE: (
        "This agent key's toolset is not available (it is missing, disabled, or not curated yet)."
    ),
    AgentAccessReason.ACCESS_UNAVAILABLE: "Agent access could not be verified; try again later.",
}

_CODES: dict[AgentAccessReason, int] = {
    AgentAccessReason.TOOLSET_UNAVAILABLE: AGENT_TOOLSET_UNAVAILABLE_CODE,
    AgentAccessReason.ACCESS_UNAVAILABLE: AGENT_ACCESS_UNAVAILABLE_CODE,
}


class AgentAccessDeniedError(McpError):
    """An agent request was refused. An MCP error, so FastMCP returns it as a JSON-RPC error.

    Attributes:
        reason: Why.
    """

    def __init__(self, reason: AgentAccessReason) -> None:
        self.reason = reason
        super().__init__(
            mt.ErrorData(
                code=_CODES.get(reason, AGENT_KEY_REJECTED_CODE),
                message=f"{reason.value}: {_MESSAGES[reason]}",
                data={"reason": reason.value},
            )
        )


@dataclass(frozen=True)
class AgentKey:
    """A verified, currently usable agent key.

    Attributes:
        key_id: The ``api_keys.id``.
        tenant_id: The owning tenant.
        toolset_id: The agent toolset the key is bound to.
        tool_allowlist: The tool names the key may use (before intersecting with the toolset).
    """

    key_id: str
    tenant_id: str
    toolset_id: str
    tool_allowlist: frozenset[str]


@dataclass(frozen=True)
class AgentAccess:
    """What one agent request may do.

    Attributes:
        key: The verified key.
        permitted: The tool names it may list and call (:func:`permitted_tools`).
    """

    key: AgentKey
    permitted: frozenset[str]

    def permits(self, tool_name: str) -> bool:
        """Return whether ``tool_name`` may be listed and called on this request."""
        return tool_name in self.permitted


#: Resolves a presented secret to a usable key, or raises :class:`AgentAccessDeniedError`.
AgentKeyResolver = Callable[[Context, str], Awaitable[AgentKey]]

#: Returns a key's toolset's enabled tool names, or ``None`` when the toolset is missing or
#: disabled. AGX-1.2 (#4530) provides the real one.
EnabledToolsSource = Callable[[Context, AgentKey], Awaitable[Iterable[str] | None]]


def permitted_tools(enabled: Iterable[str], allowlist: Iterable[str]) -> frozenset[str]:
    """Return the tools an agent key may use: the toolset's enabled tools ∩ the key's allowlist.

    Args:
        enabled: Tool names the toolset exposes (AGX-1.2 curation).
        allowlist: Tool names on the key.

    Returns:
        The intersection. A tool on the allowlist that the toolset does not enable is not
        permitted, and neither is an enabled tool the allowlist omits.
    """
    return frozenset(enabled) & frozenset(allowlist)


async def toolset_curation_pending(ctx: Context, key: AgentKey) -> Iterable[str] | None:
    """The default :data:`EnabledToolsSource` until AGX-1.2 (#4530) ships toolset curation.

    There is no ``agent_toolsets`` table to read yet, so no toolset is known and every agent
    request fails closed with ``agent_toolset_unavailable``.

    Args:
        ctx: The request's FastMCP context (unused).
        key: The verified key (unused).

    Returns:
        Always ``None``.
    """
    _ = (ctx, key)
    return None


_AGENT_KEY_LOOKUP = """
    SELECT ak.id::text AS id,
           ak.tenant_id::text AS tenant_id,
           ak.key_hash,
           ak.toolset_id::text AS toolset_id,
           ak.tool_allowlist,
           ak.enabled,
           (ak.deleted_at IS NOT NULL) AS revoked,
           (ak.expires_at IS NOT NULL AND ak.expires_at <= CURRENT_TIMESTAMP) AS expired,
           (t.enabled AND t.deleted_at IS NULL) AS tenant_active
    FROM apiome.api_keys ak
    JOIN apiome.tenants t ON t.id = ak.tenant_id
    WHERE ak.key_prefix = %s AND ak.kind = 'agent'
"""


def _key_prefix(secret: str) -> str:
    """The stored lookup prefix for ``secret`` (first 12 characters + ``...``)."""
    return secret[:_PREFIX_CHARS] + "..."


def _hash_matches(secret: str, key_hash: Any) -> bool:
    """Return whether ``secret`` verifies against a stored bcrypt ``key_hash``."""
    if isinstance(key_hash, memoryview):
        key_hash = key_hash.tobytes()
    if isinstance(key_hash, str):
        key_hash = key_hash.encode("utf-8")
    if not isinstance(key_hash, bytes):
        return False
    try:
        return bool(bcrypt.checkpw(secret.encode("utf-8"), key_hash))
    except (ValueError, TypeError):
        return False


def _allowlist(raw: Any) -> frozenset[str]:
    """Read a stored ``tool_allowlist`` (JSONB, decoded or not) as a set of names."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return frozenset()
    if isinstance(raw, list):
        return frozenset(item for item in raw if isinstance(item, str))
    return frozenset()


async def _touch_last_used(pool: AsyncConnectionPool, key_id: str) -> None:
    """Record that a key authenticated (best-effort, off the request path)."""
    try:
        async with pool.connection() as conn:
            await conn.execute(
                "UPDATE apiome.api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
                (key_id,),
            )
            await conn.commit()
    except Exception:
        _log.warning("agent_key_last_used_update_failed", key_id=key_id, exc_info=True)


async def resolve_agent_key(pool: AsyncConnectionPool, secret: str) -> AgentKey:
    """Verify an agent-key secret against ``api_keys`` and return the key if it is usable.

    The hash is verified *before* any state is reported, so only the holder of the real secret
    learns that a key is revoked, disabled or expired. bcrypt runs in a worker thread to keep the
    event loop free.

    Args:
        pool: The shared Postgres pool.
        secret: The presented key.

    Returns:
        The verified key.

    Raises:
        AgentAccessDeniedError: ``agent_key_invalid`` when nothing matches (or the tenant is disabled),
            else ``agent_key_revoked`` / ``agent_key_disabled`` / ``agent_key_expired``, checked in
            that order.
    """
    if len(secret) < _MIN_SECRET_CHARS:
        raise AgentAccessDeniedError(AgentAccessReason.KEY_INVALID)
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_AGENT_KEY_LOOKUP, (_key_prefix(secret),))
            rows = await cur.fetchall()

    for row in rows:
        if not await asyncio.to_thread(_hash_matches, secret, row.get("key_hash")):
            continue
        if not row.get("tenant_active") or not row.get("toolset_id"):
            raise AgentAccessDeniedError(AgentAccessReason.KEY_INVALID)
        if row.get("revoked"):
            raise AgentAccessDeniedError(AgentAccessReason.KEY_REVOKED)
        if not row.get("enabled"):
            raise AgentAccessDeniedError(AgentAccessReason.KEY_DISABLED)
        if row.get("expired"):
            raise AgentAccessDeniedError(AgentAccessReason.KEY_EXPIRED)
        key = AgentKey(
            key_id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            toolset_id=str(row["toolset_id"]),
            tool_allowlist=_allowlist(row.get("tool_allowlist")),
        )
        task = asyncio.get_running_loop().create_task(_touch_last_used(pool, key.key_id))
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
        return key
    raise AgentAccessDeniedError(AgentAccessReason.KEY_INVALID)


async def resolve_agent_key_in_context(ctx: Context, secret: str) -> AgentKey:
    """The default :data:`AgentKeyResolver`: :func:`resolve_agent_key` on the lifespan pool."""
    return await resolve_agent_key(get_db_pool(ctx), secret)


async def _presented_secret(ctx: Context | None) -> str | None:
    """Return the agent key presented with this request, if any.

    HTTP ``Authorization`` first, then ``params._meta`` (for transports without headers), then the
    Bearer stashed by :class:`~apiome_mcp.http_credential_middleware.HttpCredentialExtractionMiddleware`.
    """
    headers = get_http_headers(include={"authorization"})
    meta = None
    if ctx is not None:
        request_context = ctx.request_context
        meta = request_context.meta if request_context else None
    secret = extract_raw_mcp_api_key(http_headers=headers, request_meta=meta)
    if secret is None and ctx is not None:
        secret = await get_http_bearer_from_context(ctx)
    return secret


#: The access decided by :meth:`AgentAccessMiddleware.on_request` for the request in flight.
_CURRENT_ACCESS: ContextVar[AgentAccess | None] = ContextVar("apiome_mcp_agent_access", default=None)


def current_agent_access() -> AgentAccess | None:
    """Return the agent access decided for the request in flight, if any.

    The AGX-2.1 invocation path reads the key (for its tenant, toolset and id) from here rather
    than resolving it a second time.
    """
    return _CURRENT_ACCESS.get()


class AgentAccessMiddleware(Middleware):
    """Authenticate agent keys and narrow ``tools/list`` / ``tools/call`` to permitted tools.

    For the **AGX agent surface only** — never add it to the catalog server (see the module
    docstring and ``docs/AGX_COORDINATION.md``).
    """

    def __init__(
        self,
        *,
        key_resolver: AgentKeyResolver = resolve_agent_key_in_context,
        enabled_tools: EnabledToolsSource = toolset_curation_pending,
    ) -> None:
        """Configure where keys and toolsets are read from.

        Args:
            key_resolver: Verifies a presented secret (default: ``api_keys`` via the lifespan
                pool).
            enabled_tools: A key's toolset's enabled tools (default: :func:`toolset_curation_pending`,
                which fails closed until AGX-1.2 provides a source).
        """
        self._key_resolver = key_resolver
        self._enabled_tools = enabled_tools

    async def authorize(self, ctx: Context | None) -> AgentAccess:
        """Decide what the request in ``ctx`` may do.

        Args:
            ctx: The request's FastMCP context. ``None`` is treated as no credential.

        Returns:
            The verified key and its permitted tools.

        Raises:
            AgentAccessDeniedError: The key is missing or unusable, its toolset is unavailable, or
                access could not be decided (any unexpected failure fails closed).
        """
        try:
            secret = await _presented_secret(ctx)
            if secret is None or ctx is None:
                raise AgentAccessDeniedError(AgentAccessReason.KEY_MISSING)
            key = await self._key_resolver(ctx, secret)
            enabled = await self._enabled_tools(ctx, key)
            if enabled is None:
                _log.info(
                    "agent_toolset_unavailable",
                    key_id=key.key_id,
                    tenant_id=key.tenant_id,
                    toolset_id=key.toolset_id,
                )
                raise AgentAccessDeniedError(AgentAccessReason.TOOLSET_UNAVAILABLE)
            return AgentAccess(key=key, permitted=permitted_tools(enabled, key.tool_allowlist))
        except AgentAccessDeniedError as denied:
            _log.info("agent_access_denied", reason=denied.reason.value)
            raise
        except Exception:
            _log.warning("agent_access_unavailable", exc_info=True)
            raise AgentAccessDeniedError(AgentAccessReason.ACCESS_UNAVAILABLE) from None

    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        """Authorize every request but the ``initialize`` handshake, then run it with the access set."""
        if context.method == "initialize":
            return await call_next(context)
        access = await self.authorize(context.fastmcp_context)
        token = _CURRENT_ACCESS.set(access)
        try:
            return await call_next(context)
        finally:
            _CURRENT_ACCESS.reset(token)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        """Return only the permitted tools: an agent never sees a tool it may not call."""
        access = _require_access()
        tools = await call_next(context)
        return [tool for tool in tools if access.permits(tool.name)]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        """Refuse a call to a non-permitted tool exactly as a call to a nonexistent one."""
        access = _require_access()
        name = context.message.name
        if not access.permits(name):
            _log.info(
                "agent_tool_not_permitted",
                tool=name,
                key_id=access.key.key_id,
                tenant_id=access.key.tenant_id,
                toolset_id=access.key.toolset_id,
            )
            raise NotFoundError(f"Unknown tool: {name!r}")
        return await call_next(context)


def _require_access() -> AgentAccess:
    """Return the access :meth:`AgentAccessMiddleware.on_request` set, failing closed without it."""
    access = _CURRENT_ACCESS.get()
    if access is None:
        raise AgentAccessDeniedError(AgentAccessReason.KEY_MISSING)
    return access
