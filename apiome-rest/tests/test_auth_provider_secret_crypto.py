"""Tests for OAuth provider-secret envelope encryption-at-rest (OLO-8.3, #4969).

Covers the full seal/unseal contract of :mod:`app.auth_provider_secret_crypto`:

* round-trips for representative client secrets (single-key and JSON-map key config),
* that the stored blob carries no plaintext (ciphertext-only at rest),
* key rotation — old rows decrypt under their original id while new secrets use the active key,
* **fail-loud** read path — a stored-but-undecryptable secret (missing/rotated KEK, corrupt blob,
  inconsistent columns) raises :class:`ProviderSecretDecryptionError` rather than silently falling
  back to env,
* the genuinely-absent case (both columns NULL) returns ``None`` (fall back to env),
* fail-closed sealing when encryption is unconfigured,
* startup validation, and
* that secrets and key material never appear in logs or error messages.
"""

import base64
import json
import logging
import os

import pytest

from app.auth_provider_secret_crypto import (
    AuthConfigEncryptionError,
    ProviderSecretDecryptionError,
    needs_reseal,
    provider_secret_encryption_configured,
    reseal_provider_secret,
    seal_provider_secret,
    unseal_provider_secret,
    validate_auth_config_encryption_keys,
)
from app.config import settings


def _b64_key() -> str:
    """A fresh base64-encoded 32-byte AES-256 KEK."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def single_key(monkeypatch):
    """Configure exactly one KEK in the bare (non-JSON) form; return its base64 value."""
    key = _b64_key()
    monkeypatch.setattr(settings, "auth_config_enc_key", key)
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    return key


@pytest.fixture
def map_single(monkeypatch):
    """Configure one KEK via the JSON-map form under id 'v1'."""
    key = _b64_key()
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v1": key}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    return key


@pytest.fixture
def two_keys(monkeypatch):
    """Configure two KEKs (ids 'v1' and 'v2') with 'v2' active."""
    keys = {"v1": _b64_key(), "v2": _b64_key()}
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps(keys))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "v2")
    return keys


@pytest.fixture
def unconfigured(monkeypatch):
    """No KEK configured."""
    monkeypatch.setattr(settings, "auth_config_enc_key", None)
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)


# --------------------------------------------------------------------------------------------------
# Round-trips (the primary acceptance criterion: encrypt → store → read → decrypt == original)
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "secret",
    [
        "gho_1234567890abcdef",
        "a" * 200,  # long secret
        "sü/per+séc=ret",  # non-ASCII + base64-ish punctuation
        "x",  # single char
        "  spaces preserved  ",  # whitespace is significant, not stripped
    ],
)
def test_seal_unseal_round_trip(single_key, secret):
    blob, key_id = seal_provider_secret(secret)
    assert key_id == "default"
    assert isinstance(blob, (bytes, bytearray))
    assert unseal_provider_secret(blob, key_id) == secret


def test_round_trip_map_form(map_single):
    blob, key_id = seal_provider_secret("client-secret-value")
    assert key_id == "v1"  # sole configured id is the active default
    assert unseal_provider_secret(blob, key_id) == "client-secret-value"


def test_active_id_honoured_for_bare_key(monkeypatch, single_key):
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "prod-2026")
    blob, key_id = seal_provider_secret("s")
    assert key_id == "prod-2026"
    assert unseal_provider_secret(blob, key_id) == "s"


def test_each_seal_is_unique(single_key):
    # Fresh DEK + nonce per seal ⇒ same secret seals to unrelated ciphertext.
    a, _ = seal_provider_secret("same-secret")
    b, _ = seal_provider_secret("same-secret")
    assert a != b


def test_ciphertext_contains_no_plaintext(single_key):
    secret = "TOP-SECRET-github-oauth-value"
    blob, _ = seal_provider_secret(secret)
    assert secret.encode("utf-8") not in blob


def test_unseal_accepts_memoryview(single_key):
    blob, key_id = seal_provider_secret("s")
    assert unseal_provider_secret(memoryview(blob), key_id) == "s"


# --------------------------------------------------------------------------------------------------
# Key rotation — old rows decrypt under their original id; new secrets use the active key
# --------------------------------------------------------------------------------------------------
def test_new_secrets_sealed_under_active_id(two_keys):
    _, key_id = seal_provider_secret("s")
    assert key_id == "v2"


def test_old_id_still_decryptable_after_rotation(monkeypatch):
    key1 = _b64_key()
    # Seal under a single key 'v1'.
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v1": key1}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    blob_v1, id_v1 = seal_provider_secret("legacy-secret")
    assert id_v1 == "v1"

    # Rotate: add 'v2', make it active. The old row must still decrypt under 'v1'.
    key2 = _b64_key()
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v1": key1, "v2": key2}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "v2")
    assert unseal_provider_secret(blob_v1, id_v1) == "legacy-secret"
    _, id_new = seal_provider_secret("new-secret")
    assert id_new == "v2"


def test_reseal_moves_row_to_active_id(two_keys, monkeypatch):
    # Seal under 'v1', then reseal under active 'v2'.
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "v1")
    blob_v1, id_v1 = seal_provider_secret("rotate-me")
    assert id_v1 == "v1"
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "v2")
    resealed = reseal_provider_secret(blob_v1, id_v1)
    assert resealed is not None
    blob_v2, id_v2 = resealed
    assert id_v2 == "v2"
    assert unseal_provider_secret(blob_v2, id_v2) == "rotate-me"


def test_needs_reseal_true_when_off_active_id(two_keys):
    assert needs_reseal("v1") is True


def test_needs_reseal_false_when_on_active_id(two_keys):
    assert needs_reseal("v2") is False


def test_needs_reseal_false_when_unconfigured(unconfigured):
    assert needs_reseal("v1") is False


def test_needs_reseal_false_when_no_secret(single_key):
    assert needs_reseal(None) is False


def test_reseal_returns_none_when_no_secret(single_key):
    assert reseal_provider_secret(None, None) is None


# --------------------------------------------------------------------------------------------------
# Absent secret — the ONLY silent path: both columns NULL ⇒ None (fall back to env)
# --------------------------------------------------------------------------------------------------
def test_unseal_absent_secret_returns_none(single_key):
    assert unseal_provider_secret(None, None) is None


def test_unseal_absent_secret_returns_none_even_unconfigured(unconfigured):
    assert unseal_provider_secret(None, None) is None


# --------------------------------------------------------------------------------------------------
# Fail-loud read path (OLO-8.3 acceptance: a stored secret that can't decrypt raises, never silent)
# --------------------------------------------------------------------------------------------------
def test_unseal_inconsistent_columns_raises(single_key):
    blob, key_id = seal_provider_secret("s")
    with pytest.raises(ProviderSecretDecryptionError, match="inconsistent"):
        unseal_provider_secret(blob, None)
    with pytest.raises(ProviderSecretDecryptionError, match="inconsistent"):
        unseal_provider_secret(None, key_id)


def test_unseal_missing_kek_raises(monkeypatch, single_key):
    blob, key_id = seal_provider_secret("s")
    # KEK removed entirely (e.g. env var dropped) but a secret is still stored.
    monkeypatch.setattr(settings, "auth_config_enc_key", None)
    with pytest.raises(ProviderSecretDecryptionError, match="not set"):
        unseal_provider_secret(blob, key_id)


def test_unseal_rotated_away_id_raises(monkeypatch):
    key1 = _b64_key()
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v1": key1}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    blob, key_id = seal_provider_secret("s")
    # 'v1' rotated away, replaced by 'v2' — the old row can no longer be read.
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v2": _b64_key()}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "v2")
    with pytest.raises(ProviderSecretDecryptionError, match="rotated away"):
        unseal_provider_secret(blob, key_id)


def test_unseal_wrong_key_raises(monkeypatch, single_key):
    blob, key_id = seal_provider_secret("s")
    # Same id, different key bytes ⇒ GCM auth fails.
    monkeypatch.setattr(settings, "auth_config_enc_key", _b64_key())
    with pytest.raises(ProviderSecretDecryptionError, match="failed to decrypt"):
        unseal_provider_secret(blob, key_id)


def test_unseal_tampered_ciphertext_raises(single_key, caplog):
    blob, key_id = seal_provider_secret("s")
    tampered = bytearray(blob)
    tampered[-1] ^= 0xFF  # flip a bit in the ciphertext/tag
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ProviderSecretDecryptionError):
            unseal_provider_secret(bytes(tampered), key_id)
    assert "failed to decrypt stored provider secret" in caplog.text


def test_unseal_wrong_id_aad_raises(two_keys):
    # Seal under active 'v2', present it as 'v1' — the AAD binding rejects the re-tag.
    blob, key_id = seal_provider_secret("s")
    assert key_id == "v2"
    with pytest.raises(ProviderSecretDecryptionError):
        unseal_provider_secret(blob, "v1")


def test_unseal_foreign_blob_raises(single_key):
    with pytest.raises(ProviderSecretDecryptionError):
        unseal_provider_secret(b"totally-unrelated-bytes-not-our-format", "default")


def test_unseal_misconfigured_kek_raises(monkeypatch, single_key):
    blob, key_id = seal_provider_secret("s")
    monkeypatch.setattr(settings, "auth_config_enc_key", "not-base64!!!")
    with pytest.raises(ProviderSecretDecryptionError, match="misconfigured"):
        unseal_provider_secret(blob, key_id)


# --------------------------------------------------------------------------------------------------
# Fail-closed sealing & configuration
# --------------------------------------------------------------------------------------------------
def test_seal_unconfigured_raises(unconfigured):
    with pytest.raises(AuthConfigEncryptionError, match="not configured"):
        seal_provider_secret("s")


def test_seal_empty_secret_raises(single_key):
    with pytest.raises(AuthConfigEncryptionError, match="non-empty"):
        seal_provider_secret("")


def test_seal_ambiguous_active_id_raises(monkeypatch, two_keys):
    # Two ids configured, none chosen ⇒ ambiguous which to seal under.
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    with pytest.raises(AuthConfigEncryptionError, match="AUTH_CONFIG_ENC_ACTIVE_KEY_ID"):
        seal_provider_secret("s")


def test_seal_active_id_without_key_raises(monkeypatch, two_keys):
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "does-not-exist")
    with pytest.raises(AuthConfigEncryptionError, match="has no configured KEK"):
        seal_provider_secret("s")


def test_encryption_configured(single_key, monkeypatch):
    assert provider_secret_encryption_configured() is True
    monkeypatch.setattr(settings, "auth_config_enc_key", None)
    assert provider_secret_encryption_configured() is False


def test_encryption_configured_false_on_malformed(monkeypatch):
    monkeypatch.setattr(settings, "auth_config_enc_key", "not-base64!!!")
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    assert provider_secret_encryption_configured() is False


@pytest.mark.parametrize(
    "raw",
    [
        "not-base64!!!",  # bare value, not base64
        base64.b64encode(b"short").decode(),  # bare value, wrong length
        "{}",  # empty JSON object
        '{"v1": 123}',  # value not a string
        '{"v1": "not-base64!!!"}',  # value not base64
        '{"v1": "' + base64.b64encode(b"short").decode() + '"}',  # wrong length
        '{"": "' + base64.b64encode(b"x" * 32).decode() + '"}',  # blank id
    ],
)
def test_validate_rejects_malformed_keys(monkeypatch, raw):
    monkeypatch.setattr(settings, "auth_config_enc_key", raw)
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    with pytest.raises(AuthConfigEncryptionError):
        validate_auth_config_encryption_keys()


def test_validate_rejects_active_id_without_key(monkeypatch, map_single):
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", "nope")
    with pytest.raises(AuthConfigEncryptionError, match="active key id 'nope'"):
        validate_auth_config_encryption_keys()


def test_validate_rejects_ambiguous_active_id(monkeypatch, two_keys):
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    with pytest.raises(AuthConfigEncryptionError, match="AUTH_CONFIG_ENC_ACTIVE_KEY_ID"):
        validate_auth_config_encryption_keys()


def test_validate_unconfigured_is_ok(unconfigured):
    # No KEK configured is acceptable — the server starts.
    validate_auth_config_encryption_keys()


def test_validate_well_formed_bare_key_ok(single_key):
    validate_auth_config_encryption_keys()


def test_validate_well_formed_map_ok(two_keys):
    validate_auth_config_encryption_keys()


def test_urlsafe_base64_key_accepted(monkeypatch):
    # A url-safe base64 KEK (as Fernet.generate_key produces) must decode too.
    key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setattr(settings, "auth_config_enc_key", key)
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    blob, key_id = seal_provider_secret("s")
    assert unseal_provider_secret(blob, key_id) == "s"


# --------------------------------------------------------------------------------------------------
# Secrets & key material never appear in logs / error messages
# --------------------------------------------------------------------------------------------------
def test_secret_absent_from_decrypt_failure_logs(single_key, caplog):
    secret = "ultra-secret-value-do-not-log"
    blob, key_id = seal_provider_secret(secret)
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ProviderSecretDecryptionError) as exc:
            unseal_provider_secret(bytes(tampered), key_id)
    assert secret not in caplog.text
    assert secret not in str(exc.value)


def test_kek_absent_from_validation_errors(monkeypatch):
    # A wrong-length key triggers an error; the (would-be) key material must not leak into it.
    bad_key = base64.b64encode(b"k" * 31).decode()  # 31 bytes ⇒ wrong length
    monkeypatch.setattr(settings, "auth_config_enc_key", json.dumps({"v1": bad_key}))
    monkeypatch.setattr(settings, "auth_config_enc_active_key_id", None)
    with pytest.raises(AuthConfigEncryptionError) as exc:
        validate_auth_config_encryption_keys()
    assert bad_key not in str(exc.value)
