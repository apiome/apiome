from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_describe_tool import build_spec_describe_response


def _sample_row(
    *,
    spec_id: UUID | None = None,
    updated_at: datetime | None = None,
    owner: str = "acme",
    spec_visibility: str = "public",
) -> dict[str, object]:
    sid = spec_id or uuid4()
    ts = updated_at or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    return {
        "id": sid,
        "title": "Payments API",
        "version": "2.1.0",
        "description": "Core payment flows",
        "owner": owner,
        "tags": ["stable"],
        "updated_at": ts,
        "spec_visibility": spec_visibility,
    }


def _pool_mock_for_fetchone(row: dict[str, object] | None) -> tuple[MagicMock, MagicMock]:
    pool = MagicMock(spec=AsyncConnectionPool)
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value=row)
    cur_cm = AsyncMock()
    cur_cm.__aenter__.return_value = cur
    cur_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)
    return pool, cur


def test_build_spec_describe_response_success() -> None:
    sid = uuid4()
    row = _sample_row(spec_id=sid)
    pool, cur = _pool_mock_for_fetchone(row)

    async def run() -> dict[str, object]:
        return await build_spec_describe_response(pool, spec_id=str(sid))

    out = asyncio.run(run())

    assert out["id"] == str(sid)
    assert out["title"] == "Payments API"
    assert out["version"] == "2.1.0"
    assert out["description"] == "Core payment flows"
    assert out["owner"] == "acme"
    assert out["tags"] == ["stable"]
    assert out["updated_at"] == "2026-05-01T12:00:00Z"

    cur.execute.assert_awaited_once()
    cur.fetchone.assert_awaited_once()


def test_build_spec_describe_response_null_description_and_tags() -> None:
    sid = uuid4()
    row = _sample_row(spec_id=sid)
    row["description"] = None
    row["tags"] = None
    pool, _ = _pool_mock_for_fetchone(row)

    async def run() -> dict[str, object]:
        return await build_spec_describe_response(pool, spec_id=str(sid))

    out = asyncio.run(run())

    assert out["description"] is None
    assert out["tags"] == []


def test_build_spec_describe_response_not_found() -> None:
    pool, _ = _pool_mock_for_fetchone(None)

    async def run() -> None:
        await build_spec_describe_response(pool, spec_id=str(uuid4()))

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_build_spec_describe_response_deny_all_raises_without_query() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock()

    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000001",
        tenant_id=str(uuid4()),
        label="x",
        scope=Scope(deny_all=True),
    )

    async def run() -> None:
        await build_spec_describe_response(pool, spec_id=str(uuid4()), auth_ctx=auth)

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())
    pool.connection.assert_not_called()


def test_build_spec_describe_response_authenticated_merged_sql() -> None:
    sid = uuid4()
    tid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000002",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    row = _sample_row(spec_id=sid)
    pool, cur = _pool_mock_for_fetchone(row)

    async def run() -> dict[str, object]:
        return await build_spec_describe_response(pool, spec_id=str(sid), auth_ctx=auth)

    out = asyncio.run(run())
    assert out["id"] == str(sid)

    sql, params = cur.execute.await_args.args
    assert "UNION ALL" in sql
    assert "mcp_v_public_specs" in sql
    assert "visibility = 'private'" in sql
    assert "spec_visibility" in sql
    assert isinstance(params, tuple)
    assert params[0] == sid
    assert params[1] == sid
    assert params[2] == str(auth.tenant_id)


def test_build_spec_describe_response_schedules_audit_for_private_row() -> None:
    sid = uuid4()
    tid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000088",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    row = _sample_row(spec_id=sid, spec_visibility="private")
    pool, _cur = _pool_mock_for_fetchone(row)

    async def run() -> None:
        with patch("apiome_mcp.spec_describe_tool.schedule_mcp_private_access_audit") as sched:
            await build_spec_describe_response(pool, spec_id=str(sid), auth_ctx=auth)
            sched.assert_called_once_with(
                pool,
                key_id=auth.key_id,
                tool="spec.describe",
                spec_id=str(sid),
            )

    asyncio.run(run())


def test_build_spec_describe_invalid_uuid() -> None:
    pool, _ = _pool_mock_for_fetchone(None)

    async def _run() -> None:
        await build_spec_describe_response(pool, spec_id="not-a-uuid")

    with pytest.raises(ValueError, match="spec_id"):
        asyncio.run(_run())


def test_build_spec_describe_empty_spec_id() -> None:
    pool, _ = _pool_mock_for_fetchone(None)

    async def _run() -> None:
        await build_spec_describe_response(pool, spec_id="   ")

    with pytest.raises(ValueError, match="required"):
        asyncio.run(_run())


def test_spec_describe_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.describe")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.describe"
