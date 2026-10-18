"""``catalog.connector.shadow_api_detected`` notifications — CDG-1.6 (#5957).

When a connector sync finds an API it has never seen before, and that API matches nothing in the
catalog (it would land in the report's **Shadow** section), the tenant hears about it once:

    new inventory rows ──► unlinked + no match? ──► won the connector's hourly slot? ──► tenant channels

Delivery reuses REPO-7.2's channel resolution and shaping
(:func:`app.repository_event_notifications.resolve_channels` / ``body_for_channel``): the tenant's
active push-webhook subscriptions, a Slack-native body for a Slack incoming webhook and the
structured JSON for anything else. The throttle is the same one-per-hour conditional upsert, keyed by
connector (V283), because the repository throttle table is keyed by repository.

Routing to the connector's **owner team** is CDG-2.3's: until it lands, every channel of the tenant
receives the event. Possible matches never notify — they wait for a person in the report.

Best-effort throughout: every failure is logged and swallowed, so a notification problem can never
fail the sync that found the API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import quote

from .repository_event_notifications import body_for_channel, resolve_channels
from .shadow_api_report import match_item
from .shadow_api_store import SHADOW_EVENT_TYPE, claim_connector_notification_slot, load_catalog_entries

logger = logging.getLogger(__name__)

__all__ = ["MAX_LISTED", "build_shadow_notification", "notify_new_shadow_apis", "shadow_report_href"]

#: At most this many APIs are named in one notification (``count`` carries the total).
MAX_LISTED = 10


def shadow_report_href(connector_id: str) -> str:
    """The report page, filtered to one connector (a relative application path)."""
    return f"/ade/dashboard/connectors/shadow?connector={quote(connector_id, safe='')}"


def build_shadow_notification(connector: Mapping[str, Any], shadow_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The structured payload for newly found shadow APIs of one connector.

    Args:
        connector: The connector row.
        shadow_rows: The new inventory rows that match nothing in the catalog.

    Returns:
        ``{event, summary, connectorId, connectorName, connectorKind, count, apis, reportHref}``.
    """
    count = len(shadow_rows)
    name = connector.get("name") or connector.get("id")
    noun = "API" if count == 1 else "APIs"
    return {
        "event": SHADOW_EVENT_TYPE,
        "summary": f"{count} new shadow {noun} on {name}: served by the gateway, described nowhere in the catalog.",
        "connectorId": str(connector["id"]),
        "connectorName": connector.get("name"),
        "connectorKind": connector.get("kind"),
        "count": count,
        "apis": [
            {
                "name": row.get("remote_name") or row.get("remote_id"),
                "remoteId": row.get("remote_id"),
                "environment": row.get("environment"),
                "hosts": list(row.get("hosts") or []),
            }
            for row in list(shadow_rows)[:MAX_LISTED]
        ],
        "reportHref": shadow_report_href(str(connector["id"])),
    }


def notify_new_shadow_apis(
    db: Any, connector: Mapping[str, Any], new_rows: Sequence[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Notify the tenant of the new rows that are shadow APIs (see the module docstring).

    Args:
        db: Database handle.
        connector: The connector the sync ran for.
        new_rows: The inventory rows the sync inserted (never seen before).

    Returns:
        ``{shadow, delivered, suppressed}`` describing what happened, or ``None`` when there was
        nothing to report. Never raises.
    """
    try:
        candidates = [r for r in new_rows if not r.get("project_id") and r.get("status") != "ignored"]
        if not candidates:
            return None
        tenant_id = str(connector["tenant_id"])
        entries = load_catalog_entries(db, tenant_id)
        shadow = [row for row in candidates if not match_item(row, entries)]
        if not shadow:
            return None
        channels = resolve_channels(db, tenant_id)
        if not channels:
            return {"shadow": len(shadow), "delivered": [], "suppressed": "no-channels"}
        if not claim_connector_notification_slot(db, tenant_id, str(connector["id"])):
            return {"shadow": len(shadow), "delivered": [], "suppressed": "throttled"}
        payload = build_shadow_notification(connector, shadow)
        delivered: List[str] = []
        for channel in channels:
            try:
                row = db.enqueue_push_webhook_delivery(
                    tenant_id, channel.subscription_id, SHADOW_EVENT_TYPE, body_for_channel(channel, payload)
                )
                if isinstance(row, Mapping) and row.get("id"):
                    delivered.append(str(row["id"]))
            except Exception:  # noqa: BLE001 - one bad subscription must not stop the fan-out
                logger.exception("shadow-api notification: enqueue failed for subscription %s", channel.subscription_id)
        return {"shadow": len(shadow), "delivered": delivered, "suppressed": None}
    except Exception:  # noqa: BLE001 - a notification must never fail the sync
        logger.exception("shadow-api notification failed connector_id=%s", connector.get("id"))
        return None
