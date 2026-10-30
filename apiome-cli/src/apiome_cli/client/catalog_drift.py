"""Catalog drift — request bodies and table rows for ``apiome catalog drift`` (MFI-31.3).

Pure helpers, so the command module only parses options, calls REST and prints. REST owns every
rule; these only build the body it expects and flatten its answers into rows.
"""

from __future__ import annotations

from typing import Any

#: Delivery modes REST accepts.
DELIVERIES = ("immediate", "daily_digest")

#: ``(flag value name, REST key)`` for the boolean settings, in display order.
_SETTING_LABELS = (
    ("Notify breaking", "notifyBreaking"),
    ("Notify dangerous", "notifyDangerous"),
    ("Notify safe", "notifySafe"),
    ("Delivery", "delivery"),
    ("Breaking skips digest", "breakingImmediate"),
    ("Email owner team", "emailEnabled"),
)


def alerts_body(current: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The ``PUT …/drift-notifications`` body: the current settings with the given changes.

    REST replaces the whole setting, so options the caller left out keep their current value.

    Args:
        current: The ``GET …/drift-notifications`` answer.
        **changes: REST keys (``notifyBreaking``, ``delivery`` …) mapped to new values; ``None``
            values are ignored.

    Returns:
        The JSON body.

    Raises:
        ValueError: An unknown delivery mode.
    """
    body = {
        key: current.get(key)
        for _label, key in _SETTING_LABELS
        if current.get(key) is not None
    }
    body.update({key: value for key, value in changes.items() if value is not None})
    if body.get("delivery") not in (None, *DELIVERIES):
        raise ValueError(f"delivery must be one of {', '.join(DELIVERIES)}")
    return body


def alerts_rows(settings: dict[str, Any]) -> list[dict[str, str]]:
    """``Field`` / ``Value`` rows for the drift alert settings."""
    rows = []
    for label, key in _SETTING_LABELS:
        value = settings.get(key)
        rows.append(
            {
                "field": label,
                "value": value
                if isinstance(value, str)
                else ("yes" if value else "no"),
            }
        )
    if not settings.get("configured"):
        rows.append({"field": "Source", "value": "defaults (never saved)"})
    if settings.get("lastDigestAt"):
        rows.append({"field": "Last digest", "value": str(settings["lastDigestAt"])})
    return rows


def event_rows(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """One row per drift event for ``apiome catalog drift list``."""
    rows = []
    for event in events:
        counts = event.get("counts") or {}
        rows.append(
            {
                "id": str(event.get("eventId")),
                "severity": str(event.get("severity")),
                "versions": f"{event.get('parentVersionLabel') or '—'} → {event.get('versionLabel')}",
                "changes": f"{event.get('changeCount', 0)} ({counts.get('breaking', 0)} breaking, "
                f"{counts.get('dangerous', 0)} dangerous)",
                "trigger": str(event.get("trigger")),
                "state": "dismissed" if event.get("dismissedAt") else "open",
            }
        )
    return rows


def change_rows(event: dict[str, Any]) -> list[dict[str, str]]:
    """One row per classified change of an event, worst first."""
    return [
        {
            "severity": str(change.get("severity")),
            "key": str(change.get("key") or "—"),
            "rationale": str(change.get("rationale") or ""),
        }
        for change in event.get("changes") or []
    ]
