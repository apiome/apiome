"""Endpoint tests for tenant MCP policy CRUD (MTG-3.1, #4775).

The DB layer is mocked (patched on ``app.mcp_policy_routes.db``) so these tests
exercise the route contract: member GET, admin-only PUT, 422 validation, and
response shapes that match the persisted snapshot.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT = "t1"
_USER = "u1"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"}
NOW = datetime(2026, 7, 13, 18, 0, 0, tzinfo=timezone.utc)
BASE = "/v1/tenants/acme/mcp-policy"


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _admin():
    """Mutations require a tenant admin; default every test to an admin caller."""
    with patch("app.mcp_policy_routes.db.is_user_tenant_admin", return_value=True):
        yield


def _policy_row(**over):
    row = {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "updated_at": NOW,
        "updated_by": _USER,
        "tools": [
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": True,
                "anonymous_enabled": True,
            }
        ],
    }
    row.update(over)
    return row


def test_get_returns_db_snapshot():
    stored = _policy_row()
    with patch(
        "app.mcp_policy_routes.db.get_tenant_mcp_policy", return_value=stored
    ) as get_policy:
        r = client.get(BASE)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "tools": [
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": True,
                "anonymous_enabled": True,
            }
        ],
        "updated_at": "2026-07-13T18:00:00Z",
        "updated_by": _USER,
    }
    get_policy.assert_called_once_with(_TENANT)


def test_get_is_readable_by_non_admin_members():
    with patch(
        "app.mcp_policy_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.mcp_policy_routes.db.get_tenant_mcp_policy",
        return_value=_policy_row(tools=[]),
    ):
        r = client.get(BASE)
    assert r.status_code == 200
    assert r.json()["default_mode"] == "all"
    assert r.json()["tools"] == []


def test_get_synthesizes_defaults_when_unseeded():
    with patch("app.mcp_policy_routes.db.get_tenant_mcp_policy", return_value=None):
        r = client.get(BASE)
    assert r.status_code == 200
    assert r.json() == {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "tools": [],
        "updated_at": None,
        "updated_by": None,
    }


def test_put_forbidden_for_non_admin():
    with patch("app.mcp_policy_routes.db.is_user_tenant_admin", return_value=False):
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "allow_anonymous_mcp": True,
                "tools": [],
            },
        )
    assert r.status_code == 403
    assert "tenant administrators" in r.json()["detail"]


def test_admin_put_persists_and_returns_body():
    stored = _policy_row(
        default_mode="explicit",
        allow_anonymous_mcp=False,
        tools=[
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": False,
                "anonymous_enabled": False,
            }
        ],
    )
    with patch(
        "app.mcp_policy_routes.db.replace_tenant_mcp_policy", return_value=stored
    ) as replace:
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "allow_anonymous_mcp": False,
                "tools": [
                    {
                        "tool_id": "ping",
                        "in_ceiling": True,
                        "default_enabled": False,
                        "anonymous_enabled": False,
                    }
                ],
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["default_mode"] == "explicit"
    assert body["allow_anonymous_mcp"] is False
    assert body["tools"] == [
        {
            "tool_id": "ping",
            "in_ceiling": True,
            "default_enabled": False,
            "anonymous_enabled": False,
        }
    ]
    replace.assert_called_once_with(
        _TENANT,
        default_mode="explicit",
        allow_anonymous_mcp=False,
        tools=[
            {
                "tool_id": "ping",
                "in_ceiling": True,
                "default_enabled": False,
                "anonymous_enabled": False,
            }
        ],
        updated_by=_USER,
        actor_label=None,
    )


def test_put_rejects_unknown_tool_id_with_422():
    with patch("app.mcp_policy_routes.db.replace_tenant_mcp_policy") as replace:
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "tools": [
                    {
                        "tool_id": "not.a.real.tool",
                        "in_ceiling": True,
                        "default_enabled": True,
                        "anonymous_enabled": True,
                    }
                ],
            },
        )
    assert r.status_code == 422
    assert "Unknown MCP tool id" in r.json()["detail"]
    replace.assert_not_called()


def test_put_rejects_default_enabled_without_ceiling_with_422():
    with patch("app.mcp_policy_routes.db.replace_tenant_mcp_policy") as replace:
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "tools": [
                    {
                        "tool_id": "ping",
                        "in_ceiling": False,
                        "default_enabled": True,
                        "anonymous_enabled": True,
                    }
                ],
            },
        )
    assert r.status_code == 422
    assert "default_enabled requires in_ceiling" in r.json()["detail"]
    replace.assert_not_called()


def test_put_rejects_duplicate_tool_id_with_422():
    with patch("app.mcp_policy_routes.db.replace_tenant_mcp_policy") as replace:
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "tools": [
                    {
                        "tool_id": "ping",
                        "in_ceiling": True,
                        "default_enabled": True,
                        "anonymous_enabled": True,
                    },
                    {
                        "tool_id": "ping",
                        "in_ceiling": True,
                        "default_enabled": False,
                        "anonymous_enabled": False,
                    },
                ],
            },
        )
    assert r.status_code == 422
    assert "Duplicate MCP tool id" in r.json()["detail"]
    replace.assert_not_called()


def test_put_allows_anonymous_enabled_outside_ceiling():
    """V165: anonymous enable-set is independent of ceiling for MVP."""
    stored = _policy_row(
        default_mode="explicit",
        tools=[
            {
                "tool_id": "ping",
                "in_ceiling": False,
                "default_enabled": False,
                "anonymous_enabled": True,
            }
        ],
    )
    with patch(
        "app.mcp_policy_routes.db.replace_tenant_mcp_policy", return_value=stored
    ) as replace:
        r = client.put(
            BASE,
            json={
                "default_mode": "explicit",
                "tools": [
                    {
                        "tool_id": "ping",
                        "in_ceiling": False,
                        "default_enabled": False,
                        "anonymous_enabled": True,
                    }
                ],
            },
        )
    assert r.status_code == 200
    replace.assert_called_once()


def test_put_forwards_actor_label_from_auth():
    stored = _policy_row(default_mode="explicit", tools=[])
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
        "user_email": "dana@acme.io",
    }
    with patch(
        "app.mcp_policy_routes.db.replace_tenant_mcp_policy", return_value=stored
    ) as replace:
        r = client.put(
            BASE,
            json={"default_mode": "explicit", "allow_anonymous_mcp": True, "tools": []},
        )
    assert r.status_code == 200
    assert replace.call_args.kwargs["actor_label"] == "dana@acme.io"


def test_history_returns_change_rows_newest_first():
    rows = [
        {
            "id": "c2",
            "actor_user_id": _USER,
            "actor_label": "dana@acme.io",
            "created_at": NOW,
            "before_policy": {
                "default_mode": "all",
                "allow_anonymous_mcp": True,
                "tools": [],
            },
            "after_policy": {
                "default_mode": "explicit",
                "allow_anonymous_mcp": False,
                "tools": [
                    {
                        "tool_id": "ping",
                        "in_ceiling": True,
                        "default_enabled": False,
                        "anonymous_enabled": False,
                    }
                ],
            },
        }
    ]
    with patch(
        "app.mcp_policy_routes.db.list_tenant_mcp_policy_changes", return_value=rows
    ) as list_changes:
        r = client.get(f"{BASE}/history?limit=10")
    assert r.status_code == 200
    body = r.json()
    assert len(body["changes"]) == 1
    change = body["changes"][0]
    assert change["id"] == "c2"
    assert change["actor_label"] == "dana@acme.io"
    assert change["before_policy"]["default_mode"] == "all"
    assert change["after_policy"]["tools"][0]["tool_id"] == "ping"
    assert change["after_policy"]["tools"][0]["default_enabled"] is False
    list_changes.assert_called_once_with(_TENANT, limit=10)


def test_history_readable_by_non_admin_members():
    with patch(
        "app.mcp_policy_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.mcp_policy_routes.db.list_tenant_mcp_policy_changes", return_value=[]
    ):
        r = client.get(f"{BASE}/history")
    assert r.status_code == 200
    assert r.json() == {"changes": []}
