"""What a delivery produced, per channel — MFX-46.3 (#4381).

Each delivery attempt of an export job now carries ``result``: what it left at its destination, for the
Review step's Deliver section — the git pull request (or commit), the webhook receiver's HTTP status and
the digest of what was sent, the object-storage objects and manifest. Pinned here: each channel's
result, that nothing secret reaches it (URLs lose their user-info and query), that the attempt listing
and the "deliver now" answer both carry it, and that the listing's UNION keeps its columns aligned.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.export_delivery_profile_routes import attempt_model
from app.export_delivery_results import MAX_RESULT_OBJECTS, delivery_result, public_url
from app.export_git_delivery_routes import ExportGitDeliveryRunModel
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROFILE = "33333333-3333-4333-8333-333333333333"
_JOB = "job-1"
_ROUTES = "app.export_delivery_profile_routes"


# ===========================================================================
# Each channel's result
# ===========================================================================


def test_a_git_delivery_shows_its_pull_request() -> None:
    result = delivery_result("git", {
        "result_mode": "pr", "result_pull_request_url": "https://github.com/acme/specs/pull/7",
        "result_pull_request_number": 7, "result_branch": "apiome/export-orders-openapi-3.1",
        "result_commit_sha": "abc123",
    })
    assert result is not None
    assert result.model_dump(by_alias=True, exclude_none=True, exclude_defaults=True) == {
        "mode": "pr", "pullRequestUrl": "https://github.com/acme/specs/pull/7", "pullRequestNumber": 7,
        "branch": "apiome/export-orders-openapi-3.1", "commitSha": "abc123",
    }


def test_a_direct_commit_shows_its_commit() -> None:
    result = delivery_result("git", {"result_mode": "commit", "result_branch": "main", "result_commit_sha": "def4"})
    assert result is not None and result.pull_request_url is None
    assert (result.mode, result.branch, result.commit_sha) == ("commit", "main", "def4")


def test_a_webhook_delivery_shows_its_receipt() -> None:
    result = delivery_result("webhook", {"result_http_status": 202, "result_payload_sha256": "f" * 64})
    assert result is not None and (result.http_status, result.payload_sha256) == (202, "f" * 64)


def test_an_object_storage_delivery_lists_its_objects_and_manifest() -> None:
    result = delivery_result("object_storage", {
        "result_endpoint_url": "https://minio.example.com:9000/",
        "result_bucket": "specs",
        "result_objects": [{"key": "orders/v1/openapi.json", "sizeBytes": 10}, {"key": "orders/v1/a b.yaml"}],
        "result_manifest_key": "orders/manifests/abc.json",
    })
    assert result is not None
    assert result.object_urls == [
        "https://minio.example.com:9000/specs/orders/v1/openapi.json",
        "https://minio.example.com:9000/specs/orders/v1/a%20b.yaml",
    ]
    assert result.object_count == 2
    assert result.manifest_url == "https://minio.example.com:9000/specs/orders/manifests/abc.json"


def test_an_aws_object_is_an_s3_url_and_a_long_list_is_capped_but_counted() -> None:
    objects = [{"key": f"k/{i}.json"} for i in range(MAX_RESULT_OBJECTS + 5)]
    result = delivery_result("object_storage", {"result_bucket": "specs", "result_objects": objects})
    assert result is not None
    assert result.object_urls[0] == "s3://specs/k/0.json"
    assert len(result.object_urls) == MAX_RESULT_OBJECTS and result.object_count == MAX_RESULT_OBJECTS + 5


def test_a_delivery_with_nothing_to_show_yet_has_no_result() -> None:
    assert delivery_result("git", {"result_mode": None}) is None
    assert delivery_result("webhook", {}) is None
    assert delivery_result("object_storage", {"result_bucket": "specs", "result_objects": []}) is None
    assert delivery_result("ftp", {"result_mode": "pr"}) is None


def test_no_credential_or_token_reaches_a_result() -> None:
    assert public_url("https://user:secret@minio.example.com:9000/x?X-Amz-Signature=abc#f") == (
        "https://minio.example.com:9000/x")
    assert public_url(None) is None and public_url("") is None
    result = delivery_result("object_storage", {
        "result_endpoint_url": "https://key:secret@s3.example.com", "result_bucket": "b",
        "result_objects": [{"key": "a.json"}],
    })
    assert result is not None and "secret" not in result.model_dump_json()
    pr = delivery_result("git", {"result_pull_request_url": "https://github.com/a/b/pull/1?token=x"})
    assert pr is not None and pr.pull_request_url == "https://github.com/a/b/pull/1"


# ===========================================================================
# The attempts carry it
# ===========================================================================


def _attempt_row(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        channel="git", id="r1", job_id=_JOB, artifact_id="a1", export_target="openapi-3.1", status="opened",
        delivery_profile_id=_PROFILE, profile_name="specs-repo", destination="acme/specs", attempt_count=1,
        error_code=None, error_message=None, started_at=None, finished_at=None, created_by="u1",
        result_mode="pr", result_pull_request_url="https://github.com/acme/specs/pull/7",
        result_pull_request_number=7, result_branch="apiome/export", result_commit_sha="abc",
        result_http_status=None, result_payload_sha256=None, result_endpoint_url=None, result_bucket=None,
        result_objects=None, result_manifest_key=None,
    )
    values.update(fields)
    return values


def test_an_attempt_carries_its_result_in_camel_case() -> None:
    dumped = attempt_model(_attempt_row()).model_dump(mode="json", by_alias=True)
    assert dumped["result"]["pullRequestUrl"] == "https://github.com/acme/specs/pull/7"
    assert dumped["result"]["pullRequestNumber"] == 7
    in_progress = attempt_model(_attempt_row(status="in_progress", result_mode=None, result_pull_request_url=None,
                                             result_pull_request_number=None, result_branch=None,
                                             result_commit_sha=None))
    assert in_progress.result is None


def test_the_job_deliveries_listing_returns_each_result() -> None:
    rows = [
        _attempt_row(),
        _attempt_row(channel="webhook", status="delivered", destination="https://ci.example.com/h?token=abc",
                     result_mode=None, result_pull_request_url=None, result_pull_request_number=None,
                     result_branch=None, result_commit_sha=None, result_http_status=200,
                     result_payload_sha256="e" * 64),
    ]
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": _TENANT, "user_id": "u1"}
    try:
        with patch(f"{_ROUTES}.enforce_permission"), \
                patch(f"{_ROUTES}.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
                patch(f"{_ROUTES}.db.list_export_delivery_attempts", return_value=rows):
            response = client.get(f"/v1/export/acme/jobs/{_JOB}/deliveries")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    git, webhook = response.json()["deliveries"]
    assert git["result"]["pullRequestUrl"].endswith("/pull/7")
    assert webhook["result"] == {"mode": None, "pullRequestUrl": None, "pullRequestNumber": None, "branch": None,
                                 "commitSha": None, "httpStatus": 200, "payloadSha256": "e" * 64,
                                 "objectUrls": [], "objectCount": None, "manifestUrl": None}
    assert "token=abc" not in response.text


def test_delivering_now_answers_with_the_result() -> None:
    run = ExportGitDeliveryRunModel(run_id="r1", status="opened", mode="pr", job_id=_JOB,
                                    repository_full_name="acme/specs", pull_request_number=9,
                                    pull_request_url="https://github.com/acme/specs/pull/9", branch_name="b",
                                    commit_sha="c1")
    stored = {"id": _PROFILE, "name": "specs-repo", "channel": "git",
              "destination": {"repositoryId": "44444444-4444-4444-8444-444444444444", "targetPath": "specs",
                              "mode": "pr"}}
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": _TENANT, "user_id": "u1"}
    try:
        with patch(f"{_ROUTES}.enforce_permission"), \
                patch(f"{_ROUTES}.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
                patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=stored), \
                patch(f"{_ROUTES}.perform_git_delivery", new=AsyncMock(return_value=run)):
            response = client.post(f"/v1/export/acme/jobs/{_JOB}/deliveries", json={"profileId": _PROFILE})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.json()["result"]["pullRequestUrl"] == "https://github.com/acme/specs/pull/9"


# ===========================================================================
# The listing's UNION stays aligned
# ===========================================================================


class _Recording(Database):
    def __init__(self) -> None:  # noqa: D107 - no connection
        self.queries: List[str] = []

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:  # type: ignore[override]
        self.queries.append(" ".join(query.split()))
        return []


def test_every_branch_of_the_attempts_union_selects_the_same_result_columns() -> None:
    database = _Recording()
    database.list_export_delivery_attempts(_TENANT, job_id=_JOB)
    sql = database.queries[0]
    branches = [b[b.index("SELECT '"):b.index(" FROM apiome.")] for b in sql.split("UNION ALL")]
    assert len(branches) == 3
    git_selects = branches[0]
    for alias in ("result_mode", "result_pull_request_url", "result_pull_request_number", "result_branch",
                  "result_commit_sha", "result_http_status", "result_payload_sha256", "result_endpoint_url",
                  "result_bucket", "result_objects", "result_manifest_key"):
        assert f"AS {alias}" in git_selects
    # Each branch lists as many columns as the first.
    counts = [branch.count(",") for branch in branches]
    assert counts[0] == counts[1] == counts[2], counts
    assert "r.last_http_status, r.payload_sha256" in branches[1]
    assert "r.endpoint_url, r.bucket, r.objects, r.manifest_key" in branches[2]
