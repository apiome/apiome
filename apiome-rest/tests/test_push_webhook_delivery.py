"""Push webhook delivery retry, attempts, and dead-letter (#2588)."""

from datetime import datetime, timezone
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



# ---------------------------------------------------------------------------------------------
# CDG-2.3 (#5962): direct-URL deliveries (team chat) and Retry-After
# ---------------------------------------------------------------------------------------------


def _direct_row(**kwargs):
    return _row(
        subscription_id=None,
        target_url="https://hooks.slack.com/services/T/B/X",
        subscription_url="https://hooks.slack.com/services/T/B/X",
        signing_secret_encrypted=None,
        **kwargs,
    )


def test_a_direct_delivery_is_sent_unsigned_through_the_ssrf_guard():
    db = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret") as decrypt,
        patch("app.push_webhook_delivery.build_guarded_client") as guarded,
        patch("app.push_webhook_delivery.httpx.Client") as plain,
    ):
        guarded.return_value.__enter__.return_value.post.return_value = mock_resp
        deliver_one_due_event(db, _direct_row())
    decrypt.assert_not_called()
    plain.assert_not_called()
    post = guarded.return_value.__enter__.return_value.post
    assert post.call_args.args[0] == "https://hooks.slack.com/services/T/B/X"
    assert "X-Apiome-Signature" not in post.call_args.kwargs["headers"]
    assert db.finalize_push_webhook_delivery_attempt.call_args[1]["new_status"] == "delivered"


def test_a_refused_destination_is_a_failed_attempt_not_a_crash():
    from app.ssrf_guard import SSRFError

    db = MagicMock()
    with patch("app.push_webhook_delivery.build_guarded_client") as guarded:
        guarded.return_value.__enter__.return_value.post.side_effect = SSRFError("private address")
        deliver_one_due_event(db, _direct_row())
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "retrying" and "private address" in kw["error_message"]


def test_retry_after_seconds_parses_both_forms():
    from app.push_webhook_delivery import RETRY_AFTER_MAX_SEC, retry_after_seconds

    now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
    assert retry_after_seconds("120") == 120
    assert retry_after_seconds("999999") == RETRY_AFTER_MAX_SEC
    assert retry_after_seconds("Sun, 18 Oct 2026 12:05:00 GMT", now=now) == 300
    assert retry_after_seconds("Sun, 18 Oct 2026 11:00:00 GMT", now=now) == 0
    for bad in (None, "", "soon", 30, MagicMock()):
        assert retry_after_seconds(bad) is None


def test_a_rate_limited_delivery_waits_as_long_as_the_receiver_asked():
    import httpx

    db = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "slow down"
    mock_resp.headers = httpx.Headers({"Retry-After": "900"})
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"),
        patch("app.push_webhook_delivery.httpx.Client") as httpx_client,
    ):
        httpx_client.return_value.__enter__.return_value.post.return_value = mock_resp
        before = datetime.now(timezone.utc)
        deliver_one_due_event(db, _row(attempt_count=0))
    kw = db.finalize_push_webhook_delivery_attempt.call_args[1]
    assert kw["new_status"] == "retrying"
    waited = (kw["next_retry_at"] - before).total_seconds()
    assert 899 <= waited <= 905, waited


def test_retry_after_on_a_server_error_is_ignored():
    import httpx

    db = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "err"
    mock_resp.headers = httpx.Headers({"Retry-After": "900"})
    with (
        patch("app.push_webhook_delivery.decrypt_signing_secret", return_value="secret"),
        patch("app.push_webhook_delivery.httpx.Client") as httpx_client,
    ):
        httpx_client.return_value.__enter__.return_value.post.return_value = mock_resp
        before = datetime.now(timezone.utc)
        deliver_one_due_event(db, _row(attempt_count=0))
    waited = (db.finalize_push_webhook_delivery_attempt.call_args[1]["next_retry_at"] - before).total_seconds()
    assert waited <= BACKOFF_AFTER_FAILURE_SEC[0] + 5
