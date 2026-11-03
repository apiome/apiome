"""The per-branch refresh rules REST surface (RAR-6.4, #3541).

``GET/PUT /v1/tenants/{slug}/repositories/{id}/branch-refresh-rules`` reads and replaces a
repository's branch rules. These tests pin the projection (camelCase aliases, the repository-wide
fallback, each tracked branch's effective settings), the replace-the-set write, the validation
rails, and the tenant scope coming from the token.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_REPO_ID = "770e8400-e29b-41d4-a716-446655440002"
_JWT = {"tenant_id": _TENANT_ID, "tenant_slug": "acme", "user_id": _USER_ID, "auth_method": "jwt"}
_URL = f"/v1/tenants/acme/repositories/{_REPO_ID}/branch-refresh-rules"


@pytest.fixture
def auth_jwt():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _repo_row(*, enabled: bool = True, interval: int = 600) -> dict:
    return {
        "id": _REPO_ID,
        "tenant_id": _TENANT_ID,
        "provider": "github",
        "default_branch": "main",
        "status": "ready",
        "auto_refresh_enabled": enabled,
        "refresh_interval_seconds": interval,
    }


_RULE_ROWS = [
    {"branch_pattern": "main", "refresh_enabled": True, "refresh_interval_seconds": 300,
     "target_version_line": "latest", "created_by": _USER_ID, "created_at": None, "updated_at": None},
    {"branch_pattern": "release/*", "refresh_enabled": True, "refresh_interval_seconds": None,
     "target_version_line": "2.x", "created_by": None, "created_at": None, "updated_at": None},
    {"branch_pattern": "sandbox", "refresh_enabled": False, "refresh_interval_seconds": None,
     "target_version_line": None, "created_by": None, "created_at": None, "updated_at": None},
]


def _mock_reads(mdb, *, rules=None, enabled=True):
    mdb.get_tenant_repository.return_value = _repo_row(enabled=enabled)
    mdb.list_repository_branch_refresh_rules.return_value = list(_RULE_ROWS if rules is None else rules)
    mdb.list_repository_branch_refresh_state.return_value = {}
    mdb.list_repository_import_spec_branches.return_value = ["feature/x", "main", "release/2.0", "sandbox"]


# --- read -------------------------------------------------------------------------------------


def test_the_read_reports_rules_and_each_tracked_branch(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_reads(mdb)
        r = client.get(_URL)

    assert r.status_code == 200
    body = r.json()["branchRefresh"]
    assert body["repositoryId"] == _REPO_ID
    assert body["autoRefreshEnabled"] is True
    assert body["repositoryIntervalSeconds"] == 600
    assert [rule["branchPattern"] for rule in body["rules"]] == ["main", "release/*", "sandbox"]
    assert body["rules"][0]["targetVersionLine"] == "latest"
    branches = {b["branch"]: b for b in body["branches"]}
    assert branches["main"] == {
        "branch": "main", "enabled": True, "intervalSeconds": 300, "targetVersionLine": "latest",
        "rulePattern": "main", "lastRefreshedAt": None,
    }
    assert (branches["release/2.0"]["intervalSeconds"], branches["release/2.0"]["targetVersionLine"]) == (600, "2.x")
    assert branches["sandbox"]["enabled"] is False
    assert branches["feature/x"]["rulePattern"] is None  # follows the repository settings
    mdb.list_repository_branch_refresh_rules.assert_called_once_with(_TENANT_ID, _REPO_ID)


def test_the_repository_switch_turns_every_branch_off(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_reads(mdb, enabled=False)
        r = client.get(_URL)
    assert {b["enabled"] for b in r.json()["branchRefresh"]["branches"]} == {False}


def test_an_unknown_repository_is_404(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = None
        r = client.get(_URL)
    assert r.status_code == 404


# --- write ------------------------------------------------------------------------------------


def test_the_write_replaces_the_set_with_clean_values(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_reads(mdb)
        mdb.replace_repository_branch_refresh_rules.return_value = True
        r = client.put(
            _URL,
            json={"rules": [
                {"branchPattern": " main ", "targetVersionLine": " latest ", "refreshIntervalSeconds": 300},
                {"branchPattern": "release/*", "refreshEnabled": False, "targetVersionLine": ""},
            ]},
        )

    assert r.status_code == 200
    args, kwargs = mdb.replace_repository_branch_refresh_rules.call_args
    assert args[:2] == (_TENANT_ID, _REPO_ID)
    assert args[2] == [
        {"branch_pattern": "main", "refresh_enabled": True, "refresh_interval_seconds": 300,
         "target_version_line": "latest"},
        {"branch_pattern": "release/*", "refresh_enabled": False, "refresh_interval_seconds": None,
         "target_version_line": None},
    ]
    assert kwargs["created_by"] == _USER_ID
    assert "branchRefresh" in r.json()


def test_an_empty_list_removes_every_rule(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_reads(mdb, rules=[])
        mdb.replace_repository_branch_refresh_rules.return_value = True
        r = client.put(_URL, json={"rules": []})
    assert r.status_code == 200
    assert mdb.replace_repository_branch_refresh_rules.call_args.args[2] == []


@pytest.mark.parametrize(
    ("rules", "fragment"),
    [
        ([{"branchPattern": "main"}, {"branchPattern": "main"}], "more than once"),
        ([{"branchPattern": "rel ease"}], "whitespace"),
        ([{"branchPattern": "main", "targetVersionLine": "2/x"}], "version line"),
        ([{"branchPattern": "main", "refreshIntervalSeconds": 5}], "at least"),
    ],
)
def test_invalid_rules_are_refused(auth_jwt, rules, fragment) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        r = client.put(_URL, json={"rules": rules})
    assert r.status_code == 400
    assert fragment in r.json()["detail"]
    mdb.replace_repository_branch_refresh_rules.assert_not_called()


def test_writing_to_an_unknown_repository_is_404(auth_jwt) -> None:
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.replace_repository_branch_refresh_rules.return_value = False
        r = client.put(_URL, json={"rules": [{"branchPattern": "main"}]})
    assert r.status_code == 404
