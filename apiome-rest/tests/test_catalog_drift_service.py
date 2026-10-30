"""Recording and announcing catalog drift, and the daily digest (MFI-31.3, #4400).

The store, the webhook fan-out and owner routing are replaced with recorders, so the tests pin what
is stored and what is sent without a database: breaking drift from a sweep raises a webhook and an
owner finding at once, safe drift only badges, a manual check never announces, digest mode holds
events until the digest, and nothing here ever raises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app import catalog_drift_service as service
from app import catalog_drift_store
from app.catalog_refresh import pipeline_discovery_result

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = {"id": "22222222-2222-4222-8222-222222222222", "tenant_id": _TENANT, "name": "Orders", "slug": "orders"}
_V1 = "type Order { id: ID! total: Float }\ntype Query { order(id: ID!): Order }\n"
_V2 = "type Order { id: ID! }\ntype Query { order(id: ID!): Order }\n"  # breaking
_V3 = "type Order { id: ID! total: Float }\ntype Query { order(id: ID!): Order orders: [Order!]! }\n"  # safe
_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _model(sdl: str):
    return pipeline_discovery_result("graphql", sdl.encode(), "schema.graphql").model


class _Recorder:
    """Fake store + fan-out + owner routing."""

    def __init__(self) -> None:
        self.settings_row: Dict[str, Any] | None = None
        self.inserted: List[Dict[str, Any]] = []
        self.webhooks: List[Dict[str, Any]] = []
        self.routed: List[Any] = []
        self.pending: Dict[str, List[Dict[str, Any]]] = {}
        self.digested: List[Any] = []

    def install(self, monkeypatch) -> "_Recorder":
        monkeypatch.setattr(catalog_drift_store, "get_settings_row", lambda db, t: self.settings_row)
        monkeypatch.setattr(catalog_drift_store, "insert_event", self._insert)
        monkeypatch.setattr(catalog_drift_store, "tenants_due_for_digest", lambda db, **kw: list(self.pending))
        monkeypatch.setattr(catalog_drift_store, "pending_digest_events", lambda db, t: self.pending.get(t, []))
        monkeypatch.setattr(catalog_drift_store, "mark_digested", lambda db, t, ids: self.digested.append((t, ids)))
        monkeypatch.setattr(
            "app.push_webhook_fanout.enqueue_event",
            lambda db, **kw: self.webhooks.append(kw) or ["d-1"],
        )
        monkeypatch.setattr(
            "app.owner_routing.route_owner_finding_safely", lambda db, finding: self.routed.append(finding)
        )
        return self

    def _insert(self, db, **kw):
        row = {
            "id": f"e-{len(self.inserted) + 1}",
            "tenant_id": kw["tenant_id"],
            "project_id": kw["project_id"],
            "version_id": kw["version_id"],
            "parent_version_id": kw["parent_version_id"],
            "version_label": kw["version_label"],
            "parent_version_label": kw["parent_version_label"],
            "trigger": kw["trigger"],
            "severity": kw["classification"].severity,
            "counts": kw["classification"].counts,
            "change_count": kw["classification"].change_count,
            "changes": kw["classification"].changes,
            "notification": kw["notification"],
            "created_at": _NOW,
        }
        self.inserted.append(row)
        return row


@pytest.fixture
def rec(monkeypatch) -> _Recorder:
    return _Recorder().install(monkeypatch)


def _record(before: str, after: str, trigger: str = "sweep"):
    return service.record_refresh_drift(
        None,
        item=_ITEM,
        previous_model=_model(before),
        new_model=_model(after),
        version_id="v-2",
        version_label="2026-10-28T12:00Z",
        parent_version_id="v-1",
        parent_version_label="1.0.0",
        trigger=trigger,
        actor_id="u-saver",
    )


def test_breaking_sweep_drift_raises_a_webhook_and_an_owner_finding_at_once(rec):
    event = _record(_V1, _V2)
    assert (event["severity"], event["notification"]) == ("breaking", "sent")
    [hook] = rec.webhooks
    assert hook["event_type"] == "catalog.drift.detected" and hook["tenant_id"] == _TENANT
    assert hook["payload"]["severity"] == "breaking"
    assert hook["payload"]["topFindings"][0]["key"] == "Order.total"
    [finding] = rec.routed
    assert (finding.entity_kind, finding.entity_id, finding.finding_type) == (
        "catalog_item",
        _ITEM["id"],
        "owner_breaking_change",
    )
    assert finding.link == f"/ade/dashboard/catalog/{_ITEM['id']}?tab=versions&drift=e-1"
    assert finding.actor_id == "u-saver" and finding.version_id == "v-2"


def test_safe_drift_badges_quietly(rec):
    event = _record(_V1, _V3)
    assert (event["severity"], event["notification"]) == ("safe", "none")
    assert rec.webhooks == [] and rec.routed == []


def test_safe_drift_notifies_when_the_tenant_asks(rec):
    rec.settings_row = {"notify_safe": True}
    assert _record(_V1, _V3)["notification"] == "sent"
    assert len(rec.webhooks) == 1


def test_a_manual_check_is_recorded_but_never_announced(rec):
    event = _record(_V1, _V2, trigger="manual")
    assert (event["severity"], event["notification"], event["trigger"]) == ("breaking", "none", "manual")
    assert rec.webhooks == [] and rec.routed == []


def test_digest_mode_holds_non_breaking_drift(rec, monkeypatch):
    rec.settings_row = {"delivery": "daily_digest", "notify_safe": True}
    assert _record(_V1, _V3)["notification"] == "pending_digest"
    assert rec.webhooks == []
    assert _record(_V1, _V2)["notification"] == "sent"  # breaking skips the digest by default


def test_a_storage_failure_is_swallowed(rec, monkeypatch):
    monkeypatch.setattr(
        catalog_drift_store, "insert_event", lambda db, **kw: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    assert _record(_V1, _V2) is None
    assert rec.webhooks == []


def test_an_owner_routing_failure_is_swallowed(rec, monkeypatch):
    monkeypatch.setattr(
        "app.owner_routing.route_owner_finding_safely", lambda db, f: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert _record(_V1, _V2)["notification"] == "sent"
    assert len(rec.webhooks) == 1


# --- digest ---------------------------------------------------------------------------------


def _pending(event_id: str, item: str, severity: str) -> Dict[str, Any]:
    return {
        "id": event_id,
        "tenant_id": _TENANT,
        "project_id": item,
        "version_id": f"v-{event_id}",
        "parent_version_id": "v-0",
        "version_label": "2026-10-27T12:00Z",
        "parent_version_label": "1.0.0",
        "trigger": "sweep",
        "severity": severity,
        "counts": {severity: 1},
        "change_count": 1,
        "changes": [],
        "notification": "pending_digest",
        "created_at": _NOW,
        "item_name": f"Item {item}",
        "item_slug": item,
    }


def test_a_due_digest_sends_one_webhook_routes_each_items_worst_and_marks_events(rec):
    rec.pending[_TENANT] = [
        _pending("e-1", "a", "safe"),
        _pending("e-2", "a", "dangerous"),
        _pending("e-3", "b", "safe"),
    ]
    assert service.send_due_digests(None, now=_NOW) == 1
    [hook] = rec.webhooks
    assert hook["event_type"] == "catalog.drift.digest"
    assert hook["payload"]["eventCount"] == 3
    assert hook["payload"]["bySeverity"] == {"safe": 2, "dangerous": 1, "breaking": 0}
    assert [(f.entity_id, f.details["severity"]) for f in rec.routed] == [("a", "dangerous"), ("b", "safe")]
    assert rec.digested == [(_TENANT, ["e-1", "e-2", "e-3"])]


def test_no_due_tenant_sends_nothing(rec):
    assert service.send_due_digests(None, now=_NOW) == 0
    assert rec.webhooks == [] and rec.digested == []


def test_one_tenants_digest_failure_does_not_stop_the_next(rec, monkeypatch):
    other = "44444444-4444-4444-8444-444444444444"
    rec.pending[_TENANT] = [_pending("e-1", "a", "safe")]
    rec.pending[other] = [{**_pending("e-9", "z", "safe"), "tenant_id": other}]

    def _events(db, tenant_id):
        if tenant_id == _TENANT:
            raise RuntimeError("read failed")
        return rec.pending[tenant_id]

    monkeypatch.setattr(catalog_drift_store, "pending_digest_events", _events)
    assert service.send_due_digests(None, now=_NOW) == 1
    assert rec.digested == [(other, ["e-9"])]


def test_a_failed_tenant_listing_sends_nothing(rec, monkeypatch):
    monkeypatch.setattr(
        catalog_drift_store, "tenants_due_for_digest", lambda db, **kw: (_ for _ in ()).throw(RuntimeError("down"))
    )
    assert service.send_due_digests(None) == 0


# --- email (#6384) --------------------------------------------------------------------------


@pytest.fixture
def emails(monkeypatch) -> Dict[str, List[Dict[str, Any]]]:
    """Records the drift email calls the service makes."""
    calls: Dict[str, List[Dict[str, Any]]] = {"event": [], "digest": []}
    monkeypatch.setattr("app.catalog_drift_email.email_event", lambda db, **kw: calls["event"].append(kw) or 1)
    monkeypatch.setattr("app.catalog_drift_email.email_digest", lambda db, **kw: calls["digest"].append(kw) or 1)
    return calls


def test_with_email_on_an_announced_event_is_emailed_too(rec, emails):
    rec.settings_row = {"email_enabled": True}
    _record(_V1, _V2)
    [call] = emails["event"]
    assert (call["tenant_id"], call["item_id"], call["actor_id"]) == (_TENANT, _ITEM["id"], "u-saver")
    assert call["payload"]["severity"] == "breaking" and call["payload"]["eventId"] == "e-1"


def test_with_email_off_nothing_is_emailed(rec, emails):
    _record(_V1, _V2)
    assert len(rec.webhooks) == 1 and emails["event"] == []


def test_email_follows_the_announcement_not_the_badge(rec, emails):
    rec.settings_row = {"email_enabled": True, "delivery": "daily_digest", "notify_safe": True}
    _record(_V1, _V3)  # held for the digest
    _record(_V1, _V2, trigger="manual")  # never announced
    assert emails["event"] == []


def test_with_email_on_a_digest_emails_every_waiting_event(rec, emails):
    rec.settings_row = {"email_enabled": True}
    rec.pending[_TENANT] = [_pending("e-1", "a", "safe"), _pending("e-2", "a", "dangerous")]
    assert service.send_due_digests(None, now=_NOW) == 1
    [call] = emails["digest"]
    assert call["tenant_id"] == _TENANT
    assert [p["eventId"] for p in call["payloads"]] == ["e-1", "e-2"]
    assert rec.digested == [(_TENANT, ["e-1", "e-2"])]


def test_with_email_off_a_digest_is_not_emailed(rec, emails):
    rec.pending[_TENANT] = [_pending("e-1", "a", "safe")]
    assert service.send_due_digests(None, now=_NOW) == 1
    assert emails["digest"] == []
