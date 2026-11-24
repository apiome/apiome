"""Call-time MCP tool enable-set gate — MTG-2.2 (#4771).

Applies the MTG-1.4 effective policy resolver; denied calls raise
:class:`~fastmcp.exceptions.ToolError` with stable code ``capability_disabled`` and schedule a
denial audit row (MTG-2.4 / #4773).

**Verification order (DBP-1.21 / #7204).** FastMCP runs the first-added middleware outermost, and
``apiome_mcp.server`` adds this gate first, so on ``tools/call`` it runs *before* the catalog key
gate's ``on_request``. It therefore verifies the key itself — with the called tool's name, so the
same single statement also returns that tool's tenant policy — and records the verification for
the rest of the request (:func:`~apiome_mcp.mcp_auth.bind_current_mcp_auth`). The key gate and the
tools' ``require_mcp_auth`` then reuse it: one key statement per call, no policy query here.

A call that somehow arrives without a key is refused, never passed through: anonymous
access was removed with the key gate (MTG-2.3's anonymous policy no longer applies).

Does **not** filter ``tools/list`` (MTG-2.1). Do not apply AGX-3.1 list
filtering here — see ``docs/AGX_COORDINATION.md`` (MTG-5.5 / #4789).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import mcp.types as mt
import structlog
from fastmcp.exceptions import AuthorizationError, ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.capability_policy import (
    CAPABILITY_DISABLED_CODE,
    capability_disabled_message,
    load_tenant_mcp_policy_snapshot,
)
from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.effective_policy import resolve_tool_effective
from apiome_mcp.mcp_auth import (
    MCP_KEY_REQUIRED_MESSAGE,
    McpAuthContext,
    bind_current_mcp_auth,
    current_mcp_auth,
    reset_current_mcp_auth,
    resolve_optional_mcp_auth,
)
from apiome_mcp.mcp_capability_denial_audit import (
    detect_mcp_transport,
    schedule_mcp_capability_denial,
)

_log = structlog.get_logger(__name__)

__all__ = [
    "CAPABILITY_DISABLED_CODE",
    "CapabilityCallGateMiddleware",
]


class CapabilityCallGateMiddleware(Middleware):
    """Deny ``tools/call`` when policy excludes the tool for the caller.

    Passthrough for ``tools/list``. Requires the DB lifespan (pool). A missing FastMCP
    context (direct in-process calls without a request) is not gated here.
    """

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        name = context.message.name
        fc = context.fastmcp_context
        if fc is None:
            return await call_next(context)

        pool = get_db_pool(fc)
        # Match CurrentHeaders(): include Authorization; empty when not on HTTP.
        headers = get_http_headers(include={"authorization"})
        already_verified = current_mcp_auth() is not None
        auth = await resolve_optional_mcp_auth(fc, pool, headers=headers, tool_name=name)
        if auth is None:
            raise AuthorizationError(MCP_KEY_REQUIRED_MESSAGE)
        token = None if already_verified else bind_current_mcp_auth(auth)
        try:
            return await self._gate(context, call_next, auth=auth, pool=pool)
        finally:
            if token is not None:
                reset_current_mcp_auth(token)

    async def _gate(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
        *,
        auth: McpAuthContext,
        pool: AsyncConnectionPool,
    ) -> Any:
        """Decide the call for a verified ``auth``; run it or raise ``capability_disabled``."""
        name = context.message.name

        key = auth.key_capability_snapshot()
        prefetched = auth.call_policy
        if prefetched is not None and prefetched.tool_name == name:
            # DBP-1.21: read with the key in the gate's one statement — no query here.
            tenant = prefetched.tenant
        else:
            tenant = await load_tenant_mcp_policy_snapshot(pool, auth.tenant_id)
        enabled, deny_reason = resolve_tool_effective(name, key=key, tenant=tenant)
        if enabled:
            return await call_next(context)

        _log.info(
            "mcp_capability_disabled",
            tool=name,
            key_id=auth.key_id,
            tenant_id=auth.tenant_id,
            deny_reason=deny_reason.value if deny_reason else None,
        )
        schedule_mcp_capability_denial(
            pool,
            key_id=auth.key_id,
            tenant_id=auth.tenant_id,
            tool_id=name,
            transport=detect_mcp_transport(),
            reason=deny_reason.value if deny_reason else None,
        )
        raise ToolError(capability_disabled_message(name))
