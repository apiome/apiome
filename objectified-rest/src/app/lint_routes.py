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


def build_lint_report(
    version: Dict[str, Any],
    project_id: str,
    tenant_slug: str,
    tenant_id: str,
    base_version: Optional[Dict[str, Any]] = None,
    resolved_base_id: Optional[str] = None,
) -> LintReportResponse:
    """
    Compute the deterministic lint report for an already-resolved revision.

    This is the post-validation core shared by the per-version lint route and the catalog
    lint-report analog (MFI-23.10): callers resolve and authorize ``version`` (and, optionally,
    ``base_version``) first, then delegate the OpenAPI reconstruction, scoring and captured-score
    surfacing here so both surfaces produce an identical :class:`LintReportResponse`.

    Args:
        version: The resolved ``versions`` row (must carry ``id``/``project_id``/``version_id``).
        project_id: The owning project id (a catalog item's id is a project id).
        tenant_slug: The tenant slug, used to reconstruct the OpenAPI document.
        tenant_id: The authenticated tenant id.
        base_version: An optional resolved base revision row; when given, breaking/unknown
            compatibility findings relative to it are folded into the report.
        resolved_base_id: The base revision's ``versions.id`` echoed back on the response (and used
            to suppress staleness, since a base comparison legitimately changes the fingerprint).

    Returns:
        The server-computed quality score, grade and itemized findings for ``version``.
    """
    head_spec = openapi_for_revision(version, tenant_slug, tenant_id)

    extra_findings = []
    compatibility_overall: Optional[str] = None
    if base_version is not None:
        base_spec = openapi_for_revision(base_version, tenant_slug, tenant_id)
        compat = CompatibilityCheckEngine.run(base_spec, head_spec)
        compatibility_overall = compat.overall
        extra_findings = merge_compatibility_findings(compat.findings)

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

    # MFI-4.4: surface the score persisted on the version at import time (#3609 / MFI-4.2)
    # alongside the live recompute, so REST/ADE/CLI all show the authoritative captured score.
    # When the captured fingerprint differs from this live report's, the stored score is stale.
    # A base-revision comparison folds in extra findings, so its fingerprint legitimately differs
    # from the (base-less) captured one — never flag staleness in that case. Best-effort: a read
    # failure must never break the authoritative live lint, so fall back to "no captured score".
    try:
        captured = db.get_version_quality_score(version["id"], tenant_id) or {}
    except Exception:  # pragma: no cover - defensive; surfacing must not break the live report
        captured = {}
    captured_fingerprint = captured.get("quality_report_fingerprint")
    score_is_stale = (
        resolved_base_id is None
        and captured_fingerprint is not None
        and captured_fingerprint != result.report_fingerprint
    )

    return LintReportResponse(
        project_id=project_id,
        version_record_id=version["id"],
        version_id=version["version_id"],
        score=result.score,
        grade=result.grade,
        findings=findings_out,
        rule_hits=dict(result.rule_hits),
        severity_counts=dict(result.severity_counts),
        report_fingerprint=result.report_fingerprint,
        base_revision_id=resolved_base_id,
        compatibility_overall=compatibility_overall,
        captured_score=captured.get("quality_score"),
        captured_grade=captured.get("quality_grade"),
        captured_report_fingerprint=captured_fingerprint,
        score_is_stale=score_is_stale,
    )


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

    base_version: Optional[Dict[str, Any]] = None
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
        resolved_base_id = base_id

    return build_lint_report(
        version,
        project_id,
        tenant_slug,
        tenant_id,
        base_version=base_version,
        resolved_base_id=resolved_base_id,
    )
