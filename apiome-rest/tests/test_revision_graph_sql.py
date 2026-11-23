"""Unit tests for :mod:`app.revision_graph_sql` — DBP-1.14 (#7197).

The SQL itself is checked against Postgres in ``test_revision_graph_queries_db.py``; these cover
the in-memory halves (the successor replay, the lineage split) and the shape of the SQL: uuids
inside the recursion, one primary-key probe per parent link, placeholder counts that match the
parameter builders.
"""

from __future__ import annotations

import re

import pytest

from app import revision_graph_sql as rgs

A, B, C = (f"00000000-0000-4000-8000-00000000000{c}" for c in "abc")


def _row(rid, successor=None, *, protected=False, project="p1"):
    return {"id": rid, "project_id": project, "successor": successor, "protected": protected}


# ───────────────────────────── successor replay ─────────────────────────────


@pytest.mark.parametrize(
    "rows, max_hops, expected",
    [
        ([], 32, (A, [], "missing_target", None)),
        ([_row(A, project="p2")], 32, (A, [], "project_mismatch", None)),
        ([_row(A)], 32, (A, [], "none", None)),
        ([_row(A, B), _row(B)], 32, (B, [B], "resolved", None)),
        ([_row(A, B, protected=True)], 32, (A, [], "blocked_protected_ref", None)),
        ([_row(A, A)], 32, (A, [], "cycle", None)),
        ([_row(A, B), _row(B, A)], 32, (B, [B], "cycle", None)),
        ([_row(A, B)], 32, (A, [], "missing_target", B)),
        ([_row(A, B), _row(B, project="p2")], 32, (A, [], "project_mismatch", None)),
        # ``max_hops + 1`` iterations, as on ``main``: one hop past the limit, then the verdict.
        ([_row(A, B), _row(B, C), _row(C)], 1, (C, [B, C], "max_hops_exceeded", None)),
        ([_row(A, B), _row(B, C), _row(C)], 2, (C, [B, C], "resolved", None)),
        ([_row(A, B), _row(B, C), _row(C)], 0, (B, [B], "max_hops_exceeded", None)),
        ([_row(A, B)], 0, (A, [], "missing_target", B)),
        ([_row(A, B)], -1, (A, [], "max_hops_exceeded", None)),
    ],
)
def test_replay_applies_the_hop_checks_in_order(rows, max_hops, expected) -> None:
    assert rgs.replay_successor_chain(A, "p1", rows, max_hops) == expected


def test_protected_is_checked_before_the_cycle() -> None:
    assert rgs.replay_successor_chain(A, "p1", [_row(A, A, protected=True)], 32)[2] == "blocked_protected_ref"


def test_successor_chain_params_match_the_placeholders() -> None:
    params = rgs.successor_chain_params(A, "t1", "p1", 34)
    assert len(params) == rgs.SUCCESSOR_CHAIN_SQL.count("%s")
    assert params[0] == A and params[5] == A  # the seen array seed, then the start lookup
    assert params[-2:] == (34, "t1")


# ───────────────────────────── snapshot lineage ─────────────────────────────


def test_lineage_keeps_the_callers_start_id_and_the_snapshot_row() -> None:
    upper = A.upper()
    rows = [
        {"chain_id": A, "depth": 1, "version_id": None},
        {"chain_id": B, "depth": 2, "version_id": B, "source_file": "o.yaml", "source_format": "yaml",
         "source_digest": "sha256:1", "canonical_document": {"openapi": "3.1.0"}, "created_at": None},
    ]
    snapshot, chain = rgs.lineage_from_rows(upper, rows)
    assert chain == [upper, B]
    assert snapshot == {
        "version_id": B, "source_file": "o.yaml", "source_format": "yaml", "source_digest": "sha256:1",
        "canonical_document": {"openapi": "3.1.0"}, "created_at": None,
    }


def test_lineage_without_a_snapshot_is_the_walked_chain() -> None:
    rows = [{"chain_id": A, "depth": 1, "version_id": None}, {"chain_id": B, "depth": 2, "version_id": None}]
    assert rgs.lineage_from_rows(A, rows) == (None, [A, B])
    assert rgs.lineage_from_rows(A, []) == (None, [A])


def test_lineage_params_match_the_placeholders() -> None:
    params = rgs.import_snapshot_lineage_params(A, "t1", 50)
    assert len(params) == rgs.IMPORT_SNAPSHOT_LINEAGE_SQL.count("%s")
    assert params[1] == A and params[4] == 50


# ───────────────────────────── SQL shape ─────────────────────────────


@pytest.mark.parametrize(
    "sql, placeholders",
    [
        (rgs.REVISION_CLOSURE_SQL, 3),
        (rgs.PRIOR_PUBLISHED_BASELINE_SQL, 5),
        (rgs.PRIOR_REVISIONS_FOR_TRANSITIVE_CHECK_SQL, 10),
        (rgs.BRANCH_DIVERGENCE_SQL, 14),
        (rgs.SOURCE_EDITS_SQL, 2),
    ],
)
def test_placeholder_counts(sql: str, placeholders: int) -> None:
    assert sql.count("%s") == placeholders


@pytest.mark.parametrize(
    "sql",
    [rgs.REVISION_CLOSURE_SQL, rgs.PRIOR_PUBLISHED_BASELINE_SQL, rgs.PRIOR_REVISIONS_FOR_TRANSITIVE_CHECK_SQL,
     rgs.BRANCH_DIVERGENCE_SQL],
)
def test_dag_walks_probe_each_parent_link_by_uuid(sql: str) -> None:
    recursion = sql.split("SELECT id::text")[0] if "SELECT id::text" in sql else sql
    assert "CROSS JOIN LATERAL (VALUES" in recursion
    assert "::uuid OR" not in sql and "id::text =" not in sql  # no text join, no OR join filter
    assert not re.search(r"JOIN \w+ \w+ ON v\.id = \w+\.\w+ OR", sql)


def test_source_edits_keep_one_row_per_pointer() -> None:
    assert "DISTINCT ON (pointer)" in rgs.SOURCE_EDITS_SQL
