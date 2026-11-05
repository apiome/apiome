"""Auto-export on version publish: the queue and the sweep — MFX-39.4 (#4336).

* :func:`enqueue_auto_export_on_publish` — the publish hook. Run after the publish's response
  (``BackgroundTasks``), it queues one ``export_auto_runs`` row per active subscription of the project. A
  failure is logged, never raised: **a publish never fails because of a subscription.**
* :func:`process_auto_export_sweep` — the sweep ``main.py`` ticks. It fails runs whose worker outlived
  ``APIOME_EXPORT_AUTO_LEASE_SECONDS`` (their export job lived on a lost instance), then claims up to
  ``APIOME_EXPORT_AUTO_BATCH_SIZE`` pending runs (``FOR UPDATE SKIP LOCKED``, so replicas share the queue)
  and runs each with :func:`run_auto_export`.
* :func:`run_auto_export` — one run: apply the preset to the published revision, run the export job on this
  instance's engine, measure its loss (:func:`app.export_auto.measure_loss`), and then either **halt** —
  nothing delivered, the publisher and the subscription's owner notified — or deliver through the preset's
  delivery profiles (:func:`app.export_delivery_profile_routes.deliver_with_profile`), as the publisher.
* :func:`release_halted_run` — a person delivers a halted run anyway, while its artifact is retained.

Every outcome lands on the run row and in the audit log (``export.auto_export.*``).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional

from fastapi import HTTPException

from .auth import get_authenticated_user_id
from .config import settings
from .export_auto import build_auto_request, halt_notice, measure_loss, should_halt
from .export_job_engine import export_job_timeout_seconds, get_export_job_status, schedule_export_job
from .export_presets import ExportPresetRequestError, preset_profile_ids
from .export_service import ExportError
from .notification_fanout import NotificationDraft
from .notifications import TYPE_EXPORT_AUTO_HALTED
from .revision_deprecation import is_uuid_string
from .sdk_publish_routes import write_audit

logger = logging.getLogger(__name__)

__all__ = [
    "AUDIT_COMPLETED",
    "AUDIT_FAILED",
    "AUDIT_HALTED",
    "AUDIT_RELEASED",
    "enqueue_auto_export_on_publish",
    "process_auto_export_sweep",
    "release_halted_run",
    "run_auto_export",
]

AUDIT_COMPLETED = "export.auto_export.completed"
AUDIT_HALTED = "export.auto_export.halted"
AUDIT_FAILED = "export.auto_export.failed"
AUDIT_RELEASED = "export.auto_export.released"

#: Seconds between polls of a running export job.
POLL_SECONDS = 2.0


def enqueue_auto_export_on_publish(
    *, db: Any, tenant_id: str, project_id: str, version_record_id: str, actor_id: Optional[str] = None
) -> int:
    """Queue the auto-exports a publish triggers — the publish hook (never raises).

    Args:
        db: The database.
        tenant_id: The publishing tenant.
        project_id: The published project.
        version_record_id: The published revision.
        actor_id: Who published; the runs deliver, and are audited, as them.

    Returns:
        How many runs were queued (``0`` on any failure, or with no active subscription).
    """
    if not (is_uuid_string(str(tenant_id or "")) and is_uuid_string(str(project_id or ""))):
        return 0
    try:
        return int(db.enqueue_export_auto_runs(tenant_id=str(tenant_id), project_id=str(project_id),
                                               version_record_id=str(version_record_id), published_by=actor_id))
    except Exception:  # noqa: BLE001 - a publish never fails because of a subscription
        logger.exception("Could not queue auto-exports for project %s", project_id)
        return 0


def _auth_for(run: Mapping[str, Any]) -> Dict[str, Any]:
    """The principal an auto-export delivers and audits as: the publisher."""
    return {"tenant_id": str(run["tenant_id"]), "user_id": run.get("published_by") or "",
            "user_name": "Auto-export on publish", "auth_method": "auto_export"}


def _notify(db: Any, run: Mapping[str, Any], *, created_by: Optional[str] = None) -> int:
    """Tell the publisher (and the subscription's owner) that an auto-export halted or failed."""
    recipients = [user for user in dict.fromkeys([run.get("published_by"), created_by]) if user]
    if not recipients:
        return 0
    payload = halt_notice(run, project_name=run.get("project_name"))
    drafts = [NotificationDraft(user_id=str(user), type=TYPE_EXPORT_AUTO_HALTED, payload=payload,
                                actor_id=None, project_id=str(run["project_id"]), version_id=None)
              for user in recipients]
    try:
        return db.notify_export_auto_run(str(run["tenant_id"]), drafts)
    except Exception:  # noqa: BLE001 - the run's record stands even when the inbox write fails
        logger.exception("Could not notify about auto-export run %s", run.get("id"))
        return 0


def _audit(run: Mapping[str, Any], action: str, **detail: Any) -> None:
    write_audit(tenant_id=str(run["tenant_id"]), action=action, auth_data=_auth_for(run),
                target=str(run["project_id"]),
                detail={"runId": run.get("id"), "preset": run.get("preset_name"),
                        "versionRecordId": run.get("version_record_id"), **detail})


async def _wait_for_job(tenant_slug: str, job_id: str) -> Any:
    """Poll an export job until it is terminal (or past its own cap plus a margin)."""
    cap = export_job_timeout_seconds()
    deadline = time.monotonic() + (cap + 120 if cap else 4 * 3600)
    while True:
        status = await get_export_job_status(tenant_slug, job_id)
        if status.state in ("completed", "failed", "canceled") or time.monotonic() >= deadline:
            return status
        await asyncio.sleep(POLL_SECONDS)


async def _deliver(run: Mapping[str, Any], tenant_slug: str, job_id: str, profiles: List[str],
                   auth_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Deliver a finished job with each profile, recording each outcome (one failing never stops the next)."""
    # Imported here: the delivery routes build on the export engine this module schedules on.
    from .export_delivery_profile_routes import deliver_with_profile

    outcomes: List[Dict[str, Any]] = []
    for profile_id in profiles:
        try:
            attempt = await deliver_with_profile(tenant_slug, str(run["tenant_id"]), job_id, profile_id, auth_data)
            outcomes.append({"profileId": profile_id, "profileName": attempt.profile_name, "channel": attempt.channel,
                             "runId": attempt.run_id, "status": attempt.status, "outcome": attempt.outcome,
                             "destination": attempt.destination, "errorCode": attempt.error_code})
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            outcomes.append({"profileId": profile_id, "outcome": "failed",
                             "errorCode": detail.get("code") or f"http-{exc.status_code}",
                             "errorMessage": detail.get("message")})
        except Exception:  # noqa: BLE001 - one broken delivery must not stop the next
            logger.exception("Auto-export delivery with profile %s failed", profile_id)
            outcomes.append({"profileId": profile_id, "outcome": "failed",
                             "errorCode": "export-auto-delivery-internal-error"})
    return outcomes


def _delivered_status(outcomes: List[Dict[str, Any]]) -> str:
    if not outcomes:
        return "exported"
    return "delivery_failed" if any(o.get("outcome") == "failed" for o in outcomes) else "delivered"


async def run_auto_export(db: Any, run: Dict[str, Any]) -> Dict[str, Any]:
    """Run one claimed auto-export to a terminal status.

    Args:
        db: The database.
        run: The claimed row (:meth:`app.database.Database.claim_next_export_auto_run`).

    Returns:
        The closed run row (or the claimed row, when it could not be closed).
    """
    token = run.get("claim_token")
    tenant_slug = str(run.get("tenant_slug") or "")

    async def finish(status: str, **fields: Any) -> Dict[str, Any]:
        row = await asyncio.to_thread(db.finish_export_auto_run, str(run["id"]), status=status,
                                      claim_token=token, **fields)
        return {**run, **(row or {}), "project_name": run.get("project_name")}

    async def fail(code: str, message: str, created_by: Optional[str] = None) -> Dict[str, Any]:
        closed = await finish("failed", error_code=code, error_message=message)
        _audit(closed, AUDIT_FAILED, errorCode=code)
        await asyncio.to_thread(_notify, db, closed, created_by=created_by)
        return closed

    subscription = None
    if run.get("subscription_id"):
        subscription = await asyncio.to_thread(db.get_export_auto_subscription, str(run["tenant_id"]),
                                               str(run["subscription_id"]))
    owner = (subscription or {}).get("created_by")
    if run.get("preset_targets") is None:
        return await fail("export-auto-preset-missing", "The export preset was deleted before the export ran.", owner)
    preset = {"id": run.get("preset_id"), "name": run.get("preset_name"), "targets": run.get("preset_targets"),
              "delivery_profile_id": run.get("preset_delivery_profile_id"),
              "delivery_profile_ids": run.get("preset_delivery_profile_ids") or []}
    try:
        request, profiles = build_auto_request(str(run["project_id"]), str(run["version_record_id"]), preset)
    except ExportPresetRequestError as exc:
        return await fail("export-auto-preset-invalid", "; ".join(exc.errors), owner)

    try:
        accepted = await schedule_export_job(tenant_slug, str(run["tenant_id"]), request)
    except ExportError as exc:
        if exc.status_code == 429:
            # The tenant's export slots are full: hand the run back to the queue for the next tick.
            return await finish("pending")
        return await fail("export-auto-export-refused", str(exc), owner)
    job_id = accepted.job_id
    await asyncio.to_thread(db.set_export_auto_run_job, str(run["id"]), str(token), job_id)
    run["job_id"] = job_id

    status = await _wait_for_job(tenant_slug, job_id)
    if status.state != "completed" or status.result is None:
        error = status.error
        return await fail(getattr(error, "code", None) or f"export-auto-job-{status.state}",
                          getattr(error, "message", None) or f"The export job is {status.state}.", owner)

    severity, reasons = measure_loss(status.result)
    if should_halt(severity, str(run.get("halt_at") or "critical"), bool(run.get("approve_loss"))):
        closed = await finish("halted", loss_severity=severity, loss_reasons=reasons)
        _audit(closed, AUDIT_HALTED, jobId=job_id, lossSeverity=severity, reasons=reasons)
        await asyncio.to_thread(_notify, db, closed, created_by=owner)
        return closed

    outcomes = await _deliver(run, tenant_slug, job_id, profiles, _auth_for(run))
    closed = await finish(_delivered_status(outcomes), loss_severity=severity, loss_reasons=reasons,
                          deliveries=outcomes)
    _audit(closed, AUDIT_COMPLETED, jobId=job_id, lossSeverity=severity, approvedLoss=bool(run.get("approve_loss"))
           and severity != "info", deliveries=[{k: o.get(k) for k in ("profileId", "outcome", "errorCode")}
                                               for o in outcomes])
    return closed


async def process_auto_export_sweep(db: Any) -> int:
    """One tick: reap lost runs, then run up to a batch of pending ones.

    Args:
        db: The database.

    Returns:
        How many runs this tick ran.
    """
    if not settings.export_auto_enabled:
        return 0
    for lost in await asyncio.to_thread(db.reap_stale_export_auto_runs, settings.export_auto_lease_seconds):
        _audit(lost, AUDIT_FAILED, errorCode=lost.get("error_code"))
        await asyncio.to_thread(_notify, db, lost)
    ran = 0
    for _ in range(max(1, int(settings.export_auto_batch_size))):
        token = str(uuid.uuid4())
        run = await asyncio.to_thread(db.claim_next_export_auto_run, token)
        if not run:
            break
        run["claim_token"] = token
        try:
            closed = await run_auto_export(db, run)
        except Exception:  # noqa: BLE001 - one broken run must not stop the sweep
            logger.exception("Auto-export run %s failed", run.get("id"))
            await asyncio.to_thread(db.finish_export_auto_run, str(run["id"]), status="failed", claim_token=token,
                                    error_code="export-auto-internal-error",
                                    error_message="The auto-export failed unexpectedly.")
            continue
        ran += 1
        if closed.get("status") == "pending":
            break  # export slots are full; try again next tick
    return ran


async def release_halted_run(db: Any, run: Mapping[str, Any], auth_data: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver a halted run anyway, with the preset's delivery profiles, as the releasing user.

    Args:
        db: The database.
        run: The halted run (:meth:`app.database.Database.get_export_auto_run`).
        auth_data: The releasing user (already checked for ``versions:publish``).

    Returns:
        The run, re-closed ``delivered`` / ``delivery_failed`` / ``exported`` with ``released_by``.

    Raises:
        HTTPException: 409 when the run is not halted, or its preset no longer names a delivery profile.
    """
    if run.get("status") != "halted" or not run.get("job_id"):
        raise HTTPException(status_code=409, detail={"code": "export-auto-not-halted",
                                                     "message": "Only a halted auto-export can be released."})
    preset = None
    if run.get("preset_id"):
        preset = await asyncio.to_thread(db.get_export_preset, str(run["tenant_id"]), str(run["preset_id"]))
    profiles = preset_profile_ids(preset or {})
    if not profiles:
        raise HTTPException(status_code=409, detail={
            "code": "export-auto-nothing-to-deliver",
            "message": "The preset no longer names a delivery profile; deliver the export from its job instead."})
    outcomes = await _deliver(run, str(run["tenant_slug"]), str(run["job_id"]), profiles, auth_data)
    released_by = get_authenticated_user_id(auth_data)
    row = await asyncio.to_thread(db.finish_export_auto_run, str(run["id"]), status=_delivered_status(outcomes),
                                  deliveries=outcomes, error_code=None, error_message=None, released_by=released_by)
    write_audit(tenant_id=str(run["tenant_id"]), action=AUDIT_RELEASED, auth_data=auth_data,
                target=str(run["project_id"]),
                detail={"runId": run.get("id"), "preset": run.get("preset_name"), "jobId": run.get("job_id"),
                        "lossSeverity": run.get("loss_severity"),
                        "deliveries": [{k: o.get(k) for k in ("profileId", "outcome", "errorCode")} for o in outcomes]})
    return {**run, **(row or {})}

