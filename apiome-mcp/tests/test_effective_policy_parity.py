"""Golden parity: MCP package shares REST MTG-1.4 resolver (#4768)."""

from __future__ import annotations

import app.mcp_effective_policy as rest_policy

from apiome_mcp.effective_policy import (
    DenyReason,
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
    is_tool_effectively_enabled,
    preview_effective_tools,
    resolve_tool_effective,
)

_REG = frozenset({"ping", "spec.list", "spec.search"})


def _case_fixtures():
    tenant = TenantMcpPolicySnapshot(
        default_mode="explicit",
        tools={
            "ping": TenantToolFlags(in_ceiling=True, default_enabled=True),
            "spec.list": TenantToolFlags(in_ceiling=True, default_enabled=False),
            "spec.search": TenantToolFlags(in_ceiling=False, default_enabled=False),
        },
    )
    inherit = KeyCapabilitySnapshot(capability_mode="inherit", enabled_tools=frozenset())
    explicit = KeyCapabilitySnapshot(
        capability_mode="explicit",
        enabled_tools=frozenset({"ping", "spec.list", "spec.search"}),
    )
    return tenant, inherit, explicit


def test_mcp_reexport_matches_rest_resolve():
    tenant, inherit, explicit = _case_fixtures()
    for tool in ("ping", "spec.list", "spec.search", "ghost"):
        for key in (inherit, explicit):
            mcp = resolve_tool_effective(tool, key=key, tenant=tenant, registry=_REG)
            rest = rest_policy.resolve_tool_effective(tool, key=key, tenant=tenant, registry=_REG)
            assert mcp == rest
            assert is_tool_effectively_enabled(
                tool, key=key, tenant=tenant, registry=_REG
            ) is rest_policy.is_tool_effectively_enabled(tool, key=key, tenant=tenant, registry=_REG)


def test_mcp_preview_matches_rest_preview():
    tenant, _, explicit = _case_fixtures()
    order = ("ping", "spec.list", "spec.search")
    mcp_rows = preview_effective_tools(key=explicit, tenant=tenant, registry=order)
    rest_rows = rest_policy.preview_effective_tools(key=explicit, tenant=tenant, registry=order)
    assert [(r.tool_id, r.enabled, r.deny_reason) for r in mcp_rows] == [
        (r.tool_id, r.enabled, r.deny_reason) for r in rest_rows
    ]
    # Spot-check expected decisions (ceiling + explicit listing)
    by_id = {r.tool_id: r for r in mcp_rows}
    assert by_id["ping"].enabled is True
    assert by_id["spec.list"].enabled is True
    assert by_id["spec.search"].enabled is False
    assert by_id["spec.search"].deny_reason is DenyReason.NOT_IN_CEILING
