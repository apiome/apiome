"""Direct push blocked when merge path required (#2583)."""

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


def test_push_merge_path_required_403():
    head = "00000000-0000-0000-0000-000000000099"
    branch = {
        "id": "b1",
        "name": "main",
        "tip_version_id": head,
        "require_merge_path": True,
        "protected": False,
    }
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.get_version_branch_by_name.return_value = branch
        mdb.is_user_tenant_admin.return_value = False
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.1",
                "shortMessage": "ok",
                "baseRevisionId": head,
                "branchName": "main",
            },
        )
        assert r.status_code == 403
        body = r.json()["detail"]
        assert body["code"] == "MERGE_PATH_REQUIRED"
        assert body["reason"] == "merge_path_required"
        mdb.create_version_push_transaction.assert_not_called()


def test_push_merge_path_allowed_for_tenant_admin():
    head = "00000000-0000-0000-0000-000000000099"
    branch = {
        "id": "b1",
        "name": "main",
        "tip_version_id": head,
        "require_merge_path": True,
        "protected": False,
    }
    row = {
        "id": "rev-new",
        "project_id": "proj-1",
        "version_id": "1.0.1",
        "description": "ok",
        "change_log": None,
        "visibility": "private",
        "published": False,
        "published_at": None,
        "enabled": True,
        "parent_version_id": head,
        "merge_parent_version_id": None,
        "metadata": None,
    }
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.get_version_branch_by_name.return_value = branch
        mdb.is_user_tenant_admin.return_value = True
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.1",
                "shortMessage": "ok",
                "baseRevisionId": head,
                "branchName": "main",
            },
        )
        assert r.status_code == 200
        mdb.create_version_push_transaction.assert_called_once()


def test_push_project_metadata_pattern_merge():
    head = "00000000-0000-0000-0000-000000000099"
    branch = {
        "id": "b1",
        "name": "main",
        "tip_version_id": head,
        "require_merge_path": False,
        "protected": False,
    }
    meta = {"branchPushPolicy": {"patterns": [{"pattern": "main", "requireMergePath": True}]}}
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": meta}
        mdb.get_latest_version_for_project.return_value = None
        mdb.get_version_branch_by_name.return_value = branch
        mdb.is_user_tenant_admin.return_value = False
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.1",
                "shortMessage": "ok",
                "baseRevisionId": head,
                "branchName": "main",
            },
        )
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "MERGE_PATH_REQUIRED"
