"""``apiome classes list <project> <version>`` (CLI 7.1, #3229).

The rules (:mod:`apiome_cli.class_view`), snapshot tests of both modes
(``tests/fixtures/classes_list/``; regenerate with ``UPDATE_SNAPSHOTS=1``), and the command against a
mocked REST API: the lean call (``GET /v1/classes/{tenant}?version_id=…``) and the hydrated one
(``…/version/{id}/with-properties-tags``), ``--tag``, ``--search``, ``--limit`` / ``--all`` and the
raw ``--json`` payload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from apiome_cli.class_view import (
    class_tags,
    filter_classes,
    property_count,
    render_hydrated,
    render_lean,
    summary_line,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "classes_list"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_LEAN = f"{_HOST}/classes/acme?version_id={_VERSION}"
_HYDRATED = f"{_HOST}/classes/acme/version/{_VERSION}/with-properties-tags"


def _tag(name):
    return {"id": f"t-{name}", "project_id": _PROJECT, "name": name, "color": "default", "description": None}


_LEAN_CLASSES = [
    {"id": "c1", "version_id": _VERSION, "name": "Charge", "description": "Inbound payment from a customer.",
     "property_count": 11, "tags": [_tag("core"), _tag("financial")]},
    {"id": "c2", "version_id": _VERSION, "name": "Customer", "description": "End-user / payer record.",
     "property_count": 9, "tags": [_tag("identity"), _tag("pii")]},
    {"id": "c3", "version_id": _VERSION, "name": "Refund", "description": "Reversal of a charge.",
     "property_count": 7, "tags": [_tag("financial")]},
    {"id": "c4", "version_id": _VERSION, "name": "Webhook", "description": None, "property_count": 0, "tags": []},
]


def _cp(pid, name, data, parent=None):
    return {"id": pid, "class_id": "c1", "name": name, "data": data, "parent_id": parent}


_HYDRATED_CLASSES = [
    {"id": "c1", "version_id": _VERSION, "name": "Charge", "description": "Inbound payment from a customer.",
     "properties": [
         _cp("p3", "metadata", {"type": "object"}),
         _cp("p1", "amount", {"type": "number", "required": True}),
         _cp("p4", "note", {"type": "string"}, parent="p3"),
         _cp("p2", "created_at", {"type": "string", "format": "date-time", "required": True}),
     ],
     "tags": [{"id": "ct1", "class_id": "c1", "tag_id": "t-core", "tag_name": "core"},
              {"id": "ct2", "class_id": "c1", "tag_id": "t-fin", "tag_name": "financial"}]},
    {"id": "c4", "version_id": _VERSION, "name": "Webhook", "description": None, "properties": [], "tags": []},
]


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, *, hydrated=False):
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=[{"name": "stable", "version_id": _VERSION}])
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[{"id": _VERSION, "version_id": "2.1.0"}])
    if hydrated:
        httpx_mock.add_response(url=_HYDRATED, json=_HYDRATED_CLASSES)
    else:
        httpx_mock.add_response(url=_LEAN, json=_LEAN_CLASSES)


def _run(*args, json_mode=False):
    argv = (["--json"] if json_mode else []) + ["classes", "list", "payments-api", *args]
    return runner.invoke(app, argv, env=_ENV)


def _urls(httpx_mock):
    return [str(r.url) for r in httpx_mock.get_requests()]


# ---- rules ----------------------------------------------------------------------------------------


def test_class_tags_from_either_shape() -> None:
    assert class_tags(_LEAN_CLASSES[0]) == ["core", "financial"]
    assert class_tags(_HYDRATED_CLASSES[0]) == ["core", "financial"]
    assert class_tags({"tags": None}) == []


def test_property_count() -> None:
    assert property_count(_LEAN_CLASSES[0]) == 11
    assert property_count(_HYDRATED_CLASSES[0]) == 3  # the nested "note" is not top level
    assert property_count({"name": "Old"}) is None


def test_filter_classes() -> None:
    assert [c["name"] for c in filter_classes(_LEAN_CLASSES, tag="FINANCIAL")] == ["Charge", "Refund"]
    assert [c["name"] for c in filter_classes(_LEAN_CLASSES, search="payer")] == ["Customer"]
    assert [c["name"] for c in filter_classes(_LEAN_CLASSES, tag="financial", search="reversal")] == ["Refund"]
    assert filter_classes(_LEAN_CLASSES) == _LEAN_CLASSES


def test_summary_line() -> None:
    assert summary_line(shown=4, matched=4, total=4, where="p 2.1.0") == "4 classes in p 2.1.0."
    assert summary_line(shown=1, matched=1, total=1, where="p 2.1.0") == "1 class in p 2.1.0."
    assert summary_line(shown=2, matched=3, total=4, where="p 2.1.0") == (
        "3 of 4 classes in p 2.1.0 match. Showing 2; pass --all or --limit N."
    )


def test_an_old_server_without_counts_shows_a_question_mark() -> None:
    assert render_lean([{"name": "Charge", "tags": None}])[1].split()[1] == "?"


def test_the_lean_snapshot() -> None:
    _snapshot("lean", "\n".join(render_lean(_LEAN_CLASSES)))


def test_the_hydrated_snapshot() -> None:
    _snapshot("hydrated", "\n".join(render_hydrated(_HYDRATED_CLASSES)))


def test_long_descriptions_are_cut() -> None:
    row = render_lean([{"name": "A", "property_count": 1, "tags": [], "description": "x" * 100}])[1]
    assert row.endswith("…") and len(row.split("  ")[-1].strip()) == 60


# ---- command --------------------------------------------------------------------------------------


def test_the_lean_list_uses_one_class_call(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("v2.1.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == "\n".join(render_lean(_LEAN_CLASSES)) + "\n\n4 classes in payments-api 2.1.0.\n"
    assert [u for u in _urls(httpx_mock) if "/classes/" in u] == [_LEAN]


def test_with_properties_uses_the_hydrated_call(httpx_mock) -> None:
    _mock(httpx_mock, hydrated=True)
    result = _run("2.1.0", "--with-properties")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "    note      string     —" in result.output
    assert result.output.endswith("2 classes in payments-api 2.1.0.\n")
    assert [u for u in _urls(httpx_mock) if "/classes/" in u] == [_HYDRATED]


def test_a_version_tag_works(httpx_mock) -> None:
    _mock(httpx_mock)
    assert _run("stable").exit_code == EXIT_SUCCESS


def test_filters_and_limit(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("2.1.0", "--tag", "financial", "--limit", "1")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Charge" in result.output and "Refund" not in result.output
    assert "2 of 4 classes in payments-api 2.1.0 match. Showing 1; pass --all or --limit N." in result.output


def test_json_is_the_raw_payload_lean_and_hydrated(httpx_mock) -> None:
    _mock(httpx_mock)
    assert json.loads(_run("2.1.0", "--all", json_mode=True).stdout) == _LEAN_CLASSES


def test_json_hydrated_is_raw(httpx_mock) -> None:
    _mock(httpx_mock, hydrated=True)
    assert json.loads(_run("2.1.0", "--with-properties", json_mode=True).stdout) == _HYDRATED_CLASSES


def test_nothing_matches(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _run("2.1.0", "--search", "zzz")
    assert result.exit_code == EXIT_SUCCESS
    assert result.output == "0 of 4 classes in payments-api 2.1.0 match.\n"


def test_an_unknown_version_exits_2(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=[])
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=[{"id": _VERSION, "version_id": "2.1.0"}])
    result = _run("9.9.9")
    assert result.exit_code == EXIT_USAGE
    assert "No version or version tag '9.9.9'" in result.output
