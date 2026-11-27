"""The ``pacts`` permission matrix and audit trail, proved route by route — PFX-6.1 (#6953).

``docs/pacts-permission-matrix.json`` tables every Pact Broker write: the ``pacts:*`` permission it
needs and the ``access_audit`` action it writes. This suite checks that:

* every write route the app mounts under the Pact surfaces has a row (or is a POST that changes
  nothing, listed under ``reads``, or a 501 compatibility stub), and every row names a mounted route —
  so a new write cannot skip the table;
* every row's audit is wired: a ``route`` row is wrapped in :func:`app.pact_audit.audited_write`
  with exactly the row's action, a ``transaction`` row's action is one the transactional writer owns
  (and the route is *not* also wrapped, which would write the row twice), an ``explicit`` row's
  handler calls :func:`app.pact_audit.record_pact_write`;
* for viewer / editor / admin / owner and every row, a role the table refuses gets **403** naming the
  permission, and a role the table allows passes the guard (the stubbed predicate answers "granted"
  with a sentinel 418, so the call stops at the guard without touching the database);
* the table's grants are the built-in roles' ``pacts`` grants in ``apiome.seed_builtin_roles``.
"""

from __future__ import annotations

import inspect
import json
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.pact_audit import AUDIT_ACTIONS, AUDITED_ENDPOINTS, TRANSACTIONAL_AUDIT_ACTIONS
from app.pact_broker_auth import validate_broker_authentication

_REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = _REPO_ROOT / "docs" / "pacts-permission-matrix.json"
MATRIX: Dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
ROLES: List[str] = list(MATRIX["roles"])

#: Values substituted into the table's path templates.
PATH_VALUES = {
    "tenant": "acme",
    "pacticipant": "billing-service",
    "number": "1.0.0",
    "version": "1.0.0",
    "tag": "prod",
    "label": "team-a",
    "branch": "main",
    "provider": "accounts",
    "consumer": "billing-service",
    "sha": "a" * 64,
    "metadata": "bWV0YQ",
    "uuid": "00000000-0000-4000-8000-000000000001",
    "delivery": "00000000-0000-4000-8000-000000000002",
    "status": "00000000-0000-4000-8000-000000000003",
    "state": "00000000-0000-4000-8000-000000000004",
    "project": "payments",
    "run": "00000000-0000-4000-8000-000000000005",
}

#: The status the stubbed predicate raises for a granted permission.
GRANTED = 418

#: The modules whose routes are Pact surfaces.
_PACT_MODULE = re.compile(r"^app\.(pact\w*|pacticipant\w*|consumer_pact_export_routes|mcp_pact_routes)$")
#: The module of the Pact Broker routes Apiome answers with 501 (they change nothing).
_NOT_IMPLEMENTED = "app.pact_broker_compat_routes"

client = TestClient(app, raise_server_exceptions=False)


def _shape(path: str) -> str:
    """A path with every ``{param}`` (and ``{param:path}``) blanked, for matching rows to routes."""
    return re.sub(r"\{[^}]+\}", "{}", path.replace("{tenant_slug}", "{tenant}"))


def _write_routes() -> Iterator[Tuple[str, APIRoute]]:
    """Every (method, route) pair under the Pact surfaces that is not a GET."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not _PACT_MODULE.match(route.endpoint.__module__) or route.endpoint.__module__ == _NOT_IMPLEMENTED:
            continue
        for method in sorted(route.methods - {"GET", "HEAD", "OPTIONS"}):
            yield method, route


def _route_for(row: Dict[str, Any]) -> APIRoute:
    """The mounted route a row names."""
    for method, route in _write_routes():
        if method == row["method"] and _shape(route.path) == _shape(row["path"]):
            return route
    raise AssertionError(f"{row['id']}: no mounted route {row['method']} {row['path']}")


def role_may(role: str, permission: Optional[str]) -> bool:
    """Whether the table lets ``role`` perform an action needing ``permission``."""
    spec = MATRIX["roles"][role]
    return permission is None or spec["tenantAdmin"] or permission in spec["grants"]


# ---------------------------------------------------------------------------
# The table covers every write route, and nothing else.
# ---------------------------------------------------------------------------


def test_every_pact_write_route_has_a_row() -> None:
    """A write route without a row (or a ``reads`` entry) would be unaudited and unchecked."""
    listed = {(row["method"], _shape(row["path"])) for row in MATRIX["writes"] + MATRIX["reads"]}
    missing = sorted(
        f"{method} {route.path} ({route.endpoint.__module__}.{route.endpoint.__name__})"
        for method, route in _write_routes()
        if (method, _shape(route.path)) not in listed
    )
    assert missing == [], "write routes missing from docs/pacts-permission-matrix.json:\n" + "\n".join(missing)


def test_every_row_names_a_mounted_route() -> None:
    """A stale row (a route renamed or removed) fails here rather than proving nothing."""
    for row in MATRIX["writes"] + MATRIX["reads"]:
        _route_for(row)


def test_rows_are_unique_and_use_the_known_vocabulary() -> None:
    """Ids are unique; permissions are ``pacts:*`` grants; actions are ones a writer owns."""
    ids = [row["id"] for row in MATRIX["writes"]]
    assert len(ids) == len(set(ids)), "duplicate row ids"
    vocabulary = {grant for spec in MATRIX["roles"].values() for grant in spec["grants"]}
    for row in MATRIX["writes"]:
        assert row["permission"] in vocabulary, row["id"]
        assert row["auditedBy"] in {"route", "transaction", "explicit"}, row["id"]
        owned = TRANSACTIONAL_AUDIT_ACTIONS if row["auditedBy"] == "transaction" else AUDIT_ACTIONS
        assert row["audit"] in owned, f"{row['id']}: {row['audit']} is not a {row['auditedBy']} audit action"
        for other in row.get("alsoRequires", []):
            assert not other.startswith("pacts:"), f"{row['id']}: alsoRequires is for other resources"
    for row in MATRIX["reads"]:
        assert row["permission"] == "pacts:view" and row["why"], row["path"]


# ---------------------------------------------------------------------------
# Every write writes its audit row.
# ---------------------------------------------------------------------------


def _qualified(route: APIRoute) -> str:
    endpoint = inspect.unwrap(route.endpoint)
    return f"{endpoint.__module__}.{endpoint.__qualname__}"


@pytest.mark.parametrize("row", MATRIX["writes"], ids=lambda row: row["id"])
def test_every_write_is_audited_as_the_table_says(row: Dict[str, Any]) -> None:
    """``route`` rows are wrapped with their action; ``transaction`` rows are not wrapped twice."""
    route = _route_for(row)
    key = _qualified(route)
    if row["auditedBy"] == "route":
        assert AUDITED_ENDPOINTS.get(key) == row["audit"], f"{row['id']}: {key} is not audited as {row['audit']}"
    elif row["auditedBy"] == "transaction":
        assert key not in AUDITED_ENDPOINTS, f"{row['id']}: {key} would write its audit row twice"
    else:
        assert key not in AUDITED_ENDPOINTS
        source = inspect.getsource(inspect.getmodule(inspect.unwrap(route.endpoint)))
        assert "record_pact_write(" in source and f'"{row["audit"]}"' in source, row["id"]


def test_every_audited_endpoint_has_a_row() -> None:
    """Nothing is wrapped that the table does not list (a wrapped GET would audit reads)."""
    rows = {_qualified(_route_for(row)) for row in MATRIX["writes"] if row["auditedBy"] == "route"}
    wrapped = {key for key in AUDITED_ENDPOINTS if key.startswith("app.")}  # not the suites' toy routes
    assert wrapped == rows


@pytest.mark.parametrize("row", [r for r in MATRIX["writes"] if r["auditedBy"] == "route"], ids=lambda r: r["id"])
def test_an_audit_target_is_filled_from_the_routes_own_parameters(row: Dict[str, Any]) -> None:
    """Every ``{placeholder}`` of a route's audit target is one of its path parameters."""
    route = _route_for(row)
    source = inspect.getsource(inspect.getmodule(inspect.unwrap(route.endpoint)))
    name = inspect.unwrap(route.endpoint).__name__
    match = re.search(rf'@audited_write\("[^"]+", "([^"]+)"\)\n\s*(?:async )?def {name}\(', source)
    assert match, f"{row['id']}: no audited_write decorator on {name}"
    placeholders = set(re.findall(r"\{(\w+)\}", match.group(1)))
    params = set(route.param_convertors)
    assert placeholders <= params, f"{row['id']}: target {match.group(1)} names {placeholders - params}"


# ---------------------------------------------------------------------------
# Each role is answered as the table says.
# ---------------------------------------------------------------------------


class _Granted(HTTPException):
    """Raised by the stubbed predicate when the role holds the permission."""


@pytest.fixture
def as_role(monkeypatch):
    """Authenticate as a member of ``acme`` holding ``role``'s grants; record what the guard asks.

    ``also`` are permissions outside ``pacts`` a row needs as well (``alsoRequires``); they are granted
    quietly, so the ``pacts`` check is the one that answers.
    """
    asked: List[str] = []

    def use(role: str, also: Iterable[str] = ()) -> List[str]:
        quiet = set(also)
        spec = MATRIX["roles"][role]
        auth = {"tenant_id": "tenant-acme", "tenant_slug": "acme", "user_id": f"user-{role}", "auth_method": "jwt"}
        app.dependency_overrides[validate_authentication] = lambda: auth
        app.dependency_overrides[validate_broker_authentication] = lambda: auth

        def user_has_permission(tenant_id, user_id, resource, action) -> bool:
            permission = f"{resource}:{action}"
            if permission in quiet:
                return True
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
    app.dependency_overrides.pop(validate_broker_authentication, None)


def _cases() -> Iterator[Any]:
    for row in MATRIX["writes"]:
        if row["path"].startswith("/v1/internal/"):
            continue  # The MCP route authenticates by key; test_record_mcp_deployment_is_audited covers it.
        for role in ROLES:
            yield pytest.param(row, role, id=f"{row['id']}:{role}")


def _stubs(row: Dict[str, Any]) -> Any:
    """The data a route reads before its guard, so the guard is what answers."""
    if row.get("stub") == "webhook_exists":
        return patch("app.pact_broker_webhook_routes.load_for_delivery", return_value=object())
    if row.get("stub") == "live_run_exists":
        # A live run (PFX-8.9) is looked up in the caller's workspace before the guard asks.
        return patch("app.pact_verify_runs.live_runs.provider_of", return_value=PATH_VALUES["provider"])
    return nullcontext()


@pytest.mark.parametrize("row,role", list(_cases()))
def test_each_role_is_answered_as_the_table_says(as_role, row: Dict[str, Any], role: str) -> None:
    """A refused role gets the guard's 403; an allowed one passes it."""
    asked = as_role(role, row.get("alsoRequires", ()))
    kwargs: Dict[str, Any] = {"json": row["body"]} if "body" in row else {"content": b"{}"}
    with _stubs(row):
        response = client.request(row["method"], row["path"].format(**PATH_VALUES), params=row.get("query"), **kwargs)
    permission = row["permission"]
    assert permission in asked, (
        f"{row['id']}: the guard never asked for {permission} (asked {asked}; "
        f"status {response.status_code}: {response.text[:200]})"
    )
    if role_may(role, permission):
        assert response.status_code == GRANTED, f"{role} should pass: {response.status_code} {response.text[:200]}"
    else:
        assert response.status_code == 403, f"{role} should be refused: {response.status_code} {response.text[:200]}"
        assert permission in response.text


# ---------------------------------------------------------------------------
# The table's grants are the built-in roles' grants.
# ---------------------------------------------------------------------------


def _latest_seed_sql() -> str:
    """The body of ``apiome.seed_builtin_roles`` in the newest migration that defines it."""
    scripts = sorted(
        (_REPO_ROOT / "apiome-db" / "scripts").glob("V*__*.sql"),
        key=lambda p: int(re.match(r"V(\d+)__", p.name).group(1)),
    )
    defining = [p for p in scripts if "FUNCTION apiome.seed_builtin_roles" in p.read_text(encoding="utf-8")]
    sql = defining[-1].read_text(encoding="utf-8")
    start = sql.index("CREATE OR REPLACE FUNCTION apiome.seed_builtin_roles")
    return sql[start : sql.index("$$ LANGUAGE plpgsql;", start)]


def test_table_grants_match_the_builtin_role_seed() -> None:
    """Viewer views; Editor views, creates and edits; Owner and Admin also delete."""
    sql = _latest_seed_sql()
    every = re.search(r"all_resources TEXT\[\] := ARRAY\[([^\]]*)\]", sql)
    assert every and "'pacts'" in every.group(1), "pacts is not in all_resources"
    content = re.search(r"content_resources TEXT\[\] := ARRAY\[([^\]]*)\]", sql)
    assert content and "'pacts'" not in content.group(1), "pacts must not get the Editor's full CRUD"
    assert "SELECT v_editor, 'pacts', a FROM unnest(ARRAY['view','create','edit']) AS a;" in sql

    crud = ["pacts:view", "pacts:create", "pacts:edit", "pacts:delete"]
    assert MATRIX["roles"]["viewer"]["grants"] == ["pacts:view"]
    assert MATRIX["roles"]["editor"]["grants"] == crud[:3]
    assert MATRIX["roles"]["admin"]["grants"] == crud
    assert MATRIX["roles"]["owner"]["grants"] == crud and MATRIX["roles"]["owner"]["tenantAdmin"] is True


def test_the_table_and_the_rest_guard_share_a_vocabulary() -> None:
    """``pacts`` is a resource the REST guard knows, with the four CRUD actions."""
    from app.permissions import Action, Resource

    assert Resource.PACTS == "pacts"
    actions = {grant.split(":")[1] for spec in MATRIX["roles"].values() for grant in spec["grants"]}
    assert actions == {Action.VIEW, Action.CREATE, Action.EDIT, Action.DELETE}
