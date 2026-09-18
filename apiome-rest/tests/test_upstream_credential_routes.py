"""Upstream credential endpoints — AGX-2.2 (#4534).

Authentication is overridden, the vault's store is the in-memory
:class:`~upstream_credential_fakes.FakeUpstreamStore`, and encryption uses a throwaway key, so these
tests assert the HTTP contract: which ``api_keys`` permission each route enforces, how every
refusal maps to a status, that each mutation writes a metadata-only audit row, and that no
response — success or refusal, including FastAPI's own ``422`` — carries the secret sent.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from upstream_credential_fakes import FakeUpstreamStore

from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.main import app
from app.permissions import Action, Resource
from app.redacted_validation_route import MASKED_KEY
from app.upstream_credential_routes import AUDIT_CREATE, AUDIT_DELETE, AUDIT_ROTATE

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_TOOLSET = "22222222-2222-4222-8222-222222222222"
_MISSING = "77777777-7777-4777-8777-777777777777"
_SECRET = "sk_live_TOPSECRET_value_123"
_ROTATED = "sk_live_ROTATED_value_456"

_BASE = f"/v1/tenants/acme/agent-toolsets/{_TOOLSET}/upstream-credentials"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    """Configure one upstream-vault master key."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "upstream_credential_active_key_version", None)


@pytest.fixture
def store(monkeypatch) -> FakeUpstreamStore:
    """The vault's store, in memory."""
    return FakeUpstreamStore().install(monkeypatch, db)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    """Capture access-audit rows instead of writing them."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(db, "write_access_audit", lambda **fields: rows.append(fields))
    return rows


def _body(**overrides: Any) -> Dict[str, Any]:
    """An apiKey-in-header create body."""
    data: Dict[str, Any] = {
        "serverUrl": "https://api.example.com/v1",
        "kind": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "secret": {"value": _SECRET},
    }
    data.update(overrides)
    return data


def _create(**overrides: Any) -> Dict[str, Any]:
    """Create a credential through the API and return the response body."""
    response = client.post(_BASE, json=_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


# ============================================================================
# Permissions
# ============================================================================
@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("get", "", None, Action.VIEW),
        ("post", "", "create", Action.CREATE),
        ("post", "/{id}/rotate", {"secret": {"value": _ROTATED}}, Action.EDIT),
        ("delete", "/{id}", None, Action.DELETE),
    ],
)
def test_each_route_enforces_its_api_keys_permission(store, audits, method, suffix, body, action):
    existing = _create(serverUrl="https://seed.example.com")
    path = _BASE + suffix.replace("{id}", existing["id"])
    payload = _body() if body == "create" else body
    with patch(
        "app.upstream_credential_routes.enforce_permission", return_value=_ACTOR
    ) as guard:
        response = client.request(method.upper(), path, json=payload)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:] == (Resource.API_KEYS, action)


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("post", "", "create"),
        ("post", f"/{_MISSING}/rotate", {"secret": {"value": _ROTATED}}),
        ("delete", f"/{_MISSING}", None),
    ],
)
def test_a_denied_caller_changes_nothing(store, audits, method, suffix, body):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.upstream_credential_routes.enforce_permission", side_effect=denied):
        response = client.request(
            method.upper(), _BASE + suffix, json=_body() if body == "create" else body
        )
    assert response.status_code == 403
    assert store.rows == {}
    assert audits == []


def test_a_principal_without_a_tenant_is_refused(store):
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": _ACTOR}
    with patch("app.upstream_credential_routes.enforce_permission", return_value=_ACTOR):
        response = client.get(_BASE)
    assert response.status_code == 403


# ============================================================================
# Create
# ============================================================================
def test_create_returns_201_with_metadata_only(store, audits):
    response = client.post(_BASE, json=_body(serverUrl="https://API.example.com:443/v1/"))
    assert response.status_code == 201
    body = response.json()
    assert _SECRET not in response.text
    assert body["schemaVersion"] == "agx.upstream-credential.v1"
    assert body["toolsetId"] == _TOOLSET
    assert body["serverUrl"] == "https://api.example.com/v1"
    assert (body["kind"], body["in"], body["name"]) == ("apiKey", "header", "X-Api-Key")
    assert body["readable"] is True
    assert body["keyVersion"] == 1
    assert body["createdBy"] == _ACTOR
    assert body["rotatedAt"] is None and body["lastUsedAt"] is None
    assert "secret" not in body and "encryptedSecret" not in body


def test_create_is_audited_with_metadata_only(store, audits):
    created = _create()
    (row,) = audits
    assert row["action"] == AUDIT_CREATE
    assert row["tenant_id"] == _TENANT
    assert row["actor_id"] == _ACTOR
    assert row["target"] == created["id"]
    assert row["source"] == "api"
    assert row["detail"] == {
        "toolsetId": _TOOLSET,
        "serverUrl": "https://api.example.com/v1",
        "kind": "apiKey",
        "in": "header",
        "name": "X-Api-Key",
        "keyVersion": 1,
    }
    assert _SECRET not in json.dumps(row, default=str)


def test_a_failing_audit_does_not_fail_the_create(store, monkeypatch):
    def boom(**_fields):
        raise RuntimeError("audit down")

    monkeypatch.setattr(db, "write_access_audit", boom)
    assert client.post(_BASE, json=_body()).status_code == 201


def test_a_second_credential_for_the_same_server_is_a_409(store, audits):
    _create()
    response = client.post(_BASE, json=_body(secret={"value": _ROTATED}))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "upstream-credential-exists"
    assert _ROTATED not in response.text
    assert len(audits) == 1


def test_an_invalid_create_is_a_422_listing_every_problem(store, audits):
    response = client.post(
        _BASE,
        json=_body(serverUrl="http://api.example.com", name="Host", secret={"token": _SECRET}),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "upstream-credential-invalid"
    assert len(detail["errors"]) == 4
    assert _SECRET not in response.text
    assert store.rows == {} and audits == []


def test_create_without_a_master_key_is_a_503_naming_the_variable(store, audits, monkeypatch):
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    response = client.post(_BASE, json=_body())
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "upstream-credential-encryption-unconfigured"
    assert "APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS" in detail["message"]
    assert _SECRET not in response.text
    assert store.rows == {} and audits == []


# ============================================================================
# List
# ============================================================================
def test_list_describes_the_toolset_without_secrets(store, audits):
    _create()
    _create(
        serverUrl="https://auth.example.com",
        kind="basic",
        secret={"username": "svc-user", "password": _ROTATED},
        **{"in": None, "name": None},
    )
    response = client.get(_BASE)
    assert response.status_code == 200
    body = response.json()
    assert body["toolsetId"] == _TOOLSET
    assert body["encryptionConfigured"] is True
    assert body["kinds"] == ["apiKey", "bearer", "basic"]
    assert body["apiKeyLocations"] == ["header", "query"]
    assert [item["serverUrl"] for item in body["credentials"]] == [
        "https://api.example.com/v1",
        "https://auth.example.com",
    ]
    for needle in (_SECRET, _ROTATED, "svc-user"):
        assert needle not in response.text


def test_list_of_an_empty_toolset(store):
    body = client.get(_BASE).json()
    assert body["credentials"] == []


def test_a_malformed_toolset_id_is_a_422(store):
    response = client.get("/v1/tenants/acme/agent-toolsets/not-a-uuid/upstream-credentials")
    assert response.status_code == 422


# ============================================================================
# Rotate
# ============================================================================
def test_rotate_replaces_the_secret_and_is_audited(store, audits):
    created = _create()
    response = client.post(
        f"{_BASE}/{created['id']}/rotate", json={"secret": {"value": _ROTATED}}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["rotatedAt"] is not None
    assert body["rotatedBy"] == _ACTOR
    assert _ROTATED not in response.text and _SECRET not in response.text
    assert [row["action"] for row in audits] == [AUDIT_CREATE, AUDIT_ROTATE]
    assert _ROTATED not in json.dumps(audits, default=str)


def test_rotating_an_unknown_credential_is_a_404(store, audits):
    response = client.post(f"{_BASE}/{_MISSING}/rotate", json={"secret": {"value": _ROTATED}})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "upstream-credential-not-found"
    assert audits == []


def test_rotating_with_the_wrong_secret_shape_is_a_422(store, audits):
    created = _create()
    response = client.post(
        f"{_BASE}/{created['id']}/rotate", json={"secret": {"token": _ROTATED}}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "upstream-credential-invalid"
    assert _ROTATED not in response.text


def test_rotate_without_a_master_key_is_a_503(store, audits, monkeypatch):
    created = _create()
    monkeypatch.setattr(settings, "upstream_credential_encryption_keys", None)
    response = client.post(
        f"{_BASE}/{created['id']}/rotate", json={"secret": {"value": _ROTATED}}
    )
    assert response.status_code == 503


# ============================================================================
# Delete
# ============================================================================
def test_delete_is_a_204_and_is_audited(store, audits):
    created = _create()
    response = client.delete(f"{_BASE}/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert store.rows == {}
    assert [row["action"] for row in audits] == [AUDIT_CREATE, AUDIT_DELETE]
    assert audits[-1]["target"] == created["id"]


def test_deleting_twice_is_a_404(store, audits):
    created = _create()
    client.delete(f"{_BASE}/{created['id']}")
    response = client.delete(f"{_BASE}/{created['id']}")
    assert response.status_code == 404
    assert len(audits) == 2


# ============================================================================
# Validation errors never echo what was sent
# ============================================================================
_LEAKY_BODIES = [
    # A missing field: pydantic's error ``input`` is the whole enclosing object.
    pytest.param({"serverUrl": "https://a.example", "secret": {"value": _SECRET}}, id="missing-kind"),
    # An unknown kind next to a secret.
    pytest.param(_body(kind="oauth2"), id="bad-kind"),
    # The secret sent where an object belongs.
    pytest.param(_body(secret=_SECRET), id="secret-as-string"),
    # The secret sent as an unexpected key, and as an unexpected value.
    pytest.param(_body(secret={"value": "x", _SECRET: "y"}), id="secret-as-extra-key"),
    pytest.param(_body(secret={"value": "x", "apiKey": _SECRET}), id="secret-as-extra-value"),
    pytest.param({**_body(), "plaintext": _SECRET}, id="extra-top-level"),
    # Wrong types around a secret.
    pytest.param(_body(secret={"value": [_SECRET]}), id="secret-in-list"),
    pytest.param(_body(serverUrl=[_SECRET]), id="secret-in-server-url"),
]


@pytest.mark.parametrize("payload", _LEAKY_BODIES)
def test_a_malformed_create_body_does_not_echo_the_secret(store, payload):
    response = client.post(_BASE, json=payload)
    assert response.status_code == 422
    assert _SECRET not in response.text
    for error in response.json()["detail"]:
        assert set(error) <= {"type", "loc", "msg"}
    assert store.rows == {}


def test_an_unexpected_key_is_masked_in_the_error_location(store):
    response = client.post(_BASE, json=_body(secret={"value": "x", _SECRET: "y"}))
    (error,) = response.json()["detail"]
    assert error["type"] == "extra_forbidden"
    assert error["loc"] == ["body", "secret", MASKED_KEY]


def test_a_redacted_error_still_says_what_to_fix(store):
    response = client.post(_BASE, json={"serverUrl": "https://a.example", "secret": {"value": _SECRET}})
    (error,) = response.json()["detail"]
    assert error == {"type": "missing", "loc": ["body", "kind"], "msg": "Field required"}
    assert response.json()["error"]["type"] == "validation_error"


def test_invalid_json_carrying_a_secret_is_not_echoed(store):
    raw = '{"serverUrl": "https://a.example", "kind": "bearer", "secret": {"token": "' + _SECRET + '"'
    response = client.post(_BASE, content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert _SECRET not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"secret": _SECRET},
        {"secret": {"value": _SECRET}, "extra": _SECRET},
        {"secret": {"value": _SECRET, _SECRET: 1}},
        {"value": _SECRET},
    ],
)
def test_a_malformed_rotate_body_does_not_echo_the_secret(store, payload):
    created = _create(secret={"value": "sk_live_original_000"})
    response = client.post(f"{_BASE}/{created['id']}/rotate", json=payload)
    assert response.status_code == 422
    assert _SECRET not in response.text
