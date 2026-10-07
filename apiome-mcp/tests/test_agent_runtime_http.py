"""AGX-2.1 acceptance over streamable HTTP (#4533).

The real HTTP app (:func:`apiome_mcp.http_app.build_http_app`) — a stand-in catalog at ``/mcp`` and
the real agent runtime (:func:`apiome_mcp.agent_server.build_agent_server`) at ``/agent/mcp`` — is
served by Uvicorn. A FastMCP client presents an agent key over ``Authorization: Bearer``. The agent
key resolves through a stub (the resolver itself is AGX-3.1's, tested there); the toolset, its
source, the quota caps and the audit rows go through the real SQL paths against the recording pool;
the upstream is an in-memory Petstore standing in for the SIM mock.

The ticket's acceptance criteria, as tests:

* with an agent key and a Petstore toolset targeting the mock, an MCP client lists pets and creates a
  pet through ``tools/call``;
* upstream 400 / 404 / 500 and a timeout each produce a distinct, hint-carrying MCP error;
* argument validation failures never reach the upstream;
* P95 proxy overhead stays under 100 ms over the upstream call.
"""

from __future__ import annotations

import asyncio
import json
import socket
import statistics
import threading
import time
from collections.abc import Generator
from typing import Any

import httpx
import mcp.types as mt
import pytest
import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.lifespan import lifespan
from mcp import McpError
from starlette.requests import Request
from starlette.responses import JSONResponse

from agent_runtime_fakes import ALL_TOOLS, KEY_ID, TENANT_ID, TOOLSET_ID, AgentDb, PetstoreUpstream, invocation_rows
from apiome_mcp.agent_access import (
    AGENT_TOOLSET_UNAVAILABLE_CODE,
    AgentAccessDeniedError,
    AgentAccessMiddleware,
    AgentAccessReason,
    AgentKey,
)
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.agent_server import AGENT_HTTP_CLIENT_KEY, build_agent_server
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy
from apiome_mcp.database_pool import MCP_DB_POOL_KEY
from apiome_mcp.http_app import build_http_app

SECRET = "ak_" + "a1" * 32
NARROW_SECRET = "ak_" + "b2" * 32

#: The SIM mock stand-in; ``/{tenant}/{project}/{version}/pets…`` like the real mock.
UPSTREAM = PetstoreUpstream()
DB = AgentDb()
POOL = DB.pool()

#: Agent keys by secret: the full key may use every tool, the narrow one only listPets.
KEYS = {
    SECRET: AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=ALL_TOOLS),
    NARROW_SECRET: AgentKey(
        key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=frozenset({"listPets"})
    ),
}


async def _resolve(ctx: Context, secret: str) -> AgentKey:
    key = KEYS.get(secret)
    if key is None:
        raise AgentAccessDeniedError(AgentAccessReason.KEY_INVALID)
    return key


async def _enabled(ctx: Context, key: AgentKey) -> set[str] | None:
    return set(ALL_TOOLS) if DB.manifest is not None else None


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


def _catalog_app() -> FastMCP:
    catalog = FastMCP("Catalog stand-in")

    @catalog.tool(name="spec.list")
    def spec_list() -> list[str]:
        return []

    @catalog.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return catalog


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def base_url() -> Generator[str, None, None]:
    """Serve catalog + agent runtime on a free port for this module; yield the server root."""
    port = _free_port()
    app = build_http_app(_catalog_app(), _agent_app())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    ready = threading.Event()
    stop = threading.Event()

    def _run() -> None:
        async def _serve() -> None:
            task = asyncio.ensure_future(server.serve())
            while not server.started:
                await asyncio.sleep(0.05)
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            server.should_exit = True
            await task

        asyncio.run(_serve())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    if not ready.wait(timeout=15):
        raise RuntimeError("HTTP app did not start within 15 s")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        stop.set()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    UPSTREAM.override = None
    UPSTREAM.requests.clear()
    POOL.statements.clear()
    yield
    UPSTREAM.override = None


def _client(base_url: str, secret: str | None = SECRET) -> Client:
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return Client(StreamableHttpTransport(url=f"{base_url}/agent/mcp", headers=headers))


def _call(base_url: str, tool: str, arguments: dict[str, Any], secret: str = SECRET) -> mt.CallToolResult:
    async def run() -> mt.CallToolResult:
        async with _client(base_url, secret) as client:
            return await client.call_tool_mcp(tool, arguments)

    return asyncio.run(run())


def _structured(result: mt.CallToolResult) -> dict[str, Any]:
    assert result.structuredContent is not None
    return result.structuredContent


# ============================================================================
# Acceptance: list pets and create a pet through tools/call (mock target)
# ============================================================================


def test_tools_list_serves_the_compiled_toolset(base_url: str) -> None:
    async def run() -> list[mt.Tool]:
        async with _client(base_url) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    assert set(tools) == ALL_TOOLS
    assert tools["createPet"].inputSchema["required"] == ["name"]
    assert tools["listPets"].outputSchema is None


def test_tools_carry_annotations_from_the_write_op_flags(base_url: str) -> None:
    async def run() -> list[mt.Tool]:
        async with _client(base_url) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run())}
    for name in ("listPets", "showPetById"):
        hints = tools[name].annotations
        assert hints is not None
        assert (hints.readOnlyHint, hints.destructiveHint, hints.idempotentHint) == (True, False, True)
        assert "Changes data" not in (tools[name].description or "")
    create, delete = tools["createPet"], tools["deletePet"]
    assert create.annotations is not None and delete.annotations is not None
    assert (create.annotations.readOnlyHint, create.annotations.destructiveHint) == (False, True)
    assert (create.annotations.idempotentHint, delete.annotations.idempotentHint) == (False, True)
    assert "Not idempotent" in (create.description or "")
    assert "Idempotent: repeating" in (delete.description or "")


def test_an_agent_lists_pets_and_creates_a_pet(base_url: str) -> None:
    listed = _call(base_url, "listPets", {"limit": 5})
    assert listed.isError is False
    assert [pet["name"] for pet in _structured(listed)["body"]] == ["Rex"]
    assert UPSTREAM.requests[-1].url.path == "/acme/petstore/1.0.0/pets"

    created = _call(base_url, "createPet", {"name": "Tom", "tag": "cat"})
    assert created.isError is False
    assert _structured(created)["httpStatus"] == 201
    assert json.loads(created.content[0].text)["name"] == "Tom"  # type: ignore[union-attr]

    names = [pet["name"] for pet in _structured(_call(base_url, "listPets", {}))["body"]]
    assert "Tom" in names
    outcomes = [row["outcome"] for row in invocation_rows(POOL)]
    assert outcomes == ["success", "success", "success"]


def test_the_catalog_and_health_route_stay_on_their_own_paths(base_url: str) -> None:
    assert httpx.get(f"{base_url}/health").json() == {"status": "ok"}

    async def run() -> set[str]:
        async with Client(StreamableHttpTransport(url=f"{base_url}/mcp")) as client:
            return {tool.name for tool in await client.list_tools()}

    assert asyncio.run(run()) == {"spec.list"}


# ============================================================================
# Acceptance: 400 / 404 / 500 / timeout are distinct, hint-carrying errors
# ============================================================================


def test_upstream_failures_are_distinct_hint_carrying_errors(base_url: str) -> None:
    reasons = {}
    for status in (400, 500):
        UPSTREAM.override = lambda request, status=status: httpx.Response(status, json={"detail": "nope"})
        result = _call(base_url, "showPetById", {"petId": "1"})
        assert result.isError is True
        reasons[status] = _structured(result)

    UPSTREAM.override = None
    reasons[404] = _structured(_call(base_url, "showPetById", {"petId": "404404"}))

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    UPSTREAM.override = slow
    timeout = _call(base_url, "listPets", {})
    assert timeout.isError is True
    reasons[0] = _structured(timeout)

    assert {key: value["reason"] for key, value in reasons.items()} == {
        400: "upstream_bad_request",
        404: "upstream_not_found",
        500: "upstream_server_error",
        0: "upstream_timeout",
    }
    assert all(value["hint"] for value in reasons.values())
    assert len({value["hint"] for value in reasons.values()}) == 4


# ============================================================================
# Acceptance: validation failures never reach the upstream
# ============================================================================


def test_validation_failures_never_reach_the_upstream(base_url: str) -> None:
    for tool, arguments in (("createPet", {}), ("listPets", {"limit": 0}), ("listPets", {"bogus": 1})):
        result = _call(base_url, tool, arguments)
        assert result.isError is True
        assert _structured(result)["reason"] == "invalid_arguments"
    assert UPSTREAM.requests == []
    assert {row["outcome"] for row in invocation_rows(POOL)} == {"validation_failure"}


# ============================================================================
# Access still applies
# ============================================================================


def test_a_tool_outside_the_allowlist_looks_like_an_unknown_tool(base_url: str) -> None:
    result = _call(base_url, "createPet", {"name": "Tom"}, secret=NARROW_SECRET)
    assert result.isError is True
    assert "Unknown tool: 'createPet'" in result.content[0].text  # type: ignore[union-attr]
    assert UPSTREAM.requests == []


def test_an_unavailable_toolset_fails_closed(base_url: str) -> None:
    saved = DB.manifest
    DB.manifest = None
    try:

        async def run() -> None:
            async with _client(base_url) as client:
                await client.list_tools()

        with pytest.raises(McpError) as exc:
            asyncio.run(run())
        assert exc.value.error.code == AGENT_TOOLSET_UNAVAILABLE_CODE
    finally:
        DB.manifest = saved


# ============================================================================
# Acceptance: P95 proxy overhead < 100 ms over the upstream call
# ============================================================================


def test_p95_proxy_overhead_is_under_100_ms(base_url: str) -> None:
    """The upstream answers instantly, so each call's whole round trip is overhead (an upper bound)."""

    async def run() -> list[float]:
        timings = []
        async with _client(base_url) as client:
            await client.call_tool_mcp("listPets", {})  # warm the compile cache and the connection
            for _ in range(40):
                started = time.perf_counter()
                result = await client.call_tool_mcp("listPets", {"limit": 3})
                timings.append((time.perf_counter() - started) * 1000)
                assert result.isError is False
        return timings

    timings = asyncio.run(run())
    p95 = statistics.quantiles(timings, n=20)[-1]
    assert p95 < 100, f"P95 overhead {p95:.1f} ms"
