"""Unit tests for the MCP discovery error taxonomy (V2-MCP-16.6, #3662).

Drives :func:`app.mcp_client.errors.classify_exception` across every failure mode
the discovery pipeline must distinguish — SSRF block, time-budget timeout,
version mismatch, partial pagination, JSON-RPC error, auth-required, session
expiry, other HTTP statuses, protocol errors, the httpx timing/TLS/connect
family, and an unknown fallback — and checks the two invariants the ticket exists
to enforce: stable persisted codes, and ``partial`` set whenever a run saw only
part of a server's surface (so it is never silently recorded as complete).
"""

import json
import ssl

import httpx

from app.mcp_client.discovery import McpDiscoveryError, McpPaginationError
from app.mcp_client.errors import (
    DiscoveryError,
    DiscoveryErrorCode,
    classify_exception,
)
from app.mcp_client.handshake import McpVersionNegotiationError
from app.mcp_client.resilience import BudgetExceededError
from app.mcp_client.transport_http import (
    McpAuthRequiredError,
    McpHttpStatusError,
    McpProtocolError,
    McpSessionExpiredError,
    McpSsrfError,
    McpTransportError,
)

# ===========================================================================
# DiscoveryError value object
# ===========================================================================


def test_discovery_error_serializes_to_stable_json():
    err = DiscoveryError(
        DiscoveryErrorCode.JSONRPC_ERROR,
        "tools/list failed",
        detail={"method": "tools/list", "code": -32000},
    )
    record = err.to_record()
    # to_record() is the exact string persisted to mcp_discovery_jobs.error.
    assert json.loads(record) == {
        "code": "jsonrpc_error",
        "message": "tools/list failed",
        "partial": False,
        "detail": {"method": "tools/list", "code": -32000},
    }
    # Keys are sorted for diff-friendly storage.
    assert record.index('"code"') < record.index('"detail"') < record.index('"message"')


def test_error_codes_are_stable_strings():
    # These values are a persisted contract; guard against accidental renames.
    assert DiscoveryErrorCode.SSRF_BLOCKED == "ssrf_blocked"
    assert DiscoveryErrorCode.PARTIAL_PAGE == "partial_page"
    assert DiscoveryErrorCode.VERSION_MISMATCH == "version_mismatch"
    assert DiscoveryErrorCode.BUDGET_EXCEEDED == "budget_exceeded"


# ===========================================================================
# classify_exception — resilience guards
# ===========================================================================


def test_classify_ssrf_block():
    err = classify_exception(McpSsrfError("169.254.169.254", "link-local"))
    assert err.code is DiscoveryErrorCode.SSRF_BLOCKED
    assert err.partial is False
    assert err.detail == {"host": "169.254.169.254", "reason": "link-local"}


def test_classify_budget_exceeded_is_partial():
    err = classify_exception(BudgetExceededError(elapsed=130.0, total=120.0))
    assert err.code is DiscoveryErrorCode.BUDGET_EXCEEDED
    # Timing out mid-run means the surface is incomplete.
    assert err.partial is True
    assert err.detail == {"elapsed": 130.0, "total": 120.0}


# ===========================================================================
# classify_exception — protocol / JSON-RPC semantics
# ===========================================================================


def test_classify_version_mismatch_carries_negotiation_detail():
    exc = McpVersionNegotiationError(
        "no common version",
        server_version="2024-01-01",
        client_supported=("2025-06-18", "2025-03-26"),
        server_supported=("2024-01-01",),
    )
    err = classify_exception(exc)
    assert err.code is DiscoveryErrorCode.VERSION_MISMATCH
    assert err.detail == {
        "server_version": "2024-01-01",
        "client_supported": ["2025-06-18", "2025-03-26"],
        "server_supported": ["2024-01-01"],
    }


def test_classify_pagination_is_partial_page():
    exc = McpPaginationError("tools/list", "cursor cycle", pages=3, items_so_far=7)
    err = classify_exception(exc)
    assert err.code is DiscoveryErrorCode.PARTIAL_PAGE
    assert err.partial is True
    assert err.detail == {"method": "tools/list", "pages": 3, "items_so_far": 7}


def test_classify_jsonrpc_error_after_pagination_specificity():
    # McpPaginationError subclasses McpDiscoveryError; the more specific code wins.
    exc = McpDiscoveryError("prompts/list", -32000, "boom", data={"k": "v"})
    err = classify_exception(exc)
    assert err.code is DiscoveryErrorCode.JSONRPC_ERROR
    assert err.partial is False
    assert err.detail == {"method": "prompts/list", "code": -32000, "data": {"k": "v"}}


def test_classify_jsonrpc_error_with_unserializable_data():
    exc = McpDiscoveryError("tools/list", -1, "bad", data=object())
    err = classify_exception(exc)
    # data is coerced to a repr so the record always serializes.
    assert isinstance(err.detail["data"], str)
    json.loads(err.to_record())  # must not raise


def test_classify_protocol_error():
    err = classify_exception(McpProtocolError("malformed SSE"))
    assert err.code is DiscoveryErrorCode.PROTOCOL_ERROR


# ===========================================================================
# classify_exception — HTTP status family
# ===========================================================================


def test_classify_auth_required_keeps_challenge():
    exc = McpAuthRequiredError("nope", www_authenticate='Bearer realm="mcp"')
    err = classify_exception(exc)
    assert err.code is DiscoveryErrorCode.AUTH_REQUIRED
    assert err.detail == {"status": 401, "www_authenticate": 'Bearer realm="mcp"'}


def test_classify_session_expired():
    err = classify_exception(McpSessionExpiredError("sess-9", "gone"))
    assert err.code is DiscoveryErrorCode.SESSION_EXPIRED
    assert err.detail == {"status": 404, "session_id": "sess-9"}


def test_classify_generic_http_status():
    err = classify_exception(McpHttpStatusError(503, "overloaded"))
    assert err.code is DiscoveryErrorCode.HTTP_STATUS
    assert err.detail == {"status": 503}


def test_unsupported_scheme_transport_error_is_protocol():
    # A bare McpTransportError (e.g. unsupported scheme) falls to the protocol bucket.
    err = classify_exception(McpTransportError("unsupported URL scheme"))
    assert err.code is DiscoveryErrorCode.PROTOCOL_ERROR


# ===========================================================================
# classify_exception — httpx timing / TLS / connect family
# ===========================================================================


def test_classify_connect_timeout():
    err = classify_exception(httpx.ConnectTimeout("connect timed out"))
    assert err.code is DiscoveryErrorCode.CONNECT_TIMEOUT


def test_classify_read_timeout_is_generic_timeout():
    err = classify_exception(httpx.ReadTimeout("read timed out"))
    assert err.code is DiscoveryErrorCode.TIMEOUT


def test_classify_connect_error():
    err = classify_exception(httpx.ConnectError("connection refused"))
    assert err.code is DiscoveryErrorCode.CONNECT_ERROR


def test_classify_tls_error_wrapped_by_httpx():
    # httpx surfaces a TLS verification failure as a ConnectError caused by SSLError.
    wrapped = httpx.ConnectError("connect failed")
    wrapped.__cause__ = ssl.SSLCertVerificationError("certificate verify failed")
    err = classify_exception(wrapped)
    assert err.code is DiscoveryErrorCode.TLS_ERROR


def test_classify_bare_ssl_error():
    err = classify_exception(ssl.SSLError("handshake failure"))
    assert err.code is DiscoveryErrorCode.TLS_ERROR


# ===========================================================================
# classify_exception — fallback
# ===========================================================================


def test_classify_unknown_exception():
    err = classify_exception(RuntimeError("something odd"))
    assert err.code is DiscoveryErrorCode.UNKNOWN
    assert err.message == "something odd"


def test_classify_exception_with_empty_message_uses_class_name():
    err = classify_exception(RuntimeError())
    assert err.message == "RuntimeError"
