"""Export preset routes — MFX-39.3 (#4335).

* ``POST   /v1/export/{tenant_slug}/presets`` stores a preset (every target's options validated);
* ``GET    /v1/export/{tenant_slug}/presets`` lists them, by name;
* ``GET    /v1/export/{tenant_slug}/presets/{preset}`` reads one, by id or name;
* ``PATCH  /v1/export/{tenant_slug}/presets/{preset_id}`` changes one;
* ``DELETE /v1/export/{tenant_slug}/presets/{preset_id}`` removes one.

A preset is **applied** by naming it on the job submit (``POST /v1/export/{tenant_slug}/jobs`` with
``"preset"``), which :func:`expand_job_preset` turns into the request it stands for.

**Permissions.** Managing a preset is ``projects:edit`` (reading ``projects:view``), as a delivery
profile is. Changes are audited as ``export.preset.created`` / ``.updated`` / ``.deleted``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .export_git_delivery_routes import _check_tenant
from .export_job_engine import ExportJobStartRequest
from .export_presets import (
    ExportPresetCreate,
    ExportPresetRequestError,
    ExportPresetUpdate,
    NormalizedPreset,
    PresetTarget,
    apply_preset,
    normalize_create,
    normalize_update,
    preset_profile_ids,
)
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit

router = APIRouter(prefix="/v1/export", tags=["export-presets"])

AUDIT_PRESET_CREATED = "export.preset.created"
AUDIT_PRESET_UPDATED = "export.preset.updated"
AUDIT_PRESET_DELETED = "export.preset.deleted"

_NOT_FOUND = "Export preset not found"


class ExportPresetModel(BaseModel):
    """A stored export preset.

    Attributes:
        id: The preset.
        name: Its unique name in the workspace.
        description: What it is for.
        targets: The targets, in order, each with its emit options.
        delivery_profile_id: The first delivery profile the export is delivered with, or null.
        delivery_profile_name: That profile's name (null when none, or the profile was deleted).
        delivery_profile_ids: Every delivery profile, in the order the export is delivered with them (MFX-46.4).
        delivery_profile_names: Their names, in the same order.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: str
    description: Optional[str] = None
    targets: List[PresetTarget] = Field(default_factory=list)
    delivery_profile_id: Optional[str] = Field(default=None, serialization_alias="deliveryProfileId")
    delivery_profile_name: Optional[str] = Field(default=None, serialization_alias="deliveryProfileName")
    delivery_profile_ids: List[str] = Field(default_factory=list, serialization_alias="deliveryProfileIds")
    delivery_profile_names: List[str] = Field(default_factory=list, serialization_alias="deliveryProfileNames")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


class ExportPresetListResponse(BaseModel):
    """A workspace's export presets, by name."""

    model_config = ConfigDict(extra="forbid")

    presets: List[ExportPresetModel] = Field(default_factory=list)


def preset_model(row: Dict[str, Any]) -> ExportPresetModel:
    """Project a stored preset onto the wire model."""
    return ExportPresetModel(
        id=str(row["id"]), name=str(row["name"]), description=row.get("description"),
        targets=[PresetTarget(target=str(t.get("target")), options=t.get("options") or None)
                 for t in row.get("targets") or []],
        delivery_profile_id=row.get("delivery_profile_id"), delivery_profile_name=row.get("delivery_profile_name"),
        delivery_profile_ids=preset_profile_ids(row),
        delivery_profile_names=[str(name) for name in row.get("delivery_profile_names") or []],
        created_at=row.get("created_at"), updated_at=row.get("updated_at"), created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
    )


def _invalid(exc: ExportPresetRequestError) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "export-preset-invalid", "errors": exc.errors})


def _name_taken(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "export-preset-name-taken",
                                                  "message": f"An export preset named {name!r} already exists."})


async def _check_profile(tenant_id: str, preset: NormalizedPreset) -> None:
    """Refuse (400) any delivery profile the workspace does not have."""
    errors: List[str] = []
    for index, profile_id in enumerate(preset.delivery_profile_ids):
        if not await asyncio.to_thread(db.get_export_delivery_profile, tenant_id, profile_id):
            errors.append(f"deliveryProfileIds[{index}]: no delivery profile {profile_id!r} exists in this workspace")
    if errors:
        raise HTTPException(status_code=400, detail={"code": "export-preset-invalid", "errors": errors})


def _audit_detail(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": row.get("name"), "targets": [t.get("target") for t in row.get("targets") or []],
            "deliveryProfileId": row.get("delivery_profile_id"), "deliveryProfileIds": preset_profile_ids(row)}


async def _preset_or_404(tenant_id: str, ref: str) -> Dict[str, Any]:
    row = await asyncio.to_thread(db.get_export_preset, tenant_id, ref)
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return row


def expand_job_preset(request: ExportJobStartRequest, tenant_id: str) -> ExportJobStartRequest:
    """The job request a submit naming ``preset`` stands for (no-op without one).

    Args:
        request: The submitted job request.
        tenant_id: The submitter's tenant (scopes the preset lookup).

    Returns:
        The expanded request (see :func:`app.export_presets.apply_preset`).

    Raises:
        HTTPException: 400 for an unknown preset (``export-preset-unknown``) or one whose targets no
            longer validate (``export-preset-invalid``); 422 when the expanded request is not a valid job
            (e.g. ``acknowledged_snapshot`` with a multi-target preset).
    """
    if request.preset is None:
        return request
    preset = db.get_export_preset(tenant_id, request.preset)
    if not preset:
        raise HTTPException(status_code=400, detail={
            "code": "export-preset-unknown",
            "errors": [f"preset: no export preset {request.preset!r} exists in this workspace"],
        })
    try:
        return apply_preset(request, preset)
    except ExportPresetRequestError as exc:
        raise _invalid(exc) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail={
            "code": "export-preset-request-invalid",
            "errors": [str(error.get("msg")) for error in exc.errors()],
        }) from exc


@router.post(
    "/{tenant_slug}/presets",
    response_model=ExportPresetModel,
    response_model_by_alias=True,
    status_code=201,
    summary="Store an export preset",
    description=(
        "Saves a named export combination for the workspace: 1–16 `targets`, each with its emit `options` "
        "(validated against that emitter's options schema, MFX-1.4; no two targets may resolve to the same "
        "format), and an optional `deliveryProfileId` (MFX-38.4) the export is delivered with on completion. "
        "Apply it with `POST /v1/export/{tenant}/jobs` and `\"preset\": \"<name or id>\"`. Requires "
        "`projects:edit`; audited as `export.preset.created`. `400` for an invalid field, target, option or "
        "unknown delivery profile (every problem in `errors`); `409` for a name already in use."
    ),
    responses={400: {"description": "Invalid name, target, option or delivery profile."},
               409: {"description": "A preset of that name exists."}},
)
async def create_export_preset(
    tenant_slug: str,
    body: ExportPresetCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportPresetModel:
    """Validate and store one export preset.

    Args:
        tenant_slug: The tenant.
        body: The preset.
        auth_data: Authenticated principal.

    Returns:
        The stored preset.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    try:
        preset = await asyncio.to_thread(normalize_create, body)
    except ExportPresetRequestError as exc:
        raise _invalid(exc) from exc
    await _check_profile(tenant_id, preset)
    try:
        row = await asyncio.to_thread(
            db.insert_export_preset, tenant_id=tenant_id, name=preset.name, description=preset.description,
            targets=preset.targets, delivery_profile_id=preset.delivery_profile_id,
            actor_id=get_authenticated_user_id(auth_data), delivery_profile_ids=preset.delivery_profile_ids,
        )
    except pg_errors.UniqueViolation as exc:
        raise _name_taken(preset.name) from exc
    if not row:
        raise HTTPException(status_code=500, detail="The export preset could not be stored.")
    write_audit(tenant_id=tenant_id, action=AUDIT_PRESET_CREATED, auth_data=auth_data, target=row["id"],
                detail=_audit_detail(row))
    return preset_model(row)


@router.get(
    "/{tenant_slug}/presets",
    response_model=ExportPresetListResponse,
    response_model_by_alias=True,
    summary="List the workspace's export presets",
    description="Every export preset, by name. Requires `projects:view`.",
)
async def list_export_presets(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportPresetListResponse:
    """List the tenant's export presets."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_presets, tenant_id)
    return ExportPresetListResponse(presets=[preset_model(row) for row in rows])


@router.get(
    "/{tenant_slug}/presets/{preset}",
    response_model=ExportPresetModel,
    response_model_by_alias=True,
    summary="Read an export preset",
    description="One export preset, by id or name. Requires `projects:view`. `404` when the workspace has "
    "no such preset.",
    responses={404: {"description": "Unknown preset for this tenant."}},
)
async def get_export_preset(
    tenant_slug: str,
    preset: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportPresetModel:
    """Read one export preset."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    return preset_model(await _preset_or_404(tenant_id, preset))


@router.patch(
    "/{tenant_slug}/presets/{preset_id}",
    response_model=ExportPresetModel,
    response_model_by_alias=True,
    summary="Change an export preset",
    description=(
        "Changes a preset's `name`, `description`, `targets` (replaced whole, validated again) or "
        "`deliveryProfileId` (`null` removes delivery). Omitted fields keep their value. Requires "
        "`projects:edit`; audited as `export.preset.updated`."
    ),
    responses={400: {"description": "Invalid name, target, option or delivery profile."},
               404: {"description": "Unknown preset for this tenant."},
               409: {"description": "Another preset has that name."}},
)
async def update_export_preset(
    tenant_slug: str,
    preset_id: str,
    body: ExportPresetUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportPresetModel:
    """Change one export preset.

    Args:
        tenant_slug: The tenant.
        preset_id: The preset (id or name).
        body: What changes.
        auth_data: Authenticated principal.

    Returns:
        The updated preset.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _preset_or_404(tenant_id, preset_id)
    try:
        preset = await asyncio.to_thread(normalize_update, body, existing)
    except ExportPresetRequestError as exc:
        raise _invalid(exc) from exc
    if preset.delivery_profile_ids != preset_profile_ids(existing):
        await _check_profile(tenant_id, preset)
    try:
        row = await asyncio.to_thread(
            db.update_export_preset, tenant_id, str(existing["id"]), name=preset.name,
            description=preset.description, targets=preset.targets,
            delivery_profile_id=preset.delivery_profile_id, actor_id=get_authenticated_user_id(auth_data),
            delivery_profile_ids=preset.delivery_profile_ids,
        )
    except pg_errors.UniqueViolation as exc:
        raise _name_taken(preset.name) from exc
    if not row:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    write_audit(tenant_id=tenant_id, action=AUDIT_PRESET_UPDATED, auth_data=auth_data, target=row["id"],
                detail=_audit_detail(row))
    return preset_model(row)


@router.delete(
    "/{tenant_slug}/presets/{preset_id}",
    status_code=204,
    summary="Delete an export preset",
    description="Removes the preset (by id or name). Exports already started with it are unaffected. "
    "Requires `projects:edit`; audited as `export.preset.deleted`. `404` when the workspace has no such preset.",
    responses={404: {"description": "Unknown preset for this tenant."}},
)
async def delete_export_preset(
    tenant_slug: str,
    preset_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete one export preset."""
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    existing = await _preset_or_404(tenant_id, preset_id)
    if not await asyncio.to_thread(db.delete_export_preset, tenant_id, str(existing["id"])):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    write_audit(tenant_id=tenant_id, action=AUDIT_PRESET_DELETED, auth_data=auth_data, target=str(existing["id"]),
                detail=_audit_detail(existing))
    return Response(status_code=204)
