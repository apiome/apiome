"""The usage sweep's sunset check — "still used" alerts (RDG-5.3, #5788).

Each usage-sweep tick (:mod:`app.usage_sweep`) calls :func:`check_sunset_still_used` after the
rollup, so the window it reads is fresh. For every revision whose sunset is 0–30 days away and
that bound consumers called in the last 7 days (``prod``), it:

1. resolves the version's collaborators — the COL-3.1 rule
   (:meth:`app.database.Database.list_version_collaborators`), before the transaction;
2. claims the week and writes one ``sunset_still_used`` inbox row per collaborator in one
   transaction (:func:`app.sunset_readiness_store.claim_and_notify`) — so at most one alert per
   revision per 7 days, enforced by ``sunset_still_used_alert``, not by this process;
3. sends a ``sunset.still_used`` push-webhook event (:func:`app.push_webhook_fanout.enqueue_event`).

A revision with no collaborators still claims its week and sends the webhook. Anonymous traffic
alone never alerts. One revision's failure is logged and the next one is checked.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from .notification_fanout import NotificationDraft, recipients
from .notifications import TYPE_SUNSET_STILL_USED
from .push_webhook_fanout import enqueue_event
from .revision_deprecation import effective_sunset_string
from .sunset_readiness import (
    EVENT_STILL_USED,
    days_until_sunset,
    is_alert_due,
    notification_payload,
    summarize_usage,
    webhook_payload,
)
from .sunset_readiness_store import alert_candidates, candidate_project, claim_and_notify, usage_for_revisions

__all__ = ["check_sunset_still_used"]

_logger = logging.getLogger(__name__)


def check_sunset_still_used(db: Any, *, today: Optional[date] = None) -> int:
    """Send this tick's "still used before its sunset" alerts.

    Args:
        db: The sweep's database handle.
        today: The current UTC day; defaults to now.

    Returns:
        How many revisions were alerted about.
    """
    today = today or datetime.now(timezone.utc).date()
    sent = 0
    for row in alert_candidates(db, today=today):
        try:
            if _alert(db, row, today):
                sent += 1
        except Exception:  # noqa: BLE001 - one revision must not stop the others
            _logger.warning(
                "sunset still-used check failed for revision %s", row.get("revision_id"), exc_info=True
            )
    return sent


def _alert(db: Any, row: Any, today: date) -> bool:
    """Alert about one candidate, if it is due and its week is unclaimed.

    Args:
        db: The database.
        row: An :func:`app.sunset_readiness_store.alert_candidates` row.
        today: The current UTC day.

    Returns:
        True when the alert was sent.
    """
    tenant_id = str(row["tenant_id"])
    project_id = str(row["project_id"])
    revision_id = str(row["revision_id"])
    metadata = row.get("metadata")
    days_left = days_until_sunset(metadata, today)
    if days_left is None:
        return False
    usage = summarize_usage(
        usage_for_revisions(db, tenant_id, [(revision_id, project_id)], today=today).get(revision_id, []),
        project_id=project_id,
        consumers_visible=True,
    )
    if not is_alert_due(metadata, usage, today):
        return False

    project = candidate_project(row)
    label = str(row.get("version_label") or "")
    sunset_at = effective_sunset_string(metadata)
    payload = notification_payload(
        project=project, version_label=label, sunset_at=sunset_at, days_left=days_left, usage=usage
    )
    users = recipients(
        db.list_version_collaborators(tenant_id=tenant_id, project_id=project_id, version_id=revision_id)
    )
    drafts = [
        NotificationDraft(
            user_id=user,
            type=TYPE_SUNSET_STILL_USED,
            payload=dict(payload),
            project_id=project_id,
            version_id=revision_id,
        )
        for user in users
    ]
    if not claim_and_notify(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        revision_id=revision_id,
        sunset_at=sunset_at,
        usage=usage,
        drafts=drafts,
    ):
        return False
    enqueue_event(
        db,
        tenant_id=tenant_id,
        event_type=EVENT_STILL_USED,
        payload=webhook_payload(
            tenant_id=tenant_id,
            project=project,
            version_record_id=revision_id,
            version_label=label,
            sunset_at=sunset_at,
            days_left=days_left,
            usage=usage,
        ),
        log_label="sunset still used",
    )
    return True
