"""Workflow audit ledger writes (#2577)."""

from unittest.mock import MagicMock, patch, call

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


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_version_emits_pull_audit():
    row = {
        "id": "rev-1",
        "project_id": "proj-1",
        "creator_id": "test-user-id",
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
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
    }
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        mdb.insert_workflow_audit = MagicMock()
        r = client.get("/v1/versions/tn/proj-1/rev-1")
    assert r.status_code == 200
    mdb.insert_workflow_audit.assert_called_once()
    kw = mdb.insert_workflow_audit.call_args
    assert kw[0][3] == "version.pull"
    assert kw[0][4] == "success"
    assert kw[0][2] == "rev-1"


def test_create_version_push_success_audits():
    version_row = {
        "id": "new-rev",
        "project_id": "proj-1",
        "creator_id": "test-user-id",
        "version_id": "0.1.0",
        "description": "m",
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
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
    }
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (version_row, 0)
        mdb.insert_workflow_audit = MagicMock()
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "0.1.0",
                "short_message": "hello",
                "base_revision_id": "",
            },
        )
    assert r.status_code == 200
    mdb.insert_workflow_audit.assert_called_once()
    args = mdb.insert_workflow_audit.call_args[0]
    assert args[3] == "version.push"
    assert args[4] == "success"
    assert args[2] == "new-rev"


def test_merge_project_not_found_emits_failure_audit():
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = None
        mdb.insert_workflow_audit = MagicMock()
        r = client.post(
            "/v1/versions/tn/proj-1/version-branches/merge",
            json={
                "sourceBranchName": "feature",
                "targetBranchName": "main",
                "baseRevisionId": "rev-base",
            },
        )
    assert r.status_code == 404
    mdb.insert_workflow_audit.assert_called_once()
    args = mdb.insert_workflow_audit.call_args[0]
    assert args[3] == "version.merge"
    assert args[4] == "failure"
    assert args[6]["reason"] == "project_not_found"


def test_rollback_project_not_found_emits_failure_audit():
    head_tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    tgt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "proj-1", "metadata": {}}
    branch = {"id": "br-1", "tip_version_id": head_tip, "protected": False}
    head_ver = {"id": head_tip, "project_id": "proj-1", "version_id": "1.0.0",
                "metadata": None, "published": False}
    tgt_ver = {"id": tgt_id, "project_id": "proj-1", "version_id": "0.9.0",
               "metadata": None, "published": False}
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = proj
        mdb.get_version_branch_by_name.return_value = branch
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            head_ver if vid == head_tip else tgt_ver if vid == tgt_id else None
        )
        mdb.collect_revision_ancestors.return_value = [tgt_id]
        mdb.insert_workflow_audit = MagicMock()
        # base_revision_id deliberately wrong → STALE_HEAD → audit failure
        r = client.post(
            "/v1/versions/tn/proj-1/version-branches/rollback",
            json={
                "branchName": "main",
                "targetRevisionId": tgt_id,
                "baseRevisionId": "wrong-base",
            },
        )
    assert r.status_code == 409
    mdb.insert_workflow_audit.assert_called_once()
    args = mdb.insert_workflow_audit.call_args[0]
    assert args[3] == "version.rollback"
    assert args[4] == "failure"
    assert args[6]["detail"]["code"] == "STALE_HEAD"
    assert args[6]["fromRevision"] == head_tip
    assert args[6]["toRevision"] == tgt_id
    assert args[6]["branchName"] == "main"


def test_rollback_stale_head_audit_includes_optional_reason():
    head_tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    tgt_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "proj-1", "metadata": {}}
    branch = {"id": "br-1", "tip_version_id": head_tip, "protected": False}
    head_ver = {"id": head_tip, "project_id": "proj-1", "version_id": "1.0.0",
                "metadata": None, "published": False}
    tgt_ver = {"id": tgt_id, "project_id": "proj-1", "version_id": "0.9.0",
               "metadata": None, "published": False}
    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = proj
        mdb.get_version_branch_by_name.return_value = branch
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            head_ver if vid == head_tip else tgt_ver if vid == tgt_id else None
        )
        mdb.collect_revision_ancestors.return_value = [tgt_id]
        mdb.insert_workflow_audit = MagicMock()
        r = client.post(
            "/v1/versions/tn/proj-1/version-branches/rollback",
            json={
                "branchName": "main",
                "targetRevisionId": tgt_id,
                "baseRevisionId": "wrong-base",
                "reason": "incident-42 mitigation",
            },
        )
    assert r.status_code == 409
    mdb.insert_workflow_audit.assert_called_once()
    args = mdb.insert_workflow_audit.call_args[0]
    assert args[3] == "version.rollback"
    assert args[4] == "failure"
    assert args[6]["detail"]["code"] == "STALE_HEAD"
    assert args[6]["reason"] == "incident-42 mitigation"
