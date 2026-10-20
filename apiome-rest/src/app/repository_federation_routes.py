"""Federation endpoints — V2-REPO-8.2 (#2806).

```
GET|PUT  /v1/tenants/{t}/projects/{project}/repository-federation
POST     /v1/tenants/{t}/projects/{project}/federation-merges
GET      /v1/tenants/{t}/projects/{project}/federation-merges
GET      /v1/tenants/{t}/repositories/{repository_id}/federation-merges
```

**The switch** is the project's: reading it is ``projects:view``, changing it ``projects:edit``
(audited as ``repository.federation_toggled``).

**Recording a merge** is done by apiome-ui's import, as the importing user, after federation acted
on a repository-file import — it needs ``imports:create``, the permission the import itself needs.
The row and its audit row (``repository.federation_merged`` / ``…_conflicted`` /
``…_replaced``) are written in one transaction. For a conflict, the contributing file's side of
each collision is read here from the parent version's rendered spec, so the history carries both
sources' definitions.

**Reading the history** is ``projects:view`` for a project and ``imports:view`` for a repository
(its Imports tab, where the repository's sync history lives).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from . import repository_federation_store as store
from .auth import get_authenticated_user_id, validate_authentication
from .compatibility_engine import openapi_for_revision
from .database import db
from .permissions import Action, Resource, enforce_permission
from .repository_federation import (
    FederationMerge,
    FederationMergeCreate,
    FederationMergeList,
    FederationSetting,
    FederationSettingUpdate,
    with_existing_definitions,
)
from .revision_deprecation import is_uuid_string
from .sdk_publish_routes import resolve_project, tenant_id_of

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["repository-federation"])


def _actor_label(auth_data: Dict[str, Any]) -> Optional[str]:
    """The audit label of the caller."""
    return auth_data.get("user_email") or auth_data.get("user_name")


def _parent_spec(tenant_id: str, tenant_slug: str, project_id: str, parent_version_id: Optional[str]) -> Any:
    """Render the parent version's spec, for the existing side of each conflict (best-effort).

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: For the rendered server URLs.
        project_id: The project the parent must belong to.
        parent_version_id: The parent version.

    Returns:
        The rendered OpenAPI document, or ``None`` when there is no such version or it cannot be
        rendered (the conflict is still recorded, with a null definition on that side).
    """
    if not parent_version_id or not is_uuid_string(parent_version_id):
        return None
    try:
        version = db.get_version_by_id(parent_version_id, tenant_id)
        if not version or str(version.get("project_id")) != project_id:
            return None
        return openapi_for_revision(version, tenant_slug, tenant_id)
    except Exception:  # noqa: BLE001 - a render fault must not lose the conflict record
        logger.warning("Could not render parent version %s for a federation conflict", parent_version_id, exc_info=True)
        return None


@router.get(
    "/{tenant_slug}/projects/{project_ref}/repository-federation",
    response_model=FederationSetting,
    summary="Read a project's multi-repository federation switch",
    description=(
        "`enabled: true` (the default) merges each repository file imported into the project with "
        "the other contributing files into one API surface. `false` makes each import replace the "
        "surface with the importing file alone.\n\nRequires `projects:view`."
    ),
)
async def get_repository_federation(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> FederationSetting:
    """Read a project's federation switch.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        The switch.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 for an unknown project.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project_id = str(resolve_project(tenant_id, project_ref)["id"])
    enabled = store.get_federation_enabled(tenant_id, project_id)
    return FederationSetting(project_id=project_id, enabled=True if enabled is None else enabled)


@router.put(
    "/{tenant_slug}/projects/{project_ref}/repository-federation",
    response_model=FederationSetting,
    summary="Switch a project's multi-repository federation on or off",
    description=(
        "Applies to the next import; existing versions are not changed. Requires `projects:edit`. "
        "Audited as `repository.federation_toggled`."
    ),
)
async def put_repository_federation(
    tenant_slug: str,
    project_ref: str,
    body: FederationSettingUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> FederationSetting:
    """Switch a project's federation on or off.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The new value.
        auth_data: The authenticated principal.

    Returns:
        The stored switch.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 for an unknown project.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project_id = str(resolve_project(tenant_id, project_ref)["id"])
    stored = store.set_federation_enabled(
        tenant_id,
        project_id,
        body.enabled,
        actor_id=get_authenticated_user_id(auth_data),
        actor_label=_actor_label(auth_data),
    )
    if stored is None:
        raise HTTPException(status_code=404, detail="project not found")
    return FederationSetting(project_id=project_id, enabled=stored)


@router.post(
    "/{tenant_slug}/projects/{project_ref}/federation-merges",
    response_model=FederationMerge,
    status_code=201,
    summary="Record a federation merge (called by the import)",
    description=(
        "Records what federation did to one repository-file import: `merged`, `conflicted` (nothing "
        "written; each conflict carries every source's definition — the contributing file's is read "
        "from `parentVersionId`'s rendered spec when not sent) or `replaced` (federation off). The "
        "row and its audit row (`repository.federation_merged`, `repository.federation_conflicted` "
        "or `repository.federation_replaced`) are written in one transaction.\n\n"
        "Requires `imports:create`."
    ),
)
async def create_federation_merge(
    tenant_slug: str,
    project_ref: str,
    body: FederationMergeCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> FederationMerge:
    """Record one federation merge.

    Args:
        tenant_slug: The tenant in the URL (renders the parent spec's server URLs).
        project_ref: Project slug or id.
        body: The import's report.
        auth_data: The authenticated principal (the importing user).

    Returns:
        The stored history row.

    Raises:
        HTTPException: 403 without ``imports:create``; 404 for an unknown project.
    """
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE)
    tenant_id = tenant_id_of(auth_data)
    project_id = str(resolve_project(tenant_id, project_ref)["id"])
    parent_spec = (
        _parent_spec(tenant_id, str(tenant_slug or ""), project_id, body.parent_version_id)
        if body.conflicts and any(
            s.role == "existing" and s.definition is None for c in body.conflicts for s in c.sources
        )
        else None
    )
    conflicts = with_existing_definitions(body.conflicts, parent_spec)
    merge_id = store.insert_merge(
        tenant_id,
        project_id,
        body,
        conflicts,
        actor_id=get_authenticated_user_id(auth_data),
        actor_label=_actor_label(auth_data),
    )
    if merge_id is None:
        raise HTTPException(status_code=404, detail="project not found")
    row = next((r for r in store.list_project_merges(tenant_id, project_id, 5) if r["id"] == merge_id), None)
    if row is None:  # pragma: no cover - the row was just committed
        raise HTTPException(status_code=500, detail="merge recorded but could not be read back")
    return FederationMerge.model_validate(row)


@router.get(
    "/{tenant_slug}/projects/{project_ref}/federation-merges",
    response_model=FederationMergeList,
    summary="List a project's federation merge history",
    description="Newest first. Requires `projects:view`.",
)
async def list_project_federation_merges(
    tenant_slug: str,
    project_ref: str,
    limit: int = Query(default=50, ge=1, le=store.MAX_HISTORY_LIMIT),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> FederationMergeList:
    """List a project's merge history.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        limit: Rows to return.
        auth_data: The authenticated principal.

    Returns:
        The history, newest first.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project_id = str(resolve_project(tenant_id, project_ref)["id"])
    rows = store.list_project_merges(tenant_id, project_id, limit)
    return FederationMergeList(merges=[FederationMerge.model_validate(r) for r in rows])


@router.get(
    "/{tenant_slug}/repositories/{repository_id}/federation-merges",
    response_model=FederationMergeList,
    summary="List the federation merges a repository's files were imported in",
    description=(
        "The repository's sync history: every merge, conflict and replacement where one of its "
        "files was the imported file, newest first. Requires `imports:view`."
    ),
)
async def list_repository_federation_merges(
    tenant_slug: str,
    repository_id: str,
    limit: int = Query(default=50, ge=1, le=store.MAX_HISTORY_LIMIT),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> FederationMergeList:
    """List the merges a repository's files were imported in.

    Args:
        tenant_slug: The tenant in the URL.
        repository_id: The registered repository.
        limit: Rows to return.
        auth_data: The authenticated principal.

    Returns:
        The history, newest first.

    Raises:
        HTTPException: 404 for an unknown repository.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    if not is_uuid_string(repository_id) or not db.get_tenant_repository(tenant_id, repository_id):
        raise HTTPException(status_code=404, detail="repository not found")
    rows = store.list_repository_merges(tenant_id, repository_id, limit)
    return FederationMergeList(merges=[FederationMerge.model_validate(r) for r in rows])
