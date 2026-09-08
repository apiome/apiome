"""Scheduled verification endpoints — CTG-4.4 (#4501).

Six routes over one idea: *keep checking this deployment, and tell us when it drifts.*

* ``GET/POST   /v1/tenants/{tenant}/verification-schedules`` — what is being watched, and define
  something new to watch. The list read is the freshness lookup CTG-4.5 consumes: filter by
  ``version_ref`` and every schedule comes back with ``last_success_at`` and ``freshness_seconds``.
* ``GET/PATCH/DELETE …/verification-schedules/{schedule_ref}`` — read, retune, retire. A schedule is
  addressable by handle or by id, the same way a verification target is.
* ``GET …/verification-schedules/{schedule_ref}/runs`` — the write-once history: what each tick
  found, whether it notified, and why.

**Permissions reuse the two resources this surface already has.** Defining *where and how often* a
deployment is checked is the same class of decision as defining where verification points, so
schedule management is governed by ``verification_targets`` (Owner/Admin manage, Editor and Viewer
read). The run history is verification evidence, so it is governed by ``verification_evidence``.
Neither earns a resource of its own: adding one costs four synchronised edits across the database,
this enum, the enforcement call sites, and the UI role matrix.

**Scheduling state is not writable here.** A PATCH changes the cadence, the name, the options, or
whether the schedule is paused. It cannot touch the freshness anchor, the alert state, or the
failure counters — those are the sweep's record of what actually happened.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .verification_schedule import (
    CADENCE_PRESETS,
    CODE_CADENCE_INVALID,
    CODE_NOT_FOUND,
    CODE_PAIR_TAKEN,
    CODE_SLUG_INVALID,
    CODE_SLUG_TAKEN,
    CODE_TARGET_UNKNOWN,
    CODE_VERSION_REF_INVALID,
    RUN_STATUSES,
    ScheduleValidationError,
    VerificationScheduleInput,
    VerificationSchedulePatch,
    VerificationScheduleRecord,
    VerificationScheduleRunRecord,
)
from .verification_schedule_store import (
    create_schedule,
    delete_schedule,
    get_schedule,
    list_runs,
    list_schedules,
    update_schedule,
)
from .verification_target_store import actor_from_auth

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["contract-assurance"])

#: Which HTTP status each refusal deserves. A duplicate is a conflict, a missing schedule or target
#: is a 404, and a malformed definition is a 400 — so a caller can branch on the status without
#: parsing the code, and on the code when it wants to be precise.
_STATUS_BY_CODE = {
    CODE_NOT_FOUND: 404,
    CODE_TARGET_UNKNOWN: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_PAIR_TAKEN: 409,
    CODE_SLUG_INVALID: 400,
    CODE_CADENCE_INVALID: 400,
    CODE_VERSION_REF_INVALID: 400,
}

#: Rendered into the create/patch descriptions so the accepted cadence names live in one place.
_CADENCE_HELP = ", ".join(f"`{name}`" for name in CADENCE_PRESETS)


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant context.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: ScheduleValidationError) -> HTTPException:
    """Map a schedule refusal onto its HTTP status, keeping the stable code in the body.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


@router.get(
    "/{tenant_slug}/verification-schedules",
    response_model=List[VerificationScheduleRecord],
    summary="List scheduled verifications",
    description=(
        "Every live verification schedule in the tenant, newest first, each carrying its "
        "**freshness**: `last_success_at` and `freshness_seconds` — the seconds since this "
        "deployment last verified clean.\n\n"
        "`freshness_seconds` is `null` when the schedule has never verified clean. A gate must "
        "read that as *unknown*, never as *fresh*.\n\n"
        "Filter by `version_ref` to ask \"is this version's deployment being watched, and how "
        "recently?\", by `target_id` for one deployment, or by `enabled` to find what is paused.\n\n"
        "Requires `verification_targets:view`."
    ),
)
async def list_verification_schedules(
    tenant_slug: str,
    version_ref: Optional[str] = Query(
        default=None, description="Restrict to one version reference."
    ),
    target_id: Optional[str] = Query(
        default=None, description="Restrict to one verification target."
    ),
    enabled: Optional[bool] = Query(
        default=None, description="Restrict to enabled (`true`) or paused (`false`) schedules."
    ),
    limit: int = Query(default=100, ge=1, le=200, description="Maximum schedules to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VerificationScheduleRecord]:
    """List the tenant's live schedules.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes the read).
        version_ref: Optional version filter.
        target_id: Optional target filter.
        enabled: Optional paused/enabled filter.
        limit: Maximum schedules.
        auth_data: Authenticated principal.

    Returns:
        The schedules, newest first.

    Raises:
        HTTPException: 403 without ``verification_targets:view``.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_TARGETS, Action.VIEW)
    _ = tenant_slug
    return list_schedules(
        _tenant_id(auth_data),
        version_ref=version_ref,
        target_id=target_id,
        enabled=enabled,
        limit=limit,
    )


@router.post(
    "/{tenant_slug}/verification-schedules",
    response_model=VerificationScheduleRecord,
    status_code=201,
    summary="Schedule recurring verification of a deployment",
    description=(
        "Define a standing instruction: verify one published version against one registered "
        "deployment on a cadence, and notify when it drifts.\n\n"
        "**Each tick is a CTG-4.3 run, unchanged.** The same suite is compiled, the same "
        "requests are sent, the same mutation rules apply (safe methods only unless the target "
        "policy, the schedule's `verification.allow_mutating`, *and* a fixture naming the "
        "operation all agree), and the same immutable evidence and conformance report are "
        "written. A scheduled check that behaved differently from a manual one would be "
        "worthless as a gate input.\n\n"
        f"**Cadence** is a number of seconds or one of {_CADENCE_HELP}. The floor is five "
        "minutes: anything shorter against a live deployment is load, not monitoring.\n\n"
        "**Alerting is quiet by design.** A pass→fail transition notifies exactly once; a repeat "
        "of the same failure is silent; a failure whose set of violations *changed* notifies "
        "again, because new drift hiding behind old drift is how a second regression is missed. "
        "Recovery notifies unless `alert_on_recovery` is false.\n\n"
        "One live schedule per handle, and one per (version, deployment) pair — a second schedule "
        "for the same pair would double the traffic and double every alert.\n\n"
        "Requires `verification_targets:create`."
    ),
)
async def create_verification_schedule(
    tenant_slug: str,
    body: VerificationScheduleInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VerificationScheduleRecord:
    """Define a new schedule.

    Args:
        tenant_slug: Tenant in the URL.
        body: The schedule definition.
        auth_data: Authenticated principal.

    Returns:
        The stored schedule.

    Raises:
        HTTPException: 400 for a rejected definition, 404 for an unknown target, 409 for a
            duplicate handle or pair, 403 without ``verification_targets:create``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_TARGETS, Action.CREATE, target=body.slug
    )
    _ = tenant_slug
    try:
        return create_schedule(
            _tenant_id(auth_data), body, actor=actor_from_auth(auth_data, user_id)
        )
    except ScheduleValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/verification-schedules/{schedule_ref}",
    response_model=VerificationScheduleRecord,
    summary="Read one scheduled verification",
    description=(
        "Read a schedule by its handle or its id, with its current freshness and alert state.\n\n"
        "`alert_state` is `alerting` while drift is outstanding — that is the state which makes "
        "a repeated failure quiet, and it clears when the deployment verifies clean again.\n\n"
        "Requires `verification_targets:view`."
    ),
)
async def read_verification_schedule(
    tenant_slug: str,
    schedule_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VerificationScheduleRecord:
    """Read one schedule.

    Args:
        tenant_slug: Tenant in the URL.
        schedule_ref: The schedule's handle or id.
        auth_data: Authenticated principal.

    Returns:
        The schedule.

    Raises:
        HTTPException: 404 when nothing live matches, 403 without ``verification_targets:view``.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_TARGETS, Action.VIEW)
    _ = tenant_slug
    try:
        return get_schedule(_tenant_id(auth_data), schedule_ref)
    except ScheduleValidationError as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{tenant_slug}/verification-schedules/{schedule_ref}",
    response_model=VerificationScheduleRecord,
    summary="Retune or pause a scheduled verification",
    description=(
        "Change the cadence, the name, the run options, or whether the schedule ticks. "
        "A paused schedule (`enabled: false`) keeps its history and its freshness anchor.\n\n"
        "**The scheduling state is not settable here.** `last_success_at`, `alert_state`, and the "
        "failure counters are the sweep's record of what actually happened; a monitor whose "
        "freshness could be edited would not be a monitor.\n\n"
        f"**Cadence** accepts seconds or one of {_CADENCE_HELP}.\n\n"
        "Requires `verification_targets:edit`."
    ),
)
async def update_verification_schedule(
    tenant_slug: str,
    schedule_ref: str,
    body: VerificationSchedulePatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VerificationScheduleRecord:
    """Update one schedule.

    Args:
        tenant_slug: Tenant in the URL.
        schedule_ref: The schedule's handle or id.
        body: The partial update.
        auth_data: Authenticated principal.

    Returns:
        The updated schedule.

    Raises:
        HTTPException: 400 for a rejected cadence, 404 when nothing live matches, 403 without
            ``verification_targets:edit``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_TARGETS, Action.EDIT, target=schedule_ref
    )
    _ = tenant_slug
    try:
        return update_schedule(
            _tenant_id(auth_data),
            schedule_ref,
            body,
            actor=actor_from_auth(auth_data, user_id),
        )
    except ScheduleValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/verification-schedules/{schedule_ref}",
    status_code=204,
    summary="Retire a scheduled verification",
    description=(
        "Stop the schedule ticking. The retirement is a **soft delete**: the run history stays, "
        "because \"when did this version last verify clean?\" outlives the instruction that "
        "answered it.\n\n"
        "To stop checks temporarily, PATCH `enabled: false` instead — a paused schedule can be "
        "resumed, a retired one cannot.\n\n"
        "Requires `verification_targets:delete`."
    ),
)
async def remove_verification_schedule(
    tenant_slug: str,
    schedule_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Retire one schedule.

    Args:
        tenant_slug: Tenant in the URL.
        schedule_ref: The schedule's handle or id.
        auth_data: Authenticated principal.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 when nothing live matches, 403 without ``verification_targets:delete``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_TARGETS, Action.DELETE, target=schedule_ref
    )
    _ = tenant_slug
    try:
        delete_schedule(
            _tenant_id(auth_data), schedule_ref, actor=actor_from_auth(auth_data, user_id)
        )
    except ScheduleValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


@router.get(
    "/{tenant_slug}/verification-schedules/{schedule_ref}/runs",
    response_model=List[VerificationScheduleRunRecord],
    summary="Read a schedule's verification history",
    description=(
        "The write-once history of what each tick found, newest first: the verdict, the coverage "
        "it measured, how much drift it saw, and — for every tick, not only the noisy ones — "
        "whether it notified and why. \"Why was I not paged?\" is answerable from the history "
        "rather than from a worker's log.\n\n"
        "`status` is `passed`, `failed` (the deployment contradicted the contract), or `errored` "
        "(no verdict to trust — the deployment never answered, or the run could not be executed "
        "at all; the latter carries an `error_code`).\n\n"
        "`drift_fingerprint` is the digest of the violation set: two failing ticks with the same "
        "fingerprint found the same thing, which is exactly when the second one stays silent.\n\n"
        "Requires `verification_evidence:view` — a verification history is evidence."
    ),
)
async def list_verification_schedule_runs(
    tenant_slug: str,
    schedule_ref: str,
    status: Optional[str] = Query(
        default=None, description="Restrict to `passed`, `failed`, or `errored`."
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum ticks to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VerificationScheduleRunRecord]:
    """List one schedule's recorded ticks.

    Args:
        tenant_slug: Tenant in the URL.
        schedule_ref: The schedule's handle or id.
        status: Optional verdict filter.
        limit: Maximum rows.
        auth_data: Authenticated principal.

    Returns:
        The history, newest first.

    Raises:
        HTTPException: 400 for an unknown status filter, 404 when no such schedule exists,
            403 without ``verification_evidence:view``.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    _ = tenant_slug
    if status is not None and status not in RUN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "schedule-run-status-invalid",
                "message": f"status must be one of: {', '.join(RUN_STATUSES)}",
            },
        )
    tenant_id = _tenant_id(auth_data)
    try:
        schedule = get_schedule(tenant_id, schedule_ref)
    except ScheduleValidationError as exc:
        raise _http_error(exc) from exc
    return list_runs(tenant_id, schedule.id, status=status, limit=limit)
