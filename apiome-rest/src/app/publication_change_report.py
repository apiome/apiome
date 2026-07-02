"""Generate and persist publication change reports after successful publish (CR-04, #2702)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional, Tuple

from fastapi import HTTPException

from .change_report_render import (
    build_render_metadata,
    bundled_system_template_row,
    render_from_template_row,
)
from .change_report_template_resolve import resolve_effective_change_report_template
from .compatibility_engine import openapi_for_revision
from .database import db
from .openapi_change_report import build_change_report

logger = logging.getLogger(__name__)

# Minimal OpenAPI baseline when there is no prior published revision on the lineage.
EMPTY_BASELINE_OPENAPI: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "(empty baseline)", "version": "0.0.0"},
    "paths": {},
    "components": {"schemas": {}},
}


def _iso_published_at(version_row: Dict[str, Any]) -> str:
    ts = version_row.get("published_at")
    if ts is None:
        return "—"
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


def _resolve_template_row(tenant_id: str, project_id: str) -> Dict[str, Any]:
    try:
        return resolve_effective_change_report_template(db, tenant_id, project_id, None)
    except HTTPException:
        return bundled_system_template_row()


def resolve_baseline_revision_id_for_change_report(
    *,
    project_id: str,
    tenant_id: str,
    candidate_revision_id: str,
    mode: str,
    manual_baseline_revision_id: Optional[str],
) -> Optional[str]:
    """
    Which published revision UUID to diff from (if any), before row lookup.

    * ``initial`` — force empty baseline / initial-publication report.
    * ``manual`` — caller-supplied baseline (must be validated separately).
    * ``auto`` — latest prior published ancestor (existing behavior).
    """
    if mode == "initial":
        return None
    if mode == "manual":
        bid = (manual_baseline_revision_id or "").strip()
        if not bid:
            raise ValueError(
                "changeReportBaselineRevisionId is required when changeReportBaselineMode is manual"
            )
        return bid
    if mode != "auto":
        raise ValueError(f"Invalid changeReportBaselineMode: {mode!r}")
    return db.get_prior_published_baseline_revision_id(
        project_id, tenant_id, candidate_revision_id
    )


def validate_manual_baseline_revision(
    tenant_id: str,
    project_id: str,
    candidate_revision_id: str,
    baseline_revision_id: str,
) -> None:
    """Raises HTTPException when manual baseline is not allowed."""
    if baseline_revision_id == candidate_revision_id:
        raise HTTPException(
            status_code=400,
            detail="Baseline revision must differ from the revision being published",
        )
    row = db.get_version_by_id(baseline_revision_id, tenant_id)
    if not row or str(row.get("project_id")) != str(project_id):
        raise HTTPException(
            status_code=400,
            detail="Baseline revision not found in this project",
        )
    if not row.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Compare baseline must be a published revision",
        )


def build_publication_change_report_render(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    candidate_version: Dict[str, Any],
    baseline_revision_id: Optional[str],
) -> Tuple[
    Dict[str, Any],
    str,
    str,
    str,
    Optional[str],
    Optional[str],
    bool,
    str,
]:
    """
    Compute Mustache render + change model for a candidate revision (published or draft).

    Returns:
        change_model, header, body, footnote, stored_baseline_id,
        requested_ghost_baseline_id (for audit if row missing), baseline_row_missing, from_label
    """
    proj = db.get_project_by_id(project_id, tenant_id)
    project_name = (proj or {}).get("name") or "API"

    candidate_openapi = openapi_for_revision(candidate_version, tenant_slug, tenant_id)

    baseline_ver: Optional[Dict[str, Any]] = None
    baseline_row_missing = False
    if baseline_revision_id:
        baseline_ver = db.get_version_by_id(baseline_revision_id, tenant_id)
        if not baseline_ver:
            baseline_row_missing = True
            logger.warning(
                "baseline revision %s not found; using empty baseline for change report",
                baseline_revision_id,
            )

    stored_baseline_id: Optional[str] = None
    requested_ghost: Optional[str] = None
    if baseline_ver:
        baseline_openapi = openapi_for_revision(baseline_ver, tenant_slug, tenant_id)
        change_model = build_change_report(baseline_openapi, candidate_openapi)
        stored_baseline_id = str(baseline_revision_id)
    else:
        change_model = build_change_report(EMPTY_BASELINE_OPENAPI, candidate_openapi)
        if not baseline_revision_id:
            change_model["initialPublication"] = True
        stored_baseline_id = None
        if baseline_row_missing:
            requested_ghost = str(baseline_revision_id)

    template_row = _resolve_template_row(tenant_id, project_id)

    if baseline_ver:
        from_label = str(baseline_ver.get("version_id") or "—")
    elif baseline_row_missing:
        from_label = f"(unknown baseline {baseline_revision_id})"
    else:
        from_label = "Initial publication"

    metadata = build_render_metadata(
        product_name=project_name,
        from_version_label=from_label,
        to_version_label=str(candidate_version.get("version_id") or "—"),
        publish_timestamp=_iso_published_at(candidate_version),
        static_footnote="",
    )

    header, body, footnote = render_from_template_row(
        change_model, template_row, metadata=metadata
    )

    return (
        change_model,
        header,
        body,
        footnote,
        stored_baseline_id,
        requested_ghost,
        baseline_row_missing,
        from_label,
    )


def preview_change_report_before_publish(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    candidate_revision_id: str,
    baseline_mode: Literal["auto", "initial", "manual"],
    baseline_revision_id: Optional[str],
) -> Dict[str, Any]:
    """
    Dry-run the same pipeline as post-publish, for an **unpublished** candidate revision.
    """
    version = db.get_version_by_id(candidate_revision_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {candidate_revision_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Preview is only available before the revision is published",
        )

    try:
        resolved = resolve_baseline_revision_id_for_change_report(
            project_id=project_id,
            tenant_id=tenant_id,
            candidate_revision_id=candidate_revision_id,
            mode=baseline_mode,
            manual_baseline_revision_id=baseline_revision_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if baseline_mode == "manual" and resolved:
        validate_manual_baseline_revision(
            tenant_id, project_id, candidate_revision_id, resolved
        )

    (
        change_model,
        header,
        body,
        footnote,
        stored_baseline_id,
        _ghost,
        _missing,
        from_label,
    ) = build_publication_change_report_render(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        candidate_version=version,
        baseline_revision_id=resolved,
    )

    tpl = _resolve_template_row(tenant_id, project_id)
    tpl_id = str(tpl["id"]) if tpl.get("id") else None

    return {
        "header_snapshot": header,
        "rendered_body": body,
        "footnote_snapshot": footnote,
        "change_model_json": change_model,
        "baseline_revision_id": stored_baseline_id,
        "template_version_id": tpl_id,
        "from_version_label": from_label,
        "to_version_label": str(version.get("version_id") or "—"),
        "initial_publication": bool(change_model.get("initialPublication")),
    }


def generate_change_report_on_publish(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    actor_id: Optional[str],
    change_report_baseline_mode: str = "auto",
    change_report_baseline_revision_id: Optional[str] = None,
) -> None:
    """
    Best-effort CR-01 → CR-03 → CR-02 after publish.

    Does not raise: failures are logged and recorded in ``workflow_audit`` with outcome ``failure``.
    """
    try:
        _generate_change_report_on_publish_impl(
            tenant_slug=tenant_slug,
            tenant_id=tenant_id,
            project_id=project_id,
            published_revision_id=published_revision_id,
            actor_id=actor_id,
            change_report_baseline_mode=change_report_baseline_mode,
            change_report_baseline_revision_id=change_report_baseline_revision_id,
        )
    except Exception as e:
        logger.warning(
            "change report generation failed after publish (revision=%s): %s",
            published_revision_id,
            e,
            exc_info=True,
        )
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            published_revision_id,
            "schema.change_report.generated",
            "failure",
            actor_id,
            {"error": str(e), "phase": "unexpected"},
        )


def _generate_change_report_on_publish_impl(
    *,
    tenant_slug: str,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    actor_id: Optional[str],
    change_report_baseline_mode: str = "auto",
    change_report_baseline_revision_id: Optional[str] = None,
) -> None:
    version = db.get_version_by_id(published_revision_id, tenant_id)
    if not version or not version.get("published"):
        return

    try:
        baseline_revision_id = resolve_baseline_revision_id_for_change_report(
            project_id=project_id,
            tenant_id=tenant_id,
            candidate_revision_id=published_revision_id,
            mode=change_report_baseline_mode,
            manual_baseline_revision_id=change_report_baseline_revision_id,
        )
    except ValueError as e:
        logger.warning(
            "change report baseline resolution failed (revision=%s): %s",
            published_revision_id,
            e,
        )
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            published_revision_id,
            "schema.change_report.generated",
            "failure",
            actor_id,
            {"error": str(e), "phase": "baseline_resolution"},
        )
        return

    (
        change_model,
        header,
        body,
        footnote,
        stored_baseline_id,
        _requested_ghost,
        baseline_row_missing,
        _from_label,
    ) = build_publication_change_report_render(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        project_id=project_id,
        candidate_version=version,
        baseline_revision_id=baseline_revision_id,
    )

    template_row = _resolve_template_row(tenant_id, project_id)
    tpl_id = str(template_row["id"]) if template_row.get("id") else None

    db.insert_change_report_if_absent(
        tenant_id,
        project_id,
        published_revision_id,
        baseline_revision_id=stored_baseline_id,
        change_model_json=change_model,
        rendered_body=body,
        header_snapshot=header,
        footnote_snapshot=footnote,
        template_version_id=tpl_id,
    )

    audit_detail: Dict[str, Any] = {
        "baselineRevisionId": stored_baseline_id,
        "publishedRevisionId": published_revision_id,
        "templateVersionId": tpl_id,
        "initialPublication": bool(change_model.get("initialPublication")),
        "changeReportBaselineMode": change_report_baseline_mode,
    }
    if baseline_row_missing and baseline_revision_id is not None:
        audit_detail["requestedBaselineRevisionId"] = baseline_revision_id
        audit_detail["baselineLookupMissing"] = True

    db.insert_workflow_audit(
        tenant_id,
        project_id,
        published_revision_id,
        "schema.change_report.generated",
        "success",
        actor_id,
        audit_detail,
    )
