"""Load tenant MCP policy snapshots for call-time gating (MTG-2.2 / #4771).

Key grants come from :class:`~apiome_mcp.mcp_auth.McpAuthContext` (MTG-1.3
columns on ``mcp_api_keys``). Tenant ceiling / defaults come from
``tenant_mcp_policies`` + ``tenant_mcp_policy_tools`` (MTG-1.2).
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


async def load_tenant_mcp_policy_snapshot(
    pool: AsyncConnectionPool,
    tenant_id: str,
) -> TenantMcpPolicySnapshot | None:
    """Load tenant policy for the MTG-1.4 resolver, or ``None`` if unseeded.

    A missing policy row is treated as ``default_mode=all`` by the resolver
    (legacy-safe). Present rows may still have an empty tools map.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT default_mode
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
                SELECT tool_id, in_ceiling, default_enabled
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
        )
        for row in tool_rows
    }
    return TenantMcpPolicySnapshot(
        default_mode=_parse_default_mode(policy.get("default_mode")),
        tools=tools,
    )
