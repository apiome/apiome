"""MCP tool & toolset registry — MTG-1.1 (#4765).

Single source of truth for every Apiome MCP tool (and governance capability) id
exposed by ``apiome-mcp``. The Control Panel, REST catalog
(``GET /api-keys/mcp-tools``), and MCP call-time fail-closed gate all read from
here so admin UX and runtime share stable identifiers.

Stable-id policy
----------------

Registry ``id`` values are the MCP ``tools/call`` names (and planned capability
ids such as ``spec.mcp`` / ``spec.catalog``). Shipped ids are never renamed —
tenant policies and key grants (MTG-1.2+) store them by value.

Live FastMCP tools must be a subset of this catalog; CI in ``apiome-mcp`` fails
if a ``@mcp.tool`` is missing. Capability-only ids (not yet registered as
FastMCP tools) are intentional supersets for admin toggles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, FrozenSet, List, Literal, Tuple

__all__ = [
    "McpToolDescriptor",
    "McpToolset",
    "is_registered_mcp_tool",
    "mcp_tool_descriptors",
    "mcp_tool_ids",
    "mcp_tools_by_toolset",
]

McpToolset = Literal["health", "catalog", "search", "document", "structure"]


@dataclass(frozen=True)
class McpToolDescriptor:
    """One registered MCP tool or governance capability id.

    :param id: Stable MCP tool / capability identifier (e.g. ``spec.list``).
    :param description: Short human summary for admin UX and REST catalog.
    :param toolset: MVP toolset grouping for grouped enable/disable toggles.
    """

    id: str
    description: str
    toolset: McpToolset


_REGISTRY: Final[Tuple[McpToolDescriptor, ...]] = (
    McpToolDescriptor(
        id="ping",
        description=(
            "Smoke-test: service name, package version, Postgres reachability, UTC timestamp."
        ),
        toolset="health",
    ),
    McpToolDescriptor(
        id="project.list",
        description=(
            "List distinct projects that have at least one published spec revision the caller "
            "can see (cursor-paginated)."
        ),
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.list",
        description=(
            "List published OpenAPI specs with cursor pagination (public catalog; with API key, "
            "also in-scope private revisions)."
        ),
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.list_my_specs",
        description=(
            "List published specs visible to the caller's MCP API key (requires authentication)."
        ),
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.describe",
        description="Return metadata for a single published OpenAPI spec revision by id.",
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.list_tags",
        description="Distinct tag names across published public specs with counts (cursor-paginated).",
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.mcp",
        description=(
            "Governance capability: allow access to MCP catalog entries "
            "(not a live FastMCP tool handler until implemented)."
        ),
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.catalog",
        description=(
            "Governance capability: allow access to Catalog entries "
            "(not a live FastMCP tool handler until implemented)."
        ),
        toolset="catalog",
    ),
    McpToolDescriptor(
        id="spec.search",
        description="Full-text search over published public OpenAPI specs (Postgres tsquery).",
        toolset="search",
    ),
    McpToolDescriptor(
        id="spec.search_semantic",
        description=(
            "Semantic (embedding) search over published public specs with mcp_public_embedding set."
        ),
        toolset="search",
    ),
    McpToolDescriptor(
        id="spec.get_openapi",
        description="Return the generated OpenAPI 3.1 JSON document for a published revision.",
        toolset="document",
    ),
    McpToolDescriptor(
        id="spec.export_yaml",
        description="Return the generated OpenAPI 3.1 document as YAML for a published revision.",
        toolset="document",
    ),
    McpToolDescriptor(
        id="spec.list_operations",
        description=(
            "Compact index of HTTP operations (path, method, operation_id, summary, tags) for a revision."
        ),
        toolset="structure",
    ),
    McpToolDescriptor(
        id="spec.describe_operation",
        description=(
            "OpenAPI fragments for one operation: parameters, requestBody, responses, security."
        ),
        toolset="structure",
    ),
    McpToolDescriptor(
        id="spec.list_components",
        description=(
            "Component keys grouped by kind (schemas, parameters, responses, securitySchemes)."
        ),
        toolset="structure",
    ),
    McpToolDescriptor(
        id="spec.describe_component",
        description="Single OpenAPI component definition by kind + name (internal $ref expanded).",
        toolset="structure",
    ),
)

_IDS: Final[FrozenSet[str]] = frozenset(d.id for d in _REGISTRY)


def mcp_tool_descriptors() -> List[McpToolDescriptor]:
    """Return every registered descriptor in registry order (deterministic)."""
    return list(_REGISTRY)


def mcp_tool_ids() -> List[str]:
    """Return every registered tool / capability id in registry order."""
    return [d.id for d in _REGISTRY]


def is_registered_mcp_tool(tool_id: str) -> bool:
    """Return True when ``tool_id`` appears in the registry (exact match)."""
    return tool_id in _IDS


def mcp_tools_by_toolset(toolset: McpToolset) -> List[McpToolDescriptor]:
    """Return descriptors whose ``toolset`` matches, preserving registry order."""
    return [d for d in _REGISTRY if d.toolset == toolset]
