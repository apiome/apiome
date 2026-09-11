"""The rules of an auto-regen job — SDK-4.3 (#4497).

:mod:`app.sdk_regen_policy` is pure, so each rule is asserted directly: when a failure is retried
and when it is dead-lettered, which steps a retry may skip, how a run's status is read off its jobs,
and what the dead-letter alert carries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.sdk_regen_policy import (
    BACKOFF_AFTER_FAILURE_SECONDS,
    EVENT_SDK_REGEN_DEAD_LETTERED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_DEAD_LETTER,
    JOB_STATUS_PENDING,
    JOB_STATUS_RETRYING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    MAX_ATTEMPTS,
    MAX_ERROR_CODE_CHARS,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_DEAD_LETTER,
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_SUCCEEDED,
    attempt_entry,
    backoff_seconds,
    bound_error_code,
    dead_letter_payload,
    decide_after_failure,
    git_step_done,
    registry_step_done,
    run_status,
)

_NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------------------------
# Retry or dead letter
# --------------------------------------------------------------------------------------------
def test_a_transient_failure_is_retried_with_the_backoff_for_its_attempt():
    for attempt, wait in zip(range(1, MAX_ATTEMPTS), BACKOFF_AFTER_FAILURE_SECONDS):
        decision = decide_after_failure(attempt_count=attempt, retryable=True, now=_NOW)
        assert decision.status == JOB_STATUS_RETRYING
        assert decision.next_attempt_at == _NOW + timedelta(seconds=wait)


def test_a_transient_failure_that_spent_its_attempts_is_dead_lettered():
    decision = decide_after_failure(attempt_count=MAX_ATTEMPTS, retryable=True, now=_NOW)
    assert decision.status == JOB_STATUS_DEAD_LETTER
    assert decision.next_attempt_at is None


def test_a_permanent_failure_is_dead_lettered_at_once():
    """A missing credential fails identically four times; the dead letter names the fix now."""
    decision = decide_after_failure(attempt_count=1, retryable=False, now=_NOW)
    assert decision.status == JOB_STATUS_DEAD_LETTER
    assert decision.next_attempt_at is None


def test_the_backoff_grows_and_is_bounded_by_its_table():
    assert list(BACKOFF_AFTER_FAILURE_SECONDS) == sorted(BACKOFF_AFTER_FAILURE_SECONDS)
    assert backoff_seconds(0) == BACKOFF_AFTER_FAILURE_SECONDS[0]
    assert backoff_seconds(99) == BACKOFF_AFTER_FAILURE_SECONDS[-1]


# --------------------------------------------------------------------------------------------
# A step that succeeded is never repeated
# --------------------------------------------------------------------------------------------
def test_a_published_registry_step_is_done_whatever_the_options_now_say():
    for status in ("published", "already_published"):
        assert registry_step_done(status, dry_run=False)
        assert registry_step_done(status, dry_run=True)


def test_a_dry_run_completes_the_registry_step_only_while_the_subscription_still_rehearses():
    assert registry_step_done("dry_run", dry_run=True)
    # Switched to real publishing since: the retry publishes.
    assert not registry_step_done("dry_run", dry_run=False)


def test_a_failed_or_missing_registry_step_runs_again():
    for status in (None, "failed", "in_progress"):
        assert not registry_step_done(status, dry_run=False)


def test_every_delivery_that_left_the_sdk_in_place_completes_the_git_step():
    for status in ("opened", "updated", "unchanged", "up_to_date"):
        assert git_step_done(status)
    for status in (None, "failed", "in_progress"):
        assert not git_step_done(status)


# --------------------------------------------------------------------------------------------
# A run's status
# --------------------------------------------------------------------------------------------
def test_a_run_is_in_progress_while_any_job_has_work_ahead():
    for active in (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_RETRYING):
        assert run_status([JOB_STATUS_DEAD_LETTER, active]) == RUN_STATUS_IN_PROGRESS


def test_a_settled_run_with_a_dead_letter_is_a_dead_letter():
    """One subscription's failure is visible on the run without hiding the others' success."""
    assert run_status([JOB_STATUS_SUCCEEDED, JOB_STATUS_DEAD_LETTER]) == RUN_STATUS_DEAD_LETTER


def test_a_run_whose_jobs_were_all_cancelled_is_cancelled_and_a_mix_with_success_succeeded():
    assert run_status([JOB_STATUS_CANCELLED, JOB_STATUS_CANCELLED]) == RUN_STATUS_CANCELLED
    assert run_status([JOB_STATUS_CANCELLED, JOB_STATUS_SUCCEEDED]) == RUN_STATUS_SUCCEEDED
    assert run_status([JOB_STATUS_SUCCEEDED]) == RUN_STATUS_SUCCEEDED
    assert run_status([]) == RUN_STATUS_SUCCEEDED


# --------------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------------
def test_an_error_code_is_bounded_to_its_column():
    assert bound_error_code(None) is None
    assert bound_error_code("sdk-publish-registry-refused") == "sdk-publish-registry-refused"
    assert len(bound_error_code("x" * 500)) == MAX_ERROR_CODE_CHARS


def test_an_attempt_record_links_the_runs_it_wrote():
    entry = attempt_entry(
        attempt=2,
        started_at=_NOW,
        finished_at=_NOW + timedelta(seconds=5),
        outcome=JOB_STATUS_RETRYING,
        error_step="git",
        error_code="sdk-git-delivery-rate-limited",
        publish_run_id="p-run",
        publish_status="published",
        delivery_run_id="d-run",
        delivery_status="failed",
    )
    assert entry == {
        "attempt": 2,
        "startedAt": "2026-09-10T12:00:00+00:00",
        "finishedAt": "2026-09-10T12:00:05+00:00",
        "outcome": "retrying",
        "errorStep": "git",
        "errorCode": "sdk-git-delivery-rate-limited",
        "publishRunId": "p-run",
        "publishStatus": "published",
        "deliveryRunId": "d-run",
        "deliveryStatus": "failed",
    }


def test_the_dead_letter_alert_routes_explains_and_says_what_was_already_delivered():
    payload = dead_letter_payload(
        {
            "id": "job-1",
            "tenant_id": "t",
            "project_id": "p",
            "project_slug": "widgets",
            "run_id": "run-1",
            "subscription_id": "sub-1",
            "ecosystem": "npm",
            "delivery_mode": "registry_and_git",
            "attempt_count": 4,
            "error_step": "git",
            "error_code": "sdk-git-delivery-provider-unavailable",
            "error_message": "GitHub answered 502",
            "version_id": "v-1",
            "version_line": "1.4.2",
            "publish_run_id": "p-run",
            "publish_status": "published",
            "package_name": "@acme/widgets-sdk",
            "package_version": "1.4.0",
            "delivery_run_id": None,
            "pull_request_url": "",
            "finished_at": _NOW,
        }
    )
    assert payload["event"] == EVENT_SDK_REGEN_DEAD_LETTERED == "sdk.regen.dead_lettered"
    assert payload["jobId"] == "job-1" and payload["runId"] == "run-1"
    assert payload["attemptCount"] == 4
    assert payload["error"] == {
        "step": "git",
        "code": "sdk-git-delivery-provider-unavailable",
        "message": "GitHub answered 502",
    }
    # What the job had already shipped before it failed.
    assert payload["publishStatus"] == "published" and payload["packageVersion"] == "1.4.0"
    assert payload["versionLine"] == "1.4.2" and payload["projectSlug"] == "widgets"
    assert payload["deadLetteredAt"] == "2026-09-10T12:00:00+00:00"
    # Unknown coordinates are omitted, not sent as null.
    assert "deliveryRunId" not in payload and "pullRequestUrl" not in payload
    # A tenant id is routing, not payload.
    assert "tenantId" not in payload
