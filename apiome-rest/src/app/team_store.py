"""Persistence for teams and their membership — CDG-2.1 (#5960).

:mod:`app.teams` says what a team *is*; this module is the only place one is read or written, so
the rules below are applied once rather than at each route.

**Every write is audited in its own transaction.** ``team.create``, ``team.update``,
``team.delete`` and ``team.members.replace`` are appended to the tenant's hash-chained
``access_audit`` ledger on the cursor that makes the change (:meth:`Database._append_access_audit`),
so a team never changes without the row that says who changed it.

**Members must be tenant members.** A membership write names every user it was given that has no
``tenant_users`` row in the tenant, and refuses before writing anything. V284's trigger refuses the
same rows, so a writer that bypasses this module cannot store one either. The reverse direction —
a user who *leaves* the tenant leaves every team in the same transaction — is V284's other trigger.

**A delete is soft, and refuses while the team owns entities.** Ownership is CDG-2.2's
``entity_owners`` table (apiome-db V285); on a database without it :func:`_owned_entity_count`
reads zero. A team with confirmed ownership rows can only be deleted with
``reassign_to``, which moves those rows to the named team in the delete's own transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

import psycopg2

from .consumer_contract_store import ConsumerActor
from .database import db
from .revision_deprecation import is_uuid_string
from .teams import (
    CODE_MEMBER_NOT_IN_TENANT,
    CODE_NOT_FOUND,
    CODE_OWNS_ENTITIES,
    CODE_REASSIGN_INVALID,
    CODE_SLUG_TAKEN,
    TeamInput,
    TeamMember,
    TeamMemberInput,
    TeamPatch,
    TeamRecord,
    TeamValidationError,
    normalize_contact_email,
    normalize_link,
    normalize_name,
    resolve_slug,
    validate_members,
)

__all__ = [
    "ACTIVITY_DAYS",
    "create_team",
    "delete_team",
    "get_team",
    "list_teams",
    "replace_team_members",
    "team_activity",
    "update_team",
]

#: How far back a team page's routed-event history reaches (CDG-2.4).
ACTIVITY_DAYS = 30

#: Most owned entities and events one activity read returns.
_ACTIVITY_LIMIT = 200

#: The display name of each kind of owned entity, read in the same statement as the owner rows.
_OWNED_ENTITY_NAME_SQL = """
    COALESCE(
        CASE eo.entity_kind
            WHEN 'project' THEN (SELECT p.name FROM apiome.projects p WHERE p.id = eo.entity_id)
            WHEN 'catalog_item' THEN (SELECT p.name FROM apiome.projects p WHERE p.id = eo.entity_id)
            WHEN 'mcp_endpoint' THEN (SELECT m.name FROM apiome.mcp_endpoints m WHERE m.id = eo.entity_id)
            WHEN 'consumer' THEN (SELECT c.name FROM apiome.consumer c WHERE c.id = eo.entity_id)
            WHEN 'connector' THEN (SELECT k.name FROM apiome.catalog_connectors k WHERE k.id = eo.entity_id)
            WHEN 'agent' THEN (SELECT a.name FROM apiome.catalog_agents a WHERE a.id = eo.entity_id)
            WHEN 'model' THEN (SELECT m.name FROM apiome.catalog_models m WHERE m.id = eo.entity_id)
        END,
        eo.entity_id::text
    )
"""

#: The team columns every read selects, with the live member count beside them.
_TEAM_COLUMNS = """
    t.id::text AS id, t.slug, t.name, t.description, t.contact_email,
    t.chat_url, t.oncall_url, t.docs_url, t.created_by::text AS created_by,
    t.created_at, t.updated_at,
    (SELECT count(*) FROM apiome.team_members m WHERE m.team_id = t.id)::int AS member_count
"""

#: The fields a create or update may set, in the order audits list them.
_EDITABLE_FIELDS = ("name", "description", "contact_email", "chat_url", "oncall_url", "docs_url")


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp as ISO-8601, passing ``None`` and strings through.

    Args:
        value: A ``datetime``, a string, or ``None``.

    Returns:
        The ISO string, or ``None``.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _record(row: Dict[str, Any], members: Optional[List[TeamMember]] = None) -> TeamRecord:
    """Build a :class:`TeamRecord` from a ``teams`` row.

    Args:
        row: A row selected with ``_TEAM_COLUMNS``.
        members: The members, for a read that includes them.

    Returns:
        The record.
    """
    return TeamRecord(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        contact_email=row.get("contact_email"),
        chat_url=row.get("chat_url"),
        oncall_url=row.get("oncall_url"),
        docs_url=row.get("docs_url"),
        member_count=int(row.get("member_count") or 0),
        created_by=row.get("created_by"),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        members=members,
    )


def _audit(
    cursor: Any, tenant_id: str, actor: ConsumerActor, action: str, slug: str, detail: Dict[str, Any]
) -> None:
    """Append a ``team.*`` row to the tenant's access audit inside the open transaction.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The tenant whose chain the row extends.
        actor: Who acted.
        action: ``team.create``, ``team.update``, ``team.delete`` or ``team.members.replace``.
        slug: The team's slug (the audit *target*).
        detail: Structured context.
    """
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=action,
        actor_id=actor.user_id,
        actor_label=actor.label,
        target=f"team:{slug}",
        source="api_key" if actor.kind == "api_key" else "web",
        detail=detail,
    )


def _run(work: Callable[[Any], Any]) -> Any:
    """Run ``work`` in one transaction, translating a slug collision into a refusal.

    Args:
        work: A callable taking the cursor; whatever it returns is committed.

    Returns:
        Whatever ``work`` returned.

    Raises:
        TeamValidationError: ``team-slug-taken`` when V284's partial unique index refused a
            write, plus whatever ``work`` raised (everything it wrote is rolled back).
    """
    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise TeamValidationError(
            CODE_SLUG_TAKEN, "another team in this tenant already has that slug"
        ) from exc


def _lock_team(cursor: Any, tenant_id: str, slug: str) -> Dict[str, Any]:
    """Select and lock a live team by slug inside the open transaction.

    Args:
        cursor: The transaction's cursor.
        tenant_id: The caller's tenant.
        slug: The team's slug.

    Returns:
        The team row.

    Raises:
        TeamValidationError: ``team-not-found`` when no live team has that slug.
    """
    cursor.execute(
        f"""
        SELECT {_TEAM_COLUMNS}
        FROM apiome.teams t
        WHERE t.tenant_id = %s::uuid AND t.slug = %s AND t.deleted_at IS NULL
        FOR UPDATE OF t
        """,
        (tenant_id, (slug or "").strip().lower()),
    )
    row = cursor.fetchone()
    if not row:
        raise TeamValidationError(CODE_NOT_FOUND, f"no team '{slug}' in this tenant")
    return dict(row)


def _members(rows: Iterable[Dict[str, Any]]) -> List[TeamMember]:
    """Build member records from member rows.

    Args:
        rows: Rows with ``user_id``, ``role``, ``email``, ``name`` and ``added_at``.

    Returns:
        The members.
    """
    return [
        TeamMember(
            user_id=str(row["user_id"]),
            role=row["role"],
            email=row.get("email"),
            name=row.get("name"),
            added_at=_iso(row.get("added_at")),
        )
        for row in rows
    ]


_MEMBERS_SQL = """
    SELECT m.user_id::text AS user_id, m.role, u.email, u.name, m.created_at AS added_at
    FROM apiome.team_members m
    JOIN apiome.users u ON u.id = m.user_id
    WHERE m.team_id = %s::uuid
    ORDER BY (m.role = 'lead') DESC, lower(COALESCE(u.name, u.email, '')), m.user_id
"""


def _owned_entity_count(cursor: Any, team_id: str) -> int:
    """How many entities the team is the confirmed owner of.

    CDG-2.2 adds ``apiome.entity_owners`` (V285); before that migration has run the table is absent
    and the team owns nothing. Reading through ``to_regclass`` keeps this module correct on both sides
    of that migration without a code change.

    Args:
        cursor: The transaction's cursor.
        team_id: The team.

    Returns:
        The confirmed-ownership row count.
    """
    cursor.execute("SELECT to_regclass('apiome.entity_owners') IS NOT NULL AS present")
    row = cursor.fetchone()
    if not row or not row["present"]:
        return 0
    cursor.execute(
        """
        SELECT count(*)::int AS n FROM apiome.entity_owners
        WHERE team_id = %s::uuid AND status = 'confirmed'
        """,
        (team_id,),
    )
    counted = cursor.fetchone()
    return int(counted["n"]) if counted else 0


def _reassign_owned_entities(cursor: Any, from_team_id: str, to_team_id: str) -> int:
    """Move every confirmed ownership row from one team to another.

    Args:
        cursor: The transaction's cursor.
        from_team_id: The team being deleted.
        to_team_id: The team that takes ownership.

    Returns:
        How many rows moved.
    """
    cursor.execute(
        """
        UPDATE apiome.entity_owners SET team_id = %s::uuid
        WHERE team_id = %s::uuid AND status = 'confirmed'
        """,
        (to_team_id, from_team_id),
    )
    return int(cursor.rowcount or 0)


def list_teams(tenant_id: str) -> List[TeamRecord]:
    """Every live team of the tenant, by name.

    Args:
        tenant_id: The caller's tenant.

    Returns:
        The teams with their member counts (no member lists); empty for a non-UUID tenant.
    """
    if not is_uuid_string(tenant_id):
        return []
    rows = db.execute_query(
        f"""
        SELECT {_TEAM_COLUMNS}
        FROM apiome.teams t
        WHERE t.tenant_id = %s::uuid AND t.deleted_at IS NULL
        ORDER BY lower(t.name), t.slug
        """,
        (tenant_id,),
    )
    return [_record(dict(row)) for row in rows]


def get_team(tenant_id: str, slug: str) -> TeamRecord:
    """One live team with its members.

    Args:
        tenant_id: The caller's tenant.
        slug: The team's slug.

    Returns:
        The team, members included.

    Raises:
        TeamValidationError: ``team-not-found`` when no live team has that slug.
    """
    if not is_uuid_string(tenant_id):
        raise TeamValidationError(CODE_NOT_FOUND, f"no team '{slug}' in this tenant")
    rows = db.execute_query(
        f"""
        SELECT {_TEAM_COLUMNS}
        FROM apiome.teams t
        WHERE t.tenant_id = %s::uuid AND t.slug = %s AND t.deleted_at IS NULL
        """,
        (tenant_id, (slug or "").strip().lower()),
    )
    if not rows:
        raise TeamValidationError(CODE_NOT_FOUND, f"no team '{slug}' in this tenant")
    row = dict(rows[0])
    return _record(row, _members(db.execute_query(_MEMBERS_SQL, (row["id"],))))


def create_team(tenant_id: str, body: TeamInput, *, actor: ConsumerActor) -> TeamRecord:
    """Create a team, audited as ``team.create``.

    Args:
        tenant_id: The caller's tenant.
        body: The team to create.
        actor: Who is creating it.

    Returns:
        The stored team, with an empty member list.

    Raises:
        TeamValidationError: ``team-invalid`` for a malformed field, ``team-slug-taken`` when a
            live team already has the slug.
    """
    name = normalize_name(body.name)
    slug = resolve_slug(body.slug, name)
    values = {
        "name": name,
        "description": (body.description or "").strip() or None,
        "contact_email": normalize_contact_email(body.contact_email),
        "chat_url": normalize_link("chat_url", body.chat_url),
        "oncall_url": normalize_link("oncall_url", body.oncall_url),
        "docs_url": normalize_link("docs_url", body.docs_url),
    }

    def work(cursor: Any) -> TeamRecord:
        cursor.execute(
            """
            INSERT INTO apiome.teams
                (tenant_id, slug, name, description, contact_email, chat_url, oncall_url,
                 docs_url, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s::uuid)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                slug,
                values["name"],
                values["description"],
                values["contact_email"],
                values["chat_url"],
                values["oncall_url"],
                values["docs_url"],
                actor.user_id if is_uuid_string(actor.user_id or "") else None,
            ),
        )
        team_id = cursor.fetchone()["id"]
        _audit(cursor, tenant_id, actor, "team.create", slug, {"team_id": team_id, **values})
        row = _lock_team(cursor, tenant_id, slug)
        return _record(row, [])

    return _run(work)


def update_team(
    tenant_id: str, slug: str, patch: TeamPatch, *, actor: ConsumerActor
) -> TeamRecord:
    """Apply a partial update, audited as ``team.update`` with the fields that changed.

    Args:
        tenant_id: The caller's tenant.
        slug: The team's slug.
        patch: The fields to change; omitted fields are left alone, ``null`` clears one.
        actor: Who is changing it.

    Returns:
        The updated team with its members.

    Raises:
        TeamValidationError: ``team-not-found`` for an unknown slug, ``team-invalid`` for a
            malformed field (including ``name: null``).
    """
    provided = patch.model_fields_set
    changes: Dict[str, Optional[str]] = {}
    if "name" in provided:
        changes["name"] = normalize_name(patch.name or "")
    if "description" in provided:
        changes["description"] = (patch.description or "").strip() or None
    if "contact_email" in provided:
        changes["contact_email"] = normalize_contact_email(patch.contact_email)
    for field in ("chat_url", "oncall_url", "docs_url"):
        if field in provided:
            changes[field] = normalize_link(field, getattr(patch, field))

    def work(cursor: Any) -> TeamRecord:
        row = _lock_team(cursor, tenant_id, slug)
        changed = {key: value for key, value in changes.items() if row.get(key) != value}
        if changed:
            assignments = ", ".join(f"{key} = %s" for key in changed)
            cursor.execute(
                f"""
                UPDATE apiome.teams SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s::uuid
                """,
                (*changed.values(), row["id"]),
            )
            _audit(
                cursor,
                tenant_id,
                actor,
                "team.update",
                row["slug"],
                {
                    "team_id": row["id"],
                    "changes": {
                        key: {"from": row.get(key), "to": value} for key, value in changed.items()
                    },
                },
            )
            row = _lock_team(cursor, tenant_id, slug)
        cursor.execute(_MEMBERS_SQL, (row["id"],))
        return _record(row, _members(cursor.fetchall()))

    return _run(work)


def delete_team(
    tenant_id: str, slug: str, *, actor: ConsumerActor, reassign_to: Optional[str] = None
) -> Dict[str, Any]:
    """Soft-delete a team, audited as ``team.delete``.

    Args:
        tenant_id: The caller's tenant.
        slug: The team's slug.
        actor: Who is deleting it.
        reassign_to: The slug of the live team that takes over the deleted team's entities.

    Returns:
        ``{"slug", "owned_count", "reassigned_to"}`` — ``reassigned_to`` is ``None`` when nothing
        was moved.

    Raises:
        TeamValidationError: ``team-not-found`` for an unknown slug; ``team-owns-entities``
            (with ``owned_count``) when the team owns entities and ``reassign_to`` is absent;
            ``team-reassign-invalid`` when ``reassign_to`` names this team or no live team.
    """
    target_slug = (reassign_to or "").strip().lower() or None

    def work(cursor: Any) -> Dict[str, Any]:
        row = _lock_team(cursor, tenant_id, slug)
        target: Optional[Dict[str, Any]] = None
        if target_slug is not None:
            if target_slug == row["slug"]:
                raise TeamValidationError(
                    CODE_REASSIGN_INVALID, "reassign_to must name a different team"
                )
            try:
                target = _lock_team(cursor, tenant_id, target_slug)
            except TeamValidationError as exc:
                raise TeamValidationError(
                    CODE_REASSIGN_INVALID, f"reassign_to names no team '{target_slug}'"
                ) from exc

        owned = _owned_entity_count(cursor, row["id"])
        if owned and target is None:
            raise TeamValidationError(
                CODE_OWNS_ENTITIES,
                f"team '{row['slug']}' owns {owned} entities; pass reassign_to to move them",
                owned_count=owned,
            )
        moved = _reassign_owned_entities(cursor, row["id"], target["id"]) if owned else 0

        cursor.execute(
            """
            UPDATE apiome.teams SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid
            """,
            (row["id"],),
        )
        reassigned = target["slug"] if (target is not None and moved) else None
        _audit(
            cursor,
            tenant_id,
            actor,
            "team.delete",
            row["slug"],
            {"team_id": row["id"], "owned_count": owned, "reassigned_to": reassigned},
        )
        return {"slug": row["slug"], "owned_count": owned, "reassigned_to": reassigned}

    return _run(work)


def replace_team_members(
    tenant_id: str, slug: str, members: List[TeamMemberInput], *, actor: ConsumerActor
) -> TeamRecord:
    """Replace a team's membership, audited as ``team.members.replace``.

    Args:
        tenant_id: The caller's tenant.
        slug: The team's slug.
        members: The complete new membership; an empty list empties the team.
        actor: Who is changing it.

    Returns:
        The team with its new members.

    Raises:
        TeamValidationError: ``team-not-found`` for an unknown slug; ``team-invalid`` for a
            duplicate or malformed user id; ``team-member-not-in-tenant`` naming every listed user
            who is not a member of the tenant (nothing is written).
    """
    wanted = validate_members(members)

    def work(cursor: Any) -> TeamRecord:
        row = _lock_team(cursor, tenant_id, slug)
        ids = [member.user_id for member in wanted]
        if ids:
            cursor.execute(
                """
                SELECT user_id::text AS user_id FROM apiome.tenant_users
                WHERE tenant_id = %s::uuid AND user_id = ANY(%s::uuid[])
                """,
                (tenant_id, ids),
            )
            in_tenant = {str(found["user_id"]) for found in cursor.fetchall()}
            outsiders = [user_id for user_id in ids if user_id not in in_tenant]
            if outsiders:
                raise TeamValidationError(
                    CODE_MEMBER_NOT_IN_TENANT,
                    "not members of this tenant: " + ", ".join(outsiders),
                )

        cursor.execute(
            "SELECT user_id::text AS user_id, role FROM apiome.team_members WHERE team_id = %s::uuid",
            (row["id"],),
        )
        before = {str(prior["user_id"]): prior["role"] for prior in cursor.fetchall()}
        after = {member.user_id: member.role for member in wanted}

        # Remove whoever is no longer listed, then upsert the rest: a member who stays keeps the
        # date they joined, and a changed role is an update rather than a remove-and-add.
        cursor.execute(
            """
            DELETE FROM apiome.team_members
            WHERE team_id = %s::uuid AND NOT (user_id = ANY(%s::uuid[]))
            """,
            (row["id"], list(after.keys())),
        )
        if wanted:
            cursor.execute(
                """
                INSERT INTO apiome.team_members (team_id, user_id, role)
                SELECT %s::uuid, item.user_id, item.role
                FROM unnest(%s::uuid[], %s::text[]) AS item(user_id, role)
                ON CONFLICT (team_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                (row["id"], list(after.keys()), list(after.values())),
            )
        cursor.execute(
            "UPDATE apiome.teams SET updated_at = CURRENT_TIMESTAMP WHERE id = %s::uuid",
            (row["id"],),
        )
        _audit(
            cursor,
            tenant_id,
            actor,
            "team.members.replace",
            row["slug"],
            {
                "team_id": row["id"],
                "added": sorted(set(after) - set(before)),
                "removed": sorted(set(before) - set(after)),
                "role_changed": sorted(
                    user_id for user_id in set(before) & set(after) if before[user_id] != after[user_id]
                ),
                "member_count": len(after),
            },
        )
        cursor.execute(_MEMBERS_SQL, (row["id"],))
        listed = _members(cursor.fetchall())
        row["member_count"] = len(listed)
        return _record(row, listed)

    return _run(work)


def team_activity(tenant_id: str, slug: str, viewer_id: Optional[str]) -> Dict[str, Any]:
    """What a team page shows beyond the team itself (CDG-2.4, #5963).

    * **owned** — every entity the team is the *confirmed* owner of, with its kind and name;
      ``owned_counts`` tallies them by kind and ``suggested_count`` says how many suggestions
      name the team.
    * **open_findings** — the viewer's unread owner-finding inbox rows routed to this team. It is
      exactly the number the viewer's bell shows for those rows, so it is 0 for a non-member.
    * **events** — the last :data:`ACTIVITY_DAYS` days of routed findings, one per event: a finding
      reaches every member as a separate inbox row, so rows of one type about one entity within the
      same minute are one event.

    Args:
        tenant_id: The caller's tenant.
        slug: The team's slug.
        viewer_id: The signed-in user, whose unread rows are counted.

    Returns:
        ``{team_id, owned, owned_counts, suggested_count, open_findings, events}``.

    Raises:
        TeamValidationError: ``team-not-found`` for an unknown slug.
    """
    from .notifications import OWNER_NOTIFICATION_TYPES

    team = get_team(tenant_id, slug)
    owned_rows = db.execute_query(
        f"""
        SELECT eo.entity_kind, eo.entity_id::text AS entity_id, eo.source,
               {_OWNED_ENTITY_NAME_SQL} AS name
        FROM apiome.entity_owners eo
        WHERE eo.tenant_id = %s::uuid AND eo.team_id = %s::uuid AND eo.status = 'confirmed'
        ORDER BY eo.entity_kind, lower({_OWNED_ENTITY_NAME_SQL})
        LIMIT %s
        """,
        (tenant_id, team.id, _ACTIVITY_LIMIT),
    )
    suggested = db.execute_query(
        """
        SELECT count(*)::int AS n FROM apiome.entity_owners
        WHERE tenant_id = %s::uuid AND team_id = %s::uuid AND status = 'suggested'
        """,
        (tenant_id, team.id),
    )
    open_findings = 0
    if is_uuid_string(viewer_id or ""):
        counted = db.execute_query(
            """
            SELECT count(*)::int AS n FROM apiome.notifications
            WHERE tenant_id = %s::uuid AND user_id = %s::uuid AND read_at IS NULL
              AND type = ANY(%s::text[]) AND payload->'team'->>'id' = %s
            """,
            (tenant_id, viewer_id, list(OWNER_NOTIFICATION_TYPES), team.id),
        )
        open_findings = int(counted[0]["n"]) if counted else 0
    events = db.execute_query(
        """
        SELECT type,
               payload->>'entity_kind' AS entity_kind,
               payload->>'entity_id' AS entity_id,
               max(payload->>'entity_name') AS entity_name,
               max(payload->>'summary') AS summary,
               max(payload->>'link') AS link,
               max(created_at) AS created_at,
               count(*)::int AS recipients
        FROM apiome.notifications
        WHERE tenant_id = %s::uuid AND type = ANY(%s::text[])
          AND payload->'team'->>'id' = %s
          AND created_at >= CURRENT_TIMESTAMP - make_interval(days => %s)
        GROUP BY type, payload->>'entity_kind', payload->>'entity_id', date_trunc('minute', created_at)
        ORDER BY max(created_at) DESC
        LIMIT %s
        """,
        (tenant_id, list(OWNER_NOTIFICATION_TYPES), team.id, ACTIVITY_DAYS, _ACTIVITY_LIMIT),
    )

    counts: Dict[str, int] = {}
    owned = []
    for row in owned_rows:
        counts[row["entity_kind"]] = counts.get(row["entity_kind"], 0) + 1
        owned.append(
            {
                "kind": row["entity_kind"],
                "id": row["entity_id"],
                "name": row["name"],
                "source": row["source"],
            }
        )
    return {
        "team_id": team.id,
        "owned": owned,
        "owned_counts": counts,
        "suggested_count": int(suggested[0]["n"]) if suggested else 0,
        "open_findings": open_findings,
        "events": [
            {
                "type": row["type"],
                "entity_kind": row.get("entity_kind"),
                "entity_id": row.get("entity_id"),
                "entity_name": row.get("entity_name"),
                "summary": row.get("summary"),
                "link": row.get("link"),
                "created_at": _iso(row.get("created_at")),
                "recipients": int(row.get("recipients") or 0),
            }
            for row in events
        ],
    }
