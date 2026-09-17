"""HTTP contract tests for three-way spec synchronization — GNC-2.3 (#4739).

``…/versions/{version_ref}/binding/sync`` and ``…/sync-plans/{plan_id}``. Storage is the in-memory
:class:`tests.fake_sync_db.FakeSyncDb`, the repository and the canonical model are stand-ins, and
everything above them is real — the RBAC guard, the store's rules, and the credential resolution.
Asserted here:

* **The acceptance criteria.** Overlapping changes come back as explicit conflicts with base,
  incoming and current values and a source location; non-overlapping changes come back applied; the
  draft and any review decision survive untouched; every result records all three digests.
* The rules around them: which permission each verb needs, project and tenant scoping, the refusal
  codes and their statuses, rerun idempotency, and the OpenAPI contract.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml
from fastapi.testclient import TestClient

from app import (
    comment_store,
    draft_binding_routes,
    draft_binding_store,
    git_import_routes,
    spec_sync_routes,
    spec_sync_store,
)
from app.auth import validate_authentication
from app.git_intake import GitFilesetResult, GitIntakeError, GitProvenance
from app.main import app
from tests.fake_sync_db import FakeSyncDb

client = TestClient(app)

TENANT = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0001"
OTHER_TENANT = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f00ff"
PROJECT = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0002"
OTHER_PROJECT = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0003"
VERSION = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0010"
REPOSITORY = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0020"
REVIEW = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0030"
ALICE = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0101"
BOB = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0102"

COMMIT_BASE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COMMIT_NEXT = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

PROJECT_BASE = "/v1/tenants/acme/projects/pets"
SYNC = f"{PROJECT_BASE}/versions/1.0.0/binding/sync"

BASE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {"/pets": {"get": {"summary": "List pets"}}},
}


class Provider:
    """A repository whose selection differs from commit to commit."""

    def __init__(self) -> None:
        self.documents: Dict[str, Dict[str, Any]] = {
            COMMIT_BASE: copy.deepcopy(BASE_SPEC),
            COMMIT_NEXT: copy.deepcopy(BASE_SPEC),
        }
        self.error: Optional[GitIntakeError] = None
        self.tokens: List[Optional[str]] = []

    def at(self, commit: str) -> Dict[str, Any]:
        """The document one commit's selection holds, for a test to edit."""
        return self.documents[commit]

    def fetch(self, selector, *, access_token=None, require_root=True, **_kwargs) -> GitFilesetResult:
        """Answer a fileset read, recording the credential it was made with."""
        self.tokens.append(access_token)
        if self.error:
            raise self.error
        commit = selector.ref if selector.ref in self.documents else COMMIT_BASE
        return GitFilesetResult(
            members={"openapi.yaml": yaml.safe_dump(self.documents[commit], sort_keys=False)},
            root_path="openapi.yaml" if require_root else "",
            detection=None,
            provenance=GitProvenance(
                provider="github",
                repo_url="https://github.com/acme/specs",
                owner="acme",
                repo="specs",
                ref=(selector.ref or "main"),
                commit_sha=commit,
                path=selector.path,
                browse_url="https://github.com/acme/specs",
            ),
            member_prefix="",
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
def draft(monkeypatch) -> Dict[str, Any]:
    """The draft document, in place of a rebuild from the canonical model."""
    document = copy.deepcopy(BASE_SPEC)
    monkeypatch.setattr(spec_sync_store, "openapi_for_revision", lambda *a: copy.deepcopy(document))
    return document


@pytest.fixture
def fake(monkeypatch, provider) -> FakeSyncDb:
    """A seeded store with one bound draft, swapped in beneath every layer."""
    store = FakeSyncDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_project(TENANT, OTHER_PROJECT, "orders")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs")
    store.add_member(ALICE, "Alice Anders", "alice@example.com")
    store.add_member(BOB, "Bob Brown", "bob@example.com")
    for module in (
        comment_store,
        draft_binding_store,
        draft_binding_routes,
        spec_sync_store,
        spec_sync_routes,
    ):
        monkeypatch.setattr(module, "db", store)
    from app.draft_bindings import DraftBindingCreate

    draft_binding_store.bind_draft(
        TENANT,
        "pets",
        "1.0.0",
        ALICE,
        DraftBindingCreate(repository_id=REPOSITORY, ref=COMMIT_BASE, path=""),
    )
    provider.tokens.clear()
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


def _move_to(fake: FakeSyncDb, commit: str = COMMIT_NEXT) -> str:
    """Raise a pending sync candidate for a commit the ref has moved to."""
    binding_id = next(iter(fake.bindings))
    raised = fake.raise_binding_sync_candidate(
        tenant_id=TENANT, binding_id=binding_id, to_commit_sha=commit, origin="webhook"
    )
    return str(raised["candidate_id"])


def _merged(**body: Any) -> Dict[str, Any]:
    """Compute a merge, assert it worked, and return the detail."""
    response = client.post(SYNC, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _code(response) -> str:
    """The stable refusal code of an error response."""
    return response.json()["detail"]["code"]


def _actions(fake: FakeSyncDb) -> List[str]:
    """The audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# Computing a merge
# ---------------------------------------------------------------------------------------------


def test_a_merge_records_the_base_git_and_draft_digests(fake, provider, draft, act_as):
    provider.at(COMMIT_NEXT)["info"]["description"] = "Pets as a service"
    _move_to(fake)

    plan = _merged()["plan"]

    assert plan["status"] == "mergeable"
    assert plan["base_commit_sha"] == COMMIT_BASE
    assert plan["git_commit_sha"] == COMMIT_NEXT
    for key in ("base_digest", "git_digest", "draft_digest"):
        assert plan[key].startswith("sha256:")
    assert plan["computed_by_name"] == "Alice Anders"
    assert plan["source_file"] == "openapi.yaml"
    assert _actions(fake)[-1] == "sync.planned"


def test_a_non_overlapping_change_comes_back_applied(fake, provider, draft, act_as):
    provider.at(COMMIT_NEXT)["paths"]["/pets"]["get"]["description"] = "Every pet"
    _move_to(fake)

    detail = _merged()

    assert detail["plan"]["auto_applied_count"] == 1
    change = detail["plan"]["changes"][0]
    assert change["pointer"] == "/paths/~1pets/get/description"
    assert (change["kind"], change["scope"], change["group"]) == ("addition", "operation", "GET /pets")
    assert change["after"] == "Every pet"
    assert detail["conflicts"] == []


def test_an_overlapping_change_comes_back_as_a_located_conflict(fake, provider, draft, act_as):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft["info"]["version"] = "1.5.0"
    _move_to(fake)

    detail = _merged()

    assert detail["plan"]["status"] == "conflicted"
    assert detail["plan"]["unresolved_count"] == 1
    conflict = detail["conflicts"][0]
    assert conflict["pointer"] == "/info/version"
    assert (conflict["base_value"], conflict["git_value"], conflict["draft_value"]) == (
        "1.0.0",
        "2.0.0",
        "1.5.0",
    )
    assert (conflict["git_kind"], conflict["draft_kind"]) == ("update", "update")
    assert conflict["source_file"] == "openapi.yaml"
    assert conflict["source_url"].endswith(f"/blob/{COMMIT_NEXT}/openapi.yaml#L4")
    assert conflict["resolution"] is None


def test_computing_a_merge_reads_the_repository_with_a_stored_credential(
    fake, provider, draft, act_as
):
    _move_to(fake)
    _merged()
    # Two proven reads: the merge base and the incoming commit.
    assert provider.tokens == ["stored-token", "stored-token"]


def test_a_repository_the_credential_cannot_reach_is_refused_before_anything_is_written(
    fake, provider, draft, act_as
):
    _move_to(fake)
    provider.error = GitIntakeError("no access", code="SOURCE_AUTH_REQUIRED")
    response = client.post(SYNC, json={})
    assert response.status_code == 403
    assert _code(response) == "binding-repository-forbidden"
    assert fake.sync_plans == {}


def test_a_rewritten_merge_base_is_a_conflict_not_a_guess(fake, provider, draft, act_as):
    _move_to(fake)
    provider.at(COMMIT_BASE)["info"]["title"] = "Something else entirely"
    response = client.post(SYNC, json={})
    assert response.status_code == 409
    assert _code(response) == "sync-base-drifted"


def test_a_version_that_is_not_bound_has_nothing_to_merge_against(fake, provider, draft, act_as):
    fake.add_version(PROJECT, "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f0011", "2.0.0")
    response = client.post(f"{PROJECT_BASE}/versions/2.0.0/binding/sync", json={})
    assert response.status_code == 404
    assert _code(response) == "sync-not-bound"


def test_a_ref_that_has_not_moved_has_nothing_to_merge(fake, provider, draft, act_as):
    response = client.post(SYNC, json={})
    assert response.status_code == 409
    assert _code(response) == "sync-nothing-to-merge"


def test_a_request_may_not_smuggle_a_credential(fake, provider, draft, act_as):
    _move_to(fake)
    assert client.post(SYNC, json={"token": "ghp_secret"}).status_code == 422


def test_rerunning_a_merge_of_the_same_three_documents_returns_the_same_result(
    fake, provider, draft, act_as
):
    provider.at(COMMIT_NEXT)["info"]["description"] = "Pets as a service"
    _move_to(fake)
    first = _merged()
    provider.tokens.clear()

    second = _merged()

    assert second["plan"]["id"] == first["plan"]["id"]
    assert provider.tokens == []
    assert _actions(fake).count("sync.planned") == 1


# ---------------------------------------------------------------------------------------------
# What the merge must never touch
# ---------------------------------------------------------------------------------------------


def test_a_merge_never_rewrites_the_draft(fake, provider, draft, act_as):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    before = copy.deepcopy(draft)
    _move_to(fake)
    _merged()
    assert draft == before
    assert fake.versions[VERSION]["version_id"] == "1.0.0"


def test_a_recorded_review_decision_is_reported_and_left_alone(fake, provider, draft, act_as):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft["info"]["version"] = "1.5.0"
    fake.open_review(VERSION, REVIEW, decisions=["approve"])
    _move_to(fake)

    plan = _merged()["plan"]

    assert plan["guard"] == "review_decided"
    assert fake.review_reviewers[REVIEW] == [{"round": 1, "decision": "approve"}]


def test_a_published_version_still_merges_but_says_it_may_not_be_edited(
    fake, provider, draft, act_as
):
    _move_to(fake)
    fake.publish(VERSION)
    assert _merged()["plan"]["guard"] == "version_published"


# ---------------------------------------------------------------------------------------------
# Settling conflicts
# ---------------------------------------------------------------------------------------------


def _conflicted(fake, provider, draft) -> Dict[str, Any]:
    """A stored plan with one outstanding conflict."""
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft["info"]["version"] = "1.5.0"
    _move_to(fake)
    return _merged()


def _conflict_url(detail: Dict[str, Any], index: int = 0) -> str:
    """The settle endpoint of one conflict of a plan."""
    return (
        f"{PROJECT_BASE}/sync-plans/{detail['plan']['id']}"
        f"/conflicts/{detail['conflicts'][index]['id']}"
    )


def test_settling_the_last_conflict_resolves_the_plan(fake, provider, draft, act_as):
    detail = _conflicted(fake, provider, draft)
    response = client.post(
        _conflict_url(detail), json={"resolution": "git", "note": "the repository is right"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"]["status"] == "resolved"
    assert body["plan"]["unresolved_count"] == 0
    assert body["plan"]["conflict_count"] == 1
    conflict = body["conflicts"][0]
    assert (conflict["resolution"], conflict["resolution_note"]) == (
        "git",
        "the repository is right",
    )
    assert _actions(fake)[-1] == "sync.conflict_resolved"


def test_a_settlement_is_final(fake, provider, draft, act_as):
    detail = _conflicted(fake, provider, draft)
    url = _conflict_url(detail)
    assert client.post(url, json={"resolution": "git"}).status_code == 200
    again = client.post(url, json={"resolution": "draft"})
    assert again.status_code == 409
    assert _code(again) == "sync-conflict-resolved"


def test_only_the_two_sides_may_be_chosen(fake, provider, draft, act_as):
    detail = _conflicted(fake, provider, draft)
    assert client.post(_conflict_url(detail), json={"resolution": "mine"}).status_code == 422


def test_an_unknown_plan_or_conflict_is_not_found(fake, provider, draft, act_as):
    detail = _conflicted(fake, provider, draft)
    missing = "5a6b7c80-3d4e-4f50-9a1b-2c3d4e5f00aa"
    plan_id = detail["plan"]["id"]
    for url, code in (
        (f"{PROJECT_BASE}/sync-plans/{missing}/conflicts/{detail['conflicts'][0]['id']}",
         "sync-plan-not-found"),
        (f"{PROJECT_BASE}/sync-plans/{plan_id}/conflicts/{missing}", "sync-conflict-not-found"),
    ):
        response = client.post(url, json={"resolution": "git"})
        assert response.status_code == 404
        assert _code(response) == code


# ---------------------------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------------------------


def test_the_version_view_carries_the_newest_merge_and_its_history(fake, provider, draft, act_as):
    _move_to(fake)
    first = _merged()
    draft["info"]["contact"] = {"name": "Platform"}
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft["info"]["version"] = "1.5.0"
    second = _merged()

    body = client.get(SYNC).json()
    assert body["bound"] is True
    assert body["latest"]["plan"]["id"] == second["plan"]["id"]
    assert len(body["latest"]["conflicts"]) == 1
    assert [plan["id"] for plan in body["history"]] == [first["plan"]["id"]]


def test_a_result_computed_against_an_older_draft_reads_as_stale(fake, provider, draft, act_as):
    _move_to(fake)
    plan_id = _merged()["plan"]["id"]
    draft["info"]["contact"] = {"name": "Platform"}
    body = client.get(f"{PROJECT_BASE}/sync-plans/{plan_id}").json()
    assert body["plan"]["stale"] is True


def test_a_plan_of_another_project_is_not_found(fake, provider, draft, act_as):
    _move_to(fake)
    plan_id = _merged()["plan"]["id"]
    response = client.get(f"/v1/tenants/acme/projects/orders/sync-plans/{plan_id}")
    assert response.status_code == 404
    assert _code(response) == "sync-plan-not-found"


def test_another_tenant_sees_nothing(fake, provider, draft, act_as):
    _move_to(fake)
    plan_id = _merged()["plan"]["id"]
    act_as(ALICE, OTHER_TENANT)
    assert client.get(f"{PROJECT_BASE}/sync-plans/{plan_id}").status_code == 404
    assert client.get(SYNC).status_code == 404


# ---------------------------------------------------------------------------------------------
# Permissions and contract
# ---------------------------------------------------------------------------------------------


def test_reading_needs_projects_view(fake, provider, draft, act_as):
    fake.grants = set()
    assert client.get(SYNC).status_code == 403
    fake.grants = {("projects", "view")}
    assert client.get(SYNC).status_code == 200


def test_every_write_needs_versions_edit(fake, provider, draft, act_as):
    detail = _conflicted(fake, provider, draft)
    fake.grants = {("projects", "view")}
    assert client.post(SYNC, json={}).status_code == 403
    assert client.post(_conflict_url(detail), json={"resolution": "git"}).status_code == 403


def test_a_credential_without_a_user_cannot_merge(fake, provider, draft, act_as):
    _move_to(fake)
    act_as(None)
    assert client.post(SYNC, json={}).status_code == 403


def test_every_synchronization_endpoint_is_in_the_openapi_contract(fake):
    base = "/v1/tenants/{tenant_slug}/projects/{project_ref}"
    expected = {
        f"{base}/versions/{{version_ref}}/binding/sync": {"get", "post"},
        f"{base}/sync-plans/{{plan_id}}": {"get"},
        f"{base}/sync-plans/{{plan_id}}/conflicts/{{conflict_id}}": {"post"},
    }
    live = app.openapi()["paths"]
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "openapi.json").read_text(encoding="utf-8")
    )["paths"]
    for path, methods in expected.items():
        assert methods <= set(live.get(path, {})), f"missing route {path}"
        assert methods <= set(committed.get(path, {})), f"openapi.json is stale for {path}"
