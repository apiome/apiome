"""Webhook subscriptions for MCP change events (V2-MCP-27.2 / MCAT-13.2, #3712).

:mod:`app.mcp_change_events` (MCAT-13.1) raises one in-process ``mcp.version.created`` event per
new MCP endpoint version. This module is the subscriber that carries that event **outside
Apiome**: it enqueues one delivery per active tenant push-webhook subscription, reusing the
existing dispatch queue::

    emit_version_created(event)
        └─► deliver_version_created(event)
              └─► push_webhook_fanout.enqueue_event(...)     one row per active subscription
                    └─► push_webhook_delivery worker          HMAC-signed POST, bounded retries,
                                                              then dead-letter

Signing (``X-Apiome-Signature``), the ``X-Apiome-Event: mcp.version.created`` header, retry with
backoff and dead-lettering are all the standard push-webhook pipeline's; nothing here re-implements
them.

Design rules:

* **Tenant-scoped.** Only the subscriptions of the endpoint's own tenant are enqueued; an event
  without a tenant id is dropped (logged) rather than guessed at.
* **Never raises.** Fan-out is best-effort (:func:`app.push_webhook_fanout.enqueue_event` never
  raises, and this handler guards everything else), so a webhook problem never fails the
  discovery job that produced the version.
* **No secret in the body.** The payload is :meth:`McpVersionCreatedEvent.to_payload`, which names
  the endpoint by id / name / slug only — never its URL or credential.
* **Wired by the discovery engine.** :mod:`app.mcp_discovery_engine` subscribes a handler that
  calls :func:`deliver_version_created` with the engine's own database handle, so the queue rows
  are written through the same handle that persisted the version.
* **Cheap on the emitting thread.** The handler only inserts queue rows; the HTTP delivery happens
  later on the delivery worker, so a slow receiver cannot stall discovery.
"""

from __future__ import annotations

import logging
from typing import Any, List

from .mcp_change_events import EVENT_TYPE_VERSION_CREATED, McpVersionCreatedEvent
from .push_webhook_fanout import enqueue_event

logger = logging.getLogger(__name__)

#: Family name used in fan-out log lines, so a failure names this feature.
_LOG_LABEL = "mcp-change-webhook"


def deliver_version_created(event: McpVersionCreatedEvent, db_handle: Any) -> List[str]:
    """Enqueue ``event`` for every active push-webhook subscription in its tenant.

    Args:
        event: The ``mcp.version.created`` event emitted for a new endpoint version.
        db_handle: Database handle exposing ``list_active_push_webhook_subscription_ids`` and
            ``enqueue_push_webhook_delivery`` — the discovery engine passes its own handle.

    Returns:
        The enqueued delivery-event ids — empty when the event has no tenant, the tenant has no
        active subscription, or the fan-out failed. Never raises.
    """
    tenant_id = (event.tenant_id or "").strip()
    if not tenant_id:
        logger.warning(
            "%s: dropping %s without a tenant id event_id=%s",
            _LOG_LABEL,
            event.event_type,
            event.event_id,
        )
        return []
    try:
        payload = event.to_payload()
    except Exception:  # noqa: BLE001 - a notification problem must not fail discovery
        logger.exception(
            "%s: failed to prepare %s event_id=%s",
            _LOG_LABEL,
            event.event_type,
            event.event_id,
        )
        return []
    enqueued = enqueue_event(
        db_handle,
        tenant_id=tenant_id,
        event_type=EVENT_TYPE_VERSION_CREATED,
        payload=payload,
        log_label=_LOG_LABEL,
    )
    if enqueued:
        logger.info(
            "%s: enqueued %d deliveries of %s endpoint=%s event_id=%s",
            _LOG_LABEL,
            len(enqueued),
            event.event_type,
            event.endpoint_id,
            event.event_id,
        )
    return enqueued


__all__ = ["deliver_version_created"]
