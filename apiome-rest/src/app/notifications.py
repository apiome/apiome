"""Notification inbox — the shared vocabulary of COL-3.1 (#4521).

A **notification** is one recipient's copy of one collaboration event: somebody mentioned them in a
comment (COL-1.1, #4513), asked them to review a version (COL-2.1, #4517), decided a review they
requested, resolved a thread they took part in, or published a version they worked on. Each row is
written in the same transaction as the event that caused it, so a committed event and its inbox
rows can never diverge.

This module holds only data: the type vocabulary, the retention cap the database keeps, the stable
refusal codes, the refusal exception, and the request/response models the routes
(:mod:`app.notification_routes`) and the store (:mod:`app.notification_store`) share. Which users an
event concerns is :mod:`app.notification_fanout`; the storage lives in apiome-db V263.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_FORBIDDEN",
    "CODE_INVALID_REQUEST",
    "MAX_EXCERPT_LENGTH",
    "MAX_MARK_READ_IDS",
    "MAX_RECIPIENTS",
    "NOTIFICATION_TYPES",
    "RETENTION_PER_USER",
    "TYPE_MENTION",
    "TYPE_REVIEW_DECISION",
    "TYPE_REVIEW_REQUESTED",
    "TYPE_THREAD_RESOLVED",
    "TYPE_VERSION_PUBLISHED",
    "MarkReadRequest",
    "MarkReadResponse",
    "NotificationListResponse",
    "NotificationRecord",
    "NotificationType",
    "NotificationValidationError",
    "UnreadCount",
]

#: Somebody named the recipient with an ``@name`` token in a comment.
TYPE_MENTION = "mention"
#: The recipient was asked to review a version (a new review, or a new round of one).
TYPE_REVIEW_REQUESTED = "review_requested"
#: A reviewer approved or requested changes on a review the recipient requested.
TYPE_REVIEW_DECISION = "review_decision"
#: A thread the recipient took part in was resolved.
TYPE_THREAD_RESOLVED = "thread_resolved"
#: A version the recipient collaborated on was published.
TYPE_VERSION_PUBLISHED = "version_published"

#: The whole vocabulary. Mirrors ``notifications_type_check`` in apiome-db V263.
NOTIFICATION_TYPES = (
    TYPE_MENTION,
    TYPE_REVIEW_REQUESTED,
    TYPE_REVIEW_DECISION,
    TYPE_THREAD_RESOLVED,
    TYPE_VERSION_PUBLISHED,
)

NotificationType = Literal[
    "mention", "review_requested", "review_decision", "thread_resolved", "version_published"
]

#: Newest rows kept per user. Mirrors ``retention_cap`` in V263's pruning trigger, which is what
#: actually enforces it — this constant is for documentation and for the tests that hold the two
#: together.
RETENTION_PER_USER = 500

#: Longest comment excerpt carried in a payload. An inbox row is a pointer, not a copy.
MAX_EXCERPT_LENGTH = 280

#: Most recipients one event may fan out to. A comment caps mentions at 50 and a review caps
#: reviewers at 20; this is the backstop for the collaborator sets a publish resolves.
MAX_RECIPIENTS = 200

#: Most notification ids one mark-read call may name.
MAX_MARK_READ_IDS = 500

# Stable refusal codes. A client branches on the code, never on the message.
CODE_FORBIDDEN = "notification-forbidden"
CODE_INVALID_REQUEST = "notification-invalid-request"


class NotificationValidationError(Exception):
    """A refusal from the notification store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


class NotificationRecord(BaseModel):
    """One stored notification, as the caller's inbox returns it."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The notification id.")
    tenant_id: str
    user_id: str = Field(description="The recipient — always the calling user.")
    type: NotificationType = Field(description="Which kind of event this is.")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "What the notification's sentence and deep link need: `project_slug`, `project_name` "
            "and `version_label` throughout, plus `thread_id`/`comment_id`/`anchor_type`/"
            "`anchor_id`/`excerpt` for a comment event and `review_id`/`round`/`decision` for a "
            "review one."
        ),
    )
    actor_id: Optional[str] = Field(
        default=None, description="Who caused the event; null once that user has been deleted."
    )
    actor_name: Optional[str] = Field(default=None, description="Their display name, read fresh.")
    project_id: Optional[str] = Field(default=None, description="The project the event happened in.")
    version_id: Optional[str] = Field(default=None, description="The version the event happened on.")
    read_at: Optional[datetime] = Field(
        default=None, description="When the recipient read it; null exactly while unread."
    )
    created_at: datetime = Field(description="When the event happened.")


class NotificationListResponse(BaseModel):
    """A page of the caller's inbox."""

    model_config = ConfigDict(extra="forbid")

    notifications: List[NotificationRecord] = Field(
        default_factory=list, description="Notifications, newest first."
    )
    count: int = Field(description="How many notifications this page holds.")
    total: int = Field(description="How many match the filters in all.")
    limit: int = Field(description="The page size used.")
    offset: int = Field(description="The offset used.")


class UnreadCount(BaseModel):
    """How much of the caller's inbox is unread — the bell badge (COL-3.2)."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0, description="Unread notifications in this tenant.")
    by_type: Dict[str, int] = Field(
        default_factory=dict,
        description="Unread count per type; every type is present, zeroes included.",
    )


class MarkReadRequest(BaseModel):
    """Mark some — or all — of the caller's notifications read.

    Attributes:
        ids: The notifications to mark. Ignored when ``all`` is set.
        all: Mark every unread notification of the caller in this tenant.
    """

    model_config = ConfigDict(extra="forbid")

    ids: Optional[List[str]] = Field(
        default=None, max_length=MAX_MARK_READ_IDS, description="Notification ids to mark read."
    )
    all: bool = Field(default=False, description="Mark the caller's whole inbox read instead.")


class MarkReadResponse(BaseModel):
    """What a mark-read call changed."""

    model_config = ConfigDict(extra="forbid")

    updated: int = Field(ge=0, description="How many notifications went from unread to read.")
    unread: UnreadCount = Field(description="The caller's unread count after the change.")
