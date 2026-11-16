"""Shared probe consent, limits and the verification-target gate — ASP-4.1 (#5939).

What is pinned here:

* the extraction: :mod:`app.mcp_probe` re-exports the very objects defined in
  :mod:`app.probe_consent` (one safety model, not two copies), and the MCP kill-switch refusal reads
  exactly as it did;
* the shared pieces work for both subject kinds (``subject_kind`` validation, the kill switch naming
  the right flag, :class:`CountingTransport` bounding any transport shape);
* the verification-target gate's acceptance criteria: a staging target without consent is refused
  with a stable code, an expired consent refuses, a mock target runs without consent with
  ``proof_ceiling: observed``, and the kill switch off refuses every non-mock run;
* the hosted-mock exemption needs both the ``mock`` environment and the hosted origin.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from app import mcp_probe as mp
from app import probe_consent as pc

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
MOCK_ORIGIN = "http://localhost:8775"
TARGET_ID = "22222222-2222-4222-8222-222222222222"


def _target(environment: str = "staging", base_url: str = "https://staging.example.com/api"):
    """A verification target as the gate sees it."""
    return pc.ProbeTargetSubject(target_id=TARGET_ID, environment=environment, base_url=base_url)


def _consent(**overrides) -> pc.TargetProbeConsent:
    """A live consent for :data:`TARGET_ID` allowing passive and safe-active."""
    base = dict(
        consent_id="44444444-4444-4444-8444-444444444444",
        target_id=TARGET_ID,
        ownership_declared=True,
        approved_by="33333333-3333-4333-8333-333333333333",
        approved_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=1),
        profiles_allowed=("passive", "safe-active"),
    )
    base.update(overrides)
    return pc.TargetProbeConsent(**base)


def _policy(enabled: bool = True, **overrides) -> pc.GovernorPolicy:
    """A verification-target governor policy."""
    return pc.GovernorPolicy(
        enabled=enabled, subject_kind=pc.SUBJECT_VERIFICATION_TARGET, **overrides
    )


def _authorize(**overrides) -> pc.ProbeAuthorization:
    """Call the gate with sensible defaults."""
    kwargs = dict(
        target=_target(),
        consent=_consent(),
        profile_id="passive",
        explicit_approval=False,
        policy=_policy(),
        usage=pc.TenantUsage(),
        now=NOW,
        mock_origin=MOCK_ORIGIN,
    )
    kwargs.update(overrides)
    return pc.authorize_verification_target_probe(**kwargs)


def _refusal_code(**overrides) -> str:
    """Return the refusal code the gate raises for ``overrides``."""
    with pytest.raises(pc.ProbeRefusalError) as excinfo:
        _authorize(**overrides)
    return excinfo.value.code


# ===========================================================================
# The extraction
# ===========================================================================


@pytest.mark.parametrize(
    "name",
    [
        "ProbeLimits",
        "DEFAULT_LIMITS",
        "ConsentRecord",
        "ConsentError",
        "CountingTransport",
        "LimitExceededError",
        "GovernorPolicy",
        "TenantUsage",
        "KillSwitchError",
        "RateLimitError",
        "authorize_active_run",
        "CLASSIFICATIONS",
        "CLASSIFICATION_LABELS",
        "CLASS_OBSERVED",
        "CLASS_EXPLOITED_IN_TEST",
        "TRANSPORT_HTTP",
        "TRANSPORT_STDIO",
    ],
)
def test_mcp_probe_reexports_the_shared_object_not_a_copy(name: str) -> None:
    assert getattr(mp, name) is getattr(pc, name)


def test_the_mcp_kill_switch_message_is_unchanged() -> None:
    profile = mp.resolve_profile(mp.PROFILE_SAFE_ACTIVE)
    with pytest.raises(pc.KillSwitchError) as excinfo:
        pc.authorize_active_run(profile, pc.GovernorPolicy(enabled=False), pc.TenantUsage())
    assert str(excinfo.value) == (
        "MCP active probing is disabled by the global kill switch (mcp_probe_enabled=false); "
        "only the read-only passive profile may run"
    )


def test_the_verification_target_kill_switch_names_its_own_flag() -> None:
    with pytest.raises(pc.KillSwitchError) as excinfo:
        pc.check_kill_switch(_policy(enabled=False))
    assert "security_probe_enabled=false" in str(excinfo.value)
    assert _policy().kill_switch_setting == "security_probe_enabled"


def test_consent_and_policy_default_to_the_mcp_subject_and_reject_unknown_kinds() -> None:
    record = pc.ConsentRecord(
        target_endpoint_id="ep1",
        target_locator="https://mcp.example.com",
        transport=pc.TRANSPORT_HTTP,
        allowlisted=True,
        ownership_declared=True,
        acknowledged_by="u1",
        acknowledged_at="2026-11-16T00:00:00Z",
    )
    assert record.subject_kind == pc.SUBJECT_MCP_ENDPOINT
    assert record.subject_id == "ep1"
    assert record.as_dict()["subject_kind"] == pc.SUBJECT_MCP_ENDPOINT
    assert pc.GovernorPolicy().subject_kind == pc.SUBJECT_MCP_ENDPOINT
    with pytest.raises(ValueError, match="subject kind"):
        pc.GovernorPolicy(subject_kind="printer")
    with pytest.raises(ValueError, match="subject kind"):
        pc.ConsentRecord(**{**record.__dict__, "subject_kind": "printer"})


def test_consent_record_validates_against_a_rest_profile_too() -> None:
    record = pc.ConsentRecord(
        target_endpoint_id=TARGET_ID,
        target_locator="https://staging.example.com",
        transport=pc.TRANSPORT_HTTP,
        allowlisted=True,
        ownership_declared=True,
        acknowledged_by="u1",
        acknowledged_at="2026-11-16T00:00:00Z",
        subject_kind=pc.SUBJECT_VERIFICATION_TARGET,
    )
    record.validate(pc.TARGET_PROFILES["safe-active"])
    with pytest.raises(pc.ConsentError, match="explicit per-run approval"):
        record.validate(pc.TARGET_PROFILES["payload"])


def test_caps_are_checked_independently_of_the_kill_switch() -> None:
    policy = _policy(enabled=False, max_concurrent_per_tenant=1, max_runs_per_hour_per_tenant=3)
    pc.check_tenant_caps(policy, pc.TenantUsage(active_runs=0, runs_last_hour=2))
    with pytest.raises(pc.RateLimitError, match="in flight"):
        pc.check_tenant_caps(policy, pc.TenantUsage(active_runs=1))
    with pytest.raises(pc.RateLimitError, match="last hour"):
        pc.check_tenant_caps(policy, pc.TenantUsage(runs_last_hour=3))


# ===========================================================================
# CountingTransport is shape-agnostic
# ===========================================================================


@dataclass
class _HttpResponse:
    status: int
    response_bytes: int = 10


class _FakeHttpTransport:
    """An HTTP-shaped transport: send(method, url, headers=...)."""

    def __init__(self, response_bytes: int = 10) -> None:
        self.calls = []
        self._bytes = response_bytes

    async def send(self, method, url, *, headers=None):
        self.calls.append((method, url, headers))
        return _HttpResponse(status=401, response_bytes=self._bytes)


def test_counting_transport_forwards_any_signature_and_stops_at_the_cap() -> None:
    inner = _FakeHttpTransport()
    transport = pc.CountingTransport(inner, pc.ProbeLimits(max_requests=2))

    async def run():
        await transport.send("GET", "https://x/a", headers={"Authorization": "Bearer x.y"})
        await transport.send("GET", "https://x/b")
        await transport.send("GET", "https://x/c")

    with pytest.raises(pc.LimitExceededError, match="request cap of 2"):
        asyncio.run(run())
    assert transport.request_count == 2
    assert [c[1] for c in inner.calls] == ["https://x/a", "https://x/b"]
    assert transport.limits.max_requests == 2


def test_counting_transport_stops_on_an_oversized_response() -> None:
    transport = pc.CountingTransport(
        _FakeHttpTransport(response_bytes=11), pc.ProbeLimits(max_response_bytes=10)
    )
    with pytest.raises(pc.LimitExceededError, match="exceeded the cap"):
        asyncio.run(transport.send("GET", "https://x/a"))


# ===========================================================================
# Hosted mock detection
# ===========================================================================


@pytest.mark.parametrize(
    ("environment", "base_url", "expected"),
    [
        ("mock", "http://localhost:8775/m/acme/petstore", True),
        ("mock", "HTTP://LOCALHOST:8775", True),
        ("mock", "http://localhost:80", False),
        ("mock", "https://localhost:8775", False),
        ("mock", "https://staging.example.com", False),  # says mock, points elsewhere
        ("staging", "http://localhost:8775", False),  # hosted origin, wrong environment
        ("mock", "not a url", False),
    ],
)
def test_the_hosted_mock_needs_both_the_environment_and_the_origin(
    environment: str, base_url: str, expected: bool
) -> None:
    assert pc.is_hosted_mock(_target(environment, base_url), MOCK_ORIGIN) is expected


def test_default_ports_compare_equal() -> None:
    assert pc.is_hosted_mock(_target("mock", "https://mock.apiome.io/x"), "https://mock.apiome.io:443")
    assert not pc.is_hosted_mock(_target("mock", "https://mock.apiome.io"), None)


# ===========================================================================
# The verification-target gate
# ===========================================================================


def test_a_live_consent_authorizes_with_the_exploited_ceiling() -> None:
    auth = _authorize(consent=_consent(identity_a={"kind": "env", "ref": "PROBE_A"}))
    assert auth.consent_id == "44444444-4444-4444-8444-444444444444"
    assert auth.hosted_mock is False
    assert auth.proof_ceiling == pc.CLASS_EXPLOITED_IN_TEST
    assert auth.identities == ("identity_a",)
    assert auth.permits(pc.CLASS_EXPLOITED_IN_TEST)
    body = auth.as_dict()
    assert body["subject_kind"] == pc.SUBJECT_VERIFICATION_TARGET
    assert body["limits"] == pc.DEFAULT_LIMITS.as_dict()


def test_a_staging_target_without_consent_is_refused_with_a_stable_code() -> None:
    assert _refusal_code(consent=None) == pc.CODE_CONSENT_MISSING


def test_an_expired_consent_refuses() -> None:
    assert _refusal_code(consent=_consent(expires_at=NOW)) == pc.CODE_CONSENT_EXPIRED


def test_a_revoked_consent_refuses() -> None:
    code = _refusal_code(consent=_consent(revoked_at=NOW - timedelta(minutes=1)))
    assert code == pc.CODE_CONSENT_REVOKED


def test_a_consent_for_another_target_refuses() -> None:
    code = _refusal_code(consent=_consent(target_id="99999999-9999-4999-8999-999999999999"))
    assert code == pc.CODE_CONSENT_TARGET_MISMATCH


def test_a_profile_outside_the_consent_refuses() -> None:
    code = _refusal_code(profile_id="payload", explicit_approval=True)
    assert code == pc.CODE_PROFILE_NOT_CONSENTED


def test_a_consent_without_ownership_refuses() -> None:
    assert _refusal_code(consent=_consent(ownership_declared=False)) == (
        pc.CODE_OWNERSHIP_NOT_DECLARED
    )


def test_payload_needs_the_per_run_approval_flag() -> None:
    consent = _consent(profiles_allowed=("payload",))
    assert _refusal_code(consent=consent, profile_id="payload") == pc.CODE_APPROVAL_REQUIRED
    auth = _authorize(consent=consent, profile_id="payload", explicit_approval=True)
    assert auth.explicit_approval is True


def test_an_unknown_profile_refuses() -> None:
    assert _refusal_code(profile_id="fuzz-everything") == pc.CODE_UNKNOWN_PROFILE


def test_no_profile_means_passive() -> None:
    assert _authorize(profile_id=None).profile_id == "passive"


def test_a_mock_target_runs_without_consent_and_is_capped_at_observed() -> None:
    auth = _authorize(target=_target("mock", MOCK_ORIGIN + "/m/acme"), consent=None)
    assert auth.hosted_mock is True
    assert auth.consent_id is None
    assert auth.proof_ceiling == pc.CLASS_OBSERVED
    assert not auth.permits(pc.CLASS_EXPLOITED_IN_TEST)
    assert auth.as_dict()["proof_ceiling"] == "observed"


def test_the_kill_switch_off_refuses_every_non_mock_run_but_not_the_mock() -> None:
    off = _policy(enabled=False)
    for environment in ("development", "test", "staging", "production"):
        assert _refusal_code(target=_target(environment), policy=off) == pc.CODE_KILL_SWITCH_OFF
    # A target that only *says* mock is not exempt.
    assert _refusal_code(target=_target("mock"), policy=off) == pc.CODE_KILL_SWITCH_OFF
    auth = _authorize(target=_target("mock", MOCK_ORIGIN), consent=None, policy=off)
    assert auth.hosted_mock is True


def test_the_kill_switch_is_checked_before_consent() -> None:
    assert _refusal_code(consent=None, policy=_policy(enabled=False)) == pc.CODE_KILL_SWITCH_OFF


def test_the_mock_is_still_rate_limited() -> None:
    code = _refusal_code(
        target=_target("mock", MOCK_ORIGIN),
        consent=None,
        usage=pc.TenantUsage(runs_last_hour=20),
    )
    assert code == pc.CODE_RATE_LIMITED


def test_payload_approval_applies_on_the_mock_too() -> None:
    code = _refusal_code(target=_target("mock", MOCK_ORIGIN), consent=None, profile_id="payload")
    assert code == pc.CODE_APPROVAL_REQUIRED


def test_every_refusal_code_is_listed() -> None:
    assert len(set(pc.REFUSAL_CODES)) == len(pc.REFUSAL_CODES)
    assert all(code.startswith("probe-") for code in pc.REFUSAL_CODES)


# ===========================================================================
# Consent status and tier counts
# ===========================================================================


def test_consent_status() -> None:
    assert _consent().status(NOW) == "active"
    assert _consent(expires_at=NOW - timedelta(seconds=1)).status(NOW) == "expired"
    assert _consent(revoked_at=NOW).status(NOW) == "revoked"


def test_tier_counts_fill_every_tier_and_reject_unknowns() -> None:
    assert pc.tier_counts(["observed", "observed", "exploited-in-test"]) == {
        "suspected": 0,
        "observed": 2,
        "exploited-in-test": 1,
    }
    with pytest.raises(ValueError, match="unknown proof tier"):
        pc.tier_counts(["proven"])


def test_target_profiles_are_ordered_and_only_payload_needs_approval() -> None:
    assert pc.TARGET_PROFILE_IDS == ("passive", "safe-active", "payload")
    assert [pc.TARGET_PROFILES[p].invasiveness for p in pc.TARGET_PROFILE_IDS] == [0, 1, 2]
    assert [p for p in pc.TARGET_PROFILE_IDS if pc.TARGET_PROFILES[p].requires_explicit_approval] == [
        "payload"
    ]
    assert pc.TARGET_PROFILES["payload"].as_dict()["requires_explicit_approval"] is True
