"""The scheduled-verification worker — CTG-4.4 (#4501).

Drift happens between manual checks. CTG-4.3 made a deployment checkable on demand; this module is
the periodic worker (wired in :mod:`app.main`, mirroring :mod:`app.mcp_catalog_digest_sweep`) that
makes the check happen without anybody remembering to ask for it.

On each tick it selects the schedules whose cadence has elapsed
(:meth:`Database.list_due_verification_schedules` — the policy work is done in the database, against
a single ``now()``, so due-ness is free of clock skew and identical for every replica) and, for each
one:

1. takes a per-schedule advisory lock so two workers or two overlapping ticks never run the same
   schedule at once — which would double the traffic at the deployment and could double an alert;
2. executes the **CTG-4.3 service unchanged** (:func:`app.provider_verification_service
   .verify_version_against_target`), so a scheduled run and a manual one compile the same suite,
   send the same requests, obey the same mutation rules, and write the same immutable evidence and
   report — a scheduled check that behaved differently from the one an engineer ran by hand would
   be worthless as a gate input;
3. decides whether to notify (:func:`app.verification_schedule.decide_alert`) and fans the alert out
   over the tenant's existing push-webhook subscriptions; and
4. records the tick in the write-once history and advances the cadence anchor.

**The anchor advances on every processed schedule** — clean, drifting, or unable to run at all — so
a schedule whose version stopped compiling cannot stay perpetually due and hammer the sweep every
tick. This is the same rule the repository-refresh and catalog-digest sweeps follow.

**No idempotency key is passed to the run.** It would be tempting: a deterministic key derived from
the due anchor would make a second replica replay rather than re-execute. It is a trap. The stored
evidence is returned *instead of* a fresh run when the key matches, so if the anchor write ever
failed, the next tick would compute the same key and report the previous tick's verdict as though it
were current — a stale ``passed`` masking live drift. Single-flight is the advisory lock's job;
freshness is not negotiable.

The global ``APIOME_VERIFICATION_SCHEDULE_ENABLED`` kill switch short-circuits the whole tick (like
the discovery, refresh, and digest sweeps' kill switches), so an operator can halt every scheduled
run during an incident without touching per-schedule state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional

from .verification_schedule import (
    ALERT_REASON_RECOVERED,
    STATUS_ERRORED,
    AlertDecision,
    AlertState,
    TickOutcome,
    VerificationScheduleRecord,
    build_alert_payload,
    decide_alert,
    record_from_row,
    run_fingerprint,
)
from .verification_schedule_notifications import (
    EVENT_VERIFICATION_DRIFT_DETECTED,
    EVENT_VERIFICATION_DRIFT_RESOLVED,
    notify_verification_drift,
    notify_verification_recovered,
)
from .verification_schedule_store import record_tick

logger = logging.getLogger(__name__)

__all__ = [
    "execute_scheduled_verification",
    "process_verification_schedule_sweep",
    "run_due_schedule",
]

#: Taxonomy code stamped on a tick that raised something the service does not model. Kept distinct
#: from the service's own codes so "the platform broke" never reads as "the deployment is wrong".
CODE_SWEEP_FAILURE = "INTERNAL_ERROR"

#: V253's ``error_code`` column width. Bounded here rather than trusted, because one source of a
#: code is an exception class name — and a filing failure caused by an over-long code would lose
#: the very tick that was trying to report a problem.
MAX_ERROR_CODE_CHARS = 64


def _code(value: Optional[str]) -> Optional[str]:
    """Bound an error code to what the history column can store.

    Args:
        value: The taxonomy code or exception name.

    Returns:
        The code, truncated to :data:`MAX_ERROR_CODE_CHARS`; ``None`` passes through.
    """
    return None if value is None else str(value)[:MAX_ERROR_CODE_CHARS]


def execute_scheduled_verification(
    schedule: VerificationScheduleRecord,
) -> TickOutcome:
    """Run one schedule's verification, turning every failure mode into an outcome.

    Never raises. A run that could not happen is an ``errored`` tick carrying the taxonomy code
    that says why — which is a fact worth recording and, on the first occurrence, worth an alert.
    Letting it escape would abort the sweep and leave the tick unrecorded, so the next replica
    would rediscover the same breakage and also say nothing.

    Args:
        schedule: The schedule to execute.

    Returns:
        The tick's outcome.
    """
    # Imported lazily: the service pulls in the whole compile/run stack, and the sweep module is
    # imported by ``app.main`` at startup.
    from .provider_verification_service import (
        ProviderVerificationRequest,
        SchemaReferenceError,
        verify_version_against_target,
    )
    from .verification_evidence import EvidenceValidationError
    from .verification_target import TargetValidationError
    from .verification_target_store import TargetActor

    started_at = datetime.now(timezone.utc)
    actor = TargetActor(user_id=None, label=f"schedule:{schedule.slug}", kind="system")
    try:
        # Built inside the guard on purpose: a stored row that can no longer be turned into a
        # valid request (a target handle emptied by a hand-edited row, an options blob from a
        # newer build) is a *recorded* errored tick, not an exception that skips the window.
        request = ProviderVerificationRequest(
            target_ref=schedule.target_slug,
            options=schedule.options,
            verification=schedule.verification,
            idempotency_key=None,
            context={
                "trigger": "schedule",
                "scheduleId": schedule.id,
                "scheduleSlug": schedule.slug,
            },
        )
        response = verify_version_against_target(
            schedule.version_ref,
            request,
            tenant_id=schedule.tenant_id,
            actor=actor,
        )
    except (SchemaReferenceError, TargetValidationError, EvidenceValidationError) as exc:
        return TickOutcome(
            status=STATUS_ERRORED,
            error_code=_code(getattr(exc, "code", None) or exc.__class__.__name__),
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - a broken tick must still be recorded
        logger.exception(
            "verification schedule %s: run raised unexpectedly", schedule.id
        )
        return TickOutcome(
            status=STATUS_ERRORED,
            error_code=CODE_SWEEP_FAILURE,
            error_message=str(exc),
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )

    finished_at = datetime.now(timezone.utc)
    if not response.ok or response.report is None:
        error = response.error
        return TickOutcome(
            status=STATUS_ERRORED,
            error_code=_code(error.code) if error is not None else CODE_SWEEP_FAILURE,
            error_message=(
                f"{error.message} {error.remediation}".strip()
                if error is not None
                else "the scheduled verification produced no report"
            ),
            started_at=started_at,
            finished_at=finished_at,
        )

    report = response.report
    return TickOutcome(
        status=report.outcome,
        report=report,
        report_id=response.stored.id if response.stored is not None else None,
        run_id=response.run.id if response.run is not None else None,
        started_at=report.started_at or started_at,
        finished_at=report.finished_at or finished_at,
    )


def _deliver_alert(
    db: Any,
    schedule: VerificationScheduleRecord,
    outcome: TickOutcome,
    decision: AlertDecision,
) -> List[str]:
    """Build and fan out one alert, never raising.

    Args:
        db: Database handle for the fan-out.
        schedule: The schedule as it was before this tick (its ``last_success_at`` is what makes
            the payload's freshness answer the question "how long has this been wrong?").
        outcome: What the tick produced.
        decision: The alert decision, whose reason selects the event type.

    Returns:
        Enqueued delivery-event ids.
    """
    recovered = decision.reason == ALERT_REASON_RECOVERED
    event = (
        EVENT_VERIFICATION_DRIFT_RESOLVED if recovered else EVENT_VERIFICATION_DRIFT_DETECTED
    )
    payload = build_alert_payload(
        event=event,
        reason=decision.reason or "",
        schedule=schedule,
        outcome=outcome,
        previous_status=schedule.last_status,
        consecutive_failures=0 if recovered else schedule.consecutive_failures + 1,
    )
    try:
        if recovered:
            return notify_verification_recovered(
                db, tenant_id=schedule.tenant_id, payload=payload
            )
        return notify_verification_drift(db, tenant_id=schedule.tenant_id, payload=payload)
    except Exception:  # noqa: BLE001 - fan-out is best-effort by contract; belt and braces
        logger.exception(
            "verification schedule %s: alert fan-out failed", schedule.id
        )
        return []


def run_due_schedule(db: Any, row: Mapping[str, Any]) -> Optional[str]:
    """Execute, judge, notify, and record one due schedule.

    Args:
        db: Database handle for this tick (the same connection that holds the advisory lock).
        row: A row from :meth:`Database.list_due_verification_schedules`.

    Returns:
        The tick's status, or ``None`` when the row could not be read as a schedule.
    """
    try:
        schedule = record_from_row(row)
    except Exception:  # noqa: BLE001 - a row this build cannot read must not abort the tick
        logger.exception("verification schedule sweep: unreadable schedule row")
        return None

    outcome = execute_scheduled_verification(schedule)
    fingerprint = run_fingerprint(
        status=outcome.status,
        drift=outcome.report.drift if outcome.report is not None else (),
        error_code=outcome.error_code,
    )
    decision = decide_alert(
        status=outcome.status,
        fingerprint=fingerprint,
        previous=AlertState(
            state=schedule.alert_state, fingerprint=schedule.alert_fingerprint
        ),
        alert_on_recovery=schedule.alert_on_recovery,
    )

    deliveries: List[str] = []
    if decision.notify:
        deliveries = _deliver_alert(db, schedule, outcome, decision)

    record_tick(
        schedule,
        outcome,
        decision,
        fingerprint=fingerprint,
        alert_deliveries=len(deliveries),
        handle=db,
    )
    logger.info(
        "verification schedule %s (%s) tick: status=%s alerted=%s deliveries=%d",
        schedule.slug,
        schedule.id,
        outcome.status,
        decision.reason or "no",
        len(deliveries),
    )
    return outcome.status


def process_verification_schedule_sweep(db: Any) -> int:
    """Run one scheduled-verification sweep tick over all due schedules (CTG-4.4).

    The global ``APIOME_VERIFICATION_SCHEDULE_ENABLED`` kill switch short-circuits the whole tick.
    One schedule's failure never aborts the rest: each is executed, judged, and recorded
    independently, and a schedule another worker is already running is skipped rather than waited
    for (its next tick is one cadence away).

    Args:
        db: Database handle for this tick. The caller uses a dedicated ``Database`` per tick,
            because the per-schedule advisory locks are session-scoped.

    Returns:
        The number of schedules actually executed this tick.
    """
    from .config import settings

    if not settings.verification_schedule_enabled:
        logger.info(
            "verification schedule sweep halted: APIOME_VERIFICATION_SCHEDULE_ENABLED is disabled"
        )
        return 0

    batch = max(1, int(settings.verification_schedule_batch_size))
    executed = 0
    try:
        due_rows = db.list_due_verification_schedules(limit=batch)
    except Exception:  # noqa: BLE001 - a failed selection retries on the next tick
        logger.exception("verification schedule sweep: due selection failed")
        return 0

    for row in due_rows:
        schedule_id = str(row.get("id") or "")
        if not schedule_id:
            continue
        if not db.try_acquire_verification_schedule_lock(schedule_id):
            logger.debug(
                "verification schedule skipped (lock held) schedule_id=%s", schedule_id
            )
            continue
        try:
            if run_due_schedule(db, row) is not None:
                executed += 1
        except Exception:  # noqa: BLE001 - one schedule never aborts the sweep
            logger.exception(
                "verification schedule sweep failed schedule_id=%s", schedule_id
            )
        finally:
            try:
                db.release_verification_schedule_lock(schedule_id)
            except Exception:  # noqa: BLE001 - the lock dies with the connection anyway
                logger.exception(
                    "verification schedule lock release failed schedule_id=%s", schedule_id
                )

    return executed
