"""Change-notification events for MCP catalog endpoints (V2-MCP-27.1 / MCAT-13.1, #3711).

Downstream consumers want to know *when an MCP server changed* without polling its version
history. The version-on-change pipeline (MCAT-4.3, :func:`app.mcp_discovery_engine._persist_outcome`)
already decides exactly when that happens — a discovery whose surface fingerprint differs from
the current snapshot persists one new ``mcp_endpoint_versions`` row. This module turns that moment
into an **internal event** other code can subscribe to::

    discovery ──► new version persisted ──► emit_version_created(event)
                                              └─► every subscribed handler(event)

The event is ``mcp.version.created`` (:data:`EVENT_TYPE_VERSION_CREATED`) and carries the endpoint
identity, the new version's ``version_seq`` / ``version_tag``, and a **change summary** folded from
the persisted ``mcp_version_changes`` rows (counts by change type, item type and breaking-change
severity). It is the foundation for tenant webhook subscriptions (MCAT-13.2, #3712), which will
register a handler here.

Design rules:

* **Exactly once per new version.** The discovery engine emits only on the *changed* path, after
  the transactional persist returns, and never on an unchanged re-discovery. The event's
  ``event_id`` is derived deterministically from the version id (:func:`event_id_for_version`),
  so a consumer that does see a duplicate (e.g. a future retrying transport) can de-duplicate.
* **Best-effort, never blocking.** A handler that raises is logged and skipped; the remaining
  handlers still run and :func:`emit_version_created` never raises, so a notification problem can
  never fail the discovery job that produced the version.
* **No secret ever emitted.** The payload names the endpoint by id / name / slug only — the stored
  ``endpoint_url`` (which may embed a credential) is never read.
* **In-process and thread-safe.** Handlers are held in a module-level registry guarded by a lock;
  emission happens on the discovery worker thread (:func:`asyncio.to_thread`), so handlers must be
  synchronous and quick (hand heavy work to a queue).
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

from .mcp_change_severity import SEVERITY_ORDER, severity_counts
from .mcp_client.diff import CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_REMOVED

logger = logging.getLogger(__name__)

#: Event type stamped on every new-version event. Namespaced alongside the other MCP event
#: families (``mcp.catalog.digest``, ``mcp.trust.drift``) so a subscriber can route it distinctly.
EVENT_TYPE_VERSION_CREATED = "mcp.version.created"

#: Payload schema version, bumped only on a breaking change to :meth:`McpVersionCreatedEvent.to_payload`.
EVENT_SCHEMA_VERSION = 1

#: Namespace for the deterministic ``event_id`` (uuid5 of the version id). Fixed forever: changing
#: it would give an already-delivered version a new identity and defeat consumer de-duplication.
_EVENT_ID_NAMESPACE = uuid.UUID("6f1d3c52-4b7e-5a39-9c0e-2d8f7a1b3e64")

#: The change types a summary always reports, in display order (zero when absent).
_CHANGE_TYPES = (CHANGE_ADDED, CHANGE_REMOVED, CHANGE_MODIFIED)

#: A subscriber: called once per emitted event, synchronously, on the emitting thread.
EventHandler = Callable[["McpVersionCreatedEvent"], None]

_handlers: List[EventHandler] = []
_handlers_lock = threading.Lock()


def event_id_for_version(version_id: str) -> str:
    """Return the stable event id for the version-created event of ``version_id``.

    Args:
        version_id: The new ``mcp_endpoint_versions`` row id.

    Returns:
        A UUID string that is identical every time it is computed for the same version, so
        consumers can use it as an idempotency key.
    """
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, str(version_id)))


def build_change_summary(
    change_rows: Iterable[Mapping[str, Any]], *, initial: bool
) -> Dict[str, Any]:
    """Fold persisted diff rows into the compact summary carried on the event.

    Args:
        change_rows: ``mcp_version_changes``-shaped dicts (``change_type`` / ``item_type`` /
            ``item_name`` / ``detail``) relative to the previous version.
        initial: ``True`` when this is the endpoint's first version (every item is ``added``).

    Returns:
        ``{"initial", "total", "by_change_type", "by_item_type", "by_severity", "max_severity"}``.
        ``by_change_type`` always lists ``added`` / ``removed`` / ``modified``; ``by_severity``
        always lists every severity; ``max_severity`` is ``None`` when there are no changes.
    """
    rows = list(change_rows)
    by_change_type = {change_type: 0 for change_type in _CHANGE_TYPES}
    by_item_type: Dict[str, int] = {}
    for row in rows:
        change_type = str(row.get("change_type") or "")
        by_change_type[change_type] = by_change_type.get(change_type, 0) + 1
        item_type = str(row.get("item_type") or "")
        by_item_type[item_type] = by_item_type.get(item_type, 0) + 1

    tallies = severity_counts(rows)
    by_severity = {severity: tallies[severity] for severity in SEVERITY_ORDER}
    max_severity: Optional[str] = None
    for severity in SEVERITY_ORDER:
        if by_severity.get(severity):
            max_severity = severity
    return {
        "initial": initial,
        "total": len(rows),
        "by_change_type": by_change_type,
        "by_item_type": dict(sorted(by_item_type.items())),
        "by_severity": by_severity,
        "max_severity": max_severity,
    }


@dataclass(frozen=True)
class McpVersionCreatedEvent:
    """One ``mcp.version.created`` event: an endpoint's surface changed and a version was persisted.

    Attributes:
        event_id: Deterministic id (:func:`event_id_for_version`) — the consumer idempotency key.
        tenant_id: The endpoint's owning tenant.
        endpoint_id: The catalog endpoint that changed.
        endpoint_name: Its display name (may be empty).
        endpoint_slug: Its URL slug (may be empty).
        version_id: The new ``mcp_endpoint_versions`` row.
        version_seq: The new version's per-endpoint sequence (1 on first discovery).
        version_tag: Its human-readable date/time tag (MCAT-4.4), when assigned.
        previous_version_id: The snapshot this version replaced; ``None`` on first discovery.
        previous_version_seq: That snapshot's sequence; ``None`` on first discovery.
        discovered_at: When the discovery that produced the version ran.
        discovery_trigger: ``manual`` / ``sweep`` / ``registry`` provenance, when recorded.
        change_summary: :func:`build_change_summary` output.
        event_type: Always :data:`EVENT_TYPE_VERSION_CREATED`.
    """

    event_id: str
    tenant_id: str
    endpoint_id: str
    endpoint_name: str
    endpoint_slug: str
    version_id: str
    version_seq: int
    version_tag: Optional[str]
    previous_version_id: Optional[str]
    previous_version_seq: Optional[int]
    discovered_at: datetime
    discovery_trigger: Optional[str]
    change_summary: Dict[str, Any] = field(default_factory=dict)
    event_type: str = EVENT_TYPE_VERSION_CREATED

    def to_payload(self) -> Dict[str, Any]:
        """Return the JSON-serializable payload a transport (e.g. a webhook) would send.

        Returns:
            A dict with ``event_id`` / ``event_type`` / ``schema_version``, an ``endpoint`` block
            (id, tenant, name, slug — never the URL), a ``version`` block, a ``previous_version``
            block (``None`` on first discovery), ``discovered_at`` (ISO-8601), ``trigger`` and
            ``change_summary``.
        """
        previous = None
        if self.previous_version_id is not None:
            previous = {"id": self.previous_version_id, "seq": self.previous_version_seq}
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "schema_version": EVENT_SCHEMA_VERSION,
            "endpoint": {
                "id": self.endpoint_id,
                "tenant_id": self.tenant_id,
                "name": self.endpoint_name,
                "slug": self.endpoint_slug,
            },
            "version": {
                "id": self.version_id,
                "seq": self.version_seq,
                "tag": self.version_tag,
            },
            "previous_version": previous,
            "discovered_at": self.discovered_at.isoformat(),
            "trigger": self.discovery_trigger,
            "change_summary": self.change_summary,
        }


def build_version_created_event(
    endpoint: Mapping[str, Any],
    persisted: Mapping[str, Any],
    previous: Optional[Mapping[str, Any]],
    change_rows: Iterable[Mapping[str, Any]],
    *,
    discovered_at: datetime,
    discovery_trigger: Optional[str] = None,
) -> McpVersionCreatedEvent:
    """Assemble the event for a freshly persisted version.

    Args:
        endpoint: The ``mcp_endpoints`` row (``id``, ``tenant_id``, ``name``, ``slug``).
        persisted: :meth:`Database.record_mcp_discovery_version` result (``version_id``,
            ``version_seq``, optional ``version_tag``).
        previous: The version row this one replaced (``id``, ``version_seq``), or ``None``.
        change_rows: The diff rows persisted with the version.
        discovered_at: When the producing discovery ran.
        discovery_trigger: The producing job's trigger, when known.

    Returns:
        The populated :class:`McpVersionCreatedEvent`.
    """
    version_id = str(persisted["version_id"])
    return McpVersionCreatedEvent(
        event_id=event_id_for_version(version_id),
        tenant_id=str(endpoint.get("tenant_id") or ""),
        endpoint_id=str(endpoint["id"]),
        endpoint_name=str(endpoint.get("name") or ""),
        endpoint_slug=str(endpoint.get("slug") or ""),
        version_id=version_id,
        version_seq=int(persisted["version_seq"]),
        version_tag=persisted.get("version_tag"),
        previous_version_id=str(previous["id"]) if previous is not None else None,
        previous_version_seq=int(previous["version_seq"]) if previous is not None else None,
        discovered_at=discovered_at,
        discovery_trigger=discovery_trigger,
        change_summary=build_change_summary(change_rows, initial=previous is None),
    )


def subscribe(handler: EventHandler) -> None:
    """Register ``handler`` to receive every future version-created event.

    Registering the same handler twice is a no-op, so a module that subscribes at import time
    cannot be delivered the same event twice.

    Args:
        handler: Synchronous callable taking one :class:`McpVersionCreatedEvent`.
    """
    with _handlers_lock:
        if handler not in _handlers:
            _handlers.append(handler)


def unsubscribe(handler: EventHandler) -> None:
    """Remove ``handler``; unknown handlers are ignored.

    Args:
        handler: A callable previously passed to :func:`subscribe`.
    """
    with _handlers_lock:
        if handler in _handlers:
            _handlers.remove(handler)


def emit_version_created(event: McpVersionCreatedEvent) -> int:
    """Deliver ``event`` to every subscribed handler, isolating failures.

    Never raises. Each handler runs in registration order; one that raises is logged and the
    rest still run.

    Args:
        event: The event to deliver.

    Returns:
        The number of handlers that completed without raising.
    """
    with _handlers_lock:
        handlers = list(_handlers)
    logger.info(
        "mcp event %s endpoint=%s version_seq=%s changes=%s event_id=%s",
        event.event_type,
        event.endpoint_id,
        event.version_seq,
        event.change_summary.get("total"),
        event.event_id,
    )
    delivered = 0
    for handler in handlers:
        try:
            handler(event)
            delivered += 1
        except Exception:  # noqa: BLE001 - one bad subscriber must not affect the others
            logger.exception(
                "mcp event handler %r failed for event_id=%s", handler, event.event_id
            )
    return delivered


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "EVENT_TYPE_VERSION_CREATED",
    "EventHandler",
    "McpVersionCreatedEvent",
    "build_change_summary",
    "build_version_created_event",
    "emit_version_created",
    "event_id_for_version",
    "subscribe",
    "unsubscribe",
]
