"""Catalog upload reconciliation API — RAR-6.2 (#3539).

An item imported from an uploaded file has no live source to refresh, so the catalog flags it
when its newest version is older than the tenant's threshold and offers a re-upload that replays
the import spec the upload recorded (:mod:`app.catalog_upload_reconcile`).

* ``GET  /v1/catalog/{tenant}/upload-policy`` — the tenant's staleness threshold in days.
* ``PUT  /v1/catalog/{tenant}/upload-policy`` — change it (``imports:edit``).
* ``GET  /v1/catalog/{tenant}/{item_id}/upload`` — whether the item is an upload, its age, whether
  it may be stale, and the stored import spec a re-upload replays.
* ``POST /v1/catalog/{tenant}/{item_id}/reupload`` — re-import a new copy of the file with that
  spec: ``unchanged`` when it matches the current version, else ``changed`` with the new version.

Item routes look the item up first, so an id from another tenant (or a Project's id) is a 404.
Reading needs ``projects:view``; a re-upload needs ``imports:create`` (it is an import) and
``projects:edit`` (it adds a version to the item), and passes the tenant's import quality gate
like any upload.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from typing import Any, Dict, Literal, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import catalog_upload_reconcile as reconcile
from .auth import validate_authentication
from .catalog_refresh import RefreshSettingsError
from .database import db
from .permissions import Action, Resource, enforce_permission

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(prefix="/v1/catalog", tags=["catalog-upload"])

#: HTTP status per re-upload refusal code; anything else is a 422.
_STATUS_BY_CODE = {
    reconcile.CODE_NOT_AN_UPLOAD: 409,
}


# ---------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------


class CatalogUploadPolicy(BaseModel):
    """The tenant's staleness threshold for uploaded catalog items."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    stale_after_days: int = Field(
        alias="staleAfterDays",
        ge=reconcile.MIN_STALE_AFTER_DAYS,
        le=reconcile.MAX_STALE_AFTER_DAYS,
        description="An uploaded item's newest version this many days old or older may be stale (default 90).",
    )


class CatalogUploadSpec(BaseModel):
    """The import spec an upload recorded, replayed by a re-upload."""

    model_config = ConfigDict(populate_by_name=True)

    spec_schema_version: int = Field(alias="specSchemaVersion")
    source_kind: str = Field(alias="sourceKind", description="The importer the upload ran (for example `asyncapi-2`).")
    options: Dict[str, Any] = Field(default_factory=dict, description="The import options the user chose.")


class CatalogUploadOut(BaseModel):
    """Whether an item's current version came from an upload and whether it may be stale."""

    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(alias="itemId")
    eligible: bool = Field(
        description="True when the item's newest version came from a file upload, so it can be re-uploaded."
    )
    stale: bool = Field(description="True when it is eligible and at least `staleAfterDays` old.")
    stale_after_days: int = Field(alias="staleAfterDays")
    uploaded_at: Optional[str] = Field(default=None, alias="uploadedAt")
    age_days: Optional[int] = Field(default=None, alias="ageDays")
    version_id: Optional[str] = Field(default=None, alias="versionId")
    version_label: Optional[str] = Field(default=None, alias="versionLabel")
    source_label: Optional[str] = Field(default=None, alias="sourceLabel", description="The uploaded file's name.")
    spec: Optional[CatalogUploadSpec] = Field(
        default=None,
        description="The stored import spec; null for an upload from before spec capture, whose re-upload "
        "runs with default options.",
    )


class CatalogReuploadRequest(BaseModel):
    """``POST …/{item_id}/reupload``: the new copy of the file."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    filename: str = Field(min_length=1, max_length=512, description="The file's name.")
    document_base64: str = Field(
        alias="documentBase64", description="Standard base64 (RFC 4648) of the file bytes; no data: URL prefix."
    )
    content_type: Optional[str] = Field(default=None, alias="contentType", description="Optional MIME type hint.")


class CatalogReuploadOut(BaseModel):
    """What a re-upload did, and the item's upload state afterwards."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["changed", "unchanged"] = Field(
        description="changed: the file differed, so a version was added; unchanged: it matches the current "
        "version and nothing was written."
    )
    spec_replayed: bool = Field(
        alias="specReplayed",
        description="True when the stored import spec was replayed; false for an upload from before spec "
        "capture, which ran with default options.",
    )
    version_id: Optional[str] = Field(default=None, alias="versionId")
    version_label: Optional[str] = Field(default=None, alias="versionLabel")
    upload: CatalogUploadOut


# ---------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this catalog item.")
    return str(tenant_id)


def _require_item(tenant_id: str, item_id: str) -> None:
    """404 unless ``item_id`` is a live catalog item in the tenant."""
    if not db.get_catalog_item_by_id(item_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Catalog item not found: {item_id}")


def _audit(tenant_id: str, action: str, actor_id: Optional[str], detail: Dict[str, Any]) -> None:
    """Write one metadata-only workflow-audit row (best-effort)."""
    try:
        db.insert_workflow_audit(tenant_id, None, None, action, "success", actor_id, detail)
    except Exception:  # noqa: BLE001 — an audit failure never fails the request.
        logger.exception("catalog upload audit write failed action=%s", action)


def _upload_out(item_id: str, tenant_id: str) -> CatalogUploadOut:
    """The item's upload state, read fresh."""
    staleness = reconcile.upload_staleness(
        reconcile.newest_revision(db, item_id, tenant_id),
        stale_after_days=reconcile.get_tenant_stale_after_days(db, tenant_id),
    )
    return CatalogUploadOut(
        item_id=item_id,
        eligible=staleness.eligible,
        stale=staleness.stale,
        stale_after_days=staleness.stale_after_days,
        uploaded_at=staleness.uploaded_at,
        age_days=staleness.age_days,
        version_id=staleness.version_id,
        version_label=staleness.version_label,
        source_label=staleness.source_label,
        spec=CatalogUploadSpec.model_validate(staleness.spec) if staleness.spec else None,
    )


async def _enforce_quality_gate(
    *,
    tenant_id: str,
    tenant_slug: str,
    user_id: str,
    item_id: str,
    raw: bytes,
    body: CatalogReuploadRequest,
) -> None:
    """Run the tenant's import quality gate over the re-uploaded file, as an upload would (IXH-2.3).

    Raises:
        HTTPException: 409 ``not-an-upload`` / 422 when the item cannot be re-uploaded; 409
            ``QUALITY_POLICY_BLOCKED`` when the policy refuses the file.
    """
    from .models import SpecImportOptions, SpecImportProjectTarget, SpecImportStartMetadata, SpecImportVersionTarget
    from .spec_import_routes import _enforce_quality_gate as enforce

    revision = reconcile.newest_revision(db, item_id, tenant_id)
    if revision is None or not reconcile.is_upload_revision(revision.get("format_metadata")):
        raise _refusal(
            reconcile.ReuploadError(
                reconcile.CODE_NOT_AN_UPLOAD, "Only an item imported from an uploaded file can be re-uploaded."
            )
        )
    try:
        source_kind, options, _ = reconcile.replay_spec(revision, raw)
        input_kind = (revision.get("format_metadata") or {}).get("inputKind") or "file"
        metadata = SpecImportStartMetadata(
            source_kind=source_kind,
            project=SpecImportProjectTarget(project_id=item_id),
            version=SpecImportVersionTarget(version_id="reupload"),
            options=SpecImportOptions.model_validate({**options, "input_kind": input_kind}),
        )
    except reconcile.ReuploadError as exc:
        raise _refusal(exc) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"The stored import spec is no longer valid: {exc}") from exc
    await enforce(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=user_id,
        raw=raw,
        metadata=metadata,
        filename=body.filename,
        content_type=body.content_type,
    )


def _refusal(exc: reconcile.ReuploadError) -> HTTPException:
    """The HTTP error for a re-upload refusal."""
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 422), detail={"code": exc.code, "message": exc.message}
    )


# ---------------------------------------------------------------------------------------
# Tenant setting
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/upload-policy", response_model=CatalogUploadPolicy, response_model_by_alias=True)
async def get_catalog_upload_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogUploadPolicy:
    """Read the tenant's staleness threshold for uploaded catalog items (``projects:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="catalog:upload-policy")
    return CatalogUploadPolicy(stale_after_days=reconcile.get_tenant_stale_after_days(db, tenant_id))


@router.put("/{tenant_slug}/upload-policy", response_model=CatalogUploadPolicy, response_model_by_alias=True)
async def set_catalog_upload_policy(
    tenant_slug: str,
    body: CatalogUploadPolicy,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogUploadPolicy:
    """Change how many days old an uploaded item's newest version is before it may be stale (``imports:edit``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target="catalog:upload-policy")
    days = reconcile.set_tenant_stale_after_days(db, tenant_id, body.stale_after_days)
    _audit(tenant_id, reconcile.AUDIT_POLICY, actor_id, {"staleAfterDays": days})
    return CatalogUploadPolicy(stale_after_days=days)


# ---------------------------------------------------------------------------------------
# Per item
# ---------------------------------------------------------------------------------------


@router.get("/{tenant_slug}/{item_id}/upload", response_model=CatalogUploadOut, response_model_by_alias=True)
async def get_catalog_item_upload(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogUploadOut:
    """Whether the item came from an upload, how old it is and whether it may be stale (``projects:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target=f"catalog:{item_id}:upload")
    return _upload_out(item_id, tenant_id)


@router.post("/{tenant_slug}/{item_id}/reupload", response_model=CatalogReuploadOut, response_model_by_alias=True)
async def reupload_catalog_item(
    tenant_slug: str,
    item_id: str,
    body: CatalogReuploadRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogReuploadOut:
    """Re-import a new copy of the item's uploaded file with the import spec it recorded.

    The file goes through the import pipeline with the importer and options of the original upload,
    and the tenant's import quality gate, exactly as an upload would. A file identical to the
    current version writes nothing (``unchanged``); a changed one adds a date/time-labelled version
    with a change report against the version it supersedes (``changed``).

    Raises:
        HTTPException: 404 when the item is not a catalog item in the tenant; 409 ``not-an-upload``
            when its newest version did not come from an upload; 409 ``QUALITY_POLICY_BLOCKED``;
            413 when the file is over the intake limit; 422 when the file is not valid base64 or
            cannot be imported.
    """
    from .intake_resource_guard import resolve_guard_profile

    tenant_id = _tenant_id(auth_data)
    _require_item(tenant_id, item_id)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target=f"catalog:{item_id}:reupload")
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=f"catalog:{item_id}:reupload")
    try:
        raw = base64.standard_b64decode(body.document_base64)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"documentBase64 is not valid base64: {exc}") from exc
    if not raw:
        raise HTTPException(status_code=422, detail="The file is empty.")
    limits = resolve_guard_profile(tenant_id=tenant_id).limits
    if len(raw) > limits.max_bytes:
        raise HTTPException(status_code=413, detail=f"The file is over the {limits.max_bytes}-byte intake limit.")

    await _enforce_quality_gate(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=str(actor_id or ""),
        item_id=item_id,
        raw=raw,
        body=body,
    )
    try:
        outcome = await asyncio.to_thread(
            reconcile.reupload_catalog_item,
            db,
            tenant_id=tenant_id,
            project_id=item_id,
            raw=raw,
            filename=body.filename,
            actor_id=str(actor_id) if actor_id else None,
        )
    except reconcile.ReuploadError as exc:
        raise _refusal(exc) from exc
    except RefreshSettingsError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": str(exc)}) from exc

    detail: Dict[str, Any] = {
        "itemId": item_id,
        "status": "changed" if outcome.changed else "unchanged",
        "specReplayed": outcome.spec_replayed,
        "filename": body.filename,
    }
    if outcome.version_id:
        detail.update(versionId=outcome.version_id, versionLabel=outcome.version_label)
    _audit(tenant_id, reconcile.AUDIT_REUPLOADED, actor_id, detail)
    return CatalogReuploadOut(
        status="changed" if outcome.changed else "unchanged",
        spec_replayed=outcome.spec_replayed,
        version_id=outcome.version_id,
        version_label=outcome.version_label,
        upload=_upload_out(item_id, tenant_id),
    )
