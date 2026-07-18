"""License seat-capacity enforcement (OLO-5.3, #4213).

Three layers are exercised:

* The pure helpers — ``member_seat_limit`` (license lookup + Free-default
  fallback) and ``assert_member_seat_available`` (the structured 403).
* The ``Database`` helpers — ``get_tenant_license_seats`` (V182 attachment →
  V097 catalog) and ``count_member_seats_in_use`` (suspended and soft-deleted
  members never occupy a seat), with ``execute_query`` mocked so no live
  database is touched.
* The route gate — ``require_member_seat`` around the member-invite route,
  including the ``license_enforcement_enabled`` kill switch.

Route-level companions (invite blocked at capacity, reinstate guard) live in
``test_access_routes.py`` beside the other member-route tests.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.config import settings
from app.database import DEFAULT_FREE_MAX_USERS_PER_TENANT
from app.database import db as real_db
from app.license_capacity import (
    LICENSE_SEATS_EXHAUSTED_CODE,
    assert_member_seat_available,
    member_seat_limit,
    require_license_capacity,
)
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-1111-1111-111111111111"
_AUTH = {
    "tenant_id": _TENANT,
    "user_id": "22222222-2222-2222-2222-222222222222",
    "auth_method": "jwt",
    "user_email": "owner@acme.io",
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# member_seat_limit — license lookup with Free-default fallback
# ===========================================================================


def _limit_with_seats(seats):
    with patch("app.license_capacity.db") as ldb:
        ldb.get_tenant_license_seats.return_value = seats
        return member_seat_limit(_TENANT)


def test_limit_reads_license_seats():
    assert _limit_with_seats({"max_tenants": 5, "max_users_per_tenant": 25}) == 25


def test_limit_falls_back_to_free_default_without_license_row():
    assert _limit_with_seats(None) == DEFAULT_FREE_MAX_USERS_PER_TENANT


def test_limit_falls_back_when_key_missing():
    assert _limit_with_seats({"max_tenants": 1}) == DEFAULT_FREE_MAX_USERS_PER_TENANT


def test_limit_falls_back_on_non_numeric_value():
    assert _limit_with_seats({"max_users_per_tenant": "lots"}) == DEFAULT_FREE_MAX_USERS_PER_TENANT


def test_limit_falls_back_on_negative_value():
    assert _limit_with_seats({"max_users_per_tenant": -3}) == DEFAULT_FREE_MAX_USERS_PER_TENANT


def test_limit_accepts_numeric_string():
    # JSONB round-trips can stringify numbers; int() coercion keeps them usable.
    assert _limit_with_seats({"max_users_per_tenant": "10"}) == 10


# ===========================================================================
# assert_member_seat_available — the structured 403
# ===========================================================================


def _assert_with(used, limit=5):
    with patch("app.license_capacity.db") as ldb:
        ldb.get_tenant_license_seats.return_value = {"max_users_per_tenant": limit}
        ldb.count_member_seats_in_use.return_value = used
        assert_member_seat_available(_TENANT)


def test_seat_available_under_limit_passes():
    _assert_with(used=4, limit=5)


def test_seats_exhausted_raises_structured_403():
    with pytest.raises(HTTPException) as exc:
        _assert_with(used=5, limit=5)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == LICENSE_SEATS_EXHAUSTED_CODE
    assert "5" in exc.value.detail["message"]


def test_over_limit_raises_too():
    # Counts can already exceed the limit (downgrade, pre-enforcement data);
    # the guard must still refuse new seats.
    with pytest.raises(HTTPException):
        _assert_with(used=7, limit=5)


def test_zero_seat_license_blocks_first_member():
    with pytest.raises(HTTPException):
        _assert_with(used=0, limit=0)


# ===========================================================================
# Database helpers — SQL shape and result handling (execute_query mocked)
# ===========================================================================


def test_get_tenant_license_seats_joins_attachment_to_catalog():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [{"seats": {"max_users_per_tenant": 5}}]
        seats = real_db.get_tenant_license_seats(_TENANT)
    assert seats == {"max_users_per_tenant": 5}
    sql = q.call_args.args[0]
    assert "tenant_licenses" in sql and "licenses" in sql
    assert q.call_args.args[1] == (_TENANT,)


def test_get_tenant_license_seats_returns_none_without_row():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = []
        assert real_db.get_tenant_license_seats(_TENANT) is None


def test_get_tenant_license_seats_rejects_non_object_seats():
    # A scalar/array seats value is malformed — callers must get the Free fallback.
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [{"seats": [5]}]
        assert real_db.get_tenant_license_seats(_TENANT) is None


def test_count_member_seats_excludes_suspended_and_deleted():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [{"c": 3}]
        assert real_db.count_member_seats_in_use(_TENANT) == 3
    sql = q.call_args.args[0]
    assert "status <> 'suspended'" in sql
    assert "deleted_at IS NULL" in sql
    assert q.call_args.args[1] == (_TENANT,)


def test_count_member_seats_defaults_to_zero():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = []
        assert real_db.count_member_seats_in_use(_TENANT) == 0


def test_get_member_status_returns_status_or_none():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [{"status": "suspended"}]
        assert real_db.get_member_status(_TENANT, "u-1") == "suspended"
        q.return_value = []
        assert real_db.get_member_status(_TENANT, "u-1") is None


# ===========================================================================
# Route gate — require_member_seat on the invite route + kill switch
# ===========================================================================


def test_kill_switch_off_bypasses_guard_entirely():
    with (
        patch("app.access_routes.db") as mdb,
        patch("app.license_capacity.db") as ldb,
        patch.object(settings, "license_enforcement_enabled", False),
    ):
        mdb.get_user_by_email.return_value = {"id": "u-9", "email": "noah@partner.com"}
        r = client.post("/v1/access/acme/members", json={"email": "noah@partner.com"})
    assert r.status_code == 200
    # Enforcement off: the license/seat lookups are never consulted.
    ldb.get_tenant_license_seats.assert_not_called()
    ldb.count_member_seats_in_use.assert_not_called()
    mdb.add_member.assert_called_once()


def test_guard_uses_free_default_when_license_row_missing():
    # Tenant predating the V183 backfill (no license row): Free's 5 seats apply.
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        ldb.get_tenant_license_seats.return_value = None
        ldb.count_member_seats_in_use.return_value = DEFAULT_FREE_MAX_USERS_PER_TENANT
        r = client.post("/v1/access/acme/members", json={"email": "noah@partner.com"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == LICENSE_SEATS_EXHAUSTED_CODE
    mdb.add_member.assert_not_called()


def test_guard_skips_when_auth_has_no_tenant_context():
    # Without a tenant id there is nothing to count against; the guard passes
    # auth through and defers to the route's own permission checks.
    dep = require_license_capacity(enforcement_enabled=lambda: True)
    auth = {"user_id": _AUTH["user_id"], "auth_method": "jwt"}
    with patch("app.license_capacity.db") as ldb:
        assert dep(auth) is auth
    ldb.count_member_seats_in_use.assert_not_called()
