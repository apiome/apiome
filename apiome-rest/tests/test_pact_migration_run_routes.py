"""The Migration wizard's routes — PFX-8.16 (#7313).

No database and no network: the run store is stubbed, the permission predicate chooses what the
caller holds, and the source is an httpx mock transport. What a run does is ``test_pact_migration_job``;
the stored rows are ``test_pact_migration_run_db``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import pact_migration_run_routes as routes
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_migration_run_routes import PactMigrationSourceCredentials
from app.pact_migration_run_routes import _launch as real_launch
from app.pact_migration_run_store import RunActiveError
from app.pact_migration_source import SourceBroker
from app.pact_retention_policy import RetentionRules
from tests.pact_migration_fakes import SOURCE, FakeSource, FakeStore

client = TestClient(app, raise_server_exceptions=False)
BASE = "/v1/tenants/acme/pact-migration"
TOKEN = "s3cr3t-read-token"
EVERYTHING = {"pacts:view", "pacts:create", "pacts:edit"}
RUN_ID = "0b0f4a52-8d5e-4a53-9f0c-2c0f6f6f1a11"


class Stubs:
    """What the routes were asked to do.

    Attributes:
        permissions: The pacts permissions the caller holds.
        tenant: The authenticated tenant.
        created: Keyword arguments of each ``create_run``.
        launched: ``(row, credentials)`` of each job started.
        store: The rows ``get_run`` answers from, per tenant.
    """

    def __init__(self) -> None:
        self.permissions: set = set(EVERYTHING)
        self.tenant = "tenant-acme"
        self.created: List[Dict[str, Any]] = []
        self.launched: List[Any] = []
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.active = False
        self.room = True
        self.rules = RetentionRules()
        self.source = FakeSource()
        self.fake = FakeStore()


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Authenticate, stub the store, and keep jobs from starting."""
    state = Stubs()
    app.dependency_overrides[validate_broker_authentication] = lambda: {
        "tenant_id": state.tenant,
        "user_id": "user-1",
        "auth_method": "jwt",
    }

    def enforce(_db: Any, _auth: Any, resource: Any, action: Any, **_: Any) -> str:
        permission = f"{getattr(resource, 'value', resource)}:{getattr(action, 'value', action)}"
        if permission not in state.permissions:
            raise HTTPException(status_code=403, detail=f"Missing permission {permission}")
        return "user-1"

    def create_run(_db: Any, tenant_id: str, **fields: Any) -> Dict[str, Any]:
        if state.active:
            raise RunActiveError("this workspace already has a migration running; stop it or wait for it")
        state.created.append({"tenant_id": tenant_id, **fields})
        row = state.fake.row(fields["mode"], fields["options"], run_id=RUN_ID)
        row.update(tenant_id=tenant_id, source=fields["source"], auth_kind=fields["auth_kind"], facts=fields["facts"])
        state.rows[tenant_id] = row
        return dict(row)

    def get_run(_db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        row = state.rows.get(tenant_id)
        return dict(row) if row and row["id"] == run_id else None

    def reopen_run(_db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        if state.active:
            raise RunActiveError("this migration is already running")
        row = get_run(None, tenant_id, run_id)
        if row is None or row["mode"] != "copy":
            return None
        row["status"] = "running"
        return row

    def request_stop(_db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        row = get_run(None, tenant_id, run_id)
        if row is not None:
            row["stop_requested"] = True
        return row

    def broker(self: Any, source: str) -> SourceBroker:
        return SourceBroker(
            source,
            token=self.token.get_secret_value() if self.token else None,
            username=self.username,
            password=self.password.get_secret_value() if self.password else None,
            transport=state.source.transport(),
        )

    monkeypatch.setattr(routes, "enforce_permission", enforce)
    monkeypatch.setattr(routes.store, "create_run", create_run)
    monkeypatch.setattr(routes.store, "get_run", get_run)
    monkeypatch.setattr(routes.store, "reopen_run", reopen_run)
    monkeypatch.setattr(routes.store, "request_stop", request_stop)
    monkeypatch.setattr(routes.store, "close_stale", lambda _db, _tenant: 0)
    monkeypatch.setattr(routes.store, "finish_run", lambda *a, **k: None)
    monkeypatch.setattr(
        routes.store, "list_runs", lambda _db, tenant_id, limit=50: [r for t, r in state.rows.items() if t == tenant_id]
    )
    monkeypatch.setattr(routes, "read_rules", lambda _db, _tenant: state.rules)
    monkeypatch.setattr(
        routes,
        "has_permission",
        lambda _db, _auth, resource, action: (
            f"{getattr(resource, 'value', resource)}:{getattr(action, 'value', action)}" in state.permissions
        ),
    )
    monkeypatch.setattr(routes.PactMigrationSourceCredentials, "broker", broker)
    monkeypatch.setattr(routes.migration_jobs, "has_room", lambda: state.room)
    monkeypatch.setattr(routes, "_launch", lambda row, credentials, actor, keep: state.launched.append((row, keep)))
    monkeypatch.setattr("app.pact_audit.record_pact_write", lambda *a, **k: True)
    yield state
    app.dependency_overrides.pop(validate_broker_authentication, None)


def _start(**extra: Any) -> Any:
    return client.post(f"{BASE}/runs", json={"source": SOURCE, "token": TOKEN, **extra})


# ---------------------------------------------------------------------------------------------
# Who may do what
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body,permissions,status",
    [
        ("post", "/test", {"source": SOURCE, "token": TOKEN}, {"pacts:view"}, 403),
        ("post", "/test", {"source": SOURCE, "token": TOKEN}, {"pacts:view", "pacts:create"}, 403),
        ("post", "/test", {"source": SOURCE, "token": TOKEN}, {"pacts:create", "pacts:edit"}, 200),
        ("post", "/runs", {"source": SOURCE, "token": TOKEN}, {"pacts:view"}, 403),
        ("post", "/runs", {"source": SOURCE, "token": TOKEN}, {"pacts:view", "pacts:edit"}, 403),
        ("post", "/runs", {"source": SOURCE, "token": TOKEN}, {"pacts:create", "pacts:edit"}, 202),
        ("get", "/runs", None, set(), 403),
        ("get", "/runs", None, {"pacts:view"}, 200),
        ("get", f"/runs/{RUN_ID}", None, set(), 403),
        ("post", f"/runs/{RUN_ID}/stop", None, {"pacts:view", "pacts:create"}, 403),
        ("post", f"/runs/{RUN_ID}/resume", {"token": TOKEN}, {"pacts:view"}, 403),
    ],
)
def test_the_permissions_each_route_needs(
    stubs: Any, method: str, path: str, body: Any, permissions: set, status: int
) -> None:
    stubs.permissions = permissions
    response = getattr(client, method)(f"{BASE}{path}", **({"json": body} if body is not None else {}))
    assert response.status_code == status, response.text
    if status == 403:
        assert stubs.created == [] and stubs.launched == [] and stubs.source.requests == []


# ---------------------------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------------------------


def test_a_connection_test_says_what_it_found(stubs: Any) -> None:
    response = client.post(f"{BASE}/test", json={"source": SOURCE + "/", "token": TOKEN})
    assert response.status_code == 200
    assert response.json() == {"host": "broker.example.com", "product": "Pact Broker", "pacticipants": 2}
    assert {request.method for request in stubs.source.requests} == {"GET"}


def test_a_refused_sign_in_is_a_422_with_the_reason_and_no_token(stubs: Any) -> None:
    stubs.source.docs["/pacticipants"] = 401
    response = client.post(f"{BASE}/test", json={"source": SOURCE, "token": TOKEN})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "pact-migration-source-refused",
        "message": "Could not sign in to broker.example.com (401). Check the token.",
    }
    assert TOKEN not in response.text


def test_a_url_the_server_must_not_read_is_refused(stubs: Any) -> None:
    response = client.post(f"{BASE}/test", json={"source": "file:///etc/passwd", "token": TOKEN})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "pact-migration-source-invalid"
    assert stubs.source.requests == []


@pytest.mark.parametrize("body", [{}, {"token": TOKEN}, {"source": SOURCE, "tokn": TOKEN}, {"source": ""}])
def test_a_malformed_source_request_is_a_422(stubs: Any, body: Dict[str, Any]) -> None:
    assert client.post(f"{BASE}/test", json=body).status_code == 422
    assert stubs.source.requests == []


# ---------------------------------------------------------------------------------------------
# Starting a run
# ---------------------------------------------------------------------------------------------


def test_starting_a_run_records_it_and_launches_the_job(stubs: Any) -> None:
    response = _start(mode="copy", options={"kinds": ["pact", "pacticipant"], "conflicts": "replace"})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "running" and body["mode"] == "copy" and body["host"] == "broker.example.com"
    assert body["options"]["kinds"] == ["pacticipant", "pact"] and body["options"]["conflicts"] == "replace"
    (created,) = stubs.created
    assert created["tenant_id"] == "tenant-acme" and created["source"] == SOURCE and created["auth_kind"] == "token"
    assert created["facts"] == {"product": "Pact Broker", "cleanup_rules_set": False}
    assert len(stubs.launched) == 1


def test_the_credentials_are_neither_stored_nor_answered(stubs: Any) -> None:
    response = client.post(f"{BASE}/runs", json={"source": SOURCE, "username": "ci", "password": "hunter2-pw"})
    assert response.status_code == 202
    assert "hunter2-pw" not in response.text and "hunter2-pw" not in repr(stubs.created)
    assert stubs.created[0]["auth_kind"] == "basic"
    _start()
    assert TOKEN not in repr(stubs.created) and TOKEN not in repr(stubs.rows)


def test_a_run_defaults_to_a_dry_run_of_everything(stubs: Any) -> None:
    body = _start().json()
    assert body["mode"] == "dry-run" and len(body["options"]["kinds"]) == 8 and body["can_resume"] is False


def test_one_migration_at_a_time(stubs: Any) -> None:
    stubs.active = True
    response = _start()
    assert response.status_code == 409 and response.json()["detail"]["code"] == "pact-migration-run-active"
    assert stubs.launched == []


def test_a_busy_worker_says_so(stubs: Any) -> None:
    stubs.room = False
    response = _start()
    assert response.status_code == 429 and response.json()["detail"]["code"] == "pact-migration-run-busy"
    assert stubs.created == []


def test_thinning_versions_needs_keep_rules(stubs: Any) -> None:
    response = _start(mode="copy", options={"versions": "kept"})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "pact-migration-run-invalid"
    assert stubs.created == []

    stubs.rules = RetentionRules(keep_main_branch_latest=3)
    response = _start(mode="copy", options={"versions": "kept"})
    assert response.status_code == 202
    assert stubs.created[0]["facts"]["cleanup_rules_set"] is True and stubs.launched[0][1] is not None


@pytest.mark.parametrize(
    "extra",
    [{"mode": "sync"}, {"options": {"kinds": ["teams"]}}, {"options": {"conflicts": "merge"}}, {"dry_run": True}],
)
def test_an_unknown_choice_is_refused_not_ignored(stubs: Any, extra: Dict[str, Any]) -> None:
    response = _start(**extra)
    assert response.status_code == 422 and stubs.created == []
    assert TOKEN not in response.text


def test_a_bad_source_url_starts_nothing(stubs: Any) -> None:
    response = client.post(f"{BASE}/runs", json={"source": "https://user:pw@broker.example.com", "token": TOKEN})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "pact-migration-source-invalid"
    assert stubs.created == []


# ---------------------------------------------------------------------------------------------
# Reading, stopping, resuming — and other tenants
# ---------------------------------------------------------------------------------------------


def test_a_run_is_read_and_listed_by_its_tenant_only(stubs: Any) -> None:
    _start()
    assert client.get(f"{BASE}/runs/{RUN_ID}").status_code == 200
    assert [run["id"] for run in client.get(f"{BASE}/runs").json()["runs"]] == [RUN_ID]

    stubs.tenant = "tenant-other"
    response = client.get(f"{BASE}/runs/{RUN_ID}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == "pact-migration-run-not-found"
    assert client.get(f"{BASE}/runs").json() == {"runs": [], "can_migrate": True}
    assert client.post(f"{BASE}/runs/{RUN_ID}/stop").status_code == 404
    assert client.post(f"{BASE}/runs/{RUN_ID}/resume", json={"token": TOKEN}).status_code == 404


def test_an_unknown_run_is_a_404(stubs: Any) -> None:
    for response in (
        client.get(f"{BASE}/runs/nope"),
        client.post(f"{BASE}/runs/nope/stop"),
        client.post(f"{BASE}/runs/nope/resume", json={"token": TOKEN}),
    ):
        assert response.status_code == 404 and response.json()["detail"]["code"] == "pact-migration-run-not-found"


def test_stopping_asks_the_run_to_stop(stubs: Any) -> None:
    _start(mode="copy")
    response = client.post(f"{BASE}/runs/{RUN_ID}/stop")
    assert response.status_code == 200 and response.json()["stop_requested"] is True


def test_resuming_launches_the_job_again_and_never_from_scratch(stubs: Any) -> None:
    _start(mode="copy", options={"restart": True})
    response = client.post(f"{BASE}/runs/{RUN_ID}/resume", json={"token": TOKEN})
    assert response.status_code == 202 and response.json()["status"] == "running"
    assert len(stubs.launched) == 2 and stubs.launched[1][0]["options"]["restart"] is False
    assert TOKEN not in response.text


def test_a_dry_run_cannot_be_resumed(stubs: Any) -> None:
    _start()
    assert client.post(f"{BASE}/runs/{RUN_ID}/resume", json={"token": TOKEN}).status_code == 404


def test_resuming_a_run_that_is_going_is_a_409(stubs: Any) -> None:
    _start(mode="copy")
    stubs.active = True
    response = client.post(f"{BASE}/runs/{RUN_ID}/resume", json={"token": TOKEN})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "pact-migration-run-active"


def test_resuming_a_thinned_run_whose_rules_are_gone_is_refused(stubs: Any) -> None:
    stubs.rules = RetentionRules(keep_main_branch_latest=3)
    _start(mode="copy", options={"versions": "kept"})
    stubs.rules = RetentionRules()
    response = client.post(f"{BASE}/runs/{RUN_ID}/resume", json={"token": TOKEN})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "pact-migration-run-invalid"
    assert len(stubs.launched) == 1


def test_the_log_cursor_is_validated(stubs: Any) -> None:
    _start()
    assert client.get(f"{BASE}/runs/{RUN_ID}?after=-1").status_code == 422
    assert client.get(f"{BASE}/runs/{RUN_ID}?after=3").json()["log"] == []


@pytest.mark.parametrize(
    "permissions,expected",
    [({"pacts:view"}, False), ({"pacts:view", "pacts:create"}, False), (EVERYTHING, True)],
)
def test_the_list_says_whether_the_caller_may_migrate(stubs: Any, permissions: set, expected: bool) -> None:
    stubs.permissions = permissions
    assert client.get(f"{BASE}/runs").json()["can_migrate"] is expected


# ---------------------------------------------------------------------------------------------
# Launching the job
# ---------------------------------------------------------------------------------------------


def test_launching_runs_the_job_with_the_credentials_in_memory_only(
    stubs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ran: List[Any] = []
    monkeypatch.setattr(routes.migration_jobs, "start", lambda work: work())
    monkeypatch.setattr(
        routes, "run_migration", lambda _db, row, broker, **kwargs: ran.append((row["id"], broker, kwargs))
    )
    row = stubs.fake.row("copy", {}, run_id=RUN_ID)
    real_launch(row, PactMigrationSourceCredentials(token=TOKEN), actor="actor", keep=None)
    ((run_id, broker, kwargs),) = ran
    assert run_id == RUN_ID and broker.base_url == SOURCE and kwargs == {"actor": "actor", "keep": None}
    assert TOKEN not in repr(row) and TOKEN not in repr(PactMigrationSourceCredentials(token=TOKEN))


def test_a_source_that_cannot_be_built_fails_the_run_instead_of_leaving_it_running(
    stubs: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    finished: List[Any] = []
    monkeypatch.setattr(
        routes.store, "finish_run", lambda _db, run_id, status, error=None: finished.append((status, error))
    )
    monkeypatch.setattr(routes.migration_jobs, "start", lambda work: pytest.fail("the job must not start"))
    row = stubs.fake.row("copy", {}, run_id=RUN_ID)
    row["source"] = "file:///etc/passwd"
    with pytest.raises(HTTPException) as caught:
        real_launch(row, PactMigrationSourceCredentials(token=TOKEN), actor="actor", keep=None)
    assert caught.value.status_code == 422 and caught.value.detail["code"] == "pact-migration-source-invalid"
    assert finished and finished[0][0] == "failed"
