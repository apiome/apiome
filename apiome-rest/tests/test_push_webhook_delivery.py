"""Push webhook delivery retry, attempts, and dead-letter (#2588)."""

from unittest.mock import MagicMock, patch

from app.push_webhook_delivery import (
    BACKOFF_AFTER_FAILURE_SEC,
    MAX_DELIVERY_ATTEMPTS,
    deliver_one_due_event,
    process_due_push_webhook_deliveries,
)


def _row(**kwargs):
    base = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
        "subscription_id": "22222222-2222-2222-2222-222222222222",
        "event_type": "test.event",
        "payload": {"k": "v"},
        "event_status": "pending",
        "attempt_count": 0,
        "next_retry_at": None,
        "subscription_url": "https://hooks.example.com/r",
        "subscription_active": True,
        "signing_secret_encrypted": b"x",
    }
    base.update(kwargs)
    return base


def test_constants_bounded_backoff():
    assert MAX_DELIVERY_ATTEMPTS == 4
    assert BACKOFF_AFTER_FAILURE_SEC == (10, 60, 300)


def test_deliver_success_records_delivered():
    db = MagicMock()
    row = _row(attempt_count=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"),
        patch("app.push_webhook_delivery.httpx.Client") as httpx_client,
    ):
        httpx_client.return_value.__enter__.return_value.post.return_value = mock_resp
        deliver_one_due_event(db, row)
    db.finalize_push_webhook_delivery_attempt.assert_called_once()
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "delivered"
    assert kw["attempt_number"] == 1
    assert kw["next_retry_at"] is None


def test_inactive_subscription_dead_letter():
    db = MagicMock()
    row = _row(subscription_active=False)
    deliver_one_due_event(db, row)
    db.finalize_push_webhook_delivery_attempt.assert_called_once()
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "dead_letter"


def test_http_failure_schedules_retry():
    db = MagicMock()
    row = _row(attempt_count=0)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "err"
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"),
        patch("app.push_webhook_delivery.httpx.Client") as httpx_client,
    ):
        httpx_client.return_value.__enter__.return_value.post.return_value = mock_resp
        deliver_one_due_event(db, row)
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "retrying"
    assert kw["attempt_number"] == 1
    assert kw["next_retry_at"] is not None


def test_four_failures_dead_letter():
    db = MagicMock()
    row = _row(attempt_count=3)
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.text = "no"
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"),
        patch("app.push_webhook_delivery.httpx.Client") as httpx_client,
    ):
        httpx_client.return_value.__enter__.return_value.post.return_value = mock_resp
        deliver_one_due_event(db, row)
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "dead_letter"
    assert kw["attempt_number"] == 4


def test_process_due_calls_until_empty():
    db = MagicMock()
    db.get_next_due_push_webhook_delivery.side_effect = [_row(), None]
    with (
        patch("app.push_webhook_delivery.deliver_one_due_event") as d,
        patch("app.push_webhook_delivery.httpx.Client"),
    ):
        n = process_due_push_webhook_deliveries(db, max_events=10)
    assert n == 1
    d.assert_called_once()

