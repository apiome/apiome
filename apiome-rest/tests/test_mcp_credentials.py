"""Tests for the credential loader that bridges the vault to the auth-type model (MCAT-6.1).

:mod:`app.mcp_credentials` reads a stored ``mcp_endpoint_credentials`` row, unseals it through
the MCAT-6.2 decryption seam (:func:`decrypt_credential_payload`), and feeds the plaintext to the
auth-type model. These tests exercise that wiring by stubbing the seam and the DB read, covering:
the anonymous fast path, a decrypted bearer credential, the not-yet-decryptable fallback, a
malformed payload, and a credential-store failure — each degrading safely to no/usable headers.
"""

import json

import pytest

from app import mcp_credentials
from app.config import settings
from app.mcp_auth import AUTHORIZATION_HEADER
from app.mcp_credential_crypto import seal_credential_payload


def test_none_credential_skips_decryption(monkeypatch):
    # The anonymous fast path must never invoke the decryptor.
    def _boom(_credential):
        raise AssertionError("decrypt_credential_payload should not be called for auth_type=none")

    monkeypatch.setattr(mcp_credentials, "decrypt_credential_payload", _boom)
    assert mcp_credentials._headers_for_credential({"auth_type": "none"}) == {}


def test_missing_credential_row_yields_no_headers():
    assert mcp_credentials._headers_for_credential(None) == {}


def test_decrypted_bearer_builds_header(monkeypatch):
    monkeypatch.setattr(
        mcp_credentials, "decrypt_credential_payload", lambda _c: {"token": "live-token"}
    )
    headers = mcp_credentials._headers_for_credential(
        {"auth_type": "bearer", "encrypted_payload": b"ciphertext", "key_version": 1}
    )
    assert headers == {AUTHORIZATION_HEADER: "Bearer live-token"}


def test_undecryptable_secret_runs_unauthenticated(monkeypatch, caplog):
    # Decryption seam not wired (MCAT-6.2): returns None -> no headers, with a warning.
    monkeypatch.setattr(mcp_credentials, "decrypt_credential_payload", lambda _c: None)
    with caplog.at_level("WARNING"):
        headers = mcp_credentials._headers_for_credential(
            {"auth_type": "bearer", "encrypted_payload": b"ciphertext", "key_version": 1}
        )
    assert headers == {}
    assert "no decryptable payload" in caplog.text


def test_malformed_payload_degrades_to_no_headers(monkeypatch, caplog):
    # A decrypted payload that does not match its auth_type must not crash discovery.
    monkeypatch.setattr(
        mcp_credentials, "decrypt_credential_payload", lambda _c: {"wrong": "shape"}
    )
    with caplog.at_level("WARNING"):
        headers = mcp_credentials._headers_for_credential(
            {"auth_type": "bearer", "encrypted_payload": b"ciphertext", "key_version": 1}
        )
    assert headers == {}
    assert "malformed" in caplog.text


def test_load_endpoint_auth_headers_swallows_db_errors(monkeypatch, caplog):
    def _raise(_endpoint_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(mcp_credentials.db, "get_mcp_endpoint_credentials", _raise)
    with caplog.at_level("WARNING"):
        headers = mcp_credentials.load_endpoint_auth_headers("endpoint-1")
    assert headers == {}
    assert "failed to load credentials" in caplog.text


def test_load_endpoint_auth_headers_uses_model(monkeypatch):
    monkeypatch.setattr(
        mcp_credentials.db,
        "get_mcp_endpoint_credentials",
        lambda _eid: {"auth_type": "header", "encrypted_payload": b"x", "key_version": 1},
    )
    monkeypatch.setattr(
        mcp_credentials,
        "decrypt_credential_payload",
        lambda _c: {"name": "X-API-Key", "value": "k-123"},
    )
    assert mcp_credentials.load_endpoint_auth_headers("e1") == {"X-API-Key": "k-123"}


@pytest.fixture
def _encryption_key(monkeypatch):
    """Configure a real AES-256 master key so seal/unseal exercise the full crypto path."""
    import base64
    import os

    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)


def test_real_seal_then_decrypt_produces_headers(_encryption_key):
    # End-to-end through the real MCAT-6.2 crypto seam (no monkeypatch of decrypt): a bearer
    # credential sealed at rest is unsealed in-memory and mapped to an Authorization header.
    blob, version = seal_credential_payload({"token": "live-token"})
    headers = mcp_credentials._headers_for_credential(
        {"auth_type": "bearer", "encrypted_payload": blob, "key_version": version}
    )
    assert headers == {AUTHORIZATION_HEADER: "Bearer live-token"}


def test_real_undecryptable_row_runs_unauthenticated(_encryption_key, caplog):
    # A row whose ciphertext cannot be decrypted (foreign bytes) degrades to no auth headers.
    with caplog.at_level("WARNING"):
        headers = mcp_credentials._headers_for_credential(
            {"auth_type": "bearer", "encrypted_payload": b"garbage", "key_version": 1}
        )
    assert headers == {}
    assert "no decryptable payload" in caplog.text
