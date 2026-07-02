"""Push webhook subscription API (#2587)."""

from unittest.mock import patch

import psycopg2.errors
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-a",
    "auth_method": "jwt",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_create_rejects_non_https_url():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        r = client.post(
            "/v1/push-webhook-subscriptions/tn",
            json={
                "url": "http://example.com/hook",
                "signingSecret": "x" * 16,
            },
        )
        assert r.status_code == 400
        mdb.create_push_webhook_subscription.assert_not_called()


def test_create_ok():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.create_push_webhook_subscription.return_value = {
            "id": "11111111-1111-1111-1111-111111111111",
            "url": "https://example.com/hook",
            "active": True,
            "signing_secret_ref": "22222222-2222-2222-2222-222222222222",
            "created_at": None,
            "updated_at": None,
        }
        r = client.post(
            "/v1/push-webhook-subscriptions/tn",
            json={
                "url": "https://example.com/hook/",
                "signingSecret": "supersecretvaluehere",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "signingSecret" not in body
        assert body["signingSecretRef"] == "22222222-2222-2222-2222-222222222222"
        assert body["url"] == "https://example.com/hook"
        mdb.create_push_webhook_subscription.assert_called_once()
        ca = mdb.create_push_webhook_subscription.call_args
        assert ca[0][1] == "https://example.com/hook/"  # original url preserved
        assert ca[0][2] == "https://example.com/hook"   # normalized url for dedup
        assert ca[0][3] == "supersecretvaluehere"        # signing_secret


def test_create_duplicate_409():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.create_push_webhook_subscription.side_effect = psycopg2.errors.UniqueViolation(
            "duplicate key value violates unique constraint"
        )
        r = client.post(
            "/v1/push-webhook-subscriptions/tn",
            json={
                "url": "https://dup.example/webhook",
                "signingSecret": "x" * 16,
            },
        )
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "WEBHOOK_URL_DUPLICATE"


def test_list_empty():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.list_push_webhook_subscriptions.return_value = []
        r = client.get("/v1/push-webhook-subscriptions/tn")
        assert r.status_code == 200
        assert r.json() == []


def test_update_requires_field():
    r = client.patch(
        "/v1/push-webhook-subscriptions/tn/11111111-1111-1111-1111-111111111111",
        json={},
    )
    assert r.status_code == 400


def test_update_duplicate_409():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.update_push_webhook_subscription.side_effect = psycopg2.errors.UniqueViolation(
            "duplicate key value violates unique constraint"
        )
        r = client.patch(
            "/v1/push-webhook-subscriptions/tn/11111111-1111-1111-1111-111111111111",
            json={"url": "https://other.example/h"},
        )
        assert r.status_code == 409


def test_normalize_rejects_userinfo():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        r = client.post(
            "/v1/push-webhook-subscriptions/tn",
            json={
                "url": "https://user:pass@example.com/hook",
                "signingSecret": "x" * 16,
            },
        )
        assert r.status_code == 400
        mdb.create_push_webhook_subscription.assert_not_called()


def test_get_single_ok():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.get_push_webhook_subscription.return_value = {
            "id": "11111111-1111-1111-1111-111111111111",
            "url": "https://example.com/hook",
            "active": True,
            "signing_secret_ref": "22222222-2222-2222-2222-222222222222",
            "created_at": None,
            "updated_at": None,
        }
        r = client.get(
            "/v1/push-webhook-subscriptions/tn/11111111-1111-1111-1111-111111111111"
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "11111111-1111-1111-1111-111111111111"
        assert body["signingSecretRef"] == "22222222-2222-2222-2222-222222222222"
        assert "signingSecret" not in body


def test_get_single_not_found():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.get_push_webhook_subscription.return_value = None
        r = client.get(
            "/v1/push-webhook-subscriptions/tn/00000000-0000-0000-0000-000000000000"
        )
        assert r.status_code == 404


def test_update_not_found():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.update_push_webhook_subscription.return_value = None
        r = client.patch(
            "/v1/push-webhook-subscriptions/tn/00000000-0000-0000-0000-000000000000",
            json={"active": False},
        )
        assert r.status_code == 404


def test_dead_letter_deliveries_list():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.list_push_webhook_dead_letter_events.return_value = []
        r = client.get("/v1/push-webhook-subscriptions/tn/deliveries/dead-letter")
        assert r.status_code == 200
        assert r.json() == []


def test_delivery_detail_not_found():
    with patch("app.push_webhook_subscriptions_routes.db") as mdb:
        mdb.get_push_webhook_delivery_event.return_value = None
        r = client.get(
            "/v1/push-webhook-subscriptions/tn/deliveries/11111111-1111-1111-1111-111111111111"
        )
        assert r.status_code == 404
