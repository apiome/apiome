"""
Read APIs over persisted publish-time classified changelogs (CTG-3.2, #4476).

CTG-3.1 (#4475) stores one ``apiome.version_changelogs`` row per published
revision. These endpoints expose that data to the dashboard:

* ``GET /v1/versions/{tenant_slug}/{project_id}/changelogs`` — one summary row
  per published revision (badges / Changes tab list), newest publish first.
* ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/changelog``
  — the full stored ``ctg.changelog.v1`` payload for one revision.

Authentication matches the other version APIs (JWT or API key, tenant-scoped).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .database import db
from .models import (
    ProjectVersionChangelogsResponse,
    VersionChangelogOut,
    VersionChangelogSummaryRow,
)
from .revision_deprecation import is_uuid_string

# NOTE: this router must be registered before ``versions_router`` in main.py so the
# literal ``/{tenant_slug}/{project_id}/changelogs`` path wins over the versions
# ``/{tenant_slug}/{project_id}/{version_record_id}`` parameter route.
router = APIRouter(prefix="/v1/versions", tags=["version-changelog"])


def _counts_dict(value: Any) -> Optional[Dict[str, int]]:
    """Coerce a JSONB ``counts`` object to ``Dict[str, int]`` (``None`` if absent/invalid)."""
    if not isinstance(value, dict):
        return None
    out: Dict[str, int] = {}
    for key, raw in value.items():
        try:
            out[str(key)] = int(raw)
        except (TypeError, ValueError):
            continue
    return out


def _summary_row_out(row: Dict[str, Any]) -> VersionChangelogSummaryRow:
    """Map a ``list_version_changelogs_for_project`` row to its response model."""
    return VersionChangelogSummaryRow(
        published_revision_id=str(row["published_revision_id"]),
        version_label=row.get("version_label"),
        published_at=row.get("published_at"),
        baseline_revision_id=(
            str(row["baseline_revision_id"]) if row.get("baseline_revision_id") else None
        ),
        baseline_version_label=row.get("baseline_version_label"),
        status=row.get("status"),
        max_severity=row.get("max_severity"),
        counts=_counts_dict(row.get("counts")),
        updated_at=row.get("updated_at"),
    )


def _require_project(project_id: str, tenant_id: str) -> Dict[str, Any]:
    """Resolve a project UUID within the tenant or raise 404 (400 for malformed ids)."""
    ref = (project_id or "").strip()
    if not is_uuid_string(ref):
        raise HTTPException(status_code=400, detail=f"Invalid project id: {project_id}")
    project = db.get_project_by_id(ref, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return project


@router.get(
    "/{tenant_slug}/{project_id}/changelogs",
    response_model=ProjectVersionChangelogsResponse,
    responses={
        400: {"description": "Malformed project id."},
        404: {"description": "Project not found in tenant."},
    },
)
async def list_project_version_changelogs(
    tenant_slug: str,
    project_id: str,
    limit: Optional[int] = Query(
        None,
        ge=1,
        le=500,
        description="Optional max rows, newest publish first.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectVersionChangelogsResponse:
    """
    List changelog summaries for every published revision of a project.

    Revisions without a stored classification row (pending or pre-backfill) are
    included with ``status: null`` so callers can render a pending state.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    project = _require_project(project_id, tenant_id)
    rows = db.list_version_changelogs_for_project(
        str(project["id"]), tenant_id, limit=limit
    )
    changelogs = [_summary_row_out(row) for row in rows]
    return ProjectVersionChangelogsResponse(
        project_id=str(project["id"]),
        changelogs=changelogs,
        filtered_count=len(changelogs),
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/changelog",
    response_model=VersionChangelogOut,
    responses={
        400: {"description": "Revision is not published."},
        404: {"description": "Version not found, or no changelog stored for this revision."},
    },
)
async def get_version_changelog(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionChangelogOut:
    """
    Return the stored classified changelog for one **published** revision.

    The ``changelog`` field is the raw ``ctg.changelog.v1`` payload (entries in
    breaking → non-breaking → docs-only order, grouped by path), or the
    initial-publication marker when the revision had no published baseline.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    if not is_uuid_string((version_record_id or "").strip()):
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    if str(version.get("project_id")) != str(project_id):
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )
    if not version.get("published"):
        raise HTTPException(
            status_code=400,
            detail="Changelogs are only defined for published revisions",
        )

    row = db.get_version_changelog(version_record_id, tenant_id, str(version["project_id"]))
    if not row:
        raise HTTPException(
            status_code=404,
            detail="No changelog stored for this revision",
        )

    baseline_id = str(row["baseline_revision_id"]) if row.get("baseline_revision_id") else None
    baseline_label: Optional[str] = None
    if baseline_id:
        baseline_row = db.get_version_by_id(baseline_id, tenant_id)
        if baseline_row:
            baseline_label = baseline_row.get("version_id")

    changelog_json = row.get("changelog_json")
    return VersionChangelogOut(
        published_revision_id=str(row["published_revision_id"]),
        baseline_revision_id=baseline_id,
        version_label=version.get("version_id"),
        baseline_version_label=baseline_label,
        published_at=version.get("published_at"),
        status=str(row.get("status") or "failed"),
        max_severity=row.get("max_severity"),
        error=row.get("error"),
        changelog=changelog_json if isinstance(changelog_json, dict) else None,
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )
