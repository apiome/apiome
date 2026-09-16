"""The five source events, and the inbox rows they write — COL-3.1 (#4521).

The ticket's first acceptance criterion is that *each* source event produces the right per-user
rows, in the same transaction as the event. The "same transaction" half is pinned by
``tests/test_notification_database_accessors.py``, which drives the real SQL accessors against a
scripted connection. This file pins the other half — *which* rows — by driving the real comment and
review stores over the in-memory double, so the rules under test are the ones that ship:

* a mention notifies the members it names, never their author, and an edit notifies only the
  members it newly names;
* resolving a thread notifies the people who were in it; reopening notifies nobody;
* a review request (and every re-request) notifies that round's reviewers, and a decision notifies
  the member who asked for the review;
* a publish notifies the version's collaborators, resolved from its reviews and its threads;
* a write that did not happen — a no-op resolve, a refused decision — notifies nobody;
* the retention cap keeps an inbox bounded.
"""

from __future__ import annotations

import pytest

from app import comment_store, notification_store, review_store
from app.comments import CommentThreadCreate
from app.notifications import (
    RETENTION_PER_USER,
    TYPE_MENTION,
    TYPE_REVIEW_DECISION,
    TYPE_REVIEW_REQUESTED,
    TYPE_THREAD_RESOLVED,
    TYPE_VERSION_PUBLISHED,
)
from app.reviews import ReviewDecisionCreate, ReviewRequestCreate, ReviewReRequest, ReviewValidationError
from tests.fake_review_db import FakeReviewDb

TENANT = "7d4e6f80-0000-4000-8000-00000000a001"
PROJECT = "7d4e6f80-0000-4000-8000-00000000b001"
VERSION = "7d4e6f80-0000-4000-8000-00000000c001"
CLASS_ID = "7d4e6f80-0000-4000-8000-00000000d001"
ALICE = "7d4e6f80-0000-4000-8000-00000000e001"
BOB = "7d4e6f80-0000-4000-8000-00000000e002"
CARA = "7d4e6f80-0000-4000-8000-00000000e003"


@pytest.fixture
def fake(monkeypatch) -> FakeReviewDb:
    """A seeded store beneath the comment, review, and notification stores."""
    store = FakeReviewDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_anchor(VERSION, "class", CLASS_ID)
    for user_id, name in ((ALICE, "Alice"), (BOB, "Bob"), (CARA, "Cara")):
        store.add_member(user_id, name, f"{name.lower()}@example.com")
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(review_store, "db", store)
    monkeypatch.setattr(notification_store, "db", store)
    monkeypatch.setattr(review_store, "spec_fingerprint", store.spec_fingerprint)
    return store


def _open_thread(body: str = "Hello", actor: str = ALICE) -> str:
    """Open a thread on the class, and return its id."""
    request = CommentThreadCreate(version="1.0.0", anchor_type="class", anchor_id=CLASS_ID, body=body)
    return comment_store.create_thread(TENANT, "pets", request, actor).thread.id


def _request_review(fake: FakeReviewDb, reviewers=(BOB, CARA), actor: str = ALICE) -> str:
    """Request a review of the version, and return its id."""
    request = ReviewRequestCreate(version="1.0.0", reviewers=list(reviewers))
    return review_store.request_review(TENANT, "pets", request, actor).review.id


# ---------------------------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------------------------


def test_opening_a_thread_that_names_somebody_reaches_their_inbox(fake):
    thread_id = _open_thread("@bob does this need a format?")
    row = fake.inbox(BOB)[0]
    assert row["type"] == TYPE_MENTION
    assert row["actor_id"] == ALICE
    assert row["project_id"] == PROJECT and row["version_id"] == VERSION
    assert row["payload"]["thread_id"] == thread_id
    assert row["payload"]["anchor_type"] == "class"
    assert row["payload"]["anchor_id"] == CLASS_ID
    assert row["payload"]["version_label"] == "1.0.0"
    assert row["payload"]["project_slug"] == "pets"
    assert row["payload"]["excerpt"] == "@bob does this need a format?"
    assert row["read_at"] is None


def test_a_comment_that_names_nobody_writes_no_rows(fake):
    _open_thread("just thinking out loud")
    assert fake.notifications == []


def test_naming_yourself_writes_no_rows(fake):
    _open_thread("note to self, says @alice")
    assert fake.notifications == []


def test_a_reply_that_names_somebody_reaches_them(fake):
    thread_id = _open_thread()
    comment = comment_store.add_comment(TENANT, "pets", thread_id, "cc @cara", ALICE)
    row = fake.inbox(CARA)[0]
    assert row["type"] == TYPE_MENTION
    assert row["payload"]["comment_id"] == comment.id


def test_an_edit_reaches_only_the_member_it_newly_names(fake):
    thread_id = _open_thread("@bob take a look")
    comment_id = comment_store.get_thread(TENANT, "pets", thread_id).comments[0].id
    comment_store.edit_comment(TENANT, "pets", thread_id, comment_id, "@bob @cara take a look", ALICE)
    assert len(fake.inbox(BOB)) == 1
    assert len(fake.inbox(CARA)) == 1


def test_a_recipient_whose_account_is_gone_is_skipped(fake):
    fake.deleted_users.add(BOB)
    _open_thread("@bob are you there?")
    assert fake.notifications == []


# ---------------------------------------------------------------------------------------------
# Thread resolution
# ---------------------------------------------------------------------------------------------


def test_resolving_a_thread_tells_the_people_who_were_in_it(fake):
    thread_id = _open_thread("what about nulls?", actor=ALICE)
    comment_store.add_comment(TENANT, "pets", thread_id, "good question", BOB)
    fake.notifications.clear()

    comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", CARA)

    assert [row["user_id"] for row in fake.notifications] == [ALICE, BOB]
    row = fake.inbox(ALICE)[0]
    assert row["type"] == TYPE_THREAD_RESOLVED
    assert row["actor_id"] == CARA
    assert row["payload"]["thread_id"] == thread_id
    assert "excerpt" not in row["payload"]


def test_resolving_your_own_thread_tells_nobody(fake):
    thread_id = _open_thread(actor=ALICE)
    comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", ALICE)
    assert fake.notifications == []


def test_reopening_a_thread_tells_nobody(fake):
    thread_id = _open_thread(actor=ALICE)
    comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", BOB)
    fake.notifications.clear()
    comment_store.set_thread_status(TENANT, "pets", thread_id, "open", BOB)
    assert fake.notifications == []


def test_resolving_a_thread_that_is_already_resolved_tells_nobody_again(fake):
    thread_id = _open_thread(actor=ALICE)
    comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", BOB)
    fake.notifications.clear()
    comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", BOB)
    assert fake.notifications == []


def test_resolving_an_orphaned_thread_tells_nobody(fake):
    thread_id = _open_thread(actor=ALICE)
    fake.delete_element("class", CLASS_ID, "Customer")
    with pytest.raises(Exception):
        comment_store.set_thread_status(TENANT, "pets", thread_id, "resolved", BOB)
    assert fake.notifications == []


# ---------------------------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------------------------


def test_requesting_a_review_reaches_its_reviewers(fake):
    review_id = _request_review(fake)
    assert sorted(row["user_id"] for row in fake.notifications) == sorted([BOB, CARA])
    row = fake.inbox(BOB)[0]
    assert row["type"] == TYPE_REVIEW_REQUESTED
    assert row["actor_id"] == ALICE
    assert row["payload"]["review_id"] == review_id
    assert row["payload"]["round"] == 1
    assert row["payload"]["version_label"] == "1.0.0"


def test_a_re_request_asks_the_new_round_again(fake):
    review_id = _request_review(fake)
    fake.notifications.clear()
    fake.change_spec(VERSION)
    review_store.re_request_review(TENANT, "pets", review_id, ReviewReRequest(reviewers=[BOB]), ALICE)
    assert [row["user_id"] for row in fake.notifications] == [BOB]
    assert fake.inbox(BOB)[0]["payload"]["round"] == 2


def test_a_decision_reaches_the_member_who_asked_for_the_review(fake):
    review_id = _request_review(fake)
    fake.notifications.clear()
    review_store.record_decision(
        TENANT, "pets", review_id, ReviewDecisionCreate(decision="request_changes"), BOB
    )
    assert [row["user_id"] for row in fake.notifications] == [ALICE]
    row = fake.inbox(ALICE)[0]
    assert row["type"] == TYPE_REVIEW_DECISION
    assert row["actor_id"] == BOB
    assert row["payload"]["decision"] == "request_changes"
    assert row["payload"]["round"] == 1


def test_the_other_reviewers_are_not_told_about_a_sibling_decision(fake):
    review_id = _request_review(fake)
    fake.notifications.clear()
    review_store.record_decision(TENANT, "pets", review_id, ReviewDecisionCreate(decision="approve"), BOB)
    assert fake.inbox(CARA) == []


def test_a_refused_decision_tells_nobody(fake):
    review_id = _request_review(fake, reviewers=[BOB])
    fake.notifications.clear()
    with pytest.raises(ReviewValidationError):
        review_store.record_decision(
            TENANT, "pets", review_id, ReviewDecisionCreate(decision="approve"), CARA
        )
    assert fake.notifications == []


def test_withdrawing_a_review_tells_nobody(fake):
    review_id = _request_review(fake)
    fake.notifications.clear()
    review_store.withdraw_review(TENANT, "pets", review_id, ALICE)
    assert fake.notifications == []


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def test_publishing_tells_the_versions_collaborators(fake):
    fake.add_collaborators(TENANT, PROJECT, VERSION, [ALICE, BOB, CARA])
    notify = notification_store.version_published_notifier(
        tenant_id=TENANT,
        project=fake.get_project_by_id(PROJECT, TENANT),
        version=fake.get_version_by_id(VERSION, TENANT),
        actor_id=ALICE,
    )
    drafts = notify({"version_id": VERSION})
    assert [draft.user_id for draft in drafts] == [BOB, CARA]
    assert {draft.type for draft in drafts} == {TYPE_VERSION_PUBLISHED}
    assert drafts[0].payload["version_label"] == "1.0.0"


def test_publishing_something_nobody_else_touched_needs_no_fan_out(fake):
    fake.add_collaborators(TENANT, PROJECT, VERSION, [ALICE])
    assert (
        notification_store.version_published_notifier(
            tenant_id=TENANT,
            project=fake.get_project_by_id(PROJECT, TENANT),
            version=fake.get_version_by_id(VERSION, TENANT),
            actor_id=ALICE,
        )
        is None
    )


def test_a_publish_is_never_failed_by_its_own_fan_out(fake, monkeypatch):
    def explode(**_kwargs):
        raise RuntimeError("collaborator read failed")

    monkeypatch.setattr(fake, "list_version_collaborators", explode)
    assert (
        notification_store.version_published_notifier(
            tenant_id=TENANT,
            project=fake.get_project_by_id(PROJECT, TENANT),
            version=fake.get_version_by_id(VERSION, TENANT),
            actor_id=ALICE,
        )
        is None
    )


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


def test_an_inbox_keeps_only_its_newest_rows(fake):
    for index in range(RETENTION_PER_USER):
        fake.add_notification(tenant_id=TENANT, user_id=BOB, payload={"index": index})
    oldest = fake.inbox(BOB)[0]["id"]

    _open_thread("@bob one more")

    inbox = fake.inbox(BOB)
    assert len(inbox) == RETENTION_PER_USER
    assert oldest not in {row["id"] for row in inbox}
    assert inbox[-1]["type"] == TYPE_MENTION
