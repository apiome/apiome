"""Revision DAG storage, merge-base and graph queries — #2593.

Covers the pure DAG module (``app.revision_dag``: ancestors with distances and depth, merge-base
including disjoint, ancestor-of-the-other, diamond and criss-cross histories, history windows and
their limits), the single-query closure loader and the two database methods rebuilt on it, and the
three REST routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app
from app.revision_dag import (
    MAX_HISTORY_DEPTH,
    MAX_HISTORY_LIMIT,
    RevisionNode,
    ancestors,
    history_window,
    merge_base,
    merge_base_candidates,
)

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _graph(spec: Dict[str, List[str]]) -> Dict[str, RevisionNode]:
    """``{"c": ["b"], "m": ["c", "x"]}`` → nodes; creation order follows the spec's key order."""
    nodes: Dict[str, RevisionNode] = {}
    for index, (rid, parents) in enumerate(spec.items()):
        nodes[rid] = RevisionNode(
            revision_id=rid,
            parent_id=parents[0] if parents else None,
            merge_parent_id=parents[1] if len(parents) > 1 else None,
            created_at=_T0 + timedelta(minutes=index),
            version_label=f"v-{rid}",
        )
    return nodes


# a ─ b ─ c ─ d          (main)
#      \       \
#       x ─ y ─ m        (feature, merged back: m has parents y and d)
DAG = _graph({"a": [], "b": ["a"], "c": ["b"], "x": ["b"], "d": ["c"], "y": ["x"], "m": ["y", "d"]})


# ===========================================================================
# ancestors
# ===========================================================================


class TestAncestors:
    def test_linear_distances(self) -> None:
        assert ancestors(DAG, ["d"]) == {"d": 0, "c": 1, "b": 2, "a": 3}

    def test_both_parents_of_a_merge_are_followed(self) -> None:
        assert ancestors(DAG, ["m"]) == {"m": 0, "y": 1, "d": 1, "x": 2, "c": 2, "b": 3, "a": 4}

    def test_depth_cuts_the_walk(self) -> None:
        assert ancestors(DAG, ["m"], depth=1) == {"m": 0, "y": 1, "d": 1}
        assert ancestors(DAG, ["m"], depth=0) == {"m": 0}

    def test_several_tips_take_the_nearest_distance(self) -> None:
        result = ancestors(DAG, ["d", "y"])
        assert result["b"] == 2 and result["d"] == 0 and result["y"] == 0

    def test_missing_tip_and_missing_parent(self) -> None:
        assert ancestors(DAG, ["ghost"]) == {"ghost": 0}
        dangling = _graph({"r": ["deleted"]})
        assert ancestors(dangling, ["r"]) == {"r": 0, "deleted": 1}

    def test_a_cycle_in_bad_data_terminates(self) -> None:
        loop = _graph({"p": ["q"], "q": ["p"]})
        assert ancestors(loop, ["p"]) == {"p": 0, "q": 1}

    def test_accepts_an_iterable(self) -> None:
        assert ancestors(list(DAG.values()), ["c"]) == {"c": 0, "b": 1, "a": 2}


# ===========================================================================
# merge-base
# ===========================================================================


class TestMergeBase:
    def test_fork_point_of_two_branches(self) -> None:
        assert merge_base(DAG, "d", "y") == "b"

    def test_after_a_merge_the_merged_tip_is_the_base(self) -> None:
        assert merge_base(DAG, "m", "d") == "d"

    def test_ancestor_of_the_other_is_the_base(self) -> None:
        assert merge_base(DAG, "a", "d") == "a"
        assert merge_base(DAG, "d", "a") == "a"

    def test_same_revision(self) -> None:
        assert merge_base(DAG, "c", "c") == "c"

    def test_disjoint_histories_have_no_base(self) -> None:
        two_roots = _graph({"a": [], "b": ["a"], "r": [], "s": ["r"]})
        assert merge_base(two_roots, "b", "s") is None
        assert merge_base_candidates(two_roots, "b", "s") == []

    def test_disjoint_when_a_revision_is_unknown(self) -> None:
        assert merge_base(DAG, "d", "ghost") is None

    def test_two_root_revisions_are_disjoint(self) -> None:
        roots = _graph({"r1": [], "r2": []})
        assert merge_base(roots, "r1", "r2") is None

    def test_criss_cross_history_lists_both_and_picks_the_newest(self) -> None:
        #   b1 ─ m1 (merges c1)        a ─ b1, a ─ c1 ; m1 = (b1, c1) ; m2 = (c1, b1)
        #  /    ×
        # a ─ c1 ─ m2 (merges b1)
        criss = _graph({"a": [], "b1": ["a"], "c1": ["a"], "m1": ["b1", "c1"], "m2": ["c1", "b1"]})
        assert merge_base_candidates(criss, "m1", "m2") == ["c1", "b1"]
        assert merge_base(criss, "m1", "m2") == "c1"

    def test_a_tie_on_creation_time_resolves_by_id(self) -> None:
        same = {
            "a": RevisionNode("a"),
            "b1": RevisionNode("b1", parent_id="a", created_at=_T0),
            "c1": RevisionNode("c1", parent_id="a", created_at=_T0),
            "m1": RevisionNode("m1", parent_id="b1", merge_parent_id="c1"),
            "m2": RevisionNode("m2", parent_id="c1", merge_parent_id="b1"),
        }
        assert merge_base(same, "m1", "m2") == merge_base(same, "m2", "m1") == "c1"

    def test_string_and_naive_timestamps_are_ordered(self) -> None:
        nodes = {
            "a": RevisionNode("a"),
            "b1": RevisionNode("b1", parent_id="a", created_at="2026-01-02T00:00:00Z"),
            "c1": RevisionNode("c1", parent_id="a", created_at=datetime(2026, 1, 1)),
            "m1": RevisionNode("m1", parent_id="b1", merge_parent_id="c1"),
            "m2": RevisionNode("m2", parent_id="c1", merge_parent_id="b1"),
        }
        assert merge_base(nodes, "m1", "m2") == "b1"


# ===========================================================================
# history windows
# ===========================================================================


class TestHistoryWindow:
    def test_window_orders_by_distance_then_newest(self) -> None:
        window = history_window(DAG, ["m"], depth=10, limit=100)
        # y was created after d, and x after c: newest first within a distance.
        assert [n.revision_id for n in window.nodes] == ["m", "y", "d", "x", "c", "b", "a"]
        assert window.truncated is False

    def test_depth_truncates_and_says_so(self) -> None:
        window = history_window(DAG, ["m"], depth=1, limit=100)
        assert [n.revision_id for n in window.nodes] == ["m", "y", "d"]
        assert window.truncated is True

    def test_depth_reaching_a_root_is_not_truncated(self) -> None:
        assert history_window(DAG, ["d"], depth=3, limit=100).truncated is False

    def test_limit_keeps_the_nearest(self) -> None:
        window = history_window(DAG, ["m"], depth=10, limit=3)
        assert [n.revision_id for n in window.nodes] == ["m", "y", "d"]
        assert window.truncated is True
        assert window.distances == {"m": 0, "y": 1, "d": 1}

    def test_unknown_tip_and_dangling_parent_are_left_out(self) -> None:
        dangling = _graph({"r": ["deleted"]})
        window = history_window(dangling, ["r", "ghost"], depth=5, limit=10)
        assert [n.revision_id for n in window.nodes] == ["r"]
        assert window.truncated is False

    def test_bounds_are_clamped(self) -> None:
        long_line = _graph({f"r{i}": ([f"r{i - 1}"] if i else []) for i in range(MAX_HISTORY_DEPTH + 5)})
        tip = f"r{MAX_HISTORY_DEPTH + 4}"
        window = history_window(long_line, [tip], depth=10**6, limit=10**6)
        assert len(window.nodes) == MAX_HISTORY_DEPTH + 1 and window.truncated is True
        assert len(history_window(long_line, [tip], depth=5, limit=0).nodes) == 1
        assert MAX_HISTORY_LIMIT >= MAX_HISTORY_DEPTH

    def test_legacy_null_parent_rows_are_roots(self) -> None:
        legacy = _graph({"v1": [], "v2": [], "v3": []})
        window = history_window(legacy, ["v3", "v1"], depth=50, limit=50)
        assert {n.revision_id for n in window.nodes} == {"v1", "v3"}
        assert all(n.parents == () for n in window.nodes)
        assert merge_base(legacy, "v1", "v3") is None


# ===========================================================================
# Database methods
# ===========================================================================


def _row(rid: str, parent: Optional[str] = None, merge: Optional[str] = None, minute: int = 0) -> Dict[str, object]:
    return {
        "id": rid,
        "parent_version_id": parent,
        "merge_parent_version_id": merge,
        "created_at": _T0 + timedelta(minutes=minute),
        "version_id": f"1.{minute}.0",
    }


#: Valid v4 UUIDs — ``fetch_revision_closure`` ignores anything else (production ids are v4).
U = [f"00000000-0000-4000-8000-00000000000{i}" for i in range(8)]


class TestDatabaseClosure:
    def _db(self, rows: List[Dict[str, object]]) -> Database:
        db = Database.__new__(Database)
        db.execute_query = MagicMock(return_value=rows)  # type: ignore[method-assign]
        return db

    def test_one_recursive_query_for_the_closure(self) -> None:
        db = self._db([_row(U[1], U[0], minute=1), _row(U[0])])
        nodes = db.fetch_revision_closure([U[1], U[1], "not-a-uuid", ""], "t1")
        assert db.execute_query.call_count == 1
        sql, params = db.execute_query.call_args.args
        assert "WITH RECURSIVE" in sql and "UNION" in sql and "UNION ALL" not in sql
        assert "merge_parent_version_id" in sql and "deleted_at IS NULL" in sql
        assert params == ([U[1]], "t1", "t1")
        assert {n.revision_id: n.parent_id for n in nodes} == {U[1]: U[0], U[0]: None}
        assert nodes[0].version_label == "1.1.0"

    def test_no_valid_ids_skips_the_query(self) -> None:
        db = self._db([])
        assert db.fetch_revision_closure(["nope", ""], "t1") == []
        db.execute_query.assert_not_called()

    def test_collect_revision_ancestors_keeps_its_contract(self) -> None:
        db = self._db([_row(U[2], U[1], minute=2), _row(U[1], U[0], minute=1), _row(U[0])])
        assert db.collect_revision_ancestors(U[2], "t1") == {U[0], U[1], U[2]}
        assert db.execute_query.call_count == 1
        assert self._db([]).collect_revision_ancestors(U[5], "t1") == {U[5]}

    def test_compute_merge_base_revision_id(self) -> None:
        # U0 ─ U1 ─ U2 (main) ; U1 ─ U3 (feature)
        rows = [_row(U[0]), _row(U[1], U[0], minute=1), _row(U[2], U[1], minute=2), _row(U[3], U[1], minute=3)]
        db = self._db(rows)
        assert db.compute_merge_base_revision_id(U[2], U[3], "t1") == U[1]
        assert db.execute_query.call_count == 1

    def test_compute_merge_base_revision_id_disjoint(self) -> None:
        db = self._db([_row(U[0]), _row(U[4], minute=4)])
        assert db.compute_merge_base_revision_id(U[0], U[4], "t1") is None


# ===========================================================================
# REST routes
# ===========================================================================

client = TestClient(app)
_PROJECT = "00000000-0000-0000-0000-0000000000a1"
_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}


@pytest.fixture
def mdb():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    with (
        patch("app.revision_graph_routes.db") as mock_db,
        patch("app.revision_graph_routes.enforce_permission") as permission,
    ):
        mock_db.get_project_by_id.return_value = {"id": _PROJECT}
        mock_db.get_version_by_id.side_effect = lambda rid, tenant: (
            {"id": rid, "project_id": _PROJECT} if rid in DAG else None
        )
        mock_db.fetch_revision_closure.return_value = list(DAG.values())
        mock_db.permission = permission
        yield mock_db
    app.dependency_overrides.clear()


def _url(tail: str) -> str:
    return f"/v1/versions/acme/{_PROJECT}/{tail}"


class TestRoutes:
    def test_ancestors(self, mdb: MagicMock) -> None:
        response = client.get(_url("m/ancestors"), params={"depth": 1})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tips"] == ["m"] and body["depth"] == 1 and body["truncated"] is True
        assert [(n["revisionId"], n["distance"]) for n in body["nodes"]] == [("m", 0), ("y", 1), ("d", 1)]
        merge = body["nodes"][0]
        assert (merge["parentRevisionId"], merge["mergeParentRevisionId"], merge["versionLabel"]) == ("y", "d", "v-m")
        mdb.fetch_revision_closure.assert_called_once_with(["m"], "t1")
        assert mdb.permission.call_args.args[2:] == ("versions", "view")

    def test_ancestors_query_bounds_are_validated(self, mdb: MagicMock) -> None:
        assert client.get(_url("m/ancestors"), params={"depth": MAX_HISTORY_DEPTH + 1}).status_code == 422
        assert client.get(_url("m/ancestors"), params={"limit": 0}).status_code == 422

    def test_unknown_revision_and_other_project(self, mdb: MagicMock) -> None:
        response = client.get(_url("ghost/ancestors"))
        assert response.status_code == 404 and response.json()["detail"]["code"] == "REVISION_NOT_FOUND"
        mdb.get_version_by_id.side_effect = lambda rid, tenant: {"id": rid, "project_id": "other"}
        response = client.get(_url("m/ancestors"))
        assert response.status_code == 400 and response.json()["detail"]["code"] == "REVISION_PROJECT_MISMATCH"

    def test_unknown_project(self, mdb: MagicMock) -> None:
        mdb.get_project_by_id.return_value = None
        assert client.get(_url("m/ancestors")).status_code == 404

    def test_history_with_named_tips(self, mdb: MagicMock) -> None:
        response = client.get(_url("revision-graph/history"), params=[("tip", "d"), ("tip", "y"), ("tip", "d")])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tips"] == ["d", "y"]
        assert {n["revisionId"] for n in body["nodes"]} == {"d", "y", "c", "x", "b", "a"}
        mdb.fetch_revision_closure.assert_called_once_with(["d", "y"], "t1")

    def test_history_defaults_to_branch_tips(self, mdb: MagicMock) -> None:
        mdb.list_version_branches_for_project.return_value = [
            {"tip_version_id": "m"},
            {"tip_version_id": "d"},
            {"tip_version_id": None},
        ]
        body = client.get(_url("revision-graph/history")).json()
        assert body["tips"] == ["m", "d"]

    def test_history_without_tips_or_branches(self, mdb: MagicMock) -> None:
        mdb.list_version_branches_for_project.return_value = []
        response = client.get(_url("revision-graph/history"))
        assert response.status_code == 400 and response.json()["detail"]["code"] == "TIPS_REQUIRED"

    def test_history_rejects_too_many_tips(self, mdb: MagicMock) -> None:
        params = [("tip", f"t{i}") for i in range(51)]
        response = client.get(_url("revision-graph/history"), params=params)
        assert response.status_code == 400 and response.json()["detail"]["code"] == "TOO_MANY_TIPS"

    def test_merge_base(self, mdb: MagicMock) -> None:
        body = client.get(_url("revision-graph/merge-base"), params={"a": "d", "b": "y"}).json()
        assert body["mergeBase"]["revisionId"] == "b" and body["mergeBase"]["versionLabel"] == "v-b"
        assert body["candidates"] == ["b"] and body["disjoint"] is False
        mdb.fetch_revision_closure.assert_called_once_with(["d", "y"], "t1")

    def test_merge_base_disjoint(self, mdb: MagicMock) -> None:
        two_roots = _graph({"a": [], "r": []})
        mdb.get_version_by_id.side_effect = lambda rid, tenant: {"id": rid, "project_id": _PROJECT}
        mdb.fetch_revision_closure.return_value = list(two_roots.values())
        body = client.get(_url("revision-graph/merge-base"), params={"a": "a", "b": "r"}).json()
        assert body == {"a": "a", "b": "r", "mergeBase": None, "candidates": [], "disjoint": True}

    def test_merge_base_requires_both(self, mdb: MagicMock) -> None:
        assert client.get(_url("revision-graph/merge-base"), params={"a": "d"}).status_code == 422
