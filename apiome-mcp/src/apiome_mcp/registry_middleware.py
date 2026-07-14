"""Fail-closed MCP tool registry gate — MTG-1.1 (#4765).

Unknown / future ``tools/call`` names that are not in the shared registry
(``app.mcp_tool_registry``) are denied at call time until explicitly registered.
Tenant / key enable-set gating uses MTG-1.4 (``app.mcp_effective_policy``) and
is wired in MTG-2.2.
"""

from __future__ import annotations

from typing import Any

import mcp.types as mt
from app.mcp_tool_registry import is_registered_mcp_tool
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext


class RegistryFailClosedMiddleware(Middleware):
    """Reject ``tools/call`` when the tool name is absent from the MTG-1.1 registry."""

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        name = context.message.name
        if not is_registered_mcp_tool(name):
            raise ToolError(
                f"Tool '{name}' is not registered in the Apiome MCP tool registry "
                "(MTG-1.1). Unknown tools fail closed until explicitly registered."
            )
        return await call_next(context)
