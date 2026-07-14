"""MTG-1.5 (#4769) upgrade regression: pre-migration MCP key still allows all tools.

After V163, every tenant is seeded with ``default_mode=all`` (empty tool rows =
full MTG-1.1 registry) and legacy keys use ``capability_mode=inherit``. The
effective-policy resolver is the enforceable contract until MTG-2.2 wires the
``tools/call`` gate — if every registry tool is enabled here, existing call
flows stay open and mcp-quickstart remains valid without admin policy edits.
"""

from __future__ import annotations

from app.mcp_effective_policy import (
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    is_tool_effectively_enabled,
    preview_effective_tools,
    resolve_tool_effective,
)
from app.mcp_tool_registry import mcp_tool_ids


def _pre_migration_key() -> KeyCapabilitySnapshot:
    """Shape of an mcp_api_keys row after V162/V163 inherit affirmation."""
    return KeyCapabilitySnapshot(
        capability_mode="inherit",
        enabled_tools=frozenset(),
    )


def _post_seed_tenant() -> TenantMcpPolicySnapshot:
    """Shape after ``seed_tenant_mcp_policy``: default_mode=all, no tool rows."""
    return TenantMcpPolicySnapshot(default_mode="all", tools={})


def test_pre_migration_inherit_key_enables_all_registry_tools() -> None:
    """Authenticate-equivalent: inherit key + seeded tenant → all tools succeed."""
    key = _pre_migration_key()
    tenant = _post_seed_tenant()
    registry = frozenset(mcp_tool_ids())

    assert registry, "MTG-1.1 registry must not be empty"

    for tool_id in registry:
        enabled, reason = resolve_tool_effective(
            tool_id, key=key, tenant=tenant, registry=registry
        )
        assert enabled is True, f"{tool_id} denied: {reason}"
        assert reason is None
        assert (
            is_tool_effectively_enabled(
                tool_id, key=key, tenant=tenant, registry=registry
            )
            is True
        )


def test_pre_migration_preview_matches_full_registry() -> None:
    key = _pre_migration_key()
    tenant = _post_seed_tenant()
    preview = preview_effective_tools(key=key, tenant=tenant)

    assert [row.tool_id for row in preview] == list(mcp_tool_ids())
    assert all(row.enabled for row in preview)
    assert all(row.deny_reason is None for row in preview)
