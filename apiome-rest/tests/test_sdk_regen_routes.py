"""Auto-regen on publish endpoints — SDK-4.3 (#4497).

Authentication is overridden and every collaborator below the route is patched, so these tests
assert the HTTP contract only: which permissions each route enforces (subscribing needs
``versions:publish`` as well as ``projects:edit``; disabling does not), how refusals map to statuses,
that the history links a publish to its package and pull request, that only a dead letter of an
active subscription can be retried, and that every mutation is audited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.sdk_regen_subscriptions import RegenSubscriptionError, RegenSubscriptionOut

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
_JOB = "66666666-6666-4666-8666-666666666666"
_PUBLISH_RUN = "77777777-7777-4777-8777-777777777777"
_DELIVERY_RUN = "88888888-8888-4888-8888-888888888888"

_SUBSCRIPTIONS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-regen-subscriptions"
_RUNS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-regen-runs"
_RETRY = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-regen-jobs/{_JOB}/retry"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _project_lookup():
    """Answer the shared project resolver for ``_PROJECT``."""
    return patch("app.sdk_regen_routes.db.get_project_by_id", return_value=dict(_PROJECT_ROW))


def _subscription(**fields: Any) -> RegenSubscriptionOut:
    values: Dict[str, Any] = {
        "ecosystem": "npm",
        "delivery_mode": "registry_and_git",
        "options": {"dryRun": False},
        "active": True,
    }
    values.update(fields)
    return RegenSubscriptionOut(**values)


def _job(**fields: Any) -> Dict[str, Any]:
    """A job row as the store returns it."""
    row: Dict[str, Any] = {
        "id": _JOB,
        "tenant_id": _MOCK_AUTH["tenant_id"],
        "project_id": _PROJECT,
        "run_id": _RUN,
        "subscription_id": "sub-1",
        "subscription_active": True,
        "ecosystem": "npm",
        "delivery_mode": "registry_and_git",
        "options": {"dryRun": False},
        "status": "succeeded",
        "attempt_count": 1,
        "next_attempt_at": None,
        "publish_run_id": _PUBLISH_RUN,
        "publish_status": "published",
        "delivery_run_id": _DELIVERY_RUN,
        "delivery_status": "opened",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.0",
        "regen_counter": 0,
        "artifact_sha256": "f" * 64,
        "pull_request_number": 12,
        "pull_request_url": "https://github.com/acme/widgets-sdk/pull/12",
        "error_step": None,
        "error_code": None,
        "error_message": None,
        "attempts": [{"attempt": 1, "outcome": "succeeded"}],
        "created_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
    }
    row.update(fields)
    return row


def _run(**fields: Any) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": _RUN,
        "project_id": _PROJECT,
        "version_id": _REVISION,
        "version_line": "1.4.2",
        "published_by": _MOCK_AUTH["user_id"],
        "created_at": datetime(2026, 9, 10, tzinfo=timezone.utc),
    }
    row.update(fields)
    return row


def _guards(guard) -> list:
    return [call.args[2:] for call in guard.call_args_list]


# ============================================================================
# Subscriptions
# ============================================================================
def test_listing_subscriptions_requires_projects_view():
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.list_subscriptions", return_value=[_subscription()]
    ) as listing:
        response = client.get(_SUBSCRIPTIONS)
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_MOCK_AUTH["tenant_id"], _PROJECT)
    body = response.json()
    assert body["ecosystems"] == ["npm", "pypi"]
    assert body["deliveryModes"] == ["registry", "git", "registry_and_git"]
    assert body["subscriptions"][0]["deliveryMode"] == "registry_and_git"
    assert body["subscriptions"][0]["options"] == {"dryRun": False}


def test_subscribing_requires_projects_edit_and_versions_publish_and_is_audited():
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.save_subscription", return_value=_subscription(options={"dryRun": True})
    ) as save, patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.put(
            f"{_SUBSCRIPTIONS}/npm",
            json={"deliveryMode": "registry_and_git", "options": {"dryRun": True}},
        )
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.PROJECTS, Action.EDIT), (Resource.VERSIONS, Action.PUBLISH)]
    assert save.call_args.kwargs == {
        "ecosystem": "npm",
        "delivery_mode": "registry_and_git",
        "options": {"dryRun": True},
        "active": True,
        "actor_id": _MOCK_AUTH["user_id"],
    }
    audit.assert_called_once()
    assert audit.call_args.kwargs["action"] == "sdk.regen_subscription.update"
    assert audit.call_args.kwargs["detail"] == {
        "ecosystem": "npm",
        "deliveryMode": "registry_and_git",
        "options": {"dryRun": True},
        "active": True,
    }
    assert response.json()["options"] == {"dryRun": True}


def test_a_caller_who_cannot_publish_cannot_subscribe_a_project_to_automatic_releases():
    def guard(_db, _auth_data, resource, action):
        if resource == Resource.VERSIONS:
            raise HTTPException(status_code=403, detail="forbidden")

    with patch("app.sdk_regen_routes.enforce_permission", side_effect=guard), _project_lookup(), patch(
        "app.sdk_regen_routes.save_subscription"
    ) as save:
        response = client.put(f"{_SUBSCRIPTIONS}/npm", json={"deliveryMode": "git"})
    assert response.status_code == 403
    save.assert_not_called()


def test_a_subscription_has_no_default_delivery_mode():
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.save_subscription"
    ) as save:
        response = client.put(f"{_SUBSCRIPTIONS}/npm", json={})
    assert response.status_code == 422
    save.assert_not_called()


def test_an_invalid_subscription_is_a_422_listing_every_problem():
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.save_subscription",
        side_effect=RegenSubscriptionError("bad ecosystem", "unknown option 'dry_run'"),
    ), patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.put(
            f"{_SUBSCRIPTIONS}/gomod", json={"deliveryMode": "registry", "options": {"dry_run": True}}
        )
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "sdk-regen-subscription-invalid",
        "errors": ["bad ecosystem", "unknown option 'dry_run'"],
    }
    audit.assert_not_called()


def test_disabling_needs_only_projects_edit_and_enabling_also_needs_versions_publish():
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.set_subscription_active", return_value=_subscription(active=False)
    ) as toggle, patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.patch(f"{_SUBSCRIPTIONS}/NPM", json={"active": False})
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.PROJECTS, Action.EDIT)]
    assert toggle.call_args.args[2] == "npm"
    assert audit.call_args.kwargs["action"] == "sdk.regen_subscription.disable"
    assert response.json()["active"] is False

    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.set_subscription_active", return_value=_subscription()
    ), patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.patch(f"{_SUBSCRIPTIONS}/npm", json={"active": True})
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.PROJECTS, Action.EDIT), (Resource.VERSIONS, Action.PUBLISH)]
    assert audit.call_args.kwargs["action"] == "sdk.regen_subscription.enable"


def test_toggling_a_missing_subscription_is_404_and_an_unknown_ecosystem_422():
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.set_subscription_active", return_value=None
    ):
        response = client.patch(f"{_SUBSCRIPTIONS}/pypi", json={"active": False})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-regen-subscription-not-found"

    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup():
        response = client.patch(f"{_SUBSCRIPTIONS}/gomod", json={"active": False})
    assert response.status_code == 422


def test_unsubscribing_needs_projects_edit_and_audits_only_a_real_delete():
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.delete_subscription", return_value=True
    ), patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.delete(f"{_SUBSCRIPTIONS}/npm")
    assert response.status_code == 200 and response.json() == {"deleted": True}
    assert _guards(guard) == [(Resource.PROJECTS, Action.EDIT)]
    assert audit.call_args.kwargs["action"] == "sdk.regen_subscription.delete"

    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.delete_subscription", return_value=False
    ), patch("app.sdk_regen_routes.db.write_access_audit") as audit:
        response = client.delete(f"{_SUBSCRIPTIONS}/npm")
    assert response.json() == {"deleted": False}
    audit.assert_not_called()


def test_an_unknown_project_is_404():
    with patch("app.sdk_regen_routes.enforce_permission"), patch(
        "app.sdk_regen_routes.db.get_project_by_id", return_value=None
    ), patch("app.sdk_regen_routes.db.get_project_by_slug", return_value=None):
        response = client.get(_SUBSCRIPTIONS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project-not-found"


# ============================================================================
# History
# ============================================================================
def test_the_history_links_each_publish_to_its_jobs_packages_and_pull_requests():
    retrying = _job(
        id="job-2",
        ecosystem="pypi",
        status="retrying",
        publish_run_id=None,
        publish_status=None,
        delivery_run_id=None,
        delivery_status=None,
        error_step="git",
        error_code="sdk-git-delivery-rate-limited",
        error_message="Rate limited",
        next_attempt_at=datetime(2026, 9, 10, 1, tzinfo=timezone.utc),
    )
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.db.list_sdk_regen_runs", return_value=[_run()]
    ) as runs, patch(
        "app.sdk_regen_routes.db.count_sdk_regen_runs", return_value=1
    ), patch(
        "app.sdk_regen_routes.db.list_sdk_regen_jobs_for_runs", return_value=[_job(), retrying]
    ) as jobs:
        response = client.get(_RUNS, params={"limit": 10})
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.VERSIONS, Action.VIEW)]
    assert runs.call_args.kwargs == {"job_status": None, "limit": 10, "offset": 0}
    jobs.assert_called_once_with(_MOCK_AUTH["tenant_id"], [_RUN])

    body = response.json()
    assert body["total"] == 1
    [run] = body["runs"]
    assert run["status"] == "in_progress"
    assert run["versionLine"] == "1.4.2"
    assert run["versionHref"] == f"/v1/versions/{_TENANT_SLUG}/{_PROJECT}/{_REVISION}"
    npm, pypi = run["jobs"]
    # publish event → job → artifact → delivery.
    assert npm["publish"] == {
        "runId": _PUBLISH_RUN,
        "status": "published",
        "packageName": "@acme/widgets-sdk",
        "packageVersion": "1.4.0",
        "artifactSha256": "f" * 64,
        "href": f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-publish-runs/{_PUBLISH_RUN}",
    }
    assert npm["delivery"] == {
        "runId": _DELIVERY_RUN,
        "status": "opened",
        "pullRequestNumber": 12,
        "pullRequestUrl": "https://github.com/acme/widgets-sdk/pull/12",
        "href": f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-git-delivery-runs/{_DELIVERY_RUN}",
    }
    assert npm["error"] is None and npm["retryable"] is False and npm["retryHref"] is None
    assert npm["attempts"] == [{"attempt": 1, "outcome": "succeeded"}]
    assert pypi["publish"] is None and pypi["delivery"] is None
    assert pypi["error"] == {"step": "git", "code": "sdk-git-delivery-rate-limited", "message": "Rate limited"}
    assert pypi["nextAttemptAt"].startswith("2026-09-10T01:00")
    assert pypi["maxAttempts"] == 4


def test_the_dead_letter_is_the_history_filtered_by_status_and_each_job_says_how_to_retry_it():
    dead = _job(status="dead_letter", error_step="registry", error_code="sdk-publish-credential-missing",
                error_message="No credential", publish_run_id=None, publish_status="failed",
                delivery_run_id=None, delivery_status=None)
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.db.list_sdk_regen_runs", return_value=[_run()]
    ) as runs, patch("app.sdk_regen_routes.db.count_sdk_regen_runs", return_value=1) as count, patch(
        "app.sdk_regen_routes.db.list_sdk_regen_jobs_for_runs", return_value=[dead]
    ):
        response = client.get(_RUNS, params={"status": "DEAD_LETTER"})
    assert response.status_code == 200
    assert runs.call_args.kwargs["job_status"] == "dead_letter"
    assert count.call_args.kwargs == {"job_status": "dead_letter"}
    [run] = response.json()["runs"]
    assert run["status"] == "dead_letter"
    [job] = run["jobs"]
    assert job["retryable"] is True
    assert job["retryHref"] == _RETRY
    # A failed registry step with no run still reports its status, without a dangling link.
    assert job["publish"] == {
        "runId": None,
        "status": "failed",
        "packageName": "@acme/widgets-sdk",
        "packageVersion": "1.4.0",
        "artifactSha256": "f" * 64,
        "href": None,
    }


def test_an_unknown_status_filter_is_422():
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup():
        response = client.get(_RUNS, params={"status": "exploded"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "sdk-regen-status-invalid"


def test_reading_one_run_is_scoped_to_the_project():
    unsubscribed = _job(subscription_active=None, subscription_id=None)
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.db.get_sdk_regen_run", return_value=_run()
    ) as get, patch("app.sdk_regen_routes.db.list_sdk_regen_jobs_for_runs", return_value=[unsubscribed]):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 200
    get.assert_called_once_with(_MOCK_AUTH["tenant_id"], _PROJECT, _RUN)
    job = response.json()["jobs"][0]
    # Unsubscribed since: the job keeps its record, and says so.
    assert job["subscriptionId"] is None and job["subscriptionActive"] is None

    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.db.get_sdk_regen_run", return_value=None
    ):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-regen-run-not-found"


# ============================================================================
# Retry
# ============================================================================
def test_retrying_a_dead_letter_requires_versions_publish_requeues_it_and_is_audited():
    dead = _job(status="dead_letter", error_code="sdk-git-delivery-permission-denied")
    requeued = _job(status="pending", attempt_count=0, error_code=None, subscription_active=None)
    with patch("app.sdk_regen_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_regen_routes.db.get_sdk_regen_job", return_value=dead
    ), patch("app.sdk_regen_routes.db.retry_sdk_regen_job", return_value=requeued) as retry, patch(
        "app.sdk_regen_routes.db.write_access_audit"
    ) as audit:
        response = client.post(_RETRY)
    assert response.status_code == 200
    assert _guards(guard) == [(Resource.VERSIONS, Action.PUBLISH)]
    retry.assert_called_once_with(
        _MOCK_AUTH["tenant_id"], _PROJECT, _JOB, actor_id=_MOCK_AUTH["user_id"]
    )
    assert audit.call_args.kwargs["action"] == "sdk.regen_job.retry"
    assert audit.call_args.kwargs["detail"]["previousErrorCode"] == "sdk-git-delivery-permission-denied"
    body = response.json()
    assert body["status"] == "pending" and body["attemptCount"] == 0
    assert body["subscriptionActive"] is True


@pytest.mark.parametrize(
    ("job", "status", "code"),
    [
        (None, 404, "sdk-regen-job-not-found"),
        (_job(project_id="another-project", status="dead_letter"), 404, "sdk-regen-job-not-found"),
        (_job(status="succeeded"), 409, "sdk-regen-job-not-dead-lettered"),
        (_job(status="dead_letter", subscription_active=False), 409, "sdk-regen-subscription-disabled"),
        (_job(status="dead_letter", subscription_active=None, subscription_id=None), 409, "sdk-regen-unsubscribed"),
    ],
)
def test_only_a_dead_letter_of_an_active_subscription_in_this_project_can_be_retried(job, status, code):
    """Unsubscribing stops future runs — a retry included."""
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.db.get_sdk_regen_job", return_value=job
    ), patch("app.sdk_regen_routes.db.retry_sdk_regen_job") as retry, patch(
        "app.sdk_regen_routes.db.write_access_audit"
    ) as audit:
        response = client.post(_RETRY)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    retry.assert_not_called()
    audit.assert_not_called()


def test_a_retry_that_loses_the_race_is_a_409_not_a_second_queueing():
    with patch("app.sdk_regen_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_regen_routes.db.get_sdk_regen_job", return_value=_job(status="dead_letter")
    ), patch("app.sdk_regen_routes.db.retry_sdk_regen_job", return_value=None), patch(
        "app.sdk_regen_routes.db.write_access_audit"
    ) as audit:
        response = client.post(_RETRY)
    assert response.status_code == 409
    audit.assert_not_called()


def test_every_route_is_in_the_openapi_document():
    paths = app.openapi()["paths"]
    base = "/v1/projects/{tenant_slug}/{project_ref}"
    assert set(paths[f"{base}/sdk-regen-subscriptions/{{ecosystem}}"]) == {"put", "patch", "delete"}
    assert "get" in paths[f"{base}/sdk-regen-subscriptions"]
    assert "get" in paths[f"{base}/sdk-regen-runs"]
    assert "get" in paths[f"{base}/sdk-regen-runs/{{run_id}}"]
    assert "post" in paths[f"{base}/sdk-regen-jobs/{{job_id}}/retry"]
