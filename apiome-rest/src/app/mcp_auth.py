"""The MCP outbound auth-type model: turn a decrypted credential into request headers.

MCAT-6.1 (#3677). A protected MCP server is reached by attaching a credential to every
outbound request. This module owns the *model* — the mapping from an endpoint's ``auth_type``
and its **decrypted** secret payload onto the HTTP headers the Streamable HTTP transport
(:class:`app.mcp_client.transport_http.StreamableHttpTransport`) attaches to each request.

It is deliberately split from its two neighbours so each can land and be tested in isolation:

* **Encryption-at-rest** (sealing/unsealing ``encrypted_payload``) is MCAT-6.2 (#3678). This
  module never touches ciphertext or keys; it only ever sees the plaintext payload the
  credential loader (:mod:`app.mcp_credentials`) hands it once decryption is wired in.
* **The OAuth 2.1 flows** (metadata discovery, auth-code+PKCE, token refresh) are MCAT-6.3/6.4.
  Here ``oauth2`` is honoured only to the extent of presenting an *already-obtained* access
  token as a bearer header; obtaining/refreshing that token lives in those later tickets.

Supported auth types (per the
`MCP authorization spec <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>`_
and the V129 credential-vault schema):

* ``none``   — anonymous server; contributes no headers.
* ``bearer`` — ``Authorization: Bearer <token>``.
* ``header`` — one arbitrary ``<name>: <value>`` request header.
* ``oauth2`` — presents ``payload['access_token']`` as a bearer header (full flow elsewhere).
* ``env``    — an environment-variable bundle for a *future* stdio transport; it contributes
  **no** HTTP headers (see :func:`env_vars_for_payload`).

Security invariants this module enforces:

* **Tokens only ever travel in headers, never in a URL/query string** (per the MCP spec). This
  module returns headers only — it never constructs, mutates, or returns a URL.
* **No header injection.** Header names are validated against the RFC 9110 token grammar and
  header values are rejected if they contain ``CR``/``LF`` or other control characters, so a
  stored secret can never split the request or smuggle in extra headers.
* **Secrets are never logged.** Errors describe only the non-secret shape problem and the
  ``auth_type``; the offending value is never included.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping

# Canonical auth-type identifiers (mirror the V129 ``auth_type`` CHECK constraint).
AUTH_TYPE_NONE = "none"
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_HEADER = "header"
AUTH_TYPE_OAUTH2 = "oauth2"
AUTH_TYPE_ENV = "env"

#: Every auth type the model understands. A type outside this set is a programming/data error.
SUPPORTED_AUTH_TYPES = frozenset(
    {AUTH_TYPE_NONE, AUTH_TYPE_BEARER, AUTH_TYPE_HEADER, AUTH_TYPE_OAUTH2, AUTH_TYPE_ENV}
)

AUTHORIZATION_HEADER = "Authorization"

# RFC 9110 §5.1 "token": the characters a header field-name may legally contain. Anything else
# (notably ':', whitespace, or controls) would let a stored name break the header framing.
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

# Characters forbidden anywhere in a header value (or a bearer token, which becomes one): the C0
# control range and DEL, minus horizontal tab which RFC 9110 permits in a field-value. CR and LF
# fall in this range, so this single check is also the header-injection / request-splitting guard.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")


class CredentialPayloadError(ValueError):
    """A decrypted credential payload is malformed for its declared ``auth_type``.

    Raised for a missing/blank required field, a value of the wrong type, an unsupported
    ``auth_type``, or a name/value that would corrupt the HTTP header framing. The message
    never contains secret material — only the ``auth_type`` and the non-secret shape problem —
    so it is safe to log and surface.
    """


def _require_str(payload: Mapping[str, Any], key: str, auth_type: str) -> str:
    """Return ``payload[key]`` as a non-empty string, or raise :class:`CredentialPayloadError`.

    Args:
        payload: The decrypted credential payload.
        key: The required field name.
        auth_type: The auth type, for the (secret-free) error message.

    Returns:
        The field's string value (not stripped — a credential value may be space-sensitive).

    Raises:
        CredentialPayloadError: If the field is absent, not a string, or empty/whitespace.
    """
    value = payload.get(key)
    if value is None:
        raise CredentialPayloadError(f"{auth_type} credential payload is missing '{key}'")
    if not isinstance(value, str):
        raise CredentialPayloadError(
            f"{auth_type} credential payload field '{key}' must be a string"
        )
    if not value.strip():
        raise CredentialPayloadError(f"{auth_type} credential payload field '{key}' is empty")
    return value


def _validate_header_value(value: str, auth_type: str, field: str) -> str:
    """Reject a header value (or bearer token) carrying control/CRLF characters.

    This is the request-splitting / header-injection guard: a stored secret must never be able
    to introduce a newline and thereby forge additional headers or a second request.

    Args:
        value: The candidate header value.
        auth_type: The auth type, for the (secret-free) error message.
        field: The payload field name the value came from, for the error message.

    Returns:
        ``value`` unchanged when it is safe.

    Raises:
        CredentialPayloadError: If ``value`` contains a control or CR/LF character.
    """
    if _CONTROL_CHARS_RE.search(value):
        raise CredentialPayloadError(
            f"{auth_type} credential payload field '{field}' contains illegal "
            "control characters (possible header injection)"
        )
    return value


def _validate_header_name(name: str) -> str:
    """Return ``name`` if it is a legal HTTP header field-name, else raise.

    Args:
        name: The candidate header name.

    Returns:
        ``name`` unchanged when it is a valid RFC 9110 token.

    Raises:
        CredentialPayloadError: If ``name`` is not a valid header token (e.g. contains a colon,
            whitespace, or control character).
    """
    if not _HEADER_NAME_RE.match(name):
        raise CredentialPayloadError(
            f"header credential payload field 'name' ({name!r}) is not a valid HTTP header name"
        )
    return name


def _bearer_headers(token: str, auth_type: str, field: str) -> Dict[str, str]:
    """Build an ``Authorization: Bearer <token>`` header from a validated token."""
    _validate_header_value(token, auth_type, field)
    return {AUTHORIZATION_HEADER: f"Bearer {token}"}


def build_auth_headers(auth_type: str, payload: Mapping[str, Any]) -> Dict[str, str]:
    """Map a decrypted credential onto the HTTP headers to attach to every request.

    The headers returned here are merged into every outbound MCP request by the transport.
    The credential is supplied **decrypted**: this function performs no decryption and reads no
    keys (that is MCAT-6.2). It only ever returns headers — never a URL — upholding the spec
    rule that tokens travel in headers, never in the URL.

    Expected payload shape per ``auth_type``:

    * ``none``   — payload ignored; returns ``{}``.
    * ``bearer`` — ``{"token": "<secret>"}`` → ``{"Authorization": "Bearer <secret>"}``.
    * ``header`` — ``{"name": "<Header-Name>", "value": "<secret>"}`` → ``{<name>: <value>}``.
    * ``oauth2`` — ``{"access_token": "<token>", "token_type": "Bearer"?}``. When an access
      token is present it becomes an ``Authorization`` header (default scheme ``Bearer``);
      when absent, ``{}`` is returned (token acquisition/refresh is MCAT-6.3/6.4).
    * ``env``    — payload ignored for HTTP; returns ``{}`` (env vars are not request headers;
      see :func:`env_vars_for_payload`).

    Args:
        auth_type: One of :data:`SUPPORTED_AUTH_TYPES`.
        payload: The decrypted credential payload (empty/ignored for ``none`` and ``env``).

    Returns:
        The auth headers to attach to every request — possibly empty.

    Raises:
        CredentialPayloadError: If ``auth_type`` is unsupported, or the payload is missing a
            required field or carries a value that would corrupt the HTTP header framing.
    """
    if auth_type == AUTH_TYPE_NONE:
        return {}

    if auth_type == AUTH_TYPE_BEARER:
        token = _require_str(payload, "token", AUTH_TYPE_BEARER)
        return _bearer_headers(token, AUTH_TYPE_BEARER, "token")

    if auth_type == AUTH_TYPE_HEADER:
        name = _validate_header_name(_require_str(payload, "name", AUTH_TYPE_HEADER))
        value = _require_str(payload, "value", AUTH_TYPE_HEADER)
        _validate_header_value(value, AUTH_TYPE_HEADER, "value")
        return {name: value}

    if auth_type == AUTH_TYPE_OAUTH2:
        access_token = payload.get("access_token")
        if not access_token:
            # No token yet: the OAuth flow (MCAT-6.3/6.4) has not produced one. Send no auth
            # rather than guess; the server's 401 surfaces through the normal error taxonomy.
            return {}
        if not isinstance(access_token, str) or not access_token.strip():
            raise CredentialPayloadError(
                "oauth2 credential payload field 'access_token' must be a non-empty string"
            )
        token_type = payload.get("token_type") or "Bearer"
        if not isinstance(token_type, str) or not token_type.strip():
            raise CredentialPayloadError(
                "oauth2 credential payload field 'token_type' must be a non-empty string"
            )
        scheme = token_type.strip()
        _validate_header_value(access_token, AUTH_TYPE_OAUTH2, "access_token")
        _validate_header_value(scheme, AUTH_TYPE_OAUTH2, "token_type")
        return {AUTHORIZATION_HEADER: f"{scheme} {access_token}"}

    if auth_type == AUTH_TYPE_ENV:
        # Environment variables are injected into a future stdio child process, not sent as
        # HTTP headers. An HTTP discovery run contributes nothing from an env credential.
        return {}

    raise CredentialPayloadError(f"unsupported auth_type {auth_type!r}")


def validate_credential_payload(auth_type: str, payload: Mapping[str, Any]) -> None:
    """Validate a *plaintext* credential payload against its ``auth_type`` before it is sealed.

    The check that gates **storing** a secret (MCAT-6.5) is deliberately the same model that gates
    **using** one (MCAT-6.1): a payload that would not produce valid request headers must not be
    accepted into the vault. Reusing :func:`build_auth_headers` / :func:`env_vars_for_payload` also
    means the request-splitting / header-injection guards apply at write time, so a malformed or
    hostile secret is rejected at the REST boundary rather than silently degrading discovery later.

    Required shape per ``auth_type``:

    * ``bearer`` — ``{"token": "<secret>"}`` (non-empty string).
    * ``header`` — ``{"name": "<Header-Name>", "value": "<secret>"}`` (valid header name + value).
    * ``oauth2`` — ``{"access_token": "<token>", "token_type": "Bearer"?}``; an ``access_token`` is
      required here (a manually-set oauth2 credential must carry a token — automatic acquisition is
      MCAT-6.3/6.4).
    * ``env``    — ``{"vars": {"NAME": "value", ...}}`` (a non-empty string→string map).
    * ``none``   — no payload (anonymous; reached by clearing the credential, not setting one).

    Args:
        auth_type: One of :data:`SUPPORTED_AUTH_TYPES`.
        payload: The decrypted/plaintext credential payload to validate.

    Raises:
        CredentialPayloadError: If ``auth_type`` is unsupported or the payload is missing a required
            field, carries a value of the wrong type, or would corrupt the HTTP header framing. The
            message is secret-free, so it is safe to surface to the caller and log.
    """
    if auth_type not in SUPPORTED_AUTH_TYPES:
        raise CredentialPayloadError(f"unsupported auth_type {auth_type!r}")
    if auth_type == AUTH_TYPE_NONE:
        return
    if auth_type == AUTH_TYPE_ENV:
        if not env_vars_for_payload(auth_type, payload):
            raise CredentialPayloadError(
                "env credential payload requires a non-empty 'vars' object"
            )
        return
    if auth_type == AUTH_TYPE_OAUTH2 and not payload.get("access_token"):
        # build_auth_headers tolerates a token-less oauth2 payload (the flow may not have run yet),
        # but a credential the tenant is *setting* by hand must carry the token to be meaningful.
        raise CredentialPayloadError("oauth2 credential payload requires 'access_token'")
    # bearer/header/oauth2 all validate through the header model (shape + injection guards).
    build_auth_headers(auth_type, payload)


def env_vars_for_payload(auth_type: str, payload: Mapping[str, Any]) -> Dict[str, str]:
    """Return the environment-variable bundle for an ``env`` credential (future stdio).

    The ``env`` auth type carries a ``{"vars": {"NAME": "value", ...}}`` map intended to be set
    in the environment of a stdio MCP child process (a transport not yet implemented). It is
    surfaced here — separate from :func:`build_auth_headers`, which returns HTTP headers only —
    so the model for it exists and is tested now, ready for the stdio transport to consume.

    Args:
        auth_type: The credential's auth type.
        payload: The decrypted credential payload.

    Returns:
        A name→value environment map for ``env`` credentials; ``{}`` for every other auth type.

    Raises:
        CredentialPayloadError: If an ``env`` payload's ``vars`` is not a string→string map.
    """
    if auth_type != AUTH_TYPE_ENV:
        return {}
    raw = payload.get("vars")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise CredentialPayloadError("env credential payload field 'vars' must be an object")
    result: Dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise CredentialPayloadError(
                "env credential payload 'vars' contains a non-string or empty name"
            )
        if not isinstance(value, str):
            raise CredentialPayloadError(
                f"env credential payload variable '{key}' must be a string"
            )
        result[key] = value
    return result
