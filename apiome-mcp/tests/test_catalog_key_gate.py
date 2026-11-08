"""Catalog key gate — every catalog request needs an MCP API key."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as mt
import pytest
from fastmcp import Client, FastMCP
from fastmcp.dependencies import Depends
from fastmcp.exceptions import AuthorizationError
from mcp import McpError
from pydantic import SecretStr

from apiome_mcp.catalog_key_gate import MCP_KEY_REJECTED_CODE, McpKeyRequiredMiddleware
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.mcp_auth import McpAuthContext, require_mcp_auth

_SECRET = "mcp_live_0123456789abcdef"


def _auth(label: str = "gate") -> McpAuthContext:
    return McpAuthContext(key_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), label=label)


def _gated_server() -> FastMCP:
    """Two tools behind the gate: one keyless in signature (like ``spec.search``), one keyed."""
    server = FastMCP("gate-probe")
    server.add_middleware(McpKeyRequiredMiddleware())
    server.add_middleware(StashHttpBearerInToolContextMiddleware())

    @server.tool
    async def public_probe() -> str:
        return "public"

    @server.tool
    async def keyed_probe(auth: McpAuthContext = Depends(require_mcp_auth)) -> str:
        return auth.label

    return server


def _no_stdio_key():
    return patch("apiome_mcp.mcp_auth.get_settings", return_value=SimpleNamespace(api_key=None))


def _gate_db(validate: AsyncMock):
    return (
        patch("apiome_mcp.catalog_key_gate.get_db_pool", return_value=MagicMock()),
        patch("apiome_mcp.catalog_key_gate.validate_mcp_api_key", new=validate),
    )


async def _raw_call(client: Client, name: str, *, meta: dict[str, str]) -> mt.CallToolResult:
    """Send tools/call as-is: the SDK client's own result validation lists tools without the meta."""
    request = mt.ClientRequest(mt.CallToolRequest(params=mt.CallToolRequestParams(name=name, arguments={}, _meta=meta)))
    return await client.session.send_request(request, mt.CallToolResult)


def test_tools_list_without_a_key_is_refused() -> None:
    async def run() -> None:
        with _no_stdio_key():
            async with Client(_gated_server()) as client:
                with pytest.raises(McpError) as excinfo:
                    await client.list_tools()
        assert excinfo.value.error.code == MCP_KEY_REJECTED_CODE
        assert "MCP API key required" in excinfo.value.error.message

    asyncio.run(run())


def test_tool_call_without_a_key_is_refused_even_for_a_keyless_tool() -> None:
    async def run() -> None:
        with _no_stdio_key():
            async with Client(_gated_server()) as client:
                with pytest.raises(Exception, match="MCP API key required"):
                    await client.call_tool("public_probe", {})

    asyncio.run(run())


def test_protocol_ping_needs_no_key() -> None:
    async def run() -> None:
        with _no_stdio_key():
            async with Client(_gated_server()) as client:
                assert await client.ping() is True

    asyncio.run(run())


def test_a_valid_key_in_meta_is_verified_by_the_gate_and_reused_by_the_tool() -> None:
    validate = AsyncMock(return_value=_auth("meta-key"))

    async def run() -> None:
        db, gate_validate = _gate_db(validate)
        with _no_stdio_key(), db, gate_validate:
            with patch("apiome_mcp.mcp_auth.validate_mcp_api_key", new=AsyncMock()) as tool_validate:
                async with Client(_gated_server()) as client:
                    result = await _raw_call(client, "keyed_probe", meta={"apiome_api_key": _SECRET})
                tool_validate.assert_not_awaited()
        assert not result.isError
        assert result.structuredContent == {"result": "meta-key"}
        # The gate verified it (the SDK's first-call tool-cache fill is a nested request of its own);
        # the tool's require_mcp_auth reused that instead of checking bcrypt again.
        assert validate.await_count >= 1
        assert all(call.args[1] == _SECRET for call in validate.await_args_list)

    asyncio.run(run())


def test_an_invalid_key_is_refused_with_the_validators_reason() -> None:
    validate = AsyncMock(side_effect=AuthorizationError("This MCP API key has been revoked."))

    async def run() -> None:
        db, gate_validate = _gate_db(validate)
        with _no_stdio_key(), db, gate_validate:
            async with Client(_gated_server()) as client:
                with pytest.raises(Exception, match="has been revoked"):
                    await client.call_tool("public_probe", {}, meta={"apiome_api_key": _SECRET})

    asyncio.run(run())


def test_verification_failure_fails_closed() -> None:
    validate = AsyncMock(side_effect=OSError("database unreachable"))

    async def run() -> None:
        db, gate_validate = _gate_db(validate)
        with _no_stdio_key(), db, gate_validate:
            async with Client(_gated_server()) as client:
                with pytest.raises(Exception, match="could not be verified"):
                    await client.call_tool("public_probe", {}, meta={"apiome_api_key": _SECRET})

    asyncio.run(run())


def test_stdio_uses_the_configured_api_key() -> None:
    validate = AsyncMock(return_value=_auth("stdio-key"))
    settings = SimpleNamespace(api_key=SecretStr(_SECRET))

    async def run() -> None:
        db, gate_validate = _gate_db(validate)
        with patch("apiome_mcp.mcp_auth.get_settings", return_value=settings), db, gate_validate:
            async with Client(_gated_server()) as client:
                tools = await client.list_tools()
                result = await client.call_tool("keyed_probe", {})
        assert {t.name for t in tools} == {"public_probe", "keyed_probe"}
        assert result.data == "stdio-key"
        assert all(call.args[1] == _SECRET for call in validate.await_args_list)

    asyncio.run(run())


def test_the_configured_api_key_is_never_used_over_http() -> None:
    settings = SimpleNamespace(api_key=SecretStr(_SECRET))

    async def run() -> None:
        from apiome_mcp.mcp_auth import presented_mcp_api_key

        with (
            patch("apiome_mcp.mcp_auth.get_settings", return_value=settings),
            patch("apiome_mcp.mcp_auth.on_http_request", return_value=True),
        ):
            assert await presented_mcp_api_key(None, headers={}) is None

    asyncio.run(run())


def test_direct_in_process_calls_are_not_gated() -> None:
    async def run() -> None:
        with _no_stdio_key():
            tools = await _gated_server().list_tools()
        assert {t.name for t in tools} == {"public_probe", "keyed_probe"}

    asyncio.run(run())


def test_the_catalog_server_runs_the_gate() -> None:
    from apiome_mcp.server import mcp

    assert any(isinstance(m, McpKeyRequiredMiddleware) for m in mcp.middleware)
