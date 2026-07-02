"""Unit tests for the MCP invocation service (V2-MCP-22.1 / MCAT-8.1, #3687).

These drive :mod:`app.mcp_invoke` against the real
:class:`~app.mcp_client.transport_http.StreamableHttpTransport` wired to a mocked
httpx transport (no sockets), so every outcome the test harness must distinguish is
covered deterministically:

* a tool that runs and succeeds (content + latency, ``is_error`` False),
* a tool that runs but reports a tool-level error (``isError:true`` → ``is_error``
  True, still ``completed``),
* a JSON-RPC *protocol* error result (unknown tool → ``completed`` False,
  ``jsonrpc_error``),
* a transport/handshake failure (401 → ``completed`` False, ``auth_required``),
* ``resources/read`` and ``prompts/get`` happy paths, and
* argument-validation guards (empty name, non-mapping arguments).

A companion integration test that calls a real loopback stub server lives in
``test_mcp_invoke_integration.py`` (the ticket's acceptance criterion).
"""

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.mcp_client.errors import DiscoveryErrorCode
from app.mcp_invoke import (
    INVOCATION_METHODS,
    PROMPT_GET,
    RESOURCE_READ,
    TOOL_CALL,
    get_prompt,
    invoke_tool,
    read_resource,
)

ENDPOINT = "https://mcp.example.com/mcp"
SESSION_ID = "invoke-session-0001"


# ===========================================================================
# Test helpers
# ===========================================================================


class InvokeHandler:
    """A MockTransport handler scripting an ``initialize`` + one invocation reply.

    The handshake (``initialize`` / ``notifications/initialized``) is always answered;
    the post-handshake request is answered by ``responder`` — a callable mapping the
    request body to either a ``result`` object or a JSON-RPC ``error`` object. Every
    request body is recorded on ``bodies`` for assertions.
    """

    def __init__(self, responder: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self._responder = responder
        self.bodies: List[Dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        self.bodies.append(body)
        if "id" not in body:  # notifications/initialized
            return httpx.Response(202)
        if body.get("method") == "initialize":
            return _json_rpc(
                body["id"],
                result={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "stub", "version": "0.1.0"},
                },
                headers={"Mcp-Session-Id": SESSION_ID},
            )
        return _json_rpc_envelope(body["id"], self._responder(body))

    def invocation_body(self, method: str) -> Optional[Dict[str, Any]]:
        """The recorded request body for ``method`` (e.g. ``"tools/call"``), if any."""
        for body in self.bodies:
            if body.get("method") == method:
                return body
        return None


def _json_rpc(rpc_id: Any, *, result: Any, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    """Build a single-object JSON-RPC *result* response."""
    payload = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result})
    return httpx.Response(
        200,
        content=payload,
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def _json_rpc_envelope(rpc_id: Any, envelope: Dict[str, Any]) -> httpx.Response:
    """Build a JSON-RPC response from a ``{"result": …}`` or ``{"error": …}`` envelope."""
    message = {"jsonrpc": "2.0", "id": rpc_id, **envelope}
    return httpx.Response(
        200, content=json.dumps(message), headers={"Content-Type": "application/json"}
    )


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    """An httpx client whose transport is the given mock handler."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ===========================================================================
# tools/call — the three outcomes
# ===========================================================================


async def test_invoke_tool_success_returns_content_and_latency():
    """A tool that runs OK returns its content blocks, no error, and a latency reading."""
    handler = InvokeHandler(
        lambda body: {
            "result": {
                "content": [{"type": "text", "text": "hello world"}],
                "isError": False,
            }
        }
    )
    async with _client(handler) as client:
        result = await invoke_tool(
            ENDPOINT, "echo", {"message": "hi"}, client=client
        )

    assert result.completed is True
    assert result.is_error is False
    assert result.succeeded is True
    assert result.content == ({"type": "text", "text": "hello world"},)
    assert result.error is None
    assert result.latency_ms >= 0.0
    assert result.method == "tools/call"
    assert result.target == "echo"
    # The tool name + arguments are forwarded verbatim in the params.
    call = handler.invocation_body("tools/call")
    assert call["params"] == {"name": "echo", "arguments": {"message": "hi"}}


async def test_invoke_tool_iserror_result_is_completed_but_flagged():
    """A tool-level error (``isError:true``) completes with content, distinct from a failure."""
    handler = InvokeHandler(
        lambda body: {
            "result": {
                "content": [{"type": "text", "text": "upstream API failed"}],
                "isError": True,
            }
        }
    )
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "fetch", client=client)

    assert result.completed is True  # the call itself ran
    assert result.is_error is True  # ...but the tool reported an error
    assert result.succeeded is False
    assert result.error is None  # not a transport/protocol failure
    assert result.content == ({"type": "text", "text": "upstream API failed"},)


async def test_invoke_tool_captures_structured_content():
    """A tool's optional ``structuredContent`` is surfaced alongside the content blocks."""
    handler = InvokeHandler(
        lambda body: {
            "result": {
                "content": [{"type": "text", "text": "{}"}],
                "structuredContent": {"temperature": 21, "unit": "C"},
            }
        }
    )
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "weather", client=client)

    assert result.structured_content == {"temperature": 21, "unit": "C"}


async def test_invoke_tool_jsonrpc_error_is_a_protocol_failure():
    """An unknown tool (top-level JSON-RPC error) fails distinctly with ``jsonrpc_error``."""
    handler = InvokeHandler(
        lambda body: {"error": {"code": -32602, "message": "Unknown tool: nope"}}
    )
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "nope", client=client)

    assert result.completed is False
    assert result.is_error is False
    assert result.content == ()
    assert result.error is not None
    assert result.error.code is DiscoveryErrorCode.JSONRPC_ERROR
    assert result.error.detail["method"] == "tools/call"
    assert result.error.detail["code"] == -32602
    assert result.latency_ms >= 0.0


async def test_invoke_tool_transport_failure_is_classified():
    """A 401 during the call surfaces as a transport failure (``auth_required``), not isError."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("method") == "initialize":
            return _json_rpc(
                body["id"],
                result={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stub"},
                },
            )
        if "id" not in body:
            return httpx.Response(202)
        # The tools/call itself is rejected with an auth challenge.
        return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})

    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "secure", client=client)

    assert result.completed is False
    assert result.error is not None
    assert result.error.code is DiscoveryErrorCode.AUTH_REQUIRED
    assert result.error.detail["www_authenticate"] == "Bearer"


async def test_invoke_tool_non_object_result_completes_empty():
    """A spec-violating non-object result completes with empty content rather than raising."""
    handler = InvokeHandler(lambda body: {"result": "not-an-object"})
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "weird", client=client)

    assert result.completed is True
    assert result.content == ()
    assert result.is_error is False


async def test_invoke_tool_defaults_arguments_to_empty_object():
    """Omitting ``arguments`` sends an empty object, never a missing/None params field."""
    handler = InvokeHandler(lambda body: {"result": {"content": []}})
    async with _client(handler) as client:
        await invoke_tool(ENDPOINT, "ping", client=client)

    call = handler.invocation_body("tools/call")
    assert call["params"]["arguments"] == {}


# ===========================================================================
# resources/read and prompts/get
# ===========================================================================


async def test_read_resource_returns_contents():
    """``resources/read`` returns the ``contents`` array under the content key."""
    handler = InvokeHandler(
        lambda body: {
            "result": {
                "contents": [
                    {"uri": "file:///a.txt", "text": "alpha", "mimeType": "text/plain"}
                ]
            }
        }
    )
    async with _client(handler) as client:
        result = await read_resource(ENDPOINT, "file:///a.txt", client=client)

    assert result.completed is True
    assert result.method == "resources/read"
    assert result.content[0]["text"] == "alpha"
    call = handler.invocation_body("resources/read")
    assert call["params"] == {"uri": "file:///a.txt"}


async def test_read_resource_ignores_iserror_flag():
    """A resource read has no tool-level error channel even if a server sends ``isError``."""
    handler = InvokeHandler(
        lambda body: {"result": {"contents": [], "isError": True}}
    )
    async with _client(handler) as client:
        result = await read_resource(ENDPOINT, "file:///x", client=client)

    # supports_is_error is False for resources/read, so the flag is not honoured.
    assert result.is_error is False
    assert result.completed is True


async def test_get_prompt_returns_messages():
    """``prompts/get`` returns the ``messages`` array and forwards name + arguments."""
    handler = InvokeHandler(
        lambda body: {
            "result": {
                "description": "A greeting",
                "messages": [
                    {"role": "user", "content": {"type": "text", "text": "Hi"}}
                ],
            }
        }
    )
    async with _client(handler) as client:
        result = await get_prompt(ENDPOINT, "greet", {"name": "Sam"}, client=client)

    assert result.completed is True
    assert result.method == "prompts/get"
    assert result.content[0]["role"] == "user"
    assert result.raw_result["description"] == "A greeting"
    call = handler.invocation_body("prompts/get")
    assert call["params"] == {"name": "greet", "arguments": {"name": "Sam"}}


async def test_get_prompt_unknown_is_jsonrpc_failure():
    """An unknown prompt fails as a JSON-RPC protocol error, not a completed call."""
    handler = InvokeHandler(
        lambda body: {"error": {"code": -32602, "message": "Unknown prompt"}}
    )
    async with _client(handler) as client:
        result = await get_prompt(ENDPOINT, "missing", client=client)

    assert result.completed is False
    assert result.error.code is DiscoveryErrorCode.JSONRPC_ERROR
    assert result.error.detail["method"] == "prompts/get"


# ===========================================================================
# Argument validation (programming-error guards)
# ===========================================================================


@pytest.mark.parametrize("bad_name", ["", "   "])
async def test_invoke_tool_rejects_empty_name(bad_name):
    """An empty/blank tool name is a caller error and raises before any network call."""
    with pytest.raises(ValueError, match="tool name"):
        await invoke_tool(ENDPOINT, bad_name)


async def test_invoke_tool_rejects_non_mapping_arguments():
    """Non-mapping ``arguments`` raise rather than producing invalid JSON-RPC params."""
    with pytest.raises(ValueError, match="arguments must be a mapping"):
        await invoke_tool(ENDPOINT, "echo", ["not", "a", "map"])  # type: ignore[arg-type]


async def test_read_resource_rejects_empty_uri():
    """A blank resource URI raises before any network call."""
    with pytest.raises(ValueError, match="resource uri"):
        await read_resource(ENDPOINT, "")


# ===========================================================================
# Result serialization & method registry
# ===========================================================================


async def test_as_dict_shapes_the_harness_response():
    """``as_dict`` exposes the fields the test-harness API surfaces, with rounded latency."""
    handler = InvokeHandler(
        lambda body: {"result": {"content": [{"type": "text", "text": "ok"}]}}
    )
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "echo", client=client)

    payload = result.as_dict()
    assert payload["method"] == "tools/call"
    assert payload["target"] == "echo"
    assert payload["completed"] is True
    assert payload["is_error"] is False
    assert payload["content"] == [{"type": "text", "text": "ok"}]
    assert payload["error"] is None
    assert isinstance(payload["latency_ms"], float)


async def test_as_dict_carries_classified_error_on_failure():
    """On failure ``as_dict`` carries the classified error's JSON and empty content."""
    handler = InvokeHandler(
        lambda body: {"error": {"code": -32000, "message": "boom"}}
    )
    async with _client(handler) as client:
        result = await invoke_tool(ENDPOINT, "x", client=client)

    payload = result.as_dict()
    assert payload["completed"] is False
    assert payload["content"] == []
    assert payload["error"]["code"] == "jsonrpc_error"


def test_invocation_methods_registry_maps_item_types():
    """The registry resolves each invocable catalog item type to its JSON-RPC method."""
    assert INVOCATION_METHODS["tool"] is TOOL_CALL
    assert INVOCATION_METHODS["resource"] is RESOURCE_READ
    assert INVOCATION_METHODS["prompt"] is PROMPT_GET
    # Resource templates are not directly invocable (need URI expansion first).
    assert "resource_template" not in INVOCATION_METHODS
    assert TOOL_CALL.supports_is_error is True
    assert RESOURCE_READ.supports_is_error is False
