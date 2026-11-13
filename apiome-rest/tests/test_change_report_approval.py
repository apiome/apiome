"""Unit tests for the change-report approval rules (#2705, CR-V2-01) — no database, no HTTP."""

import pytest

from app.change_report_approval import (
    APPROVAL_STATES,
    STATE_APPROVED,
    STATE_DRAFT,
    STATE_PENDING_REVIEW,
    TRANSITION_APPROVE,
    TRANSITION_REJECT,
    TRANSITION_SUBMIT,
    check_transition,
    normalize_review_note,
    normalize_state,
    pdf_export_refusal,
    target_state,
)


def _check(transition, state, *, actor="u1", admin=False, can_edit=False, submitted_by=None):
    return check_transition(
        transition,
        current_state=state,
        actor_id=actor,
        actor_is_tenant_admin=admin,
        actor_can_edit_report=can_edit,
        submitted_by=submitted_by,
    )


def test_states_are_listed_in_the_order_a_report_moves_through_them():
    assert APPROVAL_STATES == ("draft", "pending_review", "approved")


@pytest.mark.parametrize("raw", [None, "", "published", "APPROVED"])
def test_a_missing_or_unknown_state_reads_as_draft(raw):
    assert normalize_state(raw) == STATE_DRAFT


def test_known_states_are_kept():
    for state in APPROVAL_STATES:
        assert normalize_state(state) == state


def test_each_transition_names_its_target_state():
    assert target_state(TRANSITION_SUBMIT) == STATE_PENDING_REVIEW
    assert target_state(TRANSITION_APPROVE) == STATE_APPROVED
    assert target_state(TRANSITION_REJECT) == STATE_DRAFT


class TestSubmit:
    def test_an_editor_submits_a_draft(self):
        assert _check(TRANSITION_SUBMIT, STATE_DRAFT, can_edit=True) is None

    def test_someone_who_cannot_edit_is_refused_403(self):
        refusal = _check(TRANSITION_SUBMIT, STATE_DRAFT)
        assert refusal.status_code == 403
        assert "version creator or a tenant administrator" in refusal.detail

    @pytest.mark.parametrize("state", [STATE_PENDING_REVIEW, STATE_APPROVED])
    def test_only_a_draft_can_be_submitted(self, state):
        refusal = _check(TRANSITION_SUBMIT, state, can_edit=True)
        assert refusal.status_code == 409
        assert f"'{state}'" in refusal.detail and "'draft'" in refusal.detail

    def test_a_row_with_no_state_is_a_draft(self):
        assert _check(TRANSITION_SUBMIT, None, can_edit=True) is None


class TestApprove:
    def test_an_admin_approves_someone_elses_submission(self):
        assert (
            _check(TRANSITION_APPROVE, STATE_PENDING_REVIEW, admin=True, submitted_by="u2")
            is None
        )

    def test_the_submitter_cannot_approve_their_own_report(self):
        refusal = _check(
            TRANSITION_APPROVE, STATE_PENDING_REVIEW, admin=True, submitted_by="u1"
        )
        assert refusal.status_code == 403
        assert "someone other than its submitter" in refusal.detail

    def test_a_non_admin_is_refused_even_if_they_can_edit(self):
        refusal = _check(
            TRANSITION_APPROVE, STATE_PENDING_REVIEW, can_edit=True, submitted_by="u2"
        )
        assert refusal.status_code == 403
        assert "tenant administrator" in refusal.detail

    @pytest.mark.parametrize("state", [STATE_DRAFT, STATE_APPROVED])
    def test_only_a_pending_report_can_be_approved(self, state):
        refusal = _check(TRANSITION_APPROVE, state, admin=True, submitted_by="u2")
        assert refusal.status_code == 409

    def test_who_is_checked_before_what_state(self):
        """A caller who may not approve learns nothing about the report's state."""
        refusal = _check(TRANSITION_APPROVE, STATE_DRAFT)
        assert refusal.status_code == 403

    def test_a_report_with_no_recorded_submitter_can_be_approved(self):
        assert _check(TRANSITION_APPROVE, STATE_PENDING_REVIEW, admin=True) is None


class TestReject:
    def test_an_admin_rejects_a_pending_report(self):
        assert (
            _check(TRANSITION_REJECT, STATE_PENDING_REVIEW, admin=True, submitted_by="u2")
            is None
        )

    def test_the_submitter_may_withdraw_their_own_submission(self):
        assert (
            _check(TRANSITION_REJECT, STATE_PENDING_REVIEW, admin=True, submitted_by="u1")
            is None
        )

    def test_a_non_admin_is_refused(self):
        assert _check(TRANSITION_REJECT, STATE_PENDING_REVIEW, can_edit=True).status_code == 403

    @pytest.mark.parametrize("state", [STATE_DRAFT, STATE_APPROVED])
    def test_only_a_pending_report_can_be_rejected(self, state):
        assert _check(TRANSITION_REJECT, state, admin=True).status_code == 409


def test_an_unknown_transition_is_a_400():
    assert _check("publish", STATE_DRAFT, admin=True, can_edit=True).status_code == 400


class TestPdfExport:
    def test_an_approved_report_can_be_exported(self):
        assert pdf_export_refusal(STATE_APPROVED) is None

    @pytest.mark.parametrize("state", [STATE_DRAFT, STATE_PENDING_REVIEW, None])
    def test_anything_else_is_a_409_naming_the_state(self, state):
        refusal = pdf_export_refusal(state)
        assert refusal.status_code == 409
        assert normalize_state(state) in refusal.detail


def test_review_note_is_trimmed_and_blank_is_none():
    assert normalize_review_note("  Looks right.  ") == "Looks right."
    assert normalize_review_note("   ") is None
    assert normalize_review_note(None) is None
