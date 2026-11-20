"""
Arazzo workflow viewer — read API (COA-1.3, #7039).

GET /v1/workflows/{tenant_slug}/versions/{version_id}
GET /v1/workflows/{tenant_slug}/catalog/{item_id}
GET /v1/workflows/{tenant_slug}/operations/{path_operation_id}

The first two return the workflows REPO-3.4 (#2773) persisted for a revision — a catalog item's
read follows its latest revision — with each step's resolved operation and each workflow's
source-description status. The third reads one operation for the step drawer. All three are
tenant-scoped reads, like the paths reads the viewer links into.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from .arazzo_workflow_view import build_source_views, build_workflow_views
from .auth import validate_authentication
from .database import db
from .models import ArazzoOperationDetailOut, ArazzoWorkflowsResponse

router = APIRouter(prefix="/v1/workflows", tags=["arazzo-workflows"])


def _require_uuid(label: str, raw: str) -> str:
    """Return ``raw`` as a canonical UUID string, or raise 400.

    Args:
        label: The parameter name, for the error message.
        raw: The path parameter as received.

    Returns:
        The canonical UUID string.

    Raises:
        HTTPException: 400 when ``raw`` is not a UUID (a malformed id would otherwise reach a
            ``::uuid`` cast and surface as a 500).
    """
    try:
        return str(uuid.UUID(str(raw).strip()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}: expected UUID") from exc


def _workflows_for_version(
    tenant_id: str, version_id: str, project_id: str
) -> ArazzoWorkflowsResponse:
    """Assemble the viewer payload for one revision.

    Args:
        tenant_id: Owning tenant UUID.
        version_id: The revision (``versions.id``) to read.
        project_id: The revision's project, echoed back.

    Returns:
        The revision's workflows (empty when it has none) and declared sources.
    """
    workflows = db.load_arazzo_workflows(tenant_id=tenant_id, version_id=version_id)
    context = db.get_arazzo_source_context(tenant_id=tenant_id, version_id=version_id)
    sources = build_source_views(context["source_descriptions"], context["report"])
    operations = db.get_arazzo_step_operations(
        tenant_id=tenant_id,
        path_operation_ids=[
            step.resolved_path_operation_id
            for workflow in workflows
            for step in workflow.steps
            if step.resolved_path_operation_id
        ],
    )
    return ArazzoWorkflowsResponse(
        version_id=version_id,
        project_id=project_id,
        sources=sources,
        workflows=build_workflow_views(workflows, operations=operations, sources=sources),
    )


@router.get("/{tenant_slug}/versions/{version_id}")
async def list_version_workflows(
    tenant_slug: str,
    version_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowsResponse:
    """
    List the Arazzo workflows persisted for a revision.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        version_id: The revision (``versions.id``) UUID.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The revision's workflows in declaration order, each with its ordered steps, the
        operation each step resolved to, and its source-description status. An empty
        ``workflows`` list means the revision holds no Arazzo document.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant.
    """
    version_id = _require_uuid("version_id", version_id)
    tenant_id = auth_data["tenant_id"]
    version = db.get_version_for_tenant(tenant_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")
    return _workflows_for_version(tenant_id, version_id, str(version["project_id"]))


@router.get("/{tenant_slug}/catalog/{item_id}")
async def list_catalog_item_workflows(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowsResponse:
    """
    List the Arazzo workflows of a catalog item's latest revision.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        item_id: The catalog item UUID.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The latest revision's workflows; ``version_id`` is null and ``workflows`` empty when the
        item has no revisions yet.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the id is not a catalog item in this
            tenant (a publishable Project is read through the versions route instead).
    """
    item_id = _require_uuid("item_id", item_id)
    tenant_id = auth_data["tenant_id"]
    if not db.get_catalog_item_by_id(item_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Catalog item not found: {item_id}")
    version_id = db.get_latest_revision_id_for_project(item_id, tenant_id)
    if not version_id:
        return ArazzoWorkflowsResponse(version_id=None, project_id=item_id)
    return _workflows_for_version(tenant_id, version_id, item_id)


@router.get("/{tenant_slug}/operations/{path_operation_id}")
async def get_workflow_step_operation(
    tenant_slug: str,
    path_operation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoOperationDetailOut:
    """
    Read the operation an Arazzo step calls, for the step drawer.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        path_operation_id: The ``path_operation.id`` a step resolved to.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The operation's method, route, summary, owning project and revision, parameters and
        declared responses.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the operation is not in this tenant.
    """
    path_operation_id = _require_uuid("path_operation_id", path_operation_id)
    detail = db.get_arazzo_operation_detail(
        tenant_id=auth_data["tenant_id"], path_operation_id=path_operation_id
    )
    if not detail:
        raise HTTPException(
            status_code=404, detail=f"Operation not found: {path_operation_id}"
        )
    return ArazzoOperationDetailOut(**detail)
