"""Catalog drift API and the catalog's drift badge (MFI-31.3, #4400).

The store is replaced with an in-memory fake; the tests pin each route's permission, 404 before
403, the settings round trip (camelCase, defaults when unset), the event list shape, idempotent
dismissal, and the ``drift`` badge on the catalog list and detail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import catalog_drift_store
from app.auth import validate_authentication
from app.catalog_drift_routes import AUDIT_DISMISSED, AUDIT_SETTINGS, drift_badges
from app.database import db
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_ITEM = "22222222-2222-4222-8222-222222222222"
_MISSING = "77777777-7777-4777-8777-777777777777"
_EVENT = "55555555-5555-4555-8555-555555555555"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_SETTINGS_URL = "/v1/catalog/acme/drift-notifications"
_EVENTS_URL = f"/v1/catalog/acme/{_ITEM}/drift"
_DISMISS_URL = f"{_EVENTS_URL}/{_EVENT}/dismiss"
_WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _event(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": _EVENT,
        "tenant_id": _TENANT,
        "project_id": _ITEM,
        "version_id": "66666666-6666-4666-8666-666666666666",
        "parent_version_id": "88888888-8888-4888-8888-888888888888",
        "version_label": "2026-10-28T12:00Z",
        "parent_version_label": "1.0.0",
        "trigger": "sweep",
        "severity": "breaking",
        "counts": {"safe": 1, "dangerous": 0, "breaking": 1},
        "change_count": 2,
        "changes": [
            {
                "severity": "breaking",
                "category": "field",
                "kind": "removed",
                "key": "Order.total",
                "ruleId": "removed-entity",
                "rationale": "gone",
            },
            {
                "severity": "safe",
                "category": "operation",
                "kind": "added",
                "key": "Query.orders",
                "ruleId": "added-entity",
                "rationale": "new",
            },
        ],
        "notification": "sent",
        "notified_at": _WHEN,
        "dismissed_at": None,
        "dismissed_by": None,
        "created_at": _WHEN,
    }
    row.update(overrides)
    return row


class _FakeDriftStore:
    def __init__(self) -> None:
        self.settings: Optional[Dict[str, Any]] = None
        self.events: List[Dict[str, Any]] = []

    def install(self, monkeypatch) -> "_FakeDriftStore":
        monkeypatch.setattr(
            catalog_drift_store, "get_settings_row", lambda d, t: self.settings if t == _TENANT else None
        )
        monkeypatch.setattr(catalog_drift_store, "put_settings", self._put)
        monkeypatch.setattr(
            catalog_drift_store,
            "list_events",
            lambda d, t, p, **kw: [e for e in self.events if e["project_id"] == p and t == _TENANT],
        )
        monkeypatch.setattr(catalog_drift_store, "dismiss_event", self._dismiss)
        monkeypatch.setattr(catalog_drift_store, "latest_open_events", self._latest)
        return self

    def _put(self, d, tenant_id, settings, *, actor_id):
        self.settings = {**settings.as_dict(), "tenant_id": tenant_id, "updated_at": _WHEN, "updated_by": actor_id}
        return self.settings

    def _dismiss(self, d, tenant_id, project_id, event_id, *, actor_id):
        for event in self.events:
            if event["id"] == event_id and event["project_id"] == project_id and tenant_id == _TENANT:
                event["dismissed_at"] = event["dismissed_at"] or _WHEN
                return event
        return None

    def _latest(self, d, tenant_id, ids):
        return {e["project_id"]: e for e in self.events if e["project_id"] in ids and not e["dismissed_at"]}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    monkeypatch.setattr(
        db,
        "get_catalog_item_by_id",
        lambda item_id, tenant_id, **kw: {"id": item_id} if item_id == _ITEM and tenant_id == _TENANT else None,
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> _FakeDriftStore:
    return _FakeDriftStore().install(monkeypatch)


@pytest.fixture
def audits(monkeypatch) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        db,
        "insert_workflow_audit",
        lambda tenant_id, project_id, version_id, action, outcome, actor_id, detail=None: rows.append(
            {"action": action, "project_id": project_id, "detail": detail}
        ),
    )
    return rows


# --- permissions -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "url", "body", "resource", "action"),
    [
        ("GET", _SETTINGS_URL, None, Resource.PROJECTS, Action.VIEW),
        ("PUT", _SETTINGS_URL, {}, Resource.IMPORTS, Action.EDIT),
        ("GET", _EVENTS_URL, None, Resource.PROJECTS, Action.VIEW),
        ("POST", _DISMISS_URL, None, Resource.PROJECTS, Action.EDIT),
    ],
)
def test_each_route_enforces_its_permission(store, audits, method, url, body, resource, action):
    store.events.append(_event())
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR) as guard:
        response = client.request(method, url, json=body)
    assert response.status_code < 400, response.text
    guard.assert_called_once()
    assert guard.call_args.args[2:4] == (resource, action)


@pytest.mark.parametrize(
    "method,url",
    [("GET", f"/v1/catalog/acme/{_MISSING}/drift"), ("POST", f"/v1/catalog/acme/{_MISSING}/drift/{_EVENT}/dismiss")],
)
def test_an_unknown_item_is_404_before_the_permission_check(store, method, url):
    with patch("app.catalog_drift_routes.enforce_permission") as guard:
        response = client.request(method, url)
    assert response.status_code == 404
    guard.assert_not_called()


def test_a_denied_caller_changes_no_settings(store, audits):
    with patch("app.catalog_drift_routes.enforce_permission", side_effect=HTTPException(403, "denied")):
        response = client.put(_SETTINGS_URL, json={"notifySafe": True})
    assert response.status_code == 403
    assert store.settings is None and audits == []


# --- settings --------------------------------------------------------------------------------


def test_unset_settings_read_as_the_defaults(store):
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        body = client.get(_SETTINGS_URL).json()
    assert body == {
        "notifyBreaking": True,
        "notifyDangerous": True,
        "notifySafe": False,
        "delivery": "immediate",
        "breakingImmediate": True,
        "emailEnabled": False,
        "configured": False,
        "updatedAt": None,
        "lastDigestAt": None,
    }


def test_settings_round_trip_and_are_audited(store, audits):
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        saved = client.put(
            _SETTINGS_URL,
            json={"notifySafe": True, "delivery": "daily_digest", "breakingImmediate": False, "emailEnabled": True},
        ).json()
        read = client.get(_SETTINGS_URL).json()
    assert saved == read
    assert (read["notifySafe"], read["delivery"], read["breakingImmediate"], read["emailEnabled"]) == (
        True,
        "daily_digest",
        False,
        True,
    )
    assert read["configured"] is True and read["updatedAt"] == _WHEN.isoformat()
    assert audits == [
        {
            "action": AUDIT_SETTINGS,
            "project_id": None,
            "detail": {
                "notify_breaking": True,
                "notify_dangerous": True,
                "notify_safe": True,
                "delivery": "daily_digest",
                "breaking_immediate": False,
                "email_enabled": True,
            },
        }
    ]


@pytest.mark.parametrize("body", [{"delivery": "hourly"}, {"notifyEverything": True}])
def test_bad_settings_are_rejected(store, body):
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        assert client.put(_SETTINGS_URL, json=body).status_code == 422
    assert store.settings is None


# --- events ----------------------------------------------------------------------------------


def test_events_list_with_changes_and_a_link(store):
    store.events.append(_event())
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        [event] = client.get(_EVENTS_URL).json()["events"]
    assert (event["eventId"], event["severity"], event["versionLabel"], event["parentVersionLabel"]) == (
        _EVENT,
        "breaking",
        "2026-10-28T12:00Z",
        "1.0.0",
    )
    assert event["link"] == f"/ade/dashboard/catalog/{_ITEM}?tab=versions&drift={_EVENT}"
    assert event["changes"][0] == {
        "severity": "breaking",
        "category": "field",
        "kind": "removed",
        "key": "Order.total",
        "ruleId": "removed-entity",
        "rationale": "gone",
    }
    assert event["notification"] == "sent" and event["dismissedAt"] is None


def test_dismiss_is_idempotent_and_audited(store, audits):
    store.events.append(_event())
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        first = client.post(_DISMISS_URL).json()
        second = client.post(_DISMISS_URL).json()
    assert first["dismissedAt"] == second["dismissedAt"] == _WHEN.isoformat()
    assert audits[0] == {"action": AUDIT_DISMISSED, "project_id": _ITEM, "detail": {"itemId": _ITEM, "eventId": _EVENT}}


@pytest.mark.parametrize("event_id", [_MISSING, "not-a-uuid"])
def test_dismissing_an_unknown_event_is_404(store, audits, event_id):
    with patch("app.catalog_drift_routes.enforce_permission", return_value=_ACTOR):
        response = client.post(f"{_EVENTS_URL}/{event_id}/dismiss")
    assert response.status_code == 404
    assert audits == []


# --- badge on the catalog list and detail ----------------------------------------------------


def test_drift_badges_skip_dismissed_events_and_survive_a_failure(store, monkeypatch):
    store.events.append(_event())
    [badge] = drift_badges(_TENANT, [_ITEM]).values()
    assert (badge.severity, badge.change_count, badge.trigger) == ("breaking", 2, "sweep")
    store.events[0]["dismissed_at"] = _WHEN
    assert drift_badges(_TENANT, [_ITEM]) == {}
    monkeypatch.setattr(catalog_drift_store, "latest_open_events", lambda *a: (_ for _ in ()).throw(RuntimeError("db")))
    assert drift_badges(_TENANT, [_ITEM]) == {}


def test_the_catalog_list_and_detail_carry_the_badge(store, monkeypatch):
    store.events.append(_event())
    item = {"id": _ITEM, "tenant_id": _TENANT, "name": "Orders", "slug": "orders", "publishable": False}
    monkeypatch.setattr(db, "get_catalog_items_for_tenant", lambda *a, **kw: [dict(item)])
    monkeypatch.setattr(db, "get_artifact_tags_for_projects", lambda *a, **kw: {})
    monkeypatch.setattr(db, "get_catalog_item_by_id", lambda *a, **kw: dict(item))
    monkeypatch.setattr("app.catalog_routes._build_related_artifacts", lambda *a: [])
    monkeypatch.setattr("app.catalog_routes._audit_catalog_access", lambda *a, **kw: None, raising=False)

    [listed] = client.get("/v1/catalog/acme").json()
    assert listed["drift"]["severity"] == "breaking"
    assert listed["drift"]["eventId"] == _EVENT
    assert listed["drift"]["link"].endswith(f"drift={_EVENT}")
    detail = client.get(f"/v1/catalog/acme/{_ITEM}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["drift"]["versionLabel"] == "2026-10-28T12:00Z"
