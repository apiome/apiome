"""
Persisted publication change reports per schema revision (CR-02, #2700).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from .auth import get_authenticated_user_id, validate_authentication
from .change_report_render import render_from_template_row
from .change_report_template_resolve import resolve_effective_change_report_template
from .database import db
from .permissions import enforce_permission, Resource, Action
from .models import (
    VersionChangeReportOut,
    VersionChangeReportPatch,
    VersionChangeReportRegenerateRequest,
    VersionPublishChangeReportPreviewOut,
    VersionPublishChangeReportPreviewRequest,
)
from .publication_change_report import preview_change_report_before_publish

router = APIRouter(prefix="/v1/versions", tags=["version-change-report"])


def _str_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _effective(rendered: Optional[str], edited: Optional[str]) -> Optional[str]:
    """User edit is a full snapshot; any non-null edited value overrides rendered."""
    if edited is not None:
        return edited
    return rendered


def _row_to_out(row: Dict[str, Any]) -> VersionChangeReportOut:
    rb = row.get("rendered_body")
    hb = row.get("header_snapshot")
    fb = row.get("footnote_snapshot")
    er = row.get("edited_rendered_body")
    eh = row.get("edited_header_snapshot")
    ef = row.get("edited_footnote_snapshot")
    cm = row.get("change_model_json")
    if isinstance(cm, dict):
        cmj: Dict[str, Any] = cm
    else:
        cmj = {}
    return VersionChangeReportOut(
        id=_str_id(row["id"]) or "",
        tenant_id=_str_id(row["tenant_id"]) or "",
        project_id=_str_id(row["project_id"]) or "",
        published_revision_id=_str_id(row["published_revision_id"]) or "",
        baseline_revision_id=_str_id(row.get("baseline_revision_id")),
        change_model_json=cmj,
        rendered_body=rb,
        header_snapshot=hb,
        footnote_snapshot=fb,
        edited_rendered_body=er,
        edited_header_snapshot=eh,
        edited_footnote_snapshot=ef,
        effective_rendered_body=_effective(rb, er),
        effective_header_snapshot=_effective(hb, eh),
        effective_footnote_snapshot=_effective(fb, ef),
        edited_at=_iso(row.get("edited_at")),
        edited_by=_str_id(row.get("edited_by")),
        template_version_id=_str_id(row.get("template_version_id")),
        rendered_at=_iso(row.get("rendered_at")),
        regenerated_at=_iso(row.get("regenerated_at")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


def _can_edit_change_report(version: Dict[str, Any], user_id: Optional[str], tenant_id: str) -> bool:
    if not user_id:
        return False
    if str(version.get("creator_id") or "") == user_id:
        return True
    return db.is_user_tenant_admin(tenant_id, user_id)


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report",
    response_model=VersionChangeReportOut,
)
async def get_version_change_report(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionChangeReportOut:
    """
    Return the persisted change report for a **published** revision, if present.

    Authentication: JWT or API key (tenant-scoped). Read access follows the same tenant/project
    scoping as other version APIs.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Change reports are only defined for published revisions",
        )
    row = db.get_change_report_by_published_revision(version_record_id, tenant_id, project_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No change report stored for this revision",
        )
    return _row_to_out(row)


@router.patch(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report",
    response_model=VersionChangeReportOut,
)
async def patch_version_change_report(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionChangeReportPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionChangeReportOut:
    """
    Save **user edit** snapshots (full replacement per field sent).

    **Authorization:** JWT required. Only the revision **creator** or a **tenant administrator**
    may edit. API-key-only authentication cannot PATCH.

    **Semantics:** Each optional field is a full snapshot of that slice (not a diff). Sending
    ``null`` for a field clears that user override. ``clearEdits: true`` removes all overrides.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Editing change reports requires user authentication (JWT)",
        )
    tenant_id = auth_data["tenant_id"]
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Change reports are only defined for published revisions",
        )
    if not _can_edit_change_report(version, user_id, tenant_id):
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can edit this change report",
        )
    existing = db.get_change_report_by_published_revision(version_record_id, tenant_id, project_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail="No change report stored for this revision",
        )

    fs = body.model_fields_set
    clear = bool(body.clear_edits is True)
    if clear:
        row = db.patch_change_report_edits(
            version_record_id,
            tenant_id,
            project_id,
            user_id,
            clear_edits=True,
        )
    else:
        set_body = "edited_rendered_body" in fs
        set_head = "edited_header_snapshot" in fs
        set_fn = "edited_footnote_snapshot" in fs
        if not (set_body or set_head or set_fn):
            raise HTTPException(
                status_code=400,
                detail="Provide clearEdits or at least one edited* field to update",
            )
        row = db.patch_change_report_edits(
            version_record_id,
            tenant_id,
            project_id,
            user_id,
            clear_edits=False,
            set_edited_rendered_body=set_body,
            edited_rendered_body=body.edited_rendered_body,
            set_edited_header=set_head,
            edited_header_snapshot=body.edited_header_snapshot,
            set_edited_footnote=set_fn,
            edited_footnote_snapshot=body.edited_footnote_snapshot,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Change report not found")
    return _row_to_out(row)


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/regenerate",
    response_model=VersionChangeReportOut,
)
async def regenerate_version_change_report(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionChangeReportRegenerateRequest = Body(default_factory=VersionChangeReportRegenerateRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionChangeReportOut:
    """
    Re-run rendering from stored ``changeModelJson`` using the Mustache template pipeline (CR-03).

    Resolution order: optional ``templateVersionId`` in the body, then project default, tenant
    default, then the system template (**1.0.0**).

    **Authorization:** Same as PATCH (creator or tenant admin, JWT required).
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Regenerating change reports requires user authentication (JWT)",
        )
    tenant_id = auth_data["tenant_id"]
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Change reports are only defined for published revisions",
        )
    if not _can_edit_change_report(version, user_id, tenant_id):
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can regenerate this change report",
        )
    existing = db.get_change_report_by_published_revision(version_record_id, tenant_id, project_id)
    if not existing:
        raise HTTPException(
            status_code=404,
            detail="No change report stored for this revision",
        )
    cm = existing.get("change_model_json")
    if not isinstance(cm, dict):
        raise HTTPException(status_code=500, detail="Stored change model is invalid")
    tpl: Optional[str] = None
    if "template_version_id" in body.model_fields_set:
        tpl = body.template_version_id
    template_row = resolve_effective_change_report_template(
        db,
        tenant_id,
        project_id,
        tpl,
    )
    header, rendered, footnote = render_from_template_row(cm, template_row, metadata=None)
    row = db.apply_change_report_regeneration(
        version_record_id,
        tenant_id,
        project_id,
        header,
        rendered,
        footnote,
        discard_user_edits=body.discard_user_edits,
        template_version_id=_str_id(template_row.get("id")),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Change report not found")
    return _row_to_out(row)


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/publish-preview",
    response_model=VersionPublishChangeReportPreviewOut,
)
async def preview_change_report_for_publish(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionPublishChangeReportPreviewRequest = Body(
        default_factory=VersionPublishChangeReportPreviewRequest
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionPublishChangeReportPreviewOut:
    """
    Preview the publication change report that would be generated after publish, without persisting.

    Same baseline options as ``POST …/publish`` (``changeReportBaselineMode`` / ``changeReportBaselineRevisionId``).
    Requires JWT; same authorization as publishing (revision creator or tenant admin).
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Preview requires user authentication (JWT)",
        )
    tenant_id = auth_data["tenant_id"]
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if not _can_edit_change_report(version, user_id, tenant_id):
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can publish this revision",
        )

    raw = preview_change_report_before_publish(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        candidate_revision_id=version_record_id,
        baseline_mode=body.change_report_baseline_mode,
        baseline_revision_id=body.change_report_baseline_revision_id,
    )
    return VersionPublishChangeReportPreviewOut(**raw)
