"""Consent-gated, sandboxed MCP dynamic probes (CLX-3.3, #4857).

The three prior MCP scan engines are all *static* — they read what the server advertises
(:mod:`app.mcp_lint`), what it did on the wire during ordinary discovery
(:mod:`app.mcp_conformance`), or what it is built from (:mod:`app.mcp_trust_posture`). None of them
can answer the question a security reviewer eventually has to ask: **is this defect actually
reachable?** A tool whose description looks like a prompt-injection vector, a parameter with no
constraints, a manifest that runs a shell command — each is a *signal*, and CLX-3.2 was careful to
render every one of them as exactly that: ``"Signal — not proven exploitable"``. Proving one requires
sending the server something and watching what it does.

That is dangerous in two directions, and this module's entire shape is the response to both:

* **A probe can damage the system under test.** Invoking a business tool with a real payload can
  delete data, spend money, or e-mail a customer. So the default profile
  (:data:`PROFILE_PASSIVE`) never sends a single new request — it re-reads the transcript discovery
  already captured — and no profile is *ever* allowed to invoke a declared business tool with a
  side-effecting payload. Active profiles are opt-in, consent-gated, and rate-capped.

* **A probe can be attacked by the system under test.** A stdio MCP server is *arbitrary code we run
  on our own host*. Fuzzing it means executing untrusted code and feeding it hostile input — the
  server, not us, may end up holding the exploit. So stdio probes may run only inside a disposable,
  least-privilege sandbox (:class:`IsolationSpec`), and this module refuses to hand a stdio target to
  a runner whose isolation is not provably locked down.

The honesty contract inherited from CLX-3.2
-------------------------------------------
CLX-3.2 shipped :func:`app.mcp_trust_posture.make_proven_finding` and
:class:`app.mcp_trust_posture.ProbeEvidence` as a *guarded, unused door*: the only way for a finding
to claim :data:`app.mcp_trust_posture.EXPLOITABILITY_PROVEN`, deliberately with no caller, so the
honest state (``"not proven"``) was the only reachable one until a real probe existed. This module is
that probe. It fills the door — but keeps the guarantee, by classifying every observation into one of
three tiers of proof and only ever minting :class:`~app.mcp_trust_posture.ProbeEvidence` from the
strongest one:

    suspected < observed < exploited-in-test

A ``suspected`` finding is a static signal (what the other engines already emit). ``observed`` means a
probe *watched the server do* the risky thing (e.g. accept a malformed request a correct server
rejects) without anything being exploited. ``exploited-in-test`` means a probe *demonstrated* the
defect against a live server in isolation — a canary was reflected, an unauthorized call succeeded.
Only :data:`CLASS_EXPLOITED_IN_TEST` becomes probe evidence, so the trust-posture report's
``proven_count`` moves only for defects a probe actually demonstrated, never for ones it merely saw.

What is and is not in this module
---------------------------------
This is the **orchestration and evidence layer**: the profiles, the consent gate, the isolation
contract, the per-tenant rate/concurrency governor, the global kill switch, the audit envelope, and
the classification of results into the three tiers. The bytes-on-the-wire runner — the thing that
actually spawns a Firecracker microVM or a locked-down container and speaks JSON-RPC to the server —
is injected as a :class:`ProbeTransport`, so the policy here is testable without real
infrastructure and a future runner swap changes nothing above it. Passive probes need no transport
at all; they read the :class:`~app.mcp_protocol_transcript.ProtocolTranscript` already on disk.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from .mcp_client.normalize import DiscoverySurface
from .mcp_owasp import validate_risk_ids
from .mcp_protocol_transcript import ProtocolTranscript
from .mcp_trust_posture import ProbeEvidence

# =================================================================================================
# Classification — the three tiers of proof a probe result can carry.
# =================================================================================================
# AC4: "Findings distinguish suspected, observed, and exploited-in-test." This is the axis the whole
# feature turns on, so it is modelled as first-class data, ordered weakest-to-strongest, and every
# probe must declare which of the two tiers it is *capable* of reaching (a passive probe can never
# reach exploited-in-test — it sends nothing).

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

#: Every classification, weakest first. The order is load-bearing: :func:`_class_rank` compares by
#: index, so a report can say "the strongest thing we proved here was *observed*".
CLASSIFICATIONS: Tuple[str, ...] = (CLASS_SUSPECTED, CLASS_OBSERVED, CLASS_EXPLOITED_IN_TEST)

#: Human labels. As with CLX-3.2's exploitability labels, the wording is deliberately explicit so a
#: reader skimming red chips cannot come away believing an *observed* behaviour was *exploited*.
CLASSIFICATION_LABELS: Mapping[str, str] = {
    CLASS_SUSPECTED: "Suspected — static signal, not probed",
    CLASS_OBSERVED: "Observed — probe witnessed the behaviour",
    CLASS_EXPLOITED_IN_TEST: "Exploited in test — probe demonstrated it against an isolated server",
}


def _class_rank(classification: str) -> int:
    """Return the strength ordinal of a classification (higher = stronger proof)."""
    return CLASSIFICATIONS.index(classification)


# =================================================================================================
# Profiles — passive / safe-active / payload-fuzzing.
# =================================================================================================
# The three invasiveness levels the ticket calls for. They differ in exactly three ways that matter
# to safety, and each difference is a field rather than a convention: whether they touch the network
# at all, whether they need consent, and the strongest classification they may emit. A passive
# profile that could emit exploited-in-test, or an active one that needed no consent, would be a bug
# the type system should refuse to express — so it can't.

#: Read-only. Sends nothing new; re-reads the captured transcript. No consent, no network, no
#: sandbox, always available (subject only to the kill switch). Never invokes a business tool because
#: it never invokes anything. This is the default and the only profile enabled without explicit,
#: recorded opt-in.
PROFILE_PASSIVE = "passive"

#: Sends *benign, well-formed and mildly-malformed protocol messages* — never a business-tool call
#: with a side-effecting payload. It probes the protocol boundary (does the server reject a duplicate
#: id? a missing required parameter? an unauthenticated privileged method?). Requires a recorded
#: :class:`ConsentRecord`; stdio targets additionally require a validated :class:`IsolationSpec`.
PROFILE_SAFE_ACTIVE = "safe-active"

#: Sends crafted hostile payloads — injection strings, SSRF canaries, oversized fields — to tool
#: *parameters* to demonstrate reachability. The most dangerous profile: it requires explicit,
#: per-run approval (a stronger consent flag than safe-active), a dedicated test identity, and — for
#: any stdio target — a locked-down sandbox. This is where an exploited-in-test finding comes from.
PROFILE_PAYLOAD_FUZZING = "payload-fuzzing"


@dataclass(frozen=True)
class ProbeProfile:
    """A named invasiveness level — the unit the CLI and API run.

    Attributes:
        profile_id: Stable id used on the wire (``--profile``, ``?profile=``).
        label: Human-readable name.
        description: What the profile does and what it costs to run.
        sends_requests: Whether the profile emits any new network traffic. ``False`` only for
            :data:`PROFILE_PASSIVE`; a ``False`` profile can never need consent, a sandbox, or a
            transport, and can never reach :data:`CLASS_EXPLOITED_IN_TEST`.
        requires_consent: Whether a :class:`ConsentRecord` must be present and valid before the
            profile may run at all.
        requires_explicit_approval: Whether the consent must additionally carry the stronger
            per-run ``explicit_approval`` acknowledgement (payload fuzzing only).
        max_classification: The strongest tier a probe under this profile may emit. Enforced in
            :meth:`ProbeReport.assemble`, so a passive probe physically cannot report an exploit.
        invasiveness: Ordinal for ordering and for "is A stronger than B" checks.
    """

    profile_id: str
    label: str
    description: str
    sends_requests: bool
    requires_consent: bool
    requires_explicit_approval: bool
    max_classification: str
    invasiveness: int

    def permits(self, classification: str) -> bool:
        """True when ``classification`` is within this profile's ceiling."""
        return _class_rank(classification) <= _class_rank(self.max_classification)

    def as_dict(self) -> Dict[str, Any]:
        """Return the profile as a JSON-ready dict (the ``/rules`` catalog payload)."""
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "description": self.description,
            "sends_requests": self.sends_requests,
            "requires_consent": self.requires_consent,
            "requires_explicit_approval": self.requires_explicit_approval,
            "max_classification": self.max_classification,
            "max_classification_label": CLASSIFICATION_LABELS[self.max_classification],
            "invasiveness": self.invasiveness,
        }


PROFILES: Mapping[str, ProbeProfile] = {
    PROFILE_PASSIVE: ProbeProfile(
        profile_id=PROFILE_PASSIVE,
        label="Passive",
        description=(
            "Read-only. Re-reads the transcript captured during ordinary discovery and classifies "
            "observed protocol behaviour; sends no new request and never touches a business tool. "
            "The default; the only profile that runs without recorded consent."
        ),
        sends_requests=False,
        requires_consent=False,
        requires_explicit_approval=False,
        max_classification=CLASS_OBSERVED,
        invasiveness=0,
    ),
    PROFILE_SAFE_ACTIVE: ProbeProfile(
        profile_id=PROFILE_SAFE_ACTIVE,
        label="Safe active",
        description=(
            "Sends benign, well-formed and mildly-malformed protocol messages to probe the server's "
            "boundaries — never a side-effecting business-tool call. Requires recorded consent; a "
            "stdio target additionally requires a validated isolation sandbox."
        ),
        sends_requests=True,
        requires_consent=True,
        requires_explicit_approval=False,
        max_classification=CLASS_EXPLOITED_IN_TEST,
        invasiveness=1,
    ),
    PROFILE_PAYLOAD_FUZZING: ProbeProfile(
        profile_id=PROFILE_PAYLOAD_FUZZING,
        label="Payload fuzzing",
        description=(
            "Sends crafted hostile payloads (injection, SSRF canaries, oversized fields) to tool "
            "parameters to demonstrate reachability. Requires explicit per-run approval, a dedicated "
            "test identity, and a locked-down sandbox for any stdio target."
        ),
        sends_requests=True,
        requires_consent=True,
        requires_explicit_approval=True,
        max_classification=CLASS_EXPLOITED_IN_TEST,
        invasiveness=2,
    ),
}

#: The profile used when a caller names none — always the read-only one, so a bare "probe this"
#: cannot accidentally send traffic. AC1: "Default discovery remains read-only."
DEFAULT_PROFILE = PROFILE_PASSIVE


class UnknownProfileError(ValueError):
    """Raised when a caller names a profile that is not in :data:`PROFILES`."""

    def __init__(self, profile_id: str) -> None:
        super().__init__(
            f"unknown probe profile '{profile_id}'; known profiles: {sorted(PROFILES)}"
        )
        self.profile_id = profile_id


def resolve_profile(profile_id: Optional[str]) -> ProbeProfile:
    """Return the :class:`ProbeProfile` for ``profile_id`` (or the default when ``None``)."""
    if profile_id is None:
        return PROFILES[DEFAULT_PROFILE]
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise UnknownProfileError(profile_id) from exc


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
# AC2: "Active profiles record target, scope, test identity, limits, and consent in evidence." Every
# one of those is a required field here, and validate() refuses the run if the profile needs consent
# and any of them is missing. The record is copied verbatim into the audit envelope, so the evidence
# always answers "who authorized firing what at whom, under what limits, as which identity".

TRANSPORT_HTTP = "http"
TRANSPORT_STDIO = "stdio"
TRANSPORTS: Tuple[str, ...] = (TRANSPORT_HTTP, TRANSPORT_STDIO)


class ConsentError(ValueError):
    """Raised when an active profile is asked to run without valid consent for it."""


@dataclass(frozen=True)
class ConsentRecord:
    """Operator authorization to run active probes against one target.

    Attributes:
        target_endpoint_id: The catalogued endpoint under test.
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

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(
                f"consent declares unknown transport {self.transport!r}; known: {list(TRANSPORTS)}"
            )

    def validate(self, profile: ProbeProfile) -> None:
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
# Isolation — the least-privilege sandbox contract for stdio targets.
# =================================================================================================
# AC3: "Isolation has least privilege, restricted egress, read-only filesystem where possible, no
# host socket, and hard limits." A stdio MCP server is untrusted code we execute; running it outside
# a locked-down sandbox is the single most dangerous thing this feature could do. So the sandbox is
# modelled as an explicit spec with a validate() that fails CLOSED — a runner may only be handed a
# stdio target after this module has confirmed the spec provides every guarantee below. This is a
# contract the runner must satisfy, not the runner itself; the runner (Firecracker/gVisor/container)
# is injected, but it cannot run a stdio probe under a spec that does not validate.


class IsolationError(ValueError):
    """Raised when a stdio probe is asked to run under an isolation spec that is not locked down."""


@dataclass(frozen=True)
class IsolationSpec:
    """The least-privilege sandbox a stdio probe must run inside.

    Every field is a guarantee the runner must provide; :meth:`violations` lists the ones a given
    spec fails to meet, and :func:`require_isolation` turns any non-empty list into a refusal. The
    defaults are the *hardened* values, so an incomplete spec is an insecure spec and is rejected —
    you have to actively weaken it to get an unsafe run, and even then it will not validate.

    Attributes:
        egress_allowlist: The exact set of hosts the sandbox may reach. Restricted egress (AC3): for
            a stdio server this is normally empty (a server that needs no network gets none); a run
            that must reach the target lists only it. A spec allowing ``*`` never validates.
        read_only_rootfs: The container root filesystem is mounted read-only (AC3).
        no_new_privileges: ``no_new_privs`` is set so the process cannot gain privileges via setuid.
        drop_all_capabilities: All Linux capabilities are dropped (least privilege, AC3).
        mount_host_socket: Whether the host's container/daemon socket is mounted in. Must be
            ``False`` — mounting it is a trivial sandbox escape (AC3: "no host socket").
        network_disabled: Whether the sandbox has no network at all. When ``True`` the egress
            allowlist must be empty and vice-versa; the two describe the same decision from opposite
            sides and disagreeing is a spec bug.
        pids_limit: Hard cap on process count (fork-bomb defence).
        memory_bytes: Hard memory cap.
        cpu_quota_percent: Hard CPU cap, as a percentage of one core.
        wall_clock_seconds: Hard ceiling on how long the sandbox may live before it is killed.
        disposable: The sandbox is destroyed after the run and never reused across tenants or runs.
    """

    egress_allowlist: Tuple[str, ...] = ()
    read_only_rootfs: bool = True
    no_new_privileges: bool = True
    drop_all_capabilities: bool = True
    mount_host_socket: bool = False
    network_disabled: bool = True
    pids_limit: int = 128
    memory_bytes: int = 268_435_456  # 256 MiB
    cpu_quota_percent: int = 50
    wall_clock_seconds: int = 30
    disposable: bool = True

    def violations(self) -> Tuple[str, ...]:
        """Return every least-privilege guarantee this spec fails to provide (empty = locked down)."""
        problems: List[str] = []
        if not self.read_only_rootfs:
            problems.append("root filesystem is not read-only")
        if not self.no_new_privileges:
            problems.append("no_new_privileges is not set")
        if not self.drop_all_capabilities:
            problems.append("Linux capabilities are not all dropped")
        if self.mount_host_socket:
            problems.append("the host container socket is mounted (a sandbox escape)")
        if not self.disposable:
            problems.append("the sandbox is not disposable")
        if "*" in self.egress_allowlist:
            problems.append("egress is unrestricted ('*' in the allowlist)")
        if self.network_disabled and self.egress_allowlist:
            problems.append("network is disabled but an egress allowlist is present (contradiction)")
        if not self.network_disabled and not self.egress_allowlist:
            problems.append("network is enabled with no egress allowlist (unrestricted by omission)")
        for name in ("pids_limit", "memory_bytes", "cpu_quota_percent", "wall_clock_seconds"):
            if getattr(self, name) <= 0:
                problems.append(f"hard limit '{name}' is not set to a positive value")
        return tuple(problems)

    def is_least_privilege(self) -> bool:
        """True when the spec provides every guarantee AC3 requires."""
        return not self.violations()

    def as_dict(self) -> Dict[str, Any]:
        """Return the isolation spec as a JSON-ready dict (goes into the audit envelope)."""
        return {
            "egress_allowlist": list(self.egress_allowlist),
            "read_only_rootfs": self.read_only_rootfs,
            "no_new_privileges": self.no_new_privileges,
            "drop_all_capabilities": self.drop_all_capabilities,
            "mount_host_socket": self.mount_host_socket,
            "network_disabled": self.network_disabled,
            "pids_limit": self.pids_limit,
            "memory_bytes": self.memory_bytes,
            "cpu_quota_percent": self.cpu_quota_percent,
            "wall_clock_seconds": self.wall_clock_seconds,
            "disposable": self.disposable,
        }

    @classmethod
    def hardened(
        cls, *, egress_allowlist: Sequence[str] = (), wall_clock_seconds: int = 30
    ) -> "IsolationSpec":
        """Return a locked-down spec, optionally allowing egress to a specific set of hosts.

        The one-call way to get a spec that validates. With no ``egress_allowlist`` the sandbox has
        no network; supplying hosts enables the network and restricts it to exactly those hosts.
        """
        hosts = tuple(egress_allowlist)
        return cls(
            egress_allowlist=hosts,
            network_disabled=not hosts,
            wall_clock_seconds=wall_clock_seconds,
        )


def require_isolation(consent: ConsentRecord, isolation: Optional[IsolationSpec]) -> None:
    """Refuse an active run whose stdio target lacks a locked-down sandbox.

    A stdio target executes untrusted code, so it *must* be sandboxed. An http target contacts a
    remote host, so an in-process transport with restricted egress is acceptable and no local
    sandbox is required (though one may still be supplied). This is the single chokepoint that AC3
    passes through.

    Args:
        consent: The consent record naming the transport.
        isolation: The sandbox spec, when the runner supplied one.

    Raises:
        IsolationError: If a stdio target has no spec, or a spec that is not least-privilege.
    """
    if consent.transport != TRANSPORT_STDIO:
        return
    if isolation is None:
        raise IsolationError(
            "a stdio MCP target executes untrusted code and may only be probed inside a disposable, "
            "least-privilege sandbox; no isolation spec was supplied"
        )
    violations = isolation.violations()
    if violations:
        raise IsolationError(
            "the isolation spec for this stdio target is not least-privilege: "
            + "; ".join(violations)
        )


# =================================================================================================
# Kill switch + per-tenant governor.
# =================================================================================================
# AC5: "Kill switch, tenant concurrency/rate limits, and audit trail exist before rollout." The
# governor is kept as a *pure decision function over supplied usage*, not a stateful object that owns
# counters — the route layer reads the live counts from the audit table and hands them in, so the
# same policy is testable in isolation and there is one source of truth (the DB) for how many runs a
# tenant already has in flight.


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
    """

    enabled: bool = False
    max_concurrent_per_tenant: int = 2
    max_runs_per_hour_per_tenant: int = 20


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


def authorize_active_run(
    profile: ProbeProfile, policy: GovernorPolicy, usage: TenantUsage
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
    if not policy.enabled:
        raise KillSwitchError(
            "MCP active probing is disabled by the global kill switch "
            "(mcp_probe_enabled=false); only the read-only passive profile may run"
        )
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


# =================================================================================================
# Transport — the injected boundary between policy (here) and bytes-on-the-wire (the runner).
# =================================================================================================


@dataclass(frozen=True)
class ProbeResponse:
    """The redacted shape of one probe request/response, as the runner reports it.

    Deliberately structural, like :class:`~app.mcp_protocol_transcript.ProtocolExchange`: a probe
    reasons about *whether* the server errored, echoed its id, or reflected a canary — never about
    secret payload values. ``reflected_canaries`` is the one exploit-bearing field, and it carries
    canary *tokens the prober itself generated*, never server data.

    Attributes:
        ok: Whether the transport completed the round trip (not whether the server liked it).
        http_status: The HTTP status observed, when the transport is http.
        id_echoed: Whether the response echoed the request id.
        error_code: The JSON-RPC error code, or ``None`` on a result.
        result_keys: Top-level key names of the result object (names only).
        reflected_canaries: Canary tokens (generated by the prober) that appeared in the response —
            the evidence an injected string was honoured or reflected.
        response_bytes: The size of the response, for the max-response-bytes limit.
    """

    ok: bool
    http_status: Optional[int] = None
    id_echoed: bool = True
    error_code: Optional[int] = None
    result_keys: Tuple[str, ...] = ()
    reflected_canaries: Tuple[str, ...] = ()
    response_bytes: int = 0


class ProbeTransport(Protocol):
    """The runner boundary: send one JSON-RPC request, get back a redacted :class:`ProbeResponse`.

    The real implementation lives inside the sandbox and speaks to the server; tests supply a fake.
    Policy in this module never touches a socket — it only ever calls :meth:`send`, so the sandbox,
    the transport, and the runner can all change without any rule here changing.
    """

    async def send(self, method: str, params: Mapping[str, Any]) -> ProbeResponse:  # pragma: no cover - protocol
        """Send one JSON-RPC ``method`` with ``params`` and return the redacted response."""
        ...


class LimitExceededError(RuntimeError):
    """Raised by :class:`CountingTransport` when a run would exceed its request or byte budget."""


class CountingTransport:
    """A transport wrapper that *enforces* :class:`ProbeLimits` rather than merely recording them.

    Wrapping the injected transport here means every probe, however written, is bounded by the same
    counter — a probe cannot bust the request cap by looping, because the cap lives in the wrapper it
    has to call through, not in each probe's good intentions. AC3's "hard limits" made real at the
    one point all traffic passes.

    Attributes:
        request_count: How many requests have been sent so far (read into the audit envelope).
    """

    def __init__(self, inner: ProbeTransport, limits: ProbeLimits) -> None:
        self._inner = inner
        self._limits = limits
        self.request_count = 0

    async def send(self, method: str, params: Mapping[str, Any]) -> ProbeResponse:
        """Send through the inner transport after checking, and then updating, the request budget.

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
        response = await self._inner.send(method, params)
        if response.response_bytes > self._limits.max_response_bytes:
            raise LimitExceededError(
                f"a probe response of {response.response_bytes} bytes exceeded the cap of "
                f"{self._limits.max_response_bytes}; the run was stopped"
            )
        return response


# =================================================================================================
# Probe model + registry.
# =================================================================================================


@dataclass(frozen=True)
class ProbeFinding:
    """One thing a probe found, at one of the three classification tiers.

    Shares its core key set (``path``/``rule``/``severity``/``message``) with the static engines so a
    consumer can render probe findings beside them, and adds the probe-specific ``classification``,
    ``observed`` evidence, and ``probe_id``.

    Attributes:
        probe_id: The probe that produced this.
        rule_id: The trust-posture rule this finding maps to — the same id a static ``suspected``
            finding for the same defect would carry, so the two tiers line up on one rule. Only used
            to mint :class:`ProbeEvidence` when the classification is exploited-in-test.
        path: Where the defect is (a surface path, a tool name).
        severity: ``error`` / ``warning`` / ``info``.
        classification: :data:`CLASS_OBSERVED` or :data:`CLASS_EXPLOITED_IN_TEST` (a probe never
            emits ``suspected`` — that is the static engines' tier).
        message: Human-readable description. Never contains secret material.
        observed: What the probe actually saw — the evidence, stated as an observation rather than an
            inference from it.
        owasp_ids: The OWASP MCP risks this is an instance of.
        remediation: What to do about it.
        id: Stable identifier; auto-derived from ``probe_id|path|classification``.
    """

    probe_id: str
    rule_id: str
    path: str
    severity: str
    classification: str
    message: str
    observed: str
    owasp_ids: Tuple[str, ...] = ()
    remediation: Optional[str] = None
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if self.classification not in (CLASS_OBSERVED, CLASS_EXPLOITED_IN_TEST):
            raise ValueError(
                f"a probe finding may only be '{CLASS_OBSERVED}' or '{CLASS_EXPLOITED_IN_TEST}', "
                f"not {self.classification!r} — 'suspected' is the static engines' tier"
            )
        object.__setattr__(self, "owasp_ids", validate_risk_ids(self.owasp_ids))
        if not self.id:
            digest = hashlib.sha256(
                f"{self.probe_id}|{self.path}|{self.classification}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"mcp-probe-{digest}")

    @property
    def is_exploit(self) -> bool:
        """True only when a probe demonstrated the defect against a live server."""
        return self.classification == CLASS_EXPLOITED_IN_TEST

    def to_probe_evidence(self, probe_run_id: Optional[str] = None) -> ProbeEvidence:
        """Mint the CLX-3.2 :class:`ProbeEvidence` for an exploited-in-test finding.

        This is the *only* place probe evidence is created, and it refuses to create it for anything
        weaker than an exploit — so the trust-posture ``proven`` door stays exactly as narrow as
        CLX-3.2 built it. An ``observed`` finding is real, but it is not a demonstrated exploit, and
        it must not become one by being fed through here.

        Raises:
            ValueError: If the finding is not exploited-in-test.
        """
        if not self.is_exploit:
            raise ValueError(
                "only an exploited-in-test finding may become ProbeEvidence; an observed finding "
                "was not demonstrated to be exploitable"
            )
        return ProbeEvidence(
            probe_id=self.probe_id, observed=self.observed, probe_run_id=probe_run_id
        )

    def as_dict(self) -> Dict[str, Any]:
        """Return the finding as a JSON-ready dict."""
        return {
            "id": self.id,
            "probe_id": self.probe_id,
            "rule_id": self.rule_id,
            "path": self.path,
            "severity": self.severity,
            "classification": self.classification,
            "classification_label": CLASSIFICATION_LABELS[self.classification],
            "message": self.message,
            "observed": self.observed,
            "owasp_ids": list(self.owasp_ids),
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class Probe:
    """A registered probe descriptor.

    Attributes:
        probe_id: Stable dotted id (e.g. ``passive.id-not-echoed``, ``fuzz.parameter-injection``).
            Hashed into finding ids; never renamed once shipped.
        profile: The profile that runs this probe (:data:`PROFILE_PASSIVE` / ...).
        title: One-line human name.
        rationale: What risk the probe speaks to and why it matters.
        owasp_ids: The OWASP MCP risks it maps to (validated at registration).
        emits: The strongest classification this probe can produce — must be within its profile's
            ceiling, checked at registration so a mis-tiered probe fails at import, not at runtime.
    """

    probe_id: str
    profile: str
    title: str
    rationale: str
    owasp_ids: Tuple[str, ...]
    emits: str

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise ValueError(f"probe '{self.probe_id}' declares unknown profile {self.profile!r}")
        if self.emits not in (CLASS_OBSERVED, CLASS_EXPLOITED_IN_TEST):
            raise ValueError(
                f"probe '{self.probe_id}' declares invalid emits {self.emits!r}"
            )
        if not PROFILES[self.profile].permits(self.emits):
            raise ValueError(
                f"probe '{self.probe_id}' emits {self.emits!r}, stronger than its profile "
                f"'{self.profile}' permits ({PROFILES[self.profile].max_classification!r})"
            )
        object.__setattr__(self, "owasp_ids", validate_risk_ids(self.owasp_ids))

    def as_dict(self) -> Dict[str, Any]:
        """Return the probe descriptor as a JSON-ready dict (the ``/rules`` catalog payload)."""
        return {
            "probe_id": self.probe_id,
            "profile": self.profile,
            "title": self.title,
            "rationale": self.rationale,
            "owasp_ids": list(self.owasp_ids),
            "emits": self.emits,
            "emits_label": CLASSIFICATION_LABELS[self.emits],
        }


#: probe_id -> descriptor, for every registered probe.
PROBE_REGISTRY: Dict[str, Probe] = {}

#: A passive probe reads the transcript + surface and appends findings. Pure: no I/O.
PassiveProbeFn = Callable[["PassiveContext", List[ProbeFinding]], None]

#: An active probe drives the transport and appends findings. Async; all I/O goes through the
#: transport, which the :class:`CountingTransport` wrapper bounds.
ActiveProbeFn = Callable[["ActiveContext", List[ProbeFinding]], Awaitable[None]]

_PASSIVE_PROBES: List[PassiveProbeFn] = []
_ACTIVE_PROBES: List[ActiveProbeFn] = []


def register_probes(probes: Sequence[Probe]) -> None:
    """Register probe descriptors in :data:`PROBE_REGISTRY`.

    Raises:
        ValueError: If a probe id is already registered with different metadata (two packs claiming
            one id, or a shipped probe silently redefined — its id is hashed into finding ids).
    """
    for probe in probes:
        existing = PROBE_REGISTRY.get(probe.probe_id)
        if existing is not None and existing != probe:
            raise ValueError(
                f"probe '{probe.probe_id}' is already registered with different metadata; "
                f"probe ids are stable and may not be redefined"
            )
        PROBE_REGISTRY[probe.probe_id] = probe


def passive_probe(func: PassiveProbeFn) -> PassiveProbeFn:
    """Register a passive probe function (decorator)."""
    _PASSIVE_PROBES.append(func)
    return func


def active_probe(func: ActiveProbeFn) -> ActiveProbeFn:
    """Register an active probe function (decorator)."""
    _ACTIVE_PROBES.append(func)
    return func


def make_observed(
    probe_id: str, path: str, message: str, *, observed: str, severity: str = "warning",
    remediation: Optional[str] = None,
) -> ProbeFinding:
    """Build an ``observed`` finding, resolving OWASP mapping from the probe registry.

    The safe constructor: it hard-codes the classification to :data:`CLASS_OBSERVED`, so a probe
    author cannot accidentally claim an exploit by passing a stronger tier — the same discipline
    CLX-3.2's :func:`~app.mcp_trust_posture.make_finding` uses for ``static_signal``.
    """
    probe = PROBE_REGISTRY[probe_id]
    return ProbeFinding(
        probe_id=probe_id,
        rule_id=path,
        path=path,
        severity=severity,
        classification=CLASS_OBSERVED,
        message=message,
        observed=observed,
        owasp_ids=probe.owasp_ids,
        remediation=remediation,
    )


def make_exploited(
    probe_id: str, rule_id: str, path: str, message: str, *, observed: str,
    severity: str = "error", remediation: Optional[str] = None,
) -> ProbeFinding:
    """Build an ``exploited-in-test`` finding — the tier that becomes probe evidence.

    ``rule_id`` is required and distinct from ``path`` here: an exploit is mapped to the *same
    trust-posture rule* a static signal for the defect carries, so the two tiers converge on one rule
    when the report is assembled. ``observed`` is mandatory (it is the evidence the exploit rests on).
    """
    if not observed:
        raise ValueError("an exploited-in-test finding requires an 'observed' evidence string")
    probe = PROBE_REGISTRY[probe_id]
    return ProbeFinding(
        probe_id=probe_id,
        rule_id=rule_id,
        path=path,
        severity=severity,
        classification=CLASS_EXPLOITED_IN_TEST,
        message=message,
        observed=observed,
        owasp_ids=probe.owasp_ids,
        remediation=remediation,
    )


# =================================================================================================
# Probe contexts.
# =================================================================================================


@dataclass(frozen=True)
class PassiveContext:
    """Everything a passive probe may read. No transport — passive probes send nothing.

    Attributes:
        surface: The normalized capability surface (what the server advertises).
        transcript: The redacted transcript ordinary discovery captured, or ``None`` when the
            snapshot has none. A passive probe needing a transcript it does not have is skipped and
            reported, exactly as the trust-posture engine skips a rule with no evidence.
    """

    surface: DiscoverySurface
    transcript: Optional[ProtocolTranscript] = None


@dataclass(frozen=True)
class ActiveContext:
    """Everything an active probe may read, plus the bounded transport it drives.

    Attributes:
        surface: The advertised surface — where a probe finds the tool names and parameters to target.
        transport: The :class:`CountingTransport` every request goes through (bounded by the run's
            limits). A probe never constructs its own transport; it is handed this one.
        consent: The consent record authorizing the run (a probe may read the test identity from it).
    """

    surface: DiscoverySurface
    transport: CountingTransport
    consent: ConsentRecord


# =================================================================================================
# Report.
# =================================================================================================


@dataclass(frozen=True)
class ProbeReport:
    """The assembled result of one probe run, plus the audit envelope AC2/AC5 require.

    Attributes:
        profile: The profile that ran.
        target_endpoint_id: The endpoint probed.
        findings: Every finding, sorted deterministically.
        classification_counts: How many findings at each tier.
        severity_counts: How many findings at each severity.
        requests_sent: How many requests the run actually sent (0 for passive).
        skipped_probes: Probe ids that could not run (e.g. passive probe with no transcript), each
            with a reason — never silently dropped, so an absent probe reads as a gap, not a pass.
        consent: The consent record (``None`` for passive), copied verbatim into the audit trail.
        limits: The hard limits the run carried (``None`` for passive).
        isolation: The isolation spec a stdio run used (``None`` otherwise).
        evidence: The :class:`ProbeEvidence` for every exploited-in-test finding — what the
            trust-posture engine consumes to move ``proven_count``.
        report_fingerprint: Stable hash over the profile, target, and findings.
    """

    profile: ProbeProfile
    target_endpoint_id: str
    findings: Tuple[ProbeFinding, ...]
    classification_counts: Mapping[str, int]
    severity_counts: Mapping[str, int]
    requests_sent: int
    skipped_probes: Mapping[str, str]
    consent: Optional[ConsentRecord]
    limits: Optional[ProbeLimits]
    isolation: Optional[IsolationSpec]
    evidence: Tuple[ProbeEvidence, ...]
    report_fingerprint: str

    @property
    def exploited_count(self) -> int:
        """How many findings a probe demonstrated against a live server."""
        return sum(1 for f in self.findings if f.is_exploit)

    def as_dict(self) -> Dict[str, Any]:
        """Return the whole report as a JSON-ready dict (the API/CLI payload and audit record)."""
        return {
            "profile": self.profile.profile_id,
            "profile_label": self.profile.label,
            "target_endpoint_id": self.target_endpoint_id,
            "findings": [f.as_dict() for f in self.findings],
            "classification_counts": dict(self.classification_counts),
            "severity_counts": dict(self.severity_counts),
            "exploited_count": self.exploited_count,
            "requests_sent": self.requests_sent,
            "skipped_probes": dict(self.skipped_probes),
            "consent": self.consent.as_dict() if self.consent is not None else None,
            "limits": self.limits.as_dict() if self.limits is not None else None,
            "isolation": self.isolation.as_dict() if self.isolation is not None else None,
            "evidence": [e.as_dict() for e in self.evidence],
            "report_fingerprint": self.report_fingerprint,
        }

    @staticmethod
    def assemble(
        profile: ProbeProfile,
        target_endpoint_id: str,
        findings: Sequence[ProbeFinding],
        *,
        requests_sent: int,
        skipped_probes: Mapping[str, str],
        consent: Optional[ConsentRecord],
        limits: Optional[ProbeLimits],
        isolation: Optional[IsolationSpec],
        probe_run_id: Optional[str] = None,
    ) -> "ProbeReport":
        """Sort, tally, and fingerprint findings into a report, enforcing the profile ceiling.

        The ceiling check is the last line of defence for AC4: even if a probe were mis-written to
        emit a stronger tier than its profile allows, the report refuses to carry it. Combined with
        the per-probe check at registration, a passive run *cannot* produce an exploited-in-test
        finding by any path.

        Raises:
            ValueError: If any finding exceeds the profile's ``max_classification``.
        """
        for finding in findings:
            if not profile.permits(finding.classification):
                raise ValueError(
                    f"probe '{finding.probe_id}' emitted a {finding.classification!r} finding under "
                    f"the '{profile.profile_id}' profile, which permits at most "
                    f"{profile.max_classification!r}"
                )
        ordered = tuple(sorted(findings, key=lambda f: (f.path, f.probe_id, f.id)))
        as_dicts = [f.as_dict() for f in ordered]
        evidence = tuple(
            f.to_probe_evidence(probe_run_id) for f in ordered if f.is_exploit
        )
        return ProbeReport(
            profile=profile,
            target_endpoint_id=target_endpoint_id,
            findings=ordered,
            classification_counts=_counts(f.classification for f in ordered),
            severity_counts=_counts(f.severity for f in ordered),
            requests_sent=requests_sent,
            skipped_probes=dict(sorted(skipped_probes.items())),
            consent=consent,
            limits=limits,
            isolation=isolation,
            evidence=evidence,
            report_fingerprint=_report_fingerprint(
                profile.profile_id, target_endpoint_id, as_dicts
            ),
        )


def _counts(values) -> Dict[str, int]:
    """Tally an iterable of keys into a sorted count map (stable for rendering)."""
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _report_fingerprint(
    profile_id: str, target: str, findings: Sequence[Mapping[str, Any]]
) -> str:
    """Stable hash over the profile, target, and sorted findings."""
    payload = {
        "profile": profile_id,
        "target": target,
        "findings": sorted(
            [
                {
                    "id": f.get("id", ""),
                    "path": f.get("path", ""),
                    "classification": f.get("classification", ""),
                }
                for f in findings
            ],
            key=lambda f: (f["path"], f["classification"], f["id"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# =================================================================================================
# Orchestrators — the two entry points.
# =================================================================================================


def run_passive_probes(
    surface: DiscoverySurface,
    transcript: Optional[ProtocolTranscript],
    *,
    target_endpoint_id: str,
) -> ProbeReport:
    """Run every passive probe over the captured evidence. Sends nothing; always safe.

    This is the default path and the only one that runs without consent, a sandbox, or the kill
    switch being on — because it produces no traffic. A probe that needs a transcript this snapshot
    lacks is skipped and reported, never assumed to have passed.

    Args:
        surface: The advertised capability surface.
        transcript: The redacted discovery transcript, or ``None`` when the snapshot has none.
        target_endpoint_id: The endpoint being assessed (for the report and audit).

    Returns:
        The assembled :class:`ProbeReport`. Its ``evidence`` is always empty — passive probes never
        reach exploited-in-test, so they never mint probe evidence.
    """
    profile = PROFILES[PROFILE_PASSIVE]
    context = PassiveContext(surface=surface, transcript=transcript)
    findings: List[ProbeFinding] = []
    skipped: Dict[str, str] = {}
    for func in _PASSIVE_PROBES:
        collected: List[ProbeFinding] = []
        func(context, collected)
        findings.extend(collected)
    # A passive probe that reasons about the transcript cannot run without one; surface the gap.
    if transcript is None:
        for probe in PROBE_REGISTRY.values():
            if probe.profile == PROFILE_PASSIVE and probe.probe_id.startswith("passive.protocol"):
                skipped.setdefault(
                    probe.probe_id,
                    "no discovery transcript is stored for this snapshot, so observed protocol "
                    "behaviour could not be assessed",
                )
    return ProbeReport.assemble(
        profile,
        target_endpoint_id,
        findings,
        requests_sent=0,
        skipped_probes=skipped,
        consent=None,
        limits=None,
        isolation=None,
    )


async def run_active_probes(
    surface: DiscoverySurface,
    transport: ProbeTransport,
    *,
    profile: str,
    consent: ConsentRecord,
    policy: GovernorPolicy,
    usage: TenantUsage,
    limits: Optional[ProbeLimits] = None,
    isolation: Optional[IsolationSpec] = None,
    probe_run_id: Optional[str] = None,
) -> ProbeReport:
    """Run an active profile against a live server, through every gate the ACs require.

    The order of the gates is deliberate — cheapest and most consequential first, so a run that must
    be refused is refused before anything is sent:

    1. **Kill switch + rate/concurrency** (:func:`authorize_active_run`) — is active probing on at
       all, and is this tenant within budget?
    2. **Consent** (:meth:`ConsentRecord.validate`) — did someone authorize firing *this* profile at
       *this* target, as a dedicated identity, with (for fuzzing) explicit approval?
    3. **Isolation** (:func:`require_isolation`) — if the target is stdio (untrusted local code), is
       there a locked-down sandbox to run it in?

    Only past all three does a single request go out, and even then every request is bounded by
    :class:`CountingTransport`. The returned report carries the full audit envelope.

    Args:
        surface: The advertised surface (where probes find targets).
        transport: The runner's transport into the sandboxed/remote server.
        profile: The active profile id (``safe-active`` or ``payload-fuzzing``).
        consent: The consent record authorizing the run.
        policy: The global/per-tenant governor policy.
        usage: The tenant's live usage, read from the audit trail.
        limits: The hard limits (defaults to :data:`DEFAULT_LIMITS`).
        isolation: The sandbox spec for a stdio target (required for stdio).
        probe_run_id: The audit-row id, threaded onto minted probe evidence.

    Returns:
        The assembled :class:`ProbeReport`, whose ``evidence`` feeds the trust-posture engine.

    Raises:
        UnknownProfileError: If ``profile`` is unknown.
        ValueError: If ``profile`` is the passive profile (use :func:`run_passive_probes`).
        KillSwitchError / RateLimitError / ConsentError / IsolationError: If any gate refuses.
    """
    resolved = resolve_profile(profile)
    if not resolved.sends_requests:
        raise ValueError(
            f"'{resolved.profile_id}' is a read-only profile; call run_passive_probes for it"
        )
    effective_limits = limits or DEFAULT_LIMITS

    authorize_active_run(resolved, policy, usage)
    consent.validate(resolved)
    require_isolation(consent, isolation)

    counting = CountingTransport(transport, effective_limits)
    context = ActiveContext(surface=surface, transport=counting, consent=consent)
    findings: List[ProbeFinding] = []
    for func in _ACTIVE_PROBES:
        if _probe_profile_of(func) != resolved.profile_id:
            continue
        collected: List[ProbeFinding] = []
        await func(context, collected)
        findings.extend(collected)

    return ProbeReport.assemble(
        resolved,
        consent.target_endpoint_id,
        findings,
        requests_sent=counting.request_count,
        skipped_probes={},
        consent=consent,
        limits=effective_limits,
        isolation=isolation,
        probe_run_id=probe_run_id,
    )


#: Active probe function -> the profile id it belongs to, discovered from the probe it registers.
#: Filled by the pack at import; kept as a side table so :func:`run_active_probes` can select the
#: probes for a profile without each function having to re-declare it.
_ACTIVE_PROBE_PROFILES: Dict[int, str] = {}


def _probe_profile_of(func: ActiveProbeFn) -> str:
    """Return the profile id an active probe function was registered under (default safe-active)."""
    return _ACTIVE_PROBE_PROFILES.get(id(func), PROFILE_SAFE_ACTIVE)


def bind_active_profile(func: ActiveProbeFn, profile_id: str) -> ActiveProbeFn:
    """Record that ``func`` runs under ``profile_id`` and register it. Used by the probe pack."""
    _ACTIVE_PROBE_PROFILES[id(func)] = profile_id
    return active_probe(func)


def probe_catalog(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return every registered probe descriptor, sorted by probe id (the ``/rules`` catalog).

    Args:
        profile: When given, restrict the catalog to that profile's probes.

    Raises:
        UnknownProfileError: If ``profile`` names no known profile.
    """
    resolved = resolve_profile(profile) if profile is not None else None
    probes = [
        probe
        for probe in PROBE_REGISTRY.values()
        if resolved is None or probe.profile == resolved.profile_id
    ]
    return [probe.as_dict() for probe in sorted(probes, key=lambda p: p.probe_id)]


# --- Probe pack + trust-posture bridge auto-registration ----------------------------------------
# The probe pack registers its descriptors and probe functions on import, exactly as the conformance
# and trust-posture rule packs do. The bridge then registers the ``REQUIRES_PROBE`` trust-posture
# rules that consume exploited-in-test evidence — loaded from here (the probe side) rather than from
# the trust-posture packs so the import graph stays acyclic and the ``proven`` rules exist exactly
# when the probe subsystem is loaded. Imported last so every public symbol above is already defined.
from . import mcp_probe_probes as _mcp_probe_probes  # noqa: E402,F401,I001  (side-effecting)
from . import mcp_probe_rules as _mcp_probe_rules  # noqa: E402,F401,I001  (side-effecting)
