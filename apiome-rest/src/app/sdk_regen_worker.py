"""The auto-regen worker — SDK-4.3 (#4497).

A publish queues one job per active subscription (:func:`app.sdk_regen_subscriptions
.enqueue_regen_on_publish`); this module is the periodic worker (wired in :mod:`app.main`, like the
push-webhook delivery sweep) that runs them. **It adds no regeneration or delivery machinery of its
own.** Each job calls the shipped pipelines unchanged — SDK-4.1's :func:`app.sdk_publish_pipeline
.publish` and SDK-4.2's :func:`app.sdk_git_delivery_pipeline.deliver` — so an automatic release and
a manual one build the same package, claim versions by the same rule, write the same ledgers and
redact the same secrets. What lives here is the order the steps run in, what each outcome means for
the job, and the dead letter.

**Why not SDK-1.1 generation jobs.** The ticket's worker "enqueues generation jobs (SDK-1.1)"; the
job service was closed not-planned, and SDK-4.1/4.2 both regenerate from the persisted canonical
model inline. A job therefore *is* the generation job: its ``generate`` step loads the published
revision's model, and its delivery steps build the package from it.

Each tick:

1. **Reap lost claims.** A job ``running`` past the lease had its worker die mid-job — after an
   upload, perhaps. It is dead-lettered (and alerted), never retried automatically: SDK-4.1's rule is
   that a run which may have published keeps its version, and a person should look at the publish
   history before anything runs again.
2. **Claim and run jobs one at a time**, up to the batch size. The claim is ``FOR UPDATE SKIP
   LOCKED``, so replicas share the queue, and it takes a subscription's jobs in publish order.

A job runs its steps in order and stops at the first failure:

* **Subscription check** — the subscription as it is *now*: removed or disabled → ``cancelled``.
  The mode and options a job applies are also read now, so a dead letter retried after the
  subscription was fixed runs with the fix.
* **generate** — the revision must still exist and be published (otherwise ``cancelled``), and its
  canonical model must load.
* **registry** (``registry`` / ``registry_and_git``) — SDK-4.1 publish, or a dry run.
* **git** (``git`` / ``registry_and_git``) — SDK-4.2 delivery, pinned to the counter the registry
  step claimed so the pull request and the registry carry the same version.

A step that already succeeded on an earlier attempt is skipped (:func:`app.sdk_regen_policy
.registry_step_done`), so a retry never publishes a second version of one publish.

**One job's failure never touches another.** Every job is executed, judged and recorded on its own;
nothing a job raises escapes :func:`run_claimed_job`, and a job the worker could not even close is
caught by the lease on a later tick.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from .database import db as default_db
from .export_source import ExportSource, ExportSourceError, load_export_source
from .push_webhook_fanout import enqueue_event
from .sdk_git_delivery_github import ClientFactory
from .sdk_git_delivery_pipeline import RUN_STATUS_FAILED as DELIVERY_FAILED
from .sdk_git_delivery_pipeline import deliver
from .sdk_git_delivery_targets import resolve_target
from .sdk_publish_pipeline import RUN_STATUS_FAILED as PUBLISH_FAILED
from .sdk_publish_pipeline import PublishContext, PublishError, PublishTransport, publish
from .sdk_regen_policy import (
    ERROR_GIT_TARGET_MISSING,
    ERROR_INTERNAL,
    ERROR_SOURCE_UNAVAILABLE,
    ERROR_SUBSCRIPTION_DISABLED,
    ERROR_UNSUBSCRIBED,
    ERROR_VERSION_MISSING,
    ERROR_VERSION_UNPUBLISHED,
    ERROR_WORKER_LOST,
    EVENT_SDK_REGEN_DEAD_LETTERED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_DEAD_LETTER,
    JOB_STATUS_SUCCEEDED,
    MAX_ATTEMPT_ENTRIES,
    PUBLISH_DONE_STATUSES,
    STEP_GENERATE,
    STEP_GIT,
    STEP_REGISTRY,
    attempt_entry,
    bound_error_code,
    dead_letter_payload,
    decide_after_failure,
    git_step_done,
    registry_step_done,
)
from .sdk_regen_subscriptions import includes_git, includes_registry, options_object, read_options

logger = logging.getLogger(__name__)

__all__ = [
    "RETRYABLE_PUBLISH_CODES",
    "WORKER_LOST_MESSAGE",
    "JobProgress",
    "notify_dead_lettered",
    "process_sdk_regen_sweep",
    "reap_lost_jobs",
    "run_claimed_job",
]

#: SDK-4.1 refusals worth repeating unchanged. Only the claim race is: every other refusal (no
#: credential, no package name, an unmappable version line, no encryption key) fails identically
#: until a person changes something.
RETRYABLE_PUBLISH_CODES = frozenset({"sdk-publish-version-unavailable"})

#: What a reaped job says.
WORKER_LOST_MESSAGE = (
    "The worker running this job stopped before recording an outcome (the process restarted or "
    "the job outlived its lease). It may already have published a package or pushed a branch, so "
    "it was not retried automatically: check this project's SDK publish and git delivery history, "
    "then retry the job if nothing was delivered."
)

#: How the worker reads the clock. Injected by tests.
Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------------------------------
# Progress and outcomes
# -------------------------------------------------------------------------------------------


@dataclass
class JobProgress:
    """What a job has produced so far — carried forward across attempts.

    Initialised from the claimed row, so a step that succeeded on an earlier attempt keeps its
    results when this attempt skips it, and overwritten only by a step that runs again.

    Attributes:
        delivery_mode: The mode this attempt runs with.
        options: The normalised options this attempt runs with.
        publish_run_id: The SDK-4.1 run the registry step last wrote.
        publish_status: That run's status.
        delivery_run_id: The SDK-4.2 run the git step last wrote.
        delivery_status: That run's status.
        package_name: The package the job produced.
        package_version: Its version.
        regen_counter: The counter a registry publish claimed (``None`` for a dry run).
        artifact_sha256: The built archive's digest.
        pull_request_number: The pull request opened or updated.
        pull_request_url: Its web page.
    """

    delivery_mode: str
    options: Dict[str, Any]
    publish_run_id: Optional[str] = None
    publish_status: Optional[str] = None
    delivery_run_id: Optional[str] = None
    delivery_status: Optional[str] = None
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    regen_counter: Optional[int] = None
    artifact_sha256: Optional[str] = None
    pull_request_number: Optional[int] = None
    pull_request_url: Optional[str] = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "JobProgress":
        """Start from what a claimed job row already records.

        Args:
            row: The claimed job.

        Returns:
            The progress.
        """
        options = row.get("options")
        return cls(
            delivery_mode=str(row.get("delivery_mode") or ""),
            options=dict(options) if isinstance(options, Mapping) else {},
            publish_run_id=row.get("publish_run_id"),
            publish_status=row.get("publish_status"),
            delivery_run_id=row.get("delivery_run_id"),
            delivery_status=row.get("delivery_status"),
            package_name=row.get("package_name"),
            package_version=row.get("package_version"),
            regen_counter=row.get("regen_counter"),
            artifact_sha256=row.get("artifact_sha256"),
            pull_request_number=row.get("pull_request_number"),
            pull_request_url=row.get("pull_request_url"),
        )


class _StepFailedError(Exception):
    """A step that failed; the job retries or dead-letters.

    Attributes:
        step: Which step.
        code: A stable code.
        message: What went wrong and what to do about it.
        retryable: Whether repeating it unchanged could plausibly succeed.
    """

    def __init__(self, step: str, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message
        self.retryable = retryable


class _JobCancelledError(Exception):
    """A job that must not run. Not a failure: no retry, no alert.

    Attributes:
        code: Why (``sdk-regen-unsubscribed``…).
        message: The explanation recorded on the job.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# -------------------------------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------------------------------


def _apply_subscription(row: Mapping[str, Any], progress: JobProgress) -> None:
    """Refuse to run for a removed or disabled subscription; adopt its current mode and options.

    Args:
        row: The claimed job, carrying the subscription's current state.
        progress: Updated with the mode and options this attempt runs with.

    Raises:
        _JobCancelledError: When the subscription was removed or disabled after the job was queued.
    """
    ecosystem = row.get("ecosystem")
    if not row.get("subscription_id") or row.get("subscription_active") is None:
        raise _JobCancelledError(
            ERROR_UNSUBSCRIBED,
            f"The project's {ecosystem} SDK was unsubscribed after this publish queued the job, so "
            "it was not regenerated.",
        )
    if not row.get("subscription_active"):
        raise _JobCancelledError(
            ERROR_SUBSCRIPTION_DISABLED,
            f"The project's {ecosystem} regen subscription was disabled after this publish queued "
            "the job, so it was not regenerated. Enable the subscription and retry the job to "
            "deliver this version.",
        )
    mode = str(row.get("subscription_delivery_mode") or progress.delivery_mode)
    progress.delivery_mode = mode
    # Read leniently: a row saved by a newer build still runs, ignoring what this one does not know.
    progress.options = options_object(mode, row.get("subscription_options"))


def _load_revision(db: Any, row: Mapping[str, Any]) -> ExportSource:
    """The ``generate`` step: confirm the revision is still published and load its model.

    Args:
        db: The worker's database handle.
        row: The claimed job, carrying the run's ``version_id``.

    Returns:
        The loaded source.

    Raises:
        _JobCancelledError: When the revision was deleted or unpublished.
        _StepFailedError: When its model cannot be loaded.
    """
    tenant_id = str(row.get("tenant_id") or "")
    project_id = str(row.get("project_id") or "")
    version_id = row.get("version_id")
    line = row.get("version_line") or version_id
    if not version_id:
        raise _JobCancelledError(
            ERROR_VERSION_MISSING,
            f"Version {line!r} no longer exists, so there is nothing to regenerate.",
        )
    try:
        revision = db.get_version_by_id(version_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 - a lookup fault is a transient failure
        logger.warning("SDK regen: revision lookup failed for %s", version_id, exc_info=True)
        raise _StepFailedError(
            STEP_GENERATE, ERROR_INTERNAL, "The published version could not be read.", retryable=True
        ) from exc
    if not revision:
        raise _JobCancelledError(
            ERROR_VERSION_MISSING,
            f"Version {line!r} no longer exists, so there is nothing to regenerate.",
        )
    if not revision.get("published"):
        raise _JobCancelledError(
            ERROR_VERSION_UNPUBLISHED,
            f"Version {line!r} was unpublished before its SDK was regenerated, so nothing was "
            "delivered.",
        )
    try:
        return load_export_source(tenant_id, project_id, str(version_id))
    except ExportSourceError as exc:
        if exc.status_code == 404:
            raise _JobCancelledError(ERROR_VERSION_MISSING, str(exc)) from exc
        raise _StepFailedError(
            STEP_GENERATE,
            ERROR_SOURCE_UNAVAILABLE,
            f"The SDK for version {line!r} cannot be regenerated: {exc}",
            retryable=False,
        ) from exc
    except Exception as exc:  # noqa: BLE001 - an unexplained load fault is worth one more try
        logger.exception("SDK regen: loading revision %s failed unexpectedly", version_id)
        raise _StepFailedError(
            STEP_GENERATE,
            ERROR_INTERNAL,
            f"Loading version {line!r} failed unexpectedly ({type(exc).__name__}).",
            retryable=True,
        ) from exc


def _registry_step(
    source: ExportSource,
    *,
    context: PublishContext,
    ecosystem: str,
    dry_run: bool,
    progress: JobProgress,
    transport: Optional[PublishTransport],
    apiome_version: Optional[str],
) -> None:
    """The ``registry`` step: SDK-4.1 publish (or dry run), unchanged.

    Args:
        source: The revision's loaded model and contract.
        context: Which revision, and on whose publish.
        ecosystem: ``npm`` or ``pypi``.
        dry_run: Rehearse instead of uploading.
        progress: Updated with the publish run's coordinates.
        transport: Upload transport override (tests).
        apiome_version: The running API version, for provenance.

    Raises:
        _StepFailedError: When the publish is refused or the registry refuses the upload.
    """
    progress.publish_run_id = None
    progress.publish_status = None
    progress.regen_counter = None
    try:
        outcome = publish(
            source.api,
            context=context,
            ecosystem=ecosystem,
            dry_run=dry_run,
            source_text=source.source_text,
            source_format=source.source_format,
            apiome_version=apiome_version,
            transport=transport,
        )
    except PublishError as exc:
        progress.publish_status = PUBLISH_FAILED
        raise _StepFailedError(
            STEP_REGISTRY, exc.code, exc.message, retryable=exc.code in RETRYABLE_PUBLISH_CODES
        ) from exc
    except Exception as exc:  # noqa: BLE001 - recorded, and deliberately not retried
        logger.exception("SDK regen: publish of %s failed unexpectedly", ecosystem)
        progress.publish_status = PUBLISH_FAILED
        # Not retryable: an unexplained fault may have come after the upload, and SDK-4.1's rule
        # is that a run which may have published is never silently repeated.
        raise _StepFailedError(
            STEP_REGISTRY,
            ERROR_INTERNAL,
            f"The {ecosystem} publish failed unexpectedly ({type(exc).__name__}). Check the "
            "project's SDK publish history before retrying: the upload may have landed.",
            retryable=False,
        ) from exc

    progress.publish_run_id = outcome.run_id
    progress.publish_status = outcome.status
    progress.package_name = outcome.package_name
    progress.package_version = outcome.package_version
    progress.artifact_sha256 = outcome.artifact_sha256
    if outcome.status in PUBLISH_DONE_STATUSES:
        progress.regen_counter = outcome.regen_counter
    if outcome.status == PUBLISH_FAILED:
        raise _StepFailedError(
            STEP_REGISTRY,
            outcome.error_code or ERROR_INTERNAL,
            outcome.error_message or "The registry refused the upload.",
            retryable=outcome.retryable,
        )


def _git_step(
    source: ExportSource,
    *,
    context: PublishContext,
    ecosystem: str,
    progress: JobProgress,
    client_factory: Optional[ClientFactory],
    apiome_version: Optional[str],
) -> None:
    """The ``git`` step: SDK-4.2 delivery, unchanged, pinned to a claimed version.

    Args:
        source: The revision's loaded model and contract.
        context: Which revision, and on whose publish.
        ecosystem: ``npm`` or ``pypi``.
        progress: Updated with the delivery run's coordinates.
        client_factory: GitHub client override (tests).
        apiome_version: The running API version, for provenance.

    Raises:
        _StepFailedError: When no target is configured or the delivery fails.
    """
    progress.delivery_run_id = None
    progress.delivery_status = None
    progress.pull_request_number = None
    progress.pull_request_url = None
    try:
        target = resolve_target(context.tenant_id, context.project_id, ecosystem)
    except Exception as exc:  # noqa: BLE001 - a lookup fault is a transient failure
        logger.warning("SDK regen: delivery target lookup failed", exc_info=True)
        raise _StepFailedError(
            STEP_GIT, ERROR_INTERNAL, "The delivery target could not be read.", retryable=True
        ) from exc
    if target is None:
        raise _StepFailedError(
            STEP_GIT,
            ERROR_GIT_TARGET_MISSING,
            f"No {ecosystem} git delivery target is configured for this project, so there is no "
            "repository to deliver to. Configure one (a registered repository, a base branch and a "
            "path) and retry the job — or change the subscription's delivery mode to `registry`.",
            retryable=False,
        )

    # Pin the version the registry step claimed, so the pull request and the registry agree. A dry
    # run claimed nothing; the delivery then carries the version the next real publish would take.
    pinned = progress.regen_counter if progress.publish_status in PUBLISH_DONE_STATUSES else None
    try:
        outcome = deliver(
            source.api,
            context=context,
            target=target,
            source_text=source.source_text,
            source_format=source.source_format,
            apiome_version=apiome_version,
            regen_counter=pinned,
            client_factory=client_factory,
        )
    except Exception as exc:  # noqa: BLE001 - deliver() raises only before it writes anything
        logger.exception("SDK regen: git delivery of %s could not start", ecosystem)
        raise _StepFailedError(
            STEP_GIT,
            ERROR_INTERNAL,
            f"The {ecosystem} git delivery could not start ({type(exc).__name__}).",
            retryable=True,
        ) from exc

    progress.delivery_run_id = outcome.run_id
    progress.delivery_status = outcome.status
    progress.pull_request_number = outcome.pull_request_number
    progress.pull_request_url = outcome.pull_request_url
    if not includes_registry(progress.delivery_mode):
        progress.package_name = outcome.package_name
        progress.package_version = outcome.package_version
    if outcome.status == DELIVERY_FAILED:
        raise _StepFailedError(
            STEP_GIT,
            outcome.error_code or ERROR_INTERNAL,
            outcome.error_message or "The git delivery failed.",
            retryable=outcome.retryable,
        )


def _save_registry_progress(db: Any, row: Mapping[str, Any], progress: JobProgress) -> None:
    """Record a completed registry step before the git step starts, best-effort.

    A package on a registry cannot be taken back, so the job must know about it even if the worker
    dies during the pull request that follows. Without this, the lease sweep's dead letter would not
    say a version was published, and a retry would publish another. A failure to record is logged
    and the attempt carries on: the close-out writes the same columns.

    Args:
        db: The worker's database handle.
        row: The claimed job (its id and claim token).
        progress: The registry step's result.
    """
    try:
        db.save_sdk_regen_job_progress(
            str(row.get("id") or ""),
            str(row.get("claim_token") or ""),
            publish_run_id=progress.publish_run_id,
            publish_status=progress.publish_status,
            package_name=progress.package_name,
            package_version=progress.package_version,
            regen_counter=progress.regen_counter,
            artifact_sha256=progress.artifact_sha256,
        )
    except Exception:  # noqa: BLE001 - the close-out records it too; never fail the delivery for it
        logger.warning("SDK regen: could not record publish progress for job %s", row.get("id"), exc_info=True)


def _execute(
    db: Any,
    row: Mapping[str, Any],
    progress: JobProgress,
    *,
    publish_transport: Optional[PublishTransport],
    git_client_factory: Optional[ClientFactory],
    apiome_version: Optional[str],
) -> None:
    """Run every step a job still needs, in order.

    Args:
        db: The worker's database handle.
        row: The claimed job.
        progress: Carried forward and updated.
        publish_transport: Upload transport override (tests).
        git_client_factory: GitHub client override (tests).
        apiome_version: The running API version, for provenance.

    Raises:
        _JobCancelledError: When the job must not run.
        _StepFailedError: At the first step that fails.
    """
    _apply_subscription(row, progress)
    ecosystem = str(row.get("ecosystem") or "")
    options = read_options(progress.delivery_mode, progress.options)

    source = _load_revision(db, row)
    context = PublishContext(
        tenant_id=str(row.get("tenant_id") or ""),
        tenant_slug=str(row.get("tenant_slug") or ""),
        project_id=str(row.get("project_id") or ""),
        project_slug=str(row.get("project_slug") or ""),
        version_record_id=source.version_record_id,
        version_line=source.version_label,
        actor_id=row.get("published_by"),
    )

    if includes_registry(progress.delivery_mode) and not registry_step_done(
        progress.publish_status, dry_run=options.dry_run
    ):
        _registry_step(
            source,
            context=context,
            ecosystem=ecosystem,
            dry_run=options.dry_run,
            progress=progress,
            transport=publish_transport,
            apiome_version=apiome_version,
        )
        if includes_git(progress.delivery_mode):
            _save_registry_progress(db, row, progress)

    if includes_git(progress.delivery_mode) and not git_step_done(progress.delivery_status):
        _git_step(
            source,
            context=context,
            ecosystem=ecosystem,
            progress=progress,
            client_factory=git_client_factory,
            apiome_version=apiome_version,
        )


# -------------------------------------------------------------------------------------------
# One job
# -------------------------------------------------------------------------------------------


def notify_dead_lettered(db: Any, job: Mapping[str, Any]) -> List[str]:
    """Fan a dead-lettered job out over the tenant's push-webhook subscriptions.

    Args:
        db: Database handle for the fan-out.
        job: The dead-lettered job, ideally carrying ``version_line`` and ``project_slug``.

    Returns:
        The enqueued delivery-event ids. Never raises: an alert problem must not lose the job's
        own record.
    """
    try:
        return enqueue_event(
            db,
            tenant_id=str(job.get("tenant_id") or ""),
            event_type=EVENT_SDK_REGEN_DEAD_LETTERED,
            payload=dead_letter_payload(job),
            log_label="sdk-regen",
        )
    except Exception:  # noqa: BLE001 - enqueue_event never raises; belt and braces
        logger.exception("SDK regen: dead-letter alert failed for job %s", job.get("id"))
        return []


def run_claimed_job(
    db: Any,
    row: Mapping[str, Any],
    *,
    publish_transport: Optional[PublishTransport] = None,
    git_client_factory: Optional[ClientFactory] = None,
    apiome_version: Optional[str] = None,
    clock: Clock = _utcnow,
) -> Optional[Dict[str, Any]]:
    """Run one claimed job's attempt, close it, and alert when it is dead-lettered.

    Args:
        db: The worker's database handle (the one that claimed the job).
        row: The claimed job, as :meth:`app.database.Database.claim_next_sdk_regen_job` returns it.
        publish_transport: Upload transport override (tests).
        git_client_factory: GitHub client override (tests).
        apiome_version: The running API version, recorded as provenance.
        clock: How to read the time (tests).

    Returns:
        The closed job, or ``None`` when its claim no longer matched (a lease sweep reaped it and a
        person already retried it).

    Raises:
        Exception: Only when the close-out itself cannot be written; the job then stays ``running``
            until the lease sweep dead-letters it.
    """
    started_at = clock()
    progress = JobProgress.from_row(row)
    attempt = int(row.get("attempt_count") or 1)
    error_step: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    next_attempt_at: Optional[datetime] = None
    try:
        _execute(
            db,
            row,
            progress,
            publish_transport=publish_transport,
            git_client_factory=git_client_factory,
            apiome_version=apiome_version,
        )
        status = JOB_STATUS_SUCCEEDED
    except _JobCancelledError as cancelled:
        status, error_code, error_message = JOB_STATUS_CANCELLED, cancelled.code, cancelled.message
    except _StepFailedError as failure:
        decision = decide_after_failure(
            attempt_count=attempt, retryable=failure.retryable, now=clock()
        )
        status, next_attempt_at = decision.status, decision.next_attempt_at
        error_step, error_code, error_message = failure.step, failure.code, failure.message
    except Exception as exc:  # noqa: BLE001 - an unexplained fault still closes its attempt
        logger.exception("SDK regen: job %s failed unexpectedly", row.get("id"))
        decision = decide_after_failure(attempt_count=attempt, retryable=True, now=clock())
        status, next_attempt_at = decision.status, decision.next_attempt_at
        error_step, error_code = None, ERROR_INTERNAL
        error_message = f"The job failed unexpectedly ({type(exc).__name__})."

    error_code = bound_error_code(error_code)
    closed = db.finish_sdk_regen_job_attempt(
        str(row.get("id") or ""),
        str(row.get("claim_token") or ""),
        status=status,
        next_attempt_at=next_attempt_at,
        delivery_mode=progress.delivery_mode,
        options=progress.options,
        publish_run_id=progress.publish_run_id,
        publish_status=progress.publish_status,
        delivery_run_id=progress.delivery_run_id,
        delivery_status=progress.delivery_status,
        package_name=progress.package_name,
        package_version=progress.package_version,
        regen_counter=progress.regen_counter,
        artifact_sha256=progress.artifact_sha256,
        pull_request_number=progress.pull_request_number,
        pull_request_url=progress.pull_request_url,
        error_step=error_step,
        error_code=error_code,
        error_message=error_message,
        attempt=attempt_entry(
            attempt=attempt,
            started_at=started_at,
            finished_at=clock(),
            outcome=status,
            error_step=error_step,
            error_code=error_code,
            publish_run_id=progress.publish_run_id,
            publish_status=progress.publish_status,
            delivery_run_id=progress.delivery_run_id,
            delivery_status=progress.delivery_status,
        ),
        max_attempt_entries=MAX_ATTEMPT_ENTRIES,
        worker_lost_code=ERROR_WORKER_LOST,
    )
    if closed is None:
        logger.warning(
            "SDK regen: job %s was reclaimed before attempt %d could be recorded (status=%s)",
            row.get("id"),
            attempt,
            status,
        )
        return None

    logger.info(
        "SDK regen: job %s (%s, %s) attempt %d → %s%s",
        row.get("id"),
        row.get("ecosystem"),
        progress.delivery_mode,
        attempt,
        status,
        f" [{error_code}]" if error_code else "",
    )
    if status == JOB_STATUS_DEAD_LETTER:
        notify_dead_lettered(
            db,
            {
                **dict(closed),
                "version_id": row.get("version_id"),
                "version_line": row.get("version_line"),
                "project_slug": row.get("project_slug"),
            },
        )
    return closed


# -------------------------------------------------------------------------------------------
# The sweep
# -------------------------------------------------------------------------------------------


def reap_lost_jobs(db: Any, *, lease_seconds: int) -> int:
    """Dead-letter (and alert on) every job whose worker never closed its claim.

    Args:
        db: The worker's database handle.
        lease_seconds: How long a claim may run.

    Returns:
        How many jobs were reaped. Never raises.
    """
    try:
        reaped = db.reap_stale_sdk_regen_jobs(
            lease_seconds=lease_seconds,
            error_code=ERROR_WORKER_LOST,
            error_message=WORKER_LOST_MESSAGE,
            max_attempt_entries=MAX_ATTEMPT_ENTRIES,
        )
    except Exception:  # noqa: BLE001 - the next tick reaps what this one could not
        logger.exception("SDK regen: lease sweep failed")
        return 0
    for job in reaped:
        logger.warning(
            "SDK regen: job %s outlived its %ds lease and was dead-lettered", job.get("id"), lease_seconds
        )
        notify_dead_lettered(db, job)
    return len(reaped)


def process_sdk_regen_sweep(
    db: Any = None,
    *,
    publish_transport: Optional[PublishTransport] = None,
    git_client_factory: Optional[ClientFactory] = None,
    apiome_version: Optional[str] = None,
) -> int:
    """Run one auto-regen tick: reap lost claims, then run up to a batch of due jobs (SDK-4.3).

    The global ``APIOME_SDK_REGEN_ENABLED`` kill switch short-circuits the whole tick, so an
    operator can stop every automatic release during an incident without touching a subscription.

    Args:
        db: Database handle for this tick. :mod:`app.main` passes a dedicated connection per tick,
            like the other sweeps; defaults to the shared handle.
        publish_transport: Upload transport override (tests).
        git_client_factory: GitHub client override (tests).
        apiome_version: The running API version, recorded as provenance.

    Returns:
        How many jobs were claimed and run this tick.
    """
    from .config import settings

    handle = db if db is not None else default_db
    if not settings.sdk_regen_enabled:
        logger.info("SDK regen sweep halted: APIOME_SDK_REGEN_ENABLED is disabled")
        return 0

    reap_lost_jobs(handle, lease_seconds=max(1, int(settings.sdk_regen_lease_seconds)))

    executed = 0
    for _ in range(max(1, int(settings.sdk_regen_batch_size))):
        try:
            row = handle.claim_next_sdk_regen_job(str(uuid.uuid4()))
        except Exception:  # noqa: BLE001 - a failed claim retries on the next tick
            logger.exception("SDK regen: claim failed")
            break
        if not row:
            break
        executed += 1
        try:
            run_claimed_job(
                handle,
                row,
                publish_transport=publish_transport,
                git_client_factory=git_client_factory,
                apiome_version=apiome_version,
            )
        except Exception:  # noqa: BLE001 - one job never aborts the sweep; the lease catches it
            logger.exception("SDK regen: job %s could not be recorded", row.get("id"))
    return executed
