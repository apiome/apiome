"""AGX-3.1 acceptance over streamable HTTP (#4537).

A stand-in agent surface — a FastMCP app with four Petstore-shaped tools and
:class:`~apiome_mcp.agent_access.AgentAccessMiddleware` — is served by a real Uvicorn server, and a
FastMCP client talks to it with ``Authorization: Bearer <agent key>``. Keys are resolved by the
real :func:`~apiome_mcp.agent_access.resolve_agent_key` against the in-memory
:class:`~agent_access_fakes.FakeAgentKeyPool` (served through the app's lifespan, as the real
pool is). The toolset's enabled tools come from a dictionary standing in for AGX-1.2.

The ticket's acceptance criteria, as tests:

* ``tools/list`` with an allowlisted key returns exactly enabled ∩ allowlist;
* ``tools/call`` on a non-permitted tool fails with an MCP error, indistinguishable from a call to
  a tool that does not exist;
* expired keys are rejected, and revocation takes effect immediately (on the same session's next
  request).
"""

from __future__ import annotations

import asyncio
import socket
import threading
import uuid
from collections.abc import Generator
from typing import Any

import pytest
import uvicorn
from fastmcp import Client, Context, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.lifespan import lifespan
from mcp import McpError

from agent_access_fakes import FakeAgentKeyPool, agent_secret
from apiome_mcp.agent_access import (
    AGENT_KEY_REJECTED_CODE,
    AGENT_TOOLSET_UNAVAILABLE_CODE,
    AgentAccessMiddleware,
    AgentKey,
)
from apiome_mcp.database_pool import MCP_DB_POOL_KEY

_POOL = FakeAgentKeyPool()
_TOOLSET = str(uuid.uuid4())
_OTHER_TOOLSET = str(uuid.uuid4())

#: AGX-1.2 stand-in: each toolset's enabled tools. ``_OTHER_TOOLSET`` is absent (unavailable).
_ENABLED: dict[str, set[str]] = {_TOOLSET: {"listPets", "getPetById", "deletePet"}}


async def _enabled_tools(ctx: Context, key: AgentKey) -> set[str] | None:
    return _ENABLED.get(key.toolset_id)


@lifespan
async def _pool_lifespan(server: Any) -> Any:
    yield {MCP_DB_POOL_KEY: _POOL}


_agent_mcp = FastMCP("AgentSurface", lifespan=_pool_lifespan)
_agent_mcp.add_middleware(AgentAccessMiddleware(enabled_tools=_enabled_tools))


@_agent_mcp.tool(name="listPets")
def list_pets() -> list[str]:
    """List pets."""
    return ["Rex", "Tom"]


@_agent_mcp.tool(name="getPetById")
def get_pet_by_id(pet_id: int) -> dict[str, Any]:
    """Get one pet."""
    return {"id": pet_id}


@_agent_mcp.tool(name="deletePet")
def delete_pet(pet_id: int) -> str:
    """Delete a pet."""
    return f"deleted {pet_id}"


@_agent_mcp.tool(name="createPet")
def create_pet(name: str) -> str:
    """Create a pet."""
    return f"created {name}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def agent_url() -> Generator[str, None, None]:
    """Serve the agent surface on a free port for this module; yield its MCP URL."""
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(_agent_mcp.http_app(path="/mcp"), host="127.0.0.1", port=port, log_level="warning")
    )
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
        raise RuntimeError("agent surface did not start within 15 s")
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        stop.set()
        thread.join(timeout=5)


def _client(url: str, secret: str | None) -> Client:
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    return Client(StreamableHttpTransport(url=url, headers=headers))


def _key(seed: int, **fields: Any) -> str:
    """Store an agent key bound to ``_TOOLSET`` (unless overridden) and return its secret."""
    secret = agent_secret(seed)
    fields.setdefault("toolset_id", _TOOLSET)
    fields.setdefault("allowlist", ["listPets", "deletePet", "createPet"])
    _POOL.add(secret=secret, **fields)
    return secret


def _listed(url: str, secret: str | None) -> set[str]:
    async def run() -> set[str]:
        async with _client(url, secret) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(run())


def _list_error(url: str, secret: str | None) -> McpError:
    async def run() -> None:
        async with _client(url, secret) as client:
            await client.list_tools()

    with pytest.raises(McpError) as exc:
        asyncio.run(run())
    return exc.value


# ============================================================================
# Acceptance: tools/list and tools/call
# ============================================================================
def test_list_returns_exactly_the_permitted_intersection(agent_url: str) -> None:
    secret = _key(1)
    # enabled {listPets, getPetById, deletePet} ∩ allowlist {listPets, deletePet, createPet}
    assert _listed(agent_url, secret) == {"listPets", "deletePet"}


def test_call_on_a_permitted_tool_succeeds(agent_url: str) -> None:
    secret = _key(2)

    async def run() -> None:
        async with _client(agent_url, secret) as client:
            result = await client.call_tool("deletePet", {"pet_id": 7})
            assert result.data == "deleted 7"

    asyncio.run(run())


def test_call_on_a_non_permitted_tool_is_an_mcp_error_like_an_unknown_tool(agent_url: str) -> None:
    secret = _key(3)

    async def run() -> dict[str, str]:
        texts = {}
        async with _client(agent_url, secret) as client:
            for name, args in (
                ("getPetById", {"pet_id": 1}),  # enabled, not on the allowlist
                ("createPet", {"name": "x"}),  # on the allowlist, not enabled
                ("doesNotExist", {}),  # not a tool at all
            ):
                result = await client.call_tool_mcp(name, args)
                assert result.isError is True
                texts[name] = result.content[0].text  # type: ignore[union-attr]
        return texts

    texts = asyncio.run(run())
    assert texts == {
        "getPetById": "Unknown tool: 'getPetById'",
        "createPet": "Unknown tool: 'createPet'",
        "doesNotExist": "Unknown tool: 'doesNotExist'",
    }


# ============================================================================
# Acceptance: expiry and revocation
# ============================================================================
def test_an_expired_key_is_rejected(agent_url: str) -> None:
    secret = _key(4)
    key_id = next(row["id"] for row in _POOL.rows.values() if row["key_prefix"] == secret[:12] + "...")
    _POOL.expire(key_id)
    error = _list_error(agent_url, secret)
    assert error.error.code == AGENT_KEY_REJECTED_CODE
    assert error.error.data == {"reason": "agent_key_expired"}


def test_revocation_takes_effect_on_the_same_sessions_next_request(agent_url: str) -> None:
    secret = _key(5)
    key_id = next(row["id"] for row in _POOL.rows.values() if row["key_prefix"] == secret[:12] + "...")

    async def run() -> McpError:
        async with _client(agent_url, secret) as client:
            assert {tool.name for tool in await client.list_tools()} == {"listPets", "deletePet"}
            _POOL.revoke(key_id)
            with pytest.raises(McpError) as exc:
                await client.list_tools()
            refused_call = await client.call_tool_mcp("listPets", {})
            assert refused_call.isError is True
            assert refused_call.content[0].text.startswith("agent_key_revoked: ")  # type: ignore[union-attr]
            return exc.value

    error = asyncio.run(run())
    assert error.error.code == AGENT_KEY_REJECTED_CODE
    assert error.error.data == {"reason": "agent_key_revoked"}


def test_an_allowlist_edit_shows_on_the_next_list(agent_url: str) -> None:
    secret = _key(6)
    key_id = next(row["id"] for row in _POOL.rows.values() if row["key_prefix"] == secret[:12] + "...")

    async def run() -> tuple[set[str], set[str]]:
        async with _client(agent_url, secret) as client:
            before = {tool.name for tool in await client.list_tools()}
            _POOL.rows[key_id]["tool_allowlist"] = ["getPetById"]
            after = {tool.name for tool in await client.list_tools()}
            return before, after

    assert asyncio.run(run()) == ({"listPets", "deletePet"}, {"getPetById"})


# ============================================================================
# Refusals
# ============================================================================
def test_no_key_is_rejected(agent_url: str) -> None:
    error = _list_error(agent_url, None)
    assert error.error.code == AGENT_KEY_REJECTED_CODE
    assert error.error.data == {"reason": "agent_key_missing"}


def test_an_unknown_key_is_rejected(agent_url: str) -> None:
    error = _list_error(agent_url, agent_secret(0xDEAD))
    assert error.error.data == {"reason": "agent_key_invalid"}


def test_a_workspace_key_is_not_an_agent_key(agent_url: str) -> None:
    secret = agent_secret(7)
    _POOL.add(secret=secret, kind="workspace", toolset_id=None)
    assert _list_error(agent_url, secret).error.data == {"reason": "agent_key_invalid"}


def test_a_disabled_key_is_rejected(agent_url: str) -> None:
    secret = _key(8, enabled=False)
    assert _list_error(agent_url, secret).error.data == {"reason": "agent_key_disabled"}


def test_a_key_whose_toolset_is_unavailable_is_rejected(agent_url: str) -> None:
    secret = _key(9, toolset_id=_OTHER_TOOLSET)
    error = _list_error(agent_url, secret)
    assert error.error.code == AGENT_TOOLSET_UNAVAILABLE_CODE
    assert error.error.data == {"reason": "agent_toolset_unavailable"}


def test_an_empty_allowlist_lists_nothing(agent_url: str) -> None:
    assert _listed(agent_url, _key(10, allowlist=[])) == set()


def test_error_messages_never_carry_the_key(agent_url: str) -> None:
    secret = _key(11, enabled=False)
    error = _list_error(agent_url, secret)
    assert secret not in error.error.message
    assert secret[:12] not in error.error.message
