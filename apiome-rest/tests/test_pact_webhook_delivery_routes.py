"""HTTP contract tests for the webhook delivery log — PFX-5.6 (#6950).

The routes of :mod:`app.pact_webhook_delivery_routes` and the cursor of
:mod:`app.pact_webhook_delivery_log`, with the store faked (``test_pact_webhook_delivery_log_db``
runs them against the real schema):

* every route is gated on ``pacts`` (view, or edit to redeliver) before the store is touched;
* a delivery renders with its webhook, status, attempts, event, pact and trigger;
* filters and the cursor are passed through and checked; a bad one is a 400 naming it;
* refusals map to their status (404, 409 with the reason).
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_publication import PactPublicationError
from app.pact_webhook import CODE_TRIGGERED_WEBHOOK_NOT_FOUND, CODE_WEBHOOK_INVALID, CODE_WEBHOOK_NOT_FOUND
from app.pact_webhook_delivery_log import (
    CODE_DELIVERY_CURSOR_INVALID,
    CODE_DELIVERY_IN_PROGRESS,
    CODE_WEBHOOK_DISABLED,
    DeliveryPage,
    decode_cursor,
    encode_cursor,
    list_deliveries,
    redeliver,
)
from app.pact_webhook_store import TriggeredWebhookLogs, TriggeredWebhookRecord
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt"}
_BASE = "/v1/tenants/acme/pact-webhook-deliveries"
_ROUTES = "app.pact_webhook_delivery_routes"
_WEBHOOK = "44444444-4444-4444-8444-444444444444"
_TRIGGERED = "55555555-5555-4555-8555-555555555555"
_SHA = "ab" * 32


def _triggered(**overrides: Any) -> TriggeredWebhookRecord:
    fields: Dict[str, Any] = {
        "id": _TRIGGERED,
        "webhook_id": _WEBHOOK,
        "name": "POST ci.example.com",
        "status": "failure",
        "attempts_made": 4,
        "attempts_remaining": 0,
        "trigger_type": "resource_creation",
        "event_name": "contract_published",
        "consumer_name": "Billing Service",
        "consumer_slug": "billing-service",
        "provider_name": "Ledger API",
        "provider_slug": "ledger-api",
        "consumer_version_number": "2.0.0",
        "sha": _SHA,
        "triggered_at": "2026-11-25T10:00:00+00:00",
    }
    fields.update(overrides)
    return TriggeredWebhookRecord(**fields)


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def _denied(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Permission denied")


# --- Rendering and filters -------------------------------------------------------------------


def test_the_log_renders_each_delivery_and_passes_its_filters(allowed: MagicMock) -> None:
    page = DeliveryPage(deliveries=[_triggered()], next_cursor="abc")
    with patch(f"{_ROUTES}.list_deliveries", return_value=page) as listing:
        response = client.get(
            _BASE, params={"webhook": _WEBHOOK.upper(), "status": "failure", "cursor": "c", "limit": 5}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["nextCursor"] == "abc"
    assert body["deliveries"] == [
        {
            "id": _TRIGGERED,
            "webhookId": _WEBHOOK,
            "name": "POST ci.example.com",
            "status": "failure",
            "attemptsMade": 4,
            "attemptsRemaining": 0,
            "triggerType": "resource_creation",
            "eventName": "contract_published",
            "consumer": {"name": "Billing Service", "slug": "billing-service"},
            "provider": {"name": "Ledger API", "slug": "ledger-api"},
            "consumerVersionNumber": "2.0.0",
            "pactVersionSha": _SHA,
            "verificationNumber": None,
            "triggeredAt": "2026-11-25T10:00:00+00:00",
        }
    ]
    kwargs = listing.call_args.kwargs
    assert listing.call_args.args[1] == _TENANT
    assert kwargs == {"webhook_id": _WEBHOOK, "status": "failure", "cursor": "c", "limit": 5}
    allowed.assert_called_once()
    assert allowed.call_args.args[2:] == (Resource.PACTS, Action.VIEW)


def test_a_malformed_webhook_id_is_a_404_without_reading(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_deliveries") as listing:
        response = client.get(_BASE, params={"webhook": "not-a-uuid"})
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_WEBHOOK_NOT_FOUND
    listing.assert_not_called()


def test_an_unknown_status_is_refused_by_the_schema(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.list_deliveries") as listing:
        response = client.get(_BASE, params={"status": "exploded"})
    assert response.status_code == 422
    listing.assert_not_called()


def test_a_page_larger_than_the_maximum_is_refused(allowed: MagicMock) -> None:
    assert client.get(_BASE, params={"limit": 51}).status_code == 422


@pytest.mark.parametrize(
    ("code", "status"),
    [(CODE_DELIVERY_CURSOR_INVALID, 400), (CODE_WEBHOOK_INVALID, 400), (CODE_WEBHOOK_NOT_FOUND, 404)],
)
def test_list_refusals_map_to_their_status(allowed: MagicMock, code: str, status: int) -> None:
    with patch(f"{_ROUTES}.list_deliveries", side_effect=PactPublicationError(code, "no")):
        response = client.get(_BASE)
    assert response.status_code == status and response.json()["detail"] == {"code": code, "message": "no"}


def test_the_latest_delivery_of_each_webhook(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.latest_deliveries", return_value={_WEBHOOK: _triggered(status="success")}):
        response = client.get(f"{_BASE}/latest")
    assert response.status_code == 200
    latest = response.json()["latest"]
    assert list(latest) == [_WEBHOOK] and latest[_WEBHOOK]["status"] == "success"


def test_one_delivery_carries_its_executions(allowed: MagicMock) -> None:
    executions = [{"attempt": 1, "success": False, "status": 500, "logs": "HTTP/1.1 500", "createdAt": "t"}]
    logs = TriggeredWebhookLogs(triggered=_triggered(), executions=executions)
    with patch(f"{_ROUTES}.get_triggered_webhook_logs", return_value=logs) as read:
        response = client.get(f"{_BASE}/{_TRIGGERED.upper()}")
    assert response.status_code == 200
    assert response.json()["executions"] == executions and response.json()["id"] == _TRIGGERED
    assert read.call_args.args[1:] == (_TENANT, _TRIGGERED)


def test_an_unknown_delivery_is_a_404(allowed: MagicMock) -> None:
    error = PactPublicationError(CODE_TRIGGERED_WEBHOOK_NOT_FOUND, "no triggered webhook")
    with patch(f"{_ROUTES}.get_triggered_webhook_logs", side_effect=error):
        assert client.get(f"{_BASE}/{_TRIGGERED}").status_code == 404


# --- Redelivery ------------------------------------------------------------------------------


def test_redeliver_answers_202_with_the_new_delivery_behind_pacts_edit(allowed: MagicMock) -> None:
    created = _triggered(id="66666666-6666-4666-8666-666666666666", status="not_run", trigger_type="user")
    with patch(f"{_ROUTES}.redeliver", return_value=created) as run:
        response = client.post(f"{_BASE}/{_TRIGGERED}/redeliver")
    assert response.status_code == 202
    assert response.json()["triggerType"] == "user" and response.json()["status"] == "not_run"
    assert run.call_args.args[1:] == (_TENANT, _TRIGGERED)
    assert allowed.call_args.args[2:] == (Resource.PACTS, Action.EDIT)


@pytest.mark.parametrize(
    ("code", "status"),
    [(CODE_DELIVERY_IN_PROGRESS, 409), (CODE_WEBHOOK_DISABLED, 409), (CODE_TRIGGERED_WEBHOOK_NOT_FOUND, 404)],
)
def test_redeliver_refusals_keep_their_reason(allowed: MagicMock, code: str, status: int) -> None:
    with patch(f"{_ROUTES}.redeliver", side_effect=PactPublicationError(code, "because")):
        response = client.post(f"{_BASE}/{_TRIGGERED}/redeliver")
    assert response.status_code == status and response.json()["detail"]["code"] == code


@pytest.mark.parametrize(
    ("method", "path", "store"),
    [
        ("get", _BASE, "list_deliveries"),
        ("get", f"{_BASE}/latest", "latest_deliveries"),
        ("get", f"{_BASE}/{_TRIGGERED}", "get_triggered_webhook_logs"),
        ("post", f"{_BASE}/{_TRIGGERED}/redeliver", "redeliver"),
    ],
)
def test_every_route_is_gated_before_the_store(method: str, path: str, store: str) -> None:
    with patch(f"{_ROUTES}.enforce_permission", side_effect=_denied), patch(f"{_ROUTES}.{store}") as touched:
        response = getattr(client, method)(path)
    assert response.status_code == 403
    touched.assert_not_called()


def test_a_credential_without_a_tenant_is_refused() -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u"}
    with patch(f"{_ROUTES}.enforce_permission", return_value=None), patch(f"{_ROUTES}.latest_deliveries") as read:
        assert client.get(f"{_BASE}/latest").status_code == 403
    read.assert_not_called()


# --- The store's own checks (no database reached) --------------------------------------------


def test_the_cursor_round_trips_and_refuses_anything_else() -> None:
    cursor = encode_cursor("2026-11-25T10:00:00.123456+00:00", _TRIGGERED)
    assert "=" not in cursor
    assert decode_cursor(cursor) == ("2026-11-25T10:00:00.123456+00:00", _TRIGGERED)
    assert decode_cursor(None) is None and decode_cursor("  ") is None
    for bad in ("%%%", encode_cursor("yesterday", _TRIGGERED), encode_cursor("2026-11-25T10:00:00", "x")):
        with pytest.raises(PactPublicationError) as caught:
            decode_cursor(bad)
        assert caught.value.code == CODE_DELIVERY_CURSOR_INVALID


def test_the_store_refuses_an_unknown_status_and_bad_cursor_before_querying() -> None:
    database = MagicMock()
    with pytest.raises(PactPublicationError) as caught:
        list_deliveries(database, _TENANT, status="exploded")
    assert caught.value.code == CODE_WEBHOOK_INVALID and caught.value.pointer == "/status"
    with pytest.raises(PactPublicationError):
        list_deliveries(database, _TENANT, cursor="%%%")
    database.execute_query.assert_not_called()


def test_the_store_pages_with_one_extra_row_and_clamps_the_size() -> None:
    row = {
        "id": _TRIGGERED,
        "webhook_id": _WEBHOOK,
        "event_name": "contract_published",
        "request_method": "POST",
        "request_url": "https://ci.example.com/x",
        "delivery_status": "pending",
        "attempt_count": 0,
        "consumer_name": "Billing Service",
        "consumer_slug": "billing-service",
        "provider_name": "Ledger API",
        "provider_slug": "ledger-api",
        "created_at": "2026-11-25T10:00:00+00:00",
    }
    database = MagicMock()
    database.execute_query.return_value = [row, {**row, "id": "77777777-7777-4777-8777-777777777777"}]
    page = list_deliveries(database, _TENANT, status="not_run", limit=1)
    assert [item.id for item in page.deliveries] == [_TRIGGERED] and page.deliveries[0].status == "not_run"
    assert decode_cursor(page.next_cursor) == ("2026-11-25T10:00:00+00:00", _TRIGGERED)
    query, params = database.execute_query.call_args.args
    assert "e.attempt_count = 0" in query and params[-1] == 2

    database.execute_query.return_value = []
    list_deliveries(database, _TENANT, limit=500)
    assert database.execute_query.call_args.args[1][-1] == 51


def test_redeliver_refuses_a_malformed_id_without_a_transaction() -> None:
    database = MagicMock()
    with pytest.raises(PactPublicationError) as caught:
        redeliver(database, _TENANT, "nope")
    assert caught.value.code == CODE_TRIGGERED_WEBHOOK_NOT_FOUND
    database._guarded_tx.assert_not_called()


def _run_tx(row: Any) -> MagicMock:
    """A database whose transaction runs ``work`` on a cursor that reads ``row``."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = [row, {"id": "event"}, {"id": "new"}]
    database = MagicMock()
    database._guarded_tx.side_effect = lambda work: work(cursor)
    return database


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (None, CODE_TRIGGERED_WEBHOOK_NOT_FOUND),
        ({"delivery_status": "retrying", "enabled": True}, CODE_DELIVERY_IN_PROGRESS),
        ({"delivery_status": "pending", "enabled": True}, CODE_DELIVERY_IN_PROGRESS),
        ({"delivery_status": "dead_letter", "enabled": False}, CODE_WEBHOOK_DISABLED),
    ],
)
def test_redeliver_refuses_with_a_reason(row: Any, code: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        redeliver(_run_tx(row), _TENANT, _TRIGGERED)
    assert caught.value.code == code
