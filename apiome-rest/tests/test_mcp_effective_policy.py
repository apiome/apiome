"""Effective policy resolver tests — MTG-1.4 (#4768).

Table-driven matrix: registry ∩ ceiling ∩ (inherit defaults | explicit key).
"""

from __future__ import annotations

from typing import Optional

import pytest

from app.mcp_effective_policy import (
    DenyReason,
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
    is_tool_effectively_enabled,
    preview_effective_tools,
    resolve_tool_effective,
    tool_in_ceiling,
    tool_in_default_enable_set,
)

# Small fixed catalog so combinations stay readable (not the live registry).
_REG = frozenset({"ping", "spec.list", "spec.search", "spec.mcp"})


def _flags(ceiling: bool, default: bool) -> TenantToolFlags:
    return TenantToolFlags(in_ceiling=ceiling, default_enabled=default)


def _tenant(mode: str, tools: Optional[dict] = None) -> TenantMcpPolicySnapshot:
    return TenantMcpPolicySnapshot(default_mode=mode, tools=tools or {})  # type: ignore[arg-type]


def _key(mode: str, enabled: Optional[set] = None) -> KeyCapabilitySnapshot:
    return KeyCapabilitySnapshot(
        capability_mode=mode,  # type: ignore[arg-type]
        enabled_tools=frozenset(enabled or ()),
    )


# ---------------------------------------------------------------------------
# Matrix: ≥12 combinations of inherit/explicit × ceiling/defaults × modes
# Each row: (id, tool, tenant, key, expected_enabled, expected_deny_or_None)
# ---------------------------------------------------------------------------
_MATRIX = [
    # 1 registry miss (always deny)
    (
        "unknown_tool",
        "ghost.tool",
        _tenant("all"),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_REGISTRY,
    ),
    # 2 legacy / unseeded tenant (None) + inherit → full allow for registry tools
    (
        "legacy_unseeded_inherit",
        "ping",
        None,
        _key("inherit"),
        True,
        None,
    ),
    # 3 default_mode=all ignores empty/partial rows under inherit
    (
        "all_mode_inherit_ignores_rows",
        "spec.list",
        _tenant(
            "all",
            {"spec.list": _flags(False, False)},  # would deny under explicit
        ),
        _key("inherit"),
        True,
        None,
    ),
    # 4 all + explicit key with tool listed
    (
        "all_mode_explicit_listed",
        "spec.search",
        _tenant("all"),
        _key("explicit", {"spec.search"}),
        True,
        None,
    ),
    # 5 all + explicit key without tool
    (
        "all_mode_explicit_missing",
        "spec.search",
        _tenant("all"),
        _key("explicit", {"ping"}),
        False,
        DenyReason.NOT_IN_KEY_ENABLE_SET,
    ),
    # 6 explicit policy: not in ceiling even when inherit + default would want it
    (
        "explicit_ceiling_blocks_inherit",
        "spec.list",
        _tenant(
            "explicit",
            {
                "ping": _flags(True, True),
                "spec.list": _flags(False, False),
            },
        ),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_CEILING,
    ),
    # 7 explicit policy: in ceiling but not default-enabled → inherit deny
    (
        "explicit_default_off_inherit",
        "spec.list",
        _tenant(
            "explicit",
            {
                "spec.list": _flags(True, False),
                "ping": _flags(True, True),
            },
        ),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_DEFAULT_ENABLE_SET,
    ),
    # 8 explicit policy: ceiling + default → inherit allow
    (
        "explicit_default_on_inherit",
        "ping",
        _tenant("explicit", {"ping": _flags(True, True)}),
        _key("inherit"),
        True,
        None,
    ),
    # 9 explicit policy + explicit key can enable a ceiling member even if not default
    (
        "explicit_key_overrides_default",
        "spec.list",
        _tenant(
            "explicit",
            {
                "spec.list": _flags(True, False),
                "ping": _flags(True, True),
            },
        ),
        _key("explicit", {"spec.list"}),
        True,
        None,
    ),
    # 10 explicit key cannot exceed ceiling (defense in depth)
    (
        "explicit_key_blocked_by_ceiling",
        "spec.mcp",
        _tenant(
            "explicit",
            {
                "ping": _flags(True, True),
                "spec.mcp": _flags(False, False),
            },
        ),
        _key("explicit", {"spec.mcp"}),
        False,
        DenyReason.NOT_IN_CEILING,
    ),
    # 11 inherit_registry: absent rows track registry (allow)
    (
        "inherit_registry_absent_row",
        "spec.search",
        _tenant("inherit_registry", {"ping": _flags(True, True)}),
        _key("inherit"),
        True,
        None,
    ),
    # 12 inherit_registry: in_ceiling=false denies
    (
        "inherit_registry_ceiling_off",
        "spec.search",
        _tenant(
            "inherit_registry",
            {"spec.search": _flags(False, False)},
        ),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_CEILING,
    ),
    # 13 inherit_registry: default_enabled=false under inherit
    (
        "inherit_registry_default_off",
        "spec.search",
        _tenant(
            "inherit_registry",
            {"spec.search": _flags(True, False)},
        ),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_DEFAULT_ENABLE_SET,
    ),
    # 14 explicit policy: absent tool row is out of ceiling
    (
        "explicit_absent_row",
        "spec.search",
        _tenant("explicit", {"ping": _flags(True, True)}),
        _key("inherit"),
        False,
        DenyReason.NOT_IN_CEILING,
    ),
    # 15 legacy unseeded + explicit key subset
    (
        "legacy_explicit_subset",
        "ping",
        None,
        _key("explicit", {"ping"}),
        True,
        None,
    ),
]


@pytest.mark.parametrize(
    "case_id,tool,tenant,key,expected,deny",
    _MATRIX,
    ids=[row[0] for row in _MATRIX],
)
def test_resolve_matrix(case_id, tool, tenant, key, expected, deny):
    assert len(_MATRIX) >= 12
    enabled, reason = resolve_tool_effective(
        tool, key=key, tenant=tenant, registry=_REG
    )
    assert enabled is expected, case_id
    assert reason is deny, case_id
    assert (
        is_tool_effectively_enabled(tool, key=key, tenant=tenant, registry=_REG)
        is expected
    )


def test_preview_matches_per_tool_resolver():
    """REST preview must match MCP gate decisions for every registry tool."""
    tenant = _tenant(
        "explicit",
        {
            "ping": _flags(True, True),
            "spec.list": _flags(True, False),
            "spec.search": _flags(False, False),
        },
    )
    key = _key("explicit", {"ping", "spec.list", "spec.search"})
    order = ("ping", "spec.list", "spec.search", "spec.mcp")
    preview = preview_effective_tools(key=key, tenant=tenant, registry=order)
    assert [row.tool_id for row in preview] == list(order)
    for row in preview:
        gate = is_tool_effectively_enabled(
            row.tool_id, key=key, tenant=tenant, registry=_REG
        )
        assert row.enabled is gate
        resolved, reason = resolve_tool_effective(
            row.tool_id, key=key, tenant=tenant, registry=_REG
        )
        assert row.enabled is resolved
        assert row.deny_reason is reason


def test_ceiling_and_defaults_helpers_for_all_mode():
    tenant = _tenant("all", {"ping": _flags(False, False)})
    assert tool_in_ceiling("ping", tenant, registry=_REG) is True
    assert tool_in_default_enable_set("ping", tenant, registry=_REG) is True
    assert tool_in_ceiling("ghost", tenant, registry=_REG) is False


def test_preview_uses_live_registry_order_by_default():
    preview = preview_effective_tools(key=_key("inherit"), tenant=None)
    assert preview
    assert all(row.enabled for row in preview)
    assert all(row.deny_reason is None for row in preview)
