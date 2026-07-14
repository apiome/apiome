"""Unit tests for the redacted MCP protocol transcript (CLX-3.1, #4855).

These exercise :mod:`app.mcp_protocol_transcript`: the passive-only, redact-at-capture record of
the JSON-RPC exchanges discovery performs. Two of its guarantees are load-bearing for the whole
conformance feature and are tested here as properties rather than incidentally:

* **Passivity** — a non-passive method (notably ``tools/call``) cannot be recorded at all, so
  conformance evidence can never be the by-product of invoking a business tool.
* **Redaction** — nothing verbatim from the wire survives capture: no parameter values, no result
  items, no raw pagination cursors, and no credential-shaped text in an error message.

The end-to-end capture path (recorder attached to a live transport driving a real handshake and
paginated discovery) is covered in :mod:`tests.test_mcp_conformance_integration`.
"""

from __future__ import annotations

import pytest

from app.mcp_protocol_transcript import (
    JSONRPC_VERSION,
    LIST_METHODS,
    MAX_MESSAGE_CHARS,
    METHOD_INITIALIZE,
    PASSIVE_METHODS,
    REDACTED,
    PassiveMethodError,
    ProtocolTranscript,
    TranscriptRecorder,
    cursor_digest,
    redact_text,
)


def _envelope(rpc_id, *, result=None, error=None, jsonrpc=JSONRPC_VERSION):
    """Build a JSON-RPC response envelope as it would arrive off the wire."""
    message = {"jsonrpc": jsonrpc, "id": rpc_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return message


# --- Passivity ---------------------------------------------------------------------------------


def test_tools_call_can_never_be_recorded():
    """``tools/call`` is not a passive method, so the recorder refuses it outright.

    This is the structural guarantee behind the acceptance criterion "passive checks never invoke
    arbitrary business tools": the recorder rejects the method rather than sanitizing it, so a
    call to a business tool can never be laundered into conformance evidence.
    """
    recorder = TranscriptRecorder()

    with pytest.raises(PassiveMethodError) as excinfo:
        recorder.record(
            "tools/call",
            request_id=1,
            params={"name": "delete_everything"},
            http_status=200,
            envelope=_envelope(1, result={}),
        )

    assert excinfo.value.method == "tools/call"
    assert recorder.exchanges == []


@pytest.mark.parametrize("method", ["resources/read", "prompts/get", "completion/complete"])
def test_other_non_passive_methods_are_refused(method):
    """Every method outside the allow-list is refused, not just ``tools/call``."""
    recorder = TranscriptRecorder()
    with pytest.raises(PassiveMethodError):
        recorder.record(
            method, request_id=1, params=None, http_status=200, envelope=_envelope(1, result={})
        )


def test_passive_method_allow_list_is_exactly_discovery():
    """The allow-list is the handshake plus the four list endpoints — and nothing else."""
    assert PASSIVE_METHODS == {
        METHOD_INITIALIZE,
        "notifications/initialized",
        *LIST_METHODS,
    }
    assert "tools/call" not in PASSIVE_METHODS


# --- Redaction ---------------------------------------------------------------------------------


def test_request_params_are_reduced_to_key_names():
    """Only parameter *names* are kept; no value ever reaches the transcript."""
    recorder = TranscriptRecorder()
    recorder.record(
        METHOD_INITIALIZE,
        request_id=1,
        params={"protocolVersion": "2025-06-18", "clientInfo": {"name": "apiome"}},
        http_status=200,
        envelope=_envelope(1, result={"protocolVersion": "2025-06-18"}),
    )

    exchange = recorder.transcript().exchanges[0]
    assert exchange.param_keys == ("clientInfo", "protocolVersion")
    # The values are absent from the serialized evidence entirely.
    assert "apiome" not in str(exchange.as_dict())


def test_result_items_are_reduced_to_key_names_and_a_count():
    """A list page contributes its shape and item count — never the items themselves."""
    recorder = TranscriptRecorder()
    recorder.record(
        "tools/list",
        request_id=2,
        params=None,
        http_status=200,
        envelope=_envelope(
            2,
            result={
                "tools": [{"name": "alpha", "description": "secret business logic"}, {"name": "b"}]
            },
        ),
    )

    exchange = recorder.transcript().exchanges[0]
    assert exchange.result_keys == ("tools",)
    assert exchange.item_count == 2
    assert "secret business logic" not in str(exchange.as_dict())


def test_cursor_is_stored_only_as_a_digest():
    """Opaque cursors are hashed: equality survives (so cycles stay detectable), content does not.

    A ``nextCursor`` is server-defined and may encode a query or a record id, so it is never
    persisted verbatim — but two identical cursors must still hash identically, or a
    non-terminating pagination walk could not be recognized.
    """
    recorder = TranscriptRecorder()
    recorder.record(
        "tools/list",
        request_id=3,
        params={"cursor": "opaque-CURSOR-payload"},
        http_status=200,
        envelope=_envelope(3, result={"tools": [], "nextCursor": "opaque-CURSOR-payload"}),
    )

    exchange = recorder.transcript().exchanges[0]
    serialized = str(exchange.as_dict())
    assert "opaque-CURSOR-payload" not in serialized
    assert exchange.cursor_sent == cursor_digest("opaque-CURSOR-payload")
    # Same cursor in and out -> same digest, which is what makes a cycle detectable.
    assert exchange.cursor_sent == exchange.next_cursor
    assert cursor_digest("a") != cursor_digest("b")
    assert cursor_digest(None) is None


@pytest.mark.parametrize(
    "message",
    [
        "auth failed for Bearer sk-live-abcdefghijklmnopqrstuvwxyz0123456789",
        "invalid api_key=super-secret-value-here",
        "rejected token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghijklmnop",
    ],
)
def test_error_messages_are_scrubbed_of_credentials(message):
    """A server-authored error message is scrubbed before it is retained as evidence.

    Servers quote back what they rejected, so an error message is a realistic place for a token to
    leak into durable storage. Over-redacting costs nothing — the rules read the error *code* and
    shape, not its prose.
    """
    recorder = TranscriptRecorder()
    recorder.record(
        METHOD_INITIALIZE,
        request_id=4,
        params=None,
        http_status=200,
        envelope=_envelope(4, error={"code": -32602, "message": message}),
    )

    retained = recorder.transcript().exchanges[0].error_message
    assert REDACTED in retained
    for secret in ("sk-live-abcdefghijklmnopqrstuvwxyz0123456789", "super-secret-value-here"):
        assert secret not in retained


def test_redact_text_bounds_message_length():
    """A hostile server cannot inflate stored evidence with a megabyte-long error message."""
    scrubbed = redact_text("A" * (MAX_MESSAGE_CHARS * 10))
    assert len(scrubbed) <= MAX_MESSAGE_CHARS + 1  # +1 for the ellipsis
    assert redact_text(None) is None


# --- Exchange reduction ------------------------------------------------------------------------


def test_id_echo_is_recorded_and_type_tolerant():
    """A response echoing its request id passes; one echoing a different id is flagged.

    Ids are compared as strings because a server may legitimately return the id with a different
    JSON type (``"1"``) than it was sent with (``1``) — that is a quirk, not a correlation failure.
    """
    recorder = TranscriptRecorder()
    recorder.record(
        "tools/list", request_id=1, params=None, http_status=200,
        envelope=_envelope("1", result={"tools": []}),
    )
    recorder.record(
        "prompts/list", request_id=2, params=None, http_status=200,
        envelope=_envelope(9999, result={"prompts": []}),
    )

    exchanges = recorder.transcript().exchanges
    assert exchanges[0].id_echoed is True
    assert exchanges[1].id_echoed is False


def test_unparseable_envelope_is_recorded_not_dropped():
    """A response that could not be parsed is recorded as malformed rather than silently ignored.

    Dropping it would let a server that answers garbage look like one that answered nothing —
    and an unobserved exchange must never read as a clean one.
    """
    recorder = TranscriptRecorder()
    recorder.record(
        "tools/list", request_id=1, params=None, http_status=500, envelope=None
    )

    exchange = recorder.transcript().exchanges[0]
    assert exchange.jsonrpc is None
    assert exchange.id_echoed is False
    assert exchange.item_count is None
    assert exchange.http_status == 500


def test_non_integer_error_code_normalizes_to_none():
    """JSON-RPC requires an integer error code; a non-integer is recorded as absent, not guessed."""
    recorder = TranscriptRecorder()
    recorder.record(
        METHOD_INITIALIZE, request_id=1, params=None, http_status=200,
        envelope=_envelope(1, error={"code": "not-a-number", "message": "bad"}),
    )
    assert recorder.transcript().exchanges[0].error_code is None


def test_list_page_missing_its_item_array_yields_no_count():
    """A list result with no item array yields ``item_count is None`` — distinct from zero items."""
    recorder = TranscriptRecorder()
    recorder.record(
        "prompts/list", request_id=1, params=None, http_status=200,
        envelope=_envelope(1, result={}),
    )
    assert recorder.transcript().exchanges[0].item_count is None


# --- Transcript ---------------------------------------------------------------------------------


def test_initialize_exchange_returns_the_successful_attempt():
    """When the handshake falls back to an older revision, the LAST initialize is the real one."""
    recorder = TranscriptRecorder()
    recorder.record(
        METHOD_INITIALIZE, request_id=1, params=None, http_status=200,
        envelope=_envelope(1, error={"code": -32602, "message": "unsupported"}),
    )
    recorder.record(
        METHOD_INITIALIZE, request_id=2, params=None, http_status=200,
        envelope=_envelope(2, result={"protocolVersion": "2025-03-26"}),
    )

    established = recorder.transcript().initialize_exchange()
    assert established.request_id == "2"
    assert established.is_error is False


def test_note_versions_records_the_offer_and_the_settlement():
    """The requested version is knowable only from the handshake, so it is noted separately."""
    recorder = TranscriptRecorder()
    recorder.note_versions(requested="2025-06-18")
    recorder.note_versions(negotiated="2025-03-26")

    transcript = recorder.transcript()
    assert transcript.requested_version == "2025-06-18"
    assert transcript.negotiated_version == "2025-03-26"


def test_transcript_round_trips_through_its_persisted_form():
    """``as_dict``/``from_dict`` round-trip, so a stored transcript re-lints identically."""
    recorder = TranscriptRecorder()
    recorder.note_versions(requested="2025-06-18", negotiated="2025-06-18")
    recorder.record(
        "tools/list", request_id=1, params={"cursor": "c1"}, http_status=200,
        envelope=_envelope(1, result={"tools": [{"name": "a"}], "nextCursor": "c2"}),
    )

    original = recorder.transcript()
    restored = ProtocolTranscript.from_dict(original.as_dict())

    assert restored == original
    assert restored.fingerprint() == original.fingerprint()


def test_transcript_declares_itself_redacted():
    """The payload states that it is reduced evidence rather than leaving it to be assumed."""
    assert TranscriptRecorder().transcript().as_dict()["redacted"] is True


def test_from_dict_tolerates_a_payload_written_by_an_older_revision():
    """Absent keys fall back to defaults and unknown keys are ignored, so old rows still load."""
    restored = ProtocolTranscript.from_dict(
        {"exchanges": [{"method": "tools/list", "unknown_future_key": 1}]}
    )
    assert len(restored.exchanges) == 1
    assert restored.exchanges[0].method == "tools/list"
    assert restored.exchanges[0].item_count is None


def test_for_method_returns_pages_in_wire_order():
    """A paginated walk's exchanges are retrievable per method, in the order they occurred."""
    recorder = TranscriptRecorder()
    for index in range(3):
        recorder.record(
            "tools/list", request_id=index, params=None, http_status=200,
            envelope=_envelope(index, result={"tools": []}),
        )
    recorder.record(
        "prompts/list", request_id=9, params=None, http_status=200,
        envelope=_envelope(9, result={"prompts": []}),
    )

    transcript = recorder.transcript()
    assert len(transcript.for_method("tools/list")) == 3
    assert [x.request_id for x in transcript.for_method("tools/list")] == ["0", "1", "2"]
    assert len(transcript.for_method("prompts/list")) == 1
