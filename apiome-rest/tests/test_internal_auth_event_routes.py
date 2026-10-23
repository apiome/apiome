"""The server-to-server ``auth_events`` write path — EID-1.1 (#5011).

apiome-ui records every SSO sign-in outcome here. Pin that the endpoint is service-token gated,
accepts only sign-in outcomes (an admin event type cannot be forged), shape-checks every field
against the ledger's limits, and never stores the raw IP or User-Agent.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import internal_auth_event_routes as routes
from app.auth_events import hash_client_value
from app.config import settings
from app.main import app

client = TestClient(app)
PATH = "/v1/internal/auth-events"
TOKEN = "internal-token-for-auth-events"


@pytest.fixture
def ledger(monkeypatch) -> List[Dict[str, Any]]:
    monkeypatch.setattr(settings, "internal_service_token", TOKEN)
    rows: List[Dict[str, Any]] = []
    monkeypatch.setattr(routes.db, "write_auth_event", lambda **kw: rows.append(kw))
    return rows


def _post(body: Dict[str, Any], token: str = TOKEN):
    return client.post(PATH, json=body, headers={"X-Internal-Service-Token": token})


def test_records_a_failed_sso_sign_in_with_hashed_network_details(ledger) -> None:
    response = _post(
        {
            "event_type": "sign_in",
            "outcome": "failure",
            "provider": "sso:acme-okta",
            "user_label": "Ada@Acme.com",
            "error_code": "sso-assertion-invalid",
            "ip": "203.0.113.7",
            "user_agent": "Mozilla/5.0",
            "detail": {"protocol": "saml"},
        }
    )
    assert response.status_code == 202
    (row,) = ledger
    assert row["provider"] == "sso:acme-okta"
    assert row["error_code"] == "sso-assertion-invalid"
    assert row["user_label"] == "ada@acme.com"
    assert row["ip_hash"] == hash_client_value("203.0.113.7")
    assert row["user_agent_hash"] == hash_client_value("Mozilla/5.0")
    assert "203.0.113.7" not in str(row)


def test_needs_the_service_token(ledger) -> None:
    assert client.post(PATH, json={"event_type": "sign_in", "outcome": "success"}).status_code == 401
    assert _post({"event_type": "sign_in", "outcome": "success"}, token="wrong").status_code == 403
    assert ledger == []


@pytest.mark.parametrize(
    "body",
    [
        {"event_type": "sso_provider", "outcome": "success"},
        {"event_type": "two_factor_reset", "outcome": "success"},
        {"event_type": "sign_in", "outcome": "maybe"},
        {"event_type": "sign_in", "outcome": "failure", "provider": "sso:" + "a" * 29},
        {"event_type": "sign_in", "outcome": "failure", "provider": "SSO:Acme"},
        {"event_type": "sign_in", "outcome": "failure", "error_code": "bad code!"},
        {"event_type": "sign_in", "outcome": "failure", "user_id": "not-a-uuid"},
        {"event_type": "sign_in", "outcome": "failure", "detail": {"blob": "x" * 3000}},
        {"event_type": "sign_in", "outcome": "failure", "unexpected": True},
    ],
)
def test_refuses_anything_outside_the_vocabulary_or_limits(ledger, body) -> None:
    assert _post(body).status_code == 422
    assert ledger == []


def test_accepts_an_oauth_provider_slug_too(ledger) -> None:
    assert _post({"event_type": "link", "outcome": "success", "provider": "google"}).status_code == 202
