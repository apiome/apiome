"""AGX-2.3 safety rails — what keeps the agent invocation proxy from being an SSRF and abuse machine (#4535).

The AGX-2.1 proxy (:mod:`apiome_mcp.agent_invocation_proxy`) turns an agent's ``tools/call`` into an
HTTP request to a host the *spec* names. These rails fence it:

* **SSRF guard (resolve, then check, then connect to the checked address).** Every ``prod`` upstream
  connection goes through :class:`GuardedNetworkBackend`. It resolves the host itself, refuses the
  connection when *any* resolved address is private, loopback, link-local (which covers the cloud
  metadata address ``169.254.169.254``), CGNAT, unique-local, multicast or reserved, and then
  connects to one of the addresses it checked, never to the name. A DNS answer that changes between
  the check and the connect (DNS rebinding) therefore cannot steer the socket: the socket only ever
  sees a checked address. TLS still verifies the certificate against the host *name* (httpcore sends
  the origin host as SNI). The address rule is apiome-rest's
  :func:`app.ssrf_guard.is_disallowed_address`, the same rule as the SIM-3.2 Try It relay
  (``apiome-ui/lib/tryit/relay.ts``). The operator-configured mock root is the one exemption, as in
  SIM-3.2: it is deployment infrastructure (``http://mock:8775`` inside compose) and is exempt only
  for requests to exactly its origin (:func:`build_upstream_client`).
* **Declared method only** (:func:`enforce_declared_method`): the request must use the method the
  tool was compiled from, and may not carry a method-override header naming another one. A tool
  compiled from a ``GET`` can never send anything but a ``GET``, whatever the arguments say.
* **Request size cap** (:func:`enforce_request_size`): a body over ``max_request_bytes`` is refused
  before anything is sent. (The response cap and its truncation marker, and the per-call time budget
  that retries share, are AGX-2.1's :mod:`~apiome_mcp.agent_upstream_client` and
  :mod:`~apiome_mcp.agent_result_mapping`; redirects are never followed, so they cannot add time.)
* **MCP annotations** (:func:`tool_annotations`, :func:`described_with_idempotency`): every served
  tool says whether it is read-only or destructive, from the AGX-1.2 ``write_op`` flag stored for it,
  and a write tool's description says whether repeating it is safe, so MCP clients can put a
  confirmation step in front of the dangerous ones.

A refused call becomes a distinct ``isError`` result with a hint (``upstream_blocked``,
``method_not_allowed``, ``request_too_large``; see :mod:`~apiome_mcp.agent_result_mapping`).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable, Iterable, Mapping

import httpcore
import httpx
import mcp.types as mt
import structlog
from app.ssrf_guard import is_disallowed_address

from apiome_mcp.agent_upstream_client import IDEMPOTENT_METHODS

_log = structlog.get_logger(__name__)

__all__ = [
    "METHOD_OVERRIDE_HEADERS",
    "GuardedNetworkBackend",
    "MethodNotAllowedError",
    "RequestTooLargeError",
    "Resolver",
    "UpstreamBlockedError",
    "build_upstream_client",
    "described_with_idempotency",
    "enforce_declared_method",
    "enforce_request_size",
    "system_resolver",
    "tool_annotations",
]

#: Headers some servers honour to run a different method than the request line's.
METHOD_OVERRIDE_HEADERS = frozenset({"x-http-method-override", "x-http-method", "x-method-override"})

#: Resolves ``(host, port, timeout)`` to the addresses to connect to, in preference order.
Resolver = Callable[[str, int, float | None], Awaitable[list[str]]]


class UpstreamBlockedError(Exception):
    """The upstream host resolves to an address the SSRF guard refuses.

    Deliberately not an ``httpx`` / ``httpcore`` error, so the upstream client neither retries it
    nor reports it as an unreachable upstream.

    Attributes:
        host: The host name the spec named (safe to show the agent).
        address: The refused resolved address (logged, never shown to the agent).
    """

    def __init__(self, host: str, address: str) -> None:
        self.host = host
        self.address = address
        super().__init__(f"upstream host {host!r} resolves to a non-public address")


class MethodNotAllowedError(Exception):
    """A request would use a method the tool was not compiled from.

    Attributes:
        declared: The tool's method.
        attempted: The method the request would have used.
    """

    def __init__(self, declared: str, attempted: str) -> None:
        self.declared = declared
        self.attempted = attempted
        super().__init__(f"tool declares {declared}, request would send {attempted}")


class RequestTooLargeError(Exception):
    """A request body is over the cap.

    Attributes:
        size: The body size in bytes.
        limit: The cap in bytes.
    """

    def __init__(self, size: int, limit: int) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"request body of {size} bytes is over the {limit}-byte cap")


# --------------------------------------------------------------------------------------------------
# SSRF guard
# --------------------------------------------------------------------------------------------------


async def system_resolver(host: str, port: int, timeout: float | None) -> list[str]:
    """Resolve ``host`` with the system resolver.

    Args:
        host: A host name or IP literal.
        port: The port (passed to ``getaddrinfo``).
        timeout: Most seconds to wait, or ``None``.

    Returns:
        Every distinct address, in the resolver's order.

    Raises:
        httpcore.ConnectTimeout: Resolution took longer than ``timeout``.
        httpcore.ConnectError: The host does not resolve.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout)
    except TimeoutError as exc:
        raise httpcore.ConnectTimeout(f"resolving {host!r} timed out") from exc
    except OSError as exc:
        raise httpcore.ConnectError(f"could not resolve host {host!r}") from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos if info[4]))


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    """An httpcore network backend that connects only to resolved addresses the SSRF rule allows.

    ``connect_tcp`` resolves the host once, refuses when any address is disallowed, and connects the
    inner backend to a checked *address*. Addresses are tried in order until one connects.
    """

    def __init__(
        self,
        *,
        allow_private: bool = False,
        resolver: Resolver = system_resolver,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        """Configure the guard.

        Args:
            allow_private: Skip the address rule (local development against a private upstream).
                Resolution and connect-to-address still happen.
            resolver: Resolves a host (tests pass a fake).
            inner: The backend that opens sockets (default: httpcore's anyio backend).
        """
        self._allow_private = allow_private
        self._resolve = resolver
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Resolve, check every address, then connect to a checked address.

        Raises:
            UpstreamBlockedError: Any resolved address is disallowed.
            httpcore.ConnectError: The host does not resolve, or no address accepted the connection.
            httpcore.ConnectTimeout: Resolving or connecting timed out.
        """
        addresses = await self._resolve(host, port, timeout)
        if not addresses:
            raise httpcore.ConnectError(f"could not resolve host {host!r}")
        if not self._allow_private:
            for address in addresses:
                if is_disallowed_address(address):
                    _log.warning("agent_upstream_blocked", host=host, address=address)
                    raise UpstreamBlockedError(host, address)
        failure: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                failure = exc
        assert failure is not None
        raise failure

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        """Refused: an upstream is never a local socket."""
        raise UpstreamBlockedError(path, "unix-socket")

    async def sleep(self, seconds: float) -> None:
        """Delegate to the inner backend."""
        await self._inner.sleep(seconds)


def _guarded_transport(backend: GuardedNetworkBackend, limits: httpx.Limits) -> httpx.AsyncHTTPTransport:
    """An httpx transport whose connections all open through ``backend``.

    httpx has no public way to pass httpcore a network backend, so it is set on the transport's
    pool. Failing loudly here (rather than serving unguarded) is the point of the check.
    """
    transport = httpx.AsyncHTTPTransport(limits=limits, trust_env=False)
    pool = getattr(transport, "_pool", None)
    if not isinstance(pool, httpcore.AsyncConnectionPool) or not hasattr(pool, "_network_backend"):
        raise RuntimeError("httpx/httpcore internals changed: cannot install the agent upstream SSRF guard")
    pool._network_backend = backend
    return transport


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    """``(scheme, host, port)`` with the scheme's default port filled in."""
    default = {"http": 80, "https": 443}.get(url.scheme)
    return url.scheme, url.host, url.port or default


class _ExemptOriginTransport(httpx.AsyncBaseTransport):
    """Sends requests for one exact origin through ``exempt``, everything else through ``guarded``."""

    def __init__(
        self, *, guarded: httpx.AsyncBaseTransport, exempt: httpx.AsyncBaseTransport, origin: httpx.URL | None
    ) -> None:
        self._guarded = guarded
        self._exempt = exempt
        self._origin = _origin(origin) if origin is not None else None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Route by exact origin (scheme, host and effective port)."""
        exempt = self._origin is not None and _origin(request.url) == self._origin
        return await (self._exempt if exempt else self._guarded).handle_async_request(request)

    async def aclose(self) -> None:
        """Close both transports."""
        await self._guarded.aclose()
        await self._exempt.aclose()


def build_upstream_client(
    *,
    mock_base_url: str | None,
    timeout_seconds: float,
    allow_private: bool = False,
    backend: GuardedNetworkBackend | None = None,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncClient:
    """The agent runtime's upstream HTTP client, SSRF-guarded.

    Redirects are not followed (one could carry an injected credential elsewhere) and environment
    proxies are ignored (a proxy would resolve the host itself, outside the guard).

    Args:
        mock_base_url: The SIM mock root the proxy sends ``mock`` traffic to; its exact origin is
            exempt from the address rule. ``None`` exempts nothing.
        timeout_seconds: The client's default timeout (each call sets its own).
        allow_private: Turn the address rule off (``APIOME_MCP_AGENT_UPSTREAM_ALLOW_PRIVATE``).
        backend: The guard (tests); default: a :class:`GuardedNetworkBackend`.
        limits: Connection pool limits.

    Returns:
        The client. The caller closes it.
    """
    limits = limits or httpx.Limits(max_connections=200, max_keepalive_connections=50)
    guarded = _guarded_transport(backend or GuardedNetworkBackend(allow_private=allow_private), limits)
    exempt = httpx.AsyncHTTPTransport(limits=limits, trust_env=False)
    origin = httpx.URL(mock_base_url) if mock_base_url else None
    return httpx.AsyncClient(
        transport=_ExemptOriginTransport(guarded=guarded, exempt=exempt, origin=origin),
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(timeout_seconds),
    )


# --------------------------------------------------------------------------------------------------
# Method and size
# --------------------------------------------------------------------------------------------------


def enforce_declared_method(declared: str, method: str, headers: Mapping[str, str]) -> None:
    """Refuse a request that would run any method but the tool's own.

    Args:
        declared: The method the tool was compiled from (``OperationBinding.method``).
        method: The method the request is about to use.
        headers: The request headers (a method-override header naming another method is refused).

    Raises:
        MethodNotAllowedError: The method, or an override header, differs from ``declared``.
    """
    expected = declared.strip().upper()
    if method.strip().upper() != expected:
        raise MethodNotAllowedError(expected, method.strip().upper())
    for name, value in headers.items():
        if name.lower() in METHOD_OVERRIDE_HEADERS and value.strip().upper() != expected:
            raise MethodNotAllowedError(expected, value.strip().upper())


def enforce_request_size(content: bytes | None, limit: int) -> None:
    """Refuse a request body over ``limit`` bytes.

    Raises:
        RequestTooLargeError: ``len(content) > limit``.
    """
    size = len(content or b"")
    if size > limit:
        raise RequestTooLargeError(size, limit)


# --------------------------------------------------------------------------------------------------
# MCP annotations
# --------------------------------------------------------------------------------------------------


def _is_idempotent(method: str | None) -> bool:
    """Whether repeating ``method`` has the effect of sending it once (RFC 9110 §9.2.2)."""
    return method is not None and method.upper() in IDEMPOTENT_METHODS


def tool_annotations(*, write_op: bool, method: str | None) -> mt.ToolAnnotations:
    """The MCP annotations of one served tool.

    Args:
        write_op: The AGX-1.2 flag stored for the tool's operation.
        method: The tool's HTTP method, or ``None`` when it has no HTTP binding.

    Returns:
        A read tool: ``readOnlyHint``, not destructive, idempotent. A write tool: not read-only,
        ``destructiveHint``, and ``idempotentHint`` from its method. Both are open-world (they reach
        an outside API).
    """
    if not write_op:
        return mt.ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    return mt.ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=_is_idempotent(method), openWorldHint=True
    )


def described_with_idempotency(description: str | None, *, write_op: bool, method: str | None) -> str | None:
    """A write tool's description with a note on whether calling it again is safe.

    Args:
        description: The served description (``None`` when the source documents nothing).
        write_op: The AGX-1.2 flag; read tools are returned unchanged.
        method: The tool's HTTP method, or ``None``.

    Returns:
        The description, with the note appended for a write tool.
    """
    if not write_op:
        return description
    verb = f" ({method.upper()})" if method else ""
    if _is_idempotent(method):
        note = (
            f"Changes data{verb}. Idempotent: repeating the same call leaves the same result, so retrying "
            "after a failure is safe."
        )
    else:
        note = (
            f"Changes data{verb}. Not idempotent: each call may take effect again, so check the current "
            "state before retrying."
        )
    return f"{description}\n\n{note}" if description else note
