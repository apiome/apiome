"""The catalog graph without a database — CDG-3.1 (#5966).

* The read's bounds: unknown kinds, directions and filters are ``graph-invalid``; ``limit`` is
  1..500; ``truncated`` says whether more edges match.
* The producers' hooks: in-transaction work runs under a savepoint and never fails the producer;
  post-write refreshes skip bad tenants and swallow faults; identity links, MCP sources and the
  conversion back-fill refresh their family.
* The nightly sweep: one replica at a time, every tenant, one failure never stops the rest.
* The route and its permission, and the migration's shape.

The behaviour against real rows (idempotency, pointer counts, CTG-4.2 parity, staleness) is in
``test_catalog_graph_db.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import catalog_graph as graph
from app import graph_routes as routes
from app.auth import validate_authentication
from app.catalog_graph import FAMILIES, MAX_READ_LIMIT, EdgePage, GraphValidationError, list_edges, sweep
from app.database import Database
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_ENTITY = "22222222-2222-4222-8222-222222222222"
_USER = "33333333-3333-4333-8333-333333333333"


class _Rows:
    """A db double whose ``execute_query`` answers from a queue and records every call."""

    def __init__(self, *answers: List[Dict[str, Any]]) -> None:
        self.answers = list(answers)
        self.calls: List[tuple] = []

    def execute_query(self, sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
        self.calls.append((sql, params))
        return self.answers.pop(0) if self.answers else []


def _edge(**overrides: Any) -> Dict[str, Any]:
    row = {
        "id": "e1", "from_kind": "consumer", "from_id": _ENTITY, "to_kind": "project", "to_id": _TENANT,
        "edge_kind": "consumes", "pointer": "/paths/~1a", "provenance": "derived", "source_ref": "consumer_contract:c1",
        "evidence": {}, "first_seen_at": None, "last_seen_at": None, "stale_since": None, "total": 3,
    }
    return {**row, **overrides}


# ---------------------------------------------------------------------------------------------
# the read
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "galaxy"},
        {"direction": "sideways"},
        {"edge_kinds": ("likes",)},
        {"provenances": ("rumoured",)},
        {"limit": 0},
        {"limit": MAX_READ_LIMIT + 1},
    ],
)
def test_a_malformed_read_is_graph_invalid_before_any_query(kwargs) -> None:
    db = _Rows()
    call = {"kind": "project", **kwargs}
    kind = call.pop("kind")
    with pytest.raises(GraphValidationError) as raised:
        list_edges(db, _TENANT, kind, _ENTITY, **call)
    assert raised.value.code == "graph-invalid"
    assert db.calls == []


def test_a_page_reports_truncation_and_flags_stale_edges() -> None:
    db = _Rows([_edge(), _edge(id="e2", stale_since="2026-10-01T00:00:00+00:00")])
    page = list_edges(db, _TENANT, "consumer", _ENTITY, limit=2)
    assert (page.total, page.truncated) == (3, True)
    assert [edge["stale"] for edge in page.edges] == [False, True]
    assert "total" not in page.edges[0]
    sql, params = db.calls[0]
    assert "from_kind = ANY" in sql and params[1] == ["consumer"]


def test_a_projects_row_matches_either_node_kind_and_filters_apply() -> None:
    db = _Rows([_edge(total=1)])
    page = list_edges(
        db, _TENANT, "catalog_item", _ENTITY, direction="in", edge_kinds=("consumes",), provenances=("derived",)
    )
    assert (page.total, page.truncated) == (1, False)
    sql, params = db.calls[0]
    assert "to_kind = ANY" in sql and params[1] == ["project", "catalog_item"]
    assert params[3] == ["consumes"] and params[4] == ["derived"]


def test_paging_past_the_end_still_counts() -> None:
    db = _Rows([], [{"total": 4}])
    page = list_edges(db, _TENANT, "project", _ENTITY, offset=10)
    assert (page.edges, page.total, page.truncated) == ([], 4, False)
    assert "count(*)" in db.calls[1][0]


# ---------------------------------------------------------------------------------------------
# the producers' hooks
# ---------------------------------------------------------------------------------------------


class _Cursor:
    def __init__(self) -> None:
        self.executed: List[str] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append(" ".join(sql.split()))


def test_the_in_transaction_hook_runs_under_a_savepoint(monkeypatch) -> None:
    seen: List[tuple] = []
    monkeypatch.setattr(graph, "materialize_on_cursor", lambda cursor, tenant, fams: seen.append((tenant, fams)))
    cursor = _Cursor()
    Database._materialize_graph(cursor, _TENANT, ("consumes",))
    assert seen == [(_TENANT, ("consumes",))]
    assert cursor.executed == ["SAVEPOINT catalog_graph", "RELEASE SAVEPOINT catalog_graph"]


def test_a_graph_fault_rolls_back_to_the_savepoint_and_never_fails_the_producer(monkeypatch) -> None:
    def _boom(cursor, tenant, families):
        raise RuntimeError("graph down")

    monkeypatch.setattr(graph, "materialize_on_cursor", _boom)
    cursor = _Cursor()
    Database._materialize_graph(cursor, _TENANT, ("served_by",))
    assert cursor.executed == ["SAVEPOINT catalog_graph", "ROLLBACK TO SAVEPOINT catalog_graph"]


@pytest.mark.parametrize("tenant", [None, "", "t1"])
def test_hooks_skip_a_tenant_that_is_not_an_id(monkeypatch, tenant) -> None:
    monkeypatch.setattr(graph, "materialize", lambda *a, **k: pytest.fail("should not materialize"))
    cursor = _Cursor()
    Database._materialize_graph(cursor, tenant, ("consumes",))
    Database().refresh_graph(tenant, ("consumes",), trigger="test")
    assert cursor.executed == []


def test_a_post_write_refresh_swallows_faults(monkeypatch) -> None:
    calls: List[tuple] = []

    def _materialize(db, tenant, trigger, families):
        calls.append((tenant, trigger, families))
        raise RuntimeError("graph down")

    monkeypatch.setattr(graph, "materialize", _materialize)
    Database().refresh_graph(_TENANT, ("identity_of",), trigger="identity_link")
    assert calls == [(_TENANT, "identity_link", ("identity_of",))]


def _recording_db(monkeypatch) -> tuple:
    db = Database()
    refreshed: List[tuple] = []
    monkeypatch.setattr(db, "refresh_graph", lambda tenant, fams, *, trigger: refreshed.append((tenant, fams, trigger)))
    return db, refreshed


def test_identity_link_and_unlink_refresh_identity_edges(monkeypatch) -> None:
    db, refreshed = _recording_db(monkeypatch)
    monkeypatch.setattr(db, "_link_identity_projects_once", lambda **kw: "group-1")
    monkeypatch.setattr(db, "_unlink_identity_projects_once", lambda **kw: None)
    group = db.link_identity_projects(tenant_id=_TENANT, project_id_a="a", project_id_b="b", created_by=None)
    assert group == "group-1"
    db.unlink_identity_projects(tenant_id=_TENANT, project_id="a", related_project_id="b")
    assert refreshed == [
        (_TENANT, ("identity_of",), "identity_link"),
        (_TENANT, ("identity_of",), "identity_unlink"),
    ]


def test_a_failed_identity_link_refreshes_nothing(monkeypatch) -> None:
    db, refreshed = _recording_db(monkeypatch)

    def _refuse(**kw):
        raise ValueError("Cannot link a project to itself")

    monkeypatch.setattr(db, "_link_identity_projects_once", _refuse)
    with pytest.raises(ValueError):
        db.link_identity_projects(tenant_id=_TENANT, project_id_a="a", project_id_b="a", created_by=None)
    assert refreshed == []


def test_the_conversion_back_fill_refreshes_once(monkeypatch) -> None:
    db, refreshed = _recording_db(monkeypatch)
    pairs = [{"source_project_id": f"s{i}", "target_project_id": f"t{i}"} for i in range(3)]
    monkeypatch.setattr(db, "execute_query", lambda sql, params=None: pairs)
    groups: Dict[str, str] = {}
    monkeypatch.setattr(db, "get_identity_group_id_for_project", lambda tenant, pid: groups.get(pid))

    def _link(**kw):
        groups[kw["project_id_a"]] = groups[kw["project_id_b"]] = "g"

    monkeypatch.setattr(db, "_link_identity_projects_once", _link)
    assert db.seed_identity_from_conversion_provenance(_TENANT) == 3
    assert refreshed == [(_TENANT, ("identity_of",), "identity_seed")]


def test_mcp_source_link_and_retire_refresh_built_from(monkeypatch) -> None:
    db, refreshed = _recording_db(monkeypatch)
    monkeypatch.setattr(db, "_create_mcp_endpoint_source_once", lambda **kw: {"id": "s1"})
    assert db.create_mcp_endpoint_source(tenant_id=_TENANT, endpoint_id="e", source={}, linked_by=None) == {"id": "s1"}
    monkeypatch.setattr(db, "execute_query", lambda sql, params=None: [{"id": "s1", "tenant_id": _TENANT}])
    assert db.retire_mcp_endpoint_source("e", "s1") is True
    monkeypatch.setattr(db, "execute_query", lambda sql, params=None: [])
    assert db.retire_mcp_endpoint_source("e", "s1") is False
    assert refreshed == [
        (_TENANT, ("built_from",), "mcp_source_link"),
        (_TENANT, ("built_from",), "mcp_source_retire"),
    ]


# ---------------------------------------------------------------------------------------------
# the nightly sweep
# ---------------------------------------------------------------------------------------------


def test_the_sweep_skips_when_another_replica_holds_the_lock(monkeypatch) -> None:
    monkeypatch.setattr(graph, "materialize", lambda *a, **k: pytest.fail("should not materialize"))
    db = _Rows([{"locked": False}])
    assert sweep(db) == {"tenants": 0, "failed": 0}
    assert len(db.calls) == 1


def test_the_sweep_materializes_every_tenant_and_survives_one_failure(monkeypatch) -> None:
    done: List[tuple] = []

    def _materialize(db, tenant, trigger, families=None):
        if tenant == "b":
            raise RuntimeError("tenant b is broken")
        done.append((tenant, trigger, families))

    monkeypatch.setattr(graph, "materialize", _materialize)
    db = _Rows([{"locked": True}], [{"id": "a"}, {"id": "b"}, {"id": "c"}], [{"unlocked": True}])
    assert sweep(db) == {"tenants": 2, "failed": 1}
    assert done == [("a", "sweep", None), ("c", "sweep", None)]
    assert "pg_advisory_unlock" in db.calls[-1][0]


def test_every_family_is_materialized_in_a_fixed_order() -> None:
    assert FAMILIES == ("consumes", "converted_from", "identity_of", "built_from", "deployed_on", "served_by")
    with pytest.raises(ValueError, match="runtime_calls"):  # runtime edges belong to RDG-1.x, not here
        graph.materialize_on_cursor(_Cursor(), _TENANT, ("runtime_calls",))


# ---------------------------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return True

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app), asked
    app.dependency_overrides.clear()


_URL = f"/v1/graph/acme/entities/project/{_ENTITY}/edges"


def test_the_route_reads_one_page_with_its_filters(client, monkeypatch) -> None:
    http, asked = client
    seen: Dict[str, Any] = {}

    def _list(db, tenant, kind, entity, **kwargs):
        seen.update(tenant=tenant, kind=kind, entity=entity, **kwargs)
        edge = {k: v for k, v in _edge().items() if k != "total"}
        return EdgePage(edges=[{**edge, "stale": False}], total=3, truncated=True)

    monkeypatch.setattr(routes, "list_edges", _list)
    response = http.get(
        _URL, params=[("direction", "in"), ("kind", "consumes"), ("kind", "served_by"), ("provenance", "derived"),
                      ("limit", "1"), ("offset", "2")],
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["truncated"], body["limit"], body["offset"]) == (3, True, 1, 2)
    assert body["edges"][0]["edge_kind"] == "consumes" and body["edges"][0]["stale"] is False
    assert seen == {
        "tenant": _TENANT, "kind": "project", "entity": _ENTITY, "direction": "in",
        "edge_kinds": ("consumes", "served_by"), "provenances": ("derived",), "limit": 1, "offset": 2,
    }
    assert asked == ["projects:view"]


def test_the_route_refuses_bad_input(client, monkeypatch) -> None:
    http, _ = client
    assert http.get(_URL, params={"limit": MAX_READ_LIMIT + 1}).status_code == 422
    assert http.get("/v1/graph/acme/entities/project/not-an-id/edges").json()["detail"]["code"] == "graph-invalid"

    def _invalid(*a, **k):
        raise GraphValidationError("graph-invalid", "unknown node kind 'galaxy'")

    monkeypatch.setattr(routes, "list_edges", _invalid)
    response = http.get(f"/v1/graph/acme/entities/galaxy/{_ENTITY}/edges")
    assert response.status_code == 400 and response.json()["detail"]["code"] == "graph-invalid"


def test_the_route_needs_projects_view(client, monkeypatch) -> None:
    http, _ = client
    monkeypatch.setattr(routes.db, "user_has_permission", lambda *a: False)
    assert http.get(_URL).status_code == 403


# ---------------------------------------------------------------------------------------------
# the migration
# ---------------------------------------------------------------------------------------------


def test_migration(repo_root) -> None:
    text = (repo_root / "apiome-db/scripts/V288__catalog_edges_cdg_3_1.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS catalog_edges" in text or "CREATE TABLE catalog_edges" in text
    assert "UNIQUE NULLS NOT DISTINCT" in text
    for column in ("tenant_id", "from_kind", "from_id", "to_kind", "to_id", "edge_kind", "pointer", "provenance",
                   "source_ref"):
        assert column in text.split("UNIQUE NULLS NOT DISTINCT", 1)[1].split(")", 1)[0]
    for index in ("idx_catalog_edges_from", "idx_catalog_edges_to", "idx_catalog_edges_pointer"):
        assert index in text
    for provenance in ("'declared'", "'derived'", "'runtime'"):
        assert provenance in text
