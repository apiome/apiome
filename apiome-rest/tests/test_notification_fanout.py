"""Who an event notifies, and what its inbox row says — COL-3.1 (#4521).

:mod:`app.notification_fanout` is the only place that decides a recipient set, and it is pure: no
database, no HTTP. These tests pin the two rules that hold for every event type — nobody is
notified of their own action, and a recipient set is bounded — and then each builder's payload,
because a payload key that quietly disappears breaks a deep link in the notification centre
(COL-3.2) rather than anything here.
"""

from __future__ import annotations

import uuid

from app.notification_fanout import (
    excerpt,
    mention_drafts,
    recipients,
    review_decision_drafts,
    review_requested_drafts,
    thread_resolved_drafts,
    version_published_drafts,
)
from app.notifications import (
    MAX_EXCERPT_LENGTH,
    MAX_RECIPIENTS,
    TYPE_MENTION,
    TYPE_REVIEW_DECISION,
    TYPE_REVIEW_REQUESTED,
    TYPE_THREAD_RESOLVED,
    TYPE_VERSION_PUBLISHED,
)

ALICE = "3f1c9a20-0000-4000-8000-00000000a001"
BOB = "3f1c9a20-0000-4000-8000-00000000a002"
CARA = "3f1c9a20-0000-4000-8000-00000000a003"
PROJECT = {"id": "3f1c9a20-0000-4000-8000-00000000b001", "slug": "payments", "name": "Payments"}
VERSION = {"id": "3f1c9a20-0000-4000-8000-00000000c001", "version_id": "1.2.0"}
THREAD = "3f1c9a20-0000-4000-8000-00000000d001"
COMMENT = "3f1c9a20-0000-4000-8000-00000000d002"
REVIEW = "3f1c9a20-0000-4000-8000-00000000e001"
CLASS_ID = "3f1c9a20-0000-4000-8000-00000000f001"


# ---------------------------------------------------------------------------------------------
# Recipient sets
# ---------------------------------------------------------------------------------------------


def test_recipients_keep_first_seen_order_and_collapse_duplicates():
    assert recipients([BOB, ALICE, BOB]) == [BOB, ALICE]


def test_recipients_drop_the_actor_and_anything_that_is_not_a_user_id():
    assert recipients([ALICE, BOB, "", None, "not-a-uuid"], exclude=[ALICE]) == [BOB]


def test_recipients_accept_any_spelling_of_the_same_id():
    assert recipients([ALICE.upper()], exclude=[ALICE]) == []


def test_recipients_are_bounded():
    many = [str(uuid.uuid4()) for _ in range(MAX_RECIPIENTS + 25)]
    assert len(recipients(many)) == MAX_RECIPIENTS


# ---------------------------------------------------------------------------------------------
# Excerpts
# ---------------------------------------------------------------------------------------------


def test_excerpt_collapses_markdown_whitespace():
    assert excerpt("  a\n\nlong   line\t here ") == "a long line here"


def test_excerpt_is_cut_with_an_ellipsis():
    text = excerpt("x" * (MAX_EXCERPT_LENGTH + 50))
    assert len(text) == MAX_EXCERPT_LENGTH
    assert text.endswith("…")


def test_excerpt_of_nothing_is_empty():
    assert excerpt(None) == ""


# ---------------------------------------------------------------------------------------------
# Mentions
# ---------------------------------------------------------------------------------------------


def test_a_mention_points_at_the_comment_and_carries_an_excerpt():
    drafts = mention_drafts(
        mentioned=[BOB],
        actor_id=ALICE,
        project=PROJECT,
        version=VERSION,
        thread_id=THREAD,
        comment_id=COMMENT,
        anchor_type="class",
        anchor_id=CLASS_ID,
        body="@Bob does **Customer.email** need a format?",
    )
    assert [draft.user_id for draft in drafts] == [BOB]
    draft = drafts[0]
    assert draft.type == TYPE_MENTION
    assert draft.actor_id == ALICE
    assert draft.project_id == PROJECT["id"]
    assert draft.version_id == VERSION["id"]
    assert draft.payload == {
        "project_slug": "payments",
        "project_name": "Payments",
        "version_label": "1.2.0",
        "thread_id": THREAD,
        "comment_id": COMMENT,
        "anchor_type": "class",
        "anchor_id": CLASS_ID,
        "excerpt": "@Bob does **Customer.email** need a format?",
    }


def test_mentioning_yourself_notifies_nobody():
    drafts = mention_drafts(
        mentioned=[ALICE],
        actor_id=ALICE,
        project=PROJECT,
        version=VERSION,
        thread_id=THREAD,
        comment_id=COMMENT,
        anchor_type="version",
        anchor_id=None,
        body="note to self",
    )
    assert drafts == []


def test_an_edit_only_notifies_the_members_it_newly_names():
    drafts = mention_drafts(
        mentioned=[BOB, CARA],
        actor_id=ALICE,
        project=PROJECT,
        version=VERSION,
        thread_id=THREAD,
        comment_id=COMMENT,
        anchor_type="class",
        anchor_id=CLASS_ID,
        body="@Bob @Cara",
        already_mentioned=[BOB],
    )
    assert [draft.user_id for draft in drafts] == [CARA]


def test_a_payload_omits_labels_that_did_not_resolve():
    drafts = mention_drafts(
        mentioned=[BOB],
        actor_id=ALICE,
        project={"id": PROJECT["id"]},
        version=None,
        thread_id=THREAD,
        comment_id=COMMENT,
        anchor_type="version",
        anchor_id=None,
        body="hi",
    )
    payload = drafts[0].payload
    assert "project_slug" not in payload
    assert "version_label" not in payload
    assert "anchor_id" not in payload
    assert drafts[0].version_id is None


# ---------------------------------------------------------------------------------------------
# Thread resolution
# ---------------------------------------------------------------------------------------------


def test_resolving_a_thread_tells_its_other_participants():
    drafts = thread_resolved_drafts(
        participants=[ALICE, BOB, CARA, BOB],
        actor_id=CARA,
        project=PROJECT,
        version=VERSION,
        thread_id=THREAD,
        anchor_type="path",
        anchor_id=CLASS_ID,
    )
    assert [draft.user_id for draft in drafts] == [ALICE, BOB]
    assert {draft.type for draft in drafts} == {TYPE_THREAD_RESOLVED}
    assert drafts[0].payload["thread_id"] == THREAD
    assert drafts[0].payload["anchor_type"] == "path"
    assert "excerpt" not in drafts[0].payload


# ---------------------------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------------------------


def test_a_review_request_names_the_round_it_opens():
    drafts = review_requested_drafts(
        reviewers=[BOB, CARA],
        actor_id=ALICE,
        project=PROJECT,
        version=VERSION,
        review_id=REVIEW,
        round=2,
    )
    assert [draft.user_id for draft in drafts] == [BOB, CARA]
    assert drafts[0].type == TYPE_REVIEW_REQUESTED
    assert drafts[0].payload["review_id"] == REVIEW
    assert drafts[0].payload["round"] == 2


def test_a_reviewer_who_is_the_requester_is_not_asked_twice():
    drafts = review_requested_drafts(
        reviewers=[ALICE, BOB],
        actor_id=ALICE,
        project=PROJECT,
        version=VERSION,
        review_id=REVIEW,
        round=1,
    )
    assert [draft.user_id for draft in drafts] == [BOB]


def test_a_decision_tells_only_the_requester_and_says_which_way():
    drafts = review_decision_drafts(
        requested_by=ALICE,
        actor_id=BOB,
        project=PROJECT,
        version=VERSION,
        review_id=REVIEW,
        round=1,
        decision="request_changes",
    )
    assert [draft.user_id for draft in drafts] == [ALICE]
    assert drafts[0].type == TYPE_REVIEW_DECISION
    assert drafts[0].payload["decision"] == "request_changes"
    assert drafts[0].actor_id == BOB


def test_deciding_a_review_you_requested_notifies_nobody():
    assert (
        review_decision_drafts(
            requested_by=ALICE,
            actor_id=ALICE,
            project=PROJECT,
            version=VERSION,
            review_id=REVIEW,
            round=1,
            decision="approve",
        )
        == []
    )


def test_a_decision_on_a_review_whose_requester_is_gone_notifies_nobody():
    assert (
        review_decision_drafts(
            requested_by=None,
            actor_id=BOB,
            project=PROJECT,
            version=VERSION,
            review_id=REVIEW,
            round=1,
            decision="approve",
        )
        == []
    )


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def test_publishing_tells_the_version_collaborators_and_names_the_version():
    drafts = version_published_drafts(
        collaborators=[ALICE, BOB, CARA], actor_id=CARA, project=PROJECT, version=VERSION
    )
    assert [draft.user_id for draft in drafts] == [ALICE, BOB]
    assert drafts[0].type == TYPE_VERSION_PUBLISHED
    assert drafts[0].payload == {
        "project_slug": "payments",
        "project_name": "Payments",
        "version_label": "1.2.0",
    }


def test_publishing_something_nobody_else_touched_notifies_nobody():
    assert version_published_drafts(
        collaborators=[CARA], actor_id=CARA, project=PROJECT, version=VERSION
    ) == []
