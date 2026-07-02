"""Unit tests for the MCP initialize handshake + version negotiation (V2-MCP-16.2, #3658).

These drive :func:`app.mcp_client.handshake.initialize_session` against the real
:class:`StreamableHttpTransport` wired to a mocked httpx transport (no sockets),
so every negotiation branch is covered deterministically: a clean echo, a
result-level fallback, a ``-32602`` fallback-and-retry, refusal of unsupported
versions, generic JSON-RPC failures, and malformed results. A companion
integration test that negotiates against real loopback stub servers lives in
``test_mcp_handshake_integration.py``.
"""

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.mcp_client.handshake import (
    DEFAULT_CLIENT_CAPABILITIES,
    DEFAULT_CLIENT_INFO,
    SUPPORTED_PROTOCOL_VERSIONS,
    InitializeResult,
    McpVersionNegotiationError,
    ServerInfo,
    initialize_session,
)
from app.mcp_client.transport_http import (
    McpProtocolError,
    StreamableHttpTransport,
)

ENDPOINT = "https://mcp.example.com/mcp"
V_LATEST = "2025-06-18"
V_PRIOR = "2025-03-26"


# ===========================================================================
# Test helpers
# ===========================================================================


def json_response(message: Dict[str, Any], **headers: str) -> httpx.Response:
    return httpx.Response(200, json=message, headers=headers)


class InitHandler:
    """A MockTransport handler scripting the server's ``initialize`` replies.

    ``init_replies`` is a list of factories ``(body) -> httpx.Response`` consumed
    one per ``initialize`` request (so successive attempts can differ). Anything
    else (notifications, ``DELETE``) is acknowledged trivially. Every request and
    decoded JSON body is recorded for assertions.
    """

    def __init__(self, init_replies: List[Callable[[Dict[str, Any]], httpx.Response]]) -> None:
        self._init_replies = list(init_replies)
        self.requests: List[httpx.Request] = []
        self.bodies: List[Dict[str, Any]] = []
        self.init_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        self.bodies.append(body)
        if "id" not in body:  # a notification (e.g. notifications/initialized)
            return httpx.Response(202)
        if body.get("method") == "initialize":
            reply = self._init_replies[min(self.init_count, len(self._init_replies) - 1)]
            self.init_count += 1
            return reply(body)
        return json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"ok": True}})

    @property
    def init_bodies(self) -> List[Dict[str, Any]]:
        return [b for b in self.bodies if b.get("method") == "initialize"]

    @property
    def notification_methods(self) -> List[str]:
        return [b["method"] for b in self.bodies if "id" not in b]


def ok_init(
    body: Dict[str, Any],
    *,
    protocol_version: str = V_LATEST,
    capabilities: Optional[Dict[str, Any]] = None,
    server_info: Optional[Dict[str, Any]] = None,
    instructions: Optional[str] = None,
) -> httpx.Response:
    """A successful ``initialize`` result echoing the given negotiated fields."""
    result: Dict[str, Any] = {
        "protocolVersion": protocol_version,
        "capabilities": capabilities if capabilities is not None else {},
    }
    if server_info is not None:
        result["serverInfo"] = server_info
    if instructions is not None:
        result["instructions"] = instructions
    return json_response({"jsonrpc": "2.0", "id": body["id"], "result": result})


def error_init(body: Dict[str, Any], *, code: int, message: str, data: Any = None) -> httpx.Response:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return json_response({"jsonrpc": "2.0", "id": body["id"], "error": error})


def make_transport(handler: InitHandler) -> StreamableHttpTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return StreamableHttpTransport(ENDPOINT, client=client)


# ===========================================================================
# Happy path: echo
# ===========================================================================


async def test_echo_handshake_parses_full_result():
    handler = InitHandler(
        [
            lambda body: ok_init(
                body,
                protocol_version=V_LATEST,
                capabilities={"tools": {"listChanged": True}, "resources": {}},
                server_info={"name": "example", "title": "Example Server", "version": "1.2.3"},
                instructions="Use the tools sparingly.",
            )
        ]
    )
    transport = make_transport(handler)

    result = await initialize_session(transport)

    assert isinstance(result, InitializeResult)
    assert result.protocol_version == V_LATEST
    assert result.server_info == ServerInfo(name="example", title="Example Server", version="1.2.3")
    assert result.capabilities == {"tools": {"listChanged": True}, "resources": {}}
    assert result.instructions == "Use the tools sparingly."
    assert result.raw["protocolVersion"] == V_LATEST
    # The agreed version is pinned on the transport for downstream requests.
    assert transport.protocol_version == V_LATEST
    assert transport.initialized is True


async def test_initialize_request_carries_default_client_params():
    handler = InitHandler([lambda body: ok_init(body)])
    transport = make_transport(handler)

    await initialize_session(transport)

    params = handler.init_bodies[0]["params"]
    assert params["protocolVersion"] == SUPPORTED_PROTOCOL_VERSIONS[0]
    assert params["capabilities"] == DEFAULT_CLIENT_CAPABILITIES
    assert params["clientInfo"] == DEFAULT_CLIENT_INFO
    assert params["clientInfo"]["name"] == "apiome-mcp-catalog"


async def test_initialized_notification_sent_after_success():
    handler = InitHandler([lambda body: ok_init(body)])
    transport = make_transport(handler)

    await initialize_session(transport)

    assert handler.notification_methods == ["notifications/initialized"]


async def test_custom_client_info_and_capabilities_are_sent():
    handler = InitHandler([lambda body: ok_init(body)])
    transport = make_transport(handler)

    await initialize_session(
        transport,
        client_info={"name": "custom", "version": "9.9"},
        capabilities={"roots": {"listChanged": True}},
    )

    params = handler.init_bodies[0]["params"]
    assert params["clientInfo"] == {"name": "custom", "version": "9.9"}
    assert params["capabilities"] == {"roots": {"listChanged": True}}


# ===========================================================================
# Fallback in the result (server picks an older but supported version)
# ===========================================================================


async def test_result_level_fallback_to_supported_version():
    # We request the latest but the server answers with the prior (still supported) version.
    handler = InitHandler([lambda body: ok_init(body, protocol_version=V_PRIOR, server_info={"name": "old"})])
    transport = make_transport(handler)

    result = await initialize_session(transport)

    assert result.protocol_version == V_PRIOR
    # 2025-03-26 servers have no title field.
    assert result.server_info.title is None
    assert transport.protocol_version == V_PRIOR
    assert handler.init_count == 1  # single round-trip, no retry
    assert handler.notification_methods == ["notifications/initialized"]


# ===========================================================================
# -32602 fallback-and-retry
# ===========================================================================


async def test_invalid_params_triggers_retry_with_mutual_version():
    replies = [
        # First attempt (latest) is rejected; server advertises only the prior version.
        lambda body: error_init(
            body, code=-32602, message="Unsupported protocol version",
            data={"supported": [V_PRIOR], "requested": V_LATEST},
        ),
        # Retry succeeds at the prior version.
        lambda body: ok_init(body, protocol_version=V_PRIOR, server_info={"name": "old"}),
    ]
    handler = InitHandler(replies)
    transport = make_transport(handler)

    result = await initialize_session(transport)

    assert result.protocol_version == V_PRIOR
    assert handler.init_count == 2
    # The two attempts requested the latest, then the negotiated prior version.
    assert handler.init_bodies[0]["params"]["protocolVersion"] == V_LATEST
    assert handler.init_bodies[1]["params"]["protocolVersion"] == V_PRIOR
    assert handler.notification_methods == ["notifications/initialized"]


async def test_invalid_params_without_mutual_version_refuses_without_retry():
    handler = InitHandler(
        [
            lambda body: error_init(
                body, code=-32602, message="Unsupported protocol version",
                data={"supported": ["1999-01-01"]},
            )
        ]
    )
    transport = make_transport(handler)

    with pytest.raises(McpVersionNegotiationError) as exc:
        await initialize_session(transport)

    assert exc.value.server_supported == ("1999-01-01",)
    assert handler.init_count == 1  # no retry when there is no mutual version
    assert handler.notification_methods == []  # never completed the handshake


async def test_invalid_params_on_retry_is_terminal():
    # Server keeps rejecting even the version it advertised — give up after one retry.
    replies = [
        lambda body: error_init(
            body, code=-32602, message="nope", data={"supported": [V_PRIOR]},
        ),
        lambda body: error_init(
            body, code=-32602, message="still nope", data={"supported": [V_PRIOR]},
        ),
    ]
    handler = InitHandler(replies)
    transport = make_transport(handler)

    with pytest.raises(McpVersionNegotiationError):
        await initialize_session(transport)

    assert handler.init_count == 2  # one attempt + exactly one retry


# ===========================================================================
# Disconnect on unsupported
# ===========================================================================


async def test_unsupported_negotiated_version_is_refused():
    handler = InitHandler([lambda body: ok_init(body, protocol_version="2099-12-31")])
    transport = make_transport(handler)

    with pytest.raises(McpVersionNegotiationError) as exc:
        await initialize_session(transport)

    assert exc.value.server_version == "2099-12-31"
    assert exc.value.client_supported == SUPPORTED_PROTOCOL_VERSIONS
    assert handler.notification_methods == []  # handshake not completed


# ===========================================================================
# Generic / malformed failures
# ===========================================================================


async def test_generic_jsonrpc_error_is_not_a_negotiation_error():
    handler = InitHandler([lambda body: error_init(body, code=-32603, message="boom")])
    transport = make_transport(handler)

    with pytest.raises(McpProtocolError) as exc:
        await initialize_session(transport)

    assert not isinstance(exc.value, McpVersionNegotiationError)
    assert "-32603" in str(exc.value)


async def test_missing_protocol_version_in_result_is_a_protocol_error():
    handler = InitHandler(
        [lambda body: json_response({"jsonrpc": "2.0", "id": body["id"], "result": {"capabilities": {}}})]
    )
    transport = make_transport(handler)

    with pytest.raises(McpProtocolError):
        await initialize_session(transport)


# ===========================================================================
# Argument validation
# ===========================================================================


async def test_empty_supported_versions_rejected():
    handler = InitHandler([lambda body: ok_init(body)])
    transport = make_transport(handler)

    with pytest.raises(ValueError):
        await initialize_session(transport, supported_versions=[])


async def test_preferred_version_must_be_supported():
    handler = InitHandler([lambda body: ok_init(body)])
    transport = make_transport(handler)

    with pytest.raises(ValueError):
        await initialize_session(transport, preferred_version="2099-01-01")


async def test_preferred_version_is_requested_first():
    handler = InitHandler([lambda body: ok_init(body, protocol_version=V_PRIOR)])
    transport = make_transport(handler)

    await initialize_session(transport, preferred_version=V_PRIOR)

    assert handler.init_bodies[0]["params"]["protocolVersion"] == V_PRIOR


# ===========================================================================
# ServerInfo parsing edge cases
# ===========================================================================


def test_server_info_from_missing_or_partial():
    assert ServerInfo.from_dict(None) == ServerInfo()
    assert ServerInfo.from_dict({}) == ServerInfo()
    assert ServerInfo.from_dict({"name": "x"}) == ServerInfo(name="x")
    # Empty strings are normalized to None.
    assert ServerInfo.from_dict({"name": "", "title": "T"}) == ServerInfo(title="T")
