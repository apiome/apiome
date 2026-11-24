"""Append-only audit for MCP reads of private published revisions (#3013).

When the lifespan registered an :class:`~apiome_mcp.audit_writer.AuditWriter` for the pool
(DBP-1.21), the ``schedule_*`` helpers only queue the rows; the writer persists a whole list page
— and every other audit row of the moment — in one multi-row INSERT. Without one (CLI, unit
tests) they fall back to a background insert of their own.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Sequence

import structlog
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.audit_writer import audit_writer_for

_log = structlog.get_logger(__name__)


async def insert_mcp_access_audit(
    pool: AsyncConnectionPool,
    *,
    key_id: str,
    tool: str,
    spec_id: str,
    success: bool,
    error: str | None,
) -> None:
    """Persist one audit row; callers should use :func:`schedule_mcp_private_access_audit` from tools."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO apiome.mcp_access_audit (key_id, tool, spec_id, at, success, error)
            VALUES (%s::uuid, %s, %s::uuid, CURRENT_TIMESTAMP, %s, %s)
            """,
            (key_id, tool, spec_id, success, error),
        )
        await conn.commit()


async def insert_mcp_access_audit_batch(
    pool: AsyncConnectionPool,
    *,
    key_id: str,
    tool: str,
    spec_ids: Sequence[str],
    success: bool,
    error: str | None,
) -> None:
    """Persist one audit row per spec_id in a single INSERT; callers should use
    :func:`schedule_mcp_private_access_audit_batch` from tools."""
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO apiome.mcp_access_audit (key_id, tool, spec_id, at, success, error)
            SELECT %s::uuid, %s, unnest(%s::uuid[]), CURRENT_TIMESTAMP, %s, %s
            """,
            (key_id, tool, list(spec_ids), success, error),
        )
        await conn.commit()


def schedule_mcp_private_access_audit(
    pool: AsyncConnectionPool,
    *,
    key_id: str,
    tool: str,
    spec_id: str,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Fire-and-forget audit insert so MCP tool latency stays low."""
    writer = audit_writer_for(pool)
    if writer is not None:
        writer.submit("mcp_access_audit", (key_id, tool, spec_id, datetime.now(UTC), success, error))
        return

    async def _run() -> None:
        try:
            await insert_mcp_access_audit(
                pool,
                key_id=key_id,
                tool=tool,
                spec_id=spec_id,
                success=success,
                error=error,
            )
        except Exception:
            _log.warning(
                "mcp_access_audit_insert_failed",
                key_id=key_id,
                tool=tool,
                spec_id=spec_id,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug(
            "mcp_access_audit_skip_no_event_loop",
            key_id=key_id,
            tool=tool,
            spec_id=spec_id,
            success=success,
            error=error,
        )


def schedule_mcp_private_access_audit_batch(
    pool: AsyncConnectionPool,
    *,
    key_id: str,
    tool: str,
    spec_ids: Sequence[str],
    success: bool = True,
    error: str | None = None,
) -> None:
    """Fire-and-forget batch audit insert (one DB round-trip for the whole page)."""
    if not spec_ids:
        return
    writer = audit_writer_for(pool)
    if writer is not None:
        at = datetime.now(UTC)
        writer.submit_group([("mcp_access_audit", (key_id, tool, sid, at, success, error)) for sid in spec_ids])
        return

    async def _run() -> None:
        try:
            await insert_mcp_access_audit_batch(
                pool,
                key_id=key_id,
                tool=tool,
                spec_ids=spec_ids,
                success=success,
                error=error,
            )
        except Exception:
            _log.warning(
                "mcp_access_audit_batch_insert_failed",
                key_id=key_id,
                tool=tool,
                spec_ids=list(spec_ids),
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug(
            "mcp_access_audit_skip_no_event_loop",
            key_id=key_id,
            tool=tool,
            spec_ids=list(spec_ids),
            success=success,
            error=error,
        )
