"""``/v1/portal/{tenant_slug}/feedback/{project_slug}/{version}/threads`` — COL-4.4 (#4528).

The reader side of portal consumer feedback: a signed-in Browse reader lists, opens, answers,
resolves and reopens **their own** feedback threads on a published, public version. Tag
``portal-feedback``.

**Authentication.** Only a live reader session (``Authorization: Reader <token>``, PCX-1.1) for
*this* tenant is accepted: no session, an expired or revoked one, or one for another tenant is
``401 portal-session-invalid``. Signed-out users therefore cannot file feedback. A JWT or API key is
not a reader and is refused the same way — workspace members discuss in the Discussion panel, where
these threads also appear (tagged ``consumer``) for the team to answer and resolve.

**Rate limit.** Opening a thread and replying share the per-user comment budget
(:func:`app.comment_routes.enforce_comment_rate_limit`) on top of the global middleware.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException

from . import consumer_feedback_store as store
from .auth import resolve_reader_session_header
from .comment_routes import enforce_comment_rate_limit
from .comments import (
    CODE_EMPTY_BODY,
    CODE_FORBIDDEN,
    CODE_THREAD_ORPHANED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    CommentValidationError,
)
from .consumer_feedback import (
    CODE_FEEDBACK_OPERATION_NOT_FOUND,
    CODE_FEEDBACK_THREAD_NOT_FOUND,
    CODE_FEEDBACK_VERSION_NOT_FOUND,
    FeedbackCreate,
    FeedbackReply,
    FeedbackThread,
    FeedbackThreadList,
)
from .portal_auth import CODE_SESSION_INVALID, READER_SCHEME

__all__ = ["router"]

router = APIRouter(prefix="/v1/portal", tags=["portal-feedback"])

_BASE = "/{tenant_slug}/feedback/{project_slug}/{version}/threads"

_STATUS_BY_CODE = {
    CODE_FEEDBACK_VERSION_NOT_FOUND: 404,
    CODE_FEEDBACK_OPERATION_NOT_FOUND: 404,
    CODE_FEEDBACK_THREAD_NOT_FOUND: 404,
    CODE_THREAD_ORPHANED: 409,
    CODE_EMPTY_BODY: 400,
    CODE_FORBIDDEN: 403,
}


def _reader(authorization: Optional[str], tenant_slug: str) -> Any:
    """Require a live reader session bound to the tenant in the URL.

    Args:
        authorization: The ``Authorization`` header.
        tenant_slug: The tenant in the URL.

    Returns:
        The :class:`app.portal_auth_store.ReaderSession`.

    Raises:
        HTTPException: ``401 portal-session-invalid`` for no session, a dead one, or one for
            another tenant.
    """
    session = resolve_reader_session_header(authorization)
    if session.tenant_slug != tenant_slug:
        raise HTTPException(
            status_code=401,
            detail={"code": CODE_SESSION_INVALID, "message": "Sign in to this portal to send feedback."},
            headers={"WWW-Authenticate": READER_SCHEME},
        )
    return session


def _http_error(exc: CommentValidationError) -> HTTPException:
    """Translate a store refusal into the HTTP error the reader sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` carrying ``{"code", "message"}``.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400), detail={"code": exc.code, "message": str(exc)}
    )


@router.get(
    _BASE,
    response_model=FeedbackThreadList,
    summary="List my feedback on a published version",
    description=(
        "The signed-in reader's own feedback threads on a published, public version, most recently "
        "active first, each with every message — the reader's and the team's replies (`from_team`).\n\n"
        "Requires a reader session for this tenant (`Authorization: Reader <token>`); otherwise "
        "`401 portal-session-invalid`. `404 feedback-version-not-found` for an unknown, unpublished "
        "or private version."
    ),
)
def list_my_feedback(
    tenant_slug: str,
    project_slug: str,
    version: str,
    authorization: Optional[str] = Header(default=None),
) -> FeedbackThreadList:
    """List the reader's feedback threads on a version.

    Args:
        tenant_slug: The portal.
        project_slug: The project.
        version: The version label.
        authorization: ``Reader <token>``.

    Returns:
        The threads.
    """
    session = _reader(authorization, tenant_slug)
    try:
        threads = store.list_feedback(session.tenant_id, project_slug, version, session.profile.user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc
    return FeedbackThreadList(threads=threads)


@router.post(
    _BASE,
    response_model=FeedbackThread,
    status_code=201,
    summary="Send feedback on a published version",
    description=(
        "Open a feedback thread on the whole version (`target: \"version\"`) or on one operation "
        "(`target: \"operation\"` with its `method` and `path` exactly as published). The owning "
        "team sees it in its Discussion panel tagged `consumer`.\n\n"
        "`@name` tokens are **not** resolved — feedback never notifies a team member directly.\n\n"
        "Requires a reader session for this tenant. `404 feedback-operation-not-found` for an "
        "operation the version does not have. Rate limited per reader (`429 comment-rate-limited`)."
    ),
)
def send_feedback(
    tenant_slug: str,
    project_slug: str,
    version: str,
    body: FeedbackCreate,
    authorization: Optional[str] = Header(default=None),
) -> FeedbackThread:
    """Open a feedback thread.

    Args:
        tenant_slug: The portal.
        project_slug: The project.
        version: The version label.
        body: The target and first message.
        authorization: ``Reader <token>``.

    Returns:
        The new thread.
    """
    session = _reader(authorization, tenant_slug)
    enforce_comment_rate_limit(session.tenant_id, session.profile.user_id)
    try:
        return store.open_feedback(session.tenant_id, project_slug, version, body, session.profile.user_id)
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{thread_id}}/comments",
    response_model=FeedbackThread,
    status_code=201,
    summary="Reply in my feedback thread",
    description=(
        "Add a message to one of the reader's own feedback threads. A resolved thread accepts it "
        "and stays resolved. Another reader's thread is `404 feedback-thread-not-found`.\n\n"
        "Requires a reader session for this tenant. Rate limited per reader."
    ),
)
def reply_to_my_feedback(
    tenant_slug: str,
    project_slug: str,
    version: str,
    thread_id: str,
    body: FeedbackReply,
    authorization: Optional[str] = Header(default=None),
) -> FeedbackThread:
    """Reply in a feedback thread.

    Args:
        tenant_slug: The portal.
        project_slug: The project.
        version: The version label.
        thread_id: The thread.
        body: The message.
        authorization: ``Reader <token>``.

    Returns:
        The thread with the new message.
    """
    session = _reader(authorization, tenant_slug)
    enforce_comment_rate_limit(session.tenant_id, session.profile.user_id)
    try:
        return store.reply_to_feedback(
            session.tenant_id, project_slug, version, thread_id, body.body, session.profile.user_id
        )
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


def _set_status(
    tenant_slug: str, project_slug: str, version: str, thread_id: str, status: str, authorization: Optional[str]
) -> FeedbackThread:
    """Shared body of the resolve and reopen routes."""
    session = _reader(authorization, tenant_slug)
    try:
        return store.set_feedback_status(
            session.tenant_id, project_slug, version, thread_id, status, session.profile.user_id
        )
    except CommentValidationError as exc:
        raise _http_error(exc) from exc


@router.post(
    f"{_BASE}/{{thread_id}}/resolve",
    response_model=FeedbackThread,
    summary="Resolve my feedback thread",
    description=(
        "Mark one of the reader's own threads resolved, as the team can from the Discussion panel. "
        "Resolving a resolved thread changes nothing. Requires a reader session for this tenant."
    ),
)
def resolve_my_feedback(
    tenant_slug: str,
    project_slug: str,
    version: str,
    thread_id: str,
    authorization: Optional[str] = Header(default=None),
) -> FeedbackThread:
    """Resolve a feedback thread."""
    return _set_status(tenant_slug, project_slug, version, thread_id, STATUS_RESOLVED, authorization)


@router.post(
    f"{_BASE}/{{thread_id}}/reopen",
    response_model=FeedbackThread,
    summary="Reopen my feedback thread",
    description=(
        "Reopen one of the reader's own resolved threads. Reopening an open thread changes nothing. "
        "Requires a reader session for this tenant."
    ),
)
def reopen_my_feedback(
    tenant_slug: str,
    project_slug: str,
    version: str,
    thread_id: str,
    authorization: Optional[str] = Header(default=None),
) -> FeedbackThread:
    """Reopen a feedback thread."""
    return _set_status(tenant_slug, project_slug, version, thread_id, STATUS_OPEN, authorization)
