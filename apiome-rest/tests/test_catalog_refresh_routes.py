"""Catalog item refresh endpoints (MFI-31.1, #4398).

Authentication is overridden, storage is :class:`FakeRefreshStore`, the catalog item lookup is
stubbed, and the credential envelope uses a throwaway key. The tests pin the HTTP contract: the
permission each route needs, 404 before 403, the refusal codes, the keep / clear / replace
credential semantics, that no response or audit row carries a credential, and the kill switch.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from catalog_refresh_fakes import FakeRefreshStore
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import catalog_refresh
from app.auth import validate_authentication
from app.catalog_refresh import DiscoveryResult, register_discovery_runner
from app.catalog_refresh_routes import AUDIT_CHECKED, AUDIT_DELETED, AUDIT_POLICY, AUDIT_SAVED
from app.config import settings
from app.database import db
from app.main import app
from app.mcp_credential_crypto import unseal_credential_payload
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "44444444-4444-4444-8444-444444444444"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_ITEM = "22222222-2222-4222-8222-222222222222"
_MISSING = "77777777-7777-4777-8777-777777777777"
_SECRET = "gql_TOPSECRET_token_123"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_URL = f"/v1/catalog/acme/{_ITEM}/refresh"
_BODY = {"cadence": "daily", "adapter": "graphql", "endpoint": "https://api.example.com/graphql"}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    monkeypatch.setattr(settings, "catalog_refresh_enabled", True)
    monkeypatch.setattr(
        db,
        "get_catalog_item_by_id",
        lambda item_id, tenant_id, **kw: {"id": item_id} if item_id == _ITEM and tenant_id == _TENANT else None,
    )
    runners = dict(catalog_refresh._RUNNERS)
    yield
    catalog_refresh._RUNNERS.clear()
    catalog_refresh._RUNNERS.update(runners)
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> FakeRefreshStore:
    return FakeRefreshStore().install(monkeypatch)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _capture(tenant_id, project_id, version_id, action, outcome, actor_id, detail=None):
        rows.append({"tenant_id": tenant_id, "action": action, "detail": detail})

    monkeypatch.setattr(db, "insert_workflow_audit", _capture)
    return rows


def _put(body: Dict[str, Any] | None = None) -> Any:
    return client.put(_URL, json=body or _BODY)


# --- permissions and scoping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "url", "body", "resource", "action"),
    [
        ("GET", _URL, None, Resource.PROJECTS, Action.VIEW),
        ("PUT", _URL, _BODY, Resource.PROJECTS, Action.EDIT),
        ("DELETE", _URL, None, Resource.PROJECTS, Action.EDIT),
        ("POST", _URL + "/check", None, Resource.PROJECTS, Action.EDIT),
        ("GET", "/v1/catalog/acme/refresh-policy", None, Resource.PROJECTS, Action.VIEW),
        ("PUT", "/v1/catalog/acme/refresh-policy", {"enabled": False}, Resource.IMPORTS, Action.EDIT),
    ],
)
def test_each_route_enforces_its_permission(store, audits, method, url, body, resource, action):
    store.add(_ITEM, _TENANT)
    register_discovery_runner("graphql", lambda *a: DiscoveryResult("fp", None, None))
    with patch("app.catalog_refresh_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method, url, json=body)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:4] == (resource, action)


def test_an_unknown_item_is_404_before_the_permission_check(store):
    with patch("app.catalog_refresh_routes.enforce_permission") as guard:
        response = client.get(f"/v1/catalog/acme/{_MISSING}/refresh")
    assert response.status_code == 404
    guard.assert_not_called()


def test_a_denied_caller_changes_nothing(store, audits):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.catalog_refresh_routes.enforce_permission", side_effect=denied):
        response = _put()
    assert response.status_code == 403
    assert store.rows == {} and audits == []


def test_another_tenants_row_is_invisible(store):
    store.add(_ITEM, _OTHER_TENANT)
    body = client.get(_URL).json()
    assert body["configured"] is False


# --- read / write ----------------------------------------------------------------------


def test_an_item_without_a_setting_reads_as_off(store):
    body = client.get(_URL).json()
    assert body["configured"] is False and body["cadence"] == "off" and body["status"] == "never"
    assert body["adapters"] == ["graphql", "grpc"]
    assert body["cadences"] == ["off", "manual", "hourly", "daily", "weekly"]
    assert body["tenantEnabled"] is True


def test_put_stores_the_setting_and_audits_it(store, audits):
    response = _put()
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["configured"], body["cadence"], body["adapter"], body["endpoint"]) == (
        True,
        "daily",
        "graphql",
        "https://api.example.com/graphql",
    )
    assert body["nextCheckAt"] is not None
    assert audits[-1]["action"] == AUDIT_SAVED
    assert audits[-1]["detail"] == {"itemId": _ITEM, "cadence": "daily", "adapter": "graphql", "credential": "kept"}


def test_manual_cadence_has_no_next_check(store):
    assert _put({**_BODY, "cadence": "manual"}).json()["nextCheckAt"] is None


@pytest.mark.parametrize(
    ("override", "code"),
    [
        ({"adapter": "openapi"}, "adapter-not-refreshable"),
        ({"endpoint": "file:///etc/passwd"}, "invalid-endpoint"),
        ({"credential": {"authType": "bearer", "payload": {}}}, "invalid-credential"),
    ],
)
def test_invalid_settings_are_refused_with_a_code(store, override, code):
    response = _put({**_BODY, **override})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert store.rows == {}


def test_an_unknown_cadence_is_a_validation_error(store):
    assert _put({**_BODY, "cadence": "monthly"}).status_code == 422


def test_a_credential_is_sealed_and_never_returned(store, audits):
    response = _put({**_BODY, "credential": {"authType": "bearer", "payload": {"token": _SECRET}}})
    assert response.status_code == 200
    assert _SECRET not in response.text
    body = response.json()
    assert body["authType"] == "bearer" and body["hasCredential"] is True
    row = store.rows[_ITEM]
    assert unseal_credential_payload(row["encrypted_payload"], row["key_version"]) == {"token": _SECRET}
    assert _SECRET not in json.dumps(audits)
    assert _SECRET not in client.get(_URL).text


def test_omitting_the_credential_keeps_it_and_null_clears_it(store):
    _put({**_BODY, "credential": {"authType": "bearer", "payload": {"token": _SECRET}}})
    kept = _put({**_BODY, "cadence": "weekly"}).json()
    assert kept["hasCredential"] is True and kept["cadence"] == "weekly"
    cleared = _put({**_BODY, "credential": None}).json()
    assert cleared["hasCredential"] is False and cleared["authType"] == "none"


def test_a_rejected_body_never_echoes_the_secret(store):
    response = _put(
        {**_BODY, "cadence": "monthly", "credential": {"authType": "bearer", "payload": {"token": _SECRET}}}
    )
    assert response.status_code == 422
    assert _SECRET not in response.text


def test_changing_the_endpoint_resets_the_history(store):
    store.add(_ITEM, _TENANT, status="failed", last_fingerprint="fp-a", last_error="boom", consecutive_failures=3)
    body = _put({**_BODY, "endpoint": "https://other.example.com/graphql"}).json()
    assert body["status"] == "never" and body["lastFingerprint"] is None and body["consecutiveFailures"] == 0


def test_delete_removes_the_setting(store, audits):
    store.add(_ITEM, _TENANT)
    assert client.delete(_URL).status_code == 204
    assert store.rows == {} and audits[-1]["action"] == AUDIT_DELETED
    assert client.delete(_URL).status_code == 204  # idempotent


# --- check now -------------------------------------------------------------------------


def test_check_now_runs_and_returns_the_outcome(store, audits):
    register_discovery_runner("graphql", lambda *a: DiscoveryResult("fp-new", None, None))
    store.add(_ITEM, _TENANT, cadence="manual", last_fingerprint="fp-old")
    body = client.post(_URL + "/check").json()
    assert body["status"] == "changed" and body["lastFingerprint"] == "fp-new"
    assert audits[-1] == {
        "tenant_id": _TENANT,
        "action": AUDIT_CHECKED,
        "detail": {"itemId": _ITEM, "status": "changed"},
    }


def test_a_failed_check_answers_200_with_the_failure(store):
    register_discovery_runner("graphql", lambda *a: (_ for _ in ()).throw(RuntimeError("503 from upstream")))
    store.add(_ITEM, _TENANT, cadence="daily")
    response = client.post(_URL + "/check")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed" and body["lastError"] == "503 from upstream"
    assert body["consecutiveFailures"] == 1 and body["nextCheckAt"] is not None


def test_check_needs_a_setting(store):
    assert client.post(_URL + "/check").status_code == 404


def test_check_refuses_an_item_that_is_off(store):
    store.add(_ITEM, _TENANT, cadence="off")
    response = client.post(_URL + "/check")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "refresh-off"


def test_check_refuses_when_the_tenant_switch_is_off(store):
    store.add(_ITEM, _TENANT)
    store.set_tenant_refresh_enabled(None, _TENANT, False)
    response = client.post(_URL + "/check")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "refresh-disabled"


def test_check_refuses_when_the_deployment_switch_is_off(store, monkeypatch):
    monkeypatch.setattr(settings, "catalog_refresh_enabled", False)
    store.add(_ITEM, _TENANT)
    assert client.post(_URL + "/check").json()["detail"]["code"] == "refresh-disabled"


# --- tenant kill switch ----------------------------------------------------------------


def test_the_tenant_switch_round_trips_and_is_audited(store, audits):
    assert client.get("/v1/catalog/acme/refresh-policy").json() == {"enabled": True}
    assert client.put("/v1/catalog/acme/refresh-policy", json={"enabled": False}).json() == {"enabled": False}
    assert store.tenant_enabled[_TENANT] is False
    assert audits[-1]["action"] == AUDIT_POLICY and audits[-1]["detail"] == {"enabled": False}
    store.add(_ITEM, _TENANT)
    assert client.get(_URL).json()["tenantEnabled"] is False
