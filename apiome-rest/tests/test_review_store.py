"""Store rules for reviews that the HTTP tests do not isolate — COL-2.1 (#4517).

The spec fingerprint, reviewer-list normalisation, attribution, and — through the fake's
``interleave`` hook — what each write reports when a concurrent writer wins the race between the
store's read and its guarded write.
"""

from __future__ import annotations

import pytest

from app import comment_store, notification_store, review_store
from app.reviews import (
    CODE_ALREADY_DECIDED,
    CODE_ALREADY_OPEN,
    CODE_CLOSED,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_INVALID_REVIEWERS,
    CODE_NOT_IN_REVIEW,
    ReviewDecisionCreate,
    ReviewRequestCreate,
    ReviewReRequest,
    ReviewValidationError,
)
from tests.fake_review_db import FakeReviewDb

TENANT = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40001"
PROJECT = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40002"
VERSION = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40010"
ALICE = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40101"
BOB = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40102"
DAVE = "3e9a1f20-6b7c-4d8e-8f90-a1b2c3d40103"


@pytest.fixture
def fake(monkeypatch) -> FakeReviewDb:
    """A seeded store beneath :mod:`app.review_store`."""
    store = FakeReviewDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    for user_id, name in ((ALICE, "Alice"), (BOB, "Bob"), (DAVE, "Dave")):
        store.add_member(user_id, name, f"{name.lower()}@example.com")
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(review_store, "db", store)
    monkeypatch.setattr(notification_store, "db", store)
    monkeypatch.setattr(review_store, "spec_fingerprint", store.spec_fingerprint)
    return store


def _request(fake: FakeReviewDb) -> str:
    """Request a review of the version from Bob and Dave; return its id."""
    detail = review_store.request_review(
        TENANT, "pets", ReviewRequestCreate(version="1.0.0", reviewers=[BOB, DAVE]), ALICE
    )
    return detail.review.id


def _code_of(call) -> str:
    """Run a store call that must refuse, and return the refusal code."""
    with pytest.raises(ReviewValidationError) as refused:
        call()
    return refused.value.code


# ---------------------------------------------------------------------------------------------
# Fingerprint and reviewers
# ---------------------------------------------------------------------------------------------


def test_the_fingerprint_follows_the_rebuilt_document_not_the_callers_url(monkeypatch):
    documents = {
        "v1": {"openapi": "3.1.0", "info": {"title": "pets API", "version": "1.0.0"}, "paths": {}},
        "v1-reordered": {"paths": {}, "info": {"version": "1.0.0", "title": "pets API"}, "openapi": "3.1.0"},
        "v2": {"openapi": "3.1.0", "info": {"title": "pets API", "version": "1.0.0"}, "paths": {"/pets": {}}},
    }
    calls = []

    def rebuild(version, tenant_slug, tenant_id):
        calls.append((tenant_slug, tenant_id))
        return documents[version["id"]]

    monkeypatch.setattr(review_store, "openapi_for_revision", rebuild)
    first = review_store.spec_fingerprint(TENANT, {"id": "v1"})
    assert first.startswith("sha256:")
    assert review_store.spec_fingerprint(TENANT, {"id": "v1-reordered"}) == first
    assert review_store.spec_fingerprint(TENANT, {"id": "v2"}) != first
    assert {slug for slug, _tenant in calls} == {"tenant"}


def test_reviewers_are_canonical_de_duplicated_and_kept_in_order(fake):
    assert review_store.validate_reviewers(TENANT, [DAVE.upper(), BOB, f" {DAVE} "], ALICE) == [DAVE, BOB]


def test_an_unknown_requester_skips_only_the_self_review_check(fake):
    assert review_store.validate_reviewers(TENANT, [ALICE], None) == [ALICE]


def test_the_reviewer_bound_holds_without_the_http_model(fake):
    ids = [f"3e9a1f20-6b7c-4d8e-8f90-a1b2c3d4{index:04d}" for index in range(21)]
    assert _code_of(lambda: review_store.validate_reviewers(TENANT, ids, ALICE)) == CODE_INVALID_REVIEWERS
    assert _code_of(lambda: review_store.validate_reviewers(TENANT, [], ALICE)) == CODE_INVALID_REVIEWERS


def test_an_unattributable_actor_cannot_request(fake):
    request = ReviewRequestCreate(version="1.0.0", reviewers=[BOB])
    assert _code_of(lambda: review_store.request_review(TENANT, "pets", request, "api-key")) == CODE_FORBIDDEN
    assert fake.reviews == {}


def test_a_blank_note_is_stored_as_no_note(fake):
    review_id = _request(fake)
    detail = review_store.record_decision(
        TENANT, "pets", review_id, ReviewDecisionCreate(decision="approve", note="   "), BOB
    )
    assert detail.reviewers[0].note is None
    assert fake.workflow_audits[-1]["detail"]["has_note"] is False


def test_a_withdrawn_review_reads_without_rebuilding_the_spec(fake):
    review_id = _request(fake)
    review_store.withdraw_review(TENANT, "pets", review_id, ALICE)
    reads = fake.fingerprint_reads
    detail = review_store.get_review(TENANT, "pets", review_id)
    assert detail.spec_changed is None
    assert fake.fingerprint_reads == reads


def test_a_request_rebuilds_the_spec_once(fake):
    reads = fake.fingerprint_reads
    _request(fake)
    assert fake.fingerprint_reads == reads + 1


def test_a_deleted_reviewer_is_not_carried_into_the_next_round(fake):
    review_id = _request(fake)
    for row in fake.reviewer_rows.values():
        if row["user_id"] == BOB:
            row["user_id"] = None  # ON DELETE SET NULL
    fake.change_spec(VERSION)
    detail = review_store.re_request_review(TENANT, "pets", review_id, ReviewReRequest(), ALICE)
    assert [row.user_id for row in detail.reviewers] == [DAVE]
    assert [row.user_id for row in detail.history] == [DAVE, None]


# ---------------------------------------------------------------------------------------------
# Lost races
# ---------------------------------------------------------------------------------------------


def test_a_request_that_loses_to_another_request_is_already_open(fake):
    fake.interleave = lambda: fake.insert_review(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        requested_by=DAVE,
        reviewer_ids=[BOB],
        spec_fingerprint="sha256:other",
    )
    assert _code_of(lambda: _request(fake)) == CODE_ALREADY_OPEN
    assert len(fake.reviews) == 1


def test_a_decision_that_loses_to_a_request_for_changes_is_not_in_review(fake):
    review_id = _request(fake)
    fake.interleave = lambda: fake.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=review_id,
        expected_round=1,
        user_id=DAVE,
        decision="request_changes",
        note=None,
    )
    decision = ReviewDecisionCreate(decision="approve")
    assert _code_of(lambda: review_store.record_decision(TENANT, "pets", review_id, decision, BOB)) == (
        CODE_NOT_IN_REVIEW
    )
    assert fake.reviews[review_id]["state"] == "changes_requested"


def test_a_decision_that_loses_to_a_re_request_is_not_in_review(fake):
    review_id = _request(fake)
    fake.interleave = lambda: fake.re_request_review(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=review_id,
        expected_round=1,
        reviewer_ids=[BOB, DAVE],
        spec_fingerprint="sha256:next",
        actor_id=ALICE,
    )
    decision = ReviewDecisionCreate(decision="approve")
    assert _code_of(lambda: review_store.record_decision(TENANT, "pets", review_id, decision, BOB)) == (
        CODE_NOT_IN_REVIEW
    )


def test_a_decision_that_loses_to_its_own_duplicate_is_already_decided(fake):
    review_id = _request(fake)
    fake.interleave = lambda: fake.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=review_id,
        expected_round=1,
        user_id=BOB,
        decision="approve",
        note=None,
    )
    decision = ReviewDecisionCreate(decision="request_changes")
    assert _code_of(lambda: review_store.record_decision(TENANT, "pets", review_id, decision, BOB)) == (
        CODE_ALREADY_DECIDED
    )
    assert [row["decision"] for row in fake.reviewer_rows.values() if row["user_id"] == BOB] == ["approve"]


def test_a_decision_that_loses_to_a_withdrawal_is_closed(fake):
    review_id = _request(fake)
    fake.interleave = lambda: fake.withdraw_review(
        tenant_id=TENANT, project_id=PROJECT, review_id=review_id, actor_id=ALICE
    )
    decision = ReviewDecisionCreate(decision="approve")
    assert _code_of(lambda: review_store.record_decision(TENANT, "pets", review_id, decision, BOB)) == CODE_CLOSED


def test_a_re_request_that_loses_to_another_re_request_conflicts(fake):
    review_id = _request(fake)
    fake.change_spec(VERSION)
    fake.interleave = lambda: fake.re_request_review(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=review_id,
        expected_round=1,
        reviewer_ids=[DAVE],
        spec_fingerprint="sha256:theirs",
        actor_id=ALICE,
    )
    call = lambda: review_store.re_request_review(TENANT, "pets", review_id, ReviewReRequest(), ALICE)  # noqa: E731
    assert _code_of(call) == CODE_CONFLICT
    assert fake.reviews[review_id]["round"] == 2


def test_a_re_request_that_loses_to_a_withdrawal_is_closed(fake):
    review_id = _request(fake)
    fake.change_spec(VERSION)
    fake.interleave = lambda: fake.withdraw_review(
        tenant_id=TENANT, project_id=PROJECT, review_id=review_id, actor_id=ALICE
    )
    call = lambda: review_store.re_request_review(TENANT, "pets", review_id, ReviewReRequest(), ALICE)  # noqa: E731
    assert _code_of(call) == CODE_CLOSED


def test_a_withdrawal_that_loses_to_another_is_closed(fake):
    review_id = _request(fake)
    fake.interleave = lambda: fake.withdraw_review(
        tenant_id=TENANT, project_id=PROJECT, review_id=review_id, actor_id=ALICE
    )
    assert _code_of(lambda: review_store.withdraw_review(TENANT, "pets", review_id, ALICE)) == CODE_CLOSED
    assert [row["action"] for row in fake.workflow_audits].count("review.withdrawn") == 1
