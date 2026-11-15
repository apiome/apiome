"""Portal consumer feedback threads — COL-4.4 (#4528).

A Browse reader opens, reads, answers, resolves and reopens **their own** feedback threads on a
published, public version. The threads are COL-1.1 comment threads with ``origin = 'consumer'``, so
every write goes through the same tables (and, for status, the same :func:`comment_store
.set_thread_status`) as internal discussion — the team's side needs no new code to reply or resolve.

What differs from :mod:`app.comment_store`, and why:

* **The reader is not a member.** Their ``users`` row has no ``tenant_users`` membership, so nothing
  here checks ``projects:view``; the caller has proved a live reader session for this tenant
  (:func:`app.auth.resolve_reader_session_header`) and every read is narrowed to threads that reader
  opened (``created_by``). Another reader's thread is a ``404``, never a ``403``, so ids cannot be
  probed.
* **No mentions.** Reader messages are stored with an empty ``mentions`` list and no notifier —
  ``resolve_body_mentions`` is never called.
* **Only what Browse shows.** The version must be published and public (until PCX-1.3 adds private
  versions for readers), and the anchor is the version or one operation by method + path.
* **Nothing internal leaks out.** :func:`_feedback_thread` maps rows onto
  :class:`~app.consumer_feedback.FeedbackThread`, which has no user ids, mentions or internal
  statuses (an ``orphaned`` thread reads as ``open`` with no operation).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from . import comment_store
from .comments import (
    ANCHOR_VERSION,
    CODE_FORBIDDEN,
    ORIGIN_CONSUMER,
    STATUS_RESOLVED,
    CommentValidationError,
)
from .consumer_feedback import (
    CODE_FEEDBACK_OPERATION_NOT_FOUND,
    CODE_FEEDBACK_THREAD_NOT_FOUND,
    CODE_FEEDBACK_VERSION_NOT_FOUND,
    FeedbackComment,
    FeedbackCreate,
    FeedbackOperation,
    FeedbackThread,
)
from .database import db

__all__ = ["list_feedback", "open_feedback", "reply_to_feedback", "set_feedback_status"]

#: The most threads one read returns. A reader's own feedback on one version is a short list.
MAX_THREADS = 100


def _version(tenant_id: str, project_slug: str, version_label: str) -> Dict[str, Any]:
    """Resolve the published, public version the reader is looking at.

    Args:
        tenant_id: The reader's tenant.
        project_slug: The project slug in the URL.
        version_label: The version label in the URL.

    Returns:
        The version row (``id``, ``project_id``, ``version_id``, …).

    Raises:
        CommentValidationError: ``feedback-version-not-found`` when there is no such published,
            public version — the same answer for unknown, unpublished and private versions.
    """
    row = db.get_published_public_version(
        tenant_id=tenant_id, project_slug=project_slug, version_label=version_label
    )
    if not row:
        raise CommentValidationError(
            CODE_FEEDBACK_VERSION_NOT_FOUND, f"no published version '{version_label}' of '{project_slug}'"
        )
    return row


def _own_thread(tenant_id: str, version: Mapping[str, Any], thread_id: str, reader_id: str) -> Dict[str, Any]:
    """Read a feedback thread the reader opened on this version, or refuse as not found.

    Args:
        tenant_id: The reader's tenant.
        version: The version row from :func:`_version`.
        thread_id: The thread.
        reader_id: The reader's user id.

    Returns:
        The thread row.

    Raises:
        CommentValidationError: ``feedback-thread-not-found`` for an unknown thread, an internal
            thread, another reader's thread, or a thread on another version.
    """
    row = db.get_comment_thread(
        tenant_id=tenant_id, project_id=str(version["project_id"]), thread_id=thread_id
    )
    if (
        not row
        or row.get("origin") != ORIGIN_CONSUMER
        or str(row.get("created_by") or "") != str(reader_id)
        or str(row.get("version_id")) != str(version["id"])
    ):
        raise CommentValidationError(CODE_FEEDBACK_THREAD_NOT_FOUND, f"no feedback thread '{thread_id}'")
    return row


def _feedback_thread(
    row: Mapping[str, Any],
    comments: List[Mapping[str, Any]],
    operations: Mapping[str, Mapping[str, str]],
) -> FeedbackThread:
    """Map a thread and its comments onto what the reader may see.

    Args:
        row: The thread row.
        comments: Its comment rows, oldest first.
        operations: ``{operation_id: {"method", "path"}}`` for operation anchors.

    Returns:
        The reader-facing thread.
    """
    reader_id = str(row.get("created_by") or "")
    is_operation = row.get("anchor_type") == "operation"
    coordinates = operations.get(str(row.get("anchor_id"))) if is_operation else None
    return FeedbackThread(
        id=str(row["id"]),
        target="operation" if is_operation else "version",
        operation=FeedbackOperation(**coordinates) if coordinates else None,
        status=STATUS_RESOLVED if row.get("status") == STATUS_RESOLVED else "open",
        resolved_at=row.get("resolved_at") if row.get("status") == STATUS_RESOLVED else None,
        created_at=row["created_at"],
        last_activity_at=row["last_activity_at"],
        comments=[
            FeedbackComment(
                id=str(comment["id"]),
                body=str(comment["body"]),
                from_team=str(comment.get("author_id") or "") != reader_id,
                author_name=comment.get("author_name"),
                created_at=comment["created_at"],
                edited_at=comment.get("edited_at"),
            )
            for comment in comments
        ],
    )


def _render(rows: List[Mapping[str, Any]]) -> List[FeedbackThread]:
    """Load each thread's comments and its operation's coordinates, and map them.

    Args:
        rows: Thread rows.

    Returns:
        The reader-facing threads, in the rows' order.
    """
    operations = db.get_operation_coordinates(
        [str(row["anchor_id"]) for row in rows if row.get("anchor_type") == "operation"]
    )
    return [_feedback_thread(row, db.list_comments(thread_id=str(row["id"])), operations) for row in rows]


def list_feedback(tenant_id: str, project_slug: str, version_label: str, reader_id: str) -> List[FeedbackThread]:
    """The reader's own feedback threads on a version, most recently active first.

    Args:
        tenant_id: The reader's tenant.
        project_slug: The project slug.
        version_label: The version label.
        reader_id: The reader's user id.

    Returns:
        The threads, each with all of its messages.

    Raises:
        CommentValidationError: ``feedback-version-not-found``.
    """
    version = _version(tenant_id, project_slug, version_label)
    rows = db.list_comment_threads(
        tenant_id=tenant_id,
        project_id=str(version["project_id"]),
        version_id=str(version["id"]),
        origin=ORIGIN_CONSUMER,
        created_by=reader_id,
        limit=MAX_THREADS,
        offset=0,
    )
    return _render(rows)


def open_feedback(
    tenant_id: str, project_slug: str, version_label: str, request: FeedbackCreate, reader_id: str
) -> FeedbackThread:
    """Open a ``consumer`` thread on the version or one of its operations.

    Args:
        tenant_id: The reader's tenant.
        project_slug: The project slug.
        version_label: The version label.
        request: The target and the first message.
        reader_id: The reader's user id.

    Returns:
        The new thread.

    Raises:
        CommentValidationError: ``feedback-version-not-found``, ``feedback-operation-not-found``,
            or ``comment-empty-body``.
    """
    body = comment_store._require_body(request.body)
    version = _version(tenant_id, project_slug, version_label)
    version_id = str(version["id"])
    if request.target == "operation":
        anchor_type = "operation"
        anchor_id = db.find_version_operation(
            version_id=version_id, method=str(request.method).strip(), path=str(request.path).strip()
        )
        if not anchor_id:
            raise CommentValidationError(
                CODE_FEEDBACK_OPERATION_NOT_FOUND,
                f"version '{version_label}' has no operation {str(request.method).upper()} {request.path}",
            )
    else:
        anchor_type, anchor_id = ANCHOR_VERSION, version_id

    inserted = db.insert_comment_thread(
        tenant_id=tenant_id,
        project_id=str(version["project_id"]),
        version_id=version_id,
        anchor_type=anchor_type,
        anchor_id=anchor_id,
        created_by=reader_id,
        body=body,
        mentions=[],
        notify=None,
        origin=ORIGIN_CONSUMER,
    )
    if not inserted:
        raise CommentValidationError(CODE_FORBIDDEN, "feedback must be attributable to a reader")
    row = _own_thread(tenant_id, version, str(inserted["thread_id"]), reader_id)
    return _render([row])[0]


def reply_to_feedback(
    tenant_id: str, project_slug: str, version_label: str, thread_id: str, body: str, reader_id: str
) -> FeedbackThread:
    """Add the reader's message to their thread. A resolved thread accepts it and stays resolved.

    Args:
        tenant_id: The reader's tenant.
        project_slug: The project slug.
        version_label: The version label.
        thread_id: The thread.
        body: The Markdown message.
        reader_id: The reader's user id.

    Returns:
        The thread with the new message.

    Raises:
        CommentValidationError: ``feedback-version-not-found``, ``feedback-thread-not-found``, or
            ``comment-empty-body``.
    """
    text = comment_store._require_body(body)
    version = _version(tenant_id, project_slug, version_label)
    row = _own_thread(tenant_id, version, thread_id, reader_id)
    comment_id = db.insert_comment(
        tenant_id=tenant_id,
        project_id=str(version["project_id"]),
        thread_id=str(row["id"]),
        author_id=reader_id,
        body=text,
        mentions=[],
        notify=None,
    )
    if not comment_id:
        raise CommentValidationError(CODE_FEEDBACK_THREAD_NOT_FOUND, f"no feedback thread '{thread_id}'")
    return _render([_own_thread(tenant_id, version, str(row["id"]), reader_id)])[0]


def set_feedback_status(
    tenant_id: str, project_slug: str, version_label: str, thread_id: str, status: str, reader_id: str
) -> FeedbackThread:
    """Resolve or reopen the reader's thread — the same transition the team uses.

    Args:
        tenant_id: The reader's tenant.
        project_slug: The project slug.
        version_label: The version label.
        thread_id: The thread.
        status: ``open`` or ``resolved``.
        reader_id: The reader's user id.

    Returns:
        The thread as it now stands.

    Raises:
        CommentValidationError: ``feedback-version-not-found``, ``feedback-thread-not-found``, or
            ``comment-thread-orphaned`` when its operation no longer exists.
    """
    version = _version(tenant_id, project_slug, version_label)
    row = _own_thread(tenant_id, version, thread_id, reader_id)
    comment_store.set_thread_status(tenant_id, str(version["project_id"]), str(row["id"]), status, reader_id)
    return _render([_own_thread(tenant_id, version, str(row["id"]), reader_id)])[0]
