"""Append-only audit for authenticated MCP capability denials (MTG-2.4 / #4773).

Never persist tool arguments, Authorization headers, or secrets—only
key_id, tenant_id, tool_id, transport, and DenyReason.
"""

from __future__ import annotations

import asyncio
from typing import Literal

import structlog
from fastmcp.server.dependencies import get_http_request
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

TransportLiteral = Literal["stdio", "http"]

_DEFAULT_REASON = "capability_disabled"

__all__ = [
    "detect_mcp_transport",
    "insert_mcp_capability_denial",
    "schedule_mcp_capability_denial",
]


def detect_mcp_transport() -> TransportLiteral:
    """Return ``http`` when an active HTTP request exists, else ``stdio``."""
    try:
        get_http_request()
    except RuntimeError:
        return "stdio"
    return "http"


async def insert_mcp_capability_denial(
    pool: AsyncConnectionPool,
    *,
    key_id: str | None,
    tenant_id: str,
    tool_id: str,
    transport: TransportLiteral,
    reason: str,
) -> None:
    """Persist one denial row; callers should use :func:`schedule_mcp_capability_denial`."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO apiome.mcp_capability_denials
                (key_id, tenant_id, tool_id, at, transport, reason)
            VALUES (%s::uuid, %s::uuid, %s, CURRENT_TIMESTAMP, %s, %s)
            """,
            (key_id, tenant_id, tool_id, transport, reason),
        )
        await conn.commit()


def schedule_mcp_capability_denial(
    pool: AsyncConnectionPool,
    *,
    key_id: str | None,
    tenant_id: str,
    tool_id: str,
    transport: TransportLiteral,
    reason: str | None,
) -> None:
    """Fire-and-forget denial insert so the tools/call error path stays fast."""
    resolved_reason = (reason or "").strip() or _DEFAULT_REASON

    async def _run() -> None:
        try:
            await insert_mcp_capability_denial(
                pool,
                key_id=key_id,
                tenant_id=tenant_id,
                tool_id=tool_id,
                transport=transport,
                reason=resolved_reason,
            )
        except Exception:
            _log.warning(
                "mcp_capability_denial_insert_failed",
                key_id=key_id,
                tenant_id=tenant_id,
                tool_id=tool_id,
                transport=transport,
                reason=resolved_reason,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug(
            "mcp_capability_denial_skip_no_event_loop",
            key_id=key_id,
            tenant_id=tenant_id,
            tool_id=tool_id,
            transport=transport,
            reason=resolved_reason,
        )
