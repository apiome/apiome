from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.spec_list_tags_tool import (
    MAX_PAGE_SIZE,
    InvalidSpecListTagsCursorError,
    TagHistogramCache,
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


_HISTOGRAM = [
    {"tag": "a", "cnt": 3},
    {"tag": "b", "cnt": 3},
    {"tag": "c", "cnt": 1},
    {"tag": "d", "cnt": 1},
]


def test_histogram_is_counted_from_version_tags_not_the_view() -> None:
    """DBP-1.22: one aggregate over ``version_tags``, with every public-catalog rule stated."""
    pool, cur = _pool_mock_for_fetch(_HISTOGRAM)

    asyncio.run(build_spec_list_tags_response(pool, limit=2))
    (sql,) = cur.execute.await_args.args
    assert "FROM apiome.version_tags vt" in sql
    assert "mcp_v_public_specs" not in sql and "unnest" not in sql
    assert "v.visibility = 'public'::apiome.visibility_type" in sql
    for rule in ("v.published IS TRUE", "v.enabled IS TRUE", "v.deleted_at IS NULL", "p.deleted_at IS NULL"):
        assert rule in sql
    assert "ORDER BY cnt DESC, tag ASC" in sql
    assert "LIMIT" not in sql


def test_second_page_is_served_from_the_cached_histogram() -> None:
    pool, cur = _pool_mock_for_fetch(_HISTOGRAM)

    async def run() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        first = await build_spec_list_tags_response(pool, limit=2)
        second = await build_spec_list_tags_response(pool, limit=2, cursor=str(first["next_cursor"]))
        again = await build_spec_list_tags_response(pool, limit=2)
        return first, second, again

    first, second, again = asyncio.run(run())
    assert first["items"] == [{"tag": "a", "count": 3}, {"tag": "b", "count": 3}]
    assert second == {
        "items": [{"tag": "c", "count": 1}, {"tag": "d", "count": 1}],
        "has_more": False,
        "next_cursor": None,
    }
    assert again == first
    # Three calls, one statement: the count.
    assert cur.execute.await_count == 1


def test_histogram_is_recounted_after_its_lifetime() -> None:
    now = [1000.0]
    cache = TagHistogramCache(ttl_seconds=lambda: 45.0, clock=lambda: now[0])
    pool, cur = _pool_mock_for_fetch(_HISTOGRAM)

    async def call() -> None:
        await build_spec_list_tags_response(pool, limit=2)

    with patch("apiome_mcp.spec_list_tags_tool.TAG_HISTOGRAM_CACHE", cache):
        asyncio.run(call())
        now[0] += 44.0
        asyncio.run(call())
        assert cur.execute.await_count == 1
        now[0] += 2.0
        asyncio.run(call())
        assert cur.execute.await_count == 2


def test_lifetime_zero_counts_on_every_call_and_still_pages() -> None:
    cache = TagHistogramCache(ttl_seconds=lambda: 0.0)
    pool, cur = _pool_mock_for_fetch(_HISTOGRAM)

    async def run() -> dict[str, object]:
        first = await build_spec_list_tags_response(pool, limit=2)
        return await build_spec_list_tags_response(pool, limit=2, cursor=str(first["next_cursor"]))

    with patch("apiome_mcp.spec_list_tags_tool.TAG_HISTOGRAM_CACHE", cache):
        second = asyncio.run(run())
    assert second["items"] == [{"tag": "c", "count": 1}, {"tag": "d", "count": 1}]
    assert cur.execute.await_count == 2
    assert cache.rows() is None


def test_cursor_the_histogram_no_longer_holds_is_answered_by_the_database() -> None:
    """A tag whose count changed since the cursor was issued: the database compares, not the cache."""
    pool, cur = _pool_mock_for_fetch(_HISTOGRAM)
    stale = encode_spec_list_tags_cursor(2, "b")  # the histogram now has b with 3

    async def run() -> dict[str, object]:
        await build_spec_list_tags_response(pool, limit=2)  # warms the cache
        cur.fetchall.return_value = [{"tag": "c", "cnt": 1}, {"tag": "d", "cnt": 1}]
        return await build_spec_list_tags_response(pool, limit=2, cursor=stale)

    out = asyncio.run(run())
    assert out["items"] == [{"tag": "c", "count": 1}, {"tag": "d", "count": 1}]
    sql, params = cur.execute.await_args.args
    assert "cnt < %(cur_cnt)s::bigint" in sql and "tag > %(cur_tag)s" in sql
    assert params == {"cur_cnt": 2, "cur_tag": "b", "lim": 3}


def test_tag_histogram_cache_position_after() -> None:
    cache = TagHistogramCache(ttl_seconds=lambda: 45.0)
    cache.store([("a", 3), ("b", 3), ("c", 1)])
    assert cache.position_after(3, "a") == 1
    assert cache.position_after(1, "c") == 3
    assert cache.position_after(2, "a") is None  # count changed
    assert cache.position_after(3, "zzz") is None  # tag gone
    cache.clear()
    assert cache.rows() is None
    assert cache.position_after(3, "a") is None


def test_spec_list_tags_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list_tags")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list_tags"
