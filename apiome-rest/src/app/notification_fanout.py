"""Notification fan-out — who an event concerns, and what their inbox row says (COL-3.1, #4521).

Every collaboration event has a small, knowable set of people it is *about*, and this module is the
only place that decides it:

============================  ==================================================================
Event                         Recipients
============================  ==================================================================
``mention``                   The members the comment's ``@name`` tokens resolved to. An edit
                              notifies only the members it *newly* names.
``review_requested``          The reviewers of the round being opened.
``review_decision``           The member who requested the review.
``thread_resolved``           Everyone who took part in the thread — its opener and every author
                              of a comment in it.
``version_published``         Everyone who collaborated on that version: its review participants
                              and its thread participants.
============================  ==================================================================

Two rules hold for all five. **Nobody is notified of their own action** — the actor is removed from
every recipient set, so resolving your own thread or approving a review you were asked for pages
nobody. And **a recipient set is bounded** (:data:`app.notifications.MAX_RECIPIENTS`), so no single
event can write an unbounded number of rows.

The module is deliberately dependency-free — no database, no HTTP, no settings. A caller resolves
the rows it needs, calls a builder here, and hands the resulting drafts to the accessor that writes
the event, which inserts them **in the same transaction** (:meth:`app.database.Database.
_insert_notifications`). That is what makes "a committed event always has its inbox rows" true
without a queue.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .notifications import (
    MAX_EXCERPT_LENGTH,
    MAX_RECIPIENTS,
    TYPE_MENTION,
    TYPE_REVIEW_DECISION,
    TYPE_REVIEW_REQUESTED,
    TYPE_THREAD_RESOLVED,
    TYPE_VERSION_PUBLISHED,
)
from .revision_deprecation import is_uuid_string

__all__ = [
    "NotificationDraft",
    "excerpt",
    "mention_drafts",
    "recipients",
    "review_decision_drafts",
    "review_requested_drafts",
    "thread_resolved_drafts",
    "version_published_drafts",
]


@dataclass(frozen=True)
class NotificationDraft:
    """One inbox row, before it is written.

    Attributes:
        user_id: The recipient.
        type: One of :data:`app.notifications.NOTIFICATION_TYPES`.
        payload: What the notification's sentence and deep link need.
        actor_id: Who caused the event; ``None`` when it cannot be attributed.
        project_id: The project the event happened in.
        version_id: The version the event happened on.
    """

    user_id: str
    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    actor_id: Optional[str] = None
    project_id: Optional[str] = None
    version_id: Optional[str] = None


def _canonical(value: Any) -> Optional[str]:
    """Return a user id in its canonical UUID spelling, or ``None`` when it is not one.

    Args:
        value: The candidate id.

    Returns:
        The canonical spelling, or ``None``.
    """
    text = str(value or "").strip()
    if not is_uuid_string(text):
        return None
    return str(uuid.UUID(text))


def recipients(candidates: Iterable[Any], *, exclude: Iterable[Any] = ()) -> List[str]:
    """Reduce candidate ids to the users an event may actually be written for.

    Drops anything that is not a user id, removes the excluded users (the actor, above all),
    collapses duplicates keeping first-seen order, and caps the result at
    :data:`app.notifications.MAX_RECIPIENTS`.

    Args:
        candidates: The ids the event points at, in any order, possibly with duplicates.
        exclude: Ids never to notify — the acting user, and anyone already notified.

    Returns:
        The recipients, in first-seen order.
    """
    blocked = {canonical for canonical in (_canonical(item) for item in exclude) if canonical}
    seen: List[str] = []
    for item in candidates:
        canonical = _canonical(item)
        if canonical is None or canonical in blocked:
            continue
        blocked.add(canonical)
        seen.append(canonical)
        if len(seen) >= MAX_RECIPIENTS:
            break
    return seen


def excerpt(body: Optional[str]) -> str:
    """Shorten a comment to the snippet an inbox row shows.

    Whitespace (including the line breaks of a Markdown body) is collapsed to single spaces and the
    result is cut to :data:`app.notifications.MAX_EXCERPT_LENGTH` characters, ending in an ellipsis
    when anything was cut. An inbox row is a pointer to the conversation, never a copy of it.

    Args:
        body: The comment's Markdown.

    Returns:
        The excerpt; empty for an empty body.
    """
    text = " ".join((body or "").split())
    if len(text) <= MAX_EXCERPT_LENGTH:
        return text
    return text[: MAX_EXCERPT_LENGTH - 1].rstrip() + "…"


def _scope(
    project: Optional[Mapping[str, Any]], version: Optional[Mapping[str, Any]]
) -> tuple[Optional[str], Optional[str], Dict[str, Any]]:
    """Read the project and version a payload names, and the ids the row is filed under.

    Args:
        project: The project row (``id``, ``slug``, ``name``), when known.
        version: The version row (``id``, ``version_id`` label), when known.

    Returns:
        ``(project_id, version_id, payload)`` — the payload holding only the labels that resolved.
    """
    project_id = _canonical((project or {}).get("id"))
    version_id = _canonical((version or {}).get("id"))
    payload: Dict[str, Any] = {}
    for key, value in (
        ("project_slug", (project or {}).get("slug")),
        ("project_name", (project or {}).get("name")),
        ("version_label", (version or {}).get("version_id")),
    ):
        if value:
            payload[key] = str(value)
    return project_id, version_id, payload


def _drafts(
    users: Sequence[str],
    *,
    type: str,
    payload: Dict[str, Any],
    actor_id: Optional[str],
    project_id: Optional[str],
    version_id: Optional[str],
) -> List[NotificationDraft]:
    """Turn one event and its recipients into one draft each.

    Args:
        users: The recipients, already reduced by :func:`recipients`.
        type: The notification type.
        payload: The payload every recipient shares.
        actor_id: Who caused the event.
        project_id: The project.
        version_id: The version.

    Returns:
        One draft per recipient; empty when there are none.
    """
    return [
        NotificationDraft(
            user_id=user_id,
            type=type,
            payload=dict(payload),
            actor_id=actor_id,
            project_id=project_id,
            version_id=version_id,
        )
        for user_id in users
    ]


def mention_drafts(
    *,
    mentioned: Iterable[Any],
    actor_id: Optional[str],
    project: Optional[Mapping[str, Any]],
    version: Optional[Mapping[str, Any]],
    thread_id: str,
    comment_id: str,
    anchor_type: str,
    anchor_id: Optional[str],
    body: Optional[str],
    already_mentioned: Iterable[Any] = (),
) -> List[NotificationDraft]:
    """"@you" — the members a comment names.

    Args:
        mentioned: The user ids the body's ``@name`` tokens resolved to.
        actor_id: The comment's author, never notified of their own comment.
        project: The project row.
        version: The version row.
        thread_id: The thread the comment is in.
        comment_id: The comment itself.
        anchor_type: The kind of element the thread is anchored to.
        anchor_id: That element's id.
        body: The comment's Markdown, for the excerpt.
        already_mentioned: Members the *previous* text of an edited comment already named, so an
            edit notifies only the people it newly names.

    Returns:
        One draft per newly mentioned member.
    """
    project_id, version_id, payload = _scope(project, version)
    payload.update(
        {
            "thread_id": str(thread_id),
            "comment_id": str(comment_id),
            "anchor_type": str(anchor_type),
            "excerpt": excerpt(body),
        }
    )
    if anchor_id:
        payload["anchor_id"] = str(anchor_id)
    users = recipients(mentioned, exclude=[actor_id, *already_mentioned])
    return _drafts(
        users,
        type=TYPE_MENTION,
        payload=payload,
        actor_id=_canonical(actor_id),
        project_id=project_id,
        version_id=version_id,
    )


def thread_resolved_drafts(
    *,
    participants: Iterable[Any],
    actor_id: Optional[str],
    project: Optional[Mapping[str, Any]],
    version: Optional[Mapping[str, Any]],
    thread_id: str,
    anchor_type: str,
    anchor_id: Optional[str],
) -> List[NotificationDraft]:
    """"the thread you were in was resolved" — everyone who took part in it.

    Reopening a thread notifies nobody: it is the start of more conversation, and the reply that
    follows will speak for itself.

    Args:
        participants: The thread's opener and the authors of its comments, in any order.
        actor_id: Who resolved it, never notified of their own resolution.
        project: The project row.
        version: The version row.
        thread_id: The thread.
        anchor_type: The kind of element the thread is anchored to.
        anchor_id: That element's id.

    Returns:
        One draft per other participant.
    """
    project_id, version_id, payload = _scope(project, version)
    payload.update({"thread_id": str(thread_id), "anchor_type": str(anchor_type)})
    if anchor_id:
        payload["anchor_id"] = str(anchor_id)
    return _drafts(
        recipients(participants, exclude=[actor_id]),
        type=TYPE_THREAD_RESOLVED,
        payload=payload,
        actor_id=_canonical(actor_id),
        project_id=project_id,
        version_id=version_id,
    )


def review_requested_drafts(
    *,
    reviewers: Iterable[Any],
    actor_id: Optional[str],
    project: Optional[Mapping[str, Any]],
    version: Optional[Mapping[str, Any]],
    review_id: str,
    round: int,
) -> List[NotificationDraft]:
    """"you were asked to review this" — the reviewers of the round being opened.

    A re-request opens a new round and so notifies its reviewers again: the content changed, which
    is exactly what they are being asked to look at.

    Args:
        reviewers: The round's reviewer user ids.
        actor_id: Who asked, never a reviewer of their own request.
        project: The project row.
        version: The version row.
        review_id: The review.
        round: The round being opened.

    Returns:
        One draft per reviewer.
    """
    project_id, version_id, payload = _scope(project, version)
    payload.update({"review_id": str(review_id), "round": int(round)})
    return _drafts(
        recipients(reviewers, exclude=[actor_id]),
        type=TYPE_REVIEW_REQUESTED,
        payload=payload,
        actor_id=_canonical(actor_id),
        project_id=project_id,
        version_id=version_id,
    )


def review_decision_drafts(
    *,
    requested_by: Optional[Any],
    actor_id: Optional[str],
    project: Optional[Mapping[str, Any]],
    version: Optional[Mapping[str, Any]],
    review_id: str,
    round: int,
    decision: str,
) -> List[NotificationDraft]:
    """"your review was decided" — the member who asked for the review.

    Only the requester is told. The other reviewers of the round are deciding the same content
    independently, and telling each of them about every sibling decision would make a five-reviewer
    round twenty notifications.

    Args:
        requested_by: Who requested the review; ``None`` once that user is deleted.
        actor_id: The deciding reviewer, never notified of their own decision (which is what
            happens when somebody reviews a version they requested a review of).
        project: The project row.
        version: The version row.
        review_id: The review.
        round: The round decided.
        decision: ``approve`` or ``request_changes``.

    Returns:
        A single draft, or none when there is nobody left to tell.
    """
    project_id, version_id, payload = _scope(project, version)
    payload.update({"review_id": str(review_id), "round": int(round), "decision": str(decision)})
    return _drafts(
        recipients([requested_by], exclude=[actor_id]),
        type=TYPE_REVIEW_DECISION,
        payload=payload,
        actor_id=_canonical(actor_id),
        project_id=project_id,
        version_id=version_id,
    )


def version_published_drafts(
    *,
    collaborators: Iterable[Any],
    actor_id: Optional[str],
    project: Optional[Mapping[str, Any]],
    version: Optional[Mapping[str, Any]],
) -> List[NotificationDraft]:
    """"the version you worked on was published" — its collaborators.

    Collaboration is read from what the version actually holds: whoever requested or was asked for
    its review, and whoever opened or replied to a thread on it. A publish is not an announcement
    to the whole tenant — a member who never touched the version learns about it from the catalogue.

    Args:
        collaborators: The version's review and thread participants, in any order.
        actor_id: Who published, never notified of their own publish.
        project: The project row.
        version: The version row.

    Returns:
        One draft per collaborator.
    """
    project_id, version_id, payload = _scope(project, version)
    return _drafts(
        recipients(collaborators, exclude=[actor_id]),
        type=TYPE_VERSION_PUBLISHED,
        payload=payload,
        actor_id=_canonical(actor_id),
        project_id=project_id,
        version_id=version_id,
    )
