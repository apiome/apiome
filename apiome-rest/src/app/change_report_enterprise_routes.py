"""
Enterprise change reports: approvals, PDF export and the audit trail (#2705, CR-V2-01).

Routes, all behind the ``change-report-enterprise`` entitlement (``feature_gating.py``; a
pass-through unless the operator switch is on):

* ``POST /v1/versions/{tenant}/{project}/{version}/change-report/submit``
* ``POST /v1/versions/{tenant}/{project}/{version}/change-report/approve``
* ``POST /v1/versions/{tenant}/{project}/{version}/change-report/reject``
* ``GET  /v1/versions/{tenant}/{project}/{version}/change-report/pdf``
* ``GET  /v1/tenants/{tenant}/change-report-audit``

The approval rules are in ``change_report_approval.py`` and the PDF pipeline in
``change_report_pdf.py``; this module loads the report, asks the rules, writes, and audits.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from .auth import get_authenticated_user_id
from .change_report_approval import (
    TRANSITION_APPROVE,
    TRANSITION_REJECT,
    TRANSITION_SUBMIT,
    check_transition,
    normalize_review_note,
    normalize_state,
    pdf_export_refusal,
    target_state,
)
from .change_report_audit import (
    ACTION_REPORT_APPROVE,
    ACTION_REPORT_EXPORT_PDF,
    ACTION_REPORT_REJECT,
    ACTION_REPORT_SUBMIT,
    CHANGE_REPORT_AUDIT_ACTIONS,
    record_change_report_audit,
)
from .change_report_pdf import pdf_sha256, render_change_report_pdf
from .database import db
from .feature_gating import require_change_report_enterprise
from .models import (
    ChangeReportAuditEntryOut,
    ChangeReportAuditPageOut,
    ChangeReportReviewRequest,
    VersionChangeReportOut,
)
from .permissions import Action, Resource, enforce_permission
from .registry_audit_routes import (
    _decode_cursor,
    _encode_cursor,
    _optional_uuid_param,
    _parse_iso_datetime,
)
from .version_change_report_routes import _effective, _row_to_out

router = APIRouter(prefix="/v1/versions", tags=["version-change-report"])
audit_router = APIRouter(prefix="/v1/tenants", tags=["change-report-audit"])

_AUDIT_VERB = {
    TRANSITION_SUBMIT: ACTION_REPORT_SUBMIT,
    TRANSITION_APPROVE: ACTION_REPORT_APPROVE,
    TRANSITION_REJECT: ACTION_REPORT_REJECT,
}

_AUDIT_DEFAULT_LIMIT = 50
_AUDIT_MAX_LIMIT = 200


def _load_report(
    tenant_id: str, project_id: str, version_record_id: str
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Load a published version and its stored change report.

    Args:
        tenant_id: The caller's tenant id.
        project_id: The project id from the path.
        version_record_id: The version id from the path.

    Returns:
        ``(version, report)`` rows.

    Raises:
        HTTPException: 404 when the version or its report is missing or belongs to another
            project; 400 when the version is not published.
    """
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Version not found in project: {project_id}"
        )
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Change reports are only defined for published revisions",
        )
    report = db.get_change_report_by_published_revision(version_record_id, tenant_id, project_id)
    if not report:
        raise HTTPException(status_code=404, detail="No change report stored for this revision")
    return version, report


def _transition(
    transition: str,
    *,
    project_id: str,
    version_record_id: str,
    note: Optional[str],
    auth_data: Dict[str, Any],
) -> VersionChangeReportOut:
    """Make one approval transition on a report: check, write, audit.

    Args:
        transition: ``submit``, ``approve`` or ``reject``.
        project_id: The project id from the path.
        version_record_id: The version id from the path.
        note: The reviewer's note (approve / reject only).
        auth_data: The request's auth context.

    Returns:
        The report after the transition.

    Raises:
        HTTPException: 403 without a user, or for the wrong person; 409 for the wrong state or
            when another reviewer got there first; 404 / 400 as :func:`_load_report`.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Reviewing change reports requires user authentication (JWT)",
        )
    tenant_id = auth_data["tenant_id"]
    version, report = _load_report(tenant_id, project_id, version_record_id)

    current = normalize_state(report.get("approval_state"))
    submitted_by = report.get("submitted_by")
    is_admin = bool(db.is_user_tenant_admin(tenant_id, user_id))
    refusal = check_transition(
        transition,
        current_state=current,
        actor_id=user_id,
        actor_is_tenant_admin=is_admin,
        # The report's edit rule (PATCH): the version's creator, or a tenant administrator.
        actor_can_edit_report=is_admin or str(version.get("creator_id") or "") == user_id,
        submitted_by=str(submitted_by) if submitted_by is not None else None,
    )
    if refusal:
        raise HTTPException(status_code=refusal.status_code, detail=refusal.detail)

    review_note = None if transition == TRANSITION_SUBMIT else normalize_review_note(note)
    new_state = target_state(transition)
    row = db.transition_change_report_approval(
        version_record_id,
        tenant_id,
        project_id,
        from_state=current,
        to_state=new_state,
        actor_id=user_id,
        review_note=review_note,
    )
    if not row:
        # The conditional UPDATE matched nothing: the state moved between the read and the write.
        raise HTTPException(
            status_code=409,
            detail="The change report's review state changed; reload it and try again",
        )

    record_change_report_audit(
        db,
        auth_data,
        _AUDIT_VERB[transition],
        project_id=project_id,
        change_report_id=str(row["id"]),
        published_revision_id=version_record_id,
        detail={"from": current, "to": new_state, "note": review_note},
    )
    return _row_to_out(row)


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/submit",
    response_model=VersionChangeReportOut,
)
async def submit_change_report_for_review(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(require_change_report_enterprise),
) -> VersionChangeReportOut:
    """
    Submit a **draft** change report for review (``draft`` → ``pending_review``).

    **Authorization:** JWT required. The revision **creator** or a **tenant administrator** —
    the same people who may edit the report.

    Returns **409** when the report is not a draft.
    """
    _ = tenant_slug
    return _transition(
        TRANSITION_SUBMIT,
        project_id=project_id,
        version_record_id=version_record_id,
        note=None,
        auth_data=auth_data,
    )


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/approve",
    response_model=VersionChangeReportOut,
)
async def approve_change_report(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: ChangeReportReviewRequest = Body(default_factory=ChangeReportReviewRequest),
    auth_data: Dict[str, Any] = Depends(require_change_report_enterprise),
) -> VersionChangeReportOut:
    """
    Approve a change report that is pending review (``pending_review`` → ``approved``).

    An approved report can be exported as PDF. Editing or regenerating it afterwards returns
    it to ``draft``.

    **Authorization:** JWT required. A **tenant administrator** who did **not** submit the
    report.

    Returns **409** when the report is not pending review, **403** for the submitter.
    """
    _ = tenant_slug
    return _transition(
        TRANSITION_APPROVE,
        project_id=project_id,
        version_record_id=version_record_id,
        note=body.note,
        auth_data=auth_data,
    )


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/reject",
    response_model=VersionChangeReportOut,
)
async def reject_change_report(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: ChangeReportReviewRequest = Body(default_factory=ChangeReportReviewRequest),
    auth_data: Dict[str, Any] = Depends(require_change_report_enterprise),
) -> VersionChangeReportOut:
    """
    Send a change report that is pending review back to ``draft``, with an optional note.

    **Authorization:** JWT required. A **tenant administrator**.

    Returns **409** when the report is not pending review.
    """
    _ = tenant_slug
    return _transition(
        TRANSITION_REJECT,
        project_id=project_id,
        version_record_id=version_record_id,
        note=body.note,
        auth_data=auth_data,
    )


def _pdf_filename(project: Optional[Dict[str, Any]], version: Dict[str, Any]) -> str:
    """Build the download name of a report's PDF from its project and version.

    Args:
        project: The project row, when found.
        version: The published version row.

    Returns:
        ``<project>-<version>-change-report.pdf`` with only filename-safe characters.
    """
    parts = [
        str((project or {}).get("slug") or (project or {}).get("name") or "project"),
        str(version.get("version_id") or version.get("version") or version.get("id") or ""),
    ]
    stem = "-".join(re.sub(r"[^A-Za-z0-9._-]+", "-", p).strip("-") for p in parts if p)
    return f"{stem or 'report'}-change-report.pdf"


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/change-report/pdf",
    response_class=Response,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "The approved change report as a PDF. `X-Content-SHA256` carries "
                           "the file's SHA-256, which is also stored as `lastPdfSha256`.",
        },
        409: {"description": "The report is not approved."},
    },
)
async def export_change_report_pdf(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(require_change_report_enterprise),
) -> Response:
    """
    Download an **approved** change report as a PDF.

    The PDF is rendered from the report's effective header, body and footnote (your edits
    where you made any). Exporting the same report twice gives the same bytes, so the
    ``X-Content-SHA256`` header — also stored on the report as ``lastPdfSha256`` — identifies
    the file that was handed out. Each export is written to the audit trail.

    **Authorization:** JWT or API key; read access to versions.

    Returns **409** unless the report is ``approved``.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    version, report = _load_report(tenant_id, project_id, version_record_id)

    refusal = pdf_export_refusal(report.get("approval_state"))
    if refusal:
        raise HTTPException(status_code=refusal.status_code, detail=refusal.detail)

    project = db.get_project_by_id(project_id, tenant_id)
    filename = _pdf_filename(project, version)
    pinned_at = report.get("updated_at")
    try:
        pdf = render_change_report_pdf(
            _effective(report.get("header_snapshot"), report.get("edited_header_snapshot")),
            _effective(report.get("rendered_body"), report.get("edited_rendered_body")),
            _effective(report.get("footnote_snapshot"), report.get("edited_footnote_snapshot")),
            title=filename.removesuffix(".pdf"),
            pinned_at=pinned_at if isinstance(pinned_at, datetime) else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    digest = pdf_sha256(pdf)
    db.record_change_report_pdf_export(version_record_id, tenant_id, project_id, digest)
    record_change_report_audit(
        db,
        auth_data,
        ACTION_REPORT_EXPORT_PDF,
        project_id=project_id,
        change_report_id=str(report["id"]),
        published_revision_id=version_record_id,
        detail={"sha256": digest, "bytes": len(pdf), "filename": filename},
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": digest,
        },
    )


def _audit_entry(row: Dict[str, Any]) -> ChangeReportAuditEntryOut:
    """Map a ``change_report_audit`` row to its API model.

    Args:
        row: The audit row.

    Returns:
        The entry, ids as text and the timestamp as ISO 8601.
    """

    def text(key: str) -> Optional[str]:
        value = row.get(key)
        return str(value) if value is not None else None

    created = row.get("created_at")
    detail = row.get("detail")
    return ChangeReportAuditEntryOut(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        project_id=text("project_id"),
        change_report_id=text("change_report_id"),
        published_revision_id=text("published_revision_id"),
        template_version_id=text("template_version_id"),
        action=str(row["action"]),
        actor_id=text("actor_id"),
        detail=detail if isinstance(detail, dict) else None,
        created_at=created.isoformat() if hasattr(created, "isoformat") else str(created or ""),
    )


@audit_router.get(
    "/{tenant_slug}/change-report-audit",
    response_model=ChangeReportAuditPageOut,
    response_model_by_alias=True,
)
async def list_change_report_audit(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(require_change_report_enterprise),
    action: Optional[List[str]] = Query(
        None,
        description="Only these audit verbs (repeat for several, e.g. report.approve).",
    ),
    actor_id: Optional[str] = Query(
        None, alias="actorId", description="Only events by this user (UUID)."
    ),
    project_id: Optional[str] = Query(
        None, alias="projectId", description="Only events of this project (UUID)."
    ),
    version_id: Optional[str] = Query(
        None,
        alias="versionId",
        description="Only events of this published version's report (UUID).",
    ),
    since: Optional[str] = Query(
        None, description="Inclusive lower bound on createdAt (ISO 8601)."
    ),
    until: Optional[str] = Query(
        None, description="Inclusive upper bound on createdAt (ISO 8601)."
    ),
    limit: int = Query(_AUDIT_DEFAULT_LIMIT, ge=1, le=_AUDIT_MAX_LIMIT),
    cursor: Optional[str] = Query(
        None, description="The `nextCursor` of the previous page, for the next (older) one."
    ),
) -> ChangeReportAuditPageOut:
    """
    List the tenant's change-report audit trail, newest first.

    One entry per report edit, regeneration, submission, approval, rejection and PDF export,
    and per template creation or default change.

    **Authorization:** JWT required; **tenant administrators only**.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)
    if not user_id or not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(
            status_code=403,
            detail="Only a tenant administrator can read the change-report audit trail",
        )

    actions = [a.strip() for a in (action or []) if a and a.strip()] or None
    unknown = sorted(set(actions or []) - set(CHANGE_REPORT_AUDIT_ACTIONS))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action(s): {', '.join(unknown)}. "
                   f"Known: {', '.join(CHANGE_REPORT_AUDIT_ACTIONS)}",
        )

    before = None
    if cursor:
        try:
            before = _decode_cursor(cursor)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {e}") from e

    # One row beyond the page tells whether an older page exists without a COUNT.
    rows = db.list_change_report_audit(
        tenant_id,
        actions=actions,
        actor_id=_optional_uuid_param("actorId", actor_id),
        project_id=_optional_uuid_param("projectId", project_id),
        published_revision_id=_optional_uuid_param("versionId", version_id),
        since=_parse_iso_datetime("since", since),
        until=_parse_iso_datetime("until", until),
        before=before,
        limit=limit + 1,
    )
    page = rows[:limit]
    next_cursor = (
        _encode_cursor(page[-1]["created_at"], str(page[-1]["id"]))
        if len(rows) > limit and page
        else None
    )
    return ChangeReportAuditPageOut(
        items=[_audit_entry(r) for r in page], limit=limit, next_cursor=next_cursor
    )
