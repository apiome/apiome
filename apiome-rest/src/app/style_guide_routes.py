"""
Style-guide management API — GOV-2.1 (#4433).

GOV-EPIC-1 delivered storage (V159), the rule registry, the custom-rule DSL, and engine
integration — but guides and assignments were only writable by the SQL seed. This module
adds the tenant-admin CRUD surface the Control Panel's Governance → Style Guides screen
drives:

* **List** — every guide with its list-view rollups (rules on, assignments, default badge).
  Listing self-heals the seeded read-only "Apiome Recommended" guide for tenants created
  after the V159 migration (``ensure_builtin_roles`` pattern).
* **Create / duplicate** — a create with an optional ``sourceGuideId`` whose rule rows are
  copied, which is both "duplicate" and "start from Recommended".
* **Assign** — set a guide as tenant default (moves ``is_default`` *and* the tenant-wide
  ``style_guide_assignments`` row, keeping resolution tiers 1 and 2 agreeing) or bind it to
  a single project. The next lint run picks assignments up live — GOV-1.4 resolution
  queries the tables on every run and the compiled-guide cache is content-addressed.

Reads require tenant authentication; every mutation requires a **tenant administrator**
user session — governance is the buyer-admin persona's surface, and API keys cannot
administer it. The builtin guide is read-only: rename/delete return ``409
STYLE_GUIDE_READ_ONLY`` (duplicate it instead), though it can be assigned like any guide.
"""

from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import APIRouter, Depends, HTTPException

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .models import (
    StyleGuideCreateRequest,
    StyleGuideListResponse,
    StyleGuideOut,
    StyleGuideProjectAssignmentOut,
    StyleGuideUpdateRequest,
)

router = APIRouter(prefix="/v1/style-guides", tags=["style-guides"])

#: ``detail.code`` for mutations against the read-only builtin guide.
READ_ONLY_CODE = "STYLE_GUIDE_READ_ONLY"

#: ``detail.code`` for a per-tenant guide-name collision.
NAME_CONFLICT_CODE = "STYLE_GUIDE_NAME_CONFLICT"


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id or fail loudly when the context is missing."""
    tid = auth_data.get("tenant_id")
    if not tid:
        raise HTTPException(status_code=500, detail="Missing tenant context")
    return str(tid)


def _require_tenant_admin(auth_data: Dict[str, Any]) -> str:
    """Gate a mutation to tenant administrators; returns the tenant id.

    Style guides govern how every project in the tenant is scored, so mutations are an
    admin-only, user-session-only operation (an API key carries no administrator).
    """
    tenant_id = _tenant_id(auth_data)
    user_id = get_authenticated_user_id(auth_data)
    if not user_id or not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(
            status_code=403,
            detail="Only tenant administrators can manage style guides",
        )
    return tenant_id


def _guide_out(
    row: Dict[str, Any],
    project_assignments: Optional[List[StyleGuideProjectAssignmentOut]] = None,
) -> StyleGuideOut:
    """Map a ``style_guides`` row (with optional rollups) onto the response model."""
    return StyleGuideOut(
        id=str(row["id"]),
        name=row["name"],
        description=row.get("description"),
        source=row["source"],
        is_default=bool(row.get("is_default")),
        rule_count=int(row.get("rule_count") or 0),
        enabled_rule_count=int(row.get("enabled_rule_count") or 0),
        tenant_assigned=bool(row.get("tenant_assigned")),
        project_assignments=project_assignments or [],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _load_guide_or_404(guide_id: str, tenant_id: str) -> Dict[str, Any]:
    """Fetch a tenant's guide row or raise 404."""
    guide = db.get_style_guide_by_id(guide_id, tenant_id)
    if not guide:
        raise HTTPException(status_code=404, detail="Style guide not found")
    return guide


def _reject_builtin(guide: Dict[str, Any], operation: str) -> None:
    """Raise the read-only 409 for the seeded builtin guide."""
    if guide.get("source") == "builtin":
        raise HTTPException(
            status_code=409,
            detail={
                "code": READ_ONLY_CODE,
                "message": (
                    f"'{guide['name']}' is the built-in guide and cannot be {operation}. "
                    "Duplicate it to customize."
                ),
            },
        )


def _name_conflict() -> HTTPException:
    """The 409 for a per-tenant guide-name collision (UNIQUE (tenant_id, name))."""
    return HTTPException(
        status_code=409,
        detail={
            "code": NAME_CONFLICT_CODE,
            "message": "A style guide with this name already exists in this tenant",
        },
    )


@router.get("/{tenant_slug}", response_model=StyleGuideListResponse)
async def list_style_guides(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StyleGuideListResponse:
    """List the tenant's style guides with list-view rollups (rules on, assignments)."""
    tenant_id = _tenant_id(auth_data)
    db.ensure_builtin_style_guide(tenant_id)
    assignment_rows = db.list_style_guide_project_assignments(tenant_id)
    by_guide: Dict[str, List[StyleGuideProjectAssignmentOut]] = {}
    for row in assignment_rows:
        by_guide.setdefault(str(row["guide_id"]), []).append(
            StyleGuideProjectAssignmentOut(
                project_id=str(row["project_id"]),
                project_name=row["project_name"],
            )
        )
    guides = [
        _guide_out(row, by_guide.get(str(row["id"])))
        for row in db.list_style_guides(tenant_id)
    ]
    return StyleGuideListResponse(guides=guides, count=len(guides))


@router.post("/{tenant_slug}", response_model=StyleGuideOut, status_code=201)
async def create_style_guide(
    tenant_slug: str,
    body: StyleGuideCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StyleGuideOut:
    """Create a custom guide; ``sourceGuideId`` copies that guide's rules (duplicate)."""
    tenant_id = _require_tenant_admin(auth_data)
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Style guide name cannot be blank")
    rule_count = 0
    if body.source_guide_id:
        source = db.get_style_guide_by_id(body.source_guide_id, tenant_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source style guide not found")
        rule_count = len(db.get_style_guide_rules(str(source["id"]), tenant_id))
    try:
        row = db.create_style_guide(
            tenant_id, name, body.description, body.source_guide_id or None
        )
    except psycopg2.IntegrityError:
        raise _name_conflict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _guide_out({**row, "rule_count": rule_count, "enabled_rule_count": rule_count})


@router.patch("/{tenant_slug}/{guide_id}", response_model=StyleGuideOut)
async def update_style_guide(
    tenant_slug: str,
    guide_id: str,
    body: StyleGuideUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StyleGuideOut:
    """Rename / re-describe a custom guide (the builtin guide is read-only)."""
    tenant_id = _require_tenant_admin(auth_data)
    guide = _load_guide_or_404(guide_id, tenant_id)
    _reject_builtin(guide, "edited")
    name = body.name.strip() if body.name is not None else guide["name"]
    if not name:
        raise HTTPException(status_code=400, detail="Style guide name cannot be blank")
    if "description" in body.model_fields_set:
        description = body.description or None
    else:
        description = guide.get("description")
    try:
        row = db.update_style_guide(str(guide["id"]), tenant_id, name, description)
    except psycopg2.IntegrityError:
        raise _name_conflict()
    if not row:
        raise HTTPException(status_code=404, detail="Style guide not found")
    rules = db.get_style_guide_rules(str(row["id"]), tenant_id)
    return _guide_out(
        {
            **row,
            "rule_count": len(rules),
            "enabled_rule_count": sum(1 for r in rules if r.get("enabled")),
        }
    )


@router.delete("/{tenant_slug}/{guide_id}")
async def delete_style_guide(
    tenant_slug: str,
    guide_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """Delete a custom guide; its assignments cascade and the affected projects fall back
    to the tenant default. Deleting the current default promotes the builtin guide."""
    tenant_id = _require_tenant_admin(auth_data)
    guide = _load_guide_or_404(guide_id, tenant_id)
    _reject_builtin(guide, "deleted")
    if not db.delete_style_guide(str(guide["id"]), tenant_id):
        raise HTTPException(status_code=404, detail="Style guide not found")
    return {"status": "deleted", "id": str(guide["id"])}


@router.put("/{tenant_slug}/{guide_id}/default", response_model=StyleGuideOut)
async def set_tenant_default(
    tenant_slug: str,
    guide_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> StyleGuideOut:
    """Make a guide the tenant default — what every project without its own assignment
    lints under from the next run onward."""
    tenant_id = _require_tenant_admin(auth_data)
    row = db.set_style_guide_tenant_default(guide_id, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail="Style guide not found")
    rules = db.get_style_guide_rules(str(row["id"]), tenant_id)
    return _guide_out(
        {
            **row,
            "rule_count": len(rules),
            "enabled_rule_count": sum(1 for r in rules if r.get("enabled")),
            "tenant_assigned": True,
        }
    )


@router.put("/{tenant_slug}/{guide_id}/assignments/projects/{project_id}")
async def assign_project(
    tenant_slug: str,
    guide_id: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """Assign a guide to one project (replaces the project's previous assignment).

    A project-level assignment wins over the tenant default in the GOV-1.4 resolution
    order, so the project's next lint run scores under this guide.
    """
    tenant_id = _require_tenant_admin(auth_data)
    _load_guide_or_404(guide_id, tenant_id)
    if not db.assign_style_guide_to_project(guide_id, tenant_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "assigned", "guideId": guide_id, "projectId": project_id}


@router.delete("/{tenant_slug}/assignments/projects/{project_id}")
async def unassign_project(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, str]:
    """Remove a project's guide assignment; it falls back to the tenant default."""
    tenant_id = _require_tenant_admin(auth_data)
    if not db.unassign_style_guide_from_project(tenant_id, project_id):
        raise HTTPException(status_code=404, detail="No assignment found for this project")
    return {"status": "unassigned", "projectId": project_id}
