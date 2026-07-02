"""Discovery error taxonomy & resilience (V2-MCP-16.6, #3662).

Remote MCP discovery fails in many ways — a connection times out, TLS can't be
verified, the server demands authentication, a JSON-RPC call errors, no protocol
version is mutually supported, a paginated list aborts part-way through, the URL
points at a private address, or the whole job outruns its time budget. For the
catalog to be *trustworthy and diagnosable* every one of those must map to a
**stable error code** that can be persisted on ``mcp_discovery_jobs.error`` and
reasoned about long after the run.

This module is that mapping. :class:`DiscoveryErrorCode` enumerates the stable
codes; :class:`DiscoveryError` is the structured, serializable outcome stored on
a failed job; :func:`classify_exception` turns any exception raised by the
transport / handshake / discovery / resilience layers into one of those codes
without the caller having to know the exception hierarchy.

Two invariants this taxonomy exists to uphold (the ticket's acceptance criteria):

* **No silent partial success.** A pagination abort
  (:class:`~app.mcp_client.discovery.McpPaginationError`) or a budget timeout in
  the middle of enumeration carries :attr:`DiscoveryError.partial` ``True``, so a
  job that only saw *part* of a server's surface is never recorded as complete.
* **SSRF is a first-class, named failure.** A blocked private-address target
  surfaces as :attr:`DiscoveryErrorCode.SSRF_BLOCKED` rather than a vague
  transport error.

It depends only on the exception types defined by its sibling modules and on the
standard library, so persisting/inspecting a :class:`DiscoveryError` never drags
in the network stack.
"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, Mapping, Optional

import httpx

from .discovery import McpDiscoveryError, McpPaginationError
from .handshake import McpVersionNegotiationError
from .resilience import BudgetExceededError
from .transport_http import (
    McpAuthRequiredError,
    McpHttpStatusError,
    McpProtocolError,
    McpRateLimitedError,
    McpSessionExpiredError,
    McpSsrfError,
    McpTransportError,
)

# ===========================================================================
# Stable error codes
# ===========================================================================


class DiscoveryErrorCode(StrEnum):
    """Stable, persisted classification of a discovery failure.

    These string values are written into ``mcp_discovery_jobs.error`` and are part
    of the data contract: **never rename a member's value**; add new ones. Each
    maps one observable failure mode the discovery pipeline must distinguish.
    """

    # Network establishment / timing.
    CONNECT_TIMEOUT = "connect_timeout"  # TCP/connect phase exceeded the timeout.
    TIMEOUT = "timeout"  # read/write/pool timeout after a connection was made.
    CONNECT_ERROR = "connect_error"  # connection refused/reset/DNS failure, no TLS.
    TLS_ERROR = "tls_error"  # TLS handshake/certificate verification failed.

    # Application-level HTTP / MCP signalling.
    AUTH_REQUIRED = "auth_required"  # 401 + WWW-Authenticate challenge.
    RATE_LIMITED = "rate_limited"  # 429 Too Many Requests (may carry a Retry-After).
    SESSION_EXPIRED = "session_expired"  # 404 to a request carrying a session id.
    HTTP_STATUS = "http_status"  # any other rejected HTTP status (400/405/5xx…).

    # JSON-RPC / protocol semantics.
    JSONRPC_ERROR = "jsonrpc_error"  # a declared list method returned a JSON-RPC error.
    VERSION_MISMATCH = "version_mismatch"  # no mutually supported protocol version.
    PROTOCOL_ERROR = "protocol_error"  # malformed/unexpected Streamable-HTTP reply.
    PARTIAL_PAGE = "partial_page"  # pagination aborted (cycle / page-limit); partial surface.

    # Resilience guards.
    SSRF_BLOCKED = "ssrf_blocked"  # endpoint host is a blocked private address.
    BUDGET_EXCEEDED = "budget_exceeded"  # job outran its total wall-clock budget.

    # Fallback.
    UNKNOWN = "unknown"  # an exception the taxonomy does not (yet) recognize.


# ===========================================================================
# Structured failure record
# ===========================================================================


@dataclass(frozen=True)
class DiscoveryError:
    """A structured, serializable discovery failure for the job record.

    Produced by :func:`classify_exception`. Its :meth:`to_record` JSON is what a
    job runner writes to ``mcp_discovery_jobs.error``; :attr:`code` is the stable
    classification callers branch on.

    Attributes:
        code: The stable :class:`DiscoveryErrorCode`.
        message: A human-readable summary (the exception's own message).
        partial: ``True`` when the failure happened *after* some of the server's
            surface had already been enumerated, so the discovery is incomplete
            and must not be recorded as a complete run.
        detail: Code-specific structured fields preserved for diagnosis (e.g. the
            failing ``method`` and JSON-RPC ``code``, the ``www_authenticate``
            challenge, the negotiated/supported versions). Always JSON-safe.
    """

    code: DiscoveryErrorCode
    message: str
    partial: bool = False
    detail: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serializable dict of this error."""
        return {
            "code": self.code.value,
            "message": self.message,
            "partial": self.partial,
            "detail": dict(self.detail),
        }

    def to_record(self) -> str:
        """Serialize to the JSON string stored on ``mcp_discovery_jobs.error``.

        Keys are sorted for stable, diff-friendly persistence.
        """
        return json.dumps(self.as_dict(), sort_keys=True, default=str)


# ===========================================================================
# Classification
# ===========================================================================


def classify_exception(exc: BaseException) -> DiscoveryError:
    """Map any discovery exception to a stable :class:`DiscoveryError`.

    Resolves the exception against the taxonomy most-specific-first (so, e.g.,
    :class:`McpAuthRequiredError` and :class:`McpRateLimitedError` are recognized
    before their :class:`McpHttpStatusError` base, and :class:`McpPaginationError`
    before its :class:`McpDiscoveryError` base). Anything unrecognized becomes
    :attr:`DiscoveryErrorCode.UNKNOWN` rather than raising, so a job runner can
    always persist *something* explanatory.

    Args:
        exc: The exception raised while running discovery.

    Returns:
        The classified :class:`DiscoveryError`, ready to store on the job record.
    """
    message = str(exc) or exc.__class__.__name__

    # --- Resilience guards (plain exceptions, checked first) ----------------
    if isinstance(exc, McpSsrfError):
        return DiscoveryError(
            DiscoveryErrorCode.SSRF_BLOCKED,
            message,
            detail={"host": exc.host, "reason": exc.reason},
        )
    if isinstance(exc, BudgetExceededError):
        return DiscoveryError(
            DiscoveryErrorCode.BUDGET_EXCEEDED,
            message,
            partial=True,
            detail={"elapsed": exc.elapsed, "total": exc.total},
        )

    # --- Protocol / JSON-RPC semantics (most-derived first) -----------------
    if isinstance(exc, McpVersionNegotiationError):
        return DiscoveryError(
            DiscoveryErrorCode.VERSION_MISMATCH,
            message,
            detail={
                "server_version": exc.server_version,
                "client_supported": list(exc.client_supported),
                "server_supported": (
                    list(exc.server_supported) if exc.server_supported is not None else None
                ),
            },
        )
    if isinstance(exc, McpPaginationError):
        # A list endpoint aborted mid-stream: the surface is incomplete.
        return DiscoveryError(
            DiscoveryErrorCode.PARTIAL_PAGE,
            message,
            partial=True,
            detail={
                "method": exc.method,
                "pages": exc.pages,
                "items_so_far": exc.items_so_far,
            },
        )
    if isinstance(exc, McpDiscoveryError):
        return DiscoveryError(
            DiscoveryErrorCode.JSONRPC_ERROR,
            message,
            detail={"method": exc.method, "code": exc.code, "data": _json_safe(exc.data)},
        )

    # --- HTTP status family (most-derived first) ----------------------------
    if isinstance(exc, McpAuthRequiredError):
        return DiscoveryError(
            DiscoveryErrorCode.AUTH_REQUIRED,
            message,
            detail={"status": exc.status_code, "www_authenticate": exc.www_authenticate},
        )
    if isinstance(exc, McpRateLimitedError):
        return DiscoveryError(
            DiscoveryErrorCode.RATE_LIMITED,
            message,
            detail={"status": exc.status_code, "retry_after": exc.retry_after},
        )
    if isinstance(exc, McpSessionExpiredError):
        return DiscoveryError(
            DiscoveryErrorCode.SESSION_EXPIRED,
            message,
            detail={"status": exc.status_code, "session_id": exc.session_id},
        )
    if isinstance(exc, McpHttpStatusError):
        return DiscoveryError(
            DiscoveryErrorCode.HTTP_STATUS,
            message,
            detail={"status": exc.status_code},
        )

    # McpProtocolError is the base of the JSON-RPC errors handled above, so any
    # left here is a genuine malformed-reply / transport-protocol failure.
    if isinstance(exc, McpProtocolError):
        return DiscoveryError(DiscoveryErrorCode.PROTOCOL_ERROR, message)

    # --- httpx network errors (timing / TLS / connect) ----------------------
    if isinstance(exc, httpx.HTTPError):
        return _classify_httpx(exc, message)

    # A bare TLS error (not wrapped by httpx) is still a TLS failure.
    if _is_tls_error(exc):
        return DiscoveryError(DiscoveryErrorCode.TLS_ERROR, message)

    # McpTransportError base (e.g. an unsupported URL scheme) → protocol bucket.
    if isinstance(exc, McpTransportError):
        return DiscoveryError(DiscoveryErrorCode.PROTOCOL_ERROR, message)

    return DiscoveryError(DiscoveryErrorCode.UNKNOWN, message)


def _classify_httpx(exc: httpx.HTTPError, message: str) -> DiscoveryError:
    """Classify an ``httpx`` transport/timeout error into the taxonomy.

    TLS verification failures surface in httpx as a :class:`httpx.ConnectError`
    whose cause is an :class:`ssl.SSLError`, so a TLS check precedes the generic
    connect bucket. Timeouts split connect-phase from later read/write/pool
    timeouts because the former usually means an unreachable host.
    """
    if _is_tls_error(exc):
        return DiscoveryError(DiscoveryErrorCode.TLS_ERROR, message)
    if isinstance(exc, httpx.ConnectTimeout):
        return DiscoveryError(DiscoveryErrorCode.CONNECT_TIMEOUT, message)
    if isinstance(exc, httpx.TimeoutException):
        return DiscoveryError(DiscoveryErrorCode.TIMEOUT, message)
    if isinstance(exc, httpx.ConnectError):
        return DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, message)
    # Any other request/transport error (reads, protocol, proxy…): connect bucket.
    return DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, message)


def _is_tls_error(exc: BaseException) -> bool:
    """True when ``exc`` is, or was caused by, an :class:`ssl.SSLError`.

    Walks the ``__cause__``/``__context__`` chain because httpx wraps the
    underlying ``ssl`` failure (e.g. certificate verification) in a
    :class:`httpx.ConnectError`.
    """
    seen: set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ssl.SSLError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _json_safe(value: Any) -> Any:
    """Coerce a JSON-RPC ``data`` payload to something ``json.dumps`` accepts.

    Returns the value unchanged when it already round-trips through JSON;
    otherwise falls back to its ``repr`` so persisting the record never raises.
    """
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)
