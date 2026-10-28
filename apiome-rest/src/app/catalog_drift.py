"""Catalog drift — classification, alert settings and payloads (MFI-31.3, #4400).

When a live refresh (MFI-31.2, :mod:`app.catalog_refresh_apply`) adds a version to a catalog item,
the change from the version it supersedes is **drift**: the live API moved. This module holds the
rules, with no database and no clock, so they are unit-testable on their own:

* **Classify.** :func:`classify_drift` grades the change with the breaking-change engine (MFI-3.3,
  :func:`app.breaking_change.classify_models`, including each format's own classifier such as the
  GraphQL and Protobuf packs): every change is ``safe``, ``dangerous`` or ``breaking`` and the event
  takes the worst. The changes are kept worst first, capped at :data:`MAX_STORED_CHANGES`.
* **Decide delivery.** :func:`delivery_for` reads the tenant's :class:`DriftSettings`. A severity
  that does not notify only badges (``none``). Otherwise a sweep-created version is sent right away
  (``sent``) or held for the daily digest (``pending_digest``); breaking changes skip the digest
  unless the tenant turned that off. A version a person created with **Check now** is never
  announced: they are looking at the result.
* **Shape payloads.** :func:`drift_payload` is the ``catalog.drift.detected`` webhook body (the
  artifact, the two versions, the severity, the counts and the top findings) and
  :func:`digest_payload` the ``catalog.drift.digest`` body.

Storage is :mod:`app.catalog_drift_store`; the event is recorded and announced by
:mod:`app.catalog_drift_service`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

__all__ = [
    "DELIVERIES",
    "DELIVERY_DAILY_DIGEST",
    "DELIVERY_IMMEDIATE",
    "DIGEST_INTERVAL_SECONDS",
    "EVENT_DETECTED",
    "EVENT_DIGEST",
    "MAX_STORED_CHANGES",
    "NOTIFICATION_DIGESTED",
    "NOTIFICATION_NONE",
    "NOTIFICATION_PENDING_DIGEST",
    "NOTIFICATION_SENT",
    "SEVERITIES",
    "TOP_FINDINGS",
    "DriftClassification",
    "DriftSettings",
    "classify_drift",
    "delivery_for",
    "digest_payload",
    "drift_link",
    "drift_payload",
    "drift_summary",
    "settings_from_row",
]

#: Severities, least to most severe (the MFI-3.3 vocabulary).
SEVERITIES = ("safe", "dangerous", "breaking")
_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}

#: Delivery modes a tenant can choose.
DELIVERY_IMMEDIATE = "immediate"
DELIVERY_DAILY_DIGEST = "daily_digest"
DELIVERIES = (DELIVERY_IMMEDIATE, DELIVERY_DAILY_DIGEST)

#: How an event was announced (``catalog_drift_events.notification``).
NOTIFICATION_NONE = "none"
NOTIFICATION_SENT = "sent"
NOTIFICATION_PENDING_DIGEST = "pending_digest"
NOTIFICATION_DIGESTED = "digested"

#: Webhook event types.
EVENT_DETECTED = "catalog.drift.detected"
EVENT_DIGEST = "catalog.drift.digest"

#: Most changes stored on an event (``change_count`` keeps the full count).
MAX_STORED_CHANGES = 200
#: Changes a notification lists as its top findings.
TOP_FINDINGS = 5
#: A digest goes out at most this often per tenant.
DIGEST_INTERVAL_SECONDS = 86400


@dataclass(frozen=True)
class DriftSettings:
    """A tenant's drift alert settings. The defaults are what a tenant without a row gets.

    Attributes:
        notify_breaking: Announce breaking drift.
        notify_dangerous: Announce dangerous drift.
        notify_safe: Announce safe drift (off: safe drift only badges).
        delivery: ``immediate`` or ``daily_digest``.
        breaking_immediate: In digest mode, still send breaking drift right away.
        email_enabled: Stored opt-in for an email channel; nothing is emailed yet.
    """

    notify_breaking: bool = True
    notify_dangerous: bool = True
    notify_safe: bool = False
    delivery: str = DELIVERY_IMMEDIATE
    breaking_immediate: bool = True
    email_enabled: bool = False

    def notifies(self, severity: str) -> bool:
        """Whether drift of ``severity`` is announced at all (else it only badges)."""
        return {
            "breaking": self.notify_breaking,
            "dangerous": self.notify_dangerous,
            "safe": self.notify_safe,
        }.get(severity, False)

    def as_dict(self) -> Dict[str, Any]:
        """The settings as a plain dict (snake_case keys)."""
        return asdict(self)


def settings_from_row(row: Optional[Mapping[str, Any]]) -> DriftSettings:
    """The settings stored in a ``catalog_drift_settings`` row, or the defaults for ``None``."""
    if not row:
        return DriftSettings()
    defaults = DriftSettings()
    delivery = str(row.get("delivery") or defaults.delivery)
    return DriftSettings(
        notify_breaking=bool(row.get("notify_breaking", defaults.notify_breaking)),
        notify_dangerous=bool(row.get("notify_dangerous", defaults.notify_dangerous)),
        notify_safe=bool(row.get("notify_safe", defaults.notify_safe)),
        delivery=delivery if delivery in DELIVERIES else defaults.delivery,
        breaking_immediate=bool(row.get("breaking_immediate", defaults.breaking_immediate)),
        email_enabled=bool(row.get("email_enabled", defaults.email_enabled)),
    )


# ---------------------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftClassification:
    """The graded drift between two versions.

    Attributes:
        severity: The worst severity (``safe`` when nothing changed semantically).
        counts: Changes per severity, every severity present (``0`` when none).
        change_count: Every classified change, including those past the stored cap.
        changes: The changes, worst first, at most :data:`MAX_STORED_CHANGES`. Each has
            ``severity``, ``category``, ``kind``, ``key``, ``ruleId`` and ``rationale``.
    """

    severity: str
    counts: Dict[str, int]
    change_count: int
    changes: List[Dict[str, Any]]


def classify_drift(previous_model: Any, new_model: Any) -> DriftClassification:
    """Grade the change from ``previous_model`` to ``new_model`` with the MFI-3.3 engine.

    Findings a format's own diff tool reports without a canonical change (``unattributed``) are
    included, so the severity is the one a publish gate would see.

    Args:
        previous_model: The superseded version's :class:`~app.canonical_model.CanonicalApi`.
        new_model: The new version's model.

    Returns:
        The :class:`DriftClassification`.
    """
    from .breaking_change import classify_models

    result = classify_models(previous_model, new_model)
    changes: List[Dict[str, Any]] = [
        {
            "severity": _value(c.severity),
            "category": _value(c.category),
            "kind": _value(c.kind),
            "key": c.key,
            "ruleId": c.rule_id,
            "rationale": c.rationale,
        }
        for c in result.classifications
    ]
    changes.extend(
        {
            "severity": _value(f.severity),
            "category": None,
            "kind": None,
            "key": f.shape,
            "ruleId": f.rule_id,
            "rationale": f.rationale,
        }
        for f in result.unattributed
    )
    # Worst first; the stable sort keeps the diff's own order within a severity.
    changes.sort(key=lambda change: -_RANK.get(change["severity"], 0))
    counts = {severity: 0 for severity in SEVERITIES}
    for change in changes:
        counts[change["severity"]] = counts.get(change["severity"], 0) + 1
    return DriftClassification(
        severity=_value(result.overall_severity),
        counts=counts,
        change_count=len(changes),
        changes=changes[:MAX_STORED_CHANGES],
    )


def _value(item: Any) -> Any:
    """An enum's value, or the item itself."""
    return getattr(item, "value", item)


# ---------------------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------------------


def delivery_for(settings: DriftSettings, severity: str, trigger: str) -> str:
    """How a new drift event is announced.

    Args:
        settings: The tenant's settings.
        severity: The event's severity.
        trigger: ``sweep`` or ``manual``; a manual check is never announced.

    Returns:
        :data:`NOTIFICATION_NONE` (badge only), :data:`NOTIFICATION_SENT` (send now) or
        :data:`NOTIFICATION_PENDING_DIGEST` (hold for the daily digest).
    """
    if trigger != "sweep" or not settings.notifies(severity):
        return NOTIFICATION_NONE
    if settings.delivery == DELIVERY_DAILY_DIGEST and not (severity == "breaking" and settings.breaking_immediate):
        return NOTIFICATION_PENDING_DIGEST
    return NOTIFICATION_SENT


# ---------------------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------------------


def drift_link(item_id: str, event_id: str) -> str:
    """The app link to an event: the item's Versions tab, opened on the event's changes."""
    from urllib.parse import quote, urlencode

    return f"/ade/dashboard/catalog/{quote(str(item_id), safe='')}?{urlencode({'tab': 'versions', 'drift': event_id})}"


def drift_summary(item_name: str, severity: str, counts: Mapping[str, int]) -> str:
    """One sentence for an inbox row or a chat message, e.g. ``Orders API drifted: 2 breaking changes.``"""
    count = int(counts.get(severity, 0))
    noun = "change" if count == 1 else "changes"
    return f"{item_name or 'A catalog item'} drifted: {count} {severity} {noun}."


def _top_findings(changes: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The first :data:`TOP_FINDINGS` changes (they are stored worst first)."""
    return [
        {key: change.get(key) for key in ("severity", "key", "ruleId", "rationale")}
        for change in list(changes)[:TOP_FINDINGS]
    ]


def drift_payload(event: Mapping[str, Any], item: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``catalog.drift.detected`` webhook body for one event.

    Args:
        event: The stored ``catalog_drift_events`` row.
        item: The catalog item (``id``, ``name``, ``slug``).

    Returns:
        A JSON-serializable dict: the artifact, both versions, severity, counts, top findings, the
        trigger and an app link. Never a credential or an endpoint.
    """
    counts = dict(event.get("counts") or {})
    return {
        "event": EVENT_DETECTED,
        "eventId": str(event["id"]),
        "artifact": {"kind": "catalog_item", "id": str(item["id"]), "name": item.get("name"), "slug": item.get("slug")},
        "versions": {
            "from": {"id": _str_or_none(event.get("parent_version_id")), "label": event.get("parent_version_label")},
            "to": {"id": str(event["version_id"]), "label": event.get("version_label")},
        },
        "severity": event["severity"],
        "counts": counts,
        "changeCount": int(event.get("change_count") or 0),
        "topFindings": _top_findings(event.get("changes") or []),
        "trigger": event.get("trigger"),
        "summary": drift_summary(str(item.get("name") or ""), str(event["severity"]), counts),
        "link": drift_link(str(item["id"]), str(event["id"])),
        "detectedAt": _iso(event.get("created_at")),
    }


def digest_payload(entries: Sequence[Mapping[str, Any]], *, window_start: Any, window_end: Any) -> Dict[str, Any]:
    """The ``catalog.drift.digest`` webhook body.

    Args:
        entries: ``catalog_drift_events`` rows joined with the item's ``item_name`` / ``item_slug``,
            oldest first.
        window_start: The oldest event's time.
        window_end: When the digest was built.

    Returns:
        A JSON-serializable dict with per-severity totals and one entry per event.
    """
    totals = {severity: 0 for severity in SEVERITIES}
    items: List[Dict[str, Any]] = []
    for entry in entries:
        totals[str(entry["severity"])] = totals.get(str(entry["severity"]), 0) + 1
        item = {"id": entry["project_id"], "name": entry.get("item_name"), "slug": entry.get("item_slug")}
        body = drift_payload(entry, item)
        body.pop("event", None)
        items.append(body)
    return {
        "event": EVENT_DIGEST,
        "windowStart": _iso(window_start),
        "windowEnd": _iso(window_end),
        "eventCount": len(items),
        "bySeverity": totals,
        "events": items,
    }


def _str_or_none(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _iso(value: Any) -> Optional[str]:
    """An ISO-8601 timestamp, or the value unchanged when it has no ``isoformat``."""
    return value.isoformat() if hasattr(value, "isoformat") else value
