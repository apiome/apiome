"""Published immutability (#2586): helper and API guards."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.published_immutability import revision_is_published_immutable

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "user_id": "00000000-0000-0000-0000-0000000000a1",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture
def auth_client():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield client
    app.dependency_overrides.clear()


def test_revision_is_published_immutable_defaults_when_flag_missing():
    assert revision_is_published_immutable({"published": True}) is True
    assert revision_is_published_immutable({"published": True, "published_immutable": False}) is False
    assert revision_is_published_immutable({"published": False, "published_immutable": True}) is False


def test_push_blocks_immutable_published_base(auth_client):
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    head_ver = {
        "id": tip,
        "project_id": "p1",
        "version_id": "1.0.0",
        "published": True,
        "published_immutable": True,
    }
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "p1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = "1.0.0"
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = tip
        mdb.get_version_by_id.return_value = head_ver
        mdb.is_user_tenant_admin.return_value = False
        mdb.insert_workflow_audit.side_effect = lambda *a, **k: None
        r = auth_client.post(
            "/v1/versions/slug/p1",
            json={
                "baseRevisionId": tip,
                "shortMessage": "next",
            },
        )
        assert r.status_code == 409
        body = r.json()["detail"]
        assert body["code"] == "PUBLISHED_IMMUTABLE"
        mdb.create_version_push_transaction.assert_not_called()


def test_push_allows_immutable_override_tenant_admin(auth_client):
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    head_ver = {
        "id": tip,
        "project_id": "p1",
        "version_id": "1.0.0",
        "published": True,
        "published_immutable": True,
    }
    new_row = {
        "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "project_id": "p1",
        "creator_id": "u1",
        "version_id": "1.0.1",
        "description": "next",
        "change_log": None,
        "visibility": "private",
        "published": False,
        "published_at": None,
        "published_immutable": False,
        "enabled": True,
        "parent_version_id": tip,
        "merge_parent_version_id": None,
        "metadata": None,
        "commit_author": None,
        "commit_message": None,
        "external_ref": None,
        "created_at": None,
        "updated_at": None,
    }
    audit_calls = []

    def _audit(*a, **k):
        audit_calls.append((a, k))

    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "p1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = "1.0.0"
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = tip
        mdb.get_version_by_id.return_value = head_ver
        mdb.is_user_tenant_admin.return_value = True
        mdb.create_version_push_transaction.return_value = (new_row, 0)
        mdb.insert_workflow_audit.side_effect = _audit
        r = auth_client.post(
            "/v1/versions/slug/p1",
            json={
                "baseRevisionId": tip,
                "shortMessage": "next",
                "overridePublishedImmutability": True,
                "overrideReason": "break-glass",
            },
        )
        assert r.status_code == 200
    assert any(
        len(c[0]) > 3 and c[0][3] == "version.immutability_override" for c in audit_calls
    )


def test_merge_blocks_immutable_tips(auth_client):
    proj = {"id": "p1", "metadata": {}}
    src = {"id": "b-src", "tip_version_id": "s1", "name": "feature"}
    tgt = {"id": "b-tgt", "tip_version_id": "t1", "name": "main"}
    s_ver = {
        "id": "s1",
        "project_id": "p1",
        "published": True,
        "published_immutable": True,
    }
    t_ver = {
        "id": "t1",
        "project_id": "p1",
        "published": False,
        "published_immutable": False,
    }

    def branch_by_name(_pid, _tid, name):
        if name == "feature":
            return src
        if name == "main":
            return tgt
        return None

    def gv(vid, _tid):
        if vid == "s1":
            return s_ver
        if vid == "t1":
            return t_ver
        return None

    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = proj
        mdb.get_version_branch_by_name.side_effect = branch_by_name
        mdb.get_version_by_id.side_effect = gv
        mdb.is_user_tenant_admin.return_value = False
        mdb.insert_workflow_audit.side_effect = lambda *a, **k: None
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/merge",
            json={
                "sourceBranchName": "feature",
                "targetBranchName": "main",
                "baseRevisionId": "t1",
            },
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"


def test_merge_preview_blocks_immutable_tips(auth_client):
    """merge-preview returns 409 PUBLISHED_IMMUTABLE when a tip is published+immutable."""
    proj = {"id": "p1", "metadata": {}}
    src = {"id": "b-src", "tip_version_id": "s1", "name": "feature"}
    tgt = {"id": "b-tgt", "tip_version_id": "t1", "name": "main"}
    s_ver = {
        "id": "s1",
        "project_id": "p1",
        "published": True,
        "published_immutable": True,
    }
    t_ver = {
        "id": "t1",
        "project_id": "p1",
        "published": False,
        "published_immutable": False,
    }
    base_ver = {"id": "b0", "project_id": "p1", "published": False, "published_immutable": False}

    def branch_by_name(_pid, _tid, name):
        if name == "feature":
            return src
        if name == "main":
            return tgt
        return None

    def gv(vid, _tid):
        return {"s1": s_ver, "t1": t_ver, "b0": base_ver}.get(vid)

    with patch("app.version_merge_routes.db") as mdb:
        mdb.get_project_by_id.return_value = proj
        mdb.get_version_branch_by_name.side_effect = branch_by_name
        mdb.get_version_by_id.side_effect = gv
        mdb.compute_merge_base_revision_id.return_value = "b0"
        mdb.is_user_tenant_admin.return_value = False
        mdb.insert_workflow_audit.side_effect = lambda *a, **k: None
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/merge-preview",
            json={"sourceBranchName": "feature", "targetBranchName": "main"},
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"


def test_merge_preview_override_does_not_write_audit(auth_client):
    """merge-preview is a dry-run; override by admin should NOT write a workflow_audit row."""
    proj = {"id": "p1", "metadata": {}}
    src = {"id": "b-src", "tip_version_id": "s1", "name": "feature"}
    tgt = {"id": "b-tgt", "tip_version_id": "t1", "name": "main"}
    s_ver = {
        "id": "s1",
        "project_id": "p1",
        "published": True,
        "published_immutable": True,
    }
    t_ver = {
        "id": "t1",
        "project_id": "p1",
        "published": False,
        "published_immutable": False,
    }
    base_ver = {"id": "vb", "project_id": "p1", "published": False, "published_immutable": False}

    import json as _json

    SPEC = {
        "openapi": "3.0.0",
        "info": {"title": "t", "version": "1"},
        "components": {"schemas": {}},
    }

    def branch_by_name(_pid, _tid, name):
        if name == "feature":
            return src
        if name == "main":
            return tgt
        return None

    def gv(vid, _tid):
        return {
            "s1": s_ver,
            "t1": t_ver,
            "vb": base_ver,
        }.get(vid)

    audit_calls = []

    with patch("app.version_merge_routes.db") as mdb, patch(
        "app.version_merge_routes._openapi_for_revision", return_value=SPEC
    ):
        mdb.get_project_by_id.return_value = proj
        mdb.get_version_branch_by_name.side_effect = branch_by_name
        mdb.get_version_by_id.side_effect = gv
        mdb.compute_merge_base_revision_id.return_value = "vb"
        mdb.is_user_tenant_admin.return_value = True
        mdb.insert_workflow_audit.side_effect = lambda *a, **k: audit_calls.append((a, k))
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/merge-preview",
            json={
                "sourceBranchName": "feature",
                "targetBranchName": "main",
                "overridePublishedImmutability": True,
                "overrideReason": "dry-run-break-glass",
            },
        )
        assert r.status_code == 200
    # No immutability_override audit row should be written for a dry-run preview
    override_calls = [
        c for c in audit_calls if len(c[0]) > 3 and c[0][3] == "version.immutability_override"
    ]
    assert override_calls == [], "merge-preview must not write immutability_override audit rows"
