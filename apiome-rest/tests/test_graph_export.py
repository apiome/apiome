"""Graph export renderers and route — CDG-3.6 (#5971).

Pure tests: the JSON and DOT renderers over a hand-built export, DOT escaping, the truncation
marker, and ``GET /v1/graph/{t}/export`` with :func:`app.graph_export.export_graph` replaced.
``test_graph_export_db.py`` exports a real graph.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.catalog_graph import GraphValidationError
from app.graph_export import EXPORT_FORMAT, MAX_EXPORT_EDGES, GraphExport, parse_entity, render_dot, render_json
from app.main import app

client = TestClient(app)

P = "11111111-1111-4111-8111-111111111111"
C = "22222222-2222-4222-8222-222222222222"


def _edge(**overrides: Any) -> Dict[str, Any]:
    edge = {
        "id": "e1",
        "from_kind": "consumer",
        "from_id": C,
        "to_kind": "project",
        "to_id": P,
        "edge_kind": "consumes",
        "pointer": "/paths/~1pets/get",
        "provenance": "derived",
        "source_ref": "consumer_contract:x",
        "first_seen_at": "2026-10-18T00:00:00+00:00",
        "last_seen_at": "2026-10-18T00:00:00+00:00",
        "stale_since": None,
        "stale": False,
    }
    edge.update(overrides)
    return edge


def _export(truncated: bool = False, **edge_overrides: Any) -> GraphExport:
    return GraphExport(
        nodes=[
            {
                "kind": "consumer",
                "id": C,
                "name": 'Web "app"',
                "slug": "web",
                "owner": {"slug": "payments", "name": "Payments"},
            },
            {"kind": "project", "id": P, "name": None, "slug": "petstore", "owner": None},
        ],
        edges=[_edge(**edge_overrides)],
        truncated=truncated,
        filters={"kind": [], "team": None, "provenance": [], "stale": True, "entity": None, "depth": None},
    )


MOMENT = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def test_json_is_one_document() -> None:
    document = json.loads("".join(render_json(_export(), tenant="acme", generated_at=MOMENT)))
    assert document["format"] == EXPORT_FORMAT == "apiome.graph.export/v1"
    assert (document["tenant"], document["generated_at"]) == ("acme", "2026-10-18T12:00:00Z")
    assert (document["node_count"], document["edge_count"], document["truncated"]) == (2, 1, False)
    assert document["limit"] == MAX_EXPORT_EDGES
    assert document["nodes"][0]["owner"]["slug"] == "payments"
    assert document["edges"][0]["pointer"] == "/paths/~1pets/get"


def test_json_streams_a_node_or_edge_per_chunk() -> None:
    chunks = list(render_json(_export(), tenant="acme", generated_at=MOMENT))
    assert len(chunks) == 6  # head, 2 nodes, separator, 1 edge, tail
    assert chunks[-1] == "\n]}\n"


def test_json_of_an_empty_export() -> None:
    empty = GraphExport(nodes=[], edges=[], truncated=False, filters={})
    document = json.loads("".join(render_json(empty, tenant="acme")))
    assert document["nodes"] == [] and document["edges"] == []


def test_json_is_deterministic_for_a_fixed_time() -> None:
    a = "".join(render_json(_export(), tenant="acme", generated_at=MOMENT))
    b = "".join(render_json(_export(), tenant="acme", generated_at=MOMENT))
    assert a == b


def test_dot_draws_nodes_and_edges() -> None:
    dot = "".join(render_dot(_export(), tenant="acme"))
    assert dot.startswith("// apiome graph export: 2 nodes, 1 edges\ndigraph apiome {\n")
    assert dot.rstrip().endswith("}")
    # Quotes in names are escaped; the owner team is named; a node without a name uses its slug.
    assert f'"consumer:{C}" [label="Web \\"app\\"\\nconsumer · payments", kind="consumer", owner="payments"];' in dot
    assert f'"project:{P}" [label="petstore\\nproject", kind="project"];' in dot
    assert f'"consumer:{C}" -> "project:{P}" [label="consumes\\n/paths/~1pets/get", provenance="derived"];' in dot


@pytest.mark.parametrize(
    "overrides, style",
    [
        ({"stale": True, "stale_since": "x"}, 'style="dashed", color="gray"'),
        ({"provenance": "declared"}, 'style="bold"'),
        ({"provenance": "runtime"}, 'style="dotted"'),
    ],
)
def test_dot_styles_edges_by_state(overrides: Dict[str, Any], style: str) -> None:
    assert style in "".join(render_dot(_export(**overrides), tenant="acme"))


def test_dot_says_when_it_was_truncated() -> None:
    first = next(iter(render_dot(_export(truncated=True), tenant="acme")))
    assert first == f"// apiome graph export: 2 nodes, 1 edges; truncated at {MAX_EXPORT_EDGES} edges\n"


def test_dot_escapes_backslashes_and_line_breaks() -> None:
    export = _export(pointer="/a\\b\r\nc")
    dot = "".join(render_dot(export, tenant='ac"me'))
    assert 'label="consumes\\n/a\\\\b\\nc"' in dot
    assert 'label="Apiome dependency graph: ac\\"me"' in dot


def test_parse_entity() -> None:
    assert parse_entity(f"project:{P}") == ("project", P)
    for bad in ("project", "planet:1", "project:", ""):
        with pytest.raises(GraphValidationError):
            parse_entity(bad)


# ---------------------------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def mock_auth():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _get(query: str, *, allowed: bool = True, export: Any = None):
    with (
        patch("app.graph_routes.db") as mock_db,
        patch("app.graph_routes.export_graph", return_value=export or _export()) as fake,
    ):
        mock_db.user_has_permission.return_value = allowed
        response = client.get(f"/v1/graph/acme/export{query}", headers={"Authorization": "Bearer x"})
    return response, fake


def test_route_defaults_to_json(mock_auth) -> None:
    r, fake = _get("")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"] == 'attachment; filename="acme-graph.json"'
    assert r.json()["edge_count"] == 1
    assert fake.call_args.args[1] == "tenant-1"
    assert fake.call_args.kwargs == {
        "kinds": (),
        "team": None,
        "provenances": (),
        "include_stale": True,
        "entity": None,
        "depth": 2,
    }


def test_route_writes_dot(mock_auth) -> None:
    r, _ = _get("?format=dot")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/vnd.graphviz")
    assert r.headers["content-disposition"] == 'attachment; filename="acme-graph.dot"'
    assert "digraph apiome {" in r.text


def test_route_passes_the_filters(mock_auth) -> None:
    r, fake = _get(
        f"?kind=consumer&kind=project&team=payments&provenance=declared&stale=false&entity=project:{P}&depth=3"
    )
    assert r.status_code == 200
    assert fake.call_args.kwargs == {
        "kinds": ("consumer", "project"),
        "team": "payments",
        "provenances": ("declared",),
        "include_stale": False,
        "entity": f"project:{P}",
        "depth": 3,
    }


@pytest.mark.parametrize("query", ["?format=svg", "?depth=0", "?depth=6"])
def test_route_refuses_bad_parameters(mock_auth, query: str) -> None:
    r, fake = _get(query)
    assert r.status_code in (400, 422)
    fake.assert_not_called()


def test_route_maps_validation_errors_to_400(mock_auth) -> None:
    with (
        patch("app.graph_routes.db") as mock_db,
        patch(
            "app.graph_routes.export_graph",
            side_effect=GraphValidationError("graph-invalid", "unknown filter values: x"),
        ),
    ):
        mock_db.user_has_permission.return_value = True
        r = client.get("/v1/graph/acme/export?kind=x", headers={"Authorization": "Bearer x"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "graph-invalid"


def test_route_requires_projects_view(mock_auth) -> None:
    r, fake = _get("", allowed=False)
    assert r.status_code == 403
    fake.assert_not_called()
