"""HTTP contract tests for contract webhooks — PFX-1.9 (#6922).

The routes of :mod:`app.pact_broker_webhook_routes`, with the store and the network faked
(``test_pact_webhook_db`` runs them against the real schema):

* every route is gated on ``pacts`` (view / create / edit / delete) before the store is touched;
* a webhook renders in the Pact Broker's shape, with the links the ``pact-broker`` CLI follows and
  never a secret;
* create answers ``201`` with ``Location``; ``PUT`` answers ``200`` or ``201``;
* the scoped routes resolve their consumer and provider and override the body's;
* a test run shows the request, the response and the log, with secrets redacted;
* triggered webhooks, the status summary and the execution log render as the broker's;
* refusals map to their status (404, 422 with a pointer, 503);
* the index links ``pb:webhooks`` and ``pb:webhook``, and after a publish the events are fired.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from app.pact_publication import PactPublicationError
from app.pact_webhook import (
    CODE_TRIGGERED_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_INVALID,
    CODE_WEBHOOK_LIMIT,
    CODE_WEBHOOK_NOT_FOUND,
    CODE_WEBHOOK_SECRETS_UNAVAILABLE,
    CODE_WEBHOOK_TEST_RATE_LIMITED,
    REDACTED,
    TARGET_GITHUB,
    WebhookRecord,
)
from app.pact_webhook_delivery import ExecutionResult
from app.pact_webhook_events import fire_publish_events, fire_verification_events
from app.pact_webhook_store import ANY_SCOPE, DeliveryWebhook, TriggeredWebhookLogs, TriggeredWebhookRecord
from app.pacticipant import CODE_NOT_FOUND, PacticipantRecord, PacticipantValidationError
from app.rate_limit import FixedWindowRateLimiter

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "api_key"}
_ROOT = "http://testserver/v1/tenants/acme/pact-broker"
_BASE = "/v1/tenants/acme/pact-broker"
_ROUTES = "app.pact_broker_webhook_routes"
_WEBHOOK = "44444444-4444-4444-8444-444444444444"
_TRIGGERED = "55555555-5555-4555-8555-555555555555"
_SHA = "ab" * 32
_PAIR = f"{_BASE}/pacts/provider/ledger-api/consumer/billing-service"
_SECRET = "ghp_SuperSecretToken123"

_BODY = {
    "description": "Verify Ledger API",
    "provider": {"name": "Ledger API"},
    "events": [{"name": "contract_requiring_verification_published"}],
    "request": {
        "method": "POST",
        "url": "https://ci.example.com/hooks/verify",
        "headers": {"Authorization": f"Bearer {_SECRET}"},
        "body": {"pactUrl": "${pactbroker.pactUrl}"},
    },
}


def _webhook(**overrides: Any) -> WebhookRecord:
    fields: Dict[str, Any] = {
        "id": _WEBHOOK,
        "description": "Verify Ledger API",
        "consumer_name": "Billing Service",
        "consumer_slug": "billing-service",
        "provider_name": "Ledger API",
        "provider_slug": "ledger-api",
        "enabled": True,
        "events": ["contract_requiring_verification_published"],
        "method": "POST",
        "url": "https://ci.example.com/hooks/verify",
        "headers": {"Content-Type": "application/json"},
        "body": {"pactUrl": "${pactbroker.pactUrl}"},
        "username": "ci",
        "secret_fields": ["password", "signingSecret", "header:X-Api-Key"],
        "created_at": "2026-11-24T10:00:00+00:00",
        "updated_at": "2026-11-24T10:00:00+00:00",
    }
    fields.update(overrides)
    return WebhookRecord(**fields)


def _pacticipant(slug: str, name: str) -> PacticipantRecord:
    return PacticipantRecord(id=f"id-{slug}", tenant_id=_TENANT, slug=slug, name=name)


_PACTICIPANTS = {
    "ledger-api": _pacticipant("ledger-api", "Ledger API"),
    "billing-service": _pacticipant("billing-service", "Billing Service"),
}


def _get_pacticipant(_db: Any, _tenant: str, ref: str) -> PacticipantRecord:
    try:
        return _PACTICIPANTS[ref]
    except KeyError:
        raise PacticipantValidationError(CODE_NOT_FOUND, f"no pacticipant '{ref}'") from None


def _triggered(status: str = "retrying", **overrides: Any) -> TriggeredWebhookRecord:
    fields: Dict[str, Any] = {
        "id": _TRIGGERED,
        "webhook_id": _WEBHOOK,
        "name": "POST ci.example.com",
        "status": status,
        "attempts_made": 1,
        "attempts_remaining": 3,
        "event_name": "contract_published",
        "consumer_name": "Billing Service",
        "consumer_slug": "billing-service",
        "provider_name": "Ledger API",
        "provider_slug": "ledger-api",
        "consumer_version_number": "1.0.0",
        "sha": _SHA,
        "triggered_at": "2026-11-24T10:05:00+00:00",
    }
    fields.update(overrides)
    return TriggeredWebhookRecord(**fields)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_broker_authentication] = lambda: _MOCK_AUTH
    with (
        patch(f"{_ROUTES}.get_pacticipant", side_effect=_get_pacticipant),
        patch("app.pact_webhook.validate_host", return_value=None),
    ):
        yield
    app.dependency_overrides.clear()


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    """Every permission granted; yields the ``enforce_permission`` mock."""
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


# --- RBAC ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "action"),
    [
        ("get", f"{_BASE}/webhooks", "view"),
        ("post", f"{_BASE}/webhooks", "create"),
        ("post", f"{_BASE}/webhooks/execute", "create"),
        ("get", f"{_BASE}/webhooks/{_WEBHOOK}", "view"),
        ("put", f"{_BASE}/webhooks/{_WEBHOOK}", "edit"),
        ("delete", f"{_BASE}/webhooks/{_WEBHOOK}", "delete"),
        ("post", f"{_BASE}/webhooks/{_WEBHOOK}/execute", "edit"),
        ("get", f"{_BASE}/webhooks/provider/ledger-api/consumer/billing-service", "view"),
        ("post", f"{_BASE}/webhooks/provider/ledger-api/consumer/billing-service", "create"),
        ("get", f"{_BASE}/webhooks/provider/ledger-api", "view"),
        ("post", f"{_BASE}/webhooks/consumer/billing-service", "create"),
        ("get", f"{_PAIR}/webhooks", "view"),
        ("post", f"{_PAIR}/webhooks", "create"),
        ("get", f"{_PAIR}/webhooks/status", "view"),
        ("get", f"{_PAIR}/version/1.0.0/triggered-webhooks", "view"),
        ("get", f"{_PAIR}/pact-version/{_SHA}/verification-results/1/triggered-webhooks", "view"),
        ("get", f"{_BASE}/triggered-webhooks/{_TRIGGERED}/logs", "view"),
    ],
)
def test_every_route_is_gated_before_the_store_is_touched(method: str, path: str, action: str) -> None:
    denial = HTTPException(status_code=403, detail="denied")
    store = (
        "list_webhooks",
        "get_webhook",
        "create_webhook",
        "replace_webhook",
        "delete_webhook",
        "list_triggered_webhooks",
        "get_triggered_webhook_logs",
        "execute_webhook",
    )
    patches = {name: patch(f"{_ROUTES}.{name}") for name in store}
    mocks = {name: started.start() for name, started in patches.items()}
    try:
        with (
            patch(f"{_ROUTES}.enforce_permission", side_effect=denial) as enforce,
            patch(f"{_ROUTES}.load_for_delivery", return_value=DeliveryWebhook(record=_webhook(), secrets={})),
        ):
            response = getattr(client, method)(path, **({"json": _BODY} if method in ("post", "put") else {}))
    finally:
        for started in patches.values():
            started.stop()
    assert response.status_code == 403
    assert enforce.call_args.args[2] == "pacts" and enforce.call_args.args[3] == action
    assert not any(mock.called for mock in mocks.values())


def test_put_on_a_new_uuid_needs_create(allowed: MagicMock) -> None:
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=None),
        patch(f"{_ROUTES}.create_webhook", return_value=_webhook()) as create,
    ):
        response = client.put(f"{_BASE}/webhooks/{_WEBHOOK}", json=_BODY)
    assert response.status_code == 201
    assert allowed.call_args.args[3] == "create"
    assert create.call_args.kwargs["webhook_id"] == _WEBHOOK


# --- A webhook's shape ---------------------------------------------------------------------------


def test_a_webhook_renders_in_the_brokers_shape_without_secrets(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.get_webhook", return_value=_webhook()) as get:
        response = client.get(f"{_BASE}/webhooks/{_WEBHOOK.upper()}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/hal+json")
    assert get.call_args.args[1:] == (_TENANT, _WEBHOOK)
    assert response.json() == {
        "uuid": _WEBHOOK,
        "description": "Verify Ledger API",
        "consumer": {"name": "Billing Service"},
        "provider": {"name": "Ledger API"},
        "enabled": True,
        "request": {
            "method": "POST",
            "url": "https://ci.example.com/hooks/verify",
            "headers": {"Content-Type": "application/json", "X-Api-Key": REDACTED},
            "body": {"pactUrl": "${pactbroker.pactUrl}"},
            "username": "ci",
            "password": REDACTED,
        },
        "events": [{"name": "contract_requiring_verification_published"}],
        "signed": True,
        "createdAt": "2026-11-24T10:00:00+00:00",
        "_links": {
            "self": {"title": "Verify Ledger API", "href": f"{_ROOT}/webhooks/{_WEBHOOK}"},
            "pb:execute": {
                "title": (
                    "Test the execution of the webhook with the latest matching pact or verification by "
                    "sending a POST request to this URL"
                ),
                "href": f"{_ROOT}/webhooks/{_WEBHOOK}/execute",
            },
            "pb:consumer": {
                "title": "Consumer",
                "name": "Billing Service",
                "href": f"{_ROOT}/pacticipants/billing-service",
            },
            "pb:provider": {"title": "Provider", "name": "Ledger API", "href": f"{_ROOT}/pacticipants/ledger-api"},
            "pb:pact-webhooks": {
                "title": "All webhooks for consumer Billing Service and provider Ledger API",
                "href": f"{_ROOT}/webhooks/provider/ledger-api/consumer/billing-service",
            },
            "pb:webhooks": {"title": "All webhooks", "href": f"{_ROOT}/webhooks"},
        },
    }


def test_a_webhook_for_all_pacts_and_a_github_target_render(allowed: MagicMock) -> None:
    record = _webhook(
        description=None,
        consumer_name=None,
        consumer_slug=None,
        provider_name=None,
        provider_slug=None,
        username=None,
        target_kind=TARGET_GITHUB,
        target_config={"repository": "acme/ledger-api", "eventType": "pact_changed"},
        url="https://api.github.com/repos/acme/ledger-api/dispatches",
        secret_fields=["header:Authorization"],
        updated_at="2026-11-24T11:00:00+00:00",
    )
    with patch(f"{_ROUTES}.get_webhook", return_value=record):
        body = client.get(f"{_BASE}/webhooks/{_WEBHOOK}").json()
    # No description: the request stands in, as in the Pact Broker.
    assert body["description"] == "POST api.github.com" and body["_links"]["self"]["title"] == "POST api.github.com"
    assert "consumer" not in body and "provider" not in body and body["signed"] is False
    assert body["target"] == {
        "type": TARGET_GITHUB,
        "repository": "acme/ledger-api",
        "eventType": "pact_changed",
        "token": REDACTED,
    }
    assert body["request"]["headers"]["Authorization"] == REDACTED and "password" not in body["request"]
    assert body["updatedAt"] == "2026-11-24T11:00:00+00:00"
    assert set(body["_links"]) == {"self", "pb:execute", "pb:webhooks"}


def test_the_list_links_and_embeds_each_webhook(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_webhooks", return_value=[_webhook()]) as listing:
        response = client.get(f"{_BASE}/webhooks")
    assert listing.call_args.kwargs["scope"] is ANY_SCOPE
    body = response.json()
    assert body["_links"]["self"] == {"title": "Webhooks", "href": f"{_ROOT}/webhooks"}
    assert body["_links"]["pb:create"]["href"] == f"{_ROOT}/webhooks"
    assert body["_links"]["pb:webhooks"] == [
        {
            "title": "A webhook for the pact between Billing Service and Ledger API",
            "name": "Verify Ledger API",
            "href": f"{_ROOT}/webhooks/{_WEBHOOK}",
        }
    ]
    assert [item["uuid"] for item in body["_embedded"]["webhooks"]] == [_WEBHOOK]


# --- Writing -------------------------------------------------------------------------------------


def test_create_answers_201_with_location_and_seals_nothing_itself(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.create_webhook", return_value=_webhook()) as create:
        response = client.post(f"{_BASE}/webhooks", json=_BODY)
    assert response.status_code == 201, response.text
    assert response.headers["location"] == f"{_ROOT}/webhooks/{_WEBHOOK}"
    args, kwargs = create.call_args
    assert args[1] == _TENANT and kwargs["actor"].user_id == "test-user-id"
    parsed = args[2]
    assert parsed.provider_name == "Ledger API" and parsed.consumer_name is None
    assert parsed.secret_headers == {"Authorization": f"Bearer {_SECRET}"} and parsed.headers == {}
    assert _SECRET not in response.text


@pytest.mark.parametrize(
    ("path", "consumer", "provider"),
    [
        (f"{_BASE}/webhooks/provider/ledger-api/consumer/billing-service", "Billing Service", "Ledger API"),
        (f"{_PAIR}/webhooks", "Billing Service", "Ledger API"),
        (f"{_BASE}/webhooks/provider/ledger-api", None, "Ledger API"),
        (f"{_BASE}/webhooks/consumer/billing-service", "Billing Service", None),
    ],
)
def test_a_scoped_route_sets_the_scope_and_lists_exactly_it(
    allowed: MagicMock, path: str, consumer: Any, provider: Any
) -> None:
    body = {key: value for key, value in _BODY.items() if key != "provider"}
    with patch(f"{_ROUTES}.create_webhook", return_value=_webhook()) as create:
        assert client.post(path, json=body).status_code == 201
    parsed = create.call_args.args[2]
    assert (parsed.consumer_name, parsed.provider_name) == (consumer, provider)

    with patch(f"{_ROUTES}.list_webhooks", return_value=[]) as listing:
        response = client.get(path)
    assert response.status_code == 200
    scoped_consumer, scoped_provider = listing.call_args.kwargs["scope"]
    assert (scoped_consumer and scoped_consumer.name, scoped_provider and scoped_provider.name) == (consumer, provider)
    assert response.json()["_links"]["self"]["href"] == "http://testserver" + path


def test_put_replaces_an_existing_webhook(allowed: MagicMock) -> None:
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=DeliveryWebhook(record=_webhook(), secrets={})),
        patch(f"{_ROUTES}.replace_webhook", return_value=_webhook(description="Renamed")) as replace,
    ):
        response = client.put(f"{_BASE}/webhooks/{_WEBHOOK}", json=_BODY)
    assert response.status_code == 200 and response.json()["description"] == "Renamed"
    assert replace.call_args.args[1:3] == (_TENANT, _WEBHOOK)
    assert allowed.call_args.args[3] == "edit"


def test_delete_answers_204(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.delete_webhook", return_value=_webhook()) as delete:
        response = client.delete(f"{_BASE}/webhooks/{_WEBHOOK}")
    assert response.status_code == 204 and response.content == b""
    assert delete.call_args.args[1:] == (_TENANT, _WEBHOOK)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_WEBHOOK_INVALID, "/provider/name: no pacticipant", pointer="/provider/name"), 422),
        (PactPublicationError(CODE_WEBHOOK_SECRETS_UNAVAILABLE, "set the key"), 503),
        (PactPublicationError(CODE_WEBHOOK_NOT_FOUND, "no webhook"), 404),
        (PactPublicationError(CODE_WEBHOOK_LIMIT, "200 webhooks"), 409),
    ],
)
def test_store_refusals_map_to_their_status(allowed: MagicMock, error: PactPublicationError, status: int) -> None:
    with patch(f"{_ROUTES}.create_webhook", side_effect=error):
        response = client.post(f"{_BASE}/webhooks", json=_BODY)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code
    assert response.json()["detail"].get("pointer") == error.pointer


def test_a_malformed_body_is_422_with_a_pointer_and_an_unknown_scope_404(allowed: MagicMock) -> None:
    response = client.post(f"{_BASE}/webhooks", json={"request": {"method": "DELETE", "url": "https://x.example.com"}})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": CODE_WEBHOOK_INVALID,
        "message": "/request/method: must be one of POST, PUT, PATCH",
        "pointer": "/request/method",
    }
    assert client.get(f"{_BASE}/webhooks/provider/no-such").status_code == 404
    assert client.get(f"{_BASE}/webhooks/not-a-uuid").json()["detail"]["code"] == CODE_WEBHOOK_NOT_FOUND


# --- Test runs -----------------------------------------------------------------------------------


def _result(**overrides: Any) -> ExecutionResult:
    fields: Dict[str, Any] = {
        "success": True,
        "status": 204,
        "request_headers": {"Authorization": REDACTED, "Content-Type": "application/json"},
        "request_body": '{"pactUrl":"x"}',
        "response_headers": {"x-request-id": "r-1"},
        "response_body": "",
        "url": "https://ci.example.com/hooks/verify",
        "logs": "[2026-11-24T10:00:00Z] INFO: HTTP/1.1 POST https://ci.example.com/hooks/verify\n",
    }
    fields.update(overrides)
    return ExecutionResult(**fields)


def test_a_saved_webhook_is_run_with_its_secrets_and_the_latest_pact(allowed: MagicMock) -> None:
    hook = DeliveryWebhook(record=_webhook(), secrets={"password": "pw", "headers": {"X-Api-Key": "k"}})
    pact = MagicMock(
        consumer_name="Billing Service",
        provider_name="Ledger API",
        consumer_slug="billing-service",
        provider_slug="ledger-api",
        consumer_version="1.0.0",
        sha=_SHA,
    )
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=hook),
        patch(f"{_ROUTES}.get_latest_pact", return_value=pact),
        patch(f"{_ROUTES}.execute_webhook", return_value=_result()) as execute,
    ):
        response = client.post(f"{_BASE}/webhooks/{_WEBHOOK}/execute")
    assert response.status_code == 200, response.text
    record, secrets, parameters = execute.call_args.args
    assert record.id == _WEBHOOK and secrets == hook.secrets
    assert parameters["pactbroker.eventName"] == "test"
    assert parameters["pactbroker.consumerVersionNumber"] == "1.0.0"
    assert parameters["pactbroker.pactUrl"].startswith(f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/")
    assert response.json() == {
        "request": {
            "headers": {"Authorization": REDACTED, "Content-Type": "application/json"},
            "body": '{"pactUrl":"x"}',
            "url": "https://ci.example.com/hooks/verify",
        },
        "logs": _result().logs,
        "success": True,
        "response": {"status": 204, "headers": {"x-request-id": "r-1"}, "body": ""},
        "_links": {
            "try-again": {"title": "Execute the webhook again", "href": f"{_ROOT}/webhooks/{_WEBHOOK}/execute"},
            "webhook": {"href": f"{_ROOT}/webhooks/{_WEBHOOK}"},
        },
    }


def test_a_run_that_got_no_response_reports_the_error(allowed: MagicMock) -> None:
    hook = DeliveryWebhook(record=_webhook(consumer_name=None, consumer_slug=None), secrets={})
    failed = _result(success=False, status=None, error="ConnectError: connection refused")
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=hook),
        patch(f"{_ROUTES}.execute_webhook", return_value=failed) as execute,
    ):
        body = client.post(f"{_BASE}/webhooks/{_WEBHOOK}/execute").json()
    assert body["success"] is False and "response" not in body
    assert body["error"] == {"message": "ConnectError: connection refused"}
    # Without a pair to look a pact up for, placeholders stand in.
    assert execute.call_args.args[2]["pactbroker.consumerName"] == "placeholder-consumer"


def test_running_a_missing_webhook_or_one_with_unopenable_secrets_is_refused(allowed: MagicMock) -> None:
    missing = PactPublicationError(CODE_WEBHOOK_NOT_FOUND, "no webhook")
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=None),
        patch(f"{_ROUTES}.get_webhook", side_effect=missing),
    ):
        assert client.post(f"{_BASE}/webhooks/{_WEBHOOK}/execute").status_code == 404
    with patch(f"{_ROUTES}.load_for_delivery", return_value=DeliveryWebhook(record=_webhook(), secrets=None)):
        response = client.post(f"{_BASE}/webhooks/{_WEBHOOK}/execute")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == CODE_WEBHOOK_SECRETS_UNAVAILABLE


def test_test_runs_are_rate_limited_per_workspace(allowed: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(f"{_ROUTES}.TEST_RUNS_PER_WINDOW", 2)
    monkeypatch.setattr(f"{_ROUTES}._test_limiter", FixedWindowRateLimiter())
    hook = DeliveryWebhook(record=_webhook(), secrets={})
    with (
        patch(f"{_ROUTES}.load_for_delivery", return_value=hook),
        patch(f"{_ROUTES}.get_latest_pact", side_effect=PactPublicationError("pact-not-found", "none")),
        patch(f"{_ROUTES}.execute_webhook", return_value=_result()) as execute,
    ):
        statuses = [client.post(f"{_BASE}/webhooks/{_WEBHOOK}/execute").status_code for _ in range(2)]
        limited = client.post(f"{_BASE}/webhooks/execute", json=_BODY)
    assert statuses == [200, 200] and execute.call_count == 2
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1
    assert limited.json()["detail"]["code"] == CODE_WEBHOOK_TEST_RATE_LIMITED


def test_an_unsaved_webhook_is_run_from_the_body(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.execute_webhook", return_value=_result()) as execute:
        response = client.post(f"{_BASE}/webhooks/execute", json=_BODY)
    assert response.status_code == 200, response.text
    record, secrets, _parameters = execute.call_args.args
    assert record.url == "https://ci.example.com/hooks/verify" and record.provider_name == "Ledger API"
    assert secrets == {"headers": {"Authorization": f"Bearer {_SECRET}"}}
    assert "webhook" not in response.json()["_links"]

    kept = json.loads(json.dumps(_BODY))
    kept["request"]["headers"]["Authorization"] = REDACTED
    refused = client.post(f"{_BASE}/webhooks/execute", json=kept)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == CODE_WEBHOOK_INVALID


# --- What fired ----------------------------------------------------------------------------------


def test_the_status_of_a_pact_summarises_its_latest_firings(allowed: MagicMock) -> None:
    firings = [
        _triggered("success", id="a" * 8 + _TRIGGERED[8:], attempts_remaining=0),
        _triggered("retrying"),
        _triggered("failure", id="b" * 8 + _TRIGGERED[8:], attempts_made=4, attempts_remaining=0),
        _triggered("not_run", id="c" * 8 + _TRIGGERED[8:], attempts_made=0, attempts_remaining=4),
    ]
    with patch(f"{_ROUTES}.list_triggered_webhooks", return_value=firings) as listing:
        response = client.get(f"{_PAIR}/webhooks/status")
    assert response.status_code == 200
    assert listing.call_args.kwargs == {"latest_only": True}
    assert [record.slug for record in listing.call_args.args[2:4]] == ["billing-service", "ledger-api"]
    body = response.json()
    assert body["summary"] == {"successful": 1, "failed": 1, "retrying": 1, "notRun": 1}
    assert body["_embedded"]["triggeredWebhooks"][1] == {
        "name": "POST ci.example.com",
        "status": "retrying",
        "attemptsMade": 1,
        "attemptsRemaining": 3,
        "triggerType": "resource_creation",
        "eventName": "contract_published",
        "triggeredAt": "2026-11-24T10:05:00+00:00",
        "_links": {
            "pb:logs": {
                "href": f"{_ROOT}/triggered-webhooks/{_TRIGGERED}/logs",
                "title": "Webhook execution logs",
                "name": "POST ci.example.com",
            },
            "logs": {
                "href": f"{_ROOT}/triggered-webhooks/{_TRIGGERED}/logs",
                "title": "DEPRECATED - Use pb:logs",
                "name": "POST ci.example.com",
            },
            "pb:webhook": {
                "href": f"{_ROOT}/webhooks/{_WEBHOOK}",
                "title": "Webhook",
                "name": "POST ci.example.com",
            },
        },
    }
    links = body["_links"]
    assert links["self"] == {
        "title": "Webhooks status",
        "href": f"{_ROOT}/pacts/provider/ledger-api/consumer/billing-service/webhooks/status",
    }
    assert len(links["pb:error-logs"]) == 2
    assert links["pb:pact-webhooks"]["href"].endswith("/consumer/billing-service/webhooks")
    assert links["pb:consumer"]["name"] == "Billing Service" and links["pb:provider"]["name"] == "Ledger API"


def test_triggered_webhooks_of_a_publication_and_of_a_result(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_triggered_webhooks", return_value=[_triggered()]) as listing:
        publication = client.get(f"{_PAIR}/version/1.0.0/triggered-webhooks")
        result = client.get(f"{_PAIR}/pact-version/{_SHA.upper()}/verification-results/3/triggered-webhooks")
    assert publication.status_code == 200 and result.status_code == 200
    assert listing.call_args_list[0].kwargs == {"consumer_version_number": "1.0.0"}
    assert listing.call_args_list[1].kwargs == {"verification": (_SHA, 3)}
    assert publication.json()["_links"]["self"]["title"] == "Webhooks triggered by the publication of the pact"
    assert len(result.json()["_embedded"]["triggeredWebhooks"]) == 1


def test_the_log_reads_as_text_or_as_json(allowed: MagicMock) -> None:
    logs = TriggeredWebhookLogs(
        triggered=_triggered(),
        executions=[
            {"attempt": 1, "success": False, "status": 500, "logs": "first\n", "createdAt": "2026-11-24T10:05:01Z"},
            {"attempt": 2, "success": True, "status": 204, "logs": "second\n", "createdAt": "2026-11-24T10:05:11Z"},
        ],
    )
    path = f"{_BASE}/triggered-webhooks/{_TRIGGERED}/logs"
    with patch(f"{_ROUTES}.get_triggered_webhook_logs", return_value=logs) as read:
        text = client.get(path)
        document = client.get(path, headers={"Accept": "application/hal+json"})
    assert read.call_args.args[1:] == (_TENANT, _TRIGGERED)
    assert text.headers["content-type"].startswith("text/plain") and text.text == "first\n\nsecond\n"
    assert document.headers["content-type"].startswith("application/hal+json")
    body = document.json()
    assert body["eventName"] == "contract_published" and body["consumerName"] == "Billing Service"
    assert [execution["attempt"] for execution in body["executions"]] == [1, 2]
    assert body["_embedded"] == {"triggeredWebhook": {"uuid": _TRIGGERED}}
    assert body["_links"]["pb:webhook"]["href"] == f"{_ROOT}/webhooks/{_WEBHOOK}"

    with patch(f"{_ROUTES}.get_triggered_webhook_logs", return_value=TriggeredWebhookLogs(triggered=_triggered())):
        assert "has not executed yet" in client.get(path).text
    missing = PactPublicationError(CODE_TRIGGERED_WEBHOOK_NOT_FOUND, "no triggered webhook")
    with patch(f"{_ROUTES}.get_triggered_webhook_logs", side_effect=missing):
        assert client.get(path).status_code == 404


# --- The index and the hooks ---------------------------------------------------------------------


def test_the_index_links_the_webhook_resources() -> None:
    with patch("app.pact_broker_routes.enforce_permission", return_value="test-user-id"):
        links = client.get(_BASE).json()["_links"]
    assert links["pb:webhooks"] == {"href": f"{_ROOT}/webhooks", "title": "Webhooks", "templated": False}
    assert links["pb:webhook"] == {"href": f"{_ROOT}/webhooks/{{uuid}}", "title": "Webhook", "templated": True}


def test_a_publish_fires_its_events_after_the_store_committed() -> None:
    outcome = MagicMock()
    with (
        patch("app.pact_broker_routes.enforce_permission", return_value="test-user-id"),
        patch("app.pact_broker_routes.publish_pacts", return_value=outcome),
        patch("app.pact_broker_routes._publish_result", return_value={}),
        patch("app.pact_broker_routes.prepare_pact", return_value=MagicMock()),
        patch("app.pact_broker_routes.decode_contract_content", return_value=b"{}"),
        patch("app.pact_broker_routes.fire_publish_events", return_value=[]) as fire,
    ):
        response = client.post(
            f"{_BASE}/contracts/publish",
            json={
                "pacticipantName": "Billing Service",
                "pacticipantVersionNumber": "1.0.0",
                "contracts": [
                    {
                        "consumerName": "Billing Service",
                        "providerName": "Ledger API",
                        "specification": "pact",
                        "contentType": "application/json",
                        "content": "e30=",
                    }
                ],
            },
        )
    assert response.status_code == 200, response.text
    assert fire.call_args.args[1:] == (_TENANT, _ROOT, outcome)


def test_firing_never_fails_the_publish() -> None:
    database = MagicMock()
    database._guarded_tx.side_effect = RuntimeError("database is down")
    outcome = MagicMock(pacts=[MagicMock(created=True, replaced=False)])
    assert fire_publish_events(database, _TENANT, _ROOT, outcome) == []
    assert fire_verification_events(database, _TENANT, _ROOT, MagicMock()) == []
    # A publish that changed nothing does not even open a transaction.
    database._guarded_tx.reset_mock()
    unchanged = MagicMock(pacts=[MagicMock(created=False, replaced=False)])
    assert fire_publish_events(database, _TENANT, _ROOT, unchanged) == []
    database._guarded_tx.assert_not_called()
