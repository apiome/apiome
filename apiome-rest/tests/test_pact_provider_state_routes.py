"""HTTP contract tests for ``…/pact-verifier/providers/{provider}/provider-states`` — PFX-3.3 (#6933).

The routes of :mod:`app.pact_provider_state_routes` with the service faked:

* each route enforces its ``pacts`` action on the provider (view / create / edit / delete) and a
  denial is a 403 before anything runs;
* the tenant comes from the credential, never the URL;
* each refusal maps to its status and code, keeping its pointer;
* bodies are validated (unknown fields, unknown setup kinds → 422);
* the routes are documented and stay off the catalogued Pact Broker surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import BROKER_PREFIX
from app.pact_provider_state import (
    CODE_STATE_INVALID,
    CODE_STATE_NAME_TAKEN,
    CODE_STATE_NOT_FOUND,
    ProviderStateRecord,
    StateSetup,
)
from app.pact_provider_state_service import StateCheckResponse
from app.pact_publication import PactPublicationError
from app.pact_selectors import CODE_SELECTOR_INVALID
from app.pact_verifier_service import CODE_TOO_MANY_PACTS, PactVerifierError
from app.pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from app.permissions import Action, Resource
from app.verification_target import CODE_NOT_FOUND as TARGET_NOT_FOUND
from app.verification_target import TargetValidationError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key", "user_email": "ci@example.test"}
_ROUTES = "app.pact_provider_state_routes"
_BASE = "/v1/tenants/acme/pact-verifier/providers/ledger-api/provider-states"
_STATE_ID = "33333333-3333-4333-8333-333333333333"
_NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
_BODY: Dict[str, Any] = {"name": "invoice 1042 exists", "setup": {"kind": "state_change", "url": "/_pact/states"}}
_RECORD = ProviderStateRecord(
    id=_STATE_ID,
    provider="ledger-api",
    name="invoice 1042 exists",
    setup=StateSetup(kind="state_change", url="/_pact/states"),
    created_at=_NOW,
    updated_at=_NOW,
)
_CHECK = StateCheckResponse(provider="ledger-api", ready=True, pacts=0, blocking=0, warnings=0)

#: (method, path, body, service function, its answer, the action enforced, expected status)
_CALLS = [
    ("get", _BASE, None, "list_provider_states", [_RECORD], Action.VIEW, 200),
    ("post", _BASE, _BODY, "register_provider_state", _RECORD, Action.CREATE, 201),
    ("post", f"{_BASE}/check", {"target_ref": "ledger-staging"}, "check_provider_states", _CHECK, Action.VIEW, 200),
    ("get", f"{_BASE}/{_STATE_ID}", None, "read_provider_state", _RECORD, Action.VIEW, 200),
    ("put", f"{_BASE}/{_STATE_ID}", _BODY, "replace_provider_state", _RECORD, Action.EDIT, 200),
    ("delete", f"{_BASE}/{_STATE_ID}", None, "remove_provider_state", None, Action.DELETE, 204),
]


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _send(method: str, path: str, body: Any) -> Any:
    call: Callable[..., Any] = getattr(client, method)
    return call(path, json=body) if body is not None else call(path)


@pytest.mark.parametrize(("method", "path", "body", "function", "answer", "action", "status"), _CALLS)
def test_each_route_enforces_its_action_and_scopes_to_the_credential(
    method: str, path: str, body: Any, function: str, answer: Any, action: str, status: int
) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce,
        patch(f"{_ROUTES}.{function}", return_value=answer) as service,
    ):
        response = _send(method, path, body)
    assert response.status_code == status
    (call,) = enforce.call_args_list
    assert (call.args[2], call.args[3], call.kwargs.get("target")) == (Resource.PACTS, action, "ledger-api")
    args, kwargs = service.call_args
    assert args[1:3] == (_TENANT, "ledger-api")
    if function in ("register_provider_state", "replace_provider_state"):
        assert (kwargs["actor"].user_id, kwargs["actor"].kind) == ("test-user-id", "api_key")
    if function in ("read_provider_state", "replace_provider_state", "remove_provider_state"):
        assert args[3] == _STATE_ID


@pytest.mark.parametrize(("method", "path", "body", "function", "answer", "action", "status"), _CALLS)
def test_a_denial_is_a_403_before_anything_runs(
    method: str, path: str, body: Any, function: str, answer: Any, action: str, status: int
) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=HTTPException(status_code=403, detail="denied")),
        patch(f"{_ROUTES}.{function}") as service,
    ):
        assert _send(method, path, body).status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_STATE_INVALID, "/setup/url: bad", pointer="/setup/url"), 422),
        (PactPublicationError(CODE_STATE_NAME_TAKEN, "taken", pointer="/name"), 409),
        (PactPublicationError(CODE_STATE_NOT_FOUND, "no state"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "no pacticipant"), 404),
    ],
)
def test_registry_refusals_map_to_their_status_and_keep_their_pointer(error: Exception, status: int) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.register_provider_state", side_effect=error),
    ):
        response = client.post(_BASE, json=_BODY)
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == error.code and detail["message"]  # type: ignore[attr-defined]
    assert detail.get("pointer") == getattr(error, "pointer", None)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_SELECTOR_INVALID, "bad selector"), 400),
        (TargetValidationError(TARGET_NOT_FOUND, "no target"), 404),
        (TargetValidationError("target-disabled", "disabled"), 422),
        (PactVerifierError(CODE_TOO_MANY_PACTS, "too many"), 422),
    ],
)
def test_check_refusals_map_to_their_status(error: Exception, status: int) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.check_provider_states", side_effect=error),
    ):
        assert client.post(f"{_BASE}/check", json={}).status_code == status


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": "x"},
        {**_BODY, "unknown": True},
        {**_BODY, "setup": {"kind": "script", "url": "/x"}},
        {**_BODY, "setup": {"kind": "fixture", "requests": [{"method": "GET"}]}},
        {**_BODY, "overrides": [{"setup": {"kind": "fixture"}}]},
    ],
)
def test_a_malformed_state_is_a_422(body: Dict[str, Any]) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.register_provider_state") as service,
    ):
        assert client.post(_BASE, json=body).status_code == 422
    service.assert_not_called()


def test_a_credential_without_a_tenant_is_refused() -> None:
    app.dependency_overrides[validate_broker_authentication] = lambda: {"user_id": "u"}
    with (
        patch(f"{_ROUTES}.enforce_permission", return_value="u"),
        patch(f"{_ROUTES}.list_provider_states") as service,
    ):
        assert client.get(_BASE).status_code == 403
    service.assert_not_called()


def test_the_routes_are_documented_and_stay_off_the_broker_surface() -> None:
    paths = app.openapi()["paths"]
    base = "/v1/tenants/{tenant_slug}/pact-verifier/providers/{provider}/provider-states"
    assert set(paths[base]) == {"get", "post"}
    assert set(paths[f"{base}/{{state_id}}"]) == {"get", "put", "delete"}
    assert set(paths[f"{base}/check"]) == {"post"}
    for operations in (paths[base], paths[f"{base}/{{state_id}}"], paths[f"{base}/check"]):
        for operation in operations.values():
            assert operation["tags"] == ["pact-broker"]
    assert not base.startswith(BROKER_PREFIX)
