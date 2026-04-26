"""
Version lint API — schema-lint runs against a single version.

`POST :run` loads the version's classes and properties, applies every enabled
rule registered against `lint_engine.registry`, and persists one
`version_lint_results` row plus all `version_lint_findings` in a single
transaction. Reads return either the latest result (for the scorecard) or a
specific historical result + its findings.

The runner is synchronous for v1. If a tenant accumulates a schema large enough
that a `:run` blocks the request thread, v2 turns this into a job-queue
endpoint without touching the persistence layer or rule contract — that's why
the v1 response shape already includes the persisted result-id.
"""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication, get_authenticated_user_id
from .database import db
from .lint_engine import LintFinding, derive_grade, registry, run_lint
from .models import (
    LintRuleSchema,
    VersionLintFindingSchema,
    VersionLintResultSchema,
    VersionLintRunResponse,
)

router = APIRouter(prefix="/v1/version-lint", tags=["version-lint"])


# ---------- Internal helpers ----------


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _resolve_version(
    tenant_id: str,
    project_id: str,
    version_record_id: str,
) -> Dict[str, Any]:
    """Tenant-scoped version lookup with the project-membership check the rest
    of the API enforces. Raises 404 on either project or version miss."""
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _load_classes_and_properties(
    version_id: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Same bulk-load pattern as version_quality_routes — kept duplicated rather
    than abstracted because (a) the two callers are intentionally independent
    and (b) the property select-list will diverge once lint rules need fields
    quality scoring doesn't (e.g. `required`, `type`)."""
    classes: List[Dict[str, Any]] = db.get_classes_for_version(version_id) or []
    if not classes:
        return [], []
    class_ids = [str(c["id"]) for c in classes]
    placeholders = ",".join(["%s"] * len(class_ids))
    rows = db.execute_query(
        f"""
        SELECT cp.id, cp.class_id, cp.name, cp.description, cp.data
        FROM odb.class_properties cp
        WHERE cp.class_id IN ({placeholders})
        """,
        tuple(class_ids),
    )
    return classes, rows or []


def _finding_to_dict(f: LintFinding) -> Dict[str, Any]:
    """Engine LintFinding -> dict shape consumed by the DB helper. Centralised
    so route handlers don't repeat the field mapping."""
    return {
        "rule_id": f.rule_id,
        "severity": f.severity,
        "target_kind": f.target_kind,
        "target_id": f.target_id,
        "target_path": f.target_path,
        "message": f.message,
        "suggestion": f.suggestion,
        "detail": f.detail,
    }


# ---------- Routes ----------
#
# Route registration order matters: FastAPI matches in declaration order, so
# every literal-segment route (`/rules`, `.../history`) MUST be declared before
# the parameterized catch-alls below — otherwise the literal gets bound as a
# path parameter and the lookup throws 404.


@router.get("/rules", response_model=List[LintRuleSchema])
async def list_lint_rules(
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[LintRuleSchema]:
    """Static metadata for every rule the engine knows about. Tenant-agnostic:
    rules live in the binary, not in a per-tenant config (yet)."""
    _ = _tenant_id(auth_data)  # auth-only; result is intentionally unused
    return [
        LintRuleSchema(
            id=r.id,
            severity=r.severity,
            title=r.title,
            description=r.description,
            target_kind=r.target_kind,
        )
        for r in registry.all()
    ]


@router.get(
    "/{tenant_slug}/{project_id}/history",
    response_model=List[VersionLintResultSchema],
)
async def list_project_lint_history(
    tenant_slug: str,
    project_id: str,
    limit: int = Query(200, ge=1, le=1000),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionLintResultSchema]:
    """Cross-version result history for a project. Used by the Versions tab to
    badge each version with its latest grade in one round-trip."""
    tenant_id = _tenant_id(auth_data)
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = db.list_project_lint_history(project_id, tenant_id, limit=limit)
    return [VersionLintResultSchema(**dict(r)) for r in rows]


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/history",
    response_model=List[VersionLintResultSchema],
)
async def list_version_lint_history(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    limit: int = Query(50, ge=1, le=500),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionLintResultSchema]:
    """Result-row history for a single version, newest first. Findings omitted
    — callers fetch them per-result via `/results/{resultId}`."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    rows = db.list_version_lint_history(version_record_id, tenant_id, limit=limit)
    return [VersionLintResultSchema(**dict(r)) for r in rows]


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/results/{result_id}",
    response_model=VersionLintRunResponse,
)
async def get_version_lint_result(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    result_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionLintRunResponse:
    """One historical result + its findings. The `previous` field is left
    null on this endpoint — it's only meaningful in the run response."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    result = db.get_version_lint_result(result_id, tenant_id)
    if not result or str(result.get("version_id")) != str(version_record_id):
        raise HTTPException(status_code=404, detail="Lint result not found")
    findings = db.list_version_lint_findings(result_id, tenant_id)
    return VersionLintRunResponse(
        result=VersionLintResultSchema(**dict(result)),
        findings=[VersionLintFindingSchema(**dict(f)) for f in findings],
        previous=None,
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}",
    response_model=Optional[VersionLintRunResponse],
)
async def get_latest_version_lint(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Optional[VersionLintRunResponse]:
    """Latest result + its findings, or `null` when the version has never been
    linted. The UI uses null to render the `Run lint` CTA."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    result = db.get_latest_version_lint_result(version_record_id, tenant_id)
    if not result:
        return None
    findings = db.list_version_lint_findings(str(result["id"]), tenant_id)
    return VersionLintRunResponse(
        result=VersionLintResultSchema(**dict(result)),
        findings=[VersionLintFindingSchema(**dict(f)) for f in findings],
        previous=None,
    )


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/run",
    response_model=VersionLintRunResponse,
)
async def run_version_lint(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionLintRunResponse:
    """Compute and persist a fresh lint result. Synchronous for v1.

    The response includes the freshly persisted findings plus the prior
    result row (when present) so the UI can render a delta without a
    follow-up GET."""
    tenant_id = _tenant_id(auth_data)
    _resolve_version(tenant_id, project_id, version_record_id)
    actor_id = get_authenticated_user_id(auth_data)
    previous_row = db.get_latest_version_lint_result(version_record_id, tenant_id)

    classes, properties = _load_classes_and_properties(version_record_id)
    report = run_lint(classes, properties)
    grade = derive_grade(report.error_count, report.warning_count)

    inserted = db.insert_version_lint_run(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_record_id,
        grade=grade,
        error_count=report.error_count,
        warning_count=report.warning_count,
        info_count=report.info_count,
        rules_applied=report.rules_applied,
        duration_ms=report.duration_ms,
        computed_by=actor_id,
        findings=[_finding_to_dict(f) for f in report.findings],
        detail={"engine_version": "v1"},
    )
    if not inserted:
        raise HTTPException(status_code=500, detail="Failed to persist lint result")

    findings = inserted.pop("findings", [])
    return VersionLintRunResponse(
        result=VersionLintResultSchema(**inserted),
        findings=[VersionLintFindingSchema(**dict(f)) for f in findings],
        previous=VersionLintResultSchema(**dict(previous_row)) if previous_row else None,
    )
