"""Optimistic locking on POST create version (push) — #2566."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _version_row(rid: str = "rev-new"):
    return {
        "id": rid,
        "project_id": "proj-1",
        "creator_id": "test-user-id",
        "version_id": "1.0.0",
        "description": "ok",
        "change_log": None,
        "visibility": "private",
        "published": False,
        "published_at": None,
        "enabled": True,
        "parent_version_id": None,
        "merge_parent_version_id": None,
        "forked_from_revision_id": None,
        "upstream_project_id": None,
        "revision_locked": False,
        "metadata": None,
        "commit_author": None,
        "commit_message": None,
        "external_ref": None,
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
        "created_at": None,
        "updated_at": None,
    }


def test_post_create_missing_base_revision_id_validation_error():
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={"version_id": "1.0.0", "shortMessage": "ok"},
        )
    assert r.status_code == 422


def test_post_create_invalid_base_when_empty_project():
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "ok",
                "baseRevisionId": "deadbeef-dead-beef-dead-beefdeadbeef",
            },
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_BASE"


def test_post_create_stale_base_409():
    head = "00000000-0000-0000-0000-000000000099"
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = head
        mdb.get_version_by_id.return_value = _version_row(head)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "ok",
                "baseRevisionId": "00000000-0000-0000-0000-000000000001",
            },
        )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "STALE_HEAD"
    assert body["currentHeadRevisionId"] == head


def test_post_create_branch_name_required_multi_branch():
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = [
            {"id": "b1", "tip_version_id": "t1", "name": "main"},
            {"id": "b2", "tip_version_id": "t2", "name": "dev"},
        ]
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "ok",
                "baseRevisionId": "t1",
            },
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "BRANCH_NAME_REQUIRED"


def test_post_create_success_first_revision_bootstrap():
    row = _version_row()
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "first",
                "baseRevisionId": "",
            },
        )
        assert r.status_code == 200
        mdb.create_version_push_transaction.assert_called_once()
        kw = mdb.create_version_push_transaction.call_args.kwargs
        assert kw["client_base_revision_id"] == ""
        assert kw["parent_version_id"] is None
