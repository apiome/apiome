"""Tests for ``apiome graph declare|dependencies`` (CDG-3.2 / #5967)."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock
from typer.testing import CliRunner

from apiome_cli.client import api_paths
from apiome_cli.client.graph import dependency_rows, parse_depends_on
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
