"""Sending a contract webhook — PFX-1.9 (#6922).

:mod:`app.pact_webhook_delivery` with the network and the database faked:

* the webhook's own request is sent — method, rendered URL, headers and body — through the SSRF
  guard, signed when the webhook has a signing secret;
* a failed delivery is retried on the push-webhook schedule and then dead-lettered;
* ``Retry-After`` is honoured;
* no secret reaches the execution log, the error column or the response preview, even when the
  receiver echoes it back;
* a deleted or disabled webhook is dead-lettered at once, and one whose secrets cannot be opened
  is retried rather than sent without them;
* the push-webhook worker hands a firing to this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.pact_webhook import REDACTED, SIGNATURE_HEADER, WebhookRecord, template_parameters
from app.pact_webhook_delivery import deliver_pact_webhook_event, execute_webhook
from app.pact_webhook_store import DeliveryWebhook
from app.push_webhook_delivery import BACKOFF_AFTER_FAILURE_SEC, MAX_DELIVERY_ATTEMPTS, deliver_one_due_event
from app.ssrf_guard import SSRFError

_MODULE = "app.pact_webhook_delivery"
_EVENT = "11111111-1111-4111-8111-111111111111"
_WEBHOOK = "22222222-2222-4222-8222-222222222222"
_TENANT = "33333333-3333-4333-8333-333333333333"
_TOKEN = "ghp_SuperSecretToken123"
_PASSWORD = "correct-horse-battery"
_SIGNING = "signing-secret-0123456789"

_PARAMETERS = template_parameters(
    event_name="contract_requiring_verification_published",
    consumer_name="Billing Service",
    provider_name="Ledger API",
    consumer_version_number="1.0.0",
    pact_url="https://broker.example.com/pact",
    provider_version_number="4f1e2d0",
    provider_version_branch="main",
)


def _record(**overrides: Any) -> WebhookRecord:
    fields: Dict[str, Any] = {
        "id": _WEBHOOK,
        "method": "POST",
        "url": "https://ci.example.com/hooks/verify?provider=${pactbroker.providerName}",
        "headers": {"Content-Type": "application/json"},
        "body": {"pactUrl": "${pactbroker.pactUrl}", "branch": "${pactbroker.providerVersionBranch}"},
        "secret_fields": ["signingSecret", "header:Authorization"],
    }
    fields.update(overrides)
    return WebhookRecord(**fields)


def _hook(record: Optional[WebhookRecord] = None, secrets: Any = "default") -> DeliveryWebhook:
    if secrets == "default":
        secrets = {"headers": {"Authorization": f"Bearer {_TOKEN}"}, "signingSecret": _SIGNING}
    return DeliveryWebhook(record=record or _record(), secrets=secrets)


def _row(attempt_count: int = 0) -> Dict[str, Any]:
    return {
        "event_id": _EVENT,
        "tenant_id": _TENANT,
        "pact_webhook_id": _WEBHOOK,
        "subscription_id": None,
        "event_type": "pact.contract_requiring_verification_published",
        "payload": {"eventName": "contract_requiring_verification_published", "parameters": _PARAMETERS},
        "attempt_count": attempt_count,
    }


class _Client:
    """A stand-in for the guarded httpx client that records the request it is given."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.requests: List[Dict[str, Any]] = []

    def __enter__(self) -> "_Client":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def request(self, method: str, url: str, *, content: bytes, headers: Dict[str, str]) -> Any:
        self.requests.append({"method": method, "url": url, "content": content, "headers": dict(headers)})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _response(status: int, text: str = "", headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    return httpx.Response(status, text=text, headers=headers or {})


def _deliver(response: Any, *, attempt_count: int = 0, hook: Any = "default") -> tuple:
    """Run one attempt; returns ``(finalize kwargs, the fake client, the guard factory mock)``."""
    database = MagicMock()
    client = _Client(response)
    with (
        patch(f"{_MODULE}.load_for_delivery", return_value=_hook() if hook == "default" else hook),
        patch(f"{_MODULE}.build_guarded_client", return_value=client) as guard,
    ):
        deliver_pact_webhook_event(database, _row(attempt_count))
    database.finalize_push_webhook_delivery_attempt.assert_called_once()
    args, kwargs = database.finalize_push_webhook_delivery_attempt.call_args
    assert args == (_EVENT,)
    return kwargs, client, guard


def _all_text(kwargs: Dict[str, Any]) -> str:
    return "\n".join(str(kwargs.get(key) or "") for key in kwargs)


# --- What is sent --------------------------------------------------------------------------------


def test_the_webhooks_own_request_is_sent_and_recorded_as_delivered() -> None:
    kwargs, client, guard = _deliver(_response(204))
    sent = client.requests[0]
    assert sent["method"] == "POST"
    assert sent["url"] == "https://ci.example.com/hooks/verify?provider=Ledger+API"
    assert json.loads(sent["content"]) == {"pactUrl": "https://broker.example.com/pact", "branch": "main"}
    assert sent["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert sent["headers"]["Content-Type"] == "application/json"
    assert sent["headers"]["X-Apiome-Event"] == "pact.contract_requiring_verification_published"
    assert sent["headers"]["X-Apiome-Delivery"] == _EVENT
    assert sent["headers"]["User-Agent"] == "Apiome-Webhooks/1.0"
    # Through the SSRF guard, without following redirects.
    assert guard.call_args.kwargs["follow_redirects"] is False

    assert kwargs["new_status"] == "delivered" and kwargs["attempt_number"] == 1
    assert kwargs["http_status"] == 204 and kwargs["next_retry_at"] is None
    assert kwargs["error_message"] is None and kwargs["last_error"] is None
    assert "Webhook delivered" in kwargs["execution_log"]


def test_the_body_is_signed_with_the_signing_secret() -> None:
    _kwargs, client, _guard = _deliver(_response(200))
    sent = client.requests[0]
    expected = hmac.new(_SIGNING.encode(), sent["content"], hashlib.sha256).hexdigest()
    assert sent["headers"][SIGNATURE_HEADER] == f"sha256={expected}"


def test_a_webhook_without_a_signing_secret_is_sent_unsigned() -> None:
    hook = _hook(_record(secret_fields=[]), secrets={})
    _kwargs, client, _guard = _deliver(_response(200), hook=hook)
    assert SIGNATURE_HEADER not in client.requests[0]["headers"]
    assert "Authorization" not in client.requests[0]["headers"]


def test_basic_auth_is_sent_from_the_sealed_password() -> None:
    hook = _hook(_record(username="ci", secret_fields=["password"]), secrets={"password": _PASSWORD})
    kwargs, client, _guard = _deliver(_response(200), hook=hook)
    assert client.requests[0]["headers"]["Authorization"].startswith("Basic ")
    assert _PASSWORD not in kwargs["execution_log"]
    assert client.requests[0]["headers"]["Authorization"].split()[1] not in kwargs["execution_log"]


# --- Retry, then dead-letter ---------------------------------------------------------------------


def test_a_failed_delivery_is_retried_then_dead_lettered() -> None:
    statuses = []
    for attempt_count in range(MAX_DELIVERY_ATTEMPTS):
        before = datetime.now(timezone.utc)
        kwargs, _client, _guard = _deliver(_response(500, "boom"), attempt_count=attempt_count)
        statuses.append(kwargs["new_status"])
        assert kwargs["attempt_number"] == kwargs["new_attempt_count"] == attempt_count + 1
        assert kwargs["http_status"] == 500 and kwargs["error_message"] == "HTTP 500"
        if attempt_count < MAX_DELIVERY_ATTEMPTS - 1:
            # The push-webhook schedule: 10 s, 60 s, 5 min.
            delay = (kwargs["next_retry_at"] - before).total_seconds()
            assert BACKOFF_AFTER_FAILURE_SEC[attempt_count] <= delay < BACKOFF_AFTER_FAILURE_SEC[attempt_count] + 5
            assert "it will be retried" in kwargs["execution_log"]
        else:
            assert kwargs["next_retry_at"] is None and kwargs["last_error"] == "HTTP 500"
            assert "dead-letter" in kwargs["execution_log"]
    assert statuses == ["retrying", "retrying", "retrying", "dead_letter"]


def test_a_connection_error_is_a_failed_attempt() -> None:
    kwargs, _client, _guard = _deliver(httpx.ConnectError("connection refused"))
    assert kwargs["new_status"] == "retrying" and kwargs["http_status"] is None
    assert "ConnectError" in kwargs["error_message"] and "ERROR:" in kwargs["execution_log"]


def test_the_ssrf_guard_refusing_the_address_is_a_failed_attempt() -> None:
    refusal = SSRFError("host 'ci.example.com' resolves to non-public address 10.0.0.5; refusing to fetch")
    kwargs, _client, _guard = _deliver(refusal, attempt_count=MAX_DELIVERY_ATTEMPTS - 1)
    assert kwargs["new_status"] == "dead_letter"
    assert "non-public address" in kwargs["last_error"]


def test_any_other_failure_to_send_is_a_failed_attempt_too() -> None:
    # A header value the HTTP library refuses, for one, names the value in its message.
    kwargs, _client, _guard = _deliver(RuntimeError(f"Illegal header value b'Bearer {_TOKEN}'"))
    assert kwargs["new_status"] == "retrying"
    assert "RuntimeError" in kwargs["error_message"] and _TOKEN not in _all_text(kwargs)


def test_a_webhooks_own_user_agent_replaces_the_default() -> None:
    hook = _hook(_record(headers={"user-agent": "acme-ci/1.0"}, secret_fields=[]), secrets={})
    _kwargs, client, _guard = _deliver(_response(200), hook=hook)
    sent = client.requests[0]["headers"]
    assert sent["user-agent"] == "acme-ci/1.0" and "User-Agent" not in sent


def test_retry_after_is_honoured() -> None:
    before = datetime.now(timezone.utc)
    kwargs, _client, _guard = _deliver(_response(429, "slow down", {"Retry-After": "120"}))
    assert kwargs["new_status"] == "retrying"
    assert 120 <= (kwargs["next_retry_at"] - before).total_seconds() < 125


# --- Secrets never in logs -----------------------------------------------------------------------


def test_no_secret_reaches_the_log_even_when_the_receiver_echoes_it() -> None:
    echo = json.dumps({"you_sent": f"Bearer {_TOKEN}", "signature_key": _SIGNING})
    kwargs, _client, _guard = _deliver(_response(500, echo, {"Set-Cookie": "session=abc", "X-Echo": _TOKEN}))
    recorded = _all_text(kwargs)
    assert _TOKEN not in recorded and _SIGNING not in recorded
    log = kwargs["execution_log"]
    # The request is logged — with the secret headers redacted by name.
    assert "HTTP/1.1 POST https://ci.example.com/hooks/verify?provider=Ledger+API" in log
    assert f"Authorization: {REDACTED}" in log and f"{SIGNATURE_HEADER}: {REDACTED}" in log
    assert "Content-Type: application/json" in log
    assert '"pactUrl":"https://broker.example.com/pact"' in log
    # The response is logged, scrubbed.
    assert "HTTP/1.1 500" in log and f'"you_sent": "{REDACTED}"' in log
    assert f"set-cookie: {REDACTED}" in log.lower() and f"x-echo: {REDACTED}" in log.lower()
    assert kwargs["response_body_preview"] is not None and _TOKEN not in kwargs["response_body_preview"]


def test_a_secret_cut_by_the_body_limit_leaves_nothing_behind() -> None:
    # The echoed token straddles the 4,096-character limit of the stored response body.
    echo = "x" * 4090 + _TOKEN + " tail"
    kwargs, _client, _guard = _deliver(_response(500, echo))
    recorded = _all_text(kwargs)
    assert _TOKEN not in recorded and _TOKEN[:8] not in recorded


def test_no_secret_reaches_the_error_of_a_failed_connection() -> None:
    kwargs, _client, _guard = _deliver(httpx.ConnectError(f"proxy rejected Authorization: Bearer {_TOKEN}"))
    assert _TOKEN not in _all_text(kwargs) and REDACTED in kwargs["error_message"]


# --- A webhook that cannot be sent ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("hook", "reason"),
    [(None, "deleted"), (_hook(_record(enabled=False)), "disabled")],
)
def test_a_deleted_or_disabled_webhook_is_dead_lettered_at_once(hook: Any, reason: str) -> None:
    kwargs, client, _guard = _deliver(_response(200), hook=hook)
    assert client.requests == []
    assert kwargs["new_status"] == "dead_letter" and reason in kwargs["last_error"]
    assert "not sent" in kwargs["execution_log"]


def test_unopenable_secrets_are_retried_never_sent_without_them() -> None:
    kwargs, client, _guard = _deliver(_response(200), hook=_hook(secrets=None))
    assert client.requests == []
    assert kwargs["new_status"] == "retrying" and kwargs["next_retry_at"] is not None
    assert "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS" in kwargs["last_error"]


# --- The worker and a test run -------------------------------------------------------------------


def test_the_push_webhook_worker_hands_a_firing_over() -> None:
    database = MagicMock()
    with patch(f"{_MODULE}.deliver_pact_webhook_event") as deliver:
        deliver_one_due_event(database, {**_row(), "subscription_url": "https://x", "subscription_active": True})
    deliver.assert_called_once()
    database.finalize_push_webhook_delivery_attempt.assert_not_called()


def test_a_test_run_sends_once_and_reports_without_secrets() -> None:
    hook = _hook()
    client = _Client(_response(202, '{"queued": true}', {"X-Request-Id": "r-1"}))
    with patch(f"{_MODULE}.build_guarded_client", return_value=client):
        result = execute_webhook(hook.record, hook.secrets, _PARAMETERS)
    assert result.success and result.status == 202
    assert client.requests[0]["headers"]["X-Apiome-Event"] == "pact.test"
    assert "X-Apiome-Delivery" not in client.requests[0]["headers"]
    assert result.request_headers["Authorization"] == REDACTED
    assert result.response_headers["x-request-id"] == "r-1" and result.response_body == '{"queued": true}'
    assert _TOKEN not in result.model_dump_json() and _SIGNING not in result.model_dump_json()
