"""PR-back endpoints — REPO-5.8 (#2793).

Authentication is overridden and the collaborators below each route are patched, so these tests
assert the HTTP contract: the permission each route enforces, how settings are validated and
audited, how a refusal maps to a status, and that a started PR-back answers ``200`` whatever its
outcome.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import pr_back_routes
from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.pr_back import PrBackSettings, SourceFile
from app.pr_back_pipeline import PrBackOutcome

client = TestClient(app)

TENANT = "11111111-1111-4111-8111-111111111111"
USER = "33333333-3333-4333-8333-333333333333"
PROJECT = "22222222-2222-4222-8222-222222222222"
OTHER_PROJECT = "22222222-2222-4222-8222-222222222223"
REPO = "66666666-6666-4666-8666-666666666666"
VERSION = "44444444-4444-4444-8444-444444444444"
AUTH = {"tenant_id": TENANT, "user_id": USER, "auth_method": "jwt"}
PROJECT_ROW = {"id": PROJECT, "slug": "shop", "name": "Shop"}
REPO_ROW = {
    "id": REPO,
    "provider": "github",
    "repository_full_name": "acme/shop",
    "linked_account_id": "la",
    "created_by": USER,
}
SETTINGS_URL = f"/v1/tenants/acme/repositories/{REPO}/pr-back-settings"
SYNC_URL = f"/v1/tenants/acme/projects/{PROJECT}/pr-back"
LIST_URL = f"/v1/tenants/acme/projects/{PROJECT}/pr-back/repositories"
SETTINGS_ROW = {
    "repository_id": REPO,
    "tenant_id": TENANT,
    "project_policy": "allow",
    "project_ids": [PROJECT],
    "target_branch": None,
    "commit_message_template": None,
    "reviewers": ["octocat"],
    "updated_at": "2026-10-19T12:00:00+00:00",
}
SPEC = {"openapi": "3.1.0", "info": {"title": "Shop", "version": "1"}, "paths": {}}
SOURCE = SourceFile("s1", REPO, "main", "openapi.yaml", 1)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: AUTH
    yield
    app.dependency_overrides.clear()


def _patches(stack: ExitStack, **overrides: Any) -> Dict[str, Any]:
    """Patch every collaborator; return the mocks by name."""
    targets = {
        "enforce_permission": None,
        "write_audit": None,
        "resolve_project": dict(PROJECT_ROW),
        "pr_back_store.get_settings_row": dict(SETTINGS_ROW),
        "pr_back_store.get_settings": PrBackSettings.from_row(SETTINGS_ROW),
        "pr_back_store.project_names": {PROJECT: "Shop"},
        "pr_back_store.unknown_project_ids": [],
        "pr_back_store.save_settings": dict(SETTINGS_ROW),
        "pr_back_store.project_sources": [SOURCE],
        "pr_back_store.entity_sources": {},
        "pr_back_store.latest_version_id": VERSION,
        "resolve_version": {"id": VERSION, "version_id": "1.4.0", "project_id": PROJECT},
        "openapi_for_revision": SPEC,
        "db.get_tenant_repository": dict(REPO_ROW),
        "_template_row": {"id": "t"},
    }
    targets.update(overrides)
    mocks = {}
    for name, value in targets.items():
        mocks[name] = stack.enter_context(patch(f"app.pr_back_routes.{name}", return_value=value))
    return mocks


def _guards(mock) -> list:
    return [call.args[2:] for call in mock.call_args_list]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_get_settings_requires_imports_view_and_names_projects():
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.get(SETTINGS_URL)
    assert response.status_code == 200
    assert _guards(mocks["enforce_permission"]) == [(Resource.IMPORTS, Action.VIEW)]
    body = response.json()
    assert body["configured"] is True
    assert body["projectPolicy"] == "allow"
    assert body["projects"] == [{"id": PROJECT, "name": "Shop"}]
    assert body["reviewers"] == ["octocat"]
    assert body["defaultCommitMessageTemplate"] == "Sync {{project}} {{version}} from Apiome"


def test_get_settings_unconfigured_and_unknown_repository():
    with ExitStack() as stack:
        _patches(stack, **{"pr_back_store.get_settings_row": None})
        body = client.get(SETTINGS_URL).json()
    assert body["configured"] is False and body["projects"] == []
    with ExitStack() as stack:
        _patches(stack, **{"db.get_tenant_repository": None})
        response = client.get(SETTINGS_URL)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "pr-back-repository-not-found"
    with ExitStack() as stack:
        mocks = _patches(stack)
        assert client.get("/v1/tenants/acme/repositories/not-a-uuid/pr-back-settings").status_code == 404
        mocks["db.get_tenant_repository"].assert_not_called()


def test_put_settings_requires_imports_edit_saves_and_audits():
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.put(
            SETTINGS_URL,
            json={
                "projectPolicy": "deny",
                "projectIds": [PROJECT],
                "targetBranch": "develop",
                "commitMessageTemplate": "api: {{project}}",
                "reviewers": ["@octocat", "acme/reviewers"],
            },
        )
    assert response.status_code == 200, response.text
    assert _guards(mocks["enforce_permission"]) == [(Resource.IMPORTS, Action.EDIT)]
    saved = mocks["pr_back_store.save_settings"].call_args.args
    assert saved[0:2] == (TENANT, REPO)
    assert saved[2] == PrBackSettings("deny", (PROJECT,), "develop", "api: {{project}}", ("octocat", "acme/reviewers"))
    assert saved[3] == USER
    audit = mocks["write_audit"].call_args.kwargs
    assert audit["action"] == "repository.pr_back_settings.update"
    assert audit["detail"]["projectPolicy"] == "deny" and audit["target"] == REPO


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"projectPolicy": "everyone"}, "pr-back-policy-invalid"),
        ({"targetBranch": "bad..branch"}, "pr-back-branch-invalid"),
        ({"reviewers": ["two words"]}, "pr-back-reviewer-invalid"),
        ({"projectIds": ["not-a-uuid"]}, "pr-back-project-unknown"),
    ],
)
def test_put_settings_validation_errors_are_422(payload, code):
    with ExitStack() as stack:
        mocks = _patches(stack)
        response = client.put(SETTINGS_URL, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    mocks["pr_back_store.save_settings"].assert_not_called()
    mocks["write_audit"].assert_not_called()


def test_put_settings_refuses_projects_of_another_tenant():
    with ExitStack() as stack:
        _patches(stack, **{"pr_back_store.unknown_project_ids": [OTHER_PROJECT]})
        response = client.put(SETTINGS_URL, json={"projectIds": [OTHER_PROJECT]})
    assert response.status_code == 422
    assert response.json()["detail"]["projectIds"] == [OTHER_PROJECT]


def test_put_settings_rejects_unknown_fields():
    with ExitStack() as stack:
        _patches(stack)
        assert client.put(SETTINGS_URL, json={"token": "x"}).status_code == 422


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_listing_reports_eligibility_per_repository():
    other = "66666666-6666-4666-8666-666666666667"
    sources = [SOURCE, SourceFile("s2", other, "main", "billing.json", 2)]

    def repo(tenant_id, repository_id):
        return {**REPO_ROW, "id": repository_id, "repository_full_name": f"acme/{repository_id[-1]}"}

    def settings(tenant_id, repository_id):
        return PrBackSettings.from_row(SETTINGS_ROW) if repository_id == REPO else None

    with ExitStack() as stack:
        mocks = _patches(stack, **{"pr_back_store.project_sources": sources})
        stack.enter_context(patch("app.pr_back_routes.db.get_tenant_repository", side_effect=repo))
        stack.enter_context(patch("app.pr_back_routes.pr_back_store.get_settings", side_effect=settings))
        response = client.get(LIST_URL)
    assert response.status_code == 200
    assert _guards(mocks["enforce_permission"]) == [(Resource.PROJECTS, Action.VIEW)]
    first, second = response.json()["repositories"]
    assert first["eligible"] is True and first["baseBranch"] == "main"
    assert first["files"] == [{"path": "openapi.yaml", "branch": "main", "precedence": 1}]
    assert second["eligible"] is False and second["reasonCode"] == "pr-back-not-configured"


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def _outcome(**fields: Any) -> PrBackOutcome:
    values: Dict[str, Any] = {
        "status": "opened",
        "dry_run": False,
        "repository_id": REPO,
        "repository_full_name": "acme/shop",
        "base_branch": "main",
        "branch_name": "apiome/pr-back-shop-main",
        "pull_request_number": 7,
        "pull_request_url": "https://github.com/acme/shop/pull/7",
    }
    values.update(fields)
    return PrBackOutcome(**values)


def test_sync_requires_versions_publish_and_runs_the_pipeline():
    with ExitStack() as stack:
        mocks = _patches(stack, run_pr_back=_outcome())
        response = client.post(SYNC_URL, json={"repositoryId": REPO})
        mocks["run_pr_back"].call_args.kwargs["audit"]("repository.pr_back_opened", {"pullRequestNumber": 7})
    assert response.status_code == 200, response.text
    assert _guards(mocks["enforce_permission"]) == [(Resource.VERSIONS, Action.PUBLISH)]
    body = response.json()
    assert body["status"] == "opened" and body["pullRequestNumber"] == 7
    assert body["versionId"] == VERSION and body["versionLabel"] == "1.4.0"
    mocks["resolve_version"].assert_called_once_with(TENANT, PROJECT, VERSION)  # newest by default
    kwargs = mocks["run_pr_back"].call_args.kwargs
    assert kwargs["version_label"] == "1.4.0" and kwargs["dry_run"] is False
    audit = mocks["write_audit"].call_args.kwargs
    assert audit["action"] == "repository.pr_back_opened"
    assert audit["detail"] == {"pullRequestNumber": 7, "versionId": VERSION}


def test_dry_run_needs_only_projects_view():
    with ExitStack() as stack:
        mocks = _patches(stack, run_pr_back=_outcome(status="preview", dry_run=True))
        response = client.post(SYNC_URL, json={"repositoryId": REPO, "dryRun": True, "version": "1.4.0"})
    assert response.status_code == 200
    assert _guards(mocks["enforce_permission"]) == [(Resource.PROJECTS, Action.VIEW)]
    mocks["resolve_version"].assert_called_once_with(TENANT, PROJECT, "1.4.0")
    assert response.json()["dryRun"] is True


def test_failed_outcome_is_still_200():
    with ExitStack() as stack:
        _patches(stack, run_pr_back=_outcome(status="failed", error_code="pr-back-credential-missing"))
        response = client.post(SYNC_URL, json={"repositoryId": REPO})
    assert response.status_code == 200
    assert response.json()["errorCode"] == "pr-back-credential-missing"


@pytest.mark.parametrize(
    "overrides, status, code",
    [
        ({"pr_back_store.get_settings": None}, 403, "pr-back-not-configured"),
        ({"pr_back_store.get_settings": PrBackSettings()}, 403, "pr-back-project-not-allowed"),
        ({"pr_back_store.project_sources": []}, 409, "pr-back-no-source"),
        ({"db.get_tenant_repository": None}, 404, "pr-back-repository-not-found"),
        ({"pr_back_store.latest_version_id": None}, 404, "pr-back-version-not-found"),
    ],
)
def test_sync_refusals(overrides, status, code):
    with ExitStack() as stack:
        mocks = _patches(stack, run_pr_back=_outcome(), **overrides)
        response = client.post(SYNC_URL, json={"repositoryId": REPO})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    mocks["run_pr_back"].assert_not_called()
    mocks["openapi_for_revision"].assert_not_called()


def test_template_row_falls_back_to_the_bundled_default():
    with patch.object(pr_back_routes, "resolve_effective_change_report_template", side_effect=RuntimeError("db")):
        row = pr_back_routes._template_row(TENANT, PROJECT)
    assert row["header_template"]
