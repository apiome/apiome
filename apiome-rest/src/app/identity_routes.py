"""
Cross-format API identity routes (MFI-6.4, #4410).

Manual link/unlink of related artifacts plus heuristic suggestions. Conversion provenance
(MFI-22.5) auto-seeds links via :func:`app.conversion_job.run_conversion`; suggestions never
auto-link without user confirmation.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from .api_identity_service import (
    build_related_artifact_refs,
    rank_identity_suggestions,
)
from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .models import (
    IdentitySuggestionRef,
    LinkArtifactsRequest,
    RelatedArtifactRef,
    UnlinkArtifactsRequest,
)

router = APIRouter(prefix="/v1/identity", tags=["identity"])


def _related_for_project(tenant_id: str, project_id: str) -> List[RelatedArtifactRef]:
    rows = db.get_related_artifact_rows(tenant_id, project_id)
    return build_related_artifact_refs(rows)


@router.get("/{tenant_slug}/projects/{project_id}/related")
async def get_related_artifacts(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[RelatedArtifactRef]:
    """List artifacts linked to ``project_id`` in the same identity group."""
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    return _related_for_project(tenant_id, project_id)


@router.get("/{tenant_slug}/projects/{project_id}/suggestions")
async def get_identity_suggestions(
    tenant_slug: str,
    project_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[IdentitySuggestionRef]:
    """Heuristic link suggestions for ``project_id`` (never auto-applied)."""
    tenant_id = auth_data["tenant_id"]
    anchor = db.get_project_identity_profile(tenant_id, project_id)
    if not anchor:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    candidates = db.get_identity_suggestion_candidates(tenant_id, project_id, limit=50)
    anchor_ops = set(db.get_operation_keys_for_project(tenant_id, project_id))
    candidate_ops: Dict[str, set[str]] = {}
    for row in candidates:
        pid = str(row["project_id"])
        candidate_ops[pid] = set(db.get_operation_keys_for_project(tenant_id, pid))

    return rank_identity_suggestions(
        anchor=anchor,
        anchor_ops=anchor_ops,
        candidates=candidates,
        candidate_ops=candidate_ops,
    )


@router.post("/{tenant_slug}/link")
async def link_artifacts(
    tenant_slug: str,
    body: LinkArtifactsRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Link two projects into the same cross-format API identity group."""
    tenant_id = auth_data["tenant_id"]
    user_id = get_authenticated_user_id(auth_data)
    try:
        group_id = db.link_identity_projects(
            tenant_id=tenant_id,
            project_id_a=body.project_id,
            project_id_b=body.related_project_id,
            created_by=user_id,
            link_source="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "identityGroupId": group_id,
        "relatedArtifacts": _related_for_project(tenant_id, body.project_id),
    }


@router.delete("/{tenant_slug}/link")
async def unlink_artifacts(
    tenant_slug: str,
    body: UnlinkArtifactsRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Remove ``relatedProjectId`` from the shared identity group."""
    tenant_id = auth_data["tenant_id"]
    for pid in (body.project_id, body.related_project_id):
        if not db.get_project_by_id(pid, tenant_id):
            raise HTTPException(status_code=404, detail=f"Project not found: {pid}")

    db.unlink_identity_projects(
        tenant_id=tenant_id,
        project_id=body.project_id,
        related_project_id=body.related_project_id,
    )
    group_id = db.get_identity_group_id_for_project(tenant_id, body.project_id)
    return {
        "identityGroupId": group_id,
        "relatedArtifacts": _related_for_project(tenant_id, body.project_id),
    }
