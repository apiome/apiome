"""Engine tests for consent-gated, sandboxed MCP dynamic probes (CLX-3.3, #4857).

The properties under test are the acceptance criteria, made executable:

* **AC1** — the default profile is read-only and sends nothing.
* **AC2** — an active run records target, scope, test identity, limits, and consent.
* **AC3** — a stdio target may only run under a least-privilege sandbox; the spec fails closed.
* **AC4** — findings distinguish suspected / observed / exploited-in-test, and a probe cannot claim a
  tier stronger than its profile allows.
* **AC5** — a global kill switch and per-tenant concurrency/rate limits refuse an active run.

Plus the honesty bridge to CLX-3.2: only an *exploited-in-test* finding becomes ProbeEvidence, and
only ProbeEvidence moves the trust-posture report's ``proven_count``.
"""

from __future__ import annotations

import asyncio

import pytest

from app import mcp_probe as mp
from app import mcp_trust_posture as tp
from app.mcp_client.normalize import CapabilityItem, DiscoverySurface
from app.mcp_probe_probes import (
    PROBE_PARAMETER_INJECTION,
    PROBE_UNAUTHENTICATED_READ,
)
from app.mcp_probe_rules import RULE_PROVEN_AUTH_BYPASS, RULE_PROVEN_INPUT_INJECTION
from app.mcp_protocol_transcript import ProtocolExchange, ProtocolTranscript

# --- Fixtures ------------------------------------------------------------------------------------


def _surface(*, with_auth: bool = True) -> DiscoverySurface:
    return DiscoverySurface(
        tools=(
            CapabilityItem(
                item_type="tool",
                name="echo",
                ordinal=0,
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            ),
        ),
        capabilities={"authentication": {"required": True}} if with_auth else {"tools": {}},
    )


def _consent(**overrides):
    base = dict(
        target_endpoint_id="ep1",
        target_locator="https://mcp.example/mcp",
        transport=mp.TRANSPORT_HTTP,
        allowlisted=True,
        ownership_declared=True,
        acknowledged_by="user-1",
        acknowledged_at="2026-07-14T00:00:00Z",
        test_identity="probe-cred",
        dedicated_credentials=True,
        explicit_approval=True,
    )
    base.update(overrides)
    return mp.ConsentRecord(**base)


class _FakeTransport:
    """A scripted transport: an unauth listing succeeds, unknown methods are answered laxly, and a
    canary is reflected — so the exploit-tier probes fire deterministically."""

    def __init__(self, *, reflect_canary: bool = True, unknown_lax: bool = True, serve_list: bool = True):
        self.reflect_canary = reflect_canary
        self.unknown_lax = unknown_lax
        self.serve_list = serve_list
        self.calls: list[str] = []

    async def send(self, method, params):
        self.calls.append(method)
        if method.startswith("$apiome.probe/"):
            if self.unknown_lax:
                return mp.ProbeResponse(ok=True, error_code=None, result_keys=("x",))
            return mp.ProbeResponse(ok=True, error_code=-32601)
        if method == "tools/list":
            if self.serve_list:
                return mp.ProbeResponse(ok=True, error_code=None, result_keys=("tools",))
            return mp.ProbeResponse(ok=True, error_code=-32001)
        if method == "tools/call":
            value = list(params.get("arguments", {}).values())[0]
            reflected = (value,) if (self.reflect_canary and "CANARY" in str(value)) else ()
            return mp.ProbeResponse(ok=True, error_code=None, result_keys=("content",),
                                    reflected_canaries=reflected)
        return mp.ProbeResponse(ok=True)


def _run(coro):
    return asyncio.run(coro)


# --- AC4: classification tiers -------------------------------------------------------------------


def test_classifications_are_ordered_weakest_to_strongest():
    assert mp.CLASSIFICATIONS == ("suspected", "observed", "exploited-in-test")
    assert mp._class_rank("suspected") < mp._class_rank("observed") < mp._class_rank("exploited-in-test")


def test_profile_ceilings_reflect_invasiveness():
    assert not mp.PROFILES[mp.PROFILE_PASSIVE].sends_requests
    assert mp.PROFILES[mp.PROFILE_PASSIVE].max_classification == mp.CLASS_OBSERVED
    assert mp.PROFILES[mp.PROFILE_PAYLOAD_FUZZING].max_classification == mp.CLASS_EXPLOITED_IN_TEST
    assert mp.PROFILES[mp.PROFILE_PAYLOAD_FUZZING].requires_explicit_approval


def test_probe_finding_rejects_suspected_tier():
    # 'suspected' is the static engines' tier; a probe finding may not carry it.
    with pytest.raises(ValueError):
        mp.ProbeFinding(
            probe_id="p", rule_id="r", path="x", severity="warning",
            classification=mp.CLASS_SUSPECTED, message="m", observed="o",
        )


def test_probe_registered_stronger_than_profile_is_rejected():
    with pytest.raises(ValueError):
        mp.Probe(
            probe_id="bad", profile=mp.PROFILE_PASSIVE, title="t", rationale="r",
            owasp_ids=("MCP01",), emits=mp.CLASS_EXPLOITED_IN_TEST,  # passive can't exploit
        )


# --- AC1: default is read-only -------------------------------------------------------------------


def test_default_profile_is_passive_and_sends_nothing():
    assert mp.DEFAULT_PROFILE == mp.PROFILE_PASSIVE
    assert mp.resolve_profile(None).sends_requests is False


def test_passive_run_over_transcript_emits_observed_only_and_no_evidence():
    transcript = ProtocolTranscript(
        exchanges=(
            ProtocolExchange(method="tools/list", request_id="1", id_echoed=False, jsonrpc="2.0"),
            ProtocolExchange(method="initialize", request_id="2", jsonrpc=None),  # malformed envelope
        )
    )
    report = mp.run_passive_probes(_surface(), transcript, target_endpoint_id="ep1")
    classes = {f.classification for f in report.findings}
    assert classes == {mp.CLASS_OBSERVED}
    assert report.requests_sent == 0
    assert report.evidence == ()  # passive never mints probe evidence
    assert report.exploited_count == 0


def test_passive_run_without_transcript_reports_protocol_probes_skipped():
    report = mp.run_passive_probes(_surface(), None, target_endpoint_id="ep1")
    assert report.findings == ()
    assert report.skipped_probes  # the protocol probes are skipped-and-reported, not silently absent
    for reason in report.skipped_probes.values():
        assert "transcript" in reason.lower()


# --- AC2 + AC5 + AC3: gates on an active run -----------------------------------------------------


def test_consent_validation_requires_every_element():
    profile = mp.PROFILES[mp.PROFILE_SAFE_ACTIVE]
    with pytest.raises(mp.ConsentError):
        _consent(allowlisted=False).validate(profile)
    with pytest.raises(mp.ConsentError):
        _consent(ownership_declared=False).validate(profile)
    with pytest.raises(mp.ConsentError):
        _consent(dedicated_credentials=False).validate(profile)
    # payload fuzzing additionally needs explicit approval
    with pytest.raises(mp.ConsentError):
        _consent(explicit_approval=False).validate(mp.PROFILES[mp.PROFILE_PAYLOAD_FUZZING])
    # a complete record validates
    _consent().validate(profile)


def test_passive_profile_needs_no_consent():
    # A no-op: the read-only profile requires nothing.
    mp.ConsentRecord(
        target_endpoint_id="ep1", target_locator="x", transport=mp.TRANSPORT_HTTP,
        allowlisted=False, ownership_declared=False, acknowledged_by="", acknowledged_at="t",
    ).validate(mp.PROFILES[mp.PROFILE_PASSIVE])


def test_isolation_spec_fails_closed_on_missing_guarantees():
    assert mp.IsolationSpec.hardened().is_least_privilege()
    bad = mp.IsolationSpec(
        read_only_rootfs=False, mount_host_socket=True, drop_all_capabilities=False,
        disposable=False, network_disabled=False, egress_allowlist=("*",),
    )
    violations = bad.violations()
    assert any("read-only" in v for v in violations)
    assert any("host container socket" in v for v in violations)
    assert any("disposable" in v for v in violations)
    assert any("'*'" in v for v in violations)


def test_require_isolation_refuses_stdio_without_sandbox():
    stdio = _consent(transport=mp.TRANSPORT_STDIO)
    with pytest.raises(mp.IsolationError):
        mp.require_isolation(stdio, None)
    with pytest.raises(mp.IsolationError):
        mp.require_isolation(stdio, mp.IsolationSpec(read_only_rootfs=False))
    # a hardened spec is accepted
    mp.require_isolation(stdio, mp.IsolationSpec.hardened())
    # http needs no local sandbox
    mp.require_isolation(_consent(transport=mp.TRANSPORT_HTTP), None)


def test_kill_switch_and_rate_limits():
    active = mp.PROFILES[mp.PROFILE_SAFE_ACTIVE]
    passive = mp.PROFILES[mp.PROFILE_PASSIVE]
    # kill switch off -> active refused, passive unaffected
    with pytest.raises(mp.KillSwitchError):
        mp.authorize_active_run(active, mp.GovernorPolicy(enabled=False), mp.TenantUsage())
    mp.authorize_active_run(passive, mp.GovernorPolicy(enabled=False), mp.TenantUsage())
    # concurrency
    with pytest.raises(mp.RateLimitError):
        mp.authorize_active_run(
            active, mp.GovernorPolicy(enabled=True, max_concurrent_per_tenant=1),
            mp.TenantUsage(active_runs=1),
        )
    # hourly rate
    with pytest.raises(mp.RateLimitError):
        mp.authorize_active_run(
            active, mp.GovernorPolicy(enabled=True, max_runs_per_hour_per_tenant=5),
            mp.TenantUsage(runs_last_hour=5),
        )


def test_counting_transport_enforces_request_and_byte_caps():
    async def scenario():
        limits = mp.ProbeLimits(max_requests=1, max_response_bytes=10)
        counting = mp.CountingTransport(_FakeTransport(), limits)
        await counting.send("tools/list", {})
        assert counting.request_count == 1
        with pytest.raises(mp.LimitExceededError):
            await counting.send("tools/list", {})  # over the request cap

        big = mp.CountingTransport(
            type("T", (), {"send": lambda self, m, p: _resp_big()})(), mp.ProbeLimits(max_response_bytes=5)
        )
        with pytest.raises(mp.LimitExceededError):
            await big.send("x", {})

    async def _resp_big():
        return mp.ProbeResponse(ok=True, response_bytes=1000)

    _run(scenario())


# --- Active run happy paths ----------------------------------------------------------------------


def test_safe_active_run_records_audit_envelope_and_evidence():
    async def scenario():
        report = await mp.run_active_probes(
            _surface(), _FakeTransport(), profile=mp.PROFILE_SAFE_ACTIVE,
            consent=_consent(), policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
            probe_run_id="run-1",
        )
        # AC2: the audit envelope carries target, scope, identity, limits, consent.
        d = report.as_dict()
        assert d["consent"]["target_endpoint_id"] == "ep1"
        assert d["consent"]["test_identity"] == "probe-cred"
        assert d["limits"]["max_requests"] > 0
        assert d["requests_sent"] >= 1
        probes = {f.probe_id for f in report.findings}
        assert PROBE_UNAUTHENTICATED_READ in probes  # exploited-in-test
        # exactly the exploited findings mint evidence, tagged with the run id
        assert len(report.evidence) == report.exploited_count == 1
        assert report.evidence[0].probe_run_id == "run-1"
        return report

    _run(scenario())


def test_payload_fuzzing_reflected_canary_is_exploited_in_test():
    async def scenario():
        report = await mp.run_active_probes(
            _surface(), _FakeTransport(), profile=mp.PROFILE_PAYLOAD_FUZZING,
            consent=_consent(), policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
            probe_run_id="run-2",
        )
        exploited = [f for f in report.findings if f.is_exploit]
        assert {f.probe_id for f in exploited} == {PROBE_PARAMETER_INJECTION}
        assert report.evidence[0].observed  # the demonstration travels with the claim
        return report

    _run(scenario())


def test_run_active_probes_rejects_the_passive_profile():
    with pytest.raises(ValueError):
        _run(
            mp.run_active_probes(
                _surface(), _FakeTransport(), profile=mp.PROFILE_PASSIVE, consent=_consent(),
                policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
            )
        )


def test_no_auth_advertised_means_no_auth_bypass_finding():
    async def scenario():
        report = await mp.run_active_probes(
            _surface(with_auth=False), _FakeTransport(), profile=mp.PROFILE_SAFE_ACTIVE,
            consent=_consent(), policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
        )
        # A public listing is not a bypass; the auth probe stays silent.
        assert PROBE_UNAUTHENTICATED_READ not in {f.probe_id for f in report.findings}

    _run(scenario())


# --- Bridge to CLX-3.2: only exploited-in-test becomes proven ------------------------------------


def test_observed_finding_cannot_become_probe_evidence():
    observed = mp.make_observed("passive.protocol.id-not-echoed", "x", "m", observed="o")
    with pytest.raises(ValueError):
        observed.to_probe_evidence()


def test_profile_ceiling_enforced_at_report_assembly():
    # An exploit finding forced under the passive profile is refused at assembly (last-line defence).
    exploit = mp.make_exploited(
        PROBE_PARAMETER_INJECTION, "r", "p", "m", observed="demonstrated"
    )
    with pytest.raises(ValueError):
        mp.ProbeReport.assemble(
            mp.PROFILES[mp.PROFILE_PASSIVE], "ep1", [exploit],
            requests_sent=0, skipped_probes={}, consent=None, limits=None, isolation=None,
        )


def test_probe_evidence_moves_trust_posture_proven_count():
    async def scenario():
        active = await mp.run_active_probes(
            _surface(), _FakeTransport(), profile=mp.PROFILE_SAFE_ACTIVE, consent=_consent(),
            policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
        )
        fuzz = await mp.run_active_probes(
            _surface(), _FakeTransport(), profile=mp.PROFILE_PAYLOAD_FUZZING, consent=_consent(),
            policy=mp.GovernorPolicy(enabled=True), usage=mp.TenantUsage(),
        )
        evidence = active.evidence + fuzz.evidence
        context = tp.PostureContext(surface=_surface(), probes=evidence)
        report = tp.run_trust_posture(context)
        assert report.proven_count == 2
        proven_rules = {f.rule for f in report.findings if f.is_proven}
        assert proven_rules == {RULE_PROVEN_AUTH_BYPASS, RULE_PROVEN_INPUT_INJECTION}
        # And every proven finding carries the probe evidence that justifies it.
        for f in report.findings:
            if f.is_proven:
                assert f.probe is not None and f.probe.observed

    _run(scenario())


def test_probe_rules_skipped_when_no_probe_evidence():
    # Without probe evidence, the REQUIRES_PROBE rules are skipped-and-reported, never proven.
    report = tp.run_trust_posture(tp.PostureContext(surface=_surface()))
    assert report.proven_count == 0
    assert RULE_PROVEN_AUTH_BYPASS in report.skipped_rules
    assert RULE_PROVEN_INPUT_INJECTION in report.skipped_rules
    for rid in (RULE_PROVEN_AUTH_BYPASS, RULE_PROVEN_INPUT_INJECTION):
        assert rid in report.skip_reasons
