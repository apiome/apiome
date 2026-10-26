"""Shared fetch helpers for live import discovery — MFI-11.3 (#3778), MFI-13.3 (#3790).

The live-discovery adapters (OData ``$metadata``, WSDL ``?singleWsdl``) read documents from a
user-supplied service URL. They share three rules, kept here:

* every request goes through an SSRF-guarded client (:func:`app.ssrf_guard.build_guarded_client`,
  each redirect hop re-validated) unless a test injects one;
* a credential from the credential vault is turned into request headers
  (:func:`app.mcp_auth.build_auth_headers`) — tokens travel in headers, never in the URL;
* an HTTP failure maps to the intake taxonomy: 404 → ``SOURCE_NOT_FOUND``, 401/403 →
  ``SOURCE_AUTH_REQUIRED``, a network error or any other status → ``SOURCE_UNREACHABLE``, a body
  over the limit → ``INPUT_TOO_LARGE``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import httpx

from .import_source import ImportSourceError
from .mcp_auth import AUTH_TYPE_NONE, CredentialPayloadError, build_auth_headers
from .ssrf_guard import SSRFError, build_guarded_client, validate_url

__all__ = ["LIVE_FETCH_TIMEOUT", "auth_headers", "check_public_url", "guarded_client", "guarded_get"]

#: Per-request timeout for live discovery.
LIVE_FETCH_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_UA = "apiome-live-discovery/1.0"


def auth_headers(auth_type: Optional[str], auth_payload: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Request headers for a credential-vault entry (``{}`` for none).

    Raises:
        ImportSourceError: When the credential is missing or malformed for ``auth_type``.
    """
    if not auth_type or auth_type == AUTH_TYPE_NONE:
        return {}
    if auth_payload is None:
        raise ImportSourceError(f"auth_type={auth_type!r} requires a credential payload")
    try:
        return build_auth_headers(auth_type, dict(auth_payload))
    except CredentialPayloadError as exc:
        raise ImportSourceError(str(exc)) from exc


def check_public_url(url: str, *, what: str) -> None:
    """Refuse a URL the SSRF policy forbids, before any request is made.

    Raises:
        ImportSourceError: Naming ``what`` and the reason.
    """
    try:
        validate_url(url)
    except SSRFError as exc:
        raise ImportSourceError(f"The {what} URL is not allowed: {exc}") from exc


def guarded_client() -> httpx.Client:
    """A new SSRF-guarded client that follows (re-validated) redirects."""
    return build_guarded_client(timeout=LIVE_FETCH_TIMEOUT, follow_redirects=True)


def guarded_get(
    client: httpx.Client,
    url: str,
    *,
    accept: str,
    headers: Mapping[str, str],
    what: str,
    max_bytes: int,
) -> str:
    """GET ``url`` and return its body as text, mapping failures to intake codes.

    Args:
        client: The (guarded) client.
        url: The URL.
        accept: The ``Accept`` header.
        headers: Extra headers (auth first).
        what: What is being fetched, for messages (``"$metadata document"``).
        max_bytes: The largest body accepted.

    Raises:
        ImportSourceError: ``SOURCE_NOT_FOUND`` (404), ``SOURCE_AUTH_REQUIRED`` (401/403),
            ``SOURCE_UNREACHABLE`` (network error, other status), ``INPUT_TOO_LARGE``; a redirect
            to a forbidden address is refused without a code.
    """
    try:
        response = client.get(url, headers={"User-Agent": _UA, "Accept": accept, **dict(headers)})
    except SSRFError as exc:
        raise ImportSourceError(f"The {what} URL is not allowed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ImportSourceError(f"Could not reach the {what} at {url}: {exc}", code="SOURCE_UNREACHABLE") from exc
    if response.status_code == 404:
        raise ImportSourceError(f"The {what} was not found at {url} (HTTP 404).", code="SOURCE_NOT_FOUND")
    if response.status_code in (401, 403):
        raise ImportSourceError(
            f"The {what} at {url} needs credentials (HTTP {response.status_code}).",
            code="SOURCE_AUTH_REQUIRED",
        )
    if response.status_code >= 400:
        raise ImportSourceError(f"The {what} at {url} returned HTTP {response.status_code}.", code="SOURCE_UNREACHABLE")
    if len(response.content) > max_bytes:
        raise ImportSourceError(f"The {what} exceeds the {max_bytes}-byte limit.", code="INPUT_TOO_LARGE")
    return response.content.decode("utf-8", errors="replace")
