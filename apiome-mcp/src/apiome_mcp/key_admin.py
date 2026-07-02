"""MCP API key lifecycle helpers used by the CLI (#3002)."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


async def revoke_mcp_keys_by_prefix(pool: AsyncConnectionPool, prefix: str) -> int:
    """Set ``revoked_at`` for all active keys matching ``prefix``; return rows updated."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE apiome.mcp_api_keys
                SET revoked_at = CURRENT_TIMESTAMP
                WHERE prefix = %s AND revoked_at IS NULL
                """,
                (prefix,),
            )
            count = int(cur.rowcount or 0)
        await conn.commit()
        return count
