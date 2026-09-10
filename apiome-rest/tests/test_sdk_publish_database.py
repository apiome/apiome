"""SQL accessors for package publishing — SDK-4.1 (#4495).

The suite runs against a live Postgres, so these tests assert only the properties that must hold
**before** a statement is sent (the id guards) plus the shape of the SQL itself, with the driver
patched. Whether V256's partial indexes actually accept the upserts and reject a double claim is a
schema question, and is asserted against the real schema rather than here.
"""

from __future__ import annotations

from unittest.mock import patch

from app.database import db

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"


# ===========================================================================
# Guards: a malformed id never reaches the driver
# ===========================================================================
def test_a_non_uuid_tenant_never_reaches_the_database() -> None:
    with patch.object(db, "execute_query") as query:
        assert db.get_sdk_registry_credentials("not-a-uuid", _PROJECT) == []
        assert db.next_sdk_publish_counter("not-a-uuid", _PROJECT, "npm", "1.4") == 0
        assert db.list_sdk_publish_runs("not-a-uuid", _PROJECT) == []
        assert db.count_sdk_publish_runs("not-a-uuid", _PROJECT) == 0
        assert db.get_sdk_publish_run(_RUN, "not-a-uuid") is None
    query.assert_not_called()

    with patch.object(db, "connect") as connect:
        assert (
            db.upsert_sdk_registry_credential(
                tenant_id="not-a-uuid",
                project_id=None,
                ecosystem="npm",
                registry_url="https://registry.npmjs.org",
                encrypted_token=b"blob",
                key_version=1,
                token_metadata={},
            )
            is None
        )
        assert (
            db.insert_sdk_publish_run(
                tenant_id="not-a-uuid",
                project_id=_PROJECT,
                version_id=_REVISION,
                ecosystem="npm",
                status="dry_run",
                dry_run=True,
                version_line="1.4",
                release_series="1.4",
                regen_counter=0,
                package_name="@acme/widgets-sdk",
                package_version="1.4.0",
            )
            is None
        )
        assert (
            db.finish_sdk_publish_run(_RUN, "not-a-uuid", status="published") is None
        )
    connect.assert_not_called()

    with patch.object(db, "_execute_write") as write:
        assert db.delete_sdk_registry_credential("not-a-uuid", "npm") == 0
    write.assert_not_called()


def test_a_non_uuid_project_reads_only_the_tenant_credential() -> None:
    """A malformed reference must not silently read some other project's credential."""
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_registry_credentials(_TENANT, "not-a-uuid")
    sql, params = query.call_args.args[0], query.call_args.args[1]
    assert "project_id IS NULL" in sql
    assert params == (_TENANT,)


def test_a_non_uuid_project_delete_targets_the_tenant_credential() -> None:
    with patch.object(db, "_execute_write", return_value=0) as write:
        db.delete_sdk_registry_credential(_TENANT, "npm", "not-a-uuid")
    assert "project_id IS NULL" in write.call_args.args[0]
    assert write.call_args.args[1] == (_TENANT, "npm")


# ===========================================================================
# The counter query
# ===========================================================================
def test_the_counter_counts_only_rows_that_claimed_a_version() -> None:
    """A ``failed`` or ``dry_run`` row never consumed a number, so it must not raise the counter."""
    with patch.object(db, "execute_query", return_value=[{"next_counter": 4}]) as query:
        assert db.next_sdk_publish_counter(_TENANT, _PROJECT, "npm", "1.4") == 4
    sql = query.call_args.args[0]
    assert "MAX(regen_counter) + 1" in sql
    assert "status IN ('in_progress', 'published', 'already_published')" in sql
    assert query.call_args.args[1] == (_TENANT, _PROJECT, "npm", "1.4")


def test_a_series_with_no_history_starts_at_zero() -> None:
    with patch.object(db, "execute_query", return_value=[]):
        assert db.next_sdk_publish_counter(_TENANT, _PROJECT, "npm", "9.9") == 0


# ===========================================================================
# Scoping and shape
# ===========================================================================
def test_a_project_read_returns_both_scopes_tenant_first() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_registry_credentials(_TENANT, _PROJECT, ecosystem="npm")
    sql = query.call_args.args[0]
    assert "(project_id = %s::uuid OR project_id IS NULL)" in sql
    assert "ORDER BY project_id NULLS FIRST" in sql
    assert query.call_args.args[1] == (_TENANT, _PROJECT, "npm")


def test_the_two_credential_upserts_name_their_own_partial_index() -> None:
    """``ON CONFLICT`` names one index at a time, so each scope needs its own statement."""
    for project_id, expected in (
        (None, "ON CONFLICT (tenant_id, ecosystem) WHERE project_id IS NULL"),
        (
            _PROJECT,
            "ON CONFLICT (tenant_id, project_id, ecosystem) WHERE project_id IS NOT NULL",
        ),
    ):
        with patch.object(db, "connect") as connect:
            cursor = connect.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = {"id": "row"}
            db.upsert_sdk_registry_credential(
                tenant_id=_TENANT,
                project_id=project_id,
                ecosystem="npm",
                registry_url="https://registry.npmjs.org",
                encrypted_token=b"blob",
                key_version=1,
                token_metadata={"token_length": 24},
            )
        assert expected in cursor.execute.call_args.args[0]


def test_the_run_history_is_newest_first_and_bounded() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_publish_runs(_TENANT, _PROJECT, ecosystem="npm", limit=10, offset=20)
    sql = query.call_args.args[0]
    assert "ORDER BY started_at DESC" in sql
    assert "LIMIT %s OFFSET %s" in sql
    assert query.call_args.args[1] == (_TENANT, _PROJECT, "npm", 10, 20)


def test_a_nonsense_page_is_clamped_rather_than_sent() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_publish_runs(_TENANT, _PROJECT, limit=0, offset=-5)
    assert query.call_args.args[1][-2:] == (1, 0)


def test_a_run_is_read_within_its_tenant() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.get_sdk_publish_run(_RUN, _TENANT)
    assert "WHERE id = %s::uuid AND tenant_id = %s::uuid" in query.call_args.args[0]
    assert query.call_args.args[1] == (_RUN, _TENANT)


def test_finishing_a_run_stamps_it_and_keeps_the_digest_when_none_is_given() -> None:
    with patch.object(db, "connect") as connect:
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"id": _RUN}
        db.finish_sdk_publish_run(_RUN, _TENANT, status="published")
    sql = cursor.execute.call_args.args[0]
    assert "finished_at = CURRENT_TIMESTAMP" in sql
    assert "artifact_sha256 = COALESCE(%s, artifact_sha256)" in sql
    # The provenance is written at close-out, not at insert: the archive does not exist until
    # after the version number has been claimed.
    assert "provenance = COALESCE(%s, provenance)" in sql


def test_an_unfinished_insert_leaves_finished_at_null() -> None:
    """An ``in_progress`` claim is open by definition; only its close-out stamps a finish."""
    for finished, expected in ((False, "NULL, %s::uuid"), (True, "CURRENT_TIMESTAMP, %s::uuid")):
        with patch.object(db, "connect") as connect:
            cursor = connect.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = {"id": _RUN}
            db.insert_sdk_publish_run(
                tenant_id=_TENANT,
                project_id=_PROJECT,
                version_id=_REVISION,
                ecosystem="npm",
                status="in_progress",
                dry_run=False,
                version_line="1.4",
                release_series="1.4",
                regen_counter=0,
                package_name="@acme/widgets-sdk",
                package_version="1.4.0",
                finished=finished,
            )
        assert expected in cursor.execute.call_args.args[0]


def test_a_non_uuid_revision_is_stored_as_null_rather_than_refusing() -> None:
    """A run must be recordable even when its revision reference is not a UUID."""
    with patch.object(db, "connect") as connect:
        cursor = connect.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"id": _RUN}
        db.insert_sdk_publish_run(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            version_id="not-a-uuid",
            ecosystem="npm",
            status="dry_run",
            dry_run=True,
            version_line="1.4",
            release_series="1.4",
            regen_counter=0,
            package_name="@acme/widgets-sdk",
            package_version="1.4.0",
        )
    assert cursor.execute.call_args.args[1][2] is None
