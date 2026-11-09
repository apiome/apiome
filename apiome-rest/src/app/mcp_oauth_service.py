"""OAuth 2.1 token acquisition and refresh for MCP endpoints (the store-facing half of MCAT-6.4).

MCAT-6.4 (#3680). :mod:`app.mcp_oauth_flow` speaks the protocol; this module ties it to the
endpoint's credential row (``apiome.mcp_endpoint_credentials``):

* :func:`start_authorization` — checks the discovered metadata, registers a client when needed
  (RFC 7591), makes the PKCE pair and returns the URL the user's browser is sent to. The
  ``code_verifier`` and everything the callback needs travel in a **sealed** ``state`` (AES-256-GCM
  under the credential master key, with its own envelope magic so a state can never be mistaken for
  a stored credential). Only the SHA-256 of the state's nonce is stored, as
  ``oauth_metadata.pending_authorization``, so each state is accepted once.
* :func:`complete_authorization` — the callback: unseals and checks the state (endpoint, tenant,
  user, expiry), consumes the pending authorization, checks the ``iss`` (RFC 9207), exchanges the
  code and stores the sealed tokens as an ``oauth2`` credential.
* :func:`refresh_endpoint_credential` — renews a token that expires within
  :data:`app.mcp_oauth_flow.REFRESH_SKEW_SECONDS` (or, with ``force``, after a ``401``). It is
  called from :func:`app.mcp_credentials.load_endpoint_auth_headers`, the one seam every discovery
  run, sweep and test call loads its headers through, so expiry is handled without the caller
  knowing. A process-local lock and a compare-and-set on ``last_refreshed_at`` stop two refreshes
  of one token from both being stored.

The non-secret ``oauth_metadata.token`` summary (client id, scope, expiry, whether it can be
refreshed, the last refresh error) is what the redacted ``GET …/credentials`` shows.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .config import settings
from .database import db
from .envelope_crypto import EnvelopeCipher
from .mcp_auth import AUTH_TYPE_OAUTH2
from .mcp_credential_crypto import seal_credential_payload, unseal_credential_payload
from .mcp_oauth_flow import (
    AUTH_METHOD_NONE,
    OAuthFlowError,
    build_authorization_url,
    check_callback_issuer,
    check_redirect_uri,
    choose_auth_method,
    exchange_code,
    generate_pkce_pair,
    needs_refresh,
    refresh_tokens,
    register_client,
    requested_scopes,
    require_flow_metadata,
    token_payload_from_response,
    token_summary,
)

logger = logging.getLogger(__name__)

#: How long a started authorization stays valid (the user has this long to consent).
AUTHORIZATION_TTL_SECONDS = 600

#: ``purpose`` sealed into every state, checked on the way back.
STATE_PURPOSE = "mcp_oauth_authorization"

#: ``oauth_metadata.token.client_registration`` values.
REGISTRATION_DYNAMIC = "dynamic"
REGISTRATION_PREREGISTERED = "preregistered"

#: Sealed authorization state. ``OMOS`` = *Apiome MCP OAuth State*: same master keys as the
#: credential vault, different magic (part of the AAD), so a state blob and a stored credential
#: blob cannot be swapped for one another.
_STATE_CIPHER = EnvelopeCipher(
    magic=b"OMOS",
    subject="MCP OAuth state",
    keys_setting="APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS",
    read_keys=lambda: settings.mcp_credential_encryption_keys,
    read_active_version=lambda: settings.mcp_credential_active_key_version,
)

#: One lock per endpoint, so two refreshes in this process run one after the other.
_refresh_locks: Dict[str, threading.Lock] = {}
_refresh_locks_guard = threading.Lock()


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ===========================================================================
# Sealed state
# ===========================================================================


def seal_state(document: Mapping[str, Any]) -> str:
    """Seal an authorization's state into an opaque, URL-safe ``state`` value.

    Returns:
        ``"<key_version>.<base64url ciphertext>"``.

    Raises:
        CredentialEncryptionError: When credential encryption is not configured.
    """
    blob, key_version = _STATE_CIPHER.seal(document)
    return f"{key_version}." + base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def unseal_state(state: str) -> Dict[str, Any]:
    """Open a ``state`` made by :func:`seal_state`.

    Raises:
        OAuthFlowError: ``invalid_state`` when it is malformed, tampered with or not an Apiome
            authorization state.
    """
    version_text, _, encoded = (state or "").partition(".")
    try:
        key_version = int(version_text)
        blob = base64.urlsafe_b64decode((encoded + "=" * (-len(encoded) % 4)).encode("ascii"))
    except (ValueError, UnicodeError):
        raise OAuthFlowError("invalid_state", "the state is not an Apiome authorization state") from None
    document = _STATE_CIPHER.unseal(blob, key_version)
    if not document or document.get("purpose") != STATE_PURPOSE:
        raise OAuthFlowError("invalid_state", "the state is not an Apiome authorization state")
    return document


# ===========================================================================
# Authorization
# ===========================================================================


def _cached_client(metadata: Mapping[str, Any], redirect_uri: str) -> Optional[Dict[str, Any]]:
    """Return the dynamically registered public client stored earlier for this redirect URI."""
    cached = metadata.get("client")
    if not isinstance(cached, dict):
        return None
    if cached.get("redirect_uri") != redirect_uri or cached.get("issuer") != metadata.get("issuer"):
        return None
    if not isinstance(cached.get("client_id"), str) or not cached.get("client_id"):
        return None
    return {"client_id": cached["client_id"], "client_secret": None, "token_endpoint_auth_method": AUTH_METHOD_NONE}


def start_authorization(
    *,
    endpoint_id: str,
    tenant_id: str,
    user_id: str,
    redirect_uri: str,
    scopes: Optional[Sequence[str]] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Begin an authorization-code + PKCE authorization for an endpoint.

    The client is the supplied ``client_id`` (pre-registered), else the public client registered
    earlier for the same redirect URI and issuer, else a new one from Dynamic Client Registration.

    Args:
        endpoint_id: The tenant-validated endpoint.
        tenant_id: The caller's tenant (sealed into the state).
        user_id: The caller (sealed into the state; only they can complete it).
        redirect_uri: The UI callback URL.
        scopes: Scopes to request instead of the discovered ones.
        client_id: A client id registered with the server out of band.
        client_secret: That client's secret, for a confidential client.
        now: The current time (tests).

    Returns:
        ``authorization_url``, ``expires_at``, ``client_id``, ``client_registration`` and
        ``scopes``.

    Raises:
        OAuthFlowError: The metadata is missing or lacks PKCE, the redirect URI is refused, or
            registration failed.
        CredentialEncryptionError: Credential encryption is not configured.
    """
    current = _now(now)
    row = db.get_mcp_endpoint_credentials(endpoint_id)
    metadata = require_flow_metadata((row or {}).get("oauth_metadata"))
    check_redirect_uri(redirect_uri)

    cache_patch: Dict[str, Any] = {}
    if client_id and client_id.strip():
        registration = REGISTRATION_PREREGISTERED
        secret = client_secret or None
        client = {
            "client_id": client_id.strip(),
            "client_secret": secret,
            "token_endpoint_auth_method": choose_auth_method(metadata, bool(secret)),
        }
    else:
        registration = REGISTRATION_DYNAMIC
        client = _cached_client(metadata, redirect_uri)
        if client is None:
            client = register_client(metadata, redirect_uri)
            if not client["client_secret"]:
                # A public client holds nothing secret, so it is kept for the next connect.
                cache_patch["client"] = {
                    "client_id": client["client_id"],
                    "redirect_uri": redirect_uri,
                    "issuer": metadata.get("issuer"),
                    "registered_at": current.isoformat(),
                }

    scope_list = requested_scopes(metadata, scopes)
    verifier, challenge = generate_pkce_pair()
    nonce = secrets.token_urlsafe(24)
    expires_at = current + timedelta(seconds=AUTHORIZATION_TTL_SECONDS)
    state = seal_state(
        {
            "purpose": STATE_PURPOSE,
            "endpoint_id": endpoint_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "nonce": nonce,
            "expires_at": expires_at.isoformat(),
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "token_endpoint_auth_method": client["token_endpoint_auth_method"],
            "client_registration": registration,
        }
    )
    db.merge_mcp_endpoint_oauth_metadata(
        endpoint_id,
        {
            **cache_patch,
            "pending_authorization": {
                "nonce_sha256": _sha256(nonce),
                "started_at": current.isoformat(),
                "expires_at": expires_at.isoformat(),
            },
        },
    )
    url = build_authorization_url(
        metadata,
        client_id=client["client_id"],
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=state,
        scopes=scope_list,
    )
    return {
        "authorization_url": url,
        "expires_at": expires_at.isoformat(),
        "client_id": client["client_id"],
        "client_registration": registration,
        "scopes": scope_list,
    }


def complete_authorization(
    *,
    tenant_id: str,
    user_id: str,
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    iss: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Finish an authorization from the authorization server's redirect.

    Args:
        tenant_id: The caller's tenant (must match the state's).
        user_id: The caller (must be the user who started the authorization).
        state: The ``state`` query parameter.
        code: The ``code`` query parameter (absent when the user declined).
        error: The ``error`` query parameter, when the server reported one.
        error_description: The server's ``error_description``.
        iss: The ``iss`` query parameter (RFC 9207), when present.
        now: The current time (tests).

    Returns:
        ``(endpoint_id, stored credential row)``.

    Raises:
        OAuthFlowError: ``invalid_state`` / ``state_expired`` for a bad, foreign, reused or old
            state; ``authorization_denied`` when the server returned an error; ``issuer_mismatch``;
            any token-exchange failure.
        CredentialEncryptionError: Credential encryption is not configured.
    """
    current = _now(now)
    document = unseal_state(state)
    if document.get("tenant_id") != tenant_id or document.get("user_id") != user_id:
        raise OAuthFlowError("invalid_state", "this authorization was started by another user")
    try:
        expires_at = datetime.fromisoformat(str(document.get("expires_at")))
    except ValueError:
        raise OAuthFlowError("invalid_state", "the state has no valid expiry") from None
    if current > expires_at:
        raise OAuthFlowError("state_expired", "the authorization took too long; connect again")

    endpoint_id = str(document["endpoint_id"])
    if db.consume_mcp_endpoint_oauth_pending(endpoint_id, _sha256(str(document.get("nonce")))) is None:
        raise OAuthFlowError("invalid_state", "this authorization was already used or replaced; connect again")

    if error:
        detail = error if not error_description else f"{error}: {error_description[:200]}"
        raise OAuthFlowError("authorization_denied", f"the authorization server returned {detail}")
    if not code:
        raise OAuthFlowError("authorization_denied", "the authorization response has no code")

    row = db.get_mcp_endpoint_credentials(endpoint_id)
    metadata = require_flow_metadata((row or {}).get("oauth_metadata"))
    check_callback_issuer(metadata, iss)

    client_id = str(document["client_id"])
    client_secret = document.get("client_secret")
    auth_method = str(document.get("token_endpoint_auth_method") or AUTH_METHOD_NONE)
    response = exchange_code(
        metadata,
        code=code,
        code_verifier=str(document["code_verifier"]),
        redirect_uri=str(document["redirect_uri"]),
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
    )
    payload = token_payload_from_response(
        response,
        metadata=metadata,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
        now=current,
    )
    registration = str(document.get("client_registration") or REGISTRATION_DYNAMIC)
    payload["client_registration"] = registration
    sealed, key_version = seal_credential_payload(payload)
    stored = db.store_mcp_endpoint_oauth_tokens(
        endpoint_id=endpoint_id,
        encrypted_payload=sealed,
        key_version=key_version,
        metadata_patch={"token": token_summary(payload, registration=registration)},
    )
    if stored is None:
        raise OAuthFlowError("invalid_state", "the endpoint's credential was removed during the authorization")
    return endpoint_id, stored


# ===========================================================================
# Refresh
# ===========================================================================


def _lock_for(endpoint_id: str) -> threading.Lock:
    with _refresh_locks_guard:
        lock = _refresh_locks.get(endpoint_id)
        if lock is None:
            lock = _refresh_locks[endpoint_id] = threading.Lock()
        return lock


def _record_refresh_error(
    endpoint_id: str, metadata: Mapping[str, Any], exc: OAuthFlowError, current: datetime
) -> None:
    """Note a failed refresh in ``oauth_metadata.token`` (best-effort; never the token)."""
    summary = dict(metadata.get("token") or {})
    summary["last_refresh_error"] = {**exc.as_dict(), "at": current.isoformat()}
    try:
        db.merge_mcp_endpoint_oauth_metadata(endpoint_id, {"token": summary})
    except Exception:  # noqa: BLE001 - recording the error must not mask it
        logger.warning("could not record oauth refresh error endpoint=%s", endpoint_id, exc_info=True)


def refresh_endpoint_credential(
    endpoint_id: str,
    credential: Optional[Dict[str, Any]],
    *,
    force: bool = False,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Return the endpoint's credential row, refreshing its OAuth token first when due.

    Only an ``oauth2`` row with a decryptable payload and a refresh token is ever refreshed. Without
    ``force`` the token is renewed when it expires within the refresh skew; with ``force`` (after a
    ``401``) it is renewed unless another caller already refreshed it since ``credential`` was read.
    A failed refresh is logged and recorded in ``oauth_metadata.token.last_refresh_error``, and the
    existing row is returned — the run goes ahead with the old token and the server's answer
    surfaces as usual.

    Args:
        endpoint_id: The endpoint.
        credential: The row as the caller read it (``None`` when there is none).
        force: Refresh even though the token has not reached its expiry window.
        now: The current time (tests).

    Returns:
        The current credential row (refreshed when a refresh succeeded).
    """
    if not credential or credential.get("auth_type") != AUTH_TYPE_OAUTH2:
        return credential
    current = _now(now)
    if not force:
        # Fast path: most loads find a live token and need no lock and no second read.
        seen = unseal_credential_payload(credential.get("encrypted_payload"), credential.get("key_version"))
        if not seen or not needs_refresh(seen, now=current):
            return credential
    with _lock_for(endpoint_id):
        row = db.get_mcp_endpoint_credentials(endpoint_id)
        if not row or row.get("auth_type") != AUTH_TYPE_OAUTH2:
            return row
        if row.get("last_refreshed_at") != credential.get("last_refreshed_at"):
            # Refreshed (or replaced) by someone else since the caller read it.
            return row
        payload = unseal_credential_payload(row.get("encrypted_payload"), row.get("key_version"))
        if not payload or not payload.get("refresh_token"):
            return row
        if not force and not needs_refresh(payload, now=current):
            return row
        metadata = row.get("oauth_metadata") or {}
        try:
            response = refresh_tokens(require_flow_metadata(metadata), payload)
            renewed = token_payload_from_response(
                response,
                metadata=metadata,
                client_id=str(payload["client_id"]),
                client_secret=payload.get("client_secret"),
                auth_method=str(payload.get("token_endpoint_auth_method") or AUTH_METHOD_NONE),
                previous=payload,
                now=current,
            )
        except OAuthFlowError as exc:
            logger.warning("oauth token refresh failed endpoint=%s: %s", endpoint_id, exc.code)
            _record_refresh_error(endpoint_id, metadata, exc, current)
            return row
        registration = str(payload.get("client_registration") or REGISTRATION_DYNAMIC)
        renewed["client_registration"] = registration
        summary = token_summary(renewed, registration=registration)
        summary["refreshed_at"] = current.isoformat()
        sealed, key_version = seal_credential_payload(renewed)
        stored = db.store_mcp_endpoint_oauth_tokens(
            endpoint_id=endpoint_id,
            encrypted_payload=sealed,
            key_version=key_version,
            metadata_patch={"token": summary},
            expected_last_refreshed_at=row.get("last_refreshed_at"),
            compare=True,
        )
        if stored is None:
            # Another replica stored a refresh first; use what it stored.
            return db.get_mcp_endpoint_credentials(endpoint_id)
        logger.info("oauth token refreshed endpoint=%s", endpoint_id)
        return stored
