"""Agent key endpoints — AGX-3.1 (#4537).

Authentication is overridden and the store is the in-memory
:class:`~agent_key_fakes.FakeAgentKeyStore`, so these tests assert the HTTP contract: which
``api_keys`` permission each route enforces, how every refusal maps to a status, that each
lifecycle action writes exactly one metadata-only audit row, and that the secret appears in the
create response and nowhere else.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from agent_key_fakes import FakeAgentKeyStore
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent_key_routes import AUDIT_ALLOWLIST_UPDATE, AUDIT_CREATE, AUDIT_REVOKE
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_TOOLSET = "22222222-2222-4222-8222-222222222222"
_MISSING = "77777777-7777-4777-8777-777777777777"

_BASE = "/v1/tenants/acme/agent-keys"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> FakeAgentKeyStore:
    """The agent-key accessors, in memory."""
    return FakeAgentKeyStore().install(monkeypatch, db)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    """Capture access-audit rows instead of writing them."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(db, "write_access_audit", lambda **fields: rows.append(fields))
    return rows


def _body(**overrides: Any) -> Dict[str, Any]:
    """A valid create body."""
    data: Dict[str, Any] = {
        "name": "claude-desktop",
        "toolsetId": _TOOLSET,
        "toolAllowlist": ["listPets", "getPetById"],
    }
    data.update(overrides)
    return data


def _create(**overrides: Any) -> Dict[str, Any]:
    """Create a key through the API and return the response body."""
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
        ("get", "/{id}", None, Action.VIEW),
        ("put", "/{id}/allowlist", {"toolAllowlist": ["listPets"]}, Action.EDIT),
        ("delete", "/{id}", None, Action.DELETE),
    ],
)
def test_each_route_enforces_its_api_keys_permission(store, audits, method, suffix, body, action):
    existing = _create(name="seed")
    path = _BASE + suffix.replace("{id}", existing["id"])
    payload = _body() if body == "create" else body
    with patch("app.agent_key_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method.upper(), path, json=payload)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:] == (Resource.API_KEYS, action)


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("get", "", None),
        ("post", "", "create"),
        ("get", f"/{_MISSING}", None),
        ("put", f"/{_MISSING}/allowlist", {"toolAllowlist": ["x"]}),
        ("delete", f"/{_MISSING}", None),
    ],
)
def test_a_denied_caller_changes_nothing(store, audits, method, suffix, body):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.agent_key_routes.enforce_permission", side_effect=denied):
        response = client.request(
            method.upper(), _BASE + suffix, json=_body() if body == "create" else body
        )
    assert response.status_code == 403
    assert store.rows == {}
    assert store.calls == []
    assert audits == []


def test_a_principal_without_a_tenant_is_refused(store):
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": _ACTOR}
    with patch("app.agent_key_routes.enforce_permission", return_value=_ACTOR):
        response = client.get(_BASE)
    assert response.status_code == 403
    assert store.calls == []


# ============================================================================
# Create
# ============================================================================
def test_create_returns_201_with_the_secret_and_audits_metadata_only(store, audits):
    created = _create(description="Petstore agent", expiresAt="2099-01-01T00:00:00Z")
    secret = created["secret"]
    assert secret.startswith("ak_")
    assert created["schemaVersion"] == "agx.agent-key.v1"
    assert created["kind"] == "agent"
    assert created["status"] == "active"
    assert created["toolsetId"] == _TOOLSET
    assert created["toolAllowlist"] == ["getPetById", "listPets"]
    assert created["keyPrefix"] == secret[:12] + "..."
    assert created["expiresAt"].startswith("2099-01-01T00:00:00")
    assert "key_hash" not in created and "keyHash" not in created

    assert len(audits) == 1
    row = audits[0]
    assert row["action"] == AUDIT_CREATE == "agent.key.create"
    assert row["tenant_id"] == _TENANT
    assert row["actor_id"] == _ACTOR
    assert row["actor_label"] == "a@x.io"
    assert row["target"] == created["id"]
    assert row["source"] == "api"
    assert row["detail"] == {
        "name": "claude-desktop",
        "keyPrefix": created["keyPrefix"],
        "toolsetId": _TOOLSET,
        "toolAllowlist": ["getPetById", "listPets"],
        "expiresAt": "2099-01-01T00:00:00+00:00",
    }
    stored_hash = store.rows[created["id"]]["key_hash"]
    assert secret not in json.dumps(row, default=str)
    assert stored_hash not in json.dumps(row, default=str)


def test_the_secret_is_never_returned_again(store, audits):
    created = _create()
    secret = created["secret"]
    stored_hash = store.rows[created["id"]]["key_hash"]
    responses = [
        client.get(_BASE),
        client.get(_BASE, params={"includeRevoked": "true"}),
        client.get(f"{_BASE}/{created['id']}"),
        client.put(f"{_BASE}/{created['id']}/allowlist", json={"toolAllowlist": ["listPets"]}),
    ]
    for response in responses:
        assert response.status_code == 200, response.text
        assert secret not in response.text
        assert stored_hash not in response.text
        assert '"secret"' not in response.text


def test_create_with_an_invalid_body_lists_every_problem(store, audits):
    response = client.post(
        _BASE,
        json=_body(
            name="  ",
            toolAllowlist=["ok", "not ok", "*"],
            expiresAt=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        ),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "agent-key-invalid"
    assert [e.split(":")[0] for e in detail["errors"]] == [
        "name",
        "toolAllowlist[1]",
        "toolAllowlist[2]",
        "expiresAt",
    ]
    assert store.rows == {}
    assert audits == []


@pytest.mark.parametrize(
    "override",
    [
        {"toolsetId": "not-a-uuid"},
        {"toolAllowlist": "listPets"},
        {"toolAllowlist": [f"t{i}" for i in range(1025)]},
        {"name": ""},
        {"name": "x" * 256},
        {"scopes": ["*"]},
        {"kind": "workspace"},
    ],
)
def test_create_rejects_malformed_bodies_before_the_store(store, audits, override):
    response = client.post(_BASE, json=_body(**override))
    assert response.status_code == 422
    assert store.calls == []


def test_create_requires_a_toolset_and_an_allowlist(store):
    for missing in ("toolsetId", "toolAllowlist"):
        body = _body()
        del body[missing]
        assert client.post(_BASE, json=body).status_code == 422
    assert store.rows == {}


def test_create_on_a_taken_name_is_409(store, audits):
    _create()
    response = client.post(_BASE, json=_body())
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent-key-exists"
    assert len(audits) == 1  # only the first create


def test_an_audit_failure_does_not_fail_the_create(store, monkeypatch):
    def _boom(**_fields: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(db, "write_access_audit", _boom)
    response = client.post(_BASE, json=_body())
    assert response.status_code == 201
    assert len(store.rows) == 1


# ============================================================================
# List / get
# ============================================================================
def test_list_is_scoped_to_the_authenticated_tenant(store, audits):
    store.seed_workspace_key(_TENANT, "workspace-key")
    mine = _create(name="mine")
    app.dependency_overrides[validate_authentication] = lambda: {
        **_MOCK_AUTH,
        "tenant_id": _OTHER_TENANT,
    }
    _create(name="theirs")
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH

    body = client.get(_BASE).json()
    assert body["schemaVersion"] == "agx.agent-key.v1"
    assert [key["name"] for key in body["keys"]] == ["mine"]
    assert client.get(f"{_BASE}/{mine['id']}").status_code == 200


def test_list_filters_by_toolset_and_hides_revoked_by_default(store, audits):
    one = _create(name="one")
    _create(name="two", toolsetId=_MISSING)
    assert [k["name"] for k in client.get(_BASE, params={"toolsetId": _TOOLSET}).json()["keys"]] == [
        "one"
    ]
    client.delete(f"{_BASE}/{one['id']}")
    assert [k["name"] for k in client.get(_BASE).json()["keys"]] == ["two"]
    listed = client.get(_BASE, params={"includeRevoked": "true"}).json()["keys"]
    assert {k["name"]: k["status"] for k in listed} == {"one": "revoked", "two": "active"}


def test_list_rejects_a_malformed_toolset_filter(store):
    assert client.get(_BASE, params={"toolsetId": "nope"}).status_code == 422


def test_get_of_an_unknown_or_foreign_key_is_404(store, audits):
    app.dependency_overrides[validate_authentication] = lambda: {
        **_MOCK_AUTH,
        "tenant_id": _OTHER_TENANT,
    }
    theirs = _create(name="theirs")
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    for key_id in (_MISSING, theirs["id"]):
        response = client.get(f"{_BASE}/{key_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "agent-key-not-found"


def test_get_describes_expired_keys(store, audits):
    created = _create()
    store.rows[created["id"]]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get(f"{_BASE}/{created['id']}").json()["status"] == "expired"


# ============================================================================
# Allowlist edit
# ============================================================================
def test_allowlist_edit_replaces_the_list_and_audits_before_and_after(store, audits):
    created = _create()
    response = client.put(
        f"{_BASE}/{created['id']}/allowlist",
        json={"toolAllowlist": ["deletePet", "listPets", "deletePet"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["toolAllowlist"] == ["deletePet", "listPets"]

    row = audits[-1]
    assert row["action"] == AUDIT_ALLOWLIST_UPDATE == "agent.key.allowlist_update"
    assert row["target"] == created["id"]
    assert row["detail"]["before"] == ["getPetById", "listPets"]
    assert row["detail"]["after"] == ["deletePet", "listPets"]
    assert created["secret"] not in json.dumps(row, default=str)


def test_allowlist_edit_refusals(store, audits):
    created = _create()
    bad = client.put(f"{_BASE}/{created['id']}/allowlist", json={"toolAllowlist": ["a.b"]})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "agent-key-invalid"

    missing = client.put(f"{_BASE}/{_MISSING}/allowlist", json={"toolAllowlist": []})
    assert missing.status_code == 404

    client.delete(f"{_BASE}/{created['id']}")
    revoked = client.put(f"{_BASE}/{created['id']}/allowlist", json={"toolAllowlist": []})
    assert revoked.status_code == 409
    assert revoked.json()["detail"]["code"] == "agent-key-revoked"

    actions = [row["action"] for row in audits]
    assert actions == [AUDIT_CREATE, AUDIT_REVOKE]


def test_allowlist_edit_requires_the_whole_list(store):
    created = _create()
    assert client.put(f"{_BASE}/{created['id']}/allowlist", json={}).status_code == 422


# ============================================================================
# Revoke
# ============================================================================
def test_revoke_is_204_idempotent_and_audited_once(store, audits):
    created = _create()
    first = client.delete(f"{_BASE}/{created['id']}")
    second = client.delete(f"{_BASE}/{created['id']}")
    assert first.status_code == second.status_code == 204
    assert first.content == b""

    revokes = [row for row in audits if row["action"] == AUDIT_REVOKE]
    assert len(revokes) == 1
    assert revokes[0]["target"] == created["id"]
    assert revokes[0]["detail"] == {
        "name": "claude-desktop",
        "keyPrefix": created["keyPrefix"],
        "toolsetId": _TOOLSET,
    }
    stored = store.rows[created["id"]]
    assert stored["revoked_at"] is not None and stored["enabled"] is False


def test_revoke_of_an_unknown_key_is_404(store, audits):
    response = client.delete(f"{_BASE}/{_MISSING}")
    assert response.status_code == 404
    assert audits == []


def test_revoke_never_touches_a_workspace_key(store, audits):
    key_id = store.seed_workspace_key(_TENANT, "workspace-key")
    assert client.delete(f"{_BASE}/{key_id}").status_code == 404
    assert store.rows[key_id]["revoked_at"] is None


# ============================================================================
# Contract
# ============================================================================
def test_openapi_documents_the_five_routes_under_agent_access():
    paths = app.openapi()["paths"]
    collection = paths["/v1/tenants/{tenant_slug}/agent-keys"]
    item = paths["/v1/tenants/{tenant_slug}/agent-keys/{key_id}"]
    allowlist = paths["/v1/tenants/{tenant_slug}/agent-keys/{key_id}/allowlist"]
    assert set(collection) >= {"get", "post"}
    assert set(item) >= {"get", "delete"}
    assert set(allowlist) >= {"put"}
    for operation in (collection["get"], collection["post"], item["get"], item["delete"], allowlist["put"]):
        assert operation["tags"] == ["agent-access"]


def test_only_the_create_response_schema_has_a_secret():
    schemas = app.openapi()["components"]["schemas"]
    assert "secret" in schemas["AgentKeyCreated"]["properties"]
    assert "secret" not in schemas["AgentKeyOut"]["properties"]
    for name, schema in schemas.items():
        properties = schema.get("properties", {})
        assert "keyHash" not in properties and "key_hash" not in properties, name
