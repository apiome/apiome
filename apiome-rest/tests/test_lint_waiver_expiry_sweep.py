"""Unit tests for the waiver-expiry notification sweep (CLX-4.2, #4860)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.lint_waiver_expiry_sweep import process_lint_waiver_expiry_sweep


class FakeDb:
    """Claim-once double: returns the pending rows on the first claim, nothing after."""

    def __init__(self, rows):
        self._pending = list(rows)
        self.claim_calls = []
        self.enqueued = []
        self._counter = 0

    def claim_expiring_lint_waivers(self, *, cutoff, limit=50):
        self.claim_calls.append((cutoff, limit))
        claimed, self._pending = self._pending[:limit], self._pending[limit:]
        return claimed

    def list_active_push_webhook_subscription_ids(self, tenant_id):
        return ["s1"]

    def enqueue_push_webhook_delivery(self, tenant_id, subscription_id, event_type, payload):
        self._counter += 1
        self.enqueued.append((tenant_id, event_type, payload))
        return {"id": f"d{self._counter}"}


def _waiver(decision_id: str, expires_at: str) -> dict:
    return {
        "id": decision_id,
        "tenant_id": "t1",
        "project_id": None,
        "source_fingerprint": f"fp-{decision_id}",
        "rule_id": "naming.rule",
        "state": "waived",
        "rationale": "accepted",
        "linked_ticket": None,
        "expires_at": expires_at,
    }


def test_sweep_claims_once_and_notifies_each_waiver():
    db = FakeDb([_waiver("d1", "2026-07-15T00:00:00+00:00"), _waiver("d2", "2026-07-16T00:00:00+00:00")])
    assert process_lint_waiver_expiry_sweep(db, warning_hours=72) == 2
    assert [p["decisionId"] for _, _, p in db.enqueued] == ["d1", "d2"]
    assert all(e == "lint.waiver.expiring" for _, e, _ in db.enqueued)
    payload = db.enqueued[0][2]
    assert payload["expiresAt"] == "2026-07-15T00:00:00+00:00"

    # Second tick: everything already claimed -> nothing new fires.
    assert process_lint_waiver_expiry_sweep(db, warning_hours=72) == 0
    assert len(db.enqueued) == 2


def test_sweep_cutoff_uses_warning_window():
    db = FakeDb([])
    before = datetime.now(timezone.utc)
    process_lint_waiver_expiry_sweep(db, warning_hours=48)
    cutoff, limit = db.claim_calls[0]
    assert limit == 50
    assert timedelta(hours=47, minutes=59) < (cutoff - before) < timedelta(hours=48, minutes=1)


def test_sweep_defaults_to_configured_window():
    from app.config import settings

    db = FakeDb([])
    with patch.object(settings, "lint_waiver_expiry_warning_hours", 24):
        process_lint_waiver_expiry_sweep(db)
    cutoff, _ = db.claim_calls[0]
    delta = cutoff - datetime.now(timezone.utc)
    assert timedelta(hours=23) < delta < timedelta(hours=25)


def test_sweep_survives_claim_failure():
    class BrokenDb:
        def claim_expiring_lint_waivers(self, **kwargs):
            raise RuntimeError("db down")

    assert process_lint_waiver_expiry_sweep(BrokenDb(), warning_hours=1) == 0
