"""``GET /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources`` — REPO-5.7 (#2792).

The read surface of the multi-repository merge: which repository files contribute to a project and
which of them defined each class and path of a version. The rules and the writes live in the import
(apiome-ui ``lib/repository-merge.ts`` / ``lib/db/repository-merge.ts``); the read is
:mod:`app.project_repository_sources`.

**Authorization.** ``projects:view``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from .auth import validate_authentication
from .comments import CommentValidationError
from .database import db
from .permissions import Action, Resource, enforce_permission
from .project_repository_sources import (
    ProjectRepositorySourcesResponse,
    read_project_repository_sources,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["project-repository-sources"])


@router.get(
    "/{tenant_slug}/projects/{project_ref}/repository-sources",
    response_model=ProjectRepositorySourcesResponse,
    summary="List a project's contributing repositories and per-entity provenance",
    description=(
        "The repository files whose imports make up the project's merged API surface, in "
        "precedence order (1 contributed first), and every class and path of one version with "
        "the file that defined it. `source` is null for a class or path no repository defined "
        "(edited in Apiome, or imported before multi-repository merge).\n\n"
        "`version` is a revision id or version label; the project's newest version when "
        "omitted.\n\n"
        "Requires `projects:view`."
    ),
)
async def list_project_repository_sources(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ProjectRepositorySourcesResponse:
    """List a project's contributing repository files and one version's provenance.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version: Revision id or version label; the newest version when omitted.
        auth_data: The authenticated principal.

    Returns:
        The sources, the version, and the provenance of every class and path.

    Raises:
        HTTPException: 403 without ``projects:view`` or a tenant, 404 for an unknown project or
            version.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    try:
        return read_project_repository_sources(str(tenant_id), project_ref, version)
    except CommentValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
