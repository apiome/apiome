"""Denied-call audit trail — MTG-2.4 (#4773)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import structlog.testing
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_capability_denial_audit import (
    detect_mcp_transport,
    insert_mcp_capability_denial,
    schedule_mcp_capability_denial,
)


def test_detect_mcp_transport_http_when_request_present() -> None:
    with patch(
        "apiome_mcp.mcp_capability_denial_audit.get_http_request",
        return_value=MagicMock(),
    ):
        assert detect_mcp_transport() == "http"


def test_detect_mcp_transport_stdio_when_no_request() -> None:
    with patch(
        "apiome_mcp.mcp_capability_denial_audit.get_http_request",
        side_effect=RuntimeError("No active HTTP request found."),
    ):
        assert detect_mcp_transport() == "stdio"


def test_insert_mcp_capability_denial_executes_insert() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> None:
        await insert_mcp_capability_denial(
            pool,
            key_id="00000000-0000-4000-8000-000000000001",
            tenant_id="11111111-1111-4111-8111-111111111111",
            tool_id="spec.search",
            transport="stdio",
            reason="not_in_key_enable_set",
        )

    asyncio.run(run())
    conn.execute.assert_awaited_once()
    conn.commit.assert_awaited_once()
    sql, params = conn.execute.await_args.args
    assert "mcp_capability_denials" in sql
    assert "key_id" in sql
    assert "tenant_id" in sql
    assert "tool_id" in sql
    assert "transport" in sql
    assert "reason" in sql
    assert "argument" not in sql.lower()
    assert "secret" not in sql.lower()
    assert params == (
        "00000000-0000-4000-8000-000000000001",
        "11111111-1111-4111-8111-111111111111",
        "spec.search",
        "stdio",
        "not_in_key_enable_set",
    )


def test_insert_allows_null_key_id() -> None:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> None:
        await insert_mcp_capability_denial(
            pool,
            key_id=None,
            tenant_id="11111111-1111-4111-8111-111111111111",
            tool_id="ping",
            transport="http",
            reason="not_in_ceiling",
        )

    asyncio.run(run())
    _sql, params = conn.execute.await_args.args
    assert params[0] is None


def test_schedule_mcp_capability_denial_creates_background_task() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    async def run_inner() -> None:
        with patch(
            "apiome_mcp.mcp_capability_denial_audit.insert_mcp_capability_denial",
            new=AsyncMock(),
        ) as ins:
            schedule_mcp_capability_denial(
                pool,
                key_id="00000000-0000-4000-8000-000000000002",
                tenant_id="11111111-1111-4111-8111-111111111111",
                tool_id="spec.list",
                transport="http",
                reason="not_in_key_enable_set",
            )
            await asyncio.sleep(0)
            ins.assert_awaited_once_with(
                pool,
                key_id="00000000-0000-4000-8000-000000000002",
                tenant_id="11111111-1111-4111-8111-111111111111",
                tool_id="spec.list",
                transport="http",
                reason="not_in_key_enable_set",
            )

    asyncio.run(run_inner())


def test_schedule_uses_capability_disabled_fallback_when_reason_missing() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    async def run_inner() -> None:
        with patch(
            "apiome_mcp.mcp_capability_denial_audit.insert_mcp_capability_denial",
            new=AsyncMock(),
        ) as ins:
            schedule_mcp_capability_denial(
                pool,
                key_id="00000000-0000-4000-8000-000000000003",
                tenant_id="11111111-1111-4111-8111-111111111111",
                tool_id="ping",
                transport="stdio",
                reason=None,
            )
            await asyncio.sleep(0)
            assert ins.await_args.kwargs["reason"] == "capability_disabled"

    asyncio.run(run_inner())


def test_schedule_skips_when_no_event_loop() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)

    with patch("apiome_mcp.mcp_capability_denial_audit.asyncio") as mock_asyncio:
        mock_asyncio.get_running_loop.side_effect = RuntimeError("no loop")

        with structlog.testing.capture_logs() as captured:
            schedule_mcp_capability_denial(
                pool,
                key_id="00000000-0000-4000-8000-000000000004",
                tenant_id="11111111-1111-4111-8111-111111111111",
                tool_id="spec.search",
                transport="stdio",
                reason="not_in_registry",
            )

    skip_events = [e for e in captured if e.get("event") == "mcp_capability_denial_skip_no_event_loop"]
    assert skip_events
    ev = skip_events[0]
    assert ev["tool_id"] == "spec.search"
    assert ev["reason"] == "not_in_registry"
    assert "argument" not in ev
    assert "authorization" not in ev
