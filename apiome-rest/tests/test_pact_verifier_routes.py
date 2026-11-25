"""HTTP contract tests for ``POST …/pact-verifier/pacts/provider/{provider}/verify`` — PFX-3.2 (#6932).

The route of :mod:`app.pact_verifier_routes` with the service faked:

* it needs ``pacts:create`` on the provider **and** ``verification_evidence:create``; a denial is a
  403 before anything runs;
* the tenant comes from the credential, never the URL; a workspace API key works as a bearer token;
* a run that happened is a 200 whatever it found;
* each way a run cannot start maps to its status and code;
* the body is validated (unknown fields, missing target or provider version → 422);
* the route stays off the catalogued Pact Broker surface.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import BROKER_PREFIX
from app.pact_publication import PactPublicationError
from app.pact_selectors import CODE_SELECTOR_INVALID
from app.pact_verifier_service import (
    CODE_TARGET_AUTH_UNAVAILABLE,
    CODE_TOO_MANY_PACTS,
    PactVerifierError,
    PactVerifyResponse,
    VerifiedTarget,
)
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource
from app.verification_target import CODE_NOT_FOUND as TARGET_NOT_FOUND
from app.verification_target import TargetValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {
    "tenant_id": _TENANT,
    "user_id": "test-user-id",
    "auth_method": "api_key",
    "user_email": "ci@example.test",
}
_ROUTES = "app.pact_verifier_routes"
_URL = "/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/verify"
_BODY: Dict[str, Any] = {"target_ref": "ledger-staging", "provider_version": "4f1e2d0"}


def _response(outcome: str = "passed") -> PactVerifyResponse:
    return PactVerifyResponse(
        provider="ledger-api",
        provider_version="4f1e2d0",
        target=VerifiedTarget(
            target_id="22222222-2222-4222-8222-222222222222",
            slug="ledger-staging",
            environment="staging",
            base_url="https://ledger.staging.example.test",
            allow_mutating_methods=False,
        ),
        success=outcome == "passed",
        outcome=outcome,
        pacts=[],
    )


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


@pytest.fixture
def service() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.verify_provider_pacts", return_value=_response()) as verify:
        yield verify


def test_a_run_is_a_200_scoped_to_the_credentials_tenant(allowed: MagicMock, service: MagicMock) -> None:
    body = {
        **_BODY,
        "provider_branch": "main",
        "selection": {"consumerVersionSelectors": [{"mainBranch": True}], "includePendingStatus": True},
        "verification": {"allow_mutating": True, "replay_without_state_setup": True},
        "publish": False,
    }
    answer = client.post(_URL, json=body)
    assert answer.status_code == 200
    assert answer.json()["outcome"] == "passed" and answer.json()["success"] is True

    args, kwargs = service.call_args
    assert args[1:3] == (_TENANT, "ledger-api")
    request = args[3]
    assert (request.target_ref, request.provider_version, request.provider_branch) == (
        "ledger-staging",
        "4f1e2d0",
        "main",
    )
    assert request.publish is False and request.verification.allow_mutating is True
    assert request.selection["includePendingStatus"] is True
    assert kwargs["broker_base"].endswith("/v1/tenants/acme/pact-broker")
    assert (kwargs["actor"].user_id, kwargs["actor"].kind, kwargs["actor"].label) == (
        "test-user-id",
        "api_key",
        "ci@example.test",
    )


def test_both_permissions_are_enforced_in_order(allowed: MagicMock, service: MagicMock) -> None:
    client.post(_URL, json=_BODY)
    checks: List[Any] = [(call.args[2], call.args[3], call.kwargs.get("target")) for call in allowed.call_args_list]
    assert checks == [
        (Resource.PACTS, Action.CREATE, "ledger-api"),
        (Resource.VERIFICATION_EVIDENCE, Action.CREATE, None),
    ]


@pytest.mark.parametrize("denied", [Resource.PACTS, Resource.VERIFICATION_EVIDENCE])
def test_a_missing_permission_is_a_403_before_anything_runs(denied: Resource, service: MagicMock) -> None:
    def enforce(_db: Any, _auth: Any, resource: Resource, _action: Action, **_kwargs: Any) -> str:
        if resource is denied:
            raise HTTPException(status_code=403, detail="Permission denied")
        return "test-user-id"

    with patch(f"{_ROUTES}.enforce_permission", side_effect=enforce):
        answer = client.post(_URL, json=_BODY)
    assert answer.status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("outcome", ["failed", "incomplete", "no-pacts"])
def test_a_run_that_happened_is_a_200_whatever_it_found(allowed: MagicMock, outcome: str) -> None:
    with patch(f"{_ROUTES}.verify_provider_pacts", return_value=_response(outcome)):
        answer = client.post(_URL, json=_BODY)
    assert answer.status_code == 200
    assert (answer.json()["success"], answer.json()["outcome"]) == (False, outcome)


@pytest.mark.parametrize(
    "error, status, code",
    [
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'ledger-api'"), 404, CODE_NOT_FOUND),
        (
            PactPublicationError(CODE_SELECTOR_INVALID, "bad selector", pointer="/consumerVersionSelectors/0"),
            400,
            CODE_SELECTOR_INVALID,
        ),
        (PacticipantValidationError("pacticipant-invalid-version", "bad version"), 400, "pacticipant-invalid-version"),
        (TargetValidationError(TARGET_NOT_FOUND, "no target"), 404, TARGET_NOT_FOUND),
        (TargetValidationError("target-disabled", "the target is disabled"), 422, "target-disabled"),
        (PactVerifierError(CODE_TOO_MANY_PACTS, "too many"), 422, CODE_TOO_MANY_PACTS),
        (PactVerifierError(CODE_TARGET_AUTH_UNAVAILABLE, "variable unset"), 422, CODE_TARGET_AUTH_UNAVAILABLE),
    ],
)
def test_a_run_that_cannot_start_maps_to_its_status_and_code(
    allowed: MagicMock, error: Exception, status: int, code: str
) -> None:
    with patch(f"{_ROUTES}.verify_provider_pacts", side_effect=error):
        answer = client.post(_URL, json=_BODY)
    assert answer.status_code == status
    assert answer.json()["detail"]["code"] == code
    assert answer.json()["detail"]["message"]


def test_a_selector_refusal_keeps_its_pointer(allowed: MagicMock) -> None:
    error = PactPublicationError(CODE_SELECTOR_INVALID, "bad selector", pointer="/consumerVersionSelectors/0")
    with patch(f"{_ROUTES}.verify_provider_pacts", side_effect=error):
        answer = client.post(_URL, json=_BODY)
    assert answer.json()["detail"]["pointer"] == "/consumerVersionSelectors/0"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"target_ref": "ledger-staging"},
        {"provider_version": "1"},
        {**_BODY, "unknown": True},
        {**_BODY, "verification": {"allow_mutating": "perhaps"}},
        {**_BODY, "verification": {"widen_policy": True}},
        {
            **_BODY,
            "verification": {"fixtures": [{"operation_key": "POST /x", "headers": {"Authorization": "Bearer t"}}]},
        },
    ],
)
def test_a_malformed_body_is_a_422(allowed: MagicMock, service: MagicMock, body: Dict[str, Any]) -> None:
    assert client.post(_URL, json=body).status_code == 422
    service.assert_not_called()


def test_a_credential_without_a_tenant_is_refused(allowed: MagicMock, service: MagicMock) -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": "u"}
    assert client.post(_URL, json=_BODY).status_code == 403
    service.assert_not_called()


def test_the_route_is_documented_and_stays_off_the_broker_surface() -> None:
    paths = app.openapi()["paths"]
    path = "/v1/tenants/{tenant_slug}/pact-verifier/pacts/provider/{provider}/verify"
    operation = paths[path]["post"]
    assert operation["tags"] == ["pact-broker"]
    assert {"200", "400", "404", "422"} <= set(operation["responses"])
    assert not path.startswith(BROKER_PREFIX)
