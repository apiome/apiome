"""SQL accessors for auto-regen on publish — SDK-4.3 (#4497).

The suite runs against a live Postgres, so these tests assert only the properties that must hold
**before** a statement is sent (the id guards) plus the shape of the SQL itself, with the driver
patched. The statements were also exercised end to end against a scratch database carrying V258
(claim ordering, the claim token, the lease sweep, the compare-and-set retry, the attempts cap).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from unittest.mock import patch

from app.database import db

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_VERSION = "33333333-3333-4333-8333-333333333333"
_JOB = "44444444-4444-4444-8444-444444444444"
_TOKEN = "55555555-5555-4555-8555-555555555555"
_USER = "66666666-6666-4666-8666-666666666666"
_RUN = "77777777-7777-4777-8777-777777777777"


def _finish_kwargs(**overrides):
    """Every column an attempt close-out takes, spelled out."""
    kwargs = dict(
        status="succeeded",
        next_attempt_at=None,
        delivery_mode="registry_and_git",
        options={"dryRun": False},
        publish_run_id=_RUN,
        publish_status="published",
        delivery_run_id="not-a-uuid",
        delivery_status="opened",
        package_name="@acme/widgets-sdk",
        package_version="1.4.0",
        regen_counter=0,
        artifact_sha256="a" * 64,
        pull_request_number=7,
        pull_request_url="https://github.com/acme/widgets-sdk/pull/7",
        error_step=None,
        error_code=None,
        error_message=None,
        attempt={"attempt": 1},
        max_attempt_entries=50,
        worker_lost_code="sdk-regen-worker-lost",
    )
    kwargs.update(overrides)
    return kwargs


def _finish(**overrides):
    """Close an attempt of ``_JOB`` under ``_TOKEN``."""
    return db.finish_sdk_regen_job_attempt(_JOB, _TOKEN, **_finish_kwargs(**overrides))


# ===========================================================================
# Guards: a malformed id never reaches the driver
# ===========================================================================
def test_a_non_uuid_id_never_reaches_the_database() -> None:
    with patch.object(db, "execute_query") as query:
        assert db.list_sdk_regen_subscriptions("not-a-uuid", _PROJECT) == []
        assert db.get_sdk_regen_subscription(_TENANT, "not-a-uuid", "npm") is None
        assert (
            db.upsert_sdk_regen_subscription(
                tenant_id="t1",
                project_id=_PROJECT,
                ecosystem="npm",
                delivery_mode="git",
                options={},
                active=True,
            )
            is None
        )
        assert db.set_sdk_regen_subscription_active(_TENANT, "p1", "npm", active=False) is None
        assert (
            db.enqueue_sdk_regen_run(
                tenant_id=_TENANT,
                project_id="pid-1",
                version_id=_VERSION,
                version_line="1.4.2",
                published_by=None,
            )
            == []
        )
        assert db.claim_next_sdk_regen_job("not-a-token") is None
        assert db.finish_sdk_regen_job_attempt("not-a-uuid", _TOKEN, **_finish_kwargs()) is None
        assert db.finish_sdk_regen_job_attempt(_JOB, "not-a-token", **_finish_kwargs()) is None
        assert db.list_sdk_regen_runs(_TENANT, "not-a-uuid") == []
        assert db.count_sdk_regen_runs("not-a-uuid", _PROJECT) == 0
        assert db.get_sdk_regen_run(_TENANT, _PROJECT, "not-a-uuid") is None
        assert db.list_sdk_regen_jobs_for_runs(_TENANT, ["not-a-uuid"]) == []
        assert db.list_sdk_regen_jobs_for_runs("not-a-uuid", [_RUN]) == []
        assert db.get_sdk_regen_job(_TENANT, "not-a-uuid") is None
        assert db.retry_sdk_regen_job(_TENANT, _PROJECT, "not-a-uuid") is None
    query.assert_not_called()

    with patch.object(db, "_execute_write") as write:
        assert db.delete_sdk_regen_subscription("not-a-uuid", _PROJECT, "npm") == 0
        assert (
            db.save_sdk_regen_job_progress(
                _JOB,
                "not-a-token",
                publish_run_id=None,
                publish_status="published",
                package_name=None,
                package_version=None,
                regen_counter=0,
                artifact_sha256=None,
            )
            == 0
        )
    write.assert_not_called()


# ===========================================================================
# Shape
# ===========================================================================
def test_the_subscription_upsert_replaces_the_one_row_per_project_and_ecosystem() -> None:
    with patch.object(db, "execute_query", return_value=[{"id": "s"}]) as query:
        row = db.upsert_sdk_regen_subscription(
            tenant_id=_TENANT,
            project_id=_PROJECT,
            ecosystem="npm",
            delivery_mode="registry",
            options={"dryRun": True},
            active=True,
            actor_id="not-a-uuid",
        )
    assert row == {"id": "s"}
    sql, params = query.call_args.args
    assert "ON CONFLICT (tenant_id, project_id, ecosystem)" in sql
    assert "delivery_mode = EXCLUDED.delivery_mode" in sql
    assert params[:4] == (_TENANT, _PROJECT, "npm", "registry")
    assert params[4].adapted == {"dryRun": True}
    # A non-UUID actor is recorded as NULL rather than failing the cast.
    assert params[5:] == (True, None, None)


def test_enqueue_writes_the_run_and_its_jobs_in_one_statement_only_for_active_subscriptions() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        assert (
            db.enqueue_sdk_regen_run(
                tenant_id=_TENANT,
                project_id=_PROJECT,
                version_id=_VERSION,
                version_line="1.4.2",
                published_by="not-a-uuid",
            )
            == []
        )
    sql, params = query.call_args.args
    assert "WITH subscriptions AS" in sql
    assert "AND active" in sql
    assert "WHERE EXISTS (SELECT 1 FROM subscriptions)" in sql
    assert "INSERT INTO apiome.sdk_regen_runs" in sql
    assert "INSERT INTO apiome.sdk_regen_jobs" in sql
    assert "'pending', CURRENT_TIMESTAMP" in sql
    assert params == (_TENANT, _PROJECT, _TENANT, _PROJECT, _VERSION, "1.4.2", None)


def test_the_claim_skips_locked_rows_and_keeps_a_subscriptions_publishes_in_order() -> None:
    with patch.object(db, "execute_query", return_value=[{"id": _JOB}]) as query:
        assert db.claim_next_sdk_regen_job(_TOKEN) == {"id": _JOB}
    sql, params = query.call_args.args
    assert "FOR UPDATE OF j SKIP LOCKED" in sql
    assert "j.status IN ('pending', 'retrying')" in sql
    assert "j.next_attempt_at <= CURRENT_TIMESTAMP" in sql
    # In order within a subscription, and only within one.
    assert "earlier.subscription_id = j.subscription_id" in sql
    assert "earlier.status IN ('pending', 'running', 'retrying')" in sql
    assert "(earlier.created_at, earlier.id) < (j.created_at, j.id)" in sql
    assert "attempt_count = j.attempt_count + 1" in sql
    assert "claim_token = %s::uuid" in sql
    # What running the job needs, including the subscription as it is now.
    for column in ("t.slug AS tenant_slug", "p.slug AS project_slug", "s.active AS subscription_active"):
        assert column in sql
    assert "LEFT JOIN apiome.sdk_regen_subscriptions s" in sql
    assert params == (_TOKEN,)


def test_closing_an_attempt_matches_only_its_own_claim() -> None:
    with patch.object(db, "execute_query", return_value=[{"id": _JOB}]) as query:
        _finish(next_attempt_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    sql, params = query.call_args.args
    assert "WHERE j.id = %s::uuid" in sql
    assert "AND j.claim_token = %s::uuid" in sql
    assert "(j.status = 'running' OR (j.status = 'dead_letter' AND j.error_code = %s))" in sql
    assert "(j.attempts - 0) || %s::jsonb" in sql
    assert params[-3:] == (_JOB, _TOKEN, "sdk-regen-worker-lost")
    # A non-UUID run reference is recorded as NULL rather than failing the cast.
    assert params[4] == _RUN
    assert params[6] is None
    # The attempt is appended as a one-element array, and a terminal status stamps finished_at.
    assert params[17] == 50
    assert params[18].adapted == [{"attempt": 1}]
    assert params[20] is True


def test_saving_registry_progress_writes_only_to_a_claim_that_still_runs() -> None:
    with patch.object(db, "_execute_write", return_value=1) as write:
        assert (
            db.save_sdk_regen_job_progress(
                _JOB,
                _TOKEN,
                publish_run_id="not-a-uuid",
                publish_status="published",
                package_name="@acme/widgets-sdk",
                package_version="1.4.0",
                regen_counter=0,
                artifact_sha256="a" * 64,
            )
            == 1
        )
    sql, params = write.call_args.args
    assert "WHERE id = %s::uuid AND claim_token = %s::uuid AND status = 'running'" in sql
    # Only the registry step's columns; the job's status is the close-out's to set.
    assert "SET publish_run_id" in sql
    assert not re.search(r"(?<![a-z_])status = %s", sql.split("WHERE")[0])
    assert params == (None, "published", "@acme/widgets-sdk", "1.4.0", 0, "a" * 64, _JOB, _TOKEN)


def test_the_lease_sweep_dead_letters_only_stale_running_jobs_and_returns_alert_coordinates() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        assert (
            db.reap_stale_sdk_regen_jobs(
                lease_seconds=0, error_code="sdk-regen-worker-lost", error_message="lost", max_attempt_entries=0
            )
            == []
        )
    sql, params = query.call_args.args
    assert "SET status = 'dead_letter'" in sql
    assert "WHERE r.id = j.run_id" in sql
    assert "AND j.status = 'running'" in sql
    assert "j.claimed_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')" in sql
    assert "r.version_line" in sql and "p.slug AS project_slug" in sql
    # Bounds are clamped to at least one.
    assert params == ("sdk-regen-worker-lost", "lost", 1, "sdk-regen-worker-lost", 1)


def test_run_listing_is_newest_first_and_filters_on_job_status() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_regen_runs(_TENANT, _PROJECT, job_status="dead_letter", limit=0, offset=-3)
    sql, params = query.call_args.args
    assert "ORDER BY r.created_at DESC, r.id DESC" in sql
    assert "WHERE j.run_id = r.id AND j.status = %s" in sql
    assert params == (_TENANT, _PROJECT, "dead_letter", 1, 0)

    with patch.object(db, "execute_query", return_value=[{"total": 3}]) as query:
        assert db.count_sdk_regen_runs(_TENANT, _PROJECT) == 3
    assert "j.status" not in query.call_args.args[0]


def test_job_reads_are_scoped_to_the_tenant_and_carry_subscription_state() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        db.list_sdk_regen_jobs_for_runs(_TENANT, [_RUN, "junk"])
    sql, params = query.call_args.args
    assert "j.tenant_id = %s::uuid AND j.run_id = ANY(%s::uuid[])" in sql
    assert "s.active AS subscription_active" in sql
    assert params == (_TENANT, [_RUN])

    with patch.object(db, "execute_query", return_value=[{"id": _JOB}]) as query:
        assert db.get_sdk_regen_job(_TENANT, _JOB) == {"id": _JOB}
    assert "WHERE j.id = %s::uuid AND j.tenant_id = %s::uuid" in query.call_args.args[0]


def test_retry_is_a_compare_and_set_on_the_dead_letter() -> None:
    with patch.object(db, "execute_query", return_value=[]) as query:
        assert db.retry_sdk_regen_job(_TENANT, _PROJECT, _JOB, actor_id=_USER) is None
    sql, params = query.call_args.args
    assert "SET status = 'pending'" in sql
    assert "attempt_count = 0" in sql
    assert "AND j.status = 'dead_letter'" in sql
    assert "AND j.project_id = %s::uuid" in sql
    assert params == (_USER, _JOB, _TENANT, _PROJECT)


def test_deleting_a_subscription_is_a_plain_scoped_delete() -> None:
    with patch.object(db, "_execute_write", return_value=1) as write:
        assert db.delete_sdk_regen_subscription(_TENANT, _PROJECT, "npm") == 1
    sql, params = write.call_args.args
    assert "DELETE FROM apiome.sdk_regen_subscriptions" in sql
    assert params == (_TENANT, _PROJECT, "npm")
