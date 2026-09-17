"""HTTP contract tests for provider checks — GNC-2.2 (#4738).

``/v1/tenants/{tenant_slug}/projects/{project_ref}/…/checks``. Storage is the in-memory
:class:`tests.fake_check_db.FakeCheckDb` and the provider is a stand-in; everything above them is
real — the RBAC guard, the store's rules, the adapters and the credential resolution. Asserted here:

* **The acceptance criteria.** A normalized check represents pending / pass / fail / skipped; a
  verdict resolves to an authorized binding or is refused; recording is idempotent; and no browser
  client ever receives a repository token.
* The rules around them: which permission each verb needs, project and tenant scoping, the refusal
  codes and their statuses, and the OpenAPI contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from app import (
    comment_store,
    draft_binding_store,
    git_import_routes,
    provider_check_routes,
    provider_check_store,
)
from app.auth import validate_authentication
from app.main import app
from app.provider_checks import (
    CHECK_STATES,
    DEFAULT_CHECK_NAME,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
)
from tests.fake_check_db import FakeCheckDb

client = TestClient(app)

TENANT = "1a2b3c40-3333-4aaa-8bbb-000000000001"
OTHER_TENANT = "1a2b3c40-3333-4aaa-8bbb-0000000000ff"
PROJECT = "1a2b3c40-3333-4aaa-8bbb-000000000002"
OTHER_PROJECT = "1a2b3c40-3333-4aaa-8bbb-000000000003"
VERSION_1 = "1a2b3c40-3333-4aaa-8bbb-000000000010"
VERSION_2 = "1a2b3c40-3333-4aaa-8bbb-000000000011"
REPOSITORY = "1a2b3c40-3333-4aaa-8bbb-000000000020"
BINDING = "1a2b3c40-3333-4aaa-8bbb-000000000030"
ALICE = "1a2b3c40-3333-4aaa-8bbb-000000000101"
BOB = "1a2b3c40-3333-4aaa-8bbb-000000000102"

COMMIT_ONE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COMMIT_TWO = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
TOKEN = "ghp_a_real_looking_repository_token_0123456789"

PROJECT_BASE = "/v1/tenants/acme/projects/pets"
CHECKS = f"{PROJECT_BASE}/versions/1.0.0/binding/checks"


class Provider:
    """An in-memory provider API the adapters publish to."""

    def __init__(self) -> None:
        self.status = 201
        self.payload: Dict[str, Any] = {"id": 4242, "html_url": "https://github.com/x/runs/4242"}
        self.error: Optional[Exception] = None
        self.calls: List[Any] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request, recording what was asked."""
        self.calls.append((request.method, str(request.url)))
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.payload)

    def factory(self) -> httpx.Client:
        """Build a client bound to this provider."""
        return httpx.Client(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def provider(monkeypatch) -> Provider:
    """The provider API every adapter reaches, and the stored credential it is reached with."""
    fake_provider = Provider()
    monkeypatch.setattr(
        "app.provider_status_adapter._default_client_factory", fake_provider.factory
    )
    monkeypatch.setattr(git_import_routes, "resolve_stored_git_token", lambda *a, **k: TOKEN)
    return fake_provider


@pytest.fixture
def fake(monkeypatch) -> FakeCheckDb:
    """A seeded store with one bound draft, swapped in beneath the routes and both stores."""
    store = FakeCheckDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION_1, "1.0.0")
    store.add_version(PROJECT, VERSION_2, "2.0.0")
    store.add_repository(
        TENANT, REPOSITORY, clone_url="https://github.com/acme/specs", created_by=ALICE
    )
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob@example.com")
    now = store._tick()
    store.bindings[BINDING] = {
        "id": BINDING,
        "tenant_id": TENANT,
        "project_id": PROJECT,
        "version_id": VERSION_1,
        "repository_id": REPOSITORY,
        "provider": "github",
        "repo_full_name": "acme/specs",
        "repo_url": "https://github.com/acme/specs",
        "ref": "main",
        "path": "spec",
        "commit_sha": COMMIT_ONE,
        "source_digest": "sha256:abc",
        "synchronized_at": now,
        "created_by": ALICE,
        "created_at": now,
        "updated_at": now,
        "released_at": None,
        "released_by": None,
        "release_reason": None,
    }
    for module in (comment_store, draft_binding_store, provider_check_store, provider_check_routes):
        monkeypatch.setattr(module, "db", store)
    return store


@pytest.fixture
def act_as():
    """Switch the authenticated caller; defaults to Alice on a session."""

    def _set(user_id: Optional[str] = ALICE, tenant_id: str = TENANT) -> None:
        auth: Dict[str, Any] = {"tenant_id": tenant_id, "auth_method": "jwt", "user_id": user_id}
        app.dependency_overrides[validate_authentication] = lambda: auth

    _set()
    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def _post(base: str = CHECKS, **body: Any):
    """Record a verdict and return the raw response."""
    return client.post(base, json=body)


def _recorded(**body: Any) -> Dict[str, Any]:
    """Record a verdict, assert it was created, and return the detail."""
    response = _post(**body)
    assert response.status_code == 201, response.text
    return response.json()


def _code(response) -> str:
    """The stable refusal code of an error response."""
    return response.json()["detail"]["code"]


def _actions(fake: FakeCheckDb) -> List[str]:
    """The audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# The normalized model
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", CHECK_STATES)
def test_every_one_of_the_four_states_can_be_recorded(fake, provider, act_as, state):
    detail = _recorded(state=state, name=f"apiome/{state}")
    assert detail["check"]["state"] == state
    assert (detail["check"]["completed_at"] is None) is (state == STATE_PENDING)


def test_a_verdict_defaults_to_the_bound_commit_and_the_namespaced_check_name(
    fake, provider, act_as
):
    check = _recorded(state=STATE_PASS)["check"]
    assert check["commit_sha"] == COMMIT_ONE
    assert check["name"] == DEFAULT_CHECK_NAME
    assert check["provider"] == "github"
    assert check["ref"] == "main"
    assert check["version_label"] == "1.0.0"
    assert check["created_by_name"] == "Alice Anders"


def test_a_state_outside_the_four_is_refused_by_the_schema(fake, provider, act_as):
    assert _post(state="green").status_code == 422


def test_an_invalid_check_name_is_refused_with_its_code(fake, provider, act_as):
    response = _post(state=STATE_PASS, name="has space")
    assert response.status_code == 422
    assert _code(response) == "check-invalid-name"


# ---------------------------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------------------------


def test_recording_the_same_verdict_twice_is_one_check(fake, provider, act_as):
    first = _recorded(state=STATE_PENDING)["check"]
    second = _recorded(state=STATE_PENDING)["check"]
    assert second["id"] == first["id"]
    assert len(fake.check_runs) == 1
    # And the provider heard about it once.
    assert len(provider.calls) == 1


def test_moving_a_check_to_its_verdict_keeps_one_row_and_tells_the_provider(
    fake, provider, act_as
):
    _recorded(state=STATE_PENDING)
    detail = _recorded(state=STATE_FAIL, title="2 breaking changes")
    assert len(fake.check_runs) == 1
    assert detail["check"]["state"] == STATE_FAIL
    assert len(provider.calls) == 2
    assert provider.calls[1][0] == "PATCH"


def test_a_rerun_advances_the_attempt_counter(fake, provider, act_as):
    _recorded(state=STATE_FAIL)
    detail = _recorded(state=STATE_FAIL, rerun=True)
    assert detail["check"]["attempt"] == 2
    assert len(fake.check_runs) == 1


# ---------------------------------------------------------------------------------------------
# Authorized bindings
# ---------------------------------------------------------------------------------------------


def test_a_version_with_no_binding_has_nothing_to_report_against(fake, provider, act_as):
    response = _post(f"{PROJECT_BASE}/versions/2.0.0/binding/checks", state=STATE_PASS)
    assert response.status_code == 404
    assert _code(response) == "check-binding-not-found"


def test_a_binding_whose_registration_is_gone_is_a_conflict(fake, provider, act_as):
    fake.bindings[BINDING]["repository_id"] = None
    response = _post(state=STATE_PASS)
    assert response.status_code == 409
    assert _code(response) == "check-binding-released"


def test_an_unknown_project_or_version_is_a_404(fake, provider, act_as):
    assert _post("/v1/tenants/acme/projects/ghosts/versions/1.0.0/binding/checks").status_code == 404
    assert _post(f"{PROJECT_BASE}/versions/9.9.9/binding/checks").status_code == 404


# ---------------------------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------------------------


def test_a_recorded_verdict_is_published_and_the_attempt_is_visible(fake, provider, act_as):
    detail = _recorded(state=STATE_FAIL, title="2 breaking changes")
    assert len(provider.calls) == 1
    assert detail["deliveries"][0]["outcome"] == "dispatched"
    assert detail["deliveries"][0]["status_code"] == 201


def test_a_provider_refusal_still_returns_the_recorded_verdict(fake, provider, act_as):
    provider.status = 403
    provider.payload = {"message": "Resource not accessible by integration"}
    detail = _recorded(state=STATE_FAIL)
    # 201: the verdict was recorded, which is what the caller asked for. What the provider did is
    # on the check, where a caller can see it and act.
    assert detail["check"]["state"] == STATE_FAIL
    assert detail["deliveries"][0]["outcome"] == "failed"
    assert detail["deliveries"][0]["error_code"] == "check-provider-forbidden"
    assert detail["check"]["last_publish_outcome"] == "failed"


def test_publish_false_records_without_sending(fake, provider, act_as):
    detail = _recorded(state=STATE_SKIPPED, publish=False)
    assert detail["check"]["state"] == STATE_SKIPPED
    assert provider.calls == []
    assert detail["deliveries"] == []


def test_both_the_verdict_and_the_publish_are_audited(fake, provider, act_as):
    _recorded(state=STATE_PASS)
    assert _actions(fake) == ["check.recorded", "check.published"]


# ---------------------------------------------------------------------------------------------
# Credentials never cross the boundary
# ---------------------------------------------------------------------------------------------


def test_no_response_anywhere_carries_a_repository_token(fake, provider, act_as):
    provider.status = 403
    provider.payload = {"message": f"token {TOKEN} is not authorized"}
    recorded = _post(state=STATE_FAIL)
    assert TOKEN not in recorded.text
    check_id = recorded.json()["check"]["id"]
    for url in (
        f"{PROJECT_BASE}/checks",
        f"{PROJECT_BASE}/checks/{check_id}",
        CHECKS,
    ):
        response = client.get(url)
        assert response.status_code == 200, response.text
        assert TOKEN not in response.text
    assert "[repository-token-redacted]" in client.get(
        f"{PROJECT_BASE}/checks/{check_id}"
    ).text


def test_a_credential_offered_in_the_body_is_refused_outright(fake, provider, act_as):
    # The mirror of "browser clients never receive repository tokens": none may supply one either.
    assert _post(state=STATE_PASS, token=TOKEN).status_code == 422
    assert _post(state=STATE_PASS, access_token=TOKEN).status_code == 422


# ---------------------------------------------------------------------------------------------
# Reads and scoping
# ---------------------------------------------------------------------------------------------


def test_a_projects_checks_list_newest_first_with_the_adapter_providers(fake, provider, act_as):
    _recorded(state=STATE_PASS, name="apiome/one")
    _recorded(state=STATE_FAIL, name="apiome/two")
    body = client.get(f"{PROJECT_BASE}/checks").json()
    assert [check["name"] for check in body["checks"]] == ["apiome/two", "apiome/one"]
    assert body["count"] == 2
    assert body["providers"] == ["bitbucket", "github", "gitlab"]


def test_the_list_narrows_by_state_commit_and_version(fake, provider, act_as):
    _recorded(state=STATE_PASS, name="apiome/one")
    _recorded(state=STATE_FAIL, name="apiome/two", commit_sha=COMMIT_TWO)

    by_state = client.get(f"{PROJECT_BASE}/checks?state=fail").json()
    assert [check["name"] for check in by_state["checks"]] == ["apiome/two"]

    by_commit = client.get(f"{PROJECT_BASE}/checks?commit_sha={COMMIT_ONE}").json()
    assert [check["name"] for check in by_commit["checks"]] == ["apiome/one"]

    by_version = client.get(f"{PROJECT_BASE}/checks?version=1.0.0").json()
    assert by_version["count"] == 2


def test_an_unknown_state_filter_is_refused(fake, provider, act_as):
    response = client.get(f"{PROJECT_BASE}/checks?state=green")
    assert response.status_code == 422
    assert _code(response) == "check-invalid-state"


def test_a_versions_checks_are_the_checks_of_its_binding(fake, provider, act_as):
    _recorded(state=STATE_PASS)
    body = client.get(CHECKS).json()
    assert body["count"] == 1
    assert body["checks"][0]["version_id"] == VERSION_1


def test_a_check_is_not_readable_through_another_project(fake, provider, act_as):
    check_id = _recorded(state=STATE_PASS)["check"]["id"]
    response = client.get(f"/v1/tenants/acme/projects/orders/checks/{check_id}")
    assert response.status_code == 404
    assert _code(response) == "check-not-found"


def test_a_check_is_not_readable_from_another_tenant(fake, provider, act_as):
    check_id = _recorded(state=STATE_PASS)["check"]["id"]
    act_as(ALICE, OTHER_TENANT)
    assert client.get(f"{PROJECT_BASE}/checks/{check_id}").status_code == 404


def test_reading_a_check_brings_its_publish_attempts(fake, provider, act_as):
    check_id = _recorded(state=STATE_PASS)["check"]["id"]
    detail = client.get(f"{PROJECT_BASE}/checks/{check_id}").json()
    assert [delivery["outcome"] for delivery in detail["deliveries"]] == ["dispatched"]


# ---------------------------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------------------------


def test_recording_a_verdict_needs_versions_edit(fake, provider, act_as):
    fake.grants = {("projects", "view")}
    assert _post(state=STATE_PASS).status_code == 403
    fake.grants = {("versions", "edit")}
    assert _post(state=STATE_PASS).status_code == 201


def test_reading_checks_needs_projects_view(fake, provider, act_as):
    fake.grants = {("versions", "edit")}
    assert client.get(f"{PROJECT_BASE}/checks").status_code == 403
    fake.grants = {("projects", "view")}
    assert client.get(f"{PROJECT_BASE}/checks").status_code == 200


def test_a_credential_with_no_attributable_user_cannot_record_a_verdict(fake, provider, act_as):
    act_as(None)
    assert _post(state=STATE_PASS).status_code == 403


def test_a_credential_with_no_tenant_is_refused(fake, provider, act_as):
    app.dependency_overrides[validate_authentication] = lambda: {
        "auth_method": "jwt",
        "user_id": ALICE,
    }
    assert client.get(f"{PROJECT_BASE}/checks").status_code == 403


# ---------------------------------------------------------------------------------------------
# The published contract
# ---------------------------------------------------------------------------------------------


def _openapi() -> Dict[str, Any]:
    """The committed OpenAPI document."""
    return json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )


def test_the_check_routes_are_in_the_published_contract():
    paths = _openapi()["paths"]
    for path in (
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/checks",
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/checks/{check_id}",
        "/v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding/checks",
    ):
        assert path in paths, path


def test_no_schema_in_the_contract_offers_a_place_for_a_repository_token():
    schemas = _openapi()["components"]["schemas"]
    for name, schema in schemas.items():
        if not name.startswith("Check"):
            continue
        for field in schema.get("properties", {}):
            assert "token" not in field.lower()
            assert "secret" not in field.lower()


def test_a_details_link_that_is_not_http_is_refused_before_the_provider_sees_it(
    fake, provider, act_as
):
    response = _post(state=STATE_FAIL, details_url="javascript:alert(1)")
    assert response.status_code == 422
    assert _code(response) == "check-invalid-details-url"
    assert provider.calls == []
    assert fake.check_runs == {}


def test_a_commit_that_is_not_an_object_id_is_refused(fake, provider, act_as):
    response = _post(state=STATE_FAIL, commit_sha="main")
    assert response.status_code == 422
    assert _code(response) == "check-invalid-commit"
    assert fake.check_runs == {}


def test_a_short_commit_id_is_accepted_and_lowercased(fake, provider, act_as):
    check = _recorded(state=STATE_PASS, commit_sha="ABC1234")["check"]
    assert check["commit_sha"] == "abc1234"
