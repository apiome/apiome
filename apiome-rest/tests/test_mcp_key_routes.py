"""Endpoint tests for MCP API key REST management (MTG-3.2, #4776).

DB helpers are mocked on ``app.mcp_key_routes.db`` so these tests exercise the
route contract: admin-only access, secret once on create, never on list/get,
scope validation, patch, and revoke.
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
_KEY_ID = "11111111-1111-1111-1111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt"}
NOW = datetime(2026, 7, 13, 18, 0, 0, tzinfo=timezone.utc)
BASE = "/v1/tenants/acme/mcp-keys"


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _admin():
    """All mcp-keys operations require a tenant admin; default every test to admin."""
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


def test_list_returns_metadata_without_secret():
    with patch(
        "app.mcp_key_routes.db.list_mcp_api_keys", return_value=[_key_row()]
    ) as list_keys:
        r = client.get(BASE)
    assert r.status_code == 200
    body = r.json()
    assert "keys" in body
    assert len(body["keys"]) == 1
    key = body["keys"][0]
    assert key["id"] == _KEY_ID
    assert key["prefix"] == "abcdefghijkl..."
    assert key["label"] == "CI key"
    assert key["capability_mode"] == "inherit"
    assert key["enabled_tools"] == []
    assert key["scope_json"] == {"tenants": [_TENANT], "projects": []}
    assert "secret" not in key
    assert "key_hash" not in key
    list_keys.assert_called_once_with(_TENANT)


def test_list_forbidden_for_non_admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=False), patch(
        "app.mcp_key_routes.db.list_mcp_api_keys"
    ) as list_keys:
        r = client.get(BASE)
    assert r.status_code == 403
    assert "tenant administrators" in r.json()["detail"]
    list_keys.assert_not_called()


def test_create_returns_secret_once():
    row = _key_row()
    secret = "once-only-plaintext-secret-value-xx"
    with patch(
        "app.mcp_key_routes.db.create_mcp_api_key", return_value=(row, secret)
    ) as create:
        r = client.post(
            BASE,
            json={
                "label": "CI key",
                "scope_json": {"tenants": [_TENANT], "projects": []},
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["secret"] == secret
    assert body["id"] == _KEY_ID
    assert body["prefix"] == "abcdefghijkl..."
    assert "key_hash" not in body
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["label"] == "CI key"
    assert kwargs["created_by"] == _USER
    assert kwargs["scope_json"] == {"tenants": [_TENANT], "projects": []}


def test_create_forbidden_for_non_admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=False), patch(
        "app.mcp_key_routes.db.create_mcp_api_key"
    ) as create:
        r = client.post(BASE, json={"label": "nope"})
    assert r.status_code == 403
    create.assert_not_called()


def test_create_rejects_invalid_scope_item_type():
    r = client.post(
        BASE,
        json={
            "label": "bad",
            "scope_json": {"tenants": [123], "projects": []},
        },
    )
    assert r.status_code == 422


def test_get_omits_secret():
    with patch(
        "app.mcp_key_routes.db.get_mcp_api_key", return_value=_key_row()
    ) as get_key:
        r = client.get(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == _KEY_ID
    assert "secret" not in body
    assert "key_hash" not in body
    get_key.assert_called_once_with(_TENANT, _KEY_ID)


def test_get_404_when_missing():
    with patch("app.mcp_key_routes.db.get_mcp_api_key", return_value=None):
        r = client.get(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 404


def test_patch_updates_label_and_scope():
    updated = _key_row(label="Renamed", scope_json={"tenants": [], "projects": []})
    with patch(
        "app.mcp_key_routes.db.update_mcp_api_key", return_value=updated
    ) as update:
        r = client.patch(
            f"{BASE}/{_KEY_ID}",
            json={
                "label": "Renamed",
                "scope_json": {"tenants": [], "projects": []},
            },
        )
    assert r.status_code == 200
    assert r.json()["label"] == "Renamed"
    assert "secret" not in r.json()
    update.assert_called_once()
    kwargs = update.call_args.kwargs
    assert kwargs["update_label"] is True
    assert kwargs["label"] == "Renamed"
    assert kwargs["update_scope_json"] is True
    assert kwargs["update_expires_at"] is False


def test_patch_clear_expires_at():
    updated = _key_row(expires_at=None)
    with patch(
        "app.mcp_key_routes.db.update_mcp_api_key", return_value=updated
    ) as update:
        r = client.patch(f"{BASE}/{_KEY_ID}", json={"expires_at": None})
    assert r.status_code == 200
    kwargs = update.call_args.kwargs
    assert kwargs["update_expires_at"] is True
    assert kwargs["expires_at"] is None


def test_patch_empty_body_422():
    with patch("app.mcp_key_routes.db.update_mcp_api_key") as update:
        r = client.patch(f"{BASE}/{_KEY_ID}", json={})
    assert r.status_code == 422
    update.assert_not_called()


def test_patch_forbidden_for_non_admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=False), patch(
        "app.mcp_key_routes.db.update_mcp_api_key"
    ) as update:
        r = client.patch(f"{BASE}/{_KEY_ID}", json={"label": "x"})
    assert r.status_code == 403
    update.assert_not_called()


def test_revoke_returns_204():
    with patch(
        "app.mcp_key_routes.db.revoke_mcp_api_key",
        return_value=_key_row(revoked_at=NOW),
    ) as revoke:
        r = client.delete(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 204
    assert r.content == b""
    revoke.assert_called_once_with(_TENANT, _KEY_ID)


def test_revoke_idempotent_already_revoked():
    with patch(
        "app.mcp_key_routes.db.revoke_mcp_api_key",
        return_value=_key_row(revoked_at=NOW),
    ):
        r = client.delete(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 204


def test_revoke_404_when_unknown():
    with patch("app.mcp_key_routes.db.revoke_mcp_api_key", return_value=None):
        r = client.delete(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 404


def test_revoke_forbidden_for_non_admin():
    with patch("app.mcp_key_routes.db.is_user_tenant_admin", return_value=False), patch(
        "app.mcp_key_routes.db.revoke_mcp_api_key"
    ) as revoke:
        r = client.delete(f"{BASE}/{_KEY_ID}")
    assert r.status_code == 403
    revoke.assert_not_called()


def test_list_includes_revoked_for_audit():
    revoked = _key_row(revoked_at=NOW, label="old")
    with patch(
        "app.mcp_key_routes.db.list_mcp_api_keys", return_value=[revoked]
    ):
        r = client.get(BASE)
    assert r.status_code == 200
    assert r.json()["keys"][0]["revoked_at"] == "2026-07-13T18:00:00Z"
