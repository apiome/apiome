from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.spec_list_tags_tool import (
    MAX_PAGE_SIZE,
    InvalidSpecListTagsCursorError,
    _clamp_limit,
    build_spec_list_tags_response,
    decode_spec_list_tags_cursor,
    encode_spec_list_tags_cursor,
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


def test_encode_decode_spec_list_tags_cursor_roundtrips() -> None:
    c = encode_spec_list_tags_cursor(42, "beta")
    assert "=" not in c
    out = decode_spec_list_tags_cursor(c)
    assert out == (42, "beta")


def test_decode_spec_list_tags_cursor_none() -> None:
    assert decode_spec_list_tags_cursor(None) is None


def test_decode_spec_list_tags_cursor_blank_raises() -> None:
    with pytest.raises(InvalidSpecListTagsCursorError):
        decode_spec_list_tags_cursor("")


def test_clamp_limit() -> None:
    assert _clamp_limit(None) == 50
    assert _clamp_limit(100) == 100
    assert _clamp_limit(500) == MAX_PAGE_SIZE
    with pytest.raises(ValueError):
        _clamp_limit(0)


def test_build_spec_list_tags_response_first_page() -> None:
    rows = [
        {"tag": "stable", "cnt": 5},
        {"tag": "beta", "cnt": 2},
    ]
    pool, _ = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_list_tags_response(pool, limit=10)

    out = asyncio.run(run())
    assert out["has_more"] is False
    assert out["next_cursor"] is None
    assert out["items"] == [{"tag": "stable", "count": 5}, {"tag": "beta", "count": 2}]


def test_build_spec_list_tags_response_has_more_and_cursor() -> None:
    rows = [
        {"tag": "a", "cnt": 3},
        {"tag": "b", "cnt": 3},
        {"tag": "c", "cnt": 1},
    ]
    pool, _ = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_list_tags_response(pool, limit=2)

    out = asyncio.run(run())
    assert out["has_more"] is True
    assert out["items"] == [{"tag": "a", "count": 3}, {"tag": "b", "count": 3}]
    assert out["next_cursor"] is not None


def test_build_spec_list_tags_response_empty() -> None:
    pool, _ = _pool_mock_for_fetch([])

    async def run() -> dict[str, object]:
        return await build_spec_list_tags_response(pool)

    out = asyncio.run(run())
    assert out == {"items": [], "has_more": False, "next_cursor": None}


def test_spec_list_tags_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list_tags")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list_tags"
