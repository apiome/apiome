"""SQL for the revision-graph reads: closure, divergence, lineage and successors (DBP-1.14, #7197).

Every walk here is one recursive query that follows the ``versions`` primary key:

* ids stay ``uuid`` inside the recursion and are cast to text only in the final projection, so
  each step is an index probe on ``versions_pkey`` (a ``text`` join, or ``id::text = …``, cannot
  use it);
* a revision's two parent links are unpacked with ``CROSS JOIN LATERAL (VALUES …)`` so each link is
  its own primary-key probe, not one ``OR`` join filter evaluated against every candidate row.

Walks over the DAG (both parent links) use ``UNION``: one row per revision, so a diamond after a
merge is read once and a cycle in bad data ends the walk. Walks along a single pointer (the
import-snapshot lineage, the successor chain) carry an explicit depth guard instead.

The builders return SQL with positional ``%s`` placeholders; each docstring lists their order.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Columns of a :func:`revision_closure_cte` row (``apiome.versions`` columns of the same name).
CLOSURE_COLUMNS = (
    "id, project_id, parent_version_id, merge_parent_version_id, created_at, version_id, "
    "published, published_at"
)


def revision_closure_cte(name: str = "closure") -> str:
    """A recursive CTE body: the live revisions reachable from a set of starting revisions.

    The walk follows ``parent_version_id`` and ``merge_parent_version_id``; every row must be a
    live revision of a live project in the tenant. Use it after ``WITH RECURSIVE``.

    Placeholders, in order: the starting revision ids (a ``uuid[]``), the tenant id (seed), the
    tenant id (recursive step).

    Args:
        name: The CTE's name.

    Returns:
        ``<name> AS (…)`` with the columns in :data:`CLOSURE_COLUMNS`, starting revisions included.
    """
    cols = ", ".join(f"v.{c.strip()}" for c in CLOSURE_COLUMNS.split(","))
    return f"""
        {name} AS (
            SELECT {cols}
            FROM apiome.versions v
            JOIN apiome.projects p ON p.id = v.project_id
            WHERE v.id = ANY(%s::uuid[])
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
            UNION
            SELECT {cols}
            FROM {name} c
            CROSS JOIN LATERAL (VALUES (c.parent_version_id), (c.merge_parent_version_id)) AS edge(parent_id)
            JOIN apiome.versions v ON v.id = edge.parent_id
            JOIN apiome.projects p ON p.id = v.project_id
            WHERE p.tenant_id = %s
              AND v.deleted_at IS NULL
              AND p.deleted_at IS NULL
        )
    """


#: Every revision reachable from the starting ids (placeholders: ids, tenant, tenant).
REVISION_CLOSURE_SQL = f"""
    WITH RECURSIVE {revision_closure_cte()}
    SELECT id::text AS id,
           parent_version_id::text AS parent_version_id,
           merge_parent_version_id::text AS merge_parent_version_id,
           created_at,
           version_id
    FROM closure
"""

#: The newest published strict ancestor of a revision in a project.
#: Placeholders: ``[revision]``, tenant, tenant, revision, project.
PRIOR_PUBLISHED_BASELINE_SQL = f"""
    WITH RECURSIVE {revision_closure_cte()}
    SELECT c.id::text AS id
    FROM closure c
    WHERE c.id <> %s::uuid
      AND c.project_id = %s
      AND c.published = true
    ORDER BY c.published_at DESC NULLS LAST, c.created_at DESC
    LIMIT 1
"""

#: The revisions a transitive compatibility check compares against: the published ancestors,
#: newest first, or — only when there are none — the project's live revisions created before the
#: anchor. Placeholders: ``[revision]``, tenant, tenant, revision, project, limit, revision,
#: project, tenant, limit.
PRIOR_REVISIONS_FOR_TRANSITIVE_CHECK_SQL = f"""
    WITH RECURSIVE {revision_closure_cte()},
    published_ancestors AS (
        SELECT c.id, c.version_id,
               row_number() OVER (ORDER BY c.published_at DESC NULLS LAST, c.created_at DESC) AS rn
        FROM closure c
        WHERE c.id <> %s::uuid
          AND c.project_id = %s
          AND c.published = true
        ORDER BY rn
        LIMIT %s
    ),
    created_before AS (
        SELECT v.id, v.version_id,
               row_number() OVER (ORDER BY v.created_at DESC, v.id DESC) AS rn
        FROM apiome.versions v
        INNER JOIN apiome.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
        INNER JOIN apiome.versions anchor ON anchor.id = %s::uuid
        WHERE NOT EXISTS (SELECT 1 FROM published_ancestors)
          AND v.project_id = %s
          AND p.tenant_id = %s
          AND v.deleted_at IS NULL
          AND v.id <> anchor.id
          AND (v.created_at, v.id) < (anchor.created_at, anchor.id)
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT %s
    )
    SELECT id::text AS id, version_id
    FROM (
        SELECT 0 AS part, rn, id, version_id FROM published_ancestors
        UNION ALL
        SELECT 1 AS part, rn, id, version_id FROM created_before
    ) picked
    ORDER BY part, rn
"""


def _project_walk_cte(name: str, seed: str) -> str:
    """A recursive CTE body: the live revisions of one project reachable from ``seed``.

    Args:
        name: The CTE's name.
        seed: The non-recursive term: a ``SELECT v.id, v.parent_version_id,
            v.merge_parent_version_id FROM apiome.versions v …``.

    Returns:
        ``<name> AS (…)``; the recursive step's one placeholder is the project id.
    """
    return f"""
        {name} AS (
            {seed}
            UNION
            SELECT v.id, v.parent_version_id, v.merge_parent_version_id
            FROM {name} a
            CROSS JOIN LATERAL (VALUES (a.parent_version_id), (a.merge_parent_version_id)) AS edge(parent_id)
            JOIN apiome.versions v ON v.id = edge.parent_id
            WHERE v.project_id = %s
              AND v.deleted_at IS NULL
        )
    """


_TIP_SEED = """
            SELECT v.id, v.parent_version_id, v.merge_parent_version_id
            FROM apiome.versions v
            JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s::uuid
              AND v.project_id = %s
              AND p.tenant_id = %s
              AND v.deleted_at IS NULL
"""

_MERGE_BASE_SEED = """
            SELECT v.id, v.parent_version_id, v.merge_parent_version_id
            FROM apiome.versions v
            JOIN merge_base mb ON v.id = mb.id
"""


def _sample_json(name: str) -> str:
    """``json_agg`` of a sample CTE as ``[{revisionId, shortMessage}]``, newest first."""
    return f"""
        COALESCE(
            (
                SELECT json_agg(
                    json_build_object('revisionId', s.id::text, 'shortMessage', s.short_message)
                    ORDER BY s.created_at DESC, s.id DESC
                )
                FROM {name} s
            ),
            '[]'::json
        )
    """


#: Branch divergence: merge base, ahead / behind counts and samples, in one statement.
#: Placeholders: branch tip, project, tenant, project, against tip, project, tenant, project,
#: project (merge base), project (merge-base ancestors), project, limit, project, limit.
BRANCH_DIVERGENCE_SQL = f"""
    WITH RECURSIVE
    {_project_walk_cte("branch_ancestors", _TIP_SEED)},
    {_project_walk_cte("against_ancestors", _TIP_SEED)},
    merge_base AS (
        SELECT v.id, v.created_at
        FROM branch_ancestors ba
        JOIN against_ancestors aa ON aa.id = ba.id
        JOIN apiome.versions v ON v.id = ba.id
        WHERE v.project_id = %s
          AND v.deleted_at IS NULL
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT 1
    ),
    {_project_walk_cte("merge_base_ancestors", _MERGE_BASE_SEED)},
    ahead_set AS (
        SELECT ba.id FROM branch_ancestors ba
        WHERE NOT EXISTS (SELECT 1 FROM merge_base_ancestors m WHERE m.id = ba.id)
    ),
    behind_set AS (
        SELECT aa.id FROM against_ancestors aa
        WHERE NOT EXISTS (SELECT 1 FROM merge_base_ancestors m WHERE m.id = aa.id)
    ),
    ahead_sample AS (
        SELECT v.id, COALESCE(v.description, '') AS short_message, v.created_at
        FROM ahead_set a
        JOIN apiome.versions v ON v.id = a.id
        WHERE v.project_id = %s
          AND v.deleted_at IS NULL
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT %s
    ),
    behind_sample AS (
        SELECT v.id, COALESCE(v.description, '') AS short_message, v.created_at
        FROM behind_set b
        JOIN apiome.versions v ON v.id = b.id
        WHERE v.project_id = %s
          AND v.deleted_at IS NULL
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT %s
    )
    SELECT
        (SELECT mb.id::text FROM merge_base mb) AS merge_base_revision_id,
        (SELECT mb.created_at FROM merge_base mb) AS merge_base_created_at,
        (SELECT COUNT(*)::int FROM ahead_set) AS ahead_count,
        (SELECT COUNT(*)::int FROM behind_set) AS behind_count,
        {_sample_json("ahead_sample")} AS ahead_sample,
        {_sample_json("behind_sample")} AS behind_sample
"""

#: The ``parent_version_id`` chain from a revision up to the nearest one with an import snapshot,
#: with that snapshot. Placeholders: see :func:`import_snapshot_lineage_params`.
IMPORT_SNAPSHOT_LINEAGE_SQL = """
    WITH RECURSIVE walk AS (
        SELECT start.id, 1 AS depth, ARRAY[start.id] AS seen,
               EXISTS (
                   SELECT 1 FROM apiome.version_import_snapshots s
                   WHERE s.version_id = start.id AND s.tenant_id = %s
               ) AS has_snapshot
        FROM (SELECT %s::uuid AS id) start
        UNION ALL
        SELECT v.parent_version_id, w.depth + 1, w.seen || v.parent_version_id,
               EXISTS (
                   SELECT 1 FROM apiome.version_import_snapshots s
                   WHERE s.version_id = v.parent_version_id AND s.tenant_id = %s
               )
        FROM walk w
        JOIN apiome.versions v ON v.id = w.id
        JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = %s
        WHERE NOT w.has_snapshot
          AND v.parent_version_id IS NOT NULL
          AND NOT v.parent_version_id = ANY(w.seen)
          AND w.depth < %s
    )
    SELECT w.id::text AS chain_id, w.depth,
           s.version_id::text AS version_id, s.source_file, s.source_format, s.source_digest,
           s.canonical_document, s.created_at
    FROM walk w
    LEFT JOIN apiome.version_import_snapshots s
           ON w.has_snapshot AND s.version_id = w.id AND s.tenant_id = %s
    ORDER BY w.depth
"""


def import_snapshot_lineage_params(
    version_id: str, tenant_id: str, max_depth: int
) -> Tuple[Any, ...]:
    """Positional parameters for :data:`IMPORT_SNAPSHOT_LINEAGE_SQL`.

    Args:
        version_id: The starting revision (a uuid string).
        tenant_id: The tenant every snapshot and parent hop must belong to.
        max_depth: The most revisions the chain holds (the start included).
    """
    return (tenant_id, version_id, tenant_id, tenant_id, max_depth, tenant_id)


def lineage_from_rows(
    version_id: str, rows: Sequence[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Split :data:`IMPORT_SNAPSHOT_LINEAGE_SQL` rows into ``(snapshot_or_None, chain)``.

    Args:
        version_id: The starting revision as the caller passed it (kept verbatim as ``chain[0]``).
        rows: The walk, ordered by depth; only the last row can carry a snapshot.

    Returns:
        The snapshot row (``version_id``, ``source_file``, ``source_format``, ``source_digest``,
        ``canonical_document``, ``created_at``) or ``None``, and the revision ids walked.
    """
    chain = [version_id] + [str(r["chain_id"]) for r in rows[1:]]
    last = rows[-1] if rows else None
    if last is None or last.get("version_id") is None:
        return None, chain
    keys = ("version_id", "source_file", "source_format", "source_digest", "canonical_document", "created_at")
    return {k: last.get(k) for k in keys}, chain


#: A uuid-shaped successor pointer; anything else is a missing target, never a cast error.
_UUID_PATTERN = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

#: ``metadata.successorRevisionId`` (or ``successor_revision_id``) of ``v``, trimmed; ``NULL``
#: when neither is a non-blank string (:func:`app.revision_deprecation.successor_revision_id_from_metadata`).
_SUCCESSOR_SQL = """
    COALESCE(
        CASE WHEN jsonb_typeof(v.metadata -> 'successorRevisionId') = 'string'
             THEN NULLIF(btrim(v.metadata ->> 'successorRevisionId', E' \\t\\n\\r\\f\\x0B'), '') END,
        CASE WHEN jsonb_typeof(v.metadata -> 'successor_revision_id') = 'string'
             THEN NULLIF(btrim(v.metadata ->> 'successor_revision_id', E' \\t\\n\\r\\f\\x0B'), '') END
    )
"""

#: Whether ``v`` is the tip of a protected branch or the target of a protected tag in the project
#: (:meth:`app.database.Database.revision_has_protected_named_ref`). Placeholders: project,
#: tenant, project, tenant.
_PROTECTED_SQL = """
    (
        EXISTS (
            SELECT 1 FROM apiome.version_branches b
            INNER JOIN apiome.projects bp ON bp.id = b.project_id AND bp.deleted_at IS NULL
            WHERE b.project_id = %s AND b.tip_version_id = v.id AND b.protected = TRUE
              AND bp.tenant_id = %s
        )
        OR EXISTS (
            SELECT 1 FROM apiome.version_tags t
            INNER JOIN apiome.projects tp ON tp.id = t.project_id AND tp.deleted_at IS NULL
            WHERE t.project_id = %s AND t.version_id = v.id AND t.protected = TRUE
              AND tp.tenant_id = %s
        )
    )
"""

#: The successor chain from a revision: one row per live revision of the tenant it reaches,
#: ordered by depth. The walk stops after a revision in another project, with no successor, on a
#: protected ref, whose successor was already visited, or at ``max_rows``.
#: Placeholders: see :func:`successor_chain_params`.
SUCCESSOR_CHAIN_SQL = f"""
    WITH RECURSIVE chain AS (
        SELECT v.id, v.project_id, 1 AS depth, ARRAY[%s::text] AS seen,
               {_SUCCESSOR_SQL} AS successor, {_PROTECTED_SQL} AS protected
        FROM apiome.versions v
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE v.id = %s::uuid
          AND p.tenant_id = %s
          AND v.deleted_at IS NULL
          AND p.deleted_at IS NULL
        UNION ALL
        SELECT v.id, v.project_id, c.depth + 1, c.seen || c.successor,
               {_SUCCESSOR_SQL}, {_PROTECTED_SQL}
        FROM chain c
        JOIN apiome.versions v
          ON v.id = CASE WHEN c.successor ~ '{_UUID_PATTERN}' THEN c.successor::uuid END
        JOIN apiome.projects p ON p.id = v.project_id
        WHERE c.project_id = %s
          AND c.successor IS NOT NULL
          AND NOT c.protected
          AND NOT c.successor = ANY(c.seen)
          AND c.depth < %s
          AND p.tenant_id = %s
          AND v.deleted_at IS NULL
          AND p.deleted_at IS NULL
    )
    SELECT id::text AS id, project_id::text AS project_id, successor, protected
    FROM chain
    ORDER BY depth
"""


def successor_chain_params(
    start_version_id: str, tenant_id: str, project_id: str, max_rows: int
) -> Tuple[Any, ...]:
    """Positional parameters for :data:`SUCCESSOR_CHAIN_SQL`.

    Args:
        start_version_id: The first revision (a uuid string).
        tenant_id: The tenant every revision must belong to.
        project_id: The project the chain must stay in.
        max_rows: The most rows the walk returns (the start included).
    """
    protected = (project_id, tenant_id, project_id, tenant_id)
    return (
        start_version_id,
        *protected,
        start_version_id,
        tenant_id,
        *protected,
        project_id,
        max_rows,
        tenant_id,
    )


def replay_successor_chain(
    start_version_id: str, project_id: str, rows: Sequence[Dict[str, Any]], max_hops: int
) -> Tuple[str, List[str], str, Optional[str]]:
    """Decide the successor resolution from the rows :data:`SUCCESSOR_CHAIN_SQL` returned.

    Applies the per-hop checks of #749 in their original order — missing revision, other project,
    no successor, protected ref, cycle, missing successor, successor in another project — to the
    prefetched rows, so no hop needs its own lookup.

    Args:
        start_version_id: The first revision, as the caller passed it.
        project_id: The project the chain must stay in.
        rows: The chain, ordered by depth (``rows[i + 1]`` is ``rows[i]["successor"]``).
        max_hops: The most successor hops followed.

    Returns:
        ``(final_id, hop_targets, status, missing_successor_id)`` as
        :meth:`app.database.Database.resolve_successor_revision_chain` documents.
    """
    current = start_version_id
    visited = {start_version_id}
    hops: List[str] = []
    for index in range(max_hops + 1):
        row = rows[index] if index < len(rows) else None
        if row is None:  # only the start can be missing: a successor row is checked before the hop
            return current, hops, "missing_target", None
        if str(row.get("project_id")) != project_id:
            return current, hops, "project_mismatch", None
        succ = row.get("successor")
        if not succ:
            return current, hops, ("none" if not hops else "resolved"), None
        if row.get("protected"):
            return current, hops, "blocked_protected_ref", None
        if succ in visited:
            return current, hops, "cycle", None
        nxt = rows[index + 1] if index + 1 < len(rows) else None
        if not nxt:
            return current, hops, "missing_target", succ
        if str(nxt.get("project_id")) != project_id:
            return current, hops, "project_mismatch", None
        hops.append(succ)
        visited.add(succ)
        current = succ
    return current, hops, "max_hops_exceeded", None


#: The newest edit per pointer on the given revisions, newest first. Placeholders: tenant, ids.
SOURCE_EDITS_SQL = """
    SELECT pointer, change_kind, version_id, created_at
    FROM (
        SELECT DISTINCT ON (pointer) pointer, change_kind, version_id, created_at, id
        FROM apiome.version_source_edits
        WHERE tenant_id = %s AND version_id = ANY(%s::uuid[])
        ORDER BY pointer, created_at DESC, id DESC
    ) newest
    ORDER BY created_at DESC, id DESC
"""
