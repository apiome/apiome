"""End-to-end integration tests for HTTP credential extraction (MCP-2.4 / #3000).

These tests spin up a real Uvicorn/Starlette ASGI server so that the full
middleware chain (``HttpCredentialExtractionMiddleware`` → Starlette routing →
FastMCP ``StashHttpBearerInToolContextMiddleware``) is exercised against genuine
streamable-HTTP MCP requests.  This catches regressions in ``ContextVar``
propagation, middleware ordering, and ``serializable=False`` isolation that the
unit-test mocks in ``test_http_credential_middleware.py`` cannot detect.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Generator

import pytest
import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from starlette.middleware import Middleware as StarletteMiddleware

from apiome_mcp.http_credential_middleware import (
    HttpCredentialExtractionMiddleware,
    StashHttpBearerInToolContextMiddleware,
    get_http_bearer_from_context,
)

# ---------------------------------------------------------------------------
# Minimal FastMCP server used only for these integration tests
# ---------------------------------------------------------------------------

_test_mcp = FastMCP("IntegrationTestServer")
_test_mcp.add_middleware(StashHttpBearerInToolContextMiddleware())


@_test_mcp.tool
async def echo_bearer(ctx: Context) -> str | None:
    """Return the Bearer secret visible in the current tool context, or None."""
    return await get_http_bearer_from_context(ctx)


# ---------------------------------------------------------------------------
# Pytest fixture: real Uvicorn server on a free port
# ---------------------------------------------------------------------------


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def integration_server_url() -> Generator[str, None, None]:
    """Start a real Uvicorn server for the integration test module; yield its base URL."""
    starlette_app = _test_mcp.http_app(
        path="/mcp",
        middleware=[StarletteMiddleware(HttpCredentialExtractionMiddleware)],
    )

    port = _find_free_port()
    config = uvicorn.Config(starlette_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    ready_event = threading.Event()
    stop_event = threading.Event()

    def _run() -> None:
        async def _serve() -> None:
            serve_task = asyncio.ensure_future(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            ready_event.set()
            while not stop_event.is_set():
                await asyncio.sleep(0.05)
            server.should_exit = True
            await serve_task

        asyncio.run(_serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    if not ready_event.wait(timeout=15):
        raise RuntimeError("Integration test server did not start within 15 s")

    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        stop_event.set()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_bearer_token_reaches_tool_context(integration_server_url: str) -> None:
    """A Bearer secret in the Authorization header is visible inside the tool."""

    async def _run() -> None:
        transport = StreamableHttpTransport(
            url=integration_server_url,
            headers={"Authorization": "Bearer integration-secret"},
        )
        async with Client(transport) as client:
            result = await client.call_tool("echo_bearer", {})
        assert result.data == "integration-secret"

    asyncio.run(_run())


def test_anonymous_request_yields_none(integration_server_url: str) -> None:
    """A request without an Authorization header causes the tool to see None."""

    async def _run() -> None:
        transport = StreamableHttpTransport(url=integration_server_url)
        async with Client(transport) as client:
            result = await client.call_tool("echo_bearer", {})
        assert result.data is None

    asyncio.run(_run())


def test_non_bearer_auth_yields_none(integration_server_url: str) -> None:
    """A non-Bearer Authorization header (e.g. Basic) is treated as anonymous."""

    async def _run() -> None:
        transport = StreamableHttpTransport(
            url=integration_server_url,
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        async with Client(transport) as client:
            result = await client.call_tool("echo_bearer", {})
        assert result.data is None

    asyncio.run(_run())


def test_token_not_persisted_across_sessions(integration_server_url: str) -> None:
    """A Bearer token from one session is not visible in a subsequent session.

    This verifies that ``serializable=False`` (and ContextVar isolation) prevents
    the credential from leaking into the FastMCP session state store and being
    visible to a later, unauthenticated caller.
    """

    async def _run() -> None:
        # First session: with Bearer token
        t1 = StreamableHttpTransport(
            url=integration_server_url,
            headers={"Authorization": "Bearer first-session-token"},
        )
        async with Client(t1) as c:
            r1 = await c.call_tool("echo_bearer", {})
        assert r1.data == "first-session-token"

        # Second session: no Bearer token — must NOT see the first session's token
        t2 = StreamableHttpTransport(url=integration_server_url)
        async with Client(t2) as c:
            r2 = await c.call_tool("echo_bearer", {})
        assert r2.data is None, f"Token leaked across sessions: second session saw {r2.data!r} instead of None"

    asyncio.run(_run())


def test_multiple_calls_in_same_session_see_same_token(integration_server_url: str) -> None:
    """All tool calls within a single session share the same per-session Bearer token."""

    async def _run() -> None:
        transport = StreamableHttpTransport(
            url=integration_server_url,
            headers={"Authorization": "Bearer stable-session-token"},
        )
        async with Client(transport) as client:
            r1 = await client.call_tool("echo_bearer", {})
            r2 = await client.call_tool("echo_bearer", {})
        assert r1.data == "stable-session-token"
        assert r2.data == "stable-session-token"

    asyncio.run(_run())


def test_concurrent_sessions_see_their_own_tokens(integration_server_url: str) -> None:
    """Concurrent sessions each see their own Bearer token without cross-contamination."""

    async def _call(url: str, token: str | None) -> str | None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        transport = StreamableHttpTransport(url=url, headers=headers)
        async with Client(transport) as client:
            result = await client.call_tool("echo_bearer", {})
        return result.data  # type: ignore[return-value]

    async def _run() -> None:
        results = await asyncio.gather(
            _call(integration_server_url, "token-alpha"),
            _call(integration_server_url, "token-beta"),
            _call(integration_server_url, None),
        )
        assert results[0] == "token-alpha"
        assert results[1] == "token-beta"
        assert results[2] is None

    asyncio.run(_run())
