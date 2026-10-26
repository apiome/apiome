"""OpenRPC service discovery for ``apiome import openrpc --discover`` (MFI-19.1, #3979).

A JSON-RPC 2.0 service that follows the OpenRPC *Service Discovery Method* answers the reserved
method ``rpc.discover`` with its own OpenRPC document. Unlike the other ``--discover`` verbs,
which resolve a URL the server then fetches, this one is a ``POST``: :func:`discover_openrpc_document`
makes the call and returns the document, which is then uploaded through the ordinary
registry-dispatch import as if it were a file. The rules mirror the REST adapter's live discovery
(``app.openrpc_discovery``).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import httpx

#: The JSON-RPC 2.0 ``rpc.discover`` call.
DISCOVER_REQUEST = {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": []}

#: JSON-RPC 2.0 "Method not found" error code.
_METHOD_NOT_FOUND = -32601


def openrpc_endpoint_url(endpoint: str) -> str:
    """Normalize a JSON-RPC endpoint URL.

    Args:
        endpoint: The endpoint (``https://rpc.example.com/`` or ``https://host/rpc``). Path and
            query are kept — many providers put an API key in either.

    Returns:
        The URL with a lower-cased scheme and no fragment.

    Raises:
        ValueError: When the URL is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (endpoint or "").strip()
    if not cleaned:
        raise ValueError("JSON-RPC endpoint URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("JSON-RPC endpoint URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("JSON-RPC endpoint URL has no host")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, "")
    )


def openrpc_document_from_reply(body: str, *, url: str) -> bytes:
    """Extract the OpenRPC document from an ``rpc.discover`` reply.

    Args:
        body: The HTTP response body.
        url: The endpoint, for messages.

    Returns:
        The reply's ``result`` as indented UTF-8 JSON.

    Raises:
        OSError: When the reply is not JSON-RPC, carries an error (``-32601`` = the service does
            not implement ``rpc.discover``), or its ``result`` is not an object.
    """
    try:
        reply = json.loads(body)
    except ValueError as exc:
        raise OSError(f"{url} did not answer rpc.discover with JSON") from exc
    if isinstance(reply, list) and len(reply) == 1:
        reply = reply[0]
    if not isinstance(reply, dict):
        raise OSError(f"{url} did not answer rpc.discover with a JSON-RPC response")
    error = reply.get("error")
    if error is not None:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        if code == _METHOD_NOT_FOUND:
            raise OSError(
                f"The JSON-RPC service at {url} does not implement rpc.discover"
            )
        raise OSError(
            f"The JSON-RPC service at {url} answered rpc.discover with an error: {message or code}"
        )
    result = reply.get("result")
    if not isinstance(result, dict):
        raise OSError(f"{url} returned no OpenRPC document from rpc.discover")
    return json.dumps(result, indent=2, ensure_ascii=False).encode("utf-8")


def discover_openrpc_document(
    endpoint: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
    client: httpx.Client | None = None,
) -> tuple[str, bytes]:
    """Call ``rpc.discover`` on a JSON-RPC endpoint and return its OpenRPC document.

    Args:
        endpoint: The JSON-RPC endpoint.
        timeout: HTTP timeout, in seconds.
        verify: Whether to verify TLS certificates.
        client: Optional httpx client (tests); one is created and closed otherwise.

    Returns:
        ``(endpoint URL, document bytes)``.

    Raises:
        ValueError: When ``endpoint`` is unusable.
        OSError: On a network failure, an HTTP error, or a reply with no document.
    """
    url = openrpc_endpoint_url(endpoint)
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, verify=verify, follow_redirects=True)
    try:
        try:
            response = http.post(
                url, json=DISCOVER_REQUEST, headers={"Accept": "application/json"}
            )
        except httpx.RequestError as exc:
            raise OSError(f"Failed to call rpc.discover on {url!r}: {exc}") from exc
    finally:
        if owns_client:
            http.close()
    if response.status_code >= 400:
        raise OSError(f"rpc.discover on {url} returned HTTP {response.status_code}")
    return url, openrpc_document_from_reply(response.text, url=url)
