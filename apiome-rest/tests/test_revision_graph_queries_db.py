"""Revision-graph reads in one statement — DBP-1.14 (#7197), against Postgres.

Each rewritten read must return what the implementation on ``main`` returned (the ``legacy_*``
references in ``tests/revision_graph_fixtures.py``) on linear, diamond and criss-cross histories,
and must run exactly one SQL statement:

* :meth:`Database.fetch_revision_closure` and :meth:`Database.compute_merge_base_revision_id`;
* :meth:`Database.get_prior_published_baseline_revision_id`;
* :meth:`Database.list_prior_revisions_for_transitive_check`;
* :meth:`Database.compute_branch_divergence`;
* :meth:`Database.resolve_successor_revision_chain`;
* :meth:`Database.get_import_snapshot_lineage` (``main`` raised past the first level: see the
  fixtures module) and :meth:`Database.list_source_edits` (now one row per pointer).

Skips when no database with V403 is reachable (``DATABASE_URL``).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator, List

import pytest

from app.statement_stats import CountingDictCursor, capture
from tests.revision_graph_fixtures import (
    GraphBuilder,
    drop_branches,
    legacy_branch_divergence,
    legacy_fetch_revision_closure,
    legacy_import_snapshot_lineage,
    legacy_prior_published_baseline,
    legacy_prior_revisions_for_transitive_check,
    legacy_source_edits,
    legacy_successor_chain,
    node_tuple,
)
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project

pytestmark = pytest.mark.requires_db


@pytest.fixture
def graph(stamp_env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """A linear history, a diamond and a criss-cross in the seeded project, plus a second project.

    Yields the ``stamp_env`` dict with ``g`` (the :class:`GraphBuilder`, labels in ``g.ids``),
    ``linear`` (30 ids, every third published), ``diamond``, ``criss`` and ``other_project``.
    """
    ctx = stamp_env
    conn = ctx["conn"]
    conn.cursor_factory = CountingDictCursor
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug) VALUES (%s, %s, 'Other', %s) "
            "RETURNING id::text AS id",
            (ctx["tenant"], ctx["user"], f"other-{uuid.uuid4().hex[:8]}"),
        )
        ctx["other_project"] = cur.fetchone()["id"]
    conn.commit()
    g = GraphBuilder(ctx)
    ctx["g"] = g
    ctx["linear"] = g.linear("l", 30, published_every=3)
    ctx["diamond"] = g.diamond()
    ctx["criss"] = g.criss_cross()
    try:
        yield ctx
    finally:
        conn.rollback()
        drop_branches(ctx)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.versions WHERE project_id = %s::uuid", (ctx["other_project"],))
            cur.execute("DELETE FROM apiome.projects WHERE id = %s::uuid", (ctx["other_project"],))
        conn.commit()


def _one_statement(call):
    """Run ``call`` and assert it ran exactly one SQL statement; return its result."""
    with capture() as stats:
        result = call()
    assert stats.count == 1, stats.statements
    return result


def _all_revisions(ctx: Dict[str, Any]) -> List[str]:
    return list(ctx["g"].ids.values())


# ───────────────────────────── closure and merge base ─────────────────────────────


def test_closure_matches_main_on_every_history(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    d, x = graph["diamond"], graph["criss"]
    starts = [
        [graph["linear"][-1]],
        [d["e"]],
        [d["b"], d["c"]],
        [x["l3"], x["r3"]],
        [x["gone"]],  # deleted: no closure
        ["not-a-uuid"],
        [],
    ]
    for ids in starts:
        if ids and ids != ["not-a-uuid"]:
            new = _one_statement(lambda: db.fetch_revision_closure(ids, tenant))
        else:  # nothing to walk: no statement at all
            new = db.fetch_revision_closure(ids, tenant)
        assert {node_tuple(n) for n in new} == legacy_fetch_revision_closure(db, ids, tenant), ids
    assert len(db.fetch_revision_closure([graph["linear"][-1]], tenant)) == 30


def test_merge_base_on_diamond_and_criss_cross(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    d, x = graph["diamond"], graph["criss"]
    assert _one_statement(lambda: db.compute_merge_base_revision_id(d["b"], d["c"], tenant)) == d["a"]
    assert db.compute_merge_base_revision_id(d["e"], d["b"], tenant) == d["b"]
    # Criss-cross: l2 and r2 are both best common ancestors; the newer one (r2) wins.
    assert db.compute_merge_base_revision_id(x["l3"], x["r3"], tenant) == x["r2"]
    assert db.compute_merge_base_revision_id(d["e"], x["l3"], tenant) is None


# ───────────────────────── published baseline and transitive check ─────────────────────────


def test_prior_published_baseline_matches_main_for_every_revision(graph) -> None:
    db, tenant, project = graph["db"], graph["tenant"], graph["project"]
    for rid in _all_revisions(graph) + [str(uuid.uuid4())]:
        new = _one_statement(lambda: db.get_prior_published_baseline_revision_id(project, tenant, rid))
        assert new == legacy_prior_published_baseline(db, project, tenant, rid), rid
    assert db.get_prior_published_baseline_revision_id(project, tenant, graph["linear"][29]) == graph["linear"][27]
    assert db.get_prior_published_baseline_revision_id(project, tenant, graph["diamond"]["e"]) == graph["diamond"]["c"]
    assert db.get_prior_published_baseline_revision_id(project, tenant, "not-a-uuid") is None
    assert db.get_prior_published_baseline_revision_id(graph["other_project"], tenant, graph["linear"][29]) is None


def test_transitive_check_candidates_match_main_for_every_revision(graph) -> None:
    db, tenant, project = graph["db"], graph["tenant"], graph["project"]
    for rid in _all_revisions(graph):
        for limit in (0, 1, 3, 50):
            new = _one_statement(
                lambda: db.list_prior_revisions_for_transitive_check(project, tenant, rid, limit=limit)
            )
            old = legacy_prior_revisions_for_transitive_check(db, project, tenant, rid, limit=limit)
            assert new == old, (rid, limit)
    # The published ancestors, newest first (l0, l3, l6 … are published).
    picked = db.list_prior_revisions_for_transitive_check(project, tenant, graph["linear"][10])
    assert [r["version_id"] for r in picked] == ["l9", "l6", "l3", "l0"]
    fallback = db.list_prior_revisions_for_transitive_check(project, tenant, graph["linear"][0], limit=2)
    assert fallback == []  # nothing in the project is older than the first revision
    assert db.list_prior_revisions_for_transitive_check(project, tenant, "not-a-uuid") == []


def test_transitive_check_falls_back_to_revisions_created_before(graph) -> None:
    db, tenant, project = graph["db"], graph["tenant"], graph["project"]
    g = graph["g"]
    lone = g.add("lone")  # no parent, not published: the created-before fallback
    new = _one_statement(lambda: db.list_prior_revisions_for_transitive_check(project, tenant, lone, limit=3))
    assert new == legacy_prior_revisions_for_transitive_check(db, project, tenant, lone, limit=3)
    assert [r["version_id"] for r in new] == ["xr3", "xl3", "xr2"]  # x-gone is deleted


# ───────────────────────────── branch divergence ─────────────────────────────


def test_branch_divergence_matches_main(graph) -> None:
    db, tenant, project = graph["db"], graph["tenant"], graph["project"]
    d, x, lin = graph["diamond"], graph["criss"], graph["linear"]
    pairs = [
        (x["l3"], x["r3"]),
        (x["r3"], x["l3"]),
        (d["e"], d["b"]),
        (d["b"], d["c"]),
        (lin[29], lin[10]),
        (lin[10], lin[29]),
        (lin[29], d["e"]),  # disjoint histories: no merge base
    ]
    for branch, against in pairs:
        for sample in (1, 5, 99):
            kwargs = dict(
                project_id=project, tenant_id=tenant, branch_tip_revision_id=branch,
                against_tip_revision_id=against, sample_limit=sample,
            )
            new = _one_statement(lambda: db.compute_branch_divergence(**kwargs))
            assert new == legacy_branch_divergence(db, **kwargs), (branch, against, sample)
    ahead = db.compute_branch_divergence(
        project_id=project, tenant_id=tenant, branch_tip_revision_id=lin[29], against_tip_revision_id=lin[10]
    )
    assert ahead["merge_base_revision_id"] == lin[10]
    assert (ahead["ahead_count"], ahead["behind_count"]) == (19, 0)
    assert [s["revisionId"] for s in ahead["ahead_sample"]] == lin[29:24:-1]


# ───────────────────────────── successor chain ─────────────────────────────


def _successor(target: Any, key: str = "successorRevisionId") -> Dict[str, Any]:
    return {key: target}


def _chain(g: GraphBuilder, prefix: str, count: int, **last: Any) -> List[str]:
    """``count`` revisions, each naming the next as its successor; ``last`` sets the final metadata."""
    labels = [f"{prefix}{i}" for i in range(count)]
    ids = [g.add(label) for label in labels]
    with g.ctx["conn"].cursor() as cur:
        for here, there in zip(ids, ids[1:]):
            cur.execute(
                "UPDATE apiome.versions SET metadata = jsonb_build_object('successorRevisionId', %s::text) "
                "WHERE id = %s::uuid",
                (there, here),
            )
        if last:
            cur.execute("UPDATE apiome.versions SET metadata = %s::jsonb WHERE id = %s::uuid", (_json(last), ids[-1]))
    g.ctx["conn"].commit()
    return ids


def _json(value: Any) -> str:
    import json

    return json.dumps(value)


def _set_metadata(ctx: Dict[str, Any], rid: str, metadata: Dict[str, Any]) -> None:
    with ctx["conn"].cursor() as cur:
        cur.execute("UPDATE apiome.versions SET metadata = %s::jsonb WHERE id = %s::uuid", (_json(metadata), rid))
    ctx["conn"].commit()


def test_successor_chain_matches_main_in_every_outcome(graph) -> None:
    db, tenant, project, g = graph["db"], graph["tenant"], graph["project"], graph["g"]
    other = graph["other_project"]
    resolved = _chain(g, "s", 5)
    cycle = _chain(g, "c", 3, successorRevisionId=None)
    _set_metadata(graph, cycle[-1], _successor(cycle[0]))
    padded = _chain(g, "w", 2)
    _set_metadata(graph, padded[0], _successor(f"  {padded[1]}\n"))
    snake = _chain(g, "k", 2)
    _set_metadata(graph, snake[0], _successor(snake[1], "successor_revision_id"))
    numeric = g.add("num", metadata={"successorRevisionId": 12345})
    blank = g.add("blank", metadata={"successorRevisionId": "   "})
    to_garbage = g.add("garbage", metadata={"successorRevisionId": "not-a-uuid"})
    to_unknown = g.add("unknown", metadata={"successorRevisionId": str(uuid.uuid4())})
    to_deleted = g.add("to-deleted", metadata={"successorRevisionId": graph["criss"]["gone"]})
    outsider = g.add("outsider", project=other)
    to_outsider = g.add("to-outsider", metadata={"successorRevisionId": outsider})
    guarded = _chain(g, "p", 3)
    with graph["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.version_branches (project_id, name, tip_version_id, protected) "
            "VALUES (%s, 'release', %s, TRUE)",
            (project, guarded[1]),
        )
    graph["conn"].commit()
    tagged = _chain(g, "t", 3)
    with graph["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.version_tags (project_id, version_id, name, protected) VALUES (%s, %s, 'v1', TRUE)",
            (project, tagged[0]),
        )
    graph["conn"].commit()

    cases = [
        (resolved[0], project, 32, "resolved"),
        (resolved[0], project, 2, "max_hops_exceeded"),
        (resolved[0], project, 4, "resolved"),
        (resolved[0], project, 0, "max_hops_exceeded"),
        (resolved[-1], project, 32, "none"),
        (cycle[0], project, 32, "cycle"),
        (padded[0], project, 32, "resolved"),
        (snake[0], project, 32, "resolved"),
        (numeric, project, 32, "none"),
        (blank, project, 32, "none"),
        (to_garbage, project, 32, "missing_target"),
        (to_unknown, project, 32, "missing_target"),
        (to_deleted, project, 32, "missing_target"),
        (to_outsider, project, 32, "project_mismatch"),
        (outsider, project, 32, "project_mismatch"),
        (guarded[0], project, 32, "blocked_protected_ref"),
        (tagged[0], project, 32, "blocked_protected_ref"),
        (graph["criss"]["gone"], project, 32, "missing_target"),
        (str(uuid.uuid4()), project, 32, "missing_target"),
    ]
    for start, proj, hops, status in cases:
        new = _one_statement(lambda: db.resolve_successor_revision_chain(start, tenant, proj, max_hops=hops))
        assert new == legacy_successor_chain(db, start, tenant, proj, max_hops=hops), (start, hops)
        assert new[2] == status, (start, hops, new)
    final, hops, _, _ = db.resolve_successor_revision_chain(resolved[0], tenant, project)
    assert (final, hops) == (resolved[-1], resolved[1:])
    assert db.resolve_successor_revision_chain("nope", tenant, project) == ("nope", [], "missing_target", None)
    assert db.resolve_successor_revision_chain(to_unknown, str(uuid.uuid4()), project)[2] == "missing_target"


# ───────────────────────── import-snapshot lineage and source edits ─────────────────────────


def _snapshot(ctx: Dict[str, Any], rid: str, tenant: str | None = None) -> None:
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.version_import_snapshots "
            "(tenant_id, version_id, source_file, source_format, source_digest, canonical_document) "
            "VALUES (%s, %s, 'orders.yaml', 'yaml', 'sha256:abc', %s::jsonb)",
            (tenant or ctx["tenant"], rid, _json({"openapi": "3.1.0", "paths": {"/orders": {}}})),
        )
    ctx["conn"].commit()


def test_import_snapshot_lineage_matches_main(graph) -> None:
    db, tenant, lin, g = graph["db"], graph["tenant"], graph["linear"], graph["g"]
    _snapshot(graph, lin[0])
    _snapshot(graph, lin[20])
    loop = [g.add("loop0"), g.add("loop1", "loop0"), g.add("loop2", "loop1")]
    with graph["conn"].cursor() as cur:  # bad data: a parent cycle
        cur.execute("UPDATE apiome.versions SET parent_version_id = %s WHERE id = %s", (loop[2], loop[0]))
    graph["conn"].commit()
    cases = [
        (lin[29], 50),  # stops at the nearer snapshot (l20)
        (lin[19], 50),  # walks 20 levels to l0
        (lin[19], 10),  # depth guard: no snapshot within 10 revisions
        (lin[19], 20),  # exactly reaches l0
        (lin[20], 50),  # its own snapshot
        (lin[19], 1),
        (loop[2], 50),  # a cycle ends the walk
        (str(uuid.uuid4()), 50),  # unknown revision: only itself
    ]
    for start, depth in cases:
        new = _one_statement(lambda: db.get_import_snapshot_lineage(start, tenant, max_depth=depth))
        assert new == legacy_import_snapshot_lineage(db, start, tenant, max_depth=depth), (start, depth)
    snapshot, chain = db.get_import_snapshot_lineage(lin[19], tenant)
    assert snapshot["version_id"] == lin[0] and snapshot["canonical_document"]["paths"] == {"/orders": {}}
    assert chain == lin[19::-1]
    assert db.get_import_snapshot_lineage(lin[19], tenant, max_depth=10) == (None, lin[19:9:-1])
    # Another tenant sees neither the snapshot nor the parent hop.
    assert db.get_import_snapshot_lineage(lin[19], str(uuid.uuid4())) == (None, [lin[19]])
    assert db.get_import_snapshot_lineage(lin[19], tenant, max_depth=0) == (None, [])
    assert db.get_import_snapshot_lineage("not-a-uuid", tenant) == (None, ["not-a-uuid"])


def test_source_edits_keep_the_newest_edit_per_pointer(graph) -> None:
    db, tenant, lin = graph["db"], graph["tenant"], graph["linear"]
    with graph["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.version_source_edits (tenant_id, version_id, pointer, change_kind, created_at) "
            "SELECT %s, (%s::uuid[])[1 + n %% 10], '/paths/~1p' || (n %% 7), "
            "CASE WHEN n %% 2 = 0 THEN 'modified' ELSE 'added' END, "
            "timestamptz '2026-03-01' + make_interval(secs => n) FROM generate_series(1, 200) n",
            (tenant, lin[:10]),
        )
    graph["conn"].commit()
    chain = lin[:10]
    new = _one_statement(lambda: db.list_source_edits(chain, tenant))
    old = legacy_source_edits(db, chain, tenant)
    newest: Dict[str, Dict[str, Any]] = {}
    for row in old:  # newest first: the first row of a pointer is its newest edit
        newest.setdefault(row["pointer"], row)
    assert [dict(r) for r in new] == [dict(r) for r in newest.values()]
    assert len(new) == 7
    assert [r["created_at"] for r in new] == sorted((r["created_at"] for r in new), reverse=True)
    assert db.list_source_edits([], tenant) == []
    assert db.list_source_edits(chain, str(uuid.uuid4())) == []
