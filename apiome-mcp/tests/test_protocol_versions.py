"""Unit tests for the pinned protocol-version table and its ASGI gate (AAU-4.1, #5714).

The HTTP-level acceptance (the real app over Uvicorn) is in ``test_agent_self_conformance.py``; these
tests drive :class:`~apiome_mcp.protocol_version_gate.ProtocolVersionGateMiddleware` with hand-built
ASGI scopes, so every branch is exercised without a server.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS as SDK_SUPPORTED_VERSIONS

from apiome_mcp.protocol_version_gate import (
    PROTOCOL_VERSION_STATE_KEY,
    ProtocolVersionGateMiddleware,
    current_protocol_version,
    unsupported_version_body,
)
from apiome_mcp.protocol_versions import (
    ACCEPTED_PROTOCOL_VERSIONS,
    HANDSHAKE_PROTOCOL_VERSIONS,
    LATEST_HANDSHAKE_VERSION,
    LEGACY_DEFAULT_PROTOCOL_VERSION,
    SDK_WIRE_VERSION,
    SERVED_PROTOCOL_VERSIONS,
    UNSUPPORTED_PROTOCOL_VERSION_CODE,
    is_accepted_header_version,
    negotiate_handshake_version,
)

DOC = Path(__file__).resolve().parents[1] / "docs" / "PROTOCOL_VERSIONS.md"


# ============================================================================
# The table
# ============================================================================


def test_served_table_matches_the_issue() -> None:
    assert SERVED_PROTOCOL_VERSIONS == ("2026-07-28", "2025-11-25", "2025-06-18")
    assert LEGACY_DEFAULT_PROTOCOL_VERSION == "2025-03-26"
    assert "2024-11-05" not in ACCEPTED_PROTOCOL_VERSIONS
    assert HANDSHAKE_PROTOCOL_VERSIONS == ("2025-11-25", "2025-06-18", "2025-03-26")


def test_the_sdk_speaks_every_handshake_revision_we_serve() -> None:
    """Drift guard: an SDK change that drops a served revision fails here, not in a client."""
    assert set(HANDSHAKE_PROTOCOL_VERSIONS) <= set(SDK_SUPPORTED_VERSIONS)
    assert SDK_WIRE_VERSION in SDK_SUPPORTED_VERSIONS


def test_the_matrix_doc_lists_every_accepted_version() -> None:
    text = DOC.read_text(encoding="utf-8")
    for version in (*ACCEPTED_PROTOCOL_VERSIONS, "2024-11-05"):
        assert f"`{version}`" in text, version


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("2025-11-25", "2025-11-25"),
        ("2025-06-18", "2025-06-18"),
        ("2025-03-26", "2025-03-26"),
        ("2026-07-28", LATEST_HANDSHAKE_VERSION),
        ("2024-11-05", LATEST_HANDSHAKE_VERSION),
        ("not-a-version", LATEST_HANDSHAKE_VERSION),
        (20250618, LATEST_HANDSHAKE_VERSION),
        (None, LATEST_HANDSHAKE_VERSION),
    ],
)
def test_negotiate_handshake_version(requested: object, expected: str) -> None:
    assert negotiate_handshake_version(requested) == expected


@pytest.mark.parametrize("value", ACCEPTED_PROTOCOL_VERSIONS)
def test_accepted_header_versions(value: str) -> None:
    assert is_accepted_header_version(value)


@pytest.mark.parametrize("value", ["2024-11-05", "", " 2025-06-18", "2025-06-18 ", "latest"])
def test_refused_header_versions(value: str) -> None:
    assert not is_accepted_header_version(value)


def test_refusal_body_is_a_json_rpc_error_with_the_supported_list() -> None:
    body = unsupported_version_body("x" * 500)
    assert body["jsonrpc"] == "2.0" and body["id"] is None
    assert body["error"]["code"] == UNSUPPORTED_PROTOCOL_VERSION_CODE
    assert body["error"]["data"]["supported"] == list(ACCEPTED_PROTOCOL_VERSIONS)
    # A client-controlled value is never echoed back unbounded.
    assert body["error"]["data"]["requested"] == "x" * 64


# ============================================================================
# The ASGI gate
# ============================================================================


class _Recorder:
    """An ASGI app that records the scope it was handed and the version visible to it."""

    def __init__(self) -> None:
        self.scope: dict[str, Any] | None = None
        self.version: str | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.scope = scope
        self.version = current_protocol_version()


def _run(headers: list[tuple[bytes, bytes]], *, scope_type: str = "http") -> tuple[_Recorder, list[dict[str, Any]]]:
    inner = _Recorder()
    sent: list[dict[str, Any]] = []
    scope = {"type": scope_type, "headers": headers, "state": {"shared": 1}}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: Any) -> None:
        sent.append(message)

    asyncio.run(ProtocolVersionGateMiddleware(inner)(scope, receive, send))
    return inner, sent


def _header(scope: dict[str, Any]) -> list[bytes]:
    return [v for n, v in scope["headers"] if n == b"mcp-protocol-version"]


def test_absent_header_reads_as_the_legacy_default() -> None:
    inner, sent = _run([])
    assert sent == []
    assert inner.version == LEGACY_DEFAULT_PROTOCOL_VERSION
    assert inner.scope is not None and inner.scope["state"][PROTOCOL_VERSION_STATE_KEY] == "2025-03-26"


def test_handshake_header_passes_through_unchanged() -> None:
    inner, _ = _run([(b"mcp-protocol-version", b"2025-06-18")])
    assert inner.scope is not None
    assert _header(inner.scope) == [b"2025-06-18"]
    assert inner.scope["state"][PROTOCOL_VERSION_STATE_KEY] == "2025-06-18"


def test_modern_header_is_kept_for_audit_and_rewritten_for_the_sdk() -> None:
    inner, sent = _run([(b"MCP-Protocol-Version", b"2026-07-28")])
    assert sent == []
    assert inner.scope is not None
    assert _header(inner.scope) == [SDK_WIRE_VERSION.encode()]
    assert inner.scope["state"][PROTOCOL_VERSION_STATE_KEY] == "2026-07-28"
    assert inner.version == "2026-07-28"


def test_state_is_copied_not_mutated() -> None:
    inner, _ = _run([])
    assert inner.scope is not None and inner.scope["state"]["shared"] == 1


@pytest.mark.parametrize(
    "headers",
    [
        [(b"mcp-protocol-version", b"2024-11-05")],
        [(b"mcp-protocol-version", b"1999-01-01")],
        [(b"mcp-protocol-version", b"2025-06-18"), (b"mcp-protocol-version", b"2025-11-25")],
    ],
)
def test_unsupported_or_conflicting_headers_are_refused(headers: list[tuple[bytes, bytes]]) -> None:
    inner, sent = _run(headers)
    assert inner.scope is None, "a refused request must never reach the SDK"
    assert sent[0]["status"] == 400
    assert (b"content-type", b"application/json") in sent[0]["headers"]
    error = json.loads(sent[1]["body"])["error"]
    assert error["code"] == UNSUPPORTED_PROTOCOL_VERSION_CODE
    assert error["data"]["supported"] == list(ACCEPTED_PROTOCOL_VERSIONS)


def test_repeated_identical_headers_are_accepted() -> None:
    inner, sent = _run([(b"mcp-protocol-version", b"2025-11-25"), (b"mcp-protocol-version", b"2025-11-25")])
    assert sent == [] and inner.version == "2025-11-25"


def test_non_http_scopes_pass_through() -> None:
    inner, sent = _run([(b"mcp-protocol-version", b"bogus")], scope_type="lifespan")
    assert sent == [] and inner.scope is not None
