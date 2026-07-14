"""End-to-end capture tests for MCP conformance (CLX-3.1, #4855).

Where :mod:`tests.test_mcp_protocol_transcript` unit-tests the recorder against hand-built
envelopes, these drive the **real** client stack — :class:`StreamableHttpTransport` performing an
actual handshake and a real paginated discovery against a scripted MCP server — and assert that
the transcript captured along the way produces the conformance findings it should.

That distinction matters, because the MCP client is itself a strict protocol enforcer: a malformed
envelope, a bad ``jsonrpc`` version, a cursor cycle, or an errored list method each abort discovery
outright, before any surface exists to lint. A defect can only become a *finding* if the client
tolerates it. These tests pin exactly that boundary — the defects that survive discovery and reach
the conformance engine — so a future change to the client's strictness cannot silently turn a
reachable rule into one that can never fire (and would therefore report "pass" forever).
"""

from __future__ import annotations

import json
from typing import Any, Dict

import httpx
import pytest

from app.mcp_client.discovery import discover_listings
from app.mcp_client.handshake import initialize_session
from app.mcp_client.normalize import DiscoverySurface
from app.mcp_client.transport_http import StreamableHttpTransport
from app.mcp_conformance import PROFILE_PROTOCOL, ConformanceContext, run_conformance
from app.mcp_protocol_transcript import TranscriptRecorder

ENDPOINT = "https://example.com/mcp"

#: A cursor whose literal value must never appear in the persisted transcript.
SECRET_CURSOR = "cursor-carrying-a-private-query-abc123"


def _rpc(rpc_id: Any, result: Dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": rpc_id, "result": result})


async def _discover(handler):
    """Drive the real transport + handshake + discovery against ``handler``, capturing a transcript.

    Returns ``(surface, transcript)`` exactly as :func:`app.mcp_discovery_engine._run_mcp_client`
    would produce them in production.
    """
    recorder = TranscriptRecorder()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = StreamableHttpTransport(ENDPOINT, client=client, transcript=recorder)
    try:
        initialize = await initialize_session(transport)
        listings = await discover_listings(transport, initialize.capabilities)
    finally:
        await transport.aclose()
    return DiscoverySurface.from_discovery(initialize, listings), recorder.transcript()


def _misbehaving_server(request: httpx.Request) -> httpx.Response:
    """A server that exhibits every protocol defect the MCP client tolerates.

    Deliberately *not* the defects the client hard-fails on (bad envelopes, cursor cycles, errored
    list methods) — those never produce a surface, so they are unreachable by design.
    """
    if request.method == "DELETE":
        return httpx.Response(200)
    body = json.loads(request.content)
    if "id" not in body:  # a notification
        return httpx.Response(202)

    method, rpc_id = body["method"], body["id"]

    if method == "initialize":
        return _rpc(
            rpc_id,
            {
                "protocolVersion": "2025-03-26",  # downgrade from the offered 2025-06-18
                "serverInfo": {"name": "demo"},  # no version
                "capabilities": {"tools": {}, "prompts": {}},  # prompts declared, none listed
            },
        )

    if method == "tools/list":
        cursor = (body.get("params") or {}).get("cursor")
        if cursor is None:
            # An empty first page that still promises another: a wasted round trip.
            return _rpc(rpc_id, {"tools": [], "nextCursor": SECRET_CURSOR})
        # A response that never echoes the request id — the one envelope defect the client allows.
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 9999,
                "result": {
                    "tools": [
                        {
                            "name": "search_items",
                            "description": "Search.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"q": {"type": "string"}},
                            },
                        }
                    ]
                },
            },
        )

    if method == "prompts/list":
        return _rpc(rpc_id, {})  # result with no item array at all

    return _rpc(rpc_id, {})


def _healthy_server(request: httpx.Request) -> httpx.Response:
    """A fully conformant server: honoured version, complete identity, matched capabilities."""
    if request.method == "DELETE":
        return httpx.Response(200)
    body = json.loads(request.content)
    if "id" not in body:
        return httpx.Response(202)

    method, rpc_id = body["method"], body["id"]
    if method == "initialize":
        return _rpc(
            rpc_id,
            {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "demo", "version": "1.4.2"},
                "capabilities": {"tools": {}},
            },
        )
    if method == "tools/list":
        return _rpc(rpc_id, {"tools": [{"name": "search_items"}]})
    return _rpc(rpc_id, {})


# --- Capture ---------------------------------------------------------------------------------------


async def test_transcript_is_captured_during_ordinary_discovery():
    """A recorder on the transport observes the handshake and every list page — with no extra calls.

    Capture is purely observational: it records the exchanges discovery was already going to make.
    """
    _, transcript = await _discover(_healthy_server)

    methods = [exchange.method for exchange in transcript.exchanges]
    assert methods[0] == "initialize"
    assert "tools/list" in methods
    # The client only queries a declared capability, so an undeclared one is never even requested.
    assert "prompts/list" not in methods
    assert transcript.negotiated_version == "2025-06-18"


async def test_captured_transcript_never_contains_a_raw_cursor():
    """Redaction holds on the real path: the opaque cursor is stored only as a digest.

    A ``nextCursor`` is server-defined and may encode a private query, so the persisted evidence
    must not be able to reveal it.
    """
    _, transcript = await _discover(_misbehaving_server)

    serialized = json.dumps(transcript.as_dict())
    assert SECRET_CURSOR not in serialized
    assert transcript.as_dict()["redacted"] is True

    # …but the digest is still present, which is what keeps cursor equality checkable.
    tools_pages = transcript.for_method("tools/list")
    assert any(page.next_cursor for page in tools_pages)


# --- Findings from a real session ---------------------------------------------------------------------


async def test_real_session_defects_become_conformance_findings():
    """Every protocol defect the client tolerates is caught by the conformance engine end-to-end."""
    surface, transcript = await _discover(_misbehaving_server)

    report = run_conformance(
        ConformanceContext(surface=surface, transcript=transcript),
        profile=PROFILE_PROTOCOL,
        fail_on="error",
    )
    rules = {finding.rule for finding in report.findings}

    # Surface-derived (deterministic, recomputable from the database):
    assert "protocol.missing-server-version" in rules
    assert "protocol.declared-capability-empty" in rules  # prompts declared, none listed
    # Transcript-derived (only observable on the wire):
    assert "protocol.protocol-version-downgraded" in rules
    assert "protocol.response-id-not-echoed" in rules
    assert "protocol.empty-page-with-next-cursor" in rules
    assert "protocol.list-result-missing-items" in rules

    assert report.transcript_captured is True
    assert report.skipped_rules == ()
    assert report.gate.passed is False  # the id-echo and item-array defects are errors


async def test_a_conformant_server_produces_a_clean_gated_report():
    """A well-behaved server passes the protocol gate outright, with a full-marks score."""
    surface, transcript = await _discover(_healthy_server)

    report = run_conformance(
        ConformanceContext(surface=surface, transcript=transcript),
        profile=PROFILE_PROTOCOL,
        fail_on="info",
    )

    assert report.findings == ()
    assert report.score == 100
    assert report.gate.passed is True


async def test_recompute_without_the_transcript_skips_the_wire_only_rules():
    """The same surface, re-linted from the database alone, cannot claim the wire-only rules passed.

    This is the determinism/honesty split in one assertion: the surface-derived findings survive a
    transcript-less recompute unchanged, while every transcript-derived finding disappears — and
    its rule is reported as *skipped*, not as passing.
    """
    surface, transcript = await _discover(_misbehaving_server)

    with_transcript = run_conformance(
        ConformanceContext(surface=surface, transcript=transcript), profile=PROFILE_PROTOCOL
    )
    without = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_PROTOCOL)

    wire_only = {"protocol.response-id-not-echoed", "protocol.list-result-missing-items"}
    assert wire_only <= {f.rule for f in with_transcript.findings}
    assert not (wire_only & {f.rule for f in without.findings})
    assert wire_only <= set(without.skipped_rules)

    # The deterministic half is identical either way.
    surface_derived = {"protocol.missing-server-version", "protocol.declared-capability-empty"}
    assert surface_derived <= {f.rule for f in without.findings}


async def test_tools_call_is_never_issued_during_discovery():
    """Passive by construction: conformance capture never invokes a business tool.

    The recorder's allow-list would raise on ``tools/call``, but this asserts the stronger, more
    direct property — no such request is ever put on the wire in the first place.
    """
    seen: list = []

    def _recording_server(request: httpx.Request) -> httpx.Response:
        if request.method != "DELETE":
            body = json.loads(request.content)
            seen.append(body.get("method"))
        return _healthy_server(request)

    await _discover(_recording_server)

    assert "tools/call" not in seen
    assert "resources/read" not in seen
    assert "prompts/get" not in seen
    assert set(seen) <= {
        "initialize",
        "notifications/initialized",
        "tools/list",
    }


@pytest.mark.parametrize(
    "handler,expected_pass",
    [(_healthy_server, True), (_misbehaving_server, False)],
)
async def test_gate_decides_from_a_real_session(handler, expected_pass):
    """The gate — the thing CI acts on — reflects the server's real observed behaviour."""
    surface, transcript = await _discover(handler)
    report = run_conformance(
        ConformanceContext(surface=surface, transcript=transcript),
        profile=PROFILE_PROTOCOL,
        fail_on="error",
    )
    assert report.gate.passed is expected_pass
