"""Tests for the super-admin sign-up policy REST surface (SGN-1.4, #5653).

Pin the route contract of :mod:`app.signup_policy_routes`:

* gated by the signed super-admin session — no session ⇒ ``401``, bad session ⇒ ``403``;
* GET reports the stored policy, or the env fallback when nothing is stored;
* PUT validates, normalizes, stores (with the audit actor) and invalidates the policy cache;
* PUT ``mode: null`` clears the stored policy.

The data layer is mocked (``patch('app.signup_policy_routes.db')``) so these assert route
behaviour, not Postgres.
"""

import base64
import hmac
import json
from datetime import datetime, timezone
from hashlib import sha256
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import signup_policy as sp
from app.config import settings
from app.main import app

client = TestClient(app)

URL = "/v1/admin/signup-policy"
_ADMIN_SECRET = "test-admin-session-secret"


def _mint_admin_token(key: str = _ADMIN_SECRET) -> str:
    """Mint a far-future super-admin session token (same recipe as the provider-config tests)."""
    payload = {"v": 1, "sub": "admin", "iat": 0, "exp": 9_999_999_999_999}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    digest = hmac.new(key.encode(), encoded.encode(), sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(digest).rstrip(b'=').decode()}"


@pytest.fixture
def admin_headers(monkeypatch):
    """Configure the admin signing key and return a header carrying a valid session token."""
    monkeypatch.setattr(settings, "admin_session_secret", _ADMIN_SECRET)
    monkeypatch.setattr(settings, "admin_password", None)
    return {"X-Admin-Session": _mint_admin_token()}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Start every test with the env flag unset and an empty policy cache."""
    monkeypatch.delenv("AUTH_SIGNUP_DISABLED", raising=False)
    sp.invalidate_signup_policy_cache()
    yield
    sp.invalidate_signup_policy_cache()


def _row(**overrides):
    """A stored signup_policy row (as the DB layer returns it)."""
    base = {
        "mode": "invite_only",
        "allowed_email_domains": [],
        "updated_at": datetime(2026, 10, 11, tzinfo=timezone.utc),
        "updated_by": "admin",
    }
    base.update(overrides)
    return base


# --- Auth gate ----------------------------------------------------------------


@pytest.mark.parametrize("method", ["get", "put"])
def test_requires_session(method):
    kwargs = {"json": {"mode": "closed"}} if method == "put" else {}
    assert getattr(client, method)(URL, **kwargs).status_code == 401


@pytest.mark.parametrize("method", ["get", "put"])
def test_invalid_session_forbidden(method, monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", _ADMIN_SECRET)
    monkeypatch.setattr(settings, "admin_password", None)
    kwargs = {"json": {"mode": "closed"}} if method == "put" else {}
    with patch("app.signup_policy_routes.db") as db:
        resp = getattr(client, method)(URL, headers={"X-Admin-Session": "forged.token"}, **kwargs)
    assert resp.status_code == 403
    db.set_signup_policy.assert_not_called()


# --- GET ----------------------------------------------------------------------


def test_get_reports_env_fallback_when_nothing_is_stored(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        db.get_signup_policy.return_value = None
        resp = client.get(URL, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "mode": "open",
        "allowed_email_domains": [],
        "blocked_email_domains": [],
        "source": "env",
        "env_mode": "open",
        "updated_at": None,
        "updated_by": None,
    }


def test_get_env_fallback_follows_auth_signup_disabled(admin_headers, monkeypatch):
    monkeypatch.setenv("AUTH_SIGNUP_DISABLED", "true")
    with patch("app.signup_policy_routes.db") as db:
        db.get_signup_policy.return_value = None
        body = client.get(URL, headers=admin_headers).json()
    assert (body["mode"], body["source"], body["env_mode"]) == ("closed", "env", "closed")


def test_get_reports_the_stored_policy(admin_headers, monkeypatch):
    monkeypatch.setenv("AUTH_SIGNUP_DISABLED", "true")
    with patch("app.signup_policy_routes.db") as db:
        db.get_signup_policy.return_value = _row(mode="open", allowed_email_domains=["example.com"])
        body = client.get(URL, headers=admin_headers).json()
    assert body["mode"] == "open"
    assert body["allowed_email_domains"] == ["example.com"]
    assert body["source"] == "db"
    assert body["env_mode"] == "closed"
    assert body["updated_by"] == "admin"
    assert body["updated_at"].startswith("2026-10-11")


# --- PUT ----------------------------------------------------------------------


def test_put_stores_a_normalized_policy_and_invalidates_the_cache(admin_headers):
    with patch("app.signup_policy_routes.db") as db, patch(
        "app.signup_policy_routes.invalidate_signup_policy_cache"
    ) as invalidate:
        db.set_signup_policy.return_value = _row(
            mode="open", allowed_email_domains=["example.com", "corp.example"]
        )
        resp = client.put(
            URL,
            headers=admin_headers,
            json={
                "mode": "open",
                "allowed_email_domains": [" Example.com", "@corp.example", "example.com"],
            },
        )
    assert resp.status_code == 200
    db.set_signup_policy.assert_called_once_with(
        "open", ["example.com", "corp.example"], updated_by="admin", blocked_email_domains=[]
    )
    invalidate.assert_called_once_with()
    assert resp.json()["source"] == "db"
    assert resp.json()["allowed_email_domains"] == ["example.com", "corp.example"]


@pytest.mark.parametrize("mode", sp.SIGNUP_MODES)
def test_put_accepts_every_mode(admin_headers, mode):
    with patch("app.signup_policy_routes.db") as db:
        db.set_signup_policy.return_value = _row(mode=mode)
        resp = client.put(URL, headers=admin_headers, json={"mode": mode})
    assert resp.status_code == 200
    assert resp.json()["mode"] == mode
    db.set_signup_policy.assert_called_once_with(
        mode, [], updated_by="admin", blocked_email_domains=[]
    )


def test_put_null_mode_clears_the_stored_policy(admin_headers, monkeypatch):
    monkeypatch.setenv("AUTH_SIGNUP_DISABLED", "1")
    with patch("app.signup_policy_routes.db") as db, patch(
        "app.signup_policy_routes.invalidate_signup_policy_cache"
    ) as invalidate:
        db.set_signup_policy.return_value = None
        resp = client.put(
            URL, headers=admin_headers, json={"mode": None, "allowed_email_domains": ["x.example"]}
        )
    assert resp.status_code == 200
    db.set_signup_policy.assert_called_once_with(None, [], updated_by="admin")
    invalidate.assert_called_once_with()
    assert (resp.json()["mode"], resp.json()["source"]) == ("closed", "env")


def test_put_rejects_an_unknown_mode(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        resp = client.put(URL, headers=admin_headers, json={"mode": "members_only"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_mode"
    db.set_signup_policy.assert_not_called()


@pytest.mark.parametrize("domain", ["ada@example.com", "*.example.com", "localhost", ""])
def test_put_rejects_an_invalid_domain(admin_headers, domain):
    with patch("app.signup_policy_routes.db") as db:
        resp = client.put(
            URL, headers=admin_headers, json={"mode": "open", "allowed_email_domains": [domain]}
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_email_domain"
    db.set_signup_policy.assert_not_called()


def test_put_requires_the_mode_field(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        resp = client.put(URL, headers=admin_headers, json={"allowed_email_domains": []})
    assert resp.status_code == 422
    db.set_signup_policy.assert_not_called()


# --- Blocked email domains (SGN-1.5, #5654) ------------------------------------


def test_put_stores_normalized_blocked_domains(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        db.set_signup_policy.return_value = _row(
            mode="open", blocked_email_domains=["throwaway.example"]
        )
        resp = client.put(
            URL,
            headers=admin_headers,
            json={
                "mode": "open",
                "blocked_email_domains": ["@Throwaway.example", "throwaway.example"],
            },
        )
    assert resp.status_code == 200
    db.set_signup_policy.assert_called_once_with(
        "open", [], updated_by="admin", blocked_email_domains=["throwaway.example"]
    )
    assert resp.json()["blocked_email_domains"] == ["throwaway.example"]


def test_put_rejects_an_invalid_blocked_domain(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        resp = client.put(
            URL, headers=admin_headers, json={"mode": "open", "blocked_email_domains": ["*.bad"]}
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_email_domain"
    db.set_signup_policy.assert_not_called()


def test_put_rejects_an_over_long_blocked_list(admin_headers):
    domains = [f"d{i}.example" for i in range(sp.MAX_BLOCKED_EMAIL_DOMAINS + 1)]
    with patch("app.signup_policy_routes.db") as db:
        resp = client.put(
            URL, headers=admin_headers, json={"mode": "open", "blocked_email_domains": domains}
        )
    assert resp.status_code == 422
    db.set_signup_policy.assert_not_called()


def test_get_env_fallback_has_no_blocked_domains(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        db.get_signup_policy.return_value = None
        resp = client.get(URL, headers=admin_headers)
    assert resp.json()["blocked_email_domains"] == []


# --- Blocked attempts (SGN-1.5, #5654) -----------------------------------------

ATTEMPTS_URL = f"{URL}/blocked-attempts"


def test_blocked_attempts_requires_session():
    assert client.get(ATTEMPTS_URL).status_code == 401


def test_blocked_attempts_lists_guard_refusals(admin_headers):
    with patch("app.signup_policy_routes.db") as db:
        db.list_signup_guard_events.return_value = [
            {
                "id": "6f1c1f0e-1111-4c4c-8888-000000000001",
                "provider": "email",
                "error_code": "email-signup-disposable-domain",
                "user_label": "x@mailinator.com",
                "guard": "disposable_domain",
                "scope": None,
                "ip_hash": "a" * 64,
                "created_at": datetime(2026, 10, 23, tzinfo=timezone.utc),
            },
            {
                "id": "6f1c1f0e-1111-4c4c-8888-000000000002",
                "provider": "github",
                "error_code": "auth-rate-limited",
                "user_label": None,
                "guard": "rate_limit",
                "scope": "ip",
                "ip_hash": None,
                "created_at": datetime(2026, 10, 22, tzinfo=timezone.utc),
            },
        ]
        resp = client.get(ATTEMPTS_URL, headers=admin_headers, params={"limit": 10})
    assert resp.status_code == 200
    db.list_signup_guard_events.assert_called_once_with(limit=10)
    first, second = resp.json()["attempts"]
    assert first["guard"] == "disposable_domain"
    assert first["email"] == "x@mailinator.com"
    # Only a prefix of the salted digest leaves the server.
    assert first["client"] == "a" * 12
    assert (second["scope"], second["client"], second["email"]) == ("ip", None, None)


@pytest.mark.parametrize("limit", [0, 201])
def test_blocked_attempts_bounds_the_limit(admin_headers, limit):
    with patch("app.signup_policy_routes.db") as db:
        resp = client.get(ATTEMPTS_URL, headers=admin_headers, params={"limit": limit})
    assert resp.status_code == 422
    db.list_signup_guard_events.assert_not_called()
