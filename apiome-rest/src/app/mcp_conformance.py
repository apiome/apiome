"""MCP protocol-conformance & agent-readiness engine (CLX-3.1, #4855).

The MCP surface linter (:mod:`app.mcp_lint`) answers "is each advertised capability
well-formed and well-described?". It cannot answer the two questions an agent host actually
has to answer before it trusts a server:

1. **Does the server behave like an MCP server?** — did it negotiate a protocol version
   honestly, does it answer with well-formed JSON-RPC envelopes, does its pagination
   terminate, does it list only the capabilities it declared?
2. **Can an agent actually use these tools safely?** — are descriptions substantive, are
   parameters constrained, are destructive operations declared as such, is there recovery
   guidance when a call fails?

This module is the engine for both. It is deliberately a *separate* engine from
:mod:`app.mcp_lint` rather than more rule packs bolted into it, for two reasons that are not
stylistic:

* **The surface score must not move.** ``mcp_score.score_mcp_surface`` runs every rule in the
  shared registry and hashes the result into a persisted ``report_fingerprint``. Adding a
  dozen rules there would silently change the score, grade, and fingerprint of every MCP
  snapshot already stored — a retroactive regrade of history. Conformance therefore carries
  its own registry, its own score, and its own fingerprint, and leaves the surface report
  byte-identical.
* **The surface engine cannot see the wire.** Its rules take a ``DiscoverySurface`` and
  nothing else. Protocol behaviour is only observable in the JSON-RPC exchanges, so
  conformance rules take a :class:`ConformanceContext` — the surface *plus* an optional
  redacted :class:`~app.mcp_protocol_transcript.ProtocolTranscript`.

Determinism contract
--------------------

The two halves have deliberately different guarantees, and the engine keeps them honest:

* A rule declared ``requires_transcript=False`` reads only the persisted surface. It is
  **deterministic and offline** — the same stored snapshot always yields the same findings,
  so conformance can be recomputed from the database at any time with no network access.
* A rule declared ``requires_transcript=True`` reads the transcript, which is *observational*
  live evidence. When no transcript is available the engine **skips** the rule and reports it
  in :attr:`ConformanceReport.skipped_rules` — it never guesses, and an unobserved protocol
  behaviour never silently reads as a pass.

Every rule cites the MCP specification revision it is derived from and a resolvable source
reference (:attr:`ConformanceRule.spec_version` / :attr:`ConformanceRule.spec_reference`), so
a finding always traces back to a normative statement rather than to an opinion.

Profiles
--------

A *profile* is a named, gateable selection of rules (:data:`PROFILES`) — the unit the CLI and
API run and gate. ``mcp-conformance`` (the default) runs everything; ``mcp-protocol`` and
``mcp-agent-readiness`` run one half each, so a team can gate hard protocol correctness in CI
without also gating on advisory tool-definition quality.

The concrete rules live in the two packs that self-register on import at the bottom of this
module: :mod:`app.mcp_conformance_rules` (protocol) and :mod:`app.mcp_agent_readiness`
(agent-readiness).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .axis_score import grade_for_score, score_from_finding_dicts, severity_counts
from .mcp_client.normalize import DiscoverySurface
from .mcp_protocol_transcript import ProtocolTranscript

# --- Specification identity -------------------------------------------------------------------

#: The MCP specification revision this rule set is written against. Every rule cites it (or an
#: older revision, when the rule encodes a requirement that predates it), so a finding is always
#: attributable to a specific version of the spec rather than to a moving target.
MCP_SPEC_VERSION = "2025-06-18"

#: Base URL of the cited specification revision; rule references extend it with a page path.
SPEC_BASE = f"https://modelcontextprotocol.io/specification/{MCP_SPEC_VERSION}"

#: Resolvable references for the specification pages the rules derive from.
SPEC_LIFECYCLE = f"{SPEC_BASE}/basic/lifecycle"
SPEC_TRANSPORTS = f"{SPEC_BASE}/basic/transports"
SPEC_PAGINATION = f"{SPEC_BASE}/server/utilities/pagination"
SPEC_TOOLS = f"{SPEC_BASE}/server/tools"
SPEC_RESOURCES = f"{SPEC_BASE}/server/resources"
SPEC_PROMPTS = f"{SPEC_BASE}/server/prompts"

#: Agent-readiness rules encode *published, transparent* tool-definition-quality concepts —
#: the categories ToolBench and Anthropic's tool-authoring guidance both identify as what makes
#: a tool usable by a model (substantive descriptions, constrained parameters, declared
#: destructive operations, recovery guidance). They are reimplemented here as Apiome rules with
#: their own thresholds and their own published rationale; no third-party score is copied,
#: imported, or approximated, and each rule stands on its own stated reasoning.
REFERENCE_TOOL_AUTHORING = "https://www.anthropic.com/engineering/writing-tools-for-agents"

#: The two rule categories, which are also the two halves a profile can select.
CATEGORY_PROTOCOL = "protocol"
CATEGORY_READINESS = "readiness"


# --- Rule model -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformanceRule:
    """One registered conformance rule: identity, weight, provenance, and evidence needs.

    Attributes:
        rule_id: Stable dotted id, exactly the string findings carry in their ``rule`` field
            (e.g. ``protocol.jsonrpc-version-invalid``). Never renamed once shipped — it is
            hashed into finding ids and the report fingerprint.
        category: :data:`CATEGORY_PROTOCOL` or :data:`CATEGORY_READINESS`.
        severity: ``error`` (a normative MUST is violated) / ``warning`` (a SHOULD, or a
            posture gap worth review) / ``info`` (advisory).
        spec_version: The MCP specification revision the rule is derived from.
        spec_reference: A resolvable URL for the normative statement (or, for the
            agent-readiness pack, the published guidance the rule transparently encodes).
        rationale: One line on why the rule exists — what breaks when it is violated.
        requires_transcript: When ``True`` the rule reads live protocol evidence and is
            skipped (never guessed at) if no transcript was captured.
    """

    rule_id: str
    category: str
    severity: str
    spec_version: str
    spec_reference: str
    rationale: str
    requires_transcript: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """Return the rule descriptor as a JSON-ready dict (the ``/rules`` catalog payload)."""
        return {
            "rule_id": self.rule_id,
            "category": self.category,
            "severity": self.severity,
            "spec_version": self.spec_version,
            "spec_reference": self.spec_reference,
            "rationale": self.rationale,
            "requires_transcript": self.requires_transcript,
        }


@dataclass(frozen=True)
class ConformanceFinding:
    """One conformance defect.

    Mirrors :class:`app.mcp_lint.LintFinding` field-for-field so both kinds of finding render,
    normalize into the evidence envelope, and score through exactly the same code paths. The
    id is a stable hash of ``path|rule|message`` (prefixed ``mcp-conf-``), so re-running over
    unchanged inputs reproduces identical ids and a stable report fingerprint.

    Attributes:
        path: Where in the surface (or transcript) the defect is — e.g. ``tools.search`` or
            ``transcript.tools/list``.
        category: The rule's category, resolved from the registry.
        rule: The dotted rule id.
        severity: ``error`` / ``warning`` / ``info``.
        message: Human-readable description of the defect.
        id: Stable identifier; auto-derived when not supplied.
    """

    path: str
    category: str
    rule: str
    severity: str
    message: str
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.path}|{self.rule}|{self.message}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"mcp-conf-{digest}")

    def as_dict(self) -> Dict[str, str]:
        """Return a JSON-ready dict of this finding (same key set as an MCP lint finding)."""
        return {
            "id": self.id,
            "path": self.path,
            "category": self.category,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


# --- Evaluation context -----------------------------------------------------------------------


@dataclass(frozen=True)
class ConformanceContext:
    """What the rules get to look at: the stored surface, and live evidence when it exists.

    Attributes:
        surface: The normalized capability surface. Always present — it is the deterministic,
            offline-recomputable half of the evidence.
        transcript: The redacted protocol transcript captured during discovery, when one was.
            ``None`` for a recompute from the database, in which case every transcript-backed
            rule is skipped rather than assumed to pass.
    """

    surface: DiscoverySurface
    transcript: Optional[ProtocolTranscript] = None

    @property
    def has_transcript(self) -> bool:
        """True when live protocol evidence is available to the transcript-backed rules."""
        return self.transcript is not None


# --- Registry ---------------------------------------------------------------------------------
# Rule packs declare their descriptors and register their rule functions here on import. The
# registry is separate from :data:`app.mcp_lint.RULE_CATALOGUE` on purpose (see the module
# docstring): the surface score must not move when a conformance rule is added.

#: Rule id -> descriptor, for every registered conformance rule.
RULE_REGISTRY: Dict[str, ConformanceRule] = {}

#: A rule function inspects the context and appends findings in any order (the engine sorts).
#: Rules MUST be pure: no I/O, no mutation of the context.
RuleFunction = Callable[[ConformanceContext, List[ConformanceFinding]], None]

#: Registered rule functions, each paired with whether it needs live transcript evidence.
_RULE_FUNCTIONS: List[Tuple[RuleFunction, bool]] = []


def register_rules(rules: Iterable[ConformanceRule]) -> None:
    """Register rule descriptors in :data:`RULE_REGISTRY`.

    Called at import time by each rule pack, before any of its rules can emit a finding, so
    :func:`make_finding` can always resolve a rule's category and severity. Re-registering an
    identical descriptor is a no-op; redefining an existing rule id with *different* metadata
    raises, which catches two packs accidentally claiming the same id.

    Args:
        rules: The descriptors to register.

    Raises:
        ValueError: If a rule id is already registered with a different descriptor.
    """
    for rule in rules:
        existing = RULE_REGISTRY.get(rule.rule_id)
        if existing is not None and existing != rule:
            raise ValueError(
                f"conformance rule '{rule.rule_id}' is already registered with different "
                f"metadata; rule ids are stable and may not be redefined"
            )
        RULE_REGISTRY[rule.rule_id] = rule


def conformance_rule(*, requires_transcript: bool = False) -> Callable[[RuleFunction], RuleFunction]:
    """Register a rule function with the engine (decorator factory).

    Args:
        requires_transcript: Declare that the function reads
            :attr:`ConformanceContext.transcript`. The engine will not call it when no
            transcript was captured, and will list the rules it covers as *skipped* rather
            than let an unobserved behaviour read as a pass.

    Returns:
        The decorator, which appends the function to the registry and returns it unchanged.
    """

    def decorate(func: RuleFunction) -> RuleFunction:
        _RULE_FUNCTIONS.append((func, requires_transcript))
        return func

    return decorate


def make_finding(path: str, rule_id: str, message: str) -> ConformanceFinding:
    """Build a finding, resolving its category and severity from :data:`RULE_REGISTRY`.

    Args:
        path: The finding's location (surface path or ``transcript.<method>``).
        rule_id: A rule id that MUST already be registered.
        message: Human-readable description of the defect.

    Returns:
        A fully populated :class:`ConformanceFinding` with a stable, auto-derived id.

    Raises:
        KeyError: If ``rule_id`` is not registered — a rule pack emitting an unregistered id
            is a bug, and failing loudly beats emitting an unattributable finding.
    """
    rule = RULE_REGISTRY[rule_id]
    return ConformanceFinding(
        path=path,
        category=rule.category,
        rule=rule.rule_id,
        severity=rule.severity,
        message=message,
    )


# --- Profiles ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformanceProfile:
    """A named, gateable selection of rules — the unit the CLI and API run.

    Attributes:
        profile_id: Stable id used on the wire (``--profile``, ``?profile=``).
        label: Human-readable name.
        categories: The rule categories this profile evaluates.
        description: What the profile is for, and when to gate on it.
    """

    profile_id: str
    label: str
    categories: Tuple[str, ...]
    description: str

    def includes(self, rule: ConformanceRule) -> bool:
        """True when ``rule`` is part of this profile."""
        return rule.category in self.categories

    def as_dict(self) -> Dict[str, Any]:
        """Return the profile as a JSON-ready dict."""
        return {
            "profile_id": self.profile_id,
            "label": self.label,
            "categories": list(self.categories),
            "description": self.description,
        }


PROFILE_FULL = "mcp-conformance"
PROFILE_PROTOCOL = "mcp-protocol"
PROFILE_READINESS = "mcp-agent-readiness"

#: Every runnable profile, keyed by id. ``mcp-conformance`` is the default and runs everything;
#: the two halves exist so a team can gate hard protocol correctness in CI without also gating
#: on advisory tool-definition quality (or vice versa).
PROFILES: Mapping[str, ConformanceProfile] = {
    PROFILE_FULL: ConformanceProfile(
        profile_id=PROFILE_FULL,
        label="MCP conformance",
        categories=(CATEGORY_PROTOCOL, CATEGORY_READINESS),
        description=(
            "Full passive conformance: protocol behaviour plus agent-readiness of the tool "
            "definitions. The default profile."
        ),
    ),
    PROFILE_PROTOCOL: ConformanceProfile(
        profile_id=PROFILE_PROTOCOL,
        label="MCP protocol conformance",
        categories=(CATEGORY_PROTOCOL,),
        description=(
            "Protocol behaviour only: version negotiation, capability declaration, JSON-RPC "
            "envelopes and errors, and pagination. Suitable as a hard CI gate."
        ),
    ),
    PROFILE_READINESS: ConformanceProfile(
        profile_id=PROFILE_READINESS,
        label="MCP agent readiness",
        categories=(CATEGORY_READINESS,),
        description=(
            "Agent-readiness of the tool definitions only: descriptions, constrained "
            "parameters, output schemas, recovery guidance, bounded lists, destructive-"
            "operation declarations, naming, and annotations."
        ),
    ),
}

#: The profile used when a caller names none.
DEFAULT_PROFILE = PROFILE_FULL


class UnknownProfileError(ValueError):
    """Raised when a caller names a profile that is not in :data:`PROFILES`."""

    def __init__(self, profile_id: str) -> None:
        super().__init__(
            f"unknown conformance profile '{profile_id}'; known profiles: {sorted(PROFILES)}"
        )
        self.profile_id = profile_id


def resolve_profile(profile_id: Optional[str]) -> ConformanceProfile:
    """Resolve a profile id to its :class:`ConformanceProfile`, defaulting when ``None``.

    Args:
        profile_id: The requested profile id, or ``None`` for :data:`DEFAULT_PROFILE`.

    Returns:
        The resolved profile.

    Raises:
        UnknownProfileError: If ``profile_id`` names no known profile. Unknown profiles are
            rejected rather than silently defaulted, so a typo in CI never quietly widens or
            narrows what is being gated.
    """
    resolved = PROFILES.get(profile_id or DEFAULT_PROFILE)
    if resolved is None:
        raise UnknownProfileError(str(profile_id))
    return resolved


# --- Gate -------------------------------------------------------------------------------------

#: Severity ranking, most severe first — the order a ``fail_on`` threshold is applied against.
SEVERITY_ORDER: Tuple[str, ...] = ("error", "warning", "info")

#: ``fail_on`` value meaning "never fail on findings alone".
FAIL_ON_NONE = "none"

#: Accepted ``fail_on`` thresholds: any severity, or ``none``.
FAIL_ON_VALUES: Tuple[str, ...] = (*SEVERITY_ORDER, FAIL_ON_NONE)


@dataclass(frozen=True)
class ConformanceGate:
    """The pass/fail decision for one conformance run, and why.

    Attributes:
        passed: Whether the run satisfied every configured threshold.
        fail_on: The severity threshold applied — a finding of this severity *or worse* fails
            the gate. ``none`` disables severity gating.
        min_score: Optional score floor; a score below it fails the gate.
        reasons: Human-readable reasons the gate failed, empty when it passed.
    """

    passed: bool
    fail_on: str
    min_score: Optional[int] = None
    reasons: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        """Return the gate decision as a JSON-ready dict."""
        return {
            "passed": self.passed,
            "fail_on": self.fail_on,
            "min_score": self.min_score,
            "reasons": list(self.reasons),
        }


def evaluate_gate(
    findings: Sequence[ConformanceFinding],
    score: int,
    *,
    fail_on: str = "error",
    min_score: Optional[int] = None,
) -> ConformanceGate:
    """Decide whether a conformance run passes its gate.

    Two independent thresholds, both of which must hold:

    * **Severity** — any finding whose severity is ``fail_on`` *or more severe* fails the gate.
      ``fail_on="warning"`` therefore also fails on errors, and ``fail_on="none"`` disables
      severity gating entirely (useful for a report-only CI stage).
    * **Score floor** — an optional ``min_score``; the run fails when its score is below it.

    Args:
        findings: The run's findings.
        score: The run's 0-100 score.
        fail_on: Severity threshold; one of :data:`FAIL_ON_VALUES`.
        min_score: Optional score floor (0-100).

    Returns:
        The :class:`ConformanceGate` decision, carrying a reason per failed threshold.

    Raises:
        ValueError: If ``fail_on`` is not one of :data:`FAIL_ON_VALUES`.
    """
    if fail_on not in FAIL_ON_VALUES:
        raise ValueError(
            f"fail_on must be one of {list(FAIL_ON_VALUES)}, not {fail_on!r}"
        )

    reasons: List[str] = []
    if fail_on != FAIL_ON_NONE:
        # Everything at or above the threshold's rank, e.g. fail_on="warning" -> error+warning.
        triggering = set(SEVERITY_ORDER[: SEVERITY_ORDER.index(fail_on) + 1])
        hits = [f for f in findings if f.severity in triggering]
        if hits:
            counts = severity_counts([f.as_dict() for f in hits])
            detail = ", ".join(
                f"{counts[sev]} {sev}" for sev in SEVERITY_ORDER if counts[sev]
            )
            reasons.append(f"{len(hits)} finding(s) at or above '{fail_on}' ({detail})")

    if min_score is not None and score < min_score:
        reasons.append(f"score {score} is below the required minimum of {min_score}")

    return ConformanceGate(
        passed=not reasons,
        fail_on=fail_on,
        min_score=min_score,
        reasons=tuple(reasons),
    )


# --- Report -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ConformanceReport:
    """The rolled-up result of one conformance run.

    Attributes:
        profile: The profile that was run.
        findings: Ordered, deterministic findings (sorted by ``(path, rule, id)``).
        score: 0-100 score over the findings, on the same penalty model and scale as the MCP
            surface lint score, so the two are directly comparable.
        grade: A-F grade of ``score``, using the house thresholds.
        rule_hits: Findings per rule id, in sorted rule-id order.
        severity_counts: Findings per severity (all three keys always present).
        evaluated_rules: Rule ids the profile actually evaluated.
        skipped_rules: Rule ids in the profile that were *not* evaluated because they need a
            transcript and none was captured. Surfaced explicitly so an unobserved protocol
            behaviour is a visible gap, never a silent pass.
        transcript_captured: Whether live protocol evidence backed this run.
        gate: The pass/fail decision.
        report_fingerprint: Stable hash over the profile, score, grade, and sorted findings.
    """

    profile: ConformanceProfile
    findings: Tuple[ConformanceFinding, ...]
    score: int
    grade: str
    rule_hits: Mapping[str, int]
    severity_counts: Mapping[str, int]
    evaluated_rules: Tuple[str, ...]
    skipped_rules: Tuple[str, ...]
    transcript_captured: bool
    gate: ConformanceGate
    report_fingerprint: str

    def finding_dicts(self) -> List[Dict[str, str]]:
        """Return the findings as JSON-ready dicts, in the engine's sorted order."""
        return [finding.as_dict() for finding in self.findings]

    def report_dict(self) -> Dict[str, Any]:
        """Return the whole report as a JSON-ready dict.

        This is the payload the API serves, the CLI prints, and the evidence run stores. Its
        key set intentionally *contains* the MCP lint report's keys (``score``, ``grade``,
        ``findings``, ``rule_hits``, ``severity_counts``, ``report_fingerprint``) so every
        consumer that already understands a lint report — the evidence normalizer, the axis
        model, the SARIF/JUnit gate serializer — reads a conformance report unchanged.
        """
        return {
            "profile": self.profile.profile_id,
            "spec_version": MCP_SPEC_VERSION,
            "score": self.score,
            "grade": self.grade,
            "report_fingerprint": self.report_fingerprint,
            "rule_hits": dict(self.rule_hits),
            "severity_counts": dict(self.severity_counts),
            "findings": self.finding_dicts(),
            "evaluated_rules": list(self.evaluated_rules),
            "skipped_rules": list(self.skipped_rules),
            "transcript_captured": self.transcript_captured,
            "gate": self.gate.as_dict(),
        }


def _rule_hits(findings: Iterable[ConformanceFinding]) -> Dict[str, int]:
    """Count findings per rule id, in sorted rule-id order (stable for rendering)."""
    hits: Dict[str, int] = {}
    for finding in findings:
        hits[finding.rule] = hits.get(finding.rule, 0) + 1
    return dict(sorted(hits.items()))


def _report_fingerprint(
    profile_id: str, score: int, grade: str, findings: Sequence[Mapping[str, str]]
) -> str:
    """Stable hash over the profile, score, grade, and sorted findings.

    The profile is part of the hash because the same surface legitimately produces different
    reports under different profiles; without it, a protocol-only run and a full run could
    collide. Findings are re-sorted inside the payload and the JSON is emitted with sorted keys
    and no whitespace, so equal reports always hash equal regardless of input order.
    """
    payload = {
        "profile": profile_id,
        "score": score,
        "grade": grade,
        "findings": sorted(
            findings,
            key=lambda f: (f.get("path", ""), f.get("rule", ""), f.get("id", "")),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def run_conformance(
    context: ConformanceContext,
    *,
    profile: Optional[str] = None,
    fail_on: str = "error",
    min_score: Optional[int] = None,
) -> ConformanceReport:
    """Run a conformance ``profile`` over ``context`` and roll it up into a gated report.

    Rules are selected by the profile's categories, then filtered by what the context can
    actually evidence: a transcript-backed rule with no transcript is *skipped and reported*,
    never evaluated against an assumption. The surviving rules run, their findings are sorted
    into a deterministic order, scored on the same penalty model as the MCP surface lint, and
    gated.

    Given the same surface and the same profile, a run with no transcript is fully
    deterministic and reproducible offline — which is what lets the API recompute conformance
    from the database with no network access.

    Args:
        context: The surface, and the redacted transcript when one was captured.
        profile: The profile id to run; defaults to :data:`DEFAULT_PROFILE`.
        fail_on: Severity threshold for the gate (see :func:`evaluate_gate`).
        min_score: Optional score floor for the gate.

    Returns:
        The rolled-up :class:`ConformanceReport`.

    Raises:
        UnknownProfileError: If ``profile`` names no known profile.
        ValueError: If ``fail_on`` is not a recognized threshold.
    """
    resolved = resolve_profile(profile)

    in_profile = [rule for rule in RULE_REGISTRY.values() if resolved.includes(rule)]
    evaluated = sorted(
        rule.rule_id
        for rule in in_profile
        if context.has_transcript or not rule.requires_transcript
    )
    skipped = sorted(
        rule.rule_id
        for rule in in_profile
        if rule.requires_transcript and not context.has_transcript
    )
    runnable = frozenset(evaluated)

    findings: List[ConformanceFinding] = []
    for func, requires_transcript in _RULE_FUNCTIONS:
        if requires_transcript and not context.has_transcript:
            continue
        collected: List[ConformanceFinding] = []
        func(context, collected)
        # A rule function may cover several rule ids; keep only the ones this profile selected,
        # so a pack is free to group related checks in one function without leaking findings
        # from a category the caller did not ask for.
        findings.extend(f for f in collected if f.rule in runnable)

    findings.sort(key=lambda f: (f.path, f.rule, f.id))
    ordered = tuple(findings)
    as_dicts = [f.as_dict() for f in ordered]

    score = score_from_finding_dicts(as_dicts)
    grade = grade_for_score(score)

    return ConformanceReport(
        profile=resolved,
        findings=ordered,
        score=score,
        grade=grade,
        rule_hits=_rule_hits(ordered),
        severity_counts=severity_counts(as_dicts),
        evaluated_rules=tuple(evaluated),
        skipped_rules=tuple(skipped),
        transcript_captured=context.has_transcript,
        gate=evaluate_gate(ordered, score, fail_on=fail_on, min_score=min_score),
        report_fingerprint=_report_fingerprint(
            resolved.profile_id, score, grade, as_dicts
        ),
    )


def rule_catalog(profile: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return every registered rule descriptor, sorted by rule id.

    This is the payload behind the rules catalog endpoint: it is how a consumer discovers which
    MCP specification version each rule cites and where its normative source lives.

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


# --- Rule pack auto-registration ---------------------------------------------------------------
# The packs register their descriptors and rule functions on import. Importing them here — after
# every public symbol above is defined, so the import is non-circular — means any caller of
# :func:`run_conformance` gets the full rule set with no extra wiring, exactly as
# :mod:`app.mcp_lint` does for its own packs.
from . import mcp_agent_readiness as _mcp_agent_readiness  # noqa: E402,F401,I001  (side-effecting)
from . import mcp_conformance_rules as _mcp_conformance_rules  # noqa: E402,F401,I001  (side-effecting)
