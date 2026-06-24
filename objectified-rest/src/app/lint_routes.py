"""
Quality-scoring / linting API: deterministic score + itemized findings for a schema revision.

Replaces the old client-side (localStorage) quality score with a real service (#3609). The
generated OpenAPI document for a version is reconstructed via the shared
``openapi_for_revision`` helper and fed to the deterministic :mod:`app.schema_lint` engine.
Breaking-change risk can optionally be folded in by comparing against a base revision using the
existing :mod:`app.compatibility_engine`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .compatibility_engine import CompatibilityCheckEngine, openapi_for_revision
from .database import db
from .models import LintFindingOut, LintReportResponse
from .schema_lint import lint_openapi_spec, merge_compatibility_findings

router = APIRouter(prefix="/v1/versions", tags=["lint"])


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/lint",
    response_model=LintReportResponse,
)
async def lint_revision(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    base_revision_id: Optional[str] = Query(
        default=None,
        alias="baseRevisionId",
        description="Optional base revision (versions.id) to flag breaking changes against.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> LintReportResponse:
    """
    Score the quality of a schema revision and return itemized, deterministic lint findings.

    The score (0-100) and A-F grade are computed by the server from the reconstructed
    OpenAPI/JSON-Schema — no client-side scoring. When ``baseRevisionId`` is supplied, breaking
    and unknown compatibility findings relative to that revision are folded into the report.
    """
    tenant_id = auth_data["tenant_id"]

    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Revision not found: {version_record_id}")
    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=400,
            detail="Revision does not belong to the specified project",
        )

    head_spec = openapi_for_revision(version, tenant_slug, tenant_id)

    extra_findings = []
    compatibility_overall: Optional[str] = None
    resolved_base_id: Optional[str] = None
    base_id = (base_revision_id or "").strip()
    if base_id:
        if base_id == version_record_id:
            raise HTTPException(
                status_code=400,
                detail="baseRevisionId must differ from the linted revision",
            )
        base_version = db.get_version_by_id(base_id, tenant_id)
        if not base_version:
            raise HTTPException(status_code=404, detail=f"Base revision not found: {base_id}")
        if base_version["project_id"] != project_id:
            raise HTTPException(
                status_code=400,
                detail="Base revision must belong to the specified project",
            )
        base_spec = openapi_for_revision(base_version, tenant_slug, tenant_id)
        compat = CompatibilityCheckEngine.run(base_spec, head_spec)
        compatibility_overall = compat.overall
        extra_findings = merge_compatibility_findings(compat.findings)
        resolved_base_id = base_id

    result = lint_openapi_spec(head_spec, extra_findings=extra_findings)

    findings_out = [
        LintFindingOut(
            id=f.id,
            path=f.path,
            category=f.category,
            rule=f.rule,
            severity=f.severity,
            message=f.message,
        )
        for f in result.findings
    ]

    return LintReportResponse(
        project_id=project_id,
        version_record_id=version_record_id,
        version_id=version["version_id"],
        score=result.score,
        grade=result.grade,
        findings=findings_out,
        rule_hits=dict(result.rule_hits),
        severity_counts=dict(result.severity_counts),
        report_fingerprint=result.report_fingerprint,
        base_revision_id=resolved_base_id,
        compatibility_overall=compatibility_overall,
    )
