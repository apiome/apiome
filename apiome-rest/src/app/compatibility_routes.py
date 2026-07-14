"""
Backward compatibility API: compare two schema revisions (versions.id) using generated OpenAPI.

Also exposes independent oasdiff compatibility evidence (CLX-2.3 / #4853) with
normalized JSON / SARIF / JUnit gate outputs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from .auth import validate_authentication
from .compatibility_engine import CompatibilityCheckEngine, compat_report_fingerprint, openapi_for_revision
from .database import db
from .gate_report_emit import (
    GATE_FORMAT_JSON,
    normalize_gate_format,
    serialize_gate,
    to_normalized_json,
)
from .openapi_compatibility_adapters import OASDIFF_ADAPTER_ID, OASDIFF_ADAPTER_VERSION
from .openapi_compatibility_evidence import (
    capture_oasdiff_compatibility_evidence,
    run_oasdiff_compatibility,
)
from .permissions import enforce_permission, Resource, Action
from .models import (
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    CompatibilityEvidenceFindingOut,
    CompatibilityEvidenceRequest,
    CompatibilityEvidenceResponse,
    CompatibilityFindingOut,
    LintEvidenceResponse,
    RevisionDeprecationWarningOut,
    lint_evidence_response_from_rows,
)
from .revision_deprecation import warnings_for_revision
from .schema_compatibility import BREAKING_DOC_ISSUE_URL, CompatibilityRules


router = APIRouter(prefix="/v1/versions", tags=["compatibility"])


def _parse_project_metadata(metadata: Any) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _tenant_compat_gate(project: Dict[str, Any]) -> bool:
    return bool(_parse_project_metadata(project.get("metadata")).get("compatGateOnMerge"))


def _tenant_fail_ci_on_deprecated(project: Dict[str, Any]) -> bool:
    """When true, consumers should treat deprecated revisions as merge/CI blockers (see ``deprecatedRevisionBlocked``)."""
    return bool(_parse_project_metadata(project.get("metadata")).get("failCiOnDeprecatedRevision"))


def _rules_from_payload(req: CompatibilityCheckRequest) -> CompatibilityRules:
    p = req.rules
    if not p:
        return CompatibilityRules()
    return CompatibilityRules(
        check_paths=p.check_paths,
        check_schemas=p.check_schemas,
        treat_removed_schema_as_breaking=p.treat_removed_schema_as_breaking,
        treat_removed_property_as_breaking=p.treat_removed_property_as_breaking,
        treat_removed_path_as_breaking=p.treat_removed_path_as_breaking,
        treat_removed_operation_as_breaking=p.treat_removed_operation_as_breaking,
        detect_possible_renames=p.detect_possible_renames,
    )


@router.post("/{tenant_slug}/{project_id}/compatibility", response_model=CompatibilityCheckResponse)
async def check_revision_compatibility(
    tenant_slug: str,
    project_id: str,
    body: CompatibilityCheckRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CompatibilityCheckResponse:
    """
    Compare **baseRevisionId** (older / consumer expectation) to **headRevisionId** (newer).
    Returns structured safe / breaking / unknown findings for CI-style merge gates.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    base_id = (body.base_revision_id or "").strip()
    head_id = (body.head_revision_id or "").strip()
    if not base_id or not head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId are required",
        )
    if base_id == head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId must differ",
        )

    base_ver = db.get_version_by_id(base_id, tenant_id)
    head_ver = db.get_version_by_id(head_id, tenant_id)
    if not base_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {base_id}")
    if not head_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {head_id}")

    if base_ver["project_id"] != project_id or head_ver["project_id"] != project_id:
        raise HTTPException(
            status_code=400,
            detail="Both revisions must belong to the specified project",
        )

    rules = _rules_from_payload(body)
    base_spec = openapi_for_revision(base_ver, tenant_slug, tenant_id)
    head_spec = openapi_for_revision(head_ver, tenant_slug, tenant_id)

    result = CompatibilityCheckEngine.run(base_spec, head_spec, rules)
    overall = result.overall
    finding_out = [
        CompatibilityFindingOut(
            id=f.id,
            path=f.path,
            category=f.category,
            rule=f.rule,
            message=f.message,
        )
        for f in result.findings
    ]
    finding_dicts = [f.model_dump(by_alias=True) for f in finding_out]
    rule_hits_sorted = dict(sorted(result.rule_hits.items()))

    dep_out: List[RevisionDeprecationWarningOut] = []
    dep_out.extend(
        warnings_for_revision(
            revision_id=base_ver["id"],
            version_label=base_ver["version_id"],
            role="base",
            metadata=base_ver.get("metadata"),
        )
    )
    dep_out.extend(
        warnings_for_revision(
            revision_id=head_ver["id"],
            version_label=head_ver["version_id"],
            role="head",
            metadata=head_ver.get("metadata"),
        )
    )

    dep_dicts = [w.model_dump(by_alias=True) for w in dep_out]
    fp = compat_report_fingerprint(overall, finding_dicts, dep_dicts or None)

    tenant_gate = _tenant_compat_gate(project)
    merge_blocked = bool(tenant_gate and overall != "safe")
    fail_dep = _tenant_fail_ci_on_deprecated(project)
    deprecated_revision_blocked = bool(fail_dep and dep_out)

    doc_url = BREAKING_DOC_ISSUE_URL if overall == "breaking" else None

    response = CompatibilityCheckResponse(
        overall=overall,
        base_revision_id=base_id,
        head_revision_id=head_id,
        findings=finding_out,
        rule_hits=rule_hits_sorted,
        breaking_change_documentation_issue_url=doc_url,
        report_fingerprint=fp,
        tenant_compat_gate_active=tenant_gate,
        merge_blocked_by_compat_gate=merge_blocked,
        deprecation_warnings=dep_out,
        deprecated_revision_blocked=deprecated_revision_blocked,
    )

    policy = body.policy
    if policy and policy.http409_when_breaking and overall == "breaking":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPATIBILITY_BREAKING",
                "message": "Head revision introduces breaking changes relative to base",
                "report": response.model_dump(by_alias=True),
            },
        )

    if policy and policy.http409_when_deprecated_revision and dep_out:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEPRECATED_REVISION",
                "message": "One or both revisions in this compatibility check are deprecated",
                "report": response.model_dump(by_alias=True),
            },
        )

    # CLX-2.3: best-effort independent oasdiff evidence (does not affect native gate).
    try:
        await capture_oasdiff_compatibility_evidence(
            base_document=base_spec,
            head_document=head_spec,
            version_record_id=str(head_id),
            base_revision_id=base_id,
            head_revision_id=head_id,
        )
    except Exception:  # noqa: BLE001
        pass

    return response


def _resolve_revision_pair(
    *,
    tenant_id: str,
    project_id: str,
    base_id: str,
    head_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not base_id or not head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId are required",
        )
    if base_id == head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId must differ",
        )
    base_ver = db.get_version_by_id(base_id, tenant_id)
    head_ver = db.get_version_by_id(head_id, tenant_id)
    if not base_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {base_id}")
    if not head_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {head_id}")
    if base_ver["project_id"] != project_id or head_ver["project_id"] != project_id:
        raise HTTPException(
            status_code=400,
            detail="Both revisions must belong to the specified project",
        )
    return base_ver, head_ver


def _evidence_response_from_run(
    *,
    result: Any,
    changelog_md: Optional[str],
    base_id: str,
    head_id: str,
    evidence_run_id: Optional[str],
) -> CompatibilityEvidenceResponse:
    from .external_linter_evidence import outcome_for_adapter_result

    findings = [
        CompatibilityEvidenceFindingOut(
            rule_id=f.get("rule_id"),
            message=f.get("message"),
            severity=f.get("severity"),
            change_class=f.get("change_class"),
            category=f.get("category"),
            location=f.get("location") if isinstance(f.get("location"), dict) else {},
            source_fingerprint=f.get("source_fingerprint"),
            remediation=f.get("remediation"),
        )
        for f in (result.envelope_findings or [])
    ]
    outcome = outcome_for_adapter_result(
        failure_kind=result.failure_kind,
        findings=result.envelope_findings or [],
    )
    payload = to_normalized_json(
        findings=result.envelope_findings or [],
        scanner_id=OASDIFF_ADAPTER_ID,
        base_revision_id=base_id,
        head_revision_id=head_id,
        outcome=outcome,
        changelog_markdown=changelog_md,
        coverage=(
            {
                "state": "none" if result.failure_kind else "full",
                "failureKind": result.failure_kind,
                "diagnostics": result.diagnostics,
            }
            if result.failure_kind
            else {"state": "full"}
        ),
        evidence_run_id=evidence_run_id,
    )
    return CompatibilityEvidenceResponse(
        schema_version=1,
        scanner_id=OASDIFF_ADAPTER_ID,
        base_revision_id=base_id,
        head_revision_id=head_id,
        outcome=payload.get("outcome"),
        overall=str(payload.get("overall") or "safe"),
        counts=payload.get("counts") or {},
        findings=findings,
        coverage=payload.get("coverage") or {},
        changelog_markdown=changelog_md,
        evidence_run_id=evidence_run_id,
    )


@router.post(
    "/{tenant_slug}/{project_id}/compatibility/evidence",
    response_model=None,
)
async def create_compatibility_evidence(
    tenant_slug: str,
    project_id: str,
    body: CompatibilityEvidenceRequest,
    request: Request,
    format: Optional[str] = Query(
        default=None,
        description="Gate output format: json (default), sarif, or junit.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Run oasdiff, persist evidence on the head revision, return gate output.

    Emits normalized JSON by default. Pass ``?format=sarif`` or ``?format=junit``
    (or matching ``Accept``) for CI-compatible artifacts.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    base_id = (body.base_revision_id or "").strip()
    head_id = (body.head_revision_id or "").strip()
    base_ver, head_ver = _resolve_revision_pair(
        tenant_id=tenant_id,
        project_id=project_id,
        base_id=base_id,
        head_id=head_id,
    )
    base_spec = openapi_for_revision(base_ver, tenant_slug, tenant_id)
    head_spec = openapi_for_revision(head_ver, tenant_slug, tenant_id)

    result, changelog_md, changelog_html = await run_oasdiff_compatibility(
        base_document=base_spec,
        head_document=head_spec,
    )
    evidence_run_id = await capture_oasdiff_compatibility_evidence(
        base_document=base_spec,
        head_document=head_spec,
        version_record_id=str(head_id),
        base_revision_id=base_id,
        head_revision_id=head_id,
        result=result,
        changelog_md=changelog_md,
        changelog_html=changelog_html,
    )

    accept = request.headers.get("accept")
    fmt = normalize_gate_format(format or accept)
    if fmt != GATE_FORMAT_JSON:
        body_text, media = serialize_gate(
            fmt,
            findings=result.envelope_findings or [],
            scanner_id=OASDIFF_ADAPTER_ID,
            base_revision_id=base_id,
            head_revision_id=head_id,
            outcome=_evidence_response_from_run(
                result=result,
                changelog_md=changelog_md,
                base_id=base_id,
                head_id=head_id,
                evidence_run_id=evidence_run_id,
            ).outcome,
            changelog_markdown=changelog_md,
            evidence_run_id=evidence_run_id,
            tool_version=OASDIFF_ADAPTER_VERSION,
        )
        return Response(content=body_text, media_type=media)

    return _evidence_response_from_run(
        result=result,
        changelog_md=changelog_md,
        base_id=base_id,
        head_id=head_id,
        evidence_run_id=evidence_run_id,
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_id}/compatibility/evidence",
    response_model=None,
)
async def list_compatibility_evidence(
    tenant_slug: str,
    project_id: str,
    version_id: str,
    request: Request,
    format: Optional[str] = Query(
        default=None,
        description="When set to sarif/junit, emit gate output for the latest oasdiff run.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """List persisted oasdiff compatibility evidence runs for a revision."""
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    version = db.get_version_by_id(version_id, tenant_id)
    if not version or version["project_id"] != project_id:
        raise HTTPException(status_code=404, detail=f"Revision not found: {version_id}")

    rows = db.list_lint_evidence_runs_for_version(version_id, tenant_id)
    oasdiff_rows = [
        row for row in rows if str(row.get("scanner_id") or "") == OASDIFF_ADAPTER_ID
    ]
    fmt = normalize_gate_format(format or request.headers.get("accept"))
    if fmt != GATE_FORMAT_JSON and oasdiff_rows:
        latest = oasdiff_rows[0]
        findings = latest.get("findings") or []
        coverage = latest.get("coverage") if isinstance(latest.get("coverage"), dict) else {}
        body_text, media = serialize_gate(
            fmt,
            findings=findings,
            scanner_id=OASDIFF_ADAPTER_ID,
            base_revision_id=coverage.get("baseRevisionId"),
            head_revision_id=coverage.get("headRevisionId") or version_id,
            outcome=str(latest.get("outcome") or ""),
            changelog_markdown=coverage.get("changelogMarkdown"),
            coverage=coverage,
            evidence_run_id=str(latest.get("id")) if latest.get("id") else None,
            tool_version=str(latest.get("adapter_version") or OASDIFF_ADAPTER_VERSION),
        )
        return Response(content=body_text, media_type=media)

    return lint_evidence_response_from_rows(
        "catalog_revision",
        version_id,
        oasdiff_rows,
    )
