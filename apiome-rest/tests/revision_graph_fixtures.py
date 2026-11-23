"""Revision-graph fixtures and the pre-DBP-1.14 reference implementations (#7197).

Used by ``test_revision_graph_queries_db.py`` (the one-statement queries return what the old
multi-statement code returned, on linear, diamond and criss-cross histories) and
``test_query_budgets_db.py`` (one statement each on a 500-revision linear and a branching history).

The ``legacy_*`` functions are the implementations on ``main`` @ ``62810ea9f``, kept verbatim
apart from taking the :class:`~app.database.Database` as an argument. One fix:
``legacy_import_snapshot_lineage`` scopes the parent hop through ``projects.tenant_id`` —
``main`` filtered on a ``versions.tenant_id`` column that does not exist, so any walk past the
first revision raised ``UndefinedColumn``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.revision_deprecation import is_uuid_string, successor_revision_id_from_metadata


class GraphBuilder:
    """Insert revisions with explicit parents and strictly increasing ``created_at``.

    Args:
        ctx: The ``stamp_env`` dict (``conn``, ``tenant``, ``project``, ``user``).
    """

    def __init__(self, ctx: Dict[str, Any]) -> None:
        self.ctx = ctx
        self.clock = 0
        self.ids: Dict[str, str] = {}

    def add(
        self,
        label: str,
        parent: Optional[str] = None,
        merge: Optional[str] = None,
        *,
        published: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
        deleted: bool = False,
    ) -> str:
        """Insert one revision; ``parent`` / ``merge`` are labels added earlier.

        Args:
            label: The revision's ``version_id`` label (and its key in :attr:`ids`).
            parent: Label of the ``parent_version_id`` revision.
            merge: Label of the ``merge_parent_version_id`` revision.
            published: Published, with ``published_at`` in creation order.
            metadata: ``versions.metadata``.
            project: Another project id (default: the seeded project).
            deleted: Soft-deleted.

        Returns:
            The new revision's id.
        """
        self.clock += 1
        with self.ctx["conn"].cursor() as cur:
            cur.execute(
                """
                INSERT INTO apiome.versions
                  (project_id, creator_id, version_id, parent_version_id, merge_parent_version_id,
                   created_at, published, published_at, metadata, deleted_at)
                VALUES (%s, %s, %s, %s, %s,
                        timestamptz '2026-01-01' + make_interval(secs => %s), %s,
                        CASE WHEN %s THEN timestamptz '2026-01-01' + make_interval(secs => %s) END,
                        %s::jsonb, CASE WHEN %s THEN now() END)
                RETURNING id::text AS id
                """,
                (
                    project or self.ctx["project"],
                    self.ctx["user"],
                    label,
                    self.ids.get(parent) if parent else None,
                    self.ids.get(merge) if merge else None,
                    self.clock,
                    published,
                    published,
                    self.clock,
                    json.dumps(metadata or {}),
                    deleted,
                ),
            )
            self.ids[label] = cur.fetchone()["id"]
        self.ctx["conn"].commit()
        return self.ids[label]

    def linear(self, prefix: str, count: int, *, published_every: int = 0) -> List[str]:
        """``count`` revisions in one parent chain, labelled ``<prefix>0`` … oldest first."""
        out: List[str] = []
        for i in range(count):
            published = bool(published_every) and i % published_every == 0
            out.append(self.add(f"{prefix}{i}", f"{prefix}{i - 1}" if i else None, published=published))
        return out

    def diamond(self, prefix: str = "d") -> Dict[str, str]:
        """``a`` → ``b``, ``c``; ``m`` = merge of ``b`` and ``c``; ``e`` on ``m``; ``a`` and ``c`` published."""
        self.add(f"{prefix}a", published=True)
        self.add(f"{prefix}b", f"{prefix}a")
        self.add(f"{prefix}c", f"{prefix}a", published=True)
        self.add(f"{prefix}m", f"{prefix}b", f"{prefix}c")
        self.add(f"{prefix}e", f"{prefix}m")
        return {k: self.ids[f"{prefix}{k}"] for k in ("a", "b", "c", "m", "e")}

    def criss_cross(self, prefix: str = "x") -> Dict[str, str]:
        """Two lines off ``a`` that merge each other twice; tips ``l3`` and ``r3``."""
        self.add(f"{prefix}a", published=True)
        self.add(f"{prefix}l1", f"{prefix}a")
        self.add(f"{prefix}r1", f"{prefix}a", published=True)
        self.add(f"{prefix}l2", f"{prefix}l1", f"{prefix}r1")
        self.add(f"{prefix}r2", f"{prefix}r1", f"{prefix}l1")
        self.add(f"{prefix}l3", f"{prefix}l2", f"{prefix}r2", published=True)
        self.add(f"{prefix}r3", f"{prefix}r2", f"{prefix}l2")
        self.add(f"{prefix}gone", f"{prefix}r3", deleted=True)
        keys = ("a", "l1", "r1", "l2", "r2", "l3", "r3", "gone")
        return {k: self.ids[f"{prefix}{k}"] for k in keys}


def drop_branches(ctx: Dict[str, Any], project: Optional[str] = None) -> None:
    """Delete the project's branches (``version_branches`` restricts deleting their tips)."""
    with ctx["conn"].cursor() as cur:
        cur.execute("DELETE FROM apiome.version_branches WHERE project_id = %s::uuid", (project or ctx["project"],))
    ctx["conn"].commit()


# ───────────────────────── main @ 62810ea9f reference implementations ─────────────────────────


def legacy_prior_published_baseline(db, project_id: str, tenant_id: str, published_revision_id: str) -> Optional[str]:
    """``Database.get_prior_published_baseline_revision_id`` before #7197."""
    ancestors = db.collect_revision_ancestors(published_revision_id, tenant_id)
    cand_ids = [str(a) for a in ancestors if str(a) != str(published_revision_id)]
    if not cand_ids:
        return None
    placeholders = ",".join(["%s"] * len(cand_ids))
    rows = db.execute_query(
        f"""
        SELECT v.id
        FROM apiome.versions v
        INNER JOIN apiome.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
        WHERE v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL AND v.published = true
          AND v.id IN ({placeholders})
        ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
        LIMIT 1
        """,
        tuple([project_id, tenant_id, *cand_ids]),
    )
    if not rows:
        return None
    rid = rows[0].get("id")
    return str(rid) if rid is not None else None


def legacy_prior_revisions_for_transitive_check(
    db, project_id: str, tenant_id: str, revision_id: str, *, limit: int = 50
) -> List[Dict[str, Any]]:
    """``Database.list_prior_revisions_for_transitive_check`` before #7197."""
    if not revision_id or not is_uuid_string(str(revision_id)):
        return []
    bound = max(0, int(limit))
    ancestors = db.collect_revision_ancestors(revision_id, tenant_id)
    cand_ids = [str(a) for a in ancestors if str(a) != str(revision_id)]
    if cand_ids:
        placeholders = ",".join(["%s"] * len(cand_ids))
        rows = db.execute_query(
            f"""
            SELECT v.id::text AS id, v.version_id
            FROM apiome.versions v
            INNER JOIN apiome.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
            WHERE v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL AND v.published = true
              AND v.id IN ({placeholders})
            ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
            LIMIT %s
            """,
            tuple([project_id, tenant_id, *cand_ids, bound]),
        )
        if rows:
            return [dict(r) for r in rows]
    rows = db.execute_query(
        """
        SELECT v.id::text AS id, v.version_id
        FROM apiome.versions v
        INNER JOIN apiome.projects p ON v.project_id = p.id AND p.deleted_at IS NULL
        INNER JOIN apiome.versions anchor ON anchor.id = %s
        WHERE v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL
          AND v.id <> anchor.id AND (v.created_at, v.id) < (anchor.created_at, anchor.id)
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT %s
        """,
        (revision_id, project_id, tenant_id, bound),
    )
    return [dict(r) for r in rows or []]


def legacy_successor_chain(
    db, start_version_id: str, tenant_id: str, project_id: str, *, max_hops: int = 32
) -> Tuple[str, List[str], str, Optional[str]]:
    """``Database.resolve_successor_revision_chain`` before #7197 (2–4 lookups per hop)."""
    current = start_version_id
    visited: Set[str] = {start_version_id}
    hops: List[str] = []
    for _ in range(max_hops + 1):
        row = db.get_version_by_id(current, tenant_id)
        if not row:
            return current, hops, "missing_target", None
        if str(row.get("project_id")) != project_id:
            return current, hops, "project_mismatch", None
        succ = successor_revision_id_from_metadata(row.get("metadata"))
        if not succ:
            return current, hops, ("none" if not hops else "resolved"), None
        if db.revision_has_protected_named_ref(current, project_id, tenant_id):
            return current, hops, "blocked_protected_ref", None
        if succ in visited:
            return current, hops, "cycle", None
        nxt = db.get_version_core(succ, tenant_id)
        if not nxt:
            return current, hops, "missing_target", succ
        if str(nxt.get("project_id")) != project_id:
            return current, hops, "project_mismatch", None
        hops.append(succ)
        visited.add(succ)
        current = succ
    return current, hops, "max_hops_exceeded", None


def legacy_import_snapshot_lineage(
    db, version_id: str, tenant_id: str, *, max_depth: int = 50
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """``Database.get_import_snapshot_lineage`` before #7197, with the parent hop's tenant fixed."""
    chain: List[str] = []
    current: Optional[str] = version_id
    while current and current not in chain and len(chain) < max_depth:
        chain.append(current)
        rows = db.execute_query(
            """
            SELECT s.version_id, s.source_file, s.source_format, s.source_digest,
                   s.canonical_document, s.created_at
            FROM apiome.version_import_snapshots s
            WHERE s.version_id = %s::uuid AND s.tenant_id = %s
            """,
            (current, tenant_id),
        )
        if rows:
            return rows[0], chain
        parent = db.execute_query(
            "SELECT v.parent_version_id FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id "
            "WHERE v.id = %s::uuid AND p.tenant_id = %s",
            (current, tenant_id),
        )
        current = str(parent[0]["parent_version_id"]) if parent and parent[0].get("parent_version_id") else None
    return None, chain


def legacy_source_edits(db, version_ids: Sequence[str], tenant_id: str) -> List[Dict[str, Any]]:
    """``Database.list_source_edits`` before #7197 (every edit, not one per pointer)."""
    if not version_ids:
        return []
    return db.execute_query(
        """
        SELECT pointer, change_kind, version_id, created_at
        FROM apiome.version_source_edits
        WHERE tenant_id = %s AND version_id = ANY(%s::uuid[])
        ORDER BY created_at DESC
        """,
        (tenant_id, list(version_ids)),
    )


def legacy_branch_divergence(
    db, *, project_id: str, tenant_id: str, branch_tip_revision_id: str, against_tip_revision_id: str,
    sample_limit: int = 5,
) -> Dict[str, Any]:
    """``Database.compute_branch_divergence`` before #7197 (text ids inside the recursion)."""
    limit = max(1, min(int(sample_limit), 25))
    walk = """
        {name} AS (
            SELECT v.id::text AS revision_id, v.parent_version_id::text AS parent_revision_id,
                   v.merge_parent_version_id::text AS merge_parent_revision_id
            FROM apiome.versions v JOIN apiome.projects p ON v.project_id = p.id
            WHERE v.id = %s AND v.project_id = %s AND p.tenant_id = %s AND v.deleted_at IS NULL
            UNION
            SELECT v.id::text, v.parent_version_id::text, v.merge_parent_version_id::text
            FROM apiome.versions v
            JOIN {name} a ON v.id = a.parent_revision_id::uuid OR v.id = a.merge_parent_revision_id::uuid
            WHERE v.project_id = %s AND v.deleted_at IS NULL
        )
    """
    sample = """
        {name} AS (
            SELECT v.id::text AS revision_id, COALESCE(v.description, '') AS short_message, v.created_at
            FROM apiome.versions v JOIN {src} a ON a.revision_id = v.id::text
            WHERE v.project_id = %s AND v.deleted_at IS NULL
            ORDER BY v.created_at DESC, v.id DESC
            LIMIT %s
        )
    """
    agg = """
        COALESCE((SELECT json_agg(json_build_object('revisionId', a.revision_id, 'shortMessage', a.short_message)
                  ORDER BY a.created_at DESC, a.revision_id DESC) FROM {name} a), '[]'::json)
    """
    q = f"""
        WITH RECURSIVE
        {walk.format(name="branch_ancestors")},
        {walk.format(name="against_ancestors")},
        merge_base AS (
            SELECT v.id::text AS revision_id, v.created_at
            FROM apiome.versions v
            JOIN branch_ancestors ba ON v.id = ba.revision_id::uuid
            JOIN against_ancestors aa ON v.id = aa.revision_id::uuid
            WHERE v.project_id = %s AND v.deleted_at IS NULL
            ORDER BY v.created_at DESC, v.id DESC
            LIMIT 1
        ),
        merge_base_ancestors AS (
            SELECT v.id::text AS revision_id, v.parent_version_id::text AS parent_revision_id,
                   v.merge_parent_version_id::text AS merge_parent_revision_id
            FROM apiome.versions v JOIN merge_base mb ON v.id = mb.revision_id::uuid
            UNION
            SELECT v.id::text, v.parent_version_id::text, v.merge_parent_version_id::text
            FROM apiome.versions v
            JOIN merge_base_ancestors mba
              ON v.id = mba.parent_revision_id::uuid OR v.id = mba.merge_parent_revision_id::uuid
            WHERE v.project_id = %s AND v.deleted_at IS NULL
        ),
        ahead_set AS (
            SELECT ba.revision_id FROM branch_ancestors ba
            LEFT JOIN merge_base_ancestors mba ON mba.revision_id = ba.revision_id WHERE mba.revision_id IS NULL
        ),
        behind_set AS (
            SELECT aa.revision_id FROM against_ancestors aa
            LEFT JOIN merge_base_ancestors mba ON mba.revision_id = aa.revision_id WHERE mba.revision_id IS NULL
        ),
        {sample.format(name="ahead_sample", src="ahead_set")},
        {sample.format(name="behind_sample", src="behind_set")}
        SELECT (SELECT mb.revision_id FROM merge_base mb) AS merge_base_revision_id,
               (SELECT mb.created_at FROM merge_base mb) AS merge_base_created_at,
               (SELECT COUNT(*)::int FROM ahead_set) AS ahead_count,
               (SELECT COUNT(*)::int FROM behind_set) AS behind_count,
               {agg.format(name="ahead_sample")} AS ahead_sample,
               {agg.format(name="behind_sample")} AS behind_sample
    """
    p, t = project_id, tenant_id
    rows = db.execute_query(
        q, (branch_tip_revision_id, p, t, p, against_tip_revision_id, p, t, p, p, p, p, limit, p, limit)
    )
    row = rows[0]
    return {
        "merge_base_revision_id": row.get("merge_base_revision_id"),
        "merge_base_created_at": row.get("merge_base_created_at"),
        "ahead_count": int(row.get("ahead_count") or 0),
        "behind_count": int(row.get("behind_count") or 0),
        "ahead_sample": row.get("ahead_sample") or [],
        "behind_sample": row.get("behind_sample") or [],
    }


def legacy_fetch_revision_closure(db, revision_ids: Sequence[str], tenant_id: str) -> Set[Tuple[Any, ...]]:
    """``Database.fetch_revision_closure`` before #7197 (an ``OR`` join per step), as row tuples."""
    ids = sorted({str(r) for r in revision_ids if r and is_uuid_string(str(r))})
    if not ids:
        return set()
    rows = db.execute_query(
        """
        WITH RECURSIVE closure AS (
            SELECT v.id, v.parent_version_id, v.merge_parent_version_id, v.created_at, v.version_id
            FROM apiome.versions v JOIN apiome.projects p ON p.id = v.project_id
            WHERE v.id = ANY(%s::uuid[]) AND p.tenant_id = %s AND v.deleted_at IS NULL AND p.deleted_at IS NULL
            UNION
            SELECT v.id, v.parent_version_id, v.merge_parent_version_id, v.created_at, v.version_id
            FROM apiome.versions v
            JOIN closure c ON v.id = c.parent_version_id OR v.id = c.merge_parent_version_id
            JOIN apiome.projects p ON p.id = v.project_id
            WHERE p.tenant_id = %s AND v.deleted_at IS NULL AND p.deleted_at IS NULL
        )
        SELECT id::text AS id, parent_version_id::text AS parent_version_id,
               merge_parent_version_id::text AS merge_parent_version_id, created_at, version_id
        FROM closure
        """,
        (ids, tenant_id, tenant_id),
    )
    return {node_tuple(r) for r in rows or []}


def node_tuple(row: Any) -> Tuple[Any, ...]:
    """A closure row or :class:`~app.revision_dag.RevisionNode` as a comparable tuple."""
    if isinstance(row, dict):
        keys = ("id", "parent_version_id", "merge_parent_version_id", "created_at", "version_id")
        return tuple(row[k] for k in keys)
    return (row.revision_id, row.parent_id, row.merge_parent_id, row.created_at, row.version_label)
