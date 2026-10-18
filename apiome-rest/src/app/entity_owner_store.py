"""Persistence for entity owners — CDG-2.2 (#5961).

:mod:`app.entity_owners` says what an owner is; this module is the only place ``apiome.entity_owners``
(apiome-db V285) is read or written by apiome-rest.

**Every change is audited, in its own transaction.** A manual assignment, a removal, a confirmation
and a bulk assignment append ``owner.assign``, ``owner.remove``, ``owner.confirm`` or
``owner.bulk_assign`` to the tenant's hash-chained ``access_audit`` on the cursor that makes the
change. When an importer changes an entity's suggestions, ``owner.suggestions`` records the
before-and-after for that source (no actor: the importer acted, not a person).

**Suggestions never become owners on their own.** :func:`record_suggestions` only writes
``suggested`` rows; :func:`confirm_owner` is the one path that turns a suggestion into the owner,
and it records who confirmed it. Nothing here sends a notification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .consumer_contract_store import ConsumerActor
from .database import db
from .entity_owners import (
    CODE_ENTITY_NOT_FOUND,
    CODE_INVALID,
    CODE_NO_SUGGESTION,
    CODE_TEAM_NOT_FOUND,
    SOURCE_MANUAL,
    EntityRef,
    OwnerRecord,
    OwnersResponse,
    OwnerTeamRef,
    OwnerValidationError,
    kind_spec,
)
from .revision_deprecation import is_uuid_string

__all__ = [
    "assign_owner",
    "bulk_assign_owner",
    "confirm_owner",
    "read_owners",
    "record_suggestions",
    "remove_owner",
]

_OWNER_COLUMNS = """
    eo.id::text AS id, eo.status, eo.source, eo.source_ref, eo.team_id::text AS team_id,
    eo.confirmed_by::text AS confirmed_by, eo.confirmed_at, eo.created_at,
    t.slug AS team_slug, t.name AS team_name
"""


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 for a timestamp; strings and ``None`` pass through."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _record(row: Mapping[str, Any]) -> OwnerRecord:
    """Build an :class:`OwnerRecord` from a row selected with ``_OWNER_COLUMNS``."""
    return OwnerRecord(
        team=OwnerTeamRef(id=str(row["team_id"]), slug=row["team_slug"], name=row["team_name"]),
        status=row["status"],
        source=row["source"],
        source_ref=row.get("source_ref"),
        confirmed_by=row.get("confirmed_by"),
        confirmed_at=_iso(row.get("confirmed_at")),
        created_at=_iso(row.get("created_at")),
    )


def _audit(
    cursor: Any,
    tenant_id: str,
    actor: Optional[ConsumerActor],
    action: str,
    kind: str,
    entity_id: str,
    detail: Dict[str, Any],
) -> None:
    """Append an ``owner.*`` row to the tenant's access audit inside the open transaction."""
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=action,
        actor_id=actor.user_id if actor else None,
        actor_label=actor.label if actor else "importer",
        target=f"{kind}:{entity_id}",
        source="api_key" if actor and actor.kind == "api_key" else "web",
        detail={"kind": kind, "entity_id": entity_id, **detail},
    )


def _require_entity(cursor: Any, tenant_id: str, kind: str, entity_id: str) -> None:
    """Refuse an entity that is not a live row of ``kind`` in the tenant.

    Raises:
        OwnerValidationError: ``owner-invalid`` for an unknown kind; ``owner-entity-not-found``
            for a malformed id or a missing, deleted or other-tenant entity.
    """
    spec = kind_spec(kind)
    if not is_uuid_string(entity_id or ""):
        raise OwnerValidationError(CODE_ENTITY_NOT_FOUND, f"no {kind} '{entity_id}' in this tenant")
    cursor.execute(
        f"SELECT 1 AS found FROM {spec.table} e "
        f"WHERE e.id = %s::uuid AND e.tenant_id = %s::uuid AND {spec.where}",
        (entity_id, tenant_id),
    )
    if not cursor.fetchone():
        raise OwnerValidationError(CODE_ENTITY_NOT_FOUND, f"no {kind} '{entity_id}' in this tenant")


def _require_team(cursor: Any, tenant_id: str, slug: str) -> Dict[str, Any]:
    """Resolve a live team by slug.

    Raises:
        OwnerValidationError: ``owner-team-not-found`` when no live team has the slug.
    """
    cursor.execute(
        """
        SELECT id::text AS id, slug, name FROM apiome.teams
        WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL
        """,
        (tenant_id, (slug or "").strip().lower()),
    )
    row = cursor.fetchone()
    if not row:
        raise OwnerValidationError(CODE_TEAM_NOT_FOUND, f"no team '{slug}' in this tenant")
    return dict(row)


def _owner_rows(cursor: Any, tenant_id: str, kind: str, entity_id: str) -> List[Dict[str, Any]]:
    """Every owner row of an entity whose team is live, confirmed first."""
    cursor.execute(
        f"""
        SELECT {_OWNER_COLUMNS}
        FROM apiome.entity_owners eo
        JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
        WHERE eo.tenant_id = %s::uuid AND eo.entity_kind = %s AND eo.entity_id = %s::uuid
        ORDER BY (eo.status = 'confirmed') DESC, eo.created_at, eo.id
        """,
        (tenant_id, kind, entity_id),
    )
    return [dict(row) for row in cursor.fetchall()]


def _response(kind: str, entity_id: str, rows: Sequence[Mapping[str, Any]]) -> OwnersResponse:
    """Split owner rows into the confirmed owner and the suggestions."""
    confirmed = [row for row in rows if row["status"] == "confirmed"]
    return OwnersResponse(
        kind=kind,
        entity_id=entity_id,
        owner=_record(confirmed[0]) if confirmed else None,
        suggestions=[_record(row) for row in rows if row["status"] == "suggested"],
    )


def _confirmed_slug(rows: Sequence[Mapping[str, Any]]) -> Optional[str]:
    """The confirmed owner's team slug, or ``None``."""
    return next((row["team_slug"] for row in rows if row["status"] == "confirmed"), None)


def _clear_confirmed(cursor: Any, tenant_id: str, kind: str, entity_id: str) -> None:
    """Remove the confirmed owner row, leaving suggestions alone.

    A confirmed row that came from a suggestion goes back to being a suggestion rather than
    disappearing, so the importer's evidence is not lost when someone picks another owner.
    """
    # A manual row has no evidence behind it, and an imported row whose suggestion has since been
    # re-made would duplicate it: both are dropped. What remains goes back to being a suggestion.
    cursor.execute(
        """
        DELETE FROM apiome.entity_owners c
        WHERE c.tenant_id = %s::uuid AND c.entity_kind = %s AND c.entity_id = %s::uuid
          AND c.status = 'confirmed'
          AND (c.source = 'manual' OR EXISTS (
              SELECT 1 FROM apiome.entity_owners s
              WHERE s.tenant_id = c.tenant_id AND s.entity_kind = c.entity_kind
                AND s.entity_id = c.entity_id AND s.team_id = c.team_id
                AND s.source = c.source AND s.status = 'suggested'
          ))
        """,
        (tenant_id, kind, entity_id),
    )
    cursor.execute(
        """
        UPDATE apiome.entity_owners
        SET status = 'suggested', confirmed_by = NULL, confirmed_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE tenant_id = %s::uuid AND entity_kind = %s AND entity_id = %s::uuid
          AND status = 'confirmed'
        """,
        (tenant_id, kind, entity_id),
    )


def _insert_manual(
    cursor: Any, tenant_id: str, kind: str, entity_id: str, team_id: str, actor: ConsumerActor
) -> None:
    """Insert a confirmed, manually assigned owner row."""
    cursor.execute(
        """
        INSERT INTO apiome.entity_owners
            (tenant_id, entity_kind, entity_id, team_id, status, source, confirmed_by, confirmed_at)
        VALUES (%s::uuid, %s, %s::uuid, %s::uuid, 'confirmed', %s, %s::uuid, CURRENT_TIMESTAMP)
        """,
        (
            tenant_id,
            kind,
            entity_id,
            team_id,
            SOURCE_MANUAL,
            actor.user_id if is_uuid_string(actor.user_id or "") else None,
        ),
    )


def _run(work: Callable[[Any], Any]) -> Any:
    """Run ``work`` in one transaction; whatever it raises rolls everything back."""
    return db._guarded_tx(work)


def read_owners(tenant_id: str, kind: str, entity_id: str) -> OwnersResponse:
    """An entity's confirmed owner and suggestions.

    Raises:
        OwnerValidationError: ``owner-invalid`` / ``owner-entity-not-found``.
    """

    def work(cursor: Any) -> OwnersResponse:
        _require_entity(cursor, tenant_id, kind, entity_id)
        return _response(kind, entity_id, _owner_rows(cursor, tenant_id, kind, entity_id))

    return _run(work)


def assign_owner(
    tenant_id: str, kind: str, entity_id: str, team_slug: str, *, actor: ConsumerActor
) -> OwnersResponse:
    """Make a team the confirmed owner (source ``manual``), audited as ``owner.assign``.

    Args:
        tenant_id: The caller's tenant.
        kind: The entity kind.
        entity_id: The entity.
        team_slug: The team to make the owner.
        actor: Who assigned it.

    Returns:
        The entity's owners after the change.

    Raises:
        OwnerValidationError: ``owner-invalid``, ``owner-entity-not-found``, ``owner-team-not-found``.
    """

    def work(cursor: Any) -> OwnersResponse:
        _require_entity(cursor, tenant_id, kind, entity_id)
        team = _require_team(cursor, tenant_id, team_slug)
        previous = _confirmed_slug(_owner_rows(cursor, tenant_id, kind, entity_id))
        _clear_confirmed(cursor, tenant_id, kind, entity_id)
        _insert_manual(cursor, tenant_id, kind, entity_id, team["id"], actor)
        _audit(cursor, tenant_id, actor, "owner.assign", kind, entity_id,
               {"from": previous, "to": team["slug"]})
        return _response(kind, entity_id, _owner_rows(cursor, tenant_id, kind, entity_id))

    return _run(work)


def remove_owner(
    tenant_id: str, kind: str, entity_id: str, *, actor: ConsumerActor
) -> OwnersResponse:
    """Remove the confirmed owner, audited as ``owner.remove``; suggestions stay.

    A confirmed owner that came from a suggestion becomes a suggestion again.

    Raises:
        OwnerValidationError: ``owner-invalid``, ``owner-entity-not-found``.
    """

    def work(cursor: Any) -> OwnersResponse:
        _require_entity(cursor, tenant_id, kind, entity_id)
        previous = _confirmed_slug(_owner_rows(cursor, tenant_id, kind, entity_id))
        if previous is not None:
            _clear_confirmed(cursor, tenant_id, kind, entity_id)
            _audit(cursor, tenant_id, actor, "owner.remove", kind, entity_id, {"from": previous})
        return _response(kind, entity_id, _owner_rows(cursor, tenant_id, kind, entity_id))

    return _run(work)


def confirm_owner(
    tenant_id: str,
    kind: str,
    entity_id: str,
    team_slug: Optional[str],
    *,
    actor: ConsumerActor,
) -> OwnersResponse:
    """Turn a suggestion into the confirmed owner, audited as ``owner.confirm`` with who confirmed.

    Args:
        tenant_id: The caller's tenant.
        kind: The entity kind.
        entity_id: The entity.
        team_slug: The suggested team to confirm; may be omitted when only one team is suggested.
        actor: Who confirmed it.

    Returns:
        The entity's owners after the change.

    Raises:
        OwnerValidationError: ``owner-no-suggestion`` when the entity has no suggestion (for that
            team); ``owner-invalid`` when ``team_slug`` is omitted and several teams are suggested.
    """

    def work(cursor: Any) -> OwnersResponse:
        _require_entity(cursor, tenant_id, kind, entity_id)
        rows = _owner_rows(cursor, tenant_id, kind, entity_id)
        suggested = [row for row in rows if row["status"] == "suggested"]
        if team_slug:
            wanted = (team_slug or "").strip().lower()
            suggested = [row for row in suggested if row["team_slug"] == wanted]
        if not suggested:
            raise OwnerValidationError(
                CODE_NO_SUGGESTION,
                f"no suggested owner{' ' + repr(team_slug) if team_slug else ''} to confirm",
            )
        if len({row["team_slug"] for row in suggested}) > 1:
            raise OwnerValidationError(
                CODE_INVALID, "several teams are suggested; name the one to confirm in `team`"
            )
        chosen = suggested[0]
        previous = _confirmed_slug(rows)
        _clear_confirmed(cursor, tenant_id, kind, entity_id)
        cursor.execute(
            """
            UPDATE apiome.entity_owners
            SET status = 'confirmed', confirmed_by = %s::uuid, confirmed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid
            """,
            (actor.user_id if is_uuid_string(actor.user_id or "") else None, chosen["id"]),
        )
        _audit(
            cursor,
            tenant_id,
            actor,
            "owner.confirm",
            kind,
            entity_id,
            {
                "from": previous,
                "to": chosen["team_slug"],
                "source": chosen["source"],
                "source_ref": chosen.get("source_ref"),
                "confirmed_by": actor.user_id,
            },
        )
        return _response(kind, entity_id, _owner_rows(cursor, tenant_id, kind, entity_id))

    return _run(work)


def bulk_assign_owner(
    tenant_id: str, team_slug: str, entities: Sequence[EntityRef], *, actor: ConsumerActor
) -> List[OwnersResponse]:
    """Make one team the confirmed owner of many entities, all or nothing.

    One ``owner.bulk_assign`` audit row lists every entity and its previous owner.

    Raises:
        OwnerValidationError: ``owner-team-not-found``; ``owner-entity-not-found`` naming the first
            entity that does not exist (nothing is written).
    """
    seen: set[tuple[str, str]] = set()
    unique: List[EntityRef] = []
    for ref in entities:
        key = (ref.kind, ref.id.strip().lower())
        if key not in seen:
            seen.add(key)
            unique.append(EntityRef(kind=ref.kind, id=key[1]))

    def work(cursor: Any) -> List[OwnersResponse]:
        team = _require_team(cursor, tenant_id, team_slug)
        for ref in unique:
            _require_entity(cursor, tenant_id, ref.kind, ref.id)
        changes = []
        results = []
        for ref in unique:
            previous = _confirmed_slug(_owner_rows(cursor, tenant_id, ref.kind, ref.id))
            _clear_confirmed(cursor, tenant_id, ref.kind, ref.id)
            _insert_manual(cursor, tenant_id, ref.kind, ref.id, team["id"], actor)
            changes.append({"kind": ref.kind, "entity_id": ref.id, "from": previous})
            results.append(_response(ref.kind, ref.id, _owner_rows(cursor, tenant_id, ref.kind, ref.id)))
        db._append_access_audit(
            cursor,
            tenant_id=tenant_id,
            action="owner.bulk_assign",
            actor_id=actor.user_id,
            actor_label=actor.label,
            target=f"team:{team['slug']}",
            source="api_key" if actor.kind == "api_key" else "web",
            detail={"to": team["slug"], "entities": changes},
        )
        return results

    return _run(work)


def record_suggestions(
    tenant_id: str,
    kind: str,
    entity_id: str,
    source: str,
    suggestions: Sequence[Mapping[str, Any]],
) -> List[str]:
    """Replace one source's suggestions for an entity; return the slugs that name no team.

    Called by importers: a connector sync with its gateway tags, the import pipeline with a
    document's ``x-apiome-owner`` / ``info.contact``. A slug that names no live team is not stored;
    it is returned so the importer can say so (a connector reports "unknown team `x` in tag"). A
    suggestion that is already the confirmed owner is left as it is. Nothing is notified.

    Args:
        tenant_id: The entity's tenant.
        kind: The entity kind.
        entity_id: The entity.
        source: ``gateway_tag``, ``spec_extension`` (or another non-manual source).
        suggestions: ``[{team, sourceRef}]`` — the complete current set for this source.

    Returns:
        The slugs that match no live team, in input order.
    """
    if source == SOURCE_MANUAL:
        raise OwnerValidationError(CODE_INVALID, "manual owners are assigned, not suggested")
    if not is_uuid_string(tenant_id or "") or not is_uuid_string(entity_id or ""):
        return []
    kind_spec(kind)
    wanted: Dict[str, Optional[str]] = {}
    for suggestion in suggestions or []:
        slug = str(suggestion.get("team") or "").strip().lower()
        if slug and slug not in wanted:
            wanted[slug] = suggestion.get("sourceRef")

    def work(cursor: Any) -> List[str]:
        teams: Dict[str, str] = {}
        if wanted:
            cursor.execute(
                """
                SELECT slug, id::text AS id FROM apiome.teams
                WHERE tenant_id = %s::uuid AND deleted_at IS NULL AND slug = ANY(%s::text[])
                """,
                (tenant_id, list(wanted)),
            )
            teams = {row["slug"]: row["id"] for row in cursor.fetchall()}
        unknown = [slug for slug in wanted if slug not in teams]

        def stored() -> List[str]:
            cursor.execute(
                """
                SELECT t.slug FROM apiome.entity_owners eo JOIN apiome.teams t ON t.id = eo.team_id
                WHERE eo.tenant_id = %s::uuid AND eo.entity_kind = %s AND eo.entity_id = %s::uuid
                  AND eo.source = %s AND eo.status = 'suggested'
                """,
                (tenant_id, kind, entity_id, source),
            )
            return sorted(row["slug"] for row in cursor.fetchall())

        before = stored()
        cursor.execute(
            """
            DELETE FROM apiome.entity_owners
            WHERE tenant_id = %s::uuid AND entity_kind = %s AND entity_id = %s::uuid
              AND source = %s AND status = 'suggested' AND NOT (team_id = ANY(%s::uuid[]))
            """,
            (tenant_id, kind, entity_id, source, list(teams.values())),
        )
        for slug, team_id in teams.items():
            cursor.execute(
                """
                INSERT INTO apiome.entity_owners
                    (tenant_id, entity_kind, entity_id, team_id, status, source, source_ref)
                SELECT %s::uuid, %s, %s::uuid, %s::uuid, 'suggested', %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM apiome.entity_owners c
                    WHERE c.tenant_id = %s::uuid AND c.entity_kind = %s AND c.entity_id = %s::uuid
                      AND c.team_id = %s::uuid AND c.status = 'confirmed'
                )
                ON CONFLICT (tenant_id, entity_kind, entity_id, team_id, source)
                    WHERE status = 'suggested'
                DO UPDATE SET source_ref = EXCLUDED.source_ref, updated_at = CURRENT_TIMESTAMP
                """,
                (
                    tenant_id, kind, entity_id, team_id, source, wanted[slug],
                    tenant_id, kind, entity_id, team_id,
                ),
            )
        after = stored()
        if after != before:
            _audit(cursor, tenant_id, None, "owner.suggestions", kind, entity_id,
                   {"source": source, "from": before, "to": after, "unknown": unknown})
        return unknown

    return _run(work)
