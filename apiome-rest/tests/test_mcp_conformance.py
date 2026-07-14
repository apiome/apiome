"""Unit tests for the MCP conformance engine (CLX-3.1, #4855).

These exercise :mod:`app.mcp_conformance` — the engine, its profiles, its gate, and its rule
catalog — as distinct from the two rule packs that plug into it (covered in
:mod:`tests.test_mcp_conformance_rules` and :mod:`tests.test_mcp_agent_readiness`).

Four contracts matter most and are tested as properties:

* **The surface lint is untouched.** Conformance carries its own registry, so adding a
  conformance rule must never move an MCP snapshot's persisted lint score or fingerprint.
* **Determinism.** With no transcript, the same stored surface always yields the same report —
  which is what lets the API recompute conformance from the database.
* **Nothing unobserved reads as clean.** A rule needing a transcript is *skipped* and reported,
  never silently passed, when no transcript was captured.
* **Every rule cites a spec.** A finding must be traceable to a normative statement.
"""

from __future__ import annotations

import pytest

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import (
    ITEM_TYPE_TOOL,
    CapabilityItem,
    DiscoverySurface,
)
from app.mcp_conformance import (
    CATEGORY_PROTOCOL,
    CATEGORY_READINESS,
    DEFAULT_PROFILE,
    FAIL_ON_NONE,
    MCP_SPEC_VERSION,
    PROFILE_FULL,
    PROFILE_PROTOCOL,
    PROFILE_READINESS,
    PROFILES,
    RULE_REGISTRY,
    ConformanceContext,
    UnknownProfileError,
    evaluate_gate,
    make_finding,
    resolve_profile,
    rule_catalog,
    run_conformance,
)
from app.mcp_protocol_transcript import TranscriptRecorder


def _tool(name: str, ordinal: int = 0, **extra):
    return CapabilityItem(item_type=ITEM_TYPE_TOOL, name=name, ordinal=ordinal, **extra)


def _surface(tools=(), *, capabilities=None, protocol_version="2025-06-18", server_name="demo"):
    """A conformant baseline surface; tests degrade exactly the facet they are about."""
    return DiscoverySurface(
        protocol_version=protocol_version,
        server_info=ServerInfo(name=server_name, version="1.0.0"),
        capabilities={"tools": {}} if capabilities is None else capabilities,
        tools=tuple(tools),
    )


def _clean_tool(name: str = "search_items", ordinal: int = 0) -> CapabilityItem:
    """A tool that satisfies every agent-readiness rule, so it contributes no findings."""
    return _tool(
        name,
        ordinal,
        description=(
            "Search the item catalog by keyword and return matching items; "
            "returns an empty list when nothing matches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The keyword to search the catalog for.",
                    "minLength": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of items to return.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
        output_schema={"type": "object", "properties": {"items": {"type": "array"}}},
        annotations={"readOnlyHint": True},
    )


def _transcript():
    """A minimal, well-behaved transcript so transcript-backed rules become evaluable."""
    recorder = TranscriptRecorder()
    recorder.note_versions(requested="2025-06-18", negotiated="2025-06-18")
    recorder.record(
        "initialize",
        request_id=1,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}},
    )
    recorder.record(
        "tools/list",
        request_id=2,
        params=None,
        http_status=200,
        envelope={"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}]}},
    )
    return recorder.transcript()


# --- Isolation from the surface lint ------------------------------------------------------------


def test_conformance_rules_are_not_in_the_surface_lint_registry():
    """Conformance rules must never leak into the MCP surface lint's registry.

    ``mcp_score.score_mcp_surface`` runs *every* rule in ``mcp_lint.RULE_CATALOGUE`` and hashes
    the result into a persisted ``report_fingerprint``. If a conformance rule registered there,
    every MCP snapshot already stored would be retroactively regraded. The two registries are
    separate precisely to prevent that, and this test is the guard on it.
    """
    from app.mcp_lint import RULE_CATALOGUE

    overlap = set(RULE_REGISTRY) & set(RULE_CATALOGUE)
    assert overlap == set(), f"conformance rules leaked into the surface lint registry: {overlap}"


def test_surface_lint_score_is_unchanged_by_conformance_rules():
    """Scoring a surface through the lint engine ignores the conformance rules entirely."""
    from app.mcp_score import score_mcp_surface

    surface = _surface([_clean_tool()])
    result = score_mcp_surface(surface)

    assert all(not f.rule.startswith(("protocol.", "readiness.")) for f in result.findings)


# --- Determinism & transcript handling ----------------------------------------------------------


def test_report_is_deterministic_without_a_transcript():
    """The same stored surface always yields the same report — so the API can recompute offline."""
    surface = _surface([_clean_tool()])

    first = run_conformance(ConformanceContext(surface=surface))
    second = run_conformance(ConformanceContext(surface=surface))

    assert first.report_fingerprint == second.report_fingerprint
    assert first.finding_dicts() == second.finding_dicts()


def test_transcript_rules_are_skipped_not_passed_when_unobserved():
    """With no transcript, transcript-backed rules are reported as skipped — never as passing.

    This is the acceptance criterion that an unobserved protocol behaviour must not read as
    clean. A skipped rule appears in ``skipped_rules`` and NOT in ``evaluated_rules``.
    """
    report = run_conformance(ConformanceContext(surface=_surface([_clean_tool()])))

    assert report.transcript_captured is False
    assert report.skipped_rules, "transcript-backed rules should be reported as skipped"

    transcript_rules = {r.rule_id for r in RULE_REGISTRY.values() if r.requires_transcript}
    assert set(report.skipped_rules) == transcript_rules
    assert not (set(report.evaluated_rules) & transcript_rules)


def test_transcript_rules_are_evaluated_when_a_transcript_exists():
    """With a transcript in hand, nothing is skipped and the full rule set runs."""
    report = run_conformance(
        ConformanceContext(surface=_surface([_clean_tool()]), transcript=_transcript())
    )

    assert report.transcript_captured is True
    assert report.skipped_rules == ()
    assert set(report.evaluated_rules) == set(RULE_REGISTRY)


def test_report_fingerprint_distinguishes_profiles():
    """The same surface under two profiles must not produce colliding fingerprints."""
    surface = _surface([_tool("x")])

    protocol = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_PROTOCOL)
    readiness = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_READINESS)

    assert protocol.report_fingerprint != readiness.report_fingerprint


# --- Profiles ------------------------------------------------------------------------------------


def test_profiles_select_only_their_own_categories():
    """A profile evaluates its categories and emits findings from no other."""
    surface = _surface([_tool("Bad Name")], capabilities={})  # trips both packs

    protocol = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_PROTOCOL)
    readiness = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_READINESS)
    full = run_conformance(ConformanceContext(surface=surface), profile=PROFILE_FULL)

    assert {f.category for f in protocol.findings} == {CATEGORY_PROTOCOL}
    assert {f.category for f in readiness.findings} == {CATEGORY_READINESS}
    assert {f.category for f in full.findings} == {CATEGORY_PROTOCOL, CATEGORY_READINESS}
    # The full profile is exactly the union of the two halves.
    assert len(full.findings) == len(protocol.findings) + len(readiness.findings)


def test_default_profile_is_the_full_one():
    """Naming no profile runs everything, so a caller cannot under-gate by omission."""
    assert DEFAULT_PROFILE == PROFILE_FULL
    assert resolve_profile(None).profile_id == PROFILE_FULL


def test_unknown_profile_is_rejected_not_defaulted():
    """A typo'd profile raises rather than silently widening or narrowing what is gated."""
    with pytest.raises(UnknownProfileError):
        run_conformance(ConformanceContext(surface=_surface()), profile="mcp-typo")
    with pytest.raises(UnknownProfileError):
        resolve_profile("nope")


def test_every_profile_selects_at_least_one_registered_rule():
    """A profile that selects nothing would gate on nothing while appearing to gate."""
    for profile_id in PROFILES:
        assert rule_catalog(profile_id), f"profile {profile_id} selects no rules"


# --- Gate ----------------------------------------------------------------------------------------


def test_gate_fails_on_the_threshold_severity_and_worse():
    """``fail_on='warning'`` fails on warnings AND errors — the threshold is inclusive upward."""
    warning = make_finding("tools.x", "readiness.tool-unbounded-list", "unbounded")
    info = make_finding("tools.x", "readiness.tool-missing-output-schema", "no output schema")

    assert evaluate_gate([warning], 90, fail_on="warning").passed is False
    assert evaluate_gate([warning], 90, fail_on="error").passed is True  # warning < error
    assert evaluate_gate([info], 90, fail_on="warning").passed is True
    assert evaluate_gate([info], 90, fail_on="info").passed is False


def test_gate_none_disables_severity_gating():
    """``fail_on='none'`` is a report-only stage: findings never fail the gate on their own."""
    error = make_finding(
        "surface.serverInfo.name", "protocol.missing-server-name", "no name"
    )
    gate = evaluate_gate([error], 10, fail_on=FAIL_ON_NONE)

    assert gate.passed is True
    assert gate.reasons == ()


def test_gate_applies_a_score_floor_independently():
    """``min_score`` fails a run whose score is below it, even with no gating severity present."""
    gate = evaluate_gate([], 70, fail_on=FAIL_ON_NONE, min_score=80)

    assert gate.passed is False
    assert any("below the required minimum" in reason for reason in gate.reasons)
    assert evaluate_gate([], 80, fail_on=FAIL_ON_NONE, min_score=80).passed is True


def test_gate_reports_a_reason_per_failed_threshold():
    """Both thresholds can fail at once, and each contributes its own explanation."""
    error = make_finding(
        "surface.serverInfo.name", "protocol.missing-server-name", "no name"
    )
    gate = evaluate_gate([error], 40, fail_on="error", min_score=90)

    assert gate.passed is False
    assert len(gate.reasons) == 2


def test_gate_rejects_an_unknown_threshold():
    """An unrecognized ``fail_on`` raises rather than quietly gating on nothing."""
    with pytest.raises(ValueError):
        evaluate_gate([], 100, fail_on="critical")


def test_clean_surface_scores_100_and_passes():
    """A fully conformant surface produces no findings, scores 100, and clears the gate."""
    report = run_conformance(
        ConformanceContext(surface=_surface([_clean_tool()]), transcript=_transcript()),
        fail_on="info",
    )

    assert report.findings == ()
    assert report.score == 100
    assert report.grade == "A"
    assert report.gate.passed is True


# --- Rule catalog ---------------------------------------------------------------------------------


def test_every_rule_cites_a_spec_version_and_a_resolvable_reference():
    """Acceptance criterion: a finding must trace to a normative statement, not an opinion."""
    for rule in rule_catalog():
        assert rule["spec_version"] == MCP_SPEC_VERSION
        assert rule["spec_reference"].startswith("https://"), rule["rule_id"]
        assert rule["rationale"].strip(), rule["rule_id"]
        assert rule["severity"] in ("error", "warning", "info")
        assert rule["category"] in (CATEGORY_PROTOCOL, CATEGORY_READINESS)


def test_rule_catalog_is_sorted_and_filterable_by_profile():
    """The catalog is deterministic, and a profile filter returns only that profile's rules."""
    ids = [rule["rule_id"] for rule in rule_catalog()]
    assert ids == sorted(ids)

    protocol_only = rule_catalog(PROFILE_PROTOCOL)
    assert protocol_only
    assert {rule["category"] for rule in protocol_only} == {CATEGORY_PROTOCOL}


def test_make_finding_rejects_an_unregistered_rule():
    """Emitting a rule id nobody registered is a bug, and fails loudly rather than silently."""
    with pytest.raises(KeyError):
        make_finding("tools.x", "protocol.invented-rule", "nope")


def test_findings_are_sorted_deterministically():
    """Findings are ordered by (path, rule, id) regardless of the order rules appended them."""
    surface = _surface([_tool("z_bad"), _tool("a_bad", ordinal=1)], capabilities={})
    report = run_conformance(ConformanceContext(surface=surface))

    keys = [(f.path, f.rule, f.id) for f in report.findings]
    assert keys == sorted(keys)


def test_finding_ids_are_stable_across_runs():
    """A finding id is a hash of (path, rule, message), so it tracks across re-runs."""
    surface = _surface([_tool("x")], capabilities={})

    first = {f.id for f in run_conformance(ConformanceContext(surface=surface)).findings}
    second = {f.id for f in run_conformance(ConformanceContext(surface=surface)).findings}

    assert first == second
    assert all(fid.startswith("mcp-conf-") for fid in first)


def test_report_dict_is_a_superset_of_the_lint_report_shape():
    """The report reuses the lint report's key set so every existing consumer reads it unchanged.

    The evidence normalizer, the axis model, and the SARIF/JUnit serializer all consume a lint
    report; conformance rides those code paths rather than duplicating them.
    """
    report = run_conformance(ConformanceContext(surface=_surface([_tool("x")]))).report_dict()

    for key in (
        "score",
        "grade",
        "findings",
        "rule_hits",
        "severity_counts",
        "report_fingerprint",
    ):
        assert key in report

    for key in ("profile", "spec_version", "evaluated_rules", "skipped_rules", "gate"):
        assert key in report

    finding = report["findings"][0]
    assert set(finding) == {"id", "path", "category", "rule", "severity", "message"}
