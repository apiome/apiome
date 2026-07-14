from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from fastmcp.exceptions import AuthorizationError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.database_pool import MCP_DB_POOL_KEY
from apiome_mcp.mcp_auth import (
    McpAuthContext,
    extract_raw_mcp_api_key,
    hash_mcp_api_key_secret,
    mcp_key_prefix,
    meta_as_dict,
    normalize_stored_prefix,
    require_mcp_auth,
    schedule_mcp_key_last_used_touch,
    touch_mcp_key_last_used,
    validate_mcp_api_key,
)
from apiome_mcp.scope import Scope

_SECRET = "0123456789ab" + "cursor-test-secret"


def test_mcp_key_prefix_format() -> None:
    assert mcp_key_prefix(_SECRET) == _SECRET[:12] + "..."


def test_normalize_stored_prefix_accepts_plain_or_ellipsis() -> None:
    assert normalize_stored_prefix("abcdefghijkl") == "abcdefghijkl..."
    assert normalize_stored_prefix("  abcdefghijkl...  ") == "abcdefghijkl..."
    assert normalize_stored_prefix("abcdefghijklmno") == "abcdefghijkl..."
    with pytest.raises(ValueError, match="non-empty"):
        normalize_stored_prefix("   ")
    with pytest.raises(ValueError, match="invalid"):
        normalize_stored_prefix("...")
    with pytest.raises(ValueError, match="too short"):
        normalize_stored_prefix("abc")
    with pytest.raises(ValueError, match="too short"):
        normalize_stored_prefix("abc...")


def test_extract_prefers_http_authorization_over_meta() -> None:
    meta = {"apiome_api_key": "from-meta"}
    got = extract_raw_mcp_api_key(
        http_headers={"authorization": "Bearer from-header"},
        request_meta=meta,
    )
    assert got == "from-header"


def test_extract_bearer_case_insensitive() -> None:
    assert extract_raw_mcp_api_key(http_headers={"authorization": "bearer abc.def"}, request_meta=None) == "abc.def"


def test_extract_meta_authorization_and_raw_keys() -> None:
    assert extract_raw_mcp_api_key(http_headers={}, request_meta={"authorization": "Bearer meta-token"}) == "meta-token"
    assert extract_raw_mcp_api_key(http_headers={}, request_meta={"apiome_api_key": " raw "}) == "raw"
    assert extract_raw_mcp_api_key(http_headers={}, request_meta={"api_key": "plain"}) == "plain"


def test_meta_as_dict_merges_nested_meta() -> None:
    d = meta_as_dict({"_meta": {"api_key": "nested"}, "other": 1})
    assert d["api_key"] == "nested"
    assert d["other"] == 1


def _pool_mock(rows: list[dict]) -> MagicMock:
    cur = AsyncMock()
    cur.fetchall = AsyncMock(return_value=rows)
    cur.execute = AsyncMock()
    conn = MagicMock()
    conn.execute = AsyncMock()
    cm_cur = AsyncMock()
    cm_cur.__aenter__ = AsyncMock(return_value=cur)
    cm_cur.__aexit__ = AsyncMock(return_value=None)
    conn.cursor = MagicMock(return_value=cm_cur)
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm_conn)
    return pool


def test_validate_success_returns_scope() -> None:
    kid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    stored_hash = hash_mcp_api_key_secret(_SECRET).decode("ascii")
    row = {
        "id": kid,
        "tenant_id": tid,
        "label": "unit",
        "scope_json": {"tenants": [tid], "projects": [pid]},
        "key_hash": stored_hash,
        "expires_at": None,
        "revoked_at": None,
        "capability_mode": "explicit",
        "enabled_tools": ["ping", "spec.list"],
    }
    pool = _pool_mock([row])

    async def run() -> None:
        with patch("apiome_mcp.mcp_auth.schedule_mcp_key_last_used_touch") as sched:
            auth = await validate_mcp_api_key(pool, _SECRET)
        sched.assert_called_once_with(pool, kid)
        expected = McpAuthContext(
            key_id=kid,
            tenant_id=tid,
            label="unit",
            scope=Scope(tenants=[tid], projects=[pid]),
            capability_mode="explicit",
            enabled_tools=frozenset({"ping", "spec.list"}),
        )
        assert auth == expected
        assert auth.key_capability_snapshot().enabled_tools == frozenset({"ping", "spec.list"})

    asyncio.run(run())


def test_validate_revoked() -> None:
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "label": "x",
        "scope_json": {},
        "key_hash": hash_mcp_api_key_secret(_SECRET).decode("ascii"),
        "expires_at": None,
        "revoked_at": datetime.now(timezone.utc),
    }
    pool = _pool_mock([row])

    async def run() -> None:
        with pytest.raises(AuthorizationError, match="revoked"):
            await validate_mcp_api_key(pool, _SECRET)

    asyncio.run(run())


def test_validate_expired() -> None:
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "label": "x",
        "scope_json": {},
        "key_hash": hash_mcp_api_key_secret(_SECRET).decode("ascii"),
        "expires_at": datetime.now(timezone.utc) - timedelta(days=1),
        "revoked_at": None,
    }
    pool = _pool_mock([row])

    async def run() -> None:
        with pytest.raises(AuthorizationError, match="expired"):
            await validate_mcp_api_key(pool, _SECRET)

    asyncio.run(run())


def test_validate_wrong_secret() -> None:
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": str(uuid.uuid4()),
        "label": "x",
        "scope_json": {},
        "key_hash": hash_mcp_api_key_secret(_SECRET).decode("ascii"),
        "expires_at": None,
        "revoked_at": None,
    }
    pool = _pool_mock([row])

    async def run() -> None:
        with pytest.raises(AuthorizationError, match="Invalid or unknown"):
            await validate_mcp_api_key(pool, _SECRET + "x")

    asyncio.run(run())


def test_require_mcp_auth_missing_credential() -> None:
    ctx = MagicMock(spec=Context)
    ctx.request_context = None

    async def run() -> None:
        with patch(
            "apiome_mcp.mcp_auth.get_http_bearer_from_context",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(AuthorizationError, match="MCP authentication required"):
                await require_mcp_auth(ctx, {})

    asyncio.run(run())


def test_require_mcp_auth_uses_http_bearer_stash_when_headers_missing_token() -> None:
    kid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    stored_hash = hash_mcp_api_key_secret(_SECRET).decode("ascii")
    row = {
        "id": kid,
        "tenant_id": tid,
        "label": "live",
        "scope_json": {},
        "key_hash": stored_hash,
        "expires_at": None,
        "revoked_at": None,
    }
    pool = _pool_mock([row])
    ctx = MagicMock(spec=Context)
    ctx.request_context = None
    ctx.lifespan_context = {MCP_DB_POOL_KEY: pool}

    async def run() -> None:
        with patch("apiome_mcp.mcp_auth.schedule_mcp_key_last_used_touch") as sched:
            with patch(
                "apiome_mcp.mcp_auth.get_http_bearer_from_context",
                new=AsyncMock(return_value=_SECRET),
            ):
                auth = await require_mcp_auth(ctx, {})
        sched.assert_called_once_with(pool, kid)
        assert auth.key_id == kid

    asyncio.run(run())


def test_require_mcp_auth_happy_path() -> None:
    kid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    stored_hash = hash_mcp_api_key_secret(_SECRET).decode("ascii")
    row = {
        "id": kid,
        "tenant_id": tid,
        "label": "live",
        "scope_json": {},
        "key_hash": stored_hash,
        "expires_at": None,
        "revoked_at": None,
    }
    pool = _pool_mock([row])
    ctx = MagicMock(spec=Context)
    ctx.request_context = None
    ctx.lifespan_context = {MCP_DB_POOL_KEY: pool}

    async def run() -> None:
        with patch("apiome_mcp.mcp_auth.schedule_mcp_key_last_used_touch") as sched:
            auth = await require_mcp_auth(ctx, {"authorization": f"Bearer {_SECRET}"})
        sched.assert_called_once_with(pool, kid)
        assert auth.key_id == kid

    asyncio.run(run())


def test_touch_mcp_key_last_used_executes_update() -> None:
    kid = str(uuid.uuid4())
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock(return_value=cm)

    async def run() -> None:
        await touch_mcp_key_last_used(pool, kid)

    asyncio.run(run())
    conn.execute.assert_awaited_once()
    conn.commit.assert_awaited_once()
    call_args = conn.execute.await_args
    assert kid in str(call_args)


def test_schedule_mcp_key_last_used_touch_uses_event_loop() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    captured: list[object] = []

    async def run() -> None:
        mock_loop = MagicMock()

        def capture_task(coro: object) -> MagicMock:
            captured.append(coro)
            return MagicMock()

        mock_loop.create_task.side_effect = capture_task
        with patch("apiome_mcp.mcp_auth.touch_mcp_key_last_used", new=AsyncMock()):
            with patch("asyncio.get_running_loop", return_value=mock_loop):
                schedule_mcp_key_last_used_touch(pool, "key-id")
        mock_loop.create_task.assert_called_once()
        assert len(captured) == 1
        assert asyncio.iscoroutine(captured[0])
        await captured[0]  # type: ignore[misc]

    asyncio.run(run())
