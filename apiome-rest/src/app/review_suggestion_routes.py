"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions`` — COL-4.2 (#4526).

Suggested changes on a review: a reviewer proposes a concrete edit to a class or property of the
version under review, and the author applies it or rejects it in one click.

* ``GET …/suggestions`` — the review's suggestions; an open one carries a live ``stale`` flag.
* ``POST …/suggestions`` — propose (``target_type``, ``target_id``, RFC 6902 ``patch``, ``note``).
* ``POST …/suggestions/{id}/apply`` — merge it onto the element with the merge-session engine and
  write it. An overlapping edit made since is a ``409 suggestion-stale`` carrying
  ``conflict_paths``; the suggestion is then recorded ``stale`` and nothing else is written.
* ``POST …/suggestions/{id}/reject`` — record a rejection, with an optional reason.

**Authorization.** Every route requires ``projects:view``. Proposing is open to the review's
current-round reviewers, its requester, and project editors (``projects:edit``); deciding to the
requester and editors, and an author can never apply their own suggestion. See
:mod:`app.review_suggestion_store`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import review_store, review_suggestion_store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission, has_permission
from .review_suggestions import (
    CODE_FORBIDDEN,
    CODE_NOT_OPEN,
    CODE_STALE,
    CODE_SUGGESTION_NOT_FOUND,
    CODE_TARGET_NOT_FOUND,
    SuggestionApplyResult,
    SuggestionCreate,
    SuggestionDecision,
    SuggestionRecord,
    SuggestionValidationError,
)
from .reviews import (
    CODE_CLOSED,
    CODE_PROJECT_NOT_FOUND,
    CODE_REVIEW_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    CODE_VERSION_PUBLISHED,
    ReviewValidationError,
)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["review-suggestions"])

_BASE = "/{tenant_slug}/projects/{project_ref}/reviews/{review_id}/suggestions"

_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_REVIEW_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_SUGGESTION_NOT_FOUND: 404,
    CODE_TARGET_NOT_FOUND: 404,
    CODE_FORBIDDEN: 403,
    CODE_NOT_OPEN: 409,
    CODE_STALE: 409,
    CODE_CLOSED: 409,
    CODE_VERSION_PUBLISHED: 409,
}


class ReviewSuggestionListResponse(BaseModel):
    """A review's suggestions."""

    model_config = ConfigDict(extra="forbid")

    suggestions: List[SuggestionRecord] = Field(default_factory=list, description="Oldest first.")
    can_decide: bool = Field(description="Whether the caller may apply or reject (others') suggestions.")


def _http_error(exc: Exception) -> HTTPException:
    """Translate a refusal into ``{"code", "message"[, "conflict_paths"]}`` with its status."""
    code = getattr(exc, "code", "suggestion-invalid")
    detail: Dict[str, Any] = {"code": code, "message": str(exc)}
    if getattr(exc, "conflict_paths", None):
        detail["conflict_paths"] = exc.conflict_paths  # type: ignore[attr-defined]
    return HTTPException(status_code=_STATUS_BY_CODE.get(code, 400), detail=detail)


def _context(auth_data: Dict[str, Any], project_ref: str, review_id: str) -> Tuple[str, str, bool, Dict, Dict]:
    """Require ``projects:view`` and resolve the review and its version.

    Returns:
        ``(tenant_id, user_id, is_editor, review, version)``.

    Raises:
        HTTPException: 403 without access, 404 for an unknown project, review, or version.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    tenant_id = str(tenant_id)
    try:
        project = review_store.resolve_project(tenant_id, project_ref)
        review = review_store._review_row(tenant_id, str(project["id"]), review_id)
        version = review_store._review_version(tenant_id, review)
    except ReviewValidationError as exc:
        raise _http_error(exc) from exc
    is_editor = has_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    return tenant_id, user_id, is_editor, review, version


@router.get(_BASE, response_model=ReviewSuggestionListResponse, summary="List a review's suggested changes")
def list_suggestions(
    tenant_slug: str, project_ref: str, review_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ReviewSuggestionListResponse:
    """Every suggestion on the review, oldest first. Requires `projects:view`."""
    _tenant, user_id, is_editor, review, _version = _context(auth_data, project_ref, review_id)
    return ReviewSuggestionListResponse(
        suggestions=review_suggestion_store.list_suggestions(review),
        can_decide=is_editor or user_id == str(review.get("requested_by") or ""),
    )


@router.post(_BASE, response_model=SuggestionRecord, status_code=201, summary="Suggest a change")
def create_suggestion(
    tenant_slug: str, project_ref: str, review_id: str, body: SuggestionCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SuggestionRecord:
    """Propose an RFC 6902 patch to one class or property of the reviewed version.

    Open to the review's current-round reviewers, its requester, and project editors.
    """
    tenant_id, user_id, is_editor, review, version = _context(auth_data, project_ref, review_id)
    try:
        return review_suggestion_store.create_suggestion(tenant_id, review, version, user_id, body, is_editor=is_editor)
    except SuggestionValidationError as exc:
        raise _http_error(exc) from exc


@router.post(f"{_BASE}/{{suggestion_id}}/apply", response_model=SuggestionApplyResult, summary="Apply a suggested change")
def apply_suggestion(
    tenant_slug: str, project_ref: str, review_id: str, suggestion_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SuggestionApplyResult:
    """Merge the suggestion onto the element and write it.

    `409 suggestion-stale` (with `conflict_paths`) when the element changed since in a way that
    overlaps the suggestion; it is then recorded stale and nothing else is written. The review's
    requester or a project editor only, never the suggestion's author.
    """
    _tenant, user_id, is_editor, review, version = _context(auth_data, project_ref, review_id)
    try:
        return review_suggestion_store.apply_suggestion(review, version, suggestion_id, user_id, is_editor=is_editor)
    except SuggestionValidationError as exc:
        raise _http_error(exc) from exc


@router.post(f"{_BASE}/{{suggestion_id}}/reject", response_model=SuggestionRecord, summary="Reject a suggested change")
def reject_suggestion(
    tenant_slug: str, project_ref: str, review_id: str, suggestion_id: str,
    body: SuggestionDecision = SuggestionDecision(),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SuggestionRecord:
    """Record a rejection (or its author's withdrawal), with an optional reason."""
    _tenant, user_id, is_editor, review, version = _context(auth_data, project_ref, review_id)
    try:
        return review_suggestion_store.reject_suggestion(
            review, version, suggestion_id, user_id, is_editor=is_editor, reason=body.reason
        )
    except SuggestionValidationError as exc:
        raise _http_error(exc) from exc
