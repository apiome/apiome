"""HTTP contract tests for the live verification run routes — PFX-8.9 (#7306).

The routes of :mod:`app.pact_verifier_routes` with the registry faked:

* starting a run is a ``202`` with the run as it starts, behind ``pacts:create`` **and**
  ``verification_evidence:create``; every way it cannot start keeps the status ``…/verify`` uses;
* reading a run needs ``pacts:view``; stopping one ``pacts:create``; re-running an interaction
  both permissions — each a ``403`` before anything happens;
* the tenant comes from the credential: a run of another workspace is a ``404`` and its provider
  is never checked or named;
* the registry's own refusals (limit, busy, unknown pact) keep their status and code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_verifier import InteractionVerification
from app.pact_verifier_service import CODE_MUTATING_PRODUCTION, PactVerifierError
from app.pact_verify_runs import (
    CODE_RUN_BUSY,
    CODE_RUN_LIMIT,
    CODE_RUN_NOT_FOUND,
    LiveRunError,
    LiveRunSnapshot,
    RerunResponse,
)
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt", "user_email": "dev@example.test"}
_ROUTES = "app.pact_verifier_routes"
_START = "/v1/tenants/acme/pact-verifier/pacts/provider/ledger-api/verify/runs"
_RUN = "/v1/tenants/acme/pact-verifier/runs/run-1"
_BODY: Dict[str, Any] = {"target_ref": "ledger-staging", "provider_version": "4f1e2d0"}


def _snapshot(**fields: Any) -> LiveRunSnapshot:
    base: Dict[str, Any] = {
        "run_id": "run-1",
        "provider": "ledger-api",
        "provider_name": "Ledger API",
        "provider_version": "4f1e2d0",
        "target": "ledger-staging",
        "target_base_url": "https://ledger.staging.example.test",
        "environment": "staging",
        "status": "running",
        "stop_requested": False,
        "started_at": datetime(2026, 11, 27, 14, 2, 11, tzinfo=timezone.utc),
        "interactions": 0,
        "done": 0,
        "log_next": 0,
    }
    base.update(fields)
    return LiveRunSnapshot(**base)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


@pytest.fixture
def registry() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.live_runs") as runs:
        runs.provider_of.return_value = "ledger-api"
        runs.start.return_value = _snapshot()
        runs.snapshot.return_value = _snapshot(status="finished")
        runs.stop.return_value = _snapshot(stop_requested=True)
        yield runs


def test_starting_a_run_is_a_202_scoped_to_the_credentials_tenant(allowed: MagicMock, registry: MagicMock) -> None:
    answer = client.post(_START, json=_BODY)
    assert answer.status_code == 202, answer.text
    assert answer.json()["run_id"] == "run-1" and answer.json()["status"] == "running"
    args, kwargs = registry.start.call_args
    assert args[1:3] == (_TENANT, "ledger-api")
    assert args[3].target_ref == "ledger-staging" and kwargs["broker_base"].endswith("/v1/tenants/acme/pact-broker")
    asked = [(c.args[2], c.args[3]) for c in allowed.call_args_list]
    assert asked == [(Resource.PACTS, Action.CREATE), (Resource.VERIFICATION_EVIDENCE, Action.CREATE)]


@pytest.mark.parametrize(
    "error,status,code",
    [
        (PactVerifierError(CODE_MUTATING_PRODUCTION, "never production"), 422, CODE_MUTATING_PRODUCTION),
        (LiveRunError(CODE_RUN_LIMIT, "three already", 429), 429, CODE_RUN_LIMIT),
    ],
)
def test_a_run_that_cannot_start_keeps_its_status_and_code(
    allowed: MagicMock, registry: MagicMock, error: Exception, status: int, code: str
) -> None:
    registry.start.side_effect = error
    answer = client.post(_START, json=_BODY)
    assert answer.status_code == status
    assert answer.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    "method,url,body,needs",
    [
        ("POST", _START, _BODY, (Resource.PACTS, Action.CREATE)),
        ("GET", _RUN, None, (Resource.PACTS, Action.VIEW)),
        ("POST", f"{_RUN}/stop", None, (Resource.PACTS, Action.CREATE)),
        ("POST", f"{_RUN}/rerun", {"pact_version_sha": "a" * 64, "case_id": "c"}, (Resource.PACTS, Action.CREATE)),
        (
            "POST",
            f"{_RUN}/rerun",
            {"pact_version_sha": "a" * 64, "case_id": "c"},
            (Resource.VERIFICATION_EVIDENCE, Action.CREATE),
        ),
    ],
)
def test_a_missing_permission_is_a_403_before_anything_happens(
    registry: MagicMock, method: str, url: str, body: Any, needs: tuple
) -> None:
    def enforce(_db: Any, _auth: Any, resource: Resource, action: Action, **_k: Any) -> str:
        if (resource, action) == needs:
            raise HTTPException(status_code=403, detail="Permission denied")
        return "test-user-id"

    with patch(f"{_ROUTES}.enforce_permission", side_effect=enforce):
        answer = client.request(method, url, json=body)
    assert answer.status_code == 403
    registry.start.assert_not_called()
    registry.stop.assert_not_called()
    registry.rerun_interaction.assert_not_called()
    registry.snapshot.assert_not_called()


def test_reading_a_run_passes_the_log_cursor(allowed: MagicMock, registry: MagicMock) -> None:
    answer = client.get(_RUN, params={"log_after": 7})
    assert answer.status_code == 200 and answer.json()["status"] == "finished"
    registry.snapshot.assert_called_once_with(_TENANT, "run-1", 7)
    assert allowed.call_args.kwargs["target"] == "ledger-api"


def test_a_negative_log_cursor_is_refused(allowed: MagicMock, registry: MagicMock) -> None:
    assert client.get(_RUN, params={"log_after": -1}).status_code == 422


def test_another_workspaces_run_is_a_404_and_no_permission_is_asked(allowed: MagicMock, registry: MagicMock) -> None:
    registry.provider_of.side_effect = LiveRunError(CODE_RUN_NOT_FOUND, "no such run", 404)
    for method, url, body in (
        ("GET", _RUN, None),
        ("POST", f"{_RUN}/stop", None),
        ("POST", f"{_RUN}/rerun", {"pact_version_sha": "a", "case_id": "c"}),
    ):
        answer = client.request(method, url, json=body)
        assert answer.status_code == 404 and answer.json()["detail"]["code"] == CODE_RUN_NOT_FOUND
    registry.provider_of.assert_called_with(_TENANT, "run-1")
    allowed.assert_not_called()


def test_stopping_answers_the_run_as_it_stands(allowed: MagicMock, registry: MagicMock) -> None:
    answer = client.post(f"{_RUN}/stop")
    assert answer.status_code == 200 and answer.json()["stop_requested"] is True
    registry.stop.assert_called_once_with(_TENANT, "run-1")


def test_a_re_run_answers_the_interaction_and_says_nothing_was_published(
    allowed: MagicMock, registry: MagicMock
) -> None:
    registry.rerun_interaction.return_value = RerunResponse(
        run_id="run-1",
        pact_version_sha="a" * 64,
        interaction=InteractionVerification(
            case_id="c", description="d", pointer="/interactions/0", operation="GET /invoices/1", outcome="passed"
        ),
    )
    answer = client.post(f"{_RUN}/rerun", json={"pact_version_sha": "a" * 64, "case_id": "c"})
    assert answer.status_code == 200
    assert answer.json()["published"] is False and answer.json()["interaction"]["outcome"] == "passed"
    args = registry.rerun_interaction.call_args.args
    assert args[1:3] == (_TENANT, "run-1") and args[3].case_id == "c"


def test_a_re_run_while_the_run_is_going_is_a_409(allowed: MagicMock, registry: MagicMock) -> None:
    registry.rerun_interaction.side_effect = LiveRunError(CODE_RUN_BUSY, "still going", 409)
    answer = client.post(f"{_RUN}/rerun", json={"pact_version_sha": "a", "case_id": "c"})
    assert answer.status_code == 409 and answer.json()["detail"]["code"] == CODE_RUN_BUSY


def test_a_re_run_body_is_strict(allowed: MagicMock, registry: MagicMock) -> None:
    answer = client.post(f"{_RUN}/rerun", json={"pact_version_sha": "a", "case_id": "c", "publish": True})
    assert answer.status_code == 422
    registry.rerun_interaction.assert_not_called()
