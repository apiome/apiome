"""Runtime edges of the catalog graph — CDG-3.5 (#5970).

The CDG-3.1 graph knows what depends on what because someone said so (a contract, a declaration, a
conversion). The RDG-1.x usage index knows what **calls** what, once RDG-1.8 bindings attribute
traffic to a consumer. This module turns the second into ``runtime_calls`` edges of
``apiome.catalog_edges`` (V288), written beside the declared and derived ones and **never merged**
into them:

=================  ==============================================================================
Column             Value
=================  ==============================================================================
``from``           the consumer a binding attributed the calls to (a live CTG-4.1 consumer)
``to``             the project or catalog item that served them
``edge_kind``      ``runtime_calls``
``pointer``        the operation, as the classifier's pointer ``/paths/<escaped>/<method>``
``provenance``     ``runtime``
``source_ref``     ``usage:30d`` — the window the edge was observed in (:data:`SOURCE_REF`)
``evidence``       ``{calls, errors, last_seen_day, window_days, via, consumer_slug}`` — request
                   counts, the newest UTC day with a call, and which binding kinds attributed them
=================  ==============================================================================

**Same life cycle as a derived edge.** :func:`materialize_runtime_on_cursor` upserts every edge the
window's ``usage_daily`` rows produce, stamps ``stale_since`` on runtime edges the window no longer
produces (a consumer that stopped calling an operation, a deleted binding whose calls aged out), and
purges edges stale for :data:`app.catalog_graph.STALE_PURGE_DAYS` days. A stale runtime edge is still
listed (``stale: true``) and is skipped by the blast radius, like every stale edge.

**When.** The usage sweep (:mod:`app.usage_sweep`) re-derives the edges of every tenant with usage
right after it rolls the days up, so the edges follow ``usage_daily``: a call shows up as an edge
after the rollup that counts it.

Traffic no binding attributes produces **no** edge: there is no consumer to draw it from. Its client
keys are what :mod:`app.consumer_suggestions` lists as Suggested consumers instead.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .catalog_graph import STALE_PURGE_DAYS

__all__ = [
    "EDGE_KIND",
    "PROVENANCE",
    "SOURCE_REF",
    "WINDOW_DAYS",
    "materialize_runtime",
    "materialize_runtime_on_cursor",
    "refresh_runtime_edges",
]

_logger = logging.getLogger(__name__)

#: How many UTC days of ``usage_daily`` one edge summarises (today included).
WINDOW_DAYS = 30

#: The ``source_ref`` of every runtime edge: the observation window.
SOURCE_REF = f"usage:{WINDOW_DAYS}d"

EDGE_KIND = "runtime_calls"
PROVENANCE = "runtime"

#: The edges the window's attributed usage produces, for tenant ``%(tenant)s``. A binding is joined
#: whether or not it was deleted since (its history stays attributed, as RDG-1.8 promises); its
#: consumer and the project must still be live.
_RUNTIME_SQL = """
    SELECT 'consumer' AS from_kind, c.id AS from_id,
           CASE WHEN p.publishable THEN 'project' ELSE 'catalog_item' END AS to_kind, p.id AS to_id,
           d.operation_key AS pointer,
           jsonb_build_object(
               'calls', sum(d.calls),
               'errors', sum(d.errors),
               'last_seen_day', max(d.day),
               'window_days', %(window)s,
               'via', to_jsonb(array_agg(DISTINCT b.kind ORDER BY b.kind)),
               'consumer_slug', c.slug
           ) AS evidence
    FROM apiome.usage_daily d
    JOIN apiome.usage_consumer_binding b ON b.id = d.consumer_binding_id
    JOIN apiome.consumer c ON c.id = b.consumer_id AND c.deleted_at IS NULL
    JOIN apiome.projects p ON p.id = d.project_id AND p.deleted_at IS NULL
    WHERE d.tenant_id = %(tenant)s::uuid
      AND d.day > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - %(window)s
    GROUP BY c.id, c.slug, p.id, p.publishable, d.operation_key
    HAVING sum(d.calls) > 0
"""


def materialize_runtime_on_cursor(cursor: Any, tenant_id: str) -> Dict[str, int]:
    """Re-derive one tenant's runtime edges on an open cursor (the caller's transaction).

    Args:
        cursor: An open cursor; nothing is committed here.
        tenant_id: The tenant.

    Returns:
        ``{"current": n, "staled": n, "purged": n}``.
    """
    params = {"tenant": tenant_id, "window": WINDOW_DAYS, "source_ref": SOURCE_REF, "days": STALE_PURGE_DAYS}
    cursor.execute(
        f"""
        INSERT INTO apiome.catalog_edges
            (tenant_id, from_kind, from_id, to_kind, to_id, edge_kind, pointer, provenance, source_ref,
             evidence)
        SELECT %(tenant)s::uuid, r.from_kind, r.from_id, r.to_kind, r.to_id, '{EDGE_KIND}', r.pointer,
               '{PROVENANCE}', %(source_ref)s, r.evidence
        FROM ({_RUNTIME_SQL}) AS r
        ON CONFLICT ON CONSTRAINT catalog_edges_identity_key DO UPDATE
           SET last_seen_at = CURRENT_TIMESTAMP,
               stale_since = NULL,
               evidence = EXCLUDED.evidence
        """,
        params,
    )
    current = int(cursor.rowcount or 0)
    # Within one transaction CURRENT_TIMESTAMP is fixed: "not touched above" is "last_seen_at older".
    cursor.execute(
        f"""
        UPDATE apiome.catalog_edges
           SET stale_since = CURRENT_TIMESTAMP
         WHERE tenant_id = %(tenant)s::uuid AND provenance = '{PROVENANCE}'
           AND last_seen_at < CURRENT_TIMESTAMP AND stale_since IS NULL
        """,
        params,
    )
    staled = int(cursor.rowcount or 0)
    cursor.execute(
        f"""
        DELETE FROM apiome.catalog_edges
         WHERE tenant_id = %(tenant)s::uuid AND provenance = '{PROVENANCE}'
           AND stale_since < CURRENT_TIMESTAMP - make_interval(days => %(days)s)
        """,
        params,
    )
    return {"current": current, "staled": staled, "purged": int(cursor.rowcount or 0)}


def materialize_runtime(db: Any, tenant_id: str) -> Dict[str, int]:
    """Re-derive one tenant's runtime edges in a transaction of its own.

    Args:
        db: Database handle.
        tenant_id: The tenant.

    Returns:
        The counts (see :func:`materialize_runtime_on_cursor`).
    """
    return db._guarded_tx(lambda cursor: materialize_runtime_on_cursor(cursor, tenant_id))


def refresh_runtime_edges(db: Any) -> Dict[str, int]:
    """Re-derive the runtime edges of every tenant that has usage in the window or runtime edges.

    A tenant with runtime edges but no usage left in the window is included too, so its edges go
    stale (and are later purged) instead of lingering as current. One tenant's failure never stops
    the rest.

    Args:
        db: Database handle (the usage sweep's dedicated one).

    Returns:
        ``{"tenants": refreshed, "failed": failures}``.
    """
    rows = db.execute_query(
        """
        SELECT DISTINCT tenant_id::text AS id FROM apiome.usage_daily
         WHERE day > (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date - %s AND consumer_binding_id IS NOT NULL
        UNION
        SELECT DISTINCT tenant_id::text FROM apiome.catalog_edges WHERE provenance = %s
        ORDER BY 1
        """,
        (WINDOW_DAYS, PROVENANCE),
    )
    refreshed = failed = 0
    tenants: List[str] = [str(row["id"]) for row in rows or []]
    for tenant_id in tenants:
        try:
            counts = materialize_runtime(db, tenant_id)
            refreshed += 1
            _logger.info("runtime edges materialized tenant_id=%s counts=%s", tenant_id, counts)
        except Exception:
            failed += 1
            _logger.warning("runtime edges failed tenant_id=%s", tenant_id, exc_info=True)
    return {"tenants": refreshed, "failed": failed}
