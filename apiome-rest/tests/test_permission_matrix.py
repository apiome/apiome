"""The Catalog and Projects permission matrix, proved route by route — RC6-H5 (#6212).

``docs/catalog-projects-permission-matrix.json`` tables every Catalog, Projects and Versions action:
the ``resource:action`` permission it needs, the REST calls that perform it and the UI controls that
offer it. A role may perform an action when it is a tenant administrator (Owner) or its grants hold
the permission; ``permission: null`` means any member. The UI suite
(``apiome-ui/tests/permission-matrix-ui.test.tsx``) reads the same file.

This suite checks, for viewer / editor / owner and every REST call in the table:

* a role the table refuses gets **403** from the route's permission guard, naming the permission;
* a role the table allows passes the guard. To prove that without running the handler against the
  database, the permission predicate answers "granted" by raising a sentinel 418 — so an allowed
  call stops at the guard, having asked for exactly the table's permission;
* an action with no permission (export) never consults the guard, for any role.

It also checks the table's role grants against the built-in role seed (``apiome.seed_builtin_roles``
in the latest apiome-db migration that defines it), so the table cannot drift from what the
database actually grants.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import db
from app.main import app

_REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = _REPO_ROOT / "docs" / "catalog-projects-permission-matrix.json"
MATRIX: Dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
ROLES: List[str] = list(MATRIX["roles"])

#: Values substituted into the table's path templates.
PATH_VALUES = {
    "tenant": "acme",
    "item": "cat-1",
    "project": "proj-1",
    "version": "ver-1",
    "job": "job-1",
    "tag": "tag-1",
}

#: The status the stubbed predicate raises for a granted permission (see the module docstring).
GRANTED = 418

client = TestClient(app, raise_server_exceptions=False)


def role_may(role: str, permission: Optional[str]) -> bool:
    """Whether the table lets ``role`` perform an action needing ``permission``."""
    spec = MATRIX["roles"][role]
    return permission is None or spec["tenantAdmin"] or permission in spec["grants"]


def _cases() -> Iterator[Tuple[str, Dict[str, Any], Dict[str, Any], str]]:
    for action in MATRIX["actions"]:
        for call in action["rest"]:
            for role in ROLES:
                yield pytest.param(action, call, role, id=f"{action['id']}:{call['method']}:{call['path']}:{role}")


def _fill(template: str) -> str:
    return template.format(**PATH_VALUES)


class _Granted(HTTPException):
    """Raised by the stubbed predicate when the role holds the permission."""


@pytest.fixture
def as_role(monkeypatch):
    """Authenticate as a member of ``acme`` holding ``role``'s grants; record what the guard asks."""
    asked: List[str] = []

    def use(role: str) -> List[str]:
        spec = MATRIX["roles"][role]
        user = f"user-{role}"
        app.dependency_overrides[validate_authentication] = lambda: {
            "tenant_id": "tenant-acme",
            "tenant_slug": "acme",
            "user_id": user,
            "auth_method": "jwt",
        }

        def user_has_permission(tenant_id, user_id, resource, action) -> bool:
            permission = f"{resource}:{action}"
            asked.append(permission)
            if spec["tenantAdmin"] or permission in spec["grants"]:
                raise _Granted(status_code=GRANTED, detail=f"granted {permission}")
            return False

        monkeypatch.setattr(db, "user_has_permission", user_has_permission)
        monkeypatch.setattr(db, "is_user_tenant_admin", lambda *a, **k: bool(spec["tenantAdmin"]))
        monkeypatch.setattr(db, "write_access_audit", lambda *a, **k: None)
        return asked

    yield use
    app.dependency_overrides.pop(validate_authentication, None)


def _stubs(call: Dict[str, Any]):
    """The data a route reads before its guard, so the guard is what answers."""
    stub = call.get("stub")
    if stub == "catalog_item":
        return patch.object(db, "get_catalog_item_by_id", return_value={"id": "cat-1", "tenant_id": "tenant-acme"})
    if stub == "export_source":
        return patch("app.export_routes.load_export_source", side_effect=HTTPException(404, "stubbed source"))
    return patch.object(db, "get_catalog_item_by_id", wraps=db.get_catalog_item_by_id)


@pytest.mark.parametrize("action,call,role", list(_cases()))
def test_rest_call_answers_each_role_as_the_table_says(as_role, action, call, role) -> None:
    """A refused role gets the guard's 403; an allowed one passes it; a member-only action never asks."""
    asked = as_role(role)
    query = {k: _fill(v) for k, v in (call.get("query") or {}).items()}
    with _stubs(call):
        response = client.request(
            call["method"],
            _fill(call["path"]),
            params=query,
            json=call.get("body"),
        )

    permission = action["permission"]
    if permission is None:
        assert asked == [], f"{action['id']}: a member-only action consulted the guard for {asked}"
        assert response.status_code != 403, response.text
        return

    assert permission in asked, (
        f"{action['id']} {call['method']} {call['path']}: the guard never asked for {permission} "
        f"(asked {asked}; status {response.status_code}: {response.text[:200]})"
    )
    if role_may(role, permission):
        assert response.status_code == GRANTED, f"{role} should pass: {response.status_code} {response.text[:200]}"
    else:
        assert response.status_code == 403, f"{role} should be refused: {response.status_code} {response.text[:200]}"
        assert permission in response.json()["detail"]


def test_every_action_has_a_rest_call_and_a_known_permission() -> None:
    """Each row names how REST performs it, and its permission is one the role grants use."""
    vocabulary = {grant for spec in MATRIX["roles"].values() for grant in spec["grants"]}
    ids = [action["id"] for action in MATRIX["actions"]]
    assert len(ids) == len(set(ids)), "duplicate action ids"
    for action in MATRIX["actions"]:
        assert action["rest"], f"{action['id']} has no REST call"
        if action["permission"] is not None:
            assert action["permission"] in vocabulary, action["id"]


# ---------------------------------------------------------------------------
# The table's grants are the built-in roles' grants.
# ---------------------------------------------------------------------------


def _latest_seed_sql() -> str:
    """The body of the newest migration that (re)defines ``apiome.seed_builtin_roles``."""
    scripts = sorted(
        (_REPO_ROOT / "apiome-db" / "scripts").glob("V*__*.sql"),
        key=lambda p: int(re.match(r"V(\d+)__", p.name).group(1)),
    )
    defining = [p for p in scripts if "FUNCTION apiome.seed_builtin_roles" in p.read_text(encoding="utf-8")]
    assert defining, "no migration defines apiome.seed_builtin_roles"
    return defining[-1].read_text(encoding="utf-8")


def _array(sql: str, name: str) -> List[str]:
    match = re.search(rf"{name} TEXT\[\] := ARRAY\[([^\]]*)\]", sql)
    assert match, f"{name} not found in the role seed"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def test_table_grants_match_the_builtin_role_seed() -> None:
    """Viewer views everything; Editor has CRUD on content resources and no publish; Owner adds publish."""
    sql = _latest_seed_sql()
    content = set(_array(sql, "content_resources"))
    every = set(_array(sql, "all_resources"))
    crud = ["view", "create", "edit", "delete"]
    resources = {grant.split(":")[0] for spec in MATRIX["roles"].values() for grant in spec["grants"]}
    assert resources <= every

    expected = {
        "viewer": {f"{r}:view" for r in resources},
        "editor": {f"{r}:{a}" for r in resources for a in (crud if r in content else ["view"])},
        "owner": {f"{r}:{a}" for r in resources for a in crud},
    }
    assert "(v_owner, 'versions', 'publish')" in sql
    expected["owner"].add("versions:publish")
    assert "(v_editor, 'versions', 'publish')" not in sql

    for role, grants in expected.items():
        assert set(MATRIX["roles"][role]["grants"]) == grants, role
    assert MATRIX["roles"]["owner"]["tenantAdmin"] is True
