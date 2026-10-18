"""Connector dry run and the unified refresh ledger (CDG-1.7, #5958).

``POST …/connectors/dry-run`` asks a connector's source for its inventory with credentials used
for that call only; ``GET …/refresh-runs`` lists Git refresh jobs and connector runs together. The
store is the in-memory fake and authentication is overridden.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from catalog_connector_fakes import FakeConnectorStore, restore_builtin_sources
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_connector_sync import ConnectorRefreshSource, dry_run_connector, register_connector_source
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.database import db
from app.main import app
from app.permissions import Action, Resource
from app.refresh_source import FetchedDocument, RefreshCandidate, RefreshSourceError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_OTHER_TENANT = "44444444-4444-4444-8444-444444444444"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_SECRET = "kpat_DRYRUN_secret_value_42"
_BASE = "/v1/tenants/acme"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    monkeypatch.setattr(settings, "connector_private_network_allowlist", "")
    monkeypatch.setattr(db, "insert_workflow_audit", lambda *a, **k: None)
    yield
    app.dependency_overrides.clear()
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    return FakeConnectorStore().install(monkeypatch)


class _Inventory(ConnectorRefreshSource):
    """Records what it was built with and lists ``count`` candidates."""

    built: List[Dict[str, Any]] = []
    count = 3

    def __init__(self, connector, credentials=None):
        super().__init__(connector, credentials)
        _Inventory.built.append({"connector": dict(connector), "credentials": credentials})
        self.findings = [{"code": "route-without-service", "severity": "warning"}]

    def list_candidates(self):
        return [
            RefreshCandidate(remote_id=f"svc-{n}", name=f"Service {n}", revision=str(n), environment="prod")
            for n in range(self.count)
        ]

    def fetch(self, candidate):  # pragma: no cover - a dry run never fetches
        raise AssertionError("a dry run must not fetch")


class _Refusing(ConnectorRefreshSource):
    def list_candidates(self):
        raise RefreshSourceError(f"Token {_SECRET} is not valid (401 Unauthorized)", http_status=401)

    def fetch(self, candidate):  # pragma: no cover
        return FetchedDocument(content=b"", filename="x")


def _dry(body: Dict[str, Any]):
    return client.post(f"{_BASE}/connectors/dry-run", json=body)


# --- dry run -----------------------------------------------------------------------------


def test_a_dry_run_counts_the_inventory_and_stores_nothing(store):
    _Inventory.built = []
    _Inventory.count = 3
    register_connector_source("kong-admin", _Inventory)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = _dry(
            {
                "kind": "kong-admin",
                "baseUrl": "https://93.184.216.34:8001",
                "scope": {"workspace": "default"},
                "credentials": {"token": _SECRET},
            }
        )
    assert response.status_code == 200, response.text
    assert guard.call_args.args[2:] == (Resource.IMPORTS, Action.CREATE)
    body = response.json()
    assert body["itemCount"] == 3 and body["truncated"] is False
    assert body["items"][0] == {"remoteId": "svc-0", "name": "Service 0", "environment": "prod", "revision": "0"}
    assert body["findings"] == [{"code": "route-without-service", "severity": "warning"}]
    assert _Inventory.built[0]["credentials"] == {"token": _SECRET}
    assert _Inventory.built[0]["connector"]["scope"] == {"workspace": "default"}
    assert store.connectors == {} and store.credentials == {} and store.runs == {} and store.items == {}
    assert _SECRET not in response.text


def test_a_large_inventory_is_sampled(store):
    _Inventory.count = 45
    register_connector_source("kong-admin", _Inventory)
    body = _dry({"kind": "kong-admin", "baseUrl": "https://93.184.216.34:8001", "scope": {}}).json()
    _Inventory.count = 3
    assert body["itemCount"] == 45 and len(body["items"]) == 20 and body["truncated"] is True


def test_a_refused_dry_run_names_the_provider_reason_without_the_secret(store):
    register_connector_source("kong-admin", _Refusing)
    response = _dry(
        {"kind": "kong-admin", "baseUrl": "https://93.184.216.34:8001", "scope": {}, "credentials": {"token": _SECRET}}
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "connector-check-failed" and detail["reason"] == "auth"
    assert "401 Unauthorized" in detail["message"] and "HTTP 401" in detail["message"]
    assert _SECRET not in response.text


def test_a_dry_run_checks_the_scope_and_the_base_url(store):
    response = _dry({"kind": "kong-konnect", "scope": {"region": "mars"}})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "connector-invalid"
    response = _dry({"kind": "kong-admin", "baseUrl": "http://10.0.0.5:8001", "scope": {}})
    assert response.status_code == 422 and response.json()["detail"]["reason"] == "private-address"


def test_a_kind_without_a_source_is_a_409(store):
    response = _dry({"kind": "mcp-registry", "scope": {}})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "connector-kind-unsupported"


def test_a_kind_that_stores_no_credential_refuses_one(store):
    response = _dry(
        {
            "kind": "aws-apigateway",
            "scope": {"roleArn": "arn:aws:iam::123456789012:role/r", "externalId": "ext-123", "regions": ["eu-west-1"]},
            "credentials": {"secretAccessKey": _SECRET},
        }
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "connector-credentials-refused"


def test_a_malformed_dry_run_never_echoes_a_credential(store):
    response = _dry({"kind": "kong-admin", "credentials": {"token": _SECRET}, "unexpected": True})
    assert response.status_code == 422 and _SECRET not in response.text


def test_dry_run_helper_redacts_and_classifies():
    register_connector_source("kong-admin", _Refusing)
    with pytest.raises(ConnectorError) as info:
        dry_run_connector({"id": "x", "kind": "kong-admin", "scope": {}}, {"token": _SECRET})
    assert info.value.reason == "auth" and _SECRET not in str(info.value)


# --- the ledger --------------------------------------------------------------------------


def test_the_ledger_interleaves_git_and_connector_runs(store):
    connector = store.add_connector(_TENANT, kind="kong-admin", name="Prod Kong")
    store.add_git_run(_TENANT, repository_full_name="acme/specs", path="orders.yaml")
    store.start_run(db, _TENANT, connector["id"], trigger="manual", created_by=_ACTOR)
    store.add_git_run(_TENANT, status="failed", error_message="clone failed")
    store.add_git_run(_OTHER_TENANT)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR) as guard:
        body = client.get(f"{_BASE}/refresh-runs").json()
    assert guard.call_args.args[2:] == (Resource.IMPORTS, Action.VIEW)
    assert body["total"] == 3
    assert [r["source"] for r in body["runs"]] == ["git", "connector", "git"]
    connector_run = body["runs"][1]
    assert connector_run["connectorName"] == "Prod Kong" and connector_run["connectorKind"] == "kong-admin"
    assert connector_run["trigger"] == "manual"
    git_run = body["runs"][2]
    assert (git_run["repositoryName"], git_run["path"], git_run["reason"]) == (
        "acme/specs",
        "orders.yaml",
        "newer-content",
    )


def test_the_ledger_filters_by_connector_and_source(store):
    connector = store.add_connector(_TENANT, kind="kong-admin", name="Prod Kong")
    store.add_git_run(_TENANT)
    store.start_run(db, _TENANT, connector["id"], trigger="scheduled", created_by=None)
    only = client.get(f"{_BASE}/refresh-runs?connector={connector['id']}").json()
    assert [r["source"] for r in only["runs"]] == ["connector"] and only["total"] == 1
    git = client.get(f"{_BASE}/refresh-runs?source=git").json()
    assert [r["source"] for r in git["runs"]] == ["git"]
    assert client.get(f"{_BASE}/refresh-runs?source=ftp").status_code == 400
    missing = "77777777-7777-4777-8777-777777777777"
    assert client.get(f"{_BASE}/refresh-runs?connector={missing}").status_code == 404
