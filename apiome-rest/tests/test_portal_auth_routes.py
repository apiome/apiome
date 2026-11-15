"""``/v1/portal/{tenant}/auth`` — PCX-1.1 (#5889) acceptance criteria, HTTP level."""

from __future__ import annotations

import pytest
from fake_portal_auth_repo import FakePortalAuthRepository, RecordingMailer
from fastapi.testclient import TestClient

from app import portal_auth_routes, portal_auth_store
from app.config import settings
from app.main import app

_BASE = "/v1/portal/acme/auth"
_CHROME = "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


@pytest.fixture
def repo(monkeypatch):
    fake = FakePortalAuthRepository()
    monkeypatch.setattr(portal_auth_store, "default_repository", lambda: fake)
    return fake


@pytest.fixture
def mailer(monkeypatch):
    recording = RecordingMailer()
    monkeypatch.setattr(portal_auth_routes, "default_reader_mailer", lambda: recording)
    return recording


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setattr(portal_auth_routes, "_signup_rejection", lambda _email: None)


@pytest.fixture
def client(repo, mailer, open_signup, monkeypatch):
    monkeypatch.setattr(settings, "public_browse_url", "https://browse.example")
    return TestClient(app, raise_server_exceptions=False)


def _sign_in(client, mailer, email="ada@example.com"):
    assert client.post(f"{_BASE}/magic-link", json={"email": email}).status_code == 202
    response = client.post(
        f"{_BASE}/exchange", json={"token": mailer.last_token()}, headers={"User-Agent": _CHROME}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _reader(token):
    return {"Authorization": f"Reader {token}"}


# ---------------------------------------------------------------------------------------------
# magic-link
# ---------------------------------------------------------------------------------------------


def test_a_request_is_accepted_and_mails_a_link(client, mailer):
    response = client.post(f"{_BASE}/magic-link", json={"email": "ada@example.com", "return_to": "/tenant/acme"})
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "expires_in_minutes": 15}
    assert mailer.sent[0]["link"].startswith("https://browse.example/portal/auth/exchange?tenant=acme&token=pml_")


@pytest.mark.parametrize("tenant", ["acme", "nope"])
def test_the_answer_is_the_same_whether_or_not_a_link_was_sent(client, mailer, repo, tenant, monkeypatch):
    monkeypatch.setattr(portal_auth_routes, "_signup_rejection", lambda _email: "signup-disabled")
    response = client.post(f"/v1/portal/{tenant}/auth/magic-link", json={"email": "new@example.com"})
    assert response.status_code == 202 and response.json()["accepted"] is True
    assert mailer.sent == [] and repo.users == {}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"email": "not-an-address"}, "portal-invalid-email"),
        ({"email": "ada@example.com", "return_to": "https://evil.example"}, "portal-invalid-return-to"),
        ({"email": "ada@example.com", "return_to": "//evil.example"}, "portal-invalid-return-to"),
    ],
)
def test_malformed_input_is_a_422_with_a_code(client, body, code):
    response = client.post(f"{_BASE}/magic-link", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_unknown_fields_are_refused(client):
    assert client.post(f"{_BASE}/magic-link", json={"email": "a@b.io", "admin": True}).status_code == 422


# ---------------------------------------------------------------------------------------------
# Rate limits (SGN-1.5 pattern)
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def limits(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_public_per_minute", 10_000)
    monkeypatch.setattr(settings, "rate_limit_authenticated_per_minute", 10_000)
    monkeypatch.setattr(portal_auth_routes, "_magic_link_limiter", portal_auth_routes.FixedWindowRateLimiter())
    monkeypatch.setattr(settings, "portal_magic_link_rate_limit_email_per_minute", 2)
    monkeypatch.setattr(settings, "portal_magic_link_rate_limit_ip_per_minute", 4)


def test_the_per_email_budget_is_enforced(client, limits, mailer):
    for _ in range(2):
        assert client.post(f"{_BASE}/magic-link", json={"email": "ada@example.com"}).status_code == 202
    response = client.post(f"{_BASE}/magic-link", json={"email": "ADA@example.com"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "portal-rate-limited"
    assert int(response.headers["Retry-After"]) >= 1
    assert len(mailer.sent) == 2
    # Another address still has its own budget.
    assert client.post(f"{_BASE}/magic-link", json={"email": "lin@example.com"}).status_code == 202


def test_the_per_address_budget_is_enforced(client, limits):
    for index in range(4):
        assert client.post(f"{_BASE}/magic-link", json={"email": f"r{index}@example.com"}).status_code == 202
    response = client.post(f"{_BASE}/magic-link", json={"email": "r9@example.com"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "portal-rate-limited"


def test_the_kill_switch_turns_the_budgets_off(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "portal_magic_link_rate_limit_email_per_minute", 1)
    for _ in range(3):
        assert client.post(f"{_BASE}/magic-link", json={"email": "ada@example.com"}).status_code == 202


# ---------------------------------------------------------------------------------------------
# exchange
# ---------------------------------------------------------------------------------------------


def test_the_exchange_returns_a_session_once(client, mailer, repo):
    grant = _sign_in(client, mailer)
    assert grant["session_token"].startswith("prs_")
    assert grant["reader"]["email"] == "ada@example.com"
    assert grant["reader"]["membership_status"] == "active"
    assert next(iter(repo.sessions.values()))["user_agent_family"] == "Chrome"


def test_a_reused_token_is_410_used(client, mailer):
    _sign_in(client, mailer)
    response = client.post(f"{_BASE}/exchange", json={"token": mailer.last_token()})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "portal-token-used"


def test_an_expired_token_is_410_expired(client, mailer, repo):
    client.post(f"{_BASE}/magic-link", json={"email": "ada@example.com"})
    for link in repo.links.values():
        link["expires_at"] = link["expires_at"].replace(year=2000)
    response = client.post(f"{_BASE}/exchange", json={"token": mailer.last_token()})
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "portal-token-expired"


def test_a_garbage_token_is_400_invalid(client):
    response = client.post(f"{_BASE}/exchange", json={"token": "pml_nope"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "portal-token-invalid"


# ---------------------------------------------------------------------------------------------
# me / sign-out
# ---------------------------------------------------------------------------------------------


def test_me_returns_the_reader(client, mailer):
    grant = _sign_in(client, mailer)
    response = client.get(f"{_BASE}/me", headers=_reader(grant["session_token"]))
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"
    assert response.json()["tenant_slug"] == "acme"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Reader prs_unknown"}, {"Authorization": "Bearer prs_x"}],
)
def test_me_without_a_live_session_is_401(client, headers):
    response = client.get(f"{_BASE}/me", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "portal-session-invalid"
    assert response.headers["WWW-Authenticate"] == "Reader"


def test_a_session_is_bound_to_its_tenant(client, mailer):
    grant = _sign_in(client, mailer)
    response = client.get("/v1/portal/globex/auth/me", headers=_reader(grant["session_token"]))
    assert response.status_code == 401


def test_sign_out_takes_effect_on_the_next_request(client, mailer):
    grant = _sign_in(client, mailer)
    headers = _reader(grant["session_token"])
    assert client.post(f"{_BASE}/sign-out", headers=headers).status_code == 204
    assert client.get(f"{_BASE}/me", headers=headers).status_code == 401
    # Idempotent.
    assert client.post(f"{_BASE}/sign-out", headers=headers).status_code == 204
    assert client.post(f"{_BASE}/sign-out").status_code == 204


def test_the_routes_are_tagged_portal_auth():
    paths = app.openapi()["paths"]
    for suffix, method in [("magic-link", "post"), ("exchange", "post"), ("sign-out", "post"), ("me", "get")]:
        assert paths[f"/v1/portal/{{tenant_slug}}/auth/{suffix}"][method]["tags"] == ["portal-auth"]
