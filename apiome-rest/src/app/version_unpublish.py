"""The rules of unpublishing a schema revision (#3213, CLI 4.6 ``apiome versions unpublish``).

``POST /v1/versions/{tenant}/{project}/{version_record_id}/unpublish`` returns a published
revision to draft. These functions hold the decisions around it, without a database:

* :func:`previous_published` — where the version tags on the revision move: the project's
  next-most-recent **published** revision;
* :func:`plan_tag_moves` — which tags move there and which stay (immutable, protected, or no
  published revision to move to), unless the caller asked to keep them;
* :func:`build_unpublish_notification` / :func:`notify_version_unpublished` — the
  ``version.unpublished`` push-webhook event, fanned out to every active subscription unless
  the unpublish is *silent* (tenant administrators only; the route enforces that).

A dry run uses the same plan, so what the CLI previews is what the real call does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .push_webhook_fanout import enqueue_event

logger = logging.getLogger(__name__)

#: Push-webhook event type stamped on each unpublish notification (sibling of ``version.published``).
EVENT_TYPE_VERSION_UNPUBLISHED = "version.unpublished"

#: Longest unpublish reason accepted, in characters.
REASON_MAX_LENGTH = 2000

#: Why a tag stays on the unpublished revision.
KEPT_REQUESTED = "keep-tags"
KEPT_IMMUTABLE = "immutable"
KEPT_PROTECTED = "protected"
KEPT_NO_TARGET = "no-published-version"


def _sort_instant(value: Any) -> float:
    """A timestamp (datetime or ISO string) as a sortable number; missing → oldest."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.timestamp()
    if isinstance(value, str) and value.strip():
        try:
            moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return float("-inf")
        return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()
    return float("-inf")


def previous_published(
    versions: Sequence[Mapping[str, Any]], version_record_id: str
) -> Optional[Mapping[str, Any]]:
    """The project's most recently published revision other than ``version_record_id``.

    Ordered by ``published_at`` and then ``created_at``, newest first.

    Args:
        versions: The project's revisions (``Database.get_versions_for_project`` rows).
        version_record_id: The revision being unpublished.

    Returns:
        That revision, or ``None`` when no other revision is published.
    """
    candidates = [
        v
        for v in versions
        if v.get("published") and str(v.get("id")) != str(version_record_id)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda v: (_sort_instant(v.get("published_at")), _sort_instant(v.get("created_at"))),
    )


@dataclass(frozen=True)
class TagPlan:
    """What an unpublish does to the version tags on the revision."""

    #: ``{"id", "name", "toVersionId", "toVersionLabel"}`` per tag that moves.
    moves: List[Dict[str, Any]]
    #: ``{"id", "name", "reason"}`` per tag that stays (``reason`` is one of the ``KEPT_*`` values).
    kept: List[Dict[str, Any]]


def plan_tag_moves(
    tags: Sequence[Mapping[str, Any]],
    version_record_id: str,
    target: Optional[Mapping[str, Any]],
    *,
    keep_tags: bool,
    is_admin: bool,
) -> TagPlan:
    """Decide which tags on the unpublished revision move to ``target``.

    A tag stays when the caller passed ``keepTags``, when it is immutable, when it is protected
    and the caller is not a tenant administrator (the same rule as moving a tag by hand), or
    when there is no other published revision to move it to.

    Args:
        tags: The project's version tags (``Database.list_version_tags_for_project`` rows).
        version_record_id: The revision being unpublished; only tags pointing at it count.
        target: :func:`previous_published`'s result.
        keep_tags: Leave every tag where it is.
        is_admin: Whether the caller is a tenant administrator.

    Returns:
        The :class:`TagPlan`, tags in name order.
    """
    moves: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    on_version = sorted(
        (t for t in tags if str(t.get("version_id")) == str(version_record_id)),
        key=lambda t: str(t.get("name")),
    )
    for tag in on_version:
        ident = {"id": str(tag.get("id")), "name": tag.get("name")}
        if keep_tags:
            kept.append({**ident, "reason": KEPT_REQUESTED})
        elif tag.get("immutable"):
            kept.append({**ident, "reason": KEPT_IMMUTABLE})
        elif tag.get("protected") and not is_admin:
            kept.append({**ident, "reason": KEPT_PROTECTED})
        elif target is None:
            kept.append({**ident, "reason": KEPT_NO_TARGET})
        else:
            moves.append(
                {
                    **ident,
                    "toVersionId": str(target.get("id")),
                    "toVersionLabel": target.get("version_id"),
                }
            )
    return TagPlan(moves=moves, kept=kept)


def build_unpublish_notification(
    *,
    project_id: str,
    version_record_id: str,
    version_label: Optional[str],
    actor_id: Optional[str],
    reason: Optional[str],
    unpublished_at: Any,
    tags_moved: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """The JSON-serializable ``version.unpublished`` payload (camelCase, like ``version.published``).

    Args:
        project_id: The project the revision belongs to.
        version_record_id: The unpublished revision's record id.
        version_label: Its label (e.g. ``2.1.0``).
        actor_id: Who unpublished it.
        reason: The recorded reason, if any.
        unpublished_at: When (datetime or ISO string).
        tags_moved: :attr:`TagPlan.moves` as applied.

    Returns:
        The payload.
    """
    when = unpublished_at.isoformat() if isinstance(unpublished_at, datetime) else unpublished_at
    return {
        "event": EVENT_TYPE_VERSION_UNPUBLISHED,
        "projectId": str(project_id),
        "versionId": str(version_record_id),
        "versionLabel": version_label,
        "unpublishedBy": actor_id,
        "unpublishedAt": when,
        "reason": reason,
        "tagsMoved": [
            {"name": m.get("name"), "toVersionId": m.get("toVersionId"), "toVersionLabel": m.get("toVersionLabel")}
            for m in tags_moved
        ],
    }


def notify_version_unpublished(db: Any, *, tenant_id: str, payload: Mapping[str, Any]) -> List[str]:
    """Enqueue one ``version.unpublished`` delivery per active subscription. Never raises.

    Args:
        db: Database handle (see :func:`app.push_webhook_fanout.enqueue_event`).
        tenant_id: Subscription scope.
        payload: :func:`build_unpublish_notification`'s result.

    Returns:
        The enqueued delivery-event ids.
    """
    return enqueue_event(
        db,
        tenant_id=tenant_id,
        event_type=EVENT_TYPE_VERSION_UNPUBLISHED,
        payload=payload,
        log_label="version-unpublish",
    )


def count_active_subscriptions(db: Any, tenant_id: str) -> Optional[int]:
    """How many active push-webhook subscriptions an unpublish would notify; ``None`` if unknown."""
    try:
        return len(db.list_active_push_webhook_subscription_ids(tenant_id))
    except Exception:  # noqa: BLE001 - a preview never fails on the subscription count
        logger.exception("version-unpublish: failed to count subscriptions for tenant %s", tenant_id)
        return None
