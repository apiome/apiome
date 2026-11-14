"""``apiome migrations list`` (CLI 11.1, #3260).

Snapshot tests of the human output (``tests/fixtures/migrations/*.txt``; regenerate with
``UPDATE_SNAPSHOTS=1``) and the command against a mocked
``GET /v1/migration-plans/{t}/projects/{p}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from apiome_cli.migration_view import filter_plans, render_plan_list, sort_plans, summarize_plan, version_labels

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "migrations"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PROJECT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_V1 = "10000000-0000-4000-8000-000000000001"
_V20 = "20000000-0000-4000-8000-000000000020"
_V21 = "21000000-0000-4000-8000-000000000021"

_VERSIONS = [
    {"id": _V1, "version_id": "1.4.0"},
    {"id": _V20, "version_id": "2.0.0"},
    {"id": _V21, "version_id": "2.1.0"},
]
_TAGS = [{"id": "7a900000-0000-4000-8000-000000000001", "name": "stable", "version_id": _V20}]


def _rule(class_name: str, prop: str) -> dict:
    return {"class_name": class_name, "source_property": prop, "rule": {"ruleType": "simple"}}


_PLANS = [
    {
        "id": "3a910000-0000-4000-8000-00000000b41c",
        "from_version_id": _V20,
        "to_version_id": _V21,
        "created_at": "2026-05-01T09:00:00Z",
        "updated_at": "2026-05-04T12:43:10Z",
        "rules": [_rule("Customer", "zip"), _rule("Customer", "phone"), _rule("Order", "total")],
    },
    {
        "id": "7c3d0000-0000-4000-8000-00000000e22a",
        "from_version_id": _V1,
        "to_version_id": _V20,
        "created_at": "2026-02-18T09:00:00Z",
        "updated_at": "2026-02-18T09:00:00Z",
        "rules": [_rule("Customer", "zipcode")],
    },
    {
        "id": "9e000000-0000-4000-8000-000000000001",
        "from_version_id": _V1,
        "to_version_id": _V21,
        "created_at": "2026-03-10T09:00:00Z",
        "updated_at": "2026-03-10T09:00:00Z",
        "rules": [],
    },
]


def _summaries() -> list[dict]:
    labels = version_labels(_VERSIONS)
    return list(sort_plans([summarize_plan(p, labels) for p in _PLANS]))


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock(httpx_mock, plans=_PLANS, *, with_tags: bool = False) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS)
    if with_tags:
        httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=_TAGS)
    httpx_mock.add_response(url=f"{_HOST}/migration-plans/acme/projects/{_PROJECT}", json={"plans": list(plans)})


def _list(*args: str):
    return runner.invoke(app, ["migrations", "list", "--project", "payments-api", *args], env=_ENV)


# --- presentation ---------------------------------------------------------------------------


def test_list_snapshot() -> None:
    _snapshot("list", render_plan_list(_summaries()))


def test_list_snapshot_when_limited() -> None:
    _snapshot("list_limited", render_plan_list(_summaries()[:2], total=3))


def test_no_plans() -> None:
    assert render_plan_list([]) == "No migration plans."


def test_summary_names_versions_and_counts_rules() -> None:
    row = summarize_plan(_PLANS[0], version_labels(_VERSIONS))
    assert (row["from_version"], row["to_version"]) == ("2.0.0", "2.1.0")
    assert row["classes"] == ["Customer", "Order"]
    assert row["rule_count"] == 3
    assert "rules" not in row


def test_summary_falls_back_to_the_id_for_an_unknown_version() -> None:
    row = summarize_plan({**_PLANS[0], "to_version_id": "gone"}, version_labels(_VERSIONS))
    assert row["to_version"] == "gone"


def test_sort_is_newest_first() -> None:
    assert [p["id"][:4] for p in _summaries()] == ["3a91", "9e00", "7c3d"]


def test_filter_by_from_to_or_both() -> None:
    plans = _summaries()
    assert {p["to_version"] for p in filter_plans(plans, from_version_id=_V1)} == {"2.0.0", "2.1.0"}
    assert {p["from_version"] for p in filter_plans(plans, to_version_id=_V21)} == {"2.0.0", "1.4.0"}
    both = filter_plans(plans, from_version_id=_V1, to_version_id=_V20)
    assert [p["id"][:4] for p in both] == ["7c3d"]
    assert filter_plans(plans) == plans


# --- the command ----------------------------------------------------------------------------


def test_list_prints_the_table(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _list()
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_plan_list(_summaries()) + "\n"


def test_project_is_required() -> None:
    result = runner.invoke(app, ["migrations", "list"], env=_ENV)
    assert result.exit_code == EXIT_USAGE


def test_from_filter_accepts_a_v_prefixed_label(httpx_mock) -> None:
    _mock(httpx_mock, with_tags=True)
    result = _list("--from", "v2.0.0")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "3a910000" in result.stdout
    assert "7c3d0000" not in result.stdout and "9e000000" not in result.stdout


def test_to_filter_accepts_a_version_tag(httpx_mock) -> None:
    _mock(httpx_mock, with_tags=True)
    result = _list("--to", "stable")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "7c3d0000" in result.stdout
    assert "3a910000" not in result.stdout


def test_from_and_to_together(httpx_mock) -> None:
    _mock(httpx_mock, with_tags=True)
    result = _list("--json", "--from", "1.4.0", "--to", _V21)
    assert [p["id"][:4] for p in json.loads(result.stdout)] == ["9e00"]


def test_unknown_version_is_a_usage_error(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PROJECT})
    httpx_mock.add_response(url=f"{_HOST}/versions/acme/{_PROJECT}", json=_VERSIONS)
    httpx_mock.add_response(url=f"{_HOST}/version-tags/acme/{_PROJECT}", json=_TAGS)
    result = _list("--from", "9.9.9")
    assert result.exit_code == EXIT_USAGE
    assert "--from: no version or version tag '9.9.9'" in result.stderr


def test_filter_matching_nothing(httpx_mock) -> None:
    _mock(httpx_mock, with_tags=True)
    result = _list("--from", "2.1.0")
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout == "No migration plans.\n"


def test_limit_and_all(httpx_mock) -> None:
    _mock(httpx_mock)
    limited = _list("--limit", "2")
    assert "Showing 2 of 3 plans" in limited.stdout
    _mock(httpx_mock)
    everything = _list("--limit", "2", "--all")
    assert "Showing" not in everything.stdout
    assert everything.stdout.count("\n") == 4  # header + 3 plans


def test_json_returns_the_array(httpx_mock) -> None:
    _mock(httpx_mock)
    result = _list("--json", "--limit", "2")
    body = json.loads(result.stdout)
    assert isinstance(body, list)
    assert [p["id"][:4] for p in body] == ["3a91", "9e00"]
    assert body[0]["from_version"] == "2.0.0" and body[0]["rule_count"] == 3


def test_global_json_flag_matches_the_local_one(httpx_mock) -> None:
    _mock(httpx_mock)
    result = runner.invoke(app, ["--json", "migrations", "list", "--project", "payments-api"], env=_ENV)
    assert json.loads(result.stdout) == _summaries()


def test_json_with_no_plans_is_an_empty_array(httpx_mock) -> None:
    _mock(httpx_mock, plans=[])
    result = _list("--json")
    assert json.loads(result.stdout) == []
