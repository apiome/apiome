"""Store rules for three-way spec synchronization — GNC-2.3 (#4739).

What the merge engine cannot settle on its own: that the three documents are *proven reads*, that a
rewritten merge base refuses instead of guessing, that a rerun of an unchanged trio costs nothing,
that a recorded review decision is reported rather than trampled — and, above all, that computing
and settling a merge leave the draft exactly where it was.

The provider is a double, so every read is observable; the database is
:class:`tests.fake_sync_db.FakeSyncDb`, whose ``interleave`` hook stands in for a concurrent writer.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pytest
import yaml

from app import comment_store, draft_binding_store, git_import_routes, spec_sync_store
from app.draft_bindings import (
    CODE_REPOSITORY_FORBIDDEN,
    DraftBindingCreate,
    DraftBindingValidationError,
)
from app.git_intake import GitFilesetResult, GitIntakeError, GitProvenance
from app.spec_sync import (
    CODE_BASE_DRIFTED,
    CODE_CONFLICT,
    CODE_CONFLICT_NOT_FOUND,
    CODE_CONFLICT_RESOLVED,
    CODE_INVALID_DOCUMENT,
    CODE_NOT_BOUND,
    CODE_NOTHING_TO_MERGE,
    CODE_PLAN_NOT_FOUND,
    GUARD_NONE,
    GUARD_REVIEW_DECIDED,
    GUARD_VERSION_PUBLISHED,
    STATUS_CLEAN,
    STATUS_CONFLICTED,
    STATUS_MERGEABLE,
    STATUS_RESOLVED,
    SpecSyncValidationError,
    SyncConflictResolve,
    SyncPlanCompute,
)
from tests.fake_sync_db import FakeSyncDb

TENANT = "8d2e3f40-2222-4bbb-9ccc-000000000001"
PROJECT = "8d2e3f40-2222-4bbb-9ccc-000000000002"
VERSION = "8d2e3f40-2222-4bbb-9ccc-000000000010"
REPOSITORY = "8d2e3f40-2222-4bbb-9ccc-000000000020"
REVIEW = "8d2e3f40-2222-4bbb-9ccc-000000000030"
ALICE = "8d2e3f40-2222-4bbb-9ccc-000000000101"
BOB = "8d2e3f40-2222-4bbb-9ccc-000000000102"

COMMIT_BASE = "1111111111111111111111111111111111111111"
COMMIT_NEXT = "2222222222222222222222222222222222222222"

BASE_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {"/pets": {"get": {"summary": "List pets"}}},
}


def _yaml(document: Dict[str, Any]) -> str:
    """Serialize a document the way a repository file holds one."""
    return yaml.safe_dump(document, sort_keys=False)


class Provider:
    """A repository whose selection differs from commit to commit.

    Attributes:
        documents: Commit sha -> the document that commit's selection holds.
        error: Raised instead of answering, to simulate a refused or unreachable read.
        reads: One entry per read: ``(ref, path, token)``.
    """

    def __init__(self) -> None:
        self.documents: Dict[str, Dict[str, Any]] = {
            COMMIT_BASE: copy.deepcopy(BASE_SPEC),
            COMMIT_NEXT: copy.deepcopy(BASE_SPEC),
        }
        self.error: Optional[GitIntakeError] = None
        self.reads: List[Any] = []

    def at(self, commit: str) -> Dict[str, Any]:
        """The document one commit's selection holds, for a test to edit."""
        return self.documents[commit]

    def fetch(self, selector, *, access_token=None, require_root=True, **_kwargs) -> GitFilesetResult:
        """Answer a fileset read, recording what was asked for."""
        self.reads.append((selector.ref, selector.path, access_token))
        if self.error:
            raise self.error
        commit = selector.ref if selector.ref in self.documents else COMMIT_BASE
        return GitFilesetResult(
            members={"openapi.yaml": _yaml(self.documents[commit])},
            root_path="openapi.yaml" if require_root else "",
            detection=None,
            provenance=GitProvenance(
                provider="github",
                repo_url="https://github.com/Acme/Specs",
                owner="Acme",
                repo="Specs",
                ref=(selector.ref or "main"),
                commit_sha=commit,
                path=selector.path,
                browse_url="https://github.com/Acme/Specs",
            ),
            member_prefix="spec/",
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


class Draft:
    """The canonical model's side of the merge, in place of a rebuild from the database.

    Attributes:
        document: What ``openapi_for_revision`` would produce for the bound version.
        rebuilds: How many times it has been asked for.
    """

    def __init__(self) -> None:
        self.document: Dict[str, Any] = copy.deepcopy(BASE_SPEC)
        self.rebuilds = 0

    def build(self, _version: Dict[str, Any], _slug: str, _tenant_id: str) -> Dict[str, Any]:
        """Answer a rebuild."""
        self.rebuilds += 1
        return copy.deepcopy(self.document)


@pytest.fixture
def draft(monkeypatch) -> Draft:
    """The draft document the store merges into."""
    fake_draft = Draft()
    monkeypatch.setattr(spec_sync_store, "openapi_for_revision", fake_draft.build)
    return fake_draft


@pytest.fixture
def fake(monkeypatch, provider) -> FakeSyncDb:
    """A seeded store with one bound draft, beneath :mod:`app.spec_sync_store`."""
    store = FakeSyncDb()
    store.add_project(TENANT, PROJECT, "pets")
    store.add_version(PROJECT, VERSION, "1.0.0")
    store.add_repository(TENANT, REPOSITORY, clone_url="https://github.com/acme/specs")
    for user_id, name in ((ALICE, "Alice"), (BOB, "Bob")):
        store.add_member(user_id, name, f"{name.lower()}@example.com")
    monkeypatch.setattr(comment_store, "db", store)
    monkeypatch.setattr(draft_binding_store, "db", store)
    monkeypatch.setattr(spec_sync_store, "db", store)
    draft_binding_store.bind_draft(
        TENANT,
        "pets",
        "1.0.0",
        ALICE,
        DraftBindingCreate(repository_id=REPOSITORY, ref=COMMIT_BASE, path="spec"),
    )
    provider.reads.clear()
    return store


def _move_to(fake: FakeSyncDb, commit: str = COMMIT_NEXT) -> str:
    """Raise a pending sync candidate for a commit the ref has moved to."""
    binding_id = next(iter(fake.bindings))
    raised = fake.raise_binding_sync_candidate(
        tenant_id=TENANT, binding_id=binding_id, to_commit_sha=commit, origin="webhook"
    )
    return str(raised["candidate_id"])


def _compute(**kwargs: Any) -> Any:
    """Compute a merge for the bound draft."""
    return spec_sync_store.compute_plan(
        TENANT, "pets", "1.0.0", ALICE, SyncPlanCompute(**kwargs)
    )


def _code_of(call) -> str:
    """Run a store call that must refuse, and return the refusal code."""
    with pytest.raises((SpecSyncValidationError, DraftBindingValidationError)) as refused:
        call()
    return refused.value.code


def _actions(fake: FakeSyncDb) -> List[str]:
    """The workflow-audit actions written so far, in order."""
    return [row["action"] for row in fake.workflow_audits]


# ---------------------------------------------------------------------------------------------
# What a merge needs before it can run
# ---------------------------------------------------------------------------------------------


def test_an_unbound_version_has_nothing_to_merge_against(fake, provider, draft):
    fake.add_version(PROJECT, "8d2e3f40-2222-4bbb-9ccc-000000000011", "2.0.0")
    assert (
        _code_of(
            lambda: spec_sync_store.compute_plan(
                TENANT, "pets", "2.0.0", ALICE, SyncPlanCompute()
            )
        )
        == CODE_NOT_BOUND
    )
    assert provider.reads == []


def test_a_binding_whose_ref_has_not_moved_refuses_without_reading_anything(fake, provider, draft):
    assert _code_of(_compute) == CODE_NOTHING_TO_MERGE
    assert provider.reads == []
    assert fake.sync_plans == {}


def test_a_candidate_from_another_binding_is_not_a_target(fake, provider, draft):
    _move_to(fake)
    assert (
        _code_of(lambda: _compute(candidate_id="8d2e3f40-2222-4bbb-9ccc-0000000000ff"))
        == CODE_NOTHING_TO_MERGE
    )


def test_a_repository_refusal_keeps_its_binding_vocabulary(fake, provider, draft):
    _move_to(fake)
    provider.error = GitIntakeError("no access", code="SOURCE_AUTH_REQUIRED")
    assert _code_of(_compute) == CODE_REPOSITORY_FORBIDDEN
    assert fake.sync_plans == {}


def test_a_selection_that_is_not_a_spec_document_refuses(fake, provider, draft, monkeypatch):
    _move_to(fake)
    provider.documents[COMMIT_BASE] = {}
    monkeypatch.setattr(
        spec_sync_store, "parse_document", lambda *a, **k: (_ for _ in ()).throw(
            spec_sync_store.IngestionError("not a document")
        )
    )
    assert _code_of(_compute) == CODE_INVALID_DOCUMENT
    assert fake.sync_plans == {}


def test_a_rewritten_merge_base_refuses_rather_than_guessing(fake, provider, draft):
    _move_to(fake)
    # Somebody force-pushed over the commit the binding was synchronized with, so the digest the
    # binding recorded no longer describes what is there.
    provider.at(COMMIT_BASE)["info"]["title"] = "Something else entirely"
    assert _code_of(_compute) == CODE_BASE_DRIFTED
    assert fake.sync_plans == {}
    assert [action for action in _actions(fake) if action.startswith("sync.")] == []


# ---------------------------------------------------------------------------------------------
# The merge itself
# ---------------------------------------------------------------------------------------------


def test_a_non_overlapping_change_is_recorded_as_applied_with_all_three_digests(
    fake, provider, draft
):
    provider.at(COMMIT_NEXT)["paths"]["/pets"]["get"]["description"] = "Every pet"
    candidate_id = _move_to(fake)

    detail = _compute()
    plan = detail.plan

    assert plan.status == STATUS_MERGEABLE
    assert plan.auto_applied_count == 1
    assert plan.conflict_count == 0
    assert [change.pointer for change in plan.changes] == ["/paths/~1pets/get/description"]
    assert plan.candidate_id == candidate_id
    # The acceptance criterion, literally: base, Git and draft digests are all on the row.
    assert plan.base_commit_sha == COMMIT_BASE
    assert plan.git_commit_sha == COMMIT_NEXT
    assert plan.base_digest.startswith("sha256:")
    assert plan.git_digest.startswith("sha256:")
    assert plan.draft_digest.startswith("sha256:")
    assert plan.base_digest != plan.git_digest
    assert _actions(fake)[-1] == "sync.planned"


def test_the_incoming_document_is_read_at_the_candidate_commit_not_the_branch(fake, provider, draft):
    _move_to(fake)
    _compute()
    assert [ref for ref, _path, _token in provider.reads] == [COMMIT_BASE, COMMIT_NEXT]
    assert {token for _ref, _path, token in provider.reads} == {"stored-token"}


def test_an_overlapping_change_becomes_a_conflict_located_in_the_repository(fake, provider, draft):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft.document["info"]["version"] = "1.5.0"
    _move_to(fake)

    detail = _compute()

    assert detail.plan.status == STATUS_CONFLICTED
    assert (detail.plan.conflict_count, detail.plan.unresolved_count) == (1, 1)
    conflict = detail.conflicts[0]
    assert conflict.pointer == "/info/version"
    assert (conflict.base_value, conflict.git_value, conflict.draft_value) == (
        "1.0.0",
        "2.0.0",
        "1.5.0",
    )
    # Located in the document *and* in the repository: file, line and a link at the commit.
    assert conflict.source_file == "spec/openapi.yaml"
    # `version:` is the fourth line of the serialized document, and the link opens it there.
    assert conflict.source_line == 4
    assert conflict.source_url == (
        f"https://github.com/Acme/Specs/blob/{COMMIT_NEXT}/spec/openapi.yaml#L4"
    )


def test_a_commit_that_changed_nothing_is_a_clean_merge(fake, provider, draft):
    _move_to(fake)
    detail = _compute()
    assert detail.plan.status == STATUS_CLEAN
    assert (detail.plan.auto_applied_count, detail.plan.conflict_count) == (0, 0)


def test_the_draft_is_untouched_by_computing_a_merge(fake, provider, draft):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    before = copy.deepcopy(draft.document)
    _move_to(fake)
    _compute()
    # The whole safety property: a merge reads the draft and writes a row, never the other way.
    assert draft.document == before
    assert fake.versions[VERSION] == {"id": VERSION, "project_id": PROJECT, "version_id": "1.0.0"}


# ---------------------------------------------------------------------------------------------
# Reruns
# ---------------------------------------------------------------------------------------------


def test_rerunning_an_unchanged_merge_returns_the_stored_result_without_reading(
    fake, provider, draft
):
    provider.at(COMMIT_NEXT)["info"]["description"] = "Pets as a service"
    _move_to(fake)
    first = _compute()
    provider.reads.clear()

    second = _compute()

    assert second.plan.id == first.plan.id
    assert provider.reads == []
    assert len(fake.sync_plans) == 1
    assert _actions(fake).count("sync.planned") == 1


def test_refresh_re_reads_but_still_does_not_write_a_second_answer(fake, provider, draft):
    _move_to(fake)
    first = _compute()
    provider.reads.clear()

    second = _compute(refresh=True)

    assert [ref for ref, _p, _t in provider.reads] == [COMMIT_BASE, COMMIT_NEXT]
    assert second.plan.id == first.plan.id
    assert len(fake.sync_plans) == 1


def test_a_draft_edited_since_the_merge_gets_its_own_result(fake, provider, draft):
    provider.at(COMMIT_NEXT)["info"]["description"] = "Pets as a service"
    _move_to(fake)
    first = _compute()

    draft.document["info"]["contact"] = {"name": "Platform"}
    second = _compute()

    assert second.plan.id != first.plan.id
    assert second.plan.draft_digest != first.plan.draft_digest


def test_a_stored_result_computed_against_an_older_draft_reads_as_stale(fake, provider, draft):
    _move_to(fake)
    plan_id = _compute().plan.id
    draft.document["info"]["contact"] = {"name": "Platform"}

    assert spec_sync_store.get_plan(TENANT, "pets", plan_id).plan.stale is True
    status = spec_sync_store.version_sync_status(TENANT, "pets", "1.0.0")
    assert status.latest is not None
    assert status.latest.plan.stale is True


# ---------------------------------------------------------------------------------------------
# Guards: work that already exists
# ---------------------------------------------------------------------------------------------


def test_an_ordinary_draft_carries_no_guard(fake, provider, draft):
    _move_to(fake)
    assert _compute().plan.guard == GUARD_NONE


def test_a_recorded_review_decision_is_reported_not_trampled(fake, provider, draft):
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft.document["info"]["version"] = "1.5.0"
    fake.open_review(VERSION, REVIEW, decisions=["approve", "pending"])
    _move_to(fake)

    detail = _compute()

    # The merge still computes — knowing what would collide is exactly what this reader needs —
    # but it says plainly that it may not become an edit.
    assert detail.plan.guard == GUARD_REVIEW_DECIDED
    assert detail.plan.status == STATUS_CONFLICTED
    assert fake.review_reviewers[REVIEW][0]["decision"] == "approve"


def test_a_review_whose_round_has_decided_nothing_yet_is_no_guard(fake, provider, draft):
    fake.open_review(VERSION, REVIEW, decisions=["pending", "pending"])
    _move_to(fake)
    assert _compute().plan.guard == GUARD_NONE


def test_a_decision_from_an_earlier_round_is_not_a_guard(fake, provider, draft):
    fake.open_review(VERSION, REVIEW, round_number=2, decisions=["pending"])
    fake.review_reviewers[REVIEW].append({"round": 1, "decision": "approve"})
    _move_to(fake)
    assert _compute().plan.guard == GUARD_NONE


def test_a_published_version_is_guarded(fake, provider, draft):
    _move_to(fake)
    fake.publish(VERSION)
    assert _compute().plan.guard == GUARD_VERSION_PUBLISHED


# ---------------------------------------------------------------------------------------------
# Settling conflicts
# ---------------------------------------------------------------------------------------------


def _conflicted(fake, provider, draft):
    """A plan with two outstanding conflicts."""
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    provider.at(COMMIT_NEXT)["paths"]["/pets"]["get"]["summary"] = "List every pet"
    draft.document["info"]["version"] = "1.5.0"
    draft.document["paths"]["/pets"]["get"]["summary"] = "Pets"
    _move_to(fake)
    return _compute()


def test_settling_one_conflict_leaves_the_plan_conflicted_until_the_last(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    plan_id = detail.plan.id
    first, second = detail.conflicts[0].id, detail.conflicts[1].id

    after_first = spec_sync_store.resolve_conflict(
        TENANT, "pets", plan_id, first, BOB, SyncConflictResolve(resolution="git", note="theirs")
    )
    assert after_first.plan.status == STATUS_CONFLICTED
    assert after_first.plan.unresolved_count == 1

    after_second = spec_sync_store.resolve_conflict(
        TENANT, "pets", plan_id, second, BOB, SyncConflictResolve(resolution="draft")
    )
    assert after_second.plan.status == STATUS_RESOLVED
    assert after_second.plan.unresolved_count == 0
    # What the merge found never moves, however much of it is settled.
    assert after_second.plan.conflict_count == 2
    assert _actions(fake).count("sync.conflict_resolved") == 2


def test_a_settlement_records_who_decided_and_why(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    settled = spec_sync_store.resolve_conflict(
        TENANT,
        "pets",
        detail.plan.id,
        detail.conflicts[0].id,
        BOB,
        SyncConflictResolve(resolution="git", note="the repository is right here"),
    )
    row = next(c for c in settled.conflicts if c.id == detail.conflicts[0].id)
    assert row.resolution == "git"
    assert row.resolved_by_name == "Bob"
    assert row.resolution_note == "the repository is right here"


def test_settling_changes_nothing_about_the_draft(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    before = copy.deepcopy(draft.document)
    spec_sync_store.resolve_conflict(
        TENANT, "pets", detail.plan.id, detail.conflicts[0].id, BOB,
        SyncConflictResolve(resolution="git"),
    )
    assert draft.document == before


def test_a_settlement_is_final(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    conflict_id = detail.conflicts[0].id
    spec_sync_store.resolve_conflict(
        TENANT, "pets", detail.plan.id, conflict_id, BOB, SyncConflictResolve(resolution="git")
    )
    assert (
        _code_of(
            lambda: spec_sync_store.resolve_conflict(
                TENANT, "pets", detail.plan.id, conflict_id, ALICE,
                SyncConflictResolve(resolution="draft"),
            )
        )
        == CODE_CONFLICT_RESOLVED
    )


def test_losing_the_race_to_settle_says_so(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    conflict_id = detail.conflicts[0].id
    fake.interleave = lambda: fake.sync_conflicts[conflict_id].update(
        resolution="draft", resolved_at=fake._tick(), resolved_by=ALICE
    )
    assert (
        _code_of(
            lambda: spec_sync_store.resolve_conflict(
                TENANT, "pets", detail.plan.id, conflict_id, BOB,
                SyncConflictResolve(resolution="git"),
            )
        )
        == CODE_CONFLICT
    )


def test_an_unknown_plan_or_conflict_is_not_found(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    missing = "8d2e3f40-2222-4bbb-9ccc-0000000000aa"
    assert (
        _code_of(
            lambda: spec_sync_store.resolve_conflict(
                TENANT, "pets", missing, detail.conflicts[0].id, BOB,
                SyncConflictResolve(resolution="git"),
            )
        )
        == CODE_PLAN_NOT_FOUND
    )
    assert (
        _code_of(
            lambda: spec_sync_store.resolve_conflict(
                TENANT, "pets", detail.plan.id, missing, BOB,
                SyncConflictResolve(resolution="git"),
            )
        )
        == CODE_CONFLICT_NOT_FOUND
    )
    assert _code_of(lambda: spec_sync_store.get_plan(TENANT, "pets", missing)) == CODE_PLAN_NOT_FOUND


# ---------------------------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------------------------


def test_a_version_with_no_merge_yet_reports_only_that_it_is_bound(fake, provider, draft):
    status = spec_sync_store.version_sync_status(TENANT, "pets", "1.0.0")
    assert (status.bound, status.latest, status.history) == (True, None, [])
    assert status.version_label == "1.0.0"


def test_the_newest_merge_comes_back_with_its_conflicts_and_the_rest_behind_it(
    fake, provider, draft
):
    _move_to(fake)
    first = _compute()
    draft.document["info"]["contact"] = {"name": "Platform"}
    provider.at(COMMIT_NEXT)["info"]["version"] = "2.0.0"
    draft.document["info"]["version"] = "1.5.0"
    second = _compute(refresh=True)

    status = spec_sync_store.version_sync_status(TENANT, "pets", "1.0.0")
    assert status.latest is not None
    assert status.latest.plan.id == second.plan.id
    assert len(status.latest.conflicts) == 1
    assert [plan.id for plan in status.history] == [first.plan.id]


def test_outstanding_conflicts_are_listed_before_settled_ones(fake, provider, draft):
    detail = _conflicted(fake, provider, draft)
    # `/info/version` sorts first while both are outstanding.
    assert [c.pointer for c in detail.conflicts] == ["/info/version", "/paths/~1pets/get/summary"]
    settled = spec_sync_store.resolve_conflict(
        TENANT, "pets", detail.plan.id, detail.conflicts[0].id, BOB,
        SyncConflictResolve(resolution="git"),
    )
    assert [c.resolution for c in settled.conflicts] == [None, "git"]
