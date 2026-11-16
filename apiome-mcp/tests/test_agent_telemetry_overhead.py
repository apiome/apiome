"""ATQ-4.4 acceptance: OTel export costs under 2 % CPU on the AGX-2.1 benchmark (#5846).

Two numbers, both process CPU time (``time.process_time``: every thread of this process):

1. **The AGX-2.1 call.** ``test_agent_runtime_http``'s benchmark drives ``listPets`` through the
   real HTTP app over streamable HTTP. The same app is served here with telemetry **off**, and
   the median CPU per call over several blocks is taken.
2. **The telemetry of one call.** Everything ATQ-4.4 adds to a call, at the **default** settings
   (:func:`telemetry_from_settings`, traces sampled at 0.25, metrics on every call): the invocation
   span (each call starts its own trace, so the ratio alone decides), the ``vault.resolve`` and
   ``upstream.request`` children, the audit attributes, both metrics, and the real batched
   OTLP/HTTP export to the in-process collector stub (flushed inside the measurement, so encoding
   and posting are charged).

Comparing the two directly is far steadier than timing the HTTP benchmark with telemetry on and
off: on a shared machine those two medians differ by several percent from run to run, which is
more than the effect being measured. The ratio must stay under 2 %. The cost at a ratio of 1.0 is
printed (not asserted) for the documentation.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.lifespan import lifespan
from opentelemetry.trace import SpanKind

from agent_runtime_fakes import ALL_TOOLS, KEY_ID, TENANT_ID, TOOLSET_ID, AgentDb, PetstoreUpstream
from apiome_mcp.agent_access import AgentAccessMiddleware, AgentKey
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_invocations import InvocationOutcome, InvocationRecord
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.agent_server import AGENT_HTTP_CLIENT_KEY, build_agent_server
from apiome_mcp.agent_telemetry import SPAN_UPSTREAM, SPAN_VAULT, AgentTelemetry, telemetry_from_settings
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy
from apiome_mcp.database_pool import MCP_DB_POOL_KEY
from apiome_mcp.http_app import build_http_app
from apiome_mcp.settings import Settings
from http_server_harness import serve_http_app
from otlp_collector_stub import otlp_collector

SECRET = "ak_" + "c3" * 32
KEY = AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=ALL_TOOLS)
UPSTREAM = PetstoreUpstream()
POOL = AgentDb().pool()

#: HTTP calls per block, and blocks.
CALLS = 100
ROUNDS = 5
#: Simulated calls for the telemetry measurement.
TELEMETRY_CALLS = 4000
_RECORD = InvocationRecord(
    tenant_id=TENANT_ID,
    key_id=KEY_ID,
    toolset_id=TOOLSET_ID,
    tool_name="listPets",
    target="mock",
    invoked_at=datetime.now(UTC),
    latency_ms=4,
    outcome=InvocationOutcome.SUCCESS,
    error_code=None,
    http_status=200,
    request_bytes=11,
    response_bytes=120,
)


async def _resolve(ctx: Context, secret: str) -> AgentKey:
    return KEY


async def _enabled(ctx: Context, key: AgentKey) -> set[str]:
    return set(ALL_TOOLS)


@lifespan
async def _agent_lifespan(server: Any) -> Any:
    async with UPSTREAM.client() as client:
        yield {MCP_DB_POOL_KEY: POOL, AGENT_HTTP_CLIENT_KEY: client}


def _agent_app() -> FastMCP:
    config = InvocationConfig(
        policy=UpstreamCallPolicy(timeout_seconds=0.3, budget_seconds=1.0, backoff_seconds=0.0),
        mock_base_url="http://mock.internal:8775",
    )
    return build_agent_server(
        proxy=InvocationProxy(config),
        access=AgentAccessMiddleware(key_resolver=_resolve, enabled_tools=_enabled),
        quota=AgentQuotaMiddleware(guard=AgentQuotaGuard(), pool_source=lambda ctx: POOL),  # type: ignore[arg-type,return-value]
        server_lifespan=_agent_lifespan,
    )


@pytest.fixture(scope="module")
def base_url() -> Generator[str, None, None]:
    with serve_http_app(build_http_app(FastMCP("Catalog stand-in"), _agent_app())) as url:
        yield url


def _call_cpu(base_url: str) -> float:
    """Median CPU seconds per AGX-2.1 ``listPets`` call (telemetry off)."""

    async def block() -> float:
        transport = StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers={"Authorization": f"Bearer {SECRET}"})
        async with Client(transport) as client:
            await client.call_tool_mcp("listPets", {})
            started = time.process_time()
            for _ in range(CALLS):
                result = await client.call_tool_mcp("listPets", {"limit": 3})
                assert result.isError is False
            return (time.process_time() - started) / CALLS

    return statistics.median(asyncio.run(block()) for _ in range(ROUNDS))


def _settings(endpoint: str, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql://u:p@localhost/db",
        internal_secret="x" * 16,
        otel_exporter_otlp_endpoint=endpoint,
        **overrides,
    )


def _telemetry_cpu(telemetry: AgentTelemetry) -> float:
    """CPU seconds the telemetry adds to one call, export included (cheapest of three passes)."""
    best = float("inf")
    for _ in range(3):
        started = time.process_time()
        for _ in range(TELEMETRY_CALLS):
            with telemetry.invocation(None) as span:
                with telemetry.child(SPAN_VAULT) as vault:
                    vault.set("apiome.agent.credential_injected", True)
                with telemetry.child(
                    SPAN_UPSTREAM, kind=SpanKind.CLIENT, attributes={"http.request.method": "GET"}
                ) as upstream:
                    upstream.set("http.response.status_code", 200)
                span.record(_RECORD)
        telemetry.flush()
        best = min(best, (time.process_time() - started) / TELEMETRY_CALLS)
    return best


def test_otel_export_costs_under_two_percent_cpu_at_the_defaults(base_url: str) -> None:
    call = _call_cpu(base_url)
    with otlp_collector(parse=False) as (collector, collected):
        default = telemetry_from_settings(_settings(collector))
        full = telemetry_from_settings(_settings(collector, otel_traces_sampler_ratio=1.0))
        try:
            at_default = _telemetry_cpu(default)
            at_full = _telemetry_cpu(full)
        finally:
            default.shutdown()
            full.shutdown()
        assert collected.raw, "the collector received no export"
    print(
        f"AGX-2.1 call {call * 1000:.2f} ms CPU; telemetry at 0.25 {at_default * 1e6:.0f} us "
        f"({at_default / call:.2%}), at 1.0 {at_full * 1e6:.0f} us ({at_full / call:.2%})"
    )
    assert at_default / call < 0.02, f"OTel export overhead {at_default / call:.2%} of {call * 1000:.2f} ms"
