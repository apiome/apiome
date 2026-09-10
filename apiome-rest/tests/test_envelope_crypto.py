"""The shared envelope cipher — SDK-4.1 (#4495).

:mod:`app.envelope_crypto` is the scheme MCAT-6.2's MCP credentials and SDK-4.1's registry tokens
both use. Its own tests are about the properties two vaults must *share*: that a payload survives
a round trip, that nothing usable survives without the key, and that one vault cannot open
another's blob even under a shared master key — which is the whole reason the magic is a
parameter.

The MCP vault's own behaviour is asserted in ``test_mcp_credential_crypto.py``; those tests are
also what proves this extraction preserved the stored format.
"""

from __future__ import annotations

import base64
import json
import logging

import pytest

from app.envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError

_KEY_ONE = base64.b64encode(b"1" * 32).decode()
_KEY_TWO = base64.b64encode(b"2" * 32).decode()


class _Env:
    """A mutable stand-in for the process settings a vault reads its keys from."""

    def __init__(self, keys=None, active=None):
        self.keys = keys
        self.active = active


def _cipher(env: _Env, magic: bytes = b"TSTV") -> EnvelopeCipher:
    """Build a cipher reading from ``env``."""
    return EnvelopeCipher(
        magic=magic,
        subject="test secret",
        keys_setting="APIOME_TEST_KEYS",
        read_keys=lambda: env.keys,
        read_active_version=lambda: env.active,
    )


@pytest.fixture
def env() -> _Env:
    """One configured master key, version 1."""
    return _Env(keys=json.dumps({"1": _KEY_ONE}))


# --------------------------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------------------------
def test_magic_must_be_four_bytes():
    """A short or long magic would shift every offset in the blob; refuse at construction."""
    with pytest.raises(ValueError, match="four bytes|4 bytes"):
        EnvelopeCipher(
            magic=b"AB",
            subject="s",
            keys_setting="X",
            read_keys=lambda: None,
            read_active_version=lambda: None,
        )


# --------------------------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------------------------
def test_seal_and_unseal_round_trips(env):
    cipher = _cipher(env)
    blob, version = cipher.seal({"token": "s3cr3t-value", "note": "hello"})
    assert version == 1
    assert cipher.unseal(blob, version) == {"token": "s3cr3t-value", "note": "hello"}


def test_ciphertext_never_contains_the_plaintext(env):
    cipher = _cipher(env)
    blob, _ = cipher.seal({"token": "unique-plaintext-marker"})
    assert b"unique-plaintext-marker" not in blob


def test_two_seals_of_one_payload_differ(env):
    """A fresh data key and nonce per secret: identical tokens must not look identical at rest."""
    cipher = _cipher(env)
    first, _ = cipher.seal({"token": "same"})
    second, _ = cipher.seal({"token": "same"})
    assert first != second


def test_tampering_is_detected(env):
    cipher = _cipher(env)
    blob, version = cipher.seal({"token": "value"})
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    assert cipher.unseal(bytes(tampered), version) is None


# --------------------------------------------------------------------------------------------
# Vault isolation — the reason `magic` is a parameter
# --------------------------------------------------------------------------------------------
def test_one_vault_cannot_open_anothers_blob_even_on_a_shared_key(env):
    """The magic is bound into the AAD, so a blob does not authenticate in the wrong vault."""
    mine = _cipher(env, magic=b"AAAA")
    theirs = _cipher(env, magic=b"BBBB")
    blob, version = mine.seal({"token": "value"})
    assert theirs.unseal(blob, version) is None
    assert mine.unseal(blob, version) == {"token": "value"}


def test_a_blob_cannot_be_re_tagged_to_another_key_version(env):
    """The key-version is authenticated data, not merely a column."""
    env.keys = json.dumps({"1": _KEY_ONE, "2": _KEY_TWO})
    cipher = _cipher(env)
    env.active = 1
    blob, _ = cipher.seal({"token": "value"})
    assert cipher.unseal(blob, 2) is None


# --------------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------------
def test_unconfigured_seal_fails_closed():
    cipher = _cipher(_Env(keys=None))
    with pytest.raises(EnvelopeEncryptionError, match="not configured"):
        cipher.seal({"token": "value"})


def test_unconfigured_unseal_returns_none_rather_than_raising():
    """A caller that cannot decrypt degrades; it does not crash."""
    assert _cipher(_Env(keys=None)).unseal(b"anything-at-all", 1) is None


def test_validate_accepts_no_keys_but_rejects_malformed_ones():
    _cipher(_Env(keys=None)).validate()  # the server still starts
    with pytest.raises(EnvelopeEncryptionError):
        _cipher(_Env(keys="not json")).validate()


def test_validate_rejects_an_active_version_with_no_key(env):
    env.active = 9
    with pytest.raises(EnvelopeEncryptionError, match="active key-version 9"):
        _cipher(env).validate()


def test_configured_is_false_when_the_key_map_is_broken():
    assert _cipher(_Env(keys='{"1": "not-base64!!!"}')).configured() is False


def test_the_active_version_defaults_to_the_highest(env):
    env.keys = json.dumps({"1": _KEY_ONE, "3": _KEY_TWO})
    _, version = _cipher(env).seal({"token": "value"})
    assert version == 3


# --------------------------------------------------------------------------------------------
# Rotation
# --------------------------------------------------------------------------------------------
def test_reseal_moves_a_row_onto_the_active_key(env):
    env.keys = json.dumps({"1": _KEY_ONE, "2": _KEY_TWO})
    env.active = 1
    cipher = _cipher(env)
    blob, version = cipher.seal({"token": "rotate-me"})
    assert cipher.needs_reseal(version) is False

    env.active = 2
    assert cipher.needs_reseal(version) is True
    resealed, new_version = cipher.reseal(blob, version)
    assert new_version == 2
    assert cipher.unseal(resealed, new_version) == {"token": "rotate-me"}
    # The old blob still opens under the key that sealed it — rotation is not a cliff.
    assert cipher.unseal(blob, version) == {"token": "rotate-me"}


def test_reseal_of_an_unopenable_blob_is_none(env):
    assert _cipher(env).reseal(b"foreign-bytes-that-are-long-enough-to-parse", 1) is None


# --------------------------------------------------------------------------------------------
# Secrets never reach a log or an error
# --------------------------------------------------------------------------------------------
def test_no_secret_in_decrypt_failure_logs(env, caplog):
    cipher = _cipher(env)
    secret = "do-not-log-this-value"
    blob, version = cipher.seal({"token": secret})
    tampered = bytearray(blob)
    tampered[-1] ^= 0x01
    with caplog.at_level(logging.WARNING):
        cipher.unseal(bytes(tampered), version)
    assert secret not in caplog.text


def test_no_master_key_in_validation_errors():
    key = base64.b64encode(b"k" * 31).decode()  # wrong length: triggers the error
    with pytest.raises(EnvelopeEncryptionError) as exc:
        _cipher(_Env(keys=json.dumps({"1": key}))).validate()
    assert key not in str(exc.value)


def test_the_error_names_the_setting_to_configure():
    """An operator reading the message must be told which variable to set."""
    with pytest.raises(EnvelopeEncryptionError, match="APIOME_TEST_KEYS"):
        _cipher(_Env(keys="not json")).validate()
