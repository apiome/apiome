"""`apiome login` — browser-approved CLI sign-in, the pure parts (#5501).

The flow follows the OAuth 2.0 device authorization grant (RFC 8628) in shape:

1. ``POST /v1/cli/login`` — the CLI starts a login and gets a secret **device code** plus a short
   **user code** and the page to open (``/cli/login`` in apiome-ui).
2. The person signs in to apiome-ui in the browser, checks the user code matches the terminal,
   picks a workspace and approves (``api_keys:create`` in that workspace is required).
3. ``POST /v1/cli/login/token`` — the CLI polls with its device code. Once approved, the poll mints
   a workspace API key marked ``cli_login`` that expires after :data:`CLI_LOGIN_KEY_TTL`, returns
   it **once**, and the request is consumed. The secret is minted at that moment and never stored
   in clear (the row holds a bcrypt hash, like every workspace key).

This module holds what needs no database or HTTP: code generation and normalization, hashing,
the poll error vocabulary and the request / response models. Persistence is in
:mod:`app.cli_login_store`; the routes in :mod:`app.cli_login_routes`.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import bcrypt
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CLI_LOGIN_KEY_TTL",
    "CLI_LOGIN_POLL_INTERVAL_SECONDS",
    "CLI_LOGIN_REQUEST_TTL",
    "CLI_LOGIN_UI_PATH",
    "CliLoginApproveRequest",
    "CliLoginApproved",
    "CliLoginKeyIssued",
    "CliLoginRequestView",
    "CliLoginStartRequest",
    "CliLoginStarted",
    "CliLoginTokenRequest",
    "CliLoginWorkspace",
    "POLL_ACCESS_DENIED",
    "POLL_EXPIRED_TOKEN",
    "POLL_INVALID_GRANT",
    "POLL_PENDING",
    "POLL_SLOW_DOWN",
    "USER_CODE_ALPHABET",
    "cli_login_key_name",
    "generate_device_code",
    "generate_user_code",
    "hash_device_code",
    "mint_workspace_key_secret",
    "normalize_user_code",
    "verification_uris",
]

#: How long a started login waits for approval and collection.
CLI_LOGIN_REQUEST_TTL = timedelta(minutes=10)

#: How long the key `apiome login` hands out stays valid (the ticket asks for 7–14 days).
CLI_LOGIN_KEY_TTL = timedelta(days=14)

#: Seconds the CLI waits between polls. Polling faster is answered with ``slow_down``.
CLI_LOGIN_POLL_INTERVAL_SECONDS = 5

#: The apiome-ui page the person opens to approve a login.
CLI_LOGIN_UI_PATH = "/cli/login"

#: RFC 8628 §6.1: consonants only, so a code never spells a word, and no 0/O or 1/I confusion.
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"

#: Poll answers (RFC 8628 §3.5 error codes), carried as ``detail.error`` on a 400.
POLL_PENDING = "authorization_pending"
POLL_SLOW_DOWN = "slow_down"
POLL_ACCESS_DENIED = "access_denied"
POLL_EXPIRED_TOKEN = "expired_token"
#: The device code is unknown, or its key was already collected.
POLL_INVALID_GRANT = "invalid_grant"

#: Workspace keys share this prefix and lookup format with apiome-ui (``lib/db/helper.ts``), so
#: ``validate_api_key`` accepts a CLI login key exactly like a key created on the API Keys page.
_WORKSPACE_KEY_PREFIX = "sk_"
_KEY_PREFIX_CHARS = 12
_BCRYPT_ROUNDS = 10

_USER_CODE_RE = re.compile(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")


def generate_device_code() -> str:
    """Mint the secret the CLI polls with.

    Returns:
        43 characters of URL-safe base64 (32 random bytes).
    """
    return secrets.token_urlsafe(32)


def hash_device_code(device_code: str) -> str:
    """Hash a device code for storage and lookup.

    Args:
        device_code: The plain code.

    Returns:
        Lowercase hex SHA-256 (64 characters).
    """
    return hashlib.sha256(device_code.encode("utf-8")).hexdigest()


def generate_user_code() -> str:
    """Mint a user code such as ``KTXR-MWDB``.

    Returns:
        Eight characters from :data:`USER_CODE_ALPHABET`, grouped 4-4 with a dash.
    """
    chars = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{chars[:4]}-{chars[4:]}"


def normalize_user_code(raw: object) -> Optional[str]:
    """Canonicalize a user code typed or pasted by a person.

    Case, spaces and the dash are forgiven: ``ktxr mwdb``, ``KTXRMWDB`` and ``ktxr-mwdb`` are all
    ``KTXR-MWDB``.

    Args:
        raw: The code as received.

    Returns:
        The canonical ``XXXX-XXXX`` form, or ``None`` when it cannot be a user code.
    """
    if not isinstance(raw, str):
        return None
    compact = re.sub(r"[\s-]", "", raw).upper()
    if len(compact) != 8:
        return None
    code = f"{compact[:4]}-{compact[4:]}"
    return code if _USER_CODE_RE.match(code) else None


def verification_uris(ui_base_url: str, user_code: str) -> Tuple[str, str]:
    """The approve page, without and with the code filled in.

    Args:
        ui_base_url: Public base URL of apiome-ui (``settings.ui_public_url``).
        user_code: The canonical user code.

    Returns:
        ``(verification_uri, verification_uri_complete)``.
    """
    base = ui_base_url.rstrip("/") + CLI_LOGIN_UI_PATH
    return base, f"{base}?code={user_code}"


def mint_workspace_key_secret() -> Tuple[str, str, str]:
    """Mint a workspace API key secret in the format apiome-ui uses.

    Returns:
        ``(secret, key_prefix, key_hash)`` — the secret (returned to the CLI once), its lookup
        prefix (first 12 characters + ``...``) and the bcrypt hash that is stored.
    """
    secret = _WORKSPACE_KEY_PREFIX + secrets.token_hex(32)
    prefix = secret[:_KEY_PREFIX_CHARS] + "..."
    key_hash = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return secret, prefix, key_hash.decode("utf-8")


def cli_login_key_name(client_name: Optional[str], request_id: str) -> str:
    """The name the minted key carries on the API Keys page.

    Key names are unique per workspace (revoked keys included), so the request id's first eight
    characters make every login key's name distinct.

    Args:
        client_name: What the CLI called itself, if anything.
        request_id: The login request's id.

    Returns:
        For example ``CLI login · apiome-cli on build-box · 3f9a1c22``.
    """
    label = (client_name or "").strip()[:120] or "apiome-cli"
    return f"CLI login · {label} · {request_id[:8]}"


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


class CliLoginStartRequest(BaseModel):
    """Body of ``POST /v1/cli/login``."""

    model_config = ConfigDict(extra="forbid")

    client_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="How the CLI names itself on the approve page, e.g. `apiome-cli on build-box`.",
    )


class CliLoginStarted(BaseModel):
    """A started login (RFC 8628 §3.2 device authorization response)."""

    device_code: str = Field(description="Secret the CLI polls with. Never show it to the person.")
    user_code: str = Field(description="Code the person compares in the browser, e.g. `KTXR-MWDB`.")
    verification_uri: str = Field(description="The approve page in apiome-ui.")
    verification_uri_complete: str = Field(description="The approve page with the code filled in.")
    expires_in: int = Field(description="Seconds until the login expires.")
    interval: int = Field(description="Seconds to wait between polls.")


class CliLoginTokenRequest(BaseModel):
    """Body of ``POST /v1/cli/login/token``."""

    model_config = ConfigDict(extra="forbid")

    device_code: str = Field(min_length=1, max_length=128)


class CliLoginKeyIssued(BaseModel):
    """The key an approved login hands to the CLI — shown once."""

    api_key: str = Field(description="The secret. Send it as `X-API-Key`; it is never shown again.")
    key_id: str
    key_prefix: str
    key_name: str
    tenant_slug: str
    tenant_name: str
    expires_at: datetime


class CliLoginWorkspace(BaseModel):
    """A workspace the signed-in person could approve the login for."""

    slug: str
    name: str
    can_approve: bool = Field(description="Whether the person holds `api_keys:create` there.")


class CliLoginRequestView(BaseModel):
    """What the approve page shows about a pending login."""

    user_code: str
    client_name: Optional[str] = None
    status: str
    created_at: datetime
    expires_at: datetime
    workspaces: List[CliLoginWorkspace]


class CliLoginApproveRequest(BaseModel):
    """Body of ``POST /v1/cli/login/requests/{user_code}/approve``."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(min_length=1, max_length=255)


class CliLoginApproved(BaseModel):
    """The outcome of approving or denying a login."""

    user_code: str
    status: str
    tenant_slug: Optional[str] = None
