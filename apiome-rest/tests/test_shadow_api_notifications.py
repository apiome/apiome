"""``catalog.connector.shadow_api_detected`` notifications (CDG-1.6, #5957).

A sync that sees an API for the first time, unlinked and matching nothing in the catalog, notifies
the tenant's channels once per connector per hour; possible matches, known rows and ignored rows
never notify, and a notification problem never fails the sync.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import shadow_api_notifications as notifications
from app.catalog_connector_sync import ConnectorRefreshSource, register_connector_source, run_connector_sync
from app.refresh_source import FetchedDocument, RefreshCandidate
from app.shadow_api_store import SHADOW_EVENT_TYPE

TENANT = "11111111-1111-4111-8111-111111111111"


class _ChannelDb(FakeDb):
    """FakeDb plus the push-webhook calls the notifier makes."""

    def __init__(self, channels: List[Dict[str, Any]]) -> None:
        super().__init__()
        self.channels = channels
        self.deliveries: List[Dict[str, Any]] = []

    def list_active_push_webhook_subscription_channels(self, tenant_id):
        return self.channels

    def enqueue_push_webhook_delivery(self, tenant_id, subscription_id, event_type, payload):
        self.deliveries.append({"subscription": subscription_id, "event": event_type, "payload": payload})
        return {"id": f"d{len(self.deliveries)}"}


@pytest.fixture(autouse=True)
def _restore():
    yield
    restore_builtin_sources()


@pytest.fixture
def slots(monkeypatch):
    claimed: List[str] = []

    def claim(db, tenant_id, connector_id, event_type=SHADOW_EVENT_TYPE, window_seconds=3600):
        won = connector_id not in claimed
        claimed.append(connector_id)
        return won

    monkeypatch.setattr(notifications, "claim_connector_notification_slot", claim)
    return claimed


@pytest.fixture
def catalog(monkeypatch):
    entries: List[Dict[str, Any]] = []
    monkeypatch.setattr(notifications, "load_catalog_entries", lambda db, tenant_id: entries)
    return entries


CONNECTOR = {"id": "c1", "tenant_id": TENANT, "name": "Prod Kong", "kind": "kong-admin"}
HOOK = {"id": "s1", "url": "https://hooks.example.com/apiome"}
SLACK = {"id": "s2", "url": "https://hooks.slack.com/services/T/B/x"}


def _row(remote_id: str, **fields: Any) -> Dict[str, Any]:
    return {
        "remote_id": remote_id,
        "remote_name": remote_id,
        "hosts": [f"{remote_id}.example.com"],
        "base_path": None,
        "project_id": None,
        "status": "discovered",
        **fields,
    }


def test_new_shadow_apis_reach_every_channel_once(slots, catalog):
    db = _ChannelDb([HOOK, SLACK])
    outcome = notifications.notify_new_shadow_apis(db, CONNECTOR, [_row("billing"), _row("metrics")])
    assert outcome == {"shadow": 2, "delivered": ["d1", "d2"], "suppressed": None}
    hook, slack = db.deliveries
    assert hook["event"] == SHADOW_EVENT_TYPE and hook["payload"]["count"] == 2
    assert hook["payload"]["reportHref"] == "/ade/dashboard/connectors/shadow?connector=c1"
    assert [a["remoteId"] for a in hook["payload"]["apis"]] == ["billing", "metrics"]
    assert slack["payload"]["text"].startswith("2 new shadow APIs on Prod Kong")

    again = notifications.notify_new_shadow_apis(db, CONNECTOR, [_row("other")])
    assert again["suppressed"] == "throttled" and len(db.deliveries) == 2


def test_possible_matches_linked_and_ignored_rows_do_not_notify(slots, catalog):
    catalog.append(
        {
            "project_id": "p",
            "name": "Orders API",
            "publishable": True,
            "servers": ["https://orders.example.com"],
            "remote_ids": [],
            "version_id": "v",
            "version_label": "1",
        }
    )
    db = _ChannelDb([HOOK])
    rows = [_row("orders"), _row("linked", project_id="p2"), _row("quiet", status="ignored")]
    assert notifications.notify_new_shadow_apis(db, CONNECTOR, rows) is None
    assert db.deliveries == [] and slots == []


def test_no_channels_consumes_no_slot(slots, catalog):
    outcome = notifications.notify_new_shadow_apis(_ChannelDb([]), CONNECTOR, [_row("billing")])
    assert outcome["suppressed"] == "no-channels" and slots == []


def test_a_failure_is_swallowed(monkeypatch, slots):
    def boom(db, tenant_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(notifications, "load_catalog_entries", boom)
    assert notifications.notify_new_shadow_apis(_ChannelDb([HOOK]), CONNECTOR, [_row("x")]) is None


def test_the_payload_lists_at_most_ten_apis():
    payload = notifications.build_shadow_notification(CONNECTOR, [_row(f"api{n}") for n in range(15)])
    assert payload["count"] == 15 and len(payload["apis"]) == notifications.MAX_LISTED


# --- from a sync -------------------------------------------------------------------------


class _Source(ConnectorRefreshSource):
    remote_ids = ["billing"]

    def list_candidates(self):
        return [
            RefreshCandidate(remote_id=r, name=r, revision="1", hosts=(f"{r}.example.com",)) for r in self.remote_ids
        ]

    def fetch(self, candidate):
        return FetchedDocument(content=b"x", filename="x.yaml", revision="1")


def test_a_sync_notifies_only_for_apis_it_sees_for_the_first_time(monkeypatch, slots, catalog):
    store = FakeConnectorStore().install(monkeypatch)
    connector = store.add_connector(TENANT, kind="kong-admin", name="Prod Kong")
    register_connector_source("kong-admin", _Source)
    db = _ChannelDb([HOOK])
    importer = lambda *args: None  # noqa: E731 - every import fails, which must not matter here
    run_connector_sync(db, store.connectors[connector["id"]], importer=importer)
    assert [d["payload"]["apis"][0]["remoteId"] for d in db.deliveries] == ["billing"]

    slots.clear()
    run_connector_sync(db, store.connectors[connector["id"]], importer=importer)
    assert len(db.deliveries) == 1  # billing is no longer new

    _Source.remote_ids = ["billing", "metrics"]
    try:
        run_connector_sync(db, store.connectors[connector["id"]], importer=importer)
    finally:
        _Source.remote_ids = ["billing"]
    assert [a["remoteId"] for a in db.deliveries[-1]["payload"]["apis"]] == ["metrics"]


def test_an_item_import_never_notifies(monkeypatch, slots, catalog):
    store = FakeConnectorStore().install(monkeypatch)
    connector = store.add_connector(TENANT, kind="kong-admin", name="Prod Kong")
    register_connector_source("kong-admin", _Source)
    db = _ChannelDb([HOOK])
    run_connector_sync(db, store.connectors[connector["id"]], importer=lambda *a: "p", only_remote_ids=["billing"])
    assert db.deliveries == []
