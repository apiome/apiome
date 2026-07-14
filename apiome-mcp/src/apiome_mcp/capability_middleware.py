"""Call-time MCP tool enable-set gate — MTG-2.2 (#4771).

After optional auth resolve (HTTP Bearer + stdio ``_meta``, same path as
``resolve_optional_mcp_auth``), applies the MTG-1.4 effective policy resolver.
Disabled tools raise :class:`~fastmcp.exceptions.ToolError` with stable code
``capability_disabled``. Does **not** filter ``tools/list`` (MTG-2.1).

Anonymous callers (no credential) pass through; policy for that path is MTG-2.3.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import mcp.types as mt
import structlog
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool

from apiome_mcp.capability_policy import (
    CAPABILITY_DISABLED_CODE,
    capability_disabled_message,
    load_tenant_mcp_policy_snapshot,
)
from apiome_mcp.database_pool import get_db_pool
from apiome_mcp.effective_policy import resolve_tool_effective
from apiome_mcp.mcp_auth import resolve_optional_mcp_auth

_log = structlog.get_logger(__name__)

__all__ = [
    "CAPABILITY_DISABLED_CODE",
    "CapabilityCallGateMiddleware",
]


class CapabilityCallGateMiddleware(Middleware):
    """Deny ``tools/call`` when the authenticated key's effective enable-set excludes the tool.

    Passthrough for ``tools/list``. Requires DB lifespan (pool) when a credential
    is present; missing FastMCP context is treated as anonymous (no gate).
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
        auth = await resolve_optional_mcp_auth(fc, pool, headers=headers)
        if auth is None:
            # Anonymous: deferred to MTG-2.3.
            return await call_next(context)

        key = auth.key_capability_snapshot()
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
        raise ToolError(capability_disabled_message(name))
