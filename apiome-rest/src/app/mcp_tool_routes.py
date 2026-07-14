"""MCP tool catalog under ``/api-keys`` — MTG-1.1 (#4765).

Exposes the shared :mod:`app.mcp_tool_registry` as a read-only list so the CLI
(``GET /api-keys/mcp-tools``) and Control Panel can enumerate stable tool ids,
descriptions, and toolset membership for governance UX.

Full ``/api-keys`` CRUD lives in later tickets; this module only serves the
catalog endpoint the CLI already consumes.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import validate_session_credentials
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
