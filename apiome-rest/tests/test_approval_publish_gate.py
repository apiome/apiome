"""Approval policy, gate assessment, and the publish gate it drives (COL-2.3, #4519)."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.approval_policy import (
    DEFAULT_REQUIRED_APPROVALS,
    MAX_REQUIRED_APPROVALS,
    normalize_required_approvals,
    normalize_required_reviewer_role,
)
from app.approval_publish_gate import (
    REASON_CHANGES_REQUESTED,
    REASON_INSUFFICIENT_APPROVALS,
    REASON_MISSING_REQUIRED_ROLE,
    REASON_NO_REVIEW,
    REASON_SPEC_CHANGED,
    STATUS_BLOCKED,
    STATUS_DISABLED,
    STATUS_SATISFIED,
    STATUS_UNAVAILABLE,
    ApprovalPolicy,
    assess_approval_gate,
    resolve_approval_policy,
)
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_FINGERPRINT = "sha256:abc123"

_BASE_SPEC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {"summary": "List pets", "responses": {"200": {"description": "ok"}}}
        }
    },
    "components": {"schemas": {}},
}


def _head_row() -> Dict[str, Any]:
    """The draft revision the publish gate judges."""
    return {
        "id": "vid-1",
        "project_id": "pid-1",
        "creator_id": "user-a",
        "published": False,
        "version_id": "1.1.0",
        "description": None,
        "change_log": None,
    }


def _review_row(state: str = "approved", round_: int = 1) -> Dict[str, Any]:
    """An open review row as ``get_open_review_for_version`` returns it."""
    return {
        "id": "rev-1",
        "tenant_id": "t1",
        "project_id": "pid-1",
        "version_id": "vid-1",
        "state": state,
        "round": round_,
        "spec_fingerprint": _FINGERPRINT,
        "closed_at": None,
    }


def _reviewer(
    user_id: str, decision: str, *, round_: int = 1, name: Optional[str] = None
) -> Dict[str, Any]:
    """One reviewer row of a round."""
    return {
        "id": f"rr-{user_id}-{round_}",
        "review_id": "rev-1",
        "round": round_,
        "user_id": user_id,
        "user_name": name or user_id.title(),
        "decision": decision,
        "note": None,
    }


def _gate_db(
    *,
    review: Optional[Dict[str, Any]] = None,
    reviewers: Optional[List[Dict[str, Any]]] = None,
    roles: Optional[Dict[str, str]] = None,
) -> MagicMock:
    """A db double answering the three reads the gate makes."""
    shared = MagicMock()
    shared.get_open_review_for_version.return_value = review
    shared.list_review_reviewers.return_value = list(reviewers or [])
    shared.get_effective_role_slug.side_effect = lambda _tid, uid: (roles or {}).get(uid)
    return shared


def _assess(
    shared: MagicMock,
    *,
    policy: ApprovalPolicy,
    fingerprint: str = _FINGERPRINT,
):
    """Run an assessment with the gate's collaborators stubbed."""
    with patch("app.approval_publish_gate.db", shared):
        return assess_approval_gate(
            tenant_id="t1",
            project_id="pid-1",
            version=_head_row(),
            policy=policy,
            fingerprint_loader=lambda *_a, **_k: fingerprint,
        )


# ===========================================================================
# Policy vocabulary
# ===========================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [(0, 0), (1, 1), ("2", 2), (" 3 ", 3), (20, 20), (99, MAX_REQUIRED_APPROVALS)],
)
def test_normalize_required_approvals_accepts_and_clamps(raw, expected) -> None:
    assert normalize_required_approvals(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "two", -1, True, False, {"n": 2}, [1]])
def test_normalize_required_approvals_never_arms_the_gate_by_accident(raw) -> None:
    assert normalize_required_approvals(raw) == DEFAULT_REQUIRED_APPROVALS


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("release-manager", "release-manager"),
        (" Release-Manager ", "release-manager"),
        ("OWNER", "owner"),
        (b"admin", "admin"),
    ],
)
def test_normalize_required_reviewer_role_canonicalizes(raw, expected) -> None:
    assert normalize_required_reviewer_role(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", 7, True, "x" * 65, ["owner"]])
def test_normalize_required_reviewer_role_rejects_unusable_values(raw) -> None:
    assert normalize_required_reviewer_role(raw) is None


def test_policy_is_inactive_without_a_required_count() -> None:
    assert ApprovalPolicy().active is False
    # A role alone is not a satisfiable policy.
    assert ApprovalPolicy(required_reviewer_role="owner").active is False
    assert ApprovalPolicy(required_approvals=1).active is True


def test_resolve_policy_reads_the_assigned_guide() -> None:
    shared = MagicMock()
    shared.get_assigned_style_guide.return_value = {
        "id": "g1",
        "name": "Payments",
        "source": "custom",
        "required_approvals": 2,
        "required_reviewer_role": " Release-Manager ",
    }
    with patch("app.approval_publish_gate.db", shared):
        policy = resolve_approval_policy("t1", "pid-1")
    assert policy == ApprovalPolicy(
        required_approvals=2, required_reviewer_role="release-manager"
    )
    shared.get_assigned_style_guide.assert_called_once_with("t1", "pid-1")


def test_resolve_policy_degrades_to_off_when_no_guide_or_a_fault() -> None:
    shared = MagicMock()
    shared.get_assigned_style_guide.return_value = None
    with patch("app.approval_publish_gate.db", shared):
        assert resolve_approval_policy("t1").active is False

    shared.get_assigned_style_guide.side_effect = RuntimeError("no db")
    with patch("app.approval_publish_gate.db", shared):
        assert resolve_approval_policy("t1").active is False


# ===========================================================================
# Assessment
# ===========================================================================


def test_gate_is_disabled_when_no_approvals_are_required() -> None:
    shared = _gate_db()
    assessment = _assess(shared, policy=ApprovalPolicy())
    assert assessment.status == STATUS_DISABLED
    assert assessment.blocked is False
    # Nothing is read when the policy is off.
    shared.get_open_review_for_version.assert_not_called()


def test_gate_blocks_a_version_with_no_open_review() -> None:
    assessment = _assess(_gate_db(review=None), policy=ApprovalPolicy(required_approvals=1))
    assert assessment.status == STATUS_BLOCKED
    assert assessment.reason == REASON_NO_REVIEW
    assert "no open review" in assessment.message()


def test_gate_is_satisfied_when_the_round_carries_enough_approvals() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "approve")],
    )
    assessment = _assess(shared, policy=ApprovalPolicy(required_approvals=2))
    assert assessment.status == STATUS_SATISFIED
    assert assessment.blocked is False
    assert assessment.approvals == 2
    assert assessment.pending == 0
    assert [a["userId"] for a in assessment.approvers] == ["u1", "u2"]


def test_gate_blocks_when_the_round_is_short_of_approvals() -> None:
    shared = _gate_db(
        review=_review_row(state="in_review"),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "pending")],
    )
    assessment = _assess(shared, policy=ApprovalPolicy(required_approvals=2))
    assert assessment.status == STATUS_BLOCKED
    assert assessment.reason == REASON_INSUFFICIENT_APPROVALS
    assert assessment.approvals == 1
    assert assessment.pending == 1
    assert "1 of 2 required approval(s)" in assessment.message()


def test_gate_blocks_on_a_request_for_changes_even_with_enough_approvals() -> None:
    shared = _gate_db(
        review=_review_row(state="changes_requested"),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "request_changes")],
    )
    assessment = _assess(shared, policy=ApprovalPolicy(required_approvals=1))
    assert assessment.status == STATUS_BLOCKED
    assert assessment.reason == REASON_CHANGES_REQUESTED
    assert assessment.changes_requested == 1


def test_gate_treats_a_changed_spec_as_not_approved() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "approve")],
    )
    assessment = _assess(
        shared, policy=ApprovalPolicy(required_approvals=2), fingerprint="sha256:moved-on"
    )
    assert assessment.status == STATUS_BLOCKED
    assert assessment.reason == REASON_SPEC_CHANGED
    assert assessment.spec_changed is True
    assert "Re-request the review" in assessment.message()


def test_gate_only_counts_the_current_round() -> None:
    shared = _gate_db(
        review=_review_row(round_=2),
        reviewers=[
            _reviewer("u1", "approve", round_=1),
            _reviewer("u2", "approve", round_=1),
            _reviewer("u1", "approve", round_=2),
        ],
    )
    assessment = _assess(shared, policy=ApprovalPolicy(required_approvals=2))
    assert assessment.round == 2
    assert assessment.approvals == 1
    assert assessment.reason == REASON_INSUFFICIENT_APPROVALS


def test_gate_requires_an_approval_from_the_named_role() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "approve")],
        roles={"u1": "editor", "u2": "viewer"},
    )
    policy = ApprovalPolicy(required_approvals=2, required_reviewer_role="release-manager")
    assessment = _assess(shared, policy=policy)
    assert assessment.status == STATUS_BLOCKED
    assert assessment.reason == REASON_MISSING_REQUIRED_ROLE
    assert assessment.role_approvals == 0
    assert "'release-manager' role" in assessment.message()


def test_gate_passes_when_one_approver_holds_the_named_role() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "approve")],
        roles={"u1": "editor", "u2": "Release-Manager"},
    )
    policy = ApprovalPolicy(required_approvals=2, required_reviewer_role="release-manager")
    assessment = _assess(shared, policy=policy)
    assert assessment.status == STATUS_SATISFIED
    assert assessment.role_approvals == 1
    assert assessment.approvers[1]["roleSlug"] == "release-manager"


def test_gate_does_not_resolve_roles_when_none_is_required() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve")],
        roles={"u1": "owner"},
    )
    _assess(shared, policy=ApprovalPolicy(required_approvals=1))
    shared.get_effective_role_slug.assert_not_called()


def test_gate_degrades_to_unavailable_and_never_blocks_on_a_fault() -> None:
    shared = _gate_db(review=_review_row())
    shared.list_review_reviewers.side_effect = RuntimeError("connection reset")
    assessment = _assess(shared, policy=ApprovalPolicy(required_approvals=2))
    assert assessment.status == STATUS_UNAVAILABLE
    assert assessment.blocked is False
    assert assessment.detail == "connection reset"


def test_payload_is_camel_cased_and_self_describing() -> None:
    shared = _gate_db(
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve")],
    )
    payload = _assess(shared, policy=ApprovalPolicy(required_approvals=1)).as_payload()
    assert payload["status"] == STATUS_SATISFIED
    assert payload["blocked"] is False
    assert payload["requiredApprovals"] == 1
    assert payload["requiredReviewerRole"] is None
    assert payload["approvals"] == 1
    assert payload["reviewId"] == "rev-1"
    assert payload["specChanged"] is False
    assert payload["policy"] == {"requiredApprovals": 1, "requiredReviewerRole": None}
    assert payload["message"]


# ===========================================================================
# Publish gate
# ===========================================================================


_PUBLISHED_ROW: Dict[str, Any] = {
    "id": "vid-1",
    "project_id": "pid-1",
    "version_id": "1.1.0",
    "published": True,
    "creator_id": "user-a",
    "visibility": "private",
    "description": "Ship it",
    "change_log": None,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _publish_db(
    *,
    required_approvals: int,
    required_reviewer_role: Optional[str] = None,
    review: Optional[Dict[str, Any]] = None,
    reviewers: Optional[List[Dict[str, Any]]] = None,
    roles: Optional[Dict[str, str]] = None,
) -> MagicMock:
    """A db double wired for the publish route: clean prechecks, one configurable policy."""
    shared = MagicMock()
    shared.get_version_by_id.side_effect = lambda vid, _tid: (
        _head_row() if str(vid) == "vid-1" else None
    )
    shared.get_classes_for_version.return_value = [{"name": "Pet", "description": "Animal"}]
    shared.get_project_by_id.return_value = {"id": "pid-1", "slug": "pay", "metadata": {}}
    shared.get_prior_published_baseline_revision_id.return_value = None
    shared.get_assigned_style_guide.return_value = {
        "id": "g1",
        "name": "Payments",
        "source": "custom",
        "breaking_publish_policy": "off",
        "required_approvals": required_approvals,
        "required_reviewer_role": required_reviewer_role,
    }
    shared.get_open_review_for_version.return_value = review
    shared.list_review_reviewers.return_value = list(reviewers or [])
    shared.get_effective_role_slug.side_effect = lambda _tid, uid: (roles or {}).get(uid)
    shared.publish_version.return_value = dict(_PUBLISHED_ROW)
    return shared


def _publish(shared: MagicMock, body: Dict[str, Any]):
    """POST the publish endpoint with the approval gate's collaborators stubbed."""
    with patch("app.versions_routes.db", shared), patch(
        "app.version_publish_prechecks.db", shared
    ), patch("app.approval_publish_gate.db", shared), patch(
        "app.breaking_publish_guardrail.db", shared
    ), patch(
        "app.publication_change_report.db", shared
    ), patch(
        "app.version_publish_prechecks.openapi_for_revision",
        return_value=copy.deepcopy(_BASE_SPEC),
    ), patch(
        "app.review_store.spec_fingerprint", return_value=_FINGERPRINT
    ), patch(
        "app.version_publish_prechecks.CompatibilityCheckEngine.run"
    ) as compat_run, patch(
        "app.version_publish_prechecks.evaluate_and_record",
        side_effect=RuntimeError("policy not configured"),
    ):
        compat_run.return_value.overall = "non-breaking"
        return client.post("/v1/versions/acme/pid-1/vid-1/publish", json=body)


def _approval_audits(shared: MagicMock) -> list:
    """Every ``version.approval_policy_gate`` audit write recorded on the double."""
    return [
        call.args
        for call in shared.insert_workflow_audit.call_args_list
        if len(call.args) > 3 and call.args[3] == "version.approval_policy_gate"
    ]


def test_publish_is_blocked_when_the_required_approvals_are_missing() -> None:
    shared = _publish_db(
        required_approvals=2,
        review=_review_row(state="in_review"),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "pending")],
    )
    res = _publish(shared, {"shortMessage": "Ship it"})

    assert res.status_code == 422
    detail = res.json()["detail"]
    gate = detail["approvalGate"]
    assert gate["status"] == "blocked"
    assert gate["blocked"] is True
    assert gate["reason"] == REASON_INSUFFICIENT_APPROVALS
    assert gate["approvals"] == 1
    assert gate["requiredApprovals"] == 2
    assert "force-publish with a reason" in detail["message"]
    shared.publish_version.assert_not_called()
    assert _approval_audits(shared) == []


def test_publish_is_blocked_when_no_approver_holds_the_required_role() -> None:
    shared = _publish_db(
        required_approvals=1,
        required_reviewer_role="release-manager",
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve")],
        roles={"u1": "editor"},
    )
    res = _publish(shared, {"shortMessage": "Ship it"})

    assert res.status_code == 422
    gate = res.json()["detail"]["approvalGate"]
    assert gate["reason"] == REASON_MISSING_REQUIRED_ROLE
    assert gate["roleApprovals"] == 0
    shared.publish_version.assert_not_called()


def test_publish_proceeds_and_audits_when_the_policy_is_met() -> None:
    shared = _publish_db(
        required_approvals=1,
        required_reviewer_role="release-manager",
        review=_review_row(),
        reviewers=[_reviewer("u1", "approve")],
        roles={"u1": "release-manager"},
    )
    res = _publish(shared, {"shortMessage": "Ship it"})

    assert res.status_code == 200
    shared.publish_version.assert_called_once()
    audits = _approval_audits(shared)
    assert len(audits) == 1
    detail = audits[0][6]
    assert detail["action"] == "satisfied"
    assert detail["reason"] is None
    assert detail["approvalGate"]["approvals"] == 1
    assert detail["approvalGate"]["roleApprovals"] == 1


def test_force_publish_gets_past_the_gate_and_is_audited_with_its_reason() -> None:
    shared = _publish_db(
        required_approvals=2,
        review=_review_row(state="in_review"),
        reviewers=[_reviewer("u1", "approve"), _reviewer("u2", "pending")],
    )
    res = _publish(
        shared,
        {
            "shortMessage": "Emergency fix",
            "skipPublishChecks": True,
            "forcePublishReason": "Incident 4519 — approver unavailable, CAB approved out of band",
        },
    )

    assert res.status_code == 200
    shared.publish_version.assert_called_once()
    audits = _approval_audits(shared)
    assert len(audits) == 1
    detail = audits[0][6]
    assert detail["action"] == "forced"
    assert detail["reason"].startswith("Incident 4519")
    assert detail["approvalGate"]["blocked"] is True
    assert detail["approvalGate"]["reason"] == REASON_INSUFFICIENT_APPROVALS


def test_force_publish_still_requires_a_reason() -> None:
    shared = _publish_db(required_approvals=2)
    res = _publish(shared, {"shortMessage": "Ship it", "skipPublishChecks": True})
    assert res.status_code == 422
    shared.publish_version.assert_not_called()


def test_publish_without_an_approval_policy_records_nothing() -> None:
    shared = _publish_db(required_approvals=0)
    res = _publish(shared, {"shortMessage": "Docs only"})

    assert res.status_code == 200
    assert _approval_audits(shared) == []
    shared.get_open_review_for_version.assert_not_called()
