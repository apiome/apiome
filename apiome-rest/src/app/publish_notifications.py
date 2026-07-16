"""Publish-event webhook notifications with classified-changelog payloads (CTG-3.3, #4477).

Consumers who want "tell me when something breaking ships" need more than *that*
a version was published — they need *what changed* and *whether it breaks anyone*.
This module fans a ``version.published`` event out over the **existing**
push-webhook channels (``apiome.push_webhook_subscriptions`` /
``push_webhook_delivery_events``, #2587/#2588 — same retry/dead-letter semantics),
embedding the classified changelog persisted by CTG-3.1 (#4475)::

    publish ──► version_changelogs row ──► payload {counts, top changes, max severity}
            ──► deliver to each subscription whose ``min_severity`` threshold is met

**Severity filtering.** Each subscription may carry a ``min_severity`` threshold
(``docs-only`` < ``non-breaking`` < ``breaking``; V179). A publish is delivered
only when its classified max severity meets the threshold:

* No threshold (``NULL``) — every publish is delivered (backwards compatible with
  all pre-#4477 subscriptions).
* Threshold set, changelog ``ready`` — delivered when
  ``rank(max_severity) >= rank(min_severity)``.
* Threshold set, changelog ``initial`` or empty (no classified changes) — **not**
  delivered: there is no change to meet any threshold.
* Threshold set, changelog ``failed`` or missing — **delivered**: classification
  could not prove the publish is below the threshold, so it fails safe toward
  notifying (mirroring the taxonomy's unclassified→breaking fail-safe).

Only ``version.published`` events are filtered; the other webhook event families
(``repository.refresh.*``, ``lint.*``, ``mcp.*``) ignore ``min_severity``.

Like the sibling refresh/lint notification modules, delivery is **best-effort**:
fan-out swallows per-subscription errors and the public entrypoint never raises,
so a notification problem can never fail the publish it describes. The entrypoint
runs as a FastAPI background task *after* :func:`generate_version_changelog_on_publish`
(background tasks execute in the order they were added), so the changelog row is
already persisted when the payload is built.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from .changelog_generator import severity_rank
from .database import db as default_db

logger = logging.getLogger(__name__)

#: Push-webhook event type stamped on each publish notification. Namespaced so a
#: subscriber can route publish events distinctly from refresh/lint/mcp webhooks.
EVENT_TYPE_VERSION_PUBLISHED = "version.published"

#: Maximum number of changelog entries embedded in a webhook payload. Entries are
#: already ordered most-severe-first by the generator, so the slice keeps the
#: changes a consumer must act on; ``totalChanges``/``topChangesTruncated`` tell
#: them when to fetch the full changelog via the REST API.
TOP_CHANGES_LIMIT = 10


def _clean_str(raw: Any) -> Optional[str]:
    """Return a stripped non-empty string, or ``None`` for blank/missing values."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def should_deliver_publish_event(
    min_severity: Optional[str],
    *,
    max_severity: Optional[str],
    changelog_status: Optional[str],
) -> bool:
    """Decide whether one subscription receives one publish event.

    Args:
        min_severity: The subscription's threshold (``docs-only`` /
            ``non-breaking`` / ``breaking``), or ``None`` for no filter.
        max_severity: The publish's classified worst severity, or ``None`` when
            the changelog is initial/empty/failed/missing.
        changelog_status: The persisted changelog row's status (``ready`` /
            ``initial`` / ``failed``), or ``None`` when no row exists.

    Returns:
        ``True`` when the event must be enqueued for this subscription.
    """
    if min_severity is None:
        return True

    min_rank = severity_rank(min_severity)
    if min_rank is None:
        # Unrecognized threshold (should be impossible past the API/DB CHECK
        # validation) — fail open so a malformed filter never silences a channel.
        logger.warning(
            "publish-notification: unrecognized min_severity %r; delivering",
            min_severity,
        )
        return True

    if changelog_status is None or changelog_status == "failed":
        # Classification missing or failed: we cannot prove the publish is below
        # the threshold, so fail safe toward notifying (taxonomy parity).
        return True

    max_rank = severity_rank(max_severity)
    if max_rank is None:
        # Initial publication or an empty changelog — nothing changed, so no
        # threshold is met.
        return False

    return max_rank >= min_rank


def _changelog_facet(changelog_row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build the ``changelog`` facet of the payload from a persisted row.

    Args:
        changelog_row: The ``version_changelogs`` row for the published revision
            (as returned by ``Database.get_version_changelog``), or ``None``.

    Returns:
        A JSON-serializable dict with ``status``, ``counts``, ``maxSeverity``,
        ``topChanges`` (at most :data:`TOP_CHANGES_LIMIT`, most severe first),
        ``totalChanges`` and ``topChangesTruncated``; plus ``schemaVersion`` /
        ``fromVersion`` / ``toVersion`` / ``initialPublication`` when the stored
        JSON carries them.
    """
    if not changelog_row:
        return {
            "status": "unavailable",
            "counts": {},
            "maxSeverity": None,
            "topChanges": [],
            "totalChanges": 0,
            "topChangesTruncated": False,
        }

    stored = changelog_row.get("changelog_json") or {}
    entries = stored.get("entries") or []
    top = [
        {
            "severity": e.get("severity"),
            "ruleId": e.get("ruleId"),
            "path": e.get("pathGroup"),
            "pointer": e.get("pointer"),
            "summary": e.get("summary"),
        }
        for e in entries[:TOP_CHANGES_LIMIT]
        if isinstance(e, Mapping)
    ]

    facet: Dict[str, Any] = {
        "status": _clean_str(changelog_row.get("status")) or "unavailable",
        "counts": dict(stored.get("counts") or {}),
        "maxSeverity": changelog_row.get("max_severity"),
        "topChanges": top,
        "totalChanges": len(entries),
        "topChangesTruncated": len(entries) > TOP_CHANGES_LIMIT,
    }
    for src_key, dst_key in (
        ("schemaVersion", "schemaVersion"),
        ("fromVersion", "fromVersion"),
        ("toVersion", "toVersion"),
        ("initialPublication", "initialPublication"),
    ):
        if src_key in stored:
            facet[dst_key] = stored[src_key]
    return facet


def build_publish_notification(
    *,
    project_id: str,
    version_record_id: str,
    version_label: Optional[str] = None,
    actor_id: Optional[str] = None,
    changelog_row: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the JSON-serializable ``version.published`` payload.

    The ``event`` / ``projectId`` / ``versionId`` keys and the ``changelog``
    facet are always present so a recipient can route the event; ``maxSeverity``
    is mirrored at the top level for cheap routing without descending into the
    facet. Optional context (``versionLabel``, ``publishedBy``) is included only
    when supplied.

    Args:
        project_id: The catalog project the version belongs to.
        version_record_id: The published version's revision record id.
        version_label: The human version label (e.g. ``1.2.0``), when known.
        actor_id: The user who published, when known.
        changelog_row: The persisted ``version_changelogs`` row, or ``None``
            when classification has not produced one.

    Returns:
        A JSON-serializable notification dict with camelCase keys.
    """
    payload: Dict[str, Any] = {
        "event": EVENT_TYPE_VERSION_PUBLISHED,
        "projectId": _clean_str(project_id),
        "versionId": _clean_str(version_record_id),
        "maxSeverity": (changelog_row or {}).get("max_severity"),
        "changelog": _changelog_facet(changelog_row),
    }
    for key, value in (
        ("versionLabel", version_label),
        ("publishedBy", actor_id),
    ):
        cleaned = _clean_str(value)
        if cleaned is not None:
            payload[key] = cleaned
    return payload


def notify_version_published(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    version_record_id: str,
    version_label: Optional[str] = None,
    actor_id: Optional[str] = None,
    changelog_row: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Fan a publish event out to every subscription whose threshold it meets.

    Enqueues one push-webhook delivery per active tenant subscription
    (``Database.list_active_push_webhook_subscription_filters``) that passes
    :func:`should_deliver_publish_event`, each carrying the payload from
    :func:`build_publish_notification`. Retry/dead-letter semantics are the
    delivery worker's, unchanged (#2588).

    Best-effort: a per-subscription enqueue failure (e.g. a subscription
    deactivated between the listing and the enqueue) is logged and skipped, and
    the function never raises, so a notification problem cannot break the
    publish it describes.

    Args:
        db: Database handle exposing ``list_active_push_webhook_subscription_filters``
            and ``enqueue_push_webhook_delivery``.
        tenant_id: Owning tenant id (subscription scope).
        project_id: The catalog project the version belongs to.
        version_record_id: The published version's revision record id.
        version_label: The human version label, when known.
        actor_id: The user who published, when known.
        changelog_row: The persisted ``version_changelogs`` row, or ``None``.

    Returns:
        The list of enqueued delivery-event ids (empty when no subscription
        passed the filter or none exists).
    """
    payload = build_publish_notification(
        project_id=project_id,
        version_record_id=version_record_id,
        version_label=version_label,
        actor_id=actor_id,
        changelog_row=changelog_row,
    )
    max_severity = (changelog_row or {}).get("max_severity")
    changelog_status = (changelog_row or {}).get("status")

    try:
        subscriptions = db.list_active_push_webhook_subscription_filters(tenant_id)
    except Exception:
        logger.exception(
            "publish-notification fan-out: failed to list subscriptions for tenant %s",
            tenant_id,
        )
        return []

    enqueued: List[str] = []
    for sub in subscriptions:
        subscription_id = _clean_str(sub.get("id")) if isinstance(sub, Mapping) else None
        if subscription_id is None:
            continue
        if not should_deliver_publish_event(
            sub.get("min_severity"),
            max_severity=max_severity,
            changelog_status=changelog_status,
        ):
            continue
        try:
            row = db.enqueue_push_webhook_delivery(
                tenant_id,
                subscription_id,
                EVENT_TYPE_VERSION_PUBLISHED,
                payload,
            )
            event_id = _clean_str(row.get("id")) if isinstance(row, Mapping) else None
            if event_id is not None:
                enqueued.append(event_id)
        except Exception:
            # A subscription may have been deactivated/deleted between the listing
            # and the enqueue; skip it rather than fail the whole fan-out.
            logger.exception(
                "publish-notification fan-out: failed to enqueue %s for subscription %s",
                EVENT_TYPE_VERSION_PUBLISHED,
                subscription_id,
            )
    return enqueued


def notify_version_published_on_publish(
    *,
    tenant_id: str,
    project_id: str,
    published_revision_id: str,
    actor_id: Optional[str],
) -> None:
    """Background-task entrypoint: load publish context, then fan out.

    Scheduled by the publish route *after* the CTG-3.1 changelog task, so the
    ``version_changelogs`` row is already persisted (background tasks run in
    order). Skips silently when the revision is missing or not published (e.g.
    unpublished between response and task execution). Never raises.

    Args:
        tenant_id: Owning tenant id.
        project_id: The catalog project the version belongs to.
        published_revision_id: The published version's revision record id.
        actor_id: The user who published, when known.
    """
    db = default_db

    try:
        version = db.get_version_by_id(published_revision_id, tenant_id)
        if not version or not version.get("published"):
            return
        version_label = _clean_str(version.get("version_id"))

        try:
            changelog_row = db.get_version_changelog(
                published_revision_id, tenant_id, project_id
            )
        except Exception:
            logger.exception(
                "publish-notification: failed to load changelog for revision %s",
                published_revision_id,
            )
            changelog_row = None

        notify_version_published(
            db,
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=published_revision_id,
            version_label=version_label,
            actor_id=actor_id,
            changelog_row=changelog_row,
        )
    except Exception:
        logger.exception(
            "publish-notification failed after publish (revision=%s)",
            published_revision_id,
        )
