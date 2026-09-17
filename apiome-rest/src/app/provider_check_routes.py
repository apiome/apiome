"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/…/checks`` — GNC-2.2 (#4738).

The HTTP surface of the provider status adapter: record a normalized verdict about a bound draft's
commit, read what has been recorded, and see every attempt to put it on the provider. The rules are
:mod:`app.provider_check_store`; the vocabulary is :mod:`app.provider_checks`; the one call that
reaches a provider is :mod:`app.provider_status_adapter`.

**Authorization.** There is no check RBAC resource, and the same two rules the binding surface uses
apply, for the same reasons:

* Recording a verdict changes what a reviewer sees on a pull request, which is a version's
  workflow, so it requires ``versions:edit``; reads require ``projects:view``.
* A verdict can only be recorded against a version's **active binding whose repository
  registration is intact** — GNC-2.1 wrote that binding only after proving a read of the repository
  through a stored credential, and that same registration is the credential the verdict is
  published with.

**No credential crosses this boundary, in either direction.** No request body accepts a token, and
no response model has a field one could occupy: :class:`app.provider_checks.CheckRunRecord` and
:class:`app.provider_checks.CheckDeliveryRecord` both forbid extras, so a column that later grew a
secret would raise here rather than leak. A provider's own refusal is stored redacted, because a
provider's error body is outside our control.

**Audit.** Every recorded verdict is a ``check.recorded`` row and every publish attempt a
``check.published`` row in ``workflow_audit``, written in the same transaction as the change, and
readable through ``GET /v1/tenants/{tenant_slug}/workflow-audit?version_id=…``.

**Provider deliveries.** A push to a bound ref seeds its pending check through the existing
repository webhook endpoint (:mod:`app.repository_webhook_dispatch`), not through anything here.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import provider_check_store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .provider_check_store import CheckFilters
from .provider_checks import (
    CHECK_STATES,
    CODE_BINDING_NOT_FOUND,
    CODE_BINDING_RELEASED,
    CODE_CHECK_NOT_FOUND,
    CODE_COMMIT_UNKNOWN,
    CODE_INVALID_COMMIT,
    CODE_INVALID_DETAILS_URL,
    CODE_INVALID_NAME,
    CODE_PROJECT_NOT_FOUND,
    CODE_PROVIDER_FORBIDDEN,
    CODE_PROVIDER_REFUSED,
    CODE_PROVIDER_UNAVAILABLE,
    CODE_PROVIDER_UNSUPPORTED,
    CODE_VERSION_NOT_FOUND,
    CheckRunDetail,
    CheckRunRecord,
    CheckRunUpsert,
    ProviderCheckValidationError,
)
from .provider_status_adapter import supported_providers

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["provider-checks"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_CHECK_NOT_FOUND: 404,
    CODE_BINDING_NOT_FOUND: 404,
    CODE_BINDING_RELEASED: 409,
    CODE_COMMIT_UNKNOWN: 409,
    CODE_INVALID_NAME: 422,
    CODE_INVALID_COMMIT: 422,
    CODE_INVALID_DETAILS_URL: 422,
    CODE_PROVIDER_UNSUPPORTED: 422,
    CODE_PROVIDER_FORBIDDEN: 403,
    CODE_PROVIDER_REFUSED: 502,
    CODE_PROVIDER_UNAVAILABLE: 502,
}

_PROJECT_BASE = "/{tenant_slug}/projects/{project_ref}"
_VERSION_BASE = f"{_PROJECT_BASE}/versions/{{version_ref}}/binding/checks"


class CheckListResponse(BaseModel):
    """A page of a project's check runs."""

    model_config = ConfigDict(extra="forbid")

    checks: List[CheckRunRecord] = Field(
        default_factory=list, description="Check runs, newest first."
    )
    count: int = Field(description="How many check runs this page holds.")
    limit: int = Field(description="The page size used.")
    offset: int = Field(description="The offset used.")
    providers: List[str] = Field(
        default_factory=list,
        description="Providers a verdict can be published to through the status adapter.",
    )


def _caller(auth_data: Dict[str, Any], resource: str, action: str) -> Tuple[str, str]:
    """Require a permission and return ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.
        resource: The RBAC resource.
        action: The RBAC action.

    Returns:
        The tenant and the acting user.

    Raises:
        HTTPException: 403 without the permission, without an attributable user, or without a
            tenant.
    """
    user_id = enforce_permission(db, auth_data, resource, action)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    if not user_id:
        raise HTTPException(
            status_code=403, detail="An authenticated user id is required to record a check."
        )
    return str(tenant_id), str(user_id)


def _http_error(exc: ProviderCheckValidationError) -> HTTPException:
    """Translate a store refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise, always carrying ``{"code", "message"}``.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


@router.get(
    f"{_PROJECT_BASE}/checks",
    response_model=CheckListResponse,
    summary="List a project's provider check runs",
    description=(
        "A page of the project's normalized check verdicts, newest first. Each is one of "
        "`pending`, `pass`, `fail` or `skipped` about one commit of one bound draft.\n\n"
        "Filters combine: `version` (revision id or version label), `commit_sha`, and `state`.\n\n"
        "No repository credential appears anywhere in the response.\n\n"
        "Requires `projects:view`."
    ),
)
async def list_checks(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label."),
    commit_sha: Optional[str] = Query(default=None, description="Only checks about this commit."),
    state: Optional[str] = Query(
        default=None, description=f"Only checks in this state: {', '.join(CHECK_STATES)}."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Check runs to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckListResponse:
    """List a project's check runs.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version: Only this version's checks.
        commit_sha: Only checks about this commit.
        state: Only checks in this normalized state.
        limit: Page size.
        offset: Check runs to skip.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 404 for an unknown project or version, 422 for an unknown state, 403
            without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    if state is not None and state not in CHECK_STATES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "check-invalid-state",
                "message": f"state must be one of {', '.join(CHECK_STATES)}.",
            },
        )
    filters = CheckFilters(
        version=version, commit_sha=commit_sha, state=state, limit=limit, offset=offset
    )
    try:
        checks, _version_id = provider_check_store.list_checks(tenant_id, project_ref, filters)
    except ProviderCheckValidationError as exc:
        raise _http_error(exc) from exc
    return CheckListResponse(
        checks=checks,
        count=len(checks),
        limit=limit,
        offset=offset,
        providers=list(supported_providers()),
    )


@router.get(
    f"{_PROJECT_BASE}/checks/{{check_id}}",
    response_model=CheckRunDetail,
    summary="Read one check run",
    description=(
        "One normalized verdict with every attempt to publish it to the provider: what state was "
        "sent, whether it was `dispatched`, `suppressed` or `failed`, the provider's status code, "
        "and its refusal — redacted, because a provider's error body is outside our control.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_check(
    tenant_slug: str,
    project_ref: str,
    check_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckRunDetail:
    """Read one check run.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        check_id: The check run.
        auth_data: The authenticated principal.

    Returns:
        The check detail.

    Raises:
        HTTPException: 404 for an unknown project or check, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return provider_check_store.get_check(tenant_id, project_ref, check_id)
    except ProviderCheckValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    _VERSION_BASE,
    response_model=CheckListResponse,
    summary="List a version's provider check runs",
    description=(
        "The checks recorded against this version's binding, newest first.\n\n"
        "Requires `projects:view`."
    ),
)
async def list_version_checks(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    commit_sha: Optional[str] = Query(default=None, description="Only checks about this commit."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Check runs to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckListResponse:
    """List one version's check runs.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        commit_sha: Only checks about this commit.
        limit: Page size.
        offset: Check runs to skip.
        auth_data: The authenticated principal.

    Returns:
        The page.

    Raises:
        HTTPException: 404 for an unknown project or version, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    filters = CheckFilters(
        version=version_ref, commit_sha=commit_sha, limit=limit, offset=offset
    )
    try:
        checks, _version_id = provider_check_store.list_checks(tenant_id, project_ref, filters)
    except ProviderCheckValidationError as exc:
        raise _http_error(exc) from exc
    return CheckListResponse(
        checks=checks,
        count=len(checks),
        limit=limit,
        offset=offset,
        providers=list(supported_providers()),
    )


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


@router.post(
    _VERSION_BASE,
    response_model=CheckRunDetail,
    status_code=201,
    summary="Record a check verdict against a version's binding",
    description=(
        "Record one normalized verdict — `pending`, `pass`, `fail` or `skipped` — about a commit "
        "of the ref this draft is bound to, and publish it to the provider.\n\n"
        "**Idempotent.** `(binding, commit, name)` identifies the check, so the same call twice "
        "is one verdict a reviewer reads, not two they have to reconcile. Pass `rerun: true` to "
        "say this is a fresh run of the same check, which advances its attempt counter.\n\n"
        "`commit_sha` defaults to the commit the binding is synchronized with. `publish: false` "
        "records the verdict without sending it, which is useful while a check suite is being "
        "developed against a real repository — the attempt is still ledgered, as `suppressed`.\n\n"
        "**Recording never fails because publishing did.** A provider that refuses the write "
        "leaves a `failed` row on the check's publish ledger and a `201` here: a verdict that was "
        "recorded and not published is evidence, and losing it would be worse than not showing "
        "it. Read the check back to see what the provider did.\n\n"
        "The repository token is resolved server-side from the registration the binding was "
        "authorized through; a credential is never accepted in the body.\n\n"
        "Requires `versions:edit`."
    ),
)
async def record_check(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    body: CheckRunUpsert,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CheckRunDetail:
    """Record a check verdict.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        body: The verdict.
        auth_data: The authenticated principal.

    Returns:
        The check detail, including the publish attempt this call made.

    Raises:
        HTTPException: 404 for an unknown project, version or unbound draft, 409 when the binding
            was released, 422 for an invalid check name, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        # The publish reaches a provider over the network, so it runs on a worker thread rather
        # than holding the event loop for the length of somebody else's API call.
        return await asyncio.to_thread(
            provider_check_store.record_check,
            tenant_id,
            user_id,
            project_ref,
            version_ref,
            body,
        )
    except ProviderCheckValidationError as exc:
        raise _http_error(exc) from exc
