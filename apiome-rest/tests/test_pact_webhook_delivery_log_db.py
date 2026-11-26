"""The webhook delivery log and redelivery against a live Postgres — PFX-5.6 (#6950).

What only the real schema proves (apiome-db V436, V445):

* the workspace's log and one webhook's log list firings newest first, narrowed by status, and
  page through an opaque cursor without repeating or skipping a firing;
* the latest delivery of each webhook is the newest of its firings; a webhook that never fired
  has none;
* **redelivering a finished firing queues a new one** with the same event and parameters,
  triggered by a user, and keeps the original; a firing still queued, or one of a disabled
  webhook, is refused with its reason;
* nothing crosses a tenant.

Runs inside one always-rolled-back transaction (the fixtures of ``test_pact_webhook_db``).
Skipped when no database is reachable or V436 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest

from tests import test_pact_webhook_db as webhook_db

tx = webhook_db.tx
stack = webhook_db.stack
broker = webhook_db.broker
integration = webhook_db.integration

pytestmark = pytest.mark.requires_db

BASE = webhook_db.BASE
DELIVERIES = "/v1/tenants/t/pact-webhook-deliveries"
_MODULE = "app.pact_webhook_delivery_routes"


@pytest.fixture
def log(integration: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The integration, with the delivery-log routes on its transaction."""
    with patch(f"{_MODULE}.db", integration["db"]), patch(f"{_MODULE}.enforce_permission", return_value=None):
        yield integration


def _finish(log: Dict[str, Any], delivery_event_id: str, status: str = "dead_letter", attempts: int = 4) -> None:
    """Move a queued delivery to a finished state, as the worker would."""
    log["cursor"].execute(
        "UPDATE apiome.push_webhook_delivery_events SET status = %s::apiome.push_webhook_delivery_status, "
        "attempt_count = %s, next_retry_at = NULL WHERE id = %s::uuid",
        (status, attempts, delivery_event_id),
    )


def test_the_workspace_and_webhook_logs_list_newest_first_and_page(log: Dict[str, Any]) -> None:
    client = log["client"]
    published = webhook_db._create(log, "contract_published")
    changed = webhook_db._create(log, "contract_content_changed")
    webhook_db._publish(log, "2.0.0", total=2500, branch="main")
    webhook_db._publish(log, "3.0.0", total=2600, branch="main")
    firings = webhook_db._firings(log)
    assert len(firings) == 4

    everything = client.get(DELIVERIES).json()
    assert {item["id"] for item in everything["deliveries"]} == {firing["id"] for firing in firings}
    assert everything["nextCursor"] is None
    first = everything["deliveries"][0]
    assert first["status"] == "not_run" and first["triggerType"] == "resource_creation"
    assert first["consumer"] == {"name": "Billing Service", "slug": "billing-service"}
    assert first["provider"]["slug"] == "ledger-api" and len(first["pactVersionSha"]) == 64

    # One page at a time: no firing repeated or skipped.
    seen = []
    cursor = None
    while True:
        query = {"limit": 1, **({"cursor": cursor} if cursor else {})}
        page = client.get(DELIVERIES, params=query).json()
        seen += [item["id"] for item in page["deliveries"]]
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(firing["id"] for firing in firings) and len(set(seen)) == 4

    mine = client.get(DELIVERIES, params={"webhook": published["uuid"]}).json()["deliveries"]
    assert {item["webhookId"] for item in mine} == {published["uuid"]} and len(mine) == 2

    _finish(log, firings[0]["delivery_event_id"])
    failed = client.get(DELIVERIES, params={"status": "failure"}).json()["deliveries"]
    assert [item["id"] for item in failed] == [firings[0]["id"]]
    assert failed[0]["attemptsMade"] == 4 and failed[0]["attemptsRemaining"] == 0
    assert len(client.get(DELIVERIES, params={"status": "not_run"}).json()["deliveries"]) == 3

    latest = client.get(f"{DELIVERIES}/latest").json()["latest"]
    assert set(latest) == {published["uuid"], changed["uuid"]}
    # The newest is the first of the webhook's firings in the (newest-first) log.
    newest = next(item for item in everything["deliveries"] if item["webhookId"] == published["uuid"])
    assert latest[published["uuid"]]["id"] == newest["id"]

    detail = client.get(f"{DELIVERIES}/{firings[0]['id']}").json()
    assert detail["id"] == firings[0]["id"] and detail["executions"] == []


def test_a_finished_delivery_is_redelivered_as_a_new_firing(log: Dict[str, Any]) -> None:
    client = log["client"]
    webhook_db._create(log, "contract_published")
    webhook_db._publish(log, "2.0.0", total=2500, branch="main")
    (firing,) = webhook_db._firings(log)

    # Still queued: sending it again would deliver it twice.
    queued = client.post(f"{DELIVERIES}/{firing['id']}/redeliver")
    assert queued.status_code == 409 and queued.json()["detail"]["code"] == "pact-webhook-delivery-in-progress"

    _finish(log, firing["delivery_event_id"])
    response = client.post(f"{DELIVERIES}/{firing['id']}/redeliver")
    assert response.status_code == 202, response.text
    again = response.json()
    assert again["id"] != firing["id"] and again["webhookId"] == firing["webhook_id"]
    assert again["status"] == "not_run" and again["triggerType"] == "user"
    assert again["eventName"] == "contract_published" and again["consumerVersionNumber"] == "2.0.0"

    after = webhook_db._firings(log)
    assert len(after) == 2
    original = next(item for item in after if item["id"] == firing["id"])
    copy = next(item for item in after if item["id"] == again["id"])
    assert original["status"] == "dead_letter"
    assert copy["status"] == "pending" and copy["payload"] == firing["payload"]
    assert copy["event_type"] == firing["event_type"]


def test_a_disabled_webhook_is_not_redelivered(log: Dict[str, Any]) -> None:
    client = log["client"]
    created = webhook_db._create(log, "contract_published")
    webhook_db._publish(log, "2.0.0", total=2500, branch="main")
    (firing,) = webhook_db._firings(log)
    _finish(log, firing["delivery_event_id"], status="delivered", attempts=1)
    log["cursor"].execute("UPDATE apiome.pact_webhook SET enabled = false WHERE id = %s::uuid", (created["uuid"],))

    response = client.post(f"{DELIVERIES}/{firing['id']}/redeliver")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "pact-webhook-disabled"
    assert len(webhook_db._firings(log)) == 1


def test_another_tenants_deliveries_are_not_found(log: Dict[str, Any]) -> None:
    client = log["client"]
    created = webhook_db._create(log, "contract_published")
    webhook_db._publish(log, "2.0.0", total=2500, branch="main")
    (firing,) = webhook_db._firings(log)
    _finish(log, firing["delivery_event_id"])

    with patch(f"{_MODULE}._tenant_id", return_value=log["other"]["tenant"]):
        assert client.get(DELIVERIES).json() == {"deliveries": [], "nextCursor": None}
        assert client.get(f"{DELIVERIES}/latest").json() == {"latest": {}}
        assert client.get(f"{DELIVERIES}/{firing['id']}").status_code == 404
        assert client.post(f"{DELIVERIES}/{firing['id']}/redeliver").status_code == 404
        assert client.get(DELIVERIES, params={"webhook": created["uuid"]}).status_code == 404
