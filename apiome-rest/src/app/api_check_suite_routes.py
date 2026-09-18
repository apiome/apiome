"""``/v1/tenants/{tenant_slug}/…/check-suite`` — the API change check suite, GNC-3.1 (#4740).

One verdict about an API change, aggregated from the evidence the platform already produces —
governance lint, CTG breaking and consumer analysis, ECA contract runs, the SDK kit manifest — and,
for a draft bound to a repository ref, reported on the pull request through GNC-2.2's status
adapter. The rules are :mod:`app.api_check_suite`; the evidence :mod:`app.api_check_suite_evidence`;
the orchestration :mod:`app.api_check_suite_store`; the publish gate
:mod:`app.api_check_suite_gate`.

**Authorization.** No new RBAC resource:

* Running the suite records a verdict a reviewer sees on a pull request — a version's workflow, as
  GNC-2.2 decided — so it requires ``versions:edit``. Reads require ``projects:view``.
* The consumers component names registered consumers. A caller without
  ``consumer_contracts:view`` gets the verdict unchanged and the names redacted — the CTG-4.5
  gate's rule, applied to a reader rather than to the verdict, which never depends on who asked.
* A suite policy can block publishing, so it is a governance setting: changing it requires a
  signed-in tenant administrator (an API key cannot), exactly as the COL-2.3 approval policy.

**CI keys.** Reading the latest evaluation is allowlisted for both CTG-2.3 CI read scopes
(``diff:read`` / ``lint:read``) — the CTG-4.5 gate's reasoning: the aggregate is composed of a lint
grade and a diff classification. Running the suite writes, so it needs a full-access key.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from . import api_check_suite_store
from .api_check_suite import (
    CODE_COMMIT_UNKNOWN,
    CODE_INVALID_COMMIT,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOT_RUN,
    CODE_POLICY_INVALID,
    CODE_PROJECT_NOT_FOUND,
    CODE_RUN_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    CheckSuiteError,
    CheckSuitePolicyError,
    CheckSuitePolicyOut,
    CheckSuiteRunDetail,
    CheckSuiteRunList,
    CheckSuiteRunRequest,
)
from .api_check_suite_policy_store import audit_detail, clear_policy, load_policy, save_policy
from .auth import get_authenticated_user_id, require_tenant_admin_session, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission, has_permission

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["api-check-suite"])

#: Audit actions this module writes (``access_audit``, beside every other governance edit).
AUDIT_POLICY_UPDATE = "governance.check_suite_policy.update"
AUDIT_POLICY_CLEAR = "governance.check_suite_policy.clear"

#: A refusal maps onto the HTTP status of its kind.
_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_RUN_NOT_FOUND: 404,
    CODE_NOT_RUN: 404,
    CODE_NOT_BOUND: 409,
    CODE_COMMIT_UNKNOWN: 409,
    CODE_INVALID_COMMIT: 422,
    CODE_INVALID_DOCUMENT: 422,
}

_PROJECT_BASE = "/{tenant_slug}/projects/{project_ref}"
_VERSION_BASE = f"{_PROJECT_BASE}/versions/{{version_ref}}/check-suite"

_POLICY_DESCRIPTION = (
    "Each component — `lint`, `breaking`, `consumers`, `contract`, `sdk` — is `required` (it "
    "decides the verdict), `advisory` (evaluated and reported, never deciding) or `off` (not "
    "evaluated). Absent components take their documented defaults: lint, breaking and consumers "
    "required; contract and sdk advisory.\n\n"
    "`requiredForPublish: true` refuses to publish a version whose current content has no "
    "passing (or skipped) evaluation under the policy in force; force-publish with a reason "
    "stays the escape, and is audited."
)


class CheckSuitePolicyPutRequest(BaseModel):
    """Body for saving a suite policy — the ``gnc.check-suite-policy.v1`` document."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    components: Dict[str, str] = Field(
        default_factory=dict,
        description="component → `required` | `advisory` | `off`; absent components take defaults.",
    )
    required_for_publish: bool = Field(
        default=False,
        alias="requiredForPublish",
        description="Require a passing suite evaluation of the current content to publish.",
    )


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _caller(auth_data: Dict[str, Any], resource: str, action: str) -> Tuple[str, str]:
    """Require a permission and return ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.
        resource: The RBAC resource.
        action: The RBAC action.

    Returns:
        The tenant and the acting user.

    Raises:
        HTTPException: 403 without the permission, a user, or a tenant.
    """
    user_id = enforce_permission(db, auth_data, resource, action)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id), str(user_id)


def _consumers_visible(auth_data: Dict[str, Any]) -> bool:
    """Whether the caller may read consumer contracts — never raises.

    Args:
        auth_data: The authenticated principal.

    Returns:
        True when the caller holds ``consumer_contracts:view``.
    """
    try:
        return bool(has_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW))
    except Exception:  # noqa: BLE001 - an unreadable grant hides the names; it never fails a read
        return False


def _http_error(exc: CheckSuiteError) -> HTTPException:
    """Translate a suite refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException``, always carrying ``{"code", "message"}``.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


def _policy_error(exc: CheckSuitePolicyError) -> HTTPException:
    """Translate an invalid policy body into a 422 listing every problem.

    Args:
        exc: The validation failure.

    Returns:
        The ``HTTPException``.
    """
    return HTTPException(
        status_code=422, detail={"code": CODE_POLICY_INVALID, "errors": list(exc.errors)}
    )


def _policy_body(body: CheckSuitePolicyPutRequest) -> Dict[str, Any]:
    """The policy document a PUT body describes.

    Args:
        body: The request.

    Returns:
        The ``gnc.check-suite-policy.v1`` body for :func:`app.api_check_suite.policy_from_body`.
    """
    return {"components": dict(body.components), "requiredForPublish": body.required_for_publish}


def _project_id(tenant_id: str, project_ref: str) -> str:
    """Resolve a project reference to its id through the suite's own resolver.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.

    Returns:
        The project id.

    Raises:
        HTTPException: 404 when nothing matches.
    """
    try:
        return str(api_check_suite_store.resolve_project(tenant_id, project_ref)["id"])
    except CheckSuiteError as exc:
        raise _http_error(exc) from exc


def _audit(
    *,
    tenant_id: str,
    action: str,
    auth_data: Dict[str, Any],
    target: Optional[str],
    detail: Dict[str, Any],
) -> None:
    """Write one governance audit row — best-effort.

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


# ---------------------------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------------------------


@router.post(
    _VERSION_BASE,
    response_model=CheckSuiteRunDetail,
    status_code=201,
    summary="Run the API change check suite for a version",
    description=(
        "Aggregate the evidence the platform already has about this version into **one** "
        "verdict — `pending`, `pass`, `fail` or `skipped` — and, when the version is bound to a "
        "repository ref, report it on the pull request as the `apiome/api-change` check.\n\n"
        "Five components, each a reading of existing evidence: **lint** (the stored GOV lint "
        "report), **breaking** and **consumers** (the CTG classification against the previous "
        "published revision, judged by the CTG-4.5 deploy gate's own rules and thresholds), "
        "**contract** (the newest ECA contract run of this revision, if its suite is still this "
        "draft's) and **sdk** (the SDK client-kit manifest). Only the components the suite "
        "policy marks `required` decide the verdict.\n\n"
        "**Idempotent.** An evaluation is keyed by everything it is a function of — the draft's "
        "content digest, the commit, both policies and every component's evidence. Re-running "
        "over unchanged inputs returns that evaluation (`200`, `replayed: true`) with the same "
        "evidence ids, and the provider is not called again for a publish it already has. New "
        "inputs are a new evaluation (`201`).\n\n"
        "`commit_sha` defaults to the commit the binding is synchronized with. A newer commit "
        "on the branch gets `skipped` (`spec-unchanged`) when it does not touch the bound "
        "specification, otherwise `pending` (`draft-not-synchronized`) until the draft catches "
        "up. A commit the binding has never been observed at is `409 check-suite-commit-unknown`.\n\n"
        "Requires `versions:edit`."
    ),
    responses={200: {"description": "These inputs were already evaluated; that evaluation."}},
)
async def run_check_suite(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    response: Response,
    body: CheckSuiteRunRequest = Body(default_factory=CheckSuiteRunRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuiteRunDetail:
    """Run the suite.

    Args:
        tenant_slug: The tenant in the URL (validated by authentication).
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        response: The response, whose status a replay sets to ``200``.
        body: The commit, pull request and publish choice.
        auth_data: The authenticated principal.

    Returns:
        The evaluation, and the provider check it became.

    Raises:
        HTTPException: 404 for an unknown project or version, 409 for a commit on an unbound
            version or an unknown commit, 422 for an invalid commit or an unbuildable draft, 403
            without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    try:
        detail = await api_check_suite_store.run_suite(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            user_id=user_id,
            project_ref=project_ref,
            version_ref=version_ref,
            request=body,
            consumers_visible=_consumers_visible(auth_data),
        )
    except CheckSuiteError as exc:
        raise _http_error(exc) from exc
    if detail.replayed:
        response.status_code = 200
    return detail


@router.get(
    _VERSION_BASE,
    response_model=CheckSuiteRunDetail,
    summary="Read the latest API change check suite evaluation of a version",
    description=(
        "The newest evaluation (at `commit_sha`, when given), with `stale: true` when the "
        "draft's content or either policy has moved since — the evaluation then no longer "
        "answers for the version as it is now — and the provider check it became.\n\n"
        "Requires `projects:view`; readable by a CI key holding `diff:read` or `lint:read`."
    ),
)
async def read_check_suite(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    commit_sha: Optional[str] = Query(default=None, description="Only evaluations at this commit."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuiteRunDetail:
    """Read the latest evaluation.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        commit_sha: Only evaluations at this commit.
        auth_data: The authenticated principal.

    Returns:
        The evaluation.

    Raises:
        HTTPException: 404 for an unknown project or version or when the suite has not run.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    try:
        return api_check_suite_store.latest_run(
            tenant_id,
            tenant_slug,
            project_ref,
            version_ref,
            commit_sha=commit_sha,
            consumers_visible=_consumers_visible(auth_data),
        )
    except CheckSuiteError as exc:
        raise _http_error(exc) from exc


@router.get(
    f"{_VERSION_BASE}/runs",
    response_model=CheckSuiteRunList,
    summary="List a version's API change check suite evaluations",
    description="Every evaluation of the version, newest first.\n\nRequires `projects:view`.",
)
async def list_check_suite_runs(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    commit_sha: Optional[str] = Query(default=None, description="Only evaluations at this commit."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Evaluations to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuiteRunList:
    """List a version's evaluations.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        commit_sha: Only evaluations at this commit.
        limit: Page size.
        offset: Evaluations to skip.
        auth_data: The authenticated principal.

    Returns:
        The page.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    try:
        return api_check_suite_store.list_runs(
            tenant_id,
            tenant_slug,
            project_ref,
            version_ref,
            commit_sha=commit_sha,
            limit=limit,
            offset=offset,
            consumers_visible=_consumers_visible(auth_data),
        )
    except CheckSuiteError as exc:
        raise _http_error(exc) from exc


@router.get(
    f"{_PROJECT_BASE}/check-suite/runs/{{run_id}}",
    response_model=CheckSuiteRunDetail,
    summary="Read one API change check suite evaluation — the drill-down",
    description=(
        "One evaluation: every component with the evidence it read (ids, digests, counts), a "
        "link to that evidence, and the policy it was judged under. This is what a provider "
        "check's summary points at.\n\nRequires `projects:view`."
    ),
)
async def read_check_suite_run(
    tenant_slug: str,
    project_ref: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuiteRunDetail:
    """Read one evaluation.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        run_id: The evaluation.
        auth_data: The authenticated principal.

    Returns:
        The evaluation.

    Raises:
        HTTPException: 404 when it is not this project's.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    try:
        return api_check_suite_store.get_run(
            tenant_id,
            tenant_slug,
            project_ref,
            run_id,
            consumers_visible=_consumers_visible(auth_data),
        )
    except CheckSuiteError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/governance/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    tags=["governance"],
    summary="Read the tenant's API change check suite policy",
    description=f"{_POLICY_DESCRIPTION}\n\nRequires `projects:view`.",
)
async def get_tenant_check_suite_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Read the tenant-wide policy.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        The policy in force (the documented default when none is saved).
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    return load_policy(tenant_id)


@router.put(
    "/{tenant_slug}/governance/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    tags=["governance"],
    summary="Save the tenant's API change check suite policy",
    description=(
        f"{_POLICY_DESCRIPTION}\n\nRequires a signed-in tenant administrator. Audited as "
        "`governance.check_suite_policy.update`."
    ),
)
async def put_tenant_check_suite_policy(
    tenant_slug: str,
    body: CheckSuitePolicyPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Save the tenant-wide policy.

    Args:
        tenant_slug: The tenant in the URL.
        body: The policy.
        auth_data: The authenticated principal.

    Returns:
        The stored policy.

    Raises:
        HTTPException: 403 unless a signed-in tenant administrator; 422 for an invalid policy.
    """
    tenant_id = require_tenant_admin_session(
        db, auth_data, detail="Only tenant administrators can change the check-suite policy"
    )
    try:
        saved = save_policy(
            tenant_id, body=_policy_body(body), actor_id=get_authenticated_user_id(auth_data)
        )
    except CheckSuitePolicyError as exc:
        raise _policy_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_POLICY_UPDATE,
        auth_data=auth_data,
        target=saved.policy_id,
        detail={"scope": "tenant", **audit_detail(saved)},
    )
    return saved


@router.delete(
    "/{tenant_slug}/governance/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    tags=["governance"],
    summary="Clear the tenant's API change check suite policy",
    description=(
        "Drop the tenant-wide policy so the documented default governs. Project overrides are "
        "left in place. Returns the policy now in force.\n\nRequires a signed-in tenant "
        "administrator. Audited as `governance.check_suite_policy.clear`."
    ),
)
async def delete_tenant_check_suite_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Clear the tenant-wide policy.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        The policy now in force.
    """
    tenant_id = require_tenant_admin_session(
        db, auth_data, detail="Only tenant administrators can change the check-suite policy"
    )
    if clear_policy(tenant_id):
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_POLICY_CLEAR,
            auth_data=auth_data,
            target=None,
            detail={"scope": "tenant"},
        )
    return load_policy(tenant_id)


@router.get(
    f"{_PROJECT_BASE}/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    summary="Read the API change check suite policy in force for a project",
    description=(
        f"{_POLICY_DESCRIPTION}\n\nResolution is project → tenant → documented default, and "
        "`source` says which supplied it.\n\nRequires `projects:view`."
    ),
)
async def get_project_check_suite_policy(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Read the policy in force for a project.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        The policy in force.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    return load_policy(tenant_id, _project_id(tenant_id, project_ref))


@router.put(
    f"{_PROJECT_BASE}/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    summary="Save a project's API change check suite policy override",
    description=(
        f"{_POLICY_DESCRIPTION}\n\nRequires a signed-in tenant administrator. Audited as "
        "`governance.check_suite_policy.update`."
    ),
)
async def put_project_check_suite_policy(
    tenant_slug: str,
    project_ref: str,
    body: CheckSuitePolicyPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Save a project's override.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The policy.
        auth_data: The authenticated principal.

    Returns:
        The stored policy.

    Raises:
        HTTPException: 403 unless a signed-in tenant administrator; 404 for an unknown project;
            422 for an invalid policy.
    """
    tenant_id = require_tenant_admin_session(
        db, auth_data, detail="Only tenant administrators can change the check-suite policy"
    )
    project_id = _project_id(tenant_id, project_ref)
    try:
        saved = save_policy(
            tenant_id,
            project_id=project_id,
            body=_policy_body(body),
            actor_id=get_authenticated_user_id(auth_data),
        )
    except CheckSuitePolicyError as exc:
        raise _policy_error(exc) from exc
    _audit(
        tenant_id=tenant_id,
        action=AUDIT_POLICY_UPDATE,
        auth_data=auth_data,
        target=saved.policy_id,
        detail={"scope": "project", "projectId": project_id, **audit_detail(saved)},
    )
    return saved


@router.delete(
    f"{_PROJECT_BASE}/check-suite-policy",
    response_model=CheckSuitePolicyOut,
    summary="Remove a project's API change check suite policy override",
    description=(
        "Drop the project override so the tenant-wide policy (or the documented default) "
        "governs again. Returns the policy now in force.\n\nRequires a signed-in tenant "
        "administrator. Audited as `governance.check_suite_policy.clear`."
    ),
)
async def delete_project_check_suite_policy(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckSuitePolicyOut:
    """Remove a project's override.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        The policy now in force.
    """
    tenant_id = require_tenant_admin_session(
        db, auth_data, detail="Only tenant administrators can change the check-suite policy"
    )
    project_id = _project_id(tenant_id, project_ref)
    if clear_policy(tenant_id, project_id=project_id):
        _audit(
            tenant_id=tenant_id,
            action=AUDIT_POLICY_CLEAR,
            auth_data=auth_data,
            target=project_id,
            detail={"scope": "project", "projectId": project_id},
        )
    return load_policy(tenant_id, project_id)
