"""Tests for GET /v1/tenants/{slug}/repositories/{id}/refresh-history (RAR-5.3, #3534).

Covers the second acceptance criterion — *audit queryable per repo and per file* —
plus the trigger/outcome/branch/time filters, tenant-scoped 404, projection of the
``detail`` JSONB facets to first-class fields, and offset pagination.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_REPO_ID = "880e8400-e29b-41d4-a716-446655440003"
_ROW_ID = "990e8400-e29b-41d4-a716-446655440009"
_PROJECT_ID = "770e8400-e29b-41d4-a716-446655440002"
_VERSION_ID = "660e8400-e29b-41d4-a716-446655440001"

_API_KEY_AUTH = {
    "tenant_id": _TENANT_ID,
    "tenant_slug": "acme",
    "auth_method": "api_key",
}


def _audit_row(**overrides):
    """A refresh-cycle ``apiome.workflow_audit`` row as the DAO returns it."""
    row = {
        "id": _ROW_ID,
        "tenant_id": _TENANT_ID,
        "project_id": _PROJECT_ID,
        "version_id": _VERSION_ID,
        "action": "repository.refresh.cycle",
        "outcome": "success",
        "actor_id": None,
        "detail": {
            "trigger": "scheduled",
            "outcome": "new-version",
            "repositoryId": _REPO_ID,
            "branch": "main",
            "path": "openapi/petstore.yaml",
            "decision": "newer-content",
            "versionId": _VERSION_ID,
            "parentVersionId": "v1",
            "changeReportId": "cr9",
            "sourceCommitSha": "abc123",
        },
        "created_at": "2026-06-22T12:00:00+00:00",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _auth_api_key():
    app.dependency_overrides[validate_authentication] = lambda: _API_KEY_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_per_repo_history_ok():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        mdb.count_repository_refresh_audit.return_value = 1
        mdb.search_repository_refresh_audit.return_value = [_audit_row()]
        r = client.get(f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history")
    assert r.status_code == 200
    body = r.json()
    assert body["pagination"]["total"] == 1
    assert body["pagination"]["hasMore"] is False
    item = body["items"][0]
    # detail facets hoisted to first-class fields (camelCase on the wire).
    assert item["trigger"] == "scheduled"
    assert item["outcome"] == "new-version"
    assert item["decision"] == "newer-content"
    assert item["repositoryId"] == _REPO_ID
    assert item["path"] == "openapi/petstore.yaml"
    assert item["changeReportId"] == "cr9"
    assert item["versionId"] == _VERSION_ID
    assert item["parentVersionId"] == "v1"
    assert item["sourceCommitSha"] == "abc123"
    assert item["createdAt"] == "2026-06-22T12:00:00+00:00"
    # Tenant scope from token; repository scope from the path; no path filter.
    mdb.search_repository_refresh_audit.assert_called_once()
    kwargs = mdb.search_repository_refresh_audit.call_args.kwargs
    assert kwargs["repository_id"] == _REPO_ID
    assert kwargs["path"] is None
    assert mdb.search_repository_refresh_audit.call_args.args[0] == _TENANT_ID


def test_per_file_history_passes_path_filter():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        mdb.count_repository_refresh_audit.return_value = 0
        mdb.search_repository_refresh_audit.return_value = []
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"path": "openapi/petstore.yaml", "branch": "main"},
        )
    assert r.status_code == 200
    kwargs = mdb.search_repository_refresh_audit.call_args.kwargs
    assert kwargs["path"] == "openapi/petstore.yaml"
    assert kwargs["branch"] == "main"


def test_trigger_and_outcome_filters_forwarded():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        mdb.count_repository_refresh_audit.return_value = 0
        mdb.search_repository_refresh_audit.return_value = []
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"trigger": "manual", "outcome": "diverged"},
        )
    assert r.status_code == 200
    kwargs = mdb.search_repository_refresh_audit.call_args.kwargs
    assert kwargs["trigger"] == "manual"
    assert kwargs["outcome"] == "diverged"


def test_invalid_trigger_is_400():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"trigger": "bogus"},
        )
    assert r.status_code == 400
    mdb.search_repository_refresh_audit.assert_not_called()


def test_invalid_outcome_is_400():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"outcome": "success"},  # column value, not a refresh outcome
        )
    assert r.status_code == 400


def test_unknown_repository_is_404():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = None
        r = client.get(f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history")
    assert r.status_code == 404
    mdb.search_repository_refresh_audit.assert_not_called()


def test_pagination_reports_next_offset():
    rows = [_audit_row(id=f"{i:032x}") for i in range(2)]
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        mdb.count_repository_refresh_audit.return_value = 5
        mdb.search_repository_refresh_audit.return_value = rows
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"limit": 2, "offset": 0},
        )
    assert r.status_code == 200
    pag = r.json()["pagination"]
    assert pag["limit"] == 2
    assert pag["total"] == 5
    assert pag["offset"] == 0
    assert pag["hasMore"] is True
    assert pag["nextOffset"] == 2


def test_limit_over_max_is_422():
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.get_tenant_repository.return_value = {"id": _REPO_ID}
        r = client.get(
            f"/v1/tenants/acme/repositories/{_REPO_ID}/refresh-history",
            params={"limit": 9999},
        )
    assert r.status_code == 422
