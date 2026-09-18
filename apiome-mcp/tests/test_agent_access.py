"""AGX-3.1 agent access middleware — unit tests (#4537).

Covers the pieces of :mod:`apiome_mcp.agent_access` in isolation: the permitted-tools
intersection, the MCP error each refusal becomes, the ``api_keys`` resolver (against
:class:`~agent_access_fakes.FakeAgentKeyPool`), and the middleware's list filter and call gate
driven through FastMCP's own dispatch (``Middleware.__call__``). The end-to-end behaviour over
streamable HTTP is ``test_agent_access_http.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as mt
import pytest
from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import MiddlewareContext
from mcp import McpError

from agent_access_fakes import AGENT_SECRET, FakeAgentKeyPool, agent_secret
from apiome_mcp import agent_access
from apiome_mcp.agent_access import (
    AGENT_ACCESS_UNAVAILABLE_CODE,
    AGENT_KEY_KIND,
    AGENT_KEY_REJECTED_CODE,
    AGENT_TOOLSET_UNAVAILABLE_CODE,
    AgentAccess,
    AgentAccessDeniedError,
    AgentAccessMiddleware,
    AgentAccessReason,
    AgentKey,
    current_agent_access,
    permitted_tools,
    resolve_agent_key,
    toolset_curation_pending,
)

_KEY = AgentKey(
    key_id=str(uuid.uuid4()),
    tenant_id=str(uuid.uuid4()),
    toolset_id=str(uuid.uuid4()),
    tool_allowlist=frozenset({"listPets", "deletePet", "createPet"}),
)
_ENABLED = frozenset({"listPets", "getPetById", "deletePet"})


# ============================================================================
# permitted_tools
# ============================================================================
@pytest.mark.parametrize(
    ("enabled", "allowlist", "expected"),
    [
        (_ENABLED, _KEY.tool_allowlist, {"listPets", "deletePet"}),
        (_ENABLED, [], set()),
        ([], _KEY.tool_allowlist, set()),
        (["a", "b"], ["a", "b"], {"a", "b"}),
        (["a", "a"], ["a"], {"a"}),
    ],
)
def test_permitted_is_enabled_intersect_allowlist(enabled, allowlist, expected) -> None:
    assert permitted_tools(enabled, allowlist) == frozenset(expected)


def test_access_permits_only_its_set() -> None:
    access = AgentAccess(key=_KEY, permitted=frozenset({"listPets"}))
    assert access.permits("listPets")
    assert not access.permits("deletePet")
    assert not access.permits("")


def test_toolset_curation_is_pending_until_agx_1_2() -> None:
    assert asyncio.run(toolset_curation_pending(MagicMock(), _KEY)) is None


# ============================================================================
# AgentAccessDeniedError
# ============================================================================
@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (AgentAccessReason.KEY_MISSING, AGENT_KEY_REJECTED_CODE),
        (AgentAccessReason.KEY_INVALID, AGENT_KEY_REJECTED_CODE),
        (AgentAccessReason.KEY_REVOKED, AGENT_KEY_REJECTED_CODE),
        (AgentAccessReason.KEY_DISABLED, AGENT_KEY_REJECTED_CODE),
        (AgentAccessReason.KEY_EXPIRED, AGENT_KEY_REJECTED_CODE),
        (AgentAccessReason.TOOLSET_UNAVAILABLE, AGENT_TOOLSET_UNAVAILABLE_CODE),
        (AgentAccessReason.ACCESS_UNAVAILABLE, AGENT_ACCESS_UNAVAILABLE_CODE),
    ],
)
def test_each_refusal_is_a_coded_mcp_error(reason, code) -> None:
    denied = AgentAccessDeniedError(reason)
    assert isinstance(denied, McpError)
    assert denied.error.code == code
    assert denied.error.data == {"reason": reason.value}
    assert denied.error.message.startswith(f"{reason.value}: ")
    assert str(denied) == denied.error.message
    assert "ak_" not in denied.error.message


def test_error_codes_avoid_the_codes_mcp_sdks_use() -> None:
    reserved = {-32000, -32001, -32002, -32042, -32700, -32600, -32601, -32602}
    assert AGENT_KEY_REJECTED_CODE not in reserved
    assert AGENT_TOOLSET_UNAVAILABLE_CODE not in reserved
    assert -32099 <= AGENT_KEY_REJECTED_CODE <= -32000
    assert -32099 <= AGENT_TOOLSET_UNAVAILABLE_CODE <= -32000
    assert AGENT_ACCESS_UNAVAILABLE_CODE == mt.INTERNAL_ERROR


# ============================================================================
# resolve_agent_key
# ============================================================================
def _resolve(pool: FakeAgentKeyPool, secret: str = AGENT_SECRET) -> AgentKey:
    async def run() -> AgentKey:
        key = await resolve_agent_key(pool, secret)  # type: ignore[arg-type]
        await asyncio.sleep(0)  # let the last-used touch run
        return key

    return asyncio.run(run())


def _reason(pool: FakeAgentKeyPool, secret: str = AGENT_SECRET) -> AgentAccessReason:
    with pytest.raises(AgentAccessDeniedError) as exc:
        _resolve(pool, secret)
    return exc.value.reason


def test_resolves_an_agent_key_and_touches_last_used() -> None:
    pool = FakeAgentKeyPool()
    key_id = pool.add(allowlist=["listPets", "deletePet"])
    key = _resolve(pool)
    row = pool.rows[key_id]
    assert key == AgentKey(
        key_id=key_id,
        tenant_id=row["tenant_id"],
        toolset_id=row["toolset_id"],
        tool_allowlist=frozenset({"listPets", "deletePet"}),
    )
    assert pool.touched == [key_id]


def test_the_lookup_is_by_prefix_and_agent_kind_only() -> None:
    pool = FakeAgentKeyPool()
    pool.add()
    _resolve(pool)
    sql = pool.queries[0]
    assert "WHERE ak.key_prefix = %s AND ak.kind = 'agent'" in sql
    assert AGENT_KEY_KIND == "agent"
    # The lookup must see revoked rows (to say so), so it must not filter them out.
    assert "ak.deleted_at IS NULL" not in sql


def test_a_workspace_key_with_the_same_secret_is_not_an_agent_key() -> None:
    pool = FakeAgentKeyPool()
    pool.add(kind="workspace", allowlist=[])
    assert _reason(pool) == AgentAccessReason.KEY_INVALID


def test_unknown_or_short_secrets_are_invalid() -> None:
    pool = FakeAgentKeyPool()
    pool.add()
    assert _reason(pool, agent_secret(99)) == AgentAccessReason.KEY_INVALID
    assert _reason(pool, "ak_short") == AgentAccessReason.KEY_INVALID
    assert len(pool.queries) == 1  # the short secret never reached the database


def test_a_wrong_secret_with_a_matching_prefix_is_invalid() -> None:
    pool = FakeAgentKeyPool()
    pool.add()
    assert _reason(pool, AGENT_SECRET[:-1] + "0") == AgentAccessReason.KEY_INVALID


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"revoked": True, "enabled": False}, AgentAccessReason.KEY_REVOKED),
        ({"revoked": True, "expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc)}, AgentAccessReason.KEY_REVOKED),
        ({"enabled": False}, AgentAccessReason.KEY_DISABLED),
        ({"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}, AgentAccessReason.KEY_EXPIRED),
        ({"tenant_active": False}, AgentAccessReason.KEY_INVALID),
    ],
)
def test_unusable_keys_are_refused_with_their_reason(fields, reason) -> None:
    pool = FakeAgentKeyPool()
    pool.add(**fields)
    assert _reason(pool) == reason
    assert pool.touched == []


@pytest.mark.parametrize(
    "fields", [{"revoked": True}, {"enabled": False}, {"expires_at": datetime(2000, 1, 1, tzinfo=timezone.utc)}]
)
def test_key_state_is_only_revealed_to_the_real_secret(fields) -> None:
    pool = FakeAgentKeyPool()
    pool.add(**fields)
    assert _reason(pool, AGENT_SECRET[:-1] + "0") == AgentAccessReason.KEY_INVALID


def test_a_future_expiry_still_resolves() -> None:
    pool = FakeAgentKeyPool()
    pool.add(expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
    assert _resolve(pool).tool_allowlist == frozenset()


def test_a_key_without_a_toolset_is_invalid() -> None:
    pool = FakeAgentKeyPool()
    key_id = pool.add()
    pool.rows[key_id]["toolset_id"] = None
    assert _reason(pool) == AgentAccessReason.KEY_INVALID


def test_the_matching_row_among_several_with_one_prefix_wins() -> None:
    pool = FakeAgentKeyPool()
    other = "ak_" + "0123456789abcdef" * 3 + "fedcba9876543210"
    assert other[:12] == AGENT_SECRET[:12]
    pool.add(secret=other, allowlist=["other"])
    pool.add(allowlist=["mine"])
    assert _resolve(pool).tool_allowlist == frozenset({"mine"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["a", "b"], {"a", "b"}),
        ('["a", "b"]', {"a", "b"}),
        (["a", 1, None], {"a"}),
        ("not json", set()),
        (None, set()),
        ({"a": 1}, set()),
    ],
)
def test_the_stored_allowlist_is_read_defensively(raw, expected) -> None:
    assert agent_access._allowlist(raw) == frozenset(expected)


def test_a_failed_last_used_touch_is_swallowed() -> None:
    pool = MagicMock()
    pool.connection.side_effect = RuntimeError("db down")
    asyncio.run(agent_access._touch_last_used(pool, "k"))


# ============================================================================
# AgentAccessMiddleware (through FastMCP's dispatch)
# ============================================================================
def _fc() -> MagicMock:
    fc = MagicMock()
    fc.request_context = SimpleNamespace(meta=None)
    fc.get_state = AsyncMock(return_value=None)
    return fc


def _middleware(
    *,
    key: AgentKey | Exception = _KEY,
    enabled: frozenset[str] | None | Exception = _ENABLED,
) -> tuple[AgentAccessMiddleware, AsyncMock, AsyncMock]:
    resolver = AsyncMock(side_effect=key) if isinstance(key, Exception) else AsyncMock(return_value=key)
    source = AsyncMock(side_effect=enabled) if isinstance(enabled, Exception) else AsyncMock(return_value=enabled)
    return AgentAccessMiddleware(key_resolver=resolver, enabled_tools=source), resolver, source


def _dispatch(
    mw: AgentAccessMiddleware,
    method: str,
    message: object,
    call_next: AsyncMock,
    *,
    headers: dict[str, str] | None = None,
    fc: object | None = "default",
) -> object:
    ctx = MiddlewareContext(
        message=message,
        fastmcp_context=_fc() if fc == "default" else fc,
        method=method,
        type="request",
    )

    async def run() -> object:
        with patch(
            "apiome_mcp.agent_access.get_http_headers",
            return_value={"authorization": f"Bearer {AGENT_SECRET}"} if headers is None else headers,
        ):
            return await mw(ctx, call_next)

    return asyncio.run(run())


def _tools(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(name=name) for name in names]


def test_list_returns_exactly_the_permitted_intersection() -> None:
    mw, resolver, source = _middleware()
    listed = _dispatch(
        mw,
        "tools/list",
        mt.ListToolsRequest(method="tools/list"),
        AsyncMock(return_value=_tools("listPets", "getPetById", "deletePet", "createPet", "other")),
    )
    assert [tool.name for tool in listed] == ["listPets", "deletePet"]
    assert resolver.await_args.args[1] == AGENT_SECRET
    assert source.await_args.args[1] == _KEY


def test_a_permitted_call_passes_through_with_the_access_visible() -> None:
    seen: list[AgentAccess | None] = []

    async def call_next(context: object) -> str:
        seen.append(current_agent_access())
        return "ok"

    mw, _, _ = _middleware()
    result = _dispatch(
        mw,
        "tools/call",
        mt.CallToolRequestParams(name="listPets", arguments={}),
        AsyncMock(side_effect=call_next),
    )
    assert result == "ok"
    assert seen[0] is not None and seen[0].key == _KEY
    assert current_agent_access() is None  # reset after the request


@pytest.mark.parametrize("name", ["getPetById", "createPet", "nope"])
def test_a_non_permitted_call_looks_like_an_unknown_tool(name: str) -> None:
    mw, _, _ = _middleware()
    call_next = AsyncMock()
    with pytest.raises(NotFoundError, match=f"^Unknown tool: '{name}'$"):
        _dispatch(mw, "tools/call", mt.CallToolRequestParams(name=name, arguments={}), call_next)
    call_next.assert_not_awaited()


def test_initialize_is_not_authenticated() -> None:
    mw, resolver, _ = _middleware()
    call_next = AsyncMock(return_value="init")
    assert _dispatch(mw, "initialize", SimpleNamespace(), call_next, headers={}) == "init"
    resolver.assert_not_awaited()


@pytest.mark.parametrize("method", ["tools/list", "tools/call", "resources/list", "prompts/list"])
def test_every_other_request_needs_a_key(method: str) -> None:
    mw, resolver, _ = _middleware()
    call_next = AsyncMock()
    message = mt.CallToolRequestParams(name="listPets", arguments={}) if method == "tools/call" else SimpleNamespace()
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, method, message, call_next, headers={})
    assert exc.value.reason == AgentAccessReason.KEY_MISSING
    resolver.assert_not_awaited()
    call_next.assert_not_awaited()


def test_the_key_can_arrive_in_request_meta() -> None:
    mw, resolver, _ = _middleware()
    fc = _fc()
    fc.request_context = SimpleNamespace(meta={"apiome_api_key": AGENT_SECRET})
    _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock(return_value=[]), headers={}, fc=fc)
    assert resolver.await_args.args[1] == AGENT_SECRET


def test_the_key_can_arrive_through_the_http_bearer_stash() -> None:
    mw, resolver, _ = _middleware()
    fc = _fc()
    fc.get_state = AsyncMock(return_value=AGENT_SECRET)
    _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock(return_value=[]), headers={}, fc=fc)
    assert resolver.await_args.args[1] == AGENT_SECRET


def test_no_fastmcp_context_fails_closed() -> None:
    mw, resolver, _ = _middleware()
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock(), fc=None)
    assert exc.value.reason == AgentAccessReason.KEY_MISSING
    resolver.assert_not_awaited()


def test_a_refused_key_stops_the_request() -> None:
    mw, _, source = _middleware(key=AgentAccessDeniedError(AgentAccessReason.KEY_EXPIRED))
    call_next = AsyncMock()
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, "tools/list", SimpleNamespace(), call_next)
    assert exc.value.reason == AgentAccessReason.KEY_EXPIRED
    source.assert_not_awaited()
    call_next.assert_not_awaited()


def test_an_unavailable_toolset_stops_the_request() -> None:
    mw, _, _ = _middleware(enabled=None)
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock())
    assert exc.value.reason == AgentAccessReason.TOOLSET_UNAVAILABLE
    assert exc.value.error.code == AGENT_TOOLSET_UNAVAILABLE_CODE


def test_the_default_source_fails_closed_until_agx_1_2() -> None:
    mw = AgentAccessMiddleware(key_resolver=AsyncMock(return_value=_KEY))
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock())
    assert exc.value.reason == AgentAccessReason.TOOLSET_UNAVAILABLE


@pytest.mark.parametrize("where", ["key", "enabled"])
def test_an_unexpected_failure_fails_closed_without_leaking_it(where: str) -> None:
    boom = RuntimeError("password=hunter2 at db.internal")
    mw, _, _ = _middleware(**{where: boom})
    with pytest.raises(AgentAccessDeniedError) as exc:
        _dispatch(mw, "tools/list", SimpleNamespace(), AsyncMock())
    assert exc.value.reason == AgentAccessReason.ACCESS_UNAVAILABLE
    assert "hunter2" not in exc.value.error.message
    assert exc.value.__cause__ is None


def test_list_and_call_handlers_fail_closed_outside_on_request() -> None:
    mw, _, _ = _middleware()
    ctx = MiddlewareContext(message=SimpleNamespace(name="listPets"), fastmcp_context=None)
    for handler in (mw.on_list_tools, mw.on_call_tool):
        call_next = AsyncMock()
        with pytest.raises(AgentAccessDeniedError):
            asyncio.run(handler(ctx, call_next))
        call_next.assert_not_awaited()


# ============================================================================
# Surface separation (MTG-2.1 / MTG-5.5)
# ============================================================================
def test_the_catalog_server_never_mounts_agent_access() -> None:
    from apiome_mcp.server import mcp

    assert not any(isinstance(middleware, AgentAccessMiddleware) for middleware in mcp.middleware)
