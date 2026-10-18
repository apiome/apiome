"""Owner routing of findings — CDG-2.3 (#5962).

A finding about an entity — a new error-level lint finding, a breaking change on refresh, verification
drift, a failing deploy gate, MCP trust drift, a shadow API, a failed connector sync — is routed to the
entity's **confirmed** owner team (CDG-2.2):

* one inbox row per team member (``owner_*`` types, apiome-db V286), minus the actor and anyone the
  producer already notified (a requester, say);
* one post to the team's ``chat_url`` — a Slack-shaped message for a Slack incoming webhook, the
  structured payload otherwise — queued on the webhook worker as a direct-URL delivery, so it gets the
  same retries, dead-letter handling and ``Retry-After`` respect as every other webhook;
* at most once per (team, entity, finding type) per :data:`THROTTLE_WINDOW_SECONDS`: a gate read in a
  loop, or a schedule that keeps drifting, does not flood a team.

The inbox rows, the chat delivery and the throttle claim are written in **one transaction**, so a
routed finding always has both and a rolled-back one has neither (the COL-3.1 rule).

**Nothing is dropped.** With no confirmed owner — no owner, or only *suggested* ones, which never
receive anything — the finding is recorded in the **Unowned findings** report (``unowned_findings``):
one row per entity and finding type, counting occurrences. CDG-2.5 adds the catch-all team.

Routing is advisory to the producer: :func:`route_owner_finding_safely` never raises, so a lint gate,
a sync or a sweep cannot fail because a notification could not be written.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .entity_owners import KINDS
from .notification_fanout import NotificationDraft, recipients
from .notifications import (
    OWNER_NOTIFICATION_TYPES,
    TYPE_OWNER_BREAKING_CHANGE,
    TYPE_OWNER_FINDING,
    TYPE_OWNER_GATE_BLOCKED,
    TYPE_OWNER_SHADOW_API,
    TYPE_OWNER_SYNC_FAILED,
    TYPE_OWNER_TRUST_DRIFT,
    TYPE_OWNER_VERIFICATION_DRIFT,
)
from .repository_event_notifications import ChannelKind, build_slack_message, channel_kind_for_url
from .revision_deprecation import is_uuid_string

__all__ = [
    "FINDING_TYPES",
    "OUTCOME_CATCH_ALL",
    "OUTCOME_ROUTED",
    "OUTCOME_SKIPPED",
    "OUTCOME_THROTTLED",
    "OUTCOME_UNOWNED",
    "THROTTLE_WINDOW_SECONDS",
    "entity_link",
    "TYPE_OWNER_BREAKING_CHANGE",
    "TYPE_OWNER_FINDING",
    "TYPE_OWNER_GATE_BLOCKED",
    "TYPE_OWNER_SHADOW_API",
    "TYPE_OWNER_SYNC_FAILED",
    "TYPE_OWNER_TRUST_DRIFT",
    "TYPE_OWNER_VERIFICATION_DRIFT",
    "OwnerFinding",
    "OwnerRecipients",
    "OwnerTeam",
    "RoutingOutcome",
    "catch_all_recipients",
    "entity_kind_of",
    "list_unowned_findings",
    "project_id_for_version_ref",
    "owner_recipients",
    "route_owner_finding",
    "route_mcp_endpoint_problem",
    "route_owner_finding_safely",
]

_logger = logging.getLogger(__name__)

#: The seven finding types, in the order the notification centre lists them.
FINDING_TYPES = OWNER_NOTIFICATION_TYPES

#: One routed event per (team, entity, finding type) per hour — the repository throttle's window.
THROTTLE_WINDOW_SECONDS = 3600

OUTCOME_ROUTED = "routed"
OUTCOME_THROTTLED = "throttled"
OUTCOME_UNOWNED = "unowned"
OUTCOME_SKIPPED = "skipped"
#: No owner; recorded as unowned and delivered to the tenant's catch-all team (CDG-2.5).
OUTCOME_CATCH_ALL = "catch_all"

#: Kinds stored on a ``projects`` row; a caller may name either and the row decides.
_PROJECT_KINDS = ("project", "catalog_item")


@dataclass(frozen=True)
class OwnerTeam:
    """The confirmed owner team of an entity."""

    id: str
    slug: str
    name: str
    chat_url: Optional[str] = None


@dataclass(frozen=True)
class OwnerRecipients:
    """Who a routed finding reaches.

    Attributes:
        team: The confirmed owner team.
        user_ids: The team's members, minus the excluded ids, de-duplicated.
    """

    team: OwnerTeam
    user_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class OwnerFinding:
    """One finding to route.

    Attributes:
        tenant_id: The entity's tenant.
        entity_kind: ``project``, ``catalog_item``, ``mcp_endpoint``, ``consumer`` or ``connector``
            (for a projects row either of the first two; the row's ``publishable`` decides).
        entity_id: The entity.
        finding_type: One of :data:`FINDING_TYPES`.
        summary: One sentence for the inbox and the chat message.
        link: Relative deep link into the app (``/ade/…``), or ``None``.
        finding_id: The producer's id for the finding (an evaluation, report, run…), or ``None``.
        entity_name: The entity's display name, when the producer has it.
        details: Extra payload keys (counts, severities); JSON-serializable.
        actor_id: Whoever caused it; never notified about their own action.
        already_notified: Users the producer already notified (a requester), not notified twice.
        version_id: The revision the finding is about, for the inbox row's version column.
    """

    tenant_id: str
    entity_kind: str
    entity_id: str
    finding_type: str
    summary: str
    link: Optional[str] = None
    finding_id: Optional[str] = None
    entity_name: Optional[str] = None
    details: Mapping[str, Any] = field(default_factory=dict)
    actor_id: Optional[str] = None
    already_notified: Sequence[str] = ()
    version_id: Optional[str] = None


@dataclass(frozen=True)
class RoutingOutcome:
    """What routing did.

    Attributes:
        status: ``routed``, ``throttled``, ``unowned`` or ``skipped`` (malformed input).
        team_slug: The owner team, when there is one.
        inbox_rows: Inbox rows written.
        chat_delivery_id: The queued chat delivery, when the team has a ``chat_url``.
    """

    status: str
    team_slug: Optional[str] = None
    inbox_rows: int = 0
    chat_delivery_id: Optional[str] = None


def project_id_for_version_ref(db: Any, tenant_id: str, version_ref: Optional[str]) -> Optional[str]:
    """The projects row a verification ``version_ref`` names (``project/{slug}/{v}``, ``catalog/{item}/{v}``).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        version_ref: The reference; the middle segment is a slug or an id.

    Returns:
        The project / catalog item id, or ``None`` when the reference does not resolve.
    """
    parts = str(version_ref or "").strip().split("/")
    if len(parts) < 2 or parts[0] not in ("project", "catalog") or not is_uuid_string(tenant_id or ""):
        return None
    rows = db.execute_query(
        """
        SELECT id::text AS id FROM apiome.projects
        WHERE tenant_id = %s::uuid AND deleted_at IS NULL AND (slug = %s OR id::text = %s)
        ORDER BY (slug = %s) DESC
        LIMIT 1
        """,
        (tenant_id, parts[1], parts[1].lower(), parts[1]),
    )
    return str(rows[0]["id"]) if rows else None


def entity_link(kind: str, entity_id: str, *, tab: Optional[str] = None) -> Optional[str]:
    """The app page an entity lives on, as a relative deep link.

    Args:
        kind: The stored entity kind.
        entity_id: The entity.
        tab: A tab to open (``lint``, ``runs``…), where the page has tabs.

    Returns:
        ``/ade/…``, or ``None`` for a kind with no page of its own (a consumer).
    """
    from urllib.parse import quote, urlencode

    ident = quote(str(entity_id), safe="")
    if kind == "project":
        query = {"projectId": str(entity_id), **({"tab": tab} if tab else {})}
        return f"/ade/dashboard/versions?{urlencode(query)}"
    pages = {
        "catalog_item": f"/ade/dashboard/catalog/{ident}",
        "mcp_endpoint": f"/ade/dashboard/mcp/{ident}",
        "connector": f"/ade/dashboard/connectors/{ident}",
    }
    page = pages.get(kind)
    if page is None:
        return None
    return f"{page}?{urlencode({'tab': tab})}" if tab else page


def entity_kind_of(db: Any, tenant_id: str, entity_kind: str, entity_id: str) -> Optional[str]:
    """Public spelling of :func:`_resolve_kind`, for producers that build a link before routing."""
    return _resolve_kind(db, tenant_id, entity_kind, entity_id)


def _resolve_kind(db: Any, tenant_id: str, entity_kind: str, entity_id: str) -> Optional[str]:
    """The stored kind of an entity: a projects row is a project or a catalog item by ``publishable``.

    Returns:
        The kind, or ``None`` for an unknown kind or a projects row that does not exist.
    """
    if entity_kind not in KINDS:
        return None
    if entity_kind not in _PROJECT_KINDS:
        return entity_kind
    rows = db.execute_query(
        "SELECT publishable FROM apiome.projects WHERE id = %s::uuid AND tenant_id = %s::uuid",
        (entity_id, tenant_id),
    )
    if not rows:
        return None
    return "project" if rows[0]["publishable"] else "catalog_item"


def owner_recipients(
    db: Any,
    tenant_id: str,
    entity_kind: str,
    entity_id: str,
    *,
    exclude: Iterable[Optional[str]] = (),
) -> Optional[OwnerRecipients]:
    """Resolve an entity's confirmed owner team and who on it should be told.

    Suggested owners never count. A soft-deleted team owns nothing.

    Args:
        db: Database handle.
        tenant_id: The entity's tenant.
        entity_kind: The entity kind (a projects row may be named ``project`` or ``catalog_item``).
        entity_id: The entity.
        exclude: Ids not to notify — the actor, users the producer already notified.

    Returns:
        The team and its member ids (possibly empty when every member is excluded), or ``None``
        when the entity has no confirmed owner.
    """
    if not is_uuid_string(tenant_id or "") or not is_uuid_string(entity_id or ""):
        return None
    kinds = _PROJECT_KINDS if entity_kind in _PROJECT_KINDS else (entity_kind,)
    rows = db.execute_query(
        """
        SELECT t.id::text AS team_id, t.slug, t.name, t.chat_url,
               COALESCE(array_agg(m.user_id::text ORDER BY (m.role = 'lead') DESC, m.created_at)
                        FILTER (WHERE m.user_id IS NOT NULL), ARRAY[]::text[]) AS members
        FROM apiome.entity_owners eo
        JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
        LEFT JOIN apiome.team_members m ON m.team_id = t.id
        WHERE eo.tenant_id = %s::uuid AND eo.entity_id = %s::uuid
          AND eo.entity_kind = ANY(%s::text[]) AND eo.status = 'confirmed'
        GROUP BY t.id, t.slug, t.name, t.chat_url
        LIMIT 1
        """,
        (tenant_id, entity_id, list(kinds)),
    )
    if not rows:
        return None
    row = rows[0]
    team = OwnerTeam(
        id=str(row["team_id"]), slug=row["slug"], name=row["name"], chat_url=row.get("chat_url")
    )
    return OwnerRecipients(team=team, user_ids=recipients(row.get("members") or [], exclude=exclude))


def _payload(finding: OwnerFinding, kind: str, team: Optional[OwnerTeam]) -> Dict[str, Any]:
    """The inbox payload / unowned-report payload for a finding."""
    payload: Dict[str, Any] = {
        "entity_kind": kind,
        "entity_id": finding.entity_id,
        "summary": finding.summary,
    }
    if finding.entity_name:
        payload["entity_name"] = finding.entity_name
    if finding.link:
        payload["link"] = finding.link
    if finding.finding_id:
        payload["finding_id"] = finding.finding_id
    if team is not None:
        payload["team"] = {"id": team.id, "slug": team.slug, "name": team.name}
    for key, value in (finding.details or {}).items():
        payload.setdefault(str(key), value)
    return payload


def _chat_body(finding: OwnerFinding, team: OwnerTeam, payload: Mapping[str, Any]) -> Dict[str, Any]:
    """The chat-channel body: a Slack message for a Slack webhook, the structured event otherwise."""
    event = {
        "event": f"owner.{finding.finding_type.removeprefix('owner_')}",
        "summary": f"[{team.name}] {finding.summary}",
        "team": team.slug,
        **{k: v for k, v in payload.items() if k not in {"summary", "team"}},
    }
    if finding.link:
        event["reviewHref"] = finding.link
    if channel_kind_for_url(team.chat_url) is ChannelKind.SLACK:
        return build_slack_message(event)
    return event


def catch_all_recipients(
    db: Any, tenant_id: str, *, exclude: Iterable[Optional[str]] = ()
) -> Optional[OwnerRecipients]:
    """The tenant's catch-all team (CDG-2.5, ``tenants.unowned_findings_team_id``), if one is set.

    A soft-deleted catch-all team receives nothing (the drift report shows it instead).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        exclude: Ids not to notify.

    Returns:
        The team and its members, or ``None`` when no live catch-all team is set.
    """
    if not is_uuid_string(tenant_id or ""):
        return None
    rows = db.execute_query(
        """
        SELECT t.id::text AS team_id, t.slug, t.name, t.chat_url,
               COALESCE(array_agg(m.user_id::text ORDER BY (m.role = 'lead') DESC, m.created_at)
                        FILTER (WHERE m.user_id IS NOT NULL), ARRAY[]::text[]) AS members
        FROM apiome.tenants tn
        JOIN apiome.teams t ON t.id = tn.unowned_findings_team_id AND t.deleted_at IS NULL
        LEFT JOIN apiome.team_members m ON m.team_id = t.id
        WHERE tn.id = %s::uuid
        GROUP BY t.id, t.slug, t.name, t.chat_url
        """,
        (tenant_id,),
    )
    if not rows:
        return None
    row = rows[0]
    team = OwnerTeam(
        id=str(row["team_id"]), slug=row["slug"], name=row["name"], chat_url=row.get("chat_url")
    )
    return OwnerRecipients(team=team, user_ids=recipients(row.get("members") or [], exclude=exclude))


def _delivery_plan(
    finding: OwnerFinding, kind: str, owner: OwnerRecipients, *, catch_all: bool
) -> tuple[list[NotificationDraft], Optional[Dict[str, Any]]]:
    """The inbox drafts and the chat body for delivering a finding to one team.

    Args:
        finding: The finding.
        kind: The stored entity kind.
        owner: The team and the members to notify.
        catch_all: True when the team is the tenant's catch-all team, not the entity's owner; the
            payload says so (``catch_all: true``) so the reader knows why it reached them.

    Returns:
        ``(drafts, chat_body)``; the body is ``None`` when the team has no ``chat_url``.
    """
    team = owner.team
    payload = _payload(finding, kind, team)
    if catch_all:
        payload["catch_all"] = True
    drafts = [
        NotificationDraft(
            user_id=user_id,
            type=finding.finding_type,
            payload=payload,
            actor_id=finding.actor_id if is_uuid_string(finding.actor_id or "") else None,
            project_id=finding.entity_id if kind in _PROJECT_KINDS else None,
            version_id=finding.version_id if is_uuid_string(finding.version_id or "") else None,
        )
        for user_id in owner.user_ids
    ]
    return drafts, (_chat_body(finding, team, payload) if team.chat_url else None)


def _deliver(
    db: Any,
    cursor: Any,
    finding: OwnerFinding,
    kind: str,
    team: OwnerTeam,
    drafts: list[NotificationDraft],
    chat_body: Optional[Dict[str, Any]],
) -> Optional[tuple[int, Optional[str]]]:
    """Claim the throttle slot, then write the inbox rows and queue the chat post, on ``cursor``.

    Returns:
        ``(inbox rows written, chat delivery id)``, or ``None`` when the throttle held.
    """
    cursor.execute(
        """
        INSERT INTO apiome.owner_notification_throttle
            (tenant_id, team_id, entity_kind, entity_id, finding_type)
        VALUES (%s::uuid, %s::uuid, %s, %s::uuid, %s)
        ON CONFLICT (team_id, entity_kind, entity_id, finding_type) DO UPDATE
           SET last_notified_at = CASE
                   WHEN apiome.owner_notification_throttle.last_notified_at
                        <= CURRENT_TIMESTAMP - make_interval(secs => %s)
                   THEN CURRENT_TIMESTAMP
                   ELSE apiome.owner_notification_throttle.last_notified_at END,
               suppressed_count = CASE
                   WHEN apiome.owner_notification_throttle.last_notified_at
                        <= CURRENT_TIMESTAMP - make_interval(secs => %s)
                   THEN 0
                   ELSE apiome.owner_notification_throttle.suppressed_count + 1 END
        RETURNING (last_notified_at = CURRENT_TIMESTAMP) AS claimed
        """,
        (finding.tenant_id, team.id, kind, finding.entity_id, finding.finding_type,
         THROTTLE_WINDOW_SECONDS, THROTTLE_WINDOW_SECONDS),
    )
    claimed = cursor.fetchone()
    if not claimed or not claimed["claimed"]:
        return None
    written = db._insert_notifications(cursor, tenant_id=finding.tenant_id, notify=lambda _produced: drafts)
    delivery_id = None
    if chat_body is not None:
        delivery_id = db._insert_direct_delivery(
            cursor,
            tenant_id=finding.tenant_id,
            team_id=team.id,
            target_url=str(team.chat_url),
            event_type=f"owner.{finding.finding_type.removeprefix('owner_')}",
            payload=chat_body,
        )
    return written, delivery_id


def _record_unowned(
    db: Any, finding: OwnerFinding, kind: str, catch_all: Optional[OwnerRecipients] = None
) -> RoutingOutcome:
    """Add (or count again) the finding in the Unowned findings report, and tell the catch-all team.

    The report row is written either way — the entity still has no owner — and, when the tenant
    has a live catch-all team (CDG-2.5), the same transaction delivers the finding to it, under the
    same throttle as an owner team.
    """
    plan = _delivery_plan(finding, kind, catch_all, catch_all=True) if catch_all else None

    def work(cursor: Any) -> RoutingOutcome:
        from psycopg2.extras import Json

        cursor.execute(
            """
            INSERT INTO apiome.unowned_findings
                (tenant_id, entity_kind, entity_id, finding_type, payload)
            VALUES (%s::uuid, %s, %s::uuid, %s, %s::jsonb)
            ON CONFLICT (tenant_id, entity_kind, entity_id, finding_type) DO UPDATE
               SET payload = EXCLUDED.payload,
                   occurrences = apiome.unowned_findings.occurrences + 1,
                   last_seen_at = CURRENT_TIMESTAMP
            """,
            (finding.tenant_id, kind, finding.entity_id, finding.finding_type,
             Json(_payload(finding, kind, None))),
        )
        if catch_all is None or plan is None:
            return RoutingOutcome(status=OUTCOME_UNOWNED)
        delivered = _deliver(db, cursor, finding, kind, catch_all.team, *plan)
        if delivered is None:
            return RoutingOutcome(status=OUTCOME_UNOWNED, team_slug=catch_all.team.slug)
        return RoutingOutcome(
            status=OUTCOME_CATCH_ALL,
            team_slug=catch_all.team.slug,
            inbox_rows=delivered[0],
            chat_delivery_id=delivered[1],
        )

    return db._guarded_tx(work)


def route_owner_finding(db: Any, finding: OwnerFinding) -> RoutingOutcome:
    """Route one finding to its entity's confirmed owner team, or to the Unowned report.

    With no confirmed owner the finding is recorded in the Unowned report and, when the tenant has
    a catch-all team (CDG-2.5), delivered to that team too (``catch_all`` outcome).

    Args:
        db: Database handle.
        finding: The finding.

    Returns:
        What happened. ``skipped`` for malformed input (a non-UUID id, an unknown kind or type, an
        entity that no longer exists).
    """
    if finding.finding_type not in FINDING_TYPES:
        return RoutingOutcome(status=OUTCOME_SKIPPED)
    if not is_uuid_string(finding.tenant_id or "") or not is_uuid_string(finding.entity_id or ""):
        return RoutingOutcome(status=OUTCOME_SKIPPED)
    kind = _resolve_kind(db, finding.tenant_id, finding.entity_kind, finding.entity_id)
    if kind is None:
        return RoutingOutcome(status=OUTCOME_SKIPPED)

    # Resolve everything before the transaction opens (notification_store's rule).
    exclude = [finding.actor_id, *finding.already_notified]
    owner = owner_recipients(db, finding.tenant_id, kind, finding.entity_id, exclude=exclude)
    if owner is None:
        return _record_unowned(
            db, finding, kind, catch_all_recipients(db, finding.tenant_id, exclude=exclude)
        )

    team = owner.team
    drafts, chat_body = _delivery_plan(finding, kind, owner, catch_all=False)

    def work(cursor: Any) -> RoutingOutcome:
        delivered = _deliver(db, cursor, finding, kind, team, drafts, chat_body)
        if delivered is None:
            return RoutingOutcome(status=OUTCOME_THROTTLED, team_slug=team.slug)
        # The entity has an owner now; it no longer belongs in the Unowned report for this type.
        cursor.execute(
            """
            DELETE FROM apiome.unowned_findings
            WHERE tenant_id = %s::uuid AND entity_kind = %s AND entity_id = %s::uuid
              AND finding_type = %s
            """,
            (finding.tenant_id, kind, finding.entity_id, finding.finding_type),
        )
        return RoutingOutcome(
            status=OUTCOME_ROUTED, team_slug=team.slug, inbox_rows=delivered[0],
            chat_delivery_id=delivered[1],
        )

    return db._guarded_tx(work)


def route_owner_finding_safely(db: Any, finding: OwnerFinding) -> RoutingOutcome:
    """:func:`route_owner_finding`, but a failure is logged and reported as ``skipped``.

    Producers call this: their own work (a gate verdict, a sync, a sweep tick) has already
    happened, and routing must not undo or fail it.
    """
    try:
        return route_owner_finding(db, finding)
    except Exception as exc:  # noqa: BLE001 - routing is advisory to the producer
        _logger.warning(
            "owner routing failed type=%s entity=%s:%s error=%s",
            finding.finding_type,
            finding.entity_kind,
            finding.entity_id,
            f"{type(exc).__name__}: {exc}"[:300],
        )
        return RoutingOutcome(status=OUTCOME_SKIPPED)


def route_mcp_endpoint_problem(
    db: Any,
    *,
    tenant_id: str,
    endpoint: Mapping[str, Any],
    summary: str,
    details: Optional[Mapping[str, Any]] = None,
    finding_id: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> RoutingOutcome:
    """Route an MCP endpoint problem (trust drift, a failing probe) to its owner team.

    Trust drift calls this today; it is also the entry point an MCP probe-failure producer calls,
    so both reach the team as ``owner_trust_drift`` with the endpoint's page as the link. Never
    raises.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        endpoint: The ``mcp_endpoints`` row (``id``, ``name``, ``slug``).
        summary: One sentence for the inbox and the chat message.
        details: Extra payload keys.
        finding_id: The report, run or probe id.
        actor_id: Whoever triggered it.

    Returns:
        What routing did.
    """
    endpoint_id = str(endpoint.get("id") or "")
    return route_owner_finding_safely(
        db,
        OwnerFinding(
            tenant_id=tenant_id,
            entity_kind="mcp_endpoint",
            entity_id=endpoint_id,
            finding_type=TYPE_OWNER_TRUST_DRIFT,
            summary=summary,
            link=entity_link("mcp_endpoint", endpoint_id),
            finding_id=finding_id,
            entity_name=endpoint.get("name") or endpoint.get("slug"),
            details=dict(details or {}),
            actor_id=actor_id,
        ),
    )


def list_unowned_findings(
    db: Any, tenant_id: str, *, finding_type: Optional[str] = None, limit: int = 50, offset: int = 0
) -> Dict[str, Any]:
    """The Unowned findings report: newest first, paged.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        finding_type: Only this type, when given.
        limit: Page size (1..200).
        offset: Rows to skip.

    Returns:
        ``{"items": [...], "total": n}``; each item has ``id``, ``entity_kind``, ``entity_id``,
        ``finding_type``, ``payload``, ``occurrences``, ``first_seen_at`` and ``last_seen_at``.
    """
    if not is_uuid_string(tenant_id or ""):
        return {"items": [], "total": 0}
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    type_clause = "AND finding_type = %s" if finding_type else ""
    params: List[Any] = [tenant_id] + ([finding_type] if finding_type else [])
    rows = db.execute_query(
        f"""
        SELECT id::text AS id, entity_kind, entity_id::text AS entity_id, finding_type, payload,
               occurrences, first_seen_at, last_seen_at, count(*) OVER () AS total
        FROM apiome.unowned_findings
        WHERE tenant_id = %s::uuid {type_clause}
        ORDER BY last_seen_at DESC, id
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    total = int(rows[0]["total"]) if rows else 0
    if not rows and offset:
        counted = db.execute_query(
            f"SELECT count(*)::int AS n FROM apiome.unowned_findings WHERE tenant_id = %s::uuid {type_clause}",
            tuple(params),
        )
        total = int(counted[0]["n"]) if counted else 0
    items = []
    for row in rows:
        item = dict(row)
        item.pop("total", None)
        for key in ("first_seen_at", "last_seen_at"):
            value = item.get(key)
            item[key] = value.isoformat() if hasattr(value, "isoformat") else value
        items.append(item)
    return {"items": items, "total": total}
