"""Entitlement & feature gating for the Primitives type registry (#3478).

Two layers are exercised:

* ``Database.tenant_has_feature_flag`` — the precedence resolver
  (per-user override > per-tenant override > license default), honoring the flag's global
  master switch.
* The ``require_primitives_registry`` route gate — pass-through when the operator switch
  ``settings.primitives_registry_gating_enabled`` is off (default), and a 403 wall around the
  advanced Type Registry routes when it is on and the caller is not entitled. Baseline
  primitives CRUD is never gated.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.config import settings
from app.database import db as real_db
from app.main import app

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

_STATS = {
    "core_type_count": 36,
    "tenant_type_count": 12,
    "imported_count": 5,
    "properties_bound_count": 42,
    "bound_class_count": 8,
    "unresolved_ref_count": 3,
    "namespace_count": 4,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def _gating_on(monkeypatch):
    """Turn the operator gating switch on for the duration of a test."""
    monkeypatch.setattr(settings, "primitives_registry_gating_enabled", True)
    yield


# ===========================================================================
# Database.tenant_has_feature_flag — precedence resolver
# ===========================================================================


def _resolve(**row):
    """Run the helper with execute_query returning a single layered-entitlement row."""
    with patch.object(real_db, "execute_query") as q:
        q.return_value = [row]
        result = real_db.tenant_has_feature_flag("t1", "u1", "primitives-registry")
    return result, q


def test_user_override_takes_precedence_over_tenant_and_license():
    # User explicitly revoked — wins even though tenant + license would grant.
    result, _ = _resolve(
        flag_enabled=True, user_override=False, tenant_override=True, license_grant=True
    )
    assert result is False


def test_tenant_override_used_when_no_user_override():
    result, _ = _resolve(
        flag_enabled=True, user_override=None, tenant_override=True, license_grant=False
    )
    assert result is True


def test_license_default_used_when_no_overrides():
    result, _ = _resolve(
        flag_enabled=True, user_override=None, tenant_override=None, license_grant=True
    )
    assert result is True


def test_not_entitled_when_no_overrides_and_no_license_grant():
    result, _ = _resolve(
        flag_enabled=True, user_override=None, tenant_override=None, license_grant=False
    )
    assert result is False


def test_globally_disabled_flag_is_never_entitled():
    # Master switch off — overrides and license grants are irrelevant.
    result, _ = _resolve(
        flag_enabled=False, user_override=True, tenant_override=True, license_grant=True
    )
    assert result is False


def test_undefined_flag_returns_false():
    with patch.object(real_db, "execute_query") as q:
        q.return_value = []  # no such flag in the registry
        assert real_db.tenant_has_feature_flag("t1", "u1", "nope") is False


def test_resolver_binds_params_in_order():
    _, q = _resolve(
        flag_enabled=True, user_override=None, tenant_override=None, license_grant=True
    )
    # params: (flag_name, user_id, tenant_id, user_id)
    assert q.call_args.args[1] == ("primitives-registry", "u1", "t1", "u1")


# ===========================================================================
# Route gate — advanced Type Registry routes (e.g. GET /v1/types/{slug}/stats)
# ===========================================================================


def test_gating_disabled_allows_advanced_route_without_entitlement():
    # Default: operator switch off -> pass-through, entitlement never consulted.
    with patch("app.type_namespaces_routes.db") as mdb, patch("app.feature_gating.db") as gdb:
        mdb.get_registry_coverage_stats.return_value = _STATS
        r = client.get("/v1/types/acme/stats")
    assert r.status_code == 200
    gdb.tenant_has_feature_flag.assert_not_called()


def test_gating_enabled_entitled_tenant_allowed(_gating_on):
    with patch("app.type_namespaces_routes.db") as mdb, patch("app.feature_gating.db") as gdb:
        gdb.tenant_has_feature_flag.return_value = True
        mdb.get_registry_coverage_stats.return_value = _STATS
        r = client.get("/v1/types/acme/stats")
    assert r.status_code == 200
    gdb.tenant_has_feature_flag.assert_called_once_with("t1", "u1", "primitives-registry")


def test_gating_enabled_non_entitled_tenant_blocked(_gating_on):
    with patch("app.feature_gating.db") as gdb:
        gdb.tenant_has_feature_flag.return_value = False
        r = client.get("/v1/types/acme/stats")
    assert r.status_code == 403
    assert "primitives-registry" in r.json()["detail"]


def test_gating_enabled_blocks_primitives_import(_gating_on):
    # An advanced /v1/primitives route (import pipeline) is gated too.
    with patch("app.feature_gating.db") as gdb:
        gdb.tenant_has_feature_flag.return_value = False
        r = client.post(
            "/v1/primitives/acme/import",
            json={"schema": {"type": "string"}, "import_all": True, "target_namespace": "std/v0/types"},
        )
    assert r.status_code == 403


def test_gating_enabled_blocks_unresolved_refs(_gating_on):
    with patch("app.feature_gating.db") as gdb:
        gdb.tenant_has_feature_flag.return_value = False
        r = client.get("/v1/primitives/acme/unresolved")
    assert r.status_code == 403


# ===========================================================================
# Baseline primitives CRUD is never gated
# ===========================================================================


def test_baseline_list_open_even_when_gating_on_and_not_entitled(_gating_on):
    with patch("app.feature_gating.db") as gdb, patch("app.primitives_routes.db") as mdb:
        gdb.tenant_has_feature_flag.return_value = False
        mdb.get_primitives_for_tenant.return_value = []
        r = client.get("/v1/primitives/acme")
    assert r.status_code == 200
    # The baseline route does not consult the entitlement gate at all.
    gdb.tenant_has_feature_flag.assert_not_called()


def test_health_open_even_when_gating_on(_gating_on):
    with patch("app.feature_gating.db") as gdb, patch("app.primitives_routes.db") as mdb:
        gdb.tenant_has_feature_flag.return_value = False
        mdb.registry_ping.return_value = {"connection": "connected", "storage_present": True}
        r = client.get("/v1/primitives/health")
    # /health is ungated; status code is driven by the handler, never 403 from the gate.
    assert r.status_code != 403
    gdb.tenant_has_feature_flag.assert_not_called()
