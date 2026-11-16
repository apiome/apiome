"""Shared probe consent, limits and guardrails — ASP-4.1 (#5939).

CLX-3.3 (#4857) built the safety model an active probe has to pass before it may send a single
request: an allowlisted target, a declared owner, an acknowledging user, a dedicated test identity,
a stronger per-run approval for hostile payloads, a global kill switch, per-tenant concurrency and
hourly caps, and per-run :class:`ProbeLimits` that :class:`CountingTransport` *enforces* rather than
records. It was written for MCP endpoints, inside :mod:`app.mcp_probe`.

REST security probes (ASP-4.2/4.3) need exactly the same guarantees against ECA-1.2 verification
targets, and a second copy of a safety model is the failure mode the delivery principles forbid: the
two copies drift, and the weaker one is the one an attacker finds. So the model lives here, once,
keyed by a **subject kind**:

* :data:`SUBJECT_MCP_ENDPOINT` — a catalogued MCP endpoint (``mcp_probe_targets``, V173).
  :mod:`app.mcp_probe` re-exports every name below, so its callers and tests are unchanged.
* :data:`SUBJECT_VERIFICATION_TARGET` — an ECA-1.2 verification target
  (``verification_target_probe_consents``, V386).

What is shared, and what is not
-------------------------------
Shared: the three proof tiers, :class:`ProbeLimits`, :class:`ConsentRecord`, the kill switch and
tenant caps (:class:`GovernorPolicy`, :func:`authorize_active_run`) and :class:`CountingTransport`.

Verification targets only: the stored consent (:class:`TargetProbeConsent`), the REST probe
profiles, the hosted-mock rule and the run gate :func:`authorize_verification_target_probe`. Its
rules, from the roadmap:

* a target whose environment is ``mock`` **and** whose base URL is the Apiome-hosted mock origin
  needs no consent row, is still rate-limited, and can only yield ``observed`` findings — a mock
  proves nothing about the real deployment's enforcement;
* any other target needs a live (unrevoked, unexpired) consent that lists the profile;
* the ``payload`` profile also needs the per-run approval flag, copied into the audit;
* the kill switch (``security_probe_enabled``) defaults to **off** and, while off, refuses every
  non-mock run for every tenant.

This module is pure: no database, no clock, no settings. The caller supplies ``now``, the policy and
the usage, so every rule is testable in isolation; :mod:`app.probe_consent_store` reads them from the
database and settings and writes the audit rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple
from urllib.parse import urlsplit

# =================================================================================================
# Subjects — what a consent is about.
# =================================================================================================

#: A catalogued MCP endpoint (CLX-3.3). The default, so every pre-existing caller keeps its meaning.
SUBJECT_MCP_ENDPOINT = "mcp_endpoint"

#: An ECA-1.2 verification target (ASP-4.1).
SUBJECT_VERIFICATION_TARGET = "verification_target"

#: Every subject kind a consent or a governor policy may name.
SUBJECT_KINDS: Tuple[str, ...] = (SUBJECT_MCP_ENDPOINT, SUBJECT_VERIFICATION_TARGET)


def _require_subject_kind(subject_kind: str) -> None:
    """Raise ``ValueError`` unless ``subject_kind`` is one of :data:`SUBJECT_KINDS`."""
    if subject_kind not in SUBJECT_KINDS:
        raise ValueError(
            f"unknown probe subject kind {subject_kind!r}; known: {list(SUBJECT_KINDS)}"
        )


# =================================================================================================
# Classification — the three tiers of proof a probe result can carry.
# =================================================================================================
# The axis the whole feature turns on, so it is modelled as first-class data, ordered
# weakest-to-strongest. It is shared because a verification-target run's *proof ceiling* (the
# hosted mock caps it at observed) is expressed on the same scale the MCP probes report on.

#: A static signal — a pattern that *indicates* a risk without demonstrating it. This is what the
#: static engines emit; probes never downgrade to it, but it is part of the shared taxonomy so a UI
#: can render all three tiers on one scale.
CLASS_SUSPECTED = "suspected"

#: A probe *observed* the server do the risky thing — e.g. accept a malformed request a conformant
#: server would reject, or echo a mismatched id. The behaviour is real and was witnessed, but nothing
#: was exploited and no harm was demonstrated.
CLASS_OBSERVED = "observed"

#: A probe *demonstrated* the defect against a live server in isolation: a canary was reflected, an
#: unauthorized call returned data, an injected instruction was honoured. This is the only tier that
#: becomes :class:`~app.mcp_trust_posture.ProbeEvidence`.
CLASS_EXPLOITED_IN_TEST = "exploited-in-test"

#: Every classification, weakest first. The order is load-bearing: :func:`class_rank` compares by
#: index, so a report can say "the strongest thing we proved here was *observed*".
CLASSIFICATIONS: Tuple[str, ...] = (CLASS_SUSPECTED, CLASS_OBSERVED, CLASS_EXPLOITED_IN_TEST)

#: Human labels. As with CLX-3.2's exploitability labels, the wording is deliberately explicit so a
#: reader skimming red chips cannot come away believing an *observed* behaviour was *exploited*.
CLASSIFICATION_LABELS: Mapping[str, str] = {
    CLASS_SUSPECTED: "Suspected — static signal, not probed",
    CLASS_OBSERVED: "Observed — probe witnessed the behaviour",
    CLASS_EXPLOITED_IN_TEST: "Exploited in test — probe demonstrated it against an isolated server",
}


def class_rank(classification: str) -> int:
    """Return the strength ordinal of a classification (higher = stronger proof).

    Args:
        classification: One of :data:`CLASSIFICATIONS`.

    Returns:
        Its index in :data:`CLASSIFICATIONS`.

    Raises:
        ValueError: If ``classification`` is not a known tier.
    """
    return CLASSIFICATIONS.index(classification)


# =================================================================================================
# Profiles — the minimum a consent check needs to know about one.
# =================================================================================================


class ConsentProfile(Protocol):
    """The fields consent and governor checks read from a profile.

    :class:`app.mcp_probe.ProbeProfile` and :class:`TargetProbeProfile` both satisfy it, which is
    what lets one :meth:`ConsentRecord.validate` and one :func:`authorize_active_run` serve both
    subject kinds.
    """

    profile_id: str
    sends_requests: bool
    requires_consent: bool
    requires_explicit_approval: bool


# =================================================================================================
# Limits — the hard caps every active run carries.
# =================================================================================================


@dataclass(frozen=True)
class ProbeLimits:
    """The hard resource ceilings a single probe run must not exceed.

    Recorded into the audit envelope (AC2: "record ... limits ... in evidence") and enforced by the
    transport wrapper (:class:`CountingTransport`) so an over-budget run *stops* rather than merely
    being noted after the fact.

    Attributes:
        max_requests: The most JSON-RPC requests the whole run may send. A hard stop, not a target.
        rate_per_minute: The most requests per minute the run may send (client-side pacing; the
            per-tenant governor enforces the cross-run rate separately).
        wall_clock_seconds: The most wall-clock seconds the run may take before it is aborted.
        max_response_bytes: The largest single response the run will read before treating it as an
            abuse signal and stopping — a server that answers a 10-byte probe with a gigabyte is
            attacking the prober.
    """

    max_requests: int = 50
    rate_per_minute: int = 60
    wall_clock_seconds: int = 30
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name in ("max_requests", "rate_per_minute", "wall_clock_seconds", "max_response_bytes"):
            if getattr(self, name) <= 0:
                raise ValueError(f"probe limit '{name}' must be positive")

    def as_dict(self) -> Dict[str, Any]:
        """Return the limits as a JSON-ready dict."""
        return {
            "max_requests": self.max_requests,
            "rate_per_minute": self.rate_per_minute,
            "wall_clock_seconds": self.wall_clock_seconds,
            "max_response_bytes": self.max_response_bytes,
        }


#: The default limits an active run gets when a caller names none. Deliberately small: a probe run is
#: a diagnostic, not a load test, and a conservative default is the safe one to have to raise
#: explicitly rather than to have to remember to lower.
DEFAULT_LIMITS = ProbeLimits()


# =================================================================================================
# Consent — the record that must exist before an active probe may run.
# =================================================================================================
# Every field the consent model needs is a required field here, and validate() refuses the run if the
# profile needs consent and any of them is missing. The record is copied verbatim into the audit
# envelope, so the evidence always answers "who authorized firing what at whom, under what limits, as
# which identity".

TRANSPORT_HTTP = "http"
TRANSPORT_STDIO = "stdio"
TRANSPORTS: Tuple[str, ...] = (TRANSPORT_HTTP, TRANSPORT_STDIO)


class ConsentError(ValueError):
    """Raised when an active profile is asked to run without valid consent for it."""


@dataclass(frozen=True)
class ConsentRecord:
    """Operator authorization to run active probes against one target.

    Attributes:
        target_endpoint_id: The subject under test — the catalogued MCP endpoint id for
            :data:`SUBJECT_MCP_ENDPOINT`, the verification target id for
            :data:`SUBJECT_VERIFICATION_TARGET` (the field keeps its CLX-3.3 name so every existing
            caller and audit row is unchanged; :attr:`subject_id` is the neutral alias).
        target_locator: The resolved target — a URL for an ``http`` server, a command reference for a
            ``stdio`` one. Recorded so the audit says exactly what was contacted, not just an id.
        transport: :data:`TRANSPORT_HTTP` or :data:`TRANSPORT_STDIO`. Decides whether an isolation
            sandbox is mandatory (stdio runs untrusted code locally; http contacts a remote host).
        allowlisted: Whether the target is on the tenant's probe allowlist. A run against a
            non-allowlisted target is refused even with every other field present — you may only fire
            at hosts someone explicitly enrolled.
        ownership_declared: Whether the operator has asserted they own, or are authorized to test,
            the target. Probing a system you do not control is an attack; this is the record that you
            said you do.
        test_identity: The id of the *dedicated test credential* the run authenticates with. Never a
            production credential — a probe must not act as a real user. ``None`` is allowed only for
            an unauthenticated target.
        dedicated_credentials: Whether ``test_identity`` names a credential provisioned specifically
            for probing (as opposed to a reused production one). Required true when a test identity is
            present.
        acknowledged_by: The user id that acknowledged the run. Required for any consent record.
        acknowledged_at: When it was acknowledged (ISO-8601, supplied by the caller so this module
            stays clock-free and its evidence stays reproducible in tests).
        explicit_approval: The stronger, per-run acknowledgement payload fuzzing requires — a
            separate flag from ``acknowledged_by`` so "I logged in" can never be mistaken for "I
            approved firing hostile payloads".
        subject_kind: What ``target_endpoint_id`` names (:data:`SUBJECT_KINDS`). Defaults to
            :data:`SUBJECT_MCP_ENDPOINT`, the only kind before ASP-4.1.
    """

    target_endpoint_id: str
    target_locator: str
    transport: str
    allowlisted: bool
    ownership_declared: bool
    acknowledged_by: str
    acknowledged_at: str
    test_identity: Optional[str] = None
    dedicated_credentials: bool = False
    explicit_approval: bool = False
    subject_kind: str = SUBJECT_MCP_ENDPOINT

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(
                f"consent declares unknown transport {self.transport!r}; known: {list(TRANSPORTS)}"
            )
        _require_subject_kind(self.subject_kind)

    @property
    def subject_id(self) -> str:
        """The id of the subject under test, whatever its kind."""
        return self.target_endpoint_id

    def validate(self, profile: ConsentProfile) -> None:
        """Raise :class:`ConsentError` unless this record authorizes ``profile``.

        A profile that ``sends_requests`` is only allowed to run when the target was allowlisted, the
        operator declared ownership, the run was acknowledged, and — when a test identity is used — it
        is a dedicated credential. Payload fuzzing additionally demands ``explicit_approval``. A
        passive profile needs none of this and this method is a no-op for it.

        Args:
            profile: The profile about to run.

        Raises:
            ConsentError: If any required element of consent for ``profile`` is missing.
        """
        if not profile.requires_consent:
            return
        problems: List[str] = []
        if not self.allowlisted:
            problems.append("target is not on the tenant probe allowlist")
        if not self.ownership_declared:
            problems.append("operator has not declared ownership/authorization of the target")
        if not self.acknowledged_by:
            problems.append("run was not acknowledged by a user")
        if self.test_identity is not None and not self.dedicated_credentials:
            problems.append(
                "test identity is not a dedicated probe credential (production credentials may not "
                "be used for probing)"
            )
        if profile.requires_explicit_approval and not self.explicit_approval:
            problems.append(
                "payload fuzzing requires explicit per-run approval, which was not given"
            )
        if problems:
            raise ConsentError(
                f"consent does not authorize the '{profile.profile_id}' profile: "
                + "; ".join(problems)
            )

    def as_dict(self) -> Dict[str, Any]:
        """Return the consent record as a JSON-ready dict (goes verbatim into the audit envelope)."""
        return {
            "subject_kind": self.subject_kind,
            "target_endpoint_id": self.target_endpoint_id,
            "target_locator": self.target_locator,
            "transport": self.transport,
            "allowlisted": self.allowlisted,
            "ownership_declared": self.ownership_declared,
            "test_identity": self.test_identity,
            "dedicated_credentials": self.dedicated_credentials,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at,
            "explicit_approval": self.explicit_approval,
        }


# =================================================================================================
# Kill switch + per-tenant governor.
# =================================================================================================
# The governor is kept as a *pure decision function over supplied usage*, not a stateful object that
# owns counters — the route layer reads the live counts from the audit/report table and hands them
# in, so the same policy is testable in isolation and there is one source of truth (the DB) for how
# many runs a tenant already has.

#: The settings flag that is each subject kind's kill switch — named in the refusal so an operator
#: knows which flag to flip.
KILL_SWITCH_SETTINGS: Mapping[str, str] = {
    SUBJECT_MCP_ENDPOINT: "mcp_probe_enabled",
    SUBJECT_VERIFICATION_TARGET: "security_probe_enabled",
}

#: What the kill switch stops, per subject kind, for the refusal message.
_KILL_SWITCH_FEATURES: Mapping[str, str] = {
    SUBJECT_MCP_ENDPOINT: "MCP active probing",
    SUBJECT_VERIFICATION_TARGET: "REST security probing",
}

#: What still runs while the kill switch is off, per subject kind.
_KILL_SWITCH_EXEMPT: Mapping[str, str] = {
    SUBJECT_MCP_ENDPOINT: "only the read-only passive profile may run",
    SUBJECT_VERIFICATION_TARGET: "only runs against the Apiome-hosted mock may proceed",
}


@dataclass(frozen=True)
class GovernorPolicy:
    """The global and per-tenant guardrails an active run is checked against.

    Attributes:
        enabled: The global kill switch. When ``False`` *no* active probe runs for *any* tenant,
            regardless of consent — the single flag an operator flips to stop the feature dead during
            an incident. Passive runs are unaffected (they send nothing), which is what lets the
            catalog keep classifying observed behaviour while active probing is frozen.
        max_concurrent_per_tenant: The most active runs one tenant may have in flight at once.
        max_runs_per_hour_per_tenant: The most active runs one tenant may start per rolling hour.
        subject_kind: Which subject the policy governs; picks the kill-switch flag a refusal names.
    """

    enabled: bool = False
    max_concurrent_per_tenant: int = 2
    max_runs_per_hour_per_tenant: int = 20
    subject_kind: str = SUBJECT_MCP_ENDPOINT

    def __post_init__(self) -> None:
        _require_subject_kind(self.subject_kind)

    @property
    def kill_switch_setting(self) -> str:
        """The settings flag this policy's ``enabled`` was read from."""
        return KILL_SWITCH_SETTINGS[self.subject_kind]


@dataclass(frozen=True)
class TenantUsage:
    """The live usage the route layer reads from the audit trail and hands to the governor.

    Attributes:
        active_runs: How many of this tenant's runs are currently in flight.
        runs_last_hour: How many runs this tenant started in the trailing hour.
    """

    active_runs: int = 0
    runs_last_hour: int = 0


class KillSwitchError(RuntimeError):
    """Raised when an active probe is requested while the global kill switch is off."""


class RateLimitError(RuntimeError):
    """Raised when a tenant is over its concurrency or hourly run limit."""


def check_kill_switch(policy: GovernorPolicy) -> None:
    """Refuse when the global kill switch for ``policy.subject_kind`` is off.

    Args:
        policy: The guardrails in force.

    Raises:
        KillSwitchError: If ``policy.enabled`` is ``False``.
    """
    if policy.enabled:
        return
    raise KillSwitchError(
        f"{_KILL_SWITCH_FEATURES[policy.subject_kind]} is disabled by the global kill switch "
        f"({policy.kill_switch_setting}=false); {_KILL_SWITCH_EXEMPT[policy.subject_kind]}"
    )


def check_tenant_caps(policy: GovernorPolicy, usage: TenantUsage) -> None:
    """Refuse when the tenant is at its concurrency or hourly run cap.

    Separate from :func:`check_kill_switch` because the hosted mock is exempt from the kill switch
    but never from the caps — a mock run still costs the shared runtime.

    Args:
        policy: The guardrails in force.
        usage: The tenant's live in-flight and trailing-hour run counts.

    Raises:
        RateLimitError: If either cap is reached.
    """
    if usage.active_runs >= policy.max_concurrent_per_tenant:
        raise RateLimitError(
            f"tenant already has {usage.active_runs} active probe run(s) in flight; the limit is "
            f"{policy.max_concurrent_per_tenant}"
        )
    if usage.runs_last_hour >= policy.max_runs_per_hour_per_tenant:
        raise RateLimitError(
            f"tenant has started {usage.runs_last_hour} probe run(s) in the last hour; the limit is "
            f"{policy.max_runs_per_hour_per_tenant}"
        )


def authorize_active_run(
    profile: ConsentProfile, policy: GovernorPolicy, usage: TenantUsage
) -> None:
    """Gate an active run on the kill switch and the tenant's concurrency/rate budget.

    A no-op for a profile that sends nothing — the kill switch and rate limits govern *traffic*, and
    a passive run produces none, so freezing active probing never blinds the passive lane.

    Args:
        profile: The profile about to run.
        policy: The global/per-tenant guardrails.
        usage: The tenant's live in-flight and trailing-hour run counts.

    Raises:
        KillSwitchError: If ``profile`` sends requests and the kill switch is off.
        RateLimitError: If the tenant is at its concurrency or hourly limit.
    """
    if not profile.sends_requests:
        return
    check_kill_switch(policy)
    check_tenant_caps(policy, usage)


# =================================================================================================
# Transport budget — enforced at the one point all traffic passes.
# =================================================================================================


class SizedResponse(Protocol):
    """Anything a probe transport returns: it must say how many bytes it read."""

    response_bytes: int


class LimitExceededError(RuntimeError):
    """Raised by :class:`CountingTransport` when a run would exceed its request or byte budget."""


class CountingTransport:
    """A transport wrapper that *enforces* :class:`ProbeLimits` rather than merely recording them.

    Wrapping the injected transport here means every probe, however written, is bounded by the same
    counter — a probe cannot bust the request cap by looping, because the cap lives in the wrapper it
    has to call through, not in each probe's good intentions.

    The wrapper is shape-agnostic: it forwards whatever arguments its inner transport's ``send``
    takes (a JSON-RPC ``method, params`` for MCP; an HTTP request for REST probes) and only reads the
    response's ``response_bytes``.

    Attributes:
        request_count: How many requests have been sent so far (read into the audit envelope).
    """

    def __init__(self, inner: Any, limits: ProbeLimits) -> None:
        self._inner = inner
        self._limits = limits
        self.request_count = 0

    @property
    def limits(self) -> ProbeLimits:
        """The limits this wrapper enforces."""
        return self._limits

    async def send(self, *args: Any, **kwargs: Any) -> Any:
        """Send through the inner transport after checking, and then updating, the request budget.

        Args:
            *args: Forwarded to the inner transport's ``send``.
            **kwargs: Forwarded to the inner transport's ``send``.

        Returns:
            The inner transport's response.

        Raises:
            LimitExceededError: If the request cap is already reached, or the response exceeds the
                byte cap (a server answering a tiny probe with an enormous body is an abuse signal,
                so the run stops rather than reads it).
        """
        if self.request_count >= self._limits.max_requests:
            raise LimitExceededError(
                f"probe run reached its request cap of {self._limits.max_requests}"
            )
        self.request_count += 1
        response = await self._inner.send(*args, **kwargs)
        response_bytes = int(getattr(response, "response_bytes", 0) or 0)
        if response_bytes > self._limits.max_response_bytes:
            raise LimitExceededError(
                f"a probe response of {response_bytes} bytes exceeded the cap of "
                f"{self._limits.max_response_bytes}; the run was stopped"
            )
        return response


# =================================================================================================
# Verification targets — REST probe profiles.
# =================================================================================================
# Every REST probe sends HTTP traffic to a deployment, so unlike the MCP passive profile none of them
# is consent-free: what separates them is how invasive the traffic is, and only ``payload`` needs the
# stronger per-run approval. ASP-4.2/4.3 assign each probe to one of these.

#: Read-only requests the contract already describes (safe methods, a TLS handshake).
TARGET_PROFILE_PASSIVE = "passive"

#: Benign but non-conformant requests: missing or unsigned credentials, a malformed body, a bounded
#: burst.
TARGET_PROFILE_SAFE_ACTIVE = "safe-active"

#: Crafted hostile payloads. Needs the per-run approval flag on top of a live consent.
TARGET_PROFILE_PAYLOAD = "payload"


@dataclass(frozen=True)
class TargetProbeProfile:
    """A REST probe profile, as consent and the governor see it.

    Attributes:
        profile_id: Stable id (``--profile``, ``profiles_allowed``).
        label: Human-readable name.
        description: What traffic the profile sends.
        invasiveness: Ordinal, weakest first.
        requires_explicit_approval: Whether a run needs the per-run approval flag.
        sends_requests: Always ``True`` — every REST probe sends traffic.
        requires_consent: Always ``True`` off the hosted mock.
    """

    profile_id: str
    label: str
    description: str
    invasiveness: int
    requires_explicit_approval: bool = False
    sends_requests: bool = True
    requires_consent: bool = True

    def as_dict(self) -> Dict[str, Any]:
        """Return the profile as a JSON-ready dict."""
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "description": self.description,
            "invasiveness": self.invasiveness,
            "requires_explicit_approval": self.requires_explicit_approval,
        }


TARGET_PROFILES: Mapping[str, TargetProbeProfile] = {
    TARGET_PROFILE_PASSIVE: TargetProbeProfile(
        profile_id=TARGET_PROFILE_PASSIVE,
        label="Passive",
        description="Read-only requests the contract already describes, and a TLS handshake.",
        invasiveness=0,
    ),
    TARGET_PROFILE_SAFE_ACTIVE: TargetProbeProfile(
        profile_id=TARGET_PROFILE_SAFE_ACTIVE,
        label="Safe active",
        description=(
            "Benign but non-conformant requests: no or unsigned credentials, malformed bodies, a "
            "bounded burst."
        ),
        invasiveness=1,
    ),
    TARGET_PROFILE_PAYLOAD: TargetProbeProfile(
        profile_id=TARGET_PROFILE_PAYLOAD,
        label="Payload",
        description="Crafted hostile payloads. Needs explicit approval on every run.",
        invasiveness=2,
        requires_explicit_approval=True,
    ),
}

#: Profile ids in invasiveness order — the closed vocabulary of ``profiles_allowed`` (V386 CHECK).
TARGET_PROFILE_IDS: Tuple[str, ...] = (
    TARGET_PROFILE_PASSIVE,
    TARGET_PROFILE_SAFE_ACTIVE,
    TARGET_PROFILE_PAYLOAD,
)

#: The verification-target environment that may be the hosted mock (ECA-1.2's vocabulary).
ENVIRONMENT_MOCK = "mock"

#: The environment whose consent only a tenant administrator may grant.
ENVIRONMENT_PRODUCTION = "production"


# =================================================================================================
# Verification targets — refusals.
# =================================================================================================

#: The global kill switch is off and the target is not the hosted mock.
CODE_KILL_SWITCH_OFF = "probe-kill-switch-off"
#: The tenant is at its concurrency or hourly cap.
CODE_RATE_LIMITED = "probe-rate-limited"
#: The profile id is not one of :data:`TARGET_PROFILE_IDS`.
CODE_UNKNOWN_PROFILE = "probe-unknown-profile"
#: The target needs a consent and has none.
CODE_CONSENT_MISSING = "probe-consent-missing"
#: The target's consent has been revoked.
CODE_CONSENT_REVOKED = "probe-consent-revoked"
#: The target's consent has passed its ``expires_at``.
CODE_CONSENT_EXPIRED = "probe-consent-expired"
#: The consent is for a different target (a caller bug; refused rather than trusted).
CODE_CONSENT_TARGET_MISMATCH = "probe-consent-target-mismatch"
#: The consent does not list the requested profile.
CODE_PROFILE_NOT_CONSENTED = "probe-profile-not-consented"
#: The consent has no ownership declaration.
CODE_OWNERSHIP_NOT_DECLARED = "probe-ownership-not-declared"
#: A ``payload`` run without the per-run approval flag.
CODE_APPROVAL_REQUIRED = "probe-approval-required"

#: Every refusal code, for documentation and tests.
REFUSAL_CODES: Tuple[str, ...] = (
    CODE_KILL_SWITCH_OFF,
    CODE_RATE_LIMITED,
    CODE_UNKNOWN_PROFILE,
    CODE_CONSENT_MISSING,
    CODE_CONSENT_REVOKED,
    CODE_CONSENT_EXPIRED,
    CODE_CONSENT_TARGET_MISMATCH,
    CODE_PROFILE_NOT_CONSENTED,
    CODE_OWNERSHIP_NOT_DECLARED,
    CODE_APPROVAL_REQUIRED,
)


class ProbeRefusalError(Exception):
    """A verification-target probe run was refused, with a stable code.

    Attributes:
        code: One of :data:`REFUSAL_CODES`.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# =================================================================================================
# Verification targets — the stored consent and the run gate.
# =================================================================================================


@dataclass(frozen=True)
class TargetProbeConsent:
    """A stored ``verification_target_probe_consents`` row, as the gate reads it.

    Identities are carried as the ECA-1.2 credential *reference* dicts (``kind``/``scheme``/``ref``/
    ``header_name``) — never a secret; this module only records whether they are present.

    Attributes:
        consent_id: Row id, recorded on every run it authorizes.
        target_id: The verification target the consent is for.
        ownership_declared: The grantor's assertion that they own or may test the target.
        approved_by: User id that granted it.
        approved_at: When it was granted.
        expires_at: When it stops authorizing runs. Required — a consent never lasts forever.
        profiles_allowed: The profile ids it authorizes.
        identity_a: Primary test identity reference, when one was named.
        identity_b: Second test identity reference (ASP-4.3's BOLA/BFLA probes), when named.
        revoked_at: When it was revoked, or ``None`` while live.
    """

    consent_id: str
    target_id: str
    ownership_declared: bool
    approved_by: Optional[str]
    approved_at: datetime
    expires_at: datetime
    profiles_allowed: Tuple[str, ...]
    identity_a: Optional[Mapping[str, Any]] = None
    identity_b: Optional[Mapping[str, Any]] = None
    revoked_at: Optional[datetime] = None

    def status(self, now: datetime) -> str:
        """Return ``revoked``, ``expired`` or ``active`` at ``now``.

        Args:
            now: The current time (timezone-aware, like the stored columns).

        Returns:
            The consent's state.
        """
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= now:
            return "expired"
        return "active"


@dataclass(frozen=True)
class ProbeTargetSubject:
    """The verification-target facts the gate needs.

    Attributes:
        target_id: The target id.
        environment: ECA-1.2 environment class (``mock`` … ``production``).
        base_url: The target's base URL.
    """

    target_id: str
    environment: str
    base_url: str


def _origin(url: str) -> Optional[Tuple[str, str, int]]:
    """Return ``(scheme, host, port)`` for an http(s) URL, with the default port filled in.

    Args:
        url: Any URL.

    Returns:
        The normalized origin, or ``None`` when the URL has no http(s) scheme or host.
    """
    try:
        parts = urlsplit(str(url or "").strip())
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def is_hosted_mock(target: ProbeTargetSubject, mock_origin: Optional[str]) -> bool:
    """True when ``target`` is the Apiome-hosted mock and so needs no consent.

    Both halves are required: the environment must be ``mock`` **and** the base URL's origin must be
    the hosted mock's. An environment label alone is something any tenant can type, so a target that
    merely *says* ``mock`` while pointing at a real host gets no exemption.

    Args:
        target: The target under test.
        mock_origin: The hosted mock's public base URL (``settings.mock_public_base_url``).

    Returns:
        Whether the consent exemption applies.
    """
    if target.environment != ENVIRONMENT_MOCK or not mock_origin:
        return False
    target_origin = _origin(target.base_url)
    return target_origin is not None and target_origin == _origin(mock_origin)


@dataclass(frozen=True)
class ProbeAuthorization:
    """An allowed verification-target run, and the terms it runs under.

    Attributes:
        target_id: The target under test.
        profile_id: The profile that will run.
        hosted_mock: Whether the hosted-mock exemption applied (no consent row needed).
        consent_id: The consent that authorized it; ``None`` on the hosted mock.
        proof_ceiling: The strongest tier the run may report — ``observed`` on the hosted mock,
            ``exploited-in-test`` otherwise.
        explicit_approval: The per-run approval flag as the caller sent it (copied into the audit).
        limits: The per-run limits :class:`CountingTransport` will enforce.
        identities: Which consent identities are available (``identity_a``/``identity_b``).
    """

    target_id: str
    profile_id: str
    hosted_mock: bool
    consent_id: Optional[str]
    proof_ceiling: str
    explicit_approval: bool
    limits: ProbeLimits
    identities: Tuple[str, ...] = field(default_factory=tuple)

    def permits(self, classification: str) -> bool:
        """True when ``classification`` is within this run's proof ceiling."""
        return class_rank(classification) <= class_rank(self.proof_ceiling)

    def as_dict(self) -> Dict[str, Any]:
        """Return the authorization as a JSON-ready dict (audit detail and report header)."""
        return {
            "subject_kind": SUBJECT_VERIFICATION_TARGET,
            "target_id": self.target_id,
            "profile": self.profile_id,
            "hosted_mock": self.hosted_mock,
            "consent_id": self.consent_id,
            "proof_ceiling": self.proof_ceiling,
            "proof_ceiling_label": CLASSIFICATION_LABELS[self.proof_ceiling],
            "explicit_approval": self.explicit_approval,
            "limits": self.limits.as_dict(),
            "identities": list(self.identities),
        }


#: Why a hosted-mock run is capped at observed — shown in the report so the ceiling is explained.
MOCK_CEILING_REASON = (
    "The target is the Apiome-hosted mock, which serves the contract rather than the real "
    "deployment, so a probe can observe how the contract behaves but cannot prove the deployment "
    "enforces it."
)


def resolve_target_profile(profile_id: Optional[str]) -> TargetProbeProfile:
    """Return the REST probe profile for ``profile_id`` (``passive`` when ``None``).

    Args:
        profile_id: A profile id, or ``None`` for the default.

    Returns:
        The profile.

    Raises:
        ProbeRefusalError: :data:`CODE_UNKNOWN_PROFILE` for an id outside :data:`TARGET_PROFILE_IDS`.
    """
    key = profile_id or TARGET_PROFILE_PASSIVE
    try:
        return TARGET_PROFILES[key]
    except KeyError as exc:
        raise ProbeRefusalError(
            CODE_UNKNOWN_PROFILE,
            f"unknown probe profile '{key}'; known profiles: {list(TARGET_PROFILE_IDS)}",
        ) from exc


def _check_consent(
    consent: Optional[TargetProbeConsent],
    target: ProbeTargetSubject,
    profile: TargetProbeProfile,
    now: datetime,
) -> TargetProbeConsent:
    """Return ``consent`` when it authorizes ``profile`` against ``target`` at ``now``.

    Raises:
        ProbeRefusalError: With the code naming the first rule the consent fails.
    """
    if consent is None:
        raise ProbeRefusalError(
            CODE_CONSENT_MISSING,
            f"target {target.target_id} ({target.environment}) has no probe consent; grant one "
            "before probing anything other than the Apiome-hosted mock",
        )
    if str(consent.target_id) != str(target.target_id):
        raise ProbeRefusalError(
            CODE_CONSENT_TARGET_MISMATCH,
            "the probe consent supplied is for a different target",
        )
    state = consent.status(now)
    if state == "revoked":
        raise ProbeRefusalError(CODE_CONSENT_REVOKED, "the target's probe consent has been revoked")
    if state == "expired":
        raise ProbeRefusalError(
            CODE_CONSENT_EXPIRED,
            f"the target's probe consent expired at {consent.expires_at.isoformat()}",
        )
    if not consent.ownership_declared:
        raise ProbeRefusalError(
            CODE_OWNERSHIP_NOT_DECLARED,
            "the probe consent does not declare ownership of the target",
        )
    if profile.profile_id not in consent.profiles_allowed:
        raise ProbeRefusalError(
            CODE_PROFILE_NOT_CONSENTED,
            f"the probe consent allows {list(consent.profiles_allowed)}, not "
            f"'{profile.profile_id}'",
        )
    return consent


def authorize_verification_target_probe(
    *,
    target: ProbeTargetSubject,
    consent: Optional[TargetProbeConsent],
    profile_id: Optional[str],
    explicit_approval: bool,
    policy: GovernorPolicy,
    usage: TenantUsage,
    now: datetime,
    mock_origin: Optional[str],
    limits: ProbeLimits = DEFAULT_LIMITS,
) -> ProbeAuthorization:
    """Decide whether a probe run against a verification target may start.

    The checks run in a fixed order, so a refusal always names the most fundamental problem:

    1. the profile must exist;
    2. ``payload`` needs the per-run approval flag (on every target, the mock included — the flag is
       an assertion about intent, not about the target);
    3. the hosted mock skips the kill switch and the consent but never the tenant caps, and its
       ceiling is ``observed``;
    4. every other target needs the kill switch on, the tenant under its caps, and a live consent
       that declares ownership and lists the profile; its ceiling is ``exploited-in-test``.

    Args:
        target: The target under test.
        consent: The target's current consent row, or ``None``.
        profile_id: The requested profile (``passive`` when ``None``).
        explicit_approval: The caller's per-run approval flag.
        policy: Kill switch and caps (``subject_kind`` should be verification_target).
        usage: The tenant's live run counts.
        now: The current time (timezone-aware).
        mock_origin: The hosted mock's public base URL.
        limits: The per-run limits to carry.

    Returns:
        The authorization.

    Raises:
        ProbeRefusalError: With a stable code from :data:`REFUSAL_CODES`.
    """
    profile = resolve_target_profile(profile_id)
    if profile.requires_explicit_approval and not explicit_approval:
        raise ProbeRefusalError(
            CODE_APPROVAL_REQUIRED,
            f"the '{profile.profile_id}' profile sends hostile payloads and needs explicit "
            "approval on every run",
        )

    hosted_mock = is_hosted_mock(target, mock_origin)
    if not hosted_mock:
        try:
            check_kill_switch(policy)
        except KillSwitchError as exc:
            raise ProbeRefusalError(CODE_KILL_SWITCH_OFF, str(exc)) from exc
    try:
        check_tenant_caps(policy, usage)
    except RateLimitError as exc:
        raise ProbeRefusalError(CODE_RATE_LIMITED, str(exc)) from exc

    if hosted_mock:
        return ProbeAuthorization(
            target_id=str(target.target_id),
            profile_id=profile.profile_id,
            hosted_mock=True,
            consent_id=None,
            proof_ceiling=CLASS_OBSERVED,
            explicit_approval=bool(explicit_approval),
            limits=limits,
        )

    granted = _check_consent(consent, target, profile, now)
    identities = tuple(
        name
        for name, ref in (("identity_a", granted.identity_a), ("identity_b", granted.identity_b))
        if ref
    )
    return ProbeAuthorization(
        target_id=str(target.target_id),
        profile_id=profile.profile_id,
        hosted_mock=False,
        consent_id=str(granted.consent_id),
        proof_ceiling=CLASS_EXPLOITED_IN_TEST,
        explicit_approval=bool(explicit_approval),
        limits=limits,
        identities=identities,
    )


def tier_counts(classifications: Sequence[str]) -> Dict[str, int]:
    """Count classifications by tier, with every tier present (zero when absent).

    Args:
        classifications: Tier ids, e.g. each finding's ``classification``.

    Returns:
        ``{tier: count}`` over :data:`CLASSIFICATIONS`.

    Raises:
        ValueError: If a value is not a known tier.
    """
    counts = {tier: 0 for tier in CLASSIFICATIONS}
    for value in classifications:
        if value not in counts:
            raise ValueError(f"unknown proof tier {value!r}; known: {list(CLASSIFICATIONS)}")
        counts[value] += 1
    return counts
