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
``includes``       API product → project / catalog item / MCP  ``api_product_members`` of live products
                   endpoint (APX-1.1: what the product         (apiome-db V387)
                   bundles)
=================  ==========================================  ========================================

A projects row is a ``project`` when it is publishable and a ``catalog_item`` otherwise.

**Materializing is idempotent.** :func:`materialize_on_cursor` re-derives a family for one tenant in
two statements: one derives the edges the sources say exist, upserts the new and changed ones
(``stale_since`` cleared) and stamps ``stale_since`` on derived edges of the family the sources no
longer produce; the other purges edges stale for :data:`STALE_PURGE_DAYS` days. An unchanged edge is
not rewritten (DBP-1.18, #7201). Running it twice leaves the same edges. Producers in apiome-rest
call it inside their own write transaction for the family they touch, **scoped to the node they
changed** (:class:`GraphScope`, through ``Database._materialize_graph``), so one consumer's contract
write touches only that consumer's edges. A nightly sweep re-derives every family for every tenant —
which also covers the repository imports apiome-ui writes — and refreshes ``last_seen_at`` on every
current edge, so ``last_seen_at`` is "confirmed by the last sweep or changed since".

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

from .keyset_columns import (
    SortColumn,
    decode_columns_cursor,
    encode_columns_cursor,
    keyset_after_columns,
    order_by_sql,
)
from .keyset_pagination import MAX_OFFSET, capped_count_sql

__all__ = [
    "EDGE_KINDS",
    "EDGE_SORT_COLUMNS",
    "FAMILIES",
    "MAX_READ_LIMIT",
    "NODE_KINDS",
    "PROVENANCES",
    "decode_edge_cursor",
    "STALE_PURGE_DAYS",
    "EdgePage",
    "GraphScope",
    "GraphValidationError",
    "PROJECT_NODE_KINDS",
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
    # APX-1.1 (V387): an API product; its `includes` edges point at what it bundles.
    "api_product",
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
    # APX-1.1 (V387): an API product bundles a project, catalog item or MCP server.
    "includes",
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
    # APX-1.1: a live product includes each of its members. One edge per member row, so a product
    # that bundles a project twice (two environments, two version ranges) has two edges.
    "includes": f"""
        SELECT 'api_product' AS from_kind, ap.id AS from_id,
               {_PROJECT_KIND} AS to_kind, p.id AS to_id,
               NULL::text AS pointer, 'api_product_member:' || m.id::text AS source_ref,
               jsonb_strip_nulls(jsonb_build_object(
                   'member_kind', m.member_kind, 'version_selector', m.version_selector,
                   'environment', m.environment, 'product_slug', ap.slug
               )) AS evidence
        FROM apiome.api_product_members m
        JOIN apiome.api_products ap ON ap.id = m.product_id AND ap.deleted_at IS NULL
        JOIN apiome.projects p ON p.id = m.member_ref AND p.tenant_id = m.tenant_id AND p.deleted_at IS NULL
        WHERE m.tenant_id = %(tenant)s::uuid AND m.member_kind <> 'mcp_server'
        UNION ALL
        SELECT 'api_product', ap.id, 'mcp_endpoint', e.id,
               NULL::text, 'api_product_member:' || m.id::text,
               jsonb_strip_nulls(jsonb_build_object(
                   'member_kind', m.member_kind, 'environment', m.environment, 'product_slug', ap.slug
               ))
        FROM apiome.api_product_members m
        JOIN apiome.api_products ap ON ap.id = m.product_id AND ap.deleted_at IS NULL
        JOIN apiome.mcp_endpoints e ON e.id = m.member_ref AND e.tenant_id = m.tenant_id AND e.deleted_at IS NULL
        WHERE m.tenant_id = %(tenant)s::uuid AND m.member_kind = 'mcp_server'
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


#: Node kinds a projects row can be (see :data:`_PROJECT_KIND`).
PROJECT_NODE_KINDS: Tuple[str, ...] = ("project", "catalog_item")


@dataclass(frozen=True)
class GraphScope:
    """One node whose edges a write can change: the scope of an in-transaction re-derivation.

    A producer that changes one source row (one consumer's contract, one project's binding, one
    repository) re-derives only the edges that start (``end="from"``) or end (``end="to"``) at
    the node it touched, instead of the tenant's whole family (DBP-1.18, #7201).

    Attributes:
        end: ``from`` or ``to`` — which end of the edge the node is.
        kinds: The node kinds it may have (a projects row is a ``project`` or a ``catalog_item``).
        node_id: The node's id.
    """

    end: str
    kinds: Tuple[str, ...]
    node_id: str

    def __post_init__(self) -> None:
        if self.end not in ("from", "to"):
            raise ValueError(f"unknown graph scope end: {self.end!r}")
        unknown = [kind for kind in self.kinds if kind not in NODE_KINDS]
        if not self.kinds or unknown:
            raise ValueError(f"unknown graph scope kinds: {self.kinds!r}")

    @classmethod
    def consumer(cls, consumer_id: str) -> "GraphScope":
        """Edges a consumer declares (``consumes``)."""
        return cls("from", ("consumer",), str(consumer_id))

    @classmethod
    def project(cls, project_id: str) -> "GraphScope":
        """Edges that start at a project or catalog item (``served_by``, ``converted_from`` …)."""
        return cls("from", PROJECT_NODE_KINDS, str(project_id))

    @classmethod
    def api_product(cls, product_id: str) -> "GraphScope":
        """Edges an API product's members produce (``includes``)."""
        return cls("from", ("api_product",), str(product_id))

    @classmethod
    def repository(cls, repository_id: str) -> "GraphScope":
        """Edges that point at a repository (``served_by``)."""
        return cls("to", ("repository",), str(repository_id))


def materialize_on_cursor(
    cursor: Any,
    tenant_id: str,
    families: Optional[Iterable[str]] = None,
    *,
    scope: Optional[GraphScope] = None,
    confirm_all: bool = False,
) -> Dict[str, Dict[str, int]]:
    """Re-derive edge families for one tenant on an open cursor (the caller's transaction).

    For each family one statement derives the edges its source rows produce, upserts them, and
    marks the family's derived edges that were not produced as stale; a second purges edges stale
    for :data:`STALE_PURGE_DAYS` days.

    **Only changed edges are written** (DBP-1.18, #7201). An existing edge is updated only when it
    was stale or its evidence changed (``IS DISTINCT FROM``), so re-deriving an unchanged family
    writes nothing; ``confirm_all`` also refreshes ``last_seen_at`` on every current edge, which the
    nightly sweep does. Stale edges are found by comparing with the derived set, not by
    ``last_seen_at``.

    **Scoped.** With ``scope`` only the edges at that node are derived, compared and staled, so a
    producer's write touches only its own edges.

    Args:
        cursor: An open cursor; nothing is committed here.
        tenant_id: The tenant.
        families: The families to re-derive; ``None`` for all of them.
        scope: Re-derive only the edges at this node; ``None`` for the whole tenant.
        confirm_all: Refresh ``last_seen_at`` on every current edge (the nightly sweep).

    Returns:
        ``{family: {"current": n, "written": n, "staled": n, "purged": n}}`` — ``current`` counts
        the edges the sources produce, ``written`` the rows inserted or updated.
    """
    scope_sql = ""
    edge_scope_sql = ""
    params: Dict[str, Any] = {"tenant": tenant_id, "confirm": bool(confirm_all)}
    if scope is not None:
        scope_sql = f" WHERE d.{scope.end}_kind = ANY(%(scope_kinds)s) AND d.{scope.end}_id = %(scope_id)s::uuid"
        edge_scope_sql = f" AND e.{scope.end}_kind = ANY(%(scope_kinds)s) AND e.{scope.end}_id = %(scope_id)s::uuid"
        params.update({"scope_kinds": list(scope.kinds), "scope_id": scope.node_id})
    counts: Dict[str, Dict[str, int]] = {}
    for family in _families(families):
        cursor.execute(
            f"""
            WITH derived AS MATERIALIZED (
                SELECT d.from_kind, d.from_id, d.to_kind, d.to_id, d.pointer, d.source_ref, d.evidence
                FROM ({_FAMILY_SQL[family]}) AS d{scope_sql}
            ),
            written AS (
                INSERT INTO apiome.catalog_edges AS e
                    (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance,
                     source_ref, evidence)
                SELECT %(tenant)s::uuid, d.from_kind, d.from_id, d.to_kind, d.to_id, %(family)s,
                       d.pointer, 'derived', d.source_ref, d.evidence
                FROM derived d
                ON CONFLICT ON CONSTRAINT catalog_edges_identity_key DO UPDATE
                   SET last_seen_at = CURRENT_TIMESTAMP,
                       stale_since = NULL,
                       evidence = EXCLUDED.evidence
                 WHERE e.stale_since IS NOT NULL
                    OR e.evidence IS DISTINCT FROM EXCLUDED.evidence
                    OR %(confirm)s
                RETURNING 1
            ),
            staled AS (
                UPDATE apiome.catalog_edges e
                   SET stale_since = CURRENT_TIMESTAMP
                 WHERE e.tenant_id = %(tenant)s::uuid AND e.provenance = 'derived'
                   AND e.edge_kind = %(family)s AND e.stale_since IS NULL{edge_scope_sql}
                   AND NOT EXISTS (
                       SELECT 1 FROM derived d
                        WHERE d.from_kind = e.from_kind AND d.from_id = e.from_id
                          AND d.to_kind = e.to_kind AND d.to_id = e.to_id
                          AND d.pointer IS NOT DISTINCT FROM e.pointer
                          AND d.source_ref = e.source_ref
                   )
                RETURNING 1
            )
            SELECT (SELECT count(*) FROM derived) AS current,
                   (SELECT count(*) FROM written) AS written,
                   (SELECT count(*) FROM staled) AS staled
            """,
            {**params, "family": family},
        )
        row = cursor.fetchone() or {}
        cursor.execute(
            f"""
            DELETE FROM apiome.catalog_edges e
             WHERE e.tenant_id = %(tenant)s::uuid AND e.provenance = 'derived' AND e.edge_kind = %(family)s
               AND e.stale_since < CURRENT_TIMESTAMP - make_interval(days => %(days)s){edge_scope_sql}
            """,
            {**params, "family": family, "days": STALE_PURGE_DAYS},
        )
        counts[family] = {
            "current": int(_column(row, "current", 0)),
            "written": int(_column(row, "written", 1)),
            "staled": int(_column(row, "staled", 2)),
            "purged": int(cursor.rowcount or 0),
        }
    return counts


def _column(row: Any, name: str, index: int) -> Any:
    """Read one column of a dict-like or tuple row (cursor factories differ), ``0`` when absent."""
    if isinstance(row, dict):
        return row.get(name) or 0
    try:
        return row[index] or 0
    except (IndexError, KeyError, TypeError):
        return 0


def materialize(
    db: Any,
    tenant_id: str,
    trigger: str,
    families: Optional[Iterable[str]] = None,
    *,
    confirm_all: bool = False,
) -> Dict[str, Dict[str, int]]:
    """Re-derive edge families for one tenant in a transaction of its own.

    Args:
        db: Database handle.
        tenant_id: The tenant.
        trigger: Why (``sweep``, ``connector_sync``, …), for the log line.
        families: The families; ``None`` for all.
        confirm_all: Refresh ``last_seen_at`` on every current edge (the nightly sweep).

    Returns:
        The per-family counts (see :func:`materialize_on_cursor`).
    """
    counts = db._guarded_tx(
        lambda cursor: materialize_on_cursor(cursor, tenant_id, families, confirm_all=confirm_all)
    )
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
                materialize(db, str(row["id"]), "sweep", confirm_all=True)
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
        total: How many edges match, counted up to the cap; ``None`` unless the read asked for it.
        truncated: True when more edges match than were returned.
        next_cursor: The cursor of the next page; ``None`` on the last page.
    """

    edges: List[Dict[str, Any]]
    total: Optional[int]
    truncated: bool
    next_cursor: Optional[str] = None


#: The order an entity's edges are listed in: current before stale, then a stable order ending in
#: the edge id. The ids compare as text because the query projects them as text and ``ORDER BY``
#: resolves a bare name to the projected column.
EDGE_SORT_COLUMNS: Tuple[SortColumn, ...] = (
    SortColumn("(stale_since IS NOT NULL)", "bool", ("stale",)),
    SortColumn("edge_kind", "text", ("edge_kind",)),
    SortColumn("to_kind", "text", ("to_kind",)),
    SortColumn("to_id::text", "text", ("to_id",)),
    SortColumn("from_id::text", "text", ("from_id",)),
    SortColumn("pointer", "text", ("pointer",), nullable=True, nulls_first=True),
    SortColumn("id::text", "text", ("id",)),
)

#: Cursor tag of the edge list's one ordering.
_EDGE_CURSOR_TAG = "edges"


def decode_edge_cursor(token: Any) -> List[Any]:
    """Read an edge-list cursor.

    Args:
        token: The ``cursor`` query parameter.

    Returns:
        The sort values of the last edge already seen, one per :data:`EDGE_SORT_COLUMNS` column.

    Raises:
        InvalidCursor: The token is not one :func:`list_edges` issued.
    """
    return decode_columns_cursor(token, _EDGE_CURSOR_TAG, EDGE_SORT_COLUMNS)


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
    cursor: Optional[Sequence[Any]] = None,
    include_total: bool = False,
) -> EdgePage:
    """One entity's edges, bounded: current edges first, then stale, in a stable order.

    Reads one row more than the page to learn whether more match, so nothing is counted unless
    the caller asks for a total (#7196).

    Args:
        db: Database handle.
        tenant_id: The tenant.
        kind: The entity's node kind. A projects row may be named ``project`` or ``catalog_item``.
        entity_id: The entity.
        direction: ``out`` (edges from it) or ``in`` (edges to it).
        edge_kinds: Only these edge kinds (empty for all).
        provenances: Only these provenances (empty for all).
        limit: Page size, 1..:data:`MAX_READ_LIMIT`.
        offset: Rows to skip (deprecated; ignored when ``cursor`` is given).
        cursor: The values from :func:`decode_edge_cursor`; the page continues after that edge.
        include_total: Also count the matching edges, up to ``TOTAL_CAP``.

    Returns:
        The page; ``truncated`` says whether more match and ``next_cursor`` continues it.

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
    where_sql = " AND ".join(clauses)
    after_sql, after_params = keyset_after_columns(EDGE_SORT_COLUMNS, cursor)
    skip = 0 if cursor is not None else max(0, min(int(offset), MAX_OFFSET))
    rows = db.execute_query(
        f"""
        SELECT id::text AS id, from_kind, from_id::text AS from_id, to_kind, to_id::text AS to_id,
               edge_kind, pointer, provenance, source_ref, evidence,
               first_seen_at, last_seen_at, stale_since
        FROM apiome.catalog_edges
        WHERE {where_sql}{after_sql}
        ORDER BY {order_by_sql(EDGE_SORT_COLUMNS)}
        LIMIT %s OFFSET %s
        """,
        tuple(params + after_params + [int(limit) + 1, skip]),
    )
    total: Optional[int] = None
    if include_total:
        counted = db.execute_query(
            capped_count_sql(f"FROM apiome.catalog_edges WHERE {where_sql}"), tuple(params)
        )
        total = int(counted[0]["total"]) if counted else 0
    has_more = len(rows) > int(limit)
    edges = []
    for row in rows[: int(limit)]:
        edge = dict(row)
        for key in ("first_seen_at", "last_seen_at", "stale_since"):
            edge[key] = _iso(edge.get(key))
        edge["stale"] = edge["stale_since"] is not None
        edges.append(edge)
    next_cursor = (
        encode_columns_cursor(_EDGE_CURSOR_TAG, EDGE_SORT_COLUMNS, edges[-1])
        if has_more and edges
        else None
    )
    return EdgePage(edges=edges, total=total, truncated=has_more, next_cursor=next_cursor)
