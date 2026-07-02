from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from psycopg_pool import AsyncConnectionPool

from apiome_mcp.key_admin import revoke_mcp_keys_by_prefix


def test_revoke_mcp_keys_by_prefix_returns_rowcount() -> None:
    cur = AsyncMock()
    cur.rowcount = 2
    cur.execute = AsyncMock()
    cm_cur = AsyncMock()
    cm_cur.__aenter__ = AsyncMock(return_value=cur)
    cm_cur.__aexit__ = AsyncMock(return_value=None)

    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cm_cur)
    conn.commit = AsyncMock()

    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> int:
        return await revoke_mcp_keys_by_prefix(pool, "abcdefghijkl...")

    assert asyncio.run(run()) == 2
    cur.execute.assert_awaited_once()
    conn.commit.assert_awaited_once()
