"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/draft-branches`` and ``…/merge-requests`` — COL-4.3 (#4527).

The HTTP surface of the branch / merge-request spec workflow: draft a change on a named branch off
a version line, open a merge request, let reviewers decide through the COL-2.1 review of the
branch tip, check for conflicts through a merge session, and merge through the existing merge
path. The rules are :mod:`app.merge_request_store`; the vocabulary is :mod:`app.merge_requests`.

**Authorization.**

* Reads require ``versions:view``.
* Creating a draft branch requires ``versions:create`` (it creates a revision).
* Opening, re-requesting a review for, and closing a merge request require ``versions:edit``.
* Checking for conflicts requires ``versions:view``; merging requires ``versions:edit``. Both run
  the existing merge-preview and merge routes, which enforce the same permissions themselves.

**Errors.** Every refusal carries ``{"code", "message"}`` — an ``mr-*`` code from this surface, a
``review-*`` code from the review it composes, or the merge path's own code (``STALE_HEAD``,
``PUBLISHED_IMMUTABLE``, ``MERGE_BLOCKED_BY_COMPAT_GATE`` …). ``mr-not-ready`` adds ``blockers``;
``mr-conflicts`` adds ``conflicts`` and ``merge_session_id``.

**Audit.** ``branch.draft_created``, ``merge_request.opened``, ``merge_request.merged`` and
``merge_request.closed`` are written to ``workflow_audit``, beside the merge path's own rows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import merge_request_store
from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .merge_requests import (
    CODE_ALREADY_OPEN,
    CODE_BRANCH_EXISTS,
    CODE_BRANCH_NOT_FOUND,
    CODE_CONFLICTS,
    CODE_FORBIDDEN,
    CODE_LABEL_TAKEN,
    CODE_MERGE_REQUEST_NOT_FOUND,
    CODE_NOT_OPEN,
    CODE_NOT_READY,
    CODE_PROJECT_NOT_FOUND,
    DraftBranchCreate,
    DraftBranchRecord,
    MergeRequestCreate,
    MergeRequestDetail,
    MergeRequestMerge,
    MergeRequestRecord,
    MergeRequestReviewRequest,
    MergeRequestState,
    MergeRequestValidationError,
)
from .permissions import Action, Resource, enforce_permission
from .review_routes import _http_error as _review_http_error
from .reviews import ReviewValidationError

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["merge-requests"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_MERGE_REQUEST_NOT_FOUND: 404,
    CODE_BRANCH_NOT_FOUND: 404,
    CODE_FORBIDDEN: 403,
    CODE_BRANCH_EXISTS: 409,
    CODE_LABEL_TAKEN: 409,
    CODE_ALREADY_OPEN: 409,
    CODE_NOT_OPEN: 409,
    CODE_NOT_READY: 409,
    CODE_CONFLICTS: 409,
}

_PROJECT = "/{tenant_slug}/projects/{project_ref}"
_MR = _PROJECT + "/merge-requests/{merge_request_id}"


class DraftBranchListResponse(BaseModel):
    """A project's draft branches."""

    model_config = ConfigDict(extra="forbid")

    branches: List[DraftBranchRecord] = Field(default_factory=list, description="Newest first.")


class MergeRequestListResponse(BaseModel):
    """A page of a project's merge requests."""

    model_config = ConfigDict(extra="forbid")

    merge_requests: List[MergeRequestRecord] = Field(
        default_factory=list, description="Merge requests, most recently active first."
    )
    count: int = Field(description="How many merge requests this page holds.")
    total: int = Field(description="How many merge requests match the filter in all.")
    limit: int
    offset: int


# ---------------------------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------------------------


def _caller(auth_data: Dict[str, Any], resource: str, action: str) -> Tuple[str, Optional[str]]:
    """Require a permission and return ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.
        resource: The RBAC resource.
        action: The RBAC action.

    Returns:
        The tenant and the acting user (``None`` when the credential names none).

    Raises:
        HTTPException: 403 without the permission or without a tenant.
    """
    enforce_permission(db, auth_data, resource, action)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id), get_authenticated_user_id(auth_data)


def _http_error(exc: Exception) -> HTTPException:
    """Translate a store refusal into the HTTP error a client sees.

    Args:
        exc: A :class:`MergeRequestValidationError` or a :class:`ReviewValidationError`.

    Returns:
        The ``HTTPException`` to raise, always carrying ``{"code", "message"}``.
    """
    if isinstance(exc, ReviewValidationError):
        return _review_http_error(exc)
    assert isinstance(exc, MergeRequestValidationError)
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc), **exc.extra},
    )


_REFUSALS = (MergeRequestValidationError, ReviewValidationError)

_ERROR_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    403: {"description": "Missing permission, or the action needs an attributable user."},
    404: {"description": "Unknown project, branch, or merge request (`mr-*-not-found`)."},
    409: {"description": "The request conflicts with the current state (see the `code`)."},
}


# ---------------------------------------------------------------------------------------------
# Draft branches
# ---------------------------------------------------------------------------------------------


@router.get(
    _PROJECT + "/draft-branches",
    response_model=DraftBranchListResponse,
    summary="List draft branches",
    responses={404: _ERROR_RESPONSES[404]},
)
async def list_draft_branches(
    tenant_slug: str, project_ref: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> DraftBranchListResponse:
    """List the project's draft branches, each with the version line it was drafted off."""
    tenant_id, _ = _caller(auth_data, Resource.VERSIONS, Action.VIEW)
    try:
        return DraftBranchListResponse(branches=merge_request_store.list_draft_branches(tenant_id, project_ref))
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.post(
    _PROJECT + "/draft-branches",
    response_model=DraftBranchRecord,
    status_code=201,
    summary="Create a draft branch off a version line",
    responses=_ERROR_RESPONSES,
)
async def create_draft_branch(
    tenant_slug: str,
    project_ref: str,
    body: DraftBranchCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DraftBranchRecord:
    """Create a named draft branch off a version line (a branch; the default branch when omitted).

    The line's tip is copied — classes and paths — into a new draft revision that becomes the
    branch's tip, so edits on the branch never touch the line. ``version_label`` names that
    revision; it defaults to the next patch version of the project.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.CREATE)
    try:
        return merge_request_store.create_draft_branch(tenant_id, project_ref, body, user_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Merge requests
# ---------------------------------------------------------------------------------------------


@router.get(
    _PROJECT + "/merge-requests",
    response_model=MergeRequestListResponse,
    summary="List merge requests",
    responses={404: _ERROR_RESPONSES[404]},
)
async def list_merge_requests(
    tenant_slug: str,
    project_ref: str,
    state: Optional[MergeRequestState] = Query(default=None, description="Only requests in this state."),
    limit: int = Query(default=50, ge=1, le=merge_request_store.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestListResponse:
    """List the project's merge requests, most recently active first."""
    tenant_id, _ = _caller(auth_data, Resource.VERSIONS, Action.VIEW)
    try:
        records, total = merge_request_store.list_merge_requests(
            tenant_id, project_ref, state=state, limit=limit, offset=offset
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
    return MergeRequestListResponse(merge_requests=records, count=len(records), total=total, limit=limit, offset=offset)


@router.post(
    _PROJECT + "/merge-requests",
    response_model=MergeRequestDetail,
    status_code=201,
    summary="Open a merge request",
    responses=_ERROR_RESPONSES,
)
async def open_merge_request(
    tenant_slug: str,
    project_ref: str,
    body: MergeRequestCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Open a merge request from a draft branch into a line (the line it was drafted off by default).

    The branch tip's review is requested from ``reviewers`` (COL-2.1), or the tip's open review is
    attached when it already has one.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    try:
        return merge_request_store.open_merge_request(tenant_id, project_ref, body, user_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.get(
    _MR,
    response_model=MergeRequestDetail,
    summary="Read a merge request",
    responses={404: _ERROR_RESPONSES[404]},
)
async def read_merge_request(
    tenant_slug: str,
    project_ref: str,
    merge_request_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Read a merge request: its branches' tips, merge base, review, merge session, and readiness."""
    tenant_id, _ = _caller(auth_data, Resource.VERSIONS, Action.VIEW)
    try:
        return merge_request_store.get_merge_request(tenant_id, project_ref, merge_request_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.post(
    _MR + "/review",
    response_model=MergeRequestDetail,
    summary="Request a review of the branch's current tip",
    responses=_ERROR_RESPONSES,
)
async def request_merge_request_review(
    tenant_slug: str,
    project_ref: str,
    merge_request_id: str,
    body: MergeRequestReviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Attach a review of the branch's current tip, withdrawing the review of an older tip.

    Use it after the branch moved on (``review-outdated``) or its review was withdrawn. A review
    whose round went stale on the *same* tip is re-requested on the review page instead.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    try:
        return merge_request_store.request_merge_request_review(tenant_id, project_ref, merge_request_id, body, user_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.post(
    _MR + "/check",
    response_model=MergeRequestDetail,
    summary="Check a merge request for conflicts",
    responses=_ERROR_RESPONSES,
)
async def check_merge_request(
    tenant_slug: str,
    project_ref: str,
    merge_request_id: str,
    body: Optional[MergeRequestMerge] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Run a merge session (the existing merge preview, persisted) for the current tips.

    The session's conflicts come back on ``conflicts``; a session with conflicts is left in
    ``resolving`` until the branch is updated and checked again.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.VIEW)
    try:
        return await merge_request_store.check_merge_request(
            tenant_slug, auth_data, user_id, project_ref, merge_request_id, body or MergeRequestMerge()
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.post(
    _MR + "/merge",
    response_model=MergeRequestDetail,
    summary="Merge a merge request",
    responses=_ERROR_RESPONSES,
)
async def merge_merge_request(
    tenant_slug: str,
    project_ref: str,
    merge_request_id: str,
    body: Optional[MergeRequestMerge] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Merge the branch into the line through a merge session and the existing merge path.

    Needs the review approved and current (and the approval policy satisfied, when one applies).
    Conflicts refuse with ``mr-conflicts``; the merge path's own refusals (``STALE_HEAD``,
    ``PUBLISHED_IMMUTABLE``, ``MERGE_BLOCKED_BY_COMPAT_GATE``) pass through unchanged.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    try:
        return await merge_request_store.merge_merge_request(
            tenant_slug, auth_data, user_id, project_ref, merge_request_id, body or MergeRequestMerge()
        )
    except _REFUSALS as exc:
        raise _http_error(exc) from exc


@router.post(
    _MR + "/close",
    response_model=MergeRequestDetail,
    summary="Close a merge request without merging",
    responses=_ERROR_RESPONSES,
)
async def close_merge_request(
    tenant_slug: str,
    project_ref: str,
    merge_request_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MergeRequestDetail:
    """Close the merge request. The branch and its revisions stay; its review is withdrawn when allowed."""
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    try:
        return merge_request_store.close_merge_request(tenant_id, project_ref, merge_request_id, user_id)
    except _REFUSALS as exc:
        raise _http_error(exc) from exc
