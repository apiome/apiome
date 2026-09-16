"""Notification store — COL-3.1 (#4521).

Two jobs, either side of the inbox.

**Reading it.** The rules between the HTTP surface (:mod:`app.notification_routes`) and storage
(apiome-db V263) are short, because an inbox has exactly one reader:

* **Scope.** Every read and every mark-read is bound to the *authenticated* user in the
  *authenticated* tenant. There is no route that reads somebody else's inbox, so there is no RBAC
  resource to grant and no id a caller could substitute: naming another user's notification simply
  marks nothing.
* **Reading is not destructive.** Listing notifications never marks them read; only an explicit
  mark-read call moves ``read_at``, so the bell badge is the user's to clear.
* **Marking read is idempotent.** Re-marking an already-read notification changes nothing and is
  counted as nothing.

**Writing it.** The ``*_notifier`` builders turn "this event just happened" into the callable the
write accessors take. Each one resolves everything it needs **eagerly** and closes over it, so the
callable it returns is pure: it runs inside the caller's open transaction, where issuing another
query through :data:`app.database.db` would commit that transaction out from under the write it is
supposed to be part of.

Refusals raise :class:`app.notifications.NotificationValidationError` with a stable code.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import notification_fanout as fanout
from .database import db
from .notification_fanout import NotificationDraft
from .notifications import (
    CODE_FORBIDDEN,
    NOTIFICATION_TYPES,
    MarkReadRequest,
    MarkReadResponse,
    NotificationRecord,
    NotificationValidationError,
    UnreadCount,
)
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

__all__ = [
    "NotificationFilters",
    "Notifier",
    "comment_mention_notifier",
    "list_notifications",
    "mark_read",
    "require_recipient",
    "review_decision_notifier",
    "review_requested_notifier",
    "thread_resolved_notifier",
    "unread_count",
    "version_published_notifier",
]

#: What a write accessor calls inside its transaction: given what the write produced, the inbox
#: rows to write with it.
Notifier = Callable[[Mapping[str, Any]], Sequence[NotificationDraft]]

#: Columns of a notification row that belong on :class:`NotificationRecord`.
_NOTIFICATION_FIELDS = tuple(NotificationRecord.model_fields)


@dataclass(frozen=True)
class NotificationFilters:
    """What an inbox read narrows to.

    Attributes:
        unread: Only notifications the caller has not read.
        type: Only this notification type.
        limit: Page size.
        offset: Notifications to skip.
    """

    unread: bool = False
    type: Optional[str] = None
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def require_recipient(user_id: Optional[str]) -> str:
    """Require an inbox owner, and return their canonical id.

    Args:
        user_id: The authenticated user.

    Returns:
        The canonical user id.

    Raises:
        NotificationValidationError: ``notification-forbidden`` for a credential that resolves to
            no user — an API key with no user behind it has no inbox of its own.
    """
    text = str(user_id or "").strip()
    if not is_uuid_string(text):
        raise NotificationValidationError(
            CODE_FORBIDDEN, "notifications belong to a user; this credential resolves to none"
        )
    return str(uuid.UUID(text))


def _record(row: Mapping[str, Any]) -> NotificationRecord:
    """Map a notification row onto its record.

    Args:
        row: A row from an inbox read.

    Returns:
        The record.
    """
    values = {name: row.get(name) for name in _NOTIFICATION_FIELDS if name in row}
    values["payload"] = dict(values.get("payload") or {})
    return NotificationRecord(**values)


def list_notifications(
    tenant_id: str, user_id: str, filters: NotificationFilters
) -> Tuple[List[NotificationRecord], int]:
    """A page of the caller's inbox, newest first.

    Args:
        tenant_id: The caller's tenant.
        user_id: The caller.
        filters: What to narrow to.

    Returns:
        The page of records and the total matching the filters.
    """
    scope = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "unread_only": filters.unread,
        "type_filter": filters.type,
    }
    rows = db.list_notifications(**scope, limit=filters.limit, offset=filters.offset)
    total = db.count_notifications(**scope)
    return [_record(row) for row in rows], total


def unread_count(tenant_id: str, user_id: str) -> UnreadCount:
    """How much of the caller's inbox is unread, in total and per type.

    Every type is reported, zeroes included, so a client can render a stable set of counters
    without having to know which types exist.

    Args:
        tenant_id: The caller's tenant.
        user_id: The caller.

    Returns:
        The counts.
    """
    counted = db.count_unread_notifications_by_type(tenant_id=tenant_id, user_id=user_id)
    by_type = {name: int(counted.get(name, 0)) for name in NOTIFICATION_TYPES}
    # Sum the reported buckets rather than counting again: a type the database knows and this
    # build does not would otherwise vanish from the total the badge shows.
    for name, value in counted.items():
        if name not in by_type:
            by_type[name] = int(value)
    return UnreadCount(total=sum(by_type.values()), by_type=by_type)


def mark_read(tenant_id: str, user_id: str, request: MarkReadRequest) -> MarkReadResponse:
    """Mark some — or all — of the caller's notifications read.

    Args:
        tenant_id: The caller's tenant.
        user_id: The caller.
        request: The ids to mark, or ``all``.

    Returns:
        How many changed, and the unread count that follows.
    """
    updated = db.mark_notifications_read(
        tenant_id=tenant_id,
        user_id=user_id,
        notification_ids=None if request.all else (request.ids or []),
        all_unread=bool(request.all),
    )
    return MarkReadResponse(updated=int(updated), unread=unread_count(tenant_id, user_id))


# ---------------------------------------------------------------------------------------------
# Fan-out builders
#
# Each returns the callable a write accessor runs inside its transaction. Everything the callable
# needs is resolved here, before the transaction opens — see the module docstring.
# ---------------------------------------------------------------------------------------------


def comment_mention_notifier(
    *,
    project: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    anchor_type: str,
    anchor_id: Optional[str],
    actor_id: Optional[str],
    body: str,
    mentions: Sequence[str],
    already_mentioned: Iterable[str] = (),
) -> Optional[Notifier]:
    """"@you" for the members a comment names.

    Args:
        project: The project row.
        version: The version row the thread hangs off.
        anchor_type: The kind of element the thread is anchored to.
        anchor_id: That element's id.
        actor_id: The comment's author.
        body: The comment's Markdown, for the excerpt.
        mentions: The user ids the body resolved to.
        already_mentioned: Members the previous text of an edited comment already named.

    Returns:
        The notifier, or ``None`` when the comment names nobody new — so an ordinary reply adds no
        statement to its own transaction.
    """
    fresh = fanout.recipients(mentions, exclude=[actor_id, *already_mentioned])
    if not fresh:
        return None

    def notify(produced: Mapping[str, Any]) -> Sequence[NotificationDraft]:
        return fanout.mention_drafts(
            mentioned=fresh,
            actor_id=actor_id,
            project=project,
            version=version,
            thread_id=str(produced.get("thread_id") or ""),
            comment_id=str(produced.get("comment_id") or ""),
            anchor_type=anchor_type,
            anchor_id=anchor_id,
            body=body,
        )

    return notify


def thread_resolved_notifier(
    *,
    project: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    thread: Mapping[str, Any],
    actor_id: Optional[str],
) -> Optional[Notifier]:
    """"the thread you were in was resolved" for everyone who took part in it.

    The participants are read here, before the write opens its transaction.

    Args:
        project: The project row.
        version: The version row.
        thread: The thread row being resolved.
        actor_id: Who is resolving it.

    Returns:
        The notifier, or ``None`` when nobody but the actor took part.
    """
    participants: List[Any] = [thread.get("created_by")]
    participants.extend(
        row.get("author_id") for row in db.list_comments(thread_id=str(thread.get("id")))
    )
    people = fanout.recipients(participants, exclude=[actor_id])
    if not people:
        return None

    def notify(produced: Mapping[str, Any]) -> Sequence[NotificationDraft]:
        return fanout.thread_resolved_drafts(
            participants=people,
            actor_id=actor_id,
            project=project,
            version=version,
            thread_id=str(produced.get("thread_id") or thread.get("id") or ""),
            anchor_type=str(thread.get("anchor_type") or ""),
            anchor_id=thread.get("anchor_id"),
        )

    return notify


def review_requested_notifier(
    *,
    project: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    actor_id: Optional[str],
    reviewers: Sequence[str],
) -> Optional[Notifier]:
    """"you were asked to review this" for the reviewers of the round being opened.

    Args:
        project: The project row.
        version: The version row.
        actor_id: Who is asking.
        reviewers: The round's reviewers.

    Returns:
        The notifier, or ``None`` when there is nobody to ask.
    """
    people = fanout.recipients(reviewers, exclude=[actor_id])
    if not people:
        return None

    def notify(produced: Mapping[str, Any]) -> Sequence[NotificationDraft]:
        return fanout.review_requested_drafts(
            reviewers=people,
            actor_id=actor_id,
            project=project,
            version=version,
            review_id=str(produced.get("review_id") or ""),
            round=int(produced.get("round") or 1),
        )

    return notify


def review_decision_notifier(
    *,
    project: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    actor_id: Optional[str],
    requested_by: Optional[str],
) -> Optional[Notifier]:
    """"your review was decided" for the member who asked for it.

    Args:
        project: The project row.
        version: The version row.
        actor_id: The deciding reviewer.
        requested_by: Who requested the review.

    Returns:
        The notifier, or ``None`` when the requester is gone or is the one deciding.
    """
    if not fanout.recipients([requested_by], exclude=[actor_id]):
        return None

    def notify(produced: Mapping[str, Any]) -> Sequence[NotificationDraft]:
        return fanout.review_decision_drafts(
            requested_by=requested_by,
            actor_id=actor_id,
            project=project,
            version=version,
            review_id=str(produced.get("review_id") or ""),
            round=int(produced.get("round") or 1),
            decision=str(produced.get("decision") or ""),
        )

    return notify


def version_published_notifier(
    *,
    tenant_id: str,
    project: Mapping[str, Any],
    version: Optional[Mapping[str, Any]],
    actor_id: Optional[str],
) -> Optional[Notifier]:
    """"the version you worked on was published" for its collaborators.

    The collaborator set is resolved here, before the publish opens its transaction.

    Args:
        tenant_id: The tenant.
        project: The project row.
        version: The version row being published.
        actor_id: Who is publishing.

    Returns:
        The notifier, or ``None`` when nobody but the publisher worked on the version.
    """
    try:
        collaborators = db.list_version_collaborators(
            tenant_id=tenant_id,
            project_id=str((project or {}).get("id") or ""),
            version_id=str((version or {}).get("id") or ""),
        )
    except Exception:  # pragma: no cover - defensive; a publish must not fail over its inbox rows
        logger.warning("notification fan-out: could not resolve publish collaborators", exc_info=True)
        return None
    people = fanout.recipients(collaborators, exclude=[actor_id])
    if not people:
        return None

    def notify(_produced: Mapping[str, Any]) -> Sequence[NotificationDraft]:
        return fanout.version_published_drafts(
            collaborators=people, actor_id=actor_id, project=project, version=version
        )

    return notify
