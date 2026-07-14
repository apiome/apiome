"""Load tenant MCP policy snapshots for call-time gating (MTG-2.2 / #4771).

Key grants come from :class:`~apiome_mcp.mcp_auth.McpAuthContext` (MTG-1.3
columns on ``mcp_api_keys``). Tenant ceiling / defaults / anonymous flags come
from ``tenant_mcp_policies`` + ``tenant_mcp_policy_tools`` (MTG-1.2 + MTG-2.3).

**Policy freshness (MTG-2.5 / #4774):** MVP resolves policy from Postgres on
**every** authenticated ``tools/call`` (and every gated anonymous call). There
is no in-process policy cache. Callers may rely on
:data:`POLICY_FRESHNESS_LAG_BUDGET_SECONDS` (``0``): any call that starts after
a policy row's commit must see the new value without redeploying or restarting
the MCP process. See ``docs/POLICY_FRESHNESS.md``.
"""

from __future__ import annotations

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
# tools/call must observe it. MVP = per-call DB load → 0. A future TTL cache
# must keep this ≤ 30 and document the chosen budget.
POLICY_FRESHNESS_LAG_BUDGET_SECONDS = 0


def capability_disabled_message(tool_name: str) -> str:
    """Human + machine-readable denial; never includes secrets or key material."""
    return (
        f"{CAPABILITY_DISABLED_CODE}: Tool '{tool_name}' is disabled for this API key. "
        "A tenant admin must enable it before it can be called."
    )


def capability_disabled_anonymous_message(tool_name: str) -> str:
    """Denial for anonymous callers (MTG-2.3); never says \"API key\"."""
    return (
        f"{CAPABILITY_DISABLED_CODE}: Tool '{tool_name}' is disabled for anonymous callers. "
        "A tenant admin must allow anonymous MCP access for this tool, "
        "or call with a valid API key."
    )


def _parse_default_mode(raw: Any) -> TenantDefaultMode:
    if raw == "inherit_registry":
        return "inherit_registry"
    if raw == "explicit":
        return "explicit"
    return "all"


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

    tools: dict[str, TenantToolFlags] = {
        str(row["tool_id"]): TenantToolFlags(
            in_ceiling=bool(row["in_ceiling"]),
            default_enabled=bool(row["default_enabled"]),
            anonymous_enabled=bool(row.get("anonymous_enabled", True)),
        )
        for row in tool_rows
    }
    return TenantMcpPolicySnapshot(
        default_mode=_parse_default_mode(policy.get("default_mode")),
        tools=tools,
        allow_anonymous_mcp=bool(policy.get("allow_anonymous_mcp", True)),
    )
