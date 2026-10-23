"""`apiome login` routes — #5501.

Route contract of :mod:`app.cli_login_routes` with the store replaced by an in-memory fake that keeps
the same state rules as the SQL in :mod:`app.cli_login_store` (whose statements were exercised
against Postgres when written; see the migration test for the schema):

* start → pending login with a device code, a user code and the approve page;
* poll answers ``authorization_pending`` / ``slow_down`` / ``access_denied`` / ``expired_token`` /
  ``invalid_grant`` until approved, then a key **once**;
* reading, approving and denying need a session JWT (an API key is refused); approving needs
  ``api_keys:create`` in the chosen workspace and is audited;
* ``DELETE /key`` revokes only a CLI login key;
* the pure helpers (codes, hashing, key format, names).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import cli_login as pure
from app import cli_login_routes as routes
from app.config import settings
from app.main import app

client = TestClient(app)

BASE = "/v1/cli/login"
USER = "0b6c5a52-3f0e-4e6a-9d3b-2f1f0e7c1a11"
TENANT_ID = "6f2d0a7e-1c3b-4a5d-8e9f-0a1b2c3d4e5f"


def _bearer(user_id: str = USER) -> Dict[str, str]:
    token = jwt.encode(
        {"user_id": user_id, "sub": user_id, "email": "ada@northwind.io"},
        settings.effective_jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


class FakeStore:
    """In-memory :mod:`app.cli_login_store` with the same transitions."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.keys: Dict[str, Dict[str, Any]] = {}
        self.taken_codes: List[str] = []
        self.purged = 0

    def _by(self, field: str, value: str) -> Optional[Dict[str, Any]]:
        return next((r for r in self.rows.values() if r[field] == value), None)

    def purge_stale_requests(self, db) -> None:
        self.purged += 1

    def create_request(self, db, *, device_code_hash, user_code, client_name, expires_at):
        if user_code in self.taken_codes:
            return None
        row = {
            "id": str(uuid.uuid4()),
            "device_code_hash": device_code_hash,
            "user_code": user_code,
            "client_name": client_name,
            "status": "pending",
            "user_id": None,
            "tenant_id": None,
            "created_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
            "last_polled_at": None,
        }
        self.rows[row["id"]] = row
        return dict(row)

    def _live(self, user_code):
        row = self._by("user_code", user_code)
        if row and row["status"] == "pending" and row["expires_at"] > datetime.now(timezone.utc):
            return row
        return None

    def find_live_request(self, db, user_code):
        row = self._live(user_code)
        return dict(row) if row else None

    def approve_request(self, db, *, user_code, user_id, tenant_id):
        row = self._live(user_code)
        if not row:
            return None
        row.update(status="approved", user_id=user_id, tenant_id=tenant_id)
        return dict(row)

    def deny_request(self, db, *, user_code, user_id):
        row = self._live(user_code)
        if not row:
            return None
        row.update(status="denied", user_id=user_id)
        return dict(row)

    def record_poll(self, db, device_code_hash):
        row = self._by("device_code_hash", device_code_hash)
        if not row:
            return None
        previous = row["last_polled_at"]
        row["last_polled_at"] = datetime.now(timezone.utc)
        return {**row, "previous_poll_at": previous}

    def collect_key(self, db, *, device_code_hash, key_id, key_name, key_hash, key_prefix, key_expires_at):
        row = self._by("device_code_hash", device_code_hash)
        if not row or row["status"] != "approved" or row["expires_at"] <= datetime.now(timezone.utc):
            return None
        row["status"] = "consumed"
        self.keys[key_id] = {
            "key_hash": key_hash,
            "name": key_name,
            "created_by_user_id": row["user_id"],
            "tenant_id": row["tenant_id"],
            "cli_login": True,
            "revoked": False,
        }
        return {
            "key_id": key_id,
            "key_name": key_name,
            "key_prefix": key_prefix,
            "expires_at": key_expires_at,
            "tenant_slug": "northwind",
            "tenant_name": "Northwind",
        }

    def revoke_cli_login_key(self, db, key_id):
        key = self.keys.get(key_id)
        if not key or key["revoked"]:
            return None
        if not key["cli_login"]:
            return False
        key["revoked"] = True
        return True


class FakeDb:
    """The handful of ``db`` methods the routes call."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store
        self.allowed = {(TENANT_ID, USER)}
        self.audits: List[Dict[str, Any]] = []

    def user_has_permission(self, tenant_id, user_id, resource, action):
        assert (resource, action) == ("api_keys", "create")
        return (str(tenant_id), user_id) in self.allowed

    def write_access_audit(self, **row):
        self.audits.append(row)

    def validate_api_key(self, secret):
        for key_id, key in self.store.keys.items():
            if not key["revoked"] and bcrypt.checkpw(secret.encode(), key["key_hash"].encode()):
                return {"id": key_id, "tenant_id": key["tenant_id"], "created_by_user_id": key["created_by_user_id"]}
        return None


@pytest.fixture()
def env(monkeypatch):
    store = FakeStore()
    fake_db = FakeDb(store)
    for name in (
        "purge_stale_requests",
        "create_request",
        "find_live_request",
        "approve_request",
        "deny_request",
        "record_poll",
        "collect_key",
        "revoke_cli_login_key",
    ):
        monkeypatch.setattr(routes.store, name, getattr(store, name))
    monkeypatch.setattr(routes, "db", fake_db)
    monkeypatch.setattr(
        routes,
        "get_user_tenants",
        lambda user_id: [
            {"id": TENANT_ID, "slug": "northwind", "name": "Northwind"},
            {"id": "a" * 8 + "-0000-4000-8000-" + "0" * 12, "slug": "harbor", "name": "Harbor Labs"},
        ],
    )

    def fake_validate(request, tenant_slug, authorization=None, x_api_key=None):
        if tenant_slug == "northwind":
            return {"tenant_id": TENANT_ID, "tenant_slug": "northwind", "user_email": "ada@northwind.io"}
        if tenant_slug == "harbor":
            return {"tenant_id": "a" * 8 + "-0000-4000-8000-" + "0" * 12, "tenant_slug": "harbor"}
        raise HTTPException(status_code=403, detail="no access")

    monkeypatch.setattr(routes, "validate_authentication", fake_validate)
    monkeypatch.setattr(settings, "ui_public_url", "https://app.apiome.dev/")
    return store, fake_db


def _start(client_name: Optional[str] = "apiome-cli on build-box") -> Dict[str, Any]:
    response = client.post(BASE, json={"client_name": client_name})
    assert response.status_code == 201, response.text
    return response.json()


def _poll(device_code: str):
    return client.post(f"{BASE}/token", json={"device_code": device_code})


def _rewind_poll(store: FakeStore, user_code: str, seconds: int = 10) -> None:
    row = store._by("user_code", user_code)
    if row["last_polled_at"]:
        row["last_polled_at"] -= timedelta(seconds=seconds)


# ---------------------------------------------------------------------------------------------
# Start and poll
# ---------------------------------------------------------------------------------------------


def test_start_returns_codes_and_the_approve_page(env):
    store, _ = env
    started = _start()
    assert pure.normalize_user_code(started["user_code"]) == started["user_code"]
    assert started["verification_uri"] == "https://app.apiome.dev/cli/login"
    assert started["verification_uri_complete"] == f"https://app.apiome.dev/cli/login?code={started['user_code']}"
    assert started["expires_in"] == 600 and started["interval"] == 5
    # Only the hash of the device code is stored.
    row = store._by("user_code", started["user_code"])
    assert row["device_code_hash"] == pure.hash_device_code(started["device_code"])
    assert started["device_code"] not in str(row)
    assert row["client_name"] == "apiome-cli on build-box"
    assert store.purged == 1


def test_start_without_a_body_and_retries_a_taken_user_code(env, monkeypatch):
    store, _ = env
    codes = iter(["BCDF-GHJK", "LMNP-QRST"])
    store.taken_codes.append("BCDF-GHJK")
    monkeypatch.setattr(routes, "generate_user_code", lambda: next(codes))
    response = client.post(BASE)
    assert response.status_code == 201
    assert response.json()["user_code"] == "LMNP-QRST"


def test_start_rejects_unknown_fields(env):
    assert client.post(BASE, json={"tenant": "x"}).status_code == 422


def test_poll_is_pending_then_slow_down_when_too_fast(env):
    store, _ = env
    started = _start()
    first = _poll(started["device_code"])
    assert first.status_code == 400 and first.json()["detail"]["error"] == "authorization_pending"
    second = _poll(started["device_code"])
    assert second.json()["detail"]["error"] == "slow_down"
    _rewind_poll(store, started["user_code"])
    assert _poll(started["device_code"]).json()["detail"]["error"] == "authorization_pending"


def test_poll_with_an_unknown_device_code_is_invalid_grant(env):
    response = _poll("not-a-real-code")
    assert response.status_code == 400 and response.json()["detail"]["error"] == "invalid_grant"


def test_poll_after_expiry_is_expired_token(env):
    store, _ = env
    started = _start()
    store._by("user_code", started["user_code"])["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert _poll(started["device_code"]).json()["detail"]["error"] == "expired_token"


def test_approved_login_yields_a_working_key_once(env):
    store, fake_db = env
    started = _start()
    approved = client.post(
        f"{BASE}/requests/{started['user_code'].lower().replace('-', ' ')}/approve",
        json={"tenant_slug": "northwind"},
        headers=_bearer(),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json() == {"user_code": started["user_code"], "status": "approved", "tenant_slug": "northwind"}
    assert fake_db.audits[-1]["action"] == "cli_login.approve"
    assert fake_db.audits[-1]["actor_id"] == USER
    assert started["device_code"] not in str(fake_db.audits)

    issued = _poll(started["device_code"])
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["api_key"].startswith("sk_") and body["key_prefix"] == body["api_key"][:12] + "..."
    assert body["tenant_slug"] == "northwind"
    assert body["key_name"].startswith("CLI login · apiome-cli on build-box · ")
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=13, hours=23) < expires - datetime.now(timezone.utc) <= timedelta(days=14)
    key = store.keys[body["key_id"]]
    assert key["created_by_user_id"] == USER and key["cli_login"]
    assert bcrypt.checkpw(body["api_key"].encode(), key["key_hash"].encode())

    # Collected: the next poll gets nothing.
    assert _poll(started["device_code"]).json()["detail"]["error"] == "invalid_grant"


def test_denied_login_stops_the_cli(env):
    started = _start()
    denied = client.post(f"{BASE}/requests/{started['user_code']}/deny", headers=_bearer())
    assert denied.status_code == 200 and denied.json()["status"] == "denied"
    assert _poll(started["device_code"]).json()["detail"]["error"] == "access_denied"
    # Decided: it can no longer be approved.
    again = client.post(
        f"{BASE}/requests/{started['user_code']}/approve", json={"tenant_slug": "northwind"}, headers=_bearer()
    )
    assert again.status_code == 404


# ---------------------------------------------------------------------------------------------
# The approve page
# ---------------------------------------------------------------------------------------------


def test_read_lists_workspaces_with_who_may_approve(env):
    started = _start()
    response = client.get(f"{BASE}/requests/{started['user_code']}", headers=_bearer())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_name"] == "apiome-cli on build-box" and body["status"] == "pending"
    assert [(w["slug"], w["can_approve"]) for w in body["workspaces"]] == [("northwind", True), ("harbor", False)]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nonsense"}, {"X-API-Key": "sk_whatever"}])
def test_the_browser_routes_need_a_session_jwt(env, headers):
    started = _start()
    code = started["user_code"]
    assert client.get(f"{BASE}/requests/{code}", headers=headers).status_code == 401
    assert (
        client.post(f"{BASE}/requests/{code}/approve", json={"tenant_slug": "northwind"}, headers=headers).status_code
        == 401
    )
    assert client.post(f"{BASE}/requests/{code}/deny", headers=headers).status_code == 401


def test_approve_needs_api_keys_create_in_the_workspace(env):
    store, fake_db = env
    started = _start()
    refused = client.post(
        f"{BASE}/requests/{started['user_code']}/approve", json={"tenant_slug": "harbor"}, headers=_bearer()
    )
    assert refused.status_code == 403
    assert "permission to create API keys" in refused.json()["detail"]
    assert store._by("user_code", started["user_code"])["status"] == "pending"
    assert fake_db.audits == []
    # Not a member at all: the tenant check refuses first.
    outsider = client.post(
        f"{BASE}/requests/{started['user_code']}/approve", json={"tenant_slug": "elsewhere"}, headers=_bearer()
    )
    assert outsider.status_code == 403


@pytest.mark.parametrize("code", ["nope", "BCDF-GHJ", "ZZZZ-ZZZZ"])
def test_unknown_or_malformed_codes_are_404(env, code):
    assert client.get(f"{BASE}/requests/{code}", headers=_bearer()).status_code == 404


# ---------------------------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------------------------


def test_logout_revokes_only_a_cli_login_key(env):
    store, fake_db = env
    started = _start()
    client.post(f"{BASE}/requests/{started['user_code']}/approve", json={"tenant_slug": "northwind"}, headers=_bearer())
    secret = _poll(started["device_code"]).json()["api_key"]

    assert client.delete(f"{BASE}/key", headers={"X-API-Key": secret}).status_code == 204
    assert fake_db.audits[-1]["action"] == "cli_login.key_revoke"
    # Revoked: the key no longer authenticates.
    assert client.delete(f"{BASE}/key", headers={"X-API-Key": secret}).status_code == 401

    plain, _, plain_hash = pure.mint_workspace_key_secret()
    store.keys["plain"] = {
        "key_hash": plain_hash,
        "tenant_id": TENANT_ID,
        "created_by_user_id": USER,
        "cli_login": False,
        "revoked": False,
    }
    refused = client.delete(f"{BASE}/key", headers={"X-API-Key": plain})
    assert refused.status_code == 409
    assert store.keys["plain"]["revoked"] is False


def test_logout_without_a_key_is_401(env):
    assert client.delete(f"{BASE}/key").status_code == 401


# ---------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------


def test_user_codes_use_the_unambiguous_alphabet():
    for _ in range(200):
        code = pure.generate_user_code()
        assert pure.normalize_user_code(code) == code
        assert set(code.replace("-", "")) <= set(pure.USER_CODE_ALPHABET)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ktxr-mwdb", "KTXR-MWDB"),
        (" KTXR MWDB ", "KTXR-MWDB"),
        ("KTXRMWDB", "KTXR-MWDB"),
        ("KTXR-MWD", None),
        ("KTXR-MWD!", None),
        (None, None),
        (12345678, None),
    ],
)
def test_normalize_user_code(raw, expected):
    assert pure.normalize_user_code(raw) == expected


def test_device_codes_are_long_and_hashed():
    code = pure.generate_device_code()
    assert len(code) >= 43
    digest = pure.hash_device_code(code)
    assert len(digest) == 64 and digest == pure.hash_device_code(code) and digest != pure.hash_device_code(code + "x")


def test_key_names_are_bounded_and_distinct():
    rid = str(uuid.uuid4())
    assert pure.cli_login_key_name(None, rid) == f"CLI login · apiome-cli · {rid[:8]}"
    assert len(pure.cli_login_key_name("x" * 500, rid)) < 255
