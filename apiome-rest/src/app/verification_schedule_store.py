"""Persistence for verification schedules and their run history — CTG-4.4 (#4501).

:mod:`app.verification_schedule` decides *what* a schedule is and *when* it notifies; this module
is the only place one is written or read, so V253's guarantees are applied once rather than at each
call site.

**A schedule is refused before it is stored.** The handle shape, the version-reference shape, the
cadence band, and the existence of the named deployment are all checked here, in cheapest-first
order, so a definition that is wrong in an obvious way never costs a target resolution. The two
uniqueness rules the database also keeps — one live schedule per handle, one per (version,
deployment) pair — are checked here as well, so a caller gets a stable code rather than a driver
error about a unique index.

**Scheduling state is not writable through the front door.** A PATCH can change the cadence, the
name, the options, or whether the schedule is paused. It cannot touch ``last_success_at``,
``alert_state``, or the failure counters: those are the sweep's record of what actually happened,
and a monitor whose freshness can be edited by the thing being monitored is not a monitor.
:meth:`Database.update_verification_schedule` enforces this with a column whitelist; this module
never assembles one from caller keys.

**Retiring a schedule keeps its history.** Delete is a soft delete, because "when did this version
last verify clean?" outlives the instruction that answered it.

**Nothing reaches the database on a malformed id.** Every accessor short-circuits on a non-UUID
tenant or schedule id and returns the empty value for its type.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import db as _default_db
from .verification_schedule import (
    ALERT_STATE_OK,
    CODE_NOT_FOUND,
    CODE_PAIR_TAKEN,
    CODE_SLUG_TAKEN,
    CODE_TARGET_UNKNOWN,
    STATUS_PASSED,
    AlertDecision,
    ScheduleValidationError,
    TickOutcome,
    VerificationScheduleInput,
    VerificationSchedulePatch,
    VerificationScheduleRecord,
    VerificationScheduleRunRecord,
    record_from_row,
    resolve_cadence_seconds,
    run_record_from_row,
    summarize_tick,
    validate_schedule_slug,
    validate_version_ref,
)
from .verification_target import TargetValidationError
from .verification_target_store import TargetActor, get_target

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_RUN_LIST_LIMIT",
    "MAX_SCHEDULE_LIST_LIMIT",
    "create_schedule",
    "delete_schedule",
    "get_schedule",
    "list_runs",
    "list_schedules",
    "record_tick",
    "update_schedule",
]

#: Ceiling on a schedule list read.
MAX_SCHEDULE_LIST_LIMIT = 200
#: Ceiling on a run-history read. A trend view asks for the newest few hundred, not the archive.
MAX_RUN_LIST_LIMIT = 500


def _handle(handle: Any) -> Any:
    """Return the database handle to use.

    The sweep runs on its own connection (advisory locks are session-scoped), so every accessor
    accepts one; routes use the shared singleton.

    Args:
        handle: An explicit handle, or ``None``.

    Returns:
        The handle.
    """
    return handle if handle is not None else _default_db


def list_schedules(
    tenant_id: str,
    *,
    version_ref: Optional[str] = None,
    target_id: Optional[str] = None,
    enabled: Optional[bool] = None,
    limit: int = 100,
    handle: Any = None,
    now: Optional[datetime] = None,
) -> List[VerificationScheduleRecord]:
    """A tenant's live schedules, newest first, each carrying its freshness.

    Args:
        tenant_id: The caller's tenant.
        version_ref: Restrict to one version reference.
        target_id: Restrict to one verification target.
        enabled: Restrict to enabled or paused schedules.
        limit: Maximum schedules (clamped to 1..200).
        handle: Database handle; the shared singleton by default.
        now: Reference instant for the freshness computation.

    Returns:
        The records; empty when nothing matches.
    """
    rows = _handle(handle).list_verification_schedules(
        tenant_id,
        version_ref=version_ref,
        target_id=target_id,
        enabled=enabled,
        limit=max(1, min(int(limit), MAX_SCHEDULE_LIST_LIMIT)),
    )
    return [record_from_row(row, now=now) for row in rows]


def get_schedule(
    tenant_id: str,
    schedule_ref: str,
    *,
    handle: Any = None,
    now: Optional[datetime] = None,
) -> VerificationScheduleRecord:
    """Read one schedule by handle **or** id.

    Accepting both is what lets a pipeline name a stable handle (``petstore-staging``) while an
    alert payload names an immutable id — the same endpoint answers either.

    Args:
        tenant_id: The caller's tenant.
        schedule_ref: The schedule's slug or its id.
        handle: Database handle.
        now: Reference instant for the freshness computation.

    Returns:
        The record.

    Raises:
        ScheduleValidationError: :data:`CODE_NOT_FOUND` when nothing live matches in this tenant.
    """
    database = _handle(handle)
    row = database.get_verification_schedule_by_slug(tenant_id, schedule_ref)
    if row is None:
        row = database.get_verification_schedule_by_id(schedule_ref, tenant_id)
    if row is None:
        raise ScheduleValidationError(
            CODE_NOT_FOUND, f"no verification schedule '{schedule_ref}' in this tenant"
        )
    return record_from_row(row, now=now)


def create_schedule(
    tenant_id: str,
    definition: VerificationScheduleInput,
    *,
    actor: TargetActor,
    handle: Any = None,
) -> VerificationScheduleRecord:
    """Define a new schedule, validating it before anything is stored.

    Order matters: the handle shape, then the reference shape, then the cadence, then the target
    resolution (the only check that costs a database read of another table), then the two
    uniqueness reads. A definition that is wrong in a cheap way never pays for the expensive check.

    Args:
        tenant_id: The caller's tenant.
        definition: The full definition.
        actor: Who is defining it; recorded as creator.
        handle: Database handle.

    Returns:
        The stored record.

    Raises:
        ScheduleValidationError: For an unusable handle, reference, or cadence; an unknown target;
            a handle already in use; or a pair already watched.
    """
    database = _handle(handle)
    slug = validate_schedule_slug(definition.slug)
    version_ref = validate_version_ref(definition.version_ref)
    cadence_seconds = resolve_cadence_seconds(definition.cadence)

    try:
        target = get_target(tenant_id, definition.target_ref)
    except TargetValidationError as exc:
        raise ScheduleValidationError(
            CODE_TARGET_UNKNOWN,
            f"no verification target '{definition.target_ref}' in this tenant — define the "
            "deployment before scheduling checks against it",
        ) from exc

    if database.get_verification_schedule_by_slug(tenant_id, slug) is not None:
        raise ScheduleValidationError(
            CODE_SLUG_TAKEN, f"a verification schedule named '{slug}' already exists"
        )
    existing = database.find_verification_schedule_for_pair(tenant_id, version_ref, target.id)
    if existing is not None:
        raise ScheduleValidationError(
            CODE_PAIR_TAKEN,
            f"schedule '{existing.get('slug')}' already verifies {version_ref} against "
            f"'{target.slug}'; change its cadence rather than adding a second one",
        )

    row = database.insert_verification_schedule(
        schedule={
            "tenant_id": tenant_id,
            "slug": slug,
            "name": definition.name,
            "description": definition.description,
            "version_ref": version_ref,
            "target_id": target.id,
            "target_slug": target.slug,
            "cadence_seconds": cadence_seconds,
            "enabled": definition.enabled,
            "alert_on_recovery": definition.alert_on_recovery,
            "verification": definition.verification.model_dump(mode="json"),
            "suite_options": definition.options.model_dump(mode="json"),
            "created_by": actor.user_id,
        }
    )
    if row is None:
        raise ScheduleValidationError(
            CODE_TARGET_UNKNOWN,
            "the schedule could not be stored: the tenant or target identifier is not a UUID",
        )
    return record_from_row(row)


def update_schedule(
    tenant_id: str,
    schedule_ref: str,
    patch: VerificationSchedulePatch,
    *,
    actor: TargetActor,
    handle: Any = None,
) -> VerificationScheduleRecord:
    """Apply a partial update to one schedule.

    An empty patch is not an error — it reads the schedule back unchanged, which is what a PATCH
    that sets nothing means.

    Args:
        tenant_id: The caller's tenant.
        schedule_ref: The schedule's slug or id.
        patch: The fields to change.
        actor: Who is changing it.
        handle: Database handle.

    Returns:
        The updated record.

    Raises:
        ScheduleValidationError: :data:`CODE_NOT_FOUND` when nothing live matches, or a cadence
            outside the supported band.
    """
    database = _handle(handle)
    current = get_schedule(tenant_id, schedule_ref, handle=database)
    if not patch.has_changes():
        return current

    # ``description`` is the only nullable column here, so it is the only field where an explicit
    # null means "clear it". Everywhere else a null is a client mistake, not an instruction — and
    # the mistakes it would otherwise become are bad ones: ``enabled: null`` would silently pause a
    # monitor, and ``name: null`` would fail against a NOT NULL column as a 500.
    fields: Dict[str, Any] = {}
    changes = patch.model_dump(exclude_unset=True)
    if "description" in changes:
        fields["description"] = patch.description
    if patch.name is not None:
        fields["name"] = patch.name
    if patch.cadence is not None:
        fields["cadence_seconds"] = resolve_cadence_seconds(patch.cadence)
    if patch.enabled is not None:
        fields["enabled"] = bool(patch.enabled)
    if patch.alert_on_recovery is not None:
        fields["alert_on_recovery"] = bool(patch.alert_on_recovery)
    if patch.verification is not None:
        fields["verification"] = patch.verification.model_dump(mode="json")
    if patch.options is not None:
        fields["suite_options"] = patch.options.model_dump(mode="json")

    row = database.update_verification_schedule(
        current.id, tenant_id, fields=fields, updated_by=actor.user_id
    )
    if row is None:
        # Nothing settable survived the whitelist (e.g. an explicit null-only patch), so the
        # schedule is unchanged rather than missing.
        return current
    return record_from_row(row)


def delete_schedule(
    tenant_id: str, schedule_ref: str, *, actor: TargetActor, handle: Any = None
) -> bool:
    """Retire one schedule, keeping its run history.

    Args:
        tenant_id: The caller's tenant.
        schedule_ref: The schedule's slug or id.
        actor: Who is retiring it.
        handle: Database handle.

    Returns:
        ``True`` when a live schedule was retired.

    Raises:
        ScheduleValidationError: :data:`CODE_NOT_FOUND` when nothing live matches.
    """
    database = _handle(handle)
    current = get_schedule(tenant_id, schedule_ref, handle=database)
    return database.soft_delete_verification_schedule(
        current.id, tenant_id, updated_by=actor.user_id
    )


def list_runs(
    tenant_id: str,
    schedule_id: str,
    *,
    status: Optional[str] = None,
    limit: int = 50,
    handle: Any = None,
) -> List[VerificationScheduleRunRecord]:
    """One schedule's recorded ticks, newest first.

    Args:
        tenant_id: The caller's tenant.
        schedule_id: The schedule id (already resolved from a handle by the caller).
        status: Restrict to one verdict.
        limit: Maximum rows (clamped to 1..500).
        handle: Database handle.

    Returns:
        The records; empty when the schedule has never ticked.
    """
    rows = _handle(handle).list_verification_schedule_runs(
        schedule_id,
        tenant_id,
        status=status,
        limit=max(1, min(int(limit), MAX_RUN_LIST_LIMIT)),
    )
    return [run_record_from_row(row) for row in rows]


def record_tick(
    schedule: VerificationScheduleRecord,
    outcome: TickOutcome,
    decision: AlertDecision,
    *,
    fingerprint: Optional[str] = None,
    alert_deliveries: int = 0,
    handle: Any = None,
) -> Optional[VerificationScheduleRunRecord]:
    """Write one tick's history row and advance the schedule's state.

    The two writes are deliberately ordered: the history row first, then the anchor. A crash
    between them leaves a recorded tick that will be re-run — a duplicate history row, which is
    honest — rather than an advanced anchor with nothing recorded, which would silently skip a
    verification window.

    The trend counts are derived from the tick's report by :func:`summarize_tick`, never accepted
    separately, so a stored history row can never contradict the report it points at.

    Args:
        schedule: The schedule as it was *before* this tick.
        outcome: What the tick produced.
        decision: The alert decision for this tick.
        fingerprint: This tick's own violation-set digest (``None`` for a clean tick). Stored on
            the history row so a later reader can tell two failing ticks apart without recomputing
            them from reports that may since have been purged.
        alert_deliveries: Webhook deliveries actually enqueued.
        handle: Database handle (the sweep passes its own).

    Returns:
        The stored history row, or ``None`` when it could not be written — a storage gap degrades
        the trend line rather than the monitoring itself, so the anchor still advances.
    """
    database = _handle(handle)
    summary = summarize_tick(outcome)
    tick_fingerprint = None if outcome.status == STATUS_PASSED else fingerprint

    stored: Optional[VerificationScheduleRunRecord] = None
    try:
        row = database.insert_verification_schedule_run(
            run={
                "tenant_id": schedule.tenant_id,
                "schedule_id": schedule.id,
                "report_id": outcome.report_id,
                "run_id": outcome.run_id,
                "status": outcome.status,
                "error_code": outcome.error_code,
                "error_message": outcome.error_message,
                "drift_fingerprint": tick_fingerprint,
                "alerted": decision.notify,
                "alert_reason": decision.reason,
                "alert_deliveries": alert_deliveries,
                "started_at": outcome.started_at,
                "finished_at": outcome.finished_at,
                "duration_ms": outcome.duration_ms,
                **summary,
            }
        )
        stored = run_record_from_row(row) if row is not None else None
    except Exception:  # noqa: BLE001 - the tick happened; only its filing did not
        logger.exception(
            "verification schedule %s: run history could not be written", schedule.id
        )

    database.mark_verification_schedule_ran(
        schedule.id,
        schedule.tenant_id,
        status=outcome.status,
        report_id=outcome.report_id,
        alert_state=decision.next_state or ALERT_STATE_OK,
        alert_fingerprint=decision.next_fingerprint,
        alerted=decision.notify,
        succeeded=outcome.status == STATUS_PASSED,
    )
    return stored
