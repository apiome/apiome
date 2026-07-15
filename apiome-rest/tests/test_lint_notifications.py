"""Unit tests for the lint governance webhooks (CLX-4.2, #4860)."""

from unittest.mock import MagicMock, patch

from app.lint_notifications import (
    EVENT_LINT_COVERAGE_FAILED,
    EVENT_LINT_REGRESSION_DETECTED,
    EVENT_LINT_SCAN_COMPLETED,
    EVENT_LINT_WAIVER_EXPIRING,
    notify_lint_coverage_failed,
    notify_lint_regression,
    notify_lint_scan_completed,
    notify_lint_waiver_expiring,
)


class FakeDb:
    """Minimal db double: N active subscriptions, records every enqueue."""

    def __init__(self, subscription_ids=("s1", "s2"), fail_for=()):
        self.subscription_ids = list(subscription_ids)
        self.fail_for = set(fail_for)
        self.enqueued = []
        self._counter = 0

    def list_active_push_webhook_subscription_ids(self, tenant_id):
        return list(self.subscription_ids)

    def enqueue_push_webhook_delivery(self, tenant_id, subscription_id, event_type, payload):
        if subscription_id in self.fail_for:
            raise RuntimeError("subscription is gone")
        self._counter += 1
        self.enqueued.append((tenant_id, subscription_id, event_type, payload))
        return {"id": f"d{self._counter}"}


RUN = {
    "id": "run-1",
    "subject_type": "catalog_revision",
    "version_record_id": "v1",
    "mcp_version_id": None,
    "scanner_id": "apiome.lint",
    "scanner_version": "1.0",
    "adapter_version": None,
    "profile": "default",
    "outcome": "findings",
    "report_fingerprint": "rf1",
    "input_fingerprint": "if1",
    "source_fingerprint": "sf1",
    "config_fingerprint": "cf1",
    "raw_artifact_ref": "s3://bucket/raw-should-never-appear",
    "findings": [{"rule_id": "r"}, {"rule_id": "r2"}],
}


def test_scan_completed_payload_and_fan_out():
    db = FakeDb()
    ids = notify_lint_scan_completed(db, tenant_id="t1", run=RUN)
    assert ids == ["d1", "d2"]
    assert len(db.enqueued) == 2
    _, _, event_type, payload = db.enqueued[0]
    assert event_type == EVENT_LINT_SCAN_COMPLETED
    assert payload["event"] == EVENT_LINT_SCAN_COMPLETED
    assert payload["versionRecordId"] == "v1"
    assert payload["scannerId"] == "apiome.lint"
    assert payload["evidenceRunId"] == "run-1"
    assert payload["reportFingerprint"] == "rf1"
    assert payload["findingCount"] == 2
    # Fingerprints only — the raw artifact reference never enters a payload (AC-5).
    assert "raw-should-never-appear" not in str(payload)
    # None-valued keys are dropped (mcpVersionId, adapterVersion).
    assert "mcpVersionId" not in payload and "adapterVersion" not in payload


def test_fan_out_skips_failing_subscription_and_never_raises():
    db = FakeDb(subscription_ids=("s1", "dead", "s3"), fail_for=("dead",))
    ids = notify_lint_scan_completed(db, tenant_id="t1", run=RUN)
    assert ids == ["d1", "d2"]  # dead subscription skipped, others delivered


def test_fan_out_survives_listing_failure():
    db = MagicMock()
    db.list_active_push_webhook_subscription_ids.side_effect = RuntimeError("db down")
    assert notify_lint_scan_completed(db, tenant_id="t1", run=RUN) == []


def test_regression_payload():
    db = FakeDb(subscription_ids=("s1",))
    notify_lint_regression(
        db,
        tenant_id="t1",
        subject_type="catalog_revision",
        subject_id="v1",
        project_id="p1",
        baseline_subject_id="v0",
        new_fingerprints=["fp-1", "fp-2"],
        regression_count=2,
        policy_version_id="pv1",
        policy_content_fingerprint="packfp",
        evaluation_id="e1",
        links={"evidence": "/e", "policy": None},
    )
    payload = db.enqueued[0][3]
    assert payload["event"] == EVENT_LINT_REGRESSION_DETECTED
    assert payload["newFingerprints"] == ["fp-1", "fp-2"]
    assert payload["count"] == 2
    assert payload["policyContentFingerprint"] == "packfp"
    assert payload["baselineSubjectId"] == "v0"
    assert payload["links"] == {"evidence": "/e"}


def test_coverage_failed_payload():
    db = FakeDb(subscription_ids=("s1",))
    notify_lint_coverage_failed(
        db,
        tenant_id="t1",
        subject_type="mcp_endpoint_version",
        subject_id="m1",
        missing_axes=["security"],
        required_axes=["quality", "security"],
        policy_version_id="pv1",
        evaluation_id=None,
        links=None,
    )
    payload = db.enqueued[0][3]
    assert payload["event"] == EVENT_LINT_COVERAGE_FAILED
    assert payload["missingAxes"] == ["security"]
    assert payload["requiredAxes"] == ["quality", "security"]
    assert "evaluationId" not in payload and "links" not in payload


def test_waiver_expiring_payload_and_missing_tenant():
    db = FakeDb(subscription_ids=("s1",))
    decision = {
        "id": "d-1",
        "tenant_id": "t1",
        "project_id": "p1",
        "source_fingerprint": "fp-1",
        "rule_id": "naming.rule",
        "state": "waived",
        "expires_at": "2026-08-01T00:00:00+00:00",
        "rationale": "accepted",
        "linked_ticket": "JIRA-9",
    }
    notify_lint_waiver_expiring(db, decision=decision)
    payload = db.enqueued[0][3]
    assert payload["event"] == EVENT_LINT_WAIVER_EXPIRING
    assert payload["decisionId"] == "d-1"
    assert payload["expiresAt"] == "2026-08-01T00:00:00+00:00"
    assert payload["decisionHref"] == "/v1/lint/decisions/d-1"

    # A row without a tenant cannot fan out but must not raise.
    assert notify_lint_waiver_expiring(db, decision={"id": "x"}) == []


def test_record_lint_evidence_run_notifies_only_on_insert():
    """The database hook fires once for a new run and stays silent on dedup skip."""
    from app.database import Database

    db = Database.__new__(Database)  # no connection — everything used is patched

    with patch.object(
        Database, "execute_query", return_value=[{"id": "run-9"}]
    ), patch.object(
        Database, "tenant_id_for_lint_subject", return_value="t1"
    ), patch(
        "app.lint_notifications.notify_lint_scan_completed"
    ) as notify:
        new_id = Database.record_lint_evidence_run(db, dict(RUN))
    assert new_id == "run-9"
    assert notify.call_count == 1
    kwargs = notify.call_args.kwargs
    assert kwargs["tenant_id"] == "t1"
    assert kwargs["run"]["id"] == "run-9"

    # Dedup: the guarded INSERT returned no rows -> no notification.
    with patch.object(Database, "execute_query", return_value=[]), patch(
        "app.lint_notifications.notify_lint_scan_completed"
    ) as notify:
        assert Database.record_lint_evidence_run(db, dict(RUN)) is None
    assert notify.call_count == 0


def test_record_lint_evidence_run_survives_notification_failure():
    from app.database import Database

    db = Database.__new__(Database)
    with patch.object(
        Database, "execute_query", return_value=[{"id": "run-9"}]
    ), patch.object(
        Database, "tenant_id_for_lint_subject", side_effect=RuntimeError("boom")
    ):
        assert Database.record_lint_evidence_run(db, dict(RUN)) == "run-9"
