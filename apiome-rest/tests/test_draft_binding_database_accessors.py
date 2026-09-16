"""Transaction semantics of the GNC-2.1 (#4737) binding accessors.

:class:`tests.fake_binding_db.FakeBindingDb` proves the *rules*; it has no transaction, so it
cannot prove the thing the accessors actually exist for: that a binding, the candidates a release
supersedes, and the ``binding.*`` audit row all commit or roll back together. These tests drive the
real :class:`app.database.Database` against :mod:`tests.scripted_connection`, so every statement,
commit, and rollback is visible.

The SQL text itself is exercised separately against a scratch database built from V264.
"""

from __future__ import annotations

from typing import Any, List, Optional

import psycopg2
import pytest
from psycopg2 import errors as pg_errors

from tests.scripted_connection import ScriptedConnection, database_with

TENANT = "0a1b2c30-1111-4222-8333-000000000001"
PROJECT = "0a1b2c30-1111-4222-8333-000000000002"
VERSION = "0a1b2c30-1111-4222-8333-000000000010"
BINDING = "0a1b2c30-1111-4222-8333-000000000020"
CANDIDATE = "0a1b2c30-1111-4222-8333-000000000030"
REPOSITORY = "0a1b2c30-1111-4222-8333-000000000040"
ALICE = "0a1b2c30-1111-4222-8333-000000000101"
NOT_A_UUID = "not-a-uuid"

COMMIT_ONE = "1" * 40
COMMIT_TWO = "2" * 40


def _bind_kwargs(**overrides: Any) -> dict:
    """The arguments of a well-formed :meth:`Database.insert_draft_binding` call."""
    return {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": VERSION,
        "repository_id": REPOSITORY,
        "provider": "github",
        "repo_full_name": "acme/specs",
        "repo_url": "https://github.com/acme/specs",
        "ref": "main",
        "path": "spec",
        "commit_sha": COMMIT_ONE,
        "source_digest": "sha256:one",
        "created_by": ALICE,
        "replace": False,
        **overrides,
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
        lambda db: db.insert_draft_binding(**_bind_kwargs(tenant_id=NOT_A_UUID)),
        lambda db: db.insert_draft_binding(**_bind_kwargs(repository_id=NOT_A_UUID)),
        lambda db: db.release_draft_binding(
            tenant_id=TENANT, project_id=PROJECT, binding_id=NOT_A_UUID, actor_id=ALICE, reason="unbound"
        ),
        lambda db: db.raise_binding_sync_candidate(
            tenant_id=TENANT, binding_id=BINDING, to_commit_sha="", origin="webhook"
        ),
        lambda db: db.raise_binding_sync_candidate(
            tenant_id=TENANT, binding_id=BINDING, to_commit_sha=COMMIT_TWO, origin="manual", detected_by=NOT_A_UUID
        ),
        lambda db: db.resolve_binding_sync_candidate(
            tenant_id=TENANT,
            project_id=PROJECT,
            binding_id=BINDING,
            candidate_id=CANDIDATE,
            status="applied",
            actor_id=ALICE,
            to_digest="   ",
        ),
        lambda db: db.get_draft_binding(tenant_id=TENANT, project_id=PROJECT, binding_id=NOT_A_UUID),
        lambda db: db.find_active_bindings_for_repository_ref(repository_id=NOT_A_UUID, ref="main"),
        lambda db: db.find_active_bindings_for_repository_ref(repository_id=REPOSITORY, ref="  "),
    ],
)
def test_a_malformed_argument_never_reaches_the_database(monkeypatch, call):
    database = database_with(monkeypatch, None)
    assert not call(database)


# ---------------------------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------------------------


def test_a_bind_locks_the_current_binding_and_audits_inside_one_transaction(monkeypatch):
    conn = ScriptedConnection([[], [{"id": BINDING}], []])
    database = database_with(monkeypatch, conn)

    produced = database.insert_draft_binding(**_bind_kwargs())
    assert produced == {"binding_id": BINDING, "released_binding_id": None}
    statements = _sql(conn)
    assert "FOR UPDATE" in statements[0]
    assert "INSERT INTO apiome.draft_repository_bindings" in statements[1]
    assert "INSERT INTO apiome.workflow_audit" in statements[2]
    assert (conn.commits, conn.rollbacks) == (1, 0)
    assert conn.autocommit is True


def test_an_already_bound_version_writes_nothing_and_rolls_back(monkeypatch):
    conn = ScriptedConnection([[{"id": BINDING}]])
    database = database_with(monkeypatch, conn)

    assert database.insert_draft_binding(**_bind_kwargs()) is None
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_replacing_releases_the_old_row_before_inserting_and_audits_a_rebind(monkeypatch):
    conn = ScriptedConnection([[{"id": "old"}], [], [{"id": BINDING}], []])
    database = database_with(monkeypatch, conn)

    produced = database.insert_draft_binding(**_bind_kwargs(replace=True))
    assert produced == {"binding_id": BINDING, "released_binding_id": "old"}
    statements = _sql(conn)
    assert "UPDATE apiome.draft_repository_bindings" in statements[1]
    assert "release_reason = %s" in statements[1]
    _audit_sql, audit_params = conn.statements[3]
    assert audit_params[3] == "binding.rebound"
    assert '"released_binding_id": "old"' in audit_params[5]
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_the_unique_index_losing_a_race_is_answered_none_not_raised(monkeypatch):
    class Colliding(ScriptedConnection):
        """A connection whose insert collides on the one-active-binding index."""

        def cursor(self) -> Any:
            cursor = super().cursor()
            execute = cursor.execute

            def guarded(sql: str, params: Optional[Any] = None) -> None:
                if "INSERT INTO apiome.draft_repository_bindings" in sql:
                    self.statements.append((" ".join(sql.split()), params))
                    raise pg_errors.UniqueViolation("duplicate key")
                execute(sql, params)

            cursor.execute = guarded  # type: ignore[method-assign]
            return cursor

    conn = Colliding([[]])
    database = database_with(monkeypatch, conn)

    assert database.insert_draft_binding(**_bind_kwargs()) is None
    assert _matching(conn, "INSERT INTO apiome.workflow_audit") == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_failed_statement_rolls_the_whole_bind_back(monkeypatch):
    conn = ScriptedConnection([[], [{"id": BINDING}]], fail_on=3)
    database = database_with(monkeypatch, conn)

    with pytest.raises(psycopg2.DatabaseError):
        database.insert_draft_binding(**_bind_kwargs())
    assert (conn.commits, conn.rollbacks) == (0, 1)
    assert conn.autocommit is True


# ---------------------------------------------------------------------------------------------
# Releasing
# ---------------------------------------------------------------------------------------------


def test_a_release_supersedes_its_candidates_and_audits_in_the_same_transaction(monkeypatch):
    conn = ScriptedConnection([[{"version_id": VERSION, "ref": "main", "commit_sha": COMMIT_ONE}], [{}, {}], []])
    database = database_with(monkeypatch, conn)

    assert (
        database.release_draft_binding(
            tenant_id=TENANT, project_id=PROJECT, binding_id=BINDING, actor_id=ALICE, reason="unbound"
        )
        is True
    )
    statements = _sql(conn)
    assert "UPDATE apiome.draft_repository_bindings" in statements[0]
    assert "status = 'superseded'" in statements[1]
    _audit_sql, audit_params = conn.statements[2]
    assert audit_params[3] == "binding.released"
    assert '"candidates_superseded": 2' in audit_params[5]
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_releasing_an_already_released_binding_writes_nothing(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert (
        database.release_draft_binding(
            tenant_id=TENANT, project_id=PROJECT, binding_id=BINDING, actor_id=ALICE, reason="unbound"
        )
        is False
    )
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_de_registering_a_repository_releases_its_bindings_in_the_same_transaction(monkeypatch):
    conn = ScriptedConnection(
        [
            [{"id": REPOSITORY}],
            [{"id": BINDING, "project_id": PROJECT, "version_id": VERSION, "ref": "main", "commit_sha": COMMIT_ONE}],
            [{}],
            [],
        ]
    )
    database = database_with(monkeypatch, conn)

    assert database.delete_tenant_repository(TENANT, REPOSITORY) is True
    statements = _sql(conn)
    assert "UPDATE apiome.tenant_repositories" in statements[0]
    assert "UPDATE apiome.draft_repository_bindings" in statements[1]
    assert "status = 'superseded'" in statements[2]
    _audit_sql, audit_params = conn.statements[3]
    assert audit_params[3] == "binding.released"
    assert audit_params[4] is None, "nobody released these personally; the registration went away"
    assert '"reason": "repository_removed"' in audit_params[5]
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_de_registering_an_unknown_repository_touches_no_binding(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert database.delete_tenant_repository(TENANT, REPOSITORY) is False
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


# ---------------------------------------------------------------------------------------------
# Sync candidates
# ---------------------------------------------------------------------------------------------


def _locked_binding(released: bool = False, commit_sha: str = COMMIT_ONE) -> dict:
    """The row :meth:`Database._lock_draft_binding` answers with."""
    return {
        "project_id": PROJECT,
        "version_id": VERSION,
        "ref": "main",
        "path": "spec",
        "commit_sha": commit_sha,
        "source_digest": "sha256:one",
        "released": released,
    }


def test_raising_a_candidate_locks_the_binding_supersedes_the_rest_and_audits(monkeypatch):
    conn = ScriptedConnection([[_locked_binding()], [{"id": CANDIDATE}], [{}], []])
    database = database_with(monkeypatch, conn)

    produced = database.raise_binding_sync_candidate(
        tenant_id=TENANT,
        binding_id=BINDING,
        to_commit_sha=COMMIT_TWO,
        origin="webhook",
        delivery_id="d1",
    )
    assert produced == {"candidate_id": CANDIDATE, "superseded": 1}
    statements = _sql(conn)
    assert "FOR UPDATE" in statements[0]
    assert "ON CONFLICT DO NOTHING" in statements[1]
    assert "status = 'superseded'" in statements[2]
    _audit_sql, audit_params = conn.statements[3]
    assert audit_params[3] == "binding.sync_candidate"
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_a_released_binding_takes_no_candidate(monkeypatch):
    conn = ScriptedConnection([[_locked_binding(released=True)]])
    database = database_with(monkeypatch, conn)

    assert (
        database.raise_binding_sync_candidate(
            tenant_id=TENANT, binding_id=BINDING, to_commit_sha=COMMIT_TWO, origin="webhook"
        )
        is None
    )
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_commit_the_binding_is_already_at_raises_nothing(monkeypatch):
    conn = ScriptedConnection([[_locked_binding(commit_sha=COMMIT_TWO)]])
    database = database_with(monkeypatch, conn)

    assert (
        database.raise_binding_sync_candidate(
            tenant_id=TENANT, binding_id=BINDING, to_commit_sha=COMMIT_TWO, origin="sweep"
        )
        is None
    )
    assert len(conn.statements) == 1


def test_a_conflicting_insert_leaves_no_audit_row(monkeypatch):
    conn = ScriptedConnection([[_locked_binding()], []])
    database = database_with(monkeypatch, conn)

    assert (
        database.raise_binding_sync_candidate(
            tenant_id=TENANT, binding_id=BINDING, to_commit_sha=COMMIT_TWO, origin="webhook", delivery_id="d1"
        )
        is None
    )
    assert _matching(conn, "INSERT INTO apiome.workflow_audit") == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_applying_advances_the_binding_and_dismissing_leaves_it(monkeypatch):
    applied = ScriptedConnection(
        [[_locked_binding()], [{"to_commit_sha": COMMIT_TWO, "from_commit_sha": COMMIT_ONE}], [], []]
    )
    database = database_with(monkeypatch, applied)
    result = database.resolve_binding_sync_candidate(
        tenant_id=TENANT,
        project_id=PROJECT,
        binding_id=BINDING,
        candidate_id=CANDIDATE,
        status="applied",
        actor_id=ALICE,
        to_digest="sha256:two",
    )
    assert result == {"candidate_id": CANDIDATE, "commit_sha": COMMIT_TWO, "source_digest": "sha256:two"}
    assert _matching(applied, "UPDATE apiome.draft_repository_bindings")
    assert (applied.commits, applied.rollbacks) == (1, 0)

    dismissed = ScriptedConnection(
        [[_locked_binding()], [{"to_commit_sha": COMMIT_TWO, "from_commit_sha": COMMIT_ONE}], []]
    )
    database = database_with(monkeypatch, dismissed)
    result = database.resolve_binding_sync_candidate(
        tenant_id=TENANT,
        project_id=PROJECT,
        binding_id=BINDING,
        candidate_id=CANDIDATE,
        status="dismissed",
        actor_id=ALICE,
    )
    assert result == {"candidate_id": CANDIDATE, "commit_sha": COMMIT_ONE, "source_digest": "sha256:one"}
    assert _matching(dismissed, "UPDATE apiome.draft_repository_bindings") == []
    assert (dismissed.commits, dismissed.rollbacks) == (1, 0)


def test_settling_a_candidate_that_is_no_longer_pending_writes_nothing(monkeypatch):
    conn = ScriptedConnection([[_locked_binding()], []])
    database = database_with(monkeypatch, conn)

    assert (
        database.resolve_binding_sync_candidate(
            tenant_id=TENANT,
            project_id=PROJECT,
            binding_id=BINDING,
            candidate_id=CANDIDATE,
            status="dismissed",
            actor_id=ALICE,
        )
        is None
    )
    assert _matching(conn, "INSERT INTO apiome.workflow_audit") == []
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_binding_of_another_project_cannot_be_settled_through_it(monkeypatch):
    conn = ScriptedConnection([[dict(_locked_binding(), project_id="0a1b2c30-1111-4222-8333-0000000000ff")]])
    database = database_with(monkeypatch, conn)

    assert (
        database.resolve_binding_sync_candidate(
            tenant_id=TENANT,
            project_id=PROJECT,
            binding_id=BINDING,
            candidate_id=CANDIDATE,
            status="dismissed",
            actor_id=ALICE,
        )
        is None
    )
    assert len(conn.statements) == 1
