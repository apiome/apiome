"""One delivery per active subscription — the shared push-webhook fan-out (CTG-4.4, #4501).

Every provider-neutral notification family in this codebase ends the same way: list the tenant's
active push-webhook subscriptions, enqueue one delivery per subscription, and never let a delivery
problem fail the thing being described. :func:`enqueue_event` is that loop, once.

**Signing, retry, and dead-lettering are not here.** They belong to the delivery pipeline
(``push_webhook_delivery``); this function only decides what is enqueued and for whom.

**It never raises.** A tenant whose subscription table cannot be read, or a subscription
deactivated between the listing and the enqueue, produces a logged skip and an empty or shorter
list — because a notification failure must never turn a completed scan, refresh, digest, or
verification into a failed one.

Four callers predate this module (``repository_refresh_notifications``, ``lint_notifications``,
``mcp_catalog_digest_sweep``, ``mcp_trust_baseline_routes``), each with its own copy of the loop.
They are deliberately left alone: migrating four unrelated notification surfaces is not this
ticket's job, and each copy is behaviourally identical to this one. New notification families
should call this rather than write a fifth.
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping

logger = logging.getLogger(__name__)

__all__ = ["enqueue_event"]


def enqueue_event(
    db: Any,
    *,
    tenant_id: str,
    event_type: str,
    payload: Mapping[str, Any],
    log_label: str,
) -> List[str]:
    """Enqueue one delivery of ``event_type`` per active subscription in ``tenant_id``.

    Args:
        db: Database handle exposing ``list_active_push_webhook_subscription_ids`` and
            ``enqueue_push_webhook_delivery``.
        tenant_id: Subscription and delivery scope.
        event_type: The event type stamped on each delivery (e.g. ``verification.drift.detected``).
        payload: JSON-serializable notification body. Copied, so a caller may reuse its dict.
        log_label: Short family name used in log lines, so a failure names the feature that
            produced it rather than only this shared helper.

    Returns:
        The enqueued delivery-event ids. Empty when the tenant has no active subscription, when
        the listing failed, or when every enqueue failed.
    """
    try:
        subscription_ids = db.list_active_push_webhook_subscription_ids(tenant_id)
    except Exception:  # noqa: BLE001 - notification fan-out never raises
        logger.exception(
            "%s fan-out: failed to list subscriptions for tenant %s", log_label, tenant_id
        )
        return []

    enqueued: List[str] = []
    for subscription_id in subscription_ids:
        try:
            row = db.enqueue_push_webhook_delivery(
                tenant_id, subscription_id, event_type, dict(payload)
            )
            event_id = (
                str(row["id"])
                if isinstance(row, Mapping) and row.get("id") is not None
                else None
            )
            if event_id is not None:
                enqueued.append(event_id)
        except Exception:  # noqa: BLE001 - a dead subscription must not fail the batch
            logger.exception(
                "%s fan-out: failed to enqueue %s for subscription %s",
                log_label,
                event_type,
                subscription_id,
            )
    return enqueued
