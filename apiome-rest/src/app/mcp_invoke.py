"""MCP tool/resource/prompt invocation service (V2-MCP-22.1 / MCAT-8.1, #3687).

This is the **query & test-harness** core: given a cataloged MCP endpoint, connect
to it with the Epic-2 client (transport → handshake), attach the endpoint's stored
Epic-6 credentials, invoke one capability, and report **what came back, whether it
was an error, and how long it took**. It is the in-process service the test-harness
REST endpoint (MCAT-8.2, #3688) will call; that route handles argument-schema
validation, tenant scoping, and per-call timeouts on top of this layer.

Three invocations are supported, one per invocable capability kind, per the MCP
`tools <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>`_,
`resources <https://modelcontextprotocol.io/specification/2025-06-18/server/resources>`_,
and `prompts <https://modelcontextprotocol.io/specification/2025-06-18/server/prompts>`_
specs:

* ``tools/call``     — :func:`invoke_tool` (``{"name", "arguments"}``)
* ``resources/read`` — :func:`read_resource` (``{"uri"}``)
* ``prompts/get``    — :func:`get_prompt` (``{"name", "arguments"}``)

**The central distinction this service draws** (the ticket's acceptance criterion)
is between the *three* outcomes a test call can have, which the MCP tools spec is
careful to separate:

1. **Tool ran, succeeded** — a JSON-RPC *result* with ``isError`` absent/false. The
   content blocks are returned and :attr:`InvocationResult.is_error` is ``False``.
2. **Tool ran, reported a tool-level error** — a JSON-RPC *result* that still carries
   ``isError: true`` (e.g. an upstream API the tool wraps failed). This is **not** a
   transport failure: the call completed, so the content (the error text the tool
   produced for the model to see) is returned with :attr:`InvocationResult.is_error`
   ``True``. Per the spec, tool execution errors live *inside* the result so a model
   can observe and react to them.
3. **The call itself failed** — either a JSON-RPC *protocol* error (unknown tool,
   invalid params: a top-level ``error`` member) **or** a transport/connection/
   handshake failure (timeout, TLS, 401, version mismatch, malformed reply). Both
   surface as :attr:`InvocationResult.completed` ``False`` with a classified
   :class:`~app.mcp_client.errors.DiscoveryError` on :attr:`InvocationResult.error`,
   reusing the same stable taxonomy the discovery pipeline persists, so the failure
   mode is named (``jsonrpc_error`` vs ``auth_required`` vs ``timeout`` …) rather
   than collapsed into one opaque "it broke".

Every path returns an :class:`InvocationResult` carrying ``latency_ms`` — the service
never raises for an *expected* remote failure; it only raises :class:`ValueError` for
a programming error in the call arguments (an empty tool name, a non-mapping
``arguments``). Latency is the wall-clock from opening the connection through the
invocation response (handshake included, the session ``DELETE`` excluded), which is
exactly the round trip a "test this tool" button measures.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, Mapping, Optional, Tuple

import httpx

from .mcp_client import (
    DiscoveryError,
    DiscoveryErrorCode,
    StreamableHttpTransport,
    classify_exception,
    initialize_session,
)
from .mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_RESOURCE,
    ITEM_TYPE_TOOL,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# Invocation method registry
# ===========================================================================


@dataclass(frozen=True)
class InvocationMethod:
    """Static description of one invocable MCP capability method.

    Attributes:
        method: The JSON-RPC method name (e.g. ``"tools/call"``).
        item_type: The catalog capability kind this method invokes (mirrors
            :data:`app.mcp_client.normalize.ITEM_TYPE_TOOL` …), so a caller holding
            a stored item type can resolve the right method via :data:`INVOCATION_METHODS`.
        content_key: The result key under which the returned payload lives — the
            content blocks (``"content"`` for tools), the resource contents
            (``"contents"``), or the prompt messages (``"messages"``).
        supports_is_error: Whether a successful result may carry an ``isError`` flag.
            Only ``tools/call`` reports tool-level execution errors this way; for
            ``resources/read`` / ``prompts/get`` a failure is always a JSON-RPC error.
    """

    method: str
    item_type: str
    content_key: str
    supports_is_error: bool


#: The tool-invocation method — the must-have of this ticket.
TOOL_CALL = InvocationMethod("tools/call", ITEM_TYPE_TOOL, "content", supports_is_error=True)
#: The resource-read method (no tool-level ``isError``; failures are JSON-RPC errors).
RESOURCE_READ = InvocationMethod(
    "resources/read", ITEM_TYPE_RESOURCE, "contents", supports_is_error=False
)
#: The prompt-get method (no tool-level ``isError``; failures are JSON-RPC errors).
PROMPT_GET = InvocationMethod("prompts/get", ITEM_TYPE_PROMPT, "messages", supports_is_error=False)

#: Every invocable method keyed by catalog ``item_type`` so the test-harness route
#: (MCAT-8.2) can dispatch from a stored capability kind. ``resource_template`` is
#: deliberately absent: a template needs URI expansion before it is a concrete
#: ``resources/read`` target, which is the route's concern, not this service's.
INVOCATION_METHODS: Dict[str, InvocationMethod] = {
    TOOL_CALL.item_type: TOOL_CALL,
    RESOURCE_READ.item_type: RESOURCE_READ,
    PROMPT_GET.item_type: PROMPT_GET,
}


# ===========================================================================
# Result value object
# ===========================================================================


@dataclass(frozen=True)
class InvocationResult:
    """The outcome of one MCP capability invocation, with latency.

    A single shape covers all three outcomes so a caller can branch on two booleans:

    * ``completed=True,  is_error=False`` — the call ran and succeeded.
    * ``completed=True,  is_error=True``  — the call ran but the tool reported a
      tool-level error (only ``tools/call``); ``content`` holds the error payload.
    * ``completed=False`` — the call failed; ``error`` carries the classified reason
      (a JSON-RPC protocol error *or* a transport/handshake failure) and ``content``
      is empty.

    Attributes:
        method: The JSON-RPC method invoked (e.g. ``"tools/call"``).
        target: What was invoked — a tool/prompt name, or a resource URI.
        completed: ``True`` when the server returned a JSON-RPC *result* (whether or
            not it was a tool-level error); ``False`` for any protocol/transport failure.
        is_error: The MCP tool-level execution-error flag (``result.isError``). Only
            meaningful when ``completed`` and the method supports it; always ``False``
            otherwise.
        content: The returned payload items (tool content blocks / resource contents /
            prompt messages), each a verbatim wire object. Empty on failure.
        structured_content: A tool's optional ``structuredContent`` object, when present.
        latency_ms: Wall-clock round trip in milliseconds (connect + handshake +
            invocation; the session teardown ``DELETE`` is excluded).
        error: The classified failure when ``completed`` is ``False``; ``None`` otherwise.
        raw_result: The full JSON-RPC ``result`` object on a completed call, for any
            field not promoted above (a prompt's ``description``, a tool's ``_meta`` …).
    """

    method: str
    target: str
    completed: bool
    latency_ms: float
    is_error: bool = False
    content: Tuple[Dict[str, Any], ...] = ()
    structured_content: Optional[Dict[str, Any]] = None
    error: Optional[DiscoveryError] = None
    raw_result: Optional[Dict[str, Any]] = None

    @property
    def succeeded(self) -> bool:
        """True only for a call that both completed *and* was not a tool-level error."""
        return self.completed and not self.is_error

    def as_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serializable dict of this result.

        Shaped for the test-harness API response (MCAT-8.2): ``latency_ms`` is rounded
        to the millisecond the UI displays, and ``error`` is the classified failure's
        own JSON form (or ``None`` on a completed call).
        """
        return {
            "method": self.method,
            "target": self.target,
            "completed": self.completed,
            "is_error": self.is_error,
            "content": [dict(item) for item in self.content],
            "structured_content": self.structured_content,
            "latency_ms": round(self.latency_ms, 3),
            "error": self.error.as_dict() if self.error is not None else None,
        }


# ===========================================================================
# Public invocation API
# ===========================================================================


async def invoke_tool(
    url: str,
    name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    allow_insecure_http: bool = False,
    allow_private_network: bool = False,
    timeout: float = 30.0,
) -> InvocationResult:
    """Call a discovered tool (``tools/call``) and capture content, ``isError``, latency.

    Connects to ``url``, runs the ``initialize`` handshake, sends
    ``tools/call`` with ``{"name", "arguments"}``, and returns an
    :class:`InvocationResult`. A tool that runs but reports an error (``isError:true``)
    completes with :attr:`InvocationResult.is_error` set — distinct from a transport or
    JSON-RPC failure, which yields ``completed=False`` with a classified
    :attr:`InvocationResult.error`.

    Args:
        url: The MCP endpoint (``…/mcp``).
        name: The tool name to invoke; must be a non-empty string.
        arguments: The tool arguments object; defaults to ``{}`` when omitted.
        headers: Auth headers to attach to every request (from
            :func:`app.mcp_credentials.load_endpoint_auth_headers`); empty for anonymous.
        client: An existing httpx ``AsyncClient`` (e.g. a mocked transport in tests);
            when omitted the transport creates and owns one.
        allow_insecure_http: Permit plaintext ``http://`` to non-loopback hosts.
        allow_private_network: Permit an endpoint whose host is a private IP literal.
        timeout: Per-request timeout in seconds (ignored when ``client`` is supplied).

    Returns:
        The :class:`InvocationResult` for the call.

    Raises:
        ValueError: ``name`` is empty, or ``arguments`` is not a mapping.
    """
    tool_name = _require_name(name, "tool name")
    params = {"name": tool_name, "arguments": _coerce_arguments(arguments)}
    return await _invoke(
        url,
        TOOL_CALL,
        params,
        target=tool_name,
        headers=headers,
        client=client,
        allow_insecure_http=allow_insecure_http,
        allow_private_network=allow_private_network,
        timeout=timeout,
    )


async def read_resource(
    url: str,
    uri: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    allow_insecure_http: bool = False,
    allow_private_network: bool = False,
    timeout: float = 30.0,
) -> InvocationResult:
    """Read a resource (``resources/read``) and capture its contents + latency.

    Unlike a tool, a resource read has no tool-level ``isError`` channel: a missing or
    unreadable resource surfaces as a JSON-RPC error (``completed=False``). A successful
    read returns the resource ``contents`` array.

    Args:
        url: The MCP endpoint (``…/mcp``).
        uri: The resource URI to read; must be a non-empty string.
        headers: Auth headers to attach to every request; empty for anonymous.
        client: An existing httpx ``AsyncClient`` (tests); transport owns one otherwise.
        allow_insecure_http: Permit plaintext ``http://`` to non-loopback hosts.
        allow_private_network: Permit an endpoint whose host is a private IP literal.
        timeout: Per-request timeout in seconds (ignored when ``client`` is supplied).

    Returns:
        The :class:`InvocationResult` for the read.

    Raises:
        ValueError: ``uri`` is empty.
    """
    resource_uri = _require_name(uri, "resource uri")
    return await _invoke(
        url,
        RESOURCE_READ,
        {"uri": resource_uri},
        target=resource_uri,
        headers=headers,
        client=client,
        allow_insecure_http=allow_insecure_http,
        allow_private_network=allow_private_network,
        timeout=timeout,
    )


async def get_prompt(
    url: str,
    name: str,
    arguments: Optional[Mapping[str, Any]] = None,
    *,
    headers: Optional[Mapping[str, str]] = None,
    client: Optional[httpx.AsyncClient] = None,
    allow_insecure_http: bool = False,
    allow_private_network: bool = False,
    timeout: float = 30.0,
) -> InvocationResult:
    """Fetch a prompt (``prompts/get``) and capture its messages + latency.

    Like a resource read, a prompt fetch has no ``isError`` channel: an unknown prompt
    or bad argument is a JSON-RPC error (``completed=False``). A successful fetch returns
    the prompt ``messages`` array (the ``description`` is preserved on ``raw_result``).

    Args:
        url: The MCP endpoint (``…/mcp``).
        name: The prompt name to fetch; must be a non-empty string.
        arguments: The prompt arguments object; defaults to ``{}`` when omitted.
        headers: Auth headers to attach to every request; empty for anonymous.
        client: An existing httpx ``AsyncClient`` (tests); transport owns one otherwise.
        allow_insecure_http: Permit plaintext ``http://`` to non-loopback hosts.
        allow_private_network: Permit an endpoint whose host is a private IP literal.
        timeout: Per-request timeout in seconds (ignored when ``client`` is supplied).

    Returns:
        The :class:`InvocationResult` for the fetch.

    Raises:
        ValueError: ``name`` is empty, or ``arguments`` is not a mapping.
    """
    prompt_name = _require_name(name, "prompt name")
    params = {"name": prompt_name, "arguments": _coerce_arguments(arguments)}
    return await _invoke(
        url,
        PROMPT_GET,
        params,
        target=prompt_name,
        headers=headers,
        client=client,
        allow_insecure_http=allow_insecure_http,
        allow_private_network=allow_private_network,
        timeout=timeout,
    )


# ===========================================================================
# Core invocation
# ===========================================================================


async def _invoke(
    url: str,
    spec: InvocationMethod,
    params: Dict[str, Any],
    *,
    target: str,
    headers: Optional[Mapping[str, str]],
    client: Optional[httpx.AsyncClient],
    allow_insecure_http: bool,
    allow_private_network: bool,
    timeout: float,
) -> InvocationResult:
    """Connect, handshake, invoke one method, and classify the outcome with latency.

    The single code path behind the three public helpers. It measures wall-clock from
    just before the connection through the invocation response, always closing the
    transport (best-effort session ``DELETE``) in a ``finally``. Every remote failure —
    transport, handshake, or a JSON-RPC error result — is turned into a
    ``completed=False`` :class:`InvocationResult` rather than propagating, so the caller
    always gets a latency-bearing result; only a programming error (bad arguments,
    already raised before this point) escapes.

    Args:
        url: The MCP endpoint.
        spec: The :class:`InvocationMethod` being invoked.
        params: The JSON-RPC params for the call.
        target: The human-facing invocation target (tool/prompt name or resource URI).
        headers: Auth headers for every request (or ``None``).
        client: An injected httpx client (tests) or ``None`` to let the transport own one.
        allow_insecure_http: Permit plaintext ``http://`` to non-loopback hosts.
        allow_private_network: Permit a private-IP endpoint host.
        timeout: Per-request timeout (ignored when ``client`` is given).

    Returns:
        The :class:`InvocationResult` describing the outcome.
    """
    start = perf_counter()
    transport: Optional[StreamableHttpTransport] = None
    try:
        transport = StreamableHttpTransport(
            url,
            headers=dict(headers) if headers else {},
            client=client,
            timeout=timeout,
            allow_insecure_http=allow_insecure_http,
            allow_private_network=allow_private_network,
        )
        await initialize_session(transport)
        response = await transport.request(spec.method, params)
        latency_ms = _elapsed_ms(start)
        if response.is_error:
            return _jsonrpc_failure(spec, target, response.error, latency_ms)
        return _completed_result(spec, target, response.result, latency_ms)
    except Exception as exc:  # noqa: BLE001 - mapped to the stable taxonomy below
        latency_ms = _elapsed_ms(start)
        error = classify_exception(exc)
        logger.info(
            "mcp invocation failed: method=%s target=%s error=%s",
            spec.method,
            target,
            error.code.value,
        )
        return InvocationResult(
            method=spec.method,
            target=target,
            completed=False,
            latency_ms=latency_ms,
            error=error,
        )
    finally:
        if transport is not None:
            await transport.aclose()


def _completed_result(
    spec: InvocationMethod,
    target: str,
    result: Any,
    latency_ms: float,
) -> InvocationResult:
    """Build the result for a call that returned a JSON-RPC *result* (success or tool error).

    Extracts the content array under the method's ``content_key`` and, for ``tools/call``,
    the ``isError`` flag and optional ``structuredContent``. A non-object result (a
    spec-violating server) is treated as an empty completed call rather than a crash.
    """
    result_obj = result if isinstance(result, Mapping) else {}
    is_error = spec.supports_is_error and bool(result_obj.get("isError"))
    structured = result_obj.get("structuredContent") if spec.method == TOOL_CALL.method else None
    return InvocationResult(
        method=spec.method,
        target=target,
        completed=True,
        latency_ms=latency_ms,
        is_error=is_error,
        content=_extract_content(result_obj, spec.content_key),
        structured_content=dict(structured) if isinstance(structured, Mapping) else None,
        raw_result=dict(result_obj),
    )


def _jsonrpc_failure(
    spec: InvocationMethod,
    target: str,
    error: Any,
    latency_ms: float,
) -> InvocationResult:
    """Build a ``completed=False`` result for a top-level JSON-RPC *error* response.

    This is a *protocol* failure (unknown tool, invalid params, server-side error) —
    distinct from a tool-level ``isError`` result — and is classified into the shared
    :attr:`DiscoveryErrorCode.JSONRPC_ERROR` bucket with the method/code/data preserved,
    mirroring how the discovery layer records a list method's JSON-RPC error.
    """
    code = getattr(error, "code", 0)
    message = getattr(error, "message", "") or "JSON-RPC error"
    discovery_error = DiscoveryError(
        DiscoveryErrorCode.JSONRPC_ERROR,
        f"{spec.method} failed: JSON-RPC error {code}: {message}",
        detail={
            "method": spec.method,
            "code": code,
            "data": _json_safe(getattr(error, "data", None)),
        },
    )
    return InvocationResult(
        method=spec.method,
        target=target,
        completed=False,
        latency_ms=latency_ms,
        error=discovery_error,
    )


# ===========================================================================
# Helpers
# ===========================================================================


def _require_name(value: str, label: str) -> str:
    """Return ``value`` if it is a non-empty/non-blank string, else raise ``ValueError``.

    Guards a programming error at the call boundary (an empty tool name, a blank URI)
    so it fails loudly here rather than producing a meaningless ``tools/call`` against
    the remote server.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _coerce_arguments(arguments: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a plain dict of call arguments, defaulting ``None`` to ``{}``.

    Raises ``ValueError`` for a non-mapping so a caller passing the wrong shape (a list,
    a string) is corrected at the boundary rather than sending invalid JSON-RPC params.
    """
    if arguments is None:
        return {}
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments must be a mapping (object) or None")
    return dict(arguments)


def _extract_content(result: Mapping[str, Any], content_key: str) -> Tuple[Dict[str, Any], ...]:
    """Return the result's content array under ``content_key`` as a tuple of objects.

    Non-object entries are dropped defensively (the spec requires each content block /
    resource content / message to be a JSON object), and an absent or non-array value
    yields an empty tuple, so a malformed payload never raises here.
    """
    raw = result.get(content_key)
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(dict(item) for item in raw if isinstance(item, Mapping))


def _json_safe(value: Any) -> Any:
    """Coerce a JSON-RPC ``data`` payload to something JSON-serializable for the record.

    Returns the value unchanged when it round-trips through JSON; otherwise its ``repr``,
    so persisting/serializing the classified error never raises on an exotic payload.
    """
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _elapsed_ms(start: float) -> float:
    """Milliseconds elapsed since ``start`` (a :func:`time.perf_counter` reading)."""
    return (perf_counter() - start) * 1000.0
