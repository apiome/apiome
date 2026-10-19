"""Graph export and the diff-gate blast-radius line against a live Postgres — CDG-3.6 (#5971).

Uses the CDG-3.3 golden ``petstore`` fixture (``test_blast_radius_db``): materialized, its consumers'
contracts become ``consumes`` edges and ``reporting`` declared ``depends_on`` the ``web`` consumer.
Runs in one always-rolled-back transaction.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from app.catalog_graph import GraphValidationError, materialize_on_cursor
from app.diff_blast_radius import annotate_breaking_changes
from app.graph_export import export_graph, render_dot, render_json
from tests.test_blast_radius_db import petstore  # noqa: F401 - the fixture
from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db

_OP = "/paths/~1pets~1{petId}/get"


@pytest.fixture
def graph(petstore) -> Dict[str, Any]:  # noqa: F811 - the imported fixture
    """Petstore with its edges materialized; ``web`` and ``reporting`` owned by ``payments``."""
    cursor = petstore["cursor"]
    materialize_on_cursor(cursor, petstore["tenant"])
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s, 'payments', 'Payments') RETURNING id::text AS id",
        (petstore["tenant"],),
    )
    team = cursor.fetchone()["id"]
    for slug in ("web", "reporting"):
        cursor.execute(
            """INSERT INTO apiome.entity_owners
                   (tenant_id, entity_kind, entity_id, team_id, status, source, confirmed_at)
               VALUES (%s, 'consumer', %s, %s, 'confirmed', 'manual', now())""",
            (petstore["tenant"], petstore["consumers"][slug], team),
        )
    return petstore


def _edge_count(graph: Dict[str, Any], where: str = "true") -> int:
    graph["cursor"].execute(
        f"SELECT count(*) AS n FROM apiome.catalog_edges WHERE tenant_id = %s AND {where}", (graph["tenant"],)
    )
    return int(graph["cursor"].fetchone()["n"])


def test_the_whole_tenant_exports_every_edge_with_labelled_nodes(graph) -> None:
    export = export_graph(graph["db"], graph["tenant"])
    assert len(export.edges) == _edge_count(graph) > 0
    assert export.truncated is False
    ids = {node["id"] for node in export.nodes}
    assert graph["project"] in ids and graph["consumers"]["reporting"] in ids
    project = next(node for node in export.nodes if node["id"] == graph["project"])
    assert (project["kind"], project["name"], project["slug"]) == ("project", "Petstore", "petstore")
    web = next(node for node in export.nodes if node["id"] == graph["consumers"]["web"])
    assert web["owner"]["slug"] == "payments"
    # Every edge end is a node, and every node is an edge end.
    ends = {e["from_id"] for e in export.edges} | {e["to_id"] for e in export.edges}
    assert ends == ids


def test_exports_are_stable(graph) -> None:
    first = export_graph(graph["db"], graph["tenant"])
    second = export_graph(graph["db"], graph["tenant"])
    assert first == second


def test_the_bound_truncates(graph) -> None:
    export = export_graph(graph["db"], graph["tenant"], max_edges=2)
    assert len(export.edges) == 2 and export.truncated is True


def test_filters(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    declared = export_graph(db, tenant, provenances=("declared",))
    assert {e["provenance"] for e in declared.edges} == {"declared"}
    assert len(declared.edges) == _edge_count(graph, "provenance = 'declared'")

    owned = export_graph(db, tenant, team="payments")
    owned_ids = {graph["consumers"]["web"], graph["consumers"]["reporting"]}
    assert owned.edges and all({e["from_id"], e["to_id"]} & owned_ids for e in owned.edges)
    assert export_graph(db, tenant, team="nobody").edges == []

    projects = export_graph(db, tenant, kinds=("project",))
    assert projects.edges and all("project" in (e["from_kind"], e["to_kind"]) for e in projects.edges)

    graph["cursor"].execute(
        "UPDATE apiome.catalog_edges SET stale_since = now() WHERE tenant_id = %s AND from_id = %s",
        (tenant, graph["consumers"]["mobile"]),
    )
    with_stale = export_graph(db, tenant)
    current = export_graph(db, tenant, include_stale=False)
    assert any(e["stale"] for e in with_stale.edges)
    assert not any(e["stale"] for e in current.edges)
    assert len(current.edges) < len(with_stale.edges)
    # Stale edges come last.
    flags = [e["stale"] for e in with_stale.edges]
    assert flags == sorted(flags)


def test_a_neighbourhood_walks_depth_hops_both_ways(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    reporting = graph["consumers"]["reporting"]
    one = export_graph(db, tenant, entity=f"consumer:{reporting}", depth=1)
    # One hop: only reporting → web.
    assert [(e["edge_kind"], e["to_id"]) for e in one.edges] == [("depends_on", graph["consumers"]["web"])]
    two = export_graph(db, tenant, entity=f"consumer:{reporting}", depth=2)
    # Two hops reach web's own consumes edges into the project.
    assert any(e["edge_kind"] == "consumes" and e["to_id"] == graph["project"] for e in two.edges)
    assert len(two.edges) > len(one.edges)
    assert two.filters["entity"] == f"consumer:{reporting}" and two.filters["depth"] == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kinds": ("planet",)},
        {"provenances": ("guessed",)},
        {"entity": "planet:1"},
        {"entity": "consumer"},
        {"depth": 0},
        {"depth": 6},
        {"max_edges": 0},
        {"max_edges": 10_001},
    ],
)
def test_bad_filters_are_refused(graph, kwargs) -> None:
    with pytest.raises(GraphValidationError):
        export_graph(graph["db"], graph["tenant"], **kwargs)


def test_renderers_write_the_export(graph) -> None:
    export = export_graph(graph["db"], graph["tenant"])
    document = json.loads("".join(render_json(export, tenant="petstore-co")))
    assert document["edge_count"] == len(export.edges) and len(document["edges"]) == len(export.edges)
    dot = "".join(render_dot(export, tenant="petstore-co"))
    assert dot.count(" -> ") == len(export.edges)
    assert f'"project:{graph["project"]}"' in dot


# ---------------------------------------------------------------------------------------------
# The diff-gate line over the CDG-3.3 golden answer
# ---------------------------------------------------------------------------------------------


def test_the_golden_breaking_change_gets_its_line(graph) -> None:
    changes = [SimpleNamespace(pointer=_OP, severity="breaking")]
    result = annotate_breaking_changes(graph["db"], graph["tenant"], graph["project"], graph["version"], changes)
    summary = result.by_pointer[_OP]
    # CDG-3.3 golden: three direct consumers, reporting transitively, two latest runs invalidated.
    assert summary.consumers == 4
    assert [team.slug for team in summary.teams] == ["payments"]
    assert summary.verification_runs == 2
    assert summary.line == "affects 4 consumers across 1 team (payments); 2 verification runs invalidated"


def test_a_change_nobody_depends_on_says_so(graph) -> None:
    changes = [SimpleNamespace(pointer="/paths/~1nobody/get", severity="breaking")]
    result = annotate_breaking_changes(graph["db"], graph["tenant"], graph["project"], graph["version"], changes)
    assert result.by_pointer["/paths/~1nobody/get"].line == (
        "affects no registered consumers; no verification runs invalidated"
    )
