"""Resolve effective Mustache template for a tenant/project (#2701)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException

from .change_report_default_templates import SYSTEM_TEMPLATE_ID
from .change_report_render import bundled_system_template_row


def template_accessible_to_tenant(row: Dict[str, Any], tenant_id: str) -> bool:
    owner = row.get("owner_tenant_id")
    return owner is None or str(owner) == str(tenant_id)


def resolve_effective_change_report_template(
    db: Any,
    tenant_id: str,
    project_id: str,
    override_template_version_id: Optional[str],
) -> Dict[str, Any]:
    """
    Project override > tenant default > system seeded row > bundled Python fallback.

    ``override_template_version_id`` (e.g. regenerate body) must belong to system or this tenant.
    """
    if override_template_version_id:
        row = db.get_change_report_template_version_by_id(override_template_version_id)
        if not row:
            raise HTTPException(status_code=404, detail="change report template version not found")
        if not template_accessible_to_tenant(row, tenant_id):
            raise HTTPException(
                status_code=400,
                detail="template version is not available for this tenant",
            )
        return row

    proj = db.get_project_by_id(project_id, tenant_id)
    if not proj:
        raise HTTPException(status_code=404, detail="project not found")
    pid = proj.get("change_report_template_version_id")
    if pid:
        row = db.get_change_report_template_version_by_id(str(pid))
        if row and template_accessible_to_tenant(row, tenant_id):
            return row

    tid = db.get_tenant_change_report_template_version_id(tenant_id)
    if tid:
        row = db.get_change_report_template_version_by_id(tid)
        if row and template_accessible_to_tenant(row, tenant_id):
            return row

    row = db.get_change_report_template_version_by_id(SYSTEM_TEMPLATE_ID)
    if row:
        return row
    return bundled_system_template_row()
