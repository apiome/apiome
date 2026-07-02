"""Conditional GET (ETag / 304) on version pull endpoints (#2568 / P0-06)."""

from unittest.mock import MagicMock, patch

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


def _min_version(rid: str, version_line: str, metadata=None):
    return {
        "id": rid,
        "project_id": "proj-1",
        "creator_id": "test-user-id",
        "version_id": version_line,
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
        "metadata": metadata,
        "created_at": None,
        "updated_at": None,
        "creator_name": None,
        "creator_email": None,
        "project_name": "P",
        "project_slug": "p",
    }


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_version_sets_etag():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get("/v1/versions/tn/proj-1/rev-1")
    assert r.status_code == 200
    assert r.headers.get("etag") == '"rev-1"'


def test_get_version_304_when_if_none_match_matches():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            headers={"If-None-Match": '"rev-1"'},
        )
    assert r.status_code == 304
    assert r.headers.get("etag") == '"rev-1"'
    assert r.content == b""


def test_get_version_200_when_if_none_match_stale():
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            headers={"If-None-Match": '"other-id"'},
        )
    assert r.status_code == 200
    assert r.json()["id"] == "rev-1"


def test_get_version_resolve_304_includes_successor_headers():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    vb = _min_version("rev-b", "1.0.1", {})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        mdb.insert_version_protection_audit = MagicMock()
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=resolve",
            headers={"If-None-Match": '"rev-b"'},
        )
    assert r.status_code == 304
    assert r.headers.get("etag") == '"rev-b"'
    assert r.headers.get("x-apiome-resolved-from") == "rev-a"


def test_get_version_by_version_id_sets_etag():
    row = _min_version("rev-x", "2.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_version_id.return_value = row
        r = client.get("/v1/versions/tn/proj-1/by-version/2.0.0")
    assert r.status_code == 200
    assert r.headers.get("etag") == '"rev-x"'


def test_get_version_304_when_if_none_match_wildcard():
    """If-None-Match: * must return 304 for any existing resource (RFC 9110 §13.1.2)."""
    row = _min_version("rev-1", "1.0.0")
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = row
        r = client.get(
            "/v1/versions/tn/proj-1/rev-1",
            headers={"If-None-Match": "*"},
        )
    assert r.status_code == 304
    assert r.headers.get("etag") == '"rev-1"'
    assert r.content == b""


def test_helpers_if_none_match_case_insensitive():
    from app.versions_routes import _if_none_match_matches_revision

    rid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert _if_none_match_matches_revision(rid, f'"{rid.lower()}"')
    assert not _if_none_match_matches_revision(rid, '"other"')


def test_helpers_if_none_match_wildcard():
    from app.versions_routes import _if_none_match_matches_revision

    rid = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
    assert _if_none_match_matches_revision(rid, "*")
    assert _if_none_match_matches_revision(rid, ' * ')
    assert _if_none_match_matches_revision(rid, '"other", *')
    assert _if_none_match_matches_revision(rid, '*, "other"')
    assert not _if_none_match_matches_revision(rid, "")
