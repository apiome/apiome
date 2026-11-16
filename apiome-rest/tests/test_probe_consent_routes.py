"""HTTP contract for probe consent and security probe report routes — ASP-4.1 (#5939).

The store is faked (its own tests cover it). Asserted here:

* granting and revoking need ``verification_evidence:create`` and reading needs
  ``verification_evidence:view``;
* a production target's consent needs a signed-in tenant administrator — an API key or a
  non-administrator is refused before anything is stored;
* refusals carry their stable code with the matching status (404 unknown target / no consent /
  no report, 400 invalid grant, 422 a body the model rejects such as a pasted token);
* the report list and read return what the store returns.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.probe_consent_store import (
    CODE_CONSENT_NOT_FOUND,
    CODE_REPORT_NOT_FOUND,
    ProbeConsentRecord,
    ProbeConsentStoreError,
    SecurityProbeReportRecord,
    SecurityProbeReportSummary,
)
from app.verification_target import (
    CODE_NOT_FOUND,
    TargetAuthReference,
    TargetValidationError,
    VerificationPolicy,
    VerificationTargetRecord,
)

client = TestClient(app)

_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_TARGET = "22222222-2222-4222-8222-222222222222"
_CONSENT_URL = "/v1/tenants/acme/verification-targets/staging/probe-consent"
_REPORTS_URL = "/v1/tenants/acme/security-probe-reports"
_NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
_MODULE = "app.probe_consent_routes"


def _target(environment: str = "staging") -> VerificationTargetRecord:
    return VerificationTargetRecord(
        id=_TARGET,
        tenant_id="test-tenant-id",
        slug="staging",
        name="Staging",
        environment=environment,
        base_url="https://staging.example.com/api",
        network_class="public",
        auth=TargetAuthReference(),
        policy=VerificationPolicy(),
        enabled=True,
    )


def _consent(**overrides: Any) -> ProbeConsentRecord:
    payload: Dict[str, Any] = dict(
        id="44444444-4444-4444-8444-444444444444",
        tenant_id="test-tenant-id",
        target_id=_TARGET,
        ownership_declared=True,
        approved_by="test-user-id",
        approved_at=_NOW,
        expires_at=_NOW + timedelta(days=7),
        profiles_allowed=["passive"],
        status="active",
    )
    payload.update(overrides)
    return ProbeConsentRecord(**payload)


def _grant_body(**overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "ownership_declared": True,
        "expires_at": "2099-01-01T00:00:00Z",
        "profiles_allowed": ["passive", "safe-active"],
        "identity_a": {"kind": "env", "scheme": "bearer", "ref": "PROBE_TOKEN_A"},
    }
    body.update(overrides)
    return body


def _report(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = dict(
        id="55555555-5555-4555-8555-555555555555",
        tenant_id="test-tenant-id",
        target_id=_TARGET,
        target_slug="mock",
        target_environment="mock",
        target_base_url="http://localhost:8775",
        profile="passive",
        hosted_mock=True,
        explicit_approval=False,
        proof_ceiling="observed",
        count_suspected=0,
        count_observed=2,
        count_exploited_in_test=0,
    )
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_AUTH)
    with patch(f"{_MODULE}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce
    app.dependency_overrides.clear()


# ===========================================================================
# Grant
# ===========================================================================


def test_granting_consent_returns_201_and_checks_the_create_permission(_auth) -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.grant_consent", return_value=_consent()
    ) as grant:
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 201
    assert response.json()["status"] == "active"
    assert _auth.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.CREATE)
    tenant_id, target, body = grant.call_args.args
    assert tenant_id == "test-tenant-id" and target.id == _TARGET
    assert body.identity_a.ref == "PROBE_TOKEN_A"
    assert grant.call_args.kwargs["actor"].user_id == "test-user-id"


def test_a_pasted_token_identity_is_rejected_before_the_store() -> None:
    body = _grant_body(identity_a={"kind": "env", "scheme": "bearer", "ref": "eyJhbGc.eyJzdWI.sig"})
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.grant_consent"
    ) as grant:
        response = client.post(_CONSENT_URL, json=body)
    assert response.status_code == 422
    grant.assert_not_called()


def test_a_grant_without_an_ownership_declaration_is_rejected() -> None:
    with patch(f"{_MODULE}.grant_consent") as grant:
        response = client.post(_CONSENT_URL, json=_grant_body(ownership_declared=False))
    assert response.status_code == 422
    grant.assert_not_called()


def test_a_grant_without_an_expiry_is_rejected() -> None:
    body = _grant_body()
    body.pop("expires_at")
    response = client.post(_CONSENT_URL, json=body)
    assert response.status_code == 422


def test_an_invalid_grant_is_a_400_with_its_code() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.grant_consent",
        side_effect=ProbeConsentStoreError("probe-consent-invalid", "expires_at must be in the future"),
    ):
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "probe-consent-invalid"


def test_granting_for_an_unknown_target_is_a_404() -> None:
    with patch(
        f"{_MODULE}.get_target", side_effect=TargetValidationError(CODE_NOT_FOUND, "no such target")
    ):
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_a_production_consent_needs_a_tenant_administrator() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target("production")), patch(
        f"{_MODULE}.require_tenant_admin_session",
        side_effect=HTTPException(status_code=403, detail="admins only"),
    ) as admin, patch(f"{_MODULE}.grant_consent") as grant:
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 403
    admin.assert_called_once()
    grant.assert_not_called()


def test_a_production_consent_by_an_administrator_is_granted() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target("production")), patch(
        f"{_MODULE}.require_tenant_admin_session", return_value="test-tenant-id"
    ), patch(f"{_MODULE}.grant_consent", return_value=_consent()):
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 201


def test_an_api_key_cannot_grant_production_consent() -> None:
    """The real admin check (not patched) refuses an API key outright."""
    app.dependency_overrides[validate_authentication] = lambda: {
        **_AUTH,
        "auth_method": "api_key",
    }
    with patch(f"{_MODULE}.get_target", return_value=_target("production")), patch(
        f"{_MODULE}.grant_consent"
    ) as grant:
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 403
    grant.assert_not_called()


def test_a_non_production_consent_skips_the_administrator_check() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target("staging")), patch(
        f"{_MODULE}.require_tenant_admin_session"
    ) as admin, patch(f"{_MODULE}.grant_consent", return_value=_consent()):
        client.post(_CONSENT_URL, json=_grant_body())
    admin.assert_not_called()


def test_a_denied_permission_is_a_403(_auth) -> None:
    _auth.side_effect = HTTPException(status_code=403, detail="no")
    with patch(f"{_MODULE}.grant_consent") as grant:
        response = client.post(_CONSENT_URL, json=_grant_body())
    assert response.status_code == 403
    grant.assert_not_called()


# ===========================================================================
# Read / revoke
# ===========================================================================


def test_reading_consent_needs_view(_auth) -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.get_live_consent", return_value=_consent(status="expired")
    ):
        response = client.get(_CONSENT_URL)
    assert response.status_code == 200
    assert response.json()["status"] == "expired"
    assert _auth.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.VIEW)


def test_reading_a_target_without_consent_is_a_404() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.get_live_consent", return_value=None
    ):
        response = client.get(_CONSENT_URL)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_CONSENT_NOT_FOUND


def test_revoking_needs_create_and_returns_the_revoked_consent(_auth) -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.revoke_consent", return_value=_consent(status="revoked", revoked_at=_NOW)
    ):
        response = client.delete(_CONSENT_URL)
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert _auth.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.CREATE)


def test_revoking_nothing_is_a_404() -> None:
    with patch(f"{_MODULE}.get_target", return_value=_target()), patch(
        f"{_MODULE}.revoke_consent",
        side_effect=ProbeConsentStoreError(CODE_CONSENT_NOT_FOUND, "nothing to revoke"),
    ):
        response = client.delete(_CONSENT_URL)
    assert response.status_code == 404


# ===========================================================================
# Reports
# ===========================================================================


def test_listing_reports_needs_view_and_passes_filters(_auth) -> None:
    with patch(
        f"{_MODULE}.list_reports", return_value=[SecurityProbeReportSummary(**_report())]
    ) as listing:
        response = client.get(_REPORTS_URL, params={"target_id": _TARGET, "limit": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["reports"][0]["proof_ceiling"] == "observed"
    assert listing.call_args.kwargs == {"target_id": _TARGET, "limit": 5}
    assert _auth.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.VIEW)


def test_the_list_limit_is_bounded() -> None:
    response = client.get(_REPORTS_URL, params={"limit": 5000})
    assert response.status_code == 422


def test_reading_a_report_returns_its_body() -> None:
    record = SecurityProbeReportRecord(**_report(), report={"ceiling_reason": "hosted mock"})
    with patch(f"{_MODULE}.get_report", return_value=record):
        response = client.get(f"{_REPORTS_URL}/{record.id}")
    assert response.status_code == 200
    assert response.json()["report"] == {"ceiling_reason": "hosted mock"}


def test_reading_a_missing_report_is_a_404() -> None:
    with patch(
        f"{_MODULE}.get_report",
        side_effect=ProbeConsentStoreError(CODE_REPORT_NOT_FOUND, "not found"),
    ):
        response = client.get(f"{_REPORTS_URL}/nope")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_REPORT_NOT_FOUND
