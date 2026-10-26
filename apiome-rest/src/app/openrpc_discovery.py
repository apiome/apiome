"""OpenRPC live discovery — MFI-19.1 (#3979).

A JSON-RPC 2.0 service that follows the OpenRPC *Service Discovery Method* answers the reserved
method ``rpc.discover`` with its own OpenRPC document — the JSON-RPC analogue of gRPC server
reflection. :func:`discover_openrpc_service` makes that call::

    POST <endpoint>
    {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": []}

over the SSRF-guarded HTTP client (:func:`app.live_fetch.guarded_client`, every redirect hop
re-validated), with an optional credential from the credential vault, and returns the
``result`` member as document text. The adapter
(:meth:`app.openrpc_import_source.OpenRpcImportSource.discover`) parses it exactly as an upload
is parsed and records the endpoint on the catalog item.

Failures map to the intake taxonomy: the HTTP ones as :func:`app.live_fetch.guarded_post_json`
does; a JSON-RPC ``Method not found`` error (``-32601``) → ``SOURCE_NOT_FOUND`` (the service
does not implement ``rpc.discover``); any other JSON-RPC error → ``SOURCE_UNREACHABLE``; a reply
that is not a JSON-RPC response carrying an object ``result`` → ``INPUT_MALFORMED``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .import_source import ImportSourceError
from .live_fetch import auth_headers, check_public_url, guarded_client, guarded_post_json

__all__ = [
    "DISCOVER_METHOD",
    "MAX_DISCOVERY_BYTES",
    "OpenRpcDiscovery",
    "discover_openrpc_service",
    "discover_request",
    "endpoint_url",
    "parse_discover_response",
]

#: The reserved JSON-RPC method a service answers with its OpenRPC document.
DISCOVER_METHOD = "rpc.discover"

#: Largest ``rpc.discover`` reply read (bytes).
MAX_DISCOVERY_BYTES = 16 * 1024 * 1024

#: JSON-RPC 2.0 "Method not found" error code.
_METHOD_NOT_FOUND = -32601

_WHAT = "OpenRPC rpc.discover endpoint"


@dataclass(frozen=True)
class OpenRpcDiscovery:
    """What a live JSON-RPC service gave back.

    Attributes:
        endpoint_url: The endpoint ``rpc.discover`` was called on.
        document: The OpenRPC document (the reply's ``result``) as JSON text.
    """

    endpoint_url: str
    document: str


def endpoint_url(url: str) -> str:
    """Normalize a JSON-RPC endpoint URL.

    Args:
        url: The endpoint (``https://rpc.example.com/`` or ``https://host/rpc``). The path and
            query are kept — many providers put an API key in either.

    Returns:
        The URL with a lower-cased scheme and no fragment.

    Raises:
        ImportSourceError: When the URL is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (url or "").strip()
    if not cleaned:
        raise ImportSourceError("The JSON-RPC endpoint URL is empty.")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ImportSourceError("The JSON-RPC endpoint URL must be an http or https URL.")
    if not parts.netloc:
        raise ImportSourceError("The JSON-RPC endpoint URL has no host.")
    return urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or "/", parts.query, ""))


def discover_request(request_id: int = 1) -> dict:
    """The JSON-RPC 2.0 ``rpc.discover`` request body.

    Args:
        request_id: The JSON-RPC ``id``.

    Returns:
        ``{"jsonrpc": "2.0", "id": request_id, "method": "rpc.discover", "params": []}``.
    """
    return {"jsonrpc": "2.0", "id": request_id, "method": DISCOVER_METHOD, "params": []}


def parse_discover_response(body: str, *, url: str) -> str:
    """Extract the OpenRPC document from an ``rpc.discover`` reply.

    Args:
        body: The HTTP response body.
        url: The endpoint, for messages.

    Returns:
        The reply's ``result`` serialized as indented JSON text (key order kept).

    Raises:
        ImportSourceError: ``SOURCE_NOT_FOUND`` when the service answers "Method not found",
            ``SOURCE_UNREACHABLE`` for any other JSON-RPC error, ``INPUT_MALFORMED`` when the
            reply is not JSON, not a JSON-RPC response, or its ``result`` is not an object.
    """
    try:
        reply = json.loads(body)
    except ValueError as exc:
        raise ImportSourceError(f"The {_WHAT} at {url} did not answer with JSON.", code="INPUT_MALFORMED") from exc
    if isinstance(reply, list):
        # A server may answer a single request as a one-element batch.
        reply = reply[0] if len(reply) == 1 else None
    if not isinstance(reply, dict):
        raise ImportSourceError(
            f"The {_WHAT} at {url} did not answer with a JSON-RPC response.", code="INPUT_MALFORMED"
        )
    error = reply.get("error")
    if error is not None:
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        detail = f" ({code}: {message})" if message else (f" ({code})" if code is not None else "")
        if code == _METHOD_NOT_FOUND:
            raise ImportSourceError(
                f"The JSON-RPC service at {url} does not implement rpc.discover{detail}.",
                code="SOURCE_NOT_FOUND",
            )
        raise ImportSourceError(
            f"The JSON-RPC service at {url} answered rpc.discover with an error{detail}.",
            code="SOURCE_UNREACHABLE",
        )
    result = reply.get("result")
    if not isinstance(result, dict):
        raise ImportSourceError(
            f"The {_WHAT} at {url} returned no OpenRPC document (result is not an object).",
            code="INPUT_MALFORMED",
        )
    return json.dumps(result, indent=2, ensure_ascii=False)


def discover_openrpc_service(
    url: str,
    *,
    auth_type: Optional[str] = None,
    auth_payload: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.Client] = None,
) -> OpenRpcDiscovery:
    """Call ``rpc.discover`` on a live JSON-RPC service and return its OpenRPC document.

    Args:
        url: The JSON-RPC endpoint.
        auth_type: Credential-vault auth type (``none``/``bearer``/``header``/``oauth2``…).
        auth_payload: The decrypted credential for ``auth_type``.
        headers: Extra request headers (after the auth headers).
        client: An httpx client to inject (tests); production uses the SSRF-guarded client.

    Returns:
        The discovery result.

    Raises:
        ImportSourceError: When the URL is unsafe or not http(s), the credential is malformed,
            the call fails, or the reply carries no document (see :func:`parse_discover_response`
            and :func:`app.live_fetch.guarded_post_json` for the codes).
    """
    endpoint = endpoint_url(url)
    check_public_url(endpoint, what="JSON-RPC endpoint")
    request_headers = {**auth_headers(auth_type, auth_payload), **dict(headers or {})}

    owns_client = client is None
    http = client if client is not None else guarded_client()
    try:
        body = guarded_post_json(
            http,
            endpoint,
            discover_request(),
            headers=request_headers,
            what=_WHAT,
            max_bytes=MAX_DISCOVERY_BYTES,
        )
    finally:
        if owns_client:
            http.close()
    return OpenRpcDiscovery(endpoint_url=endpoint, document=parse_discover_response(body, url=endpoint))
