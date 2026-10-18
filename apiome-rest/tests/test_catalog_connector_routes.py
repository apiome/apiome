"""Catalog connector endpoints (CDG-1.1, #5952).

Authentication is overridden, storage is the in-memory :class:`FakeConnectorStore`, and the MCP
credential envelope uses a throwaway key. Base URLs are IP literals, so the SSRF check resolves
them without DNS. The tests pin the HTTP contract: the ``imports`` permission each route needs,
tenant scoping, the stable private-address refusal, and that no response, audit row or
validation error ever carries a credential.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from catalog_connector_fakes import FakeConnectorStore, restore_builtin_sources
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_connector_routes import AUDIT_CREATE, AUDIT_CREDENTIALS, AUDIT_DELETE, AUDIT_UPDATE
from app.catalog_connector_sync import ConnectorRefreshSource, register_connector_source, unregister_connector_source
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.database import db
from app.main import app
from app.mcp_credential_crypto import unseal_credential_payload
from app.permissions import Action, Resource
from app.refresh_source import FetchedDocument, RefreshCandidate, RefreshSourceError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "44444444-4444-4444-8444-444444444444"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_MISSING = "77777777-7777-4777-8777-777777777777"
_SECRET = "kpat_TOPSECRET_value_123"
_BASE = "/v1/tenants/acme/connectors"


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    monkeypatch.setattr(settings, "connector_private_network_allowlist", "")
    yield
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def _capture(tenant_id, project_id, version_id, action, outcome, actor_id, detail=None):
        rows.append({"tenant_id": tenant_id, "action": action, "outcome": outcome, "detail": detail})

    monkeypatch.setattr(db, "insert_workflow_audit", _capture)
    monkeypatch.setattr(db, "increment_repository_quota_window", lambda **kwargs: None)
    return rows


def _create(**overrides: Any) -> Dict[str, Any]:
    body = {"kind": "kong-admin", "name": "Prod gateway", "scope": {"workspace": "default"}}
    body.update(overrides)
    response = client.post(_BASE, json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- permissions and scoping -----------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "suffix", "body", "action"),
    [
        ("GET", "", None, Action.VIEW),
        ("POST", "", {"kind": "url", "name": "New"}, Action.CREATE),
        ("GET", "/{id}", None, Action.VIEW),
        ("PATCH", "/{id}", {"name": "Renamed"}, Action.EDIT),
        ("DELETE", "/{id}", None, Action.DELETE),
        ("GET", "/{id}/items", None, Action.VIEW),
        ("GET", "/{id}/runs", None, Action.VIEW),
        ("PUT", "/{id}/credentials", {"credentials": {"token": _SECRET}}, Action.EDIT),
    ],
)
def test_each_route_enforces_its_imports_permission(store, audits, method, suffix, body, action):
    existing = store.add_connector(_TENANT)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method, _BASE + suffix.replace("{id}", existing["id"]), json=body)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:] == (Resource.IMPORTS, action)


def test_sync_enforces_imports_edit(store, audits):
    existing = store.add_connector(_TENANT, kind="apigee")
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR) as guard:
        client.post(f"{_BASE}/{existing['id']}/sync")
    assert guard.call_args.args[2:] == (Resource.IMPORTS, Action.EDIT)


def test_a_denied_caller_changes_nothing(store, audits):
    denied = HTTPException(status_code=403, detail="Permission denied")
    with patch("app.catalog_connector_routes.enforce_permission", side_effect=denied):
        response = client.post(_BASE, json={"kind": "url", "name": "x"})
    assert response.status_code == 403
    assert store.connectors == {} and audits == []


def test_another_tenants_connector_is_not_found(store, audits):
    theirs = store.add_connector(_OTHER_TENANT)
    for method, suffix in [("GET", ""), ("PATCH", ""), ("DELETE", ""), ("GET", "/items"), ("GET", "/runs"),
                           ("POST", "/sync"), ("PUT", "/credentials")]:
        body = {"credentials": {"token": "t"}} if suffix == "/credentials" else None
        if method == "PATCH":
            body = {"name": "x"}
        response = client.request(method, f"{_BASE}/{theirs['id']}{suffix}", json=body)
        assert response.status_code == 404, (method, suffix, response.text)
        assert response.json()["detail"]["code"] == "connector-not-found"
    assert client.get(_BASE).json()["connectors"] == []


# --- create / read / update / delete ----------------------------------------------------


def test_create_returns_the_connector_without_credentials(store, audits):
    created = _create(baseUrl="https://93.184.216.34/admin", refreshIntervalSeconds=900)
    assert created["kind"] == "kong-admin" and created["baseUrl"] == "https://93.184.216.34/admin"
    assert created["status"] == "active" and created["conflictPolicy"] == "hold-for-review"
    assert created["hasCredentials"] is False and created["refreshIntervalSeconds"] == 900
    assert created["syncable"] is True  # the Kong sources ship with CDG-1.2
    assert audits[-1]["action"] == AUDIT_CREATE
    assert _create(kind="apigee", name="Apigee", scope={})["syncable"] is False


def test_list_reports_kinds_and_syncable_kinds(store, audits):
    _create(kind="apigee", name="Apigee", scope={})
    body = client.get(_BASE).json()
    assert len(body["kinds"]) == 8
    assert body["syncableKinds"] == ["aws-apigateway", "azure-apim", "kong-admin", "kong-konnect"]
    assert body["connectors"][0]["syncable"] is False
    register_connector_source("apigee", ConnectorRefreshSource)
    try:
        body = client.get(_BASE).json()
    finally:
        unregister_connector_source("apigee")
    assert body["syncableKinds"] == ["apigee", "aws-apigateway", "azure-apim", "kong-admin", "kong-konnect"]
    assert body["connectors"][0]["syncable"] is True


def test_a_kong_scope_is_checked_on_create_and_update(store, audits):
    response = client.post(_BASE, json={"kind": "kong-konnect", "name": "K", "scope": {"region": "mars"}})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "connector-invalid"
    created = _create(kind="kong-konnect", name="Konnect", scope={"region": "eu", "controlPlanes": ["cp-1"]})
    assert created["scope"] == {"region": "eu", "controlPlanes": ["cp-1"]}
    response = client.patch(f"{_BASE}/{created['id']}", json={"scope": {"controlPlanes": "cp-1"}})
    assert response.status_code == 422 and "controlPlanes" in response.json()["detail"]["message"]
    response = client.patch(f"{_BASE}/{created['id']}", json={"scope": {"region": "us"}})
    assert response.status_code == 200 and response.json()["scope"] == {"region": "us"}


def test_a_private_range_base_url_is_refused_with_a_stable_reason(store, audits):
    response = client.post(_BASE, json={"kind": "kong-admin", "name": "x", "baseUrl": "http://10.0.0.5:8001"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "connector-base-url-refused"
    assert response.json()["detail"]["reason"] == "private-address"
    assert store.connectors == {}


def test_the_operator_allowlist_admits_a_private_range(store, audits, monkeypatch):
    monkeypatch.setattr(settings, "connector_private_network_allowlist", "10.0.0.0/24")
    assert _create(baseUrl="http://10.0.0.5:8001")["baseUrl"] == "http://10.0.0.5:8001"


def test_patch_rechecks_the_base_url(store, audits):
    created = _create()
    response = client.patch(f"{_BASE}/{created['id']}", json={"baseUrl": "http://127.0.0.1:8001"})
    assert response.status_code == 422 and response.json()["detail"]["reason"] == "private-address"


def test_secret_like_scope_keys_are_refused(store, audits):
    response = client.post(_BASE, json={"kind": "url", "name": "x", "scope": {"apiKey": _SECRET}})
    assert response.status_code == 422
    assert _SECRET not in response.text


def test_duplicate_names_conflict(store, audits):
    _create(name="Gateway")
    response = client.post(_BASE, json={"kind": "url", "name": "gateway"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "connector-name-taken"


def test_patch_updates_fields_and_audits_their_names(store, audits):
    created = _create()
    response = client.patch(
        f"{_BASE}/{created['id']}", json={"name": "Renamed", "status": "paused", "conflictPolicy": "overwrite"}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["status"], body["conflictPolicy"]) == ("Renamed", "paused", "overwrite")
    assert audits[-1]["action"] == AUDIT_UPDATE
    assert audits[-1]["detail"]["fields"] == ["conflict_policy", "name", "status"]


def test_patch_cannot_set_failing_or_change_the_kind(store, audits):
    created = _create()
    assert client.patch(f"{_BASE}/{created['id']}", json={"status": "failing"}).status_code == 422
    assert client.patch(f"{_BASE}/{created['id']}", json={"kind": "url"}).status_code == 422
    assert client.patch(f"{_BASE}/{created['id']}", json={"name": None}).status_code == 422


def test_delete_soft_deletes_and_drops_the_credential(store, audits):
    created = _create()
    client.put(f"{_BASE}/{created['id']}/credentials", json={"credentials": {"token": _SECRET}})
    assert client.delete(f"{_BASE}/{created['id']}").status_code == 204
    assert client.get(f"{_BASE}/{created['id']}").status_code == 404
    assert store.connectors[created["id"]]["deleted_at"] is not None
    assert created["id"] not in store.credentials
    assert audits[-1]["action"] == AUDIT_DELETE


# --- credentials ------------------------------------------------------------------------


def test_credentials_are_sealed_and_never_returned(store, audits):
    created = _create()
    response = client.put(
        f"{_BASE}/{created['id']}/credentials", json={"credentials": {"token": _SECRET, "user": "svc"}}
    )
    assert response.status_code == 200
    assert response.json() == {
        "connectorId": created["id"],
        "hasCredentials": True,
        "fields": ["token", "user"],
        "replacedAt": response.json()["replacedAt"],
    }
    stored = store.credentials[created["id"]]
    assert _SECRET.encode() not in stored["encrypted_payload"]
    assert unseal_credential_payload(stored["encrypted_payload"], stored["key_version"]) == {
        "token": _SECRET,
        "user": "svc",
    }
    assert client.get(f"{_BASE}/{created['id']}").json()["hasCredentials"] is True
    for path in ("", "/items", "/runs"):
        assert _SECRET not in client.get(f"{_BASE}/{created['id']}{path}").text
    assert _SECRET not in client.get(_BASE).text
    assert audits[-1]["action"] == AUDIT_CREDENTIALS
    assert _SECRET not in json.dumps(audits)


def test_credentials_are_replaced_not_merged(store, audits):
    created = _create()
    client.put(f"{_BASE}/{created['id']}/credentials", json={"credentials": {"token": "first", "extra": "x"}})
    client.put(f"{_BASE}/{created['id']}/credentials", json={"credentials": {"token": _SECRET}})
    stored = store.credentials[created["id"]]
    assert unseal_credential_payload(stored["encrypted_payload"], stored["key_version"]) == {"token": _SECRET}


def test_a_malformed_credentials_request_does_not_echo_the_secret(store, audits):
    created = _create()
    for body in ({"credentials": {"token": _SECRET}, "extra": _SECRET}, {"credential": {"token": _SECRET}},
                 {"credentials": {"token": "x" * 5000}}):
        response = client.put(f"{_BASE}/{created['id']}/credentials", json=body)
        assert response.status_code == 422
        assert _SECRET not in response.text and "x" * 100 not in response.text


def test_credentials_without_an_encryption_key_are_a_503(store, audits, monkeypatch):
    created = _create()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    response = client.put(f"{_BASE}/{created['id']}/credentials", json={"credentials": {"token": _SECRET}})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "connector-encryption-unconfigured"
    assert created["id"] not in store.credentials and _SECRET not in response.text


# --- sync, items, runs ------------------------------------------------------------------


class _RouteSource(ConnectorRefreshSource):
    fail = False

    def list_candidates(self):
        if _RouteSource.fail:
            raise RefreshSourceError("denied", http_status=401)
        return [RefreshCandidate(remote_id="orders", name="Orders", revision="r1", hosts=("orders.example.com",))]

    def fetch(self, candidate):
        return FetchedDocument(content=b"{}", filename="orders.json", revision="r1")


@pytest.fixture
def source(monkeypatch):
    _RouteSource.fail = False
    register_connector_source("kong-admin", _RouteSource)
    monkeypatch.setattr(
        "app.catalog_connector_sync.import_document_as_catalog_item",
        lambda connector, candidate, document, row, actor: "proj-orders",
    )
    yield _RouteSource
    unregister_connector_source("kong-admin")


def test_sync_returns_the_finished_run_and_fills_the_inventory(store, audits, source):
    created = _create()
    response = client.post(f"{_BASE}/{created['id']}/sync")
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded" and run["refreshSource"] == "connector" and run["trigger"] == "manual"
    assert run["pullCount"] == 1 and run["summary"]["imported"] == 1
    items = client.get(f"{_BASE}/{created['id']}/items").json()
    assert items["total"] == 1
    assert items["items"][0] | {} == {
        **items["items"][0],
        "remoteId": "orders",
        "status": "imported",
        "catalogItemId": "proj-orders",
        "hosts": ["orders.example.com"],
    }
    runs = client.get(f"{_BASE}/{created['id']}/runs").json()
    assert runs["total"] == 1 and runs["runs"][0]["id"] == run["id"]


def test_a_failed_sync_is_a_200_carrying_the_provider_failure(store, audits, source):
    created = _create()
    source.fail = True
    run = client.post(f"{_BASE}/{created['id']}/sync").json()
    assert (run["status"], run["errorClass"], run["httpStatus"]) == ("failed", "auth", 401)
    assert client.get(f"{_BASE}/{created['id']}").json()["status"] == "failing"


def test_sync_of_a_kind_without_a_source_is_a_409(store, audits):
    created = _create(kind="apigee")
    response = client.post(f"{_BASE}/{created['id']}/sync")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "connector-kind-unsupported"


def test_items_filter_by_status_and_reject_unknown_ones(store, audits, source):
    created = _create()
    client.post(f"{_BASE}/{created['id']}/sync")
    assert client.get(f"{_BASE}/{created['id']}/items?status=missing").json()["total"] == 0
    assert client.get(f"{_BASE}/{created['id']}/items?status=imported").json()["total"] == 1
    assert client.get(f"{_BASE}/{created['id']}/items?status=gone").status_code == 400


# --- CDG-1.3: dry run on create/update, no credentials for a role-assuming kind -----------

_AWS_SCOPE = {
    "roleArn": "arn:aws:iam::123456789012:role/apiome-catalog",
    "externalId": "apiome-ext-7c1d9a",
    "regions": ["eu-west-1"],
}


@pytest.fixture
def aws_check(monkeypatch):
    """Re-register the AWS source with a scriptable dry run (no AWS calls)."""
    from app import aws_apigateway_connector_source as aws

    calls: List[Dict[str, Any]] = []
    state = {"fail": None}

    def check(connector):
        calls.append(dict(connector))
        if state["fail"]:
            raise ConnectorError("connector-check-failed", "The AWS dry run failed.", reason=state["fail"])

    register_connector_source(
        aws.KIND, aws.AwsApiGatewaySource, scope_validator=aws.validate_aws_scope,
        connection_check=check, accepts_credentials=False,
    )
    return {"calls": calls, "state": state}


def test_creating_an_aws_connector_runs_the_dry_run(store, audits, aws_check):
    created = _create(kind="aws-apigateway", name="AWS prod", scope=_AWS_SCOPE)
    assert created["syncable"] is True and created["hasCredentials"] is False
    assert aws_check["calls"] == [{"kind": "aws-apigateway", "scope": _AWS_SCOPE, "base_url": None}]


def test_a_failed_dry_run_refuses_the_connector_and_names_the_permission(store, audits, aws_check):
    aws_check["state"]["fail"] = "apigateway:GET on arn:aws:apigateway:eu-west-1::/account"
    response = client.post(_BASE, json={"kind": "aws-apigateway", "name": "AWS", "scope": _AWS_SCOPE})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "connector-check-failed"
    assert detail["reason"] == "apigateway:GET on arn:aws:apigateway:eu-west-1::/account"
    assert store.connectors == {}


def test_changing_the_scope_reruns_the_dry_run_but_renaming_does_not(store, audits, aws_check):
    created = _create(kind="aws-apigateway", name="AWS prod", scope=_AWS_SCOPE)
    client.patch(f"{_BASE}/{created['id']}", json={"name": "Renamed"})
    assert len(aws_check["calls"]) == 1
    aws_check["state"]["fail"] = "sts:AssumeRole on arn:aws:iam::123456789012:role/other"
    response = client.patch(
        f"{_BASE}/{created['id']}",
        json={"scope": {**_AWS_SCOPE, "roleArn": "arn:aws:iam::123456789012:role/other"}},
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "connector-check-failed"
    assert store.connectors[created["id"]]["scope"] == _AWS_SCOPE


def test_an_aws_connector_refuses_stored_credentials(store, audits, aws_check):
    created = _create(kind="aws-apigateway", name="AWS prod", scope=_AWS_SCOPE)
    response = client.put(
        f"{_BASE}/{created['id']}/credentials",
        json={"credentials": {"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": _SECRET}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "connector-credentials-refused"
    assert _SECRET not in response.text and store.credentials == {}
