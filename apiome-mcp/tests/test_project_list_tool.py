from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.project_list_tool import (
    MAX_PAGE_SIZE,
    InvalidProjectListCursorError,
    _clamp_limit,
    build_project_list_response,
    decode_project_list_cursor,
    encode_project_list_cursor,
)


def _pool_mock_for_fetch(rows: list[dict[str, object]]) -> tuple[MagicMock, MagicMock]:
    pool = MagicMock(spec=AsyncConnectionPool)
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchall = AsyncMock(return_value=rows)
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


def test_encode_decode_project_list_cursor_roundtrips() -> None:
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    te = UUID("11111111-1111-4111-8111-111111111111")
    pr = UUID("22222222-2222-4222-8222-222222222222")
    c = encode_project_list_cursor(ts, te, pr)
    assert "=" not in c
    out = decode_project_list_cursor(c)
    assert out is not None
    u, got_te, got_pr = out
    assert got_te == te
    assert got_pr == pr
    assert u == ts.astimezone(timezone.utc)


def test_decode_project_list_cursor_none() -> None:
    assert decode_project_list_cursor(None) is None


def test_decode_project_list_cursor_blank_raises() -> None:
    with pytest.raises(InvalidProjectListCursorError):
        decode_project_list_cursor("")


def test_clamp_limit() -> None:
    assert _clamp_limit(None) == 50
    assert _clamp_limit(100) == 100
    assert _clamp_limit(999) == MAX_PAGE_SIZE


def test_build_project_list_response_maps_rows() -> None:
    te = uuid4()
    pr = uuid4()
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    rows = [{"tenant_id": te, "project_id": pr, "title": "Demo", "updated_at": ts}]
    pool, _ = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_project_list_response(pool, limit=10)

    out = asyncio.run(run())
    assert out["has_more"] is False
    assert out["next_cursor"] is None
    assert out["items"] == [
        {
            "tenant_id": str(te),
            "project_id": str(pr),
            "title": "Demo",
            "updated_at": "2026-05-01T12:00:00Z",
        }
    ]


def test_build_project_list_response_has_more() -> None:
    te = uuid4()
    pr = uuid4()
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"tenant_id": te, "project_id": pr, "title": "A", "updated_at": ts},
        {"tenant_id": te, "project_id": uuid4(), "title": "B", "updated_at": ts},
    ]
    pool, _ = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_project_list_response(pool, limit=1)

    out = asyncio.run(run())
    assert out["has_more"] is True
    assert len(out["items"]) == 1
    assert out["next_cursor"] is not None


def test_project_list_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("project.list")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "project.list"
