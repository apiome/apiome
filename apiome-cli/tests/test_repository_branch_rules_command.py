"""``apiome repository branch-rules`` — per-branch refresh rules (RAR-6.4, #3541).

``show`` prints the rules and each tracked branch's effective settings; ``set`` adds or replaces
one rule, ``remove`` drops one and ``clear`` drops them all. The server replaces the whole rule
set on ``PUT``, so ``set`` and ``remove`` must send the other rules back unchanged.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.client.repository_branch_rules import remove_rule, upsert_rule
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_TENANT_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_REPO_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_BASE = "http://localhost:8000"
_TENANTS_ME_URL = f"{_BASE}/v1/tenants/me?offset=0&limit=200"
_TENANTS_ME_BODY = {"items": [{"slug": _TENANT_ID}], "total": 1, "offset": 0, "limit": 200}
_REPOSITORIES_URL = f"{_BASE}/v1/tenants/{_TENANT_ID}/repositories?limit=200"
_REPOSITORY_BODY = {"items": [{"id": _REPO_ID, "name": "API", "full_name": "acme/api"}], "total": 1}
_RULES_URL = f"{_BASE}/v1/tenants/{_TENANT_ID}/repositories/{_REPO_ID}/branch-refresh-rules"

_MAIN = {"branchPattern": "main", "refreshEnabled": True, "refreshIntervalSeconds": 300,
         "targetVersionLine": "latest", "createdBy": None, "createdAt": None, "updatedAt": None}
_RELEASE = {"branchPattern": "release/*", "refreshEnabled": True, "refreshIntervalSeconds": None,
            "targetVersionLine": "2.x", "createdBy": None, "createdAt": None, "updatedAt": None}


def _body(rules) -> dict:
    return {
        "success": True,
        "branchRefresh": {
            "repositoryId": _REPO_ID,
            "autoRefreshEnabled": True,
            "repositoryIntervalSeconds": 3600,
            "minIntervalSeconds": 60,
            "rules": rules,
            "branches": [
                {"branch": "main", "enabled": True, "intervalSeconds": 300, "targetVersionLine": "latest",
                 "rulePattern": "main", "lastRefreshedAt": None},
                {"branch": "feature/x", "enabled": True, "intervalSeconds": 3600, "targetVersionLine": None,
                 "rulePattern": None, "lastRefreshedAt": None},
            ],
        },
    }


@pytest.fixture
def refresh_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "obj_test_workspace_key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", _TENANT_ID)


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(url=_TENANTS_ME_URL, json=_TENANTS_ME_BODY)
    httpx_mock.add_response(url=_REPOSITORIES_URL, json=_REPOSITORY_BODY)


def _put_body(httpx_mock: object) -> dict:
    requests = [r for r in httpx_mock.get_requests() if r.method == "PUT"]
    assert len(requests) == 1
    return json.loads(requests[0].content)


def test_show_prints_rules_and_tracked_branches(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([_MAIN, _RELEASE]))

    result = runner.invoke(app, ["repository", "branch-rules", "show", "acme/api"])

    assert result.exit_code == EXIT_SUCCESS
    out = strip_ansi(result.stdout)
    assert "Repository refresh: on, every 1h" in out
    assert "main: on, every 5m, line latest" in out
    assert "release/*: on, every inherit, line 2.x" in out
    assert "feature/x: on, every 1h, line - (repository settings)" in out


def test_show_json(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([]))

    result = runner.invoke(app, ["repository", "branch-rules", "show", "acme/api", "--format", "json"])

    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout)["repositoryIntervalSeconds"] == 3600


def test_set_adds_a_rule_and_keeps_the_others(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([_MAIN]))
    httpx_mock.add_response(url=_RULES_URL, method="PUT", json=_body([_MAIN, _RELEASE]))

    result = runner.invoke(
        app,
        ["repository", "branch-rules", "set", "acme/api", "release/*", "--line", "2.x", "--interval", "3600"],
    )

    assert result.exit_code == EXIT_SUCCESS, result.stdout
    assert _put_body(httpx_mock) == {
        "rules": [
            {"branchPattern": "main", "refreshEnabled": True, "refreshIntervalSeconds": 300,
             "targetVersionLine": "latest"},
            {"branchPattern": "release/*", "refreshEnabled": True, "refreshIntervalSeconds": 3600,
             "targetVersionLine": "2.x"},
        ]
    }


def test_set_off_replaces_the_rule_with_the_same_pattern(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([_MAIN, _RELEASE]))
    httpx_mock.add_response(url=_RULES_URL, method="PUT", json=_body([_MAIN, _RELEASE]))

    result = runner.invoke(app, ["repository", "branch-rules", "set", "acme/api", "main", "--off"])

    assert result.exit_code == EXIT_SUCCESS
    rules = _put_body(httpx_mock)["rules"]
    assert [r["branchPattern"] for r in rules] == ["main", "release/*"]  # order kept
    assert rules[0] == {"branchPattern": "main", "refreshEnabled": False, "refreshIntervalSeconds": None,
                        "targetVersionLine": None}


def test_remove_drops_one_rule(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([_MAIN, _RELEASE]))
    httpx_mock.add_response(url=_RULES_URL, method="PUT", json=_body([_RELEASE]))

    result = runner.invoke(app, ["repository", "branch-rules", "remove", "acme/api", "main"])

    assert result.exit_code == EXIT_SUCCESS
    assert [r["branchPattern"] for r in _put_body(httpx_mock)["rules"]] == ["release/*"]


def test_remove_an_unknown_rule_is_a_usage_error(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="GET", json=_body([_MAIN]))

    result = runner.invoke(app, ["repository", "branch-rules", "remove", "acme/api", "sandbox"])

    assert result.exit_code == EXIT_USAGE
    assert "No branch rule for 'sandbox'" in strip_ansi(result.stderr)


def test_clear_sends_an_empty_set(httpx_mock: object, refresh_env: None) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_RULES_URL, method="PUT", json=_body([]))

    result = runner.invoke(app, ["repository", "branch-rules", "clear", "acme/api"])

    assert result.exit_code == EXIT_SUCCESS
    assert _put_body(httpx_mock) == {"rules": []}
    assert "No branch rules" in strip_ansi(result.stdout)


def test_upsert_and_remove_helpers() -> None:
    rules = [{"branchPattern": "a"}, {"branchPattern": "b"}]
    assert upsert_rule(rules, {"branchPattern": "c"}) == rules + [{"branchPattern": "c"}]
    assert upsert_rule(rules, {"branchPattern": "a", "x": 1}) == [{"branchPattern": "a", "x": 1}, {"branchPattern": "b"}]
    assert remove_rule(rules, "b") == [{"branchPattern": "a"}]
