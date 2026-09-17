"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/…/binding`` — GNC-2.1 (#4737).

The HTTP surface of branch-to-draft binding: bind a draft version to a repository ref and source
path, read where a version stands, check whether the ref has moved, settle the sync candidates a
movement raises, and release the binding. The rules are :mod:`app.draft_binding_store`; the
vocabulary is :mod:`app.draft_bindings`.

**Authorization.** There is no binding RBAC resource, and two checks apply to every write:

* A binding changes a version's workflow, so binding, checking, settling, and releasing require
  ``versions:edit``; reads require ``projects:view``.
* Binding, checking and applying additionally **prove repository access**: each resolves a stored
  credential (a registered repository's linked account, or the caller's own) and reads the ref and
  the selection through the provider before anything is written. A credential is never accepted in
  a request body, and a repository that credential cannot reach is answered ``403
  binding-repository-forbidden`` or ``404 binding-repository-not-found``.

**Audit.** Every bind, re-bind, release, sync candidate, and settlement is written to
``workflow_audit`` as a ``binding.*`` action in the same transaction as the change, and is readable
through ``GET /v1/tenants/{tenant_slug}/workflow-audit?version_id=…``.

**Provider deliveries.** A push to a bound ref raises its candidate through the existing repository
webhook endpoint (:mod:`app.repository_webhook_dispatch`), not through anything here.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import draft_binding_store
from .auth import validate_authentication
from .database import db
from .draft_binding_store import BindingFilters
from .draft_bindings import (
    CODE_ALREADY_BOUND,
    CODE_CANDIDATE_NOT_FOUND,
    CODE_CANDIDATE_RESOLVED,
    CODE_CONFLICT,
    CODE_INVALID_SOURCE,
    CODE_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_RELEASED,
    CODE_REPOSITORY_FORBIDDEN,
    CODE_REPOSITORY_NOT_FOUND,
    CODE_REPOSITORY_UNREACHABLE,
    CODE_UNCHANGED,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_PUBLISHED,
    DraftBindingCreate,
    DraftBindingDetail,
    DraftBindingRecord,
    DraftBindingValidationError,
    SyncCandidateResolve,
    VersionBindingStatus,
)
from .permissions import Action, Resource, enforce_permission

__all__ = ["STATUS_BY_CODE", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["draft-bindings"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400. Public because the
#: synchronization surface (GNC-2.3) answers the same repository refusals and must not invent a
#: second opinion about what any of them means.
STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_NOT_FOUND: 404,
    CODE_CANDIDATE_NOT_FOUND: 404,
    CODE_REPOSITORY_NOT_FOUND: 404,
    CODE_REPOSITORY_FORBIDDEN: 403,
    CODE_REPOSITORY_UNREACHABLE: 502,
    CODE_INVALID_SOURCE: 422,
    CODE_VERSION_PUBLISHED: 409,
    CODE_ALREADY_BOUND: 409,
    CODE_CANDIDATE_RESOLVED: 409,
    CODE_UNCHANGED: 409,
    CODE_RELEASED: 409,
    CODE_CONFLICT: 409,
}

_PROJECT_BASE = "/{tenant_slug}/projects/{project_ref}"
_VERSION_BASE = f"{_PROJECT_BASE}/versions/{{version_ref}}/binding"


class BindingListResponse(BaseModel):
    """A page of a project's bindings."""

    model_config = ConfigDict(extra="forbid")

    bindings: List[DraftBindingRecord] = Field(
        default_factory=list, description="Bindings, newest first."
    )
    count: int = Field(description="How many bindings this page holds.")
    total: int = Field(description="How many bindings match the filters in all.")
    limit: int = Field(description="The page size used.")
    offset: int = Field(description="The offset used.")


# ---------------------------------------------------------------------------------------------
# Shared helpers
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
        HTTPException: 403 without the permission, without an attributable user, or without a
            tenant.
    """
    user_id = enforce_permission(db, auth_data, resource, action)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    if not user_id:
        raise HTTPException(
            status_code=403, detail="An authenticated user id is required to bind a repository."
        )
    return str(tenant_id), str(user_id)


def _http_error(exc: DraftBindingValidationError) -> HTTPException:
    """Translate a store refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise, always carrying ``{"code", "message"}``.
    """
    return HTTPException(
        status_code=STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


async def _off_loop(work: Any, *args: Any) -> Any:
    """Run a store call that may reach a provider on a worker thread.

    Binding, checking and applying all issue blocking HTTP calls to the provider through
    :mod:`app.git_intake`; keeping them off the event loop is what stops one slow repository read
    from stalling every other request.

    Args:
        work: The store function.
        *args: Its positional arguments.

    Returns:
        Whatever the store returned.

    Raises:
        HTTPException: The translation of any store refusal.
    """
    try:
        return await asyncio.to_thread(work, *args)
    except DraftBindingValidationError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


@router.get(
    f"{_PROJECT_BASE}/bindings",
    response_model=BindingListResponse,
    summary="List a project's branch-to-draft bindings",
    description=(
        "A page of the project's bindings, newest first — active ones and the released rows that "
        "are their history.\n\n"
        "Filters combine: `version` (revision id or version label) and `active` (`true` for the "
        "live bindings, `false` for released ones).\n\n"
        "Requires `projects:view`."
    ),
)
async def list_bindings(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label."),
    active: Optional[bool] = Query(
        default=None, description="Active (`true`) or released (`false`) bindings only."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Bindings to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> BindingListResponse:
    """List a project's bindings.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version: Only this version's bindings.
        active: Only active or only released bindings.
        limit: Page size.
        offset: Bindings to skip.
        auth_data: The authenticated principal.

    Returns:
        The page and the total.

    Raises:
        HTTPException: 404 for an unknown project or version, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    filters = BindingFilters(version=version, active=active, limit=limit, offset=offset)
    try:
        bindings, total = draft_binding_store.list_bindings(tenant_id, project_ref, filters)
    except DraftBindingValidationError as exc:
        raise _http_error(exc) from exc
    return BindingListResponse(
        bindings=bindings, count=len(bindings), total=total, limit=limit, offset=offset
    )


@router.get(
    f"{_PROJECT_BASE}/bindings/{{binding_id}}",
    response_model=DraftBindingDetail,
    summary="Read one binding",
    description=(
        "A binding with its outstanding sync candidates and the ones already settled.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_binding(
    tenant_slug: str,
    project_ref: str,
    binding_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBindingDetail:
    """Read one binding.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        binding_id: The binding.
        auth_data: The authenticated principal.

    Returns:
        The binding detail.

    Raises:
        HTTPException: 404 for an unknown project or binding, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return draft_binding_store.get_binding(tenant_id, project_ref, binding_id)
    except DraftBindingValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    _VERSION_BASE,
    response_model=VersionBindingStatus,
    summary="Read a version's repository binding",
    description=(
        "Where a version stands: its active binding with everything outstanding on it, and the "
        "bindings it has had before.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_version_binding(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionBindingStatus:
    """Read a version's binding status.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        auth_data: The authenticated principal.

    Returns:
        The status.

    Raises:
        HTTPException: 404 for an unknown project or version, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return draft_binding_store.version_binding_status(tenant_id, project_ref, version_ref)
    except DraftBindingValidationError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


@router.post(
    _VERSION_BASE,
    response_model=DraftBindingDetail,
    status_code=201,
    summary="Bind a draft version to a repository ref",
    description=(
        "Make this draft the API review unit of one repository ref and source path. The ref is "
        "resolved and the selection read through a **stored** credential before anything is "
        "written — that read is the authorization check, and it is what produces the commit and "
        "the `sha256:` source digest the binding records.\n\n"
        "Name the repository with either `repository_id` (a registered tenant repository, whose "
        "linked-account credential authorizes the read) or `repo_url` (with an optional "
        "`linked_account_id` of your own). Credentials are never accepted in the body.\n\n"
        "A published version cannot be bound (`409 binding-version-published`), and a version has "
        "at most one active binding: pass `replace: true` to release the current one and bind "
        "anew, or the request is refused with `409 binding-already-bound`. The released row stays "
        "as history.\n\n"
        "Requires `versions:edit`."
    ),
)
async def bind_version(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    body: DraftBindingCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBindingDetail:
    """Bind a draft version.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        body: What to bind to.
        auth_data: The authenticated principal.

    Returns:
        The new binding.

    Raises:
        HTTPException: 404 / 403 / 502 for a repository that cannot be read, 409 for a published or
            already-bound version, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    return await _off_loop(
        draft_binding_store.bind_draft, tenant_id, project_ref, version_ref, user_id, body
    )


@router.delete(
    _VERSION_BASE,
    response_model=DraftBindingRecord,
    summary="Release a version's repository binding",
    description=(
        "Stop this draft being the review unit of its ref. The binding row is **kept** — stamped "
        "released, with who released it and when — and any outstanding sync candidates on it are "
        "superseded, because a released binding can never act on one.\n\n"
        "Requires `versions:edit`."
    ),
)
async def release_version_binding(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBindingRecord:
    """Release a version's active binding.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        auth_data: The authenticated principal.

    Returns:
        The released binding.

    Raises:
        HTTPException: 404 when the version is not bound, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        return draft_binding_store.release_binding(tenant_id, project_ref, version_ref, user_id)
    except DraftBindingValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_VERSION_BASE}/check",
    response_model=DraftBindingDetail,
    summary="Check whether the bound ref has moved",
    description=(
        "Ask the provider where the bound ref is now. When it has moved, a **sync candidate** is "
        "recorded — the commit and digest the binding is at, and the commit the ref moved to — and "
        "nothing about the draft changes. When it has not, the request is refused with `409 "
        "binding-unchanged`.\n\n"
        "This is the same thing a push to the ref does through the repository webhook; it exists "
        "so a binding can be reconciled without waiting for one.\n\n"
        "Requires `versions:edit`."
    ),
)
async def check_version_binding(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBindingDetail:
    """Check the bound ref for movement.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        auth_data: The authenticated principal.

    Returns:
        The binding, carrying the candidate this check raised.

    Raises:
        HTTPException: 409 when the ref has not moved, 404 when the version is not bound,
            404 / 403 / 502 when the repository cannot be read.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    return await _off_loop(
        draft_binding_store.check_for_updates, tenant_id, project_ref, version_ref, user_id
    )


@router.post(
    f"{_VERSION_BASE}/candidates/{{candidate_id}}",
    response_model=DraftBindingDetail,
    summary="Settle an outstanding sync candidate",
    description=(
        "Decide what happens to an observed ref update.\n\n"
        "`applied` records that the draft is in sync with the candidate's commit: the source is "
        "re-read at that commit — so the digest stored is one that was actually fetched — and the "
        "binding's synchronized pair advances to it, which is the base the next update is compared "
        "against. It does **not** modify the draft; three-way synchronization (GNC-2.3) settles a "
        "candidate this way after it has applied the changes.\n\n"
        "`dismissed` leaves the binding exactly where it is.\n\n"
        "A candidate settles once: a settled one is refused with `409 "
        "binding-candidate-resolved`.\n\n"
        "Requires `versions:edit`."
    ),
)
async def resolve_binding_candidate(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    candidate_id: str,
    body: SyncCandidateResolve,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBindingDetail:
    """Settle one sync candidate.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version_ref: Revision id or version label.
        candidate_id: The candidate.
        body: ``applied`` or ``dismissed``, with an optional note.
        auth_data: The authenticated principal.

    Returns:
        The binding, with the candidate settled.

    Raises:
        HTTPException: 404 for an unknown candidate, 409 for one already settled,
            404 / 403 / 502 when applying could not read the source.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    return await _off_loop(
        draft_binding_store.resolve_candidate,
        tenant_id,
        project_ref,
        version_ref,
        candidate_id,
        user_id,
        body,
    )
