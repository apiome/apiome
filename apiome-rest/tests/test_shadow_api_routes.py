"""Shadow-API report endpoint and connector item actions (CDG-1.6, #5957).

Authentication is overridden and storage is the in-memory :class:`FakeConnectorStore`; the report's
SQL loaders and the item writes are replaced by fakes over the same rows. Pins the HTTP contract:
the ``imports`` permission each route needs, tenant scoping, that linking needs an existing target,
that an ignore keeps its reason, and that "Import" syncs exactly one item, past every gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from catalog_connector_fakes import FakeConnectorStore, restore_builtin_sources
from fastapi.testclient import TestClient

from app import shadow_api_store
from app.auth import validate_authentication
from app.catalog_connector_routes import AUDIT_ITEM_IGNORED, AUDIT_ITEM_LINKED, AUDIT_ITEM_UNIGNORED
from app.catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from app.database import db
from app.main import app
from app.permissions import Action, Resource
from app.refresh_source import FetchedDocument, RefreshCandidate

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_PROJECT = "55555555-5555-4555-8555-555555555555"
_MISSING = "77777777-7777-4777-8777-777777777777"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_BASE = "/v1/tenants/acme/connectors"
_NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    fake = FakeConnectorStore().install(monkeypatch)

    def get_item(db_, tenant_id, connector_id, item_id):
        row = fake.items.get(item_id)
        connector = fake.connectors.get(connector_id)
        if not row or row["connector_id"] != connector_id or not connector or connector["tenant_id"] != tenant_id:
            return None
        return dict(row)

    def ignore_item(db_, item_id, *, reason, actor_id):
        row = fake.items[item_id]
        row.update(
            status="ignored",
            ignored_reason=reason,
            ignored_at=_NOW,
            ignored_by=actor_id,
            ignored_hosts=list(row["hosts"]),
            ignored_base_path=row["base_path"],
        )

    def unignore_item(db_, item_id):
        row = fake.items[item_id]
        row.update(status="imported" if row["project_id"] else "discovered", ignored_reason=None, ignored_at=None)

    def link_item(db_, item_id, *, project_id, actor_id):
        row = fake.items[item_id]
        row.update(status="imported", project_id=project_id, linked_by=actor_id, linked_at=_NOW, ignored_reason=None)

    for name, fn in (
        ("get_item", get_item),
        ("ignore_item", ignore_item),
        ("unignore_item", unignore_item),
        ("link_item", link_item),
    ):
        monkeypatch.setattr(shadow_api_store, name, fn)
    return fake


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        db,
        "insert_workflow_audit",
        lambda tenant_id, project_id, version_id, action, outcome, actor_id, detail=None: rows.append(
            {"action": action, "detail": detail}
        ),
    )
    monkeypatch.setattr(db, "increment_repository_quota_window", lambda **kwargs: None)
    return rows


@pytest.fixture
def projects(monkeypatch):
    known = {_PROJECT: {"id": _PROJECT, "tenant_id": _TENANT, "deleted_at": None}}
    monkeypatch.setattr(db, "get_project_by_id", lambda pid, tid: known.get(pid) if tid == _TENANT else None)
    return known


def _seed(store: FakeConnectorStore, **item_fields: Any):
    connector = store.add_connector(_TENANT, kind="kong-admin", name="Prod Kong")
    item = {
        "id": "99999999-9999-4999-8999-999999999999",
        "connector_id": connector["id"],
        "remote_id": "svc-orders",
        "remote_name": "orders",
        "environment": "prod",
        "hosts": ["orders.example.com"],
        "base_path": "/v2",
        "remote_revision": "r1",
        "remote_updated_at": None,
        "imported_revision": None,
        "imported_remote_updated_at": None,
        "imported_sha256": None,
        "status": "discovered",
        "project_id": None,
        "first_seen_at": _NOW,
        "last_seen_at": _NOW,
        "deployment": {},
        **item_fields,
    }
    store.items[item["id"]] = item
    return connector, item


def _item_url(connector, item, action):
    return f"{_BASE}/{connector['id']}/items/{item['id']}/{action}"


# --- the report --------------------------------------------------------------------------


def test_the_report_route_builds_from_the_loaders(monkeypatch):
    connector = {"id": "c1", "name": "Kong", "kind": "kong-admin", "status": "active", "last_success_at": _NOW}
    seen: Dict[str, Any] = {}

    def items(db_, ids, env):
        seen["items"] = (ids, env)
        return [
            {
                "id": "i1",
                "connector_id": "c1",
                "remote_id": "a",
                "remote_name": "Shadow one",
                "hosts": ["a.example.com"],
                "base_path": None,
                "status": "discovered",
                "project_id": None,
            },
        ]

    monkeypatch.setattr(
        shadow_api_store, "load_report_connectors", lambda db_, t, c: seen.setdefault("c", (t, c)) and [connector]
    )
    monkeypatch.setattr(shadow_api_store, "load_report_items", items)
    monkeypatch.setattr(shadow_api_store, "load_catalog_entries", lambda db_, t: [])
    with patch("app.shadow_api_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.get("/v1/tenants/acme/shadow-report?environment=prod")
    assert response.status_code == 200, response.text
    assert guard.call_args.args[2:] == (Resource.IMPORTS, Action.VIEW)
    body = response.json()
    assert body["summary"] == {"shadow": 1, "possibleMatches": 0, "undeployed": 0, "drift": 0, "ignored": 0}
    assert body["shadow"][0]["itemId"] == "i1" and body["shadow"][0]["basePath"] is None
    assert body["filters"] == {"connector": None, "environment": "prod"}
    assert seen["c"] == (_TENANT, None) and seen["items"] == (["c1"], "prod")


def test_an_unknown_connector_filter_is_a_404(monkeypatch):
    monkeypatch.setattr(shadow_api_store, "load_report_connectors", lambda db_, t, c: [])
    with patch("app.shadow_api_routes.enforce_permission", return_value=_ACTOR):
        response = client.get(f"/v1/tenants/acme/shadow-report?connector={_MISSING}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "connector-not-found"


# --- item actions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "body"),
    [
        ("link", {"catalogItemId": _PROJECT}),
        ("ignore", {"reason": "Health check"}),
        ("unignore", None),
    ],
)
def test_each_item_action_needs_imports_edit(store, audits, projects, action, body):
    connector, item = _seed(store)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.post(_item_url(connector, item, action), json=body)
    assert response.status_code == 200, response.text
    assert guard.call_args.args[2:] == (Resource.IMPORTS, Action.EDIT)


def test_link_sets_the_catalog_item_and_audits(store, audits, projects):
    connector, item = _seed(store)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_item_url(connector, item, "link"), json={"catalogItemId": _PROJECT})
    body = response.json()
    assert body["catalogItemId"] == _PROJECT and body["status"] == "imported" and body["linkedAt"]
    assert audits[-1]["action"] == AUDIT_ITEM_LINKED and audits[-1]["detail"]["catalogItemId"] == _PROJECT


def test_link_to_an_unknown_target_is_a_404_and_writes_nothing(store, audits, projects):
    connector, item = _seed(store)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_item_url(connector, item, "link"), json={"catalogItemId": _MISSING})
    assert response.status_code == 404
    assert store.items[item["id"]]["project_id"] is None and audits == []


def test_ignore_keeps_the_reason_and_unignore_clears_it(store, audits, projects):
    connector, item = _seed(store)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        ignored = client.post(_item_url(connector, item, "ignore"), json={"reason": "  Internal health check "}).json()
        assert ignored["status"] == "ignored" and ignored["ignoredReason"] == "Internal health check"
        assert store.items[item["id"]]["ignored_hosts"] == ["orders.example.com"]
        restored = client.post(_item_url(connector, item, "unignore")).json()
    assert restored["status"] == "discovered" and restored["ignoredReason"] is None
    assert [a["action"] for a in audits] == [AUDIT_ITEM_IGNORED, AUDIT_ITEM_UNIGNORED]


@pytest.mark.parametrize(
    "body", [{}, {"reason": ""}, {"reason": "   "}, {"reason": "x" * 1001}, {"reason": "ok", "x": 1}]
)
def test_an_ignore_without_a_usable_reason_is_refused(store, audits, projects, body):
    connector, item = _seed(store)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_item_url(connector, item, "ignore"), json=body)
    assert response.status_code == 422 and store.items[item["id"]]["status"] == "discovered"


def test_an_item_of_another_connector_is_a_404(store, audits, projects):
    connector, item = _seed(store)
    other = store.add_connector(_TENANT, kind="kong-admin", name="Other")
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(f"{_BASE}/{other['id']}/items/{item['id']}/ignore", json={"reason": "x"})
    assert response.status_code == 404


class _TwoApis(ConnectorRefreshSource):
    """Two candidates; records what it was asked to fetch."""

    fetched: List[str] = []

    def list_candidates(self):
        return [
            RefreshCandidate(remote_id="svc-orders", name="orders", revision="r1", hosts=("orders.example.com",)),
            RefreshCandidate(remote_id="svc-other", name="other", revision="r1", hosts=("other.example.com",)),
        ]

    def should_import(self, candidate):
        return False  # by default nothing would be imported

    def fetch(self, candidate):
        _TwoApis.fetched.append(candidate.remote_id)
        return FetchedDocument(content=b"openapi: 3.0.0", filename="x.yaml", revision="r1")


def test_import_syncs_only_that_item_past_every_gate(store, audits, projects, monkeypatch):
    connector, item = _seed(store, status="ignored", ignored_reason="later", imported_revision="r1", project_id=None)
    _TwoApis.fetched = []
    register_connector_source("kong-admin", _TwoApis)
    monkeypatch.setattr("app.catalog_connector_sync.import_document_as_catalog_item", lambda *a, **k: _PROJECT)
    with patch("app.catalog_connector_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(_item_url(connector, item, "import"))
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "succeeded" and run["summary"]["imported"] == 1
    assert run["summary"]["requested"] == ["svc-orders"]
    assert _TwoApis.fetched == ["svc-orders"]
    assert store.items[item["id"]]["project_id"] == _PROJECT
