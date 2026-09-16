"""Store rules for branch-to-draft bindings — GNC-2.1 (#4737).

What the HTTP surface cannot isolate: that binding *proves* a repository read before it writes
anything, that the digest it stores is the one that read produced, that a ref update becomes a
candidate rather than a change, and — through the fake's ``interleave`` hook — what each write
reports when a concurrent writer wins the race between the store's read and its guarded write.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from app import comment_store, draft_binding_store, git_import_routes
from app.draft_bindings import (
    CODE_ALREADY_BOUND,
    CODE_CANDIDATE_NOT_FOUND,
    CODE_CANDIDATE_RESOLVED,
    CODE_CONFLICT,
    CODE_INVALID_SOURCE,
    CODE_NOT_FOUND,
    CODE_REPOSITORY_FORBIDDEN,
    CODE_REPOSITORY_NOT_FOUND,
    CODE_REPOSITORY_UNREACHABLE,
    CODE_UNCHANGED,
    CODE_VERSION_PUBLISHED,
    DraftBindingCreate,
    DraftBindingValidationError,
    SyncCandidateResolve,
    source_digest,
)
from app.git_intake import GitFilesetResult, GitIntakeError, GitProvenance
from tests.fake_binding_db import FakeBindingDb

TENANT = "7c1d2e30-1111-4aaa-8bbb-000000000001"
PROJECT = "7c1d2e30-1111-4aaa-8bbb-000000000002"
VERSION = "7c1d2e30-1111-4aaa-8bbb-000000000010"
OTHER_VERSION = "7c1d2e30-1111-4aaa-8bbb-000000000011"
REPOSITORY = "7c1d2e30-1111-4aaa-8bbb-000000000020"
ALICE = "7c1d2e30-1111-4aaa-8bbb-000000000101"
BOB = "7c1d2e30-1111-4aaa-8bbb-000000000102"

COMMIT_ONE = "1111111111111111111111111111111111111111"
COMMIT_TWO = "2222222222222222222222222222222222222222"


class Provider:
    """A stand-in for the repository the store reads through.

    Attributes:
        members: What the selection resolves to at the current commit.
        commit_sha: The commit the ref currently points at.
        error: Raised instead of answering, to simulate a refused or unreachable read.
        reads: One entry per read: ``(repo_url, ref, path, token)``.
    """

    def __init__(self) -> None:
        self.members: Dict[str, str] = {"openapi.yaml": "openapi: 3.1.0\n"}
        self.commit_sha = COMMIT_ONE
        self.error: Optional[GitIntakeError] = None
        self.reads: List[Any] = []

    def fetch(self, selector, *, access_token=None, require_root=True, **_kwargs) -> GitFilesetResult:
        """Answer a fileset read, recording what was asked for."""
        self.reads.append((selector.repo_url, selector.ref, selector.path, access_token))
        if self.error:
            raise self.error
        return GitFilesetResult(
            members=dict(self.members),
            root_path="",
            detection=None,
            provenance=GitProvenance(
                provider="github",
                repo_url="https://github.com/Acme/Specs",
                owner="Acme",
                repo="Specs",
                ref=(selector.ref or "main"),
                commit_sha=self.commit_sha,
                path=selector.path,
                browse_url="https://github.com/Acme/Specs",
            ),
        )


@pytest.fixture
def provider(monkeypatch) -> Provider:
    """A repository the store reads through, in place of the real git intake."""
    fake_provider = Provider()
    monkeypatch.setattr(draft_binding_store, "fetch_git_fileset", fake_provider.fetch)
    monkeypatch.setattr(
        git_import_routes, "resolve_stored_git_token", lambda *a, **k: "stored-token"
    )
    return fake_provider


@pytest.fixture
def fake(monkeypatch) -> FakeBindingDb:
    """A seeded store beneath :mod:`app.draft_binding_store`."""
    store = FakeBindingDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_version(PROJECT, OTHER_VERSION, "1.1.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs", default_branch="trunk")
    for user_id, name in ((ALICE, "Alice"), (BOB, "Bob")):
        store.add_member(user_id, name, f"{name.lower()}@example.com")
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(draft_binding_store, "db", store)
    return store


def _bind(version: str = "1.0.0", **kwargs) -> Any:
    """Bind a version through the store, defaulting to the registered repository."""
    request = DraftBindingCreate(**{"repository_id": REPOSITORY, "path": "spec", **kwargs})
    return draft_binding_store.bind_draft(TENANT, "pets", version, ALICE, request)


def _code_of(call) -> str:
    """Run a store call that must refuse, and return the refusal code."""
    with pytest.raises(DraftBindingValidationError) as refused:
        call()
    return refused.value.code


def _actions(fake: FakeBindingDb) -> List[str]:
    """The workflow-audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------------------------


def test_binding_stores_what_the_repository_read_produced(fake, provider):
    detail = _bind()
    binding = detail.binding
    assert binding.provider == "github"
    assert binding.repo_full_name == "acme/specs"
    assert binding.commit_sha == COMMIT_ONE
    assert binding.source_digest == source_digest(provider.members)
    assert binding.ref == "trunk"
    assert binding.path == "spec"
    assert binding.active is True
    assert binding.browse_url == f"https://github.com/Acme/Specs/tree/{COMMIT_ONE}/spec"
    assert _actions(fake) == ["binding.bound"]


def test_binding_reads_the_repository_before_it_writes_anything(fake, provider):
    provider.error = GitIntakeError("no access", code="SOURCE_AUTH_REQUIRED")
    assert _code_of(_bind) == CODE_REPOSITORY_FORBIDDEN
    assert fake.bindings == {}
    assert fake.workflow_audits == []


@pytest.mark.parametrize(
    "intake_code,expected",
    [
        ("SOURCE_AUTH_REQUIRED", CODE_REPOSITORY_FORBIDDEN),
        ("SOURCE_NOT_FOUND", CODE_REPOSITORY_NOT_FOUND),
        ("SOURCE_UNREACHABLE", CODE_REPOSITORY_UNREACHABLE),
        ("SOURCE_SELECTION_EMPTY", CODE_INVALID_SOURCE),
        ("INPUT_TOO_LARGE", CODE_INVALID_SOURCE),
    ],
)
def test_a_provider_refusal_keeps_its_meaning(fake, provider, intake_code, expected):
    provider.error = GitIntakeError("nope", code=intake_code)
    assert _code_of(_bind) == expected


def test_a_registered_repository_supplies_its_url_and_default_branch(fake, provider):
    _bind()
    repo_url, ref, path, token = provider.reads[-1]
    assert (repo_url, ref, path, token) == ("https://github.com/acme/specs", "trunk", "spec", "stored-token")


def test_an_explicit_ref_beats_the_registrations_default_branch(fake, provider):
    _bind(ref="refs/heads/release/2")
    assert provider.reads[-1][1] == "release/2"


def test_a_repository_of_another_tenant_is_simply_not_found(fake, provider):
    assert (
        _code_of(lambda: _bind(repository_id="7c1d2e30-1111-4aaa-8bbb-0000000000ff"))
        == CODE_REPOSITORY_NOT_FOUND
    )
    assert provider.reads == []


def test_naming_neither_a_repository_nor_a_url_is_an_invalid_source(fake, provider):
    request = DraftBindingCreate(path="spec")
    assert (
        _code_of(lambda: draft_binding_store.bind_draft(TENANT, "pets", "1.0.0", ALICE, request))
        == CODE_INVALID_SOURCE
    )


def test_a_published_version_cannot_be_bound(fake, provider):
    fake.publish(VERSION)
    assert _code_of(_bind) == CODE_VERSION_PUBLISHED
    assert provider.reads == []


def test_a_version_has_one_active_binding(fake, provider):
    _bind()
    assert _code_of(_bind) == CODE_ALREADY_BOUND
    assert len(fake.bindings) == 1


def test_re_binding_keeps_the_old_row_as_history(fake, provider):
    first = _bind().binding.id
    second = _bind(ref="next", replace=True).binding.id

    status = draft_binding_store.version_binding_status(TENANT, "pets", "1.0.0")
    assert status.bound is True
    assert status.binding.binding.id == second
    assert [row.id for row in status.released] == [first]
    assert status.released[0].release_reason == "replaced"
    assert status.released[0].ref == "trunk"
    assert _actions(fake) == ["binding.bound", "binding.rebound"]


def test_two_versions_of_one_project_can_each_be_bound(fake, provider):
    _bind("1.0.0")
    _bind("1.1.0")
    bindings, total = draft_binding_store.list_bindings(
        TENANT, "pets", draft_binding_store.BindingFilters(active=True)
    )
    assert total == 2
    assert {row.version_id for row in bindings} == {VERSION, OTHER_VERSION}


def test_losing_the_race_to_bind_names_what_is_there(fake, provider):
    fake.interleave = lambda: fake.insert_draft_binding(
        tenant_id=TENANT,
        project_id=PROJECT,
        version_id=VERSION,
        repository_id=REPOSITORY,
        provider="github",
        repo_full_name="acme/specs",
        repo_url="https://github.com/acme/specs",
        ref="trunk",
        path="spec",
        commit_sha=COMMIT_ONE,
        source_digest="sha256:other",
        created_by=BOB,
        replace=False,
    )
    assert _code_of(_bind) == CODE_ALREADY_BOUND


# ---------------------------------------------------------------------------------------------
# Releasing
# ---------------------------------------------------------------------------------------------


def test_releasing_keeps_the_row_and_settles_what_was_outstanding(fake, provider):
    _bind()
    provider.commit_sha = COMMIT_TWO
    draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)

    released = draft_binding_store.release_binding(TENANT, "pets", "1.0.0", ALICE)
    assert released.active is False
    assert released.release_reason == "unbound"
    assert released.released_by == ALICE
    assert all(row["status"] == "superseded" for row in fake.candidates.values())
    assert _actions(fake)[-1] == "binding.released"


def test_releasing_an_unbound_version_is_a_not_found(fake, provider):
    assert (
        _code_of(lambda: draft_binding_store.release_binding(TENANT, "pets", "1.0.0", ALICE))
        == CODE_NOT_FOUND
    )


def test_losing_the_race_to_release_is_a_conflict(fake, provider):
    binding_id = _bind().binding.id
    fake.interleave = lambda: fake.release_draft_binding(
        tenant_id=TENANT, project_id=PROJECT, binding_id=binding_id, actor_id=BOB, reason="unbound"
    )
    assert (
        _code_of(lambda: draft_binding_store.release_binding(TENANT, "pets", "1.0.0", ALICE))
        == CODE_CONFLICT
    )


def test_de_registering_the_repository_releases_its_bindings(fake, provider):
    _bind()
    fake.delete_tenant_repository(TENANT, REPOSITORY)
    status = draft_binding_store.version_binding_status(TENANT, "pets", "1.0.0")
    assert status.bound is False
    assert status.released[0].release_reason == "repository_removed"


# ---------------------------------------------------------------------------------------------
# Sync candidates
# ---------------------------------------------------------------------------------------------


def test_an_unmoved_ref_raises_nothing(fake, provider):
    _bind()
    assert (
        _code_of(lambda: draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE))
        == CODE_UNCHANGED
    )
    assert fake.candidates == {}


def test_a_moved_ref_becomes_a_candidate_and_leaves_the_binding_alone(fake, provider):
    _bind()
    before = fake.bindings[next(iter(fake.bindings))]["source_digest"]
    provider.commit_sha = COMMIT_TWO
    provider.members = {"openapi.yaml": "openapi: 3.1.0\ninfo: {}\n"}

    detail = draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    assert len(detail.pending) == 1
    candidate = detail.pending[0]
    assert (candidate.from_commit_sha, candidate.to_commit_sha) == (COMMIT_ONE, COMMIT_TWO)
    assert candidate.origin == "manual"
    assert candidate.detected_by == ALICE
    assert candidate.to_digest == source_digest(provider.members)
    # Nothing about the binding moved.
    assert detail.binding.commit_sha == COMMIT_ONE
    assert detail.binding.source_digest == before
    assert detail.binding.pending_candidate_count == 1
    assert _actions(fake) == ["binding.bound", "binding.sync_candidate"]


def test_checking_twice_for_the_same_head_raises_one_candidate(fake, provider):
    _bind()
    provider.commit_sha = COMMIT_TWO
    draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    detail = draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    assert len(detail.pending) == 1


def test_a_newer_head_supersedes_the_outstanding_candidate(fake, provider):
    _bind()
    provider.commit_sha = COMMIT_TWO
    draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    provider.commit_sha = "3" * 40
    detail = draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    assert [row.to_commit_sha for row in detail.pending] == ["3" * 40]
    assert [(row.status, row.to_commit_sha) for row in detail.history] == [("superseded", COMMIT_TWO)]


def test_checking_an_unbound_version_is_a_not_found(fake, provider):
    assert (
        _code_of(lambda: draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE))
        == CODE_NOT_FOUND
    )


def test_a_check_re_proves_repository_access(fake, provider):
    _bind()
    provider.error = GitIntakeError("no access", code="SOURCE_AUTH_REQUIRED")
    assert (
        _code_of(lambda: draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE))
        == CODE_REPOSITORY_FORBIDDEN
    )


# ---------------------------------------------------------------------------------------------
# Settling candidates
# ---------------------------------------------------------------------------------------------


def _raise_candidate(fake, provider) -> str:
    """Bind, move the ref, and return the outstanding candidate's id."""
    _bind()
    provider.commit_sha = COMMIT_TWO
    provider.members = {"openapi.yaml": "openapi: 3.1.0\ninfo: {}\n"}
    detail = draft_binding_store.check_for_updates(TENANT, "pets", "1.0.0", ALICE)
    return detail.pending[0].id


def test_applying_advances_the_binding_to_source_it_re_read(fake, provider):
    candidate_id = _raise_candidate(fake, provider)
    reads_before = len(provider.reads)

    detail = draft_binding_store.resolve_candidate(
        TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="applied", note="merged")
    )
    assert len(provider.reads) == reads_before + 1
    # The re-read is pinned to the candidate's commit, not to the ref, which may have moved again.
    assert provider.reads[-1][1] == COMMIT_TWO
    assert detail.binding.commit_sha == COMMIT_TWO
    assert detail.binding.source_digest == source_digest(provider.members)
    assert detail.pending == []
    assert [(row.status, row.resolution_note) for row in detail.history] == [("applied", "merged")]
    assert _actions(fake)[-1] == "binding.sync_resolved"


def test_dismissing_leaves_the_binding_exactly_where_it_was(fake, provider):
    candidate_id = _raise_candidate(fake, provider)
    reads_before = len(provider.reads)

    detail = draft_binding_store.resolve_candidate(
        TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="dismissed")
    )
    assert len(provider.reads) == reads_before
    assert detail.binding.commit_sha == COMMIT_ONE
    assert detail.pending == []
    assert [row.status for row in detail.history] == ["dismissed"]


def test_applying_refuses_when_the_source_can_no_longer_be_read(fake, provider):
    candidate_id = _raise_candidate(fake, provider)
    provider.error = GitIntakeError("gone", code="SOURCE_NOT_FOUND")
    assert (
        _code_of(
            lambda: draft_binding_store.resolve_candidate(
                TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="applied")
            )
        )
        == CODE_REPOSITORY_NOT_FOUND
    )
    assert fake.candidates[candidate_id]["status"] == "pending"


def test_a_candidate_settles_once(fake, provider):
    candidate_id = _raise_candidate(fake, provider)
    draft_binding_store.resolve_candidate(
        TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="dismissed")
    )
    assert (
        _code_of(
            lambda: draft_binding_store.resolve_candidate(
                TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="applied")
            )
        )
        == CODE_CANDIDATE_RESOLVED
    )


def test_an_unknown_candidate_is_a_not_found(fake, provider):
    _bind()
    assert (
        _code_of(
            lambda: draft_binding_store.resolve_candidate(
                TENANT,
                "pets",
                "1.0.0",
                "7c1d2e30-1111-4aaa-8bbb-0000000000ee",
                BOB,
                SyncCandidateResolve(status="dismissed"),
            )
        )
        == CODE_CANDIDATE_NOT_FOUND
    )


def test_losing_the_race_to_settle_is_a_conflict(fake, provider):
    candidate_id = _raise_candidate(fake, provider)
    binding_id = next(iter(fake.bindings))
    fake.interleave = lambda: fake.resolve_binding_sync_candidate(
        tenant_id=TENANT,
        project_id=PROJECT,
        binding_id=binding_id,
        candidate_id=candidate_id,
        status="dismissed",
        actor_id=BOB,
    )
    assert (
        _code_of(
            lambda: draft_binding_store.resolve_candidate(
                TENANT, "pets", "1.0.0", candidate_id, ALICE, SyncCandidateResolve(status="dismissed")
            )
        )
        == CODE_CONFLICT
    )


# ---------------------------------------------------------------------------------------------
# Provider-driven updates
# ---------------------------------------------------------------------------------------------


def test_a_ref_update_raises_one_candidate_per_bound_draft(fake, provider):
    _bind("1.0.0")
    _bind("1.1.0")
    raised = draft_binding_store.record_ref_update(
        fake, repository_id=REPOSITORY, ref="refs/heads/trunk", to_commit_sha=COMMIT_TWO, delivery_id="d1"
    )
    assert raised == 2
    assert {row["origin"] for row in fake.candidates.values()} == {"webhook"}
    # A delivery names a commit, not a document: the new digest stays unread until somebody looks.
    assert {row["to_digest"] for row in fake.candidates.values()} == {None}


def test_a_redelivery_raises_nothing_new(fake, provider):
    _bind()
    first = draft_binding_store.record_ref_update(
        fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha=COMMIT_TWO, delivery_id="d1"
    )
    again = draft_binding_store.record_ref_update(
        fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha=COMMIT_TWO, delivery_id="d1"
    )
    assert (first, again) == (1, 0)
    assert len(fake.candidates) == 1


def test_a_redelivery_cannot_resurrect_a_dismissed_candidate(fake, provider):
    _bind()
    draft_binding_store.record_ref_update(
        fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha=COMMIT_TWO, delivery_id="d1"
    )
    candidate_id = next(iter(fake.candidates))
    draft_binding_store.resolve_candidate(
        TENANT, "pets", "1.0.0", candidate_id, BOB, SyncCandidateResolve(status="dismissed")
    )
    assert (
        draft_binding_store.record_ref_update(
            fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha=COMMIT_TWO, delivery_id="d1"
        )
        == 0
    )
    assert len(fake.candidates) == 1


def test_an_unbound_ref_raises_nothing(fake, provider):
    _bind()
    assert (
        draft_binding_store.record_ref_update(
            fake, repository_id=REPOSITORY, ref="other", to_commit_sha=COMMIT_TWO
        )
        == 0
    )
    assert fake.candidates == {}


def test_a_released_binding_is_never_a_candidate_target(fake, provider):
    _bind()
    draft_binding_store.release_binding(TENANT, "pets", "1.0.0", ALICE)
    assert (
        draft_binding_store.record_ref_update(
            fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha=COMMIT_TWO
        )
        == 0
    )


def test_a_delivery_without_a_ref_or_a_commit_raises_nothing(fake, provider):
    _bind()
    assert draft_binding_store.record_ref_update(fake, repository_id=REPOSITORY, ref="", to_commit_sha=COMMIT_TWO) == 0
    assert draft_binding_store.record_ref_update(fake, repository_id=REPOSITORY, ref="trunk", to_commit_sha="") == 0


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def test_a_version_of_another_project_is_not_found(fake, provider):
    fake.add_project(TENANT, "7c1d2e30-1111-4aaa-8bbb-000000000003", "orders")
    assert (
        _code_of(lambda: draft_binding_store.version_binding_status(TENANT, "orders", "1.0.0"))
        == "binding-version-not-found"
    )


def test_a_binding_of_another_tenant_is_not_found(fake, provider):
    binding_id = _bind().binding.id
    assert (
        _code_of(lambda: draft_binding_store.get_binding("7c1d2e30-1111-4aaa-8bbb-0000000000aa", "pets", binding_id))
        == "binding-project-not-found"
    )


def test_an_unbound_version_reports_itself_as_such(fake, provider):
    status = draft_binding_store.version_binding_status(TENANT, "pets", "1.0.0")
    assert (status.bound, status.binding, status.released) == (False, None, [])
    assert status.published is False
    assert status.version_label == "1.0.0"
