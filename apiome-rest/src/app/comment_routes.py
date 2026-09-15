"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/comment-threads`` — COL-1.1 (#4513).

The HTTP surface of element-anchored discussion: open a thread on a class, property, path,
operation, or version; reply; edit and delete comments; resolve and reopen; and list a project's
threads by version, status, element, or "mentions me".

**Authorization.** There is no comment RBAC resource. Reading a project is what grants taking part
in its discussion, so every route requires ``projects:view`` — a Viewer can comment. What a role
grid cannot express is *ownership*: editing or deleting a comment is limited to its author or a
tenant administrator, and deleting a whole thread to the member who opened it or a tenant
administrator. :mod:`app.comment_store` enforces that and answers ``403 comment-forbidden``.

**Rate limits.** Opening a thread and replying both write a comment and resolve mentions against
the tenant's members, so the two share a per-user, per-tenant budget
(``APIOME_COMMENT_CREATE_RATE_LIMIT_PER_MINUTE`` over the global window) on top of the global
middleware. Over budget is a ``429 comment-rate-limited`` with ``Retry-After``.

**Mentions** are always resolved on the server; see :mod:`app.comment_mentions` for the grammar.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from . import comment_store
from .auth import validate_authentication
from .comment_store import ThreadFilters
from .comments import (
    CODE_ANCHOR_NOT_FOUND,
    CODE_COMMENT_NOT_FOUND,
    CODE_FORBIDDEN,
    CODE_PROJECT_NOT_FOUND,
    CODE_RATE_LIMITED,
    CODE_THREAD_NOT_FOUND,
    CODE_VERSION_NOT_FOUND,
    STATUS_OPEN,
    STATUS_RESOLVED,
    AnchorType,
    CommentBody,
    CommentRecord,
    CommentThreadCreate,
    CommentThreadDetail,
    CommentThreadRecord,
    CommentThreadSummary,
    CommentValidationError,
    ThreadStatus,
)
from .config import settings
from .database import db
from .permissions import Action, Resource, enforce_permission
from .rate_limit import FixedWindowRateLimiter

__all__ = ["enforce_comment_rate_limit", "router"]

router = APIRouter(prefix="/v1/tenants", tags=["comments"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400.
_STATUS_BY_CODE = {
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_ANCHOR_NOT_FOUND: 404,
    CODE_THREAD_NOT_FOUND: 404,
    CODE_COMMENT_NOT_FOUND: 404,
    CODE_FORBIDDEN: 403,
}

_BASE = "/{tenant_slug}/projects/{project_ref}/comment-threads"

_comment_limiter = FixedWindowRateLimiter()


# ---------------------------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------------------------


class CommentThreadListResponse(BaseModel):
    """A page of a project's threads."""

    model_config = ConfigDict(extra="forbid")

    threads: List[CommentThreadSummary] = Field(
        default_factory=list, description="Threads, most recently active first."
    )
    count: int = Field(description="How many threads this page holds.")
    total: int = Field(description="How many threads match the filters in all.")
    limit: int = Field(description="The page size used.")
    offset: int = Field(description="The offset used.")


class CommentDeletionResponse(BaseModel):
    """The outcome of deleting a comment."""

    model_config = ConfigDict(extra="forbid")

    deleted: bool = Field(description="Always true; a comment that is not there is a 404.")
    thread_deleted: bool = Field(
        description="True when this was the thread's last comment, so the thread was deleted too."
    )


# ---------------------------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------------------------


def _commenter(auth_data: Dict[str, Any]) -> Tuple[str, str]:
    """Require project read access and return ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant and the acting user.

    Raises:
        HTTPException: 403 without ``projects:view``, without an attributable user, or without a
            tenant.
    """
    user_id = enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id), user_id


def _http_error(exc: CommentValidationError) -> HTTPException:
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


def enforce_comment_rate_limit(tenant_id: str, user_id: str) -> None:
    """Record one comment write against the user's budget, refusing when it is spent.

    Args:
        tenant_id: The caller's tenant.
        user_id: The writing user.

    Raises:
        HTTPException: ``429 comment-rate-limited`` with ``Retry-After`` and ``X-RateLimit-*``
            headers when over ``comment_create_rate_limit_per_minute``. Does nothing while the
            global ``rate_limit_enabled`` kill switch is off.
    """
    if not settings.rate_limit_enabled:
        return
    limit = max(1, settings.comment_create_rate_limit_per_minute)
    window_seconds = max(1, settings.rate_limit_window_seconds)
    allowed, remaining, reset_after, retry_after = _comment_limiter.check(
        f"comment:{tenant_id}:{user_id}", limit, window_seconds, time.monotonic()
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "code": CODE_RATE_LIMITED,
                "message": "Too many comments in a short time. Slow down and retry later.",
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_after),
            },
        )


# ---------------------------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------------------------


@router.get(
    _BASE,
    response_model=CommentThreadListResponse,
    summary="List a project's comment threads",
    description=(
        "A page of the project's threads, most recently active first, each with its opening "
        "comment and its comment count.\n\n"
        "Filters combine: `version` (revision id or version label) lists one version's threads — "
        "on its classes, properties, paths, and operations as well as on the version itself; "
        "`status` keeps `open` or `resolved`; `anchor_type` and `anchor_id` narrow to one kind of "
        "element or one element; `mentions_me=true` keeps threads with a comment mentioning the "
        "caller.\n\n"
        "Requires `projects:view`."
    ),
)
async def list_comment_threads(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(default=None, description="Revision id or version label."),
    status: Optional[ThreadStatus] = Query(default=None, description="`open` or `resolved`."),
    anchor_type: Optional[AnchorType] = Query(default=None, description="Element kind."),
    anchor_id: Optional[str] = Query(default=None, description="Element id."),
    mentions_me: bool = Query(
        default=False, description="Only threads with a comment mentioning the caller."
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Threads to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentThreadListResponse:
    """List a project's threads.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        project_ref: Project slug or id.
        version: Only this version's threads.
        status: Only threads in this status.
        anchor_type: Only threads on this element kind.
        anchor_id: Only threads on this element.
        mentions_me: Only threads mentioning the caller.
        limit: Page size.
        offset: Threads to skip.
        auth_data: The authenticated principal.

    Returns:
        The page and the total.

    Raises:
        HTTPException: 404 for an unknown project or version, 400 for a malformed `anchor_id`,
            403 without ``projects:view``.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    filters = ThreadFilters(
        version=version,
        status=status,
        anchor_type=anchor_type,
        anchor_id=anchor_id,
        mentions_me=mentions_me,
        limit=limit,
        offset=offset,
    )
    try:
        threads, total = comment_store.list_threads(tenant_id, project_ref, filters, user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc
    return CommentThreadListResponse(
        threads=threads, count=len(threads), total=total, limit=limit, offset=offset
    )


@router.post(
    _BASE,
    response_model=CommentThreadDetail,
    status_code=201,
    summary="Open a comment thread on an element",
    description=(
        "Open a thread on one element of a version — a `class`, `property`, `path`, `operation`, "
        "or the `version` itself — together with its first comment.\n\n"
        "The anchor is the element's **stable id**, never a canvas position, and the element must "
        "exist in the named version. For a `version` anchor `anchor_id` may be omitted; if given "
        "it must be that version's id.\n\n"
        "`@name` tokens in the Markdown body are resolved **server-side** against the tenant's "
        "members (full email, email local part, or display name without spaces) and stored in "
        "the comment's `mentions`. A handle matching several members resolves to nobody.\n\n"
        "Requires `projects:view` — read access to a project grants commenting. Rate limited per "
        "user (shared with replies)."
    ),
)
async def open_comment_thread(
    tenant_slug: str,
    project_ref: str,
    body: CommentThreadCreate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentThreadDetail:
    """Open a thread with its first comment.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The version, anchor, and first comment.
        auth_data: The authenticated principal.

    Returns:
        The new thread and its first comment.

    Raises:
        HTTPException: 400 for a malformed anchor or blank body, 404 for an unknown project,
            version, or element, 403 without ``projects:view``, 429 over the comment budget.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    enforce_comment_rate_limit(tenant_id, user_id)
    try:
        return comment_store.create_thread(tenant_id, project_ref, body, user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    f"{_BASE}/{{thread_id}}",
    response_model=CommentThreadDetail,
    summary="Read a comment thread",
    description="A thread with all of its comments, oldest first.\n\nRequires `projects:view`.",
)
async def read_comment_thread(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentThreadDetail:
    """Read a thread with its comments.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        auth_data: The authenticated principal.

    Returns:
        The thread and its comments.

    Raises:
        HTTPException: 404 for an unknown project or thread, 403 without ``projects:view``.
    """
    tenant_id, _user_id = _commenter(auth_data)
    _ = tenant_slug
    try:
        return comment_store.get_thread(tenant_id, project_ref, thread_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    f"{_BASE}/{{thread_id}}",
    status_code=204,
    summary="Delete a comment thread",
    description=(
        "Delete a thread and every comment in it.\n\n"
        "Requires `projects:view`, and the caller must be the member who opened the thread or a "
        "tenant administrator (`403 comment-forbidden` otherwise)."
    ),
)
async def delete_comment_thread(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Delete a thread.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        auth_data: The authenticated principal.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 for an unknown project or thread, 403 unless the caller opened the
            thread or administers the tenant.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    try:
        comment_store.delete_thread(tenant_id, project_ref, thread_id, user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


async def _set_status(
    project_ref: str, thread_id: str, status: str, auth_data: Dict[str, Any]
) -> CommentThreadRecord:
    """Shared body of the resolve and reopen routes.

    Args:
        project_ref: Project slug or id.
        thread_id: The thread.
        status: The status to move the thread to.
        auth_data: The authenticated principal.

    Returns:
        The thread as it now stands.

    Raises:
        HTTPException: 404 for an unknown project or thread, 403 without ``projects:view``.
    """
    tenant_id, user_id = _commenter(auth_data)
    try:
        return comment_store.set_thread_status(tenant_id, project_ref, thread_id, status, user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{thread_id}}/resolve",
    response_model=CommentThreadRecord,
    summary="Resolve a comment thread",
    description=(
        "Mark a thread resolved, recording who resolved it and when. Resolving a thread that is "
        "already resolved changes nothing.\n\n"
        "Requires `projects:view` — anyone taking part in the discussion may resolve it."
    ),
)
async def resolve_comment_thread(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentThreadRecord:
    """Resolve a thread.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        auth_data: The authenticated principal.

    Returns:
        The resolved thread.
    """
    _ = tenant_slug
    return await _set_status(project_ref, thread_id, STATUS_RESOLVED, auth_data)


@router.post(
    f"{_BASE}/{{thread_id}}/reopen",
    response_model=CommentThreadRecord,
    summary="Reopen a comment thread",
    description=(
        "Reopen a resolved thread, clearing its resolution. Reopening an open thread changes "
        "nothing.\n\n"
        "Requires `projects:view`."
    ),
)
async def reopen_comment_thread(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentThreadRecord:
    """Reopen a thread.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        auth_data: The authenticated principal.

    Returns:
        The reopened thread.
    """
    _ = tenant_slug
    return await _set_status(project_ref, thread_id, STATUS_OPEN, auth_data)


# ---------------------------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------------------------


@router.post(
    f"{_BASE}/{{thread_id}}/comments",
    response_model=CommentRecord,
    status_code=201,
    summary="Reply to a comment thread",
    description=(
        "Add a Markdown comment to a thread. `@name` mentions are resolved server-side, as when "
        "opening a thread. A resolved thread accepts replies and stays resolved.\n\n"
        "Requires `projects:view`. Rate limited per user (shared with opening threads)."
    ),
)
async def reply_to_comment_thread(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    body: CommentBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentRecord:
    """Reply to a thread.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        body: The Markdown reply.
        auth_data: The authenticated principal.

    Returns:
        The stored comment.

    Raises:
        HTTPException: 400 for a blank body, 404 for an unknown project or thread, 403 without
            ``projects:view``, 429 over the comment budget.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    enforce_comment_rate_limit(tenant_id, user_id)
    try:
        return comment_store.add_comment(tenant_id, project_ref, thread_id, body.body, user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.patch(
    f"{_BASE}/{{thread_id}}/comments/{{comment_id}}",
    response_model=CommentRecord,
    summary="Edit a comment",
    description=(
        "Replace a comment's Markdown. Mentions are re-resolved from the new text and `edited_at` "
        "is stamped.\n\n"
        "Requires `projects:view`, and the caller must be the comment's author or a tenant "
        "administrator (`403 comment-forbidden` otherwise)."
    ),
)
async def edit_comment(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    comment_id: str,
    body: CommentBody,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentRecord:
    """Edit a comment.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        comment_id: The comment.
        body: The new Markdown.
        auth_data: The authenticated principal.

    Returns:
        The updated comment.

    Raises:
        HTTPException: 400 for a blank body, 404 for an unknown project, thread, or comment, 403
            unless the caller wrote the comment or administers the tenant.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    try:
        return comment_store.edit_comment(
            tenant_id, project_ref, thread_id, comment_id, body.body, user_id
        )
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    f"{_BASE}/{{thread_id}}/comments/{{comment_id}}",
    response_model=CommentDeletionResponse,
    summary="Delete a comment",
    description=(
        "Delete a comment. Deleting a thread's **last** comment deletes the thread as well, which "
        "the response reports as `thread_deleted: true`.\n\n"
        "Requires `projects:view`, and the caller must be the comment's author or a tenant "
        "administrator (`403 comment-forbidden` otherwise)."
    ),
)
async def delete_comment(
    tenant_slug: str,
    project_ref: str,
    thread_id: str,
    comment_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CommentDeletionResponse:
    """Delete a comment.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        thread_id: The thread.
        comment_id: The comment.
        auth_data: The authenticated principal.

    Returns:
        Whether the thread went with it.

    Raises:
        HTTPException: 404 for an unknown project, thread, or comment, 403 unless the caller wrote
            the comment or administers the tenant.
    """
    tenant_id, user_id = _commenter(auth_data)
    _ = tenant_slug
    try:
        thread_deleted = comment_store.delete_comment(
            tenant_id, project_ref, thread_id, comment_id, user_id
        )
    except CommentValidationError as exc:
        raise _http_error(exc) from exc
    return CommentDeletionResponse(deleted=True, thread_deleted=thread_deleted)
