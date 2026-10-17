"""``apiome properties list <project>`` (CLI 6.1, #3223).

The rules (:mod:`apiome_cli.property_view`), snapshot tests of the table and the ``--json`` document
(``tests/fixtures/properties_list/``; regenerate with ``UPDATE_SNAPSHOTS=1``), and the command against
a mocked ``GET /v1/properties/{tenant}/{project}``: ``--type`` (alias ``--primitive``), ``--search``,
``--unused``, ``--limit`` / ``--all``; the older ``--project-id`` form still works.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.property_view import (
    UsageUnavailable,
    filter_properties,
    is_required,
    render_table,
    schema_type,
    type_matches,
)

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "properties_list"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_LIST = f"{_HOST}/properties/acme/{_PROJECT}"


def _prop(name, data, used_by, description=None):
    return {
        "id": f"id-{name}",
        "project_id": _PROJECT,
        "name": name,
        "description": description,
        "data": data,
        "enabled": True,
        "used_by": used_by,
        "used_by_count": len(used_by),
    }


_PROPS = [
    _prop("amount", {"type": "integer", "format": "int64"}, ["Charge", "Refund"], "Minor units."),
    _prop(
        "created_at",
        {"type": "string", "format": "date-time", "required": True},
        ["Charge", "Customer", "Refund", "Webhook"],
    ),
    _prop("currency", {"type": "string", "enum": ["usd", "eur"]}, ["Charge", "Refund"], "ISO 4217 code."),
    _prop("customer_id", {"type": "string", "format": "uuid"}, ["Charge", "Customer"]),
    _prop("legacy_ref", {"anyOf": [{"type": "string"}, {"type": "null"}]}, [], "Unused since 2.0."),
    _prop("tags", {"type": "array", "items": {"type": "string"}}, ["Customer"]),
]


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, items=_PROPS) -> None:
    httpx_mock.add_response(
        url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT}, is_optional=True
    )
    httpx_mock.add_response(url=_LIST, json=list(items))


def _run(*args, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["properties", "list", *args]
    return runner.invoke(app, argv, env=_ENV)


# --- rules ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "label"),
    [
        ({"type": "string", "format": "uuid"}, "uuid"),
        ({"type": "integer"}, "integer"),
        ({"type": ["string", "null"]}, "string|null"),
        ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "string|null"),
        ({"type": "array", "items": {"type": "string", "format": "email"}}, "array<email>"),
        ({"$ref": "#/components/schemas/Money"}, "Money"),
        ({"enum": ["a", "b"]}, "enum"),
        ({"const": "x"}, "const"),
        ({}, "—"),
        (None, "—"),
    ],
)
def test_schema_type(schema, label) -> None:
    assert schema_type(schema) == label


def test_type_matching() -> None:
    assert type_matches("string|null", "string")
    assert type_matches("UUID", "uuid")
    assert type_matches("array<string>", "array<string>")
    assert not type_matches("array<string>", "string")


def test_required_comes_from_the_data() -> None:
    assert is_required(_PROPS[1]) and not is_required(_PROPS[0])


def test_filters() -> None:
    assert [p["name"] for p in filter_properties(_PROPS, type_filter="string")] == ["currency", "legacy_ref"]
    assert [p["name"] for p in filter_properties(_PROPS, search="iso")] == ["currency"]
    assert [p["name"] for p in filter_properties(_PROPS, unused=True)] == ["legacy_ref"]
    assert [p["name"] for p in filter_properties(_PROPS, type_filter="uuid", search="customer")] == [
        "customer_id"
    ]


def test_unused_needs_a_server_that_reports_usage() -> None:
    old = [{k: v for k, v in p.items() if k not in ("used_by", "used_by_count")} for p in _PROPS]
    with pytest.raises(UsageUnavailable):
        filter_properties(old, unused=True)
    assert len(filter_properties(old)) == 6  # without --unused an older server still lists


def test_table_snapshot() -> None:
    _snapshot("table", render_table(_PROPS, matched=6, project="payments-api", total=6))


def test_table_snapshot_filtered_and_limited() -> None:
    _snapshot("table_filtered", render_table(_PROPS[:2], matched=4, project="payments-api", total=6))


def test_an_empty_match() -> None:
    assert (
        render_table([], matched=0, project="payments-api", total=6)
        == "0 of 6 properties in project 'payments-api' match."
    )


# --- the command ----------------------------------------------------------------------------


def test_list_by_slug(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("payments-api")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_table(_PROPS, matched=6, project="payments-api", total=6) + "\n"


def test_json_snapshot(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("payments-api", "--unused", json_mode=True)
    assert result.exit_code == EXIT_SUCCESS
    _snapshot("unused_json", json.dumps(json.loads(result.stdout), indent=2, sort_keys=True))


def test_primitive_is_an_alias_of_type(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("payments-api", "--primitive", "date-time", json_mode=True)
    assert [p["name"] for p in json.loads(result.stdout)["items"]] == ["created_at"]


def test_limit_and_all(httpx_mock) -> None:
    _mock(httpx_mock)
    limited = _run("payments-api", "--limit", "2")
    assert "Showing 2; pass --all or --limit N." in limited.stdout
    _mock(httpx_mock)
    body = json.loads(_run("payments-api", "--limit", "2", "--all", json_mode=True).stdout)
    assert body["total"] == 6 and len(body["items"]) == 6


def test_the_older_project_id_form(httpx_mock) -> None:
    httpx_mock.add_response(url=_LIST, json=list(_PROPS))
    result = _run("--project-id", _PROJECT, json_mode=True)
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["total"] == 6


def test_a_project_is_required() -> None:
    result = _run()
    assert result.exit_code == EXIT_USAGE
    assert "Name the project" in result.stderr


def test_unused_against_an_older_server_is_a_usage_error(httpx_mock) -> None:
    _mock(
        httpx_mock,
        items=[{k: v for k, v in p.items() if k not in ("used_by", "used_by_count")} for p in _PROPS],
    )
    result = _run("payments-api", "--unused")
    assert result.exit_code == EXIT_USAGE
    assert "does not report where properties are used" in result.stderr
