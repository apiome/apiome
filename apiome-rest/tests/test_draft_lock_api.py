"""Draft lock API (#2584)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_MOCK_API_KEY = {
    "tenant_id": "t1",
    "tenant_slug": "tn",
    "auth_method": "api_key",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_acquire_conflict_409_metadata():
    exp = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.acquire_version_draft_lock.return_value = {
            "kind": "conflict",
            "owner_user_id": "user-b",
            "expires_at": exp,
        }
        r = client.post(
            "/v1/versions/tn/proj/v1/draft-lock/acquire",
            json={"leaseSeconds": 120},
        )
        assert r.status_code == 409
        mdb.acquire_version_draft_lock.assert_called_once()
        assert mdb.acquire_version_draft_lock.call_args.kwargs["lease_seconds"] == 120
        d = r.json()["detail"]
        assert d["code"] == "DRAFT_LOCK_CONFLICT"
        assert d["ownerUserId"] == "user-b"
        assert "expiresAt" in d


def test_acquire_ok():
    exp = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.acquire_version_draft_lock.return_value = {
            "kind": "ok",
            "version_id": "v1",
            "owner_user_id": "user-a",
            "expires_at": exp,
        }
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/acquire", json={})
        assert r.status_code == 200
        body = r.json()
        assert body["versionId"] == "v1"
        assert body["ownerUserId"] == "user-a"


def test_api_key_acquire_forbidden():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_API_KEY
    try:
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/acquire", json={})
        assert r.status_code == 403
    finally:
        app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT


def test_renew_not_held_409():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.renew_version_draft_lock.return_value = {"kind": "not_held"}
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/renew", json={})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "DRAFT_LOCK_NOT_HELD"


def test_release_204():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.release_version_draft_lock.return_value = "released"
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/release")
        assert r.status_code == 204


def test_release_forbidden_403():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.release_version_draft_lock.return_value = "forbidden"
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/release")
        assert r.status_code == 403


def test_force_release_requires_admin():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = False
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/force-release")
        assert r.status_code == 403
        mdb.force_release_version_draft_lock.assert_not_called()


def test_force_release_admin_204():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.force_release_version_draft_lock.return_value = True
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/force-release")
        assert r.status_code == 204
        mdb.force_release_version_draft_lock.assert_called_once()


def test_published_version_acquire_400():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.acquire_version_draft_lock.side_effect = ValueError("published_version")
        r = client.post("/v1/versions/tn/proj/v1/draft-lock/acquire", json={})
        assert r.status_code == 400


def test_get_draft_lock_status_inactive():
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.get_version_draft_lock_status.return_value = {"active": False}
        r = client.get("/v1/versions/tn/proj/v1/draft-lock")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is False
        assert body.get("versionId") is None
        assert body.get("ownerUserId") is None
        assert body.get("expiresAt") is None


def test_get_draft_lock_status_active():
    exp = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)
    with patch("app.draft_lock_routes.db") as mdb:
        mdb.get_version_draft_lock_status.return_value = {
            "active": True,
            "version_id": "vid-1",
            "owner_user_id": "user-b",
            "expires_at": exp,
        }
        r = client.get("/v1/versions/tn/proj/v1/draft-lock")
        assert r.status_code == 200
        body = r.json()
        assert body["active"] is True
        assert body["versionId"] == "vid-1"
        assert body["ownerUserId"] == "user-b"
        assert "expiresAt" in body
