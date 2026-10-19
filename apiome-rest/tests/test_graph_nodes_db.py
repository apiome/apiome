"""Graph node labels and the tenant-wide entity search against a live Postgres — CDG-3.4 (#5969).

Uses the CDG-3.3 golden ``petstore`` fixture (``test_blast_radius_db``): its consumers' current
contracts become ``consumes`` edges once materialized, and ``reporting`` declared ``depends_on`` the
``web`` consumer.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.catalog_graph import list_edges, materialize_on_cursor
from app.graph_nodes import label_nodes, node_labels_with_owners, search_entities
from tests.test_blast_radius_db import petstore  # noqa: F401 - the fixture
from tests.test_catalog_graph_db import tx  # noqa: F401 - the fixture

pytestmark = pytest.mark.requires_db


@pytest.fixture
def graph(petstore) -> Dict[str, Any]:  # noqa: F811 - the imported fixture
    materialize_on_cursor(petstore["cursor"], petstore["tenant"])
    cursor = petstore["cursor"]
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s, 'payments', 'Payments') RETURNING id::text AS id",
        (petstore["tenant"],),
    )
    team = cursor.fetchone()["id"]
    cursor.execute(
        """INSERT INTO apiome.entity_owners (tenant_id, entity_kind, entity_id, team_id, status, source, confirmed_at)
           VALUES (%s, 'consumer', %s, %s, 'confirmed', 'manual', now())""",
        (petstore["tenant"], petstore["consumers"]["web"], team),
    )
    return petstore


def test_labels_and_owners_for_both_ends(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    page = list_edges(db, tenant, "project", graph["project"], direction="in")
    refs = sorted({(e["from_kind"], e["from_id"]) for e in page.edges} | {("project", graph["project"])})
    info = node_labels_with_owners(db, tenant, refs)
    assert info[graph["project"]]["slug"] == "petstore"
    assert info[graph["consumers"]["web"]] == {"name": "Web", "slug": "web",
                                               "owner": {"slug": "payments", "name": "Payments", "status": "confirmed"}}
    assert info[graph["consumers"]["mobile"]]["owner"] is None
    assert label_nodes(db, tenant, [("identity_group", graph["project"])])[graph["project"]]["name"] == "Identity group"


def test_search_lists_connected_entities_most_connected_first(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    page = search_entities(db, tenant)
    assert page.entities[0]["slug"] == "petstore" and page.entities[0]["kind"] == "project"
    by_slug = {e["slug"]: e for e in page.entities}
    assert by_slug["petstore"]["in_count"] >= 4
    assert (by_slug["web"]["in_count"], by_slug["web"]["out_count"]) == (1, 1)
    assert by_slug["reporting"]["out_count"] == 1
    assert page.truncated is False and page.total == len(page.entities)


def test_search_filters(graph) -> None:
    db, tenant = graph["db"], graph["tenant"]
    assert [e["slug"] for e in search_entities(db, tenant, query="WEB").entities] == ["web"]
    assert [e["slug"] for e in search_entities(db, tenant, team="payments").entities] == ["web"]
    assert {e["kind"] for e in search_entities(db, tenant, kinds=("consumer",)).entities} == {"consumer"}
    declared = search_entities(db, tenant, provenances=("declared",))
    assert sorted(e["slug"] for e in declared.entities) == ["reporting", "web"]
    first = search_entities(db, tenant, limit=2)
    assert len(first.entities) == 2 and first.truncated is True and first.total > 2
