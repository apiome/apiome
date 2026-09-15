"""Comment threads store — COL-1.1 (#4513).

The rules between the HTTP surface (:mod:`app.comment_routes`) and storage (apiome-db V259):

* **Scope.** Every read and write resolves the project inside the caller's tenant first, and every
  thread is read back through that project, so an id from another tenant or project is simply
  "not found".
* **Anchoring.** A thread is opened on an element that must exist in the named version *now* —
  proven by :meth:`app.database.Database.comment_anchor_exists`. A version anchor can only be the
  version's own id, and may be omitted.
* **Mentions.** Every write resolves the body's ``@name`` tokens against the tenant's members
  (:mod:`app.comment_mentions`) and stores the ids; an edit re-resolves them.
* **Ownership.** Editing or deleting a comment is limited to its author or a tenant administrator;
  deleting a thread to the member who opened it or a tenant administrator. Resolving and reopening
  is open to anyone who may comment — it is part of the conversation, not a moderation act.
  Project read access itself is checked by the routes, before the store is called.
* **Deletion.** Deleting a thread's last comment deletes the thread: a thread with nothing in it
  anchors a badge to an empty conversation.
* **Orphans (COL-1.4, #4516).** Renaming or moving an element updates its row in place, so the
  thread's id-based anchor is untouched. Deleting the element orphans the thread — apiome-db V260's
  triggers set ``orphaned`` with the element's last-known label, whichever writer deleted it. An
  orphaned thread still reads, lists, and takes replies, but cannot be resolved or reopened until it
  is relinked to an element of its own version (:func:`relink_thread`).

Refusals raise :class:`app.comments.CommentValidationError` with a stable code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .comment_mentions import MentionCandidate, resolve_mentions
from .comments import (
    ANCHOR_VERSION,
    CODE_ANCHOR_NOT_FOUND,
    CODE_COMMENT_NOT_FOUND,
    CODE_EMPTY_BODY,
    CODE_FORBIDDEN,
    CODE_INVALID_ANCHOR,
    CODE_PROJECT_NOT_FOUND,
    CODE_THREAD_NOT_FOUND,
    CODE_THREAD_NOT_ORPHANED,
    CODE_THREAD_ORPHANED,
    CODE_VERSION_NOT_FOUND,
    STATUS_ORPHANED,
    CommentRecord,
    CommentThreadCreate,
    CommentThreadDetail,
    CommentThreadRecord,
    CommentThreadRelink,
    CommentThreadSummary,
    CommentValidationError,
)
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "ThreadFilters",
    "add_comment",
    "can_moderate",
    "create_thread",
    "delete_comment",
    "delete_thread",
    "edit_comment",
    "get_thread",
    "list_threads",
    "relink_thread",
    "resolve_body_mentions",
    "resolve_project",
    "resolve_version",
    "set_thread_status",
]

#: Columns of a thread row that belong on :class:`CommentThreadRecord`.
_THREAD_FIELDS = tuple(CommentThreadRecord.model_fields)

#: Columns of a comment row that belong on :class:`CommentRecord`.
_COMMENT_FIELDS = tuple(CommentRecord.model_fields)


@dataclass(frozen=True)
class ThreadFilters:
    """What a thread list read narrows to.

    Attributes:
        version: Only threads on this version (revision id or version label).
        status: Only ``open`` or only ``resolved`` threads.
        anchor_type: Only threads on this element kind.
        anchor_id: Only threads on this element.
        mentions_me: Only threads with a comment mentioning the viewer.
        limit: Page size.
        offset: Threads to skip.
    """

    version: Optional[str] = None
    status: Optional[str] = None
    anchor_type: Optional[str] = None
    anchor_id: Optional[str] = None
    mentions_me: bool = False
    limit: int = 50
    offset: int = 0


# ---------------------------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------------------------


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id to its row, within the tenant.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        CommentValidationError: ``comment-project-not-found`` when nothing matches.
    """
    ref = (project_ref or "").strip()
    row = None
    if ref:
        row = (
            db.get_project_by_id(ref, tenant_id)
            if is_uuid_string(ref)
            else db.get_project_by_slug(ref, tenant_id)
        )
    if not row:
        raise CommentValidationError(CODE_PROJECT_NOT_FOUND, f"no project '{ref}' in this tenant")
    return row


def resolve_version(tenant_id: str, project_id: str, version_ref: str) -> Dict[str, Any]:
    """Resolve a revision id or version label to a version of the project.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the version must belong to.
        version_ref: A revision UUID or a version label such as ``1.0.0``.

    Returns:
        The version row.

    Raises:
        CommentValidationError: ``comment-version-not-found`` when nothing in the project matches.
    """
    ref = (version_ref or "").strip()
    row = None
    if is_uuid_string(ref):
        row = db.get_version_by_id(ref, tenant_id)
        if row is not None and str(row.get("project_id")) != str(project_id):
            row = None
    elif ref:
        row = db.get_version_by_version_id(project_id, ref, tenant_id)
    if not row:
        raise CommentValidationError(CODE_VERSION_NOT_FOUND, f"no version '{ref}' in this project")
    return row


def _canonical_uuid(value: Optional[str]) -> Optional[str]:
    """Return a UUID in its canonical lower-case spelling, or ``None`` when it is not one.

    Args:
        value: The candidate id.

    Returns:
        The canonical spelling, or ``None``.
    """
    text = (value or "").strip()
    if not is_uuid_string(text):
        return None
    return str(uuid.UUID(text))


def _resolve_anchor(
    version_id: str, version_name: str, anchor_type: str, anchor_id: Optional[str]
) -> str:
    """Prove an anchor names an element of a version, and return its canonical id.

    Shared by opening a thread and relinking one, so both accept exactly the same anchors.

    Args:
        version_id: The version's revision id.
        version_name: How a refusal names the version (its label, or its id).
        anchor_type: The element kind.
        anchor_id: The element id as the client sent it; optional for a version anchor.

    Returns:
        The canonical anchor id — the version's own id for a version anchor.

    Raises:
        CommentValidationError: ``comment-invalid-anchor`` for a missing or malformed id, or a
            version anchor naming another version; ``comment-anchor-not-found`` when the element
            does not exist in the version now.
    """
    if anchor_type == ANCHOR_VERSION:
        own = _canonical_uuid(version_id)
        anchor = _canonical_uuid(anchor_id) if anchor_id else own
        if anchor is None or anchor != own:
            raise CommentValidationError(
                CODE_INVALID_ANCHOR,
                "a version anchor is the thread's own version; omit anchor_id or pass that version's id",
            )
        return anchor

    anchor = _canonical_uuid(anchor_id)
    if anchor is None:
        raise CommentValidationError(
            CODE_INVALID_ANCHOR,
            f"a {anchor_type} anchor needs the element's id (a UUID) in anchor_id",
        )
    if not db.comment_anchor_exists(version_id=version_id, anchor_type=anchor_type, anchor_id=anchor):
        raise CommentValidationError(
            CODE_ANCHOR_NOT_FOUND, f"no {anchor_type} '{anchor}' in version '{version_name}'"
        )
    return anchor


def _refuse_orphaned(row: Mapping[str, Any]) -> None:
    """Refuse a status change on a thread whose element was deleted.

    Args:
        row: The thread row.

    Raises:
        CommentValidationError: ``comment-thread-orphaned`` when the thread is orphaned.
    """
    if row.get("status") == STATUS_ORPHANED:
        raise CommentValidationError(
            CODE_THREAD_ORPHANED,
            "this thread's element was deleted; relink the thread to an element before resolving or reopening it",
        )


def _require_body(body: str) -> str:
    """Refuse a comment body that is only whitespace.

    Args:
        body: The Markdown body.

    Returns:
        The body, unchanged — leading indentation is meaningful Markdown.

    Raises:
        CommentValidationError: ``comment-empty-body`` for a blank body.
    """
    if not (body or "").strip():
        raise CommentValidationError(CODE_EMPTY_BODY, "a comment must say something")
    return body


def resolve_body_mentions(tenant_id: str, body: str) -> List[str]:
    """Resolve a body's ``@name`` tokens to tenant member ids.

    Args:
        tenant_id: The tenant whose members may be mentioned.
        body: The Markdown body.

    Returns:
        The mentioned member ids, in order of first mention. The member list is only read when the
        body contains a mention token at all.
    """
    if "@" not in (body or ""):
        return []
    members = [
        MentionCandidate(
            user_id=str(row.get("user_id") or ""),
            name=row.get("name"),
            email=row.get("email"),
        )
        for row in db.list_comment_mention_candidates(tenant_id)
    ]
    return resolve_mentions(body, members).user_ids


def can_moderate(tenant_id: str, actor_id: Optional[str], owner_id: Optional[str]) -> bool:
    """Whether the actor may edit or delete something owned by ``owner_id``.

    Args:
        tenant_id: The tenant.
        actor_id: The acting user.
        owner_id: The comment's author or the thread's opener (``None`` once that user is gone).

    Returns:
        ``True`` for the owner themself or a tenant administrator.
    """
    if not actor_id:
        return False
    if owner_id and str(owner_id) == str(actor_id):
        return True
    if not is_uuid_string(str(actor_id)) or not is_uuid_string(str(tenant_id or "")):
        return False
    return bool(db.is_user_tenant_admin(tenant_id, actor_id))


# ---------------------------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------------------------


def _thread_record(row: Mapping[str, Any]) -> CommentThreadRecord:
    """Map a thread row onto its record.

    Args:
        row: A row from a thread read.

    Returns:
        The record.
    """
    return CommentThreadRecord(**{name: row.get(name) for name in _THREAD_FIELDS if name in row})


def _comment_record(row: Mapping[str, Any], prefix: str = "") -> CommentRecord:
    """Map a comment row (or a ``root_``-prefixed slice of a thread row) onto its record.

    Args:
        row: The row.
        prefix: Column prefix, ``root_`` for a list read's embedded opening comment.

    Returns:
        The record.
    """
    values = {name: row.get(f"{prefix}{name}") for name in _COMMENT_FIELDS}
    if prefix:
        values["thread_id"] = row.get("id")
    values["mentions"] = [str(item) for item in (values.get("mentions") or [])]
    return CommentRecord(**values)


def _summary(row: Mapping[str, Any]) -> CommentThreadSummary:
    """Map a list-read row onto a summary with its opening comment.

    Args:
        row: A row from :meth:`app.database.Database.list_comment_threads`.

    Returns:
        The summary.
    """
    record = _thread_record(row)
    root = _comment_record(row, prefix="root_") if row.get("root_id") else None
    return CommentThreadSummary(**record.model_dump(), root_comment=root)


def _thread_row(tenant_id: str, project_id: str, thread_id: str) -> Dict[str, Any]:
    """Read a thread inside a project, or refuse.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        thread_id: The thread.

    Returns:
        The thread row.

    Raises:
        CommentValidationError: ``comment-thread-not-found``.
    """
    row = db.get_comment_thread(tenant_id=tenant_id, project_id=project_id, thread_id=thread_id)
    if not row:
        raise CommentValidationError(CODE_THREAD_NOT_FOUND, f"no thread '{thread_id}' in this project")
    return row


def _comment_row(thread_id: str, comment_id: str) -> Dict[str, Any]:
    """Read a comment of a thread, or refuse.

    Args:
        thread_id: The (already scoped) thread.
        comment_id: The comment.

    Returns:
        The comment row.

    Raises:
        CommentValidationError: ``comment-not-found``.
    """
    row = db.get_comment(thread_id=thread_id, comment_id=comment_id)
    if not row:
        raise CommentValidationError(CODE_COMMENT_NOT_FOUND, f"no comment '{comment_id}' in this thread")
    return row


# ---------------------------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------------------------


def list_threads(
    tenant_id: str, project_ref: str, filters: ThreadFilters, viewer_id: str
) -> Tuple[List[CommentThreadSummary], int]:
    """List a project's threads, most recently active first.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        filters: What to narrow to.
        viewer_id: The caller, for ``mentions_me``.

    Returns:
        The page of summaries and the total matching the filters.

    Raises:
        CommentValidationError: For an unknown project or version, or a malformed ``anchor_id``.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version_id = None
    if filters.version:
        version_id = str(resolve_version(tenant_id, project_id, filters.version)["id"])
    anchor_id = None
    if filters.anchor_id:
        anchor_id = _canonical_uuid(filters.anchor_id)
        if anchor_id is None:
            raise CommentValidationError(CODE_INVALID_ANCHOR, "anchor_id must be an element id (a UUID)")

    scope = {
        "tenant_id": tenant_id,
        "project_id": project_id,
        "version_id": version_id,
        "status": filters.status,
        "anchor_type": filters.anchor_type,
        "anchor_id": anchor_id,
        "mentioned_user_id": viewer_id if filters.mentions_me else None,
    }
    rows = db.list_comment_threads(**scope, limit=filters.limit, offset=filters.offset)
    total = db.count_comment_threads(**scope)
    return [_summary(row) for row in rows], total


def get_thread(tenant_id: str, project_ref: str, thread_id: str) -> CommentThreadDetail:
    """Read a thread with all of its comments.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.

    Returns:
        The thread and its comments, oldest first.

    Raises:
        CommentValidationError: For an unknown project or thread.
    """
    project = resolve_project(tenant_id, project_ref)
    row = _thread_row(tenant_id, str(project["id"]), thread_id)
    comments = db.list_comments(thread_id=str(row["id"]))
    return CommentThreadDetail(
        thread=_thread_record(row), comments=[_comment_record(item) for item in comments]
    )


def create_thread(
    tenant_id: str, project_ref: str, request: CommentThreadCreate, actor_id: str
) -> CommentThreadDetail:
    """Open a thread on an element of a version, with its first comment.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        request: The version, anchor, and first comment.
        actor_id: The opening user.

    Returns:
        The new thread and its first comment.

    Raises:
        CommentValidationError: For an unknown project, version, or element; a malformed anchor; a
            blank body; or an actor that cannot be attributed.
    """
    body = _require_body(request.body)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = resolve_version(tenant_id, project_id, request.version)
    version_id = str(version["id"])
    anchor_id = _resolve_anchor(
        version_id, str(version.get("version_id") or version_id), request.anchor_type, request.anchor_id
    )

    inserted = db.insert_comment_thread(
        tenant_id=tenant_id,
        project_id=project_id,
        version_id=version_id,
        anchor_type=request.anchor_type,
        anchor_id=anchor_id,
        created_by=actor_id,
        body=body,
        mentions=resolve_body_mentions(tenant_id, body),
    )
    if not inserted:
        raise CommentValidationError(CODE_FORBIDDEN, "a comment must be attributable to a user")
    return get_thread(tenant_id, project_id, str(inserted["thread_id"]))


def set_thread_status(
    tenant_id: str, project_ref: str, thread_id: str, status: str, actor_id: str
) -> CommentThreadRecord:
    """Resolve or reopen a thread. Asking for the status it already has changes nothing.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        status: ``open`` or ``resolved``.
        actor_id: The acting user.

    Returns:
        The thread as it now stands.

    Raises:
        CommentValidationError: For an unknown project or thread; ``comment-thread-orphaned`` when
            the thread's element was deleted (before or during the change).
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _thread_row(tenant_id, project_id, thread_id)
    _refuse_orphaned(row)
    if row.get("status") != status:
        db.set_comment_thread_status(
            tenant_id=tenant_id,
            project_id=project_id,
            thread_id=str(row["id"]),
            status=status,
            actor_id=actor_id,
        )
        row = _thread_row(tenant_id, project_id, str(row["id"]))
        # The element may have been deleted between the read and the write; the write then did
        # nothing, and saying so beats answering with a status the caller did not ask for.
        _refuse_orphaned(row)
    return _thread_record(row)


def relink_thread(
    tenant_id: str, project_ref: str, thread_id: str, request: CommentThreadRelink
) -> CommentThreadRecord:
    """Re-attach an orphaned thread to another element of its own version — COL-1.4 (#4516).

    The thread keeps its comments. It returns to ``resolved`` when it was resolved before its
    element was deleted and to ``open`` otherwise; its orphan label and time are cleared.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        request: The element to attach to.

    Returns:
        The thread as it now stands.

    Raises:
        CommentValidationError: ``comment-thread-not-orphaned`` for a thread still on a live element
            (or one relinked by someone else first); ``comment-invalid-anchor`` /
            ``comment-anchor-not-found`` for a target that is malformed or not in the thread's
            version; not-found codes for an unknown project or thread.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _thread_row(tenant_id, project_id, thread_id)
    not_orphaned = CommentValidationError(
        CODE_THREAD_NOT_ORPHANED,
        "only an orphaned thread can be relinked; this one is still anchored to its element",
    )
    if row.get("status") != STATUS_ORPHANED:
        raise not_orphaned

    version_id = str(row["version_id"])
    anchor_id = _resolve_anchor(version_id, version_id, request.anchor_type, request.anchor_id)
    relinked = db.relink_comment_thread(
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=str(row["id"]),
        version_id=version_id,
        anchor_type=request.anchor_type,
        anchor_id=anchor_id,
    )
    if not relinked:
        # The guarded write lost a race: someone relinked the thread first, or the target was
        # deleted after it was checked.
        if _thread_row(tenant_id, project_id, str(row["id"])).get("status") != STATUS_ORPHANED:
            raise not_orphaned
        raise CommentValidationError(
            CODE_ANCHOR_NOT_FOUND, f"no {request.anchor_type} '{anchor_id}' in version '{version_id}'"
        )
    return _thread_record(_thread_row(tenant_id, project_id, str(row["id"])))


def delete_thread(tenant_id: str, project_ref: str, thread_id: str, actor_id: str) -> None:
    """Delete a thread and all of its comments.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        actor_id: The acting user.

    Raises:
        CommentValidationError: ``comment-forbidden`` unless the actor opened the thread or is a
            tenant administrator; not-found codes for an unknown project or thread.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _thread_row(tenant_id, project_id, thread_id)
    if not can_moderate(tenant_id, actor_id, row.get("created_by")):
        raise CommentValidationError(
            CODE_FORBIDDEN, "only the member who opened a thread or a tenant administrator can delete it"
        )
    if not db.delete_comment_thread(tenant_id=tenant_id, project_id=project_id, thread_id=str(row["id"])):
        raise CommentValidationError(CODE_THREAD_NOT_FOUND, f"no thread '{thread_id}' in this project")


# ---------------------------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------------------------


def add_comment(
    tenant_id: str, project_ref: str, thread_id: str, body: str, actor_id: str
) -> CommentRecord:
    """Reply to a thread. A resolved thread accepts replies and stays resolved.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        body: The Markdown reply.
        actor_id: The replying user.

    Returns:
        The stored comment.

    Raises:
        CommentValidationError: For an unknown project or thread, or a blank body.
    """
    text = _require_body(body)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    row = _thread_row(tenant_id, project_id, thread_id)
    comment_id = db.insert_comment(
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=str(row["id"]),
        author_id=actor_id,
        body=text,
        mentions=resolve_body_mentions(tenant_id, text),
    )
    if not comment_id:
        raise CommentValidationError(CODE_THREAD_NOT_FOUND, f"no thread '{thread_id}' in this project")
    return _comment_record(_comment_row(str(row["id"]), comment_id))


def edit_comment(
    tenant_id: str, project_ref: str, thread_id: str, comment_id: str, body: str, actor_id: str
) -> CommentRecord:
    """Replace a comment's text, re-resolving its mentions and stamping the edit.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        comment_id: The comment.
        body: The new Markdown.
        actor_id: The acting user.

    Returns:
        The updated comment.

    Raises:
        CommentValidationError: ``comment-forbidden`` unless the actor wrote the comment or is a
            tenant administrator; not-found codes; ``comment-empty-body``.
    """
    text = _require_body(body)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    thread = _thread_row(tenant_id, project_id, thread_id)
    comment = _comment_row(str(thread["id"]), comment_id)
    if not can_moderate(tenant_id, actor_id, comment.get("author_id")):
        raise CommentValidationError(
            CODE_FORBIDDEN, "only the comment's author or a tenant administrator can edit it"
        )
    updated = db.update_comment(
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=str(thread["id"]),
        comment_id=str(comment["id"]),
        body=text,
        mentions=resolve_body_mentions(tenant_id, text),
    )
    if not updated:
        raise CommentValidationError(CODE_COMMENT_NOT_FOUND, f"no comment '{comment_id}' in this thread")
    return _comment_record(_comment_row(str(thread["id"]), str(comment["id"])))


def delete_comment(
    tenant_id: str, project_ref: str, thread_id: str, comment_id: str, actor_id: str
) -> bool:
    """Delete a comment; deleting a thread's last comment deletes the thread.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or id.
        thread_id: The thread.
        comment_id: The comment.
        actor_id: The acting user.

    Returns:
        ``True`` when the thread was deleted along with its last comment.

    Raises:
        CommentValidationError: ``comment-forbidden`` unless the actor wrote the comment or is a
            tenant administrator; not-found codes for an unknown project, thread, or comment.
    """
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    thread = _thread_row(tenant_id, project_id, thread_id)
    comment = _comment_row(str(thread["id"]), comment_id)
    if not can_moderate(tenant_id, actor_id, comment.get("author_id")):
        raise CommentValidationError(
            CODE_FORBIDDEN, "only the comment's author or a tenant administrator can delete it"
        )
    outcome = db.delete_comment(
        tenant_id=tenant_id,
        project_id=project_id,
        thread_id=str(thread["id"]),
        comment_id=str(comment["id"]),
    )
    if not outcome.get("deleted"):
        raise CommentValidationError(CODE_COMMENT_NOT_FOUND, f"no comment '{comment_id}' in this thread")
    return bool(outcome.get("thread_deleted"))
