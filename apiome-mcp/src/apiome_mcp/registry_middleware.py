"""Fail-closed MCP tool registry gate — MTG-1.1 (#4765).

Unknown / future ``tools/call`` names that are not in the shared registry
(``app.mcp_tool_registry``) are denied at call time until explicitly registered.
Tenant / key enable-set gating uses MTG-1.4 (``app.mcp_effective_policy``) via
``CapabilityCallGateMiddleware`` (MTG-2.2).

List-always (MTG-2.1 / #4770)
-----------------------------

This middleware must **not** filter ``tools/list``. Catalog MCP always
exposes every registered live tool for discovery, even when the caller's
enable-set is empty or a subset. Call-time denial belongs on ``tools/call``
only. **Contrast AGX-3.1 (#4537)**, which filters ``tools/list`` to permitted
agent tools — do not reuse that pattern here. See ``docs/LIST_ALWAYS.md``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import mcp.types as mt
from app.mcp_tool_registry import is_registered_mcp_tool
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool


class RegistryFailClosedMiddleware(Middleware):
    """Reject ``tools/call`` when the tool name is absent from the MTG-1.1 registry.

    Does not filter ``tools/list`` (MTG-2.1 list-always invariant).
    """

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        # MTG-2.1: pass through unchanged — never intersect with enable-set.
        return await call_next(context)

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
