"""MCP ``initialize`` handshake + protocol-version negotiation (V2-MCP-16.2, #3658).

This is the lifecycle layer that sits directly on top of the Streamable HTTP
transport (:mod:`app.mcp_client.transport_http`, 2.1). Before any capability can
be discovered, the MCP
`lifecycle <https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle>`_
requires a three-step opening handshake, which :func:`initialize_session`
performs end to end:

1. **``initialize`` request.** The client sends its preferred ``protocolVersion``,
   the ``capabilities`` it implements, and its ``clientInfo``.
2. **Version negotiation** over the server's reply:

   * **echo** — the server supports our version and returns the *same*
     ``protocolVersion``; we adopt it;
   * **fallback** — the server returns a *different* version it prefers (in the
     ``initialize`` result, or in the ``data.supported`` list of a ``-32602``
     *Invalid params* error); if we also support it we retry/adopt it;
   * **disconnect on unsupported** — if the negotiated version is not one we
     support, or no mutually supported version exists, we refuse with
     :class:`McpVersionNegotiationError` and leave the transport for the caller
     to close.
3. **``notifications/initialized``.** Once a version is agreed we send this
   notification, after which normal operations (``tools/list`` …) may proceed.

The negotiated version is recorded on the transport (so every subsequent request
pins the right ``MCP-Protocol-Version`` header) and returned on the
:class:`InitializeResult`, which also carries the server identity
(``serverInfo``), declared ``capabilities``, and ``instructions`` — exactly the
fields a discovery snapshot persists (``mcp_endpoint_versions``) and the fields
downstream layers branch on when the wire shape differs across protocol
revisions (e.g. ``serverInfo.title`` exists on 2025-06-18 but not 2025-03-26).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .. import __version__ as _rest_version
from .transport_http import (
    JsonRpcError,
    McpProtocolError,
    StreamableHttpTransport,
)

# MCP protocol revisions this client can speak, newest first. The order is also
# the *preference* order used when several versions are mutually supported.
# 2024-11-05 is intentionally excluded: that revision uses the deprecated
# HTTP+SSE two-endpoint transport, which is a separate work item (MCAT-2.5).
SUPPORTED_PROTOCOL_VERSIONS: Tuple[str, ...] = ("2025-06-18", "2025-03-26")

# JSON-RPC reserved code a server returns when it cannot agree on the requested
# protocol version (it carries the versions it *does* support in ``data``).
INVALID_PARAMS_CODE = -32602

# Who we say we are in the ``initialize`` request's ``clientInfo``. ``title`` is a
# 2025-06-18 addition; sending it to an older server is harmless (extra field).
DEFAULT_CLIENT_INFO: Dict[str, str] = {
    "name": "apiome-mcp-catalog",
    "title": "Apiome MCP Catalog",
    "version": _rest_version,
}

# Capabilities *we* implement as a client. The catalog only discovers a server's
# surface; it offers no roots/sampling/elicitation, so it declares none.
DEFAULT_CLIENT_CAPABILITIES: Dict[str, Any] = {}


# ===========================================================================
# Errors
# ===========================================================================


class McpVersionNegotiationError(McpProtocolError):
    """No protocol version acceptable to both client and server could be agreed.

    Raised when the server's negotiated/offered version is not one this client
    supports, or when a ``-32602`` rejection lists no version we have in common.
    Per the lifecycle spec the client should disconnect in this case; the
    transport is left untouched so the caller's context manager closes it.

    Attributes:
        server_version: The version the server returned/insisted on, when known
            (``None`` when the server only rejected without naming one).
        client_supported: The versions this client offered to speak.
        server_supported: The versions the server advertised in a ``-32602``
            error's ``data.supported``, when present (``None`` otherwise).
    """

    def __init__(
        self,
        message: str,
        *,
        server_version: Optional[str] = None,
        client_supported: Sequence[str] = (),
        server_supported: Optional[Sequence[str]] = None,
    ) -> None:
        self.server_version = server_version
        self.client_supported: Tuple[str, ...] = tuple(client_supported)
        self.server_supported: Optional[Tuple[str, ...]] = (
            tuple(server_supported) if server_supported is not None else None
        )
        super().__init__(message)


# ===========================================================================
# Value objects
# ===========================================================================


@dataclass(frozen=True)
class ServerInfo:
    """Identity of the MCP server, parsed from the ``initialize`` result.

    Every field is optional on the wire and across revisions: ``title`` was added
    in 2025-06-18, so a 2025-03-26 server leaves it ``None``.

    Attributes:
        name: Programmatic server name (e.g. ``"example-server"``).
        title: Human-facing display title (2025-06-18+); ``None`` on older servers.
        version: Server implementation version string.
    """

    name: Optional[str] = None
    title: Optional[str] = None
    version: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: Optional[Mapping[str, Any]]) -> "ServerInfo":
        """Build a :class:`ServerInfo` from a ``serverInfo`` object (or ``None``)."""
        if not isinstance(payload, Mapping):
            return cls()
        return cls(
            name=_optional_str(payload.get("name")),
            title=_optional_str(payload.get("title")),
            version=_optional_str(payload.get("version")),
        )


@dataclass(frozen=True)
class InitializeResult:
    """The negotiated outcome of a successful ``initialize`` handshake.

    These are precisely the fields a discovery snapshot persists
    (``mcp_endpoint_versions``: ``protocol_version``, ``server_name/title/version``,
    ``instructions``, ``capabilities``) and that downstream discovery branches on.

    Attributes:
        protocol_version: The agreed protocol version (always one of the client's
            supported versions).
        server_info: The parsed :class:`ServerInfo`.
        capabilities: The server's declared capabilities object, verbatim.
        instructions: Free-text usage guidance the server advertised, if any.
        raw: The complete ``initialize`` ``result`` object, unmodified, for any
            field not promoted above.
    """

    protocol_version: str
    server_info: ServerInfo
    capabilities: Dict[str, Any] = field(default_factory=dict)
    instructions: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Handshake
# ===========================================================================


async def initialize_session(
    transport: StreamableHttpTransport,
    *,
    client_info: Optional[Mapping[str, Any]] = None,
    capabilities: Optional[Mapping[str, Any]] = None,
    preferred_version: Optional[str] = None,
    supported_versions: Sequence[str] = SUPPORTED_PROTOCOL_VERSIONS,
) -> InitializeResult:
    """Run the MCP opening handshake over ``transport`` and return the result.

    Sends ``initialize``, negotiates a protocol version (echo / fallback /
    disconnect, including ``-32602`` handling), records the agreed version on the
    transport, and sends ``notifications/initialized``.

    Args:
        transport: An (unopened-handshake) Streamable HTTP transport to drive.
        client_info: Override the advertised ``clientInfo``; defaults to
            :data:`DEFAULT_CLIENT_INFO`.
        capabilities: Override the advertised client ``capabilities``; defaults to
            :data:`DEFAULT_CLIENT_CAPABILITIES`.
        preferred_version: The version to request first; defaults to the newest in
            ``supported_versions``. Must itself be a supported version.
        supported_versions: The versions this client will accept, newest/most
            preferred first. Defaults to :data:`SUPPORTED_PROTOCOL_VERSIONS`.

    Returns:
        The :class:`InitializeResult` with the negotiated version, server info,
        capabilities, and instructions.

    Raises:
        ValueError: if ``supported_versions`` is empty or ``preferred_version`` is
            not within it.
        McpVersionNegotiationError: if no mutually supported version can be agreed.
        McpProtocolError: if ``initialize`` fails for a non-version reason or the
            result is malformed (e.g. missing ``protocolVersion``).
    """
    supported = tuple(supported_versions)
    if not supported:
        raise ValueError("supported_versions must contain at least one version")
    first_version = preferred_version or supported[0]
    if first_version not in supported:
        raise ValueError(
            f"preferred_version {first_version!r} is not in supported_versions {supported!r}"
        )

    params_capabilities = dict(capabilities if capabilities is not None else DEFAULT_CLIENT_CAPABILITIES)
    params_client_info = dict(client_info if client_info is not None else DEFAULT_CLIENT_INFO)

    result_obj = await _negotiate_initialize(
        transport, first_version, supported, params_capabilities, params_client_info
    )

    negotiated = result_obj.get("protocolVersion")
    if not isinstance(negotiated, str) or not negotiated:
        raise McpProtocolError("initialize result is missing a 'protocolVersion'")
    if negotiated not in supported:
        # The server settled on a version we do not speak: disconnect gracefully.
        raise McpVersionNegotiationError(
            f"server negotiated unsupported protocol version {negotiated!r}; "
            f"client supports {list(supported)}",
            server_version=negotiated,
            client_supported=supported,
        )

    # Pin the agreed version so every later request carries the right
    # MCP-Protocol-Version header, then complete the handshake.
    transport.protocol_version = negotiated
    await transport.notify("notifications/initialized")

    return _build_result(negotiated, result_obj)


async def _negotiate_initialize(
    transport: StreamableHttpTransport,
    first_version: str,
    supported: Tuple[str, ...],
    capabilities: Dict[str, Any],
    client_info: Dict[str, Any],
) -> Dict[str, Any]:
    """Send ``initialize`` (with one ``-32602`` fallback retry) and return its result.

    Tries ``first_version``; on a ``-32602`` rejection that advertises versions we
    also support, retries once with the best mutual version. Returns the raw
    ``result`` object of the successful attempt.
    """
    attempt_version = first_version
    for is_retry in (False, True):
        response = await transport.request(
            "initialize",
            {
                "protocolVersion": attempt_version,
                "capabilities": capabilities,
                "clientInfo": client_info,
            },
        )
        if not response.is_error:
            return response.result if isinstance(response.result, dict) else {}

        error = response.error
        assert error is not None  # is_error guarantees this
        if error.code != INVALID_PARAMS_CODE or is_retry:
            # Not a version problem, or we already retried once: give up.
            raise _initialize_failure(error, supported)

        # -32602: the server told us which versions it supports; pick the best one
        # we have in common and try exactly once more.
        attempt_version = _select_fallback_version(error, supported)

    # Unreachable: the loop either returns a result or raises on each branch.
    raise McpProtocolError("initialize negotiation terminated unexpectedly")


def _select_fallback_version(error: JsonRpcError, supported: Tuple[str, ...]) -> str:
    """Choose the best version supported by both sides from a ``-32602`` error.

    Returns the most-preferred (per ``supported`` order) version that also appears
    in the error's ``data.supported`` list. Raises
    :class:`McpVersionNegotiationError` when there is no overlap.
    """
    server_versions = _server_supported_versions(error)
    server_set = set(server_versions)
    for candidate in supported:  # supported is newest/most-preferred first
        if candidate in server_set:
            return candidate
    raise McpVersionNegotiationError(
        "server rejected the protocol version and offers no version the client supports "
        f"(client {list(supported)}, server {server_versions})",
        client_supported=supported,
        server_supported=server_versions,
    )


def _initialize_failure(error: JsonRpcError, supported: Tuple[str, ...]) -> McpProtocolError:
    """Build the exception for a failed ``initialize`` (version vs. generic error)."""
    if error.code == INVALID_PARAMS_CODE:
        return McpVersionNegotiationError(
            f"server rejected protocol negotiation ({error.code}: {error.message})",
            client_supported=supported,
            server_supported=_server_supported_versions(error),
        )
    return McpProtocolError(f"initialize failed: JSON-RPC error {error.code}: {error.message}")


def _server_supported_versions(error: JsonRpcError) -> List[str]:
    """Extract ``data.supported`` (a list of version strings) from a JSON-RPC error."""
    data = error.data
    if isinstance(data, Mapping):
        supported = data.get("supported")
        if isinstance(supported, (list, tuple)):
            return [str(v) for v in supported if isinstance(v, str)]
    return []


def _build_result(negotiated: str, result_obj: Mapping[str, Any]) -> InitializeResult:
    """Assemble an :class:`InitializeResult` from a successful ``initialize`` result."""
    capabilities = result_obj.get("capabilities")
    instructions = result_obj.get("instructions")
    return InitializeResult(
        protocol_version=negotiated,
        server_info=ServerInfo.from_dict(result_obj.get("serverInfo")),
        capabilities=dict(capabilities) if isinstance(capabilities, Mapping) else {},
        instructions=_optional_str(instructions),
        raw=dict(result_obj),
    )


def _optional_str(value: Any) -> Optional[str]:
    """Return ``value`` as a string when it is a non-empty string, else ``None``."""
    return value if isinstance(value, str) and value != "" else None
