from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.spec_search_tool import (
    MAX_PAGE_SIZE,
    InvalidSpecSearchCursorError,
    _clamp_limit,
    build_spec_search_response,
    decode_spec_search_cursor,
    encode_spec_search_cursor,
    normalize_search_query,
)


def _sample_row(
    *,
    spec_id: UUID | None = None,
    updated_at: datetime | None = None,
    rank_score: int = 900,
) -> dict[str, object]:
    sid = spec_id or uuid4()
    ts = updated_at or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    return {
        "id": sid,
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "title": "Payments API",
        "version": "1.0.0",
        "description": "demo",
        "tags": ["alpha"],
        "updated_at": ts,
        "rank_score": rank_score,
    }


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


def test_normalize_search_query_strips_and_rejects_empty() -> None:
    assert normalize_search_query("  hello  ") == "hello"
    with pytest.raises(ValueError, match="non-empty"):
        normalize_search_query("")
    with pytest.raises(ValueError, match="non-empty"):
        normalize_search_query("   ")


def test_encode_spec_search_cursor_roundtrips() -> None:
    sid = UUID("44444444-4444-4444-8444-444444444444")
    ts = datetime(2026, 5, 2, 15, 30, 45, 123456, tzinfo=timezone.utc)
    c1 = encode_spec_search_cursor(1300, ts, sid)
    c2 = encode_spec_search_cursor(1300, ts, sid)
    assert c1 == c2
    assert "=" not in c1

    out = decode_spec_search_cursor(c1)
    assert out is not None
    rank, got_ts, got_id = out
    assert rank == 1300
    assert got_id == sid
    assert got_ts == ts.astimezone(timezone.utc)


def test_decode_spec_search_cursor_none_returns_none() -> None:
    assert decode_spec_search_cursor(None) is None


def test_decode_spec_search_cursor_blank_raises() -> None:
    with pytest.raises(InvalidSpecSearchCursorError):
        decode_spec_search_cursor("")
    with pytest.raises(InvalidSpecSearchCursorError):
        decode_spec_search_cursor("   ")


def test_decode_spec_search_cursor_rejects_bool_rank_from_json() -> None:
    import base64
    import json

    raw = json.dumps({"v": 1, "r": True, "i": str(uuid4()), "u": "2026-01-01T00:00:00Z"}).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(InvalidSpecSearchCursorError, match="rank"):
        decode_spec_search_cursor(token)


@pytest.mark.parametrize(
    ("limit_in", "expected_fetch_limit"),
    [(None, 51), (1, 2), (100, 101), (500, 101)],
)
def test_build_spec_search_response_clamps_limit(limit_in: int | None, expected_fetch_limit: int) -> None:
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_search_response(pool, q="pay", limit=limit_in)

    asyncio.run(run())
    _sql, params = cur.execute.await_args.args
    assert params["lim"] == expected_fetch_limit
    assert params["q"] == "pay"


def test_build_spec_search_response_has_more_and_next_cursor() -> None:
    base_ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    id_a = uuid4()
    id_b = uuid4()
    rows = [
        _sample_row(spec_id=id_a, updated_at=base_ts, rank_score=900),
        _sample_row(spec_id=id_b, updated_at=base_ts.replace(hour=11), rank_score=800),
    ]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_search_response(pool, q="pay", limit=1)

    out = asyncio.run(run())
    assert out["has_more"] is True
    assert len(out["items"]) == 1
    assert out["items"][0]["rank_score"] == 900
    assert out["next_cursor"] is not None
    decoded = decode_spec_search_cursor(str(out["next_cursor"]))
    assert decoded is not None
    assert decoded[0] == 900
    assert decoded[2] == id_a


def test_build_spec_search_response_no_next_when_last_page() -> None:
    rows = [_sample_row()]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_search_response(pool, q="pay", limit=50)

    out = asyncio.run(run())
    assert out["has_more"] is False
    assert out["next_cursor"] is None


def test_build_spec_search_response_cursor_binding() -> None:
    sid = UUID("33333333-3333-4333-8333-333333333333")
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    cursor = encode_spec_search_cursor(700, ts, sid)
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_search_response(pool, q="demo", cursor=cursor)

    asyncio.run(run())
    _sql, params = cur.execute.await_args.args
    assert params["has_cursor"] is True
    assert params["cur_rank"] == 700
    assert params["cur_ts"] == ts
    assert params["cur_id"] == sid


def test_build_spec_search_empty_query_raises() -> None:
    pool, _cur = _pool_mock_for_fetch([])

    async def run() -> None:
        await build_spec_search_response(pool, q="  ")

    with pytest.raises(ValueError, match="non-empty"):
        asyncio.run(run())


def test_clamp_limit_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="limit"):
        _clamp_limit(0)


def test_spec_search_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.search")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.search"


def test_max_page_size_constant() -> None:
    assert MAX_PAGE_SIZE == 100
