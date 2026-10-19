"""Tests for ``apiome graph declare|dependencies`` (CDG-3.2 / #5967)."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client import api_paths
from apiome_cli.client.graph import (
    dependency_rows,
    evidence_rows,
    impact_rows,
    operation_pointer,
    parse_depends_on,
    schema_pointer,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner(env={"COLUMNS": "200"})

_DEPS = "http://localhost:8000/v1/graph/acme-corp/entities/project/orders/dependencies"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _body() -> dict:
    return {
        "kind": "project",
        "entity_id": "p1",
        "declared": [
            {
                "id": "e1", "from_kind": "project", "from_id": "p1", "to_kind": "project", "to_id": "p2",
                "edge_kind": "depends_on", "pointer": "/components/schemas/Card", "provenance": "declared",
                "source_ref": "manual", "evidence": {"reference": "payments#/components/schemas/Card"},
                "stale": False,
            }
        ],
        "unresolved": [
            {"source_ref": "spec", "reference": "ledger", "pointer": None, "edge_kind": "depends_on",
             "reason": "not-found"}
        ],
        "truncated": False,
    }


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec,entry",
    [
        ("payments", {"to": {"slug": "payments"}}),
        ("payments#/components/schemas/Card", {"to": {"slug": "payments"}, "pointer": "/components/schemas/Card"}),
        ("consumer:c1", {"to": {"kind": "consumer", "id": "c1"}}),
        ("catalog-item:x#/paths", {"to": {"kind": "catalog_item", "id": "x"}, "pointer": "/paths"}),
    ],
)
def test_parse_depends_on(spec: str, entry: dict) -> None:
    assert parse_depends_on(spec) == entry


@pytest.mark.parametrize("spec", ["", "#/paths", "galaxy:1", "consumer:", "payments#paths"])
def test_parse_depends_on_refuses(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_depends_on(spec)


def test_a_note_rides_on_the_entry() -> None:
    assert parse_depends_on("payments", note="card capture")["note"] == "card capture"


def test_rows_list_declared_then_unresolved() -> None:
    rows = dependency_rows(_body())
    assert [row["status"] for row in rows] == ["declared", "unresolved: not-found"]
    assert rows[0]["target"] == "payments#/components/schemas/Card" and rows[0]["source"] == "manual"
    assert rows[1]["target"] == "ledger" and rows[1]["source"] == "spec"


def test_path_builder_quotes_segments() -> None:
    assert api_paths.graph_dependencies("acme", "project", "a/b").endswith("/entities/project/a%2Fb/dependencies")


# ---------------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------------


def test_declare_puts_the_complete_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="PUT", url=_DEPS, json=_body())
    result = runner.invoke(
        app,
        ["graph", "declare", "project", "orders", "--depends-on", "payments#/components/schemas/Card",
         "--depends-on", "ledger", "--note", "checkout"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent == {
        "dependencies": [
            {"to": {"slug": "payments"}, "pointer": "/components/schemas/Card", "note": "checkout"},
            {"to": {"slug": "ledger"}, "note": "checkout"},
        ]
    }
    output = strip_ansi(result.output)
    assert "now declares 2 manual dependencies; 1 unresolved." in output
    assert "unresolved: not-found" in output


def test_declare_clear_sends_an_empty_list(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="PUT", url=_DEPS, json={**_body(), "declared": [], "unresolved": []})
    result = runner.invoke(app, ["graph", "declare", "project", "orders", "--clear", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(httpx_mock.get_requests()[0].content) == {"dependencies": []}
    assert json.loads(result.stdout)["declared"] == []


@pytest.mark.parametrize(
    "args",
    [
        ["graph", "declare", "project", "orders"],
        ["graph", "declare", "project", "orders", "--clear", "--depends-on", "payments"],
        ["graph", "declare", "galaxy", "orders", "--depends-on", "payments"],
        ["graph", "declare", "project", "orders", "--depends-on", "payments#nope"],
    ],
)
def test_declare_usage_errors_make_no_call(httpx_mock: HTTPXMock, args: list) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


def test_dependencies_lists_every_source(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=_DEPS, json=_body())
    result = runner.invoke(app, ["graph", "dependencies", "project", "orders"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    output = strip_ansi(result.output)
    assert "declared" in output and "ledger" in output and "manual" in output


def test_a_refusal_exits_with_the_http_code(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET", url=_DEPS, status_code=404,
        json={"detail": {"code": "graph-entity-not-found", "message": "no project 'orders' in this tenant"}},
    )
    result = runner.invoke(app, ["graph", "dependencies", "project", "orders"])
    assert result.exit_code == 2
    assert "no project 'orders' in this tenant" in strip_ansi(result.output)


# ---------------------------------------------------------------------------------------------
# impact (CDG-3.3 / #5968)
# ---------------------------------------------------------------------------------------------

_BLAST = "http://localhost:8000/v1/graph/acme-corp/blast-radius"


def _answer(**extra: object) -> dict:
    web = {"kind": "consumer", "id": "c1", "name": "Web", "slug": "web", "depth": 1, "edge_kind": "consumes",
           "provenance": "derived", "pointers": [], "path": [], "owner": {"slug": "payments", "name": "Payments"}}
    reporting = {**web, "id": "c2", "slug": "reporting", "depth": 2, "edge_kind": "depends_on",
                 "provenance": "declared", "owner": None}
    evidence = {key: [] for key in ("verification_runs", "consumer_contracts", "deploy_gate_evaluations",
                                    "sdk_regen_targets", "agent_toolset_tools", "mock_fixture_packs",
                                    "sunset_consumers")}
    evidence["verification_runs"] = [{"run_id": "r1"}, {"run_id": "r2"}]
    return {"direct": [web], "transitive": [reporting], "invalidated_evidence": evidence, "truncated": False,
            "warnings": [], **extra}


@pytest.mark.parametrize(
    "operation,pointer",
    [("GET /pets/{id}", "/paths/~1pets~1{id}/get"), ("post /a/b", "/paths/~1a~1b/post")],
)
def test_operation_pointer(operation: str, pointer: str) -> None:
    assert operation_pointer(operation) == pointer


@pytest.mark.parametrize("operation", ["", "GET", "FETCH /pets", "GET pets"])
def test_operation_pointer_refuses(operation: str) -> None:
    with pytest.raises(ValueError):
        operation_pointer(operation)


def test_schema_pointer() -> None:
    assert schema_pointer("Pet") == "/components/schemas/Pet"
    assert schema_pointer("a/b") == "/components/schemas/a~1b"
    with pytest.raises(ValueError):
        schema_pointer(" ")


def test_impact_and_evidence_rows() -> None:
    rows = impact_rows(_answer())
    assert [(r["depth"], r["name"], r["owner"]) for r in rows] == [(1, "web", "payments"), (2, "reporting", "")]
    counts = {r["evidence"]: r["count"] for r in evidence_rows(_answer())}
    assert counts["Verification runs"] == 2 and counts["Agent toolset tools"] == 0


def test_impact_posts_the_question(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_BLAST, json=_answer(truncated=True, warnings=["no document"]))
    result = runner.invoke(
        app,
        ["graph", "impact", "--project", "petstore", "--operation", "GET /pets/{id}", "--schema", "Pet",
         "--depth", "2", "--provenance", "declared", "--version", "1.0.0"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent == {
        "entity": {"kind": "project", "id": "petstore"},
        "pointers": ["/paths/~1pets~1{id}/get", "/components/schemas/Pet"],
        "depth": 2, "provenance": ["declared"], "version": "1.0.0",
    }
    output = strip_ansi(result.output)
    assert "reporting" in output and "Verification runs" in output
    assert "truncated" in output and "Warning: no document" in output


def test_impact_json_prints_the_answer(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="POST", url=_BLAST, json=_answer())
    result = runner.invoke(app, ["graph", "impact", "--project", "petstore", "--format", "json"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["direct"][0]["slug"] == "web"
    assert json.loads(httpx_mock.get_requests()[0].content)["pointers"] == []


def test_impact_with_nothing_affected(httpx_mock: HTTPXMock) -> None:
    empty = _answer(direct=[], transitive=[])
    empty["invalidated_evidence"]["verification_runs"] = []
    httpx_mock.add_response(method="POST", url=_BLAST, json=empty)
    result = runner.invoke(app, ["graph", "impact", "--project", "petstore", "--operation", "GET /nobody"])
    assert result.exit_code == EXIT_SUCCESS
    assert "Nothing depends on this change." in strip_ansi(result.output)


@pytest.mark.parametrize(
    "args",
    [
        ["graph", "impact", "--project", "p", "--operation", "pets"],
        ["graph", "impact", "--project", "p", "--depth", "6"],
        ["graph", "impact", "--project", "p", "--kind", "galaxy"],
        ["graph", "impact", "--operation", "GET /pets"],
    ],
)
def test_impact_usage_errors_make_no_call(httpx_mock: HTTPXMock, args: list) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_USAGE
    assert httpx_mock.get_requests() == []


# ---------------------------------------------------------------------------------------------
# apiome graph export (CDG-3.6 / #5971)
# ---------------------------------------------------------------------------------------------

_EXPORT = "http://localhost:8000/v1/graph/acme-corp/export"
_JSON_EXPORT = {"format": "apiome.graph.export/v1", "truncated": False, "nodes": [], "edges": []}


def test_export_writes_json_to_stdout(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=f"{_EXPORT}?format=json", json=_JSON_EXPORT)
    result = runner.invoke(app, ["graph", "export"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["format"] == "apiome.graph.export/v1"
    assert "truncated" not in result.stderr


def test_export_passes_every_filter(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", text="digraph apiome {\n}\n")
    result = runner.invoke(
        app,
        ["graph", "export", "--format", "DOT", "--kind", "consumer", "--kind", "project", "--team", "payments",
         "--provenance", "declared", "--no-stale", "--entity", "project:abc", "--depth", "3"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    request = httpx_mock.get_requests()[0]
    assert request.url.path == "/v1/graph/acme-corp/export"
    assert list(request.url.params.multi_items()) == [
        ("format", "dot"), ("kind", "consumer"), ("kind", "project"), ("team", "payments"),
        ("provenance", "declared"), ("stale", "false"), ("entity", "project:abc"), ("depth", "3"),
    ]
    assert result.stdout == "digraph apiome {\n}\n"


def test_export_leaves_depth_out_without_an_entity(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url=f"{_EXPORT}?format=json", json=_JSON_EXPORT)
    result = runner.invoke(app, ["graph", "export", "--depth", "4"])
    assert result.exit_code == EXIT_SUCCESS, result.output


def test_export_writes_a_file(httpx_mock: HTTPXMock, tmp_path) -> None:
    httpx_mock.add_response(method="GET", text="// apiome graph export: 0 nodes, 0 edges\ndigraph apiome {\n}\n")
    target = tmp_path / "graph.dot"
    result = runner.invoke(app, ["graph", "export", "--format", "dot", "--out", str(target)])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert target.read_text().startswith("// apiome graph export")
    assert result.stdout == "" and f"Wrote {target}" in result.stderr


@pytest.mark.parametrize(
    "fmt, body",
    [("json", json.dumps({**_JSON_EXPORT, "truncated": True})),
     ("dot", "// apiome graph export: 1 nodes, 10000 edges; truncated at 10000 edges\ndigraph apiome {\n}\n")],
)
def test_export_warns_when_truncated(httpx_mock: HTTPXMock, fmt: str, body: str) -> None:
    httpx_mock.add_response(method="GET", text=body)
    result = runner.invoke(app, ["graph", "export", "--format", fmt])
    assert result.exit_code == EXIT_SUCCESS
    assert "truncated at 10,000 edges" in result.stderr


def test_export_refuses_an_unknown_format() -> None:
    result = runner.invoke(app, ["graph", "export", "--format", "svg"])
    assert result.exit_code == EXIT_USAGE


def test_export_prints_the_refusal(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET", status_code=400, json={"detail": {"code": "graph-invalid", "message": "unknown filter values: x"}}
    )
    result = runner.invoke(app, ["graph", "export", "--kind", "x"])
    assert result.exit_code == EXIT_USAGE
    assert "unknown filter values: x" in result.stderr


def test_export_truncated_reader() -> None:
    from apiome_cli.client.graph import export_truncated

    assert export_truncated('{"truncated": true}', "json") is True
    assert export_truncated('{"truncated": false}', "json") is False
    assert export_truncated("not json", "json") is False
    assert export_truncated("[]", "json") is False
    assert export_truncated("// x; truncated at 10000 edges\ndigraph {}", "dot") is True
    assert export_truncated("digraph {} // truncated", "dot") is False


def test_graph_export_path() -> None:
    assert api_paths.graph_export("acme") == "/v1/graph/acme/export"
