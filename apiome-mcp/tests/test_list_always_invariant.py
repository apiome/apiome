"""List-always invariant — MTG-2.1 (#4770) + AGX coordination — MTG-5.5 (#4789).

Catalog MCP ``tools/list`` must return every live registry tool even when the
caller's effective enable-set is empty or a proper subset. Enable-set applies
to ``tools/call`` only (MTG-2.2). Contrast AGX-3.1 (#4537), which filters list.
Shared AGX allowlist / toolset filtering must never land on catalog
``on_list_tools`` — see ``docs/AGX_COORDINATION.md``.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.mcp_tool_registry import mcp_tool_ids
from fastmcp.server.middleware import MiddlewareContext

from apiome_mcp import capability_middleware, registry_middleware
from apiome_mcp.capability_middleware import CapabilityCallGateMiddleware
from apiome_mcp.effective_policy import (
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    is_tool_effectively_enabled,
)
from apiome_mcp.registry_middleware import RegistryFailClosedMiddleware
from apiome_mcp.server import mcp

# Capability-only registry ids (not live FastMCP handlers).
_CAPABILITY_IDS = frozenset({"spec.mcp", "spec.catalog"})

# AGX-3.1-shaped filters must not appear inside catalog ``on_list_tools``.
_AGX_LIST_FILTER_NAMES = frozenset(
    {
        "allowlist",
        "tool_allowlist",
        "enabled_tools",
        "enable_set",
        "is_tool_effectively_enabled",
        "resolve_tool_effective",
        "resolve_tool_anonymous",
        "permitted",
        "toolset",
    }
)


def _live_registry_tool_ids() -> set[str]:
    return set(mcp_tool_ids()) - _CAPABILITY_IDS


async def _listed_names() -> set[str]:
    tools = await mcp.list_tools()
    return {t.name for t in tools}


def _on_list_tools_source(cls: type) -> str:
    method = cls.__dict__.get("on_list_tools")
    assert method is not None, f"{cls.__name__} must define on_list_tools (MTG list-always)"
    return inspect.getsource(method)


def _names_used_in_on_list_tools(module: object, class_name: str) -> set[str]:
    """Collect Name / Attribute identifiers inside ``on_list_tools`` via AST."""
    path = Path(inspect.getfile(module))
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "on_list_tools":
                    names: set[str] = set()
                    for child in ast.walk(item):
                        if isinstance(child, ast.Name):
                            names.add(child.id)
                        elif isinstance(child, ast.Attribute):
                            names.add(child.attr)
                    return names
    raise AssertionError(f"{class_name}.on_list_tools not found in {path}")


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


def test_capability_middleware_on_list_tools_is_passthrough() -> None:
    """Capability gate must not hide tools on list (MTG-5.5 / AGX contrast)."""
    mw = CapabilityCallGateMiddleware()
    sentinel = [SimpleNamespace(name="ping"), SimpleNamespace(name="spec.search")]
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


@pytest.mark.parametrize(
    ("module", "class_name"),
    [
        (registry_middleware, "RegistryFailClosedMiddleware"),
        (capability_middleware, "CapabilityCallGateMiddleware"),
    ],
)
def test_catalog_on_list_tools_is_pure_passthrough_source(
    module: object,
    class_name: str,
) -> None:
    """AST CI guard (MTG-5.5): list handlers only await call_next — no AGX filters."""
    cls = getattr(module, class_name)
    source = _on_list_tools_source(cls)
    assert "call_next" in source
    assert "return await call_next" in " ".join(source.split())

    names = _names_used_in_on_list_tools(module, class_name)
    forbidden = names & _AGX_LIST_FILTER_NAMES
    assert not forbidden, (
        f"{class_name}.on_list_tools references AGX/MTG filter symbols {forbidden}; "
        "catalog list must stay unfiltered (see docs/AGX_COORDINATION.md)"
    )


def test_agx_coordination_note_published() -> None:
    """Docs acceptance: MTG-5.5 architecture note is present in the package tree."""
    docs = Path(__file__).resolve().parents[1] / "docs" / "AGX_COORDINATION.md"
    text = docs.read_text(encoding="utf-8")
    assert "AGX-3.1" in text
    assert "#4537" in text
    assert "#4503" in text
    assert "tools/list" in text
    assert "must **not** share" in text or "must not" in text.lower()
