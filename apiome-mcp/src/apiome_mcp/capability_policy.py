"""Load tenant MCP policy snapshots for call-time gating (MTG-2.2 / #4771).

Key grants come from :class:`~apiome_mcp.mcp_auth.McpAuthContext` (MTG-1.3
columns on ``mcp_api_keys``). Tenant ceiling / defaults / anonymous flags come
from ``tenant_mcp_policies`` + ``tenant_mcp_policy_tools`` (MTG-1.2 + MTG-2.3).

**Policy freshness (MTG-2.5 / #4774):** policy is resolved from Postgres on
**every** authenticated ``tools/call`` (every call is authenticated). There
is no in-process policy cache. Callers may rely on
:data:`POLICY_FRESHNESS_LAG_BUDGET_SECONDS` (``0``): any call that starts after
a policy row's commit must see the new value without redeploying or restarting
the MCP process. See ``docs/POLICY_FRESHNESS.md``.

**One statement (DBP-1.21 / #7204):** the catalog key gate reads the key row,
the tenant policy row and *the called tool's* policy row in the same statement
(:data:`apiome_mcp.mcp_auth.KEY_AND_POLICY_COLUMNS`) and hands the result over
as a :class:`PrefetchedToolPolicy`, so the zero-lag budget costs no extra
round trip. The resolver only ever looks at the called tool's flags, so a
one-tool snapshot decides exactly like the full one.
:func:`load_tenant_mcp_policy_snapshot` remains the fallback when nothing was
prefetched (direct in-process calls, tests).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.effective_policy import (
    TenantDefaultMode,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
)

# Stable client-facing token embedded in ToolError / CallToolResult text.
CAPABILITY_DISABLED_CODE = "capability_disabled"

# MTG-2.5 (#4774): max seconds after a committed policy write before a new
# tools/call must observe it. Per-call DB read → 0. DBP-1.21 (#7204) kept it at
# 0 by folding the read into the key statement rather than caching it. A future
# TTL cache must keep this ≤ 30 and document the chosen budget.
POLICY_FRESHNESS_LAG_BUDGET_SECONDS = 0


@dataclass(frozen=True)
class PrefetchedToolPolicy:
    """The tenant policy for one tool, read in the same statement as the caller's key.

    Attributes:
        tool_name: The tool the policy was read for; it decides only a call to that tool.
        tenant: The tenant snapshot holding at most that tool's flags, or ``None`` when the tenant
            has no policy row (the resolvers' legacy-safe default).
    """

    tool_name: str
    tenant: TenantMcpPolicySnapshot | None


def capability_disabled_message(tool_name: str) -> str:
    """Human + machine-readable denial; never includes secrets or key material."""
    return (
        f"{CAPABILITY_DISABLED_CODE}: Tool '{tool_name}' is disabled for this API key. "
        "A tenant admin must enable it before it can be called."
    )


def _parse_default_mode(raw: Any) -> TenantDefaultMode:
    if raw == "inherit_registry":
        return "inherit_registry"
    if raw == "explicit":
        return "explicit"
    return "all"


def _tool_flags(row: Mapping[str, Any]) -> TenantToolFlags:
    """One ``tenant_mcp_policy_tools`` row's flags (``anonymous_enabled`` defaults to true)."""
    anonymous = row.get("anonymous_enabled")
    return TenantToolFlags(
        in_ceiling=bool(row["in_ceiling"]),
        default_enabled=bool(row["default_enabled"]),
        anonymous_enabled=True if anonymous is None else bool(anonymous),
    )


def prefetched_policy_from_row(row: Mapping[str, Any], tool_name: str) -> PrefetchedToolPolicy | None:
    """Read the policy columns the key statement joined in (see ``mcp_auth``).

    Args:
        row: A key row with ``has_policy``, ``default_mode``, ``allow_anonymous_mcp`` and the tool's
            ``policy_tool_id`` / ``in_ceiling`` / ``default_enabled`` / ``anonymous_enabled``.
        tool_name: The tool the statement joined.

    Returns:
        The prefetched policy, or ``None`` when the row carries no policy columns (then the
        capability gate loads the policy itself).
    """
    if "has_policy" not in row:
        return None
    if not row.get("has_policy"):
        return PrefetchedToolPolicy(tool_name=tool_name, tenant=None)
    tools: dict[str, TenantToolFlags] = {}
    if row.get("policy_tool_id") is not None:
        tools[str(row["policy_tool_id"])] = _tool_flags(row)
    allow = row.get("allow_anonymous_mcp")
    return PrefetchedToolPolicy(
        tool_name=tool_name,
        tenant=TenantMcpPolicySnapshot(
            default_mode=_parse_default_mode(row.get("default_mode")),
            tools=tools,
            allow_anonymous_mcp=True if allow is None else bool(allow),
        ),
    )


async def load_tenant_mcp_policy_snapshot(
    pool: AsyncConnectionPool,
    tenant_id: str,
) -> TenantMcpPolicySnapshot | None:
    """Load tenant policy for the MTG-1.4 / MTG-2.3 resolvers, or ``None`` if unseeded.

    A missing policy row is treated as ``default_mode=all`` / anonymous allowed
    by the resolvers (legacy-safe). Present rows may still have an empty tools map.

    **Freshness (MTG-2.5):** must query the database on every call. Do not
    memoize or process-cache results across ``tools/call`` invocations —
    callers rely on :data:`POLICY_FRESHNESS_LAG_BUDGET_SECONDS` (``0``).
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT default_mode, allow_anonymous_mcp
                FROM apiome.tenant_mcp_policies
                WHERE tenant_id = %s::uuid
                """,
                (tenant_id,),
            )
            policy = await cur.fetchone()
            if policy is None:
                return None

            await cur.execute(
                """
                SELECT tool_id, in_ceiling, default_enabled, anonymous_enabled
                FROM apiome.tenant_mcp_policy_tools
                WHERE tenant_id = %s::uuid
                """,
                (tenant_id,),
            )
            tool_rows = await cur.fetchall()

    tools: dict[str, TenantToolFlags] = {str(row["tool_id"]): _tool_flags(row) for row in tool_rows}
    return TenantMcpPolicySnapshot(
        default_mode=_parse_default_mode(policy.get("default_mode")),
        tools=tools,
        allow_anonymous_mcp=bool(policy.get("allow_anonymous_mcp", True)),
    )
