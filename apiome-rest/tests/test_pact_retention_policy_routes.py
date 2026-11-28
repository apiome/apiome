"""HTTP contract of the stored clean-up rules — PFX-8.14 (#7311).

The store is faked (``test_pact_retention_policy`` runs it on a fake database). Asserted here:

* reading the rules, previewing them and listing Recently deleted need ``pacts:view``; saving needs
  ``pacts:delete`` (Owner and Admin) — a denial is a 403 before the store is touched;
* ``can_edit`` / ``can_restore`` follow ``pacts:delete``, so a viewer gets a read-only screen;
* the tenant is the caller's, never the one in the URL;
* ``keep_deployed_or_released: false`` is a 422 with ``pact-retention-keeps-in-use``; an unknown
  field, a repeated tag and a forged cursor are refused with a reason.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_retention import RetentionError, RetentionKeep, RetentionPlan
from app.pact_retention_policy import (
    CODE_KEEPS_IN_USE,
    DeletedPage,
    RetentionPolicy,
    RetentionPreview,
    keep_of,
)

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "u-1", "auth_method": "jwt", "user_email": "dev@example.com"}
_BASE = "/v1/tenants/someone-else/pact-retention"
_ROUTES = "app.pact_retention_routes"


def _policy(**overrides: Any) -> RetentionPolicy:
    return RetentionPolicy(**{"configured": True, "can_edit": True, **overrides})


def _preview() -> RetentionPreview:
    plan = RetentionPlan(
        dry_run=True,
        applied=False,
        plan_digest="sha256:" + "a" * 64,
        keep=RetentionKeep(),
        evaluated=10,
        kept=7,
        deleted=3,
        grace_days=30,
    )
    return RetentionPreview(draft=False, nightly_enabled=True, plan=plan)


@pytest.fixture
def routes() -> Iterator[Dict[str, MagicMock]]:
    """Authenticate, grant everything, and fake the store."""
    app.dependency_overrides[validate_authentication] = lambda: _AUTH

    def save(_db: Any, _tenant: str, rules: Any, **_kw: Any) -> RetentionPolicy:
        keep_of(rules)  # the real store refuses before writing
        return _policy()

    answers = {
        "enforce_permission": "u-1",
        "has_permission": True,
        "get_policy": _policy(),
        "preview_policy": _preview(),
        "list_recently_deleted": DeletedPage(
            items=[], count=0, has_more=False, restore_window_days=30, can_restore=True
        ),
    }
    patches = {name: patch(f"{_ROUTES}.{name}", return_value=answer) for name, answer in answers.items()}
    patches["save_policy"] = patch(f"{_ROUTES}.save_policy", side_effect=save)
    mocks = {name: patcher.start() for name, patcher in patches.items()}
    yield mocks
    for patcher in patches.values():
        patcher.stop()
    app.dependency_overrides.clear()


_CALLS = [
    ("get", "/policy", None, "view", "get_policy"),
    ("put", "/policy", {"keep_main_branch_latest": 5}, "delete", "save_policy"),
    ("post", "/policy/preview", {}, "view", "preview_policy"),
    ("get", "/deleted", None, "view", "list_recently_deleted"),
]


@pytest.mark.parametrize(("method", "path", "body", "action", "store"), _CALLS)
def test_each_route_is_gated_on_the_pacts_resource_and_uses_the_callers_tenant(
    routes: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, store: str
) -> None:
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"{_BASE}{path}", **kwargs)
    assert response.status_code == 200, response.text
    assert routes["enforce_permission"].call_args.args[2:4] == ("pacts", action)
    assert routes[store].call_args.args[1] == _TENANT


@pytest.mark.parametrize(("method", "path", "body", "action", "store"), _CALLS)
def test_a_denied_caller_gets_403_before_the_store(
    routes: Dict[str, MagicMock], method: str, path: str, body: Any, action: str, store: str
) -> None:
    routes["enforce_permission"].side_effect = HTTPException(status_code=403, detail="no")
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(f"{_BASE}{path}", **kwargs).status_code == 403
    assert routes[store].call_count == 0


def test_a_viewer_reads_the_rules_read_only(routes: Dict[str, MagicMock]) -> None:
    routes["has_permission"].return_value = False
    client.get(f"{_BASE}/policy")
    assert routes["get_policy"].call_args.kwargs["can_edit"] is False
    assert routes["has_permission"].call_args.args[2:4] == ("pacts", "delete")
    client.get(f"{_BASE}/deleted")
    assert routes["list_recently_deleted"].call_args.kwargs["can_restore"] is False


def test_a_rule_set_that_removes_deployed_versions_cannot_be_saved(routes: Dict[str, MagicMock]) -> None:
    response = client.put(f"{_BASE}/policy", json={"keep_deployed_or_released": False})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == CODE_KEEPS_IN_USE
    assert "Deployed and released versions are always kept." in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"keep_everything": True},
        {"keep_tags": ["prod", "prod"]},
        {"keep_other_branch_days": 30},
        {"restore_window_days": 0},
        {"keep_main_branch_latest": "five"},
    ],
)
def test_unsupported_rules_are_refused_with_a_reason(routes: Dict[str, MagicMock], body: Dict[str, Any]) -> None:
    response = client.put(f"{_BASE}/policy", json=body)
    assert response.status_code == 422 and response.json()["detail"]
    assert routes["save_policy"].call_count == 0


def test_a_draft_preview_is_passed_to_the_store(routes: Dict[str, MagicMock]) -> None:
    response = client.post(f"{_BASE}/policy/preview", json={"rules": {"keep_main_branch_latest": 2}})
    assert response.status_code == 200 and response.json()["plan"]["deleted"] == 3
    assert routes["preview_policy"].call_args.args[2].keep_main_branch_latest == 2
    client.post(f"{_BASE}/policy/preview", json={})
    assert routes["preview_policy"].call_args.args[2] is None


@pytest.mark.parametrize(
    ("store", "method", "path", "body", "code"),
    [
        ("preview_policy", "post", "/policy/preview", {}, CODE_KEEPS_IN_USE),
        ("preview_policy", "post", "/policy/preview", {}, "pact-retention-too-many-versions"),
        ("list_recently_deleted", "get", "/deleted?cursor=forged", None, "pact-retention-bad-cursor"),
    ],
)
def test_store_refusals_keep_their_code(
    routes: Dict[str, MagicMock], store: str, method: str, path: str, body: Any, code: str
) -> None:
    routes[store].side_effect = RetentionError(code, "refused")
    kwargs = {"json": body} if body is not None else {}
    response = getattr(client, method)(f"{_BASE}{path}", **kwargs)
    assert (response.status_code, response.json()["detail"]["code"]) == (422, code)


def test_the_deleted_list_bounds_its_page(routes: Dict[str, MagicMock]) -> None:
    assert client.get(f"{_BASE}/deleted?limit=0").status_code == 422
    assert client.get(f"{_BASE}/deleted?limit=101").status_code == 422
    client.get(f"{_BASE}/deleted?limit=10&cursor=abc")
    kwargs = routes["list_recently_deleted"].call_args.kwargs
    assert (kwargs["limit"], kwargs["after"]) == (10, "abc")
