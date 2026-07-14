"""Registry parity + fail-closed middleware — MTG-1.1 (#4765)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.mcp_tool_registry import mcp_tool_ids
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext

from apiome_mcp.registry_middleware import RegistryFailClosedMiddleware
from apiome_mcp.server import mcp

# Capability-only registry ids (not live FastMCP handlers).
_CAPABILITY_IDS = frozenset({"spec.mcp", "spec.catalog"})


def test_every_registered_fastmcp_tool_is_in_registry() -> None:
    """CI gate: a ``@mcp.tool`` missing from the registry fails the build."""

    async def _names() -> set[str]:
        tools = await mcp.list_tools()
        return {t.name for t in tools}

    live = asyncio.run(_names())
    registry = set(mcp_tool_ids())
    missing = live - registry
    assert not missing, f"FastMCP tools missing from registry: {sorted(missing)}"


def test_live_fastmcp_tools_are_exactly_registry_minus_capabilities() -> None:
    async def _names() -> set[str]:
        tools = await mcp.list_tools()
        return {t.name for t in tools}

    live = asyncio.run(_names())
    expected = set(mcp_tool_ids()) - _CAPABILITY_IDS
    assert live == expected


def test_registry_middleware_allows_registered_tool() -> None:
    mw = RegistryFailClosedMiddleware()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=None,
    )

    async def run() -> object:
        return await mw.on_call_tool(ctx, call_next)

    result = asyncio.run(run())
    assert result == {"ok": True}
    call_next.assert_awaited_once()


def test_registry_middleware_rejects_unregistered_tool() -> None:
    mw = RegistryFailClosedMiddleware()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="spec.unknown_future_tool"),
        fastmcp_context=None,
    )

    async def run() -> None:
        await mw.on_call_tool(ctx, call_next)

    with pytest.raises(ToolError, match="not registered"):
        asyncio.run(run())
    call_next.assert_not_awaited()
