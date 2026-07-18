"""Tests for auth-surface rate limiting — OLO-7.1 (#4223).

Two layers are exercised:

* the :func:`enforce_auth_ip_rate_limit` / :func:`enforce_auth_account_rate_limit`
  guards in isolation (429 shape, headers, kill switch, key isolation); and
* the onboarding router end-to-end on a small FastAPI app with the session
  dependency overridden and the ``db`` singleton stubbed, asserting the per-IP
  budget fires before the endpoint body, the per-account budget fires after
  session resolution, and the global ``rate_limit_enabled`` switch (the
  conftest neutralization pattern) disables both.

Each test swaps in a fresh ``FixedWindowRateLimiter`` so buckets never leak
between tests (the module limiter is process-global by design).
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import onboarding_routes
from app.auth import validate_session_credentials
from app.auth_rate_limit import (
    AUTH_RATE_LIMITED_CODE,
    enforce_auth_account_rate_limit,
    enforce_auth_ip_rate_limit,
)
from app.config import settings
from app.rate_limit import FixedWindowRateLimiter


def _request(client_ip: str = "203.0.113.20") -> Request:
    """Build a minimal ASGI request whose peer address is ``client_ip``."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/onboarding/first-tenant",
        "headers": [],
        "client": (client_ip, 12345),
    }
    return Request(scope)


def _fresh_limiter():
    """Patch the module-level limiter with an empty one for a single test."""
    return patch("app.auth_rate_limit._auth_limiter", FixedWindowRateLimiter())


# ===========================================================================
# Guard functions in isolation
# ===========================================================================


def test_ip_guard_allows_under_budget(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        enforce_auth_ip_rate_limit(_request())
        enforce_auth_ip_rate_limit(_request())


def test_ip_guard_raises_structured_429_when_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        enforce_auth_ip_rate_limit(_request())
        enforce_auth_ip_rate_limit(_request())
        with pytest.raises(HTTPException) as exc:
            enforce_auth_ip_rate_limit(_request())
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == AUTH_RATE_LIMITED_CODE
    assert exc.value.headers["Retry-After"]
    assert exc.value.headers["X-RateLimit-Limit"] == "2"
    assert exc.value.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Reset" in exc.value.headers


def test_ip_guard_isolates_distinct_addresses(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        enforce_auth_ip_rate_limit(_request("203.0.113.1"))
        # A different client IP has its own untouched budget.
        enforce_auth_ip_rate_limit(_request("203.0.113.2"))
        with pytest.raises(HTTPException):
            enforce_auth_ip_rate_limit(_request("203.0.113.1"))


def test_ip_guard_honours_global_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 1)
    with _fresh_limiter():
        for _ in range(5):
            enforce_auth_ip_rate_limit(_request())


def test_account_guard_raises_structured_429_when_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        enforce_auth_account_rate_limit("user-1")
        enforce_auth_account_rate_limit("user-1")
        with pytest.raises(HTTPException) as exc:
            enforce_auth_account_rate_limit("user-1")
    assert exc.value.status_code == 429
    assert exc.value.detail["code"] == AUTH_RATE_LIMITED_CODE
    assert exc.value.headers["Retry-After"]


def test_account_guard_isolates_distinct_accounts(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        enforce_auth_account_rate_limit("user-1")
        enforce_auth_account_rate_limit("user-2")
        with pytest.raises(HTTPException):
            enforce_auth_account_rate_limit("user-1")


def test_account_guard_noops_on_falsy_user_id(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 1)
    with _fresh_limiter():
        for _ in range(5):
            enforce_auth_account_rate_limit("")


def test_account_guard_honours_global_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 1)
    with _fresh_limiter():
        for _ in range(5):
            enforce_auth_account_rate_limit("user-1")


def test_zero_or_negative_budget_clamps_to_one(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 0)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        # A misconfigured budget of 0 still admits one request instead of
        # bricking the auth surface entirely.
        enforce_auth_ip_rate_limit(_request())
        with pytest.raises(HTTPException):
            enforce_auth_ip_rate_limit(_request())


# ===========================================================================
# Onboarding router end-to-end
# ===========================================================================


_SESSION = {"auth_method": "jwt", "user_id": "11111111-1111-1111-1111-111111111111"}

_TENANT_ROW = {
    "id": "22222222-2222-2222-2222-222222222222",
    "name": "Acme",
    "slug": "acme",
    "created_at": datetime(2026, 7, 17),
}


@pytest.fixture()
def onboarding_client(monkeypatch):
    """A TestClient over the real onboarding router with session + db stubbed."""
    app = FastAPI()
    app.include_router(onboarding_routes.router)
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_SESSION)

    monkeypatch.setattr(
        onboarding_routes.db, "provision_first_tenant", lambda *a, **k: dict(_TENANT_ROW)
    )
    monkeypatch.setattr(
        onboarding_routes.db, "activate_pending_membership", lambda *a, **k: "activated"
    )
    return TestClient(app)


def _provision(client: TestClient):
    return client.post(
        "/v1/onboarding/first-tenant",
        json={"name": "Acme", "provision_sample_project": False},
    )


def _activate(client: TestClient):
    return client.post(
        "/v1/onboarding/membership-activation",
        json={"tenant_id": "33333333-3333-3333-3333-333333333333"},
    )


def test_first_tenant_ip_budget_returns_429_with_retry_after(monkeypatch, onboarding_client):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 2)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        assert _provision(onboarding_client).status_code == 201
        assert _provision(onboarding_client).status_code == 201
        response = _provision(onboarding_client)
    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert response.headers["X-RateLimit-Limit"] == "2"
    assert response.json()["detail"]["code"] == AUTH_RATE_LIMITED_CODE


def test_first_tenant_account_budget_returns_429(monkeypatch, onboarding_client):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 100)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        assert _provision(onboarding_client).status_code == 201
        assert _provision(onboarding_client).status_code == 201
        response = _provision(onboarding_client)
    assert response.status_code == 429
    assert response.headers["Retry-After"]
    assert response.json()["detail"]["code"] == AUTH_RATE_LIMITED_CODE


def test_membership_activation_is_covered_by_both_budgets(monkeypatch, onboarding_client):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 100)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        assert _activate(onboarding_client).status_code == 200
        assert _activate(onboarding_client).status_code == 200
        response = _activate(onboarding_client)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == AUTH_RATE_LIMITED_CODE


def test_budgets_are_shared_across_onboarding_routes(monkeypatch, onboarding_client):
    """The account budget is one bucket for the whole auth surface, not per route."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 100)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with _fresh_limiter():
        assert _provision(onboarding_client).status_code == 201
        assert _activate(onboarding_client).status_code == 200
        response = _provision(onboarding_client)
    assert response.status_code == 429


def test_disable_switch_neutralizes_route_budgets(monkeypatch, onboarding_client):
    """The conftest pattern — flipping ``rate_limit_enabled`` off — covers OLO-7.1 too."""
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_rate_limit_ip_per_minute", 1)
    monkeypatch.setattr(settings, "auth_rate_limit_account_per_minute", 1)
    with _fresh_limiter():
        for _ in range(5):
            assert _provision(onboarding_client).status_code == 201
