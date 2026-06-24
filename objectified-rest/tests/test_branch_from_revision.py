"""Branch-from-revision API (#2570)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import validate_authentication

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "t1",
    "user_id": "u1",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


def test_from_revision_requires_auth():
    app.dependency_overrides.clear()
    try:
        r = client.post(
            "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
            json={
                "sourceRevisionId": "00000000-0000-0000-0000-000000000001",
                "branchName": "feature/x",
            },
        )
        assert r.status_code == 401
    finally:
        app.dependency_overrides[validate_authentication] = _override_auth


def test_from_revision_invalid_branch_name():
    with patch(
        "app.version_merge_routes.db.create_version_branch_from_revision"
    ) as m:
        m.side_effect = AssertionError("should not call DB when name invalid")
        r = client.post(
            "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
            json={"sourceRevisionId": "00000000-0000-0000-0000-000000000001", "branchName": "1bad"},
        )
    assert r.status_code == 400
    assert "branchName" in r.json()["detail"]


def test_from_revision_project_not_found():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value=None):
        r = client.post(
            "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
            json={"sourceRevisionId": "00000000-0000-0000-0000-000000000001", "branchName": "feature/x"},
        )
    assert r.status_code == 404


def test_from_revision_success():
    branch_row = {
        "id": "b1",
        "project_id": "p1",
        "name": "feature/x",
        "tip_version_id": "v1",
        "branched_from_revision_id": "v1",
        "protected": False,
        "created_by": "u1",
        "created_at": None,
        "updated_at": None,
    }
    tip = {
        "id": "v1",
        "project_id": "p1",
        "creator_id": None,
        "version_id": "1.0.0",
        "description": None,
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
        "created_at": None,
        "updated_at": None,
    }
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": "p1"}):
        with patch(
            "app.version_merge_routes.db.create_version_branch_from_revision",
            return_value={
                "success": True,
                "branch": branch_row,
                "tip_version": tip,
                "idempotent_replay": False,
            },
        ):
            r = client.post(
                "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
                json={"sourceRevisionId": "v1", "branchName": "feature/x"},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["name"] == "feature/x"
    assert data["branch"]["tipRevisionId"] == "v1"
    assert data["branch"]["branchedFromRevisionId"] == "v1"
    assert data["tipVersion"]["id"] == "v1"
    assert data["idempotentReplay"] is False


def test_from_revision_conflict():
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": "p1"}):
        with patch(
            "app.version_merge_routes.db.create_version_branch_from_revision",
            return_value={
                "success": False,
                "error": "A branch named 'main' already exists in this project with a different tip or lineage.",
                "code": "BRANCH_NAME_CONFLICT",
            },
        ):
            r = client.post(
                "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
                json={"sourceRevisionId": "v1", "branchName": "main"},
            )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["code"] == "BRANCH_NAME_CONFLICT"


def test_from_revision_idempotent_replay():
    branch_row = {
        "id": "b1",
        "project_id": "p1",
        "name": "feature/x",
        "tip_version_id": "v1",
        "branched_from_revision_id": "v1",
        "protected": False,
        "created_by": "u1",
        "created_at": None,
        "updated_at": None,
    }
    tip = {
        "id": "v1",
        "project_id": "p1",
        "creator_id": None,
        "version_id": "1.0.0",
        "description": None,
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
        "created_at": None,
        "updated_at": None,
    }
    with patch("app.version_merge_routes.db.get_project_by_id", return_value={"id": "p1"}):
        with patch(
            "app.version_merge_routes.db.create_version_branch_from_revision",
            return_value={
                "success": True,
                "branch": branch_row,
                "tip_version": tip,
                "idempotent_replay": True,
            },
        ):
            r = client.post(
                "/v1/versions/acme/00000000-0000-0000-0000-0000000000a1/version-branches/from-revision",
                json={"sourceRevisionId": "v1", "branchName": "feature/x"},
            )
    assert r.status_code == 200
    data = r.json()
    assert data["branch"]["name"] == "feature/x"
    assert data["branch"]["tipRevisionId"] == "v1"
    assert data["branch"]["branchedFromRevisionId"] == "v1"
    assert data["idempotentReplay"] is True
