from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_list_tool import (
    MAX_PAGE_SIZE,
    InvalidSpecListCursorError,
    _clamp_limit,
    build_spec_list_response,
    decode_spec_list_cursor,
    encode_spec_list_cursor,
)


def _sample_row(
    *,
    spec_id: UUID | None = None,
    updated_at: datetime | None = None,
    spec_visibility: str = "public",
) -> dict[str, object]:
    sid = spec_id or uuid4()
    ts = updated_at or datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    return {
        "id": sid,
        "tenant_id": uuid4(),
        "project_id": uuid4(),
        "title": "Demo",
        "version": "1.0.0",
        "description": None,
        "tags": ["alpha"],
        "updated_at": ts,
        "spec_visibility": spec_visibility,
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


def test_encode_spec_list_cursor_is_stable_and_roundtrips() -> None:
    sid = UUID("33333333-3333-4333-8333-333333333333")
    ts = datetime(2026, 5, 2, 15, 30, 45, 123456, tzinfo=timezone.utc)
    c1 = encode_spec_list_cursor(ts, sid)
    c2 = encode_spec_list_cursor(ts, sid)
    assert c1 == c2
    assert "=" not in c1

    out = decode_spec_list_cursor(c1)
    assert out is not None
    got_ts, got_id = out
    assert got_id == sid
    assert got_ts == ts.astimezone(timezone.utc)


def test_decode_spec_list_cursor_none_returns_none() -> None:
    assert decode_spec_list_cursor(None) is None


def test_decode_spec_list_cursor_blank_raises() -> None:
    with pytest.raises(InvalidSpecListCursorError):
        decode_spec_list_cursor("")
    with pytest.raises(InvalidSpecListCursorError):
        decode_spec_list_cursor("   ")


def test_decode_spec_list_cursor_rejects_garbage() -> None:
    with pytest.raises(InvalidSpecListCursorError):
        decode_spec_list_cursor("not-valid-base64???")

    with pytest.raises(InvalidSpecListCursorError):
        decode_spec_list_cursor("aaaa")


def test_decode_spec_list_cursor_rejects_wrong_version() -> None:
    import base64
    import json

    raw = json.dumps({"v": 99, "i": str(uuid4()), "u": "2026-01-01T00:00:00Z"}).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(InvalidSpecListCursorError, match="version"):
        decode_spec_list_cursor(token)


@pytest.mark.parametrize(
    ("limit_in", "expected_fetch_limit"),
    [(None, 51), (1, 2), (100, 101), (500, 101)],
)
def test_build_spec_list_response_clamps_limit(limit_in: int | None, expected_fetch_limit: int) -> None:
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, limit=limit_in)

    asyncio.run(run())
    _sql, params = cur.execute.await_args.args
    assert params == [expected_fetch_limit]


def test_build_spec_list_response_has_more_and_next_cursor() -> None:
    base_ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    id_a = uuid4()
    id_b = uuid4()
    rows = [
        _sample_row(spec_id=id_a, updated_at=base_ts),
        _sample_row(spec_id=id_b, updated_at=base_ts.replace(hour=11)),
    ]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_list_response(pool, limit=1)

    out = asyncio.run(run())
    assert out["has_more"] is True
    assert len(out["items"]) == 1
    assert out["next_cursor"] is not None
    decoded = decode_spec_list_cursor(str(out["next_cursor"]))
    assert decoded is not None
    assert decoded[1] == id_a


def test_build_spec_list_response_no_next_when_last_page() -> None:
    rows = [_sample_row()]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_list_response(pool, limit=50)

    out = asyncio.run(run())
    assert out["has_more"] is False
    assert out["next_cursor"] is None


def test_build_spec_list_invalid_tenant_uuid() -> None:
    pool, _cur = _pool_mock_for_fetch([])

    async def run() -> None:
        await build_spec_list_response(pool, tenant_id="not-a-uuid")

    with pytest.raises(ValueError, match="tenant_id"):
        asyncio.run(run())


def test_spec_list_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list"


def test_spec_list_my_specs_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list_my_specs")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list_my_specs"


def test_max_page_size_constant() -> None:
    assert MAX_PAGE_SIZE == 100


def test_decode_spec_list_cursor_rejects_naive_timestamp() -> None:
    import base64
    import json

    raw = json.dumps({"v": 1, "i": str(uuid4()), "u": "2026-01-01T00:00:00"}).encode()
    token = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(InvalidSpecListCursorError, match="timezone"):
        decode_spec_list_cursor(token)


def test_clamp_limit_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="limit"):
        _clamp_limit(0)
    with pytest.raises(ValueError, match="limit"):
        _clamp_limit(-5)


def test_build_spec_list_response_rejects_non_positive_limit() -> None:
    pool, _cur = _pool_mock_for_fetch([])

    async def run() -> None:
        await build_spec_list_response(pool, limit=0)

    with pytest.raises(ValueError, match="limit"):
        asyncio.run(run())


def test_build_spec_list_response_tenant_filter_binding() -> None:
    tid = uuid4()
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, tenant_id=str(tid))

    asyncio.run(run())
    sql, params = cur.execute.await_args.args
    assert "p.tenant_id = %s" in sql
    assert params == [tid, 51]


def test_build_spec_list_response_project_filter_binding() -> None:
    pid = uuid4()
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, project_id=str(pid))

    asyncio.run(run())
    sql, params = cur.execute.await_args.args
    assert "v.project_id = %s" in sql
    assert params == [pid, 51]


def test_build_spec_list_statement_pages_on_the_stored_listing_key() -> None:
    """DBP-1.22: the page is picked on ``versions.mcp_listed_at``; tags are read for its rows only."""
    pool, cur = _pool_mock_for_fetch([_sample_row()])

    asyncio.run(build_spec_list_response(pool))
    sql, params = cur.execute.await_args.args
    assert "mcp_v_public_specs" not in sql
    assert "ORDER BY v.mcp_listed_at DESC, v.id DESC" in sql
    assert "v.mcp_listed_at IS NOT NULL AND v.visibility = 'public'::apiome.visibility_type" in sql
    # Every visibility rule is still stated, not left to the stored column.
    for rule in ("v.deleted_at IS NULL", "v.enabled IS TRUE", "v.published IS TRUE", "p.deleted_at IS NULL"):
        assert rule in sql
    # Optional filters and the cursor are absent, not "%s IS NULL OR …".
    assert "IS NULL OR" not in sql
    assert "p.tenant_id = %s" not in sql and "v.project_id = %s" not in sql and "< (%s, %s)" not in sql
    # The tag aggregate sits outside the limited page.
    assert sql.index("LIMIT %s") < sql.index("FROM apiome.version_tags vt")
    assert params == [51]


def test_build_spec_list_response_cursor_binding() -> None:
    sid = UUID("33333333-3333-4333-8333-333333333333")
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    cursor = encode_spec_list_cursor(ts, sid)
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, cursor=cursor)

    asyncio.run(run())
    sql, params = cur.execute.await_args.args
    assert "(v.mcp_listed_at, v.id) < (%s, %s)" in sql
    assert params == [ts, sid, 51]


def test_build_spec_list_response_deny_all_returns_empty_without_query() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock()

    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000001",
        tenant_id=str(uuid4()),
        label="x",
        scope=Scope(deny_all=True),
    )

    async def run() -> dict[str, object]:
        return await build_spec_list_response(pool, auth_ctx=auth)

    out = asyncio.run(run())
    assert out == {"items": [], "has_more": False, "next_cursor": None}
    pool.connection.assert_not_called()


def test_build_spec_list_response_authenticated_merged_sql() -> None:
    tid = uuid4()
    pid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000002",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, tenant_id=str(tid), project_id=str(pid), limit=5, auth_ctx=auth)

    asyncio.run(run())
    sql, params = cur.execute.await_args.args
    assert "UNION ALL" in sql
    assert "v.visibility = 'public'::apiome.visibility_type" in sql
    assert "v.visibility = 'private'::apiome.visibility_type" in sql
    assert "spec_visibility" in sql
    # public branch: tenant filter, project filter, branch limit;
    # private branch: the key's tenant (authorization), tenant, project, branch limit; then the page limit.
    assert params == [tid, pid, 6, tid, tid, pid, 6, 6]


def test_build_spec_list_response_authenticated_skips_private_branch_for_another_tenant() -> None:
    """A ``tenant_id`` filter that is not the key's tenant can match no private revision."""
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000002",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )
    other = uuid4()
    pool, cur = _pool_mock_for_fetch([_sample_row()])

    asyncio.run(build_spec_list_response(pool, tenant_id=str(other), limit=5, auth_ctx=auth))
    sql, params = cur.execute.await_args.args
    assert "UNION ALL" not in sql
    assert "'private'" not in sql
    assert "spec_visibility" in sql
    assert params == [other, 6]


def test_build_spec_list_response_schedules_audit_batch_for_private_rows() -> None:
    tid = uuid4()
    pid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    priv_id1 = uuid4()
    priv_id2 = uuid4()
    rows = [
        _sample_row(),
        _sample_row(spec_id=priv_id1, spec_visibility="private"),
        _sample_row(spec_id=priv_id2, spec_visibility="private"),
    ]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        with patch("apiome_mcp.spec_list_tool.schedule_mcp_private_access_audit_batch") as sched:
            await build_spec_list_response(pool, tenant_id=str(tid), project_id=str(pid), limit=10, auth_ctx=auth)
            sched.assert_called_once_with(
                pool,
                key_id=auth.key_id,
                tool="spec.list",
                spec_ids=[str(priv_id1), str(priv_id2)],
            )

    asyncio.run(run())


def test_build_spec_list_response_schedules_audit_with_custom_tool_name() -> None:
    tid = uuid4()
    pid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    priv_id = uuid4()
    rows = [_sample_row(spec_id=priv_id, spec_visibility="private")]
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        with patch("apiome_mcp.spec_list_tool.schedule_mcp_private_access_audit_batch") as sched:
            await build_spec_list_response(
                pool,
                tenant_id=str(tid),
                project_id=str(pid),
                limit=10,
                auth_ctx=auth,
                private_access_audit_tool="spec.list_my_specs",
            )
            sched.assert_called_once_with(
                pool,
                key_id=auth.key_id,
                tool="spec.list_my_specs",
                spec_ids=[str(priv_id)],
            )

    asyncio.run(run())


def test_build_spec_list_response_no_audit_when_no_private_rows() -> None:
    tid = uuid4()
    pid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    rows = [_sample_row(), _sample_row()]  # both public
    pool, _cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        with patch("apiome_mcp.spec_list_tool.schedule_mcp_private_access_audit_batch") as sched:
            await build_spec_list_response(pool, tenant_id=str(tid), project_id=str(pid), limit=10, auth_ctx=auth)
            sched.assert_not_called()

    asyncio.run(run())


def test_build_spec_list_response_authenticated_cursor_binding_tuple() -> None:
    sid = UUID("44444444-4444-4444-8444-444444444444")
    ts = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    cursor = encode_spec_list_cursor(ts, sid)
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000003",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )
    rows = [_sample_row()]
    pool, cur = _pool_mock_for_fetch(rows)

    async def run() -> None:
        await build_spec_list_response(pool, cursor=cursor, auth_ctx=auth)

    asyncio.run(run())
    _sql, params = cur.execute.await_args.args
    key_tenant = UUID(auth.tenant_id)
    # Each branch applies the cursor and its own limit before the merge.
    assert params == [ts, sid, 51, key_tenant, key_tenant, ts, sid, 51, 51]
