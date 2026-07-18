"""Tests for ``POST /v1/onboarding/membership-activation`` (OLO-4.4, #4208).

Route-level tests mock auth (dependency override) and the db singleton, so no
live database is touched. ``Database.activate_pending_membership`` is
exercised separately with a mocked connection to prove the status-aware
contract: only ``pending`` rows transition to ``active``; ``suspended`` rows
are never touched by sign-in.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.database import Database
from app.main import app

client = TestClient(app)

_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"

_JWT_SESSION = {
    "auth_method": "jwt",
    "user_id": _USER_ID,
    "user_email": "ada@example.com",
    "user_name": "Ada",
}

_API_KEY_SESSION = {
    "auth_method": "api_key",
    "user_id": _USER_ID,
    "tenant_id": _TENANT_ID,
}


@pytest.fixture(autouse=True)
def _jwt_session():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_JWT_SESSION)
    yield
    app.dependency_overrides.pop(validate_session_credentials, None)


def _post(body):
    return client.post("/v1/onboarding/membership-activation", json=body)


# ---- auth ----------------------------------------------------------------


def test_requires_credentials():
    app.dependency_overrides.pop(validate_session_credentials, None)
    r = _post({"tenant_id": _TENANT_ID})
    assert r.status_code == 401


def test_rejects_api_key_sessions():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_API_KEY_SESSION)
    r = _post({"tenant_id": _TENANT_ID})
    assert r.status_code == 403


def test_rejects_malformed_user_id():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        **_JWT_SESSION,
        "user_id": "not-a-uuid",
    }
    r = _post({"tenant_id": _TENANT_ID})
    assert r.status_code == 401


# ---- validation ----------------------------------------------------------


def test_tenant_id_is_required_by_schema():
    r = _post({})
    assert r.status_code == 422


def test_blank_tenant_id_rejected():
    r = _post({"tenant_id": "   "})
    assert r.status_code == 400
    assert "uuid" in r.json()["detail"].lower()


def test_non_uuid_tenant_id_rejected():
    # Malformed ids must be refused before they reach a ::uuid cast.
    r = _post({"tenant_id": "not-a-uuid"})
    assert r.status_code == 400
    assert "uuid" in r.json()["detail"].lower()


# ---- activation outcomes -------------------------------------------------


def test_pending_membership_is_activated():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.return_value = "activated"
        r = _post({"tenant_id": _TENANT_ID})

    assert r.status_code == 200
    assert r.json() == {"status": "activated", "tenant_id": _TENANT_ID}
    mdb.activate_pending_membership.assert_called_once_with(_TENANT_ID, _USER_ID)


def test_already_active_membership_is_a_noop():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.return_value = "already-active"
        r = _post({"tenant_id": _TENANT_ID})

    assert r.status_code == 200
    assert r.json() == {"status": "already-active", "tenant_id": _TENANT_ID}


def test_missing_membership_returns_404_with_code():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.return_value = "none"
        r = _post({"tenant_id": _TENANT_ID})

    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "membership-not-found"


def test_suspended_membership_returns_403_and_stays_suspended():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.return_value = "suspended"
        r = _post({"tenant_id": _TENANT_ID})

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "membership-suspended"


def test_db_fault_degrades_to_structured_500():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.side_effect = RuntimeError("db down")
        r = _post({"tenant_id": _TENANT_ID})

    assert r.status_code == 500
    assert r.json()["detail"]["code"] == "membership-activation-failed"


def test_uuid_is_canonicalized_before_lookup():
    # Uppercase input reaches the db layer in canonical lowercase form.
    with patch("app.onboarding_routes.db") as mdb:
        mdb.activate_pending_membership.return_value = "already-active"
        r = _post({"tenant_id": _TENANT_ID.upper()})

    assert r.status_code == 200
    mdb.activate_pending_membership.assert_called_once_with(_TENANT_ID, _USER_ID)


# ---- Database.activate_pending_membership --------------------------------


def _database_with_cursor():
    """A Database whose connection yields a scriptable cursor mock."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    dbi = Database()
    dbi.connect = lambda: conn  # type: ignore[method-assign]
    return dbi, conn, cursor


def test_db_activates_only_pending_rows():
    dbi, conn, cursor = _database_with_cursor()
    cursor.rowcount = 1  # the status='pending' guarded UPDATE matched

    assert dbi.activate_pending_membership(_TENANT_ID, _USER_ID) == "activated"

    update_sql = cursor.execute.call_args_list[0].args[0]
    assert "status = 'active'" in update_sql
    assert "status = 'pending'" in update_sql  # WHERE guard: pending rows only
    conn.commit.assert_called_once()


def test_db_reports_already_active_without_writing():
    dbi, conn, cursor = _database_with_cursor()
    cursor.rowcount = 0  # UPDATE matched nothing...
    cursor.fetchall.return_value = [{"status": "active"}]  # ...row is active

    assert dbi.activate_pending_membership(_TENANT_ID, _USER_ID) == "already-active"


def test_db_reports_suspended_without_reactivating():
    dbi, conn, cursor = _database_with_cursor()
    cursor.rowcount = 0
    cursor.fetchall.return_value = [{"status": "suspended"}]

    assert dbi.activate_pending_membership(_TENANT_ID, _USER_ID) == "suspended"
    # Exactly two statements ran: the guarded UPDATE and the status SELECT —
    # no second UPDATE that could flip a suspended row.
    assert cursor.execute.call_count == 2


def test_db_reports_missing_membership():
    dbi, conn, cursor = _database_with_cursor()
    cursor.rowcount = 0
    cursor.fetchall.return_value = []

    assert dbi.activate_pending_membership(_TENANT_ID, _USER_ID) == "none"
