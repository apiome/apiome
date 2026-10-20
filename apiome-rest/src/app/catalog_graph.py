"""The catalog graph — derived edges and their materializer (CDG-3.1, #5966).

Six sources in the schema already say how catalog entities relate; this module turns them into rows
of ``apiome.catalog_edges`` (apiome-db V288), one **family** per source:

=================  ==========================================  ========================================
Family             Edge                                        Source rows
=================  ==========================================  ========================================
``consumes``       consumer → project / catalog item, one      the consumer's *current* contract
                   edge per pointer it declares                (``consumer_contract.surface_pointers``)
``converted_from`` project → the catalog item it was           ``conversion_provenance`` (the latest
                   converted from                              conversion of each pair)
``identity_of``    project / catalog item → identity group     ``api_identity_members``
``built_from``     MCP endpoint → MCP source                   ``mcp_endpoint_sources`` (not retired)
``deployed_on``    project / catalog item → gateway config      ``catalog_connector_items`` (imported or
                   (CDG-5.3: the connector's environment)     discovered) × ``catalog_gateway_configs``
``served_by``      project / catalog item → repository         ``repository_import_spec`` and live
                                                               ``draft_repository_bindings``
=================  ==========================================  ========================================

A projects row is a ``project`` when it is publishable and a ``catalog_item`` otherwise.

**Materializing is idempotent.** :func:`materialize_on_cursor` re-derives a family for one tenant in a
single pass of three statements: upsert every edge the sources say exists (``last_seen_at`` now,
``stale_since`` cleared), stamp ``stale_since`` on derived edges of the family the sources no longer
produce, and purge edges stale for :data:`STALE_PURGE_DAYS` days. Running it twice leaves the same
edges. Producers in apiome-rest call it inside their own write transaction for the family they
touch (through ``Database._materialize_graph``); a nightly sweep re-derives every family for every
tenant, which also covers the repository imports apiome-ui writes.

**Stale before gone.** A revoked consumer's ``consumes`` edges keep their old ``last_seen_at`` and gain
``stale_since``; the read reports them as ``stale: true`` for 30 days before they are purged, so a
vanished dependency is visible first.

Only ``derived`` edges are touched here. ``declared`` (CDG-3.2) and ``runtime`` (RDG-1.x) edges belong
to their producers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "EDGE_KINDS",
    "FAMILIES",
    "MAX_READ_LIMIT",
    "NODE_KINDS",
    "PROVENANCES",
    "STALE_PURGE_DAYS",
    "EdgePage",
    "GraphValidationError",
    "list_edges",
    "materialize",
    "materialize_on_cursor",
    "SWEEP_INTERVAL_SECONDS",
    "sweep",
]

_logger = logging.getLogger(__name__)

#: Every node kind an edge end can be.
NODE_KINDS = (
    "project",
    "catalog_item",
    "mcp_endpoint",
    "consumer",
    "connector",
    "repository",
    "mcp_source",
    "identity_group",
    # CDG-5.3 (V298): one (connector, environment) — what `deployed_on` edges point at.
    "gateway_config",
    # CDG-5.5 (V299): an accepted Backstage or Compass component; declares its own edges.
    "component",
)

EDGE_KINDS = (
    "depends_on",
    "consumes",
    "served_by",
    "deployed_on",
    "built_from",
    "converted_from",
    "identity_of",
    "runtime_calls",
)

PROVENANCES = ("declared", "derived", "runtime")

#: Days a stale derived edge is kept before it is purged.
STALE_PURGE_DAYS = 30

#: Largest page a read returns.
MAX_READ_LIMIT = 500

#: How often the repair sweep re-derives every family for every tenant (nightly).
SWEEP_INTERVAL_SECONDS = 24 * 60 * 60

#: The session advisory-lock key that keeps two replicas from sweeping at once.
_SWEEP_LOCK_KEY = "catalog-graph-sweep"

#: The kind of a projects row aliased ``p``.
_PROJECT_KIND = "CASE WHEN p.publishable THEN 'project' ELSE 'catalog_item' END"

#: One SELECT per family producing ``from_kind, from_id, to_kind, to_id, pointer, source_ref,
#: evidence`` for tenant ``%(tenant)s``. Every query reads only live source rows; a row that is gone
#: simply stops producing its edge.
_FAMILY_SQL: Dict[str, str] = {
    "consumes": f"""
        SELECT DISTINCT 'consumer' AS from_kind, c.id AS from_id,
               {_PROJECT_KIND} AS to_kind, p.id AS to_id,
               ptr AS pointer, 'consumer_contract:' || cc.id::text AS source_ref,
               jsonb_build_object('revision', cc.revision, 'consumer_slug', c.slug) AS evidence
        FROM apiome.consumer_contract cc
        JOIN apiome.consumer c ON c.id = cc.consumer_id AND c.deleted_at IS NULL
        JOIN apiome.projects p ON p.id = cc.project_id AND p.deleted_at IS NULL
        CROSS JOIN LATERAL unnest(cc.surface_pointers) AS ptr
        WHERE cc.tenant_id = %(tenant)s::uuid AND cc.is_current
    """,
    "converted_from": f"""
        SELECT {_PROJECT_KIND.replace('p.', 't.')} AS from_kind, t.id AS from_id,
               {_PROJECT_KIND} AS to_kind, p.id AS to_id,
               NULL::text AS pointer, 'conversion:' || cp.id::text AS source_ref,
               jsonb_strip_nulls(jsonb_build_object(
                   'fidelity_grade', cp.fidelity_grade, 'target_version', cp.target_version_label
               )) AS evidence
        FROM (
            SELECT DISTINCT ON (source_project_id, target_project_id) *
            FROM apiome.conversion_provenance
            WHERE tenant_id = %(tenant)s::uuid AND target_project_id IS NOT NULL
            ORDER BY source_project_id, target_project_id, created_at DESC, id DESC
        ) cp
        JOIN apiome.projects p ON p.id = cp.source_project_id AND p.deleted_at IS NULL
        JOIN apiome.projects t ON t.id = cp.target_project_id AND t.deleted_at IS NULL
    """,
    "identity_of": f"""
        SELECT {_PROJECT_KIND} AS from_kind, p.id AS from_id,
               'identity_group' AS to_kind, m.group_id AS to_id,
               NULL::text AS pointer, 'identity_member:' || m.id::text AS source_ref,
               jsonb_strip_nulls(jsonb_build_object('link_source', m.link_source)) AS evidence
        FROM apiome.api_identity_members m
        JOIN apiome.projects p ON p.id = m.project_id AND p.deleted_at IS NULL
        WHERE m.tenant_id = %(tenant)s::uuid
    """,
    "built_from": """
        SELECT 'mcp_endpoint' AS from_kind, s.endpoint_id AS from_id,
               'mcp_source' AS to_kind, s.id AS to_id,
               NULL::text AS pointer, 'mcp_source:' || s.id::text AS source_ref,
               jsonb_strip_nulls(jsonb_build_object(
                   'source_kind', s.source_kind, 'locator', left(s.locator, 300),
                   'purl', left(s.purl, 300), 'revision', left(s.revision, 120)
               )) AS evidence
        FROM apiome.mcp_endpoint_sources s
        JOIN apiome.mcp_endpoints e ON e.id = s.endpoint_id AND e.deleted_at IS NULL
        WHERE s.tenant_id = %(tenant)s::uuid AND s.retired_at IS NULL
    """,
    # CDG-5.3: an API is deployed on the gateway config of the (connector, environment) serving it.
    "deployed_on": f"""
        SELECT {_PROJECT_KIND} AS from_kind, p.id AS from_id,
               'gateway_config' AS to_kind, g.id AS to_id,
               NULL::text AS pointer, 'connector_item:' || i.id::text AS source_ref,
               jsonb_strip_nulls(jsonb_build_object(
                   'remote_id', left(i.remote_id, 200), 'environment', i.environment,
                   'revision', left(i.remote_revision, 120), 'connector_id', k.id::text
               )) AS evidence
        FROM apiome.catalog_connector_items i
        JOIN apiome.catalog_connectors k ON k.id = i.connector_id AND k.deleted_at IS NULL
        JOIN apiome.catalog_gateway_configs g
             ON g.connector_id = i.connector_id AND g.environment = COALESCE(i.environment, '')
            AND g.deleted_at IS NULL
        JOIN apiome.projects p ON p.id = i.project_id AND p.deleted_at IS NULL
        WHERE k.tenant_id = %(tenant)s::uuid AND i.status IN ('imported', 'discovered')
    """,
    "served_by": f"""
        SELECT {_PROJECT_KIND} AS from_kind, p.id AS from_id,
               'repository' AS to_kind, r.id AS to_id,
               NULL::text AS pointer, 'import_spec:' || s.id::text AS source_ref,
               jsonb_build_object('branch', s.branch, 'path', left(s.path, 400)) AS evidence
        FROM apiome.repository_import_spec s
        JOIN apiome.tenant_repositories r ON r.id = s.repository_id AND r.deleted_at IS NULL
        JOIN apiome.projects p ON p.id = s.project_id AND p.deleted_at IS NULL
        WHERE s.tenant_id = %(tenant)s::uuid
        UNION ALL
        SELECT {_PROJECT_KIND}, p.id, 'repository', r.id,
               NULL::text, 'binding:' || b.id::text,
               jsonb_strip_nulls(jsonb_build_object('ref', b.ref, 'path', left(b.path, 400)))
        FROM apiome.draft_repository_bindings b
        JOIN apiome.tenant_repositories r ON r.id = b.repository_id AND r.deleted_at IS NULL
        JOIN apiome.projects p ON p.id = b.project_id AND p.deleted_at IS NULL
        WHERE b.tenant_id = %(tenant)s::uuid AND b.released_at IS NULL
    """,
}

#: The derived families, in materialization order.
FAMILIES: Tuple[str, ...] = tuple(_FAMILY_SQL)


class GraphValidationError(ValueError):
    """A malformed graph read, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _families(families: Optional[Iterable[str]]) -> List[str]:
    """Validate and order the families to materialize (``None`` means all)."""
    if families is None:
        return list(FAMILIES)
    wanted = list(dict.fromkeys(families))
    unknown = [family for family in wanted if family not in _FAMILY_SQL]
    if unknown:
        raise ValueError(f"unknown edge families: {', '.join(unknown)}")
    return wanted


def materialize_on_cursor(
    cursor: Any, tenant_id: str, families: Optional[Iterable[str]] = None
) -> Dict[str, Dict[str, int]]:
    """Re-derive edge families for one tenant on an open cursor (the caller's transaction).

    For each family: upsert the edges its source rows produce, mark the family's derived edges that
    were not produced as stale, and purge edges stale for :data:`STALE_PURGE_DAYS` days.

    Args:
        cursor: An open cursor; nothing is committed here.
        tenant_id: The tenant.
        families: The families to re-derive; ``None`` for all of them.

    Returns:
        ``{family: {"current": n, "staled": n, "purged": n}}``.
    """
    counts: Dict[str, Dict[str, int]] = {}
    for family in _families(families):
        cursor.execute(
            f"""
            INSERT INTO apiome.catalog_edges
                (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance,
                 source_ref, evidence)
            SELECT %(tenant)s::uuid, d.from_kind, d.from_id, d.to_kind, d.to_id, %(family)s,
                   d.pointer, 'derived', d.source_ref, d.evidence
            FROM ({_FAMILY_SQL[family]}) AS d
            ON CONFLICT ON CONSTRAINT catalog_edges_identity_key DO UPDATE
               SET last_seen_at = CURRENT_TIMESTAMP,
                   stale_since = NULL,
                   evidence = EXCLUDED.evidence
            """,
            {"tenant": tenant_id, "family": family},
        )
        current = int(cursor.rowcount or 0)
        # Anything of this family the sources did not just produce is stale from now on. Within one
        # transaction CURRENT_TIMESTAMP is fixed, so "not touched above" is "last_seen_at older".
        cursor.execute(
            """
            UPDATE apiome.catalog_edges
               SET stale_since = CURRENT_TIMESTAMP
             WHERE tenant_id = %(tenant)s::uuid AND provenance = 'derived' AND edge_kind = %(family)s
               AND last_seen_at < CURRENT_TIMESTAMP AND stale_since IS NULL
            """,
            {"tenant": tenant_id, "family": family},
        )
        staled = int(cursor.rowcount or 0)
        cursor.execute(
            """
            DELETE FROM apiome.catalog_edges
             WHERE tenant_id = %(tenant)s::uuid AND provenance = 'derived' AND edge_kind = %(family)s
               AND stale_since < CURRENT_TIMESTAMP - make_interval(days => %(days)s)
            """,
            {"tenant": tenant_id, "family": family, "days": STALE_PURGE_DAYS},
        )
        counts[family] = {"current": current, "staled": staled, "purged": int(cursor.rowcount or 0)}
    return counts


def materialize(
    db: Any, tenant_id: str, trigger: str, families: Optional[Iterable[str]] = None
) -> Dict[str, Dict[str, int]]:
    """Re-derive edge families for one tenant in a transaction of its own.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        trigger: Why (``sweep``, ``connector_sync``, …), for the log line.
        families: The families; ``None`` for all.

    Returns:
        The per-family counts (see :func:`materialize_on_cursor`).
    """
    counts = db._guarded_tx(lambda cursor: materialize_on_cursor(cursor, tenant_id, families))
    _logger.info("catalog graph materialized tenant_id=%s trigger=%s counts=%s", tenant_id, trigger, counts)
    return counts


def sweep(db: Any) -> Dict[str, int]:
    """Re-derive every family for every live tenant: the nightly repair pass.

    It catches what the producers' hooks miss (a hook that failed, repository imports written by
    apiome-ui) and moves stale edges toward their purge. It holds a session advisory lock on
    ``db``'s connection, so a second replica's sweep skips instead of doing the same work, and one
    tenant's failure never stops the rest.

    Args:
        db: A dedicated database handle (the lock lives on its connection).

    Returns:
        ``{"tenants": swept, "failed": failures}``; both 0 when another sweep holds the lock.
    """
    locked = db.execute_query("SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (_SWEEP_LOCK_KEY,))
    if not (locked and locked[0].get("locked")):
        return {"tenants": 0, "failed": 0}
    swept = failed = 0
    try:
        rows = db.execute_query("SELECT id::text AS id FROM apiome.tenants WHERE deleted_at IS NULL ORDER BY id")
        for row in rows or []:
            try:
                materialize(db, str(row["id"]), "sweep")
                swept += 1
            except Exception:
                failed += 1
                _logger.warning("catalog graph sweep failed tenant_id=%s", row.get("id"), exc_info=True)
    finally:
        db.execute_query("SELECT pg_advisory_unlock(hashtext(%s)) AS unlocked", (_SWEEP_LOCK_KEY,))
    _logger.info("catalog graph sweep finished tenants=%s failed=%s", swept, failed)
    return {"tenants": swept, "failed": failed}


# ---------------------------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EdgePage:
    """One page of edges.

    Attributes:
        edges: The edges, each with ``stale`` set.
        total: How many edges match.
        truncated: True when more edges match than were returned.
    """

    edges: List[Dict[str, Any]]
    total: int
    truncated: bool


def _iso(value: Any) -> Optional[str]:
    """ISO-8601 for a timestamp."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def list_edges(
    db: Any,
    tenant_id: str,
    kind: str,
    entity_id: str,
    *,
    direction: str = "out",
    edge_kinds: Sequence[str] = (),
    provenances: Sequence[str] = (),
    limit: int = 100,
    offset: int = 0,
) -> EdgePage:
    """One entity's edges, bounded: current edges first, then stale, in a stable order.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kind: The entity's node kind. A projects row may be named ``project`` or ``catalog_item``.
        entity_id: The entity.
        direction: ``out`` (edges from it) or ``in`` (edges to it).
        edge_kinds: Only these edge kinds (empty for all).
        provenances: Only these provenances (empty for all).
        limit: Page size, 1..:data:`MAX_READ_LIMIT`.
        offset: Rows to skip.

    Returns:
        The page; ``truncated`` says whether more match.

    Raises:
        GraphValidationError: ``graph-invalid`` for an unknown kind, direction, edge kind or
            provenance, or a limit outside the bounds.
    """
    if kind not in NODE_KINDS:
        raise GraphValidationError("graph-invalid", f"unknown node kind '{kind}'")
    if direction not in ("in", "out"):
        raise GraphValidationError("graph-invalid", "direction must be 'in' or 'out'")
    bad = [k for k in edge_kinds if k not in EDGE_KINDS] + [p for p in provenances if p not in PROVENANCES]
    if bad:
        raise GraphValidationError("graph-invalid", f"unknown filter values: {', '.join(bad)}")
    if not 1 <= int(limit) <= MAX_READ_LIMIT:
        raise GraphValidationError("graph-invalid", f"limit must be between 1 and {MAX_READ_LIMIT}")

    side_kind, side_id = ("from_kind", "from_id") if direction == "out" else ("to_kind", "to_id")
    kinds = ["project", "catalog_item"] if kind in ("project", "catalog_item") else [kind]
    clauses = ["tenant_id = %s::uuid", f"{side_kind} = ANY(%s::text[])", f"{side_id} = %s::uuid"]
    params: List[Any] = [tenant_id, kinds, entity_id]
    if edge_kinds:
        clauses.append("edge_kind = ANY(%s::text[])")
        params.append(list(edge_kinds))
    if provenances:
        clauses.append("provenance = ANY(%s::text[])")
        params.append(list(provenances))
    rows = db.execute_query(
        f"""
        SELECT id::text AS id, from_kind, from_id::text AS from_id, to_kind, to_id::text AS to_id,
               edge_kind, pointer, provenance, source_ref, evidence,
               first_seen_at, last_seen_at, stale_since,
               count(*) OVER () AS total
        FROM apiome.catalog_edges
        WHERE {' AND '.join(clauses)}
        ORDER BY (stale_since IS NOT NULL), edge_kind, to_kind, to_id, from_id, pointer NULLS FIRST, id
        LIMIT %s OFFSET %s
        """,
        tuple(params + [int(limit), max(0, int(offset))]),
    )
    if rows:
        total = int(rows[0]["total"])
    elif offset > 0:
        # Paged past the end: the window count is empty, so count separately.
        counted = db.execute_query(
            f"SELECT count(*) AS total FROM apiome.catalog_edges WHERE {' AND '.join(clauses)}", tuple(params)
        )
        total = int(counted[0]["total"]) if counted else 0
    else:
        total = 0
    edges = []
    for row in rows:
        edge = {key: value for key, value in dict(row).items() if key != "total"}
        for key in ("first_seen_at", "last_seen_at", "stale_since"):
            edge[key] = _iso(edge.get(key))
        edge["stale"] = edge["stale_since"] is not None
        edges.append(edge)
    return EdgePage(edges=edges, total=total, truncated=max(0, int(offset)) + len(edges) < total)

