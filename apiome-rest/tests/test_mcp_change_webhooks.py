"""Tests for MCP change-event webhook subscriptions (V2-MCP-27.2 / MCAT-13.2, #3712).

Three layers, all DB-free:

* **Fan-out** — :func:`app.mcp_change_webhooks.deliver_version_created` enqueues one
  ``mcp.version.created`` delivery per active subscription in the event's tenant, with the event
  payload (never the endpoint URL), and never raises.
* **Wiring** — the discovery engine subscribes the handler at import, and a changed discovery
  enqueues deliveries through the engine's own database handle; an unchanged one enqueues none.
* **Acceptance** — an enqueued delivery is sent HMAC-signed with ``X-Apiome-Event:
  mcp.version.created`` and is retried on failure by the standard delivery worker.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import mcp_change_events, mcp_discovery_engine
from app.mcp_change_events import (
    EVENT_TYPE_VERSION_CREATED,
    build_version_created_event,
    emit_version_created,
)
from app.mcp_change_webhooks import deliver_version_created
from app.mcp_client import DiscoveryListings, DiscoverySurface, InitializeResult, ServerInfo
from app.push_webhook_delivery import deliver_one_due_event

_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=timezone.utc)
_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_EP_UUID = "11111111-1111-1111-1111-111111111111"
_JOB_UUID = "22222222-2222-2222-2222-222222222222"
_SECRET_URL = "https://user:secret@mcp.acme.example/mcp"

_ENDPOINT_ROW = {
    "id": _EP_UUID,
    "tenant_id": _TENANT,
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": _SECRET_URL,
    "transport": "streamable_http",
}


def _event(**endpoint_overrides):
    """A ``mcp.version.created`` event for a first version with one added tool."""
    endpoint = {**_ENDPOINT_ROW, **endpoint_overrides}
    return build_version_created_event(
        endpoint,
        {"version_id": "ver-1", "version_seq": 1, "version_tag": "2026-11-08T12:00Z"},
        None,
        [{"change_type": "added", "item_type": "tool", "item_name": "alpha", "detail": {}}],
        discovered_at=_NOW,
        discovery_trigger="manual",
    )


def _db(subscription_ids):
    """A fake database whose enqueue returns a delivery id per subscription."""
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_ids.return_value = list(subscription_ids)
    mdb.enqueue_push_webhook_delivery.side_effect = lambda t, sid, et, p: {"id": f"evt-{sid}"}
    return mdb


# ===========================================================================
# FAN-OUT
# ===========================================================================


def test_enqueues_one_delivery_per_active_subscription():
    mdb = _db(["sub-a", "sub-b"])
    event = _event()

    assert deliver_version_created(event, mdb) == ["evt-sub-a", "evt-sub-b"]

    mdb.list_active_push_webhook_subscription_ids.assert_called_once_with(_TENANT)
    calls = mdb.enqueue_push_webhook_delivery.call_args_list
    assert [c.args[1] for c in calls] == ["sub-a", "sub-b"]
    for call in calls:
        tenant_id, _, event_type, payload = call.args
        assert tenant_id == _TENANT
        assert event_type == EVENT_TYPE_VERSION_CREATED
        assert payload == event.to_payload()


def test_payload_never_carries_the_endpoint_url():
    mdb = _db(["sub-a"])
    deliver_version_created(_event(), mdb)
    payload = mdb.enqueue_push_webhook_delivery.call_args.args[3]
    assert "secret" not in json.dumps(payload)
    assert "mcp.acme.example" not in json.dumps(payload)


def test_no_subscription_enqueues_nothing():
    mdb = _db([])
    assert deliver_version_created(_event(), mdb) == []
    mdb.enqueue_push_webhook_delivery.assert_not_called()


@pytest.mark.parametrize("tenant_id", ["", "   ", None])
def test_event_without_tenant_is_dropped_without_touching_the_db(tenant_id):
    mdb = _db(["sub-a"])
    assert deliver_version_created(_event(tenant_id=tenant_id), mdb) == []
    mdb.list_active_push_webhook_subscription_ids.assert_not_called()


def test_listing_failure_returns_empty_and_never_raises():
    mdb = MagicMock()
    mdb.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("db down")
    assert deliver_version_created(_event(), mdb) == []


def test_one_failed_enqueue_does_not_stop_the_others():
    mdb = _db(["sub-a", "sub-b"])

    def enqueue(tenant_id, subscription_id, event_type, payload):
        if subscription_id == "sub-a":
            raise RuntimeError("subscription deactivated")
        return {"id": "evt-b"}

    mdb.enqueue_push_webhook_delivery.side_effect = enqueue
    assert deliver_version_created(_event(), mdb) == ["evt-b"]


def test_payload_build_failure_returns_empty_and_never_raises():
    mdb = _db(["sub-a"])
    event = _event()
    with patch.object(type(event), "to_payload", side_effect=ValueError("bad")):
        assert deliver_version_created(event, mdb) == []
    mdb.enqueue_push_webhook_delivery.assert_not_called()


# ===========================================================================
# WIRING — the discovery engine delivers through its own handle
# ===========================================================================


def _surface(tools):
    """A tools-only discovered surface with fixed server metadata."""
    init = InitializeResult(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="acme-weather", title="Acme Weather", version="1.0"),
        capabilities={"tools": {}},
        instructions=None,
        raw={},
    )
    return DiscoverySurface.from_discovery(init, DiscoveryListings(tools=list(tools)))


def _tool(name):
    return {"name": name, "description": "d", "inputSchema": {"type": "object", "properties": {}}}


@pytest.fixture
def _engine_handler_only(monkeypatch):
    """A registry holding only the engine's webhook handler, so no other subscriber interferes."""
    monkeypatch.setattr(
        mcp_change_events, "_handlers", [mcp_discovery_engine._deliver_change_webhooks]
    )


def test_engine_subscribes_the_webhook_handler_at_import():
    assert mcp_discovery_engine._deliver_change_webhooks in mcp_change_events._handlers


def test_emitted_event_is_enqueued_through_the_engine_db(_engine_handler_only):
    mdb = _db(["sub-a"])
    with patch.object(mcp_discovery_engine, "db", mdb):
        assert emit_version_created(_event()) == 1
    mdb.enqueue_push_webhook_delivery.assert_called_once()
    assert mdb.enqueue_push_webhook_delivery.call_args.args[2] == EVENT_TYPE_VERSION_CREATED


def test_changed_discovery_enqueues_a_delivery(_engine_handler_only):
    mdb = _db(["sub-a"])
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, _surface([_tool("alpha")]), _NOW, None, "manual"
        )
    assert result["changed"] is True
    mdb.enqueue_push_webhook_delivery.assert_called_once()
    payload = mdb.enqueue_push_webhook_delivery.call_args.args[3]
    assert payload["version"]["id"] == "ver-1"
    assert payload["change_summary"]["initial"] is True


def test_unchanged_discovery_enqueues_nothing(_engine_handler_only):
    surface = _surface([_tool("alpha")])
    mdb = _db(["sub-a"])
    mdb.get_latest_mcp_endpoint_version.return_value = {
        "id": "ver-1",
        "version_seq": 1,
        "surface_fingerprint": surface.fingerprint(),
    }
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, surface, _NOW, None, "sweep"
        )
    assert result["changed"] is False
    mdb.enqueue_push_webhook_delivery.assert_not_called()


def test_webhook_failure_never_fails_the_discovery(_engine_handler_only):
    mdb = MagicMock()
    mdb.get_latest_mcp_endpoint_version.return_value = None
    mdb.record_mcp_discovery_version.return_value = {"version_id": "ver-1", "version_seq": 1}
    mdb.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("db down")
    with patch.object(mcp_discovery_engine, "db", mdb):
        result = mcp_discovery_engine._persist_outcome(
            _JOB_UUID, _ENDPOINT_ROW, _surface([_tool("alpha")]), _NOW, None, "manual"
        )
    assert result["changed"] is True
    mdb.finish_mcp_discovery_job.assert_called_once()


# ===========================================================================
# ACCEPTANCE — signed delivery, retried on failure
# ===========================================================================


def _queued_row(payload, attempt_count=0):
    """The delivery-queue row the worker reads for an enqueued ``mcp.version.created`` event."""
    return {
        "event_id": "33333333-3333-3333-3333-333333333333",
        "tenant_id": _TENANT,
        "subscription_id": "44444444-4444-4444-4444-444444444444",
        "event_type": EVENT_TYPE_VERSION_CREATED,
        "payload": payload,
        "event_status": "pending",
        "attempt_count": attempt_count,
        "next_retry_at": None,
        "subscription_url": "https://hooks.example.com/mcp",
        "subscription_active": True,
        "signing_secret_encrypted": b"x",
    }


def _send(row, status_code):
    """Run one worker attempt for ``row`` against a receiver answering ``status_code``."""
    database = MagicMock()
    response = MagicMock(status_code=status_code, text="", headers={})
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="whsec"),
        patch("app.push_webhook_delivery.httpx.Client") as client,
    ):
        post = client.return_value.__enter__.return_value.post
        post.return_value = response
        deliver_one_due_event(database, row)
    return post, database.finalize_push_webhook_delivery_attempt.call_args.kwargs


def test_subscribed_webhook_receives_a_signed_change_payload():
    payload = _event().to_payload()
    post, outcome = _send(_queued_row(payload), 200)

    sent = post.call_args.kwargs
    body = sent["content"]
    assert json.loads(body) == payload
    assert sent["headers"]["X-Apiome-Event"] == EVENT_TYPE_VERSION_CREATED
    expected = "sha256=" + hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert sent["headers"]["X-Apiome-Signature"] == expected
    assert outcome["new_status"] == "delivered"


def test_failed_delivery_is_scheduled_for_retry():
    _, outcome = _send(_queued_row(_event().to_payload()), 500)
    assert outcome["new_status"] == "retrying"
    assert outcome["next_retry_at"] is not None
