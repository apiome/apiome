"""Tenant license REST surface (OLO-5.4, #4214).

Three layers are exercised:

* The pure composition helper — ``compose_effective_features`` (override beats
  license default; a disabled master switch beats both).
* The ``Database`` helpers — ``get_tenant_license_info`` (V182 attachment →
  V097 catalog) and ``list_tenant_effective_features`` (license-bundle ∪
  tenant-override union), with ``execute_query`` mocked so no live database is
  touched.
* The route — ``GET /v1/tenants/{slug}/license``: payload shape, the
  no-license-row Free fallback (numbers must match the OLO-5.3 guard), and the
  ``billing:view`` permission matrix (admin / member / stripped role / API key
  with and without a resolvable actor).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import (
    DEFAULT_FREE_MAX_AI_REQUESTS,
    DEFAULT_FREE_MAX_PROJECTS,
    DEFAULT_FREE_MAX_USERS_PER_TENANT,
    DEFAULT_FREE_MAX_VERSIONS,
)
from app.database import db as real_db
from app.license_routes import (
    FEATURE_SOURCE_LICENSE,
    FEATURE_SOURCE_TENANT_OVERRIDE,
    compose_effective_features,
)
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-1111-1111-111111111111"
_USER = "22222222-2222-2222-2222-222222222222"
_AUTH = {
    "tenant_id": _TENANT,
    "user_id": _USER,
    "auth_method": "jwt",
    "user_email": "owner@acme.io",
}

_LICENSE_INFO = {
    "name": "Paid",
    "license_type": "paid",
    "seats": {
        "max_tenants": 5,
        "max_users_per_tenant": 25,
        "max_projects": 10,
        "max_versions": 50,
        "max_ai_requests": 1000,
    },
    "issued_at": "2026-07-01T00:00:00+00:00",
}

_FEATURE_ROWS = [
    {
        "name": "designer",
        "label": "Schema Designer",
        "description": "Visual schema designer.",
        "is_preview": False,
        "flag_enabled": True,
        "license_grant": True,
        "tenant_override": None,
    },
    {
        "name": "paths",
        "label": "API Paths",
        "description": None,
        "is_preview": False,
        "flag_enabled": True,
        "license_grant": True,
        "tenant_override": False,
    },
    {
        "name": "repositories",
        "label": "Repositories",
        "description": None,
        "is_preview": True,
        "flag_enabled": True,
        "license_grant": False,
        "tenant_override": True,
    },
]


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _get_license(rdb, ldb, *, info=_LICENSE_INFO, used=3, features=None):
    """Drive the route with both module-level db handles doubled."""
    rdb.user_has_permission.return_value = True
    rdb.get_tenant_license_info.return_value = info
    rdb.count_member_seats_in_use.return_value = used
    rdb.list_tenant_effective_features.return_value = (
        _FEATURE_ROWS if features is None else features
    )
    ldb.get_tenant_license_seats.return_value = (info or {}).get("seats")
    return client.get("/v1/tenants/acme/license")


# ===========================================================================
# compose_effective_features — the V097 composition rules
# ===========================================================================


def test_license_grant_without_override_is_enabled_from_license():
    [f] = compose_effective_features([_FEATURE_ROWS[0]])
    assert f.enabled is True
    assert f.source == FEATURE_SOURCE_LICENSE
    assert f.name == "designer" and f.label == "Schema Designer"


def test_tenant_revoke_beats_license_grant():
    [f] = compose_effective_features([_FEATURE_ROWS[1]])
    assert f.enabled is False
    assert f.source == FEATURE_SOURCE_TENANT_OVERRIDE


def test_tenant_grant_without_license_bundle_is_enabled():
    [f] = compose_effective_features([_FEATURE_ROWS[2]])
    assert f.enabled is True
    assert f.source == FEATURE_SOURCE_TENANT_OVERRIDE
    assert f.is_preview is True


def test_disabled_master_switch_beats_every_layer():
    rows = [
        {**_FEATURE_ROWS[0], "flag_enabled": False},
        {**_FEATURE_ROWS[2], "flag_enabled": False},
    ]
    composed = compose_effective_features(rows)
    assert [f.enabled for f in composed] == [False, False]
    # Source still reports the deciding layer so the UI can explain the state.
    assert composed[1].source == FEATURE_SOURCE_TENANT_OVERRIDE


def test_no_license_grant_and_no_override_is_disabled():
    # Defensive: such rows are filtered out by the SQL union, but the fold
    # must not invent an entitlement if one slips through.
    [f] = compose_effective_features(
        [{**_FEATURE_ROWS[0], "license_grant": False, "tenant_override": None}]
    )
    assert f.enabled is False
    assert f.source == FEATURE_SOURCE_LICENSE


def test_compose_tolerates_missing_metadata():
    [f] = compose_effective_features(
        [{"flag_enabled": True, "license_grant": True, "tenant_override": None}]
    )
    assert f.name == "" and f.label == "" and f.description is None
    assert f.enabled is True and f.is_preview is False


# ===========================================================================
# Database helpers — SQL shape and result handling (execute_query mocked)
# ===========================================================================


def test_get_tenant_license_info_joins_attachment_to_catalog():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [_LICENSE_INFO]
        info = real_db.get_tenant_license_info(_TENANT)
    assert info == _LICENSE_INFO
    sql = q.call_args.args[0]
    assert "tenant_licenses" in sql and "licenses" in sql
    assert "license_type" in sql
    assert q.call_args.args[1] == (_TENANT,)


def test_get_tenant_license_info_returns_none_without_row():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = []
        assert real_db.get_tenant_license_info(_TENANT) is None


def test_list_tenant_effective_features_unions_license_and_overrides():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = _FEATURE_ROWS
        rows = real_db.list_tenant_effective_features(_TENANT)
    assert rows == _FEATURE_ROWS
    sql = q.call_args.args[0]
    assert "license_feature_flags" in sql
    assert "tenant_feature_flags" in sql
    assert "tenant_licenses" in sql
    # Union filter: a flag appears when either layer references it.
    assert "lff.feature_flag_id IS NOT NULL OR tff.feature_flag_id IS NOT NULL" in sql
    assert q.call_args.args[1] == (_TENANT, _TENANT)


# ===========================================================================
# Route — payload shape and fallbacks
# ===========================================================================


def test_license_surface_returns_plan_seats_and_features():
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb)
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == {"name": "Paid", "type": "paid"}
    assert body["seats"] == {"used": 3, "max": 25}
    # Quotas reflect the stored seats keys (#64), not the Free defaults.
    assert body["quotas"] == {
        "max_projects": 10,
        "max_versions": 50,
        "max_ai_requests": 1000,
    }
    assert [(f["name"], f["enabled"], f["source"]) for f in body["features"]] == [
        ("designer", True, FEATURE_SOURCE_LICENSE),
        ("paths", False, FEATURE_SOURCE_TENANT_OVERRIDE),
        ("repositories", True, FEATURE_SOURCE_TENANT_OVERRIDE),
    ]
    rdb.count_member_seats_in_use.assert_called_once_with(_TENANT)
    rdb.list_tenant_effective_features.assert_called_once_with(_TENANT)


def test_unlicensed_tenant_reports_null_plan_and_free_default_seats():
    # Pre-V183 tenant: no license row. The surface must mirror the OLO-5.3
    # guard — Free-default seat limit, plan reported as null, no features.
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb, info=None, used=5, features=[])
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] is None
    assert body["seats"] == {"used": 5, "max": DEFAULT_FREE_MAX_USERS_PER_TENANT}
    assert body["features"] == []


def test_seat_max_matches_enforcement_helper_not_raw_json():
    # Malformed seats JSON: enforcement falls back to the Free default, so the
    # surface must report the same number (never the raw garbage value).
    info = {**_LICENSE_INFO, "seats": {"max_users_per_tenant": "lots"}}
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb, info=info)
    assert r.status_code == 200
    assert r.json()["seats"]["max"] == DEFAULT_FREE_MAX_USERS_PER_TENANT


# ===========================================================================
# Route — plan quotas (#64): projects / versions / AI limits
# ===========================================================================


def test_unlicensed_tenant_reports_free_default_quotas():
    # No license row: quotas fall back to the Free defaults, mirroring the
    # apiome-ui enforcement defaults (1 project / 3 versions / 0 AI).
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb, info=None, used=0, features=[])
    assert r.status_code == 200
    assert r.json()["quotas"] == {
        "max_projects": DEFAULT_FREE_MAX_PROJECTS,
        "max_versions": DEFAULT_FREE_MAX_VERSIONS,
        "max_ai_requests": DEFAULT_FREE_MAX_AI_REQUESTS,
    }


def test_negative_quota_is_reported_as_unlimited():
    # Sponsor tier stores -1 for unlimited; the surface passes it through as -1
    # (never the Free default), matching the apiome-ui unlimited convention.
    info = {
        **_LICENSE_INFO,
        "seats": {"max_users_per_tenant": 100, "max_projects": -1, "max_versions": -1, "max_ai_requests": -1},
    }
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb, info=info)
    assert r.status_code == 200
    assert r.json()["quotas"] == {"max_projects": -1, "max_versions": -1, "max_ai_requests": -1}


def test_partial_seats_fills_only_missing_quota_keys_with_defaults():
    # A license that sets max_projects but omits versions/AI reports the stored
    # value for the present key and Free defaults for the absent ones.
    info = {**_LICENSE_INFO, "seats": {"max_users_per_tenant": 25, "max_projects": 7}}
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _get_license(rdb, ldb, info=info)
    assert r.status_code == 200
    assert r.json()["quotas"] == {
        "max_projects": 7,
        "max_versions": DEFAULT_FREE_MAX_VERSIONS,
        "max_ai_requests": DEFAULT_FREE_MAX_AI_REQUESTS,
    }


# ===========================================================================
# Route — permission matrix (billing:view per the RBAC grid)
# ===========================================================================


def _matrix_call(rdb, ldb, *, granted):
    rdb.user_has_permission.return_value = granted
    rdb.get_tenant_license_info.return_value = _LICENSE_INFO
    rdb.count_member_seats_in_use.return_value = 1
    rdb.list_tenant_effective_features.return_value = []
    ldb.get_tenant_license_seats.return_value = _LICENSE_INFO["seats"]
    return client.get("/v1/tenants/acme/license")


def test_member_with_billing_view_reads_license():
    # Every built-in role (Owner/Admin/Editor/Viewer) holds billing:view.
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _matrix_call(rdb, ldb, granted=True)
    assert r.status_code == 200
    rdb.user_has_permission.assert_called_once_with(_TENANT, _USER, "billing", "view")


def test_role_stripped_of_billing_view_is_denied():
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        r = _matrix_call(rdb, ldb, granted=False)
    assert r.status_code == 403
    assert "billing:view" in r.json()["detail"]
    # The denial is recorded in the access-audit ledger.
    rdb.write_access_audit.assert_called_once()
    # No license data is computed for a denied caller.
    rdb.get_tenant_license_info.assert_not_called()


def test_api_key_with_fallback_creator_reads_license():
    # Legacy API key without an attributed user: the tenant's fallback creator
    # is resolved and the grid is consulted for that actor.
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": None,
        "auth_method": "api_key",
    }
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        rdb.get_fallback_creator_user_id_for_tenant.return_value = _USER
        r = _matrix_call(rdb, ldb, granted=True)
    assert r.status_code == 200
    rdb.user_has_permission.assert_called_once_with(_TENANT, _USER, "billing", "view")


def test_api_key_without_resolvable_actor_is_denied():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT,
        "user_id": None,
        "auth_method": "api_key",
    }
    with patch("app.license_routes.db") as rdb, patch("app.license_capacity.db") as ldb:
        rdb.get_fallback_creator_user_id_for_tenant.return_value = None
        r = _matrix_call(rdb, ldb, granted=True)
    assert r.status_code == 403
    rdb.user_has_permission.assert_not_called()
