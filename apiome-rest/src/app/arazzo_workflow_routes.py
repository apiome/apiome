"""
Arazzo workflow records — read API (COA-1.3, #7039; COA-1.5, #7041).

GET /v1/workflows/{tenant_slug}/versions/{version_id}
GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}
GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps
GET /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps/{step_id}
GET /v1/workflows/{tenant_slug}/catalog/{item_id}
GET /v1/workflows/{tenant_slug}/catalog/{item_id}/revisions/{version_id}
GET /v1/workflows/{tenant_slug}/operations/{path_operation_id}
POST /v1/workflows/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/run

The version and catalog reads return the workflows REPO-3.4 (#2773) persisted for a revision — a
catalog item's bare read follows its latest revision, the ``revisions`` read names one — with
each step's ``operationRef`` / ``operationId`` resolution state, the operation it resolved to,
and each workflow's source-description status. The nested ``workflows/{workflow_id}`` reads
narrow that payload to one workflow (by Arazzo ``workflowId``), its steps, or one step (by
``stepId``). The operations read serves the viewer's step drawer. All are tenant-scoped reads,
like the paths reads the viewer links into.

The ``run`` route (COA-1.7, #7043) executes one workflow end to end against an ECA-1.2
verification target — a deployment or a ``mock`` target — and returns a per-step report; it
needs ``versions:view`` and ``verification_evidence:create``, because every run is recorded.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Response

from .arazzo_workflow_run_service import (
    ArazzoWorkflowRunRequest,
    ArazzoWorkflowRunResponse,
    WorkflowNotFoundError,
    run_workflow_against_target,
)
from .arazzo_workflow_view import build_source_views, build_workflow_views
from .auth import validate_authentication
from .database import db
from .models import (
    ArazzoOperationDetailOut,
    ArazzoWorkflowDetailResponse,
    ArazzoWorkflowOut,
    ArazzoWorkflowsResponse,
    ArazzoWorkflowStepOut,
    ArazzoWorkflowStepsResponse,
)
from .permissions import Action, Resource, enforce_permission
from .verification_evidence import EvidenceValidationError
from .verification_evidence_store import actor_from_auth
from .verification_target import CODE_NOT_FOUND, TargetValidationError

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


def _version_workflows_or_404(tenant_id: str, raw_version_id: str) -> ArazzoWorkflowsResponse:
    """Validate a revision id, check it is in the tenant, and read its workflows.

    Args:
        tenant_id: Owning tenant UUID.
        raw_version_id: The ``version_id`` path parameter as received.

    Returns:
        The revision's viewer payload.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant.
    """
    version_id = _require_uuid("version_id", raw_version_id)
    version = db.get_version_for_tenant(tenant_id, version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")
    return _workflows_for_version(tenant_id, version_id, str(version["project_id"]))


def _find_workflow(payload: ArazzoWorkflowsResponse, workflow_id: str) -> ArazzoWorkflowOut:
    """Return the workflow whose Arazzo ``workflowId`` is ``workflow_id``, or raise 404.

    Args:
        payload: A revision's workflows.
        workflow_id: The ``workflowId`` to find (exact, case-sensitive, as Arazzo compares it).

    Returns:
        The matching workflow.

    Raises:
        HTTPException: 404 when the revision has no such workflow.
    """
    for workflow in payload.workflows:
        if workflow.workflow_id == workflow_id:
            return workflow
    raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}")


@router.get("/{tenant_slug}/versions/{version_id}")
def list_version_workflows(
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
    return _version_workflows_or_404(auth_data["tenant_id"], version_id)


@router.get("/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}")
def get_version_workflow(
    tenant_slug: str,
    version_id: str,
    workflow_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowDetailResponse:
    """
    Read one persisted Arazzo workflow of a revision.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        version_id: The revision (``versions.id``) UUID.
        workflow_id: The workflow's Arazzo ``workflowId``.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The workflow with its ordered steps and their resolution state, plus every source the
        document declares.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant or
            has no such workflow.
    """
    payload = _version_workflows_or_404(auth_data["tenant_id"], version_id)
    return ArazzoWorkflowDetailResponse(
        version_id=str(payload.version_id),
        project_id=str(payload.project_id),
        sources=payload.sources,
        workflow=_find_workflow(payload, workflow_id),
    )


@router.get("/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps")
def list_version_workflow_steps(
    tenant_slug: str,
    version_id: str,
    workflow_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowStepsResponse:
    """
    List the steps of one persisted Arazzo workflow, in source order.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        version_id: The revision (``versions.id``) UUID.
        workflow_id: The workflow's Arazzo ``workflowId``.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The ordered steps, each with its ``operationRef`` / ``operationId``, resolution state and
        resolved operation, and the steps counted by resolution state.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant or
            has no such workflow.
    """
    payload = _version_workflows_or_404(auth_data["tenant_id"], version_id)
    workflow = _find_workflow(payload, workflow_id)
    return ArazzoWorkflowStepsResponse(
        version_id=str(payload.version_id),
        workflow_id=workflow.workflow_id,
        step_resolution=workflow.step_resolution,
        steps=workflow.steps,
    )


@router.get("/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/steps/{step_id}")
def get_version_workflow_step(
    tenant_slug: str,
    version_id: str,
    workflow_id: str,
    step_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowStepOut:
    """
    Read one step of a persisted Arazzo workflow.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        version_id: The revision (``versions.id``) UUID.
        workflow_id: The workflow's Arazzo ``workflowId``.
        step_id: The step's Arazzo ``stepId``.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The step with its target, resolution state, resolved operation and actions.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the revision is not in this tenant, or
            has no such workflow or step.
    """
    payload = _version_workflows_or_404(auth_data["tenant_id"], version_id)
    for step in _find_workflow(payload, workflow_id).steps:
        if step.step_id == step_id:
            return step
    raise HTTPException(status_code=404, detail=f"Step not found: {step_id}")


@router.get("/{tenant_slug}/catalog/{item_id}")
def list_catalog_item_workflows(
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


@router.get("/{tenant_slug}/catalog/{item_id}/revisions/{version_id}")
def list_catalog_revision_workflows(
    tenant_slug: str,
    item_id: str,
    version_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowsResponse:
    """
    List the Arazzo workflows of one revision of a catalog item.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        item_id: The catalog item UUID.
        version_id: The revision (``versions.id``) UUID; it must belong to ``item_id``.
        auth_data: Authentication data (injected by dependency).

    Returns:
        That revision's workflows, shaped like the latest-revision read.

    Raises:
        HTTPException: 400 for a malformed id; 404 when the id is not a catalog item in this
            tenant, or the revision is not one of its revisions.
    """
    item_id = _require_uuid("item_id", item_id)
    version_id = _require_uuid("version_id", version_id)
    tenant_id = auth_data["tenant_id"]
    if not db.get_catalog_item_by_id(item_id, tenant_id):
        raise HTTPException(status_code=404, detail=f"Catalog item not found: {item_id}")
    version = db.get_version_for_tenant(tenant_id, version_id)
    if not version or str(version["project_id"]) != item_id:
        raise HTTPException(
            status_code=404,
            detail=f"Revision {version_id} not found for catalog item {item_id}",
        )
    return _workflows_for_version(tenant_id, version_id, item_id)


@router.get("/{tenant_slug}/operations/{path_operation_id}")
def get_workflow_step_operation(
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


@router.post(
    "/{tenant_slug}/versions/{version_id}/workflows/{workflow_id}/run",
    response_model=ArazzoWorkflowRunResponse,
    summary="Run an Arazzo workflow against a verification target",
    description=(
        "Execute one stored workflow end to end against an ECA-1.2 verification target (a "
        "deployment, or a `mock` environment target): steps run in order, each request built "
        "from the workflow `inputs` and earlier steps' `outputs` through runtime expressions; "
        "each step's `successCriteria` are judged as assertions with expected-vs-actual values; "
        "`onSuccess` / `onFailure` `end`, `goto` and `retry` actions are followed.\n\n"
        "**Safe by default (CTG-4.3).** A step that sends `POST`/`PUT`/`PATCH`/`DELETE` runs only "
        "when the target policy allows mutating methods, `verification.allow_mutating` is set "
        "**and** a fixture names the step's operation (or the step, by `case_id`). Otherwise the "
        "run is refused before anything is sent: **200** with `ok: false` and every reason in "
        "`refusals` (also used for unresolved steps, nested-workflow steps and inputs that fail "
        "the workflow's `inputs` schema).\n\n"
        "An executed run is recorded as immutable ECA-1.3 evidence (**201**; **200** on an "
        "idempotent replay) whatever its outcome. 404 when the revision or workflow is unknown; "
        "target faults are 400/404; evidence faults are 400."
    ),
)
def run_version_workflow(
    tenant_slug: str,
    version_id: str,
    workflow_id: str,
    body: ArazzoWorkflowRunRequest,
    response: Response,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ArazzoWorkflowRunResponse:
    """
    Run a persisted Arazzo workflow against a verification target.

    Args:
        tenant_slug: The tenant slug (the authenticated tenant scopes the work).
        version_id: The revision (``versions.id``) UUID holding the workflow.
        workflow_id: The workflow's Arazzo ``workflowId``.
        body: Target, inputs, mutation opt-in and fixtures, CI context.
        response: FastAPI response — 201 when new evidence was written.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The run response: the per-step report and evidence when ``ok``, the refusals otherwise.

    Raises:
        HTTPException: 403 without permission; 400 for a malformed id or a target/evidence fault;
            404 for an unknown revision, workflow or target.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    enforce_permission(db, auth_data, Resource.VERIFICATION_EVIDENCE, Action.CREATE)
    tenant_id = auth_data["tenant_id"]
    version_id = _require_uuid("version_id", version_id)
    if not db.get_version_for_tenant(tenant_id, version_id):
        raise HTTPException(status_code=404, detail=f"Version not found: {version_id}")
    try:
        result = run_workflow_against_target(
            version_id, workflow_id, body, tenant_id=tenant_id, actor=actor_from_auth(auth_data)
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TargetValidationError as exc:
        raise HTTPException(
            status_code=404 if exc.code == CODE_NOT_FOUND else 400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except EvidenceValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"code": exc.code, "message": str(exc)}
        ) from exc
    if result.ok and result.created is True:
        response.status_code = 201
    return result
