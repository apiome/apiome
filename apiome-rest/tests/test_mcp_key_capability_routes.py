"""Endpoint tests for per-key MCP capability grants (MTG-3.3, #4777).

DB helpers are mocked on ``app.mcp_key_routes.db`` so these tests exercise the
route contract: admin-only PUT, inherit clears tools, ceiling 422 with
offending ids, and preview parity with the MTG-1.4 resolver.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_effective_policy import (
    KeyCapabilitySnapshot,
    TenantMcpPolicySnapshot,
    TenantToolFlags,
    preview_effective_tools,
)

client = TestClient(app)

_TENANT = "t1"
_USER = "u1"
_KEY_ID = "11111111-1111-1111-1111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"}
NOW = datetime(2026, 7, 13, 18, 0, 0, tzinfo=timezone.utc)
BASE = f"/v1/tenants/acme/mcp-keys/{_KEY_ID}/capabilities"


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=True):
        yield


def _key_row(**over):
    row = {
        "id": _KEY_ID,
        "prefix": "abcdefghijkl...",
        "label": "CI key",
        "scope_json": {"tenants": [_TENANT], "projects": []},
        "capability_mode": "inherit",
        "enabled_tools": [],
        "created_at": NOW,
        "expires_at": None,
        "revoked_at": None,
        "last_used_at": None,
        "created_by": _USER,
    }
    row.update(over)
    return row


def _explicit_policy(*, ceiling_ok=("ping", "spec.list"), ceiling_off=("spec.search",)):
    tools = []
    for tid in ceiling_ok:
        tools.append(
            {
                "tool_id": tid,
                "in_ceiling": True,
                "default_enabled": True,
                "anonymous_enabled": True,
            }
        )
    for tid in ceiling_off:
        tools.append(
            {
                "tool_id": tid,
                "in_ceiling": False,
                "default_enabled": False,
                "anonymous_enabled": False,
            }
        )
    return {
        "default_mode": "explicit",
        "allow_anonymous_mcp": True,
        "updated_at": NOW,
        "updated_by": _USER,
        "tools": tools,
    }


def test_put_explicit_persists_tools():
    updated = _key_row(
        capability_mode="explicit",
        enabled_tools=["ping", "spec.list"],
    )
    with patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=_explicit_policy()
    ), patch(
        "app.mcp_key_routes.db.update_mcp_api_key_capabilities", return_value=updated
    ) as update:
        r = client.put(
            BASE,
            json={"mode": "explicit", "enabled_tools": ["ping", "spec.list"]},
        )
    assert r.status_code == 200
    assert r.json() == {
        "mode": "explicit",
        "enabled_tools": ["ping", "spec.list"],
    }
    update.assert_called_once_with(
        _TENANT,
        _KEY_ID,
        capability_mode="explicit",
        enabled_tools=["ping", "spec.list"],
    )


def test_put_inherit_clears_explicit_list():
    updated = _key_row(capability_mode="inherit", enabled_tools=[])
    with patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=None
    ), patch(
        "app.mcp_key_routes.db.update_mcp_api_key_capabilities", return_value=updated
    ) as update:
        r = client.put(
            BASE,
            json={
                "mode": "inherit",
                "enabled_tools": ["ping", "spec.search"],
            },
        )
    assert r.status_code == 200
    assert r.json() == {"mode": "inherit", "enabled_tools": []}
    update.assert_called_once_with(
        _TENANT,
        _KEY_ID,
        capability_mode="inherit",
        enabled_tools=[],
    )


def test_put_exceeding_ceiling_422_with_offending_ids():
    with patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=_explicit_policy()
    ), patch("app.mcp_key_routes.db.update_mcp_api_key_capabilities") as update:
        r = client.put(
            BASE,
            json={
                "mode": "explicit",
                "enabled_tools": ["ping", "spec.search", "not.a.tool"],
            },
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "MCP key enable-set exceeds tenant ceiling"
    assert detail["offending_tool_ids"] == ["spec.search", "not.a.tool"]
    update.assert_not_called()


def test_put_404_when_missing_or_revoked():
    with patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=None
    ), patch(
        "app.mcp_key_routes.db.update_mcp_api_key_capabilities", return_value=None
    ):
        r = client.put(BASE, json={"mode": "inherit"})
    assert r.status_code == 404


def test_put_forbidden_for_non_admin():
    with patch(
        "app.mcp_key_routes.db.is_user_tenant_admin", return_value=False
    ), patch("app.mcp_key_routes.db.update_mcp_api_key_capabilities") as update:
        r = client.put(BASE, json={"mode": "inherit"})
    assert r.status_code == 403
    update.assert_not_called()


def test_preview_matches_resolver():
    policy = _explicit_policy()
    body = {"mode": "explicit", "enabled_tools": ["ping", "spec.list"]}
    with patch(
        "app.mcp_key_routes.db.get_mcp_api_key", return_value=_key_row()
    ), patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=policy
    ):
        r = client.post(f"{BASE}/preview", json=body)
    assert r.status_code == 200
    tools = r.json()["tools"]
    assert tools
    assert all("tool_id" in row and "enabled" in row for row in tools)

    snap = TenantMcpPolicySnapshot(
        default_mode="explicit",
        allow_anonymous_mcp=True,
        tools={
            t["tool_id"]: TenantToolFlags(
                in_ceiling=t["in_ceiling"],
                default_enabled=t["default_enabled"],
                anonymous_enabled=t["anonymous_enabled"],
            )
            for t in policy["tools"]
        },
    )
    expected = preview_effective_tools(
        key=KeyCapabilitySnapshot(
            capability_mode="explicit",
            enabled_tools=frozenset({"ping", "spec.list"}),
        ),
        tenant=snap,
    )
    by_id = {row["tool_id"]: row for row in tools}
    for row in expected:
        got = by_id[row.tool_id]
        assert got["enabled"] is row.enabled
        assert got["deny_reason"] == (
            row.deny_reason.value if row.deny_reason else None
        )


def test_preview_ceiling_violation_422():
    with patch(
        "app.mcp_key_routes.db.get_mcp_api_key", return_value=_key_row()
    ), patch(
        "app.mcp_key_routes.db.get_tenant_mcp_policy", return_value=_explicit_policy()
    ):
        r = client.post(
            f"{BASE}/preview",
            json={"mode": "explicit", "enabled_tools": ["spec.search"]},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["offending_tool_ids"] == ["spec.search"]


def test_preview_404_unknown_key():
    with patch("app.mcp_key_routes.db.get_mcp_api_key", return_value=None):
        r = client.post(f"{BASE}/preview", json={"mode": "inherit"})
    assert r.status_code == 404


def test_preview_forbidden_for_non_admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=False):
        r = client.post(f"{BASE}/preview", json={"mode": "inherit"})
    assert r.status_code == 403
