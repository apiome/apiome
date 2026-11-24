from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.project_list_tool import (
    MAX_PAGE_SIZE,
    InvalidProjectListCursorError,
    _clamp_limit,
    build_project_list_response,
    decode_project_list_cursor,
    encode_project_list_cursor,
)
from apiome_mcp.scope import Scope


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


def _auth(tenant: UUID, scope: Scope | None = None) -> McpAuthContext:
    return McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000002", tenant_id=str(tenant), label="k", scope=scope or Scope()
    )


def test_anonymous_statement_reads_one_page_of_the_rollup() -> None:
    """DBP-1.22: ``mcp_project_listing`` in index order, not a GROUP BY over every listed revision."""
    pool, cur = _pool_mock_for_fetch([])

    asyncio.run(build_project_list_response(pool))
    sql, params = cur.execute.await_args.args
    assert "FROM apiome.mcp_project_listing l" in sql
    assert "mcp_v_public_specs" not in sql and "GROUP BY" not in sql
    assert "l.public_listed_at IS NOT NULL" in sql
    assert "ORDER BY l.public_listed_at DESC, l.tenant_id DESC, l.project_id DESC" in sql
    assert "p.deleted_at IS NULL AND p.enabled IS TRUE" in sql
    assert "IS NULL OR" not in sql and "UNION ALL" not in sql
    assert params == [51]


def test_filters_and_cursor_are_appended_only_when_set() -> None:
    te, pr = uuid4(), uuid4()
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    pool, cur = _pool_mock_for_fetch([])

    asyncio.run(
        build_project_list_response(
            pool, tenant_id=str(te), project_id=str(pr), limit=5, cursor=encode_project_list_cursor(ts, te, pr)
        )
    )
    sql, params = cur.execute.await_args.args
    assert "l.tenant_id = %s" in sql and "l.project_id = %s" in sql
    assert "(l.public_listed_at, l.tenant_id, l.project_id) < (%s, %s, %s)" in sql
    assert params == [te, pr, ts, te, pr, 6]


def test_authenticated_statement_merges_other_tenants_and_the_keys_own() -> None:
    """Other tenants' projects by their public timestamp; the key's own by all listed revisions."""
    key_tenant = uuid4()
    pool, cur = _pool_mock_for_fetch([])

    asyncio.run(build_project_list_response(pool, limit=5, auth_ctx=_auth(key_tenant)))
    sql, params = cur.execute.await_args.args
    others, own = sql.split("UNION ALL")
    assert "l.public_listed_at IS NOT NULL" in others and "l.tenant_id <> %s" in others
    assert "l.listed_at IS NOT NULL" in own and "l.tenant_id = %s" in own
    assert "l.listed_at AS updated_at" in own
    assert sql.rstrip().endswith("ORDER BY updated_at DESC, tenant_id DESC, project_id DESC\nLIMIT %s")
    # Each branch is limited before the merge; the branches never share a project.
    assert params == [key_tenant, 6, key_tenant, 6, 6]


def test_authenticated_statement_applies_scope_and_cursor_to_both_branches() -> None:
    key_tenant, allowed = uuid4(), uuid4()
    te, pr = uuid4(), uuid4()
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    pool, cur = _pool_mock_for_fetch([])

    asyncio.run(
        build_project_list_response(
            pool,
            limit=5,
            cursor=encode_project_list_cursor(ts, te, pr),
            auth_ctx=_auth(key_tenant, Scope(projects=(str(allowed),))),
        )
    )
    sql, params = cur.execute.await_args.args
    assert sql.count("l.project_id = ANY(%s::uuid[])") == 2
    assert "(l.listed_at, l.tenant_id, l.project_id) < (%s, %s, %s)" in sql
    assert params == [key_tenant, [allowed], ts, te, pr, 6, key_tenant, [allowed], ts, te, pr, 6, 6]


def test_key_without_a_uuid_tenant_reads_the_public_rollup_only() -> None:
    pool, cur = _pool_mock_for_fetch([])
    auth = McpAuthContext(key_id="k", tenant_id="not-a-uuid", label="k", scope=Scope())

    asyncio.run(build_project_list_response(pool, auth_ctx=auth))
    sql, params = cur.execute.await_args.args
    assert "UNION ALL" not in sql and "l.listed_at" not in sql
    assert params == [51]


def test_deny_all_scope_returns_empty_without_a_query() -> None:
    pool, cur = _pool_mock_for_fetch([])

    out = asyncio.run(build_project_list_response(pool, auth_ctx=_auth(uuid4(), Scope(deny_all=True))))
    assert out == {"items": [], "has_more": False, "next_cursor": None}
    cur.execute.assert_not_awaited()


def test_project_list_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("project.list")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "project.list"
