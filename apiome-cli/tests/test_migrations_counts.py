"""``apiome migrations counts`` (CLI 11.2, #3261).

Snapshot tests of the human output (``tests/fixtures/migrations/counts*.txt``; regenerate with
``UPDATE_SNAPSHOTS=1``) and the command against mocked ``GET /v1/projects/{t}`` and
``GET /v1/migration-plans/{t}/projects/{p}``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app
from apiome_cli.migration_view import count_project_plans, render_plan_counts, sort_counts

runner = CliRunner()

SNAPSHOTS = Path(__file__).parent / "fixtures" / "migrations"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_HOST = "http://localhost:8000/v1"
_PAYMENTS = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_CATALOG = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_WEBHOOKS = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_PROJECTS = [
    {"id": _WEBHOOKS, "slug": "webhooks", "name": "Webhooks"},
    {"id": _CATALOG, "slug": "catalog-api", "name": "Catalog API"},
    {"id": _PAYMENTS, "slug": "payments-api", "name": "Payments API"},
]


def _rule(class_name: str, prop: str) -> dict:
    return {"class_name": class_name, "source_property": prop, "rule": {"ruleType": "simple"}}


def _plan(n: int, rules: list[dict]) -> dict:
    return {"id": f"{n:08d}-0000-4000-8000-000000000000", "from_version_id": "a", "to_version_id": "b", "rules": rules}


_PLANS = {
    _PAYMENTS: [
        _plan(1, [_rule("Customer", "zip"), _rule("Customer", "phone"), _rule("Order", "total")]),
        _plan(2, [_rule("Customer", "zipcode")]),
        _plan(3, []),
    ],
    _CATALOG: [_plan(4, [_rule("Product", "sku")]), _plan(5, [])],
    _WEBHOOKS: [],
}


def _rows() -> list:
    return sort_counts([count_project_plans(p, _PLANS[p["id"]]) for p in _PROJECTS])


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text + "\n" == path.read_text(encoding="utf-8")


def _mock_tenant(httpx_mock, projects=_PROJECTS) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme", json={"items": list(projects), "total": len(projects)})
    for project in projects:
        httpx_mock.add_response(
            url=f"{_HOST}/migration-plans/acme/projects/{project['id']}", json={"plans": _PLANS[project["id"]]}
        )


def _counts(*args: str):
    return runner.invoke(app, ["migrations", "counts", *args], env=_ENV)


# --- presentation ---------------------------------------------------------------------------


def test_counts_snapshot() -> None:
    _snapshot("counts", render_plan_counts(_rows()))


def test_counts_single_project_snapshot() -> None:
    _snapshot("counts_single", render_plan_counts([count_project_plans(_PROJECTS[2], _PLANS[_PAYMENTS])]))


def test_no_projects() -> None:
    assert render_plan_counts([]) == "No projects."


def test_row_counts_plans_distinct_classes_and_rules() -> None:
    row = count_project_plans(_PROJECTS[2], _PLANS[_PAYMENTS])
    assert row == {"project_id": _PAYMENTS, "project": "payments-api", "plans": 3, "classes": 2, "rules": 4}


def test_row_name_falls_back_to_name_then_id() -> None:
    assert count_project_plans({"id": _CATALOG, "name": "Catalog"}, [])["project"] == "Catalog"
    assert count_project_plans({"id": _CATALOG}, [])["project"] == _CATALOG


def test_row_ignores_non_object_plans() -> None:
    assert count_project_plans(_PROJECTS[0], ["junk", None])["plans"] == 0  # type: ignore[list-item]


def test_sort_is_most_plans_first_then_by_name() -> None:
    assert [r["project"] for r in _rows()] == ["payments-api", "catalog-api", "webhooks"]
    tied = sort_counts([{"project": "b", "plans": 1}, {"project": "a", "plans": 1}])
    assert [r["project"] for r in tied] == ["a", "b"]


# --- the command ----------------------------------------------------------------------------


def test_counts_prints_every_project(httpx_mock) -> None:
    _mock_tenant(httpx_mock)
    result = _counts()
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_plan_counts(_rows()) + "\n"


def test_counts_with_no_projects(httpx_mock) -> None:
    _mock_tenant(httpx_mock, projects=[])
    result = _counts()
    assert result.exit_code == EXIT_SUCCESS
    assert result.stdout == "No projects.\n"


def test_project_flag_makes_one_plan_list_request(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/projects/acme/by-slug/payments-api", json={"id": _PAYMENTS})
    httpx_mock.add_response(url=f"{_HOST}/migration-plans/acme/projects/{_PAYMENTS}", json={"plans": _PLANS[_PAYMENTS]})
    result = _counts("--project", "payments-api")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == render_plan_counts([count_project_plans(_PROJECTS[2], _PLANS[_PAYMENTS])]) + "\n"
    plan_requests = [r for r in httpx_mock.get_requests() if "/migration-plans/" in str(r.url)]
    assert len(plan_requests) == 1


def test_project_flag_accepts_a_uuid_without_a_lookup(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/migration-plans/acme/projects/{_CATALOG}", json={"plans": _PLANS[_CATALOG]})
    result = _counts("--project", _CATALOG, "--json")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(httpx_mock.get_requests()) == 1
    assert json.loads(result.stdout)["projects"][0]["plans"] == 2


def test_json_returns_the_count_object(httpx_mock) -> None:
    _mock_tenant(httpx_mock)
    body = json.loads(_counts("--json").stdout)
    assert body == {"projects": _rows(), "total": {"plans": 5, "rules": 5}}


def test_global_json_flag_matches_the_local_one(httpx_mock) -> None:
    _mock_tenant(httpx_mock)
    result = runner.invoke(app, ["--json", "migrations", "counts"], env=_ENV)
    assert json.loads(result.stdout)["total"] == {"plans": 5, "rules": 5}


def test_missing_plans_body_counts_as_zero(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{_HOST}/migration-plans/acme/projects/{_CATALOG}", json={"unexpected": True})
    body = json.loads(_counts("--project", _CATALOG, "--json").stdout)
    assert body["projects"][0]["plans"] == 0 and body["total"] == {"plans": 0, "rules": 0}
