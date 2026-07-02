"""Unit tests for the central RBAC permission guard (#3611).

These exercise ``permissions.enforce_permission`` / ``has_permission`` / ``enforce_platform_admin``
against an in-memory fake ``db``, so they validate the guard's control flow (admin vs. granular vs.
denial, actor resolution, denial auditing) without a live database.
"""

import pytest
from fastapi import HTTPException

from app.permissions import (
    Action,
    Resource,
    enforce_permission,
    enforce_platform_admin,
    has_permission,
    is_valid_permission,
    permission_key,
)


class FakeDB:
    """Minimal stand-in implementing only what the guard calls."""

    def __init__(self, *, allow=False, platform=False, fallback_uid=None):
        self._allow = allow
        self._platform = platform
        self._fallback_uid = fallback_uid
        self.audit_calls = []

    def user_has_permission(self, tenant_id, user_id, resource, action):
        return self._allow

    def is_platform_admin(self, user_id):
        return self._platform

    def get_fallback_creator_user_id_for_tenant(self, tenant_id):
        return self._fallback_uid

    def write_access_audit(self, **kwargs):
        self.audit_calls.append(kwargs)


_JWT = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt", "user_email": "u1@acme.io"}


def test_permission_key_and_validation():
    assert permission_key("versions", "publish") == "versions:publish"
    assert is_valid_permission(Resource.VERSIONS, Action.PUBLISH)
    assert not is_valid_permission("versions", "frobnicate")
    assert not is_valid_permission("spaceships", "view")


def test_enforce_allows_when_granted():
    db = FakeDB(allow=True)
    uid = enforce_permission(db, _JWT, Resource.VERSIONS, Action.CREATE)
    assert uid == "u1"
    assert db.audit_calls == []  # no denial audit on success


def test_enforce_denies_and_audits_when_not_granted():
    db = FakeDB(allow=False)
    with pytest.raises(HTTPException) as exc:
        enforce_permission(db, _JWT, Resource.MEMBERS, Action.DELETE)
    assert exc.value.status_code == 403
    assert "members:delete" in exc.value.detail
    # A denial is recorded in the access ledger.
    assert len(db.audit_calls) == 1
    assert db.audit_calls[0]["action"] == "permission.denied"
    assert db.audit_calls[0]["target"] == "members:delete"


def test_enforce_requires_resolvable_user():
    db = FakeDB(allow=True)
    with pytest.raises(HTTPException) as exc:
        enforce_permission(db, {"tenant_id": "t1", "auth_method": "jwt"}, Resource.VERSIONS, Action.EDIT)
    assert exc.value.status_code == 403
    assert "Authenticated user required" in exc.value.detail


def test_api_key_actor_falls_back_to_tenant_creator():
    """An API key without a bound user resolves the tenant's fallback creator (legacy keys)."""
    db = FakeDB(allow=True, fallback_uid="creator-9")
    auth = {"tenant_id": "t1", "auth_method": "api_key"}
    uid = enforce_permission(db, auth, Resource.VERSIONS, Action.CREATE)
    assert uid == "creator-9"


def test_has_permission_is_nonraising():
    assert has_permission(FakeDB(allow=True), _JWT, Resource.PATHS, Action.EDIT) is True
    assert has_permission(FakeDB(allow=False), _JWT, Resource.PATHS, Action.EDIT) is False


def test_enforce_platform_admin():
    assert enforce_platform_admin(FakeDB(platform=True), _JWT) == "u1"
    with pytest.raises(HTTPException) as exc:
        enforce_platform_admin(FakeDB(platform=False), _JWT)
    assert exc.value.status_code == 403
