"""Admin authorization & read models for tenant MCP governance (MTG-3.4, #4778).

Covers the shared gate and the mcp-policy route contract:

* member GET ok (read model)
* member PUT 403
* non-member 403 / unknown tenant 404 (via ``validate_authentication``)
* API key auth on PUT 403 even when the key maps to a tenant admin
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import require_tenant_admin_session, validate_authentication
from app.main import app

client = TestClient(app)

_TENANT = "t1"
_USER = "u1"
_POLICY = "/v1/tenants/acme/mcp-policy"
_KEYS = "/v1/tenants/acme/mcp-keys"
NOW = datetime(2026, 7, 13, 18, 0, 0, tzinfo=timezone.utc)

_PUT_BODY = {
    "default_mode": "explicit",
    "allow_anonymous_mcp": True,
    "tools": [],
}


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def test_require_tenant_admin_session_rejects_api_key_even_if_admin_user():
    """Publish / X-API-Key must not escalate via created_by → is_user_tenant_admin."""
    db_handle = MagicMock()
    db_handle.is_user_tenant_admin.return_value = True
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin_session(
            db_handle,
            {
                "tenant_id": _TENANT,
                "user_id": _USER,
                "auth_method": "api_key",
            },
            detail="Only tenant administrators can manage MCP policy",
        )
    assert exc.value.status_code == 403
    assert "API keys cannot mutate governance" in str(exc.value.detail)
    db_handle.is_user_tenant_admin.assert_not_called()


def test_require_tenant_admin_session_allows_jwt_admin():
    db_handle = MagicMock()
    db_handle.is_user_tenant_admin.return_value = True
    tid = require_tenant_admin_session(
        db_handle,
        {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"},
        detail="Only tenant administrators can manage MCP policy",
    )
    assert tid == _TENANT
    db_handle.is_user_tenant_admin.assert_called_once_with(_TENANT, _USER)


def test_require_tenant_admin_session_rejects_jwt_non_admin():
    db_handle = MagicMock()
    db_handle.is_user_tenant_admin.return_value = False
    with pytest.raises(HTTPException) as exc:
        require_tenant_admin_session(
            db_handle,
            {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"},
            detail="Only tenant administrators can manage MCP policy",
        )
    assert exc.value.status_code == 403
    assert "tenant administrators" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# mcp-policy route contract (acceptance criteria)
# ---------------------------------------------------------------------------


def test_member_get_ok_read_model():
    """Tenant members may read the policy snapshot (UI read model)."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
    }
    stored = {
        "default_mode": "all",
        "allow_anonymous_mcp": True,
        "updated_at": NOW,
        "updated_by": _USER,
        "tools": [],
    }
    with patch(
        "app.mcp_policy_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.mcp_policy_routes.db.get_tenant_mcp_policy", return_value=stored
    ):
        r = client.get(_POLICY)
    assert r.status_code == 200
    body = r.json()
    assert body["default_mode"] == "all"
    assert body["tools"] == []
    assert body["updated_by"] == _USER


def test_member_put_403():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "jwt",
    }
    with patch(
        "app.mcp_policy_routes.db.is_user_tenant_admin", return_value=False
    ), patch("app.mcp_policy_routes.db.replace_tenant_mcp_policy") as replace:
        r = client.put(_POLICY, json=_PUT_BODY)
    assert r.status_code == 403
    assert "tenant administrators" in r.json()["detail"]
    replace.assert_not_called()


def test_api_key_auth_on_put_403_even_when_key_maps_to_admin():
    """API key whose created_by is a tenant admin still cannot PUT policy."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "api_key",
    }
    with patch(
        "app.mcp_policy_routes.db.is_user_tenant_admin", return_value=True
    ), patch("app.mcp_policy_routes.db.replace_tenant_mcp_policy") as replace:
        r = client.put(_POLICY, json=_PUT_BODY)
    assert r.status_code == 403
    assert "API keys cannot mutate governance" in r.json()["detail"]
    replace.assert_not_called()


def test_api_key_get_ok_for_tenant_principal():
    """Reads allow any authenticated tenant principal (including API keys)."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "api_key",
    }
    with patch(
        "app.mcp_policy_routes.db.get_tenant_mcp_policy",
        return_value={
            "default_mode": "inherit_registry",
            "allow_anonymous_mcp": True,
            "updated_at": None,
            "updated_by": None,
            "tools": [],
        },
    ):
        r = client.get(_POLICY)
    assert r.status_code == 200
    assert r.json()["default_mode"] == "inherit_registry"


def test_non_member_get_403():
    """``validate_authentication`` denies users without tenant membership."""

    def _deny():
        raise HTTPException(
            status_code=403,
            detail="User does not have access to tenant: acme",
        )

    app.dependency_overrides[validate_authentication] = _deny
    r = client.get(_POLICY)
    assert r.status_code == 403


def test_unknown_tenant_get_404():
    def _missing():
        raise HTTPException(status_code=404, detail="Tenant not found: ghost")

    app.dependency_overrides[validate_authentication] = _missing
    r = client.get(_POLICY)
    assert r.status_code == 404


def test_mcp_key_mutation_rejects_api_key_auth():
    """MCP key lifecycle mutations share the same governance gate."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": _USER,
        "auth_method": "api_key",
    }
    with patch(
        "app.mcp_key_routes.db.is_user_tenant_admin", return_value=True
    ), patch("app.mcp_key_routes.db.create_mcp_api_key") as create:
        r = client.post(_KEYS, json={"label": "escalation attempt"})
    assert r.status_code == 403
    assert "API keys cannot mutate governance" in r.json()["detail"]
    create.assert_not_called()
