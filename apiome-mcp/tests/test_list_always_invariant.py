"""List-always invariant — MTG-2.1 (#4770).

Catalog MCP ``tools/list`` must return every live registry tool even when the
caller's effective enable-set is empty or a proper subset. Enable-set applies
to ``tools/call`` only (MTG-2.2). Contrast AGX-3.1 (#4537), which filters list.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.mcp_tool_registry import mcp_tool_ids
from fastmcp.server.middleware import MiddlewareContext

from apiome_mcp.effective_policy import (
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    is_tool_effectively_enabled,
)
from apiome_mcp.registry_middleware import RegistryFailClosedMiddleware
from apiome_mcp.server import mcp

# Capability-only registry ids (not live FastMCP handlers).
_CAPABILITY_IDS = frozenset({"spec.mcp", "spec.catalog"})


def _live_registry_tool_ids() -> set[str]:
    return set(mcp_tool_ids()) - _CAPABILITY_IDS


async def _listed_names() -> set[str]:
    tools = await mcp.list_tools()
    return {t.name for t in tools}


def test_tools_list_includes_every_live_registry_tool() -> None:
    """CI gate: accidental ``on_list_tools`` filtering fails the build."""
    listed = asyncio.run(_listed_names())
    assert listed == _live_registry_tool_ids()


@pytest.mark.parametrize(
    "enabled_tools",
    [
        frozenset(),  # empty enable-set
        frozenset({"ping"}),  # proper subset
    ],
)
def test_tools_list_unfiltered_when_key_enable_set_empty_or_subset(
    enabled_tools: frozenset[str],
) -> None:
    """List stays full while call-time effective set is empty/subset.

    Uses MTG-1.4 with ``capability_mode=explicit`` so enable-set is the sole
    call gate (tenant ``default_mode=all`` keeps full ceiling). Prove the
    surfaces diverge: call-effective ⊆ enable_set, list == full live registry.
    """
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})
    key = KeyCapabilitySnapshot(
        capability_mode="explicit",
        enabled_tools=enabled_tools,
    )
    live_ids = _live_registry_tool_ids()
    call_enabled = {tool_id for tool_id in live_ids if is_tool_effectively_enabled(tool_id, key=key, tenant=tenant)}
    assert call_enabled == (enabled_tools & live_ids)
    assert call_enabled != live_ids  # empty or proper subset of the catalog

    listed = asyncio.run(_listed_names())
    assert listed == live_ids


def test_registry_middleware_on_list_tools_is_passthrough() -> None:
    """Explicit design: RegistryFailClosedMiddleware never filters list."""
    mw = RegistryFailClosedMiddleware()
    sentinel = [SimpleNamespace(name="ping"), SimpleNamespace(name="spec.list")]
    call_next = AsyncMock(return_value=sentinel)
    ctx = MiddlewareContext(
        message=SimpleNamespace(),
        fastmcp_context=None,
    )

    async def run() -> object:
        return await mw.on_list_tools(ctx, call_next)

    result = asyncio.run(run())
    assert result is sentinel
    call_next.assert_awaited_once_with(ctx)
