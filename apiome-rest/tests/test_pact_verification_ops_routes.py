"""HTTP contract tests for the verification operations routes — PFX-5.5 (#6949).

The routes of :mod:`app.pact_verification_ops_routes` with the service faked:

* reads need ``pacts:view`` on the provider; a denial is a 403 before anything is read;
* the evidence run is asked for only when the caller also holds ``verification_evidence:view``;
* runs need ``pacts:create`` on the provider **and** ``verification_evidence:create``;
* the tenant comes from the credential, never the URL;
* each refusal maps to its status and code (404, 400, 409, 422);
* bodies are validated (unknown fields, a missing target → 422);
* the routes stay off the catalogued Pact Broker surface.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import BROKER_PREFIX
from app.pact_publication import PactPublicationError
from app.pact_verification_ops import (
    CODE_CURSOR_INVALID,
    CODE_IN_PROGRESS,
    CODE_NO_PROVIDER_VERSION,
    ConsoleRunResponse,
    ResultHistoryPage,
    StatusCounts,
    VerificationStatus,
)
from app.pact_verifier_service import PactVerifierError, VerifiedTarget
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource
from app.verification_result import CODE_VERIFICATION_NOT_FOUND
from app.verification_target import CODE_NOT_FOUND as TARGET_NOT_FOUND
from app.verification_target import TargetValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session", "user_email": "a@example.test"}
_ROUTES = "app.pact_verification_ops_routes"
_PROVIDER_URL = "/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api"
_RESULT_ID = "44444444-4444-4444-8444-444444444444"
_SHA = "a" * 64


def _status() -> VerificationStatus:
    return VerificationStatus(
        provider="ledger-api",
        provider_name="Ledger API",
        counts=StatusCounts(pacts=0, verified=0, failing=0, stale=0, interactions=0, passing_interactions=0),
    )


def _run(trigger: str = "manual") -> ConsoleRunResponse:
    return ConsoleRunResponse(
        provider="ledger-api",
        provider_version="4f1e2d0",
        target=VerifiedTarget(
            target_id="22222222-2222-4222-8222-222222222222",
            slug="ledger-staging",
            environment="staging",
            base_url="https://ledger.staging.example.test",
            allow_mutating_methods=False,
        ),
        success=True,
        outcome="passed",
        pacts=[],
        trigger=trigger,
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


def _deny(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Permission denied")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_the_status_needs_pacts_view_on_the_provider_and_uses_the_credentials_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.verification_status", return_value=_status()) as status:
        answer = client.get(f"{_PROVIDER_URL}/verification-status")
    assert answer.status_code == 200 and answer.json()["provider"] == "ledger-api"
    assert allowed.call_args.args[2:] == (Resource.PACTS, Action.VIEW)
    assert allowed.call_args.kwargs == {"target": "ledger-api"}
    assert status.call_args.args[1:] == (_TENANT, "ledger-api")


@pytest.mark.parametrize(
    "path",
    ["/verification-status", "/results", f"/results/{_RESULT_ID}"],
)
def test_reads_without_pacts_view_are_403_before_anything_is_read(path: str) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.verification_status") as status,
        patch(f"{_ROUTES}.list_results") as listed,
        patch(f"{_ROUTES}.read_result") as read,
    ):
        answer = client.get(f"{_PROVIDER_URL}{path}")
    assert answer.status_code == 403
    assert not status.called and not listed.called and not read.called


def test_an_unknown_provider_is_404(allowed: MagicMock) -> None:
    error = PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant 'ledger-api'")
    with patch(f"{_ROUTES}.verification_status", side_effect=error):
        answer = client.get(f"{_PROVIDER_URL}/verification-status")
    assert answer.status_code == 404 and answer.json()["detail"]["code"] == CODE_NOT_FOUND


def test_the_history_forwards_consumer_cursor_and_limit(allowed: MagicMock) -> None:
    page = ResultHistoryPage(provider="ledger-api", provider_name="Ledger API", consumer="billing-service")
    with patch(f"{_ROUTES}.list_results", return_value=page) as listed:
        answer = client.get(
            f"{_PROVIDER_URL}/results", params={"consumer": "billing-service", "cursor": "9", "limit": 5}
        )
    assert answer.status_code == 200 and answer.json()["consumer"] == "billing-service"
    assert listed.call_args.args[1:] == (_TENANT, "ledger-api")
    assert listed.call_args.kwargs == {"consumer_ref": "billing-service", "cursor": "9", "limit": 5}


def test_a_bad_cursor_is_400(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_results", side_effect=PactPublicationError(CODE_CURSOR_INVALID, "bad cursor")):
        answer = client.get(f"{_PROVIDER_URL}/results", params={"cursor": "x"})
    assert answer.status_code == 400 and answer.json()["detail"]["code"] == CODE_CURSOR_INVALID


@pytest.mark.parametrize("limit", [0, 51])
def test_a_page_size_out_of_range_is_422(allowed: MagicMock, limit: int) -> None:
    assert client.get(f"{_PROVIDER_URL}/results", params={"limit": limit}).status_code == 422


@pytest.mark.parametrize("evidence_view", [True, False])
def test_one_result_asks_for_evidence_only_with_evidence_view(allowed: MagicMock, evidence_view: bool) -> None:
    with (
        patch(f"{_ROUTES}.has_permission", return_value=evidence_view) as has,
        patch(f"{_ROUTES}.read_result", side_effect=PactPublicationError(CODE_VERIFICATION_NOT_FOUND, "x")) as read,
    ):
        answer = client.get(f"{_PROVIDER_URL}/results/{_RESULT_ID}")
    assert answer.status_code == 404
    assert has.call_args.args[2:] == (Resource.VERIFICATION_EVIDENCE, Action.VIEW)
    assert read.call_args.args[1:] == (_TENANT, "ledger-api", _RESULT_ID)
    assert read.call_args.kwargs == {"include_evidence": evidence_view}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

_REVERIFY = f"{_PROVIDER_URL}/consumer/billing-service/pact-version/{_SHA}/reverify"
_STALE = f"{_PROVIDER_URL}/verify-stale"


def test_a_rerun_needs_pacts_create_and_evidence_create(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.reverify_pact", return_value=_run()) as rerun:
        answer = client.post(_REVERIFY, json={"target_ref": "ledger-staging"})
    assert answer.status_code == 200 and answer.json()["trigger"] == "manual"
    checks = [call.args[2:] for call in allowed.call_args_list]
    assert checks == [(Resource.PACTS, Action.CREATE), (Resource.VERIFICATION_EVIDENCE, Action.CREATE)]
    assert allowed.call_args_list[0].kwargs == {"target": "ledger-api"}
    args, kwargs = rerun.call_args
    assert args[1:5] == (_TENANT, "ledger-api", "billing-service", _SHA)
    assert args[5].target_ref == "ledger-staging" and args[5].provider_version is None
    assert kwargs["broker_base"].endswith("/v1/tenants/acme/pact-broker")
    assert kwargs["actor"].user_id == "test-user-id"


@pytest.mark.parametrize("url", [_REVERIFY, _STALE])
def test_runs_without_create_are_403_before_anything_runs(url: str) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_deny),
        patch(f"{_ROUTES}.reverify_pact") as rerun,
        patch(f"{_ROUTES}.verify_stale_pacts") as stale,
    ):
        answer = client.post(url, json={"target_ref": "ledger-staging", "provider_version": "1"})
    assert answer.status_code == 403 and not rerun.called and not stale.called


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (PactPublicationError("pact-not-found", "no pact"), 404, "pact-not-found"),
        (TargetValidationError(TARGET_NOT_FOUND, "no target"), 404, TARGET_NOT_FOUND),
        (TargetValidationError("target-disabled", "disabled"), 422, "target-disabled"),
    ],
)
def test_a_rerun_refusal_maps_to_its_status(allowed: MagicMock, error: Exception, status: int, code: str) -> None:
    with patch(f"{_ROUTES}.reverify_pact", side_effect=error):
        answer = client.post(_REVERIFY, json={"target_ref": "ledger-staging"})
    assert answer.status_code == status and answer.json()["detail"]["code"] == code


def test_a_rerun_of_a_running_pair_is_409(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.reverify_pact", side_effect=PactVerifierError(CODE_IN_PROGRESS, "already running")):
        answer = client.post(_REVERIFY, json={"target_ref": "ledger-staging"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == CODE_IN_PROGRESS


def test_verify_stale_without_a_version_is_422(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.verify_stale_pacts", side_effect=PactVerifierError(CODE_NO_PROVIDER_VERSION, "give it")):
        answer = client.post(_STALE, json={"target_ref": "ledger-staging"})
    assert answer.status_code == 422 and answer.json()["detail"]["code"] == CODE_NO_PROVIDER_VERSION


def test_verify_stale_runs_for_the_credentials_tenant(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.verify_stale_pacts", return_value=_run("stale-recheck")) as stale:
        answer = client.post(_STALE, json={"target_ref": "ledger-staging", "provider_version": "4f1e2d0"})
    assert answer.status_code == 200 and answer.json()["trigger"] == "stale-recheck"
    assert stale.call_args.args[1:3] == (_TENANT, "ledger-api")


@pytest.mark.parametrize(
    "body",
    [{}, {"target_ref": ""}, {"target_ref": "t", "publish": False}, {"target_ref": "t", "selection": {}}],
)
def test_a_malformed_body_is_422(allowed: MagicMock, body: Dict[str, Any]) -> None:
    with patch(f"{_ROUTES}.verify_stale_pacts") as stale:
        assert client.post(_STALE, json=body).status_code == 422
    assert not stale.called


def test_the_routes_stay_off_the_catalogued_broker_surface() -> None:
    paths = [
        getattr(route, "path", "")
        for route in app.routes
        if "pact-verifier/pacts/provider/{provider}/" in getattr(route, "path", "")
    ]
    assert len(paths) == 6  # verify (PFX-3.2) and the five PFX-5.5 routes
    assert not any(BROKER_PREFIX in path for path in paths)
