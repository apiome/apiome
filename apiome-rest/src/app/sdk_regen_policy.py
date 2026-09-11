"""The rules of an auto-regen job — SDK-4.3 (#4497).

Pure functions and vocabulary, no I/O: what each job status means, when a failure is retried and
when it is dead-lettered, which delivery steps a retry may skip, how a run's status is read off its
jobs, and what the dead-letter alert says. :mod:`app.sdk_regen_worker` applies these; keeping them
here means every decision is testable without a database, a registry or GitHub.

**The lifecycle is the push-webhook delivery lifecycle (#2588), plus one state.**

* ``pending`` — queued by a publish, or put back by a manual retry.
* ``running`` — claimed by a worker.
* ``retrying`` — failed in a way that could succeed unchanged (a registry 5xx, a GitHub timeout),
  waiting for ``next_attempt_at``.
* ``succeeded`` — every delivery step the subscription asks for completed.
* ``dead_letter`` — failed permanently (a missing credential, no delivery target), or spent its
  attempts. Visible, alerted, and retried only by a person.
* ``cancelled`` — must not run: the subscription was disabled or removed, or the version was
  unpublished before the worker reached it. Not a failure, so no alert.

**Only transient failures are retried automatically.** Webhooks retry every failure; a regen job
retries only what the pipelines flag as ``retryable``. A missing credential fails identically four
times, and a registry refusal retried blindly is a refusal repeated — so a permanent failure goes to
the dead letter at once, with the message that names the fix.

**A step that succeeded is never repeated.** A job that published ``1.4.0`` and then failed to open
its pull request must not publish ``1.4.1`` on the retry: it delivers the version it already
claimed. :func:`registry_step_done` and :func:`git_step_done` are that rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Mapping, Optional

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "BACKOFF_AFTER_FAILURE_SECONDS",
    "DELIVERY_DONE_STATUSES",
    "ERROR_GIT_TARGET_MISSING",
    "ERROR_INTERNAL",
    "ERROR_SOURCE_UNAVAILABLE",
    "ERROR_SUBSCRIPTION_DISABLED",
    "ERROR_UNSUBSCRIBED",
    "ERROR_VERSION_MISSING",
    "ERROR_VERSION_UNPUBLISHED",
    "ERROR_WORKER_LOST",
    "EVENT_SDK_REGEN_DEAD_LETTERED",
    "JOB_STATUSES",
    "JOB_STATUS_CANCELLED",
    "JOB_STATUS_DEAD_LETTER",
    "JOB_STATUS_PENDING",
    "JOB_STATUS_RETRYING",
    "JOB_STATUS_RUNNING",
    "JOB_STATUS_SUCCEEDED",
    "MAX_ATTEMPTS",
    "MAX_ATTEMPT_ENTRIES",
    "MAX_ERROR_CODE_CHARS",
    "PUBLISH_DONE_STATUSES",
    "RUN_STATUSES",
    "RUN_STATUS_CANCELLED",
    "RUN_STATUS_DEAD_LETTER",
    "RUN_STATUS_IN_PROGRESS",
    "RUN_STATUS_SUCCEEDED",
    "STEPS",
    "STEP_GENERATE",
    "STEP_GIT",
    "STEP_REGISTRY",
    "STEP_WORKER",
    "TERMINAL_JOB_STATUSES",
    "FailureDecision",
    "attempt_entry",
    "backoff_seconds",
    "bound_error_code",
    "dead_letter_payload",
    "decide_after_failure",
    "git_step_done",
    "registry_step_done",
    "run_status",
]

# -------------------------------------------------------------------------------------------
# Vocabulary
# -------------------------------------------------------------------------------------------

#: Job statuses, matching V258's ``sdk_regen_jobs_status_check``.
JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_RETRYING = "retrying"
JOB_STATUS_SUCCEEDED = "succeeded"
JOB_STATUS_DEAD_LETTER = "dead_letter"
JOB_STATUS_CANCELLED = "cancelled"

#: Every job status, in lifecycle order.
JOB_STATUSES = (
    JOB_STATUS_PENDING,
    JOB_STATUS_RUNNING,
    JOB_STATUS_RETRYING,
    JOB_STATUS_SUCCEEDED,
    JOB_STATUS_DEAD_LETTER,
    JOB_STATUS_CANCELLED,
)

#: A job in one of these still has work ahead of it.
ACTIVE_JOB_STATUSES = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_RETRYING)

#: A job in one of these will not run again unless a person retries it.
TERMINAL_JOB_STATUSES = (JOB_STATUS_SUCCEEDED, JOB_STATUS_DEAD_LETTER, JOB_STATUS_CANCELLED)

#: A run's status, read off its jobs by :func:`run_status`.
RUN_STATUS_IN_PROGRESS = "in_progress"
RUN_STATUS_SUCCEEDED = "succeeded"
RUN_STATUS_DEAD_LETTER = "dead_letter"
RUN_STATUS_CANCELLED = "cancelled"
RUN_STATUSES = (
    RUN_STATUS_IN_PROGRESS,
    RUN_STATUS_SUCCEEDED,
    RUN_STATUS_DEAD_LETTER,
    RUN_STATUS_CANCELLED,
)

#: The steps a job runs, matching V258's ``sdk_regen_jobs_error_step_check``. ``generate`` loads
#: the published revision's canonical model; ``registry`` is the SDK-4.1 publish; ``git`` is the
#: SDK-4.2 pull request; ``worker`` is the lease sweep presuming a claim lost.
STEP_GENERATE = "generate"
STEP_REGISTRY = "registry"
STEP_GIT = "git"
STEP_WORKER = "worker"
STEPS = (STEP_GENERATE, STEP_REGISTRY, STEP_GIT, STEP_WORKER)

#: SDK-4.1 run statuses after which the registry step is done: the version exists on the registry.
PUBLISH_DONE_STATUSES = ("published", "already_published")

#: The SDK-4.1 dry-run status, which completes the registry step only for a dry-run subscription.
_PUBLISH_DRY_RUN = "dry_run"

#: SDK-4.2 run statuses after which the git step is done.
DELIVERY_DONE_STATUSES = ("opened", "updated", "unchanged", "up_to_date")

#: How many attempts a job gets before a transient failure is dead-lettered — the push-webhook
#: budget (``WEBHOOK_MAX_DELIVERY_ATTEMPTS``).
MAX_ATTEMPTS = 4

#: The wait after failed attempts 1, 2 and 3. Longer than a webhook's (10s/60s/300s): a regen
#: rebuilds a package and writes to a registry or GitHub, and the outages worth waiting out — a
#: registry incident, a GitHub rate limit window — are measured in minutes.
BACKOFF_AFTER_FAILURE_SECONDS = (60, 300, 1800)

#: How many attempt records one job keeps. A retried dead letter restarts its budget, so without a
#: cap the log would grow with every manual retry.
MAX_ATTEMPT_ENTRIES = 50

#: V258's ``error_code`` column width.
MAX_ERROR_CODE_CHARS = 64

# -------------------------------------------------------------------------------------------
# Codes
# -------------------------------------------------------------------------------------------

#: A worker claimed the job and never closed it within the lease.
ERROR_WORKER_LOST = "sdk-regen-worker-lost"

#: The subscription was removed after the publish queued the job.
ERROR_UNSUBSCRIBED = "sdk-regen-unsubscribed"

#: The subscription was disabled after the publish queued the job.
ERROR_SUBSCRIPTION_DISABLED = "sdk-regen-subscription-disabled"

#: The published revision no longer exists.
ERROR_VERSION_MISSING = "sdk-regen-version-missing"

#: The revision was unpublished before the worker reached it.
ERROR_VERSION_UNPUBLISHED = "sdk-regen-version-unpublished"

#: The revision has no captured source to regenerate from.
ERROR_SOURCE_UNAVAILABLE = "sdk-regen-source-unavailable"

#: A git subscription with no SDK-4.2 delivery target for its ecosystem.
ERROR_GIT_TARGET_MISSING = "sdk-regen-git-target-missing"

#: Something failed that no refusal explains.
ERROR_INTERNAL = "sdk-regen-internal-error"

#: The push-webhook event a dead-lettered job fans out.
EVENT_SDK_REGEN_DEAD_LETTERED = "sdk.regen.dead_lettered"


# -------------------------------------------------------------------------------------------
# Decisions
# -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureDecision:
    """What becomes of a job whose attempt failed.

    Attributes:
        status: :data:`JOB_STATUS_RETRYING` or :data:`JOB_STATUS_DEAD_LETTER`.
        next_attempt_at: When a retrying job is next due; ``None`` for a dead letter.
    """

    status: str
    next_attempt_at: Optional[datetime]


def backoff_seconds(attempt_count: int) -> int:
    """Return how long to wait after a failed attempt.

    Args:
        attempt_count: How many attempts have been made, including the one that just failed.

    Returns:
        The wait in seconds; attempts beyond the table reuse its last entry.
    """
    index = min(max(int(attempt_count), 1), len(BACKOFF_AFTER_FAILURE_SECONDS)) - 1
    return BACKOFF_AFTER_FAILURE_SECONDS[index]


def decide_after_failure(
    *,
    attempt_count: int,
    retryable: bool,
    now: datetime,
    max_attempts: int = MAX_ATTEMPTS,
) -> FailureDecision:
    """Decide whether a failed attempt is retried or dead-lettered.

    Args:
        attempt_count: Attempts made, including the one that just failed.
        retryable: Whether the failure could plausibly succeed if repeated unchanged.
        now: The current time (injected, so the backoff is testable).
        max_attempts: The attempt budget.

    Returns:
        ``retrying`` with the next due time when the failure is transient and the budget allows,
        otherwise ``dead_letter``.
    """
    if retryable and int(attempt_count) < int(max_attempts):
        return FailureDecision(
            status=JOB_STATUS_RETRYING,
            next_attempt_at=now + timedelta(seconds=backoff_seconds(attempt_count)),
        )
    return FailureDecision(status=JOB_STATUS_DEAD_LETTER, next_attempt_at=None)


def registry_step_done(publish_status: Optional[str], *, dry_run: bool) -> bool:
    """Whether a job's registry step already completed, so a retry must not repeat it.

    Args:
        publish_status: The SDK-4.1 run status the step last recorded.
        dry_run: Whether the subscription (as it is now) asks for a dry run.

    Returns:
        ``True`` once the version exists on the registry. A dry run completes the step only while
        the subscription still asks for one — a subscription switched to real publishing publishes.
    """
    if publish_status in PUBLISH_DONE_STATUSES:
        return True
    return bool(dry_run) and publish_status == _PUBLISH_DRY_RUN


def git_step_done(delivery_status: Optional[str]) -> bool:
    """Whether a job's git step already completed.

    Args:
        delivery_status: The SDK-4.2 run status the step last recorded.

    Returns:
        ``True`` for any outcome that left the pull request (or the base branch) carrying the SDK.
    """
    return delivery_status in DELIVERY_DONE_STATUSES


def run_status(job_statuses: Iterable[str]) -> str:
    """Read a run's status off its jobs.

    Args:
        job_statuses: The status of each job in the run.

    Returns:
        ``in_progress`` while any job has work ahead of it; otherwise ``dead_letter`` if any job is
        dead-lettered; otherwise ``cancelled`` if every job was cancelled; otherwise ``succeeded``.
    """
    statuses = list(job_statuses)
    if any(status in ACTIVE_JOB_STATUSES for status in statuses):
        return RUN_STATUS_IN_PROGRESS
    if any(status == JOB_STATUS_DEAD_LETTER for status in statuses):
        return RUN_STATUS_DEAD_LETTER
    if statuses and all(status == JOB_STATUS_CANCELLED for status in statuses):
        return RUN_STATUS_CANCELLED
    return RUN_STATUS_SUCCEEDED


def bound_error_code(code: Optional[str]) -> Optional[str]:
    """Bound an error code to what the job's column stores.

    A code can come from a pipeline refusal the worker does not own, and a close-out that failed on
    an over-long code would lose the very failure it was recording.

    Args:
        code: The code, or ``None``.

    Returns:
        The code truncated to :data:`MAX_ERROR_CODE_CHARS`.
    """
    return None if code is None else str(code)[:MAX_ERROR_CODE_CHARS]


# -------------------------------------------------------------------------------------------
# Records
# -------------------------------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, passing strings and ``None`` through."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def attempt_entry(
    *,
    attempt: int,
    started_at: datetime,
    finished_at: datetime,
    outcome: str,
    error_step: Optional[str],
    error_code: Optional[str],
    publish_run_id: Optional[str],
    publish_status: Optional[str],
    delivery_run_id: Optional[str],
    delivery_status: Optional[str],
) -> Dict[str, Any]:
    """Build the record one attempt appends to its job's ``attempts`` log.

    Each record names the SDK-4.1 and SDK-4.2 runs its attempt wrote, so a failed attempt stays
    linked to its evidence after a later attempt succeeds and overwrites the job's latest fields.

    Args:
        attempt: The attempt number.
        started_at: When the attempt began.
        finished_at: When it ended.
        outcome: The job status the attempt left behind.
        error_step: The step that failed, if any.
        error_code: Its code.
        publish_run_id: The publish run this attempt wrote, if it ran the registry step.
        publish_status: That run's status.
        delivery_run_id: The delivery run this attempt wrote, if it ran the git step.
        delivery_status: That run's status.

    Returns:
        A JSON-serialisable record.
    """
    return {
        "attempt": int(attempt),
        "startedAt": _iso(started_at),
        "finishedAt": _iso(finished_at),
        "outcome": outcome,
        "errorStep": error_step,
        "errorCode": error_code,
        "publishRunId": publish_run_id,
        "publishStatus": publish_status,
        "deliveryRunId": delivery_run_id,
        "deliveryStatus": delivery_status,
    }


def dead_letter_payload(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Assemble the ``sdk.regen.dead_lettered`` push-webhook payload.

    The ids route the alert; the error says what to fix; the publish and delivery coordinates say
    what the job had already done, which matters most when a worker was lost mid-job and a package
    may already be on the registry.

    Args:
        job: A job row (as the store returns it), optionally carrying ``version_id``,
            ``version_line`` and ``project_slug``.

    Returns:
        A JSON-serialisable payload with camelCase keys. Optional coordinates are omitted when
        unknown rather than sent as ``null``.
    """
    payload: Dict[str, Any] = {
        "event": EVENT_SDK_REGEN_DEAD_LETTERED,
        "projectId": job.get("project_id"),
        "runId": job.get("run_id"),
        "jobId": job.get("id"),
        "subscriptionId": job.get("subscription_id"),
        "ecosystem": job.get("ecosystem"),
        "deliveryMode": job.get("delivery_mode"),
        "attemptCount": int(job.get("attempt_count") or 0),
        "error": {
            "step": job.get("error_step"),
            "code": job.get("error_code"),
            "message": job.get("error_message"),
        },
        "deadLetteredAt": _iso(job.get("finished_at") or job.get("updated_at")),
    }
    optional = (
        ("projectSlug", job.get("project_slug")),
        ("versionId", job.get("version_id")),
        ("versionLine", job.get("version_line")),
        ("publishRunId", job.get("publish_run_id")),
        ("publishStatus", job.get("publish_status")),
        ("packageName", job.get("package_name")),
        ("packageVersion", job.get("package_version")),
        ("deliveryRunId", job.get("delivery_run_id")),
        ("deliveryStatus", job.get("delivery_status")),
        ("pullRequestUrl", job.get("pull_request_url")),
    )
    for key, value in optional:
        if value is not None and value != "":
            payload[key] = value
    return payload
