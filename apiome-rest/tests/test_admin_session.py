"""Tests for server-side super-admin session verification (OLO-8.4, #4970).

:mod:`app.admin_session` re-implements, in Python, the exact HMAC-signed token the Next.js
``/admin`` portal mints (OLO-8.1, ``apiome-ui/lib/auth/admin-session.ts``). These tests pin that
byte-for-byte compatibility — a token minted the way the UI mints it must verify here — and the
fail-closed contract: forged/expired/malformed tokens, and the no-signing-key case, are rejected.
"""

import base64
import hmac
import json
from hashlib import sha256

import pytest

from app.admin_session import verify_admin_session_token
from app.config import settings

# 8 hours in ms, matching ADMIN_SESSION_MAX_AGE_MS in the UI.
_MAX_AGE_MS = 8 * 60 * 60 * 1000
_NOW = 1_700_000_000_000  # a fixed "now" in epoch ms


def _b64url(raw: bytes) -> str:
    """Unpadded base64url, exactly as Node's ``Buffer.toString('base64url')`` emits."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _mint(
    key: str,
    *,
    v: int = 1,
    sub: str = "admin",
    iat: int = _NOW,
    exp: int = _NOW + _MAX_AGE_MS,
) -> str:
    """Mint a token the way ``createAdminSessionToken`` does, with overridable claims for tests."""
    payload = {"v": v, "sub": sub, "iat": iat, "exp": exp}
    encoded = _b64url(json.dumps(payload).encode("utf-8"))
    sig = _b64url(hmac.new(key.encode("utf-8"), encoded.encode("utf-8"), sha256).digest())
    return f"{encoded}.{sig}"


@pytest.fixture
def dedicated_secret(monkeypatch):
    """Configure a dedicated ADMIN_SESSION_SECRET; return it."""
    secret = "dedicated-admin-secret"
    monkeypatch.setattr(settings, "admin_session_secret", secret)
    monkeypatch.setattr(settings, "admin_password", None)
    return secret


def test_valid_token_verifies(dedicated_secret):
    """A correctly-signed, unexpired token verifies under the configured key."""
    token = _mint(dedicated_secret)
    assert verify_admin_session_token(token, now_ms=_NOW) is True


def test_cross_impl_reference_token(dedicated_secret):
    """A token minted exactly as the Node reference does verifies (compat regression guard)."""
    # This encoded/sig pair was produced by the TS minter under key 'dedicated-admin-secret'
    # with iat=_NOW, exp=_NOW+8h — recomputed here so the test is self-contained.
    token = _mint(dedicated_secret)
    encoded, sig = token.split(".", 1)
    expected_sig = _b64url(
        hmac.new(dedicated_secret.encode(), encoded.encode(), sha256).digest()
    )
    assert sig == expected_sig
    assert verify_admin_session_token(token, now_ms=_NOW) is True


def test_missing_token_rejected(dedicated_secret):
    """Absent token (None / empty) is rejected."""
    assert verify_admin_session_token(None, now_ms=_NOW) is False
    assert verify_admin_session_token("", now_ms=_NOW) is False


def test_tampered_signature_rejected(dedicated_secret):
    """A token whose signature was altered fails the constant-time comparison."""
    token = _mint(dedicated_secret)
    encoded, sig = token.split(".", 1)
    forged = encoded + "." + ("A" * len(sig))
    assert verify_admin_session_token(forged, now_ms=_NOW) is False


def test_tampered_payload_rejected(dedicated_secret):
    """Editing the payload without re-signing (privilege the exp) is rejected."""
    token = _mint(dedicated_secret)
    _, sig = token.split(".", 1)
    evil_payload = _b64url(
        json.dumps({"v": 1, "sub": "admin", "iat": _NOW, "exp": _NOW + 10 * _MAX_AGE_MS}).encode()
    )
    assert verify_admin_session_token(f"{evil_payload}.{sig}", now_ms=_NOW) is False


def test_wrong_key_rejected(dedicated_secret):
    """A token signed under a different key does not verify."""
    token = _mint("some-other-key")
    assert verify_admin_session_token(token, now_ms=_NOW) is False


def test_expired_token_rejected(dedicated_secret):
    """A token past its expiry is rejected even with a valid signature."""
    token = _mint(dedicated_secret, iat=_NOW - 2 * _MAX_AGE_MS, exp=_NOW - _MAX_AGE_MS)
    assert verify_admin_session_token(token, now_ms=_NOW) is False


def test_exactly_at_expiry_rejected(dedicated_secret):
    """Expiry is strict (``exp > now``): a token whose exp equals now is rejected."""
    token = _mint(dedicated_secret, exp=_NOW)
    assert verify_admin_session_token(token, now_ms=_NOW) is False


def test_wrong_version_rejected(dedicated_secret):
    """A payload with an unrecognised version is rejected (properly signed)."""
    token = _mint(dedicated_secret, v=2)
    assert verify_admin_session_token(token, now_ms=_NOW) is False


def test_wrong_subject_rejected(dedicated_secret):
    """A payload whose subject is not 'admin' is rejected (properly signed)."""
    token = _mint(dedicated_secret, sub="user")
    assert verify_admin_session_token(token, now_ms=_NOW) is False


def test_malformed_tokens_rejected(dedicated_secret):
    """Structurally broken tokens (no dot, empty segments, garbage payload) are rejected."""
    assert verify_admin_session_token("no-dot-here", now_ms=_NOW) is False
    assert verify_admin_session_token(".sig", now_ms=_NOW) is False
    assert verify_admin_session_token("payload.", now_ms=_NOW) is False
    # Valid signature over non-JSON payload → JSON decode fails → rejected.
    garbage = "!!!notbase64!!!"
    sig = _b64url(hmac.new(dedicated_secret.encode(), garbage.encode(), sha256).digest())
    assert verify_admin_session_token(f"{garbage}.{sig}", now_ms=_NOW) is False


def test_non_int_exp_rejected(dedicated_secret):
    """A payload whose exp is a non-integer (or bool) is rejected."""
    for bad_exp in ("later", True, None):
        payload = {"v": 1, "sub": "admin", "iat": _NOW, "exp": bad_exp}
        encoded = _b64url(json.dumps(payload).encode())
        sig = _b64url(hmac.new(dedicated_secret.encode(), encoded.encode(), sha256).digest())
        assert verify_admin_session_token(f"{encoded}.{sig}", now_ms=_NOW) is False


def test_no_signing_key_fails_closed(monkeypatch):
    """With neither ADMIN_SESSION_SECRET nor ADMIN_PASSWORD set, every token is rejected."""
    monkeypatch.setattr(settings, "admin_session_secret", None)
    monkeypatch.setattr(settings, "admin_password", None)
    # Even a token that would verify under *some* key cannot verify when no key is configured.
    assert verify_admin_session_token(_mint("anything"), now_ms=_NOW) is False


def test_password_derived_key(monkeypatch):
    """When only ADMIN_PASSWORD is set, the derived key 'apiome-admin-session:<pw>' verifies."""
    monkeypatch.setattr(settings, "admin_session_secret", None)
    monkeypatch.setattr(settings, "admin_password", "hunter2")
    token = _mint("apiome-admin-session:hunter2")
    assert verify_admin_session_token(token, now_ms=_NOW) is True
    # A token signed under the raw password (not the namespaced derived key) must NOT verify.
    assert verify_admin_session_token(_mint("hunter2"), now_ms=_NOW) is False


def test_dedicated_secret_preferred_over_password(monkeypatch):
    """ADMIN_SESSION_SECRET wins when both are set (mirrors resolveSigningKey order)."""
    monkeypatch.setattr(settings, "admin_session_secret", "dedicated")
    monkeypatch.setattr(settings, "admin_password", "hunter2")
    assert verify_admin_session_token(_mint("dedicated"), now_ms=_NOW) is True
    assert verify_admin_session_token(
        _mint("apiome-admin-session:hunter2"), now_ms=_NOW
    ) is False
