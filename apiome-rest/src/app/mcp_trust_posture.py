"""MCP source, supply-chain, and trust-posture engine (CLX-3.2, #4856).

The third and last of the MCP scan engines, and the first one that can see past what the server
says about itself:

* :mod:`app.mcp_lint` reads the **advertised surface** — is each capability well-formed?
* :mod:`app.mcp_conformance` reads the **observed protocol** — did the server behave like an MCP
  server, and can an agent use its tools safely?
* this engine reads the **artifact** — what is the server *made of*? Whose code, whose
  dependencies, which secrets, which shell commands, how much authority?

Filling the reserved axis
-------------------------
:mod:`app.axis_score` has declared ``supply_chain`` since CLX-1.2 and has always reported it *not
assessed*, because no scanner could speak to it. This engine is that scanner. Filling the axis makes
supply chain gateable through the existing policy ``axis_gates`` with no new gate code — exactly as
CLX-3.1 did for ``protocol``.

A separate engine, again
------------------------
For the same non-stylistic reason CLX-3.1 gave: ``mcp_score`` hashes its entire rule registry into a
persisted ``report_fingerprint``. Adding rules to it retroactively regrades every snapshot ever
stored. So this engine carries its own registry, its own score, and its own fingerprint, and leaves
both the surface report and the conformance report byte-identical.

------------------------------------------------------------------------------------------------
The two properties this engine enforces structurally
------------------------------------------------------------------------------------------------

**1. Nothing is "exploitable" until a probe proves it.**

The acceptance criterion is that the catalog must render risk, evidence, and remediation *without
asserting a finding is exploitable* unless a dynamic probe proved it. That is not a UI copy problem
— a UI can only be as honest as the data it is handed — so it is enforced in the data model:

* Every finding carries an :attr:`PostureFinding.exploitability`.
* :func:`make_finding` — the *only* constructor a rule may use — hard-codes it to
  :data:`EXPLOITABILITY_SIGNAL`. A static rule cannot express anything else; there is no argument
  for it to pass.
* :data:`EXPLOITABILITY_PROVEN` may only be reached through :func:`make_proven_finding`, which
  demands a :class:`ProbeEvidence`, and **no probe exists today**. Dynamic probes are CLX-3.3
  (#4857); until they land, :attr:`PostureReport.proven_count` is 0 on every report this engine can
  produce, and the UI is *incapable* of labelling a static signal exploitable rather than merely
  disinclined to.

A grep for ``EXPLOITABILITY_PROVEN`` finding only its definition and its one guarded constructor is
the proof, and ``test_mcp_trust_posture.py`` asserts it.

**2. An unscanned thing is never a clean thing.**

A rule declares what evidence it needs (:attr:`PostureRule.requires`). When that evidence is absent —
no source is linked, no SBOM was attached, vulnerability lookup is off — the rule is **skipped and
reported** in :attr:`PostureReport.skipped_rules`, and the evidence run is recorded as *partial*
coverage. It is never evaluated against an assumption, and its silence never reads as a pass. This
is the same mechanism CLX-3.1 built for absent protocol transcripts, reused rather than reinvented.

Finding origin
--------------
Every rule declares an :attr:`PostureRule.origin` — ``metadata``, ``source``, ``dependency``, or
``protocol`` — which is carried onto every finding it emits. A reviewer looking at a finding can
therefore always tell whether it came from something the server *claimed*, something its *code*
contains, something its *dependencies* carry, or something it *did on the wire*. Those four have
very different standards of proof, and collapsing them would make the strongest evidence
indistinguishable from the weakest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .axis_score import grade_for_score, score_from_finding_dicts, severity_counts
from .mcp_client.normalize import DiscoverySurface
from .mcp_owasp import CATALOG_REFERENCE, CATALOG_REVISION, coverage_summary, validate_risk_ids
from .mcp_sbom import SbomInventory
from .mcp_source_link import (
    CONFIDENCE_HIGH,
    SourceLink,
    confidence_for_link,
)
from .mcp_static_checks import StaticScanResult
from .mcp_vulnerability import VulnerabilityReport

# --- Finding origin -----------------------------------------------------------------------------
# Which lane of evidence a finding came from. Four, because they carry four different standards of
# proof and a reviewer must be able to tell them apart.

#: The server's own advertised metadata — its tool descriptions, schemas, annotations. This is what
#: the server *claims*, and a compromised server controls every word of it.
ORIGIN_METADATA = "metadata"

#: The linked source artifact — its config, manifests, entrypoints. What the server is *built from*,
#: as of the revision that was scanned.
ORIGIN_SOURCE = "source"

#: The source's dependency inventory. What the server *pulls in*, and what is known to be wrong with it.
ORIGIN_DEPENDENCY = "dependency"

#: Observed protocol behaviour, from the redacted transcript CLX-3.1 captures. What the server
#: actually *did*, as opposed to what it said.
ORIGIN_PROTOCOL = "protocol"

#: Every finding origin, in stable order.
ORIGINS: Tuple[str, ...] = (ORIGIN_METADATA, ORIGIN_SOURCE, ORIGIN_DEPENDENCY, ORIGIN_PROTOCOL)

#: Human labels for each origin (UI chips, report rendering).
ORIGIN_LABELS: Mapping[str, str] = {
    ORIGIN_METADATA: "Advertised metadata",
    ORIGIN_SOURCE: "Linked source",
    ORIGIN_DEPENDENCY: "Dependency",
    ORIGIN_PROTOCOL: "Observed protocol",
}

# --- Exploitability -----------------------------------------------------------------------------

#: What every static rule produces, without exception. The rule found a pattern that *indicates* a
#: risk. It has not shown the risk is reachable, that the code path is live, or that an attacker
#: could trigger it. Rendered as "Signal — not proven exploitable".
EXPLOITABILITY_SIGNAL = "static_signal"

#: A dynamic probe actually demonstrated the defect. Reachable ONLY via :func:`make_proven_finding`,
#: which requires probe evidence — and no probe exists until CLX-3.3 (#4857). Until then, nothing in
#: this system can produce this value, which is precisely the guarantee AC5 asks for.
EXPLOITABILITY_PROVEN = "proven"

#: Every exploitability state, weakest first.
EXPLOITABILITY_STATES: Tuple[str, ...] = (EXPLOITABILITY_SIGNAL, EXPLOITABILITY_PROVEN)

#: Human labels. The signal label is deliberately explicit rather than neutral: a reader skimming a
#: list of red chips must not come away believing the server was demonstrated to be exploitable.
EXPLOITABILITY_LABELS: Mapping[str, str] = {
    EXPLOITABILITY_SIGNAL: "Signal — not proven exploitable",
    EXPLOITABILITY_PROVEN: "Proven by dynamic probe",
}

# --- Required evidence --------------------------------------------------------------------------
# What a rule needs in order to have an opinion. A rule whose evidence is absent is skipped and
# reported — never evaluated against an assumption.

#: Needs only the discovery surface, which every catalogued snapshot has. Always runnable, always
#: deterministic, always recomputable offline from the database.
REQUIRES_SURFACE = "surface"

#: Needs a source to be *linked* — but not its file contents fetched. This is the lighter of the two
#: source requirements: a rule that reasons about the source *association itself* (its pin strength,
#: its provenance) can run the moment a source is linked, without anyone fetching a byte of it. Kept
#: distinct from :data:`REQUIRES_SOURCE` so that linking a source lights up the pin-state rules even
#: on an offline recompute that never retrieved the artifact's files.
REQUIRES_SOURCE_LINK = "source_link"

#: Needs a linked source *and* its fetched documents (the static-check lane: secrets, unsafe config).
REQUIRES_SOURCE = "source"

#: Needs a component inventory (the SBOM lane).
REQUIRES_SBOM = "sbom"

#: Needs a completed vulnerability lookup (off by default; see :mod:`app.mcp_vulnerability`).
REQUIRES_VULNERABILITIES = "vulnerabilities"

#: Needs a dynamic probe. **Nothing satisfies this today** — CLX-3.3 (#4857) will. Rules declaring it
#: are permanently skipped until then, which is the honest state: they have observed nothing.
REQUIRES_PROBE = "probe"

#: Every evidence requirement, in stable order.
REQUIREMENTS: Tuple[str, ...] = (
    REQUIRES_SURFACE,
    REQUIRES_SOURCE_LINK,
    REQUIRES_SOURCE,
    REQUIRES_SBOM,
    REQUIRES_VULNERABILITIES,
    REQUIRES_PROBE,
)

#: Human explanations for why a rule was skipped, keyed by the requirement it lacked. Surfaced in the
#: report so a skipped rule explains itself rather than appearing as an unexplained absence.
SKIP_REASONS: Mapping[str, str] = {
    REQUIRES_SOURCE_LINK: (
        "No source is linked to this endpoint, so nothing is known about the artifact it is built "
        "from. Link a git repository, package, image, or registry identity to enable these rules."
    ),
    REQUIRES_SOURCE: (
        "The linked source's files were not available to inspect, so its code and configuration "
        "could not be scanned for secrets or unsafe patterns on this run."
    ),
    REQUIRES_SBOM: (
        "No component inventory is available for the linked source, so its dependencies could not "
        "be assessed. Attach an SBOM, or link a source whose lockfiles can be read."
    ),
    REQUIRES_VULNERABILITIES: (
        "Dependency-vulnerability lookup did not run, so known vulnerabilities in this server's "
        "dependencies are unknown — not absent."
    ),
    REQUIRES_PROBE: (
        "No dynamic probe has been run against this endpoint, so nothing here has been "
        "demonstrated against a live server (CLX-3.3, #4857)."
    ),
}


# --- Rule model ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PostureRule:
    """One registered trust-posture rule.

    Attributes:
        rule_id: Stable dotted id, exactly the string findings carry (e.g. ``metadata.tool-poisoning``
            or ``source.hardcoded-provider-credential``). Never renamed once shipped — it is hashed
            into finding ids and the report fingerprint.
        origin: Which evidence lane the rule reads (:data:`ORIGINS`).
        severity: ``error`` / ``warning`` / ``info``.
        owasp_ids: The OWASP MCP risks this rule speaks to. Validated against
            :mod:`app.mcp_owasp` at registration, so a rule citing a risk that does not exist is a
            startup failure rather than a dead link a user finds later.
        rationale: One line on what breaks when the rule is violated.
        reference: A resolvable URL for the rule's basis.
        requires: The evidence the rule needs. Absent evidence means the rule is skipped and
            reported, never assumed to pass.
    """

    rule_id: str
    origin: str
    severity: str
    owasp_ids: Tuple[str, ...]
    rationale: str
    reference: str = CATALOG_REFERENCE
    requires: str = REQUIRES_SURFACE

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ValueError(
                f"rule '{self.rule_id}' declares unknown origin {self.origin!r}; "
                f"known origins: {list(ORIGINS)}"
            )
        if self.requires not in REQUIREMENTS:
            raise ValueError(
                f"rule '{self.rule_id}' declares unknown requirement {self.requires!r}; "
                f"known requirements: {list(REQUIREMENTS)}"
            )
        # Validate (and canonically sort) the OWASP mapping at construction: a rule whose risk link
        # resolves to nothing is a broken rule, and it should break the process rather than a user's
        # report.
        object.__setattr__(self, "owasp_ids", validate_risk_ids(self.owasp_ids))

    def as_dict(self) -> Dict[str, Any]:
        """Return the rule descriptor as a JSON-ready dict (the ``/rules`` catalog payload)."""
        return {
            "rule_id": self.rule_id,
            "origin": self.origin,
            "origin_label": ORIGIN_LABELS[self.origin],
            "severity": self.severity,
            "owasp_ids": list(self.owasp_ids),
            "rationale": self.rationale,
            "reference": self.reference,
            "requires": self.requires,
        }


@dataclass(frozen=True)
class ProbeEvidence:
    """Proof from a dynamic probe that a defect is actually exploitable.

    **Nothing constructs this today.** It is the slot CLX-3.3 (#4857) fills, and it exists now so
    that :data:`EXPLOITABILITY_PROVEN` has exactly one guarded door rather than being a value any
    future rule could set on a whim. Making the honest state the *only reachable* state is the whole
    design; adding the door later, under deadline, is how that gets quietly undone.

    Attributes:
        probe_id: The probe that demonstrated it.
        observed: What the probe actually observed — the evidence, not an inference from it.
        probe_run_id: The probe run this came from, for audit.
    """

    probe_id: str
    observed: str
    probe_run_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Return the probe evidence as a JSON-ready dict."""
        return {
            "probe_id": self.probe_id,
            "observed": self.observed,
            "probe_run_id": self.probe_run_id,
        }


@dataclass(frozen=True)
class PostureFinding:
    """One trust-posture defect.

    Shares its core key set with :class:`app.mcp_lint.LintFinding` and
    :class:`app.mcp_conformance.ConformanceFinding` so all three normalize into the evidence
    envelope and score through the same code paths, and adds the four fields this lane needs:
    ``origin``, ``owasp_ids``, ``exploitability``, and ``confidence``.

    Attributes:
        path: Where the defect is — ``tools.search`` for a metadata finding, ``Dockerfile:12`` for a
            source finding, ``pkg:npm/lodash@4.17.20`` for a dependency finding.
        category: The rule's origin, mirrored here so the evidence envelope's ``category`` field
            carries it (the envelope has no ``origin`` key of its own).
        rule: The dotted rule id.
        severity: ``error`` / ``warning`` / ``info``.
        message: Human-readable description. Never contains secret material.
        origin: Which evidence lane produced this (:data:`ORIGINS`).
        owasp_ids: The OWASP MCP risks this is an instance of.
        exploitability: :data:`EXPLOITABILITY_SIGNAL` for everything a static rule can produce.
        confidence: ``high`` when the evidence is reproducible (surface, or a digest-pinned source);
            ``medium`` when it came from a moving reference that may no longer be what is running.
        excerpt: A redacted, bounded excerpt for a source finding. Never contains a secret in clear.
        remediation: What to actually do about it.
        probe: The probe evidence, when :data:`EXPLOITABILITY_PROVEN`. Always ``None`` today.
        id: Stable identifier; auto-derived from ``path|rule|message``.
    """

    path: str
    category: str
    rule: str
    severity: str
    message: str
    origin: str
    owasp_ids: Tuple[str, ...] = ()
    exploitability: str = EXPLOITABILITY_SIGNAL
    confidence: str = CONFIDENCE_HIGH
    excerpt: Optional[str] = None
    remediation: Optional[str] = None
    probe: Optional[ProbeEvidence] = None
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.path}|{self.rule}|{self.message}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"mcp-posture-{digest}")

    @property
    def is_proven(self) -> bool:
        """True only when a dynamic probe demonstrated this defect. Always False today."""
        return self.exploitability == EXPLOITABILITY_PROVEN and self.probe is not None

    def as_dict(self) -> Dict[str, Any]:
        """Return the finding as a JSON-ready dict.

        ``exploitability_label`` is emitted alongside the raw value so no consumer has to invent its
        own wording for it. A UI that renders the label it is given cannot accidentally overstate a
        static signal, and one that builds its own string can — so the honest string ships with the
        data.
        """
        return {
            "id": self.id,
            "path": self.path,
            "category": self.category,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "origin": self.origin,
            "origin_label": ORIGIN_LABELS.get(self.origin, self.origin),
            "owasp_ids": list(self.owasp_ids),
            "exploitability": self.exploitability,
            "exploitability_label": EXPLOITABILITY_LABELS[self.exploitability],
            "confidence": self.confidence,
            "excerpt": self.excerpt,
            "remediation": self.remediation,
            "probe": self.probe.as_dict() if self.probe is not None else None,
        }


# --- Evaluation context ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PostureContext:
    """Everything the rules get to look at.

    Each optional field is a lane of evidence that may or may not exist for a given endpoint. The
    engine consults :meth:`available_requirements` to decide which rules can run at all, and reports
    the rest as skipped — so what is missing here becomes a *visible gap in the report*, not a
    quietly narrower scan.

    Attributes:
        surface: The normalized capability surface. Always present.
        source: The linked source, when the endpoint has one.
        static_scan: Static findings over the source's fetched documents, when a source was fetched.
        inventory: The source's component inventory, when an SBOM was attached or derived.
        vulnerabilities: The dependency vulnerability lookup, when it ran.
        probes: Dynamic probe evidence. **Always empty today** — CLX-3.3 (#4857) fills it.
    """

    surface: DiscoverySurface
    source: Optional[SourceLink] = None
    static_scan: Optional[StaticScanResult] = None
    inventory: Optional[SbomInventory] = None
    vulnerabilities: Optional[VulnerabilityReport] = None
    probes: Tuple[ProbeEvidence, ...] = ()

    @property
    def confidence(self) -> str:
        """Confidence for findings derived from this context's source (see :mod:`app.mcp_source_link`)."""
        return confidence_for_link(self.source)

    def available_requirements(self) -> frozenset:
        """The evidence lanes this context can actually satisfy.

        A vulnerability report that did **not** run does not satisfy
        :data:`REQUIRES_VULNERABILITIES` — an empty result from a lookup that never happened is not
        evidence of no vulnerabilities, and treating it as such is the exact failure this engine is
        built to prevent. Hence the ``.ran`` check rather than a mere presence check.
        """
        available = {REQUIRES_SURFACE}
        if self.source is not None:
            # A linked source lights up the rules that reason about the association itself (pin
            # strength, provenance) — no file fetch required.
            available.add(REQUIRES_SOURCE_LINK)
        if self.source is not None and self.static_scan is not None:
            # The static-file rules additionally need the artifact's contents.
            available.add(REQUIRES_SOURCE)
        if self.inventory is not None:
            available.add(REQUIRES_SBOM)
        if self.vulnerabilities is not None and self.vulnerabilities.ran:
            available.add(REQUIRES_VULNERABILITIES)
        if self.probes:
            available.add(REQUIRES_PROBE)
        return frozenset(available)


# --- Registry -------------------------------------------------------------------------------------

#: Rule id -> descriptor, for every registered trust-posture rule.
RULE_REGISTRY: Dict[str, PostureRule] = {}

#: A rule function inspects the context and appends findings in any order (the engine sorts). Rules
#: MUST be pure: no I/O, no mutation of the context.
RuleFunction = Callable[[PostureContext, List[PostureFinding]], None]

#: Registered rule functions, each paired with the evidence lane it needs.
_RULE_FUNCTIONS: List[Tuple[RuleFunction, str]] = []


def register_rules(rules: Iterable[PostureRule]) -> None:
    """Register rule descriptors in :data:`RULE_REGISTRY`.

    Called at import time by each rule pack, before any of its rules can emit a finding, so
    :func:`make_finding` can always resolve a rule's origin, severity, and OWASP mapping.

    Args:
        rules: The descriptors to register.

    Raises:
        ValueError: If a rule id is already registered with different metadata — which catches two
            packs claiming the same id, and catches a shipped rule being silently redefined (its id
            is hashed into stored fingerprints, so redefining it would regrade history).
        app.mcp_owasp.UnknownRiskError: If a rule cites a risk that does not exist.
    """
    for rule in rules:
        existing = RULE_REGISTRY.get(rule.rule_id)
        if existing is not None and existing != rule:
            raise ValueError(
                f"trust-posture rule '{rule.rule_id}' is already registered with different "
                f"metadata; rule ids are stable and may not be redefined"
            )
        RULE_REGISTRY[rule.rule_id] = rule


def posture_rule(*, requires: str = REQUIRES_SURFACE) -> Callable[[RuleFunction], RuleFunction]:
    """Register a rule function with the engine (decorator factory).

    Args:
        requires: The evidence lane the function reads. The engine will not call it when that lane is
            unavailable, and will report the rules it covers as *skipped* rather than let an
            uninspected artifact read as a clean one.

    Returns:
        The decorator, which appends the function to the registry and returns it unchanged.
    """

    def decorate(func: RuleFunction) -> RuleFunction:
        _RULE_FUNCTIONS.append((func, requires))
        return func

    return decorate


def make_finding(
    path: str,
    rule_id: str,
    message: str,
    *,
    confidence: str = CONFIDENCE_HIGH,
    excerpt: Optional[str] = None,
    remediation: Optional[str] = None,
) -> PostureFinding:
    """Build a finding, resolving its origin, severity, and OWASP mapping from the registry.

    **This is the only constructor a rule may use, and it cannot produce a "proven" finding.** There
    is no parameter through which a rule could claim exploitability: every finding this function
    returns is a :data:`EXPLOITABILITY_SIGNAL`. That is what makes AC5 a property of the system
    rather than a promise about the UI — a static rule *cannot* assert that a defect is exploitable,
    because it has no way to say so.

    Args:
        path: The finding's location (surface path, ``file:line``, or a purl).
        rule_id: A rule id that MUST already be registered.
        message: Human-readable description. Must never contain secret material — the static rules
            redact before they reach here (:func:`app.mcp_static_checks.redact`).
        confidence: ``high`` when the evidence is reproducible; ``medium`` for a moving source
            reference (see :func:`app.mcp_source_link.confidence_for_link`).
        excerpt: A redacted, bounded excerpt, for a source finding.
        remediation: What to do about it.

    Returns:
        A fully populated :class:`PostureFinding`, always :data:`EXPLOITABILITY_SIGNAL`.

    Raises:
        KeyError: If ``rule_id`` is not registered — a rule pack emitting an unregistered id is a
            bug, and failing loudly beats emitting an unattributable finding.
    """
    rule = RULE_REGISTRY[rule_id]
    return PostureFinding(
        path=path,
        category=rule.origin,
        rule=rule.rule_id,
        severity=rule.severity,
        message=message,
        origin=rule.origin,
        owasp_ids=rule.owasp_ids,
        exploitability=EXPLOITABILITY_SIGNAL,
        confidence=confidence,
        excerpt=excerpt,
        remediation=remediation,
    )


def make_proven_finding(
    path: str,
    rule_id: str,
    message: str,
    *,
    probe: ProbeEvidence,
    remediation: Optional[str] = None,
) -> PostureFinding:
    """Build a finding a dynamic probe actually demonstrated. **Unused today.**

    The single, guarded door to :data:`EXPLOITABILITY_PROVEN`. It requires a :class:`ProbeEvidence`
    — not a boolean, not a flag, but the observation itself — so an "exploitable" claim always has
    the thing that justifies it attached to it, and cannot be asserted by a rule that merely feels
    confident.

    No caller exists: dynamic probes are CLX-3.3 (#4857). This is deliberately shipped now, unused,
    so the constraint is in place *before* there is pressure to bend it, and so #4857 has an obvious
    correct place to plug into rather than an incentive to widen :func:`make_finding`.

    Args:
        path: The finding's location.
        rule_id: A registered rule id.
        message: Human-readable description.
        probe: What the probe observed. Required — this is the whole point.
        remediation: What to do about it.

    Returns:
        A :class:`PostureFinding` with :data:`EXPLOITABILITY_PROVEN`.

    Raises:
        KeyError: If ``rule_id`` is not registered.
        ValueError: If ``probe`` is not supplied.
    """
    if probe is None:  # pragma: no cover - defended even though the type says otherwise
        raise ValueError(
            "a 'proven' finding requires ProbeEvidence; a static rule cannot prove exploitability"
        )
    rule = RULE_REGISTRY[rule_id]
    return PostureFinding(
        path=path,
        category=rule.origin,
        rule=rule.rule_id,
        severity=rule.severity,
        message=message,
        origin=rule.origin,
        owasp_ids=rule.owasp_ids,
        exploitability=EXPLOITABILITY_PROVEN,
        confidence=CONFIDENCE_HIGH,
        remediation=remediation,
        probe=probe,
    )


# --- Profiles ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PostureProfile:
    """A named, gateable selection of rules — the unit the CLI and API run.

    Attributes:
        profile_id: Stable id used on the wire (``--profile``, ``?profile=``).
        label: Human-readable name.
        origins: The finding origins this profile evaluates.
        description: What the profile is for, and when to gate on it.
    """

    profile_id: str
    label: str
    origins: Tuple[str, ...]
    description: str

    def includes(self, rule: PostureRule) -> bool:
        """True when ``rule`` is part of this profile."""
        return rule.origin in self.origins

    def as_dict(self) -> Dict[str, Any]:
        """Return the profile as a JSON-ready dict."""
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "origins": list(self.origins),
            "description": self.description,
        }


PROFILE_FULL = "mcp-trust-posture"
PROFILE_METADATA = "mcp-metadata-posture"
PROFILE_SUPPLY_CHAIN = "mcp-supply-chain"

#: Every runnable profile. ``mcp-trust-posture`` is the default and runs everything.
#:
#: The two halves exist because they have genuinely different prerequisites, and forcing them
#: together would make the useful half unusable. ``mcp-metadata-posture`` needs nothing but the
#: stored snapshot, so it runs for *every* catalogued endpoint and is gateable in CI today.
#: ``mcp-supply-chain`` needs a linked source, so for an endpoint without one it is all skips — a
#: team that gated on the full profile would be gating on a report that is mostly gaps.
PROFILES: Mapping[str, PostureProfile] = {
    PROFILE_FULL: PostureProfile(
        profile_id=PROFILE_FULL,
        label="MCP trust posture",
        origins=ORIGINS,
        description=(
            "Full posture: advertised metadata, linked source, dependencies, and observed protocol. "
            "The default profile. Rules whose evidence is absent are reported as skipped, never as "
            "passing."
        ),
    ),
    PROFILE_METADATA: PostureProfile(
        profile_id=PROFILE_METADATA,
        label="MCP metadata posture",
        origins=(ORIGIN_METADATA, ORIGIN_PROTOCOL),
        description=(
            "What the server advertises and how it behaved — tool poisoning, scope creep, "
            "shadowing, over-sharing, auth and audit gaps. Needs no linked source, so it runs for "
            "every catalogued endpoint and is suitable as a CI gate today."
        ),
    ),
    PROFILE_SUPPLY_CHAIN: PostureProfile(
        profile_id=PROFILE_SUPPLY_CHAIN,
        label="MCP supply chain",
        origins=(ORIGIN_SOURCE, ORIGIN_DEPENDENCY),
        description=(
            "What the server is built from — committed secrets, unsafe execution, excessive "
            "container authority, unpinned images, and vulnerable dependencies. Requires a linked "
            "source; without one, every rule is skipped and the report says so."
        ),
    ),
}

#: The profile used when a caller names none.
DEFAULT_PROFILE = PROFILE_FULL


class UnknownProfileError(ValueError):
    """Raised when a caller names a profile that is not in :data:`PROFILES`."""

    def __init__(self, profile_id: str) -> None:
        super().__init__(
            f"unknown trust-posture profile '{profile_id}'; known profiles: {sorted(PROFILES)}"
        )
        self.profile_id = profile_id


def resolve_profile(profile_id: Optional[str]) -> PostureProfile:
    """Resolve a profile id to its :class:`PostureProfile`, defaulting when ``None``.

    Args:
        profile_id: The requested profile id, or ``None`` for :data:`DEFAULT_PROFILE`.

    Returns:
        The resolved profile.

    Raises:
        UnknownProfileError: If ``profile_id`` names no known profile. Unknown profiles are rejected
            rather than silently defaulted, so a typo in CI never quietly widens or narrows what is
            being gated.
    """
    resolved = PROFILES.get(profile_id or DEFAULT_PROFILE)
    if resolved is None:
        raise UnknownProfileError(str(profile_id))
    return resolved


# --- Gate -------------------------------------------------------------------------------------------

#: Severity ranking, most severe first — the order a ``fail_on`` threshold is applied against.
SEVERITY_ORDER: Tuple[str, ...] = ("error", "warning", "info")

#: ``fail_on`` value meaning "never fail on findings alone".
FAIL_ON_NONE = "none"

#: Accepted ``fail_on`` thresholds: any severity, or ``none``.
FAIL_ON_VALUES: Tuple[str, ...] = (*SEVERITY_ORDER, FAIL_ON_NONE)


@dataclass(frozen=True)
class PostureGate:
    """The pass/fail decision for one posture run, and why.

    Attributes:
        passed: Whether the run satisfied every configured threshold.
        fail_on: Severity threshold — a finding of this severity *or worse* fails the gate.
        min_score: Optional score floor.
        require_full_coverage: When set, a run with any skipped rule fails the gate. This is how a
            team says "do not tell me this server is clean when you never looked at its source" —
            without it, an endpoint with no linked source passes the supply-chain profile trivially,
            because every rule that could have failed was skipped.
        reasons: Human-readable reasons the gate failed, empty when it passed.
    """

    passed: bool
    fail_on: str
    min_score: Optional[int] = None
    require_full_coverage: bool = False
    reasons: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        """Return the gate decision as a JSON-ready dict."""
        return {
            "passed": self.passed,
            "fail_on": self.fail_on,
            "min_score": self.min_score,
            "require_full_coverage": self.require_full_coverage,
            "reasons": list(self.reasons),
        }


def evaluate_gate(
    findings: Sequence[PostureFinding],
    score: int,
    skipped_rules: Sequence[str],
    *,
    fail_on: str = "error",
    min_score: Optional[int] = None,
    require_full_coverage: bool = False,
) -> PostureGate:
    """Decide whether a posture run passes its gate.

    Three independent thresholds, all of which must hold:

    * **Severity** — any finding at or above ``fail_on`` fails the gate. ``none`` disables it.
    * **Score floor** — an optional ``min_score``.
    * **Coverage** — when ``require_full_coverage`` is set, any skipped rule fails the gate.

    That third threshold is not decoration. A high score on a report where every source rule was
    skipped means "we found nothing wrong in the part we looked at", and the part we looked at may
    have been small. ``require_full_coverage`` is how a team refuses to accept that as a pass.

    Args:
        findings: The run's findings.
        score: The run's 0-100 score.
        skipped_rules: Rule ids that could not be evaluated for lack of evidence.
        fail_on: Severity threshold; one of :data:`FAIL_ON_VALUES`.
        min_score: Optional score floor (0-100).
        require_full_coverage: Fail when any rule was skipped.

    Returns:
        The :class:`PostureGate` decision, carrying a reason per failed threshold.

    Raises:
        ValueError: If ``fail_on`` is not one of :data:`FAIL_ON_VALUES`.
    """
    if fail_on not in FAIL_ON_VALUES:
        raise ValueError(f"fail_on must be one of {list(FAIL_ON_VALUES)}, not {fail_on!r}")

    reasons: List[str] = []
    if fail_on != FAIL_ON_NONE:
        triggering = set(SEVERITY_ORDER[: SEVERITY_ORDER.index(fail_on) + 1])
        hits = [f for f in findings if f.severity in triggering]
        if hits:
            counts = severity_counts([f.as_dict() for f in hits])
            detail = ", ".join(f"{counts[sev]} {sev}" for sev in SEVERITY_ORDER if counts[sev])
            reasons.append(f"{len(hits)} finding(s) at or above '{fail_on}' ({detail})")

    if min_score is not None and score < min_score:
        reasons.append(f"score {score} is below the required minimum of {min_score}")

    if require_full_coverage and skipped_rules:
        reasons.append(
            f"{len(skipped_rules)} rule(s) could not be evaluated for lack of evidence "
            f"({', '.join(sorted(skipped_rules)[:5])}"
            f"{', …' if len(skipped_rules) > 5 else ''}); full coverage was required"
        )

    return PostureGate(
        passed=not reasons,
        fail_on=fail_on,
        min_score=min_score,
        require_full_coverage=require_full_coverage,
        reasons=tuple(reasons),
    )


# --- Report -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PostureReport:
    """The rolled-up result of one trust-posture run.

    Attributes:
        profile: The profile that was run.
        findings: Ordered, deterministic findings (sorted by ``(path, rule, id)``).
        score: 0-100 score, on the same penalty model and scale as the MCP surface lint and
            conformance scores, so all three are directly comparable.
        grade: A-F grade of ``score``.
        rule_hits: Findings per rule id.
        severity_counts: Findings per severity (all three keys always present).
        origin_counts: Findings per origin — how much of this report came from what the server
            *said* versus what its *code* contains.
        owasp_counts: Findings per OWASP risk id.
        owasp_coverage: Which risks the evaluated rules cover, and — the important half — which they
            do not.
        evaluated_rules: Rule ids the profile actually evaluated.
        skipped_rules: Rule ids the profile selected but could NOT evaluate, for lack of evidence.
        skip_reasons: Why, keyed by rule id. A skipped rule explains itself.
        proven_count: Findings a dynamic probe demonstrated. **Always 0** until CLX-3.3 (#4857).
        source: The linked source's descriptor, or ``None``.
        gate: The pass/fail decision.
        report_fingerprint: Stable hash over the profile, score, grade, and sorted findings.
    """

    profile: PostureProfile
    findings: Tuple[PostureFinding, ...]
    score: int
    grade: str
    rule_hits: Mapping[str, int]
    severity_counts: Mapping[str, int]
    origin_counts: Mapping[str, int]
    owasp_counts: Mapping[str, int]
    owasp_coverage: Mapping[str, Any]
    evaluated_rules: Tuple[str, ...]
    skipped_rules: Tuple[str, ...]
    skip_reasons: Mapping[str, str]
    proven_count: int
    source: Optional[Mapping[str, Any]]
    gate: PostureGate
    report_fingerprint: str

    def finding_dicts(self) -> List[Dict[str, Any]]:
        """Return the findings as JSON-ready dicts, in the engine's sorted order."""
        return [finding.as_dict() for finding in self.findings]

    def report_dict(self) -> Dict[str, Any]:
        """Return the whole report as a JSON-ready dict.

        The key set intentionally *contains* the MCP lint report's keys (``score``, ``grade``,
        ``findings``, ``rule_hits``, ``severity_counts``, ``report_fingerprint``) so every consumer
        that already understands a lint report — the evidence normalizer, the axis model, the
        SARIF/JUnit gate serializer — reads a posture report unchanged, exactly as a conformance
        report does.
        """
        return {
            "profile": self.profile.profile_id,
            "owasp_revision": CATALOG_REVISION,
            "score": self.score,
            "grade": self.grade,
            "report_fingerprint": self.report_fingerprint,
            "rule_hits": dict(self.rule_hits),
            "severity_counts": dict(self.severity_counts),
            "origin_counts": dict(self.origin_counts),
            "owasp_counts": dict(self.owasp_counts),
            "owasp_coverage": dict(self.owasp_coverage),
            "findings": self.finding_dicts(),
            "evaluated_rules": list(self.evaluated_rules),
            "skipped_rules": list(self.skipped_rules),
            "skip_reasons": dict(self.skip_reasons),
            "proven_count": self.proven_count,
            "source": dict(self.source) if self.source is not None else None,
            "gate": self.gate.as_dict(),
        }


def _counts(values: Iterable[str]) -> Dict[str, int]:
    """Tally an iterable of keys into a sorted count map (stable for rendering)."""
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _report_fingerprint(
    profile_id: str, score: int, grade: str, findings: Sequence[Mapping[str, Any]]
) -> str:
    """Stable hash over the profile, score, grade, and sorted findings.

    The profile is part of the hash because the same context legitimately produces different reports
    under different profiles; without it, a supply-chain-only run and a full run could collide.
    """
    payload = {
        "profile": profile_id,
        "score": score,
        "grade": grade,
        "findings": sorted(
            [
                {
                    "id": f.get("id", ""),
                    "path": f.get("path", ""),
                    "rule": f.get("rule", ""),
                    "severity": f.get("severity", ""),
                }
                for f in findings
            ],
            key=lambda f: (f["path"], f["rule"], f["id"]),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def run_trust_posture(
    context: PostureContext,
    *,
    profile: Optional[str] = None,
    fail_on: str = "error",
    min_score: Optional[int] = None,
    require_full_coverage: bool = False,
) -> PostureReport:
    """Run a posture ``profile`` over ``context`` and roll it up into a gated report.

    Rules are selected by the profile's origins, then filtered by what the context can actually
    evidence: a rule whose evidence lane is missing is *skipped and reported*, never evaluated
    against an assumption. The surviving rules run, their findings are sorted deterministically,
    scored on the same penalty model as the other two MCP engines, and gated.

    A run over a snapshot with no linked source is fully deterministic and reproducible offline —
    which is what lets the API recompute posture from the database with no network access.

    Args:
        context: The surface, plus whichever evidence lanes exist for this endpoint.
        profile: The profile id to run; defaults to :data:`DEFAULT_PROFILE`.
        fail_on: Severity threshold for the gate.
        min_score: Optional score floor for the gate.
        require_full_coverage: Fail the gate when any rule was skipped.

    Returns:
        The rolled-up :class:`PostureReport`.

    Raises:
        UnknownProfileError: If ``profile`` names no known profile.
        ValueError: If ``fail_on`` is not a recognized threshold.
    """
    resolved = resolve_profile(profile)
    available = context.available_requirements()

    in_profile = [rule for rule in RULE_REGISTRY.values() if resolved.includes(rule)]
    evaluated = sorted(rule.rule_id for rule in in_profile if rule.requires in available)
    skipped = sorted(rule.rule_id for rule in in_profile if rule.requires not in available)
    runnable = frozenset(evaluated)

    # Every skipped rule says why. An unexplained absence in a security report reads as an oversight;
    # an explained one reads as a gap the reader can close.
    skip_reasons = {
        rule_id: SKIP_REASONS.get(
            RULE_REGISTRY[rule_id].requires,
            f"Required evidence '{RULE_REGISTRY[rule_id].requires}' is not available.",
        )
        for rule_id in skipped
    }

    findings: List[PostureFinding] = []
    for func, requires in _RULE_FUNCTIONS:
        if requires not in available:
            continue
        collected: List[PostureFinding] = []
        func(context, collected)
        # A rule function may cover several rule ids; keep only the ones this profile selected, so a
        # pack can group related checks in one function without leaking findings from an origin the
        # caller did not ask for.
        findings.extend(f for f in collected if f.rule in runnable)

    findings.sort(key=lambda f: (f.path, f.rule, f.id))
    ordered = tuple(findings)
    as_dicts = [f.as_dict() for f in ordered]

    score = score_from_finding_dicts(as_dicts)
    grade = grade_for_score(score)

    return PostureReport(
        profile=resolved,
        findings=ordered,
        score=score,
        grade=grade,
        rule_hits=_counts(f.rule for f in ordered),
        severity_counts=severity_counts(as_dicts),
        origin_counts=_counts(f.origin for f in ordered),
        owasp_counts=_counts(risk for f in ordered for risk in f.owasp_ids),
        owasp_coverage=coverage_summary(
            [RULE_REGISTRY[rule_id].owasp_ids for rule_id in evaluated]
        ),
        evaluated_rules=tuple(evaluated),
        skipped_rules=tuple(skipped),
        skip_reasons=skip_reasons,
        # Always 0 today: no rule can construct a proven finding (see make_finding), and no probe
        # exists to supply the evidence make_proven_finding demands. Counted rather than assumed, so
        # that when CLX-3.3 lands this number starts moving on its own.
        proven_count=sum(1 for f in ordered if f.is_proven),
        source=context.source.as_dict() if context.source is not None else None,
        gate=evaluate_gate(
            ordered,
            score,
            skipped,
            fail_on=fail_on,
            min_score=min_score,
            require_full_coverage=require_full_coverage,
        ),
        report_fingerprint=_report_fingerprint(resolved.profile_id, score, grade, as_dicts),
    )


def rule_catalog(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return every registered rule descriptor, sorted by rule id.

    This is the payload behind the rules catalog endpoint: how a consumer discovers which OWASP risk
    each rule maps to, which evidence lane it reads, and what it needs in order to run at all.

    Args:
        profile: When given, restrict the catalog to the rules that profile evaluates.

    Returns:
        The rule descriptors as JSON-ready dicts, sorted by ``rule_id``.

    Raises:
        UnknownProfileError: If ``profile`` names no known profile.
    """
    resolved = resolve_profile(profile) if profile is not None else None
    rules = [
        rule
        for rule in RULE_REGISTRY.values()
        if resolved is None or resolved.includes(rule)
    ]
    return [rule.as_dict() for rule in sorted(rules, key=lambda r: r.rule_id)]


# --- Rule pack auto-registration ----------------------------------------------------------------------
# The pack registers its descriptors and rule functions on import. Importing it here — after every
# public symbol above is defined, so the import is non-circular — means any caller of
# :func:`run_trust_posture` gets the full rule set with no extra wiring, exactly as
# :mod:`app.mcp_conformance` does for its own packs.
from . import mcp_trust_posture_rules as _mcp_trust_posture_rules  # noqa: E402,F401,I001  (side-effecting)
