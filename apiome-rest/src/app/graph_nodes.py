"""Catalog graph nodes: labels, owners and the tenant-wide search — CDG-3.4 (#5969).

Edges (:mod:`app.catalog_graph`) carry only ``(kind, id)`` ends. A screen needs a name, a slug for
links and the owner team, so this module looks them up in batch — one query per node kind present,
one for owners — for :func:`app.catalog_graph.list_edges` (``labels=true``), the blast radius
(:mod:`app.blast_radius`) and :func:`search_entities`, which lists the entities that have edges at
all, with their in/out counts, for the tenant-wide graph page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .catalog_entities import kinds_by_graph_kind
from .catalog_graph import NODE_KINDS, PROVENANCES, GraphValidationError

__all__ = [
    "MAX_SEARCH_LIMIT",
    "NodePage",
    "PROJECT_KINDS",
    "current_node_kinds",
    "label_nodes",
    "label_sql",
    "node_owners",
    "search_entities",
]

#: The tenant-wide search returns at most this many entities per page.
MAX_SEARCH_LIMIT = 2_000

_BY_IDS = " WHERE e.tenant_id = %s::uuid AND e.id = ANY(%s::uuid[])"


def _table_kind(kind: str) -> str:
    return "project" if kind == "catalog_item" else kind


def _entity_label_sql() -> Dict[str, str]:
    """``SELECT id, name, slug`` for every catalog entity kind that is a graph node (CDG-5.1).

    Derived from the kind registry (:data:`app.catalog_entities.REGISTRY`), so a kind added there
    with a ``graph_kind`` is labelled here with no other change. A catalog item and a Project share
    the ``projects`` query (labels do not filter on ``publishable``).
    """
    return {
        _table_kind(graph_kind): (
            f"SELECT e.id::text AS id, e.name, {entry.slug_sql} AS slug FROM {entry.table} e" + _BY_IDS
        )
        for graph_kind, entry in kinds_by_graph_kind().items()
    }


#: ``SELECT id, name, slug`` for the graph kinds that are not catalog entities.
_OTHER_LABEL_SQL: Mapping[str, str] = {
    "repository": (
        "SELECT e.id::text AS id, COALESCE(e.repository_full_name, e.clone_url_normalized) AS name, "
        "NULL::text AS slug FROM apiome.tenant_repositories e" + _BY_IDS
    ),
    "mcp_source": "SELECT e.id::text AS id, e.locator AS name, NULL::text AS slug FROM apiome.mcp_endpoint_sources e"
    + _BY_IDS,
}


def label_sql() -> Dict[str, str]:
    """``SELECT id, name, slug`` per table-backed node kind: the registry's entity kinds (read on
    every call, so the registry stays the one source) plus the graph-only kinds."""
    return {**_OTHER_LABEL_SQL, **_entity_label_sql()}


def label_nodes(db: Any, tenant_id: str, refs: Sequence[Tuple[str, str]]) -> Dict[str, Dict[str, Any]]:
    """``{id: {name, slug}}`` for the nodes, one query per kind present.

    An identity group has no name of its own and is labelled ``Identity group``; a node whose row
    is gone is simply absent.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        refs: ``(kind, id)`` pairs.

    Returns:
        The labels by id.
    """
    by_kind: Dict[str, List[str]] = {}
    labels: Dict[str, Dict[str, Any]] = {}
    queries = label_sql()
    for kind, entity_id in refs:
        if kind == "identity_group":
            labels[str(entity_id)] = {"name": "Identity group", "slug": None}
        elif _table_kind(kind) in queries:
            by_kind.setdefault(_table_kind(kind), []).append(str(entity_id))
    for kind, ids in by_kind.items():
        for row in db.execute_query(queries[kind], (tenant_id, sorted(set(ids)))):
            labels[str(row["id"])] = {"name": row.get("name"), "slug": row.get("slug")}
    return labels


def node_owners(db: Any, tenant_id: str, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """``{id: {slug, name, status}}`` — each node's confirmed owner team, else its oldest suggestion."""
    if not ids:
        return {}
    rows = db.execute_query(
        """
        SELECT DISTINCT ON (eo.entity_id) eo.entity_id::text AS id, t.slug, t.name, eo.status
        FROM apiome.entity_owners eo
        JOIN apiome.teams t ON t.id = eo.team_id AND t.deleted_at IS NULL
        WHERE eo.tenant_id = %s::uuid AND eo.entity_id = ANY(%s::uuid[])
        ORDER BY eo.entity_id, (eo.status = 'confirmed') DESC, eo.created_at
        """,
        (tenant_id, sorted({str(i) for i in ids})),
    )
    return {str(row["id"]): {"slug": row["slug"], "name": row["name"], "status": row["status"]} for row in rows}


def node_labels_with_owners(
    db: Any, tenant_id: str, refs: Sequence[Tuple[str, str]]
) -> Dict[str, Dict[str, Any]]:
    """``{id: {name, slug, owner}}`` — :func:`label_nodes` and :func:`node_owners` together."""
    labels = label_nodes(db, tenant_id, refs)
    owners = node_owners(db, tenant_id, [entity_id for _kind, entity_id in refs])
    return {
        str(entity_id): {
            **labels.get(str(entity_id), {"name": None, "slug": None}), "owner": owners.get(str(entity_id)),
        }
        for _kind, entity_id in refs
    }


#: The two node kinds a ``projects`` row can be.
PROJECT_KINDS = ("project", "catalog_item")


def current_node_kinds(db: Any, tenant_id: str, refs: Sequence[Tuple[str, str]]) -> Dict[str, str]:
    """The kind each ``projects``-row node has today.

    A projects row is a ``project`` or a ``catalog_item`` by its ``publishable`` flag now, not by the
    edge that first named it (a converted catalog item keeps old edges that say ``catalog_item``).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        refs: ``(kind, id)`` node references; only the ``project`` / ``catalog_item`` ones are read.

    Returns:
        ``{id: "project" | "catalog_item"}`` for each projects row still present.
    """
    project_ids = sorted({str(entity_id) for kind, entity_id in refs if kind in PROJECT_KINDS})
    if not project_ids:
        return {}
    return {
        str(row["id"]): "project" if row["publishable"] else "catalog_item"
        for row in db.execute_query(
            "SELECT id::text AS id, publishable FROM apiome.projects "
            "WHERE tenant_id = %s::uuid AND id = ANY(%s::uuid[])",
            (tenant_id, project_ids),
        )
    }


@dataclass(frozen=True)
class NodePage:
    """One page of the tenant-wide entity search.

    Attributes:
        entities: ``{kind, id, name, slug, owner, in_count, out_count, stale_count}``.
        total: How many entities match.
        truncated: True when more match than this page holds.
    """

    entities: List[Dict[str, Any]]
    total: int
    truncated: bool


def search_entities(
    db: Any,
    tenant_id: str,
    *,
    query: Optional[str] = None,
    kinds: Sequence[str] = (),
    team: Optional[str] = None,
    provenances: Sequence[str] = (),
    limit: int = 200,
    offset: int = 0,
) -> NodePage:
    """The entities that have edges, for the tenant-wide graph page.

    Each entity appears once (a project and a catalog item are one row), with how many current
    edges point in and out and how many are stale. Ordered by total edges, most connected first.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        query: Case-insensitive substring of the name or slug.
        kinds: Only these node kinds (``project`` and ``catalog_item`` are both honoured).
        team: Only entities whose owner team (the confirmed one, else the oldest suggestion) has
            this slug.
        provenances: Only count edges of these provenances.
        limit: Page size, 1..:data:`MAX_SEARCH_LIMIT`.
        offset: Entities to skip.

    Returns:
        The page.

    Raises:
        GraphValidationError: ``graph-invalid`` for an unknown kind or provenance, or a bad limit.
    """
    bad = [k for k in kinds if k not in NODE_KINDS] + [p for p in provenances if p not in PROVENANCES]
    if bad:
        raise GraphValidationError("graph-invalid", f"unknown filter values: {', '.join(bad)}")
    if not 1 <= int(limit) <= MAX_SEARCH_LIMIT:
        raise GraphValidationError("graph-invalid", f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    params: List[Any] = [tenant_id, list(provenances or PROVENANCES)]
    rows = db.execute_query(
        """
        WITH ends AS (
            SELECT from_kind AS kind, from_id AS id, 0 AS ins, 1 AS outs, (stale_since IS NOT NULL)::int AS stale
            FROM apiome.catalog_edges WHERE tenant_id = %s::uuid AND provenance = ANY(%s::text[])
            UNION ALL
            SELECT to_kind, to_id, 1, 0, (stale_since IS NOT NULL)::int
            FROM apiome.catalog_edges WHERE tenant_id = %s::uuid AND provenance = ANY(%s::text[])
        )
        SELECT CASE WHEN min(kind) IN ('catalog_item', 'project') THEN max(kind) ELSE min(kind) END AS kind,
               id::text AS id, sum(ins)::int AS in_count, sum(outs)::int AS out_count,
               sum(stale)::int AS stale_count
        FROM ends
        GROUP BY id
        """,
        (tenant_id, params[1], tenant_id, params[1]),
    )
    refs = [(str(row["kind"]), str(row["id"])) for row in rows]
    info = node_labels_with_owners(db, tenant_id, refs)
    current = current_node_kinds(db, tenant_id, refs)
    needle = (query or "").strip().lower()
    wanted_kinds = set(kinds)
    entities: List[Dict[str, Any]] = []
    for row in rows:
        entity_id = str(row["id"])
        kind = current.get(entity_id, str(row["kind"]))
        item = info.get(entity_id, {})
        if wanted_kinds and kind not in wanted_kinds:
            continue
        if needle and needle not in f"{item.get('name') or ''} {item.get('slug') or ''}".lower():
            continue
        owner = item.get("owner")
        if team and (owner or {}).get("slug") != team:
            continue
        entities.append({
            "kind": kind, "id": entity_id, "name": item.get("name"), "slug": item.get("slug"), "owner": owner,
            "in_count": int(row["in_count"]), "out_count": int(row["out_count"]),
            "stale_count": int(row["stale_count"]),
        })
    entities.sort(key=lambda e: (-(e["in_count"] + e["out_count"]), str(e["name"] or e["slug"] or ""), e["id"]))
    start = max(0, int(offset))
    page = entities[start:start + int(limit)]
    return NodePage(entities=page, total=len(entities), truncated=start + len(page) < len(entities))
