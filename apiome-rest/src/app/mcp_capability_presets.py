"""MCP capability profiles / presets — MTG-5.1 (#4785).

Named packs apply a toolset enable matrix in one click for tenant MCP policy
drafts (Tenants UI). ``custom`` is a UI sentinel only — it is not listed here.

Documented matrix: ``docs/MCP_CAPABILITY_PRESETS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, List, Optional, Sequence, Tuple

from .mcp_tool_registry import McpToolset

__all__ = [
    "McpCapabilityPreset",
    "CUSTOM_PRESET_ID",
    "enabled_toolsets_for",
    "list_presets",
    "preset_by_id",
]

CUSTOM_PRESET_ID: Final[str] = "custom"


@dataclass(frozen=True)
class McpCapabilityPreset:
    """One named capability pack (toolsets enabled on apply).

    :param id: Stable preset identifier (e.g. ``catalog_only``).
    :param label: Human label for admin UX.
    :param toolsets: Toolsets to set ``in_ceiling`` + ``default_enabled`` on apply.
    """

    id: str
    label: str
    toolsets: Tuple[McpToolset, ...]


_PRESETS: Final[Tuple[McpCapabilityPreset, ...]] = (
    McpCapabilityPreset(
        id="catalog_only",
        label="Catalog only",
        toolsets=("health", "catalog"),
    ),
    McpCapabilityPreset(
        id="search_catalog",
        label="Search + catalog",
        toolsets=("health", "catalog", "search"),
    ),
    McpCapabilityPreset(
        id="full_read",
        label="Full read",
        toolsets=("health", "catalog", "search", "document", "structure"),
    ),
)


def list_presets() -> List[McpCapabilityPreset]:
    """Return every named capability preset in display order."""
    return list(_PRESETS)


def preset_by_id(preset_id: str) -> Optional[McpCapabilityPreset]:
    """Look up a named preset by id, or ``None`` when unknown / ``custom``."""
    if preset_id == CUSTOM_PRESET_ID:
        return None
    for preset in _PRESETS:
        if preset.id == preset_id:
            return preset
    return None


def enabled_toolsets_for(preset_id: str) -> Optional[Sequence[McpToolset]]:
    """Return the enabled toolset list for ``preset_id``, or ``None`` if unknown."""
    preset = preset_by_id(preset_id)
    if preset is None:
        return None
    return preset.toolsets
