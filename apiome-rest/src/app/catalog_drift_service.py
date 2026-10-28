"""Record and announce catalog drift — MFI-31.3 (#4400).

Two entry points, both **best-effort** (they log and swallow every failure), so a notification
problem never fails the refresh check or the sweep that produced the drift:

* :func:`record_refresh_drift` — called by the refresh apply hook (:mod:`app.catalog_refresh_apply`)
  once a refresh added a version over an earlier one. It classifies the change
  (:func:`app.catalog_drift.classify_drift`), stores the event (badge + banner until dismissed) and,
  as the tenant's settings decide (:func:`app.catalog_drift.delivery_for`), announces it right
  away or holds it for the digest.
* :func:`send_due_digests` — called once per refresh-sweep tick. For every tenant whose waiting
  events are a day old (or whose last digest is), it sends one ``catalog.drift.digest`` webhook and
  routes each item's worst drift to its owners.

**Announcing** uses two channels that already exist:

* the tenant's push-webhook subscriptions (:func:`app.push_webhook_fanout.enqueue_event`), with
  their signing, four attempts with backoff and dead-lettering — ``catalog.drift.detected`` per
  event;
* owner routing (CDG-2.3, :func:`app.owner_routing.route_owner_finding_safely`) as an
  ``owner_breaking_change`` finding: an inbox row per member of the item's confirmed owner team and
  a post to the team's chat channel, or the Unowned findings report when the item has no owner.

Email is not sent yet: the tenant's opt-in is stored for a later email channel.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from . import catalog_drift_store as store
from .catalog_drift import (
    DIGEST_INTERVAL_SECONDS,
    EVENT_DETECTED,
    EVENT_DIGEST,
    NOTIFICATION_SENT,
    SEVERITIES,
    classify_drift,
    delivery_for,
    digest_payload,
    drift_payload,
    settings_from_row,
)

_logger = logging.getLogger(__name__)

__all__ = ["announce_event", "record_refresh_drift", "send_due_digests"]


def record_refresh_drift(
    db: Any,
    *,
    item: Mapping[str, Any],
    previous_model: Any,
    new_model: Any,
    version_id: str,
    version_label: str,
    parent_version_id: Optional[str],
    parent_version_label: Optional[str],
    trigger: str,
    actor_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Classify, store and (per the tenant's settings) announce one refresh-created version.

    Never raises.

    Args:
        db: Database handle.
        item: The catalog item (``id``, ``tenant_id``, ``name``, ``slug``).
        previous_model: The superseded version's canonical model.
        new_model: The new version's canonical model.
        version_id: The new version (``versions.id``).
        version_label: Its label.
        parent_version_id: The superseded version.
        parent_version_label: Its label.
        trigger: ``sweep`` or ``manual``.
        actor_id: Who the refresh acted as; never told about it as an owner.

    Returns:
        The stored event row, or ``None`` when recording failed.
    """
    try:
        tenant_id = str(item["tenant_id"])
        classification = classify_drift(previous_model, new_model)
        settings = settings_from_row(store.get_settings_row(db, tenant_id))
        notification = delivery_for(settings, classification.severity, trigger)
        event = store.insert_event(
            db,
            tenant_id=tenant_id,
            project_id=str(item["id"]),
            version_id=version_id,
            parent_version_id=parent_version_id,
            version_label=version_label,
            parent_version_label=parent_version_label,
            trigger=trigger,
            classification=classification,
            notification=notification,
        )
    except Exception:  # noqa: BLE001 - drift recording never fails the refresh check
        _logger.warning("catalog drift: could not record drift for item %s", item.get("id"), exc_info=True)
        return None
    if event and event.get("notification") == NOTIFICATION_SENT:
        announce_event(db, event, item, actor_id=actor_id)
    return event


def announce_event(
    db: Any, event: Mapping[str, Any], item: Mapping[str, Any], *, actor_id: Optional[str] = None
) -> None:
    """Send one ``catalog.drift.detected`` webhook and route the drift to the item's owners.

    Never raises.
    """
    from .push_webhook_fanout import enqueue_event

    tenant_id = str(event["tenant_id"])
    try:
        payload = drift_payload(event, item)
        enqueue_event(db, tenant_id=tenant_id, event_type=EVENT_DETECTED, payload=payload, log_label="catalog drift")
    except Exception:  # noqa: BLE001 - enqueue_event never raises; the payload might
        _logger.warning("catalog drift: could not enqueue event %s", event.get("id"), exc_info=True)
        return
    _route_to_owner(db, tenant_id=tenant_id, item=item, payload=payload, actor_id=actor_id)


def _route_to_owner(
    db: Any,
    *,
    tenant_id: str,
    item: Mapping[str, Any],
    payload: Mapping[str, Any],
    actor_id: Optional[str],
) -> None:
    """Route one event's payload to the item's owner team as an ``owner_breaking_change`` finding."""
    from .owner_routing import TYPE_OWNER_BREAKING_CHANGE, OwnerFinding, route_owner_finding_safely

    try:
        route_owner_finding_safely(
            db,
            OwnerFinding(
                tenant_id=tenant_id,
                entity_kind="catalog_item",
                entity_id=str(item["id"]),
                finding_type=TYPE_OWNER_BREAKING_CHANGE,
                summary=str(payload["summary"]),
                link=str(payload["link"]),
                finding_id=str(payload["eventId"]),
                entity_name=item.get("name"),
                details={
                    "severity": payload["severity"],
                    "counts": payload["counts"],
                    "fromVersion": payload["versions"]["from"]["label"],
                    "toVersion": payload["versions"]["to"]["label"],
                },
                actor_id=actor_id,
                version_id=payload["versions"]["to"]["id"],
            ),
        )
    except Exception:  # noqa: BLE001 - owner routing never fails the producer
        _logger.warning("catalog drift: owner routing failed for item %s", item.get("id"), exc_info=True)


def send_due_digests(db: Any, *, now: Any = None, interval_seconds: int = DIGEST_INTERVAL_SECONDS) -> int:
    """Send the daily digest to every tenant that is due one.

    Per tenant: one ``catalog.drift.digest`` webhook listing every waiting event, then each item's
    worst waiting event routed to its owners, then the events marked ``digested``. Never raises.

    Args:
        db: Database handle.
        now: The digest's end time (tests pin it); defaults to the current UTC time.
        interval_seconds: The least time between two digests of a tenant.

    Returns:
        How many digests were sent.
    """
    from datetime import datetime, timezone

    from .push_webhook_fanout import enqueue_event

    try:
        tenants = store.tenants_due_for_digest(db, interval_seconds=interval_seconds)
    except Exception:  # noqa: BLE001 - the digest never fails the sweep
        _logger.warning("catalog drift: could not list tenants due a digest", exc_info=True)
        return 0
    end = now or datetime.now(timezone.utc)
    sent = 0
    for tenant_id in tenants:
        try:
            events = store.pending_digest_events(db, tenant_id)
            if not events:
                continue
            payload = digest_payload(events, window_start=events[0].get("created_at"), window_end=end)
            enqueue_event(
                db, tenant_id=tenant_id, event_type=EVENT_DIGEST, payload=payload, log_label="catalog drift digest"
            )
            for event in _worst_per_item(events):
                item = {"id": event["project_id"], "name": event.get("item_name"), "slug": event.get("item_slug")}
                _route_to_owner(db, tenant_id=tenant_id, item=item, payload=drift_payload(event, item), actor_id=None)
            store.mark_digested(db, tenant_id, [str(event["id"]) for event in events])
            sent += 1
        except Exception:  # noqa: BLE001 - one tenant's failure never stops the others
            _logger.warning("catalog drift: digest failed for tenant %s", tenant_id, exc_info=True)
    return sent


def _worst_per_item(events: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Each item's most severe event (the newest on a tie), in first-seen order."""
    rank = {severity: index for index, severity in enumerate(SEVERITIES)}
    best: Dict[str, Mapping[str, Any]] = {}
    for event in events:
        key = str(event["project_id"])
        current = best.get(key)
        if current is None or rank.get(str(event["severity"]), 0) >= rank.get(str(current["severity"]), 0):
            best[key] = event
    return list(best.values())
