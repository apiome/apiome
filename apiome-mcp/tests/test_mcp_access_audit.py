from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_access_audit import (
    insert_mcp_access_audit,
    insert_mcp_access_audit_batch,
    schedule_mcp_private_access_audit,
    schedule_mcp_private_access_audit_batch,
)


def test_insert_mcp_access_audit_executes_insert() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> None:
        await insert_mcp_access_audit(
            pool,
            key_id="00000000-0000-4000-8000-000000000001",
            tool="spec.list",
            spec_id="11111111-1111-4111-8111-111111111111",
            success=True,
            error=None,
        )

    asyncio.run(run())
    conn.execute.assert_awaited_once()
    conn.commit.assert_awaited_once()


def test_insert_mcp_access_audit_batch_executes_single_insert() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)

    spec_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]

    async def run() -> None:
        await insert_mcp_access_audit_batch(
            pool,
            key_id="00000000-0000-4000-8000-000000000001",
            tool="spec.list",
            spec_ids=spec_ids,
            success=True,
            error=None,
        )

    asyncio.run(run())
    # Only one INSERT regardless of the number of spec_ids
    conn.execute.assert_awaited_once()
    conn.commit.assert_awaited_once()
    _sql, params = conn.execute.await_args.args
    assert params[2] == spec_ids


def test_schedule_mcp_private_access_audit_creates_background_task() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    async def run_inner() -> None:
        with patch("apiome_mcp.mcp_access_audit.insert_mcp_access_audit", new=AsyncMock()) as ins:
            schedule_mcp_private_access_audit(
                pool,
                key_id="00000000-0000-4000-8000-000000000002",
                tool="spec.describe",
                spec_id="22222222-2222-4222-8222-222222222222",
            )
            await asyncio.sleep(0)
            ins.assert_awaited_once_with(
                pool,
                key_id="00000000-0000-4000-8000-000000000002",
                tool="spec.describe",
                spec_id="22222222-2222-4222-8222-222222222222",
                success=True,
                error=None,
            )

    asyncio.run(run_inner())


def test_schedule_mcp_private_access_audit_skip_includes_spec_id_and_success() -> None:
    """When there is no running event loop the skip log must include spec_id, success, error."""
    import structlog.testing

    pool = MagicMock(spec=AsyncConnectionPool)

    with patch("apiome_mcp.mcp_access_audit.asyncio") as mock_asyncio:
        mock_asyncio.get_running_loop.side_effect = RuntimeError("no loop")

        with structlog.testing.capture_logs() as captured:
            schedule_mcp_private_access_audit(
                pool,
                key_id="00000000-0000-4000-8000-000000000003",
                tool="spec.describe",
                spec_id="33333333-3333-4333-8333-333333333333",
                success=False,
                error="some error",
            )

    skip_events = [e for e in captured if e.get("event") == "mcp_access_audit_skip_no_event_loop"]
    assert skip_events, "Expected a skip log event"
    ev = skip_events[0]
    assert ev["spec_id"] == "33333333-3333-4333-8333-333333333333"
    assert ev["success"] is False
    assert ev["error"] == "some error"


def test_schedule_mcp_private_access_audit_batch_creates_background_task() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    spec_ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]

    async def run_inner() -> None:
        with patch("apiome_mcp.mcp_access_audit.insert_mcp_access_audit_batch", new=AsyncMock()) as ins:
            schedule_mcp_private_access_audit_batch(
                pool,
                key_id="00000000-0000-4000-8000-000000000004",
                tool="spec.list",
                spec_ids=spec_ids,
            )
            await asyncio.sleep(0)
            ins.assert_awaited_once_with(
                pool,
                key_id="00000000-0000-4000-8000-000000000004",
                tool="spec.list",
                spec_ids=spec_ids,
                success=True,
                error=None,
            )

    asyncio.run(run_inner())


def test_schedule_mcp_private_access_audit_batch_noop_for_empty_list() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    async def run_inner() -> None:
        with patch("apiome_mcp.mcp_access_audit.insert_mcp_access_audit_batch", new=AsyncMock()) as ins:
            schedule_mcp_private_access_audit_batch(
                pool,
                key_id="00000000-0000-4000-8000-000000000005",
                tool="spec.list",
                spec_ids=[],
            )
            await asyncio.sleep(0)
            ins.assert_not_awaited()

    asyncio.run(run_inner())
