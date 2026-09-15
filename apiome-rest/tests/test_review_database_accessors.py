"""SQL accessor semantics for reviews — COL-2.1 (#4517).

The review writes on :class:`app.database.Database` each run several statements in one
transaction. A scripted connection stands in for Postgres, so these tests pin — without a live
database — what the fake used by the route tests can only promise:

* a write whose guard does not hold rolls back and writes no audit row;
* a successful write commits once, with its ``review.*`` audit rows inside the same transaction;
* a decision folds the round's decisions read back under the lock into the review's state;
* the connection's autocommit mode is restored whatever happens;
* non-UUID ids never reach the database.

The SQL text itself was exercised against a scratch database built from the real schema.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List, Optional, Sequence

import psycopg2
import pytest

from app.database import Database

TENANT = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0001"
PROJECT = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0002"
VERSION = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0010"
REVIEW = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0020"
ALICE = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0101"
BOB = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0102"
DAVE = "9b1d2e30-4f5a-4b6c-8d7e-0f1a2b3c0103"


class _Cursor:
    """A cursor that answers each statement with the connection's next scripted rows."""

    def __init__(self, conn: "_Connection") -> None:
        self._conn = conn
        self._rows: List[Any] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> None:
        self._conn.statements.append((" ".join(sql.split()), params))
        if self._conn.fail_on is not None and len(self._conn.statements) == self._conn.fail_on:
            raise psycopg2.DatabaseError("boom")
        self._rows = self._conn.responses.pop(0) if self._conn.responses else []

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Any]:
        return list(self._rows)


class _Connection:
    """A connection that records statements, commits, and rollbacks."""

    def __init__(self, responses: Sequence[List[Any]], fail_on: Optional[int] = None) -> None:
        self.responses = list(responses)
        self.fail_on = fail_on
        self.statements: List[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.autocommit = True
        self.closed = False
        self.info = SimpleNamespace(transaction_status=psycopg2.extensions.TRANSACTION_STATUS_IDLE)

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _database(monkeypatch, conn: Optional[_Connection]) -> Database:
    """A Database whose connection is ``conn``; connecting at all fails when ``conn`` is None."""
    database = Database()

    def connect() -> _Connection:
        if conn is None:
            raise AssertionError("a guarded call must not reach the database")
        return conn

    monkeypatch.setattr(database, "connect", connect)
    return database


def _audits(conn: _Connection):
    """``(action, detail)`` of every audit insert, in order."""
    return [
        (params[3], json.loads(params[5]))
        for sql, params in conn.statements
        if sql.startswith("INSERT INTO apiome.workflow_audit")
    ]


def _lock_row(state: str = "in_review", round_number: int = 1):
    return [{"state": state, "round": round_number, "version_id": VERSION}]


def test_a_request_commits_the_review_its_reviewers_and_its_audit_together(monkeypatch):
    conn = _Connection([[{"id": REVIEW}], [], []])
    database = _database(monkeypatch, conn)
    review_id = database.insert_review(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        requested_by=ALICE,
        reviewer_ids=[BOB, DAVE],
        spec_fingerprint="sha256:abc",
    )
    assert review_id == REVIEW
    assert (conn.commits, conn.rollbacks, conn.autocommit) == (1, 0, True)
    insert_review, insert_reviewers, _audit = conn.statements
    assert "ON CONFLICT (version_id) WHERE closed_at IS NULL DO NOTHING" in insert_review[0]
    assert insert_reviewers[1] == (REVIEW, [BOB, DAVE])
    [(action, detail)] = _audits(conn)
    assert action == "review.requested"
    assert detail == {
        "review_id": REVIEW,
        "round": 1,
        "from_state": "draft",
        "to_state": "in_review",
        "reviewers": [BOB, DAVE],
        "spec_fingerprint": "sha256:abc",
    }


def test_a_request_for_a_version_with_an_open_review_writes_nothing(monkeypatch):
    conn = _Connection([[]])
    database = _database(monkeypatch, conn)
    assert (
        database.insert_review(
            tenant_id=TENANT,
            project_id=PROJECT,
            version_id=VERSION,
            requested_by=ALICE,
            reviewer_ids=[BOB],
            spec_fingerprint="sha256:abc",
        )
        is None
    )
    assert (len(conn.statements), conn.commits, conn.rollbacks) == (1, 0, 1)


def test_a_decision_folds_the_locked_round_into_the_reviews_state(monkeypatch):
    conn = _Connection(
        [_lock_row(), [{"id": "row"}], [{"decision": "approve"}, {"decision": "request_changes"}], [], [], []]
    )
    database = _database(monkeypatch, conn)
    outcome = database.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=REVIEW,
        expected_round=1,
        user_id=DAVE,
        decision="request_changes",
        note="Rename it.",
    )
    assert outcome == {"from_state": "in_review", "to_state": "changes_requested"}
    assert (conn.commits, conn.rollbacks) == (1, 0)
    lock, decide, fold, move = conn.statements[:4]
    assert lock[0].endswith("FOR UPDATE")
    assert "decision = 'pending'" in decide[0]
    assert decide[1] == ("request_changes", "Rename it.", REVIEW, 1, DAVE)
    assert fold[1] == (REVIEW, 1)
    assert move[1] == ("changes_requested", REVIEW)
    decision = {"review_id": REVIEW, "round": 1, "reviewer": DAVE, "decision": "request_changes", "has_note": True}
    changed = {"review_id": REVIEW, "round": 1, "from_state": "in_review", "to_state": "changes_requested"}
    assert _audits(conn) == [("review.decision", decision), ("review.state_changed", changed)]


def test_a_decision_that_leaves_the_round_open_audits_only_the_decision(monkeypatch):
    conn = _Connection([_lock_row(), [{"id": "row"}], [{"decision": "approve"}, {"decision": "pending"}], [], []])
    database = _database(monkeypatch, conn)
    outcome = database.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=REVIEW,
        expected_round=1,
        user_id=BOB,
        decision="approve",
        note=None,
    )
    assert outcome == {"from_state": "in_review", "to_state": "in_review"}
    assert [action for action, _detail in _audits(conn)] == ["review.decision"]


@pytest.mark.parametrize(
    "responses",
    [
        [[]],  # the review is closed or in another project
        [_lock_row(round_number=2)],  # somebody re-requested first
        [_lock_row(state="approved")],  # the round is already decided
        [_lock_row(), []],  # the reviewer already decided, or is not in this round
    ],
)
def test_a_decision_whose_guard_fails_rolls_back_without_an_audit(monkeypatch, responses):
    conn = _Connection(responses)
    database = _database(monkeypatch, conn)
    outcome = database.record_review_decision(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=REVIEW,
        expected_round=1,
        user_id=BOB,
        decision="approve",
        note=None,
    )
    assert outcome is None
    assert (conn.commits, conn.rollbacks, conn.autocommit) == (0, 1, True)
    assert _audits(conn) == []


def test_a_re_request_starts_the_next_round_without_touching_earlier_rows(monkeypatch):
    conn = _Connection([_lock_row(state="approved"), [], [], []])
    database = _database(monkeypatch, conn)
    outcome = database.re_request_review(
        tenant_id=TENANT,
        project_id=PROJECT,
        review_id=REVIEW,
        expected_round=1,
        reviewer_ids=[BOB, DAVE],
        spec_fingerprint="sha256:new",
        actor_id=ALICE,
    )
    assert outcome == {"round": 2, "from_state": "approved"}
    _lock, move, insert, _audit = conn.statements
    assert move[1] == ("in_review", 2, "sha256:new", REVIEW)
    assert insert[0].startswith("INSERT INTO apiome.review_reviewers")
    assert insert[1] == (REVIEW, 2, [BOB, DAVE])
    assert not any(sql.startswith("UPDATE apiome.review_reviewers") for sql, _params in conn.statements)
    [(action, detail)] = _audits(conn)
    assert action == "review.re_requested"
    assert (detail["previous_round"], detail["round"], detail["from_state"]) == (1, 2, "approved")


def test_a_withdrawal_closes_and_audits_once(monkeypatch):
    conn = _Connection([[{"version_id": VERSION, "state": "approved", "round": 3}], []])
    database = _database(monkeypatch, conn)
    assert database.withdraw_review(tenant_id=TENANT, project_id=PROJECT, review_id=REVIEW, actor_id=ALICE)
    assert _audits(conn) == [("review.withdrawn", {"review_id": REVIEW, "round": 3, "state": "approved"})]

    closed = _Connection([[]])
    database = _database(monkeypatch, closed)
    assert not database.withdraw_review(tenant_id=TENANT, project_id=PROJECT, review_id=REVIEW, actor_id=ALICE)
    assert (closed.commits, closed.rollbacks) == (0, 1)


def test_a_failing_statement_rolls_back_restores_autocommit_and_raises(monkeypatch):
    conn = _Connection([[{"id": REVIEW}], []], fail_on=3)
    database = _database(monkeypatch, conn)
    with pytest.raises(psycopg2.DatabaseError):
        database.insert_review(
            tenant_id=TENANT,
            project_id=PROJECT,
            version_id=VERSION,
            requested_by=ALICE,
            reviewer_ids=[BOB],
            spec_fingerprint="sha256:abc",
        )
    assert (conn.commits, conn.rollbacks, conn.autocommit) == (0, 1, True)


def test_ids_that_are_not_uuids_never_reach_the_database(monkeypatch):
    database = _database(monkeypatch, None)
    common = {"tenant_id": "t1", "project_id": PROJECT}
    assert database.get_review(**common, review_id=REVIEW) is None
    assert database.get_open_review_for_version(**common, version_id=VERSION) is None
    assert database.list_reviews(**common) == []
    assert database.count_reviews(**common) == 0
    assert database.list_review_reviewers(review_id="nope") == []
    assert database.insert_review(
        **common, version_id=VERSION, requested_by=ALICE, reviewer_ids=["bob"], spec_fingerprint="x"
    ) is None
    scoped = {"tenant_id": TENANT, "project_id": PROJECT}
    assert database.insert_review(
        **scoped, version_id=VERSION, requested_by=ALICE, reviewer_ids=[], spec_fingerprint="x"
    ) is None
    assert database.re_request_review(
        **common, review_id=REVIEW, expected_round=1, reviewer_ids=[BOB], spec_fingerprint="x", actor_id=ALICE
    ) is None
    assert database.record_review_decision(
        **common, review_id=REVIEW, expected_round=1, user_id=BOB, decision="approve", note=None
    ) is None
    assert database.record_review_decision(
        **scoped, review_id=REVIEW, expected_round=1, user_id=BOB, decision="pending", note=None
    ) is None
    assert database.withdraw_review(**common, review_id=REVIEW, actor_id=ALICE) is False
