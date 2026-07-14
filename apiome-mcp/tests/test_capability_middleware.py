"""Call-time capability gate — MTG-2.2 (#4771)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext

from apiome_mcp.capability_middleware import CapabilityCallGateMiddleware
from apiome_mcp.capability_policy import (
    CAPABILITY_DISABLED_CODE,
    capability_disabled_anonymous_message,
    capability_disabled_message,
    load_tenant_mcp_policy_snapshot,
)
from apiome_mcp.effective_policy import KeyCapabilitySnapshot, TenantMcpPolicySnapshot, TenantToolFlags
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope


def _auth(
    *,
    tenant_id: str | None = None,
    key_id: str | None = None,
    capability_mode: str = "explicit",
    enabled_tools: frozenset[str] = frozenset(),
) -> McpAuthContext:
    return McpAuthContext(
        key_id=key_id or str(uuid.uuid4()),
        tenant_id=tenant_id or str(uuid.uuid4()),
        label="test",
        scope=Scope(),
        capability_mode=capability_mode,  # type: ignore[arg-type]
        enabled_tools=enabled_tools,
    )


def _fc_with_pool(pool: object) -> MagicMock:
    fc = MagicMock()
    fc.lifespan_context = {"db_pool": pool}
    fc.request_context = SimpleNamespace(meta=None)
    fc.get_state = AsyncMock(return_value=None)
    return fc


def test_capability_disabled_message_stable_and_secret_free() -> None:
    msg = capability_disabled_message("spec.search")
    assert msg.startswith(f"{CAPABILITY_DISABLED_CODE}:")
    assert "spec.search" in msg
    assert "tenant admin" in msg.lower()
    assert "Bearer" not in msg
    assert "api_key" not in msg
    assert "secret" not in msg.lower()


def test_capability_disabled_anonymous_message_no_api_key_wording() -> None:
    msg = capability_disabled_anonymous_message("spec.search")
    assert msg.startswith(f"{CAPABILITY_DISABLED_CODE}:")
    assert "spec.search" in msg
    assert "anonymous" in msg.lower()
    assert "this API key" not in msg
    assert "disabled for this API key" not in msg
    assert "Bearer" not in msg
    assert "secret" not in msg.lower()


def test_middleware_list_tools_passthrough() -> None:
    mw = CapabilityCallGateMiddleware()
    sentinel = [SimpleNamespace(name="ping")]
    call_next = AsyncMock(return_value=sentinel)
    ctx = MiddlewareContext(message=SimpleNamespace(), fastmcp_context=None)

    async def run() -> object:
        return await mw.on_list_tools(ctx, call_next)

    assert asyncio.run(run()) is sentinel
    call_next.assert_awaited_once_with(ctx)


def test_anonymous_call_passes_through_when_host_tenant_unset() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )
    settings = SimpleNamespace(anonymous_policy_tenant_id=None)

    async def run() -> object:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=None,
            ) as resolve,
            patch(
                "apiome_mcp.capability_middleware.get_settings",
                return_value=settings,
            ),
        ):
            result = await mw.on_call_tool(ctx, call_next)
            resolve.assert_awaited_once()
            return result

    assert asyncio.run(run()) == {"ok": True}
    call_next.assert_awaited_once()


def test_anonymous_denied_when_allow_anonymous_mcp_false() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    host = uuid.uuid4()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )
    settings = SimpleNamespace(anonymous_policy_tenant_id=host)
    tenant = TenantMcpPolicySnapshot(
        default_mode="all",
        tools={},
        allow_anonymous_mcp=False,
    )

    async def run() -> None:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "apiome_mcp.capability_middleware.get_settings",
                return_value=settings,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ) as load,
        ):
            with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE) as exc_info:
                await mw.on_call_tool(ctx, call_next)
            assert "anonymous" in str(exc_info.value).lower()
            load.assert_awaited_once_with(pool, str(host))

    asyncio.run(run())
    call_next.assert_not_awaited()


def test_anonymous_denied_when_tool_not_in_anonymous_set() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    host = uuid.uuid4()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="spec.search"),
        fastmcp_context=fc,
    )
    settings = SimpleNamespace(anonymous_policy_tenant_id=host)
    tenant = TenantMcpPolicySnapshot(
        default_mode="explicit",
        tools={
            "ping": TenantToolFlags(in_ceiling=True, default_enabled=True, anonymous_enabled=True),
            "spec.search": TenantToolFlags(in_ceiling=True, default_enabled=True, anonymous_enabled=False),
        },
        allow_anonymous_mcp=True,
    )

    async def run() -> None:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "apiome_mcp.capability_middleware.get_settings",
                return_value=settings,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE):
                await mw.on_call_tool(ctx, call_next)

    asyncio.run(run())
    call_next.assert_not_awaited()


def test_anonymous_allowed_when_tool_in_anonymous_set() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    host = uuid.uuid4()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )
    settings = SimpleNamespace(anonymous_policy_tenant_id=host)
    tenant = TenantMcpPolicySnapshot(
        default_mode="explicit",
        tools={
            "ping": TenantToolFlags(in_ceiling=True, default_enabled=True, anonymous_enabled=True),
        },
        allow_anonymous_mcp=True,
    )

    async def run() -> object:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "apiome_mcp.capability_middleware.get_settings",
                return_value=settings,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            return await mw.on_call_tool(ctx, call_next)

    assert asyncio.run(run()) == {"ok": True}
    call_next.assert_awaited_once()


def test_authenticated_ignores_anonymous_kill_switch() -> None:
    """Authenticated keys use MTG-1.4 only; anonymous fields must not apply."""
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(enabled_tools=frozenset({"ping"}))
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )
    # Host tenant would deny anonymous, but caller is authenticated.
    settings = SimpleNamespace(anonymous_policy_tenant_id=uuid.uuid4())
    tenant = TenantMcpPolicySnapshot(
        default_mode="all",
        tools={},
        allow_anonymous_mcp=False,
    )

    async def run() -> object:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={"authorization": "Bearer x"},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "apiome_mcp.capability_middleware.get_settings",
                return_value=settings,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ) as schedule,
        ):
            result = await mw.on_call_tool(ctx, call_next)
            schedule.assert_not_called()
            return result

    assert asyncio.run(run()) == {"ok": True}
    call_next.assert_awaited_once()


def test_missing_fastmcp_context_passes_through() -> None:
    mw = CapabilityCallGateMiddleware()
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=None,
    )

    assert asyncio.run(mw.on_call_tool(ctx, call_next)) == {"ok": True}
    call_next.assert_awaited_once()


def test_disabled_tool_raises_capability_disabled() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(enabled_tools=frozenset({"ping"}))
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="spec.search"),
        fastmcp_context=fc,
    )
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})

    async def run() -> None:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={"authorization": "Bearer fake-secret-not-logged"},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
            patch(
                "apiome_mcp.capability_middleware.detect_mcp_transport",
                return_value="http",
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ) as schedule,
        ):
            try:
                await mw.on_call_tool(ctx, call_next)
            finally:
                schedule.assert_called_once()
                kwargs = schedule.call_args.kwargs
                assert kwargs["key_id"] == auth.key_id
                assert kwargs["tenant_id"] == auth.tenant_id
                assert kwargs["tool_id"] == "spec.search"
                assert kwargs["transport"] == "http"
                assert kwargs["reason"] == "not_in_key_enable_set"
                assert "arguments" not in kwargs
                assert "fake-secret" not in str(kwargs)

    with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE) as exc_info:
        asyncio.run(run())
    assert "spec.search" in str(exc_info.value)
    assert "fake-secret" not in str(exc_info.value)
    call_next.assert_not_awaited()


def test_enabled_tool_allows_call_without_denial_audit() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(enabled_tools=frozenset({"ping", "spec.list"}))
    call_next = AsyncMock(return_value={"pong": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})

    async def run() -> object:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={"authorization": "Bearer ok"},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ) as schedule,
        ):
            result = await mw.on_call_tool(ctx, call_next)
            schedule.assert_not_called()
            return result

    assert asyncio.run(run()) == {"pong": True}
    call_next.assert_awaited_once()


def test_http_bearer_and_stdio_meta_both_reach_resolve() -> None:
    """Acceptance: gate uses the same resolve path for HTTP Bearer and stdio ``_meta``."""
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(capability_mode="inherit", enabled_tools=frozenset())
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})

    async def _call(headers: dict[str, str]) -> object:
        call_next = AsyncMock(return_value={"ok": True})
        ctx = MiddlewareContext(
            message=SimpleNamespace(name="ping"),
            fastmcp_context=fc,
        )
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value=headers,
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ) as resolve,
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
        ):
            result = await mw.on_call_tool(ctx, call_next)
            resolve.assert_awaited_once()
            assert resolve.await_args is not None
            assert resolve.await_args.kwargs["headers"] == headers
            call_next.assert_awaited_once()
            return result

    async def run() -> None:
        assert await _call({"authorization": "Bearer http-secret-value"}) == {"ok": True}
        # stdio: no HTTP Authorization; resolve_optional_mcp_auth still reads request meta.
        assert await _call({}) == {"ok": True}

    asyncio.run(run())


def test_concurrent_two_keys_same_tenant_different_enable_sets() -> None:
    """Two keys on one tenant: each enable-set is enforced independently under concurrency."""
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    tenant_id = str(uuid.uuid4())
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})
    key_ping = _auth(
        tenant_id=tenant_id,
        enabled_tools=frozenset({"ping"}),
    )
    key_list = _auth(
        tenant_id=tenant_id,
        enabled_tools=frozenset({"spec.list"}),
    )

    async def invoke(auth: McpAuthContext, tool: str) -> str:
        fc = _fc_with_pool(pool)
        call_next = AsyncMock(return_value={"tool": tool})
        ctx = MiddlewareContext(
            message=SimpleNamespace(name=tool),
            fastmcp_context=fc,
        )
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ),
        ):
            try:
                result = await mw.on_call_tool(ctx, call_next)
                return f"ok:{result['tool']}"
            except ToolError as exc:
                return f"deny:{exc}"

    async def run() -> list[str]:
        return list(
            await asyncio.gather(
                invoke(key_ping, "ping"),
                invoke(key_ping, "spec.list"),
                invoke(key_list, "spec.list"),
                invoke(key_list, "ping"),
            )
        )

    outcomes = asyncio.run(run())
    assert outcomes[0] == "ok:ping"
    assert outcomes[1].startswith(f"deny:{CAPABILITY_DISABLED_CODE}")
    assert "spec.list" in outcomes[1]
    assert outcomes[2] == "ok:spec.list"
    assert outcomes[3].startswith(f"deny:{CAPABILITY_DISABLED_CODE}")
    assert "ping" in outcomes[3]


def test_ceiling_denies_even_with_explicit_grant() -> None:
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(enabled_tools=frozenset({"ping"}))
    tenant = TenantMcpPolicySnapshot(
        default_mode="explicit",
        tools={
            "ping": TenantToolFlags(in_ceiling=False, default_enabled=False),
        },
    )
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name="ping"),
        fastmcp_context=fc,
    )

    async def run() -> None:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                new_callable=AsyncMock,
                return_value=auth,
            ),
            patch(
                "apiome_mcp.capability_middleware.load_tenant_mcp_policy_snapshot",
                new_callable=AsyncMock,
                return_value=tenant,
            ),
            patch(
                "apiome_mcp.capability_middleware.detect_mcp_transport",
                return_value="stdio",
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ) as schedule,
        ):
            try:
                await mw.on_call_tool(ctx, call_next)
            finally:
                schedule.assert_called_once()
                assert schedule.call_args.kwargs["reason"] == "not_in_ceiling"
                assert schedule.call_args.kwargs["transport"] == "stdio"

    with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE):
        asyncio.run(run())
    call_next.assert_not_awaited()


def test_load_tenant_mcp_policy_snapshot_none_when_missing() -> None:
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value=None)
    cur.execute = AsyncMock()
    cm_cur = AsyncMock()
    cm_cur.__aenter__ = AsyncMock(return_value=cur)
    cm_cur.__aexit__ = AsyncMock(return_value=None)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cm_cur)
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> TenantMcpPolicySnapshot | None:
        return await load_tenant_mcp_policy_snapshot(pool, str(uuid.uuid4()))

    assert asyncio.run(run()) is None


def test_load_tenant_mcp_policy_snapshot_builds_flags() -> None:
    tid = str(uuid.uuid4())
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value={"default_mode": "explicit", "allow_anonymous_mcp": False})
    cur.fetchall = AsyncMock(
        return_value=[
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": False,
                "anonymous_enabled": True,
            },
            {
                "tool_id": "spec.list",
                "in_ceiling": True,
                "default_enabled": True,
                "anonymous_enabled": False,
            },
        ]
    )
    cur.execute = AsyncMock()
    cm_cur = AsyncMock()
    cm_cur.__aenter__ = AsyncMock(return_value=cur)
    cm_cur.__aexit__ = AsyncMock(return_value=None)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cm_cur)
    cm_conn = AsyncMock()
    cm_conn.__aenter__ = AsyncMock(return_value=conn)
    cm_conn.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.connection = MagicMock(return_value=cm_conn)

    async def run() -> TenantMcpPolicySnapshot | None:
        return await load_tenant_mcp_policy_snapshot(pool, tid)

    snap = asyncio.run(run())
    assert snap is not None
    assert snap.default_mode == "explicit"
    assert snap.allow_anonymous_mcp is False
    assert snap.tools["ping"] == TenantToolFlags(in_ceiling=True, default_enabled=False, anonymous_enabled=True)
    assert snap.tools["spec.list"].default_enabled is True
    assert snap.tools["spec.list"].anonymous_enabled is False


def test_auth_context_key_capability_snapshot() -> None:
    auth = _auth(capability_mode="explicit", enabled_tools=frozenset({"ping"}))
    snap = auth.key_capability_snapshot()
    assert isinstance(snap, KeyCapabilitySnapshot)
    assert snap.capability_mode == "explicit"
    assert snap.enabled_tools == frozenset({"ping"})
