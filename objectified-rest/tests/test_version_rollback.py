"""
Rollback preview / apply API (#745) — auth and validation smoke tests.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "t1",
    "user_id": "u1",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


def test_rollback_preview_requires_auth():
    r = client.post(
        "/v1/versions/slug/p1/version-branches/rollback-preview",
        json={"branchName": "main", "targetRevisionId": "00000000-0000-0000-0000-000000000001"},
    )
    assert r.status_code == 401


def test_rollback_apply_requires_auth():
    r = client.post(
        "/v1/versions/slug/p1/version-branches/rollback",
        json={
            "branchName": "main",
            "targetRevisionId": "00000000-0000-0000-0000-000000000001",
            "baseRevisionId": "00000000-0000-0000-0000-000000000002",
        },
    )
    assert r.status_code == 401


@pytest.fixture
def auth_client():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield client
    app.dependency_overrides.clear()


def test_rollback_preview_project_not_found(auth_client):
    with patch("app.version_merge_routes.db.get_project_by_id", return_value=None):
        r = auth_client.post(
            "/v1/versions/slug/missing-project/version-branches/rollback-preview",
            json={"branchName": "main", "targetRevisionId": "00000000-0000-0000-0000-000000000001"},
        )
    assert r.status_code == 404


def test_rollback_preview_branch_not_found(auth_client):
    proj = {"id": "p1", "metadata": {}}
    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=None
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback-preview",
            json={"branchName": "main", "targetRevisionId": "00000000-0000-0000-0000-000000000001"},
        )
    assert r.status_code == 404
    assert "Branch not found" in r.json()["detail"]


def test_rollback_tip_equals_target_bad_request(auth_client):
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": False}
    head_ver = {"id": tip, "project_id": "p1", "version_id": "1.0.0", "metadata": None, "published": False}
    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", return_value=head_ver):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback-preview",
            json={"branchName": "main", "targetRevisionId": tip},
        )
    assert r.status_code == 400


def test_rollback_apply_protected_branch_forbidden(auth_client):
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    old = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": True}
    head_ver = {
        "id": tip,
        "project_id": "p1",
        "version_id": "1.0.1",
        "metadata": None,
        "published": False,
    }
    target_ver = {
        "id": old,
        "project_id": "p1",
        "version_id": "1.0.0",
        "metadata": None,
        "published": False,
    }

    def gv(vid, _tid):
        if vid == tip:
            return head_ver
        if vid == old:
            return target_ver
        return None

    ancestors = {tip, old}

    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", side_effect=gv), patch(
        "app.version_merge_routes.db.collect_revision_ancestors", return_value=ancestors
    ), patch(
        "app.version_merge_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.version_merge_routes._rollback_analyze",
        return_value=(
            "safe",
            [],
            [],
            "fp",
            None,
            {
                "added": 0,
                "removed": 0,
                "modified": 0,
                "unchanged": 0,
                "changedEntityCount": 0,
            },
        ),
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback",
            json={
                "branchName": "main",
                "targetRevisionId": old,
                "baseRevisionId": tip,
            },
        )
    assert r.status_code == 403


def test_rollback_preview_impact_summary_keys(auth_client):
    """rollback-preview success path returns impactSummary with expected keys."""
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    old = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": False}
    head_ver = {
        "id": tip,
        "project_id": "p1",
        "version_id": "1.0.1",
        "metadata": None,
        "published": False,
    }
    target_ver = {
        "id": old,
        "project_id": "p1",
        "version_id": "1.0.0",
        "metadata": None,
        "published": False,
    }

    def gv(vid, _tid):
        if vid == tip:
            return head_ver
        if vid == old:
            return target_ver
        return None

    ancestors = {tip, old}
    impact = {
        "added": 1,
        "removed": 2,
        "modified": 3,
        "unchanged": 10,
        "changedEntityCount": 6,
    }

    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", side_effect=gv), patch(
        "app.version_merge_routes.db.collect_revision_ancestors", return_value=ancestors
    ), patch(
        "app.version_merge_routes._rollback_analyze",
        return_value=("safe", [], [], "fp", None, impact),
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback-preview",
            json={"branchName": "main", "targetRevisionId": old},
        )
    assert r.status_code == 200
    body = r.json()
    assert "impactSummary" in body
    summary = body["impactSummary"]
    for key in ("added", "removed", "modified", "unchanged", "changedEntityCount"):
        assert key in summary, f"impactSummary missing key: {key}"
    assert summary["added"] == 1
    assert summary["removed"] == 2
    assert summary["modified"] == 3
    assert summary["unchanged"] == 10
    assert summary["changedEntityCount"] == 6


def _create_immutable_published_version(tip):
    return {
        "id": tip,
        "project_id": "p1",
        "version_id": "1.0.1",
        "metadata": None,
        "published": True,
        "published_immutable": True,
    }


def _create_unpublished_version(old):
    return {
        "id": old,
        "project_id": "p1",
        "version_id": "1.0.0",
        "metadata": None,
        "published": False,
        "published_immutable": False,
    }


def test_rollback_preview_blocks_immutable_tip(auth_client):
    """rollback-preview returns 409 PUBLISHED_IMMUTABLE when branch tip is published+immutable."""
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    old = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": False}
    head_ver = _create_immutable_published_version(tip)
    target_ver = _create_unpublished_version(old)
    ancestors = {tip, old}

    def gv(vid, _tid):
        if vid == tip:
            return head_ver
        if vid == old:
            return target_ver
        return None

    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", side_effect=gv), patch(
        "app.version_merge_routes.db.collect_revision_ancestors", return_value=ancestors
    ), patch(
        "app.version_merge_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.version_merge_routes.db.insert_workflow_audit", side_effect=lambda *a, **k: None
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback-preview",
            json={"branchName": "main", "targetRevisionId": old},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"


def test_rollback_apply_blocks_immutable_tip(auth_client):
    """rollback apply returns 409 PUBLISHED_IMMUTABLE when branch tip is published+immutable."""
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    old = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": False}
    head_ver = _create_immutable_published_version(tip)
    target_ver = _create_unpublished_version(old)
    ancestors = {tip, old}

    def gv(vid, _tid):
        if vid == tip:
            return head_ver
        if vid == old:
            return target_ver
        return None

    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", side_effect=gv), patch(
        "app.version_merge_routes.db.collect_revision_ancestors", return_value=ancestors
    ), patch(
        "app.version_merge_routes.db.is_user_tenant_admin", return_value=False
    ), patch(
        "app.version_merge_routes.db.insert_workflow_audit", side_effect=lambda *a, **k: None
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback",
            json={"branchName": "main", "targetRevisionId": old, "baseRevisionId": tip},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PUBLISHED_IMMUTABLE"


def test_rollback_preview_override_does_not_write_audit(auth_client):
    """rollback-preview is a dry-run; admin override must NOT write a workflow_audit row."""
    tip = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    old = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    proj = {"id": "p1", "metadata": {}}
    branch = {"id": "b1", "tip_version_id": tip, "protected": False}
    head_ver = _create_immutable_published_version(tip)
    target_ver = _create_unpublished_version(old)
    ancestors = {tip, old}
    impact = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0, "changedEntityCount": 0}

    def gv(vid, _tid):
        if vid == tip:
            return head_ver
        if vid == old:
            return target_ver
        return None

    audit_calls = []

    with patch("app.version_merge_routes.db.get_project_by_id", return_value=proj), patch(
        "app.version_merge_routes.db.get_version_branch_by_name", return_value=branch
    ), patch("app.version_merge_routes.db.get_version_by_id", side_effect=gv), patch(
        "app.version_merge_routes.db.collect_revision_ancestors", return_value=ancestors
    ), patch(
        "app.version_merge_routes.db.is_user_tenant_admin", return_value=True
    ), patch(
        "app.version_merge_routes.db.insert_workflow_audit",
        side_effect=lambda *a, **k: audit_calls.append((a, k)),
    ), patch(
        "app.version_merge_routes._rollback_analyze",
        return_value=("safe", [], [], "fp", None, impact),
    ):
        r = auth_client.post(
            "/v1/versions/slug/p1/version-branches/rollback-preview",
            json={
                "branchName": "main",
                "targetRevisionId": old,
                "overridePublishedImmutability": True,
                "overrideReason": "dry-run-glass",
            },
        )
    assert r.status_code == 200
    override_calls = [
        c for c in audit_calls if len(c[0]) > 3 and c[0][3] == "version.immutability_override"
    ]
    assert override_calls == [], "rollback-preview must not write immutability_override audit rows"
