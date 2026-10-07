"""Agent toolset endpoints — AGX-1.2 (#4530).

Authentication is overridden and the store is the in-memory
:class:`~agent_toolset_fakes.FakeToolsetStore`, so these tests assert the HTTP contract: which
``api_keys`` permission each route enforces, how every refusal maps to a status, that every change
writes exactly one metadata-only audit row, and the two acceptance rules end to end (a new toolset
exposes only reads; enabling a ``DELETE`` needs ``confirmWriteOp``).
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from agent_toolset_fakes import FakeToolsetStore
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_agent_toolsets import PETSTORE

import app.agent_toolsets as toolsets
from app.agent_toolset_routes import AUDIT_CREATE, AUDIT_DELETE, AUDIT_TOOL_UPDATE, AUDIT_UPDATE
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.openapi_normalizer import OpenApiNormalizer
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_MISSING = "77777777-7777-4777-8777-777777777777"

_BASE = "/v1/tenants/acme/agent-toolsets"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> FakeToolsetStore:
    """The toolset accessors, in memory, with every version reading as :data:`PETSTORE`."""
    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(PETSTORE)
    )
    return FakeToolsetStore().install(monkeypatch, db)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    """Capture access-audit rows instead of writing them."""
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(db, "write_access_audit", lambda **fields: rows.append(fields))
    return rows


def _create(store: FakeToolsetStore, **overrides: Any) -> Dict[str, Any]:
    """Create a toolset for a fresh published version through the API."""
    body = {"versionId": store.seed_version(_TENANT), **overrides}
    response = client.post(_BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _tool(toolset: Dict[str, Any], operation: str) -> Dict[str, Any]:
    return next(tool for tool in toolset["tools"] if tool["operation"] == operation)


# ============================================================================
# Permissions
# ============================================================================
@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("get", "", None, Action.VIEW),
        ("post", "", "create", Action.CREATE),
        ("get", "/{id}", None, Action.VIEW),
        ("patch", "/{id}", {"enabled": False}, Action.EDIT),
        ("delete", "/{id}", None, Action.DELETE),
        ("get", "/{id}/tools", None, Action.VIEW),
        ("patch", "/{id}/tools/{tool}", {"enabled": False}, Action.EDIT),
    ],
)
def test_each_route_enforces_its_api_keys_permission(store, audits, method, suffix, body, action):
    existing = _create(store)
    audits.clear()
    path = _BASE + suffix.replace("{id}", existing["id"]).replace(
        "{tool}", existing["tools"][0]["id"]
    )
    payload = {"versionId": store.seed_version(_TENANT)} if body == "create" else body
    with patch(
        "app.agent_toolset_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ) as guard:
        kwargs = {"json": payload} if payload is not None else {}
        response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    _db, _auth, resource, granted = guard.call_args.args
    assert (resource, granted) == (Resource.API_KEYS, action)
    assert audits == []


def test_a_principal_without_a_tenant_is_refused(store):
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": _ACTOR}
    with patch("app.agent_toolset_routes.enforce_permission", return_value=_ACTOR):
        assert client.get(_BASE).status_code == 403


# ============================================================================
# Create
# ============================================================================
def test_create_seeds_reads_only_and_is_audited(store, audits):
    """Acceptance: a new toolset exposes only read operations; creation is audited."""
    created = _create(store)
    assert created["schemaVersion"] == "agx.agent-toolset.v1"
    assert (created["enabled"], created["target"]) == (True, "prod")
    assert (created["toolCount"], created["enabledToolCount"], created["enabledWriteOpCount"]) == (
        8,
        3,
        0,
    )
    exposed = {tool["operation"] for tool in created["tools"] if tool["enabled"]}
    assert exposed == {"GET /pets", "HEAD /pets", "GET /pets/{id}"}
    mutating = ("POST", "PUT", "PATCH", "DELETE")
    assert all(tool["writeOp"] for tool in created["tools"] if tool["operation"].startswith(mutating))
    assert {"toolName", "writeOp", "writeConfirmedAt"} <= set(created["tools"][0])

    [row] = audits
    assert row["action"] == AUDIT_CREATE
    assert row["target"] == created["id"]
    assert row["actor_id"] == _ACTOR and row["actor_label"] == "a@x.io"
    assert row["detail"] == {
        "versionId": created["versionId"],
        "enabled": True,
        "target": "prod",
        "descriptionEnrichment": True,
        "toolCount": 8,
        "enabledToolCount": 3,
    }


@pytest.mark.parametrize(
    ("state", "status", "code"),
    [
        (None, 404, "agent-toolset-version-not-found"),
        ({"published": False}, 409, "agent-toolset-version-unpublished"),
        ({"deleted": True}, 409, "agent-toolset-version-unpublished"),
    ],
)
def test_create_refusals_for_the_version(store, audits, state, status, code):
    version_id = _MISSING if state is None else store.seed_version(_TENANT, **state)
    response = client.post(_BASE, json={"versionId": version_id})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert store.toolsets == {} and audits == []


def test_create_for_another_tenants_version_is_404(store, audits):
    response = client.post(_BASE, json={"versionId": store.seed_version(_OTHER_TENANT)})
    assert response.status_code == 404
    assert store.toolsets == {}


def test_a_second_toolset_for_a_version_is_409(store, audits):
    created = _create(store)
    response = client.post(_BASE, json={"versionId": created["versionId"]})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "agent-toolset-exists"
    assert len(audits) == 1


def test_an_unreadable_version_is_422(store, audits, monkeypatch):
    def _boom(*_args: Any):
        raise toolsets.ExportSourceError("no captured source", status_code=422)

    monkeypatch.setattr(toolsets, "_load_version_api", _boom)
    response = client.post(_BASE, json={"versionId": store.seed_version(_TENANT)})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent-toolset-source-unavailable"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"versionId": "not-a-uuid"},
        {"versionId": _MISSING, "target": "staging"},
        {"versionId": _MISSING, "surprise": True},
    ],
)
def test_malformed_create_bodies_never_reach_the_store(store, body):
    assert client.post(_BASE, json=body).status_code == 422
    assert store.calls == []


def test_an_audit_failure_does_not_fail_the_create(store, monkeypatch):
    def _boom(**_fields: Any) -> None:
        raise RuntimeError("audit down")

    monkeypatch.setattr(db, "write_access_audit", _boom)
    _create(store)
    assert len(store.toolsets) == 1


# ============================================================================
# Read
# ============================================================================
def test_list_get_and_tools_are_scoped_to_the_tenant(store, audits):
    created = _create(store)
    listed = client.get(_BASE).json()
    assert [toolset["id"] for toolset in listed["toolsets"]] == [created["id"]]
    assert "tools" not in listed["toolsets"][0]

    filtered = client.get(_BASE, params={"versionId": _MISSING}).json()
    assert filtered["toolsets"] == []

    detail = client.get(f"{_BASE}/{created['id']}").json()
    assert detail == created

    tools = client.get(f"{_BASE}/{created['id']}/tools").json()
    assert tools["toolsetId"] == created["id"]
    assert tools["tools"] == created["tools"]

    app.dependency_overrides[validate_authentication] = lambda: {**_MOCK_AUTH, "tenant_id": _OTHER_TENANT}
    assert client.get(_BASE).json()["toolsets"] == []
    assert client.get(f"{_BASE}/{created['id']}").status_code == 404
    assert client.get(f"{_BASE}/{created['id']}/tools").status_code == 404


def test_unknown_toolsets_are_404(store):
    for path in (f"{_BASE}/{_MISSING}", f"{_BASE}/{_MISSING}/tools"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "agent-toolset-not-found"


# ============================================================================
# Update / delete the toolset
# ============================================================================
def test_patch_changes_settings_and_audits_before_and_after(store, audits):
    created = _create(store)
    audits.clear()
    response = client.patch(f"{_BASE}/{created['id']}", json={"target": "mock", "enabled": False})
    assert response.status_code == 200
    assert (response.json()["target"], response.json()["enabled"]) == ("mock", False)
    [row] = audits
    assert row["action"] == AUDIT_UPDATE
    assert row["detail"]["before"] == {
        "enabled": True,
        "target": "prod",
        "descriptionEnrichment": True,
    }
    assert row["detail"]["after"] == {
        "enabled": False,
        "target": "mock",
        "descriptionEnrichment": True,
    }


def test_patch_refusals(store, audits):
    created = _create(store)
    audits.clear()
    assert client.patch(f"{_BASE}/{created['id']}", json={}).status_code == 422
    assert client.patch(f"{_BASE}/{created['id']}", json={"target": "qa"}).status_code == 422
    assert client.patch(f"{_BASE}/{_MISSING}", json={"enabled": False}).status_code == 404
    assert audits == []


def test_delete_is_204_and_audited(store, audits):
    created = _create(store)
    audits.clear()
    assert client.delete(f"{_BASE}/{created['id']}").status_code == 204
    [row] = audits
    assert row["action"] == AUDIT_DELETE
    assert row["target"] == created["id"]
    assert row["detail"]["versionId"] == created["versionId"]
    assert client.delete(f"{_BASE}/{created['id']}").status_code == 404
    assert len(audits) == 1


# ============================================================================
# Tools — the write-op confirmation
# ============================================================================
def test_enabling_a_delete_without_confirmation_is_rejected(store, audits):
    """Acceptance: a DELETE needs confirmWriteOp; without it nothing changes or is audited."""
    created = _create(store)
    delete = _tool(created, "DELETE /pets/{id}")
    audits.clear()
    for body in ({"enabled": True}, {"enabled": True, "confirmWriteOp": False}):
        response = client.patch(f"{_BASE}/{created['id']}/tools/{delete['id']}", json=body)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "agent-toolset-write-op-unconfirmed"
    assert store.tools[delete["id"]]["enabled"] is False
    assert audits == []


def test_enabling_a_delete_with_confirmation_is_audited(store, audits):
    """Acceptance: who enabled which write op, and when, is on the tool and in the audit."""
    created = _create(store)
    delete = _tool(created, "DELETE /pets/{id}")
    audits.clear()
    response = client.patch(
        f"{_BASE}/{created['id']}/tools/{delete['id']}",
        json={"enabled": True, "confirmWriteOp": True},
    )
    assert response.status_code == 200
    tool = response.json()
    assert tool["enabled"] is True and tool["writeOp"] is True
    assert tool["writeConfirmedBy"] == _ACTOR and tool["writeConfirmedAt"]

    [row] = audits
    assert row["action"] == AUDIT_TOOL_UPDATE
    assert row["target"] == delete["id"]
    assert row["actor_id"] == _ACTOR
    assert row["detail"]["toolsetId"] == created["id"]
    assert row["detail"]["operation"] == "DELETE /pets/{id}"
    assert row["detail"]["writeOp"] is True
    assert (row["detail"]["enabledBefore"], row["detail"]["enabledAfter"]) == (False, True)
    assert row["detail"]["writeConfirmedAt"]

    summary = client.get(f"{_BASE}/{created['id']}").json()
    assert summary["enabledWriteOpCount"] == 1


def test_disabling_any_tool_needs_no_confirmation_and_is_audited(store, audits):
    created = _create(store)
    read = _tool(created, "GET /pets")
    audits.clear()
    response = client.patch(f"{_BASE}/{created['id']}/tools/{read['id']}", json={"enabled": False})
    assert response.status_code == 200 and response.json()["enabled"] is False
    [row] = audits
    assert (row["detail"]["enabledBefore"], row["detail"]["enabledAfter"]) == (True, False)


def test_tool_update_refusals(store, audits):
    created = _create(store)
    other = _create(store)
    tool = created["tools"][0]
    audits.clear()
    # Unknown tool, a tool of another toolset, and an unknown toolset.
    for path in (
        f"{_BASE}/{created['id']}/tools/{_MISSING}",
        f"{_BASE}/{other['id']}/tools/{tool['id']}",
        f"{_BASE}/{_MISSING}/tools/{tool['id']}",
    ):
        response = client.patch(path, json={"enabled": False})
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "agent-toolset-tool-not-found"
    # The body must say what to do.
    assert client.patch(f"{_BASE}/{created['id']}/tools/{tool['id']}", json={}).status_code == 422
    assert audits == []


def test_the_openapi_contract_documents_the_routes():
    paths = app.openapi()["paths"]
    assert set(paths["/v1/tenants/{tenant_slug}/agent-toolsets"]) == {"get", "post"}
    assert set(paths["/v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}"]) == {
        "get",
        "patch",
        "delete",
    }
    assert set(paths["/v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/tools"]) == {"get"}
    tool_route = paths["/v1/tenants/{tenant_slug}/agent-toolsets/{toolset_id}/tools/{tool_id}"]
    assert "confirmWriteOp" in tool_route["patch"]["description"]
