"""
Backward compatibility API: compare two schema revisions (versions.id) using generated OpenAPI.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication
from .compatibility_engine import CompatibilityCheckEngine, compat_report_fingerprint, openapi_for_revision
from .database import db
from .permissions import enforce_permission, Resource, Action
from .models import (
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    CompatibilityFindingOut,
    RevisionDeprecationWarningOut,
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

    return response
