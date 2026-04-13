"""
Git-like version branch merge: three-way OpenAPI schema merge + merge-base (#738).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication, get_authenticated_user_id
from .compatibility_routes import _fingerprint, _openapi_for_revision
from .database import db
from .models import (
    CompatibilityFindingOut,
    MergeSessionStatusPatchRequest,
    RevisionDeprecationWarningOut,
    VersionBranchFromRevisionRequest,
    VersionBranchFromRevisionResponse,
    VersionBranchMergePreviewRequest,
    VersionBranchMergeRequest,
    VersionBranchPolicyPatchRequest,
    VersionBranchRecordOut,
    VersionBranchRollbackPreviewRequest,
    VersionBranchRollbackRequest,
    VersionSchema,
)
from .revision_deprecation import warnings_for_revision
from .schema_compatibility import (
    BREAKING_DOC_ISSUE_URL,
    CompatibilityRules,
    analyze_schema_compatibility,
)
from .schema_merge import (
    _MISSING,
    classify_merge_diff_two_way,
    compare_schemas,
    format_diff_summary_text,
    json_equal,
    merge_components_schemas_three_way,
    schema_merge_materializable_paths,
)
from .version_notes import (
    CommitPolicyViolation,
    commit_policy_http_exception,
    effective_commit_policy,
    enforce_max_commit_payload,
    validate_version_notes,
)
from .published_immutability import IMMUTABLE_DETAIL, revision_is_published_immutable


router = APIRouter(prefix="/v1/versions", tags=["versions"])

# Max UTF-8 size of serialized merged OpenAPI in merge-preview (dry-run only; avoids huge payloads).
_MERGE_PREVIEW_MAX_JSON_BYTES = 512 * 1024

_VERSION_BRANCH_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._\-/]{0,254}$")


def _is_valid_version_branch_name(name: str) -> bool:
    """Aligned with objectified-ui/lib/version-branch-utils.ts (Git-like branch labels)."""
    s = (name or "").strip()
    return bool(_VERSION_BRANCH_NAME_RE.match(s))


def _version_branch_record_out(br: Dict[str, Any]) -> VersionBranchRecordOut:
    return VersionBranchRecordOut(
        id=str(br["id"]),
        project_id=str(br["project_id"]),
        name=str(br["name"]),
        tip_revision_id=str(br["tip_version_id"]),
        branched_from_revision_id=(
            str(br["branched_from_revision_id"]) if br.get("branched_from_revision_id") else None
        ),
        protected=bool(br.get("protected")),
        require_merge_path=bool(br.get("require_merge_path")),
        created_by=str(br["created_by"]) if br.get("created_by") else None,
        created_at=br.get("created_at"),
        updated_at=br.get("updated_at"),
    )


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


def _tenant_compat_gate_rollback(project: Dict[str, Any]) -> bool:
    return bool(_parse_project_metadata(project.get("metadata")).get("compatGateOnRollback"))


def parse_semantic_version(version: str) -> Optional[Dict[str, int]]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version)
    if match:
        return {
            "major": int(match.group(1)),
            "minor": int(match.group(2)),
            "patch": int(match.group(3)),
        }
    return None


def bump_patch_version(version: str) -> str:
    parsed = parse_semantic_version(version)
    if parsed:
        return f"{parsed['major']}.{parsed['minor']}.{parsed['patch'] + 1}"
    return "0.1.0"


def _workflow_audit_merge(
    tenant_id: str,
    project_id: str,
    version_id: Optional[str],
    outcome: str,
    actor_id: Optional[str],
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        version_id,
        "version.merge",
        outcome,
        actor_id,
        detail,
    )


def _workflow_audit_rollback(
    tenant_id: str,
    project_id: str,
    version_id: Optional[str],
    outcome: str,
    actor_id: Optional[str],
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    db.insert_workflow_audit(
        tenant_id,
        project_id,
        version_id,
        "version.rollback",
        outcome,
        actor_id,
        detail,
    )


def _merge_immutability_guard(
    *,
    tenant_id: str,
    project_id: str,
    src_ver: Dict[str, Any],
    tgt_ver: Dict[str, Any],
    actor_id: Optional[str],
    override: bool,
    override_reason: Optional[str],
    audit_operation: str,
    on_failure_audit: Optional[Callable[..., None]] = None,
) -> None:
    """Block merge on immutable published tips unless tenant admin override (#2586)."""
    src_im = revision_is_published_immutable(src_ver)
    tgt_im = revision_is_published_immutable(tgt_ver)
    if not src_im and not tgt_im:
        return
    is_admin = bool(actor_id and db.is_user_tenant_admin(tenant_id, actor_id))
    if override and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="overridePublishedImmutability requires tenant administrator",
        )
    if not (override and is_admin):
        d = {
            "message": IMMUTABLE_DETAIL["message"],
            "code": "PUBLISHED_IMMUTABLE",
        }
        if on_failure_audit is not None:
            on_failure_audit(
                tenant_id,
                project_id,
                str(tgt_ver.get("id")),
                "failure",
                actor_id,
                {"httpStatus": 409, "detail": d},
            )
        raise HTTPException(status_code=409, detail=d)
    reason = (override_reason or "").strip() or None
    # Preview endpoints are dry-runs with no DB writes; skip audit for overrides on preview.
    if not audit_operation.endswith("_preview"):
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            str(tgt_ver.get("id")),
            "version.immutability_override",
            "success",
            actor_id,
            {
                "operation": audit_operation,
                "sourceTipRevisionId": str(src_ver.get("id")),
                "targetTipRevisionId": str(tgt_ver.get("id")),
                "sourceImmutable": src_im,
                "targetImmutable": tgt_im,
                "reason": reason,
            },
        )


def _rollback_immutability_guard(
    *,
    tenant_id: str,
    project_id: str,
    head_ver: Dict[str, Any],
    head_tip: str,
    actor_id: Optional[str],
    override: bool,
    override_reason: Optional[str],
    operation: str = "rollback",
) -> None:
    """Block rollback when branch tip is immutable published unless tenant admin override (#2586)."""
    if not revision_is_published_immutable(head_ver):
        return
    is_admin = bool(actor_id and db.is_user_tenant_admin(tenant_id, actor_id))
    if override and not is_admin:
        raise HTTPException(
            status_code=403,
            detail="overridePublishedImmutability requires tenant administrator",
        )
    if not (override and is_admin):
        d = {
            "message": IMMUTABLE_DETAIL["message"],
            "code": "PUBLISHED_IMMUTABLE",
        }
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            actor_id,
            {"httpStatus": 409, "detail": d},
        )
        raise HTTPException(status_code=409, detail=d)
    reason = (override_reason or "").strip() or None
    # Preview endpoints are dry-runs; skip audit writes for override on preview.
    if not operation.endswith("_preview"):
        db.insert_workflow_audit(
            tenant_id,
            project_id,
            head_tip,
            "version.immutability_override",
            "success",
            actor_id,
            {"operation": operation, "reason": reason},
        )


def _enrich_rollback_audit_detail(
    base: Optional[Dict[str, Any]] = None,
    *,
    from_revision: Optional[str] = None,
    to_revision: Optional[str] = None,
    branch_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Normalize workflow_audit.detail for version.rollback (#2582): fromRevision, toRevision,
    optional branchName and reason. Actor and timestamp live on the workflow_audit row.
    """
    out: Dict[str, Any] = dict(base) if base else {}
    if from_revision:
        out["fromRevision"] = from_revision
    if to_revision:
        out["toRevision"] = to_revision
    if branch_name:
        out["branchName"] = branch_name
    if reason:
        out["reason"] = reason
    return out or None


def _extract_schemas(spec: Dict[str, Any]) -> Dict[str, Any]:
    return (spec.get("components") or {}).get("schemas") or {}


def _diff_summary_counts(summary: Any) -> Dict[str, int]:
    return {
        "added": len(summary.added),
        "removed": len(summary.removed),
        "modified": len(summary.modified),
        "unchanged": len(summary.unchanged),
    }


def _merge_conflict_records(
    three_way: List[str],
    blend: List[str],
    two_way: List[str],
) -> List[Dict[str, Any]]:
    """Per-path conflict metadata for conflict UI (P1-02); paths may appear in multiple kinds."""
    by_path: Dict[str, Set[str]] = {}
    for p in three_way:
        by_path.setdefault(p, set()).add("threeWay")
    for p in blend:
        by_path.setdefault(p, set()).add("blend")
    for p in two_way:
        by_path.setdefault(p, set()).add("twoWay")
    return [
        {"path": p, "kinds": sorted(kinds)}
        for p, kinds in sorted(by_path.items(), key=lambda kv: kv[0])
    ]


def _merge_openapi_components(
    base_spec: Dict[str, Any], merged_schemas: Dict[str, Any]
) -> Dict[str, Any]:
    out = copy.deepcopy(base_spec)
    out.setdefault("components", {})["schemas"] = merged_schemas
    return out


def _merge_session_json(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(row["id"]),
        "projectId": str(row["project_id"]),
        "sourceBranchId": str(row["source_branch_id"]) if row.get("source_branch_id") else None,
        "sourceBranchName": row["source_branch_name"],
        "targetBranchName": row["target_branch_name"],
        "mergeBaseVersionId": str(row["merge_base_version_id"]),
        "sourceTipVersionId": str(row["source_tip_version_id"]),
        "targetTipVersionId": str(row["target_tip_version_id"]),
        "status": row["status"],
        "createdBy": str(row["created_by"]) if row.get("created_by") else None,
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def _merge_session_status_event_json(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(r["id"]),
        "fromStatus": r.get("from_status"),
        "toStatus": r.get("to_status"),
        "changedBy": str(r["changed_by"]) if r.get("changed_by") else None,
        "changedAt": r.get("changed_at"),
    }


def _merge_session_conflict_json(r: Dict[str, Any]) -> Dict[str, Any]:
    kinds = r.get("kinds")
    if isinstance(kinds, str):
        try:
            kinds = json.loads(kinds)
        except json.JSONDecodeError:
            kinds = []
    return {
        "id": str(r["id"]),
        "path": r["path"],
        "kinds": kinds if isinstance(kinds, list) else [],
        "sortOrder": r.get("sort_order", 0),
        "createdAt": r.get("created_at"),
    }


@router.post("/{tenant_slug}/{project_id}/version-branches/from-revision")
async def version_branch_from_revision(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchFromRevisionRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionBranchFromRevisionResponse:
    """
    Create a **named branch** whose tip is an existing revision (in-project lineage; #2570).

    **Idempotency:** Repeating the same ``branchName`` + ``sourceRevisionId`` returns **200** with
    ``idempotentReplay: true`` when the branch already exists with that tip (and compatible lineage).
    Conflicting reuse of ``branchName`` returns **409** with a clear message.
    """
    tenant_id = auth_data["tenant_id"]

    if not _is_valid_version_branch_name(body.branch_name):
        raise HTTPException(
            status_code=400,
            detail=(
                "branchName must start with a letter and contain only letters, digits, "
                "._-/ (max 255 characters)"
            ),
        )

    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    creator_id = get_authenticated_user_id(auth_data)

    result = db.create_version_branch_from_revision(
        project_id=project_id,
        tenant_id=tenant_id,
        branch_name=body.branch_name,
        source_revision_id=body.source_revision_id,
        creator_id=creator_id,
    )

    if not result.get("success"):
        code = result.get("code") or "ERROR"
        err = result.get("error", "Branch creation failed")
        if code == "NOT_FOUND":
            raise HTTPException(status_code=404, detail=err)
        if code == "BRANCH_NAME_CONFLICT":
            raise HTTPException(
                status_code=409,
                detail={"message": err, "code": "BRANCH_NAME_CONFLICT"},
            )
        if code == "INVALID_INPUT":
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=500, detail=err)

    br = result["branch"]
    record = _version_branch_record_out(br)
    tip = result["tip_version"]
    return VersionBranchFromRevisionResponse(
        branch=record,
        tip_version=VersionSchema(**tip),
        idempotent_replay=bool(result.get("idempotent_replay")),
    )


@router.patch("/{tenant_slug}/{project_id}/version-branches/{branch_id}")
async def patch_version_branch_policy(
    tenant_slug: str,
    project_id: str,
    branch_id: str,
    body: VersionBranchPolicyPatchRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Tenant administrators: set ``protected`` and/or ``requireMergePath`` on a branch (#504, #2583).
    """
    tenant_id = auth_data["tenant_id"]
    uid = get_authenticated_user_id(auth_data)
    if not uid or not db.is_user_tenant_admin(tenant_id, uid):
        raise HTTPException(
            status_code=403,
            detail="Only tenant administrators may change branch protection policy",
        )
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    row = db.update_version_branch_protection_policy(
        project_id,
        tenant_id,
        branch_id,
        protected=body.protected,
        require_merge_path=body.require_merge_path,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")

    detail: Dict[str, Any] = {}
    if body.protected is not None:
        detail["protected"] = body.protected
    if body.require_merge_path is not None:
        detail["requireMergePath"] = body.require_merge_path
    db.insert_version_protection_audit(
        tenant_id,
        project_id,
        uid,
        "branch.protection_policy",
        "version_branch",
        branch_id,
        "policy_change",
        detail,
    )
    return {"branch": _version_branch_record_out(row)}


@router.post("/{tenant_slug}/{project_id}/version-branches/merge-preview")
async def version_branch_merge_preview(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchMergePreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Dry-run merge (no DB writes): merge-base id, two-way summary counts, per-kind conflict metadata,
    classification, and optional capped merged OpenAPI when auto-merge is possible (#2572).
    """
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    src = db.get_version_branch_by_name(project_id, tenant_id, body.source_branch_name)
    tgt = db.get_version_branch_by_name(project_id, tenant_id, body.target_branch_name)
    if not src or not tgt:
        raise HTTPException(status_code=404, detail="Source or target branch not found")

    source_tip = str(src["tip_version_id"])
    target_tip = str(tgt["tip_version_id"])

    for vid, label in ((source_tip, "source"), (target_tip, "target")):
        ver = db.get_version_by_id(vid, tenant_id)
        if not ver or ver["project_id"] != project_id:
            raise HTTPException(status_code=403, detail=f"{label} tip not accessible")

    merge_base_id = db.compute_merge_base_revision_id(source_tip, target_tip, tenant_id)
    if not merge_base_id:
        raise HTTPException(
            status_code=400,
            detail="No common ancestor between branch tips (unrelated histories).",
        )

    base_ver = db.get_version_by_id(merge_base_id, tenant_id)
    src_ver = db.get_version_by_id(source_tip, tenant_id)
    tgt_ver = db.get_version_by_id(target_tip, tenant_id)
    if not base_ver or not src_ver or not tgt_ver:
        raise HTTPException(status_code=404, detail="Revision not found for merge-base or tips")

    _merge_immutability_guard(
        tenant_id=tenant_id,
        project_id=project_id,
        src_ver=src_ver,
        tgt_ver=tgt_ver,
        actor_id=get_authenticated_user_id(auth_data),
        override=bool(body.override_published_immutability),
        override_reason=body.override_reason,
        audit_operation="merge_preview",
        on_failure_audit=None,
    )

    base_spec = _openapi_for_revision(base_ver, tenant_slug, tenant_id)
    source_spec = _openapi_for_revision(src_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(tgt_ver, tenant_slug, tenant_id)

    b = _extract_schemas(base_spec)
    o = _extract_schemas(target_spec)
    t = _extract_schemas(source_spec)

    merged, conflicts = merge_components_schemas_three_way(b, o, t)
    ok_mat, blend_paths = schema_merge_materializable_paths(merged or {}, o, t) if merged else (False, [])

    two_way = compare_schemas(json.dumps(target_spec), json.dumps(source_spec))
    _, conflict_paths_two, added_schema_names = classify_merge_diff_two_way(two_way)
    can_auto = bool(merged and not conflicts and ok_mat)

    three_way_paths = list(conflicts or [])
    unique_conflict_paths = list(
        dict.fromkeys(three_way_paths + blend_paths + conflict_paths_two)
    )
    conflict_records = _merge_conflict_records(three_way_paths, blend_paths, conflict_paths_two)

    merged_open_api: Optional[Dict[str, Any]] = None
    merged_open_api_omitted: Optional[str] = None
    if (
        body.include_merged_open_api
        and can_auto
        and merged
        and isinstance(merged, dict)
    ):
        candidate = _merge_openapi_components(base_spec, merged)
        raw = json.dumps(candidate, separators=(",", ":"), ensure_ascii=False)
        if len(raw.encode("utf-8")) <= _MERGE_PREVIEW_MAX_JSON_BYTES:
            merged_open_api = candidate
        else:
            merged_open_api_omitted = "payload_too_large"

    preview: Dict[str, Any] = {
        "success": True,
        "dryRun": True,
        "mergeBaseVersionId": merge_base_id,
        "sourceTipVersionId": source_tip,
        "targetTipVersionId": target_tip,
        "summary": format_diff_summary_text(two_way),
        "summaryCounts": _diff_summary_counts(two_way),
        "conflictCounts": {
            "uniquePaths": len(unique_conflict_paths),
            "threeWay": len(set(three_way_paths)),
            "blend": len(set(blend_paths)),
            "twoWay": len(set(conflict_paths_two)),
        },
        "conflicts": conflict_records,
        "classification": {
            "canAutoMerge": can_auto,
            "conflictPaths": unique_conflict_paths,
            "threeWayConflictPaths": three_way_paths,
            "blendPaths": blend_paths,
            "twoWayConflictPaths": conflict_paths_two,
            "addedSchemaNames": added_schema_names,
        },
    }
    if merged_open_api is not None:
        preview["mergedOpenApi"] = merged_open_api
    if merged_open_api_omitted:
        preview["mergedOpenApiOmitted"] = True
        preview["mergedOpenApiOmittedReason"] = merged_open_api_omitted

    if body.persist_merge_session:
        creator_id = get_authenticated_user_id(auth_data)
        ms = db.create_merge_session_for_preview(
            project_id=project_id,
            tenant_id=tenant_id,
            source_branch_name=body.source_branch_name,
            target_branch_name=body.target_branch_name,
            source_branch_id=str(src["id"]) if src.get("id") else None,
            merge_base_version_id=merge_base_id,
            source_tip_version_id=source_tip,
            target_tip_version_id=target_tip,
            conflict_records=conflict_records,
            created_by=creator_id,
        )
        if not ms:
            raise HTTPException(status_code=500, detail="Failed to persist merge session")
        preview["mergeSessionId"] = str(ms["id"])
        preview["mergeSession"] = _merge_session_json(ms)

    return preview


@router.post("/{tenant_slug}/{project_id}/version-branches/merge")
async def version_branch_merge(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchMergeRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Execute merge into target branch: new revision with two parents, three-way materialization.
    """
    tenant_id = auth_data["tenant_id"]
    creator_id = get_authenticated_user_id(auth_data)
    if not creator_id:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            None,
            "failure",
            None,
            {"httpStatus": 403, "reason": "auth_required"},
        )
        raise HTTPException(status_code=403, detail="Merge requires user authentication (JWT token)")

    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            None,
            "failure",
            creator_id,
            {"httpStatus": 404, "reason": "project_not_found"},
        )
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    src = db.get_version_branch_by_name(project_id, tenant_id, body.source_branch_name)
    tgt = db.get_version_branch_by_name(project_id, tenant_id, body.target_branch_name)
    if not src or not tgt:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            None,
            "failure",
            creator_id,
            {"httpStatus": 404, "reason": "branch_not_found"},
        )
        raise HTTPException(status_code=404, detail="Source or target branch not found")

    source_tip = str(src["tip_version_id"])
    target_tip = str(tgt["tip_version_id"])

    if target_tip != body.base_revision_id.strip():
        d = {
            "message": "Target branch tip does not match baseRevisionId (stale head or wrong base).",
            "code": "STALE_HEAD",
        }
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 409, "detail": d},
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )

    src_ver = db.get_version_by_id(source_tip, tenant_id)
    tgt_ver = db.get_version_by_id(target_tip, tenant_id)
    if not src_ver or not tgt_ver:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 403, "reason": "tip_not_accessible"},
        )
        raise HTTPException(status_code=403, detail="Version tip not accessible")
    if src_ver["project_id"] != project_id or tgt_ver["project_id"] != project_id:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 400, "reason": "branch_tip_project_mismatch"},
        )
        raise HTTPException(status_code=400, detail="Branch tips must belong to this project")
    _merge_immutability_guard(
        tenant_id=tenant_id,
        project_id=project_id,
        src_ver=src_ver,
        tgt_ver=tgt_ver,
        actor_id=creator_id,
        override=bool(body.override_published_immutability),
        override_reason=body.override_reason,
        audit_operation="merge",
        on_failure_audit=_workflow_audit_merge,
    )

    merge_base_id = db.compute_merge_base_revision_id(source_tip, target_tip, tenant_id)
    if not merge_base_id:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 400, "reason": "unrelated_histories"},
        )
        raise HTTPException(
            status_code=400,
            detail="No common ancestor between branch tips (unrelated histories).",
        )

    base_ver = db.get_version_by_id(merge_base_id, tenant_id)
    if not base_ver:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            merge_base_id,
            "failure",
            creator_id,
            {"httpStatus": 404, "reason": "merge_base_not_found"},
        )
        raise HTTPException(status_code=404, detail="Merge base revision not found")

    base_spec = _openapi_for_revision(base_ver, tenant_slug, tenant_id)
    source_spec = _openapi_for_revision(src_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(tgt_ver, tenant_slug, tenant_id)

    b = _extract_schemas(base_spec)
    o = _extract_schemas(target_spec)
    t = _extract_schemas(source_spec)

    merged, conflicts = merge_components_schemas_three_way(b, o, t)
    if merged is None or conflicts:
        uc = len(conflicts)
        d = {
            "message": f"Merge blocked: {uc} unresolved conflict(s) — overlapping schema changes",
            "code": "MERGE_UNRESOLVED_CONFLICTS",
            "reason": "MERGE_CONFLICT",
            "unresolvedCount": uc,
            "conflictPaths": conflicts,
        }
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 409, "detail": d},
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )

    ok_mat, blend_paths = schema_merge_materializable_paths(merged, o, t)
    if not ok_mat:
        uc = len(blend_paths)
        d = {
            "message": f"Merge blocked: {uc} unresolved conflict(s) — resolved schema differs from both branch tips (blend)",
            "code": "MERGE_UNRESOLVED_CONFLICTS",
            "reason": "MERGE_BLEND",
            "unresolvedCount": uc,
            "conflictPaths": blend_paths,
        }
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": 409, "detail": d},
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )

    gate = _tenant_compat_gate(project) and not body.skip_compat_gate
    if gate:
        merged_spec = _merge_openapi_components(target_spec, merged)
        overall, _ = analyze_schema_compatibility(base_spec, merged_spec, CompatibilityRules())
        if overall != "safe":
            d = {
                "message": "Merge blocked by compatibility gate (compatGateOnMerge).",
                "code": "MERGE_BLOCKED_BY_COMPAT_GATE",
                "overall": overall,
            }
            _workflow_audit_merge(
                tenant_id,
                project_id,
                target_tip,
                "failure",
                creator_id,
                {"httpStatus": 409, "detail": d},
            )
            raise HTTPException(
                status_code=409,
                detail=d,
            )

    limits = effective_commit_policy(tenant_id, project.get("metadata"))
    try:
        enforce_max_commit_payload(body, limits)
    except CommitPolicyViolation as pe:
        he = commit_policy_http_exception(pe)
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": he.status_code, "detail": he.detail},
        )
        raise he from pe

    latest = db.get_latest_version_for_project(project_id, tenant_id)
    new_version_string = bump_patch_version(latest) if latest else "0.1.0"
    raw_msg = f"Merge {body.source_branch_name} into {body.target_branch_name}"
    try:
        short_msg, _ = validate_version_notes(raw_msg, None, limits)
    except CommitPolicyViolation as e:
        he = commit_policy_http_exception(e)
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            {"httpStatus": he.status_code, "detail": he.detail},
        )
        raise he from e
    if not short_msg:
        short_msg = raw_msg

    conn = db.connect()
    prev_autocommit = conn.autocommit
    try:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO odb.versions (project_id, creator_id, version_id, description, change_log,
                    parent_version_id, merge_parent_version_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, project_id, creator_id, version_id, description, change_log,
                    visibility, published, published_at, enabled, parent_version_id, merge_parent_version_id,
                    created_at, updated_at
                """,
                (
                    project_id,
                    creator_id,
                    new_version_string,
                    short_msg,
                    None,
                    target_tip,
                    source_tip,
                ),
            )
            new_row = cursor.fetchone()
            new_id = str(new_row["id"])

            db.copy_classes_from_version_for_merge(cursor, target_tip, new_id)

            for sn in list(o.keys()):
                if sn not in merged:
                    db.delete_class_by_name_for_version(new_id, sn, tenant_id, cursor=cursor)

            for sn in merged:
                m_val = merged[sn]
                o_val = o.get(sn, _MISSING)
                t_val = t.get(sn, _MISSING)
                if json_equal(m_val, o_val):
                    continue
                if json_equal(m_val, t_val):
                    if sn in o:
                        db.delete_class_by_name_for_version(new_id, sn, tenant_id, cursor=cursor)
                    cp = db.copy_single_class_between_versions_for_merge(
                        cursor, source_tip, new_id, sn
                    )
                    if not cp.get("success"):
                        raise HTTPException(
                            status_code=500,
                            detail=cp.get("error") or f"Failed to copy class {sn}",
                        )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail="Merge materialization invariant violated",
                    )

            cursor.execute(
                """
                UPDATE odb.version_branches
                SET tip_version_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (new_id, str(tgt["id"])),
            )

        conn.commit()
    except HTTPException as he:
        conn.rollback()
        _attempted = locals().get("new_id")
        _audit_detail: Dict[str, Any] = {"httpStatus": he.status_code, "detail": he.detail}
        if _attempted:
            _audit_detail["attemptedNewRevisionId"] = _attempted
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            _audit_detail,
        )
        raise
    except Exception as ex:
        conn.rollback()
        _attempted = locals().get("new_id")
        _audit_detail = {"httpStatus": 500, "reason": "unexpected_error", "message": str(ex)}
        if _attempted:
            _audit_detail["attemptedNewRevisionId"] = _attempted
        _workflow_audit_merge(
            tenant_id,
            project_id,
            target_tip,
            "failure",
            creator_id,
            _audit_detail,
        )
        raise
    finally:
        conn.autocommit = prev_autocommit

    full = db.get_version_by_id(new_id, tenant_id)
    if not full:
        _workflow_audit_merge(
            tenant_id,
            project_id,
            new_id,
            "failure",
            creator_id,
            {"httpStatus": 500, "reason": "revision_unreadable_after_merge"},
        )
        raise HTTPException(status_code=500, detail="Merge succeeded but revision not readable")
    _workflow_audit_merge(
        tenant_id,
        project_id,
        new_id,
        "success",
        creator_id,
        {
            "sourceBranch": body.source_branch_name,
            "targetBranch": body.target_branch_name,
            "sourceTipRevisionId": source_tip,
            "targetTipRevisionId": target_tip,
            "mergeBaseRevisionId": merge_base_id,
            "versionLine": full.get("version_id"),
        },
    )
    return {
        "success": True,
        "version": VersionSchema.model_validate(full).model_dump(by_alias=True),
    }


def _rollback_analyze(
    tenant_slug: str,
    tenant_id: str,
    head_ver: Dict[str, Any],
    target_ver: Dict[str, Any],
    include_impact: bool = True,
) -> tuple[
    str,
    list[CompatibilityFindingOut],
    list[RevisionDeprecationWarningOut],
    str,
    Optional[str],
    Optional[Dict[str, Any]],
]:
    """
    Compare current branch tip (consumer expectation) to rollback snapshot (target).
    Semantics match #506: base = tip, head = restored content.

    Returns a 6-tuple:
        (overall, finding_out, dep_out, fp, doc_url, impact_summary)
    where ``impact_summary`` is ``None`` when *include_impact* is ``False``.
    """
    tip_spec = _openapi_for_revision(head_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(target_ver, tenant_slug, tenant_id)
    impact_summary: Optional[Dict[str, Any]] = None
    if include_impact:
        schema_diff = compare_schemas(tip_spec, target_spec)
        diff_counts = _diff_summary_counts(schema_diff)
        changed_entity_count = (
            diff_counts["added"] + diff_counts["removed"] + diff_counts["modified"]
        )
        impact_summary = {
            **diff_counts,
            "changedEntityCount": changed_entity_count,
        }
    overall, findings = analyze_schema_compatibility(tip_spec, target_spec, CompatibilityRules())
    finding_out = [
        CompatibilityFindingOut(
            id=f.id,
            path=f.path,
            category=f.category,
            rule=f.rule,
            message=f.message,
        )
        for f in findings
    ]
    finding_dicts = [f.model_dump(by_alias=True) for f in finding_out]
    dep_out = []
    dep_out.extend(
        warnings_for_revision(
            revision_id=head_ver["id"],
            version_label=head_ver["version_id"],
            role="head",
            metadata=head_ver.get("metadata"),
        )
    )
    dep_out.extend(
        warnings_for_revision(
            revision_id=target_ver["id"],
            version_label=target_ver["version_id"],
            role="rollbackTarget",
            metadata=target_ver.get("metadata"),
        )
    )
    dep_dicts = [w.model_dump(by_alias=True) for w in dep_out]
    fp = _fingerprint(overall, finding_dicts, dep_dicts or None)
    doc_url = BREAKING_DOC_ISSUE_URL if overall == "breaking" else None
    return overall, finding_out, dep_out, fp, doc_url, impact_summary


def _rollback_validate_branch_and_revisions(
    project_id: str,
    tenant_id: str,
    branch_name: str,
    target_revision_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], str, str]:
    """
    Returns (project, branch_row, head_ver, target_ver, head_tip, target_id).
    """
    tgt_id = (target_revision_id or "").strip()
    if not tgt_id:
        raise HTTPException(status_code=400, detail="targetRevisionId is required")

    bname = (branch_name or "").strip()
    if not bname:
        raise HTTPException(status_code=400, detail="branchName is required")

    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    branch = db.get_version_branch_by_name(project_id, tenant_id, bname)
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")

    head_tip = str(branch["tip_version_id"])
    head_ver = db.get_version_by_id(head_tip, tenant_id)
    target_ver = db.get_version_by_id(tgt_id, tenant_id)
    if not head_ver or not target_ver:
        raise HTTPException(status_code=404, detail="Revision not found")

    if head_ver["project_id"] != project_id or target_ver["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Revisions must belong to this project")

    if head_tip == tgt_id:
        raise HTTPException(
            status_code=400,
            detail="Branch tip already matches target revision; nothing to roll back.",
        )

    anc = db.collect_revision_ancestors(head_tip, tenant_id)
    if tgt_id not in anc:
        raise HTTPException(
            status_code=400,
            detail="Target revision is not an ancestor of the branch tip; only in-history rollbacks are allowed.",
        )

    return project, branch, head_ver, target_ver, head_tip, tgt_id


@router.post("/{tenant_slug}/{project_id}/version-branches/rollback-preview")
async def version_branch_rollback_preview(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchRollbackPreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Dry-run rollback: schema compatibility tip→target, deprecation warnings (#506), fingerprint.
    """
    tenant_id = auth_data["tenant_id"]
    _project, _branch, head_ver, target_ver, head_tip, tgt_id = _rollback_validate_branch_and_revisions(
        project_id, tenant_id, body.branch_name, body.target_revision_id
    )

    _rollback_immutability_guard(
        tenant_id=tenant_id,
        project_id=project_id,
        head_ver=head_ver,
        head_tip=head_tip,
        actor_id=get_authenticated_user_id(auth_data),
        override=bool(body.override_published_immutability),
        override_reason=body.override_reason,
        operation="rollback_preview",
    )

    overall, finding_out, dep_out, fp, doc_url, impact_summary = _rollback_analyze(
        tenant_slug, tenant_id, head_ver, target_ver
    )
    gate = _tenant_compat_gate_rollback(_project)
    blocked = bool(gate and overall != "safe")

    return {
        "success": True,
        "branchTipRevisionId": head_tip,
        "targetRevisionId": tgt_id,
        "compatOverall": overall,
        "findings": [f.model_dump(by_alias=True) for f in finding_out],
        "deprecationWarnings": [w.model_dump(by_alias=True) for w in dep_out],
        "reportFingerprint": fp,
        "breakingChangeDocumentationIssueUrl": doc_url,
        "tenantCompatGateRollbackActive": gate,
        "rollbackBlockedByCompatGate": blocked,
        "impactSummary": {
            "added": impact_summary["added"],
            "removed": impact_summary["removed"],
            "modified": impact_summary["modified"],
            "unchanged": impact_summary["unchanged"],
            "changedEntityCount": impact_summary["changedEntityCount"],
        },
    }


@router.post("/{tenant_slug}/{project_id}/version-branches/rollback")
async def version_branch_rollback(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchRollbackRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Apply revert-style rollback: new revision with target snapshot, parent = prior tip (#745).
    """
    tenant_id = auth_data["tenant_id"]
    audit_reason = (body.reason or "").strip() or None
    branch_label = (body.branch_name or "").strip()
    creator_id = get_authenticated_user_id(auth_data)
    if not creator_id:
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            None,
            "failure",
            None,
            _enrich_rollback_audit_detail(
                {"httpStatus": 403, "reason": "auth_required"},
                branch_name=branch_label or None,
                reason=audit_reason,
            ),
        )
        raise HTTPException(status_code=403, detail="Rollback requires user authentication (JWT token)")

    project, branch, head_ver, target_ver, head_tip, tgt_id = _rollback_validate_branch_and_revisions(
        project_id, tenant_id, body.branch_name, body.target_revision_id
    )

    _rollback_immutability_guard(
        tenant_id=tenant_id,
        project_id=project_id,
        head_ver=head_ver,
        head_tip=head_tip,
        actor_id=creator_id,
        override=bool(body.override_published_immutability),
        override_reason=body.override_reason,
    )

    base = (body.base_revision_id or "").strip()
    if base != head_tip:
        d = {
            "message": "Branch tip does not match baseRevisionId (stale head or wrong base).",
            "code": "STALE_HEAD",
        }
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": 409, "detail": d},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )

    if bool(branch.get("protected")) and not db.is_user_tenant_admin(tenant_id, creator_id):
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": 403, "reason": "branch_protected"},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise HTTPException(
            status_code=403,
            detail="This branch is protected; only tenant administrators may roll back.",
        )

    overall, _finding_out, dep_out, _fp, _doc_url, _impact_summary = _rollback_analyze(
        tenant_slug, tenant_id, head_ver, target_ver, include_impact=False
    )
    gate = _tenant_compat_gate_rollback(project)
    if gate and overall != "safe":
        d = {
            "message": "Rollback blocked by compatibility gate (compatGateOnRollback).",
            "code": "ROLLBACK_BLOCKED_BY_COMPAT_GATE",
            "overall": overall,
        }
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": 409, "detail": d},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )
    if overall != "safe" and not body.skip_compat_warning:
        d = {
            "message": "Rollback may remove or change schema surface relative to the branch tip; confirm or set skipCompatWarning.",
            "code": "ROLLBACK_NEEDS_CONFIRMATION",
            "overall": overall,
        }
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": 409, "detail": d},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise HTTPException(
            status_code=409,
            detail=d,
        )

    limits = effective_commit_policy(tenant_id, project.get("metadata"))
    try:
        enforce_max_commit_payload(body, limits)
    except CommitPolicyViolation as pe:
        he = commit_policy_http_exception(pe)
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": he.status_code, "detail": he.detail},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise he from pe

    latest = db.get_latest_version_for_project(project_id, tenant_id)
    new_version_string = bump_patch_version(latest) if latest else "0.1.0"

    default_msg = f"Rollback schema to v{target_ver['version_id']} (revert-style)"
    raw_msg = (body.short_message or "").strip() or default_msg
    raw_cl = (body.changelog or "").strip() or None
    try:
        short_msg, cl = validate_version_notes(raw_msg, raw_cl, limits, require_short_message=limits.require_short_message)
    except CommitPolicyViolation as e:
        he = commit_policy_http_exception(e)
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": he.status_code, "detail": he.detail},
                from_revision=head_tip,
                to_revision=tgt_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise he from e

    rb_rollback: Dict[str, Any] = {
        "contentRevisionId": tgt_id,
        "priorHeadRevisionId": head_tip,
        "branchName": branch_label,
    }
    if audit_reason:
        rb_rollback["reason"] = audit_reason
    rb_meta = {"rollback": rb_rollback}

    conn = db.connect()
    prev_autocommit = conn.autocommit
    try:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO odb.versions (project_id, creator_id, version_id, description, change_log,
                    parent_version_id, merge_parent_version_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, project_id, creator_id, version_id, description, change_log,
                    visibility, published, published_at, enabled, parent_version_id, merge_parent_version_id,
                    metadata, created_at, updated_at
                """,
                (
                    project_id,
                    creator_id,
                    new_version_string,
                    short_msg,
                    cl,
                    head_tip,
                    None,
                    json.dumps(rb_meta),
                ),
            )
            new_row = cursor.fetchone()
            new_id = str(new_row["id"])

            db.copy_classes_from_version_for_merge(cursor, tgt_id, new_id)

            cursor.execute(
                """
                UPDATE odb.version_branches
                SET tip_version_id = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND tip_version_id = %s
                """,
                (new_id, str(branch["id"]), head_tip),
            )
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Branch tip was modified concurrently; please retry (stale head).",
                        "code": "STALE_HEAD",
                    },
                )

        conn.commit()
    except HTTPException as he:
        conn.rollback()
        _attempted = locals().get("new_id")
        _audit_detail: Dict[str, Any] = {"httpStatus": he.status_code, "detail": he.detail}
        if _attempted:
            _audit_detail["attemptedNewRevisionId"] = _attempted
        _to_rev = str(_attempted) if _attempted else tgt_id
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                _audit_detail,
                from_revision=head_tip,
                to_revision=_to_rev,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise
    except Exception as ex:
        conn.rollback()
        _attempted = locals().get("new_id")
        _audit_detail = {"httpStatus": 500, "reason": "unexpected_error", "message": str(ex)}
        if _attempted:
            _audit_detail["attemptedNewRevisionId"] = _attempted
        _to_rev = str(_attempted) if _attempted else tgt_id
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            head_tip,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                _audit_detail,
                from_revision=head_tip,
                to_revision=_to_rev,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise
    finally:
        conn.autocommit = prev_autocommit

    db.insert_version_protection_audit(
        tenant_id,
        project_id,
        creator_id,
        "version.rollback",
        "version",
        new_id,
        "allowed",
        {
            "branchName": branch_label,
            "targetRevisionId": tgt_id,
            "priorTipRevisionId": head_tip,
            "fromRevision": head_tip,
            "toRevision": new_id,
            "compatOverall": overall,
            "deprecationWarningCount": len(dep_out),
            **({"reason": audit_reason} if audit_reason else {}),
        },
    )

    full = db.get_version_by_id(new_id, tenant_id)
    if not full:
        _workflow_audit_rollback(
            tenant_id,
            project_id,
            new_id,
            "failure",
            creator_id,
            _enrich_rollback_audit_detail(
                {"httpStatus": 500, "reason": "revision_unreadable_after_rollback"},
                from_revision=head_tip,
                to_revision=new_id,
                branch_name=branch_label,
                reason=audit_reason,
            ),
        )
        raise HTTPException(status_code=500, detail="Rollback succeeded but revision not readable")
    _workflow_audit_rollback(
        tenant_id,
        project_id,
        new_id,
        "success",
        creator_id,
        _enrich_rollback_audit_detail(
            {
                "targetRevisionId": tgt_id,
                "priorTipRevisionId": head_tip,
                "compatOverall": overall,
                "versionLine": full.get("version_id"),
            },
            from_revision=head_tip,
            to_revision=new_id,
            branch_name=branch_label,
            reason=audit_reason,
        ),
    )
    return {
        "success": True,
        "version": VersionSchema.model_validate(full).model_dump(by_alias=True),
    }


@router.get("/{tenant_slug}/{project_id}/merge-sessions/{merge_session_id}")
async def get_merge_session(
    tenant_slug: str,
    project_id: str,
    merge_session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Load persisted merge session and status transition history (#2573)."""
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    detail = db.get_merge_session_detail(merge_session_id, project_id, tenant_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Merge session not found")

    sess = detail["session"]
    events = [_merge_session_status_event_json(e) for e in detail["status_events"]]
    return {
        "success": True,
        "mergeSession": _merge_session_json(sess),
        "statusEvents": events,
    }


@router.get("/{tenant_slug}/{project_id}/merge-sessions/{merge_session_id}/conflicts")
async def list_merge_session_conflicts_route(
    tenant_slug: str,
    project_id: str,
    merge_session_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """List conflict rows for a merge session (#2573)."""
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    rows = db.list_merge_session_conflicts(merge_session_id, project_id, tenant_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Merge session not found")

    return {
        "success": True,
        "mergeSessionId": merge_session_id,
        "conflicts": [_merge_session_conflict_json(r) for r in rows],
    }


@router.patch("/{tenant_slug}/{project_id}/merge-sessions/{merge_session_id}")
async def patch_merge_session_status(
    tenant_slug: str,
    project_id: str,
    merge_session_id: str,
    body: MergeSessionStatusPatchRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Transition merge session status with audited events (#2573)."""
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    uid = get_authenticated_user_id(auth_data)
    ok, err = db.update_merge_session_status(
        merge_session_id, project_id, tenant_id, body.status, uid
    )
    if not ok:
        if err and err.startswith("Merge session not found"):
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err or "Invalid status transition")

    detail = db.get_merge_session_detail(merge_session_id, project_id, tenant_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Merge session not found after update")

    sess = detail["session"]
    events = [_merge_session_status_event_json(e) for e in detail["status_events"]]
    return {
        "success": True,
        "mergeSession": _merge_session_json(sess),
        "statusEvents": events,
    }
