"""Transaction semantics and SQL shape of the GNC-3.1 (#4740) accessors.

:class:`tests.fake_suite_db.FakeSuiteDb` proves the *rules*; it has no transaction and no SQL. These
tests drive the real :class:`app.database.Database` against :mod:`tests.scripted_connection`, so
every statement, commit and rollback is visible: that an evaluation and its audit row commit
together, that a collision writes nothing at all, that each read carries the predicates the
publish gate's correctness depends on, and that GNC-2.2's publish ledger is keyed per outcome.

The SQL text itself was exercised against a scratch database built from the real schema plus V267.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from tests.scripted_connection import ScriptedConnection, database_with

TENANT = "7a1b2c30-5555-4aaa-8bbb-000000000001"
PROJECT = "7a1b2c30-5555-4aaa-8bbb-000000000002"
VERSION = "7a1b2c30-5555-4aaa-8bbb-000000000010"
BINDING = "7a1b2c30-5555-4aaa-8bbb-000000000020"
RUN = "7a1b2c30-5555-4aaa-8bbb-000000000030"
CHECK = "7a1b2c30-5555-4aaa-8bbb-000000000040"
ALICE = "7a1b2c30-5555-4aaa-8bbb-000000000101"
NOT_A_UUID = "not-a-uuid"
COMMIT = "1" * 40


def _run_kwargs(**overrides: Any) -> Dict[str, Any]:
    """The arguments of a well-formed :meth:`Database.insert_check_suite_run` call."""
    return {
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": VERSION,
        "binding_id": BINDING,
        "commit_sha": COMMIT,
        "pr_number": 7,
        "check_name": "apiome/api-change",
        "evaluated": True,
        "state": "fail",
        "reason": "required-component-failed",
        "draft_digest": "sha256:draft",
        "policy_source": "tenant",
        "policy_fingerprint": "sha256:policy",
        "policy": {"components": {}},
        "thresholds_source": "default",
        "thresholds_fingerprint": "sha256:thresholds",
        "thresholds": {"lint": {}},
        "components": [{"component": "lint", "state": "fail"}],
        "input_fingerprint": "sha256:inputs",
        "created_by": ALICE,
        **overrides,
    }


def _sql(conn: ScriptedConnection) -> List[str]:
    """Every statement's collapsed SQL, in order."""
    return [statement for statement, _params in conn.statements]


# ---------------------------------------------------------------------------------------------
# Guards that never reach the database
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda db: db.get_check_suite_policy(NOT_A_UUID, PROJECT),
        lambda db: db.upsert_check_suite_policy(
            tenant_id=NOT_A_UUID, project_id=None, policy={}, content_fingerprint="f"
        ),
        lambda db: db.delete_check_suite_policy(NOT_A_UUID),
        lambda db: db.insert_check_suite_run(**_run_kwargs(tenant_id=NOT_A_UUID)),
        lambda db: db.insert_check_suite_run(**_run_kwargs(version_id=NOT_A_UUID)),
        lambda db: db.insert_check_suite_run(**_run_kwargs(binding_id=NOT_A_UUID)),
        lambda db: db.get_check_suite_run(tenant_id=TENANT, run_id=NOT_A_UUID),
        lambda db: db.find_check_suite_run(
            tenant_id=TENANT, version_id=NOT_A_UUID, input_fingerprint="f"
        ),
        lambda db: db.list_check_suite_runs(tenant_id=NOT_A_UUID, version_id=VERSION),
        lambda db: db.find_current_check_suite_run(
            tenant_id=TENANT,
            version_id=NOT_A_UUID,
            draft_digest="d",
            policy_fingerprint="p",
            thresholds_fingerprint="t",
        ),
        lambda db: db.list_verification_runs_for_revision(TENANT, NOT_A_UUID),
    ],
)
def test_a_malformed_argument_never_reaches_the_database(monkeypatch, call):
    database = database_with(monkeypatch, None)
    assert not call(database)


# ---------------------------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------------------------


def test_an_evaluation_and_its_audit_row_commit_together(monkeypatch):
    conn = ScriptedConnection([[{"id": RUN}], []])
    database = database_with(monkeypatch, conn)

    assert database.insert_check_suite_run(**_run_kwargs()) == {"id": RUN}

    insert_sql, _audit_sql = _sql(conn)
    assert "INSERT INTO apiome.api_check_suite_runs" in insert_sql
    assert "ON CONFLICT (version_id, input_fingerprint) DO NOTHING" in insert_sql
    assert "INSERT INTO apiome.workflow_audit" in _audit_sql
    assert (conn.commits, conn.rollbacks) == (1, 0)
    assert conn.autocommit is True


def test_the_audit_row_names_what_the_evaluation_was_judged_from(monkeypatch):
    conn = ScriptedConnection([[{"id": RUN}], []])
    database = database_with(monkeypatch, conn)

    database.insert_check_suite_run(**_run_kwargs())

    _audit_sql, audit_params = conn.statements[1]
    assert audit_params[3] == "check_suite.evaluated"
    detail = audit_params[5]
    for fragment in (
        RUN,
        COMMIT,
        '"state": "fail"',
        "sha256:draft",
        "sha256:policy",
        "sha256:thresholds",
        "sha256:inputs",
    ):
        assert fragment in detail


def test_evaluating_the_same_inputs_again_writes_nothing(monkeypatch):
    # The ON CONFLICT insert returns no row; no audit row follows and the transaction is dropped.
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    assert database.insert_check_suite_run(**_run_kwargs()) is None
    assert len(conn.statements) == 1
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_an_unbound_unattributed_evaluation_is_still_recorded(monkeypatch):
    conn = ScriptedConnection([[{"id": RUN}], []])
    database = database_with(monkeypatch, conn)

    database.insert_check_suite_run(
        **_run_kwargs(binding_id=None, commit_sha=None, created_by="not-a-user")
    )
    _insert_sql, params = conn.statements[0]
    assert params[3] is None and params[4] is None
    # An id that is not a user is recorded as nobody, never cast into a failure.
    assert params[-1] is None


def test_the_publish_gates_read_matches_content_and_both_policies_and_skips_placeholders(
    monkeypatch,
):
    conn = ScriptedConnection([[{"id": RUN}]])
    database = database_with(monkeypatch, conn)

    row = database.find_current_check_suite_run(
        tenant_id=TENANT,
        version_id=VERSION,
        draft_digest="sha256:draft",
        policy_fingerprint="sha256:policy",
        thresholds_fingerprint="sha256:thresholds",
    )

    assert row == {"id": RUN}
    sql, params = conn.statements[0]
    for fragment in (
        "s.evaluated",
        "s.draft_digest = %s",
        "s.policy_fingerprint = %s",
        "s.thresholds_fingerprint = %s",
        "ORDER BY s.created_at DESC",
        "LIMIT 1",
    ):
        assert fragment in sql
    assert params == (VERSION, TENANT, "sha256:draft", "sha256:policy", "sha256:thresholds")


def test_a_versions_evaluations_narrow_by_commit_and_by_whether_they_judged_anything(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    database.list_check_suite_runs(
        tenant_id=TENANT, version_id=VERSION, commit_sha=f" {COMMIT} ", evaluated=False, limit=0
    )

    sql, params = conn.statements[0]
    assert "s.commit_sha = %s" in sql and "s.evaluated = %s" in sql
    assert params == (VERSION, TENANT, COMMIT, False, 1, 0)


def test_reads_join_the_version_label_and_the_evaluators_name(monkeypatch):
    conn = ScriptedConnection([[{"id": RUN}]])
    database = database_with(monkeypatch, conn)

    database.get_check_suite_run(tenant_id=TENANT, run_id=RUN)

    sql, _params = conn.statements[0]
    assert "JOIN apiome.versions v ON v.id = s.version_id" in sql
    assert "v.version_id AS version_label" in sql
    assert "created_by_name" in sql


def test_contract_runs_are_read_by_revision_through_the_v267_index(monkeypatch):
    conn = ScriptedConnection([[]])
    database = database_with(monkeypatch, conn)

    database.list_verification_runs_for_revision(TENANT, VERSION, limit=500)

    sql, params = conn.statements[0]
    # The predicate and the expression repeat the index definition, or the planner will not use it.
    assert "source ? 'revision_id'" in sql
    assert "(source ->> 'revision_id') = %s" in sql
    assert params == (TENANT, VERSION, 50)


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


def test_the_project_override_sorts_ahead_of_the_tenant_policy_in_one_query(monkeypatch):
    conn = ScriptedConnection([[{"id": "p"}]])
    database = database_with(monkeypatch, conn)

    assert database.get_check_suite_policy(TENANT, PROJECT) == {"id": "p"}
    sql, params = conn.statements[0]
    assert "(project_id = %s::uuid OR project_id IS NULL)" in sql
    assert "ORDER BY project_id NULLS LAST" in sql
    assert params == (TENANT, PROJECT)


@pytest.mark.parametrize(
    ("project_id", "target"),
    [
        (None, "ON CONFLICT (tenant_id) WHERE project_id IS NULL"),
        (PROJECT, "ON CONFLICT (tenant_id, project_id) WHERE project_id IS NOT NULL"),
    ],
)
def test_each_scope_upserts_through_its_own_partial_index(monkeypatch, project_id, target):
    conn = ScriptedConnection([[{"id": "p"}]])
    database = database_with(monkeypatch, conn)

    database.upsert_check_suite_policy(
        tenant_id=TENANT,
        project_id=project_id,
        policy={"components": {}},
        content_fingerprint="sha256:p",
        actor_id=ALICE,
    )

    assert target in conn.statements[0][0]
    assert conn.commits == 1


# ---------------------------------------------------------------------------------------------
# GNC-2.2's publish ledger, re-keyed by V267
# ---------------------------------------------------------------------------------------------


def test_a_publish_attempt_collides_only_with_the_same_outcome_of_the_same_verdict(monkeypatch):
    check = {"id": CHECK, "project_id": PROJECT, "version_id": VERSION, "name": "n"}
    conn = ScriptedConnection([[check], [{"id": "d1"}], []])
    database = database_with(monkeypatch, conn)

    database.record_provider_check_delivery(
        tenant_id=TENANT,
        check_run_id=CHECK,
        provider="github",
        state="pass",
        request_fingerprint="sha256:verdict",
        outcome="dispatched",
        status_code=201,
    )

    insert_sql = conn.statements[1][0]
    assert "ON CONFLICT (check_run_id, request_fingerprint, outcome) DO NOTHING" in insert_sql


def test_a_verdicts_dispatch_is_read_ahead_of_its_failures(monkeypatch):
    conn = ScriptedConnection([[{"outcome": "dispatched"}]])
    database = database_with(monkeypatch, conn)

    database.find_provider_check_delivery(check_run_id=CHECK, request_fingerprint="sha256:v")

    sql = conn.statements[0][0]
    assert "ORDER BY (d.outcome = 'dispatched') DESC" in sql
    assert "LIMIT 1" in sql
