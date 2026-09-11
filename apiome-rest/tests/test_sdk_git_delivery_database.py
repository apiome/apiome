"""SQL accessors for git delivery — SDK-4.2 (#4496).

The suite runs against a live Postgres, so these tests assert only the properties that must hold
**before** a statement is sent (the id guards) plus the shape of the SQL itself, with the driver
patched. Whether V257's constraints accept the rows is a schema question, asserted by the migration
guardrails and against a real database.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.database import db

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REPOSITORY = "55555555-5555-4555-8555-555555555555"
_RUN = "44444444-4444-4444-8444-444444444444"


def _connection(row=None):
    """A patched connection whose cursor returns ``row`` and records the statement."""
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


# ===========================================================================
# Guards: a malformed id never reaches the driver
# ===========================================================================
def test_a_non_uuid_id_never_reaches_the_database() -> None:
    with patch.object(db, "execute_query") as query:
        assert db.list_sdk_git_delivery_targets("not-a-uuid", _PROJECT) == []
        assert db.get_sdk_git_delivery_target(_TENANT, "not-a-uuid", "npm") is None
        assert db.list_sdk_git_delivery_runs("not-a-uuid", _PROJECT) == []
        assert db.count_sdk_git_delivery_runs(_TENANT, "not-a-uuid") == 0
        assert db.get_sdk_git_delivery_run("not-a-uuid", _TENANT) is None
    query.assert_not_called()

    with patch.object(db, "connect") as connect:
        assert (
            db.upsert_sdk_git_delivery_target(
                tenant_id=_TENANT,
                project_id=_PROJECT,
                ecosystem="npm",
                repository_id="not-a-uuid",
                base_branch=None,
                target_path="",
            )
            is None
        )
        assert (
            db.insert_sdk_git_delivery_run(
                tenant_id="not-a-uuid",
                project_id=_PROJECT,
                version_id=None,
                target_id=None,
                repository_id=None,
                ecosystem="npm",
                status="in_progress",
            )
            is None
        )
        assert db.finish_sdk_git_delivery_run(_RUN, "not-a-uuid", status="failed") is None
    connect.assert_not_called()

    with patch.object(db, "_execute_write") as write:
        assert db.delete_sdk_git_delivery_target("not-a-uuid", _PROJECT, "npm") == 0
    write.assert_not_called()


# ===========================================================================
# Shape
# ===========================================================================
def test_target_reads_join_only_live_repositories_of_the_same_tenant() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_git_delivery_targets(_TENANT, _PROJECT)
    sql = query.call_args.args[0]
    assert "LEFT JOIN apiome.tenant_repositories r" in sql
    assert "r.tenant_id = t.tenant_id AND r.deleted_at IS NULL" in sql
    assert "(r.linked_account_id IS NOT NULL) AS repository_has_linked_account" in sql
    # The linked account's token is never selected by a target read.
    assert "access_token" not in sql
    assert query.call_args.args[1] == (_TENANT, _PROJECT)


def test_the_target_upsert_replaces_the_one_row_per_project_and_ecosystem() -> None:
    conn, cursor = _connection({"id": "t"})
    with patch.object(db, "connect", return_value=conn):
        row = db.upsert_sdk_git_delivery_target(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            ecosystem="npm",
            repository_id=_REPOSITORY,
            base_branch="develop",
            target_path="sdks/ts",
            actor_id="not-a-uuid",
        )
    assert row == {"id": "t"}
    sql, params = cursor.execute.call_args.args
    assert "ON CONFLICT (tenant_id, project_id, ecosystem)" in sql
    assert "LEFT JOIN apiome.tenant_repositories r" in sql
    # A non-UUID actor is recorded as NULL rather than failing the cast.
    assert params == (_TENANT, _PROJECT, "npm", _REPOSITORY, "develop", "sdks/ts", None, None)
    conn.commit.assert_called_once()


def test_a_failed_write_rolls_back() -> None:
    conn, cursor = _connection()
    cursor.execute.side_effect = RuntimeError("constraint")
    with patch.object(db, "connect", return_value=conn):
        try:
            db.insert_sdk_git_delivery_run(
                tenant_id=_TENANT,
                project_id=_PROJECT,
                version_id=None,
                target_id=None,
                repository_id=None,
                ecosystem="npm",
                status="in_progress",
            )
        except RuntimeError:
            pass
    conn.rollback.assert_called_once()


def test_a_run_insert_drops_non_uuid_references() -> None:
    conn, cursor = _connection({"id": _RUN})
    with patch.object(db, "connect", return_value=conn):
        db.insert_sdk_git_delivery_run(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            version_id="v-handle",
            target_id="t-handle",
            repository_id=_REPOSITORY,
            ecosystem="npm",
            status="in_progress",
            version_line="1.4.2",
            target_path="sdks/ts",
        )
    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO apiome.sdk_git_delivery_runs" in sql
    assert params[2:5] == (None, None, _REPOSITORY)


def test_finishing_a_run_keeps_what_the_insert_recorded() -> None:
    conn, cursor = _connection({"id": _RUN})
    with patch.object(db, "connect", return_value=conn):
        db.finish_sdk_git_delivery_run(_RUN, _TENANT, status="failed", error_code="x")
    sql, params = cursor.execute.call_args.args
    for column in ("branch_name", "commit_sha", "pull_request_number", "changes", "provenance"):
        assert f"{column} = COALESCE(%s, {column})" in sql
    assert "finished_at = CURRENT_TIMESTAMP" in sql
    assert "WHERE id = %s::uuid AND tenant_id = %s::uuid" in sql
    assert params[-2:] == (_RUN, _TENANT)


def test_run_listing_is_newest_first_and_narrows_by_ecosystem() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_git_delivery_runs(_TENANT, _PROJECT, ecosystem="pypi", limit=0, offset=-3)
    sql, params = query.call_args.args
    assert "ORDER BY started_at DESC, id DESC" in sql
    assert "ecosystem = %s" in sql
    assert params == (_TENANT, _PROJECT, "pypi", 1, 0)


def test_run_reads_are_scoped_to_the_tenant() -> None:
    with patch.object(db, "execute_query", return_value=[{"id": _RUN}]) as query:
        assert db.get_sdk_git_delivery_run(_RUN, _TENANT) == {"id": _RUN}
    assert "WHERE id = %s::uuid AND tenant_id = %s::uuid" in query.call_args.args[0]
