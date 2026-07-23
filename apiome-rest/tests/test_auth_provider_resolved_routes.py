"""Tests for the internal resolved-provider-config read path (OLO-8.5, #4971).

Pin the contract of :mod:`app.auth_provider_resolved_routes` — the server-to-server endpoint the
apiome-ui merge resolver calls at login time:

* it is **service-token gated** and **fail-closed**: no configured token ⇒ ``503``; no header ⇒
  ``401``; wrong token ⇒ ``403``;
* with a valid token it returns each stored provider's ``enabled`` / ``client_id`` / **decrypted**
  ``client_secret`` / ``config`` (this is the one surface that returns a plaintext secret, hence the
  token gate);
* a provider whose stored secret cannot be decrypted is **omitted** (degrade to env), not fatal.

The crypto runs for real against a test KEK; the DB layer is mocked.
"""

import base64
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth_provider_secret_crypto import seal_provider_secret
from app.config import settings
from app.main import app

client = TestClient(app)

_TOKEN = "internal-service-token-abc"
_RESOLVED = "/v1/internal/auth-providers/resolved"


@pytest.fixture
def service_token(monkeypatch):
    """Configure the internal service token and return the matching header."""
    monkeypatch.setattr(settings, "internal_service_token", _TOKEN)
    return {"X-Internal-Service-Token": _TOKEN}


@pytest.fixture
def enc_key(monkeypatch):
    """Configure a real KEK so seal/unseal round-trips for real; return it."""
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "auth_config_enc_key", key)
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    return key


def _sealed_row(provider_id="github", secret="s3cr3t", **overrides):
    """A stored row (with-secret shape) whose secret is sealed under the active KEK."""
    blob, key_id = seal_provider_secret(secret)
    row = {
        "provider_id": provider_id,
        "enabled": True,
        "client_id": f"{provider_id}-client-id",
        "enc_key_id": key_id,
        "config": {"GITHUB_OAUTH_BASE_URL": "https://github.example"},
        "updated_at": None,
        "updated_by": "admin",
        "client_secret_encrypted": blob,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Service-token gate
# ---------------------------------------------------------------------------


def test_disabled_when_no_token_configured(monkeypatch):
    """No INTERNAL_SERVICE_TOKEN configured ⇒ 503, fail closed (never serves secrets)."""
    monkeypatch.setattr(settings, "internal_service_token", None)
    resp = client.get(_RESOLVED, headers={"X-Internal-Service-Token": "anything"})
    assert resp.status_code == 503


def test_missing_header_401(service_token):
    """Token configured but header absent ⇒ 401."""
    resp = client.get(_RESOLVED)
    assert resp.status_code == 401


def test_wrong_token_403(service_token):
    """Token configured but header mismatched ⇒ 403."""
    resp = client.get(_RESOLVED, headers={"X-Internal-Service-Token": "wrong"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_empty_when_no_rows(service_token):
    """No stored rows ⇒ empty providers map (everything falls back to env in the UI)."""
    with patch("app.auth_provider_resolved_routes.db") as mock_db:
        mock_db.list_auth_provider_config_with_secret.return_value = []
        resp = client.get(_RESOLVED, headers=service_token)
    assert resp.status_code == 200
    assert resp.json() == {"providers": {}}


def test_returns_decrypted_secret(service_token, enc_key):
    """A stored row is returned with its secret decrypted and config/enabled/client_id intact."""
    with patch("app.auth_provider_resolved_routes.db") as mock_db:
        mock_db.list_auth_provider_config_with_secret.return_value = [_sealed_row(secret="hunter2")]
        resp = client.get(_RESOLVED, headers=service_token)
    assert resp.status_code == 200
    gh = resp.json()["providers"]["github"]
    assert gh["enabled"] is True
    assert gh["client_id"] == "github-client-id"
    assert gh["client_secret"] == "hunter2"
    assert gh["config"] == {"GITHUB_OAUTH_BASE_URL": "https://github.example"}


def test_null_secret_when_none_stored(service_token, enc_key):
    """A provider row with no stored secret returns client_secret=null (env fallback in UI)."""
    with patch("app.auth_provider_resolved_routes.db") as mock_db:
        mock_db.list_auth_provider_config_with_secret.return_value = [
            _sealed_row(enc_key_id=None, client_secret_encrypted=None)
        ]
        resp = client.get(_RESOLVED, headers=service_token)
    assert resp.status_code == 200
    gh = resp.json()["providers"]["github"]
    assert gh["client_secret"] is None
    assert gh["client_id"] == "github-client-id"


def test_undecryptable_secret_provider_omitted(service_token, enc_key):
    """A row whose secret cannot be decrypted is omitted (degrade to env), not fatal.

    The blob is sealed under a DIFFERENT key than the one now configured, so unseal fails loud;
    the endpoint must drop just that provider and still return the others.
    """
    # Seal 'github' under a throwaway key, then switch the active KEK so it can't decrypt.
    throwaway = base64.b64encode(os.urandom(32)).decode()
    settings.auth_config_enc_key = throwaway
    bad_blob, bad_key_id = seal_provider_secret("secret")
    # Now a different active key (enc_key fixture already set one distinct from throwaway).
    settings.auth_config_enc_key = enc_key
    bad_row = {
        "provider_id": "github",
        "enabled": True,
        "client_id": "gh",
        "enc_key_id": bad_key_id,
        "config": {},
        "updated_at": None,
        "updated_by": "admin",
        "client_secret_encrypted": bad_blob,
    }
    good_row = _sealed_row(provider_id="gitlab", secret="ok")
    with patch("app.auth_provider_resolved_routes.db") as mock_db:
        mock_db.list_auth_provider_config_with_secret.return_value = [bad_row, good_row]
        resp = client.get(_RESOLVED, headers=service_token)
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert "github" not in providers  # dropped — degrade to env
    assert providers["gitlab"]["client_secret"] == "ok"


def test_no_secret_leaks_to_logs(service_token, enc_key, caplog):
    """When a provider is dropped, the log line carries no plaintext secret."""
    throwaway = base64.b64encode(os.urandom(32)).decode()
    settings.auth_config_enc_key = throwaway
    bad_blob, bad_key_id = seal_provider_secret("PLAINTEXT-SECRET-XYZ")
    settings.auth_config_enc_key = enc_key
    bad_row = {
        "provider_id": "github",
        "enabled": True,
        "client_id": "gh",
        "enc_key_id": bad_key_id,
        "config": {},
        "updated_at": None,
        "updated_by": "admin",
        "client_secret_encrypted": bad_blob,
    }
    with patch("app.auth_provider_resolved_routes.db") as mock_db:
        mock_db.list_auth_provider_config_with_secret.return_value = [bad_row]
        with caplog.at_level("WARNING"):
            resp = client.get(_RESOLVED, headers=service_token)
    assert resp.status_code == 200
    assert "PLAINTEXT-SECRET-XYZ" not in caplog.text
