"""Policy freshness — MTG-2.5 (#4774).

Tenant/key policy must be re-resolved on every authenticated ``tools/call``.
An admin write (simulated here) must flip allow↔deny on the next call against
the **same** middleware instance — no process restart.
"""

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
    POLICY_FRESHNESS_LAG_BUDGET_SECONDS,
)
from apiome_mcp.effective_policy import TenantMcpPolicySnapshot, TenantToolFlags
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope


def _auth(
    *,
    tenant_id: str | None = None,
    key_id: str | None = None,
    capability_mode: str = "inherit",
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


def test_policy_freshness_lag_budget_is_zero() -> None:
    """Documented MVP budget: next call after commit must observe the write."""
    assert POLICY_FRESHNESS_LAG_BUDGET_SECONDS == 0


def test_tenant_policy_change_visible_on_next_call_without_restart() -> None:
    """Same middleware instance: admin-style policy flip takes effect immediately."""
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    auth = _auth(capability_mode="inherit")
    tool = "spec.search"

    # Before write: default_mode=all → tool enabled under inherit.
    tenant_before = TenantMcpPolicySnapshot(default_mode="all", tools={})
    # After write: explicit ceiling excludes the tool → deny (ceiling).
    tenant_after = TenantMcpPolicySnapshot(
        default_mode="explicit",
        tools={
            "ping": TenantToolFlags(in_ceiling=True, default_enabled=True),
            tool: TenantToolFlags(in_ceiling=False, default_enabled=False),
        },
    )
    load_policy = AsyncMock(side_effect=[tenant_before, tenant_after])
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name=tool),
        fastmcp_context=fc,
    )

    async def run() -> None:
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
                load_policy,
            ),
            patch(
                "apiome_mcp.capability_middleware.schedule_mcp_capability_denial",
            ) as schedule,
        ):
            first = await mw.on_call_tool(ctx, call_next)
            assert first == {"ok": True}
            call_next.assert_awaited_once()
            schedule.assert_not_called()

            with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE):
                await mw.on_call_tool(ctx, call_next)

            schedule.assert_called_once()
            assert load_policy.await_count == 2

    asyncio.run(run())
    assert call_next.await_count == 1


def test_key_grant_change_visible_on_next_call_without_restart() -> None:
    """Key enable-set edits (same process) flip allow→deny on the next call."""
    mw = CapabilityCallGateMiddleware()
    pool = MagicMock()
    fc = _fc_with_pool(pool)
    tenant = TenantMcpPolicySnapshot(default_mode="all", tools={})
    tool = "spec.search"
    auth_enabled = _auth(
        capability_mode="explicit",
        enabled_tools=frozenset({tool}),
    )
    auth_disabled = _auth(
        key_id=auth_enabled.key_id,
        tenant_id=auth_enabled.tenant_id,
        capability_mode="explicit",
        enabled_tools=frozenset(),
    )
    resolve_auth = AsyncMock(side_effect=[auth_enabled, auth_disabled])
    call_next = AsyncMock(return_value={"ok": True})
    ctx = MiddlewareContext(
        message=SimpleNamespace(name=tool),
        fastmcp_context=fc,
    )

    async def run() -> None:
        with (
            patch(
                "apiome_mcp.capability_middleware.get_http_headers",
                return_value={"authorization": "Bearer ok"},
            ),
            patch(
                "apiome_mcp.capability_middleware.resolve_optional_mcp_auth",
                resolve_auth,
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
            first = await mw.on_call_tool(ctx, call_next)
            assert first == {"ok": True}
            schedule.assert_not_called()

            with pytest.raises(ToolError, match=CAPABILITY_DISABLED_CODE):
                await mw.on_call_tool(ctx, call_next)

            schedule.assert_called_once()
            assert resolve_auth.await_count == 2

    asyncio.run(run())
    assert call_next.await_count == 1
