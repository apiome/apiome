"""Pre-commit policy: message required, max payload (#2565)."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import VersionCreateRequest
from app.version_notes import (
    DEFAULT_VERSION_NOTES_LIMITS,
    CommitPolicyViolation,
    effective_commit_policy,
    enforce_max_commit_payload,
    validate_version_notes,
)

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


def test_effective_commit_policy_reads_project_metadata():
    md = {"commitPolicy": {"requireShortMessage": False, "maxCommitPayloadBytes": 999999}}
    lim = effective_commit_policy("tid", md)
    assert lim.require_short_message is False
    assert lim.max_commit_payload_bytes == 999999


def test_enforce_max_commit_payload_raises_payload_too_large():
    lim = DEFAULT_VERSION_NOTES_LIMITS
    small = VersionCreateRequest(short_message="x" * 100, version_id="1.0.0", base_revision_id="")
    enforce_max_commit_payload(small, lim)  # no raise

    lim2 = replace(lim, max_commit_payload_bytes=50)
    big = VersionCreateRequest(short_message="y" * 200, version_id="1.0.0", base_revision_id="")
    with pytest.raises(CommitPolicyViolation) as ei:
        enforce_max_commit_payload(big, lim2)
    assert ei.value.code == "PAYLOAD_TOO_LARGE"


def test_validate_version_notes_policy_violation_code():
    with pytest.raises(CommitPolicyViolation) as ei:
        validate_version_notes(None, None, DEFAULT_VERSION_NOTES_LIMITS)
    assert ei.value.code == "POLICY_VIOLATION"


def test_post_create_empty_short_message_returns_policy_envelope():
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
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1", "metadata": {}}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={"version_id": "1.0.0", "shortMessage": "", "baseRevisionId": ""},
        )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "POLICY_VIOLATION"
    assert "shortMessage" in body["detail"]["message"] or "Revision note" in body["detail"]["message"]


def test_post_create_respects_require_short_message_false_in_project_metadata():
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
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {
            "id": "proj-1",
            "metadata": {"commitPolicy": {"requireShortMessage": False}},
        }
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={"version_id": "1.0.0", "shortMessage": "", "baseRevisionId": ""},
        )
    assert r.status_code == 200


def test_post_create_payload_too_large_envelope():
    row = {
        "id": "rev-1",
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
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {
            "id": "proj-1",
            "metadata": {"commitPolicy": {"maxCommitPayloadBytes": 80}},
        }
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "x" * 200,
                "baseRevisionId": "",
            },
        )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "PAYLOAD_TOO_LARGE"
