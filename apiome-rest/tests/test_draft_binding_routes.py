"""HTTP contract tests for branch-to-draft binding — GNC-2.1 (#4737).

``/v1/tenants/{tenant_slug}/projects/{project_ref}/versions/{version_ref}/binding`` and the
project's binding list. Storage is the in-memory :class:`tests.fake_binding_db.FakeBindingDb` and
the repository is a stand-in; everything above them is real — the RBAC guard, the store's rules,
and the credential resolution. Asserted here:

* **The acceptance criteria.** A draft has at most one active binding; binding authorization
  verifies repository access; a ref update creates an auditable sync candidate; the source digest
  and the binding history are retained and readable.
* The rules around them: which permission each verb needs, project and tenant scoping, the refusal
  codes and their statuses, and the OpenAPI contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import comment_store, draft_binding_routes, draft_binding_store, git_import_routes
from app.auth import validate_authentication
from app.draft_bindings import source_digest
from app.git_intake import GitFilesetResult, GitIntakeError, GitProvenance
from app.main import app
from tests.fake_binding_db import FakeBindingDb

client = TestClient(app)

TENANT = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0001"
OTHER_TENANT = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f00ff"
PROJECT = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0002"
OTHER_PROJECT = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0003"
VERSION_1 = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0010"
VERSION_2 = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0011"
REPOSITORY = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0020"
ALICE = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0101"
BOB = "9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0102"

COMMIT_ONE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COMMIT_TWO = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

PROJECT_BASE = "/v1/tenants/acme/projects/pets"
BINDING = f"{PROJECT_BASE}/versions/1.0.0/binding"


class Provider:
    """A stand-in for the repository the store reads through."""

    def __init__(self) -> None:
        self.members: Dict[str, str] = {"openapi.yaml": "openapi: 3.1.0\n"}
        self.commit_sha = COMMIT_ONE
        self.error: Optional[GitIntakeError] = None
        self.tokens: List[Optional[str]] = []

    def fetch(self, selector, *, access_token=None, require_root=True, **_kwargs) -> GitFilesetResult:
        """Answer a fileset read, recording the credential it was made with."""
        self.tokens.append(access_token)
        if self.error:
            raise self.error
        return GitFilesetResult(
            members=dict(self.members),
            root_path="",
            detection=None,
            provenance=GitProvenance(
                provider="github",
                repo_url="https://github.com/acme/specs",
                owner="acme",
                repo="specs",
                ref=(selector.ref or "main"),
                commit_sha=self.commit_sha,
                path=selector.path,
                browse_url="https://github.com/acme/specs",
            ),
        )


@pytest.fixture
def provider(monkeypatch) -> Provider:
    """The repository the store reads through, and the stored credential it uses."""
    fake_provider = Provider()
    monkeypatch.setattr(draft_binding_store, "fetch_git_fileset", fake_provider.fetch)
    monkeypatch.setattr(
        git_import_routes, "resolve_stored_git_token", lambda *a, **k: "stored-token"
    )
    return fake_provider


@pytest.fixture
def fake(monkeypatch) -> FakeBindingDb:
    """A seeded store, swapped in beneath the routes, the binding store, and the comment store."""
    store = FakeBindingDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION_1, "1.0.0")
    store.add_version(PROJECT, VERSION_2, "2.0.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs")
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob@example.com")
    for module in (comment_store, draft_binding_store, draft_binding_routes):
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


def _bind(base: str = BINDING, **body: Any):
    """Bind a version and return the raw response."""
    payload = {"repository_id": REPOSITORY, "ref": "main", "path": "spec", **body}
    return client.post(base, json=payload)


def _bound(**body: Any) -> Dict[str, Any]:
    """Bind a version, assert it was created, and return the detail."""
    response = _bind(**body)
    assert response.status_code == 201, response.text
    return response.json()


def _code(response) -> str:
    """The stable refusal code of an error response."""
    return response.json()["detail"]["code"]


def _actions(fake: FakeBindingDb) -> List[str]:
    """The audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------------------------


def test_binding_a_draft_records_the_ref_path_commit_and_digest(fake, provider, act_as):
    detail = _bound()
    binding = detail["binding"]
    assert binding["version_id"] == VERSION_1
    assert binding["repository_id"] == REPOSITORY
    assert (binding["provider"], binding["repo_full_name"]) == ("github", "acme/specs")
    assert (binding["ref"], binding["path"]) == ("main", "spec")
    assert binding["commit_sha"] == COMMIT_ONE
    assert binding["source_digest"] == source_digest(provider.members)
    assert binding["active"] is True
    assert binding["created_by_name"] == "Alice Anders"
    assert detail["pending"] == [] and detail["history"] == []


def test_binding_reads_the_repository_with_a_stored_credential(fake, provider, act_as):
    _bound()
    assert provider.tokens == ["stored-token"]


def test_a_credential_can_never_be_passed_in_the_body(fake, provider, act_as):
    response = _bind(token="ghp_secret")
    assert response.status_code == 422


def test_a_repository_the_credential_cannot_reach_is_refused_before_anything_is_written(
    fake, provider, act_as
):
    provider.error = GitIntakeError("no access", code="SOURCE_AUTH_REQUIRED")
    response = _bind()
    assert response.status_code == 403
    assert _code(response) == "binding-repository-forbidden"
    assert fake.bindings == {}


def test_an_unreachable_provider_is_a_bad_gateway(fake, provider, act_as):
    provider.error = GitIntakeError("down", code="SOURCE_UNREACHABLE")
    response = _bind()
    assert response.status_code == 502
    assert _code(response) == "binding-repository-unreachable"


def test_an_empty_selection_is_the_callers_to_fix(fake, provider, act_as):
    provider.error = GitIntakeError("nothing matched", code="SOURCE_SELECTION_EMPTY")
    response = _bind()
    assert response.status_code == 422
    assert _code(response) == "binding-invalid-source"


def test_a_published_version_cannot_be_bound(fake, provider, act_as):
    fake.publish(VERSION_1)
    response = _bind()
    assert response.status_code == 409
    assert _code(response) == "binding-version-published"


def test_a_draft_has_at_most_one_active_binding(fake, provider, act_as):
    _bound()
    response = _bind(ref="next")
    assert response.status_code == 409
    assert _code(response) == "binding-already-bound"
    assert len(fake.bindings) == 1


def test_replacing_releases_the_old_binding_and_keeps_it(fake, provider, act_as):
    first = _bound()["binding"]["id"]
    second = _bound(ref="next", replace=True)["binding"]["id"]
    assert first != second

    status = client.get(BINDING).json()
    assert status["binding"]["binding"]["id"] == second
    assert [row["id"] for row in status["released"]] == [first]
    assert status["released"][0]["release_reason"] == "replaced"
    assert _actions(fake) == ["binding.bound", "binding.rebound"]


def test_binding_requires_versions_edit(fake, provider, act_as):
    fake.grants = {("projects", "view")}
    assert _bind().status_code == 403
    fake.grants = {("versions", "edit")}
    assert _bind().status_code == 201


def test_an_unknown_project_or_version_is_a_not_found(fake, provider, act_as):
    assert _bind(base="/v1/tenants/acme/projects/ghost/versions/1.0.0/binding").status_code == 404
    assert _bind(base=f"{PROJECT_BASE}/versions/9.9.9/binding").status_code == 404


def test_a_version_of_another_tenant_is_invisible(fake, provider, act_as):
    act_as(ALICE, OTHER_TENANT)
    assert client.get(BINDING).status_code == 404


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------


def test_an_unbound_version_reports_itself_as_such(fake, provider, act_as):
    body = client.get(BINDING).json()
    assert body["bound"] is False
    assert body["binding"] is None
    assert body["published"] is False


def test_reading_requires_projects_view(fake, provider, act_as):
    _bound()
    fake.grants = {("versions", "edit")}
    assert client.get(BINDING).status_code == 403
    fake.grants = {("projects", "view")}
    assert client.get(BINDING).status_code == 200


def test_the_project_list_pages_and_filters_by_version_and_state(fake, provider, act_as):
    _bound()
    _bound(replace=True, ref="next")
    client.post(f"{PROJECT_BASE}/versions/2.0.0/binding", json={"repository_id": REPOSITORY, "ref": "main"})

    listed = client.get(f"{PROJECT_BASE}/bindings").json()
    assert (listed["total"], listed["count"]) == (3, 3)

    active = client.get(f"{PROJECT_BASE}/bindings", params={"active": True}).json()
    assert active["total"] == 2

    one_version = client.get(f"{PROJECT_BASE}/bindings", params={"version": "1.0.0"}).json()
    assert one_version["total"] == 2
    assert {row["version_id"] for row in one_version["bindings"]} == {VERSION_1}

    paged = client.get(f"{PROJECT_BASE}/bindings", params={"limit": 1, "offset": 1}).json()
    assert (paged["count"], paged["total"], paged["offset"]) == (1, 3, 1)


def test_one_binding_reads_back_by_id(fake, provider, act_as):
    binding_id = _bound()["binding"]["id"]
    detail = client.get(f"{PROJECT_BASE}/bindings/{binding_id}")
    assert detail.status_code == 200
    assert detail.json()["binding"]["id"] == binding_id
    assert client.get(f"{PROJECT_BASE}/bindings/{binding_id}".replace("pets", "orders")).status_code == 404


# ---------------------------------------------------------------------------------------------
# Ref updates
# ---------------------------------------------------------------------------------------------


def test_a_ref_update_creates_an_auditable_sync_candidate(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    provider.members = {"openapi.yaml": "openapi: 3.1.0\ninfo: {}\n"}

    response = client.post(f"{BINDING}/check")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert len(detail["pending"]) == 1
    candidate = detail["pending"][0]
    assert (candidate["from_commit_sha"], candidate["to_commit_sha"]) == (COMMIT_ONE, COMMIT_TWO)
    assert candidate["status"] == "pending"
    assert candidate["detected_by_name"] == "Alice Anders"
    # The draft's own binding did not move.
    assert detail["binding"]["commit_sha"] == COMMIT_ONE

    audit = fake.workflow_audits[-1]
    assert audit["action"] == "binding.sync_candidate"
    assert audit["version_id"] == VERSION_1
    assert audit["detail"]["to_commit_sha"] == COMMIT_TWO


def test_checking_an_unmoved_ref_is_a_conflict(fake, provider, act_as):
    _bound()
    response = client.post(f"{BINDING}/check")
    assert response.status_code == 409
    assert _code(response) == "binding-unchanged"


def test_checking_an_unbound_version_is_a_not_found(fake, provider, act_as):
    response = client.post(f"{BINDING}/check")
    assert response.status_code == 404
    assert _code(response) == "binding-not-found"


def test_applying_advances_the_binding_and_dismissing_does_not(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    candidate_id = client.post(f"{BINDING}/check").json()["pending"][0]["id"]

    applied = client.post(
        f"{BINDING}/candidates/{candidate_id}", json={"status": "applied", "note": "merged by hand"}
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["binding"]["commit_sha"] == COMMIT_TWO
    assert applied.json()["history"][0]["resolution_note"] == "merged by hand"

    provider.commit_sha = "cccccccccccccccccccccccccccccccccccccccc"
    next_id = client.post(f"{BINDING}/check").json()["pending"][0]["id"]
    dismissed = client.post(f"{BINDING}/candidates/{next_id}", json={"status": "dismissed"})
    assert dismissed.status_code == 200
    assert dismissed.json()["binding"]["commit_sha"] == COMMIT_TWO


def test_a_candidate_settles_once(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    candidate_id = client.post(f"{BINDING}/check").json()["pending"][0]["id"]
    assert client.post(f"{BINDING}/candidates/{candidate_id}", json={"status": "dismissed"}).status_code == 200
    again = client.post(f"{BINDING}/candidates/{candidate_id}", json={"status": "dismissed"})
    assert again.status_code == 409
    assert _code(again) == "binding-candidate-resolved"


def test_a_candidate_cannot_be_settled_into_a_state_only_the_system_sets(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    candidate_id = client.post(f"{BINDING}/check").json()["pending"][0]["id"]
    assert client.post(f"{BINDING}/candidates/{candidate_id}", json={"status": "superseded"}).status_code == 422


def test_an_unknown_candidate_is_a_not_found(fake, provider, act_as):
    _bound()
    missing = f"{BINDING}/candidates/9f3b7a10-2c4d-4e5f-8a9b-0c1d2e3f0eee"
    response = client.post(missing, json={"status": "dismissed"})
    assert response.status_code == 404
    assert _code(response) == "binding-candidate-not-found"


def test_settling_requires_versions_edit(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    candidate_id = client.post(f"{BINDING}/check").json()["pending"][0]["id"]
    fake.grants = {("projects", "view")}
    assert client.post(f"{BINDING}/candidates/{candidate_id}", json={"status": "dismissed"}).status_code == 403


# ---------------------------------------------------------------------------------------------
# Releasing
# ---------------------------------------------------------------------------------------------


def test_releasing_keeps_the_binding_as_history(fake, provider, act_as):
    binding_id = _bound()["binding"]["id"]
    response = client.delete(BINDING)
    assert response.status_code == 200, response.text
    released = response.json()
    assert released["id"] == binding_id
    assert released["active"] is False
    assert released["release_reason"] == "unbound"

    status = client.get(BINDING).json()
    assert status["bound"] is False
    assert [row["id"] for row in status["released"]] == [binding_id]
    assert status["released"][0]["source_digest"] == source_digest(provider.members)


def test_releasing_settles_what_was_outstanding(fake, provider, act_as):
    _bound()
    provider.commit_sha = COMMIT_TWO
    client.post(f"{BINDING}/check")
    client.delete(BINDING)
    assert all(row["status"] == "superseded" for row in fake.candidates.values())
    assert _actions(fake)[-1] == "binding.released"


def test_releasing_an_unbound_version_is_a_not_found(fake, provider, act_as):
    assert client.delete(BINDING).status_code == 404


def test_releasing_requires_versions_edit(fake, provider, act_as):
    _bound()
    fake.grants = {("projects", "view")}
    assert client.delete(BINDING).status_code == 403


def test_a_binding_survives_its_version_being_published(fake, provider, act_as):
    _bound()
    fake.publish(VERSION_1)
    status = client.get(BINDING).json()
    assert status["published"] is True
    assert status["bound"] is True
    # It can still be released — evidence stays readable, it just stops being live.
    assert client.delete(BINDING).status_code == 200


# ---------------------------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------------------------


def test_a_credential_without_a_user_cannot_bind(fake, provider, act_as):
    act_as(None)
    assert _bind().status_code == 403


def test_every_binding_endpoint_is_in_the_openapi_contract(fake):
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}"
    expected = {
        f"{base}/bindings": {"get"},
        f"{base}/bindings/{{binding_id}}": {"get"},
        f"{base}/versions/{{version_ref}}/binding": {"get", "post", "delete"},
        f"{base}/versions/{{version_ref}}/binding/check": {"post"},
        f"{base}/versions/{{version_ref}}/binding/candidates/{{candidate_id}}": {"post"},
    }
    live = app.openapi()["paths"]
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )["paths"]
    for path, methods in expected.items():
        assert methods <= set(live.get(path, {})), f"missing route {path}"
        assert methods <= set(committed.get(path, {})), f"openapi.json is stale for {path}"
