"""Catalog entity reads over the kind registry — CDG-5.1 (#5979).

Every read here is bounded and its statement count is fixed by the request, never by the rows:

* :func:`list_entities` — one ``SELECT … LIMIT`` per requested kind, merged in Python into one page
  ordered by ``(lower(name), kind order, id)``; the cursor remembers the last row's sort key, so the
  next page is the next ``limit`` rows across every kind;
* :func:`kind_counts` — one ``UNION ALL`` statement counting every kind (the facet and the tiles);
* :func:`unowned_count` and :func:`stale_count` — one statement each (the home callouts).

Names are compared with ``COLLATE "C"`` (byte order), which is the order Python's ``str`` comparison
gives the same UTF-8 text, so the in-Python merge and the per-kind ``ORDER BY`` agree.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .catalog_entities import REGISTRY, EntityKind
from .entity_owners import owner_envelope_join, owner_team_filter

__all__ = [
    "CursorError",
    "EntityPage",
    "decode_cursor",
    "encode_cursor",
    "kind_counts",
    "list_entities",
    "stale_count",
    "unowned_count",
]

#: Owner rows of a ``projects`` row may be stored as either kind (a converted item keeps its rows).
_PROJECT_OWNER_KINDS = ("project", "catalog_item")


class CursorError(ValueError):
    """A ``cursor`` that this module did not issue."""


@dataclass(frozen=True)
class EntityPage:
    """One page of entities.

    Attributes:
        rows: The page's rows: ``kind`` (the :class:`EntityKind`), ``id``, ``slug``, ``name``,
            ``description``, ``updated_at``, ``entity_owner`` (the owner JSON or ``None``).
        next_cursor: The cursor of the next page, or ``None`` on the last page.
    """

    rows: List[Dict[str, Any]]
    next_cursor: Optional[str]


def _ordinal(entry: EntityKind) -> int:
    """The kind's position in :data:`REGISTRY` (its tie-break order)."""
    return next(index for index, candidate in enumerate(REGISTRY) if candidate.key == entry.key)


def encode_cursor(sort_name: str, entry: EntityKind, entity_id: str) -> str:
    """Encode the sort key of a page's last row.

    Args:
        sort_name: The row's ``lower(name)``.
        entry: Its kind.
        entity_id: Its id.

    Returns:
        A URL-safe opaque string.
    """
    raw = json.dumps({"n": sort_name, "k": entry.key, "i": entity_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> Tuple[str, int, str]:
    """Decode a cursor from :func:`encode_cursor`.

    Args:
        cursor: The opaque string.

    Returns:
        ``(sort_name, kind ordinal, id)``.

    Raises:
        CursorError: The cursor is malformed or names an unknown kind.
    """
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        name, key, entity_id = data["n"], data["k"], data["i"]
    except (binascii.Error, UnicodeError, ValueError, KeyError, TypeError) as exc:
        raise CursorError("Malformed cursor.") from exc
    if not isinstance(name, str) or not isinstance(key, str) or not isinstance(entity_id, str):
        raise CursorError("Malformed cursor.")
    for index, entry in enumerate(REGISTRY):
        if entry.key == key:
            return name, index, entity_id
    raise CursorError("Malformed cursor.")


def _owner_kinds(entry: EntityKind) -> Tuple[str, ...]:
    """The ``entity_owners`` kinds an entity of ``entry`` may be stored under."""
    if entry.owner_kind in _PROJECT_OWNER_KINDS:
        return _PROJECT_OWNER_KINDS
    return (entry.owner_kind,) if entry.owner_kind else ()


def _filters(entry: EntityKind, tenant_id: str, team: Optional[str], q: Optional[str]) -> Tuple[str, str, List[Any]]:
    """The owner join and ``WHERE`` clause every read of one kind shares.

    Args:
        entry: The kind.
        tenant_id: The tenant.
        team: Owner team slug filter (the kind must support owners).
        q: Text filter on name, slug and description.

    Returns:
        ``(join_sql, where_sql, params)``.
    """
    join = owner_envelope_join(_owner_kinds(entry), "e.id", "e.tenant_id") if entry.owner_kind else ""
    team_sql, team_params = owner_team_filter(team) if entry.owner_kind else ("", [])
    where = f"WHERE e.tenant_id = %s::uuid AND {entry.live_where} {team_sql}"
    params: List[Any] = [tenant_id, *team_params]
    text = (q or "").strip()
    if text:
        pattern = f"%{text}%"
        where += (
            f" AND (e.name ILIKE %s OR COALESCE({entry.slug_sql}, '') ILIKE %s"
            f" OR COALESCE({entry.description_sql}, '') ILIKE %s)"
        )
        params += [pattern, pattern, pattern]
    return join, where, params


def _in_scope(kinds: Sequence[EntityKind], team: Optional[str]) -> List[EntityKind]:
    """The kinds a read covers: a team filter leaves out kinds that cannot have an owner."""
    return [entry for entry in kinds if entry.owner_kind or not (team or "").strip()]


def list_entities(
    db: Any,
    tenant_id: str,
    kinds: Sequence[EntityKind],
    *,
    team: Optional[str] = None,
    q: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
) -> EntityPage:
    """One page of entities across ``kinds``, ordered by name, then kind order, then id.

    Issues exactly one statement per kind in scope, each returning at most ``limit + 1`` rows.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kinds: The kinds to list (already permission-checked).
        team: Only entities whose owner (confirmed, else suggested) is this team; kinds without
            owners are left out.
        q: Only entities whose name, slug or description contains this text.
        cursor: The ``next_cursor`` of the previous page.
        limit: Page size.

    Returns:
        The page.

    Raises:
        CursorError: ``cursor`` is malformed.
    """
    after = decode_cursor(cursor) if cursor else None
    rows: List[Dict[str, Any]] = []
    for entry in _in_scope(kinds, team):
        join, where, params = _filters(entry, tenant_id, team, q)
        sort = 'lower(COALESCE(e.name, \'\')) COLLATE "C"'
        if after is not None:
            name, ordinal, entity_id = after
            mine = _ordinal(entry)
            if mine == ordinal:
                where += f" AND ({sort}, e.id::text COLLATE \"C\") > (%s, %s)"
                params += [name, entity_id]
            elif mine > ordinal:
                where += f" AND {sort} >= %s"
                params.append(name)
            else:
                where += f" AND {sort} > %s"
                params.append(name)
        owner_col = "own.entity_owner" if entry.owner_kind else "NULL::jsonb"
        sql = f"""
            SELECT e.id::text AS id, {entry.slug_sql} AS slug, e.name AS name,
                   {entry.description_sql} AS description, e.updated_at AS updated_at,
                   {sort} AS sort_name, {owner_col} AS entity_owner
            FROM {entry.table} e
            {join}
            {where}
            ORDER BY {sort}, e.id::text COLLATE "C"
            LIMIT %s
        """
        for row in db.execute_query(sql, (*params, limit + 1)) or []:
            rows.append({**dict(row), "kind": entry, "_ordinal": _ordinal(entry)})
    rows.sort(key=lambda row: (row.get("sort_name") or "", row["_ordinal"], str(row["id"])))
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit and page:
        last = page[-1]
        next_cursor = encode_cursor(last.get("sort_name") or "", last["kind"], str(last["id"]))
    for row in page:
        row.pop("_ordinal", None)
    return EntityPage(rows=page, next_cursor=next_cursor)


def kind_counts(
    db: Any,
    tenant_id: str,
    kinds: Sequence[EntityKind],
    *,
    team: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, int]:
    """Count every kind in one ``UNION ALL`` statement.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kinds: The kinds to count.
        team: Owner team filter; kinds without owners count ``0`` under it.
        q: Text filter.

    Returns:
        ``{kind key: count}`` for every kind in ``kinds``.
    """
    counts = {entry.key: 0 for entry in kinds}
    parts: List[str] = []
    params: List[Any] = []
    for entry in _in_scope(kinds, team):
        join, where, part_params = _filters(entry, tenant_id, team, q)
        parts.append(f"SELECT %s AS kind, count(*) AS n FROM {entry.table} e {join} {where}")
        params += [entry.key, *part_params]
    if not parts:
        return counts
    for row in db.execute_query(" UNION ALL ".join(parts), tuple(params)) or []:
        counts[str(row["kind"])] = int(row["n"] or 0)
    return counts


def unowned_count(db: Any, tenant_id: str, kinds: Sequence[EntityKind]) -> int:
    """Count live entities of owner-capable ``kinds`` with no confirmed owner team, in one statement.

    A confirmed owner whose team was deleted does not count as an owner.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kinds: The kinds to look at (kinds without owners are skipped).

    Returns:
        The number of unowned entities.
    """
    parts: List[str] = []
    params: List[Any] = []
    for entry in kinds:
        if not entry.owner_kind:
            continue
        kind_list = ", ".join(f"'{k}'" for k in _owner_kinds(entry))
        parts.append(
            f"""
            SELECT count(*) AS n FROM {entry.table} e
            WHERE e.tenant_id = %s::uuid AND {entry.live_where}
              AND NOT EXISTS (
                  SELECT 1 FROM apiome.entity_owners eo
                  JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
                  WHERE eo.tenant_id = e.tenant_id AND eo.entity_id = e.id
                    AND eo.entity_kind IN ({kind_list}) AND eo.status = 'confirmed'
              )
            """
        )
        params.append(tenant_id)
    if not parts:
        return 0
    rows = db.execute_query(" UNION ALL ".join(parts), tuple(params)) or []
    return sum(int(row["n"] or 0) for row in rows)


def stale_count(
    db: Any,
    tenant_id: str,
    *,
    connectors: bool,
    mcp_servers: bool,
    connector_default_seconds: int,
    connector_floor_seconds: int,
    mcp_default_seconds: int,
) -> int:
    """Count sources not refreshed within twice their cadence, in one statement.

    * A **connector** (not paused) is stale when its last successful run — else its creation —
      is older than ``2 × max(refresh interval or default, floor)``.
    * An enabled **MCP server** is stale when its last discovery — else its creation — is older than
      ``2 × (its discovery cadence or the default)``.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        connectors: Count connectors (the caller may view them).
        mcp_servers: Count MCP servers (the caller may view them).
        connector_default_seconds: ``settings.refresh_default_interval_seconds``.
        connector_floor_seconds: ``settings.refresh_min_interval_seconds``.
        mcp_default_seconds: ``settings.mcp_discovery_default_cadence_seconds``.

    Returns:
        The number of stale sources.
    """
    parts: List[str] = []
    params: List[Any] = []
    if connectors:
        parts.append(
            """
            SELECT count(*) AS n FROM apiome.catalog_connectors c
            WHERE c.tenant_id = %s::uuid AND c.deleted_at IS NULL AND c.status <> 'paused'
              AND COALESCE(
                    (SELECT max(COALESCE(j.finished_at, j.created_at))
                       FROM apiome.tenant_repository_refresh_jobs j
                      WHERE j.connector_id = c.id AND j.status = 'succeeded'),
                    c.created_at)
                  < now() - make_interval(secs => 2 * GREATEST(COALESCE(c.refresh_interval_seconds, %s), %s))
            """
        )
        params += [tenant_id, int(connector_default_seconds), int(connector_floor_seconds)]
    if mcp_servers:
        parts.append(
            """
            SELECT count(*) AS n FROM apiome.mcp_endpoints m
            WHERE m.tenant_id = %s::uuid AND m.deleted_at IS NULL AND m.enabled
              AND COALESCE(m.last_discovered_at, m.created_at)
                  < now() - make_interval(secs => 2 * CASE WHEN COALESCE(m.discovery_cadence_seconds, 0) > 0
                                                           THEN m.discovery_cadence_seconds ELSE %s END)
            """
        )
        params += [tenant_id, max(1, int(mcp_default_seconds))]
    if not parts:
        return 0
    rows = db.execute_query(" UNION ALL ".join(parts), tuple(params)) or []
    return sum(int(row["n"] or 0) for row in rows)
