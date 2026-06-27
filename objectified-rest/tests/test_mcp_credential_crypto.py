"""Tests for MCP credential envelope encryption-at-rest (MCAT-6.2, #3678).

Covers the full seal/unseal contract of :mod:`app.mcp_credential_crypto`:

* round-trips for representative auth payloads,
* that the database blob carries no plaintext (ciphertext-only at rest),
* key rotation — old rows decrypt under their original version while new secrets use the active key,
* fail-safe decryption (tampered/foreign/wrong-version blobs, missing key) returns ``None``,
* fail-closed sealing when encryption is unconfigured,
* startup validation, and
* that secrets never appear in logs.
"""

import base64
import json
import logging
import os

import pytest

from app.config import settings
from app.mcp_credential_crypto import (
    CredentialEncryptionError,
    credential_encryption_configured,
    needs_reseal,
    reseal_credential_payload,
    seal_credential_payload,
    unseal_credential_payload,
    validate_credential_encryption_keys,
)


def _b64_key() -> str:
    """A fresh base64-encoded 32-byte AES-256 master key."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def single_key(monkeypatch):
    """Configure exactly one master key (version 1) and return its base64 value."""
    key = _b64_key()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    return key


@pytest.fixture
def two_keys(monkeypatch):
    """Configure two master keys (versions 1 and 2) with version 2 active."""
    keys = {"1": _b64_key(), "2": _b64_key()}
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps(keys))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 2)
    return keys


@pytest.fixture
def unconfigured(monkeypatch):
    """No master key configured."""
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)


# --------------------------------------------------------------------------------------------------
# Round-trips
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        {"token": "secret-bearer-token"},
        {"name": "X-API-Key", "value": "k-12345"},
        {"access_token": "at-abc", "token_type": "Bearer"},
        {"vars": {"API_KEY": "v", "REGION": "us-east-1"}},
        {},
    ],
)
def test_seal_unseal_round_trip(single_key, payload):
    blob, version = seal_credential_payload(payload)
    assert version == 1
    assert isinstance(blob, (bytes, bytearray))
    assert unseal_credential_payload(blob, version) == payload


def test_each_seal_is_unique(single_key):
    # Fresh DEK + nonce per seal: two seals of the same payload produce different ciphertext.
    blob_a, _ = seal_credential_payload({"token": "same"})
    blob_b, _ = seal_credential_payload({"token": "same"})
    assert blob_a != blob_b
    assert unseal_credential_payload(blob_a, 1) == {"token": "same"}
    assert unseal_credential_payload(blob_b, 1) == {"token": "same"}


def test_ciphertext_contains_no_plaintext(single_key):
    # The stored blob must be ciphertext only — the secret must not be recoverable by scanning bytes.
    secret = "super-secret-token-value-9f3a"
    blob, _ = seal_credential_payload({"token": secret})
    assert secret.encode("utf-8") not in blob
    assert b"token" not in blob


def test_unseal_accepts_memoryview(single_key):
    # psycopg may hand back BYTEA as a memoryview; unseal must coerce it.
    blob, version = seal_credential_payload({"token": "mv"})
    assert unseal_credential_payload(memoryview(blob), version) == {"token": "mv"}


# --------------------------------------------------------------------------------------------------
# Key rotation
# --------------------------------------------------------------------------------------------------
def test_new_secrets_sealed_under_active_version(two_keys):
    _, version = seal_credential_payload({"token": "t"})
    assert version == 2  # active version, not the lowest


def test_old_version_still_decryptable_after_rotation(monkeypatch):
    # Seal under v1 (only key present), then add v2 as the active key — the old blob still decrypts.
    key1 = _b64_key()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key1}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    blob_v1, version = seal_credential_payload({"token": "legacy"})
    assert version == 1

    key2 = _b64_key()
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": key1, "2": key2})
    )
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 2)

    # Old row still decrypts under its original version...
    assert unseal_credential_payload(blob_v1, 1) == {"token": "legacy"}
    # ...and a new secret seals under the active version.
    _, new_version = seal_credential_payload({"token": "fresh"})
    assert new_version == 2


def test_reseal_moves_row_to_active_version(two_keys, monkeypatch):
    # Seal under v1 explicitly, then reseal -> should land on the active version (2).
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 1)
    blob_v1, v1 = seal_credential_payload({"token": "rotate-me"})
    assert v1 == 1

    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 2)
    assert needs_reseal(1) is True
    resealed = reseal_credential_payload(blob_v1, 1)
    assert resealed is not None
    new_blob, new_version = resealed
    assert new_version == 2
    assert new_blob != blob_v1
    assert unseal_credential_payload(new_blob, 2) == {"token": "rotate-me"}


def test_needs_reseal_false_when_on_active_version(two_keys):
    assert needs_reseal(2) is False


def test_needs_reseal_false_when_unconfigured(unconfigured):
    assert needs_reseal(1) is False


def test_reseal_returns_none_for_undecryptable_blob(single_key):
    assert reseal_credential_payload(b"not-a-real-blob", 1) is None


# --------------------------------------------------------------------------------------------------
# Fail-safe decryption
# --------------------------------------------------------------------------------------------------
def test_unseal_none_inputs_return_none(single_key):
    assert unseal_credential_payload(None, 1) is None
    assert unseal_credential_payload(b"", 1) is None
    assert unseal_credential_payload(b"x", None) is None


def test_unseal_unknown_version_returns_none(single_key, caplog):
    blob, _ = seal_credential_payload({"token": "t"})
    with caplog.at_level(logging.WARNING):
        assert unseal_credential_payload(blob, 99) is None
    assert "no MCP credential master key configured for key_version=99" in caplog.text


def test_unseal_wrong_key_returns_none(monkeypatch):
    # A blob sealed under one key must not decrypt under a different key occupying the same version.
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": _b64_key()})
    )
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    blob, _ = seal_credential_payload({"token": "t"})

    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": _b64_key()})
    )
    assert unseal_credential_payload(blob, 1) is None


def test_unseal_wrong_version_aad_returns_none(two_keys):
    # Seal under the active version (2), then claim it is version 1: the key-version is bound into
    # the GCM AAD, so authentication fails even though a key for version 1 exists.
    blob, version = seal_credential_payload({"token": "t"})
    assert version == 2
    assert unseal_credential_payload(blob, 1) is None


def test_unseal_tampered_ciphertext_returns_none(single_key, caplog):
    blob, version = seal_credential_payload({"token": "t"})
    tampered = bytearray(blob)
    tampered[-1] ^= 0xFF  # flip a bit in the ciphertext/tag
    with caplog.at_level(logging.WARNING):
        assert unseal_credential_payload(bytes(tampered), version) is None
    assert "failed to decrypt MCP credential" in caplog.text


def test_unseal_foreign_blob_returns_none(single_key):
    assert unseal_credential_payload(b"totally-unrelated-bytes-not-our-format", 1) is None


def test_unseal_unconfigured_returns_none(unconfigured):
    # A row sealed earlier but with encryption now turned off: decrypt is a no-op, not a crash.
    assert unseal_credential_payload(b"some-bytes", 1) is None


# --------------------------------------------------------------------------------------------------
# Fail-closed sealing & configuration
# --------------------------------------------------------------------------------------------------
def test_seal_unconfigured_raises(unconfigured):
    with pytest.raises(CredentialEncryptionError, match="not configured"):
        seal_credential_payload({"token": "t"})


def test_credential_encryption_configured(single_key, monkeypatch):
    assert credential_encryption_configured() is True
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    assert credential_encryption_configured() is False


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",  # not an object
        "{}",  # empty object
        '{"one": "' + base64.b64encode(b"x" * 32).decode() + '"}',  # non-integer version
        '{"1": 123}',  # key not a string
        '{"1": "not-base64!!!"}',  # not base64
        '{"1": "' + base64.b64encode(b"short").decode() + '"}',  # wrong length
        '{"0": "' + base64.b64encode(b"x" * 32).decode() + '"}',  # version < 1
    ],
)
def test_validate_rejects_malformed_keys(monkeypatch, raw):
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", raw)
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    with pytest.raises(CredentialEncryptionError):
        validate_credential_encryption_keys()


def test_validate_rejects_active_version_without_key(monkeypatch, single_key):
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 5)
    with pytest.raises(CredentialEncryptionError, match="active key-version 5"):
        validate_credential_encryption_keys()


def test_validate_unconfigured_is_ok(unconfigured):
    # No keys configured is acceptable — the server starts.
    validate_credential_encryption_keys()


def test_validate_well_formed_keys_ok(single_key):
    validate_credential_encryption_keys()


def test_seal_active_version_without_key_raises(monkeypatch, single_key):
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", 7)
    with pytest.raises(CredentialEncryptionError, match="active key-version 7"):
        seal_credential_payload({"token": "t"})


# --------------------------------------------------------------------------------------------------
# Secrets never appear in logs
# --------------------------------------------------------------------------------------------------
def test_secret_absent_from_decrypt_failure_logs(single_key, caplog):
    secret = "ultra-secret-value-do-not-log"
    blob, version = seal_credential_payload({"token": secret})
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    with caplog.at_level(logging.WARNING):
        unseal_credential_payload(bytes(tampered), version)
    assert secret not in caplog.text


def test_master_key_absent_from_validation_errors(monkeypatch):
    secret_key = base64.b64encode(b"k" * 31).decode()  # wrong length triggers an error
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": secret_key}))
    with pytest.raises(CredentialEncryptionError) as exc:
        validate_credential_encryption_keys()
    assert secret_key not in str(exc.value)
