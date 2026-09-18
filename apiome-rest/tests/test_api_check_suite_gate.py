"""The API change check suite as a publish gate — GNC-3.1 (#4740).

"Tenant policy can require the check before publish." Pinned here: the gate is off until a policy
arms it; once armed it accepts only a passing (or skipped) evaluation of *exactly* the current
content under *exactly* the policies in force; a placeholder never satisfies it; every other case
blocks with a reason; and the gate's own faults never block a publish. Also pinned: the precheck
step refuses with the shared 422 shape, and the publish audit records what the gate decided.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from app import (
    api_check_suite_gate,
    api_check_suite_policy_store,
    deploy_gate_store,
    version_publish_prechecks,
    versions_routes,
)
from app.api_check_suite import requirements_fingerprint
from app.api_check_suite_gate import (
    REASON_FAILED,
    REASON_NOT_EVALUATED,
    REASON_PENDING,
    REASON_STALE,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_SATISFIED,
    STATUS_UNAVAILABLE,
    assess_check_suite_gate,
)
from app.version_publish_prechecks import PublishPrecheckOutcome
from tests.fake_suite_db import FakeSuiteDb

TENANT = "9f8e7d60-7777-4aaa-8bbb-000000000001"
PROJECT = "9f8e7d60-7777-4aaa-8bbb-000000000002"
VERSION = "9f8e7d60-7777-4aaa-8bbb-000000000010"
ALICE = "9f8e7d60-7777-4aaa-8bbb-000000000101"
DIGEST = "sha256:current-draft"


@pytest.fixture
def fake(monkeypatch) -> FakeSuiteDb:
    """A store beneath the gate, the policy store, and the deploy-gate threshold store."""
    database = FakeSuiteDb()
    database.add_project(TENANT, PROJECT, "pets")
    database.add_version(PROJECT, VERSION, "2.0.0")
    for module in (api_check_suite_gate, api_check_suite_policy_store, deploy_gate_store):
        monkeypatch.setattr(module, "db", database)
    return database


def _arm(**components: str) -> None:
    """Require the suite before publish, with component requirements."""
    api_check_suite_policy_store.save_policy(
        TENANT, body={"requiredForPublish": True, "components": components}
    )


def _evaluate(
    fake: FakeSuiteDb,
    state: str,
    *,
    digest: str = DIGEST,
    evaluated: bool = True,
    components: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Record an evaluation of the version under the policies in force now."""
    policy = api_check_suite_policy_store.load_policy(TENANT, PROJECT)
    thresholds = deploy_gate_store.load_policy(TENANT, PROJECT)
    produced = fake.insert_check_suite_run(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        binding_id=None,
        commit_sha=None,
        pr_number=None,
        check_name="apiome/api-change",
        evaluated=evaluated,
        state=state,
        reason="r",
        draft_digest=digest,
        policy_source=policy.source,
        policy_fingerprint=requirements_fingerprint(policy.policy),
        policy={},
        thresholds_source=thresholds.source,
        thresholds_fingerprint=thresholds.content_fingerprint,
        thresholds={},
        components=components or [],
        input_fingerprint=f"sha256:{len(fake.suite_runs)}",
        created_by=ALICE,
    )
    return produced["id"]


def _assess(digest: str = DIGEST):
    """Assess the version, with the draft at ``digest``."""
    return assess_check_suite_gate(
        tenant_id=TENANT,
        project_id=PROJECT,
        version={"id": VERSION},
        digest_loader=lambda _tenant, _version: digest,
    )


def test_the_gate_is_off_until_a_policy_arms_it(fake):
    assessment = _assess()
    assert assessment.status == STATUS_DISABLED
    assert assessment.blocked is False
    assert assessment.required_for_publish is False


def test_an_armed_gate_blocks_a_version_that_was_never_evaluated(fake):
    _arm()
    assessment = _assess()
    assert (assessment.status, assessment.reason) == (STATUS_BLOCKED, REASON_NOT_EVALUATED)
    assert "has not been run" in assessment.message()


@pytest.mark.parametrize("state", ["pass", "skipped"])
def test_a_passing_or_skipped_evaluation_of_this_content_satisfies_it(fake, state):
    _arm()
    run_id = _evaluate(fake, state)
    assessment = _assess()
    assert assessment.status == STATUS_SATISFIED
    assert assessment.run_id == run_id
    assert assessment.run_state == state
    assert assessment.draft_digest == DIGEST


def test_a_failing_evaluation_blocks_and_names_what_failed(fake):
    _arm()
    _evaluate(
        fake,
        "fail",
        components=[
            {"component": "breaking", "counted": True, "state": "fail"},
            {"component": "sdk", "counted": False, "state": "fail"},
            {"component": "lint", "counted": True, "state": "pass"},
        ],
    )
    assessment = _assess()
    assert (assessment.status, assessment.reason) == (STATUS_BLOCKED, REASON_FAILED)
    # Only the required components that decided the verdict are named.
    assert assessment.failing_components == ("breaking",)
    assert "(breaking)" in assessment.message()


def test_a_pending_evaluation_blocks(fake):
    _arm(contract="required")
    _evaluate(fake, "pending", components=[{"component": "contract", "counted": True, "state": "pending"}])
    assessment = _assess()
    assert (assessment.status, assessment.reason) == (STATUS_BLOCKED, REASON_PENDING)
    assert "waiting on contract" in assessment.message()


def test_an_evaluation_of_an_earlier_edit_is_stale(fake):
    _arm()
    _evaluate(fake, "pass", digest="sha256:before-the-edit")
    assessment = _assess()
    assert (assessment.status, assessment.reason) == (STATUS_BLOCKED, REASON_STALE)


def test_an_evaluation_under_a_policy_that_has_since_moved_is_stale(fake):
    _arm()
    _evaluate(fake, "pass")
    _arm(contract="required")
    assert _assess().reason == REASON_STALE


def test_arming_the_gate_does_not_stale_evaluations_it_cannot_change(fake):
    # requiredForPublish decides whether publishing waits, never what the suite says.
    api_check_suite_policy_store.save_policy(TENANT, body={"components": {}})
    _evaluate(fake, "pass")
    _arm()
    assert _assess().status == STATUS_SATISFIED


def test_moving_the_deploy_gate_thresholds_also_makes_an_evaluation_stale(fake):
    _arm()
    _evaluate(fake, "pass")
    deploy_gate_store.save_policy(TENANT, body={"lint": {"failBelowGrade": "B"}})
    assert _assess().reason == REASON_STALE


def test_a_placeholder_never_satisfies_the_gate(fake):
    _arm()
    _evaluate(fake, "skipped", evaluated=False)
    assert _assess().reason == REASON_NOT_EVALUATED


def test_returning_to_content_that_passed_satisfies_it_again(fake):
    _arm()
    _evaluate(fake, "pass")
    _evaluate(fake, "fail", digest="sha256:an-edit")
    assert _assess().status == STATUS_SATISFIED
    assert _assess("sha256:an-edit").status == STATUS_BLOCKED


def test_the_gates_own_fault_never_blocks_a_publish(fake, monkeypatch):
    _arm()

    def broken(**_kwargs: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(fake, "find_current_check_suite_run", broken)
    assessment = _assess()
    assert assessment.status == STATUS_UNAVAILABLE
    assert assessment.blocked is False
    assert "db down" in (assessment.detail or "")


def test_the_payload_is_the_shape_the_422_and_the_audit_share(fake):
    _arm()
    run_id = _evaluate(fake, "pass")
    payload = _assess().as_payload()
    assert payload["status"] == STATUS_SATISFIED
    assert payload["blocked"] is False
    assert payload["runId"] == run_id
    assert payload["requiredForPublish"] is True
    assert payload["draftDigest"] == DIGEST
    assert payload["message"].startswith("The API change check suite passed")


# ---------------------------------------------------------------------------------------------
# The publish precheck step
# ---------------------------------------------------------------------------------------------


def test_a_blocked_gate_refuses_publish_with_the_shared_422_shape(fake, monkeypatch):
    _arm()
    monkeypatch.setattr(
        version_publish_prechecks,
        "assess_check_suite_gate",
        lambda **kwargs: _assess(),
    )
    with pytest.raises(HTTPException) as refused:
        version_publish_prechecks._with_check_suite_gate(
            PublishPrecheckOutcome(), tenant_id=TENANT, project_id=PROJECT, version={"id": VERSION}
        )
    assert refused.value.status_code == 422
    detail = refused.value.detail
    assert detail["apiCheckSuiteGate"]["reason"] == REASON_NOT_EVALUATED
    assert "apiome checks run" in detail["message"]
    assert "force-publish with a reason" in detail["message"]


def test_a_satisfied_gate_rides_on_the_outcome(fake, monkeypatch):
    _arm()
    _evaluate(fake, "pass")
    monkeypatch.setattr(
        version_publish_prechecks,
        "assess_check_suite_gate",
        lambda **kwargs: _assess(),
    )
    outcome = version_publish_prechecks._with_check_suite_gate(
        PublishPrecheckOutcome(), tenant_id=TENANT, project_id=PROJECT, version={"id": VERSION}
    )
    assert outcome.check_suite_gate["status"] == STATUS_SATISFIED


# ---------------------------------------------------------------------------------------------
# The publish audit
# ---------------------------------------------------------------------------------------------


class AuditDb:
    """Captures workflow-audit rows."""

    def __init__(self) -> None:
        self.rows: List[Any] = []

    def insert_workflow_audit(self, *args: Any) -> None:
        self.rows.append(args)


@pytest.fixture
def audit(monkeypatch) -> AuditDb:
    """The publish route's database, reduced to its audit write."""
    database = AuditDb()
    monkeypatch.setattr(versions_routes, "db", database)
    return database


def _audit_publish(payload: Optional[Dict[str, Any]], *, forced: bool = False) -> None:
    """Run the publish route's audit step."""
    versions_routes._audit_check_suite_gate(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_record_id=VERSION,
        existing={"id": VERSION},
        check_suite_gate=payload,
        forced=forced,
        force_reason="incident 42" if forced else None,
        actor_id=ALICE,
    )


def test_a_satisfied_publish_is_audited_with_the_evaluation_that_let_it_through(audit):
    _audit_publish({"status": STATUS_SATISFIED, "runId": "run-1"})
    (row,) = audit.rows
    assert row[3] == versions_routes.CHECK_SUITE_GATE_AUDIT_ACTION == "version.api_check_suite_gate"
    assert row[6]["action"] == STATUS_SATISFIED
    assert row[6]["apiCheckSuiteGate"]["runId"] == "run-1"


def test_a_publish_the_gate_does_not_govern_records_nothing(audit):
    _audit_publish({"status": STATUS_DISABLED})
    _audit_publish(None)
    assert audit.rows == []


def test_a_forced_publish_is_assessed_after_the_fact_and_audited_with_its_reason(
    audit, monkeypatch
):
    monkeypatch.setattr(
        versions_routes,
        "assess_check_suite_gate",
        lambda **kwargs: api_check_suite_gate.CheckSuiteGateAssessment(
            status=STATUS_BLOCKED, reason=REASON_FAILED, required_for_publish=True
        ),
    )
    _audit_publish(None, forced=True)
    (row,) = audit.rows
    assert row[6]["action"] == "forced"
    assert row[6]["reason"] == "incident 42"
    assert row[6]["apiCheckSuiteGate"]["reason"] == REASON_FAILED


def test_an_audit_fault_never_fails_a_completed_publish(monkeypatch):
    class Broken:
        def insert_workflow_audit(self, *args: Any) -> None:
            raise RuntimeError("audit down")

    monkeypatch.setattr(versions_routes, "db", Broken())
    _audit_publish({"status": STATUS_SATISFIED})
