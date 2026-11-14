"""AAU-4.1 self-conformance gate: the catalog's ``mcp-protocol`` profile against ``/agent/mcp`` (#5714).

For every version in :data:`~apiome_mcp.protocol_versions.SELF_GATE_NEGOTIATION`, the real HTTP app
(catalog stand-in at ``/mcp``, real agent runtime at ``/agent/mcp``) is discovered by the catalog's own
MCP client with a transcript recorder attached — exactly the session ``apiome mcp conformance --profile
mcp-protocol`` evaluates for a registered endpoint — and the report is gated at ``failOn=error``. A
regression in what the runtime negotiates, or any protocol ``error`` finding, fails the gate; the CI
step "MCP protocol self-conformance gate" runs this module on its own so the failure is named.

The protocol-version gate's acceptance criterion is asserted here too, over the wire: an unsupported
``MCP-Protocol-Version`` is refused with ``400`` and the supported list, never served at another version.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Generator
from typing import Any

import httpx
import mcp.types as mt
import pytest
from app.mcp_client.discovery import discover_listings
from app.mcp_client.handshake import McpVersionNegotiationError, initialize_session
from app.mcp_client.normalize import DiscoverySurface
from app.mcp_client.transport_http import StreamableHttpTransport
from app.mcp_conformance import PROFILE_PROTOCOL, ConformanceContext, ConformanceReport, run_conformance
from app.mcp_protocol_transcript import TranscriptRecorder
from fastmcp import Context, FastMCP
from fastmcp.server.lifespan import lifespan
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from agent_runtime_fakes import ALL_TOOLS, KEY_ID, TENANT_ID, TOOLSET_ID, AgentDb, PetstoreUpstream
from apiome_mcp.agent_access import AgentAccessDeniedError, AgentAccessMiddleware, AgentAccessReason, AgentKey
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.agent_server import AGENT_HTTP_CLIENT_KEY, build_agent_server
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy
from apiome_mcp.database_pool import MCP_DB_POOL_KEY
from apiome_mcp.http_app import build_http_app
from apiome_mcp.protocol_version_gate import current_protocol_version
from apiome_mcp.protocol_versions import (
    ACCEPTED_PROTOCOL_VERSIONS,
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    SELF_GATE_NEGOTIATION,
    SERVED_PROTOCOL_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION_CODE,
)
from http_server_harness import serve_http_app

SECRET = "ak_" + "c3" * 32
AUTH = {"Authorization": f"Bearer {SECRET}"}
KEY = AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=ALL_TOOLS)
UPSTREAM = PetstoreUpstream()
DB = AgentDb()
POOL = DB.pool()

#: The protocol version each ``tools/list`` saw through :func:`current_protocol_version`.
SEEN_VERSIONS: list[str | None] = []

MCP_ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _resolve(ctx: Context, secret: str) -> AgentKey:
    if secret != SECRET:
        raise AgentAccessDeniedError(AgentAccessReason.KEY_INVALID)
    return KEY


async def _enabled(ctx: Context, key: AgentKey) -> set[str] | None:
    return set(ALL_TOOLS)


@lifespan
async def _agent_lifespan(server: Any) -> Any:
    async with UPSTREAM.client() as client:
        yield {MCP_DB_POOL_KEY: POOL, AGENT_HTTP_CLIENT_KEY: client}


class _VersionProbe(Middleware):
    """Records the request's protocol version as later middleware sees it (AAU-4.1 scope (c))."""

    async def on_list_tools(
        self, context: MiddlewareContext[mt.ListToolsRequest], call_next: CallNext[mt.ListToolsRequest, Any]
    ) -> Any:
        SEEN_VERSIONS.append(current_protocol_version())
        return await call_next(context)


def _agent_app() -> FastMCP:
    app = build_agent_server(
        proxy=InvocationProxy(InvocationConfig(policy=UpstreamCallPolicy(), mock_base_url="http://mock.internal:8775")),
        access=AgentAccessMiddleware(key_resolver=_resolve, enabled_tools=_enabled),
        quota=AgentQuotaMiddleware(guard=AgentQuotaGuard(), pool_source=lambda ctx: POOL),  # type: ignore[arg-type,return-value]
        server_lifespan=_agent_lifespan,
    )
    app.add_middleware(_VersionProbe())
    return app


@pytest.fixture(scope="module")
def base_url() -> Generator[str, None, None]:
    """Serve a catalog stand-in and the real agent runtime for this module."""
    with serve_http_app(build_http_app(FastMCP("Catalog stand-in"), _agent_app())) as url:
        yield url


def _offer_order(offered: str) -> tuple[str, ...]:
    """The client's version preference: ``offered`` first, then every handshake revision."""
    return (offered, *(v for v in HANDSHAKE_PROTOCOL_VERSIONS if v != offered))


async def _discover(base_url: str, offered: str) -> tuple[str, ConformanceReport]:
    """Discover ``/agent/mcp`` offering ``offered``; return the negotiated version and the gated report."""
    recorder = TranscriptRecorder()
    async with StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers=AUTH, transcript=recorder) as transport:
        initialize = await initialize_session(transport, supported_versions=_offer_order(offered))
        listings = await discover_listings(transport, initialize.capabilities)
    surface = DiscoverySurface.from_discovery(initialize, listings)
    report = run_conformance(
        ConformanceContext(surface=surface, transcript=recorder.transcript()), profile=PROFILE_PROTOCOL, fail_on="error"
    )
    return initialize.protocol_version, report


# ============================================================================
# The gate: mcp-protocol profile, failOn=error, once per served version
# ============================================================================


@pytest.mark.parametrize("offered", list(SELF_GATE_NEGOTIATION))
def test_agent_runtime_passes_the_protocol_profile(base_url: str, offered: str) -> None:
    negotiated, report = asyncio.run(_discover(base_url, offered))
    print(json.dumps({"offered": offered, "negotiated": negotiated, **report.report_dict()}, indent=2, default=str))

    assert negotiated == SELF_GATE_NEGOTIATION[offered], "the runtime's negotiation regressed"
    assert report.transcript_captured is True
    assert report.skipped_rules == (), "every protocol rule must be evaluated, none assumed to pass"
    assert report.gate.passed, report.gate.reasons
    assert not [f for f in report.findings if f.severity == "error"]


def test_every_served_version_is_gated() -> None:
    """A version added to the served table without a gate column fails here, not in production."""
    assert set(SERVED_PROTOCOL_VERSIONS) <= set(SELF_GATE_NEGOTIATION)


def test_unserved_handshake_offer_is_counter_offered_not_echoed(base_url: str) -> None:
    """The SDK alone would agree to 2024-11-05; the runtime answers its latest handshake revision."""

    async def run() -> None:
        async with StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers=AUTH) as transport:
            await initialize_session(transport, supported_versions=("2024-11-05",))

    with pytest.raises(McpVersionNegotiationError) as info:
        asyncio.run(run())
    assert info.value.server_version == LATEST_HANDSHAKE_VERSION


# ============================================================================
# Acceptance: unsupported MCP-Protocol-Version → 400 + the supported list
# ============================================================================


def _initialize_body(version: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }


@pytest.mark.parametrize("header", ["1999-01-01", "2024-11-05", "2026-07-28-draft"])
def test_unsupported_header_is_refused_with_the_supported_list(base_url: str, header: str) -> None:
    response = httpx.post(
        f"{base_url}/agent/mcp",
        headers={**AUTH, **MCP_ACCEPT, "MCP-Protocol-Version": header},
        json=_initialize_body("2025-06-18"),
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == UNSUPPORTED_PROTOCOL_VERSION_CODE
    assert error["data"]["supported"] == list(ACCEPTED_PROTOCOL_VERSIONS)
    assert error["data"]["requested"] == header


def test_conflicting_version_headers_are_refused(base_url: str) -> None:
    headers = [*AUTH.items(), *MCP_ACCEPT.items(), ("MCP-Protocol-Version", "2025-06-18")]
    headers.append(("MCP-Protocol-Version", "2025-11-25"))
    response = httpx.post(f"{base_url}/agent/mcp", headers=headers, json=_initialize_body("2025-06-18"))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == UNSUPPORTED_PROTOCOL_VERSION_CODE


def test_modern_header_is_accepted_not_refused(base_url: str) -> None:
    """A 2026-07-28 client falling back to initialize is served the latest handshake revision."""
    response = httpx.post(
        f"{base_url}/agent/mcp",
        headers={**AUTH, **MCP_ACCEPT, "MCP-Protocol-Version": "2026-07-28"},
        json=_initialize_body("2026-07-28"),
    )
    assert response.status_code == 200
    assert f'"protocolVersion":"{LATEST_HANDSHAKE_VERSION}"' in response.text


def test_http_sse_is_never_served_on_the_agent_mount(base_url: str) -> None:
    assert httpx.get(f"{base_url}/agent/sse", headers=AUTH).status_code == 404


# ============================================================================
# Scope (c): the request's version is visible to middleware
# ============================================================================


def test_middleware_sees_the_requests_protocol_version(base_url: str) -> None:
    """Each request's header version — including a modern one handed to the SDK — reaches middleware."""

    async def run() -> None:
        async with httpx.AsyncClient(base_url=base_url, headers={**AUTH, **MCP_ACCEPT}) as client:
            init = await client.post("/agent/mcp", json=_initialize_body("2025-11-25"))
            session = {"Mcp-Session-Id": init.headers["mcp-session-id"]}
            await client.post(
                "/agent/mcp",
                headers={**session, "MCP-Protocol-Version": "2025-11-25"},
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            for version in ("2025-11-25", "2026-07-28"):
                listed = await client.post(
                    "/agent/mcp",
                    headers={**session, "MCP-Protocol-Version": version},
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                assert listed.status_code == 200, listed.text

    SEEN_VERSIONS.clear()
    asyncio.run(run())
    assert SEEN_VERSIONS == ["2025-11-25", "2026-07-28"]
