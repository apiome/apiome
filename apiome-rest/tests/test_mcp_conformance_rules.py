"""Unit tests for the protocol-conformance rule pack (CLX-3.1, #4855).

These exercise :mod:`app.mcp_conformance_rules` — "did the server behave like an MCP server?" —
over hand-built surfaces and transcripts. Each test degrades exactly one facet of an otherwise
conformant baseline, so a finding can only come from the defect under test.

Both halves of the pack are covered: the surface-derived rules (deterministic, recomputable from
the database) and the transcript-derived rules (live evidence, skipped when unobserved).
"""

from __future__ import annotations

import pytest

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_PROMPT,
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_conformance import PROFILE_PROTOCOL, ConformanceContext, run_conformance
from app.mcp_conformance_rules import _error_code_problem
from app.mcp_protocol_transcript import TranscriptRecorder


def _tool(name: str = "alpha", ordinal: int = 0) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal)


def _prompt(name: str = "greet", ordinal: int = 0) -> CapabilityItem:
    return CapabilityItem(item_type=ITEM_TYPE_PROMPT, name=name, ordinal=ordinal)


def _surface(**overrides) -> DiscoverySurface:
    """A protocol-conformant baseline: correct version, named+versioned server, matched caps."""
    base = {
        "protocol_version": "2025-06-18",
        "server_info": ServerInfo(name="demo", version="1.0.0"),
        "capabilities": {"tools": {}},
        "tools": (_tool(),),
    }
    base.update(overrides)
    return DiscoverySurface(**base)


def _rules(surface, transcript=None) -> set:
    """Run the protocol profile and return the set of rule ids it reported."""
    report = run_conformance(
        ConformanceContext(surface=surface, transcript=transcript), profile=PROFILE_PROTOCOL
    )
    return {finding.rule for finding in report.findings}


def _recorder(*, requested="2025-06-18", negotiated="2025-06-18") -> TranscriptRecorder:
    recorder = TranscriptRecorder()
    recorder.note_versions(requested=requested, negotiated=negotiated)
    return recorder


def _ok(recorder, method, rpc_id, result):
    recorder.record(
        method,
        request_id=rpc_id,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": rpc_id, "result": result},
    )


# --- Baseline ------------------------------------------------------------------------------------


def test_conformant_surface_reports_nothing():
    """The baseline is genuinely clean, so every test below isolates its own defect."""
    assert _rules(_surface()) == set()


# --- Version negotiation --------------------------------------------------------------------------


def test_missing_protocol_version_is_an_error():
    """Without a negotiated version there is no contract for interpreting any later message."""
    assert "protocol.missing-protocol-version" in _rules(_surface(protocol_version=None))


def test_unsupported_protocol_version_is_an_error():
    """A version this client does not speak makes the surface uninterpretable."""
    assert "protocol.unsupported-protocol-version" in _rules(
        _surface(protocol_version="1999-01-01")
    )


def test_supported_older_revision_is_not_flagged():
    """2025-03-26 is a supported revision, so negotiating it is not itself a defect."""
    assert "protocol.unsupported-protocol-version" not in _rules(
        _surface(protocol_version="2025-03-26")
    )


# --- Server identity ------------------------------------------------------------------------------


def test_missing_server_name_is_an_error():
    """A host displays and distinguishes servers by name; an unnamed one cannot be identified."""
    assert "protocol.missing-server-name" in _rules(
        _surface(server_info=ServerInfo(name="", version="1.0.0"))
    )


def test_missing_server_version_is_a_warning():
    """An unversioned server cannot be pinned or audited across upgrades (SHOULD, not MUST)."""
    assert "protocol.missing-server-version" in _rules(
        _surface(server_info=ServerInfo(name="demo", version=None))
    )


# --- Capability negotiation -----------------------------------------------------------------------


def test_listing_a_capability_that_was_never_declared_is_an_error():
    """Serving tools without declaring the 'tools' capability relies on undefined behaviour.

    This is the highest-signal check in the pack, and it is fully deterministic: the stored
    snapshot holds both halves — what initialize declared, and what the list calls returned.
    """
    assert "protocol.undeclared-capability-listed" in _rules(
        _surface(capabilities={}, tools=(_tool(),))
    )


def test_declaring_a_capability_that_lists_nothing_is_advisory():
    """A declared-but-empty capability is legal and possibly transient, so only ``info``."""
    found = _rules(_surface(capabilities={"tools": {}, "prompts": {}}, tools=(_tool(),)))

    assert "protocol.declared-capability-empty" in found
    assert "protocol.undeclared-capability-listed" not in found


def test_resource_templates_are_gated_by_the_resources_capability():
    """Templates share the single 'resources' capability, so declaring it covers both lists."""
    template = CapabilityItem(
        item_type="resource_template", name="doc", ordinal=0, uri_template="file:///{path}"
    )
    declared = _surface(
        capabilities={"tools": {}, "resources": {}},
        tools=(_tool(),),
        resource_templates=(template,),
    )
    assert "protocol.undeclared-capability-listed" not in _rules(declared)

    undeclared = _surface(capabilities={"tools": {}}, tools=(_tool(),), resource_templates=(template,))
    assert "protocol.undeclared-capability-listed" in _rules(undeclared)


def test_prompts_listed_without_declaration_are_flagged():
    """The capability cross-check applies to every kind, not just tools."""
    assert "protocol.undeclared-capability-listed" in _rules(
        _surface(capabilities={"tools": {}}, tools=(_tool(),), prompts=(_prompt(),))
    )


def test_unknown_capability_key_is_advisory():
    """A vendor key outside the spec vocabulary belongs under 'experimental' (portability trap)."""
    found = _rules(_surface(capabilities={"tools": {}, "acmeCustom": {}}))
    assert "protocol.unknown-capability-declared" in found


def test_experimental_and_known_capabilities_are_not_flagged():
    """'experimental' is the spec's own extension escape hatch and is accepted."""
    found = _rules(
        _surface(capabilities={"tools": {}, "experimental": {"x": 1}, "logging": {}})
    )
    assert "protocol.unknown-capability-declared" not in found


# --- Transcript: envelopes ------------------------------------------------------------------------


def test_response_that_does_not_echo_its_request_id_is_an_error():
    """The one envelope defect the client tolerates — so only the transcript can reveal it."""
    recorder = _recorder()
    recorder.record(
        "tools/list",
        request_id=7,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 9999, "result": {"tools": []}},
    )
    assert "protocol.response-id-not-echoed" in _rules(_surface(), recorder.transcript())


def test_echoed_ids_are_not_flagged():
    """A correctly correlated response produces no envelope finding."""
    recorder = _recorder()
    _ok(recorder, "tools/list", 1, {"tools": [{"name": "alpha"}]})
    assert "protocol.response-id-not-echoed" not in _rules(_surface(), recorder.transcript())


# --- Transcript: error-code discipline -------------------------------------------------------------


@pytest.mark.parametrize("code", [-32700, -32600, -32601, -32602, -32603, -32050, -32000])
def test_defined_and_server_error_codes_are_accepted(code):
    """Pre-defined codes and the implementation-defined server-error band are legitimate."""
    assert _error_code_problem(code) is None


@pytest.mark.parametrize("code", [200, -1, 4040])
def test_application_defined_codes_outside_the_reserved_band_are_accepted(code):
    """Codes outside the reserved band are the server's own space and are never flagged."""
    assert _error_code_problem(code) is None


@pytest.mark.parametrize("code", [-32500, -32300, -32768])
def test_undefined_codes_inside_the_reserved_band_are_flagged(code):
    """A code squatting on reserved space cannot be interpreted by a conformant client."""
    assert _error_code_problem(code) is not None


def test_non_integer_error_code_is_flagged():
    """JSON-RPC requires an integer code; a missing/non-numeric one is itself the defect."""
    assert _error_code_problem(None) is not None


def test_reserved_band_error_code_surfaces_as_a_finding():
    """The rule fires end-to-end on a recorded initialize rejection with a bad code."""
    recorder = _recorder()
    recorder.record(
        "initialize",
        request_id=1,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 1, "error": {"code": -32500, "message": "nope"}},
    )
    assert "protocol.error-code-non-standard" in _rules(_surface(), recorder.transcript())


# --- Transcript: version downgrade -----------------------------------------------------------------


def test_protocol_version_downgrade_is_reported_as_info():
    """Negotiating down is correct behaviour, but it silently withholds newer-revision features."""
    recorder = _recorder(requested="2025-06-18", negotiated="2025-03-26")
    _ok(recorder, "initialize", 1, {"protocolVersion": "2025-03-26"})

    found = _rules(_surface(protocol_version="2025-03-26"), recorder.transcript())
    assert "protocol.protocol-version-downgraded" in found


def test_no_downgrade_finding_when_the_offer_was_honoured():
    """A server echoing the offered version is the happy path and is not flagged."""
    recorder = _recorder(requested="2025-06-18", negotiated="2025-06-18")
    _ok(recorder, "initialize", 1, {"protocolVersion": "2025-06-18"})

    assert "protocol.protocol-version-downgraded" not in _rules(_surface(), recorder.transcript())


# --- Transcript: pagination -------------------------------------------------------------------------


def test_list_page_missing_its_item_array_is_an_error():
    """An absent item array is read by a trusting client as 'no items', silently shrinking the surface."""
    recorder = _recorder()
    _ok(recorder, "prompts/list", 1, {})  # no "prompts" key at all

    assert "protocol.list-result-missing-items" in _rules(_surface(), recorder.transcript())


def test_empty_page_advertising_a_next_cursor_is_a_warning():
    """A page carrying nothing yet promising more costs a round trip for no items."""
    recorder = _recorder()
    recorder.record(
        "tools/list",
        request_id=1,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 1, "result": {"tools": [], "nextCursor": "c1"}},
    )
    _ok(recorder, "tools/list", 2, {"tools": [{"name": "alpha"}]})

    assert "protocol.empty-page-with-next-cursor" in _rules(_surface(), recorder.transcript())


def test_healthy_pagination_reports_nothing():
    """A normal multi-page walk that terminates cleanly produces no pagination findings."""
    recorder = _recorder()
    recorder.record(
        "tools/list",
        request_id=1,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "a"}], "nextCursor": "c1"}},
    )
    _ok(recorder, "tools/list", 2, {"tools": [{"name": "b"}]})

    found = _rules(_surface(), recorder.transcript())
    assert "protocol.empty-page-with-next-cursor" not in found
    assert "protocol.list-result-missing-items" not in found


def test_a_defect_repeated_on_every_page_is_reported_once():
    """A malformed 50-page list yields one actionable finding, not fifty copies of it."""
    recorder = _recorder()
    for rpc_id in range(1, 4):
        recorder.record(
            "tools/list",
            request_id=rpc_id,
            params=None,
            http_status=200,
            envelope={
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": ({"nextCursor": f"c{rpc_id}"} if rpc_id < 3 else {}),
            },
        )

    report = run_conformance(
        ConformanceContext(surface=_surface(), transcript=recorder.transcript()),
        profile=PROFILE_PROTOCOL,
    )
    missing = [f for f in report.findings if f.rule == "protocol.list-result-missing-items"]
    assert len(missing) == 1


# --- 2026-07-28 revision (AAU-4.1, #5714) ------------------------------------------------------------


def test_newest_handshake_revision_is_supported():
    """2025-11-25 is a released handshake revision, so negotiating it is not a defect."""
    assert "protocol.unsupported-protocol-version" not in _rules(
        _surface(protocol_version="2025-11-25")
    )


def test_modern_revision_on_the_surface_is_not_unsupported():
    """A 2026-07-28 surface (e.g. from server/discover) names a known revision."""
    assert "protocol.unsupported-protocol-version" not in _rules(
        _surface(protocol_version="2026-07-28")
    )


def test_initialize_answered_with_a_modern_revision_is_an_error():
    """2026-07-28 has no handshake: an initialize that settles on it claims the impossible."""
    recorder = _recorder(requested="2026-07-28", negotiated="2026-07-28")
    _ok(recorder, "initialize", 1, {"protocolVersion": "2026-07-28"})

    found = _rules(_surface(protocol_version="2026-07-28"), recorder.transcript())
    assert "protocol.modern-version-via-handshake" in found
    # initialize is not a 2026-07-28 method, so its result is not held to resultType.
    assert "protocol.result-type-missing" not in found


def test_honest_fallback_from_a_modern_offer_is_only_a_downgrade():
    """Offered 2026-07-28, answered 2025-11-25: the lifecycle's own negotiation, info only."""
    recorder = _recorder(requested="2026-07-28", negotiated="2025-11-25")
    _ok(recorder, "initialize", 1, {"protocolVersion": "2025-11-25"})

    found = _rules(_surface(protocol_version="2025-11-25"), recorder.transcript())
    assert found == {"protocol.protocol-version-downgraded"}


def test_modern_version_rule_is_skipped_without_a_transcript():
    """How a version was reached is only visible on the wire; unobserved is skipped, not passed."""
    report = run_conformance(
        ConformanceContext(surface=_surface(protocol_version="2026-07-28"), transcript=None),
        profile=PROFILE_PROTOCOL,
    )
    assert "protocol.modern-version-via-handshake" in report.skipped_rules
    assert "protocol.result-type-missing" in report.skipped_rules


def test_modern_result_without_result_type_is_an_error_once_per_method():
    """2026-07-28 makes resultType mandatory; a malformed list is one finding, not one per page."""
    recorder = _recorder(requested="2026-07-28", negotiated="2026-07-28")
    _ok(recorder, "tools/list", 1, {"tools": [{"name": "a"}], "nextCursor": "c1"})
    _ok(recorder, "tools/list", 2, {"tools": [{"name": "b"}]})

    report = run_conformance(
        ConformanceContext(
            surface=_surface(protocol_version="2026-07-28"), transcript=recorder.transcript()
        ),
        profile=PROFILE_PROTOCOL,
    )
    missing = [f for f in report.findings if f.rule == "protocol.result-type-missing"]
    assert len(missing) == 1
    assert missing[0].severity == "error"
    assert missing[0].path == "transcript.tools/list"


def test_modern_result_carrying_result_type_is_clean():
    """A 2026-07-28 result with resultType is the happy path."""
    recorder = _recorder(requested="2026-07-28", negotiated="2026-07-28")
    _ok(recorder, "tools/list", 1, {"tools": [{"name": "a"}], "resultType": "complete"})

    found = _rules(_surface(protocol_version="2026-07-28"), recorder.transcript())
    assert "protocol.result-type-missing" not in found


def test_result_type_is_not_required_before_2026():
    """Pre-2026 servers never send resultType; holding them to it would be a false positive."""
    recorder = _recorder()
    _ok(recorder, "tools/list", 1, {"tools": [{"name": "a"}]})

    assert "protocol.result-type-missing" not in _rules(_surface(), recorder.transcript())


def test_deprecated_logging_capability_is_info():
    """2026-07-28 deprecates Logging: still legal, so advisory, but visible before the window ends."""
    report = run_conformance(
        ConformanceContext(surface=_surface(capabilities={"tools": {}, "logging": {}})),
        profile=PROFILE_PROTOCOL,
    )
    deprecated = [f for f in report.findings if f.rule == "protocol.deprecated-capability-declared"]
    assert [(f.path, f.severity) for f in deprecated] == [("surface.capabilities.logging", "info")]


def test_new_rules_cite_the_2026_revision():
    """Every 2026-07-28 rule names its revision and a resolvable page of it (AC: rules cite versions)."""
    from app.mcp_conformance import RULE_REGISTRY

    for rule_id in (
        "protocol.modern-version-via-handshake",
        "protocol.result-type-missing",
        "protocol.deprecated-capability-declared",
    ):
        rule = RULE_REGISTRY[rule_id]
        assert rule.spec_version == "2026-07-28"
        assert rule.spec_reference.startswith(
            "https://modelcontextprotocol.io/specification/2026-07-28/"
        )
