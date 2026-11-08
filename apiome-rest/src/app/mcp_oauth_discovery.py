"""OAuth 2.1 authorization-server discovery for protected MCP servers (RFC 9728 / RFC 8414).

MCAT-6.3 (#3679). A protected remote MCP server answers an unauthenticated request with
``401 Unauthorized`` and a ``WWW-Authenticate`` challenge. Per the
`MCP authorization spec <https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization>`_
the client then:

1. reads the challenge's ``resource_metadata`` URL (RFC 9728 §5.1), falling back to the
   resource's well-known ``/.well-known/oauth-protected-resource`` URL (RFC 9728 §3.1);
2. fetches that **Protected Resource Metadata** (PRM), which names the server's resource
   identifier, its ``authorization_servers`` and its ``scopes_supported``;
3. fetches each authorization server's **Authorization Server Metadata** from
   ``/.well-known/oauth-authorization-server`` (RFC 8414 §3.1) until one resolves.

:func:`discover_oauth_metadata` runs those steps and returns the non-secret result as the flat
dict stored in ``mcp_endpoint_credentials.oauth_metadata`` (authorize / token / registration
endpoints, scopes, resource indicator). Obtaining tokens with that metadata is MCAT-6.4 (#3680).

Safety rules for every metadata fetch (the URLs come from a remote server, so they are untrusted):

* ``https://`` only; plain ``http://`` is allowed to a loopback host, the same rule the MCP
  transport applies (:mod:`app.mcp_client.transport_http`).
* IP literals in non-public ranges (RFC 1918, link-local, reserved, …) are refused (SSRF guard);
  loopback is exempt, as in the transport.
* Redirects are not followed, each fetch has a short timeout and the body is capped at
  :data:`MAX_METADATA_BYTES`.
* The documents are cross-checked: the PRM ``resource`` must share the endpoint URL's origin and
  be a path prefix of it, and the AS ``issuer`` must equal the issuer it was fetched for
  (RFC 8414 §3.3), so a server cannot hand back another party's metadata.

Nothing here touches secrets: the challenge, the URLs and both metadata documents are public.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx

from .mcp_client.resilience import private_address_reason

#: Well-known path suffix of RFC 9728 Protected Resource Metadata.
PROTECTED_RESOURCE_WELL_KNOWN = "/.well-known/oauth-protected-resource"

#: Well-known path suffix of RFC 8414 Authorization Server Metadata.
AUTHORIZATION_SERVER_WELL_KNOWN = "/.well-known/oauth-authorization-server"

#: Largest metadata document accepted (bytes); a larger body is refused rather than parsed.
MAX_METADATA_BYTES = 256 * 1024

#: Per-request timeout (seconds) for one metadata fetch.
METADATA_TIMEOUT_SECONDS = 10.0

#: Value of ``oauth_metadata.source`` for metadata this module discovered.
OAUTH_DISCOVERY_SOURCE = "oauth_discovery"


class OAuthDiscoveryError(Exception):
    """OAuth metadata could not be resolved.

    Attributes:
        code: Stable machine-readable reason — ``invalid_url``, ``fetch_failed``,
            ``not_found``, ``invalid_metadata``, ``resource_mismatch`` or ``issuer_mismatch``.
        message: Human-readable detail (contains URLs only, never a secret).
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> Dict[str, str]:
        """Return ``{"code", "message"}`` for a job result payload."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class AuthChallenge:
    """One challenge from a ``WWW-Authenticate`` header (RFC 9110 §11.6.1).

    Attributes:
        scheme: The auth scheme, lower-cased (e.g. ``"bearer"``).
        params: The challenge's auth-params with lower-cased names and unquoted values.
    """

    scheme: str
    params: Dict[str, str] = field(default_factory=dict)


# ===========================================================================
# WWW-Authenticate parsing
# ===========================================================================

_TCHARS = set("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t":
        i += 1
    return i


def _read_token(text: str, i: int) -> Tuple[str, int]:
    start = i
    while i < len(text) and text[i] in _TCHARS:
        i += 1
    return text[start:i], i


def _read_quoted(text: str, i: int) -> Tuple[str, int]:
    """Read a quoted-string starting at the opening quote; returns (value, index after close)."""
    out: List[str] = []
    i += 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return "".join(out), i


def parse_www_authenticate(header: Optional[str]) -> List[AuthChallenge]:
    """Parse a ``WWW-Authenticate`` header value into its challenges.

    Handles several comma-separated challenges, quoted-string values with backslash escapes
    and a bare ``token68`` (kept under the ``token68`` param). Malformed input never raises:
    whatever parsed cleanly before the bad text is returned.

    Args:
        header: The raw header value, or ``None`` when the server sent none.

    Returns:
        The challenges in header order (empty for a missing or blank header).
    """
    text = (header or "").strip()
    challenges: List[AuthChallenge] = []
    i = 0
    while i < len(text):
        i = _skip_ws(text, i)
        while i < len(text) and text[i] == ",":
            i = _skip_ws(text, i + 1)
        scheme, i = _read_token(text, i)
        if not scheme:
            break
        params: Dict[str, str] = {}
        i = _skip_ws(text, i)
        while i < len(text):
            name, j = _read_token(text, i)
            j = _skip_ws(text, j)
            if not name:
                break
            if j < len(text) and text[j] == "=" and not text[j:].startswith("=="):
                j = _skip_ws(text, j + 1)
                if j < len(text) and text[j] == '"':
                    value, j = _read_quoted(text, j)
                else:
                    value, j = _read_token(text, j)
                params[name.lower()] = value
                i = _skip_ws(text, j)
                if i < len(text) and text[i] == ",":
                    # Peek past the comma: another auth-param continues this challenge, a bare
                    # token starts the next one.
                    k = _skip_ws(text, i + 1)
                    nxt, m = _read_token(text, k)
                    m = _skip_ws(text, m)
                    if nxt and m < len(text) and text[m] == "=":
                        i = k
                        continue
                break
            if not params:
                # A token68 credential: the token plus any trailing '=' padding.
                end = j
                while end < len(text) and text[end] == "=":
                    end += 1
                params["token68"] = text[i:end]
                i = _skip_ws(text, end)
            break
        challenges.append(AuthChallenge(scheme=scheme.lower(), params=params))
        i = _skip_ws(text, i)
        if i < len(text) and text[i] != ",":
            break
    return challenges


def bearer_challenge(header: Optional[str]) -> Optional[AuthChallenge]:
    """Return the ``Bearer`` challenge of a ``WWW-Authenticate`` header, or ``None``."""
    for challenge in parse_www_authenticate(header):
        if challenge.scheme == "bearer":
            return challenge
    return None


# ===========================================================================
# URL rules
# ===========================================================================


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def check_metadata_url(url: str) -> str:
    """Validate a URL Apiome is about to fetch metadata from, or point a client at.

    Args:
        url: An absolute URL taken from a server's challenge or metadata.

    Returns:
        The URL unchanged when it is allowed.

    Raises:
        OAuthDiscoveryError: ``invalid_url`` when it is not absolute ``https://`` (``http://``
            only to loopback), carries credentials or a fragment, or names a non-public IP literal.
    """
    parts = urlsplit(url or "")
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    if scheme not in ("http", "https") or not host:
        raise OAuthDiscoveryError("invalid_url", f"not an absolute http(s) URL: {url!r}")
    if parts.username or parts.password:
        raise OAuthDiscoveryError("invalid_url", "URLs carrying credentials are refused")
    if parts.fragment:
        raise OAuthDiscoveryError("invalid_url", f"URL has a fragment: {url!r}")
    loopback = _is_loopback(host)
    if scheme == "http" and not loopback:
        raise OAuthDiscoveryError("invalid_url", f"plain http:// is only allowed to loopback: {url!r}")
    if not loopback:
        reason = private_address_reason(host)
        if reason is not None:
            raise OAuthDiscoveryError("invalid_url", f"host {host!r} is a {reason} address (SSRF guard)")
    return url


def _origin(url: str) -> Tuple[str, str, Optional[int]]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port or (443 if scheme == "https" else 80)
    return scheme, (parts.hostname or "").lower(), port


def _insert_well_known(url: str, suffix: str) -> str:
    """Insert ``suffix`` between a URL's host and path (RFC 8414 §3.1 / RFC 9728 §3.1)."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, f"{suffix}{path}", parts.query, ""))


def protected_resource_metadata_urls(endpoint_url: str, hint: Optional[str]) -> List[str]:
    """List the PRM URLs to try for an endpoint, most specific first.

    The challenge's ``resource_metadata`` URL comes first when present, then the well-known URL
    with the endpoint's path inserted, then the origin's root well-known URL.

    Args:
        endpoint_url: The MCP endpoint URL the ``401`` came from.
        hint: The challenge's ``resource_metadata`` param, if any.

    Returns:
        De-duplicated candidate URLs (query strings dropped from the derived ones).
    """
    parts = urlsplit(endpoint_url)
    bare = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    candidates: List[str] = []
    if hint:
        candidates.append(hint.strip())
    candidates.append(_insert_well_known(bare, PROTECTED_RESOURCE_WELL_KNOWN))
    candidates.append(urlunsplit((parts.scheme, parts.netloc, PROTECTED_RESOURCE_WELL_KNOWN, "", "")))
    seen: List[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.append(candidate)
    return seen


def authorization_server_metadata_url(issuer: str) -> str:
    """Return an issuer's RFC 8414 metadata URL (``/.well-known/…`` inserted before its path)."""
    return _insert_well_known(issuer, AUTHORIZATION_SERVER_WELL_KNOWN)


def resource_matches_endpoint(resource: str, endpoint_url: str) -> bool:
    """True when a PRM ``resource`` names this endpoint.

    The resource must share the endpoint's origin (scheme, host, port) and its path must be the
    endpoint's path or a ``/``-bounded prefix of it — a server may advertise its origin or its
    ``/mcp`` path as the resource, but never another host.
    """
    try:
        if _origin(resource) != _origin(endpoint_url):
            return False
    except ValueError:
        return False
    resource_path = urlsplit(resource).path.rstrip("/")
    endpoint_path = urlsplit(endpoint_url).path.rstrip("/")
    return endpoint_path == resource_path or endpoint_path.startswith(resource_path + "/")


# ===========================================================================
# Fetching
# ===========================================================================


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
    """GET ``url`` and return its JSON object body.

    Raises:
        OAuthDiscoveryError: ``invalid_url``, ``fetch_failed`` (network error, non-2xx other than
            404/410, oversized or non-JSON body), ``not_found`` (404/410) or ``invalid_metadata``
            (JSON that is not an object).
    """
    check_metadata_url(url)
    try:
        async with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            if response.status_code in (404, 410):
                raise OAuthDiscoveryError("not_found", f"{url} returned HTTP {response.status_code}")
            if not 200 <= response.status_code < 300:
                raise OAuthDiscoveryError("fetch_failed", f"{url} returned HTTP {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_METADATA_BYTES:
                    raise OAuthDiscoveryError("fetch_failed", f"{url} is larger than {MAX_METADATA_BYTES} bytes")
    except httpx.HTTPError as exc:
        raise OAuthDiscoveryError("fetch_failed", f"{url}: {type(exc).__name__}") from exc
    try:
        document = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise OAuthDiscoveryError("fetch_failed", f"{url} did not return JSON") from exc
    if not isinstance(document, dict):
        raise OAuthDiscoveryError("invalid_metadata", f"{url} did not return a JSON object")
    return document


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _optional_endpoint(document: Dict[str, Any], name: str) -> Optional[str]:
    value = document.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise OAuthDiscoveryError("invalid_metadata", f"{name} is not a string")
    return check_metadata_url(value)


async def fetch_protected_resource_metadata(
    client: httpx.AsyncClient, endpoint_url: str, hint: Optional[str]
) -> Tuple[str, Dict[str, Any]]:
    """Fetch and validate the endpoint's RFC 9728 Protected Resource Metadata.

    Tries each URL from :func:`protected_resource_metadata_urls` in turn; a ``404`` moves on to
    the next candidate, any other failure stops.

    Returns:
        ``(url, document)`` — where the PRM was found and the validated document.

    Raises:
        OAuthDiscoveryError: No candidate resolved, or the document is invalid (no
            ``resource``, no ``authorization_servers``) or names another resource.
    """
    last: Optional[OAuthDiscoveryError] = None
    for url in protected_resource_metadata_urls(endpoint_url, hint):
        try:
            document = await _fetch_json(client, url)
        except OAuthDiscoveryError as exc:
            if exc.code != "not_found":
                raise
            last = exc
            continue
        resource = document.get("resource")
        if not isinstance(resource, str) or not resource:
            raise OAuthDiscoveryError("invalid_metadata", f"{url} has no resource")
        if not resource_matches_endpoint(resource, endpoint_url):
            raise OAuthDiscoveryError("resource_mismatch", f"{url} describes {resource}, not {endpoint_url}")
        if not _string_list(document.get("authorization_servers")):
            raise OAuthDiscoveryError("invalid_metadata", f"{url} lists no authorization_servers")
        return url, document
    raise last or OAuthDiscoveryError("not_found", "no protected resource metadata")


async def fetch_authorization_server_metadata(client: httpx.AsyncClient, issuer: str) -> Tuple[str, Dict[str, Any]]:
    """Fetch and validate one issuer's RFC 8414 Authorization Server Metadata.

    Returns:
        ``(url, document)`` — the metadata URL and the validated document.

    Raises:
        OAuthDiscoveryError: The fetch failed, the ``issuer`` differs from the one asked for, or
            ``authorization_endpoint`` / ``token_endpoint`` is missing or not an allowed URL.
    """
    check_metadata_url(issuer)
    if urlsplit(issuer).query:
        raise OAuthDiscoveryError("invalid_url", f"issuer has a query string: {issuer!r}")
    url = authorization_server_metadata_url(issuer)
    document = await _fetch_json(client, url)
    if document.get("issuer") != issuer:
        raise OAuthDiscoveryError("issuer_mismatch", f"{url} names issuer {document.get('issuer')!r}, not {issuer!r}")
    for name in ("authorization_endpoint", "token_endpoint"):
        if _optional_endpoint(document, name) is None:
            raise OAuthDiscoveryError("invalid_metadata", f"{url} has no {name}")
    for name in ("registration_endpoint", "revocation_endpoint"):
        _optional_endpoint(document, name)
    return url, document


def build_oauth_metadata(
    *,
    resource_metadata_url: str,
    resource_metadata: Dict[str, Any],
    issuer: str,
    authorization_server_metadata_url: str,
    authorization_server_metadata: Dict[str, Any],
    challenge: Optional[AuthChallenge],
    discovered_at: datetime,
) -> Dict[str, Any]:
    """Flatten the two validated documents into the stored ``oauth_metadata`` shape.

    Keys: ``source``, ``discovered_at``, ``resource`` (the RFC 8707 resource indicator),
    ``resource_metadata_url``, ``authorization_servers``, ``issuer``,
    ``authorization_server_metadata_url``, ``authorization_endpoint``, ``token_endpoint``,
    ``registration_endpoint`` / ``revocation_endpoint`` (``None`` when not advertised),
    ``scopes_supported`` (the resource's list, else the server's), ``challenge_scopes`` (the
    ``scope`` the ``401`` asked for), ``bearer_methods_supported``, ``grant_types_supported``,
    ``response_types_supported``, ``token_endpoint_auth_methods_supported``,
    ``code_challenge_methods_supported`` and ``pkce_s256_supported``.
    """
    asm = authorization_server_metadata
    prm = resource_metadata
    challenge_scope = (challenge.params.get("scope") if challenge else None) or ""
    code_methods = _string_list(asm.get("code_challenge_methods_supported"))
    return {
        "source": OAUTH_DISCOVERY_SOURCE,
        "discovered_at": discovered_at.isoformat(),
        "resource": prm["resource"],
        "resource_metadata_url": resource_metadata_url,
        "authorization_servers": _string_list(prm.get("authorization_servers")),
        "issuer": issuer,
        "authorization_server_metadata_url": authorization_server_metadata_url,
        "authorization_endpoint": asm["authorization_endpoint"],
        "token_endpoint": asm["token_endpoint"],
        "registration_endpoint": asm.get("registration_endpoint"),
        "revocation_endpoint": asm.get("revocation_endpoint"),
        "scopes_supported": _string_list(prm.get("scopes_supported")) or _string_list(asm.get("scopes_supported")),
        "challenge_scopes": challenge_scope.split(),
        "bearer_methods_supported": _string_list(prm.get("bearer_methods_supported")),
        "grant_types_supported": _string_list(asm.get("grant_types_supported")),
        "response_types_supported": _string_list(asm.get("response_types_supported")),
        "token_endpoint_auth_methods_supported": _string_list(asm.get("token_endpoint_auth_methods_supported")),
        "code_challenge_methods_supported": code_methods,
        "pkce_s256_supported": "S256" in code_methods,
    }


async def discover_oauth_metadata(
    endpoint_url: str,
    www_authenticate: Optional[str],
    *,
    client: Optional[httpx.AsyncClient] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Resolve a protected MCP endpoint's OAuth metadata after a ``401``.

    Reads the ``Bearer`` challenge's ``resource_metadata`` (and ``scope``), fetches the PRM, then
    tries each listed authorization server in order until one's RFC 8414 metadata validates.

    Args:
        endpoint_url: The MCP endpoint URL that answered ``401``.
        www_authenticate: The verbatim ``WWW-Authenticate`` header (``None`` when absent — the
            well-known URLs are still tried).
        client: An ``httpx.AsyncClient`` to use (tests pass one backed by a mock transport);
            when omitted a client with no redirects and :data:`METADATA_TIMEOUT_SECONDS` is made.
        now: The ``discovered_at`` timestamp (defaults to the current UTC time).

    Returns:
        The flat ``oauth_metadata`` dict from :func:`build_oauth_metadata`.

    Raises:
        OAuthDiscoveryError: Discovery failed; ``code`` says why.
    """
    challenge = bearer_challenge(www_authenticate)
    hint = challenge.params.get("resource_metadata") if challenge else None
    owned = client is None
    http = client or httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(METADATA_TIMEOUT_SECONDS))
    try:
        prm_url, prm = await fetch_protected_resource_metadata(http, endpoint_url, hint)
        failure: Optional[OAuthDiscoveryError] = None
        for issuer in _string_list(prm.get("authorization_servers")):
            try:
                asm_url, asm = await fetch_authorization_server_metadata(http, issuer)
            except OAuthDiscoveryError as exc:
                failure = failure or exc
                continue
            return build_oauth_metadata(
                resource_metadata_url=prm_url,
                resource_metadata=prm,
                issuer=issuer,
                authorization_server_metadata_url=asm_url,
                authorization_server_metadata=asm,
                challenge=challenge,
                discovered_at=now or datetime.now(timezone.utc),
            )
        raise failure or OAuthDiscoveryError("invalid_metadata", "no usable authorization server")
    finally:
        if owned:
            await http.aclose()
