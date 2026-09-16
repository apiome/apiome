"""SQL accessor semantics for notifications — COL-3.1 (#4521).

The ticket's central promise is that inbox rows are written **in the same transaction as the event
that caused them**, so a committed event and its notifications can never diverge. A fake accessor
cannot show that — it has no transaction. A scripted connection
(:mod:`tests.scripted_connection`) can, and these tests pin:

* a comment, a review decision, and a publish each commit **once**, with their inbox insert among
  the statements of that one transaction;
* a write whose guard does not hold rolls back and writes no inbox rows at all;
* a fan-out that fails takes its event down with it, rather than leaving a committed event whose
  recipients were never told;
* a write with nothing to fan out issues no extra statement;
* the inbox reads and the mark-read write are scoped to one user, and a non-UUID id never reaches
  the database.

The SQL text itself was exercised against a scratch database built from the real schema.
"""

from __future__ import annotations

import json

import psycopg2
import pytest

from app.notification_fanout import NotificationDraft
from app.notifications import TYPE_MENTION, TYPE_REVIEW_DECISION, TYPE_VERSION_PUBLISHED
from tests.scripted_connection import ScriptedConnection, database_with

TENANT = "1c7d5e90-0000-4000-8000-00000000a001"
PROJECT = "1c7d5e90-0000-4000-8000-00000000b001"
VERSION = "1c7d5e90-0000-4000-8000-00000000c001"
THREAD = "1c7d5e90-0000-4000-8000-00000000d001"
COMMENT = "1c7d5e90-0000-4000-8000-00000000d002"
REVIEW = "1c7d5e90-0000-4000-8000-00000000d003"
NOTIFICATION = "1c7d5e90-0000-4000-8000-00000000d004"
ALICE = "1c7d5e90-0000-4000-8000-00000000e001"
BOB = "1c7d5e90-0000-4000-8000-00000000e002"
CLASS_ID = "1c7d5e90-0000-4000-8000-00000000f001"


def _notifier(seen: list, *, user_id: str = BOB, type: str = TYPE_MENTION):
    """A notifier that records what the write produced and drafts one row for ``user_id``."""

    def notify(produced):
        seen.append(dict(produced))
        return [
            NotificationDraft(
                user_id=user_id,
                type=type,
                payload={"thread_id": produced.get("thread_id", THREAD)},
                actor_id=ALICE,
                project_id=PROJECT,
                version_id=VERSION,
            )
        ]

    return notify


def _inserts(conn: ScriptedConnection):
    """Every notification insert's parameters, in order."""
    return [
        params
        for sql, params in conn.statements
        if sql.startswith("INSERT INTO apiome.notifications")
    ]


# ---------------------------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------------------------


def test_a_thread_and_its_mentions_commit_together(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[{"thread_id": THREAD, "comment_id": COMMENT}], []])
    database = database_with(monkeypatch, conn)

    produced = database.insert_comment_thread(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        anchor_type="class",
        anchor_id=CLASS_ID,
        created_by=ALICE,
        body="@bob look",
        mentions=[BOB],
        notify=_notifier(seen),
    )

    assert produced == {"thread_id": THREAD, "comment_id": COMMENT}
    assert seen == [{"thread_id": THREAD, "comment_id": COMMENT}]
    assert (conn.commits, conn.rollbacks) == (1, 0)
    assert len(conn.statements) == 2
    tenant, users, types, payloads, actors, projects, versions = _inserts(conn)[0]
    assert (tenant, users, types, actors, projects, versions) == (
        TENANT,
        [BOB],
        [TYPE_MENTION],
        [ALICE],
        [PROJECT],
        [VERSION],
    )
    assert json.loads(payloads[0]) == {"thread_id": THREAD}


def test_a_comment_that_names_nobody_issues_no_extra_statement(monkeypatch):
    conn = ScriptedConnection([[{"comment_id": COMMENT}]])
    database = database_with(monkeypatch, conn)

    database.insert_comment(
        tenant_id=TENANT,
        project_id=PROJECT,
        thread_id=THREAD,
        author_id=ALICE,
        body="no names here",
        mentions=[],
        notify=None,
    )

    assert _inserts(conn) == []
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_a_reply_to_a_thread_that_is_not_there_notifies_nobody(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert (
        database.insert_comment(
            tenant_id=TENANT,
            project_id=PROJECT,
            thread_id=THREAD,
            author_id=ALICE,
            body="@bob",
            mentions=[BOB],
            notify=_notifier(seen),
        )
        is None
    )
    assert seen == []
    assert _inserts(conn) == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_resolve_that_changes_nothing_notifies_nobody(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert not database.set_comment_thread_status(
        tenant_id=TENANT,
        project_id=PROJECT,
        thread_id=THREAD,
        status="resolved",
        actor_id=ALICE,
        notify=_notifier(seen),
    )
    assert seen == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_an_edit_commits_its_new_mentions_with_the_new_text(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[{"id": COMMENT}], []])
    database = database_with(monkeypatch, conn)

    assert database.update_comment(
        tenant_id=TENANT,
        project_id=PROJECT,
        thread_id=THREAD,
        comment_id=COMMENT,
        body="@bob now",
        mentions=[BOB],
        notify=_notifier(seen),
    )
    assert seen == [{"thread_id": THREAD, "comment_id": COMMENT}]
    assert len(_inserts(conn)) == 1
    assert (conn.commits, conn.rollbacks) == (1, 0)


# ---------------------------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------------------------


def test_a_decision_hands_its_outcome_to_the_fan_out_and_commits_once(monkeypatch):
    seen: list = []
    conn = ScriptedConnection(
        [
            [{"state": "in_review", "round": 1, "version_id": VERSION}],
            [{"id": "row"}],
            [{"decision": "approve"}],
            [],
            [],
            [],
            [],
        ]
    )
    database = database_with(monkeypatch, conn)

    outcome = database.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=REVIEW,
        expected_round=1,
        user_id=BOB,
        decision="approve",
        note=None,
        notify=_notifier(seen, user_id=ALICE, type=TYPE_REVIEW_DECISION),
    )

    assert outcome == {"from_state": "in_review", "to_state": "approved"}
    assert seen == [
        {
            "review_id": REVIEW,
            "round": 1,
            "decision": "approve",
            "from_state": "in_review",
            "to_state": "approved",
        }
    ]
    assert len(_inserts(conn)) == 1
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_a_decision_whose_guard_fails_notifies_nobody(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[{"state": "approved", "round": 1, "version_id": VERSION}]])
    database = database_with(monkeypatch, conn)

    assert (
        database.record_review_decision(
            tenant_id=TENANT,
            project_id=PROJECT,
            review_id=REVIEW,
            expected_round=1,
            user_id=BOB,
            decision="approve",
            note=None,
            notify=_notifier(seen, user_id=ALICE, type=TYPE_REVIEW_DECISION),
        )
        is None
    )
    assert seen == []
    assert _inserts(conn) == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def test_a_publish_commits_its_inbox_rows_with_the_version(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[{"id": VERSION}], [], []])
    database = database_with(monkeypatch, conn)

    assert database.publish_version(
        VERSION,
        TENANT,
        ALICE,
        "private",
        notify=_notifier(seen, type=TYPE_VERSION_PUBLISHED),
    )
    assert seen == [{"version_id": VERSION}]
    assert len(_inserts(conn)) == 1
    assert conn.commits == 1


def test_a_publish_that_the_guard_turns_away_notifies_nobody(monkeypatch):
    seen: list = []
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert (
        database.publish_version(
            VERSION, TENANT, ALICE, "private", notify=_notifier(seen, type=TYPE_VERSION_PUBLISHED)
        )
        is None
    )
    assert seen == []
    assert _inserts(conn) == []


# ---------------------------------------------------------------------------------------------
# Fan-out that fails
# ---------------------------------------------------------------------------------------------


def test_a_fan_out_that_fails_takes_its_event_with_it(monkeypatch):
    conn = ScriptedConnection([[{"thread_id": THREAD, "comment_id": COMMENT}], []], fail_on=2)
    database = database_with(monkeypatch, conn)

    with pytest.raises(psycopg2.DatabaseError):
        database.insert_comment_thread(
            tenant_id=TENANT,
            project_id=PROJECT,
            version_id=VERSION,
            anchor_type="class",
            anchor_id=CLASS_ID,
            created_by=ALICE,
            body="@bob look",
            mentions=[BOB],
            notify=_notifier([]),
        )

    assert (conn.commits, conn.rollbacks) == (0, 1)
    assert conn.autocommit is True


def test_a_draft_without_a_recipient_is_dropped_before_the_statement(monkeypatch):
    conn = ScriptedConnection([[{"thread_id": THREAD, "comment_id": COMMENT}]])
    database = database_with(monkeypatch, conn)

    database.insert_comment_thread(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        anchor_type="class",
        anchor_id=CLASS_ID,
        created_by=ALICE,
        body="@nobody",
        mentions=[],
        notify=lambda _produced: [NotificationDraft(user_id="", type=TYPE_MENTION)],
    )

    assert _inserts(conn) == []


def test_fan_out_skips_a_recipient_whose_account_is_gone(monkeypatch):
    # The insert joins users, so a recipient deleted between resolving the set and writing it is
    # skipped rather than raising a foreign-key violation that would undo the event.
    conn = ScriptedConnection([[{"thread_id": THREAD, "comment_id": COMMENT}], []])
    database = database_with(monkeypatch, conn)

    database.insert_comment_thread(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        anchor_type="class",
        anchor_id=CLASS_ID,
        created_by=ALICE,
        body="@bob look",
        mentions=[BOB],
        notify=_notifier([]),
    )

    sql = next(
        statement for statement, _ in conn.statements if statement.startswith("INSERT INTO apiome.notifications")
    )
    assert "JOIN apiome.users u ON u.id = item.user_id AND u.deleted_at IS NULL" in sql


# ---------------------------------------------------------------------------------------------
# Reads and mark-read
# ---------------------------------------------------------------------------------------------


def test_an_inbox_read_with_a_malformed_id_never_reaches_the_database(monkeypatch):
    database = database_with(monkeypatch, None)
    assert database.list_notifications(tenant_id="acme", user_id=ALICE) == []
    assert database.count_notifications(tenant_id=TENANT, user_id="me") == 0
    assert database.count_unread_notifications_by_type(tenant_id="acme", user_id=ALICE) == {}
    assert database.mark_notifications_read(tenant_id=TENANT, user_id="me", all_unread=True) == 0
    assert database.list_version_collaborators(tenant_id=TENANT, project_id=PROJECT, version_id="v1") == []


def test_marking_nothing_read_issues_no_statement(monkeypatch):
    database = database_with(monkeypatch, None)
    assert database.mark_notifications_read(tenant_id=TENANT, user_id=ALICE) == 0
    assert database.mark_notifications_read(tenant_id=TENANT, user_id=ALICE, notification_ids=[]) == 0


def test_marking_ids_read_is_scoped_to_the_caller_and_to_unread_rows(monkeypatch):
    conn = ScriptedConnection([[{"id": NOTIFICATION}]])
    database = database_with(monkeypatch, conn)

    assert (
        database.mark_notifications_read(
            tenant_id=TENANT, user_id=ALICE, notification_ids=[NOTIFICATION, "not-a-uuid"]
        )
        == 1
    )
    sql, params = conn.statements[0]
    assert "n.tenant_id = %s::uuid AND n.user_id = %s::uuid AND n.read_at IS NULL" in sql
    assert "n.id = ANY(%s::uuid[])" in sql
    assert params == (TENANT, ALICE, [NOTIFICATION])


def test_marking_everything_read_names_no_ids(monkeypatch):
    conn = ScriptedConnection([[{"id": NOTIFICATION}, {"id": NOTIFICATION}]])
    database = database_with(monkeypatch, conn)

    assert (
        database.mark_notifications_read(
            tenant_id=TENANT, user_id=ALICE, notification_ids=[NOTIFICATION], all_unread=True
        )
        == 2
    )
    sql, params = conn.statements[0]
    assert "ANY" not in sql
    assert params == (TENANT, ALICE)


def test_the_inbox_list_filters_and_pages_in_sql(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    database.list_notifications(
        tenant_id=TENANT, user_id=ALICE, unread_only=True, type_filter=TYPE_MENTION, limit=10, offset=20
    )
    sql, params = conn.statements[0]
    assert "n.read_at IS NULL" in sql
    assert "n.type = %s" in sql
    assert "ORDER BY n.created_at DESC, n.id DESC" in sql
    assert params == (TENANT, ALICE, TYPE_MENTION, 10, 20)
