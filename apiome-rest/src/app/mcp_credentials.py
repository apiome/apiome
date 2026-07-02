"""Load an MCP endpoint's auth headers for a discovery run (Epic-6 seam).

A discovery/test run against a protected MCP server must authenticate to it (V2-MCP-17.2, #3664).
Credentials live in ``apiome.mcp_endpoint_credentials`` (V129) as **ciphertext** keyed by
``auth_type``; this module turns a stored credential into the HTTP headers the
:class:`app.mcp_client.transport_http.StreamableHttpTransport` attaches to every request.

The work splits across two tickets that meet here:

* **MCAT-6.1 (#3677)** — the *auth-type model*: how a **decrypted** payload becomes headers for
  ``none``/``bearer``/``header`` (and ``oauth2``/``env``). That mapping lives in
  :mod:`app.mcp_auth`; this module wires it to the credential store and to discovery.
* **MCAT-6.2 (#3678)** — *encryption-at-rest*: sealing/unsealing ``encrypted_payload`` with an
  app-managed key. :func:`decrypt_credential_payload` is the single seam that unseals a stored
  row's ciphertext in-memory at connect time, delegating to
  :func:`app.mcp_credential_crypto.unseal_credential_payload`. When no plaintext can be produced
  (encryption unconfigured, the row's key removed, or a tampered blob) it returns ``None``, so a
  sealed credential yields no headers and discovery proceeds unauthenticated — surfacing the
  server's ``AUTH_REQUIRED`` response through the normal error taxonomy rather than guessing at a
  secret it cannot read.

The ``none`` auth type (or no credential row at all) is fully supported today: it yields no auth
headers, which is exactly right for public/anonymous MCP servers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .database import db
from .mcp_auth import AUTH_TYPE_NONE, CredentialPayloadError, build_auth_headers
from .mcp_credential_crypto import unseal_credential_payload

logger = logging.getLogger(__name__)


def decrypt_credential_payload(credential: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Unseal a credential row's ``encrypted_payload`` into its plaintext dict (MCAT-6.2 seam).

    This is the *only* place credential ciphertext is turned back into plaintext. It delegates the
    envelope decryption to :func:`app.mcp_credential_crypto.unseal_credential_payload`, passing the
    row's ciphertext and its ``key_version`` (so the right master key is selected for rotation).
    A row with no ciphertext, or one that cannot be decrypted (encryption unconfigured, the sealing
    key removed, or a tampered blob), yields ``None`` — and a caller that gets ``None`` for a
    non-``none`` credential runs the request unauthenticated rather than fabricating a header.

    Args:
        credential: An ``mcp_endpoint_credentials`` row (``auth_type``, ``encrypted_payload``,
            ``key_version``, ``oauth_metadata``, …).

    Returns:
        The decrypted credential payload as a dict, or ``None`` when no plaintext can be produced
        (the row carries no ciphertext, or decryption is not possible).
    """
    return unseal_credential_payload(
        credential.get("encrypted_payload"), credential.get("key_version")
    )


def _headers_for_credential(credential: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Map a stored credential row onto request headers via the auth-type model.

    ``none`` (and a missing row) yields no headers without any decryption. For every other
    ``auth_type`` the sealed payload is first unsealed through :func:`decrypt_credential_payload`;
    when plaintext is available it is handed to :func:`app.mcp_auth.build_auth_headers`, which
    produces the ``Authorization``/custom header (tokens only ever in headers, never in a URL).
    When no plaintext is available — decryption not wired yet (MCAT-6.2) — discovery proceeds
    unauthenticated.

    Args:
        credential: An ``mcp_endpoint_credentials`` row, or ``None`` when the endpoint has no
            credential configured.

    Returns:
        The auth headers to attach to discovery requests — empty for anonymous endpoints, a
        malformed payload, or a secret that cannot be decrypted yet.
    """
    if credential is None:
        return {}
    auth_type = str(credential.get("auth_type") or AUTH_TYPE_NONE)
    if auth_type == AUTH_TYPE_NONE:
        return {}

    payload = decrypt_credential_payload(credential)
    if payload is None:
        # A secret is configured but no plaintext is available (the MCAT-6.2 decrypting key path
        # is not wired into REST yet, or the row carries no ciphertext); proceed unauthenticated
        # rather than fabricate a header.
        logger.warning(
            "MCP endpoint credential auth_type=%s has no decryptable payload; "
            "running discovery without auth headers",
            auth_type,
        )
        return {}

    try:
        return build_auth_headers(auth_type, payload)
    except CredentialPayloadError:
        # The stored payload does not match its auth_type (or would corrupt the header framing).
        # Degrade to an unauthenticated run; the message is secret-free so it is safe to log.
        logger.warning(
            "MCP endpoint credential auth_type=%s payload is malformed; "
            "running discovery without auth headers",
            auth_type,
            exc_info=True,
        )
        return {}


def load_endpoint_auth_headers(endpoint_id: str) -> Dict[str, str]:
    """Return the auth headers for an endpoint's discovery run (synchronous DB read).

    Best-effort: any failure reading the credential is swallowed (logged) and treated as
    "no credential", so a credential-store hiccup degrades to an unauthenticated run instead
    of failing the whole discovery before it starts.

    Args:
        endpoint_id: The endpoint whose credentials to load.

    Returns:
        A possibly-empty header dict suitable for :class:`StreamableHttpTransport`.
    """
    try:
        credential = db.get_mcp_endpoint_credentials(endpoint_id)
    except Exception:  # noqa: BLE001 - credential lookup is best-effort
        logger.warning(
            "failed to load credentials for MCP endpoint %s; running discovery "
            "without auth headers",
            endpoint_id,
            exc_info=True,
        )
        return {}
    return _headers_for_credential(credential)
