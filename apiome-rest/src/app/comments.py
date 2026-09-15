"""Comment threads and comments — the shared vocabulary of COL-1.1 (#4513).

A **thread** is one conversation anchored to one element of one project version: a class, a
property, a path, an operation, or the version itself. It is anchored by the element's stable
primary key, never by where the element happens to sit on a canvas, so renaming or moving the
element keeps the thread on it. A thread is ``open`` or ``resolved``, or — once its element has
been deleted — ``orphaned`` (COL-1.4, #4516): it keeps its comments and the element's last-known
label until someone relinks it to another element. Its **comments** are Markdown replies, each
recording the tenant members its ``@name`` tokens resolved to (see :mod:`app.comment_mentions`).

This module holds only data: the vocabularies, the stable refusal codes, the refusal exception, and
the request/response models the routes (:mod:`app.comment_routes`) and the store
(:mod:`app.comment_store`) share. The storage lives in apiome-db V259 and V260.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ANCHOR_TYPES",
    "ANCHOR_VERSION",
    "CODE_ANCHOR_NOT_FOUND",
    "CODE_COMMENT_NOT_FOUND",
    "CODE_EMPTY_BODY",
    "CODE_FORBIDDEN",
    "CODE_INVALID_ANCHOR",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_RATE_LIMITED",
    "CODE_THREAD_NOT_FOUND",
    "CODE_THREAD_NOT_ORPHANED",
    "CODE_THREAD_ORPHANED",
    "CODE_VERSION_NOT_FOUND",
    "MAX_BODY_LENGTH",
    "STATUS_OPEN",
    "STATUS_ORPHANED",
    "STATUS_RESOLVED",
    "THREAD_STATUSES",
    "AnchorType",
    "CommentBody",
    "CommentRecord",
    "CommentThreadCreate",
    "CommentThreadDetail",
    "CommentThreadRecord",
    "CommentThreadRelink",
    "CommentThreadSummary",
    "CommentValidationError",
    "ThreadStatus",
]

#: The element kinds a thread may anchor to. Mirrors ``comment_threads_anchor_type_check``.
ANCHOR_TYPES = ("class", "property", "path", "operation", "version")

#: The anchor kind whose id is the thread's own version id.
ANCHOR_VERSION = "version"

#: Thread states. Mirrors ``comment_threads_status_check`` (V259 added the first two, V260
#: ``orphaned``). Only the database orphans a thread — a trigger fires when the anchored element is
#: deleted — and only a relink takes a thread out of that state.
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_ORPHANED = "orphaned"
THREAD_STATUSES = (STATUS_OPEN, STATUS_RESOLVED, STATUS_ORPHANED)

#: The longest comment body, in characters. Mirrors ``comments_body_check``.
MAX_BODY_LENGTH = 20_000

AnchorType = Literal["class", "property", "path", "operation", "version"]
ThreadStatus = Literal["open", "resolved", "orphaned"]

# Stable refusal codes. A client branches on the code, never on the message.
CODE_PROJECT_NOT_FOUND = "comment-project-not-found"
CODE_VERSION_NOT_FOUND = "comment-version-not-found"
CODE_ANCHOR_NOT_FOUND = "comment-anchor-not-found"
CODE_INVALID_ANCHOR = "comment-invalid-anchor"
CODE_THREAD_NOT_FOUND = "comment-thread-not-found"
CODE_COMMENT_NOT_FOUND = "comment-not-found"
CODE_EMPTY_BODY = "comment-empty-body"
CODE_FORBIDDEN = "comment-forbidden"
CODE_RATE_LIMITED = "comment-rate-limited"
#: Resolving or reopening a thread whose element was deleted; relink it first.
CODE_THREAD_ORPHANED = "comment-thread-orphaned"
#: Relinking a thread that is still anchored to a live element.
CODE_THREAD_NOT_ORPHANED = "comment-thread-not-orphaned"


class CommentValidationError(Exception):
    """A refusal from the comment store, carrying a stable code.

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


class CommentRecord(BaseModel):
    """One stored comment."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The comment id.")
    thread_id: str = Field(description="The thread the comment belongs to.")
    author_id: Optional[str] = Field(
        default=None, description="Who wrote it; null once that user has been deleted."
    )
    author_name: Optional[str] = Field(default=None, description="The author's display name.")
    body: str = Field(description="The comment text, as Markdown.")
    mentions: List[str] = Field(
        default_factory=list,
        description=(
            "User ids of the tenant members the body's `@name` tokens resolved to, server-side, "
            "when the comment was last written."
        ),
    )
    edited_at: Optional[datetime] = Field(
        default=None, description="When the comment was last edited; null when never edited."
    )
    created_at: datetime = Field(description="When the comment was written.")


class CommentThreadRecord(BaseModel):
    """One stored thread, without its comments."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="The thread id.")
    tenant_id: str
    project_id: str
    version_id: str = Field(description="The version (revision) whose element is discussed.")
    anchor_type: AnchorType = Field(description="The kind of element the thread is anchored to.")
    anchor_id: str = Field(
        description=(
            "The anchored element's stable id. Equals `version_id` for a version anchor. On an "
            "orphaned thread it is the id of the element that was deleted."
        )
    )
    status: ThreadStatus = Field(
        description=(
            "`open`, `resolved`, or `orphaned` — the anchored element was deleted; relink the "
            "thread to re-attach it."
        )
    )
    anchor_label: Optional[str] = Field(
        default=None,
        description=(
            "The deleted element's last-known label (`Customer`, `Customer.email`, `/customers`, "
            "`GET /customers`), captured when it was deleted. Set exactly while `orphaned`."
        ),
    )
    orphaned_at: Optional[datetime] = Field(
        default=None, description="When the anchored element was deleted. Set exactly while `orphaned`."
    )
    created_by: Optional[str] = Field(default=None, description="Who opened the thread.")
    created_by_name: Optional[str] = Field(default=None, description="Their display name.")
    resolved_by: Optional[str] = Field(default=None, description="Who resolved it, when resolved.")
    resolved_at: Optional[datetime] = Field(default=None, description="When it was resolved.")
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime = Field(description="The latest reply or status change.")
    comment_count: int = Field(default=0, ge=0, description="How many comments the thread holds.")


class CommentThreadSummary(CommentThreadRecord):
    """A thread as a list read returns it: the thread plus its opening comment."""

    root_comment: Optional[CommentRecord] = Field(
        default=None, description="The comment that opened the thread."
    )


class CommentThreadDetail(BaseModel):
    """A thread with every comment in it."""

    model_config = ConfigDict(extra="forbid")

    thread: CommentThreadRecord
    comments: List[CommentRecord] = Field(
        default_factory=list, description="The thread's comments, oldest first."
    )


class CommentThreadCreate(BaseModel):
    """Open a thread on an element, with its first comment.

    Attributes:
        version: The version the element belongs to — its revision id or its version label.
        anchor_type: The kind of element.
        anchor_id: The element's stable id. Optional for a version anchor, where it can only be
            the version's own id.
        body: The first comment, as Markdown.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=255)
    anchor_type: AnchorType
    anchor_id: Optional[str] = Field(default=None, max_length=64)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)


class CommentThreadRelink(BaseModel):
    """Re-attach an orphaned thread to another element of its own version.

    Attributes:
        anchor_type: The kind of element to attach to.
        anchor_id: That element's stable id. Optional for a version anchor, where it can only be
            the thread's own version id.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_type: AnchorType
    anchor_id: Optional[str] = Field(default=None, max_length=64)


class CommentBody(BaseModel):
    """A comment's Markdown text, for a reply or an edit."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
