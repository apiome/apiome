"""Unit tests for the drift-alert fan-out — CTG-4.4 (#4501).

The database handle is a mock. What is asserted is the contract every sibling notification module
in this codebase shares, and which the sweep depends on:

* one delivery per active subscription, stamped with the right event type;
* a per-subscription failure is skipped, never fatal to the batch; and
* **nothing here ever raises** — a notification problem must not turn a recorded verification into
  a lost one.

Retry, HMAC signing, and dead-lettering are the push-webhook pipeline's, untouched by this ticket,
so they are not re-asserted here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.verification_schedule_notifications import (
    EVENT_VERIFICATION_DRIFT_DETECTED,
    EVENT_VERIFICATION_DRIFT_RESOLVED,
    notify_verification_drift,
    notify_verification_recovered,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PAYLOAD = {"event": EVENT_VERIFICATION_DRIFT_DETECTED, "reason": "transition"}


def _db(subscriptions):
    """A database mock with the given active subscriptions."""
    db = MagicMock()
    db.list_active_push_webhook_subscription_ids.return_value = subscriptions
    db.enqueue_push_webhook_delivery.side_effect = lambda *_a, **_k: {"id": "evt"}
    return db


def test_one_delivery_per_active_subscription():
    """Fan-out, not broadcast: each subscription gets its own delivery row."""
    db = _db(["s1", "s2", "s3"])
    assert notify_verification_drift(db, tenant_id=_TENANT, payload=_PAYLOAD) == [
        "evt",
        "evt",
        "evt",
    ]
    assert db.enqueue_push_webhook_delivery.call_count == 3
    assert db.enqueue_push_webhook_delivery.call_args.args[2] == (
        EVENT_VERIFICATION_DRIFT_DETECTED
    )


def test_recovery_uses_its_own_event_type():
    """A subscriber must be able to route "it is fixed" differently from "it is broken"."""
    db = _db(["s1"])
    notify_verification_recovered(db, tenant_id=_TENANT, payload=_PAYLOAD)
    assert db.enqueue_push_webhook_delivery.call_args.args[2] == (
        EVENT_VERIFICATION_DRIFT_RESOLVED
    )


def test_a_tenant_with_no_subscriptions_is_quietly_empty():
    """Nobody is listening; that is not an error."""
    assert notify_verification_drift(_db([]), tenant_id=_TENANT, payload=_PAYLOAD) == []


def test_a_dead_subscription_does_not_fail_the_batch():
    """One subscription deactivated between the listing and the enqueue must not silence the rest."""
    db = _db(["s1", "s2"])
    db.enqueue_push_webhook_delivery.side_effect = [
        RuntimeError("gone"),
        {"id": "evt-2"},
    ]
    assert notify_verification_drift(db, tenant_id=_TENANT, payload=_PAYLOAD) == ["evt-2"]


def test_a_failed_subscription_listing_never_raises():
    """A notification problem can never fail the sweep it describes."""
    db = MagicMock()
    db.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("no table")
    assert notify_verification_drift(db, tenant_id=_TENANT, payload=_PAYLOAD) == []


def test_an_enqueue_that_returns_no_id_is_not_counted():
    """A delivery nobody can identify is not one this function claims to have made."""
    db = _db(["s1"])
    db.enqueue_push_webhook_delivery.side_effect = lambda *_a, **_k: {}
    assert notify_verification_drift(db, tenant_id=_TENANT, payload=_PAYLOAD) == []
