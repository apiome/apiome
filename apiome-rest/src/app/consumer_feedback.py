"""Portal consumer feedback — the reader-facing vocabulary of COL-4.4 (#4528).

A Browse **reader** (PCX-1.1, :mod:`app.portal_auth`) who is reading a published spec can open a
**feedback thread** on the whole version or on one of its operations. A feedback thread is an
ordinary COL-1.1 comment thread with ``origin = 'consumer'`` (apiome-db V379), so the owning team
sees it, replies to it, and resolves it in the Discussion panel with the tools it already has.

What the reader sees is deliberately narrower than what the team sees, because a reader is not a
workspace member:

* **Only their own threads.** One customer's feedback is never shown to another.
* **No internal identifiers.** No user ids, no ``mentions``, no tenant or project ids — a comment
  says only whether it came **from the team** and who wrote it.
* **No ``@mentions``.** A reader's comment never resolves ``@name`` tokens against the tenant's
  members, so feedback can neither notify staff directly nor probe who works there.
* **Version and operation anchors only.** That is what Browse shows a reader; an operation is named
  by HTTP method and path, the way the spec names it, and stored as the COL-1.1 ``operation`` anchor.

This module holds only data — models and refusal codes. The behaviour is
:mod:`app.consumer_feedback_store`; the routes are :mod:`app.consumer_feedback_routes`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .comments import MAX_BODY_LENGTH

__all__ = [
    "CODE_FEEDBACK_OPERATION_NOT_FOUND",
    "CODE_FEEDBACK_THREAD_NOT_FOUND",
    "CODE_FEEDBACK_VERSION_NOT_FOUND",
    "FeedbackComment",
    "FeedbackCreate",
    "FeedbackOperation",
    "FeedbackReply",
    "FeedbackThread",
    "FeedbackThreadList",
    "FeedbackTarget",
]

# Stable refusal codes (alongside the COL-1.1 ``comment-*`` codes the store may also raise).
CODE_FEEDBACK_VERSION_NOT_FOUND = "feedback-version-not-found"
CODE_FEEDBACK_OPERATION_NOT_FOUND = "feedback-operation-not-found"
CODE_FEEDBACK_THREAD_NOT_FOUND = "feedback-thread-not-found"

#: What a reader can give feedback on.
FeedbackTarget = Literal["version", "operation"]

#: The longest HTTP method token accepted (``path_operation.operation`` is ``VARCHAR(50)``).
_MAX_METHOD = 16
#: The longest path template accepted.
_MAX_PATH = 2048


class FeedbackOperation(BaseModel):
    """An operation, named the way the spec names it."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="HTTP method, upper case (`GET`).")
    path: str = Field(description="Path template as published (`/pets/{petId}`).")


class FeedbackComment(BaseModel):
    """One message in a feedback thread, as the reader sees it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    body: str = Field(description="Markdown.")
    from_team: bool = Field(description="True when a member of the owning team wrote it; false for the reader.")
    author_name: Optional[str] = Field(default=None, description="The writer's display name.")
    created_at: datetime
    edited_at: Optional[datetime] = None


class FeedbackThread(BaseModel):
    """A reader's feedback thread with every message in it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    target: FeedbackTarget = Field(description="`version` — the whole API; `operation` — one operation.")
    operation: Optional[FeedbackOperation] = Field(
        default=None, description="The operation, for an `operation` target that still exists."
    )
    status: Literal["open", "resolved"] = Field(description="`open` or `resolved` (by the team or the reader).")
    resolved_at: Optional[datetime] = None
    created_at: datetime
    last_activity_at: datetime
    comments: List[FeedbackComment] = Field(default_factory=list, description="Oldest first.")


class FeedbackThreadList(BaseModel):
    """The reader's own feedback threads on one version."""

    model_config = ConfigDict(extra="forbid")

    threads: List[FeedbackThread] = Field(default_factory=list, description="Most recently active first.")


class FeedbackCreate(BaseModel):
    """Open a feedback thread.

    Attributes:
        target: ``version`` for the whole API, ``operation`` for one operation.
        method: The operation's HTTP method (``operation`` only).
        path: The operation's path template (``operation`` only).
        body: The first message, as Markdown.
    """

    model_config = ConfigDict(extra="forbid")

    target: FeedbackTarget
    method: Optional[str] = Field(default=None, min_length=1, max_length=_MAX_METHOD)
    path: Optional[str] = Field(default=None, min_length=1, max_length=_MAX_PATH)
    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)

    @model_validator(mode="after")
    def _operation_needs_method_and_path(self) -> "FeedbackCreate":
        """An ``operation`` target names its method and path; a ``version`` target names neither."""
        if self.target == "operation" and not (self.method and self.path):
            raise ValueError("an operation target needs `method` and `path`")
        if self.target == "version" and (self.method or self.path):
            raise ValueError("a version target takes no `method` or `path`")
        return self


class FeedbackReply(BaseModel):
    """A message added to a feedback thread."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=MAX_BODY_LENGTH)
