"""Tests for ``POST /v1/onboarding/first-tenant`` (OLO-4.3, #4207).

Route-level tests mock auth (dependency override) and the db singleton, so no
live database is touched. The transactional ``Database.provision_first_tenant``
is exercised separately with a mocked connection to prove the all-or-nothing
contract (commit only on full success, rollback on any failure).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.database import (
    Database,
    TenantCapReachedError,
    TenantSlugConflictError,
)
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

_TENANT_ROW = {
    "id": _TENANT_ID,
    "name": "Acme Corp",
    "slug": "acme-corp",
    "created_at": datetime(2026, 7, 17, 12, 0, 0),
}


@pytest.fixture(autouse=True)
def _jwt_session():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_JWT_SESSION)
    yield
    app.dependency_overrides.pop(validate_session_credentials, None)


def _post(body):
    return client.post("/v1/onboarding/first-tenant", json=body)


# ---- auth ----------------------------------------------------------------


def test_requires_credentials():
    app.dependency_overrides.pop(validate_session_credentials, None)
    r = _post({"name": "Acme Corp"})
    assert r.status_code == 401


def test_rejects_api_key_sessions():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_API_KEY_SESSION)
    r = _post({"name": "Acme Corp"})
    assert r.status_code == 403


def test_rejects_malformed_user_id():
    app.dependency_overrides[validate_session_credentials] = lambda: {
        **_JWT_SESSION,
        "user_id": "not-a-uuid",
    }
    r = _post({"name": "Acme Corp"})
    assert r.status_code == 401


# ---- validation ----------------------------------------------------------


def test_name_is_required_by_schema():
    r = _post({})
    assert r.status_code == 422


def test_blank_name_rejected():
    r = _post({"name": "   "})
    assert r.status_code == 400
    assert "name is required" in r.json()["detail"].lower()


def test_invalid_slug_rejected():
    r = _post({"name": "Acme Corp", "slug": "not a slug!"})
    assert r.status_code == 400
    assert "lowercase letters" in r.json()["detail"]


def test_reserved_slug_rejected():
    r = _post({"name": "Acme Corp", "slug": "me"})
    assert r.status_code == 400
    assert "reserved" in r.json()["detail"]


def test_underivable_name_rejected():
    # Name has no slug-safe characters and no explicit slug was given.
    r = _post({"name": "!!!"})
    assert r.status_code == 400


# ---- provisioning --------------------------------------------------------


def test_provisions_tenant_and_sample_project():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.return_value = dict(_TENANT_ROW)
        mdb.provision_sample_project.return_value = "990e8400-e29b-41d4-a716-446655440009"
        r = _post({"name": "Acme Corp", "slug": "acme-corp"})

    assert r.status_code == 201
    body = r.json()
    assert body["tenant"] == {
        "id": _TENANT_ID,
        "name": "Acme Corp",
        "slug": "acme-corp",
        "created_at": "2026-07-17",
    }
    assert body["sample_project_id"] == "990e8400-e29b-41d4-a716-446655440009"
    mdb.provision_first_tenant.assert_called_once_with(_USER_ID, "Acme Corp", "acme-corp")
    mdb.provision_sample_project.assert_called_once_with(_TENANT_ID, _USER_ID)


def test_slug_derived_from_name_when_omitted():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.return_value = dict(_TENANT_ROW)
        mdb.provision_sample_project.return_value = None
        r = _post({"name": "Acme, Inc."})

    assert r.status_code == 201
    mdb.provision_first_tenant.assert_called_once_with(_USER_ID, "Acme, Inc.", "acme-inc")


def test_sample_project_can_be_skipped():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.return_value = dict(_TENANT_ROW)
        r = _post({"name": "Acme Corp", "provision_sample_project": False})

    assert r.status_code == 201
    assert r.json()["sample_project_id"] is None
    mdb.provision_sample_project.assert_not_called()


def test_sample_project_failure_does_not_fail_provisioning():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.return_value = dict(_TENANT_ROW)
        mdb.provision_sample_project.side_effect = RuntimeError("seed failed")
        r = _post({"name": "Acme Corp"})

    assert r.status_code == 201
    assert r.json()["sample_project_id"] is None


def test_tenant_cap_returns_403_with_code():
    # OLO-5.3 (#4213): the tenant-cap guard is a license-enforcement 403 (the
    # slug conflict below stays a 409).
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.side_effect = TenantCapReachedError(
            "Tenant limit reached (1/1 tenants used)"
        )
        r = _post({"name": "Second Org", "slug": "second-org"})

    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["code"] == "tenant-cap-reached"
    assert "limit" in detail["message"].lower()
    mdb.provision_sample_project.assert_not_called()


def test_slug_conflict_returns_409_with_code():
    with patch("app.onboarding_routes.db") as mdb:
        mdb.provision_first_tenant.side_effect = TenantSlugConflictError(
            "A tenant with this slug already exists"
        )
        r = _post({"name": "Acme Corp", "slug": "acme-corp"})

    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "tenant-slug-taken"


# ---- Database.provision_first_tenant atomicity ---------------------------


def _mock_connection():
    """A psycopg2-shaped connection mock whose cursor fetches can be scripted."""
    conn = MagicMock()
    conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE
    conn.autocommit = True
    cursor = conn.cursor.return_value.__enter__.return_value
    return conn, cursor


def _database_with(conn) -> Database:
    dbi = Database()
    dbi.connect = lambda: conn  # type: ignore[method-assign]
    return dbi


def test_tx_commits_once_on_full_success():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 1},  # entitlements row
        {"c": 0},  # current tenant count
        None,  # slug pre-check: free
        dict(_TENANT_ROW),  # INSERT ... RETURNING
        {"id": "880e8400-e29b-41d4-a716-446655440008"},  # owner role lookup
    ]
    dbi = _database_with(conn)

    tenant = dbi.provision_first_tenant(_USER_ID, "Acme Corp", "acme-corp")

    assert tenant["slug"] == "acme-corp"
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    assert conn.autocommit is True  # restored in finally
    executed_sql = " ".join(str(c.args[0]) for c in cursor.execute.call_args_list)
    for fragment in (
        "INSERT INTO apiome.tenants",
        "attach_free_license",
        "seed_builtin_roles",
        "INSERT INTO apiome.tenant_users",
        "INSERT INTO apiome.tenant_user_roles",
        "INSERT INTO apiome.tenant_administrators",
        "INSERT INTO apiome.user_entitlements",
    ):
        assert fragment in executed_sql


def test_tx_attaches_free_license_in_same_transaction():
    """OLO-5.2 (#4212): the Free license attach runs inside the provisioning
    transaction — after the tenant insert, before the single commit — so a new
    tenant always has its tenant_licenses row or does not exist at all."""
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 1},
        {"c": 0},
        None,
        dict(_TENANT_ROW),
        {"id": "880e8400-e29b-41d4-a716-446655440008"},
    ]
    dbi = _database_with(conn)

    dbi.provision_first_tenant(_USER_ID, "Acme Corp", "acme-corp")

    license_calls = [
        c
        for c in cursor.execute.call_args_list
        if "attach_free_license" in str(c.args[0])
    ]
    assert len(license_calls) == 1
    assert license_calls[0].args[1] == (_TENANT_ID,)
    # The attach happened strictly before the transaction committed.
    conn.commit.assert_called_once()
    statements = [str(c.args[0]) for c in cursor.execute.call_args_list]
    insert_idx = next(
        i for i, s in enumerate(statements) if "INSERT INTO apiome.tenants" in s
    )
    attach_idx = next(
        i for i, s in enumerate(statements) if "attach_free_license" in s
    )
    assert insert_idx < attach_idx


def test_tx_rolls_back_when_cap_reached():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 1},
        {"c": 1},  # already at cap
    ]
    dbi = _database_with(conn)

    with pytest.raises(TenantCapReachedError):
        dbi.provision_first_tenant(_USER_ID, "Second Org", "second-org")

    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    assert conn.autocommit is True


def test_tx_missing_entitlements_falls_back_to_free_default():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        None,  # no user_entitlements row -> Free default of 1
        {"c": 1},
    ]
    dbi = _database_with(conn)

    with pytest.raises(TenantCapReachedError):
        dbi.provision_first_tenant(_USER_ID, "Second Org", "second-org")


def test_tx_rolls_back_on_slug_conflict_precheck():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 5},
        {"c": 1},
        {"?column?": 1},  # slug pre-check found an active tenant
    ]
    dbi = _database_with(conn)

    with pytest.raises(TenantSlugConflictError):
        dbi.provision_first_tenant(_USER_ID, "Acme Corp", "acme-corp")

    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


def test_tx_maps_unique_violation_race_to_slug_conflict():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 5},
        {"c": 0},
        None,  # pre-check passes...
    ]

    def _execute(sql, params=None):
        # ...but the concurrent-insert race trips the unique index.
        if "INSERT INTO apiome.tenants" in sql:
            raise psycopg2.errors.UniqueViolation("duplicate key value")

    cursor.execute.side_effect = _execute
    dbi = _database_with(conn)

    with pytest.raises(TenantSlugConflictError):
        dbi.provision_first_tenant(_USER_ID, "Acme Corp", "acme-corp")

    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
    assert conn.autocommit is True


def test_tx_rolls_back_when_owner_role_missing():
    conn, cursor = _mock_connection()
    cursor.fetchone.side_effect = [
        {"max_tenants": 1},
        {"c": 0},
        None,
        dict(_TENANT_ROW),
        None,  # owner role lookup fails
    ]
    dbi = _database_with(conn)

    with pytest.raises(Exception) as exc_info:
        dbi.provision_first_tenant(_USER_ID, "Acme Corp", "acme-corp")

    assert "owner role" in str(exc_info.value).lower()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
