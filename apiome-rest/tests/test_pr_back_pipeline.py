"""PR-back pipeline — REPO-5.8 (#2793).

:func:`app.pr_back_pipeline.prepare` and :func:`app.pr_back_pipeline.run_pr_back` against the
in-memory GitHub of ``tests/fake_github_git.py``: what is refused before GitHub is called, which
files are written (one slice per multi-repository source file), the change report in the pull
request description, idempotency (one pull request per project and base branch), reviewers, the
dry run, failures as outcomes, and the ``repository.pr_back_opened`` / ``…_updated`` audit rows.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest
import yaml

from app import pr_back_pipeline
from app.change_report_render import bundled_system_template_row
from app.pr_back import PrBackSettings, SourceFile, serialize_spec
from app.pr_back_pipeline import (
    AUDIT_PR_BACK_OPENED,
    AUDIT_PR_BACK_UPDATED,
    PrBackRefusalError,
    check_eligibility,
    prepare,
    run_pr_back,
)
from tests.fake_github_git import DEFAULT_TOKEN, FakeGitHub

PROJECT = {"id": "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0002", "slug": "shop", "name": "Shop"}
REPO_ID = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0040"
OTHER_REPO_ID = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0041"
REPOSITORY = {
    "id": REPO_ID,
    "provider": "github",
    "repository_full_name": "acme/shop",
    "linked_account_id": "la-1",
    "created_by": "u-1",
}
ALLOWED = PrBackSettings(project_policy="allow", project_ids=(PROJECT["id"],))

SPEC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Shop", "version": "1.1.0"},
    "paths": {
        "/users": {"get": {"summary": "List users", "responses": {"200": {"description": "ok"}}}},
        "/invoices": {"get": {"summary": "List invoices", "responses": {"200": {"description": "ok"}}}},
    },
    "components": {
        "schemas": {
            "User": {"type": "object", "properties": {"id": {"type": "string"}}},
            "Invoice": {"type": "object", "properties": {"owner": {"$ref": "#/components/schemas/User"}}},
        }
    },
}

USERS = SourceFile("s-users", REPO_ID, "main", "services/users/openapi.yaml", 1)
BILLING = SourceFile("s-billing", REPO_ID, "main", "services/billing/openapi.json", 2)
ENTITIES = {
    ("path", "/users"): "s-users",
    ("class", "User"): "s-users",
    ("path", "/invoices"): "s-billing",
    ("class", "Invoice"): "s-billing",
}


@pytest.fixture(autouse=True)
def _token():
    """Resolve the repository's linked-account token to the fake's."""
    with patch.object(pr_back_pipeline, "resolve_linked_account_token", return_value=DEFAULT_TOKEN):
        yield


def _github(files: Dict[str, str] | None = None) -> FakeGitHub:
    github = FakeGitHub(full_name="acme/shop")
    github.seed(files or {"README.md": "# shop\n"})
    return github


def _plan(sources=(USERS,), entities=None, settings=ALLOWED, spec=SPEC):
    return prepare(
        spec=spec,
        project=PROJECT,
        repository=REPOSITORY,
        settings=settings,
        sources=list(sources),
        entity_sources=entities or {},
    )


def _run(github: FakeGitHub, plan, *, settings=ALLOWED, dry_run=False, version="1.1.0"):
    audits: List[Tuple[str, Dict[str, Any]]] = []
    outcome = run_pr_back(
        plan,
        project=PROJECT,
        version_label=version,
        repository=REPOSITORY,
        settings=settings,
        template_row=bundled_system_template_row(),
        dry_run=dry_run,
        apiome_version="1.261.0",
        audit=lambda action, detail: audits.append((action, detail)),
        client_factory=github.client_factory,
    )
    return outcome, audits


# ---------------------------------------------------------------------------
# Refusals before GitHub
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "settings, code, status",
    [
        (None, "pr-back-not-configured", 403),
        (PrBackSettings(), "pr-back-project-not-allowed", 403),
        (PrBackSettings(project_policy="deny", project_ids=(PROJECT["id"],)), "pr-back-project-not-allowed", 403),
    ],
)
def test_policy_refusals(settings, code, status):
    with pytest.raises(PrBackRefusalError) as caught:
        _plan(settings=settings)
    assert (caught.value.code, caught.value.http_status) == (code, status)


def test_deny_policy_lets_unlisted_projects():
    plan = _plan(settings=PrBackSettings(project_policy="deny", project_ids=("someone-else",)))
    assert plan.base_branch == "main"


def test_repository_problems_are_refused_in_pr_back_words():
    with pytest.raises(PrBackRefusalError) as caught:
        check_eligibility(
            project=PROJECT,
            repository={**REPOSITORY, "linked_account_id": None},
            settings=ALLOWED,
            sources=[USERS],
        )
    assert caught.value.code == "pr-back-repository-unlinked"
    assert "PR-back" in caught.value.message and caught.value.http_status == 409


def test_project_without_a_file_in_the_repository_is_refused():
    with pytest.raises(PrBackRefusalError) as caught:
        _plan(sources=[SourceFile("s-x", OTHER_REPO_ID, "main", "openapi.yaml", 1)])
    assert caught.value.code == "pr-back-no-source"


def test_files_on_several_branches_need_a_target_branch():
    develop = SourceFile("s-billing", REPO_ID, "develop", "billing.yaml", 2)
    with pytest.raises(PrBackRefusalError) as caught:
        _plan(sources=[USERS, develop])
    assert caught.value.code == "pr-back-branch-ambiguous"
    plan = _plan(
        sources=[USERS, develop],
        settings=PrBackSettings(project_ids=(PROJECT["id"],), target_branch="release"),
    )
    assert plan.base_branch == "release"
    assert plan.branch_name == "apiome/pr-back-shop-release"


def test_non_json_yaml_files_are_skipped_and_all_skipped_is_refused():
    graphql = SourceFile("s-users", REPO_ID, "main", "schema.graphql", 1)
    with pytest.raises(PrBackRefusalError) as caught:
        _plan(sources=[graphql])
    assert caught.value.code == "pr-back-no-renderable-file"
    plan = _plan(sources=[graphql, BILLING], entities=ENTITIES)
    assert [f.path for f in plan.files] == [BILLING.path]
    assert "schema.graphql" in plan.skipped[0]


def test_same_path_from_two_branches_is_written_once():
    twin = SourceFile("s-billing", REPO_ID, "develop", USERS.path, 2)
    plan = _plan(sources=[USERS, twin], settings=PrBackSettings(project_ids=(PROJECT["id"],), target_branch="main"))
    assert [f.path for f in plan.files] == [USERS.path]
    assert "would overwrite" in plan.skipped[0]


def test_multi_source_files_get_their_own_slice():
    plan = _plan(sources=[USERS, BILLING], entities=ENTITIES)
    users, billing = plan.files
    assert (users.format, billing.format) == ("yaml", "json")
    assert list(yaml.safe_load(users.text)["paths"]) == ["/users"]
    assert list(json.loads(billing.text)["components"]["schemas"]) == ["Invoice"]
    assert billing.foreign_refs == ("User",)
    assert (users.paths, users.schemas) == (1, 1)


def test_sources_in_another_repository_keep_their_entities_out():
    elsewhere = SourceFile("s-billing", OTHER_REPO_ID, "main", "openapi.yaml", 2)
    plan = _plan(sources=[USERS, elsewhere], entities=ENTITIES)
    assert [f.path for f in plan.files] == [USERS.path]
    assert list(plan.files[0].document["paths"]) == ["/users"]


# ---------------------------------------------------------------------------
# Running against GitHub
# ---------------------------------------------------------------------------


def test_opens_a_pull_request_with_rendered_files_and_change_report():
    old_spec = "openapi: 3.1.0\ninfo: {title: Shop, version: 1.0.0}\npaths: {}\n"
    github = _github({"README.md": "# shop\n", USERS.path: old_spec})
    settings = PrBackSettings(
        project_ids=(PROJECT["id"],),
        reviewers=("octocat", "acme/api-reviewers"),
        commit_message_template="api: {{project}} {{version}} ({{fileCount}} file)",
    )
    plan = _plan(sources=[USERS, BILLING], entities=ENTITIES, settings=settings)
    outcome, audits = _run(github, plan, settings=settings)

    assert outcome.status == "opened", outcome.error_message
    assert outcome.branch_name == "apiome/pr-back-shop-main"
    files = github.files_at(outcome.branch_name)
    assert yaml.safe_load(files[USERS.path])["paths"].keys() == {"/users"}
    assert json.loads(files[BILLING.path])["paths"].keys() == {"/invoices"}
    assert files["README.md"] == "# shop\n"
    assert [(f.path, f.status) for f in outcome.files] == [(USERS.path, "modified"), (BILLING.path, "added")]

    pull = github.pulls[0]
    assert pull.base == "main" and pull.head == outcome.branch_name
    assert pull.title == "Apiome: sync Shop 1.1.0"
    assert f"### `{USERS.path}` — modified" in pull.body
    assert f"### `{BILLING.path}` — added" in pull.body
    assert "left as references: `User`" in pull.body
    assert outcome.files[0].counts and sum(outcome.files[0].counts.values()) > 0
    assert pull.reviewers == ["octocat"] and pull.team_reviewers == ["api-reviewers"]
    assert outcome.reviewers == ["octocat", "acme/api-reviewers"]
    assert github.commits[outcome.commit_sha]["message"] == "api: Shop 1.1.0 (2 file)"

    assert [action for action, _ in audits] == [AUDIT_PR_BACK_OPENED]
    detail = audits[0][1]
    assert detail["pullRequestNumber"] == pull.number
    assert detail["files"] == [USERS.path, BILLING.path]
    assert detail["repositoryFullName"] == "acme/shop"
    assert DEFAULT_TOKEN not in json.dumps(detail) and DEFAULT_TOKEN not in json.dumps(outcome.log)


def test_rerun_without_changes_is_unchanged_and_a_new_version_refreshes_the_same_pull():
    github = _github()
    first, _ = _run(github, _plan())
    assert first.status == "opened"

    again, audits = _run(github, _plan())
    assert again.status == "unchanged" and audits == []
    assert len(github.pulls) == 1

    newer = {**SPEC, "info": {"title": "Shop", "version": "1.2.0"}}
    refreshed, audits = _run(github, _plan(spec=newer), version="1.2.0")
    assert refreshed.status == "updated"
    assert len(github.pulls) == 1 and github.pulls[0].title == "Apiome: sync Shop 1.2.0"
    assert [action for action, _ in audits] == [AUDIT_PR_BACK_UPDATED]
    assert github.pulls[0].reviewers == []  # reviewers only on a newly opened pull request


def test_base_already_holding_the_rendered_files_is_up_to_date():
    plan = _plan()
    github = _github({USERS.path: plan.files[0].text})
    outcome, audits = _run(github, plan)
    assert outcome.status == "up_to_date"
    assert [f.status for f in outcome.files] == ["unchanged"]
    assert github.pulls == [] and audits == []
    assert not any(method in ("POST", "PATCH") for method, _, _ in github.requests)


def test_dry_run_describes_and_writes_nothing():
    github = _github()
    outcome, audits = _run(github, _plan(), dry_run=True)
    assert outcome.status == "preview" and outcome.dry_run
    assert outcome.title == "Apiome: sync Shop 1.1.0"
    assert outcome.body and USERS.path in outcome.body
    assert outcome.commit_message == "Sync Shop 1.1.0 from Apiome"
    assert github.pulls == [] and audits == []
    assert not any(method in ("POST", "PATCH") for method, _, _ in github.requests)


def test_swagger_and_unreadable_base_files_are_noted():
    github = _github({USERS.path: "swagger: '2.0'\ninfo: {title: Shop, version: '1'}\npaths: {}\n"})
    outcome, _ = _run(github, _plan(), dry_run=True)
    assert any("Swagger 2.0" in note for note in outcome.files[0].notes)

    github = _github({USERS.path: "key: [unclosed\n"})
    outcome, _ = _run(github, _plan(), dry_run=True)
    assert any("could not be read" in note for note in outcome.files[0].notes)


def test_missing_credential_is_a_failed_outcome():
    github = _github()
    with patch.object(pr_back_pipeline, "resolve_linked_account_token", return_value=None):
        outcome, audits = _run(github, _plan())
    assert outcome.status == "failed" and outcome.error_code == "pr-back-credential-missing"
    assert audits == [] and github.requests == []


def test_provider_refusals_are_failed_outcomes_with_pr_back_codes():
    github = _github()
    github.fault("POST", r"/git/trees$", 401, "Bad credentials")
    outcome, audits = _run(github, _plan())
    assert outcome.status == "failed"
    assert outcome.error_code == "pr-back-credential-rejected"
    assert outcome.log[-1]["level"] == "error" and audits == []


def test_read_only_account_and_missing_base_branch_fail():
    github = _github()
    github.can_push = False
    outcome, _ = _run(github, _plan())
    assert outcome.error_code == "pr-back-permission-denied"
    preview, _ = _run(github, _plan(), dry_run=True)
    assert preview.status == "preview"  # a dry run only warns

    plan = _plan(settings=PrBackSettings(project_ids=(PROJECT["id"],), target_branch="nope"))
    outcome, _ = _run(_github(), plan)
    assert outcome.error_code == "pr-back-base-branch-missing"


def test_archived_repository_fails():
    github = _github()
    github.archived = True
    outcome, _ = _run(github, _plan())
    assert outcome.error_code == "pr-back-repository-archived"


def test_reviewer_refusal_only_warns():
    github = _github()
    github.fault("POST", r"/requested_reviewers$", 422, "Reviews may only be requested from collaborators.")
    settings = PrBackSettings(project_ids=(PROJECT["id"],), reviewers=("stranger",))
    outcome, audits = _run(github, _plan(settings=settings), settings=settings)
    assert outcome.status == "opened"
    assert outcome.reviewers == []
    assert any(entry["step"] == "reviewers" and entry["level"] == "warn" for entry in outcome.log)
    assert [action for action, _ in audits] == [AUDIT_PR_BACK_OPENED]


def test_file_under_a_path_that_is_a_file_fails_cleanly():
    github = _github({"services": "not a directory\n"})
    outcome, _ = _run(github, _plan())
    assert outcome.status == "failed"
    assert outcome.error_code == "pr-back-target-path-invalid"


def test_unexpected_fault_is_an_internal_failure():
    github = _github()
    with patch.object(pr_back_pipeline, "_change_report", side_effect=RuntimeError("boom")):
        outcome, _ = _run(github, _plan())
    assert outcome.error_code == "pr-back-internal-error"


def test_large_files_are_uploaded_as_blobs():
    big = {**SPEC, "info": {"title": "Shop", "version": "1.1.0", "description": "x" * 120_000}}
    github = _github()
    outcome, _ = _run(github, _plan(spec=big))
    assert outcome.status == "opened"
    assert any(path.endswith("/git/blobs") for method, path, _ in github.requests if method == "POST")
    assert github.files_at(outcome.branch_name)[USERS.path] == serialize_spec(big, "yaml")
