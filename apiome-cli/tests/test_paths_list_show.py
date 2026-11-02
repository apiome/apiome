"""``apiome paths list`` / ``apiome paths show`` (CLI 8.1, #3237).

The rules (:mod:`apiome_cli.paths_view`), snapshot tests of the grouped table and the path tree, and
both commands against a mocked REST API: ``PROJECT VERSION`` positionals (``--project`` /
``--version`` still work), ``--search`` (alias ``--q``), ``--method`` / ``--tag``, path resolution by
template, UUID, URL-encoded or RFC 6901 form, and ``--json`` printing the API's array / object.

Regenerate the snapshots with ``UPDATE_SNAPSHOTS=1``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.paths_view import (
    decode_path_ref,
    group_by_path,
    method_sort_key,
    render_tree,
)

runner = CliRunner()
SNAPSHOTS = Path(__file__).parent / "snapshots" / "paths"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_CHARGES = "c0000000-0000-4000-8000-000000000001"
_CHARGE = "c0000000-0000-4000-8000-000000000002"
_WEBHOOKS = "c0000000-0000-4000-8000-000000000003"

_PATHS = [
    {"id": _CHARGES, "pathname": "/charges", "summary": None},
    {"id": _CHARGE, "pathname": "/charges/{id}", "summary": None},
    {"id": _WEBHOOKS, "pathname": "/webhooks", "summary": None},
]


def _op(method: str, op_id: str, tags: list[str], summary: str = "") -> dict:
    return {
        "id": f"op-{op_id}",
        "operation": method,
        "description": {"operation_id": op_id, "tags": tags, "summary": summary},
    }


_OPERATIONS = {
    _CHARGES: [_op("POST", "createCharge", ["public"]), _op("GET", "listCharges", ["public"])],
    _CHARGE: [_op("DELETE", "deleteCharge", ["public"]), _op("GET", "getCharge", ["public"])],
    _WEBHOOKS: [_op("POST", "receiveWebhook", ["internal"])],
}

_FULL_CHARGE = {
    "id": _CHARGE,
    "pathname": "/charges/{id}",
    "summary": "One charge",
    "operations": [
        {
            "id": "op-delete",
            "operation": "DELETE",
            "description": {"operation_id": "deleteCharge", "tags": ["public"], "deprecated": True},
            "parameters": [{"name": "id", "in_location": "path", "data": {"schema": {"type": "string"}}}],
            "requestBody": None,
            "responses": [{"status_code": "204", "content_types": []}],
        },
        {
            "id": "op-get",
            "operation": "GET",
            "description": {"operation_id": "getCharge", "summary": "Fetch a charge", "tags": ["public"]},
            "parameters": [
                {"name": "id", "in_location": "path", "data": {"schema": {"type": "string"}}},
                {"name": "expand", "in_location": "query", "data": {"schema": {"type": "array", "items": {"type": "string"}}}},
            ],
            "requestBody": None,
            "responses": [
                {"status_code": "200", "content_types": [{"media_type": "application/json", "class_name": "Charge"}]},
                {"status_code": "404", "content_types": []},
            ],
        },
        {
            "id": "op-put",
            "operation": "PUT",
            "description": {"operation_id": "updateCharge"},
            "parameters": [],
            "requestBody": {
                "required": True,
                "content_types": [
                    {"media_type": "application/json", "class_name": "ChargeUpdate"},
                    {"media_type": "application/x-www-form-urlencoded", "inline_schema": {"type": "object"}},
                ],
            },
            "responses": [{"status_code": "200", "class_name": "Charge", "content_types": []}],
        },
    ],
}


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock_scope(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=f"{_HOST}/versions/acme/{_PROJECT}/by-version/2.1.0",
        json={"id": _VERSION},
        is_optional=True,
        is_reusable=True,
    )


def _mock_list(httpx_mock) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_HOST}/paths/acme/{_VERSION}", json=_PATHS, is_optional=True, is_reusable=True)
    for path_id, operations in _OPERATIONS.items():
        httpx_mock.add_response(
            url=f"{_HOST}/paths/acme/{_VERSION}/{path_id}/operations",
            json=operations,
            is_optional=True,
            is_reusable=True,
        )


def _mock_show(httpx_mock) -> None:
    _mock_list(httpx_mock)
    httpx_mock.add_response(
        url=f"{_HOST}/paths/acme/{_VERSION}/{_CHARGE}", json=_PATHS[1], is_optional=True, is_reusable=True
    )
    httpx_mock.add_response(
        url=f"{_HOST}/paths/acme/{_VERSION}/{_CHARGE}/full", json=_FULL_CHARGE, is_optional=True, is_reusable=True
    )


def _run(*args: str):
    return runner.invoke(app, list(args), env=_ENV, terminal_width=120)


# --- the rules ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("/charges/{id}", "/charges/{id}"),
        ("charges/{id}", "/charges/{id}"),
        ("  /charges/{id} ", "/charges/{id}"),
        ("/charges/%7Bid%7D", "/charges/{id}"),
        ("~1charges~1{id}", "/charges/{id}"),
        ("#/paths/~1charges~1{id}", "/charges/{id}"),
        ("~1a~0b", "/a~b"),
        ("~1a~01", "/a~1"),
        ("", ""),
    ],
)
def test_decode_path_ref(ref: str, expected: str) -> None:
    assert decode_path_ref(ref) == expected


def test_methods_sort_in_path_item_order() -> None:
    assert sorted(["PATCH", "DELETE", "GET", "X-PURGE", "POST"], key=method_sort_key) == [
        "GET", "POST", "DELETE", "PATCH", "X-PURGE",
    ]


def test_group_by_path_collects_methods_operations_and_tags() -> None:
    rows = [
        {"pathname": "/a", "path_id": "1", "method": "POST", "operationId": "create", "tags": ["t1"]},
        {"pathname": "/a", "path_id": "1", "method": "GET", "operationId": "list", "tags": ["t1", "t2"]},
        {"pathname": "/b", "path_id": "2", "method": "", "operationId": "", "tags": []},
    ]
    assert group_by_path(rows) == [
        {"pathname": "/a", "path_id": "1", "methods": ["GET", "POST"], "operations": ["list", "create"], "tags": ["t1", "t2"]},
        {"pathname": "/b", "path_id": "2", "methods": [], "operations": [], "tags": []},
    ]


def test_the_tree_snapshot() -> None:
    _snapshot("tree", "\n".join(render_tree(_FULL_CHARGE)))


def test_a_path_without_operations_says_so() -> None:
    assert render_tree({"pathname": "/empty", "operations": []}) == ["/empty", "└── (no operations)"]


# --- paths list ---------------------------------------------------------------------------------


def test_list_groups_one_row_per_path(httpx_mock) -> None:
    _mock_list(httpx_mock)
    result = _run("paths", "list", "payments-api", "2.1.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    _snapshot("list", result.output.rstrip("\n"))


def test_list_accepts_the_option_form(httpx_mock) -> None:
    _mock_list(httpx_mock)
    result = _run("paths", "list", "--project", "payments-api", "--version", "2.1.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "receiveWebhook" in result.output


def test_list_search_keeps_matching_paths(httpx_mock) -> None:
    _mock_list(httpx_mock)
    result = _run("paths", "list", "payments-api", "2.1.0", "--search", "webhook")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "/webhooks" in result.output
    assert "/charges" not in result.output


def test_list_json_is_the_api_array_filtered_by_search(httpx_mock) -> None:
    _mock_list(httpx_mock)
    whole = _run("--json", "paths", "list", "payments-api", "2.1.0")
    assert json.loads(whole.output) == _PATHS
    searched = _run("--json", "paths", "list", "payments-api", "2.1.0", "--q", "deleteCharge")
    assert json.loads(searched.output) == [_PATHS[1]]


def test_list_needs_both_project_and_version() -> None:
    result = _run("paths", "list", "payments-api")
    assert result.exit_code == EXIT_USAGE
    assert "PROJECT VERSION" in result.output


# --- paths show ---------------------------------------------------------------------------------


@pytest.mark.parametrize("ref", ["/charges/{id}", "~1charges~1{id}", "/charges/%7Bid%7D", _CHARGE])
def test_show_resolves_any_path_form_and_prints_the_tree(httpx_mock, ref: str) -> None:
    _mock_show(httpx_mock)
    result = _run("paths", "show", "payments-api", "2.1.0", ref)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output.rstrip("\n") == "\n".join(render_tree(_FULL_CHARGE))


def test_show_accepts_the_option_form(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _run("paths", "show", "/charges/{id}", "--project", "payments-api", "--version", "2.1.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "GET getCharge — Fetch a charge" in result.output


def test_show_method_filter_narrows_the_tree(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _run("paths", "show", "payments-api", "2.1.0", "/charges/{id}", "--method", "put")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "updateCharge" in result.output
    assert "getCharge" not in result.output


def test_show_json_is_the_full_api_object(httpx_mock) -> None:
    _mock_show(httpx_mock)
    result = _run("--json", "paths", "show", "payments-api", "2.1.0", "/charges/{id}", "--tag", "public")
    assert result.exit_code == EXIT_SUCCESS, result.output
    document = json.loads(result.output)
    assert document["pathname"] == "/charges/{id}"
    assert [op["operation"] for op in document["operations"]] == ["DELETE", "GET"]


def test_show_an_unknown_path_is_a_usage_error(httpx_mock) -> None:
    _mock_list(httpx_mock)
    result = _run("paths", "show", "payments-api", "2.1.0", "/nope")
    assert result.exit_code == EXIT_USAGE
    assert "Path not found" in result.output


def test_show_refuses_mixed_forms() -> None:
    result = _run("paths", "show", "payments-api", "2.1.0", "/charges", "--project", "x", "--version", "y")
    assert result.exit_code == EXIT_USAGE
