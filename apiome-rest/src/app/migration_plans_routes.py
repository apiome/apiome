"""
Migration plans API routes.

GET/PUT migration plan rules (per project, from_version, to_version, class_name).
Used by the migration canvas and by services that run migrations.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Dict, Any

from .database import db
from .auth import validate_authentication
from .permissions import enforce_permission, Resource, Action

router = APIRouter(prefix="/v1/migration-plans", tags=["migration-plans"])


@router.get("/{tenant_slug}")
async def get_migration_plan_rules(
    tenant_slug: str,
    project_id: str = Query(..., alias="projectId"),
    from_version_id: str = Query(..., alias="fromVersionId"),
    to_version_id: str = Query(..., alias="toVersionId"),
    class_name: str = Query(..., alias="className"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Get migration plan rules for a (project, from_version, to_version, class_name).
    Returns rules keyed by migration-edge-prop-{source_property}.
    """
    rules = db.get_migration_plan_rules(
        project_id=project_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        class_name=class_name,
        tenant_id=auth_data["tenant_id"],
    )
    return {"rules": rules}


@router.put("/{tenant_slug}")
async def save_migration_plan_rules(
    tenant_slug: str,
    request: Dict[str, Any],
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Save migration plan rules for a (project, from_version, to_version, class_name).
    Body: project_id, from_version_id, to_version_id, class_name, rules.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    project_id = request.get("project_id")
    from_version_id = request.get("from_version_id")
    to_version_id = request.get("to_version_id")
    class_name = request.get("class_name")
    rules = request.get("rules")
    if not project_id or not from_version_id or not to_version_id or not class_name:
        raise HTTPException(
            status_code=400,
            detail="project_id, from_version_id, to_version_id, and class_name are required",
        )
    if rules is not None and not isinstance(rules, dict):
        rules = {}
    error = db.save_migration_plan_rules(
        project_id=project_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        class_name=class_name,
        rules=rules or {},
        tenant_id=auth_data["tenant_id"],
    )
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"success": True}


@router.get("/{tenant_slug}/counts")
async def get_migration_plan_rule_counts(
    tenant_slug: str,
    project_id: str = Query(..., alias="projectId"),
    from_version_id: str = Query(..., alias="fromVersionId"),
    to_version_id: str = Query(..., alias="toVersionId"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """
    Get rule counts per class_name for a migration plan (project, from_version, to_version).
    Returns { "counts": { "ClassName": 2, ... } }.
    """
    counts = db.get_migration_plan_rule_counts(
        project_id=project_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        tenant_id=auth_data["tenant_id"],
    )
    return {"counts": counts}
