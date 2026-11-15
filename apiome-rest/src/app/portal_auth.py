"""Portal readers — the shared vocabulary of PCX-1.1 (#5889).

A **reader** is a person who reads a tenant's published APIs in Browse without being a member of
its workspace. There is no second identity system: a reader is an ordinary ``users`` row, and what
makes them a reader of a tenant is a ``portal_memberships`` row (apiome-db V378). A reader signs in
with a **magic link** — a one-time token mailed to them, valid for 15 minutes — and exchanges it for
a **reader session**: an opaque, tenant-bound token Browse keeps in an ``HttpOnly`` cookie and
forwards to apiome-rest as ``Authorization: Reader <token>``.

A reader session is **never a REST credential** outside the ``browse`` and ``portal-auth`` tags:
``validate_authentication`` only understands JWTs and workspace API keys, so the ``Reader`` scheme
is refused everywhere else without any code having to remember to refuse it
(``tests/test_portal_reader_rest_refusal.py`` sweeps every ``GET`` route to prove it).

This module holds only data and pure helpers: the vocabularies, refusal codes, the refusal
exception, token minting and hashing, the ``return_to`` and email guards, the user-agent family,
and the request/response models. The routes are :mod:`app.portal_auth_routes`; the storage logic is
:mod:`app.portal_auth_store`.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime
from typing import Literal, Optional, Tuple

import bcrypt
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CODE_INVALID_EMAIL",
    "CODE_INVALID_RETURN_TO",
    "CODE_RATE_LIMITED",
    "CODE_SESSION_INVALID",
    "CODE_TOKEN_EXPIRED",
    "CODE_TOKEN_INVALID",
    "CODE_TOKEN_USED",
    "MAGIC_LINK_PREFIX",
    "MAGIC_LINK_TTL_MINUTES",
    "MEMBERSHIP_ACTIVE",
    "MEMBERSHIP_INVITED",
    "MEMBERSHIP_REVOKED",
    "READER_SCHEME",
    "SESSION_TOKEN_PREFIX",
    "SOURCE_MAGIC_LINK",
    "AUDIT_ENROLLED",
    "AUDIT_SESSION_REVOKED",
    "AUDIT_SIGNED_IN",
    "MagicLinkAccepted",
    "MagicLinkRequest",
    "PortalAuthError",
    "ReaderProfile",
    "ReaderSessionGrant",
    "TokenExchange",
    "hash_session_token",
    "mint_magic_link_token",
    "mint_session_token",
    "normalize_email",
    "reader_token_from_header",
    "safe_return_to",
    "split_magic_link_token",
    "user_agent_family",
    "verify_magic_link_token",
]

#: The ``Authorization`` scheme a reader session travels in. Deliberately not ``Bearer``: nothing
#: that parses a bearer JWT or API key will ever mistake a reader token for one.
READER_SCHEME = "Reader"

#: Membership states. Mirror ``portal_memberships_status_check``.
MEMBERSHIP_INVITED = "invited"
MEMBERSHIP_ACTIVE = "active"
MEMBERSHIP_REVOKED = "revoked"

#: How a membership came to be. PCX-1.1 only writes ``magic_link``; the others are reserved for
#: PCX-1.2 (``domain``), PCX-1.5 (``sso``) and PCX-1.6 (``invite``).
SOURCE_MAGIC_LINK = "magic_link"

#: A magic link is refused this many minutes after it was issued.
MAGIC_LINK_TTL_MINUTES = 15

#: Public prefixes, so a leaked token is recognisable in a log or a secret scanner.
MAGIC_LINK_PREFIX = "pml_"
SESSION_TOKEN_PREFIX = "prs_"

#: Access-audit actions (``apiome.access_audit``). Metadata only — never a token.
AUDIT_ENROLLED = "portal.reader.enrolled"
AUDIT_SIGNED_IN = "portal.reader.signed_in"
AUDIT_SESSION_REVOKED = "portal.reader.session_revoked"

# Stable refusal codes. A client branches on the code, never on the message.
CODE_INVALID_EMAIL = "portal-invalid-email"
CODE_INVALID_RETURN_TO = "portal-invalid-return-to"
CODE_TOKEN_INVALID = "portal-token-invalid"
CODE_TOKEN_EXPIRED = "portal-token-expired"
CODE_TOKEN_USED = "portal-token-used"
CODE_SESSION_INVALID = "portal-session-invalid"
CODE_RATE_LIMITED = "portal-rate-limited"

#: bcrypt cost for magic-link tokens, matching workspace and agent keys.
_BCRYPT_ROUNDS = 10
#: Hex characters of random lookup id in a magic-link token (64 bits).
_LOOKUP_HEX = 16
#: Hex characters of the secret (192 bits). bcrypt reads only the first 72 bytes of its input, so
#: the whole token — ``pml_`` + 16 + ``.`` + 48 = 69 bytes — must fit for every byte to count.
_SECRET_HEX = 48
#: The longest address RFC 5321 allows in a forward path.
_MAX_EMAIL_LENGTH = 254
#: The longest ``return_to`` stored (mirrors ``portal_magic_links.return_to``).
_MAX_RETURN_TO_LENGTH = 1024

#: A pragmatic address shape: one ``@``, no whitespace, a dotted domain. Deliverability is the
#: magic link's job, not this pattern's.
_EMAIL_SHAPE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAGIC_LINK_SHAPE = re.compile(
    rf"^{MAGIC_LINK_PREFIX}([0-9a-f]{{{_LOOKUP_HEX}}})\.([0-9a-f]{{{_SECRET_HEX}}})$"
)


class PortalAuthError(Exception):
    """A refusal from the portal auth store, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------------------------


def mint_magic_link_token() -> Tuple[str, str, str]:
    """Mint a one-time magic-link token.

    Returns:
        ``(token, lookup_prefix, token_hash)``: the plaintext mailed to the reader once
        (``pml_<16 hex>.<48 hex>``), the public prefix that finds its row, and the bcrypt hash that
        is stored.
    """
    lookup = secrets.token_hex(_LOOKUP_HEX // 2)
    token = f"{MAGIC_LINK_PREFIX}{lookup}.{secrets.token_hex(_SECRET_HEX // 2)}"
    assert len(token.encode("utf-8")) <= 72  # bcrypt's input limit
    token_hash = bcrypt.hashpw(token.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return token, MAGIC_LINK_PREFIX + lookup, token_hash.decode("ascii")


def split_magic_link_token(token: str) -> Optional[str]:
    """Return a well-formed magic-link token's lookup prefix.

    Args:
        token: The token as presented.

    Returns:
        ``pml_<16 hex>``, or ``None`` when the token is not shaped like one.
    """
    match = _MAGIC_LINK_SHAPE.fullmatch((token or "").strip())
    return MAGIC_LINK_PREFIX + match.group(1) if match else None


def verify_magic_link_token(token: str, token_hash: str) -> bool:
    """Check a presented magic-link token against its stored bcrypt hash.

    Args:
        token: The token as presented.
        token_hash: The stored hash.

    Returns:
        True when they match; False for a mismatch or an unreadable hash.
    """
    try:
        return bcrypt.checkpw(token.strip().encode("utf-8"), token_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def mint_session_token() -> Tuple[str, str]:
    """Mint a reader session token.

    Returns:
        ``(token, token_hash)``: the plaintext Browse stores in its cookie (``prs_`` + 43 URL-safe
        characters, 256 bits) and the SHA-256 hex digest that is stored.
    """
    token = SESSION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_session_token(token)


def hash_session_token(token: str) -> str:
    """Hash a session token for storage and lookup.

    A session token is 256 random bits chosen by the server, so a fast hash is the right tool: it
    cannot be brute-forced, and every Browse request can find its session through a unique index.

    Args:
        token: The plaintext token.

    Returns:
        The SHA-256 hex digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def reader_token_from_header(authorization: Optional[str]) -> Optional[str]:
    """Extract the token from an ``Authorization: Reader <token>`` header.

    Args:
        authorization: The raw header value.

    Returns:
        The session token, or ``None`` when the header is absent, uses another scheme, or is not
        shaped like a reader session token.
    """
    raw = (authorization or "").strip()
    scheme, _, value = raw.partition(" ")
    if scheme.lower() != READER_SCHEME.lower():
        return None
    token = value.strip()
    if not token.startswith(SESSION_TOKEN_PREFIX) or len(token) > 128:
        return None
    return token


# ---------------------------------------------------------------------------------------------
# Input guards
# ---------------------------------------------------------------------------------------------


def normalize_email(raw: str) -> str:
    """Normalize and validate an email address.

    Args:
        raw: The address as typed.

    Returns:
        The trimmed, lower-cased address.

    Raises:
        PortalAuthError: ``portal-invalid-email`` when it is not shaped like an address.
    """
    email = (raw or "").strip().lower()
    if len(email) > _MAX_EMAIL_LENGTH or not _EMAIL_SHAPE.fullmatch(email):
        raise PortalAuthError(CODE_INVALID_EMAIL, "Enter a valid email address.")
    return email


def safe_return_to(raw: Optional[str]) -> Optional[str]:
    """Accept a ``return_to`` only when it is a path inside Browse.

    A magic link carries where to land after signing in. Anything that could leave the site — an
    absolute URL, a protocol-relative ``//host``, a backslash some browsers treat as a slash, or a
    control character — is refused, so the link can never be turned into an open redirect.

    Args:
        raw: The requested path, or ``None``.

    Returns:
        The path, or ``None`` when none was given.

    Raises:
        PortalAuthError: ``portal-invalid-return-to`` for anything that is not a same-site path.
    """
    if raw is None or raw == "":
        return None
    if (
        len(raw) > _MAX_RETURN_TO_LENGTH
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\\" in raw
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw)
    ):
        raise PortalAuthError(CODE_INVALID_RETURN_TO, "return_to must be a path inside Browse.")
    return raw


def user_agent_family(user_agent: Optional[str]) -> str:
    """Reduce a User-Agent string to its browser family.

    Sessions keep only this, never the full string, so a session list can say "Firefox" without
    storing a fingerprint.

    Args:
        user_agent: The raw ``User-Agent`` header.

    Returns:
        ``Edge``, ``Chrome``, ``Firefox``, ``Safari``, or ``Other``.
    """
    ua = user_agent or ""
    if "Edg/" in ua:
        return "Edge"
    if "Firefox/" in ua:
        return "Firefox"
    if "Chrome/" in ua or "CriOS/" in ua:
        return "Chrome"
    if "Safari/" in ua:
        return "Safari"
    return "Other"


# ---------------------------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    """Ask for a sign-in link.

    Attributes:
        email: The reader's address.
        return_to: A Browse path to land on after signing in.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=_MAX_EMAIL_LENGTH, description="The reader's email address.")
    return_to: Optional[str] = Field(
        default=None,
        max_length=_MAX_RETURN_TO_LENGTH,
        description="A path inside Browse to return to after signing in (for example `/tenant/acme`).",
    )


class MagicLinkAccepted(BaseModel):
    """The answer to every well-formed magic-link request."""

    model_config = ConfigDict(extra="forbid")

    accepted: Literal[True] = Field(
        default=True,
        description=(
            "Always true. Whether a link was actually sent is never revealed, so the answer cannot "
            "be used to learn who has an account."
        ),
    )
    expires_in_minutes: int = Field(
        default=MAGIC_LINK_TTL_MINUTES, description="How long a link is valid once it arrives."
    )


class TokenExchange(BaseModel):
    """Exchange a magic-link token for a reader session."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128, description="The token from the magic link.")


class ReaderProfile(BaseModel):
    """The signed-in reader."""

    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    name: Optional[str] = None
    tenant_slug: str
    tenant_name: Optional[str] = None
    membership_status: Literal["invited", "active", "revoked"]
    session_expires_at: datetime = Field(description="When the current session ends.")


class ReaderSessionGrant(BaseModel):
    """A new reader session.

    The token is returned **once**. Browse stores it in an ``HttpOnly`` cookie and forwards it as
    ``Authorization: Reader <token>``; it is never shown to the reader.
    """

    model_config = ConfigDict(extra="forbid")

    session_token: str = Field(description="The opaque session token. Returned once; store it securely.")
    expires_at: datetime
    return_to: Optional[str] = Field(default=None, description="Where the magic link asked to land.")
    reader: ReaderProfile
