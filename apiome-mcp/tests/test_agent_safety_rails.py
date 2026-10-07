"""AGX-2.3 safety rails (#4535): SSRF guard, declared method, request cap, MCP annotations.

* the guard resolves once, refuses when any resolved address is non-public, and connects to the
  *checked address*, so a DNS answer that flips between check and connect (rebinding) never reaches
  the socket;
* the guard is really installed in the client's connection pool (a real loopback server is refused),
  and only the mock root's exact origin is exempt;
* a blocked host is not retried; an unresolvable one is an ordinary connect error;
* a request may use only its tool's method, and no method-override header naming another;
* annotations follow the AGX-1.2 ``write_op`` flag, with an idempotency note on write tools.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import httpcore
import httpx
import pytest

from apiome_mcp.agent_safety_rails import (
    GuardedNetworkBackend,
    MethodNotAllowedError,
    RequestTooLargeError,
    UpstreamBlockedError,
    build_upstream_client,
    described_with_idempotency,
    enforce_declared_method,
    enforce_request_size,
    system_resolver,
    tool_annotations,
)
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy, send_upstream

PUBLIC = "93.184.216.34"


class _Inner(httpcore.AsyncNetworkBackend):
    """Records where it was asked to connect; refuses the addresses in ``refuse``."""

    def __init__(self, refuse: frozenset[str] = frozenset()) -> None:
        self.connects: list[tuple[str, int]] = []
        self.refuse = refuse

    async def connect_tcp(
        self, host: str, port: int, timeout: Any = None, local_address: Any = None, socket_options: Any = None
    ) -> Any:  # noqa: E501
        self.connects.append((host, port))
        if host in self.refuse:
            raise httpcore.ConnectError(f"refused {host}")
        return object()

    async def sleep(self, seconds: float) -> None:
        self.slept = seconds


class _Resolver:
    """Answers from a script of address lists, one per call (the last repeats)."""

    def __init__(self, *answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls: list[str] = []

    async def __call__(self, host: str, port: int, timeout: float | None) -> list[str]:
        self.calls.append(host)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


def _connect(backend: GuardedNetworkBackend, host: str = "api.example", port: int = 443) -> Any:
    return asyncio.run(backend.connect_tcp(host, port, timeout=1.0))


# ============================================================================
# Resolve, then check, then connect to the checked address
# ============================================================================


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # cloud metadata
        "169.254.10.1",  # link-local
        "100.100.100.200",  # Alibaba metadata (CGNAT)
        "fd00:ec2::254",  # AWS IPv6 metadata (unique-local)
        "10.1.2.3",
        "172.16.0.1",
        "192.168.0.1",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "::ffff:10.0.0.1",  # IPv4-mapped
        "64:ff9b::a9fe:a9fe",  # NAT64 of the metadata address
        "fe80::1",
        "224.0.0.1",
    ],
)
def test_a_non_public_address_is_blocked_before_any_connect(address: str) -> None:
    inner = _Inner()
    with pytest.raises(UpstreamBlockedError) as caught:
        _connect(GuardedNetworkBackend(resolver=_Resolver([address]), inner=inner))
    assert (caught.value.host, caught.value.address) == ("api.example", address)
    assert inner.connects == []


def test_any_private_answer_blocks_a_mixed_resolution() -> None:
    inner = _Inner()
    with pytest.raises(UpstreamBlockedError):
        _connect(GuardedNetworkBackend(resolver=_Resolver([PUBLIC, "10.0.0.1"]), inner=inner))
    assert inner.connects == []


def test_the_socket_goes_to_the_checked_address_not_the_name() -> None:
    inner = _Inner()
    _connect(GuardedNetworkBackend(resolver=_Resolver([PUBLIC]), inner=inner), host="api.example", port=8443)
    assert inner.connects == [(PUBLIC, 8443)]


def test_dns_rebinding_cannot_reach_the_socket() -> None:
    # The first answer is public (checked, then connected to by address); the rebinding answer is
    # private. Each connection resolves exactly once, so the second connection is refused rather than
    # the first one silently reaching the private address.
    resolver = _Resolver([PUBLIC], ["169.254.169.254"])
    inner = _Inner()
    backend = GuardedNetworkBackend(resolver=resolver, inner=inner)
    _connect(backend)
    with pytest.raises(UpstreamBlockedError):
        _connect(backend)
    assert resolver.calls == ["api.example", "api.example"]
    assert inner.connects == [(PUBLIC, 443)]


def test_the_next_checked_address_is_tried_when_one_refuses() -> None:
    inner = _Inner(refuse=frozenset({PUBLIC}))
    _connect(GuardedNetworkBackend(resolver=_Resolver([PUBLIC, "93.184.216.35"]), inner=inner))
    assert inner.connects == [(PUBLIC, 443), ("93.184.216.35", 443)]


def test_when_every_address_refuses_the_last_error_is_raised() -> None:
    inner = _Inner(refuse=frozenset({PUBLIC}))
    with pytest.raises(httpcore.ConnectError):
        _connect(GuardedNetworkBackend(resolver=_Resolver([PUBLIC]), inner=inner))


def test_no_addresses_is_a_connect_error() -> None:
    with pytest.raises(httpcore.ConnectError):
        _connect(GuardedNetworkBackend(resolver=_Resolver([]), inner=_Inner()))


def test_allow_private_skips_the_rule_but_still_connects_by_address() -> None:
    inner = _Inner()
    _connect(GuardedNetworkBackend(allow_private=True, resolver=_Resolver(["10.0.0.1"]), inner=inner))
    assert inner.connects == [("10.0.0.1", 443)]


def test_unix_sockets_are_refused() -> None:
    with pytest.raises(UpstreamBlockedError):
        asyncio.run(GuardedNetworkBackend(inner=_Inner()).connect_unix_socket("/var/run/docker.sock"))


def test_sleep_delegates() -> None:
    inner = _Inner()
    asyncio.run(GuardedNetworkBackend(inner=inner).sleep(0.0))
    assert inner.slept == 0.0


# ============================================================================
# System resolver
# ============================================================================


def test_the_system_resolver_resolves_an_ip_literal() -> None:
    assert asyncio.run(system_resolver("127.0.0.1", 80, 1.0)) == ["127.0.0.1"]


def test_an_unresolvable_host_is_a_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise socket.gaierror(-2, "Name or service not known")

    async def run() -> Any:
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fail)
        return await system_resolver("nowhere.invalid", 443, 1.0)

    with pytest.raises(httpcore.ConnectError, match="could not resolve"):
        asyncio.run(run())


def test_a_slow_resolution_is_a_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)

    async def run() -> Any:
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", slow)
        return await system_resolver("slow.example", 443, 0.01)

    with pytest.raises(httpcore.ConnectTimeout):
        asyncio.run(run())


# ============================================================================
# The real client: guard installed, mock origin exempt, no retries on a block
# ============================================================================


async def _serve_once(sock_port: int, client: httpx.AsyncClient, url: str) -> httpx.Response:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", sock_port, reuse_address=True)
    try:
        async with client:
            return await client.get(url)
    finally:
        server.close()
        await server.wait_closed()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_real_client_refuses_a_loopback_upstream() -> None:
    port = _free_port()
    client = build_upstream_client(mock_base_url=None, timeout_seconds=2.0)
    with pytest.raises(UpstreamBlockedError):
        asyncio.run(_serve_once(port, client, f"http://127.0.0.1:{port}/pets"))


def test_the_real_client_refuses_localhost_by_name() -> None:
    port = _free_port()
    client = build_upstream_client(mock_base_url="http://mock.internal:8775", timeout_seconds=2.0)
    with pytest.raises(UpstreamBlockedError):
        asyncio.run(_serve_once(port, client, f"http://localhost:{port}/pets"))


def test_the_mock_origin_is_exempt() -> None:
    port = _free_port()
    client = build_upstream_client(mock_base_url=f"http://127.0.0.1:{port}/root", timeout_seconds=2.0)
    response = asyncio.run(_serve_once(port, client, f"http://127.0.0.1:{port}/root/acme/pets"))
    assert (response.status_code, response.text) == (200, "ok")


@pytest.mark.parametrize(
    "variant", ["https://127.0.0.1:{port}/", "http://127.0.0.1:{other}/", "http://localhost:{port}/"]
)
def test_only_the_exact_mock_origin_is_exempt(variant: str) -> None:
    port = _free_port()
    client = build_upstream_client(mock_base_url=f"http://127.0.0.1:{port}", timeout_seconds=2.0)
    url = variant.format(port=port, other=_free_port())
    with pytest.raises(UpstreamBlockedError):
        asyncio.run(_serve_once(port, client, url))


def test_allow_private_reaches_a_private_upstream() -> None:
    port = _free_port()
    client = build_upstream_client(mock_base_url=None, timeout_seconds=2.0, allow_private=True)
    response = asyncio.run(_serve_once(port, client, f"http://127.0.0.1:{port}/"))
    assert response.status_code == 200


def test_the_client_never_follows_redirects_or_reads_proxy_env() -> None:
    client = build_upstream_client(mock_base_url=None, timeout_seconds=1.0)
    assert client.follow_redirects is False
    assert client.trust_env is False
    asyncio.run(client.aclose())


def test_a_blocked_upstream_is_not_retried() -> None:
    resolver = _Resolver(["169.254.169.254"])
    client = build_upstream_client(
        mock_base_url=None, timeout_seconds=1.0, backend=GuardedNetworkBackend(resolver=resolver, inner=_Inner())
    )
    policy = UpstreamCallPolicy(timeout_seconds=1.0, budget_seconds=2.0, max_retries=2, backoff_seconds=0.0)

    async def run() -> Any:
        async with client:
            return await send_upstream(
                client, "GET", "https://api.example/pets", headers={}, content=None, policy=policy
            )

    with pytest.raises(UpstreamBlockedError):
        asyncio.run(run())
    assert resolver.calls == ["api.example"]


def test_resolution_counts_against_the_call_budget() -> None:
    async def hang(host: str, port: int, timeout: float | None) -> list[str]:
        await asyncio.sleep(5)
        return [PUBLIC]

    client = build_upstream_client(
        mock_base_url=None, timeout_seconds=1.0, backend=GuardedNetworkBackend(resolver=hang, inner=_Inner())
    )
    policy = UpstreamCallPolicy(timeout_seconds=0.1, budget_seconds=0.25, max_retries=5, backoff_seconds=0.0)

    async def run() -> Any:
        async with client:
            return await send_upstream(client, "GET", "https://api.example/", headers={}, content=None, policy=policy)

    from apiome_mcp.agent_upstream_client import UpstreamTimeoutError

    with pytest.raises(UpstreamTimeoutError) as caught:
        asyncio.run(run())
    assert caught.value.elapsed_ms < 1000


# ============================================================================
# Declared method and request size
# ============================================================================


def test_the_declared_method_passes() -> None:
    enforce_declared_method("GET", "get", {"Accept": "application/json", "X-HTTP-Method-Override": "GET"})


@pytest.mark.parametrize(
    ("method", "headers", "attempted"),
    [
        ("DELETE", {}, "DELETE"),
        ("GET", {"X-HTTP-Method-Override": "DELETE"}, "DELETE"),
        ("GET", {"x-http-method": "put"}, "PUT"),
        ("GET", {"X-Method-Override": "POST"}, "POST"),
    ],
)
def test_any_other_method_is_refused(method: str, headers: dict[str, str], attempted: str) -> None:
    with pytest.raises(MethodNotAllowedError) as caught:
        enforce_declared_method("GET", method, headers)
    assert (caught.value.declared, caught.value.attempted) == ("GET", attempted)


def test_the_request_cap_is_inclusive() -> None:
    enforce_request_size(None, 1)
    enforce_request_size(b"x" * 10, 10)
    with pytest.raises(RequestTooLargeError) as caught:
        enforce_request_size(b"x" * 11, 10)
    assert (caught.value.size, caught.value.limit) == (11, 10)


# ============================================================================
# MCP annotations
# ============================================================================


def test_a_read_tool_is_read_only() -> None:
    hints = tool_annotations(write_op=False, method="GET")
    assert (hints.readOnlyHint, hints.destructiveHint, hints.idempotentHint, hints.openWorldHint) == (
        True,
        False,
        True,
        True,
    )


@pytest.mark.parametrize(
    ("method", "idempotent"), [("POST", False), ("PATCH", False), ("PUT", True), ("DELETE", True), (None, False)]
)
def test_a_write_tool_is_destructive_with_idempotency_from_its_method(method: str | None, idempotent: bool) -> None:
    hints = tool_annotations(write_op=True, method=method)
    assert (hints.readOnlyHint, hints.destructiveHint, hints.idempotentHint) == (False, True, idempotent)


def test_read_descriptions_are_unchanged() -> None:
    assert described_with_idempotency("List pets.", write_op=False, method="GET") == "List pets."
    assert described_with_idempotency(None, write_op=False, method="GET") is None


def test_write_descriptions_carry_an_idempotency_note() -> None:
    post = described_with_idempotency("Create a pet.", write_op=True, method="POST")
    assert post is not None and post.startswith("Create a pet.\n\nChanges data (POST). Not idempotent")
    put = described_with_idempotency(None, write_op=True, method="put")
    assert put is not None and put.startswith("Changes data (PUT). Idempotent")
    rpc = described_with_idempotency(None, write_op=True, method=None)
    assert rpc is not None and rpc.startswith("Changes data. Not idempotent")
