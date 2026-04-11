"""Tests for GET version successor resolution (#749)."""

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


def _override_auth():
    return _MOCK_AUTH


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
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_version_resolve_returns_final_revision_and_headers():
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
        )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rev-b"
    assert r.headers.get("x-objectified-resolved-from") == "rev-a"
    assert r.headers.get("x-objectified-successor-chain") == "rev-b"
    assert r.headers.get("x-objectified-successor-resolution-status") == "resolved"


def test_get_version_successor_cycle_409():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.return_value = va
        mdb.resolve_successor_revision_chain.return_value = ("rev-a", ["rev-b"], "cycle", None)
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=resolve",
        )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "SUCCESSOR_CYCLE"


def test_get_version_redirect_307():
    va = _min_version("rev-a", "1.0.0", {"successorRevisionId": "rev-b"})
    vb = _min_version("rev-b", "1.0.1", {})
    with patch("app.versions_routes.db") as mdb:
        mdb.get_version_by_id.side_effect = lambda vid, tid: (
            va if vid == "rev-a" else vb if vid == "rev-b" else None
        )
        mdb.resolve_successor_revision_chain.return_value = ("rev-b", ["rev-b"], "resolved", None)
        r = client.get(
            "/v1/versions/tn/proj-1/rev-a?successorResolution=redirect",
            follow_redirects=False,
        )
    assert r.status_code == 307
    loc = r.headers.get("location") or ""
    assert "rev-b" in loc
    assert "successorResolution=none" in loc


def test_resolve_successor_chain_unit():
    from app.database import Database

    db = Database()
    with patch.object(db, "get_version_by_id") as gv, patch.object(
        db, "revision_has_protected_named_ref", return_value=False
    ):
        a = _min_version("a", "1.0.0", {"successorRevisionId": "b"})
        b = _min_version("b", "1.0.1", {})
        gv.side_effect = lambda vid, tid: a if vid == "a" else b if vid == "b" else None
        final, hops, status, miss = db.resolve_successor_revision_chain("a", "test-tenant-id", "proj-1")
    assert final == "b"
    assert hops == ["b"]
    assert status == "resolved"
    assert miss is None


def test_resolve_successor_chain_cycle():
    from app.database import Database

    db = Database()
    with patch.object(db, "get_version_by_id") as gv, patch.object(
        db, "revision_has_protected_named_ref", return_value=False
    ):
        a = _min_version("a", "1.0.0", {"successorRevisionId": "b"})
        b = _min_version("b", "1.0.1", {"successorRevisionId": "a"})
        gv.side_effect = lambda vid, tid: a if vid == "a" else b if vid == "b" else None
        final, hops, status, miss = db.resolve_successor_revision_chain("a", "test-tenant-id", "proj-1")
    assert status == "cycle"
    assert miss is None


def test_resolve_successor_blocked_when_protected_ref():
    from app.database import Database

    db = Database()
    with patch.object(db, "get_version_by_id") as gv, patch.object(
        db, "revision_has_protected_named_ref", return_value=True
    ):
        a = _min_version("a", "1.0.0", {"successorRevisionId": "b"})
        gv.return_value = a
        final, hops, status, miss = db.resolve_successor_revision_chain("a", "test-tenant-id", "proj-1")
    assert final == "a"
    assert hops == []
    assert status == "blocked_protected_ref"
    assert miss is None
