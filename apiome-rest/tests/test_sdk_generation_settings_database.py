"""SQL accessors for generation settings — SDK-3.4 (#4494).

The suite runs against a live Postgres, so these tests assert only the properties that must hold
**before** a statement is sent (the id guards), plus the shape of the SQL itself with
``execute_query`` patched. Whether V255's partial unique indexes actually accept the upserts is
asserted in ``apiome-db/test/sdk-generation-settings.test.ts`` against the real schema.
"""

from __future__ import annotations

from unittest.mock import patch

from app.database import db

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"


# ===========================================================================
# Guards: a malformed id never reaches the driver
# ===========================================================================


def test_a_non_uuid_tenant_never_reaches_the_database() -> None:
    with patch.object(db, "execute_query") as query:
        assert db.get_sdk_generation_settings_rows("not-a-uuid", _PROJECT) == []
    query.assert_not_called()

    with patch.object(db, "connect") as connect:
        assert (
            db.upsert_sdk_generation_settings(
                tenant_id="not-a-uuid",
                project_id=None,
                settings={},
                content_fingerprint="sha256:0",
            )
            is None
        )
    connect.assert_not_called()

    with patch.object(db, "_execute_write") as write:
        assert db.delete_sdk_generation_settings("not-a-uuid") == 0
    write.assert_not_called()


def test_a_non_uuid_project_falls_back_to_the_tenant_row() -> None:
    """A malformed reference must not silently read some other project's settings."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_generation_settings_rows(_TENANT, "not-a-uuid")
    sql, params = query.call_args.args[0], query.call_args.args[1]
    assert "project_id IS NULL" in sql
    assert params == (_TENANT,)


def test_a_non_uuid_project_delete_targets_the_tenant_row() -> None:
    with patch.object(db, "_execute_write", return_value=0) as write:
        db.delete_sdk_generation_settings(_TENANT, "not-a-uuid")
    assert "project_id IS NULL" in write.call_args.args[0]
    assert write.call_args.args[1] == (_TENANT,)


# ===========================================================================
# SQL shape
# ===========================================================================


def test_a_project_read_asks_for_both_scopes_in_one_query() -> None:
    """SDK-3.4 merges key by key, so it needs both rows — not just the winner."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_generation_settings_rows(_TENANT, _PROJECT)
    sql, params = query.call_args.args[0], query.call_args.args[1]
    assert "project_id = %s::uuid OR project_id IS NULL" in sql
    assert "ORDER BY project_id NULLS FIRST" in sql
    assert "LIMIT" not in sql
    assert params == (_TENANT, _PROJECT)


def test_the_read_selects_the_shared_column_list() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_generation_settings_rows(_TENANT)
    sql = query.call_args.args[0]
    for column in ("id::text", "settings", "content_fingerprint", "updated_at"):
        assert column in sql


def test_each_scope_upserts_against_its_own_partial_index() -> None:
    """``ON CONFLICT`` names one index at a time, so the two scopes need two statements."""
    executed: list[str] = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params):
            executed.append(sql)

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def rollback(self):
            return None

    with patch.object(db, "connect", return_value=_Conn()):
        db.upsert_sdk_generation_settings(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            settings={},
            content_fingerprint="sha256:0",
        )
        db.upsert_sdk_generation_settings(
            tenant_id=_TENANT,
            project_id=None,
            settings={},
            content_fingerprint="sha256:0",
        )

    assert "ON CONFLICT (tenant_id, project_id) WHERE project_id IS NOT NULL" in executed[0]
    assert "ON CONFLICT (tenant_id) WHERE project_id IS NULL" in executed[1]
    for sql in executed:
        assert "updated_at = CURRENT_TIMESTAMP" in sql
        assert "RETURNING" in sql


def test_a_non_uuid_actor_is_stored_as_null_rather_than_failing_the_write() -> None:
    """An API key without a user must still be able to save settings."""
    captured: list[tuple] = []

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _sql, params):
            captured.append(params)

        def fetchone(self):
            return None

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            return None

        def rollback(self):
            return None

    with patch.object(db, "connect", return_value=_Conn()):
        db.upsert_sdk_generation_settings(
            tenant_id=_TENANT,
            project_id=None,
            settings={},
            content_fingerprint="sha256:0",
            actor_id="service-account",
        )
    assert captured[0][-1] is None
    assert captured[0][-2] is None


def test_a_project_delete_names_both_columns() -> None:
    with patch.object(db, "_execute_write", return_value=1) as write:
        db.delete_sdk_generation_settings(_TENANT, _PROJECT)
    sql, params = write.call_args.args[0], write.call_args.args[1]
    assert "tenant_id = %s::uuid AND project_id = %s::uuid" in sql
    assert params == (_TENANT, _PROJECT)


def test_the_public_snippet_projection_exposes_the_tenant() -> None:
    """SDK-3.4's anonymous branding read: the slug-addressed caller learns no tenant otherwise."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_public_version_source_projection("acme", "petstore", "1.0.0")
    assert "t.id AS tenant_id" in query.call_args.args[0]
