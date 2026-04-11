"""Commit metadata on revisions: author, message, externalRef (#2563)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import VersionCreateRequest, VersionSchema

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


def _make_version_row(commit_author=None, commit_message=None, external_ref=None):
    return {
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
        "commit_author": commit_author,
        "commit_message": commit_message,
        "external_ref": external_ref,
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
        "created_at": None,
        "updated_at": None,
    }



def test_migration_adds_commit_metadata_columns():
    repo_root = Path(__file__).resolve().parents[2]
    migration = repo_root / "objectified-db" / "scripts" / "20260411-120000.sql"
    text = migration.read_text()
    assert "commit_author" in text
    assert "commit_message" in text
    assert "external_ref" in text
    assert "ADD COLUMN" in text


def test_version_create_request_accepts_camel_case_commit_fields():
    body = VersionCreateRequest.model_validate(
        {
            "version_id": "1.0.0",
            "shortMessage": "subject",
            "author": "CI Bot",
            "message": "Full body",
            "externalRef": "LINEAR-42",
            "baseRevisionId": "",
        }
    )
    assert body.author == "CI Bot"
    assert body.message == "Full body"
    assert body.external_ref == "LINEAR-42"


def test_version_schema_serializes_commit_metadata_with_api_aliases():
    row = {
        "id": "rev-1",
        "project_id": "p1",
        "creator_id": None,
        "version_id": "1.0.0",
        "description": "subject",
        "change_log": None,
        "visibility": "private",
        "published": False,
        "published_at": None,
        "enabled": True,
        "parent_version_id": None,
        "merge_parent_version_id": None,
        "revision_locked": False,
        "metadata": {},
        "commit_author": "alice",
        "commit_message": "details",
        "external_ref": "JIRA-1",
        "creator_name": None,
        "creator_email": None,
        "project_name": None,
        "project_slug": None,
        "created_at": None,
        "updated_at": None,
    }
    out = VersionSchema(**row).model_dump(by_alias=True, exclude_none=False)
    assert out["author"] == "alice"
    assert out["message"] == "details"
    assert out["externalRef"] == "JIRA-1"


def test_version_schema_null_commit_metadata_renders():
    row = {
        "id": "rev-1",
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
        "revision_locked": False,
        "metadata": {},
        "commit_author": None,
        "commit_message": None,
        "external_ref": None,
        "creator_name": None,
        "creator_email": None,
        "project_name": None,
        "project_slug": None,
        "created_at": None,
        "updated_at": None,
    }
    schema = VersionSchema(**row)
    assert schema.author is None
    assert schema.message is None
    assert schema.external_ref is None
    dumped = schema.model_dump(by_alias=True)
    assert dumped.get("author") is None
    assert dumped.get("message") is None
    assert dumped.get("externalRef") is None


# ---------------------------------------------------------------------------
# TestClient (API-layer) tests – exercise normalization, DB forwarding, and
# response serialization via the live FastAPI app with db patched.
# ---------------------------------------------------------------------------


def test_post_create_commit_metadata_stored_and_echoed():
    """Commit metadata fields are normalized, passed to db.create_version_push_transaction, and echoed back."""
    row = _make_version_row(commit_author="Alice", commit_message="Add feature", external_ref="JIRA-1")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "subject",
                "author": "Alice",
                "message": "Add feature",
                "externalRef": "JIRA-1",
                "baseRevisionId": "",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["author"] == "Alice"
    assert body["message"] == "Add feature"
    assert body["externalRef"] == "JIRA-1"
    call_kwargs = mdb.create_version_push_transaction.call_args.kwargs
    assert call_kwargs["commit_author"] == "Alice"
    assert call_kwargs["commit_message"] == "Add feature"
    assert call_kwargs["external_ref"] == "JIRA-1"
    assert call_kwargs["client_base_revision_id"] == ""


def test_post_create_whitespace_only_commit_metadata_becomes_null():
    """Whitespace-only commit metadata fields normalize to None before DB insert."""
    row = _make_version_row()
    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_latest_version_for_project.return_value = None
        mdb.list_version_branches_for_project.return_value = []
        mdb.get_latest_revision_id_for_project.return_value = None
        mdb.create_version_push_transaction.return_value = (row, 0)
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "subject",
                "author": "   ",
                "message": "\t\n",
                "externalRef": "  ",
                "baseRevisionId": "",
            },
        )
    assert r.status_code == 200
    call_kwargs = mdb.create_version_push_transaction.call_args.kwargs
    assert call_kwargs["commit_author"] is None
    assert call_kwargs["commit_message"] is None
    assert call_kwargs["external_ref"] is None


def test_post_create_overlong_author_returns_400():
    """author exceeding _AUTHOR_OR_REF_MAX_CHARS returns HTTP 400."""
    from app.versions_routes import _AUTHOR_OR_REF_MAX_CHARS

    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_latest_version_for_project.return_value = None
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "subject",
                "author": "x" * (_AUTHOR_OR_REF_MAX_CHARS + 1),
                "baseRevisionId": "",
            },
        )
    assert r.status_code == 400
    assert "author" in r.json()["detail"].lower()


def test_post_create_overlong_message_returns_400():
    """message exceeding _DEFAULT_COMMIT_METADATA_MAX_CHARS returns HTTP 400."""
    from app.versions_routes import _DEFAULT_COMMIT_METADATA_MAX_CHARS

    with patch("app.versions_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_latest_version_for_project.return_value = None
        r = client.post(
            "/v1/versions/tn/proj-1",
            json={
                "version_id": "1.0.0",
                "shortMessage": "subject",
                "message": "x" * (_DEFAULT_COMMIT_METADATA_MAX_CHARS + 1),
                "baseRevisionId": "",
            },
        )
    assert r.status_code == 400
    assert "message" in r.json()["detail"].lower()

