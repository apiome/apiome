"""The export permission matrix, proved route by route — X4 (#6225).

``docs/export-permission-matrix.json`` tables every export action: the REST calls that perform it,
the permission it needs and the UI controls that offer it. Every row needs ``permission: null`` —
membership of the tenant — so viewer, editor and owner may each perform every row, and another
member's job is listed, polled, downloaded and cancelled like one's own. The roles and their grants
are the RC6-H5 table's (``docs/catalog-projects-permission-matrix.json``, #6212). The UI suite
(``apiome-ui/tests/permission-matrix-export.test.tsx``) reads the same file.

This suite checks:

* for viewer / editor / owner and every REST call in the table, the call gets past auth without
  consulting a permission guard: each call's ``reach`` — the first thing the route does once auth
  has passed — is stubbed to answer a sentinel 418, so the call never touches the database;
* every call refuses a caller outside the tenant (a signed-in user who is not a member, an API key
  of another tenant) with 403 and an anonymous caller with 401, before the route runs;
* a job started by one member is polled, downloaded and cancelled by a viewer of the same tenant,
  while a job id of another tenant is 404 on every job route, even to a member of both tenants;
* every export route the app mounts has a row, so a new route cannot skip the table.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import db
from app.main import app
from tests.test_export_job_routes import _source
from tests.test_permission_matrix import ROLES, as_role, role_may  # noqa: F401 - `as_role` is a fixture

_REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = _REPO_ROOT / "docs" / "export-permission-matrix.json"
MATRIX: Dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))

#: Values substituted into the table's path, query and body templates.
PATH_VALUES = {"tenant": "acme", "item": "cat-1", "job": "job-1", "mock": "mock-1"}

#: The status a stubbed ``reach`` answers with: the call got past auth and every guard.
REACHED = 418

client = TestClient(app, raise_server_exceptions=False)


def _fill(value: Any) -> Any:
    """Fill ``{tenant}`` / ``{item}`` / ``{job}`` / ``{mock}`` in a template, recursively."""
    if isinstance(value, str):
        return value.format(**PATH_VALUES)
    if isinstance(value, list):
        return [_fill(entry) for entry in value]
    if isinstance(value, dict):
        return {key: _fill(entry) for key, entry in value.items()}
    return value


def _calls() -> Iterator[Any]:
    for action in MATRIX["actions"]:
        for call in action["rest"]:
            yield action, call


def _send(call: Dict[str, Any], headers: Dict[str, str] | None = None):
    """Send one table call, filled in for tenant ``acme``."""
    return client.request(
        call["method"],
        _fill(call["path"]),
        params=_fill(call.get("query") or {}),
        json=_fill(call["body"]) if "body" in call else None,
        headers=headers or {},
    )


def _reached(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=REACHED, detail="reached the route")


# ---------------------------------------------------------------------------
# The table itself.
# ---------------------------------------------------------------------------


def test_every_action_is_a_member_action_with_a_rest_call() -> None:
    """Each row names a REST call and needs membership only (``permission: null``)."""
    ids = [action["id"] for action in MATRIX["actions"]]
    assert len(ids) == len(set(ids)), "duplicate action ids"
    for action in MATRIX["actions"]:
        assert action["rest"], f"{action['id']} has no REST call"
        assert action["permission"] is None, f"{action['id']}: export routes check membership only"
        assert action["ui"] or action.get("ui_note"), f"{action['id']}: no control and no note why"
        for call in action["rest"]:
            assert call.get("reach"), f"{action['id']} {call['path']} names no reach"


def test_every_export_route_has_a_row() -> None:
    """Every ``/v1/export/…`` route (and the export pre-flight) is in the table."""
    tabled = {
        (call["method"], call["path"].replace("{tenant}", "{tenant_slug}"))
        for _action, call in _calls()
    }
    mounted = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if not (path.startswith("/v1/export/") or path == "/v1/tenants/{tenant_slug}/export/preflight"):
            continue
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            mounted.add((method, path))
    normalised = {
        (method, path.replace("{job_id}", "{job}").replace("{mock_id}", "{mock}"))
        for method, path in mounted
    }
    assert normalised - tabled == set(), "export routes missing from docs/export-permission-matrix.json"
    assert tabled - normalised == set(), "table rows that name no mounted route"


# ---------------------------------------------------------------------------
# Every role of the tenant reaches every route.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,call,role",
    [
        pytest.param(action, call, role, id=f"{action['id']}:{call['method']}:{call['path']}:{role}")
        for action, call in _calls()
        for role in ROLES
    ],
)
def test_each_role_reaches_each_route(as_role, action, call, role) -> None:  # noqa: F811
    """Viewer, editor and owner all get past auth, and no permission guard is consulted."""
    asked = as_role(role)
    assert role_may(role, action["permission"])
    with patch(call["reach"], side_effect=_reached):
        response = _send(call)
    assert asked == [], f"{action['id']}: a member-only route consulted the guard for {asked}"
    assert response.status_code == REACHED, (
        f"{role} should reach {call['method']} {call['path']}: {response.status_code} {response.text[:200]}"
    )


# ---------------------------------------------------------------------------
# Nobody outside the tenant gets in.
# ---------------------------------------------------------------------------


@pytest.fixture
def real_auth(monkeypatch):
    """Use the real ``validate_authentication``, with ``acme`` an active tenant."""
    app.dependency_overrides.pop(validate_authentication, None)
    monkeypatch.setattr(db, "get_active_tenant_auth_row", lambda slug: {"id": "tenant-acme", "slug": slug})
    yield


ALL_CALLS = [
    pytest.param(call, id=f"{action['id']}:{call['method']}:{call['path']}") for action, call in _calls()
]


@pytest.mark.parametrize("call", ALL_CALLS)
def test_a_signed_in_non_member_is_refused(real_auth, monkeypatch, call) -> None:
    """A valid session of a user who is not a member of ``acme`` gets 403 before the route runs."""
    monkeypatch.setattr("app.auth.decode_jwt", lambda _header: {"user_id": "user-of-globex"})
    monkeypatch.setattr("app.auth.validate_user_tenant_access", lambda _user, _slug: None)
    with patch(call["reach"], side_effect=_reached) as reach:
        response = _send(call, {"Authorization": "Bearer token"})
    assert response.status_code == 403, response.text
    assert "does not have access to tenant" in response.json()["detail"]
    reach.assert_not_called()


@pytest.mark.parametrize("call", ALL_CALLS)
def test_another_tenants_api_key_is_refused(real_auth, monkeypatch, call) -> None:
    """An API key minted in ``globex`` gets 403 on ``acme``'s export routes."""
    monkeypatch.setattr(db, "validate_api_key", lambda _key: {"tenant_slug": "globex", "tenant_id": "tenant-globex"})
    with patch(call["reach"], side_effect=_reached) as reach:
        response = _send(call, {"X-API-Key": "globex-key"})
    assert response.status_code == 403, response.text
    reach.assert_not_called()


@pytest.mark.parametrize("call", ALL_CALLS)
def test_an_anonymous_caller_is_refused(real_auth, call) -> None:
    """No session and no key: 401."""
    with patch(call["reach"], side_effect=_reached) as reach:
        response = _send(call)
    assert response.status_code == 401, response.text
    reach.assert_not_called()


# ---------------------------------------------------------------------------
# Another member's job follows the table; another tenant's job is out of reach.
# ---------------------------------------------------------------------------


@pytest.fixture
def jobs(monkeypatch):
    """A clean job store, a faked source, and a ``login(user, tenant)`` that switches the caller."""
    from app import export_job_engine as eje

    eje._jobs.clear()
    caller: Dict[str, str] = {}

    def login(user: str, tenant: str) -> None:
        caller.update(user=user, tenant=tenant)

    def fake_auth(tenant_slug: str) -> Dict[str, Any]:
        # A member of ``caller['tenant']`` only — the real dependency's 403 for any other slug.
        if tenant_slug != caller["tenant"]:
            raise HTTPException(status_code=403, detail=f"User does not have access to tenant: {tenant_slug}")
        return {
            "tenant_id": f"tenant-{tenant_slug}",
            "tenant_slug": tenant_slug,
            "user_id": caller["user"],
            "auth_method": "jwt",
        }

    app.dependency_overrides[validate_authentication] = fake_auth
    # The shared job store is best-effort; with no database it answers "not here".
    monkeypatch.setattr(db, "get_async_job", lambda *a, **k: None, raising=False)
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        yield login
    app.dependency_overrides.pop(validate_authentication, None)
    eje._jobs.clear()


def _start(tenant: str) -> str:
    """Start a real export in ``tenant`` and wait for it to finish; return its id."""
    response = client.post(f"/v1/export/{tenant}/jobs", json={"artifact": "artifact-1", "target": "openapi"})
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    for _ in range(500):
        state = client.get(f"/v1/export/{tenant}/jobs/{job_id}").json()["state"]
        if state in ("completed", "failed", "canceled"):
            assert state == "completed"
            return job_id
        time.sleep(0.01)
    raise AssertionError("export job did not finish")


def test_a_viewer_lists_polls_downloads_and_cancels_an_editors_job(jobs) -> None:
    """Jobs carry no owner: a viewer of the tenant uses an editor's job like their own."""
    jobs("user-editor", "acme")
    job_id = _start("acme")

    jobs("user-viewer", "acme")
    listed = client.get("/v1/export/acme/jobs").json()["jobs"]
    assert [row["job_id"] for row in listed] == [job_id]
    assert client.get(f"/v1/export/acme/jobs/{job_id}").status_code == 200
    download = client.get(f"/v1/export/acme/jobs/{job_id}/download")
    assert download.status_code == 200, download.text
    assert download.content
    assert client.delete(f"/v1/export/acme/jobs/{job_id}").status_code == 204


JOB_ROUTES = [
    ("GET", "/v1/export/{tenant}/jobs/{job}"),
    ("GET", "/v1/export/{tenant}/jobs/{job}/download"),
    ("GET", "/v1/export/{tenant}/jobs/{job}/attestation"),
    ("DELETE", "/v1/export/{tenant}/jobs/{job}"),
]


@pytest.mark.parametrize("method,template", JOB_ROUTES)
def test_another_tenants_job_is_out_of_reach(jobs, method, template) -> None:
    """A globex job: a member of acme only is refused globex (403) and cannot find it in acme (404)."""
    jobs("user-globex", "globex")
    job_id = _start("globex")

    jobs("user-acme", "acme")
    assert client.request(method, template.format(tenant="globex", job=job_id)).status_code == 403
    assert client.request(method, template.format(tenant="acme", job=job_id)).status_code == 404
    assert [row["job_id"] for row in client.get("/v1/export/acme/jobs").json()["jobs"]] == []


def test_a_member_of_both_tenants_cannot_cross_them(jobs) -> None:
    """Membership of both is no bridge: a globex job id under acme's path is still 404."""
    jobs("user-both", "globex")
    job_id = _start("globex")
    jobs("user-both", "acme")
    for method, template in JOB_ROUTES:
        assert client.request(method, template.format(tenant="acme", job=job_id)).status_code == 404
