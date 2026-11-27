"""HTTP contract tests for the workspace-secret routes — PFX-6.5 (#6957).

The routes of :mod:`app.pact_secret_routes` with the store faked:

* reads need ``pacts:view``, creating ``pacts:create``, rotating ``pacts:edit``, deleting
  ``pacts:delete``; a denial is a 403 before anything is read or written;
* the tenant comes from the credential, never the URL;
* each refusal maps to its status and code (404, 409, 422, 503) and **no answer — success or
  refusal — ever contains the value**;
* the routes stay off the catalogued Pact Broker surface.
"""

from __future__ import annotations

import json
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_broker_compat import BROKER_PREFIX
from app.pact_secret import (
    CODE_SECRET_IN_USE,
    CODE_SECRET_LIMIT,
    CODE_SECRET_NAME_TAKEN,
    CODE_SECRET_NOT_FOUND,
    CODE_SECRET_VAULT_UNAVAILABLE,
    PactSecretError,
    SecretRecord,
    SecretUsage,
    SecretUser,
)
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "session", "user_email": "a@example.test"}
_ROUTES = "app.pact_secret_routes"
_URL = "/v1/tenants/acme/pact-secrets"
_ID = "55555555-5555-4555-8555-555555555555"
_VALUE = "ci-token-value-0123456789"


def _record(**changes: Any) -> SecretRecord:
    base = {"id": _ID, "name": "ciToken", "description": "CI token", "reference": "${user.ciToken}"}
    return SecretRecord(**{**base, **changes})


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


def test_listing_needs_view_reads_the_callers_tenant_and_shows_no_value(allowed: MagicMock) -> None:
    usage = SecretUsage(webhooks=[SecretUser(kind="webhook", id="w-1", name="Verify Ledger API")])
    with patch(f"{_ROUTES}.list_secrets", return_value=[_record(used_by=usage)]) as listing:
        response = client.get(_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["limit"] == 200
    assert body["secrets"][0]["reference"] == "${user.ciToken}"
    assert body["secrets"][0]["used_by"]["webhooks"][0]["name"] == "Verify Ledger API"
    assert "value" not in body["secrets"][0]
    assert listing.call_args.args[1] == _TENANT
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.VIEW)


def test_creating_needs_create_and_never_echoes_the_value(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.create_secret", return_value=_record()) as create:
        response = client.post(_URL, json={"name": "ciToken", "value": _VALUE, "description": "CI token"})
    assert response.status_code == 201, response.text
    assert _VALUE not in response.text
    assert create.call_args.args[1] == _TENANT and create.call_args.args[2].value == _VALUE
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.CREATE)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "ci-token", "value": _VALUE},
        {"name": "ciToken", "value": _VALUE + "\n"},
        {"name": "ciToken", "value": _VALUE, "secretValue": _VALUE},
        {"name": "ciToken"},
    ],
)
def test_a_bad_body_is_a_422_that_does_not_repeat_the_value(allowed: MagicMock, body: dict) -> None:
    with patch(f"{_ROUTES}.create_secret") as create:
        response = client.post(_URL, content=json.dumps(body))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "pact-secret-invalid"
    assert response.json()["detail"]["pointer"]
    assert _VALUE not in response.text
    create.assert_not_called()


@pytest.mark.parametrize(
    ("code", "status"),
    [(CODE_SECRET_NAME_TAKEN, 409), (CODE_SECRET_LIMIT, 409), (CODE_SECRET_VAULT_UNAVAILABLE, 503)],
)
def test_a_create_refusal_maps_to_its_status(allowed: MagicMock, code: str, status: int) -> None:
    with patch(f"{_ROUTES}.create_secret", side_effect=PactSecretError(code, "refused")):
        response = client.post(_URL, json={"name": "ciToken", "value": _VALUE})
    assert response.status_code == status and response.json()["detail"]["code"] == code


def test_reading_one_needs_view_and_an_unknown_one_is_a_404(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_secret", return_value=_record()) as read:
        assert client.get(f"{_URL}/{_ID}").json()["name"] == "ciToken"
    assert read.call_args.args[1:] == (_TENANT, _ID)
    with patch(f"{_ROUTES}.get_secret", side_effect=PactSecretError(CODE_SECRET_NOT_FOUND, "no secret")):
        response = client.get(f"{_URL}/{_ID}")
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_SECRET_NOT_FOUND


def test_rotating_needs_edit(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.update_secret", return_value=_record()) as update:
        response = client.put(f"{_URL}/{_ID}", json={"value": _VALUE, "description": "rotated"})
    assert response.status_code == 200, response.text
    assert _VALUE not in response.text
    change = update.call_args.args[3]
    assert update.call_args.args[1:3] == (_TENANT, _ID) and change.value == _VALUE and change.description == "rotated"
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.EDIT)


def test_deleting_needs_delete_and_one_in_use_is_a_409(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.delete_secret", return_value=_record()) as delete:
        assert client.delete(f"{_URL}/{_ID}").status_code == 204
    assert delete.call_args.args[1:] == (_TENANT, _ID)
    assert allowed.call_args.args[2:4] == (Resource.PACTS, Action.DELETE)
    refusal = PactSecretError(CODE_SECRET_IN_USE, "the secret 'ciToken' is still used by webhooks 'Verify' (w-1)")
    with patch(f"{_ROUTES}.delete_secret", side_effect=refusal):
        response = client.delete(f"{_URL}/{_ID}")
    assert response.status_code == 409 and "Verify" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("method", "url", "store"),
    [
        ("get", _URL, "list_secrets"),
        ("post", _URL, "create_secret"),
        ("get", f"{_URL}/{_ID}", "get_secret"),
        ("put", f"{_URL}/{_ID}", "update_secret"),
        ("delete", f"{_URL}/{_ID}", "delete_secret"),
    ],
)
def test_a_denied_caller_gets_a_403_before_anything_is_read_or_written(method: str, url: str, store: str) -> None:
    body = {"json": {"name": "ciToken", "value": _VALUE}} if method in ("post", "put") else {}
    with patch(f"{_ROUTES}.enforce_permission", side_effect=_deny), patch(f"{_ROUTES}.{store}") as called:
        response = getattr(client, method)(url, **body)
    assert response.status_code == 403
    called.assert_not_called()


def test_the_routes_stay_off_the_broker_surface() -> None:
    paths = {route.path for route in app.routes if "pact-secrets" in getattr(route, "path", "")}
    assert paths == {"/v1/tenants/{tenant_slug}/pact-secrets", "/v1/tenants/{tenant_slug}/pact-secrets/{secret_id}"}
    assert all(BROKER_PREFIX not in path for path in paths)


# ---------------------------------------------------------------------------
# Webhook test runs that refer to secrets
# ---------------------------------------------------------------------------

_HOOKS = "app.pact_broker_webhook_routes"
_BROKER = "/v1/tenants/acme/pact-broker"
_HOOK_ID = "66666666-6666-4666-8666-666666666666"


@pytest.fixture
def hooks_allowed(monkeypatch: pytest.MonkeyPatch) -> Iterator[MagicMock]:
    monkeypatch.setattr("app.pact_broker_webhook_routes.settings.rate_limit_enabled", False)
    monkeypatch.setattr("app.pact_webhook.validate_host", lambda _host: None)
    with patch(f"{_HOOKS}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def _unsaved(**request: Any) -> dict:
    return {"request": {"method": "POST", "url": "https://ci.example.com/hook", **request}}


def test_an_unsaved_run_refers_only_to_secrets_its_workspace_has(hooks_allowed: MagicMock) -> None:
    with (
        patch("app.pact_webhook_store.missing_secret_names", return_value=["gone"]) as missing,
        patch(f"{_HOOKS}.execute_webhook") as execute,
    ):
        response = client.post(f"{_BROKER}/webhooks/execute", json=_unsaved(headers={"X-Key": "${user.gone}"}))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["pointer"] == "/request/headers/X-Key"
    assert missing.call_args.args[1:] == (_TENANT, ["gone"])
    execute.assert_not_called()


def test_an_unsaved_run_resolves_its_references_in_the_callers_tenant(hooks_allowed: MagicMock) -> None:
    from app.pact_webhook_delivery import ExecutionResult

    with (
        patch("app.pact_webhook_store.missing_secret_names", return_value=[]),
        patch(f"{_HOOKS}.execute_webhook", return_value=ExecutionResult(success=True, status=204)) as execute,
    ):
        response = client.post(f"{_BROKER}/webhooks/execute", json=_unsaved(body={"k": "${user.ciToken}"}))
    assert response.status_code == 200, response.text
    record = execute.call_args.args[0]
    assert record.secret_refs == ["ciToken"] and execute.call_args.kwargs["tenant_id"] == _TENANT


@pytest.mark.parametrize(
    ("code", "status", "answer"),
    [
        (CODE_SECRET_NOT_FOUND, 422, "pact-webhook-invalid"),
        (CODE_SECRET_VAULT_UNAVAILABLE, 503, "pact-webhook-secrets-unavailable"),
    ],
)
def test_a_saved_run_whose_secret_cannot_be_resolved_is_refused(
    hooks_allowed: MagicMock, code: str, status: int, answer: str
) -> None:
    from app.pact_webhook import WebhookRecord
    from app.pact_webhook_store import DeliveryWebhook

    record = WebhookRecord(
        id=_HOOK_ID, url="https://ci.example.com/hook", body="${user.ciToken}", secret_refs=["ciToken"]
    )
    with (
        patch(f"{_HOOKS}.load_for_delivery", return_value=DeliveryWebhook(record=record, secrets={})),
        patch("app.pact_webhook_delivery.resolve_secrets", side_effect=PactSecretError(code, "no secret 'ciToken'")),
        patch("app.pact_webhook_delivery.build_guarded_client") as guard,
    ):
        response = client.post(f"{_BROKER}/webhooks/{_HOOK_ID}/execute")
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == answer and "ciToken" in response.json()["detail"]["message"]
    guard.assert_not_called()
