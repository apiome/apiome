"""Sunset readiness — who is still on a version that is going away (RDG-5.3, #5788).

The sunset timeline schedules a revision's end. This module answers the question a sunset date
raises: *is anybody still calling it?* It is the pure half — no database, no HTTP — so every rule
here is a unit test:

* :func:`summarize_usage` turns a revision's 7-day ``usage_daily`` rows (one per consumer, plus one
  for anonymous traffic) into the :class:`SunsetUsage` block the sunset timeline and the Published
  page draw — ``"Still used by 2 consumers (1,240 calls, 7-day)"``, or ``"Anonymous traffic only —
  bind consumers to attribute it"`` when nobody bound is on it.
* :func:`days_until_sunset` and :func:`is_alert_due` decide whether the usage sweep should warn:
  the sunset is today or at most :data:`ALERT_WITHIN_DAYS` days away **and** bound consumers still
  call the revision. Anonymous traffic alone never alerts: nobody can be told to move.
* :func:`notification_payload` and :func:`webhook_payload` shape the ``sunset_still_used`` inbox
  row and the ``sunset.still_used`` push-webhook event.

**The window is fixed.** Seven UTC days ending today, in the ``prod`` environment — the RDG-5.1
defaults — so the line on the timeline, the Published page and the alert always count the same
traffic. Days come from ``usage_daily``, which the usage sweep rolls up from the hourly rows.

**Counts are for everyone; names are not.** A reader without ``consumer_contracts:view`` gets the
counts with ``consumers: null`` and ``consumersVisible: false`` — the rule
:mod:`app.consumer_usage` follows — never an empty list that would read as "nobody".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .revision_deprecation import effective_sunset_string, parse_calendar_date

__all__ = [
    "ALERT_WITHIN_DAYS",
    "ENVIRONMENT",
    "EVENT_STILL_USED",
    "RENOTIFY_AFTER",
    "STATE_ANONYMOUS",
    "STATE_BOUND",
    "STATE_UNUSED",
    "SUNSET_TIMELINE_LINK",
    "WINDOW_DAYS",
    "SunsetConsumerUsage",
    "SunsetUsage",
    "UsageRow",
    "consumers_href",
    "days_until_sunset",
    "is_alert_due",
    "notification_payload",
    "still_used_summary",
    "summarize_usage",
    "usage_window",
    "webhook_payload",
]

#: How many UTC days of traffic the line counts, ending today.
WINDOW_DAYS = 7

#: The environment whose traffic counts. Mock and staging traffic never keep a version alive.
ENVIRONMENT = "prod"

#: The sweep warns when the sunset is at most this many days away (today included).
ALERT_WITHIN_DAYS = 30

#: The least time between two alerts for one revision. Enforced by ``sunset_still_used_alert``.
RENOTIFY_AFTER = timedelta(days=7)

#: The push-webhook event type.
EVENT_STILL_USED = "sunset.still_used"

#: Where the inbox row links: the screen that shows the line.
SUNSET_TIMELINE_LINK = "/ade/dashboard/versions/sunset-timeline"

#: Bound consumers call the revision.
STATE_BOUND = "bound"
#: Only traffic no binding recognised calls it.
STATE_ANONYMOUS = "anonymous"
#: No traffic in the window.
STATE_UNUSED = "unused"

UsageState = Literal["bound", "anonymous", "unused"]


@dataclass(frozen=True)
class UsageRow:
    """A revision's calls from one consumer in the window — or from nobody bound.

    Attributes:
        consumer_id: The consumer the binding belongs to; ``None`` for anonymous traffic.
        slug: Its handle (``billing-service``); ``None`` for anonymous traffic.
        name: Its display name; ``None`` for anonymous traffic.
        calls: Calls in the window.
    """

    consumer_id: Optional[str]
    slug: Optional[str]
    name: Optional[str]
    calls: int


class SunsetConsumerUsage(BaseModel):
    """One bound consumer still calling a revision.

    Attributes:
        id: The consumer id.
        slug: Its handle.
        name: Its display name.
        calls: Its calls in the window.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(description="Consumer id.")
    slug: str = Field(description="Consumer handle.")
    name: str = Field(description="Consumer display name.")
    calls: int = Field(ge=0, description="Its calls to this revision in the window.")


class SunsetUsage(BaseModel):
    """Who still calls a revision — the line the sunset timeline and the Published page draw."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    window_days: int = Field(serialization_alias="windowDays", description="UTC days counted, ending today.")
    environment: str = Field(description="The environment counted (prod).")
    state: UsageState = Field(
        description="`bound` (consumers still call it), `anonymous` (only unattributed traffic) or `unused`."
    )
    summary: str = Field(description="The line, e.g. `Still used by 2 consumers (1,240 calls, 7-day)`.")
    calls: int = Field(ge=0, description="Every call in the window, bound and anonymous.")
    bound_calls: int = Field(ge=0, serialization_alias="boundCalls", description="Calls from bound consumers.")
    anonymous_calls: int = Field(
        ge=0, serialization_alias="anonymousCalls", description="Calls no consumer binding recognised."
    )
    consumer_count: int = Field(ge=0, serialization_alias="consumerCount", description="Bound consumers calling it.")
    consumers: Optional[List[SunsetConsumerUsage]] = Field(
        default=None,
        description="The bound consumers, most calls first; null when the reader may not see consumer names.",
    )
    consumers_visible: bool = Field(
        serialization_alias="consumersVisible",
        description="Whether the reader holds `consumer_contracts:view` (and so sees `consumers`).",
    )
    consumers_href: str = Field(
        serialization_alias="consumersHref", description="The project's Consumers page in apiome-ui."
    )


def usage_window(today: date) -> Tuple[date, date]:
    """The UTC days the line counts.

    Args:
        today: The current UTC day.

    Returns:
        ``(first, last)``, inclusive: the :data:`WINDOW_DAYS` days ending ``today``.
    """
    return today - timedelta(days=WINDOW_DAYS - 1), today


def consumers_href(project_id: str) -> str:
    """The project's Consumers page in apiome-ui.

    Args:
        project_id: The project id.

    Returns:
        ``/ade/dashboard/projects/{projectId}/consumers``.
    """
    return f"/ade/dashboard/projects/{quote(str(project_id), safe='')}/consumers"


def _plural(count: int, noun: str) -> str:
    """``1 consumer`` / ``2 consumers``, with thousands separators.

    Args:
        count: The count.
        noun: The singular noun.

    Returns:
        The phrase.
    """
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def still_used_summary(consumer_count: int, bound_calls: int, anonymous_calls: int) -> str:
    """The line for a revision's window.

    Args:
        consumer_count: Bound consumers calling it.
        bound_calls: Their calls.
        anonymous_calls: Calls no binding recognised.

    Returns:
        ``Still used by 2 consumers (1,240 calls, 7-day)``, ``Anonymous traffic only — bind consumers
        to attribute it``, or ``No traffic in the last 7 days``.
    """
    if consumer_count > 0:
        return (
            f"Still used by {_plural(consumer_count, 'consumer')} "
            f"({_plural(bound_calls, 'call')}, {WINDOW_DAYS}-day)"
        )
    if anonymous_calls > 0:
        return "Anonymous traffic only — bind consumers to attribute it"
    return f"No traffic in the last {WINDOW_DAYS} days"


def summarize_usage(
    rows: Sequence[UsageRow],
    *,
    project_id: str,
    consumers_visible: bool,
) -> SunsetUsage:
    """Fold a revision's window rows into its :class:`SunsetUsage`.

    Rows for the same consumer (two bindings of one consumer) are added together, and rows with no
    calls are ignored.

    Args:
        rows: The revision's rows from the store.
        project_id: The revision's project, for the Consumers link.
        consumers_visible: Whether the reader may see consumer names.

    Returns:
        The usage block.
    """
    anonymous = 0
    by_consumer: Dict[str, SunsetConsumerUsage] = {}
    for row in rows:
        calls = max(0, int(row.calls or 0))
        if calls == 0:
            continue
        if not row.consumer_id:
            anonymous += calls
            continue
        known = by_consumer.get(row.consumer_id)
        if known is None:
            by_consumer[row.consumer_id] = SunsetConsumerUsage(
                id=row.consumer_id,
                slug=row.slug or row.consumer_id,
                name=row.name or row.slug or row.consumer_id,
                calls=calls,
            )
        else:
            by_consumer[row.consumer_id] = known.model_copy(update={"calls": known.calls + calls})
    consumers = sorted(by_consumer.values(), key=lambda consumer: (-consumer.calls, consumer.slug))
    bound = sum(consumer.calls for consumer in consumers)
    state: UsageState = STATE_BOUND if consumers else (STATE_ANONYMOUS if anonymous else STATE_UNUSED)
    return SunsetUsage(
        window_days=WINDOW_DAYS,
        environment=ENVIRONMENT,
        state=state,
        summary=still_used_summary(len(consumers), bound, anonymous),
        calls=bound + anonymous,
        bound_calls=bound,
        anonymous_calls=anonymous,
        consumer_count=len(consumers),
        consumers=consumers if consumers_visible else None,
        consumers_visible=consumers_visible,
        consumers_href=consumers_href(project_id),
    )


def days_until_sunset(metadata: Any, today: date) -> Optional[int]:
    """How many days remain before a revision's sunset.

    Args:
        metadata: The revision's metadata (``sunsetAt`` or the legacy keys).
        today: The current UTC day.

    Returns:
        The days left (``0`` on the day itself, negative once it passed), or ``None`` without a
        parseable sunset.
    """
    raw = effective_sunset_string(metadata)
    sunset = parse_calendar_date(raw) if raw else None
    if sunset is None:
        return None
    return (sunset - today).days


def is_alert_due(metadata: Any, usage: SunsetUsage, today: date) -> bool:
    """Whether the sweep should warn about a revision this week.

    The weekly limit is not decided here — the store's claim enforces it.

    Args:
        metadata: The revision's metadata.
        usage: Its window usage.
        today: The current UTC day.

    Returns:
        True when the sunset is 0 to :data:`ALERT_WITHIN_DAYS` days away and bound consumers still call it.
    """
    days = days_until_sunset(metadata, today)
    if days is None or days < 0 or days > ALERT_WITHIN_DAYS:
        return False
    return usage.state == STATE_BOUND


def _days_phrase(days: int) -> str:
    """``today`` / ``tomorrow`` / ``in 20 days``."""
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def notification_payload(
    *,
    project: Dict[str, Any],
    version_label: str,
    sunset_at: Optional[str],
    days_left: int,
    usage: SunsetUsage,
) -> Dict[str, Any]:
    """The ``sunset_still_used`` inbox row's payload.

    It names no consumer: a collaborator may not hold ``consumer_contracts:view``, and the link
    leads to the timeline, which shows the names to whoever may read them.

    Args:
        project: The project row (``slug``, ``name``).
        version_label: The revision's version label.
        sunset_at: The stored sunset instant.
        days_left: Days until the sunset.
        usage: The window usage.

    Returns:
        The payload, with its own ``summary`` and ``link``.
    """
    payload: Dict[str, Any] = {
        "version_label": version_label,
        "summary": (
            f"{version_label} sunsets {_days_phrase(days_left)} and is "
            f"{usage.summary[0].lower()}{usage.summary[1:]}"
        ),
        "link": SUNSET_TIMELINE_LINK,
        "sunset_at": sunset_at,
        "days_until_sunset": days_left,
        "consumer_count": usage.consumer_count,
        "calls": usage.bound_calls,
        "window_days": usage.window_days,
    }
    for key in ("slug", "name"):
        if project.get(key):
            payload[f"project_{key}"] = str(project[key])
    return payload


def webhook_payload(
    *,
    tenant_id: str,
    project: Dict[str, Any],
    version_record_id: str,
    version_label: str,
    sunset_at: Optional[str],
    days_left: int,
    usage: SunsetUsage,
) -> Dict[str, Any]:
    """The ``sunset.still_used`` push-webhook body.

    Subscriptions are the tenant's own integrations, so the event carries the consumer handles —
    the people who must move before the sunset.

    Args:
        tenant_id: The tenant.
        project: The project row (``id``, ``slug``, ``name``).
        version_record_id: The revision.
        version_label: Its version label.
        sunset_at: The stored sunset instant.
        days_left: Days until the sunset.
        usage: The window usage, computed with names visible.

    Returns:
        The event body.
    """
    return {
        "event": EVENT_STILL_USED,
        "tenantId": tenant_id,
        "projectId": str(project.get("id") or ""),
        "projectSlug": project.get("slug"),
        "projectName": project.get("name"),
        "revisionId": version_record_id,
        "versionLabel": version_label,
        "sunsetAt": sunset_at,
        "daysUntilSunset": days_left,
        "windowDays": usage.window_days,
        "environment": usage.environment,
        "calls": usage.bound_calls,
        "anonymousCalls": usage.anonymous_calls,
        "consumerCount": usage.consumer_count,
        "consumers": [
            {"id": consumer.id, "slug": consumer.slug, "name": consumer.name, "calls": consumer.calls}
            for consumer in (usage.consumers or [])
        ],
        "summary": usage.summary,
    }
