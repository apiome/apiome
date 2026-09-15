"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/reviews`` — COL-2.1 (#4517).

The HTTP surface of version review: request a review of a draft version from named reviewers,
record decisions, re-request after the spec changes, withdraw, and read a project's reviews or one
version's review status. The lifecycle is :mod:`app.review_lifecycle`; the rules are
:mod:`app.review_store`.

**Authorization.** There is no review RBAC resource.

* Requesting, re-requesting, and withdrawing change a version's workflow, so they require
  ``versions:edit``. Withdrawing is further limited to the requester or a tenant administrator.
* Recording a decision requires ``projects:view`` *and* being a reviewer of the current round —
  an assignment, which a role grid cannot express. The store answers ``403 review-not-reviewer``.
* Reads require ``projects:view``.

**Audit.** Every transition and decision is written to ``workflow_audit`` as a ``review.*`` action
in the same transaction as the change, and is readable through ``GET
/v1/tenants/{tenant_slug}/workflow-audit?version_id=…``.

**Discussion.** A review's conversation is the version's comment threads (COL-1.1): read them with
``GET …/comment-threads?version=<version_id>``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import review_store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .review_store import ReviewFilters
from .reviews import (
    CODE_ALREADY_DECIDED,
    CODE_ALREADY_OPEN,
    CODE_CLOSED,
    CODE_CONFLICT,
    CODE_FORBIDDEN,
    CODE_NOT_IN_REVIEW,
    CODE_NOT_REVIEWER,
    CODE_PROJECT_NOT_FOUND,
    CODE_REVIEW_NOT_FOUND,
    CODE_SPEC_CHANGED,
    CODE_SPEC_UNCHANGED,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_PUBLISHED,
    ReviewDecisionCreate,
    ReviewDetail,
    ReviewRecord,
    ReviewRequestCreate,
    ReviewReRequest,
    ReviewState,
    ReviewValidationError,
    VersionReviewStatus,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["reviews"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_REVIEW_NOT_FOUND: 404,
    CODE_FORBIDDEN: 403,
    CODE_NOT_REVIEWER: 403,
    CODE_VERSION_PUBLISHED: 409,
    CODE_ALREADY_OPEN: 409,
    CODE_ALREADY_DECIDED: 409,
    CODE_NOT_IN_REVIEW: 409,
    CODE_CLOSED: 409,
    CODE_SPEC_UNCHANGED: 409,
    CODE_SPEC_CHANGED: 409,
    CODE_CONFLICT: 409,
}

_BASE = "/{tenant_slug}/projects/{project_ref}/reviews"


class ReviewListResponse(BaseModel):
    """A page of a project's reviews."""

    model_config = ConfigDict(extra="forbid")

    reviews: List[ReviewRecord] = Field(default_factory=list, description="Reviews, most recently active first.")
    count: int = Field(description="How many reviews this page holds.")
    total: int = Field(description="How many reviews match the filters in all.")
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
    return str(tenant_id), user_id


def _http_error(exc: ReviewValidationError) -> HTTPException:
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
    _BASE,
    response_model=ReviewListResponse,
    summary="List a project's reviews",
    description=(
        "A page of the project's reviews, most recently active first, each with the tally of its "
        "current round.\n\n"
        "Filters combine: `version` (revision id or version label), `state` (`in_review`, "
        "`approved`, `changes_requested`), and `open` (`true` for open reviews, `false` for "
        "withdrawn ones).\n\n"
        "Requires `projects:view`."
    ),
)
async def list_reviews(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label."),
    state: Optional[ReviewState] = Query(default=None, description="Review state."),
    open: Optional[bool] = Query(default=None, description="Open (`true`) or withdrawn (`false`) reviews only."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Reviews to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewListResponse:
    """List a project's reviews.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version: Only this version's reviews.
        state: Only reviews in this state.
        open: Only open or only withdrawn reviews.
        limit: Page size.
        offset: Reviews to skip.
        auth_data: The authenticated principal.

    Returns:
        The page and the total.

    Raises:
        HTTPException: 404 for an unknown project or version, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    filters = ReviewFilters(version=version, state=state, open=open, limit=limit, offset=offset)
    try:
        reviews, total = review_store.list_reviews(tenant_id, project_ref, filters)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc
    return ReviewListResponse(reviews=reviews, count=len(reviews), total=total, limit=limit, offset=offset)


@router.get(
    f"{_BASE}/{{review_id}}",
    response_model=ReviewDetail,
    summary="Read a review",
    description=(
        "A review with its current round's reviewers, every earlier round's decisions (unchanged "
        "since they were recorded), and `spec_changed` — true when the version's content no "
        "longer matches the round being decided.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_review(
    tenant_slug: str,
    project_ref: str,
    review_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewDetail:
    """Read a review.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        review_id: The review.
        auth_data: The authenticated principal.

    Returns:
        The review detail.

    Raises:
        HTTPException: 404 for an unknown project or review, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return review_store.get_review(tenant_id, project_ref, review_id)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/review",
    response_model=VersionReviewStatus,
    summary="Read a version's review status",
    description=(
        "Where a version stands in review: `draft` when it has no open review, otherwise the open "
        "review's state together with the review.\n\n"
        "Requires `projects:view`."
    ),
)
async def read_version_review_status(
    tenant_slug: str,
    project_ref: str,
    version_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionReviewStatus:
    """Read a version's review status.

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
        return review_store.version_review_status(tenant_id, project_ref, version_ref)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc


# ---------------------------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------------------------


@router.post(
    _BASE,
    response_model=ReviewDetail,
    status_code=201,
    summary="Request a review of a draft version",
    description=(
        "Ask named reviewers whether a draft (unpublished) version is ready: `draft → in_review`, "
        "round 1, every reviewer `pending`.\n\n"
        "Reviewers are tenant member user ids (at most 20, duplicates collapsed) and cannot "
        "include the requester (`400 review-self-review`). A published version cannot be "
        "reviewed (`409 review-version-published`), and a version has at most one open review "
        "(`409 review-already-open`). The round records the fingerprint of the version's current "
        "content.\n\n"
        "Requires `versions:edit`."
    ),
)
async def request_review(
    tenant_slug: str,
    project_ref: str,
    body: ReviewRequestCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewDetail:
    """Request a review.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The version and the reviewers.
        auth_data: The authenticated principal.

    Returns:
        The new review.

    Raises:
        HTTPException: 400 for an invalid reviewer list, 404 for an unknown project or version,
            409 for a published version or an open review, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        return review_store.request_review(tenant_id, project_ref, body, user_id)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{review_id}}/decision",
    response_model=ReviewDetail,
    summary="Record a review decision",
    description=(
        "Record the caller's `approve` or `request_changes`, with an optional note, on the "
        "current round. Any `request_changes` moves the review to `changes_requested`; once "
        "every reviewer approved it is `approved`.\n\n"
        "A decision is recorded once and never changes (`409 review-already-decided`); a round "
        "that is already decided takes no more (`409 review-not-in-review`); and a round whose "
        "content changed must be re-requested first (`409 review-spec-changed`).\n\n"
        "Requires `projects:view`, and the caller must be a reviewer of the current round "
        "(`403 review-not-reviewer`)."
    ),
)
async def record_review_decision(
    tenant_slug: str,
    project_ref: str,
    review_id: str,
    body: ReviewDecisionCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewDetail:
    """Record a decision.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        review_id: The review.
        body: The decision and note.
        auth_data: The authenticated principal.

    Returns:
        The review after the decision.

    Raises:
        HTTPException: 403 for a caller who is not a reviewer, 404 for an unknown project or
            review, 409 for a closed, decided, stale, or published review.
    """
    tenant_id, user_id = _caller(auth_data, Resource.PROJECTS, Action.VIEW)
    _ = tenant_slug
    try:
        return review_store.record_decision(tenant_id, project_ref, review_id, body, user_id)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{review_id}}/re-request",
    response_model=ReviewDetail,
    summary="Re-request a review after the spec changed",
    description=(
        "Start the next round once the version's content has changed: every reviewer is asked "
        "again with a fresh `pending` decision, and the earlier rounds' decisions stay as "
        "history. Stale approvals never carry over to changed content.\n\n"
        "`reviewers` replaces the reviewer list for the new round; omit it to ask the current "
        "round's reviewers again. An unchanged spec is a `409 review-spec-unchanged`.\n\n"
        "Requires `versions:edit`."
    ),
)
async def re_request_review(
    tenant_slug: str,
    project_ref: str,
    review_id: str,
    body: Optional[ReviewReRequest] = None,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewDetail:
    """Re-request a review.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        review_id: The review.
        body: Optional new reviewer list.
        auth_data: The authenticated principal.

    Returns:
        The review in its new round.

    Raises:
        HTTPException: 400 for an invalid reviewer list, 404 for an unknown project or review, 409
            for an unchanged spec or a closed or published review, 403 without ``versions:edit``.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        return review_store.re_request_review(
            tenant_id, project_ref, review_id, body or ReviewReRequest(), user_id
        )
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{review_id}}/withdraw",
    response_model=ReviewDetail,
    summary="Withdraw a review",
    description=(
        "Close an open review. Its state and decisions stay as recorded, and the version can be "
        "sent for review again.\n\n"
        "Requires `versions:edit`, and the caller must be the member who requested the review or "
        "a tenant administrator (`403 review-forbidden`)."
    ),
)
async def withdraw_review(
    tenant_slug: str,
    project_ref: str,
    review_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewDetail:
    """Withdraw a review.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        review_id: The review.
        auth_data: The authenticated principal.

    Returns:
        The closed review.

    Raises:
        HTTPException: 403 unless the caller requested the review or administers the tenant, 404
            for an unknown project or review, 409 for a review already withdrawn.
    """
    tenant_id, user_id = _caller(auth_data, Resource.VERSIONS, Action.EDIT)
    _ = tenant_slug
    try:
        return review_store.withdraw_review(tenant_id, project_ref, review_id, user_id)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc
