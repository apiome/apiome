"""
Change report Mustache templates: list, create, assign defaults (CR-03, #2701).

See ``objectified-rest/docs/CHANGE_REPORT_TEMPLATES_API.md``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import get_authenticated_user_id, validate_authentication
from .change_report_render import validate_change_report_templates, validate_template_semver
from .change_report_template_resolve import template_accessible_to_tenant
from .database import db
from .permissions import enforce_permission, Resource, Action
from .models import (
    ChangeReportTemplateDefaultPut,
    ChangeReportTemplateVersionCreate,
    ChangeReportTemplateVersionOut,
    ChangeReportTemplateVersionSummary,
)

router = APIRouter(prefix="/v1/tenants", tags=["change-report-templates"])


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


def _assert_jwt_user(auth_data: Dict[str, Any]) -> str:
    uid = get_authenticated_user_id(auth_data)
    if not uid:
        raise HTTPException(status_code=403, detail="JWT authentication required for this operation")
    return uid


def _assert_tenant_admin(tenant_id: str, user_id: str) -> None:
    if not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(status_code=403, detail="Tenant administrator role required")


def _assert_template_assignable(tenant_id: str, template_version_id: Optional[str]) -> None:
    if template_version_id is None:
        return
    row = db.get_change_report_template_version_by_id(template_version_id)
    if not row:
        raise HTTPException(status_code=404, detail="template version not found")
    if not template_accessible_to_tenant(row, tenant_id):
        raise HTTPException(status_code=400, detail="template version is not available for this tenant")


@router.get("/{tenant_slug}/change-report-template-versions", response_model=list[ChangeReportTemplateVersionSummary])
async def list_change_report_template_versions(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> list[ChangeReportTemplateVersionSummary]:
    """List system templates and templates owned by this tenant (ids + semver; not full bodies)."""
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    rows = db.list_change_report_template_version_summaries(tenant_id)
    return [
        ChangeReportTemplateVersionSummary(
            id=_str_id(r["id"]) or "",
            semver=str(r.get("semver") or ""),
            owner_tenant_id=_str_id(r.get("owner_tenant_id")),
            created_at=_iso(r.get("created_at")),
        )
        for r in rows
    ]


@router.post(
    "/{tenant_slug}/change-report-template-versions",
    response_model=ChangeReportTemplateVersionOut,
)
async def create_change_report_template_version(
    tenant_slug: str,
    body: ChangeReportTemplateVersionCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ChangeReportTemplateVersionOut:
    """
    Create a tenant-scoped template triple (Mustache). **Tenant administrators only** (JWT).

    Invalid templates return **400** with a short validation message.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    user_id = _assert_jwt_user(auth_data)
    _assert_tenant_admin(tenant_id, user_id)

    try:
        validate_template_semver(body.semver.strip())
        validate_change_report_templates(
            body.header_template,
            body.body_template,
            body.footnote_template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        row = db.insert_change_report_template_version(
            tenant_id=tenant_id,
            semver=body.semver.strip(),
            header_template=body.header_template,
            body_template=body.body_template,
            footnote_template=body.footnote_template,
            created_by=user_id,
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "23505" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=f"A template with semver {body.semver.strip()!r} already exists for this tenant",
            ) from exc
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ChangeReportTemplateVersionOut(
        id=_str_id(row["id"]) or "",
        semver=str(row.get("semver") or ""),
        owner_tenant_id=_str_id(row.get("owner_tenant_id")),
        header_template=str(row.get("header_template") or ""),
        body_template=str(row.get("body_template") or ""),
        footnote_template=str(row.get("footnote_template") or ""),
        created_at=_iso(row.get("created_at")),
        created_by=_str_id(row.get("created_by")),
    )


@router.put("/{tenant_slug}/change-report-template-default")
async def put_tenant_change_report_template_default(
    tenant_slug: str,
    body: ChangeReportTemplateDefaultPut,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """
    Set the tenant default template pointer. **Tenant administrators only** (JWT).
    ``templateVersionId: null`` clears the tenant default (fall back to system default).
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    user_id = _assert_jwt_user(auth_data)
    _assert_tenant_admin(tenant_id, user_id)
    _assert_template_assignable(tenant_id, body.template_version_id)
    db.set_tenant_change_report_template_version(tenant_id, body.template_version_id)
    return {"status": "ok"}


@router.put("/{tenant_slug}/projects/{project_id}/change-report-template-default")
async def put_project_change_report_template_default(
    tenant_slug: str,
    project_id: str,
    body: ChangeReportTemplateDefaultPut,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """
    Set project-level template override. **JWT** — **project creator** or **tenant administrator**.

    ``templateVersionId: null`` clears the project override.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    user_id = _assert_jwt_user(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    if str(project.get("creator_id") or "") != user_id and not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(status_code=403, detail="Only the project creator or a tenant administrator may set this")
    _assert_template_assignable(tenant_id, body.template_version_id)
    updated = db.update_project(
        project_id,
        tenant_id,
        {"change_report_template_version_id": body.template_version_id},
    )
    if not updated:
        raise HTTPException(status_code=404, detail="project not found")
    return {"status": "ok"}
