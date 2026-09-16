"""``/v1/tenants/{tenant_slug}/notifications`` — COL-3.1 (#4521).

The HTTP surface of the notification inbox: read what needs the caller's attention, count what they
have not read yet, and mark notifications read. The rows themselves are written by the events that
cause them — a comment that mentions somebody, a review request or decision, a resolved thread, a
publish — in those events' own transactions (:mod:`app.notification_store`), so there is no endpoint
that creates a notification and no way for a client to page somebody else.

**Authorization.** There is no notification RBAC resource, and deliberately so: an inbox is the
caller's own. Every route resolves the authenticated user and scopes to their rows in their tenant,
which is a narrower guarantee than any ``resource:action`` could express — a tenant administrator
does not read a colleague's inbox either. A credential that resolves to no user (a legacy API key
with no user behind it) has no inbox and is answered ``403 notification-forbidden``.

**Freshness.** Listing never marks anything read; the badge is cleared by
``POST …/notifications/read`` and nothing else.

These endpoints are what the notification centre of COL-3.2 (#4522) — the bell, its dropdown, its
mark-all-read, and the full page — is built on.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from . import notification_store
from .auth import validate_authentication
from .database import db
from .notification_store import NotificationFilters
from .notifications import (
    CODE_FORBIDDEN,
    MarkReadRequest,
    MarkReadResponse,
    NotificationListResponse,
    NotificationType,
    NotificationValidationError,
    UnreadCount,
)
from .permissions import resolve_actor_id

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["notifications"])

#: A refusal maps onto the HTTP status of its kind; anything else is a 400.
_STATUS_BY_CODE = {CODE_FORBIDDEN: 403}

_BASE = "/{tenant_slug}/notifications"


def _caller(auth_data: Dict[str, Any]) -> tuple[str, str]:
    """Resolve the inbox this request is about: ``(tenant_id, user_id)``.

    Args:
        auth_data: The authenticated principal.

    Returns:
        The tenant and the user whose inbox it is.

    Raises:
        HTTPException: 403 without a tenant, or for a credential that resolves to no user.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    try:
        user_id = notification_store.require_recipient(resolve_actor_id(db, auth_data))
    except NotificationValidationError as exc:
        raise _http_error(exc) from exc
    return str(tenant_id), user_id


def _http_error(exc: NotificationValidationError) -> HTTPException:
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


@router.get(
    _BASE,
    response_model=NotificationListResponse,
    summary="List the caller's notifications",
    description=(
        "A page of the caller's own inbox in this tenant, newest first. Each row carries the "
        "event's `type`, the `payload` its sentence and deep link need, who caused it, and the "
        "project and version it points at.\n\n"
        "Filters combine: `unread` (only what has not been read) and `type`.\n\n"
        "Reading the list never marks anything read. Requires only authentication — an inbox is "
        "the caller's own, so there is no permission to grant."
    ),
)
async def list_notifications(
    tenant_slug: str,
    unread: bool = Query(default=False, description="Only unread notifications."),
    type: Optional[NotificationType] = Query(default=None, description="Only this event type."),
    limit: int = Query(default=50, ge=1, le=200, description="Page size."),
    offset: int = Query(default=0, ge=0, description="Notifications to skip."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> NotificationListResponse:
    """List the caller's notifications.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what scopes the read).
        unread: Only unread notifications.
        type: Only this event type.
        limit: Page size.
        offset: Notifications to skip.
        auth_data: The authenticated principal.

    Returns:
        The page and the total.

    Raises:
        HTTPException: 403 for a credential with no tenant or no user behind it.
    """
    tenant_id, user_id = _caller(auth_data)
    _ = tenant_slug
    filters = NotificationFilters(unread=unread, type=type, limit=limit, offset=offset)
    records, total = notification_store.list_notifications(tenant_id, user_id, filters)
    return NotificationListResponse(
        notifications=records, count=len(records), total=total, limit=limit, offset=offset
    )


@router.get(
    f"{_BASE}/unread-count",
    response_model=UnreadCount,
    summary="Count the caller's unread notifications",
    description=(
        "How many notifications the caller has not read in this tenant, in total and per type "
        "(every type is reported, zeroes included). This is the bell badge.\n\n"
        "Requires only authentication."
    ),
)
async def unread_notification_count(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UnreadCount:
    """Count the caller's unread notifications.

    Args:
        tenant_slug: The tenant in the URL.
        auth_data: The authenticated principal.

    Returns:
        The unread counts.

    Raises:
        HTTPException: 403 for a credential with no tenant or no user behind it.
    """
    tenant_id, user_id = _caller(auth_data)
    _ = tenant_slug
    return notification_store.unread_count(tenant_id, user_id)


@router.post(
    f"{_BASE}/read",
    response_model=MarkReadResponse,
    summary="Mark the caller's notifications read",
    description=(
        "Mark the notifications named by `ids` read, or the caller's whole inbox with "
        "`{\"all\": true}`. Marking is idempotent: a notification that was already read is not "
        "counted again, and an id that is not the caller's own simply matches nothing.\n\n"
        "Answers with how many rows changed and the unread count that follows, so a client can "
        "update its badge without a second call.\n\n"
        "Requires only authentication."
    ),
)
async def mark_notifications_read(
    tenant_slug: str,
    body: MarkReadRequest = Body(default_factory=MarkReadRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MarkReadResponse:
    """Mark notifications read.

    Args:
        tenant_slug: The tenant in the URL.
        body: The ids to mark, or ``all``.
        auth_data: The authenticated principal.

    Returns:
        How many changed, and the unread count after the change.

    Raises:
        HTTPException: 403 for a credential with no tenant or no user behind it.
    """
    tenant_id, user_id = _caller(auth_data)
    _ = tenant_slug
    return notification_store.mark_read(tenant_id, user_id, body)
