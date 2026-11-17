"""API products in the dependency graph — APX-1.1 (#6098).

A product is an ``api_product`` node with one derived ``includes`` edge per member
(:mod:`app.catalog_graph`). These tests pin, without a database:

* the ``includes`` family: product → Project / catalog item / MCP server, live products only;
* the blast radius treats ``includes`` as a dependency edge, so a breaking change in a member lists
  the product that bundles it (and, through it, nothing it does not depend on);
* the labeller names product nodes from the entity registry and the owner lookup reads a product's
  ``owner_team_id`` as its confirmed owner.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app import blast_radius as br
from app import catalog_graph as graph
from app import graph_nodes
from app.blast_radius import BlastRadiusRequest

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_PRODUCT = "33333333-3333-4333-8333-333333333333"
_CONSUMER = "44444444-4444-4444-8444-444444444444"


def test_api_product_is_a_node_kind_and_includes_an_edge_family() -> None:
    assert "api_product" in graph.NODE_KINDS and "includes" in graph.EDGE_KINDS
    assert "includes" in graph.FAMILIES
    sql = " ".join(graph._FAMILY_SQL["includes"].split())
    assert "FROM apiome.api_product_members m" in sql
    assert sql.count("ap.deleted_at IS NULL") == 2  # a deleted product's edges go stale
    assert "'mcp_endpoint'" in sql and "'api_product_member:' || m.id::text" in sql


def test_includes_is_a_dependency_edge_for_the_blast_radius() -> None:
    assert "includes" in br.DEPENDENCY_EDGES


class _EdgeDb:
    """Serves inbound edges from a list, as ``_inbound`` asks for them."""

    def __init__(self, edges: List[Dict[str, Any]]) -> None:
        self.edges = edges

    def execute_query(self, sql: str, params: Any = ()) -> List[Dict[str, Any]]:
        assert "FROM apiome.catalog_edges" in sql
        _tenant, ids, kinds, _provenances = params
        return [dict(e) for e in self.edges if e["to_id"] in ids and e["edge_kind"] in kinds]


def _edge(from_kind: str, from_id: str, to_kind: str, to_id: str, edge_kind: str) -> Dict[str, Any]:
    return {"from_kind": from_kind, "from_id": from_id, "to_kind": to_kind, "to_id": to_id,
            "edge_kind": edge_kind, "provenance": "derived" if edge_kind != "depends_on" else "declared",
            "pointer": None}


def test_a_breaking_change_in_a_member_lists_the_product() -> None:
    db = _EdgeDb([
        _edge("api_product", _PRODUCT, "project", _PROJECT, "includes"),
        # A consumer that declared a dependency on the product is reached through it.
        _edge("consumer", _CONSUMER, "api_product", _PRODUCT, "depends_on"),
    ])
    request = BlastRadiusRequest(kind="project", entity=_PROJECT, pointers=("/paths/~1pay/post",), depth=3)

    nodes, truncated, total = br._traverse(db, _TENANT, ("project", _PROJECT), request, contracts=[])

    product = nodes[_PRODUCT]
    assert (product.kind, product.depth, product.edge_kind) == ("api_product", 1, "includes")
    assert nodes[_CONSUMER].depth == 2 and nodes[_CONSUMER].path[0]["edge_kind"] == "includes"
    assert not truncated and total == 2


def test_product_nodes_are_labelled_from_the_registry() -> None:
    assert "FROM apiome.api_products e" in graph_nodes.label_sql()["api_product"]


def test_a_products_owner_team_is_read_as_its_confirmed_owner() -> None:
    seen: List[Any] = []

    class _Db:
        def execute_query(self, sql: str, params: Any = ()) -> List[Dict[str, Any]]:
            seen.append((" ".join(sql.split()), params))
            return [{"id": _PRODUCT, "slug": "payments", "name": "Payments", "status": "confirmed"}]

    owners = graph_nodes.node_owners(_Db(), _TENANT, [_PRODUCT, _PROJECT])

    assert owners[_PRODUCT] == {"slug": "payments", "name": "Payments", "status": "confirmed"}
    sql, params = seen[0]
    assert "FROM apiome.entity_owners eo" in sql and "FROM apiome.api_products ap" in sql
    assert "t.id = ap.owner_team_id" in sql
    assert params == (_TENANT, sorted([_PRODUCT, _PROJECT]), _TENANT, sorted([_PRODUCT, _PROJECT]))
