"""Auto-export on version publish routes — MFX-39.4 (#4336).

**Subscriptions** — an export preset run on every publish of a project:

* ``POST   /v1/export/{tenant_slug}/auto-exports`` subscribes one (``projectId``, ``preset``, ``haltAt``,
  ``approveLoss``, ``active``);
* ``GET    /v1/export/{tenant_slug}/auto-exports`` lists them (``?projectId=`` / ``?preset=`` narrow);
* ``PATCH  /v1/export/{tenant_slug}/auto-exports/{subscription_id}`` changes one;
* ``DELETE /v1/export/{tenant_slug}/auto-exports/{subscription_id}`` removes one (its runs stay).

**Runs** — what each publish did:

* ``GET  /v1/export/{tenant_slug}/auto-export-runs`` lists them, newest first;
* ``POST /v1/export/{tenant_slug}/auto-export-runs/{run_id}/release`` delivers a **halted** run anyway.

**Permissions.** Subscribing, turning a subscription on and pre-approving loss is ``projects:edit`` plus
``versions:publish`` — every publish then delivers outside Apiome — as an SDK regen subscription is.
Turning one off, or removing it, is ``projects:edit``; reading is ``projects:view``; releasing a halted run is
``versions:publish``. Changes are audited as ``export.auto_export.subscription.*``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .export_auto import AutoExportSubscriptionCreate, AutoExportSubscriptionUpdate
from .export_auto_worker import release_halted_run
from .export_git_delivery_routes import _check_tenant
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit

router = APIRouter(prefix="/v1/export", tags=["export-auto"])

AUDIT_SUBSCRIBED = "export.auto_export.subscription.created"
AUDIT_SUBSCRIPTION_UPDATED = "export.auto_export.subscription.updated"
AUDIT_UNSUBSCRIBED = "export.auto_export.subscription.deleted"

_NOT_FOUND = "Auto-export subscription not found"


class AutoExportSubscriptionModel(BaseModel):
    """An export preset subscribed to a project's publishes."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    project_id: str = Field(serialization_alias="projectId")
    project_name: Optional[str] = Field(default=None, serialization_alias="projectName")
    preset_id: str = Field(serialization_alias="presetId")
    preset_name: Optional[str] = Field(default=None, serialization_alias="presetName")
    halt_at: str = Field(serialization_alias="haltAt", description="`warn` or `critical`.")
    approve_loss: bool = Field(serialization_alias="approveLoss")
    active: bool
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")


class AutoExportSubscriptionListResponse(BaseModel):
    """Auto-export subscriptions."""

    model_config = ConfigDict(extra="forbid")

    subscriptions: List[AutoExportSubscriptionModel] = Field(default_factory=list)


class AutoExportRunModel(BaseModel):
    """One auto-export: a publish × a subscription.

    Attributes:
        status: ``pending``, ``running``, ``delivered``, ``exported`` (no delivery profile), ``halted`` (the
            loss reached ``haltAt``: nothing delivered, people notified), ``delivery_failed`` or ``failed``.
        loss_severity: The loss the export measured: ``info``, ``warn`` or ``critical``.
        loss_reasons: Why, one line per target.
        deliveries: Each delivery's outcome.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    project_id: str = Field(serialization_alias="projectId")
    project_name: Optional[str] = Field(default=None, serialization_alias="projectName")
    version_record_id: str = Field(serialization_alias="versionRecordId")
    subscription_id: Optional[str] = Field(default=None, serialization_alias="subscriptionId")
    preset_id: Optional[str] = Field(default=None, serialization_alias="presetId")
    preset_name: str = Field(serialization_alias="presetName")
    halt_at: str = Field(serialization_alias="haltAt")
    approve_loss: bool = Field(serialization_alias="approveLoss")
    status: str
    job_id: Optional[str] = Field(default=None, serialization_alias="jobId")
    loss_severity: Optional[str] = Field(default=None, serialization_alias="lossSeverity")
    loss_reasons: List[str] = Field(default_factory=list, serialization_alias="lossReasons")
    deliveries: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    published_by: Optional[str] = Field(default=None, serialization_alias="publishedBy")
    released_by: Optional[str] = Field(default=None, serialization_alias="releasedBy")
    released_at: Optional[datetime] = Field(default=None, serialization_alias="releasedAt")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    finished_at: Optional[datetime] = Field(default=None, serialization_alias="finishedAt")


class AutoExportRunListResponse(BaseModel):
    """Auto-export runs, newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: List[AutoExportRunModel] = Field(default_factory=list)


def subscription_model(row: Dict[str, Any]) -> AutoExportSubscriptionModel:
    """Project a stored subscription onto the wire model."""
    return AutoExportSubscriptionModel(
        id=str(row["id"]), project_id=str(row["project_id"]), project_name=row.get("project_name"),
        preset_id=str(row["preset_id"]), preset_name=row.get("preset_name"), halt_at=str(row["halt_at"]),
        approve_loss=bool(row.get("approve_loss")), active=bool(row.get("active")), created_at=row.get("created_at"),
        updated_at=row.get("updated_at"), created_by=row.get("created_by"),
    )


def run_model(row: Dict[str, Any]) -> AutoExportRunModel:
    """Project a stored run onto the wire model."""
    return AutoExportRunModel(
        id=str(row["id"]), project_id=str(row["project_id"]), project_name=row.get("project_name"),
        version_record_id=str(row["version_record_id"]), subscription_id=row.get("subscription_id"),
        preset_id=row.get("preset_id"), preset_name=str(row.get("preset_name") or ""),
        halt_at=str(row.get("halt_at") or "critical"), approve_loss=bool(row.get("approve_loss")),
        status=str(row["status"]), job_id=row.get("job_id"), loss_severity=row.get("loss_severity"),
        loss_reasons=[str(r) for r in row.get("loss_reasons") or []], deliveries=list(row.get("deliveries") or []),
        error_code=row.get("error_code"), error_message=row.get("error_message"),
        published_by=row.get("published_by"), released_by=row.get("released_by"), released_at=row.get("released_at"),
        created_at=row.get("created_at"), finished_at=row.get("finished_at"),
    )


def _audit_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"projectId": row.get("project_id"), "preset": row.get("preset_name"), "haltAt": row.get("halt_at"),
            "approveLoss": bool(row.get("approve_loss")), "active": bool(row.get("active"))}


async def _subscription_or_404(tenant_id: str, subscription_id: str) -> Dict[str, Any]:
    row = await asyncio.to_thread(db.get_export_auto_subscription, tenant_id, subscription_id)
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


@router.post(
    "/{tenant_slug}/auto-exports",
    response_model=AutoExportSubscriptionModel,
    response_model_by_alias=True,
    status_code=201,
    summary="Run an export preset on every publish of a project",
    description=(
        "Subscribes an export preset (by id or name) to a project: every later publish runs the preset's "
        "export on the published version and delivers it through the preset's delivery profile — unless the "
        "export's loss reaches `haltAt` (`critical`, the default: a severe or near-empty conversion, a "
        "types-only result or any critical construct; `warn`: any loss). A halted export is not delivered; "
        "the publisher and the subscriber are notified, and a person can release it. `approveLoss` "
        "pre-approves the loss: the export is delivered anyway. Requires `projects:edit` and "
        "`versions:publish`; audited as `export.auto_export.subscription.created`. `400` for an unknown "
        "project or preset; `409` when the project already runs that preset."
    ),
    responses={400: {"description": "Unknown project or preset."},
               409: {"description": "The project already runs that preset on publish."}},
)
async def create_auto_export(
    tenant_slug: str,
    body: AutoExportSubscriptionCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AutoExportSubscriptionModel:
    """Subscribe an export preset to a project's publishes.

    Args:
        tenant_slug: The tenant.
        body: The subscription.
        auth_data: Authenticated principal.

    Returns:
        The stored subscription.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    preset = await asyncio.to_thread(db.get_export_preset, tenant_id, body.preset)
    project = None
    try:
        project = await asyncio.to_thread(db.get_project_by_id, body.project_id, tenant_id)
    except Exception:  # noqa: BLE001 - an unreadable or malformed id is an unknown project
        project = None
    errors = []
    if not project:
        errors.append(f"projectId: no project {body.project_id!r} exists in this workspace")
    if not preset:
        errors.append(f"preset: no export preset {body.preset!r} exists in this workspace")
    if errors:
        raise HTTPException(status_code=400, detail={"code": "export-auto-invalid", "errors": errors})
    try:
        row = await asyncio.to_thread(
            db.insert_export_auto_subscription, tenant_id=tenant_id, project_id=str(project["id"]),
            preset_id=str(preset["id"]), halt_at=body.halt_at, approve_loss=body.approve_loss, active=body.active,
            actor_id=get_authenticated_user_id(auth_data),
        )
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail={
            "code": "export-auto-exists",
            "message": f"The project already runs export preset {preset['name']!r} on publish.",
        }) from exc
    if not row:
        raise HTTPException(status_code=500, detail="The subscription could not be stored.")
    write_audit(tenant_id=tenant_id, action=AUDIT_SUBSCRIBED, auth_data=auth_data, target=row["id"],
                detail=_audit_detail(row))
    return subscription_model(row)


@router.get(
    "/{tenant_slug}/auto-exports",
    response_model=AutoExportSubscriptionListResponse,
    response_model_by_alias=True,
    summary="List auto-export subscriptions",
    description="Every export preset run on publish, by project. `projectId` or `preset` (id or name) narrow. "
    "Requires `projects:view`.",
)
async def list_auto_exports(
    tenant_slug: str,
    project_id: Optional[str] = Query(default=None, alias="projectId"),
    preset: Optional[str] = Query(default=None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AutoExportSubscriptionListResponse:
    """List auto-export subscriptions."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    preset_id = None
    if preset:
        found = await asyncio.to_thread(db.get_export_preset, tenant_id, preset)
        if not found:
            return AutoExportSubscriptionListResponse()
        preset_id = str(found["id"])
    rows = await asyncio.to_thread(db.list_export_auto_subscriptions, tenant_id, project_id=project_id,
                                   preset_id=preset_id)
    return AutoExportSubscriptionListResponse(subscriptions=[subscription_model(row) for row in rows])


@router.patch(
    "/{tenant_slug}/auto-exports/{subscription_id}",
    response_model=AutoExportSubscriptionModel,
    response_model_by_alias=True,
    summary="Change an auto-export subscription",
    description="Changes `haltAt`, `approveLoss` or `active`. Turning a subscription on or pre-approving loss "
    "requires `versions:publish` as well as `projects:edit`. Audited as "
    "`export.auto_export.subscription.updated`.",
    responses={404: {"description": "Unknown subscription for this tenant."}},
)
async def update_auto_export(
    tenant_slug: str,
    subscription_id: str,
    body: AutoExportSubscriptionUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AutoExportSubscriptionModel:
    """Change one auto-export subscription."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _subscription_or_404(tenant_id, subscription_id)
    halt_at = body.halt_at or existing["halt_at"]
    approve_loss = existing["approve_loss"] if body.approve_loss is None else body.approve_loss
    active = existing["active"] if body.active is None else body.active
    if (active and not existing["active"]) or (approve_loss and not existing["approve_loss"]):
        enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    row = await asyncio.to_thread(db.update_export_auto_subscription, tenant_id, subscription_id, halt_at=halt_at,
                                  approve_loss=approve_loss, active=active,
                                  actor_id=get_authenticated_user_id(auth_data))
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    write_audit(tenant_id=tenant_id, action=AUDIT_SUBSCRIPTION_UPDATED, auth_data=auth_data, target=subscription_id,
                detail=_audit_detail(row))
    return subscription_model(row)


@router.delete(
    "/{tenant_slug}/auto-exports/{subscription_id}",
    status_code=204,
    summary="Remove an auto-export subscription",
    description="Stops running the preset on publish. Its past runs keep their record. Requires `projects:edit`; "
    "audited as `export.auto_export.subscription.deleted`.",
    responses={404: {"description": "Unknown subscription for this tenant."}},
)
async def delete_auto_export(
    tenant_slug: str,
    subscription_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Remove one auto-export subscription."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _subscription_or_404(tenant_id, subscription_id)
    if not await asyncio.to_thread(db.delete_export_auto_subscription, tenant_id, subscription_id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    write_audit(tenant_id=tenant_id, action=AUDIT_UNSUBSCRIBED, auth_data=auth_data, target=subscription_id,
                detail=_audit_detail(existing))
    return Response(status_code=204)


@router.get(
    "/{tenant_slug}/auto-export-runs",
    response_model=AutoExportRunListResponse,
    response_model_by_alias=True,
    summary="List auto-export runs",
    description="What each publish's auto-exports did, newest first: the export job, the loss it measured, "
    "whether delivery was halted, and every delivery's outcome. `projectId` or `subscriptionId` narrow. "
    "Requires `projects:view`.",
)
async def list_auto_export_runs(
    tenant_slug: str,
    project_id: Optional[str] = Query(default=None, alias="projectId"),
    subscription_id: Optional[str] = Query(default=None, alias="subscriptionId"),
    limit: int = Query(default=50, ge=1, le=200),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AutoExportRunListResponse:
    """List auto-export runs."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_auto_runs, tenant_id, project_id=project_id,
                                   subscription_id=subscription_id, limit=limit)
    return AutoExportRunListResponse(runs=[run_model(row) for row in rows])


@router.post(
    "/{tenant_slug}/auto-export-runs/{run_id}/release",
    response_model=AutoExportRunModel,
    response_model_by_alias=True,
    summary="Deliver a halted auto-export anyway",
    description=(
        "Delivers a **halted** auto-export through its preset's delivery profile, as the caller, while the "
        "export's artifact is retained. Requires `versions:publish`; audited as "
        "`export.auto_export.released`. `409` when the run is not halted or the preset names no delivery "
        "profile; `410` when the artifact has expired."
    ),
    responses={404: {"description": "Unknown run for this tenant."},
               409: {"description": "Not halted, or nothing to deliver with."},
               410: {"description": "The export's artifact has expired."}},
)
async def release_auto_export_run(
    tenant_slug: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AutoExportRunModel:
    """Deliver one halted auto-export anyway."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    run = await asyncio.to_thread(db.get_export_auto_run, tenant_id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Auto-export run not found")
    return run_model(await release_halted_run(db, run, auth_data))
