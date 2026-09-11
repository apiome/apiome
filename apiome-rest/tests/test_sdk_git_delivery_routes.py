"""Git delivery endpoints — SDK-4.2 (#4496).

Authentication is overridden and every collaborator below the route is patched, so these tests
assert the HTTP contract only: which permissions each route enforces (saving a target needs
``imports:edit`` as well as ``projects:edit``), how a refusal maps to a status, that a *failed
delivery* is still a ``200`` carrying the run, and that every mutation is audited.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.sdk_git_delivery_pipeline import RUN_STATUS_FAILED, RUN_STATUS_OPENED, DeliveryOutcome
from app.sdk_git_delivery_targets import DeliveryTarget, GitDeliveryTargetError, GitDeliveryTargetOut

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_PROJECT_ROW = {"id": _PROJECT, "slug": "widgets"}
_REVISION = "44444444-4444-4444-8444-444444444444"
_RUN = "55555555-5555-4555-8555-555555555555"
_REPOSITORY = "66666666-6666-4666-8666-666666666666"

_TARGETS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-git-delivery-targets"
_DELIVER = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-git-delivery"
_RUNS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-git-delivery-runs"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _project_lookup():
    """Answer the shared project resolver for ``_PROJECT``."""
    return patch("app.sdk_git_delivery_routes.db.get_project_by_id", return_value=dict(_PROJECT_ROW))


def _target_out(**fields: Any) -> GitDeliveryTargetOut:
    values: Dict[str, Any] = {
        "ecosystem": "npm",
        "repository_id": _REPOSITORY,
        "repository_full_name": "acme/widgets-sdk",
        "repository_provider": "github",
        "base_branch": None,
        "target_path": "sdks/ts",
        "branch_pattern": "apiome/sdk-regen-{version}-widgets-npm",
    }
    values.update(fields)
    return GitDeliveryTargetOut(**values)


def _outcome(**fields: Any) -> DeliveryOutcome:
    values: Dict[str, Any] = {
        "run_id": _RUN,
        "status": RUN_STATUS_OPENED,
        "ecosystem": "npm",
        "version_line": "1.4.2",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.0",
        "repository_id": _REPOSITORY,
        "repository_full_name": "acme/widgets-sdk",
        "base_branch": "main",
        "target_path": "sdks/ts",
        "branch_name": "apiome/sdk-regen-1.4.2-widgets-npm",
        "commit_sha": "c" * 40,
        "pull_request_number": 12,
        "pull_request_url": "https://github.com/acme/widgets-sdk/pull/12",
        "changes": {"added": 5},
        "provenance": {"versionRecordId": _REVISION},
    }
    values.update(fields)
    return DeliveryOutcome(**values)


class _Source:
    """A stand-in for the loaded export source."""

    api = object()
    version_record_id = _REVISION
    version_label = "1.4.2"
    source_text = "{}"
    source_format = "openapi-3.1"


_TARGET = DeliveryTarget("77777777-7777-4777-8777-777777777777", "npm", _REPOSITORY, None, "sdks/ts")


# ============================================================================
# Targets
# ============================================================================
def test_listing_targets_requires_projects_view():
    with patch("app.sdk_git_delivery_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_git_delivery_routes.list_targets", return_value=[_target_out()]
    ) as listing:
        response = client.get(_TARGETS)
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_MOCK_AUTH["tenant_id"], _PROJECT, project_slug="widgets")
    body = response.json()
    assert body["ecosystems"] == ["npm", "pypi"]
    assert body["targets"][0]["repositoryFullName"] == "acme/widgets-sdk"
    assert body["targets"][0]["branchPattern"] == "apiome/sdk-regen-{version}-widgets-npm"


def test_listing_targets_for_an_unknown_project_is_404():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), patch(
        "app.sdk_git_delivery_routes.db.get_project_by_id", return_value=None
    ), patch("app.sdk_git_delivery_routes.db.get_project_by_slug", return_value=None):
        response = client.get(_TARGETS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project-not-found"


def test_saving_a_target_requires_projects_edit_and_imports_edit_and_is_audited():
    with patch("app.sdk_git_delivery_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_git_delivery_routes.save_target", return_value=_target_out(base_branch="develop")
    ) as save, patch("app.sdk_git_delivery_routes.db.write_access_audit") as audit:
        response = client.put(
            f"{_TARGETS}/npm",
            json={"repositoryId": _REPOSITORY, "baseBranch": "develop", "targetPath": "sdks/ts"},
        )
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [
        (Resource.PROJECTS, Action.EDIT),
        (Resource.IMPORTS, Action.EDIT),
    ]
    assert save.call_args.kwargs["repository_id"] == _REPOSITORY
    assert save.call_args.kwargs["base_branch"] == "develop"
    assert save.call_args.kwargs["actor_id"] == _MOCK_AUTH["user_id"]
    audit.assert_called_once()
    assert audit.call_args.kwargs["action"] == "sdk.git_delivery_target.update"
    assert audit.call_args.kwargs["detail"]["repositoryFullName"] == "acme/widgets-sdk"
    assert response.json()["baseBranch"] == "develop"


def test_a_caller_without_imports_edit_cannot_point_a_project_at_a_repository():
    def guard(_db, _auth_data, resource, action):
        if resource == Resource.IMPORTS:
            raise HTTPException(status_code=403, detail="forbidden")

    with patch("app.sdk_git_delivery_routes.enforce_permission", side_effect=guard), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.save_target"
    ) as save:
        response = client.put(f"{_TARGETS}/npm", json={"repositoryId": _REPOSITORY})
    assert response.status_code == 403
    save.assert_not_called()


def test_an_invalid_target_is_a_422_listing_every_problem():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.save_target",
        side_effect=GitDeliveryTargetError("bad path", "bad branch"),
    ):
        response = client.put(f"{_TARGETS}/npm", json={"repositoryId": "x"})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "sdk-git-delivery-target-invalid",
        "errors": ["bad path", "bad branch"],
    }


def test_an_ineligible_repository_keeps_its_own_code():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.save_target",
        side_effect=GitDeliveryTargetError("no credential", code="sdk-git-delivery-repository-unlinked"),
    ):
        response = client.put(f"{_TARGETS}/npm", json={"repositoryId": _REPOSITORY})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "sdk-git-delivery-repository-unlinked"


def test_a_target_body_naming_an_unknown_field_is_rejected():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup():
        response = client.put(f"{_TARGETS}/npm", json={"repositoryId": _REPOSITORY, "token": "ghp_x"})
    assert response.status_code == 422


def test_clearing_a_target_requires_projects_edit_and_is_audited_only_when_one_existed():
    with patch("app.sdk_git_delivery_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_git_delivery_routes.delete_target", return_value=True
    ), patch("app.sdk_git_delivery_routes.db.write_access_audit") as audit:
        response = client.delete(f"{_TARGETS}/NPM")
    assert response.status_code == 200 and response.json() == {"cleared": True}
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    assert audit.call_args.kwargs["action"] == "sdk.git_delivery_target.clear"
    assert audit.call_args.kwargs["detail"] == {"ecosystem": "npm"}

    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.delete_target", return_value=False
    ), patch("app.sdk_git_delivery_routes.db.write_access_audit") as audit:
        response = client.delete(f"{_TARGETS}/npm")
    assert response.json() == {"cleared": False}
    audit.assert_not_called()


def test_clearing_an_unknown_ecosystem_is_422():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup():
        response = client.delete(f"{_TARGETS}/gomod")
    assert response.status_code == 422


# ============================================================================
# Delivery
# ============================================================================
def _deliverable():
    return (
        patch("app.sdk_git_delivery_routes.resolve_target", return_value=_TARGET),
        patch("app.sdk_publish_routes.load_export_source", return_value=_Source()),
        patch(
            "app.sdk_publish_routes.db.get_version_by_id",
            return_value={"id": _REVISION, "published": True},
        ),
    )


def test_delivering_requires_versions_publish_and_is_audited():
    target, source, revision = _deliverable()
    with patch("app.sdk_git_delivery_routes.enforce_permission") as guard, _project_lookup(), \
        target, source, revision, \
        patch("app.sdk_git_delivery_routes.deliver", return_value=_outcome()) as deliver, \
        patch("app.sdk_git_delivery_routes.db.write_access_audit") as audit:
        response = client.post(_DELIVER, json={"ecosystem": "npm", "version": "1.4.2"})
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    context = deliver.call_args.kwargs["context"]
    assert (context.project_slug, context.version_record_id, context.version_line) == (
        "widgets",
        _REVISION,
        "1.4.2",
    )
    assert deliver.call_args.kwargs["target"] is _TARGET
    body = response.json()
    assert body["status"] == "opened"
    assert body["pullRequestNumber"] == 12
    assert body["branchName"] == "apiome/sdk-regen-1.4.2-widgets-npm"
    detail = audit.call_args.kwargs["detail"]
    assert audit.call_args.kwargs["action"] == "sdk.git_delivery"
    assert detail["pullRequestNumber"] == 12 and detail["versionRecordId"] == _REVISION


def test_a_failed_delivery_is_a_200_carrying_the_failed_run():
    """Credential failures and push rejections surface as failed jobs, not request errors."""
    target, source, revision = _deliverable()
    failed = _outcome(
        status=RUN_STATUS_FAILED,
        pull_request_number=None,
        error_code="sdk-git-delivery-credential-rejected",
        error_message="GitHub rejected the linked account's token… re-link the GitHub account",
        log=[{"step": "failed", "level": "error", "message": "re-link"}],
    )
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), target, source, revision, \
        patch("app.sdk_git_delivery_routes.deliver", return_value=failed), \
        patch("app.sdk_git_delivery_routes.db.write_access_audit") as audit:
        response = client.post(_DELIVER, json={"ecosystem": "npm"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["errorCode"] == "sdk-git-delivery-credential-rejected"
    assert body["log"][0]["level"] == "error"
    assert audit.call_args.kwargs["detail"]["errorCode"] == "sdk-git-delivery-credential-rejected"


def test_delivering_without_a_target_is_404_and_delivers_nothing():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.resolve_target", return_value=None
    ), patch("app.sdk_git_delivery_routes.deliver") as deliver:
        response = client.post(_DELIVER, json={"ecosystem": "pypi"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-git-delivery-target-missing"
    deliver.assert_not_called()


def test_an_unsupported_ecosystem_is_400():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.deliver"
    ) as deliver:
        response = client.post(_DELIVER, json={"ecosystem": "gomod"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sdk-git-delivery-ecosystem-unsupported"
    deliver.assert_not_called()


def test_an_unpublished_revision_cannot_be_delivered():
    target, source, _ = _deliverable()
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), target, source, patch(
        "app.sdk_publish_routes.db.get_version_by_id", return_value={"id": _REVISION, "published": False}
    ), patch("app.sdk_git_delivery_routes.deliver") as deliver:
        response = client.post(_DELIVER, json={"ecosystem": "npm"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sdk-git-delivery-not-published"
    deliver.assert_not_called()


def test_a_forbidden_caller_never_reaches_the_pipeline():
    with patch(
        "app.sdk_git_delivery_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ), patch("app.sdk_git_delivery_routes.deliver") as deliver:
        response = client.post(_DELIVER, json={"ecosystem": "npm"})
    assert response.status_code == 403
    deliver.assert_not_called()


# ============================================================================
# History
# ============================================================================
def _row(**fields: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": _RUN,
        "project_id": _PROJECT,
        "status": "updated",
        "ecosystem": "npm",
        "pull_request_number": 3,
        "log": [{"step": "push"}],
    }
    row.update(fields)
    return row


def test_listing_runs_requires_versions_view_and_pages():
    with patch("app.sdk_git_delivery_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_git_delivery_routes.db.list_sdk_git_delivery_runs", return_value=[_row()]
    ) as listing, patch("app.sdk_git_delivery_routes.db.count_sdk_git_delivery_runs", return_value=9):
        response = client.get(_RUNS, params={"ecosystem": "NPM", "limit": 5, "offset": 5})
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.VERSIONS, Action.VIEW)]
    assert listing.call_args.kwargs == {"ecosystem": "npm", "limit": 5, "offset": 5}
    body = response.json()
    assert (body["total"], body["limit"], body["offset"]) == (9, 5, 5)
    assert body["runs"][0]["pullRequestNumber"] == 3


def test_the_history_page_size_is_bounded():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup():
        response = client.get(_RUNS, params={"limit": 10_000})
    assert response.status_code == 422


def test_reading_a_run_returns_it():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.db.get_sdk_git_delivery_run", return_value=_row()
    ):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 200
    assert response.json()["log"] == [{"step": "push"}]


def test_reading_a_run_belonging_to_another_project_is_404():
    with patch("app.sdk_git_delivery_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_git_delivery_routes.db.get_sdk_git_delivery_run",
        return_value=_row(project_id="99999999-9999-4999-8999-999999999999"),
    ):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-git-delivery-run-not-found"
