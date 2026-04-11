"""
Git-like version branch merge: three-way OpenAPI schema merge + merge-base (#738).
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from .auth import validate_authentication, get_authenticated_user_id
from .compatibility_routes import _fingerprint, _openapi_for_revision
from .database import db
from .models import (
    CompatibilityFindingOut,
    VersionBranchMergePreviewRequest,
    VersionBranchMergeRequest,
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
from .version_notes import limits_for_tenant, validate_version_notes


router = APIRouter(prefix="/v1/versions", tags=["versions"])


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


def _extract_schemas(spec: Dict[str, Any]) -> Dict[str, Any]:
    return (spec.get("components") or {}).get("schemas") or {}


def _merge_openapi_components(
    base_spec: Dict[str, Any], merged_schemas: Dict[str, Any]
) -> Dict[str, Any]:
    out = copy.deepcopy(base_spec)
    out.setdefault("components", {})["schemas"] = merged_schemas
    return out


@router.post("/{tenant_slug}/{project_id}/version-branches/merge-preview")
async def version_branch_merge_preview(
    tenant_slug: str,
    project_id: str,
    body: VersionBranchMergePreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Dry-run merge: merge-base revision id, three-way schema classification, optional two-way summary.
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

    base_spec = _openapi_for_revision(base_ver, tenant_slug, tenant_id)
    source_spec = _openapi_for_revision(src_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(tgt_ver, tenant_slug, tenant_id)

    b = _extract_schemas(base_spec)
    o = _extract_schemas(target_spec)
    t = _extract_schemas(source_spec)

    merged, conflicts = merge_components_schemas_three_way(b, o, t)
    ok_mat, blend_paths = schema_merge_materializable_paths(merged or {}, o, t) if merged else (False, [])

    two_way = compare_schemas(json.dumps(target_spec), json.dumps(source_spec))
    _, conflict_paths_two, _ = classify_merge_diff_two_way(two_way)
    can_auto = bool(merged and not conflicts and ok_mat)

    preview: Dict[str, Any] = {
        "success": True,
        "mergeBaseVersionId": merge_base_id,
        "sourceTipVersionId": source_tip,
        "targetTipVersionId": target_tip,
        "summary": format_diff_summary_text(two_way),
        "classification": {
            "canAutoMerge": can_auto,
            "conflictPaths": list(
                dict.fromkeys((conflicts or []) + blend_paths + conflict_paths_two)
            ),
            "threeWayConflictPaths": conflicts or [],
            "blendPaths": blend_paths,
            "twoWayConflictPaths": conflict_paths_two,
        },
    }
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
        raise HTTPException(status_code=403, detail="Merge requires user authentication (JWT token)")

    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    src = db.get_version_branch_by_name(project_id, tenant_id, body.source_branch_name)
    tgt = db.get_version_branch_by_name(project_id, tenant_id, body.target_branch_name)
    if not src or not tgt:
        raise HTTPException(status_code=404, detail="Source or target branch not found")

    source_tip = str(src["tip_version_id"])
    target_tip = str(tgt["tip_version_id"])

    if target_tip != body.base_revision_id.strip():
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Target branch tip does not match baseRevisionId (stale head or wrong base).",
                "code": "STALE_HEAD",
            },
        )

    src_ver = db.get_version_by_id(source_tip, tenant_id)
    tgt_ver = db.get_version_by_id(target_tip, tenant_id)
    if not src_ver or not tgt_ver:
        raise HTTPException(status_code=403, detail="Version tip not accessible")
    if src_ver["project_id"] != project_id or tgt_ver["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Branch tips must belong to this project")
    if src_ver.get("published") or tgt_ver.get("published"):
        raise HTTPException(
            status_code=409,
            detail={"message": "Cannot merge published or frozen versions", "code": "PUBLISHED_VERSION"},
        )

    merge_base_id = db.compute_merge_base_revision_id(source_tip, target_tip, tenant_id)
    if not merge_base_id:
        raise HTTPException(
            status_code=400,
            detail="No common ancestor between branch tips (unrelated histories).",
        )

    base_ver = db.get_version_by_id(merge_base_id, tenant_id)
    if not base_ver:
        raise HTTPException(status_code=404, detail="Merge base revision not found")

    base_spec = _openapi_for_revision(base_ver, tenant_slug, tenant_id)
    source_spec = _openapi_for_revision(src_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(tgt_ver, tenant_slug, tenant_id)

    b = _extract_schemas(base_spec)
    o = _extract_schemas(target_spec)
    t = _extract_schemas(source_spec)

    merged, conflicts = merge_components_schemas_three_way(b, o, t)
    if not merged or conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Merge blocked: overlapping schema changes detected",
                "code": "MERGE_CONFLICT",
                "conflictPaths": conflicts,
            },
        )

    ok_mat, blend_paths = schema_merge_materializable_paths(merged, o, t)
    if not ok_mat:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Merge blocked: resolved schema differs from both branch tips (blend)",
                "code": "MERGE_BLEND",
                "conflictPaths": blend_paths,
            },
        )

    gate = _tenant_compat_gate(project) and not body.skip_compat_gate
    if gate:
        merged_spec = _merge_openapi_components(target_spec, merged)
        overall, _ = analyze_schema_compatibility(base_spec, merged_spec, CompatibilityRules())
        if overall != "safe":
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Merge blocked by compatibility gate (compatGateOnMerge).",
                    "code": "MERGE_BLOCKED_BY_COMPAT_GATE",
                    "overall": overall,
                },
            )

    limits = limits_for_tenant(tenant_id)
    latest = db.get_latest_version_for_project(project_id, tenant_id)
    new_version_string = bump_patch_version(latest) if latest else "0.1.0"
    raw_msg = f"Merge {body.source_branch_name} into {body.target_branch_name}"
    try:
        short_msg, _ = validate_version_notes(raw_msg, None, limits)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
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
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = prev_autocommit

    full = db.get_version_by_id(new_id, tenant_id)
    if not full:
        raise HTTPException(status_code=500, detail="Merge succeeded but revision not readable")
    return {
        "success": True,
        "version": VersionSchema.model_validate(full).model_dump(by_alias=True),
    }


def _rollback_analyze(
    tenant_slug: str,
    tenant_id: str,
    head_ver: Dict[str, Any],
    target_ver: Dict[str, Any],
) -> tuple:
    """
    Compare current branch tip (consumer expectation) to rollback snapshot (target).
    Semantics match #506: base = tip, head = restored content.
    """
    tip_spec = _openapi_for_revision(head_ver, tenant_slug, tenant_id)
    target_spec = _openapi_for_revision(target_ver, tenant_slug, tenant_id)
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
    return overall, finding_out, dep_out, fp, doc_url


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

    if bool(head_ver.get("published")):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLISHED_VERSION",
                "message": "Cannot roll back a published branch tip; unpublish or use an admin workflow.",
            },
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

    overall, finding_out, dep_out, fp, doc_url = _rollback_analyze(
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
    creator_id = get_authenticated_user_id(auth_data)
    if not creator_id:
        raise HTTPException(status_code=403, detail="Rollback requires user authentication (JWT token)")

    project, branch, head_ver, target_ver, head_tip, tgt_id = _rollback_validate_branch_and_revisions(
        project_id, tenant_id, body.branch_name, body.target_revision_id
    )

    base = (body.base_revision_id or "").strip()
    if base != head_tip:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Branch tip does not match baseRevisionId (stale head or wrong base).",
                "code": "STALE_HEAD",
            },
        )

    if bool(branch.get("protected")) and not db.is_user_tenant_admin(tenant_id, creator_id):
        raise HTTPException(
            status_code=403,
            detail="This branch is protected; only tenant administrators may roll back.",
        )

    overall, _finding_out, dep_out, _fp, _doc_url = _rollback_analyze(
        tenant_slug, tenant_id, head_ver, target_ver
    )
    gate = _tenant_compat_gate_rollback(project)
    if gate and overall != "safe":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Rollback blocked by compatibility gate (compatGateOnRollback).",
                "code": "ROLLBACK_BLOCKED_BY_COMPAT_GATE",
                "overall": overall,
            },
        )
    if overall != "safe" and not body.skip_compat_warning:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Rollback may remove or change schema surface relative to the branch tip; confirm or set skipCompatWarning.",
                "code": "ROLLBACK_NEEDS_CONFIRMATION",
                "overall": overall,
            },
        )

    limits = limits_for_tenant(tenant_id)
    latest = db.get_latest_version_for_project(project_id, tenant_id)
    new_version_string = bump_patch_version(latest) if latest else "0.1.0"

    default_msg = f"Rollback schema to v{target_ver['version_id']} (revert-style)"
    raw_msg = (body.short_message or "").strip() or default_msg
    raw_cl = (body.changelog or "").strip() or None
    try:
        short_msg, cl = validate_version_notes(raw_msg, raw_cl, limits, require_short_message=limits.require_short_message)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    rb_meta = {
        "rollback": {
            "contentRevisionId": tgt_id,
            "priorHeadRevisionId": head_tip,
            "branchName": (body.branch_name or "").strip(),
        }
    }

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
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
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
            "branchName": (body.branch_name or "").strip(),
            "targetRevisionId": tgt_id,
            "priorTipRevisionId": head_tip,
            "compatOverall": overall,
            "deprecationWarningCount": len(dep_out),
        },
    )

    full = db.get_version_by_id(new_id, tenant_id)
    if not full:
        raise HTTPException(status_code=500, detail="Rollback succeeded but revision not readable")
    return {
        "success": True,
        "version": VersionSchema.model_validate(full).model_dump(by_alias=True),
    }
