"""Merge readiness rules — COL-4.3 (#4527).

``merge_request_store.readiness`` decides whether a merge request can merge and lists every
reason it cannot. These pin each rule in isolation; the approval gate is stubbed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import merge_request_store as store
from app.approval_publish_gate import ApprovalGateAssessment, ApprovalPolicy
from app.merge_requests import MergeConflict, MergeRequestRecord
from app.reviews import ReviewDetail, ReviewRecord

NOW = datetime.now(timezone.utc)
TIP = {"id": "v-tip", "published": False}
LINE = {"id": "v-line", "published": False}


def _mr(**over) -> MergeRequestRecord:
    data = dict(
        id="mr-1",
        tenant_id="t-1",
        project_id="p-1",
        title="Add pet tags",
        state="open",
        source_branch_id="b-src",
        source_branch_name="feature/tags",
        target_branch_id="b-main",
        target_branch_name="main",
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(over)
    return MergeRequestRecord(**data)


def _review(state="approved", version_id="v-tip", spec_changed=False, closed=False, pending=0) -> ReviewDetail:
    return ReviewDetail(
        review=ReviewRecord(
            id="r-1",
            tenant_id="t-1",
            project_id="p-1",
            version_id=version_id,
            state=state,
            round=1,
            spec_fingerprint="sha256:x",
            reviewer_count=1,
            pending_count=pending,
            closed_at=NOW if closed else None,
            created_at=NOW,
            updated_at=NOW,
        ),
        spec_changed=None if closed else spec_changed,
    )


@pytest.fixture
def gate(monkeypatch):
    """The approval gate's verdict; disabled unless a test arms it."""
    state = {"assessment": ApprovalGateAssessment(status="disabled")}
    monkeypatch.setattr(store, "assess_approval_gate", lambda **kw: state["assessment"])
    return state


def _codes(review, *, target=LINE, conflicts=(), record=None) -> list:
    ready = store.readiness(
        tenant_id="t-1",
        project_id="p-1",
        record=record or _mr(),
        review=review,
        source_tip=TIP,
        target_tip=target,
        conflicts=list(conflicts),
    )
    assert ready.can_merge == (not ready.blockers and (record or _mr()).state == "open")
    return [b.code for b in ready.blockers]


def test_an_approved_current_review_can_merge(gate):
    assert _codes(_review()) == []


def test_no_review_or_a_withdrawn_one_blocks(gate):
    assert _codes(None) == ["no-review"]
    assert _codes(_review(closed=True)) == ["no-review"]


def test_a_review_of_an_older_tip_is_outdated(gate):
    assert _codes(_review(version_id="v-older")) == ["review-outdated"]


def test_pending_changes_requested_and_stale_rounds_block(gate):
    assert _codes(_review(state="in_review", pending=2)) == ["review-pending"]
    assert _codes(_review(state="changes_requested")) == ["changes-requested"]
    assert _codes(_review(spec_changed=True)) == ["review-stale"]


def test_the_approval_policy_blocks_an_otherwise_approved_review(gate):
    gate["assessment"] = ApprovalGateAssessment(
        policy=ApprovalPolicy(required_approvals=2), status="blocked", reason="insufficient_approvals", approvals=1
    )
    ready = store.readiness(
        tenant_id="t-1", project_id="p-1", record=_mr(), review=_review(), source_tip=TIP, target_tip=LINE, conflicts=[]
    )
    assert [b.code for b in ready.blockers] == ["approval-policy"]
    assert ready.approval and ready.approval["requiredApprovals"] == 2


def test_conflicts_and_an_immutable_line_are_reported(gate):
    codes = _codes(
        _review(),
        target={"id": "v-line", "published": True, "published_immutable": True},
        conflicts=[MergeConflict(path="components.schemas.Pet", kinds=["threeWay"])],
    )
    assert codes == ["conflicts", "target-immutable"]


def test_a_closed_request_never_merges(gate):
    ready = store.readiness(
        tenant_id="t-1",
        project_id="p-1",
        record=_mr(state="closed", closed_at=NOW),
        review=_review(),
        source_tip=TIP,
        target_tip=LINE,
        conflicts=[],
    )
    assert ready.can_merge is False
