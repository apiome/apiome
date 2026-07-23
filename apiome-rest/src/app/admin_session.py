"""Server-side verification of the signed super-admin session (OLO-8.4, #4970).

The provider-config admin surface (``GET/PUT /v1/admin/auth-providers``,
:mod:`app.auth_provider_config_routes`) edits OAuth **client secrets**, so it must be gated by a
super-admin check *verified server-side* — a client claim of "I am admin" is never trusted.

The super-admin principal is minted by the Next.js ``/admin`` portal (OLO-8.1,
``apiome-ui/lib/auth/admin-session.ts``) as an HMAC-SHA256-signed token carrying an issued-at
(``iat``) and expiry (``exp``). Rather than invent a second, divergent admin credential for REST,
this module re-implements the *same* verification in Python so the one token the operator already
holds authorizes both surfaces. The admin API route in the UI forwards that token to REST (as the
``admin_session`` cookie or an ``X-Admin-Session`` header) and REST verifies it here.

Verification is intentionally byte-for-byte compatible with the TypeScript minter:

* token shape ``"<base64url(payload)>.<base64url(HMAC-SHA256(payload))>"``,
* payload ``{"v": 1, "sub": "admin", "iat": <ms>, "exp": <ms>}`` (epoch **milliseconds**),
* base64url **without** padding (Node's ``Buffer.toString('base64url')``),
* the signature is compared in constant time and the expiry is enforced on every read.

Signing-key resolution mirrors the UI (``resolveSigningKey``): the dedicated
``ADMIN_SESSION_SECRET`` is preferred; otherwise a stable key is derived from ``ADMIN_PASSWORD``
as ``"apiome-admin-session:<password>"``. With neither configured there is no key and the surface
fails closed — no token can be verified, so every caller is rejected.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import time
from hashlib import sha256
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

# Payload format version. A token whose ``v`` differs is rejected, so the shape can evolve without
# silently accepting an old (or future) format. Must match ADMIN_SESSION_VERSION in the UI.
_ADMIN_SESSION_VERSION = 1

# Fixed subject claim — the admin portal has exactly one principal. Must match the UI.
_ADMIN_SESSION_SUBJECT = "admin"


def _resolve_signing_key() -> Optional[str]:
    """Resolve the HMAC signing key, or ``None`` when no secret is configured.

    Mirrors ``resolveSigningKey`` in ``admin-session.ts`` so REST and the UI verify against the
    same key: the dedicated ``ADMIN_SESSION_SECRET`` wins; otherwise the key is derived from
    ``ADMIN_PASSWORD`` (namespaced so it can never collide with the raw password used elsewhere).

    Returns:
        The signing-key string, or ``None`` when neither secret is set (the surface then fails
        closed — every token verification returns ``False``).
    """
    dedicated = (settings.admin_session_secret or "").strip()
    if dedicated:
        return dedicated

    password = (settings.admin_password or "").strip()
    if password:
        return f"apiome-admin-session:{password}"

    return None


def _b64url_decode(segment: str) -> bytes:
    """Decode an unpadded base64url string (the token encoding used by the UI).

    Node emits base64url without ``=`` padding; Python's decoder requires the padding, so it is
    restored before decoding.

    Args:
        segment: The base64url text (no padding) to decode.

    Returns:
        The decoded bytes.

    Raises:
        ValueError / binascii.Error: If ``segment`` is not valid base64url.
    """
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def _sign(encoded_payload: str, key: str) -> str:
    """Return the unpadded base64url HMAC-SHA256 of ``encoded_payload`` under ``key``.

    Matches the UI's ``sign()`` (``createHmac('sha256', key).update(payload).digest('base64url')``).
    """
    digest = hmac.new(key.encode("utf-8"), encoded_payload.encode("utf-8"), sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verify_admin_session_token(
    token: Optional[str], now_ms: Optional[int] = None
) -> bool:
    """Verify a signed super-admin session token: signature first, then expiry.

    A token is accepted only when its signature verifies under the configured key (constant-time
    comparison), its payload is well-formed for the current version and subject, and it has not
    expired. Any other outcome — absent token, no configured key, malformed token/payload, bad
    signature, or expiry — returns ``False`` (fail closed). This is the exact contract of
    ``verifyAdminSessionToken`` in ``admin-session.ts``.

    Args:
        token: The raw token string (cookie or header value), or ``None`` when absent.
        now_ms: Current time in epoch **milliseconds** (injectable for tests); defaults to the
            wall clock. Milliseconds because the payload's ``iat``/``exp`` are minted in ms by the
            UI.

    Returns:
        ``True`` only when the token is present, correctly signed, unexpired, and well-formed.
    """
    if not token:
        return False

    key = _resolve_signing_key()
    if not key:
        return False

    dot = token.find(".")
    if dot <= 0 or dot == len(token) - 1:
        return False

    encoded = token[:dot]
    signature = token[dot + 1:]

    # Reject any tampered token before trusting a single byte of its payload. hmac.compare_digest
    # is constant-time and tolerates unequal lengths (unlike a raw ``==``).
    if not hmac.compare_digest(signature, _sign(encoded, key)):
        return False

    try:
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False

    if not isinstance(payload, dict):
        return False
    if payload.get("v") != _ADMIN_SESSION_VERSION:
        return False
    if payload.get("sub") != _ADMIN_SESSION_SUBJECT:
        return False

    exp = payload.get("exp")
    iat = payload.get("iat")
    # bool is a subclass of int; exclude it so a stray ``true`` cannot masquerade as a timestamp.
    if not isinstance(exp, int) or isinstance(exp, bool):
        return False
    if not isinstance(iat, int) or isinstance(iat, bool):
        return False

    current_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    return exp > current_ms
