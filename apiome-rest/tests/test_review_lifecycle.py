"""The review state machine — COL-2.1 (#4517).

:mod:`app.review_lifecycle` is pure, so the rules are pinned here without storage: how a round's
decisions fold into a state, exactly which transitions exist, and when a decision or a re-request
is allowed.
"""

from __future__ import annotations

import pytest

from app.review_lifecycle import (
    DECISIONS,
    RECORDABLE_DECISIONS,
    REVIEW_STATES,
    STATE_APPROVED,
    STATE_CHANGES_REQUESTED,
    STATE_DRAFT,
    STATE_IN_REVIEW,
    TRANSITIONS,
    VERSION_REVIEW_STATES,
    can_re_request,
    can_record_decision,
    is_allowed_transition,
    state_after_decisions,
    version_review_state,
)


@pytest.mark.parametrize(
    "decisions",
    [
        ["request_changes"],
        ["approve", "request_changes"],
        ["pending", "request_changes", "approve"],
        ["request_changes", "request_changes"],
    ],
)
def test_any_request_for_changes_decides_the_round(decisions):
    assert state_after_decisions(decisions) == STATE_CHANGES_REQUESTED


@pytest.mark.parametrize("decisions", [["approve"], ["approve", "approve", "approve"]])
def test_the_round_is_approved_only_when_every_reviewer_approved(decisions):
    assert state_after_decisions(decisions) == STATE_APPROVED


@pytest.mark.parametrize("decisions", [[], ["pending"], ["approve", "pending"], ["pending", "pending"]])
def test_an_undecided_round_stays_in_review(decisions):
    assert state_after_decisions(decisions) == STATE_IN_REVIEW


def test_decisions_can_be_any_iterable():
    assert state_after_decisions(decision for decision in ("approve", "approve")) == STATE_APPROVED


def test_transitions_are_the_issue_diagram_plus_the_stale_round_re_request():
    assert TRANSITIONS == {
        ("draft", "in_review"),
        ("in_review", "approved"),
        ("in_review", "changes_requested"),
        ("changes_requested", "in_review"),
        ("approved", "in_review"),
        # A spec change while a round is still open makes its approvals stale; only a re-request
        # can discard them.
        ("in_review", "in_review"),
    }


@pytest.mark.parametrize(
    "edge",
    [
        ("draft", "approved"),
        ("draft", "changes_requested"),
        ("approved", "changes_requested"),
        ("changes_requested", "approved"),
        ("approved", "draft"),
        ("in_review", "draft"),
    ],
)
def test_no_other_edge_exists(edge):
    assert not is_allowed_transition(*edge)


@pytest.mark.parametrize(
    "state, allowed",
    [(STATE_IN_REVIEW, True), (STATE_APPROVED, False), (STATE_CHANGES_REQUESTED, False), (STATE_DRAFT, False)],
)
def test_a_decision_is_recorded_only_while_in_review(state, allowed):
    assert can_record_decision(state) is allowed


@pytest.mark.parametrize(
    "state, allowed",
    [(STATE_IN_REVIEW, True), (STATE_APPROVED, True), (STATE_CHANGES_REQUESTED, True), (STATE_DRAFT, False)],
)
def test_every_stored_state_can_be_re_requested_but_a_draft_cannot(state, allowed):
    assert can_re_request(state) is allowed


def test_a_version_without_an_open_review_is_a_draft():
    assert version_review_state(None) == STATE_DRAFT
    assert version_review_state(STATE_APPROVED) == STATE_APPROVED


def test_vocabularies_are_consistent():
    assert STATE_DRAFT not in REVIEW_STATES
    assert VERSION_REVIEW_STATES == (STATE_DRAFT, *REVIEW_STATES)
    assert set(RECORDABLE_DECISIONS) == set(DECISIONS) - {"pending"}
    stored_edges = {edge for edge in TRANSITIONS if edge[0] != STATE_DRAFT}
    assert {state for edge in stored_edges for state in edge} == set(REVIEW_STATES)
