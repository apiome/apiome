"""Deploy-gating status endpoints — CTG-4.5 (#4502).

One question, one call:

```
GET /v1/projects/{tenant_slug}/{project_ref}/gate
```

and six more that decide where the bar sits — three at project scope, three at tenant scope.

**The verdict is in the body, never in the status.** A gate that answered ``409`` on a failing
build would make every pipeline's error handling ambiguous: a network problem and a breaking change
would look the same. The endpoint returns ``200`` with ``status: "fail"``, and the pipeline decides
what to do about it — the same contract the CLX-4.2 lint gate uses.

**Permissions reuse what this surface already has, and no new RBAC resource is added.** Reading a
gate is reading the status of a published version, so it needs ``versions:view`` — which is what a
CI runner's API key resolves to. Moving the bar is the same class of decision as deciding where
verification points, which V211's ``verification_targets`` resource already keeps out of an
Editor's hands; that is the identical argument CTG-4.4 made for schedules, and it saves the four
synchronised edits a new resource costs.

**The consumer signal is permission-gated inside the response.** A caller without
``consumer_contracts:view`` gets that one signal as ``unknown`` rather than a leaked registry — and
rather than a silent ``pass``, which would read as "no consumer is broken".
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .deploy_gate import (
    DeployGatePolicyOut,
    DeployGateReport,
    GateThresholdError,
)
from .deploy_gate_service import DeployGateError, build_project_gate, resolve_project
from .deploy_gate_store import audit_detail, clear_policy, load_policy, save_policy
from .permissions import Action, Resource, enforce_permission, has_permission

logger = logging.getLogger(__name__)

__all__ = ["router", "tenant_router"]

#: Project-scoped surface. Shares the ``/v1/projects`` prefix, and ``main`` registers it *after*
#: ``projects_router``: ``/{tenant}/{project}/gate`` would otherwise also match
#: ``/{tenant}/by-slug/{project_slug}`` for a project whose slug happens to be ``gate``, and a
#: project named that is far likelier than one referenced as ``by-slug``.
router = APIRouter(prefix="/v1/projects", tags=["deploy-gate"])

#: Tenant-scoped policy, beside the other governance policies.
tenant_router = APIRouter(prefix="/v1/tenants", tags=["governance"])

#: Audit actions this module writes.
AUDIT_POLICY_UPDATE = "governance.deploy_gate_policy.update"
AUDIT_POLICY_CLEAR = "governance.deploy_gate_policy.clear"

_POLICY_DESCRIPTION = (
    "Thresholds are **two-rung**: each signal carries a warn threshold and a fail threshold, "
    "either of which may be `null` to disable that rung. Absent keys take their documented "
    "defaults, so a body naming one threshold configures exactly that one.\n\n"
    "The default policy fails on a breaking change and on a broken consumer, and warns on a lint "
    "grade below B or a verification older than a day."
)


class DeployGatePolicyPutRequest(BaseModel):
    """Body for saving a deploy-gate policy.

    Attributes:
        thresholds: The ``ctg.gate-policy.v1`` threshold body.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    thresholds: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-signal warn/fail thresholds. Absent groups and absent keys take their "
            "documented defaults."
        ),
    )


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant context.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _require_project_id(tenant_id: str, project_ref: str) -> str:
    """Resolve a project reference (id or slug) to its id, or refuse.

    Delegates to the service's resolver so the policy routes and the gate agree about what a
    reference names — a policy saved against ``petstore`` must be the one the gate reads.

    Args:
        tenant_id: The caller's tenant.
        project_ref: A project UUID or slug.

    Returns:
        The project's id.

    Raises:
        HTTPException: 404 when nothing in this tenant answers to the reference.
    """
    try:
        return str(resolve_project(tenant_id, project_ref)["id"])
    except DeployGateError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}
        ) from exc


def _threshold_error(exc: GateThresholdError) -> HTTPException:
    """Map a threshold refusal onto ``422`` with every problem listed.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise.
    """
    return HTTPException(
        status_code=422,
        detail={"code": "gate-policy-invalid", "errors": list(exc.errors)},
    )


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    target: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Write one governance audit row (best-effort).

    Audit failures are logged and swallowed: a policy change that succeeded must not be reported
    as a failure because its audit row could not be appended.

    Args:
        tenant_id: The tenant whose policy changed.
        action: The audit action.
        auth_data: The authenticated principal.
        target: The policy id or scope this concerns.
        detail: The payload to record.
    """
    try:
        db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=get_authenticated_user_id(auth_data),
            actor_label=auth_data.get("user_email") or auth_data.get("user_name"),
            target=target,
            source="api",
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - auditing never fails the governed action
        logger.warning("Failed to audit %s for tenant %s", action, tenant_id, exc_info=True)


# -------------------------------------------------------------------------------------------
# The gate
# -------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/{project_ref}/gate",
    response_model=DeployGateReport,
    tags=["deploy-gate"],
    summary="Can I promote this API version?",
    description=(
        "One aggregate verdict for a CD pipeline, composed of the four signals that already "
        "exist elsewhere in the platform:\n\n"
        "* **lint** — the GOV grade stored on the revision (never recomputed here);\n"
        "* **breaking** — the CTG-3.1 classification of the publish against its predecessor;\n"
        "* **consumers** — the CTG-4.2 per-consumer verdicts (\"breaks 2 of 7\");\n"
        "* **verification** — CTG-4.4 freshness, falling back to a manual CTG-4.3 report.\n\n"
        "**Partial inputs are the normal case.** A signal with nothing behind it reports "
        "`not_configured` and is excluded from the verdict rather than failing it; a signal that "
        "exists but could not be read reports `unknown` and is also excluded, counted apart. "
        "`evaluatedSignals` says how many actually took part — branch on that, not on `status`, "
        "if a project with nothing configured must not read as a green light.\n\n"
        "**The status is always 200.** The verdict lives in `status` (`pass` / `warn` / `fail`); "
        "the pipeline owns the exit code.\n\n"
        "By default the gate judges the project's newest **published** revision. Pass "
        "`revisionId` to judge a specific one.\n\n"
        "Requires `versions:view`. The consumer signal additionally needs "
        "`consumer_contracts:view`; without it that one signal reports `unknown`."
    ),
    responses={
        404: {"description": "Project or revision not found in this tenant."},
        400: {"description": "The named revision is not published."},
        409: {"description": "The project has no published revision to gate."},
    },
)
async def get_project_deploy_gate(
    tenant_slug: str,
    project_ref: str,
    revision_id: Optional[str] = Query(
        default=None,
        alias="revisionId",
        description="Judge this published revision instead of the newest one.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGateReport:
    """Compute the aggregate deploy-gate verdict for one project.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes every read).
        project_ref: The project's id or slug.
        revision_id: An explicit published revision, or ``None`` for the newest.
        auth_data: Authenticated principal.

    Returns:
        The verdict and its per-signal breakdown.

    Raises:
        HTTPException: 403 without ``versions:view``; 404/400/409 per
            :class:`~app.deploy_gate_service.DeployGateError`.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        return build_project_gate(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            project_ref=project_ref,
            revision_id=revision_id,
            consumers_permitted=has_permission(
                db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW
            ),
        )
    except DeployGateError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


# -------------------------------------------------------------------------------------------
# Project-scoped policy
# -------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/{project_ref}/gate/policy",
    response_model=DeployGatePolicyOut,
    tags=["deploy-gate"],
    summary="Get the deploy-gate policy in force for a project",
    description=(
        "The thresholds this project's gate is judged under, and where they came from: "
        "`project` (an override saved here), `tenant` (the tenant-wide policy), or `default` "
        "(nothing saved anywhere).\n\n" + _POLICY_DESCRIPTION + "\n\n"
        "Readable by anyone who can read the gate — a verdict nobody can explain is not a gate. "
        "Requires `versions:view`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def get_project_gate_policy(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Return the policy in force for a project.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The resolved policy.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    return load_policy(tenant_id, _require_project_id(tenant_id, project_ref))


@router.put(
    "/{tenant_slug}/{project_ref}/gate/policy",
    response_model=DeployGatePolicyOut,
    tags=["deploy-gate"],
    summary="Set this project's deploy-gate thresholds",
    description=(
        "Save an override for one project, replacing whatever it held. The tenant-wide policy "
        "still governs every project without one.\n\n" + _POLICY_DESCRIPTION + "\n\n"
        "Requires `verification_targets:edit`: moving the bar is the same class of decision as "
        "deciding where verification points. Audited as "
        "`governance.deploy_gate_policy.update`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "The threshold body is not valid."},
    },
)
async def put_project_gate_policy(
    tenant_slug: str,
    project_ref: str,
    body: DeployGatePolicyPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Save a project's threshold override.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        body: The threshold body.
        auth_data: Authenticated principal.

    Returns:
        The stored policy.

    Raises:
        HTTPException: 403 without ``verification_targets:edit``; 404 when the project is
            unknown; 422 when the thresholds are not coherent.
    """
    actor_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_TARGETS, Action.EDIT
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    project_id = _require_project_id(tenant_id, project_ref)
    try:
        saved = save_policy(
            tenant_id, project_id=project_id, body=body.thresholds, actor_id=actor_id
        )
    except GateThresholdError as exc:
        raise _threshold_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_POLICY_UPDATE,
        auth_data=auth_data,
        target=saved.policy_id,
        detail={"projectId": project_id, **audit_detail(saved)},
    )
    return saved


@router.delete(
    "/{tenant_slug}/{project_ref}/gate/policy",
    response_model=DeployGatePolicyOut,
    tags=["deploy-gate"],
    summary="Remove this project's deploy-gate override",
    description=(
        "Drop the project override so the tenant-wide policy (or the documented default) governs "
        "again. Returns the policy that is now in force, so a caller sees what it fell back to "
        "rather than having to ask again.\n\n"
        "Requires `verification_targets:delete`. Audited as "
        "`governance.deploy_gate_policy.clear`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def delete_project_gate_policy(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Remove a project's threshold override.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The policy now in force.

    Raises:
        HTTPException: 403 without ``verification_targets:delete``; 404 when the project is
            unknown.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_TARGETS, Action.DELETE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    project_id = _require_project_id(tenant_id, project_ref)
    removed = clear_policy(tenant_id, project_id=project_id)
    if removed:
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_POLICY_CLEAR,
            auth_data=auth_data,
            target=project_id,
            detail={"projectId": project_id, "scope": "project"},
        )
    return load_policy(tenant_id, project_id)


# -------------------------------------------------------------------------------------------
# Tenant-scoped policy
# -------------------------------------------------------------------------------------------


@tenant_router.get(
    "/{tenant_slug}/governance/deploy-gate-policy",
    response_model=DeployGatePolicyOut,
    summary="Get the tenant's deploy-gate policy",
    description=(
        "The thresholds every project in this tenant is judged under unless it saves its own "
        "override. A tenant that has never saved one gets the documented default with "
        "`source: \"default\"`.\n\n" + _POLICY_DESCRIPTION + "\n\n"
        "Requires `versions:view`."
    ),
)
async def get_tenant_gate_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Return the tenant-wide policy.

    Args:
        tenant_slug: Tenant in the URL.
        auth_data: Authenticated principal.

    Returns:
        The tenant-wide policy, or the documented default.

    Raises:
        HTTPException: 403 without ``versions:view``.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _ = tenant_slug
    return load_policy(_tenant_id(auth_data))


@tenant_router.put(
    "/{tenant_slug}/governance/deploy-gate-policy",
    response_model=DeployGatePolicyOut,
    summary="Set the tenant's deploy-gate thresholds",
    description=(
        "Save the tenant-wide policy, replacing whatever it held. Project overrides are left "
        "alone: they were configured deliberately, and a tenant-wide edit that silently reset "
        "them would move bars nobody asked to move.\n\n" + _POLICY_DESCRIPTION + "\n\n"
        "Requires `verification_targets:edit`. Audited as "
        "`governance.deploy_gate_policy.update`."
    ),
    responses={422: {"description": "The threshold body is not valid."}},
)
async def put_tenant_gate_policy(
    tenant_slug: str,
    body: DeployGatePolicyPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Save the tenant-wide thresholds.

    Args:
        tenant_slug: Tenant in the URL.
        body: The threshold body.
        auth_data: Authenticated principal.

    Returns:
        The stored policy.

    Raises:
        HTTPException: 403 without ``verification_targets:edit``; 422 when the thresholds are
            not coherent.
    """
    actor_id = enforce_permission(
        db, auth_data, Resource.VERIFICATION_TARGETS, Action.EDIT
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        saved = save_policy(tenant_id, project_id=None, body=body.thresholds, actor_id=actor_id)
    except GateThresholdError as exc:
        raise _threshold_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_POLICY_UPDATE,
        auth_data=auth_data,
        target=saved.policy_id,
        detail={"projectId": None, **audit_detail(saved)},
    )
    return saved


@tenant_router.delete(
    "/{tenant_slug}/governance/deploy-gate-policy",
    response_model=DeployGatePolicyOut,
    summary="Remove the tenant's deploy-gate policy",
    description=(
        "Drop the tenant-wide policy so the documented default governs again. Project overrides "
        "are not cascaded away.\n\n"
        "Requires `verification_targets:delete`. Audited as "
        "`governance.deploy_gate_policy.clear`."
    ),
)
async def delete_tenant_gate_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeployGatePolicyOut:
    """Remove the tenant-wide policy.

    Args:
        tenant_slug: Tenant in the URL.
        auth_data: Authenticated principal.

    Returns:
        The policy now in force (the documented default).

    Raises:
        HTTPException: 403 without ``verification_targets:delete``.
    """
    enforce_permission(db, auth_data, Resource.VERIFICATION_TARGETS, Action.DELETE)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    if clear_policy(tenant_id, project_id=None):
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_POLICY_CLEAR,
            auth_data=auth_data,
            target=tenant_id,
            detail={"projectId": None, "scope": "tenant"},
        )
    return load_policy(tenant_id)
