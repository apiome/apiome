"""MCP tool & toolset registry tests — MTG-1.1 (#4765)."""

from app.mcp_tool_registry import (
    McpToolDescriptor,
    is_registered_mcp_tool,
    mcp_tool_descriptors,
    mcp_tool_ids,
    mcp_tools_by_toolset,
)

# Every currently registered FastMCP tool in apiome-mcp/server.py (live handlers).
_LIVE_FASTMCP_TOOL_IDS = frozenset(
    {
        "ping",
        "project.list",
        "spec.list",
        "spec.list_my_specs",
        "spec.describe",
        "spec.list_tags",
        "spec.search",
        "spec.search_semantic",
        "spec.get_openapi",
        "spec.export_yaml",
        "spec.list_operations",
        "spec.describe_operation",
        "spec.list_components",
        "spec.describe_component",
    }
)

# Capability-only ids (governance toggles; not yet FastMCP handlers).
_CAPABILITY_IDS = frozenset({"spec.mcp", "spec.catalog"})

_EXPECTED_TOOLSETS = {
    "health": frozenset({"ping"}),
    "catalog": frozenset(
        {
            "project.list",
            "spec.list",
            "spec.list_my_specs",
            "spec.describe",
            "spec.list_tags",
            "spec.mcp",
            "spec.catalog",
        }
    ),
    "search": frozenset({"spec.search", "spec.search_semantic"}),
    "document": frozenset({"spec.get_openapi", "spec.export_yaml"}),
    "structure": frozenset(
        {
            "spec.list_operations",
            "spec.describe_operation",
            "spec.list_components",
            "spec.describe_component",
        }
    ),
}


def test_registry_covers_every_live_fastmcp_tool():
    ids = set(mcp_tool_ids())
    missing = _LIVE_FASTMCP_TOOL_IDS - ids
    assert not missing, f"Live FastMCP tools missing from registry: {sorted(missing)}"


def test_registry_includes_capability_ids():
    ids = set(mcp_tool_ids())
    assert _CAPABILITY_IDS <= ids


def test_registry_equals_live_union_capabilities():
    assert set(mcp_tool_ids()) == _LIVE_FASTMCP_TOOL_IDS | _CAPABILITY_IDS


def test_toolset_membership_matches_mtg_table():
    for toolset, expected in _EXPECTED_TOOLSETS.items():
        actual = {d.id for d in mcp_tools_by_toolset(toolset)}  # type: ignore[arg-type]
        assert actual == expected, f"toolset {toolset}: {actual} != {expected}"


def test_descriptors_are_fully_populated_and_unique():
    descriptors = mcp_tool_descriptors()
    assert descriptors
    seen: set[str] = set()
    for d in descriptors:
        assert isinstance(d, McpToolDescriptor)
        assert d.id.strip()
        assert d.description.strip()
        assert d.toolset in _EXPECTED_TOOLSETS
        assert d.id not in seen
        seen.add(d.id)


def test_is_registered_mcp_tool():
    assert is_registered_mcp_tool("ping")
    assert is_registered_mcp_tool("spec.list")
    assert is_registered_mcp_tool("spec.mcp")
    assert not is_registered_mcp_tool("spec.unknown_future_tool")
    assert not is_registered_mcp_tool("")


def test_mcp_tool_ids_order_matches_descriptors():
    assert mcp_tool_ids() == [d.id for d in mcp_tool_descriptors()]
