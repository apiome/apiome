"""Transaction semantics of the GNC-2.3 (#4739) synchronization accessors.

:class:`tests.fake_sync_db.FakeSyncDb` proves the *rules*; it has no transaction, so it cannot prove
the thing these accessors actually exist for: that a merge result, every conflict it found, and the
``sync.*`` audit row all commit or roll back together. A plan whose conflicts were lost would read
as clean, which is the one way this table could cause the damage the ticket exists to prevent.

These tests drive the real :class:`app.database.Database` against :mod:`tests.scripted_connection`,
so every statement, commit, and rollback is visible. The SQL text itself is exercised separately
against a scratch database built from V266.
"""

from __future__ import annotations

from typing import Any, List, Optional

import psycopg2
import pytest

from tests.scripted_connection import ScriptedConnection, database_with

TENANT = "0b2c3d40-1111-4222-8333-000000000001"
PROJECT = "0b2c3d40-1111-4222-8333-000000000002"
VERSION = "0b2c3d40-1111-4222-8333-000000000010"
BINDING = "0b2c3d40-1111-4222-8333-000000000020"
CANDIDATE = "0b2c3d40-1111-4222-8333-000000000030"
PLAN = "0b2c3d40-1111-4222-8333-000000000040"
CONFLICT = "0b2c3d40-1111-4222-8333-000000000050"
ALICE = "0b2c3d40-1111-4222-8333-000000000101"
NOT_A_UUID = "not-a-uuid"

COMMIT_BASE = "1" * 40
COMMIT_NEXT = "2" * 40


def _plan_kwargs(**overrides: Any) -> dict:
    """The arguments of a well-formed :meth:`Database.record_draft_sync_plan` call."""
    return {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": VERSION,
        "binding_id": BINDING,
        "candidate_id": CANDIDATE,
        "base_commit_sha": COMMIT_BASE,
        "base_digest": "sha256:base",
        "git_commit_sha": COMMIT_NEXT,
        "git_digest": "sha256:git",
        "draft_digest": "sha256:draft",
        "plan_fingerprint": "sha256:plan",
        "status": "mergeable",
        "auto_applied_count": 1,
        "local_count": 0,
        "agreed_count": 0,
        "changes": [{"pointer": "/info/description", "kind": "addition"}],
        "conflicts": [],
        "conflicts_truncated": False,
        "source_file": "openapi.yaml",
        "source_member_count": 1,
        "guard": "none",
        "actor_id": ALICE,
        **overrides,
    }


def _conflict(pointer: str) -> dict:
    """One conflict row as the store hands it to the accessor."""
    return {
        "pointer": pointer,
        "scope": "document",
        "group_key": "info",
        "label": f"Changed {pointer}",
        "git_kind": "update",
        "draft_kind": "update",
        "base_value": "1.0.0",
        "git_value": "2.0.0",
        "draft_value": "1.5.0",
        "source_file": "openapi.yaml",
        "source_line": 4,
        "source_url": "https://github.com/acme/specs/blob/abc/openapi.yaml#L4",
    }


def _sql(conn: ScriptedConnection) -> List[str]:
    """Every statement's collapsed SQL, in order."""
    return [statement for statement, _params in conn.statements]


def _matching(conn: ScriptedConnection, fragment: str) -> List[str]:
    """Statements containing ``fragment``."""
    return [statement for statement in _sql(conn) if fragment in statement]


# ---------------------------------------------------------------------------------------------
# Guards that never reach the database
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda db: db.record_draft_sync_plan(**_plan_kwargs(tenant_id=NOT_A_UUID)),
        lambda db: db.record_draft_sync_plan(**_plan_kwargs(binding_id=NOT_A_UUID)),
        lambda db: db.find_draft_sync_plan(
            tenant_id=TENANT, binding_id=NOT_A_UUID, plan_fingerprint="sha256:plan"
        ),
        lambda db: db.get_draft_sync_plan(tenant_id=TENANT, project_id=PROJECT, plan_id=NOT_A_UUID),
        lambda db: db.list_draft_sync_plans(tenant_id=TENANT, version_id=NOT_A_UUID),
        lambda db: db.list_draft_sync_conflicts(tenant_id=TENANT, plan_id=NOT_A_UUID),
        lambda db: db.get_draft_sync_conflict(
            tenant_id=TENANT, plan_id=PLAN, conflict_id=NOT_A_UUID
        ),
        lambda db: db.resolve_draft_sync_conflict(
            tenant_id=TENANT,
            project_id=PROJECT,
            plan_id=PLAN,
            conflict_id=CONFLICT,
            resolution="git",
            actor_id=NOT_A_UUID,
        ),
    ],
)
def test_a_malformed_argument_never_reaches_the_database(monkeypatch, call):
    database = database_with(monkeypatch, None)
    assert not call(database)


def test_an_unattributable_merge_is_still_recorded(monkeypatch):
    # A merge may be computed by a background sweep with no user; the row simply has no author.
    conn = ScriptedConnection([[{"id": PLAN}], []])
    database = database_with(monkeypatch, conn)

    assert database.record_draft_sync_plan(**_plan_kwargs(actor_id=None)) == {
        "plan_id": PLAN,
        "created": True,
    }
    _insert_sql, insert_params = conn.statements[0]
    assert insert_params[-1] is None


# ---------------------------------------------------------------------------------------------
# Recording a merge
# ---------------------------------------------------------------------------------------------


def test_a_plan_its_conflicts_and_its_audit_row_commit_together(monkeypatch):
    conn = ScriptedConnection([[{"id": PLAN}], [], [], []])
    database = database_with(monkeypatch, conn)

    produced = database.record_draft_sync_plan(
        **_plan_kwargs(
            status="conflicted",
            conflicts=[_conflict("/info/version"), _conflict("/info/title")],
        )
    )

    assert produced == {"plan_id": PLAN, "created": True}
    statements = _sql(conn)
    assert "INSERT INTO apiome.draft_sync_plans" in statements[0]
    assert len(_matching(conn, "INSERT INTO apiome.draft_sync_conflicts")) == 2
    assert "INSERT INTO apiome.workflow_audit" in statements[3]
    assert (conn.commits, conn.rollbacks) == (1, 0)
    assert conn.autocommit is True


def test_a_truncated_merge_says_so_on_the_row_rather_than_reading_as_less_conflicted(monkeypatch):
    # Dropping findings silently would make a plan read as *less* conflicted than it is, which is
    # the one direction this table must never be wrong in.
    conn = ScriptedConnection([[{"id": PLAN}], [], []])
    database = database_with(monkeypatch, conn)

    database.record_draft_sync_plan(
        **_plan_kwargs(
            status="conflicted",
            conflicts=[_conflict("/info/version")],
            conflicts_truncated=True,
        )
    )

    _insert_sql, insert_params = conn.statements[0]
    assert True in insert_params
    _audit_sql, audit_params = conn.statements[2]
    assert '"conflicts_truncated": true' in audit_params[5]


def test_the_audit_row_names_the_three_documents_the_merge_used(monkeypatch):
    conn = ScriptedConnection([[{"id": PLAN}], []])
    database = database_with(monkeypatch, conn)

    database.record_draft_sync_plan(**_plan_kwargs())

    _audit_sql, audit_params = conn.statements[1]
    assert audit_params[3] == "sync.planned"
    detail = audit_params[5]
    for fragment in (COMMIT_BASE, COMMIT_NEXT, "sha256:draft", '"status": "mergeable"'):
        assert fragment in detail


def test_a_rerun_of_the_same_three_documents_finds_the_stored_plan(monkeypatch):
    # The ON CONFLICT DO NOTHING insert returns nothing; the accessor reads the row that won.
    conn = ScriptedConnection([[], [{"id": PLAN}]])
    database = database_with(monkeypatch, conn)

    produced = database.record_draft_sync_plan(**_plan_kwargs(conflicts=[_conflict("/info/version")]))

    assert produced == {"plan_id": PLAN, "created": False}
    # Nothing is written a second time: no conflicts, no audit row.
    assert _matching(conn, "INSERT INTO apiome.draft_sync_conflicts") == []
    assert _matching(conn, "INSERT INTO apiome.workflow_audit") == []
    assert "ON CONFLICT (binding_id, plan_fingerprint) DO NOTHING" in _sql(conn)[0]


def test_a_vanished_rerun_row_is_answered_none_and_rolled_back(monkeypatch):
    conn = ScriptedConnection([[], []])
    database = database_with(monkeypatch, conn)

    assert database.record_draft_sync_plan(**_plan_kwargs()) is None
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_failed_conflict_insert_rolls_the_whole_merge_back(monkeypatch):
    # A plan whose conflicts were lost would read as clean — the one failure mode that matters.
    conn = ScriptedConnection([[{"id": PLAN}], []], fail_on=2)
    database = database_with(monkeypatch, conn)

    with pytest.raises(psycopg2.DatabaseError):
        database.record_draft_sync_plan(
            **_plan_kwargs(status="conflicted", conflicts=[_conflict("/info/version")])
        )
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_recording_a_merge_never_touches_the_version_it_describes(monkeypatch):
    conn = ScriptedConnection([[{"id": PLAN}], [], []])
    database = database_with(monkeypatch, conn)

    database.record_draft_sync_plan(
        **_plan_kwargs(status="conflicted", conflicts=[_conflict("/info/version")])
    )

    # The safety property, as statements: nothing in this transaction writes to a draft.
    assert _matching(conn, "apiome.versions") == []
    assert _matching(conn, "apiome.classes") == []
    assert _matching(conn, "apiome.reviews") == []


# ---------------------------------------------------------------------------------------------
# Settling a conflict
# ---------------------------------------------------------------------------------------------


def _settle(database: Any, **overrides: Any) -> Optional[dict]:
    """Settle a conflict through the accessor."""
    return database.resolve_draft_sync_conflict(
        **{
            "tenant_id": TENANT,
            "project_id": PROJECT,
            "plan_id": PLAN,
            "conflict_id": CONFLICT,
            "resolution": "git",
            "actor_id": ALICE,
            "note": "the repository is right",
            **overrides,
        }
    )


def test_settling_locks_the_plan_recomputes_the_count_and_audits_in_one_transaction(monkeypatch):
    conn = ScriptedConnection(
        [
            [{"id": PLAN, "version_id": VERSION, "binding_id": BINDING, "conflict_count": 2}],
            [{"pointer": "/info/version"}],
            [{"outstanding": 1}],
            [],
            [],
        ]
    )
    database = database_with(monkeypatch, conn)

    produced = _settle(database)

    assert produced == {
        "conflict_id": CONFLICT,
        "resolution": "git",
        "status": "conflicted",
        "unresolved_count": 1,
    }
    statements = _sql(conn)
    assert "FOR UPDATE" in statements[0]
    assert "UPDATE apiome.draft_sync_conflicts" in statements[1]
    # Recomputed under the lock, never decremented: two people settling the last two conflicts at
    # once cannot leave the plan claiming an outstanding one that no longer exists.
    assert "COUNT(*) AS outstanding" in statements[2]
    assert "UPDATE apiome.draft_sync_plans" in statements[3]
    assert "INSERT INTO apiome.workflow_audit" in statements[4]
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_settling_the_last_conflict_moves_the_plan_to_resolved(monkeypatch):
    conn = ScriptedConnection(
        [
            [{"id": PLAN, "version_id": VERSION, "binding_id": BINDING, "conflict_count": 1}],
            [{"pointer": "/info/version"}],
            [{"outstanding": 0}],
            [],
            [],
        ]
    )
    database = database_with(monkeypatch, conn)

    assert _settle(database)["status"] == "resolved"
    _update_sql, update_params = conn.statements[3]
    assert update_params[:2] == (0, "resolved")


def test_a_plan_of_another_project_writes_nothing_and_rolls_back(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert _settle(database) is None
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_an_already_settled_conflict_writes_nothing_and_rolls_back(monkeypatch):
    conn = ScriptedConnection(
        [[{"id": PLAN, "version_id": VERSION, "binding_id": BINDING, "conflict_count": 1}], []]
    )
    database = database_with(monkeypatch, conn)

    assert _settle(database) is None
    # The UPDATE's `AND resolution IS NULL` is what refuses it; nothing after it runs.
    assert "AND resolution IS NULL" in _sql(conn)[1]
    assert len(conn.statements) == 2
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_settling_never_touches_the_version_it_describes(monkeypatch):
    conn = ScriptedConnection(
        [
            [{"id": PLAN, "version_id": VERSION, "binding_id": BINDING, "conflict_count": 1}],
            [{"pointer": "/info/version"}],
            [{"outstanding": 0}],
            [],
            [],
        ]
    )
    database = database_with(monkeypatch, conn)

    _settle(database)

    assert _matching(conn, "apiome.versions") == []
    assert _matching(conn, "apiome.draft_repository_bindings") == []
