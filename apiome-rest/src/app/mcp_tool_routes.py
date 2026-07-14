"""MCP tool catalog and capability presets under ``/api-keys``.

Exposes the shared :mod:`app.mcp_tool_registry` as a read-only list so the CLI
(``GET /api-keys/mcp-tools``) and Control Panel can enumerate stable tool ids,
descriptions, and toolset membership for governance UX (MTG-1.1, #4765).

Also exposes named capability profiles (``GET /api-keys/mcp-capability-presets``)
for one-click draft policy matrices (MTG-5.1, #4785).
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import validate_session_credentials
from .mcp_capability_presets import list_presets
from .mcp_tool_registry import mcp_tool_descriptors

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class McpToolCatalogItem(BaseModel):
    """One MCP tool or governance capability from the registry."""

    id: str = Field(description="Stable MCP tool / capability identifier (e.g. spec.list).")
    description: str = Field(description="Short human summary for admin UX.")
    toolset: str = Field(
        description="MVP toolset grouping: health, catalog, search, document, or structure.",
    )


class McpToolCatalogResponse(BaseModel):
    """Full MCP tool & capability catalog (MTG-1.1)."""

    tools: List[McpToolCatalogItem] = Field(
        description="Every registered tool / capability id, in registry order.",
    )


class McpCapabilityPresetItem(BaseModel):
    """One named capability profile / preset (MTG-5.1)."""

    id: str = Field(description="Stable preset identifier (e.g. catalog_only).")
    label: str = Field(description="Human label for admin UX.")
    toolsets: List[str] = Field(
        description="Toolsets enabled (in_ceiling + default_enabled) when the preset is applied.",
    )


class McpCapabilityPresetsResponse(BaseModel):
    """Named MCP capability presets (MTG-5.1). Custom is a UI sentinel only."""

    presets: List[McpCapabilityPresetItem] = Field(
        description="Named packs in display order; see docs/MCP_CAPABILITY_PRESETS.md.",
    )


@router.get(
    "/mcp-tools",
    response_model=McpToolCatalogResponse,
    summary="List MCP tools and toolsets",
    description=(
        "Enumerate every registered Apiome MCP tool id (and planned capability ids such as "
        "spec.mcp / spec.catalog), with description and toolset membership for admin "
        "enable/disable UX (MTG-1.1, #4765). Same source of truth as apiome-mcp call-time "
        "fail-closed checks."
    ),
)
async def list_mcp_tools(
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> McpToolCatalogResponse:
    """Return the shared MCP tool registry as a REST catalog."""
    _ = auth_data
    return McpToolCatalogResponse(
        tools=[
            McpToolCatalogItem(id=d.id, description=d.description, toolset=d.toolset)
            for d in mcp_tool_descriptors()
        ]
    )


@router.get(
    "/mcp-capability-presets",
    response_model=McpCapabilityPresetsResponse,
    summary="List MCP capability presets",
    description=(
        "Enumerate named capability profiles (Catalog only, Search + catalog, Full read) "
        "with the documented toolset enable matrix for tenant MCP policy drafts "
        "(MTG-5.1, #4785). Custom is not listed — it is a UI sentinel for non-matching drafts."
    ),
)
async def list_mcp_capability_presets(
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> McpCapabilityPresetsResponse:
    """Return the documented capability preset matrix."""
    _ = auth_data
    return McpCapabilityPresetsResponse(
        presets=[
            McpCapabilityPresetItem(
                id=p.id,
                label=p.label,
                toolsets=list(p.toolsets),
            )
            for p in list_presets()
        ]
    )
