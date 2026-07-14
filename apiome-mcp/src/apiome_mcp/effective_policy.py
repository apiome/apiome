"""Re-export MTG-1.4 effective policy resolver from apiome-rest.

Call-time middleware (MTG-2.2) and any MCP-side previews import from here
(or directly from ``app.mcp_effective_policy``) so REST preview and MCP
gates stay on one implementation.
"""

from __future__ import annotations

from app.mcp_effective_policy import (
    CapabilityMode,
    DenyReason,
    EffectiveToolPreview,
    KeyCapabilitySnapshot,
    TenantDefaultMode,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
    is_tool_effectively_enabled,
    preview_effective_tools,
    resolve_tool_effective,
    tool_in_ceiling,
    tool_in_default_enable_set,
)

__all__ = [
    "CapabilityMode",
    "DenyReason",
    "EffectiveToolPreview",
    "KeyCapabilitySnapshot",
    "TenantDefaultMode",
    "TenantMcpPolicySnapshot",
    "TenantToolFlags",
    "is_tool_effectively_enabled",
    "preview_effective_tools",
    "resolve_tool_effective",
    "tool_in_ceiling",
    "tool_in_default_enable_set",
]
