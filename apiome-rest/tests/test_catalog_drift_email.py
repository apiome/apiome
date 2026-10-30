"""Catalog drift email — content, recipients and sending (MFI-31.3a, #6384).

Pins: the event email names the item, grade, versions, counts and top findings and links to
**What changed** on the public UI address, escaping HTML; the digest lists each drift; recipients
are the confirmed owner team's enabled members minus the actor, and nobody without an owner; a
digest is one email per recipient listing only their items; with no mailer nothing is sent; and
nothing here raises.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app import catalog_drift_email as email
from app import mailer
from app.owner_routing import OwnerRecipients, OwnerTeam

_TENANT = "11111111-1111-4111-8111-111111111111"
_BASE = "https://app.apiome.example/"


def _payload(item_id: str = "item-a", name: str = "Orders", severity: str = "breaking", **extra: Any) -> Dict:
    return {
        "eventId": f"e-{item_id}",
        "artifact": {"kind": "catalog_item", "id": item_id, "name": name, "slug": item_id},
        "versions": {"from": {"id": "v-1", "label": "1.0.0"}, "to": {"id": "v-2", "label": "2026-10-28T12:00Z"}},
        "severity": severity,
        "counts": {"breaking": 1, "dangerous": 0, "safe": 2},
        "topFindings": [
            {
                "severity": "breaking",
                "key": "Order.total",
                "ruleId": "r1",
                "rationale": "Removing a field breaks <clients>",
            },
            {"severity": "safe", "key": "Query.orders", "ruleId": "r2", "rationale": None},
        ],
        "summary": f"{name} drifted: 1 {severity} change.",
        "link": f"/ade/dashboard/catalog/{item_id}?tab=versions&drift=e-{item_id}",
        **extra,
    }


# --- content --------------------------------------------------------------------------------


def test_the_event_email_says_what_drifted_and_links_to_it():
    message = email.event_message(_payload(), base_url=_BASE)
    assert message.subject == "[Apiome] Breaking drift in Orders"
    assert "Orders drifted: 1 breaking change." in message.text
    assert "Versions: 1.0.0 → 2026-10-28T12:00Z" in message.text
    assert "Changes: 1 breaking, 2 safe" in message.text
    assert "- [breaking] Order.total: Removing a field breaks <clients>" in message.text
    assert "- [safe] Query.orders\n" in message.text
    link = "https://app.apiome.example/ade/dashboard/catalog/item-a?tab=versions&drift=e-item-a"
    assert message.text.endswith(f"See what changed: {link}")
    assert "&lt;clients&gt;" in message.html and "<clients>" not in message.html
    assert f'href="{link.replace("&", "&amp;")}"' in message.html


def test_an_event_without_findings_or_name_still_reads():
    bare = {**_payload(), "artifact": {"id": "x"}, "topFindings": [], "counts": {}}
    message = email.event_message(bare, base_url=_BASE)
    assert message.subject == "[Apiome] Breaking drift in A catalog item"
    assert "Top findings" not in message.text and "Changes: no graded changes" in message.text


def test_the_digest_email_lists_each_drift():
    message = email.digest_message([_payload("a", "Orders"), _payload("b", "Billing", "safe")], base_url=_BASE)
    assert message.subject == "[Apiome] Daily drift digest: 2 catalog drifts"
    assert "- Orders drifted: 1 breaking change. (1.0.0 → 2026-10-28T12:00Z) https://app.apiome.example/" in (
        message.text
    )
    assert "Billing drifted: 1 safe change." in message.text
    assert message.html.count("<li>") == 2
    assert email.digest_message([_payload()], base_url=_BASE).subject.endswith("1 catalog drift")


def test_links_use_the_public_ui_address_by_default(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ui_public_url", "https://ui.example")
    assert email.absolute_link("/ade/x") == "https://ui.example/ade/x"


# --- recipients -----------------------------------------------------------------------------


class _DB:
    """Answers the users query from a map of id → (email, enabled)."""

    def __init__(self, users: Dict[str, str]) -> None:
        self.users = users
        self.queries: List[Any] = []

    def execute_query(self, sql: str, params: Any) -> List[Dict[str, Any]]:
        self.queries.append(params)
        return [{"id": uid, "email": self.users[uid]} for uid in params[0] if uid in self.users]


@pytest.fixture
def owners(monkeypatch) -> Dict[str, List[str]]:
    """Item id → owner team member ids; an item missing from the map has no confirmed owner."""
    teams: Dict[str, List[str]] = {}

    def _recipients(db, tenant_id, kind, item_id, *, exclude=()):
        assert kind == "catalog_item"
        if item_id not in teams:
            return None
        team = OwnerTeam(id="t", slug="t", name="T")
        return OwnerRecipients(team=team, user_ids=[u for u in teams[item_id] if u not in set(exclude)])

    monkeypatch.setattr("app.owner_routing.owner_recipients", _recipients)
    return teams


def test_recipients_are_the_owner_teams_members_in_order(owners):
    owners["item-a"] = ["u-lead", "u-2", "u-no-address"]
    db = _DB({"u-2": "two@team.example", "u-lead": "lead@team.example"})
    assert email.owner_emails(db, _TENANT, "item-a") == ["lead@team.example", "two@team.example"]


def test_the_actor_is_not_emailed_and_no_owner_means_nobody(owners):
    owners["item-a"] = ["u-actor", "u-2"]
    db = _DB({"u-actor": "me@team.example", "u-2": "two@team.example"})
    assert email.owner_emails(db, _TENANT, "item-a", exclude=["u-actor"]) == ["two@team.example"]
    assert email.owner_emails(db, _TENANT, "unowned") == []
    owners["empty"] = []
    assert email.owner_emails(db, _TENANT, "empty") == []
    assert len(db.queries) == 1  # no users query without members


# --- sending --------------------------------------------------------------------------------


class _Outbox:
    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    def __call__(self, to, subject, text, html=None) -> bool:
        self.sent.append({"to": to, "subject": subject, "text": text})
        return True


def test_an_event_is_emailed_to_each_owner(owners):
    owners["item-a"] = ["u-1", "u-2"]
    outbox = _Outbox()
    db = _DB({"u-1": "one@team.example", "u-2": "two@team.example"})
    assert email.email_event(db, tenant_id=_TENANT, item_id="item-a", payload=_payload(), send=outbox) == 2
    assert [m["to"] for m in outbox.sent] == ["one@team.example", "two@team.example"]
    assert outbox.sent[0]["subject"] == "[Apiome] Breaking drift in Orders"


def test_a_digest_is_one_email_per_recipient_with_only_their_items(owners):
    owners["a"] = ["u-1"]
    owners["b"] = ["u-1", "u-2"]
    outbox = _Outbox()
    db = _DB({"u-1": "one@team.example", "u-2": "two@team.example"})
    payloads = [_payload("a", "Orders"), _payload("b", "Billing"), _payload("c", "Unowned")]
    assert email.email_digest(db, tenant_id=_TENANT, payloads=payloads, send=outbox) == 2
    by_to = {m["to"]: m for m in outbox.sent}
    assert "Orders" in by_to["one@team.example"]["text"] and "Billing" in by_to["one@team.example"]["text"]
    assert "Orders" not in by_to["two@team.example"]["text"] and "Billing" in by_to["two@team.example"]["text"]
    assert all("Unowned" not in m["text"] for m in outbox.sent)
    assert by_to["one@team.example"]["subject"].endswith("2 catalog drifts")


def test_without_a_mailer_nothing_is_looked_up_or_sent(owners, monkeypatch):
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    monkeypatch.setattr(mailer, "send_email", lambda *a, **k: pytest.fail("sent without a mailer"))
    owners["item-a"] = ["u-1"]
    db = _DB({"u-1": "one@team.example"})
    assert email.email_event(db, tenant_id=_TENANT, item_id="item-a", payload=_payload()) == 0
    assert email.email_digest(db, tenant_id=_TENANT, payloads=[_payload()]) == 0
    assert db.queries == []


def test_the_configured_mailer_is_used_by_default(owners, monkeypatch):
    outbox = _Outbox()
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_email", outbox)
    owners["item-a"] = ["u-1"]
    db = _DB({"u-1": "one@team.example"})
    assert email.email_event(db, tenant_id=_TENANT, item_id="item-a", payload=_payload()) == 1


def test_a_refused_send_is_not_counted(owners):
    owners["item-a"] = ["u-1"]
    db = _DB({"u-1": "one@team.example"})
    assert email.email_event(db, tenant_id=_TENANT, item_id="item-a", payload=_payload(), send=lambda *a: False) == 0


def test_failures_are_swallowed(owners, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.owner_routing.owner_recipients", boom)
    outbox = _Outbox()
    assert email.email_event(None, tenant_id=_TENANT, item_id="item-a", payload=_payload(), send=outbox) == 0
    assert email.email_digest(None, tenant_id=_TENANT, payloads=[_payload()], send=outbox) == 0
