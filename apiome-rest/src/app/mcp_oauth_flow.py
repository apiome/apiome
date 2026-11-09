"""OAuth 2.1 authorization-code + PKCE + refresh for protected MCP servers (the protocol layer).

MCAT-6.4 (#3680). Once discovery (:mod:`app.mcp_oauth_discovery`, MCAT-6.3) has stored a protected
server's authorization-server metadata, Apiome can obtain tokens for it. This module holds the
**protocol** steps; :mod:`app.mcp_oauth_service` wires them to the credential store.

The flow follows the
`MCP authorization spec <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>`_:

1. **PKCE is required.** A ``code_verifier`` / ``S256`` ``code_challenge`` pair is made for every
   authorization (:func:`generate_pkce_pair`). A server whose metadata does not advertise ``S256``
   is refused rather than run without PKCE.
2. **Dynamic Client Registration** (RFC 7591) is optional: :func:`register_client` registers a
   public client when the server has a ``registration_endpoint`` and no client id was supplied.
3. **The resource indicator** (RFC 8707) is sent on the authorization request, the code exchange
   and every refresh, so each token is issued *for this MCP server*.
4. The authorization request URL is built by :func:`build_authorization_url`; the user consents in
   the browser and the authorization server redirects back with ``code`` and ``state``.
5. :func:`exchange_code` swaps the code for tokens; :func:`refresh_tokens` renews them later.
   :func:`token_payload_from_response` validates either response, including the **audience check**
   (:func:`check_token_audience`): a JWT access token whose ``aud`` names another resource is
   refused.

Every request goes to a URL taken from (validated) metadata and passes the same rules as discovery
(:func:`app.mcp_oauth_discovery.check_metadata_url`): https only (http to loopback), no private IP
literals, no redirects, a short timeout and a capped body.

Secrets — the verifier, the authorization code, the client secret and the tokens — are never
logged and never appear in an :class:`OAuthFlowError` message.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from .mcp_auth import AUTH_TYPE_OAUTH2, CredentialPayloadError, validate_credential_payload
from .mcp_oauth_discovery import (
    MAX_METADATA_BYTES,
    METADATA_TIMEOUT_SECONDS,
    OAuthDiscoveryError,
    check_metadata_url,
    resource_matches_endpoint,
)

#: Name Apiome registers itself under (RFC 7591 ``client_name``).
CLIENT_NAME = "Apiome"

#: Grant types a dynamically registered Apiome client asks for.
CLIENT_GRANT_TYPES = ("authorization_code", "refresh_token")

#: Token endpoint auth methods Apiome can perform.
AUTH_METHOD_NONE = "none"
AUTH_METHOD_SECRET_BASIC = "client_secret_basic"
AUTH_METHOD_SECRET_POST = "client_secret_post"
SUPPORTED_AUTH_METHODS = (AUTH_METHOD_NONE, AUTH_METHOD_SECRET_BASIC, AUTH_METHOD_SECRET_POST)

#: A token is refreshed this many seconds before it expires, so a run never starts on a token
#: that dies mid-flight.
REFRESH_SKEW_SECONDS = 60

#: Length of the random ``code_verifier`` (RFC 7636 §4.1 allows 43–128 characters).
CODE_VERIFIER_LENGTH = 64


class OAuthFlowError(Exception):
    """An authorization, code exchange or refresh step failed.

    Attributes:
        code: Stable machine-readable reason — ``not_discovered``, ``pkce_unsupported``,
            ``invalid_redirect_uri``, ``client_required``, ``registration_failed``,
            ``invalid_state``, ``state_expired``, ``authorization_denied``, ``issuer_mismatch``,
            ``token_error``, ``invalid_token_response``, ``audience_mismatch``, ``not_refreshable``
            or ``invalid_url``.
        message: Human-readable detail. Never contains a secret: at most a URL, an OAuth ``error``
            code and the authorization server's ``error_description``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> Dict[str, str]:
        """Return ``{"code", "message"}`` for an API error body."""
        return {"code": self.code, "message": self.message}


# ===========================================================================
# PKCE (RFC 7636)
# ===========================================================================

_VERIFIER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _b64url(data: bytes) -> str:
    """Base64url-encode ``data`` without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_challenge(verifier: str) -> str:
    """Return the ``S256`` code challenge for ``verifier`` (``BASE64URL(SHA256(verifier))``)."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def generate_pkce_pair() -> Tuple[str, str]:
    """Make a fresh PKCE pair.

    Returns:
        ``(code_verifier, code_challenge)`` — a :data:`CODE_VERIFIER_LENGTH`-character verifier
        from the RFC 7636 unreserved alphabet and its ``S256`` challenge.
    """
    verifier = "".join(secrets.choice(_VERIFIER_ALPHABET) for _ in range(CODE_VERIFIER_LENGTH))
    return verifier, pkce_challenge(verifier)


# ===========================================================================
# Inputs
# ===========================================================================


def _flow_url(url: str, what: str) -> str:
    """Apply the discovery URL rules to ``url``, re-raising as :class:`OAuthFlowError`."""
    try:
        return check_metadata_url(url)
    except OAuthDiscoveryError as exc:
        raise OAuthFlowError("invalid_url", f"{what}: {exc.message}") from exc


def check_redirect_uri(redirect_uri: str) -> str:
    """Validate the redirect URI the authorization server will send the user back to.

    It must be an absolute ``https://`` URL (``http://`` only to loopback) with no fragment and no
    user-info (RFC 6749 §3.1.2). It is the Apiome UI's callback page, so it is the browser — not
    Apiome's server — that follows it; private hosts are therefore allowed.

    Args:
        redirect_uri: The callback URL the client asked for.

    Returns:
        The URL unchanged when it is allowed.

    Raises:
        OAuthFlowError: ``invalid_redirect_uri`` when it is not allowed.
    """
    parts = urlsplit(redirect_uri or "")
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        raise OAuthFlowError("invalid_redirect_uri", "redirect_uri must be an absolute http(s) URL")
    if parts.fragment or parts.username or parts.password:
        raise OAuthFlowError("invalid_redirect_uri", "redirect_uri must not carry a fragment or credentials")
    if scheme == "http" and host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
        raise OAuthFlowError("invalid_redirect_uri", "plain http:// redirect_uri is only allowed to loopback")
    return redirect_uri


def require_flow_metadata(metadata: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Check stored ``oauth_metadata`` is complete enough to start an authorization.

    Args:
        metadata: The endpoint's ``oauth_metadata`` (from MCAT-6.3 discovery).

    Returns:
        The metadata as a plain dict.

    Raises:
        OAuthFlowError: ``not_discovered`` when the authorize / token endpoints or the resource
            indicator are missing; ``pkce_unsupported`` when the server does not advertise ``S256``
            (the MCP spec forbids proceeding without PKCE).
    """
    data = dict(metadata or {})
    for key in ("authorization_endpoint", "token_endpoint", "resource"):
        if not isinstance(data.get(key), str) or not data.get(key):
            raise OAuthFlowError(
                "not_discovered",
                "OAuth metadata is incomplete; run discovery against the server first",
            )
    if not data.get("pkce_s256_supported"):
        raise OAuthFlowError(
            "pkce_unsupported",
            "the authorization server does not advertise PKCE S256, which is required",
        )
    return data


def requested_scopes(metadata: Mapping[str, Any], explicit: Optional[Sequence[str]]) -> List[str]:
    """Pick the scopes to request.

    The caller's explicit list wins; otherwise the scopes the ``401`` challenge asked for, then the
    server's ``scopes_supported`` (the MCP spec's order).

    Args:
        metadata: The endpoint's ``oauth_metadata``.
        explicit: Scopes the caller asked for, or ``None``.

    Returns:
        De-duplicated scopes in order (possibly empty — the ``scope`` parameter is then omitted).
    """
    for source in (explicit, metadata.get("challenge_scopes"), metadata.get("scopes_supported")):
        if source:
            scopes: List[str] = []
            for scope in source:
                if isinstance(scope, str) and scope.strip() and scope.strip() not in scopes:
                    scopes.append(scope.strip())
            if scopes:
                return scopes
    return []


def choose_auth_method(metadata: Mapping[str, Any], has_secret: bool) -> str:
    """Choose how Apiome authenticates to the token endpoint.

    A client without a secret is a public client (``none``). With a secret, ``client_secret_basic``
    is used unless the server lists only ``client_secret_post`` (RFC 8414 defaults to basic).

    Args:
        metadata: The endpoint's ``oauth_metadata``.
        has_secret: Whether a client secret is held.

    Returns:
        One of :data:`SUPPORTED_AUTH_METHODS`.
    """
    if not has_secret:
        return AUTH_METHOD_NONE
    supported = metadata.get("token_endpoint_auth_methods_supported") or []
    if AUTH_METHOD_SECRET_POST in supported and AUTH_METHOD_SECRET_BASIC not in supported:
        return AUTH_METHOD_SECRET_POST
    return AUTH_METHOD_SECRET_BASIC


# ===========================================================================
# HTTP
# ===========================================================================


def _http_client() -> httpx.Client:
    """Return a client that never follows redirects and times out like discovery does."""
    return httpx.Client(follow_redirects=False, timeout=httpx.Timeout(METADATA_TIMEOUT_SECONDS))


def _post(
    client: httpx.Client,
    url: str,
    *,
    what: str,
    data: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """POST to an authorization-server URL and return ``(status, JSON object body)``.

    Args:
        client: The HTTP client.
        url: The endpoint, already taken from validated metadata.
        what: Short name of the step, for error messages.
        data: A form body (``application/x-www-form-urlencoded``).
        json_body: A JSON body (for client registration).
        headers: Extra request headers.

    Returns:
        The status code and the parsed body (``{}`` when the body is not a JSON object).

    Raises:
        OAuthFlowError: ``invalid_url`` for a refused URL, ``token_error`` for a network failure or
            an oversized body.
    """
    _flow_url(url, what)
    request_headers = {"Accept": "application/json", **(headers or {})}
    try:
        with client.stream("POST", url, data=data, json=json_body, headers=request_headers) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > MAX_METADATA_BYTES:
                    raise OAuthFlowError("token_error", f"{what} response is larger than {MAX_METADATA_BYTES} bytes")
            status = response.status_code
    except httpx.HTTPError as exc:
        raise OAuthFlowError("token_error", f"{what} request failed: {type(exc).__name__}") from exc
    try:
        document = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        document = {}
    return status, document if isinstance(document, dict) else {}


def _oauth_error(what: str, status: int, document: Mapping[str, Any]) -> OAuthFlowError:
    """Build the error for a non-2xx authorization-server answer (RFC 6749 §5.2)."""
    error = document.get("error") if isinstance(document.get("error"), str) else None
    description = document.get("error_description")
    detail = f"{what} returned HTTP {status}"
    if error:
        detail += f" ({error}"
        if isinstance(description, str) and description:
            detail += f": {description[:200]}"
        detail += ")"
    return OAuthFlowError("token_error", detail)


def register_client(
    metadata: Mapping[str, Any], redirect_uri: str, *, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """Register Apiome as a client with Dynamic Client Registration (RFC 7591).

    A public client is requested (``token_endpoint_auth_method: none``) for the authorization-code
    and refresh grants with the one redirect URI. A server may still issue a secret; it is returned
    and later sealed with the tokens.

    Args:
        metadata: The endpoint's ``oauth_metadata`` (must carry ``registration_endpoint``).
        redirect_uri: The validated callback URL.
        client: An ``httpx.Client`` to use (tests pass one backed by a mock transport).

    Returns:
        ``{"client_id", "client_secret" (or None), "token_endpoint_auth_method"}``.

    Raises:
        OAuthFlowError: ``client_required`` when the server has no registration endpoint,
            ``registration_failed`` when registration is refused or answers without a
            ``client_id``.
    """
    endpoint = metadata.get("registration_endpoint")
    if not isinstance(endpoint, str) or not endpoint:
        raise OAuthFlowError(
            "client_required",
            "the authorization server has no registration endpoint; supply a client id",
        )
    body = {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": list(CLIENT_GRANT_TYPES),
        "response_types": ["code"],
        "token_endpoint_auth_method": AUTH_METHOD_NONE,
    }
    owned = client is None
    http = client or _http_client()
    try:
        status, document = _post(http, endpoint, what="client registration", json_body=body)
    finally:
        if owned:
            http.close()
    if not 200 <= status < 300:
        error = _oauth_error("client registration", status, document)
        raise OAuthFlowError("registration_failed", error.message)
    client_id = document.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        raise OAuthFlowError("registration_failed", "client registration returned no client_id")
    secret = document.get("client_secret")
    secret = secret if isinstance(secret, str) and secret else None
    method = document.get("token_endpoint_auth_method")
    if method not in SUPPORTED_AUTH_METHODS:
        method = AUTH_METHOD_SECRET_BASIC if secret else AUTH_METHOD_NONE
    if method != AUTH_METHOD_NONE and not secret:
        method = AUTH_METHOD_NONE
    return {"client_id": client_id, "client_secret": secret, "token_endpoint_auth_method": method}


def build_authorization_url(
    metadata: Mapping[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scopes: Sequence[str],
) -> str:
    """Build the authorization request URL the user's browser is sent to (RFC 6749 §4.1.1).

    Carries ``response_type=code``, the client id, the redirect URI, the ``S256`` code challenge,
    the opaque ``state``, the scopes (when any) and the RFC 8707 ``resource`` indicator. Existing
    query parameters on the authorization endpoint are kept.

    Args:
        metadata: The endpoint's validated ``oauth_metadata``.
        client_id: The registered or supplied client id.
        redirect_uri: The validated callback URL.
        code_challenge: The PKCE ``S256`` challenge.
        state: The sealed state from :mod:`app.mcp_oauth_service`.
        scopes: The scopes to request (see :func:`requested_scopes`).

    Returns:
        The absolute authorization URL.
    """
    endpoint = _flow_url(str(metadata["authorization_endpoint"]), "authorization endpoint")
    parts = urlsplit(endpoint)
    params = parse_qsl(parts.query, keep_blank_values=True)
    params += [
        ("response_type", "code"),
        ("client_id", client_id),
        ("redirect_uri", redirect_uri),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("state", state),
        ("resource", str(metadata["resource"])),
    ]
    if scopes:
        params.append(("scope", " ".join(scopes)))
    query = urlencode(params, quote_via=quote)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def check_callback_issuer(metadata: Mapping[str, Any], iss: Optional[str]) -> None:
    """Apply RFC 9207: an ``iss`` on the authorization response must be the expected issuer.

    Raises:
        OAuthFlowError: ``issuer_mismatch`` when ``iss`` is present and differs.
    """
    if iss is None or iss == "":
        return
    if iss != metadata.get("issuer"):
        raise OAuthFlowError("issuer_mismatch", "the authorization response came from another issuer")


def _client_auth(
    client_id: str, client_secret: Optional[str], method: str, form: Dict[str, str]
) -> Dict[str, str]:
    """Add client authentication to a token request; returns extra headers (RFC 6749 §2.3.1)."""
    if method == AUTH_METHOD_SECRET_BASIC and client_secret:
        pair = f"{quote(client_id, safe='')}:{quote(client_secret, safe='')}"
        return {"Authorization": "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")}
    form["client_id"] = client_id
    if method == AUTH_METHOD_SECRET_POST and client_secret:
        form["client_secret"] = client_secret
    return {}


def _token_request(
    metadata: Mapping[str, Any],
    form: Dict[str, str],
    *,
    client_id: str,
    client_secret: Optional[str],
    auth_method: str,
    what: str,
    client: Optional[httpx.Client],
) -> Dict[str, Any]:
    """POST a token request and return the JSON body of a 2xx answer."""
    form["resource"] = str(metadata["resource"])
    headers = _client_auth(client_id, client_secret, auth_method, form)
    owned = client is None
    http = client or _http_client()
    try:
        status, document = _post(http, str(metadata["token_endpoint"]), what=what, data=form, headers=headers)
    finally:
        if owned:
            http.close()
    if not 200 <= status < 300:
        raise _oauth_error(what, status, document)
    return document


def exchange_code(
    metadata: Mapping[str, Any],
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    client_secret: Optional[str],
    auth_method: str,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """Exchange an authorization code for tokens (RFC 6749 §4.1.3 + PKCE + RFC 8707).

    Returns:
        The raw token response (validate it with :func:`token_payload_from_response`).

    Raises:
        OAuthFlowError: ``token_error`` when the server refuses or cannot be reached.
    """
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    return _token_request(
        metadata,
        form,
        client_id=client_id,
        client_secret=client_secret,
        auth_method=auth_method,
        what="code exchange",
        client=client,
    )


def refresh_tokens(
    metadata: Mapping[str, Any], payload: Mapping[str, Any], *, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    """Renew tokens with the stored refresh token (RFC 6749 §6 + RFC 8707).

    Args:
        metadata: The endpoint's ``oauth_metadata`` (its ``token_endpoint`` and ``resource``).
        payload: The decrypted ``oauth2`` credential payload.
        client: An ``httpx.Client`` to use (tests pass a mock-backed one).

    Returns:
        The raw token response.

    Raises:
        OAuthFlowError: ``not_refreshable`` without a refresh token or client id; ``token_error``
            when the server refuses.
    """
    refresh_token = payload.get("refresh_token")
    client_id = payload.get("client_id")
    if not isinstance(refresh_token, str) or not refresh_token or not isinstance(client_id, str) or not client_id:
        raise OAuthFlowError("not_refreshable", "the stored token has no refresh token")
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    scope = payload.get("scope")
    if isinstance(scope, str) and scope:
        form["scope"] = scope
    return _token_request(
        metadata,
        form,
        client_id=client_id,
        client_secret=payload.get("client_secret"),
        auth_method=str(payload.get("token_endpoint_auth_method") or AUTH_METHOD_NONE),
        what="token refresh",
        client=client,
    )


# ===========================================================================
# Token responses
# ===========================================================================


def jwt_audiences(token: str) -> Optional[List[str]]:
    """Read the ``aud`` claim of a JWT access token without verifying it.

    Apiome is the *client*: it cannot verify the server's signature and does not need to. Reading
    ``aud`` only lets it refuse a token plainly minted for another resource. An opaque token (not
    three base64url JSON segments) has no readable audience.

    Args:
        token: The access token.

    Returns:
        The audiences, or ``None`` when the token is opaque or carries no ``aud``.
    """
    segments = token.split(".")
    if len(segments) != 3:
        return None
    try:
        padded = segments[1] + "=" * (-len(segments[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(claims, dict):
        return None
    aud = claims.get("aud")
    if isinstance(aud, str) and aud:
        return [aud]
    if isinstance(aud, list):
        values = [item for item in aud if isinstance(item, str) and item]
        return values or None
    return None


def check_token_audience(token: str, resource: str) -> None:
    """Refuse a JWT access token whose audience does not name this MCP server.

    An audience matches when it is the resource indicator, or shares its origin and is a path
    prefix of it (the server's origin as audience). Opaque tokens pass: their audience binding
    rests on the ``resource`` parameter the server was sent.

    Raises:
        OAuthFlowError: ``audience_mismatch`` when the token names only other audiences.
    """
    audiences = jwt_audiences(token)
    if audiences is None:
        return
    for audience in audiences:
        if audience.rstrip("/") == resource.rstrip("/") or resource_matches_endpoint(audience, resource):
            return
    raise OAuthFlowError("audience_mismatch", "the access token was issued for another resource")


def token_payload_from_response(
    response: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any],
    client_id: str,
    client_secret: Optional[str],
    auth_method: str,
    previous: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Validate a token response and turn it into the sealed ``oauth2`` credential payload.

    The payload carries the access token, ``token_type`` (``Bearer``), the refresh token (a refresh
    answer without one keeps the previous refresh token, RFC 6749 §6), ``expires_at`` (from
    ``expires_in``), the granted ``scope``, the client the tokens belong to and the resource.

    Args:
        response: The token endpoint's JSON body.
        metadata: The endpoint's ``oauth_metadata``.
        client_id: The client the tokens were issued to.
        client_secret: Its secret, when it has one.
        auth_method: How the client authenticates to the token endpoint.
        previous: The payload being refreshed, or ``None`` for a code exchange.
        now: The issue time (defaults to now, UTC).

    Returns:
        The plaintext payload to seal.

    Raises:
        OAuthFlowError: ``invalid_token_response`` for a missing token, a non-Bearer type, a bad
            ``expires_in`` or a value that would corrupt a header; ``audience_mismatch`` from
            :func:`check_token_audience`.
    """
    issued = now or datetime.now(timezone.utc)
    access_token = response.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise OAuthFlowError("invalid_token_response", "the token response has no access_token")
    token_type = response.get("token_type")
    if not isinstance(token_type, str) or token_type.strip().lower() != "bearer":
        raise OAuthFlowError("invalid_token_response", "the token response is not a Bearer token")
    expires_at: Optional[str] = None
    expires_in = response.get("expires_in")
    if expires_in is not None:
        if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)) or expires_in <= 0:
            raise OAuthFlowError("invalid_token_response", "expires_in must be a positive number")
        expires_at = (issued + timedelta(seconds=float(expires_in))).isoformat()
    refresh_token = response.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        refresh_token = (previous or {}).get("refresh_token") or None
    scope = response.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        scope = (previous or {}).get("scope") or None

    resource = str(metadata.get("resource") or "")
    check_token_audience(access_token, resource)

    payload: Dict[str, Any] = {
        "access_token": access_token,
        "token_type": "Bearer",
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "scope": scope,
        "client_id": client_id,
        "client_secret": client_secret,
        "token_endpoint_auth_method": auth_method,
        "resource": resource,
        "issuer": metadata.get("issuer"),
        "obtained_at": issued.isoformat(),
    }
    try:
        validate_credential_payload(AUTH_TYPE_OAUTH2, payload)
    except CredentialPayloadError as exc:
        raise OAuthFlowError("invalid_token_response", str(exc)) from exc
    return payload


def _parse_time(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (naive values are taken as UTC); ``None`` when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def needs_refresh(payload: Mapping[str, Any], *, now: Optional[datetime] = None) -> bool:
    """True when the stored token expires within :data:`REFRESH_SKEW_SECONDS` and can be renewed.

    A token with no known expiry is used as is (a ``401`` then triggers a refresh in discovery);
    a token without a refresh token cannot be renewed and is used until it fails.
    """
    if not payload.get("refresh_token"):
        return False
    expires_at = _parse_time(payload.get("expires_at"))
    if expires_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    return expires_at - current <= timedelta(seconds=REFRESH_SKEW_SECONDS)


def token_summary(payload: Mapping[str, Any], *, registration: str) -> Dict[str, Any]:
    """The non-secret description of a stored token, kept in ``oauth_metadata.token``.

    Args:
        payload: The plaintext ``oauth2`` payload.
        registration: ``dynamic`` when the client was registered with RFC 7591, else
            ``preregistered``.

    Returns:
        ``client_id``, ``client_registration``, ``scope``, ``expires_at``, ``obtained_at``,
        ``refreshable`` and ``last_refresh_error`` (``None``). No token or secret.
    """
    return {
        "client_id": payload.get("client_id"),
        "client_registration": registration,
        "scope": payload.get("scope"),
        "expires_at": payload.get("expires_at"),
        "obtained_at": payload.get("obtained_at"),
        "refreshable": bool(payload.get("refresh_token")),
        "last_refresh_error": None,
    }
