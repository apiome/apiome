"""API change check suite — the rules of GNC-3.1 (#4740).

A pull request that changes an API used to collect a wall of checks — a lint run, a diff, a
breaking-change gate, a contract test, an SDK build — each with its own log and its own format, and
a reviewer who read none of them. The platform already *knew* every one of those answers. This
module turns them into **one** verdict, in the four words GNC-2.2 publishes to a provider:
``pending``, ``pass``, ``fail``, ``skipped``.

The suite has five components, and each is a reading of evidence an earlier ticket already
produces — nothing here is a new analysis:

============  ======  ==========================================================================
Component     Lane    What it reads
============  ======  ==========================================================================
lint          GOV     The revision's stored lint report (#5259): error-severity violations fail
                      it (the GOV-2.5 publish rule), then the grade is judged against CTG-4.5's
                      thresholds.
breaking      CTG     The CTG-1.1 classification of the draft against the previous published
                      revision, judged by CTG-4.5's own ``evaluate_breaking``.
consumers     CTG     CTG-4.2's per-consumer verdicts for that same classification, judged by
                      CTG-4.5's ``evaluate_consumers``.
contract      ECA     The newest ECA-1.3 contract run of this revision, and whether its suite is
                      still the suite this draft compiles to.
sdk           SDK     The SDK-3.3 client-kit manifest built from the draft: whether the Go client
                      and the server stubs still generate.
============  ======  ==========================================================================

Three rules make the verdict **deterministic**.

**One verdict model.** The lint, breaking and consumer components call the deploy gate's pure
evaluators (:mod:`app.deploy_gate`) against the deploy gate's thresholds, so the pull request and
the deploy gate cannot disagree about what "too breaking" means: this is a transport for that
verdict model, not a second opinion. A gate ``warn`` is a ``pass`` here (with ``warned`` set),
``not_configured`` is ``skipped``, and ``unknown`` — evidence that exists but could not be read —
is ``pending``: a check that cannot vouch must not turn green, and it is not a failure either.

**Policy decides what counts.** Each component is ``required``, ``advisory`` or ``off``. Only the
required ones reach the verdict, reduced with GNC-2.2's own precedence: one failure fails the
suite, an unfinished component holds it, and a set of skips is a skip — never a hollow pass. A
*required* component whose evidence has not been produced yet (no contract run of this draft) is
``pending``; an advisory one is ``skipped``.

**Same inputs, same row.** :func:`input_fingerprint` covers the draft's content digest, the commit,
both policies and every component's verdict and evidence, so re-running the suite over unchanged
inputs returns the evaluation that already says so — the same evidence ids, not a new record.

Like :mod:`app.provider_checks`, this module is data and pure functions only: no database, no HTTP,
no clock.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .consumer_impact import ConsumerImpactReport
from .deploy_gate import (
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_WARN,
    BreakingThresholds,
    ConsumerThresholds,
    GateSignal,
    LintThresholds,
    evaluate_breaking,
    evaluate_consumers,
    evaluate_lint,
)
from .provider_checks import (
    DEFAULT_CHECK_NAME,
    MAX_SUMMARY_LENGTH,
    MAX_TITLE_LENGTH,
    STATE_FAIL,
    STATE_PASS,
    STATE_PENDING,
    STATE_SKIPPED,
    CheckRunDetail,
    CheckState,
    summarize_states,
)

__all__ = [
    "AUDIT_SUITE_EVALUATED",
    "BreakingFacts",
    "CODE_COMMIT_UNKNOWN",
    "CODE_INVALID_COMMIT",
    "CODE_INVALID_DOCUMENT",
    "CODE_NOT_BOUND",
    "CODE_NOT_RUN",
    "CODE_POLICY_INVALID",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_RUN_NOT_FOUND",
    "CODE_VERSION_NOT_FOUND",
    "COMPONENTS",
    "COMPONENT_BREAKING",
    "COMPONENT_CONSUMERS",
    "COMPONENT_CONTRACT",
    "COMPONENT_LABELS",
    "COMPONENT_LINT",
    "COMPONENT_SDK",
    "CheckSuiteError",
    "CheckSuitePolicy",
    "CheckSuitePolicyError",
    "CheckSuitePolicyOut",
    "CheckSuiteRunDetail",
    "CheckSuiteRunList",
    "CheckSuiteRunRecord",
    "CheckSuiteRunRequest",
    "ContractFacts",
    "DEFAULT_POLICY",
    "DEFAULT_REQUIREMENTS",
    "LintFacts",
    "MAX_LISTED_EVIDENCE",
    "POLICY_SCHEMA_VERSION",
    "POLICY_SOURCES",
    "POLICY_SOURCE_DEFAULT",
    "POLICY_SOURCE_PROJECT",
    "POLICY_SOURCE_TENANT",
    "ProviderReport",
    "REASON_COMPONENT_OFF",
    "REASON_CONSUMERS_NO_BASELINE",
    "REASON_CONTRACT_FAILED",
    "REASON_CONTRACT_INCOMPLETE",
    "REASON_CONTRACT_MISSING",
    "REASON_CONTRACT_NOT_APPLICABLE",
    "REASON_CONTRACT_PASSED",
    "REASON_CONTRACT_STALE",
    "REASON_DRAFT_NOT_SYNCHRONIZED",
    "REASON_EVIDENCE_UNAVAILABLE",
    "REASON_LINT_ERRORS",
    "REASON_NO_CAPTURED_SOURCE",
    "REASON_NOTHING_APPLIED",
    "REASON_NO_REQUIRED",
    "REASON_REQUIRED_FAILED",
    "REASON_REQUIRED_PASSED",
    "REASON_REQUIRED_PENDING",
    "REASON_SDK_FAILED",
    "REASON_SDK_GENERATED",
    "REASON_SDK_NOT_APPLICABLE",
    "REASON_SPEC_UNCHANGED",
    "REQUIREMENTS",
    "REQUIREMENT_ADVISORY",
    "REQUIREMENT_OFF",
    "REQUIREMENT_REQUIRED",
    "SUITE_CHECK_NAME",
    "SUITE_SCHEMA_VERSION",
    "SdkFacts",
    "SuiteComponent",
    "aggregate",
    "canonical_policy_body",
    "component_counts",
    "component_from_signal",
    "disabled_component",
    "input_fingerprint",
    "judge_breaking",
    "judge_consumers",
    "judge_contract",
    "judge_lint",
    "judge_sdk",
    "policy_fingerprint",
    "policy_from_body",
    "render_summary",
    "render_title",
    "requirements_fingerprint",
    "unavailable_component",
    "unbuildable_component",
]

# ---------------------------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------------------------

#: Stable identity of a suite run body.
SUITE_SCHEMA_VERSION = "gnc.check-suite.v1"

#: Stable identity of the policy body a tenant writes.
POLICY_SCHEMA_VERSION = "gnc.check-suite-policy.v1"

#: The provider check the verdict becomes. Deliberately the name GNC-2.2's webhook seeds, so the
#: suite's verdict *replaces* the pending check that appeared when the pull request opened rather
#: than landing beside it.
SUITE_CHECK_NAME = DEFAULT_CHECK_NAME

COMPONENT_LINT = "lint"
COMPONENT_BREAKING = "breaking"
COMPONENT_CONSUMERS = "consumers"
COMPONENT_CONTRACT = "contract"
COMPONENT_SDK = "sdk"

#: Every component, in the order the suite reports them.
COMPONENTS: Tuple[str, ...] = (
    COMPONENT_LINT,
    COMPONENT_BREAKING,
    COMPONENT_CONSUMERS,
    COMPONENT_CONTRACT,
    COMPONENT_SDK,
)

#: What a reviewer reads for each component.
COMPONENT_LABELS: Dict[str, str] = {
    COMPONENT_LINT: "Lint (governance)",
    COMPONENT_BREAKING: "Breaking changes",
    COMPONENT_CONSUMERS: "Consumers",
    COMPONENT_CONTRACT: "Contract tests",
    COMPONENT_SDK: "SDK generation",
}

#: The component takes part in the verdict.
REQUIREMENT_REQUIRED = "required"
#: The component is evaluated and reported, and never changes the verdict.
REQUIREMENT_ADVISORY = "advisory"
#: The component is not evaluated at all.
REQUIREMENT_OFF = "off"
REQUIREMENTS: Tuple[str, ...] = (REQUIREMENT_REQUIRED, REQUIREMENT_ADVISORY, REQUIREMENT_OFF)

#: What a tenant that has configured nothing gets. The three components computed from the draft
#: itself are required; the two that depend on evidence somebody has to *produce* (a contract run
#: against a deployment, a published SDK line) are advisory, so a project that has never run a
#: contract test is not held pending forever by default.
DEFAULT_REQUIREMENTS: Dict[str, str] = {
    COMPONENT_LINT: REQUIREMENT_REQUIRED,
    COMPONENT_BREAKING: REQUIREMENT_REQUIRED,
    COMPONENT_CONSUMERS: REQUIREMENT_REQUIRED,
    COMPONENT_CONTRACT: REQUIREMENT_ADVISORY,
    COMPONENT_SDK: REQUIREMENT_ADVISORY,
}

POLICY_SOURCE_DEFAULT = "default"
POLICY_SOURCE_TENANT = "tenant"
POLICY_SOURCE_PROJECT = "project"
POLICY_SOURCES: Tuple[str, ...] = (
    POLICY_SOURCE_DEFAULT,
    POLICY_SOURCE_TENANT,
    POLICY_SOURCE_PROJECT,
)

#: ``workflow_audit`` action for every new evaluation, written inside its insert's transaction.
AUDIT_SUITE_EVALUATED = "check_suite.evaluated"

#: How many findings, breaking changes or consumers one component lists as evidence. The totals
#: are always reported; the list exists so a reviewer can act without a second request.
MAX_LISTED_EVIDENCE = 10

# ---------------------------------------------------------------------------------------------
# Reasons. A client branches on the reason, never on the prose.
# ---------------------------------------------------------------------------------------------

#: Suite: at least one required component failed.
REASON_REQUIRED_FAILED = "required-component-failed"
#: Suite: no required component failed, and at least one has no verdict yet.
REASON_REQUIRED_PENDING = "required-component-pending"
#: Suite: every required component that applied passed.
REASON_REQUIRED_PASSED = "required-components-passed"
#: Suite: every required component was skipped — nothing applied, so nothing may claim a pass.
REASON_NOTHING_APPLIED = "no-required-component-applied"
#: Suite: the policy requires no component at all.
REASON_NO_REQUIRED = "no-required-components"
#: Suite: the commit is ahead of the commit the draft is synchronized with.
REASON_DRAFT_NOT_SYNCHRONIZED = "draft-not-synchronized"
#: Suite: the commit does not change the bound specification.
REASON_SPEC_UNCHANGED = "spec-unchanged"

#: Component: the policy switched it off.
REASON_COMPONENT_OFF = "component-off"
#: Component: its evidence exists but could not be read.
REASON_EVIDENCE_UNAVAILABLE = "evidence-unavailable"
#: Component (lint): the style guide reports error-severity violations.
REASON_LINT_ERRORS = "lint-error-violations"
#: Component (consumers): nothing has been published on this line, so nobody consumes it.
REASON_CONSUMERS_NO_BASELINE = "consumers-no-baseline"
#: Component (contract): the version declares no callable operation.
REASON_CONTRACT_NOT_APPLICABLE = "contract-not-applicable"
#: Component (contract): no contract run of this revision has been recorded.
REASON_CONTRACT_MISSING = "contract-evidence-missing"
#: Component (contract): the newest run executed a suite this draft no longer compiles to.
REASON_CONTRACT_STALE = "contract-evidence-stale"
#: Component (contract): the newest run finished without a verdict (it was cancelled).
REASON_CONTRACT_INCOMPLETE = "contract-run-incomplete"
REASON_CONTRACT_PASSED = "contract-passed"
REASON_CONTRACT_FAILED = "contract-failed"
#: Component (sdk): the version has no operation a client could call.
REASON_SDK_NOT_APPLICABLE = "sdk-not-applicable"
#: Component (contract, sdk): the version has no captured source document, so no canonical model —
#: and so no suite and no kit — can be built from it. It was designed in the app, not imported.
REASON_NO_CAPTURED_SOURCE = "no-captured-source"
REASON_SDK_FAILED = "sdk-generation-failed"
REASON_SDK_GENERATED = "sdk-generated"

# ---------------------------------------------------------------------------------------------
# Refusal codes
# ---------------------------------------------------------------------------------------------

CODE_PROJECT_NOT_FOUND = "check-suite-project-not-found"
CODE_VERSION_NOT_FOUND = "check-suite-version-not-found"
CODE_RUN_NOT_FOUND = "check-suite-run-not-found"
#: The version has never been evaluated (or never at the named commit).
CODE_NOT_RUN = "check-suite-not-run"
#: A commit was named for a version that is not bound to a repository ref.
CODE_NOT_BOUND = "check-suite-not-bound"
#: A commit was named that the binding has never been observed at.
CODE_COMMIT_UNKNOWN = "check-suite-commit-unknown"
CODE_INVALID_COMMIT = "check-suite-invalid-commit"
#: The draft cannot be rebuilt into a document, so there is nothing to judge.
CODE_INVALID_DOCUMENT = "check-suite-invalid-document"
CODE_POLICY_INVALID = "check-suite-policy-invalid"


class CheckSuiteError(Exception):
    """A refusal from the suite, carrying a stable code.

    Attributes:
        code: One of the ``CODE_*`` constants in this module.
    """

    def __init__(self, code: str, message: str) -> None:
        """Create the refusal.

        Args:
            code: The stable refusal code.
            message: A human-readable explanation.
        """
        super().__init__(message)
        self.code = code


class CheckSuitePolicyError(ValueError):
    """A submitted policy body is not valid.

    Attributes:
        errors: One message per problem, so a caller fixes everything in one round trip.
    """

    def __init__(self, errors: Sequence[str]) -> None:
        """Create the refusal.

        Args:
            errors: Every problem found.
        """
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """camelCase out, either spelling in — the shape a tenant writes a policy body in."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CheckSuitePolicy(_CamelModel):
    """The ``gnc.check-suite-policy.v1`` body: what the suite requires.

    Attributes:
        components: The requirement of every component — always all five after parsing.
        required_for_publish: Whether publishing a version needs a passing (or skipped) suite
            evaluation of exactly its current content under exactly this policy.
    """

    components: Dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_REQUIREMENTS),
        description="`required` | `advisory` | `off` for each of lint, breaking, consumers, "
        "contract and sdk.",
    )
    required_for_publish: bool = Field(
        default=False,
        description="Refuse to publish a version whose current content has no passing suite "
        "evaluation under this policy.",
    )

    def requirement(self, component: str) -> str:
        """The requirement of one component.

        Args:
            component: One of :data:`COMPONENTS`.

        Returns:
            Its requirement, falling back to the documented default.
        """
        return self.components.get(component) or DEFAULT_REQUIREMENTS.get(
            component, REQUIREMENT_ADVISORY
        )

    def required_components(self) -> List[str]:
        """The components that take part in the verdict, in report order.

        Returns:
            The required components.
        """
        return [c for c in COMPONENTS if self.requirement(c) == REQUIREMENT_REQUIRED]


#: The policy a scope with nothing saved is judged under.
DEFAULT_POLICY = CheckSuitePolicy()


def policy_from_body(body: Optional[Mapping[str, Any]]) -> CheckSuitePolicy:
    """Parse and validate a submitted or stored policy body.

    Absent components take their documented defaults, so a body naming one component configures
    exactly that one. Every problem is collected before refusing, rather than one per round trip.

    Args:
        body: The policy object, or ``None``/empty for the documented default.

    Returns:
        The policy, with all five components present.

    Raises:
        CheckSuitePolicyError: When the body is not an object, names an unknown key or component,
            uses an unknown requirement, or requires the suite before publish while requiring no
            component — a gate that can never block.
    """
    if body is None:
        return DEFAULT_POLICY
    if not isinstance(body, Mapping):
        raise CheckSuitePolicyError(["The policy body must be a JSON object."])

    errors: List[str] = []
    components = dict(DEFAULT_REQUIREMENTS)
    required_for_publish = False
    for key, value in body.items():
        if key == "schemaVersion":
            continue
        if key == "components":
            if not isinstance(value, Mapping):
                errors.append("components must be an object of component → requirement.")
                continue
            for name, requirement in value.items():
                if name not in COMPONENTS:
                    errors.append(
                        f"components.{name} is not a component; use one of {', '.join(COMPONENTS)}."
                    )
                elif requirement not in REQUIREMENTS:
                    errors.append(
                        f"components.{name} must be one of {', '.join(REQUIREMENTS)} "
                        f"(got {requirement!r})."
                    )
                else:
                    components[str(name)] = str(requirement)
        elif key in ("requiredForPublish", "required_for_publish"):
            if not isinstance(value, bool):
                errors.append(f"{key} must be true or false (got {value!r}).")
            else:
                required_for_publish = value
        else:
            errors.append(f"{key} is not a policy setting; use components or requiredForPublish.")

    policy = CheckSuitePolicy(components=components, required_for_publish=required_for_publish)
    if policy.required_for_publish and not policy.required_components():
        errors.append(
            "requiredForPublish needs at least one required component — with none, the suite can "
            "only ever be skipped, and a publish gate that can never block is not a gate."
        )
    if errors:
        raise CheckSuitePolicyError(errors)
    return policy


def canonical_policy_body(policy: CheckSuitePolicy) -> Dict[str, Any]:
    """Render a policy as the stable dict that is stored, snapshotted and fingerprinted.

    Always the full body with every component present: a stored policy must keep meaning the same
    thing after a later release changes a default.

    Args:
        policy: The policy.

    Returns:
        ``{"schemaVersion", "components", "requiredForPublish"}``.
    """
    return {
        "schemaVersion": POLICY_SCHEMA_VERSION,
        "components": {component: policy.requirement(component) for component in COMPONENTS},
        "requiredForPublish": bool(policy.required_for_publish),
    }


def _digest(payload: Any) -> str:
    """``sha256:`` over the canonical JSON of a payload.

    Args:
        payload: Anything JSON-serializable (datetimes are stringified).

    Returns:
        ``"sha256:<hex>"``.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def policy_fingerprint(policy: CheckSuitePolicy) -> str:
    """A stable digest of a policy body.

    Args:
        policy: The policy.

    Returns:
        ``"sha256:<hex>"`` over :func:`canonical_policy_body`.
    """
    return _digest(canonical_policy_body(policy))


def requirements_fingerprint(policy: CheckSuitePolicy) -> str:
    """A stable digest of the part of a policy that decides a verdict: the component requirements.

    An evaluation is keyed on this, not on :func:`policy_fingerprint`, and so is the publish gate's
    "judged under the policy in force" match. ``requiredForPublish`` cannot change what the suite
    says about a draft — only whether publishing waits for it — so switching the gate on must not
    turn every evaluation already made into a stale one that has to be re-run for the same answer.

    Args:
        policy: The policy.

    Returns:
        ``"sha256:<hex>"`` over the schema version and the five requirements.
    """
    body = canonical_policy_body(policy)
    return _digest({"schemaVersion": body["schemaVersion"], "components": body["components"]})


class CheckSuitePolicyOut(_CamelModel):
    """The suite policy in force for a scope.

    Attributes:
        schema_version: :data:`POLICY_SCHEMA_VERSION`.
        source: ``default`` (nothing saved), ``tenant`` or ``project``.
        policy_id: The stored row; ``None`` for the documented default.
        content_fingerprint: Digest of the body.
        policy: The body itself.
        updated_at: When the stored policy last changed.
        updated_by: Who changed it.
        degraded: True when a saved policy could not be read and the default stood in, so
            "nothing is configured" and "I could not read what is" stay distinguishable.
    """

    schema_version: str = Field(default=POLICY_SCHEMA_VERSION)
    source: str = Field(description="`default` | `tenant` | `project`.")
    policy_id: Optional[str] = Field(default=None)
    content_fingerprint: str = Field(default="")
    policy: CheckSuitePolicy = Field(default_factory=CheckSuitePolicy)
    updated_at: Optional[datetime] = Field(default=None)
    updated_by: Optional[str] = Field(default=None)
    degraded: bool = Field(default=False)


# ---------------------------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------------------------


class SuiteComponent(BaseModel):
    """One component of the suite, judged — the unit of the drill-down.

    Attributes:
        component: One of :data:`COMPONENTS`.
        label: What a reviewer reads.
        requirement: ``required`` / ``advisory`` / ``off`` under the policy in force.
        counted: Whether it took part in the verdict (exactly when it is required).
        state: ``pending`` / ``pass`` / ``fail`` / ``skipped``.
        reason: Stable reason code — the deploy gate's for the three CTG-4.5 components.
        detail: One human sentence.
        warned: A pass that crossed a warning rung, or a pass with a caveat worth reading.
        link: API path of the evidence behind it.
        evidence: The facts the judgment was made from — ids, digests and counts.
        rule: The policy behind it: the requirement and, where one applies, the thresholds.
    """

    model_config = ConfigDict(extra="forbid")

    component: str
    label: str
    requirement: str
    counted: bool
    state: CheckState
    reason: str
    detail: str
    warned: bool = False
    link: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    rule: Dict[str, Any] = Field(default_factory=dict)


def _component(
    component: str,
    requirement: str,
    *,
    state: str,
    reason: str,
    detail: str,
    warned: bool = False,
    link: Optional[str] = None,
    evidence: Optional[Mapping[str, Any]] = None,
    rule: Optional[Mapping[str, Any]] = None,
) -> SuiteComponent:
    """Build a component, deriving ``counted`` and the rule's requirement from the requirement.

    Args:
        component: One of :data:`COMPONENTS`.
        requirement: Its requirement.
        state: Its state.
        reason: Its reason code.
        detail: One human sentence.
        warned: Whether a pass carries a caveat.
        link: Where its evidence lives.
        evidence: The facts it was judged from.
        rule: Rule details beyond the requirement.

    Returns:
        The component.
    """
    return SuiteComponent(
        component=component,
        label=COMPONENT_LABELS.get(component, component),
        requirement=requirement,
        counted=requirement == REQUIREMENT_REQUIRED,
        state=state,
        reason=reason,
        detail=detail,
        warned=warned,
        link=link,
        evidence=dict(evidence or {}),
        rule={"requirement": requirement, **dict(rule or {})},
    )


def _missing_state(requirement: str) -> str:
    """The state of a component whose evidence has not been produced yet.

    A required component is *waiting* for it — ``pending``, which a merge gate holds on. An
    advisory one simply did not apply this time — ``skipped``.

    Args:
        requirement: The component's requirement.

    Returns:
        ``pending`` or ``skipped``.
    """
    return STATE_PENDING if requirement == REQUIREMENT_REQUIRED else STATE_SKIPPED


def disabled_component(component: str) -> SuiteComponent:
    """The component as reported when the policy switched it off.

    It is still listed, so the drill-down says *why* it did not run rather than leaving a reader to
    wonder whether it was forgotten.

    Args:
        component: One of :data:`COMPONENTS`.

    Returns:
        A skipped, uncounted component.
    """
    return _component(
        component,
        REQUIREMENT_OFF,
        state=STATE_SKIPPED,
        reason=REASON_COMPONENT_OFF,
        detail=f"{COMPONENT_LABELS.get(component, component)} is switched off by the suite policy.",
    )


def unavailable_component(
    component: str,
    requirement: str,
    *,
    detail: str,
    link: Optional[str] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> SuiteComponent:
    """The component as reported when its evidence exists but could not be read.

    ``pending``, never ``pass`` and never ``fail``: a check that could not look must not turn
    green, and "the platform could not read this" is not a finding about the change either. A
    re-run once the evidence is readable replaces it.

    Args:
        component: One of :data:`COMPONENTS`.
        requirement: Its requirement.
        detail: What could not be read.
        link: Where the evidence would be.
        evidence: Anything that was read before the failure.

    Returns:
        A pending component.
    """
    return _component(
        component,
        requirement,
        state=STATE_PENDING,
        reason=REASON_EVIDENCE_UNAVAILABLE,
        detail=detail,
        link=link,
        evidence=evidence,
    )


def unbuildable_component(
    component: str,
    requirement: str,
    *,
    reason: str,
    link: Optional[str] = None,
) -> SuiteComponent:
    """The component as reported for a version no canonical model can be built from.

    ``skipped``: a version designed in the app rather than imported has no captured source
    document, so there is no contract suite to compile and no client kit to generate from it. That
    is a fact about the version — the same one the SDK kit route and the contract suite route
    report — and not a read that failed, so it neither waits nor fails.

    Args:
        component: ``contract`` or ``sdk``.
        requirement: Its requirement.
        reason: Why the model could not be built, as the loader said it.
        link: Where the evidence would be.

    Returns:
        A skipped component.
    """
    subject = (
        "No contract suite can be compiled"
        if component == COMPONENT_CONTRACT
        else "No client kit can be generated"
    )
    return _component(
        component,
        requirement,
        state=STATE_SKIPPED,
        reason=REASON_NO_CAPTURED_SOURCE,
        detail=(
            f"{subject}: this version has no captured source document to build from (it was "
            "designed in the app rather than imported)."
        ),
        link=link,
        evidence={"loader": reason},
    )


def component_from_signal(
    component: str,
    signal: GateSignal,
    requirement: str,
    *,
    rule: Optional[Mapping[str, Any]] = None,
    evidence: Optional[Mapping[str, Any]] = None,
) -> SuiteComponent:
    """Translate a CTG-4.5 gate signal into a suite component.

    ``pass`` → ``pass``; ``warn`` → ``pass`` with ``warned`` (a warning rung informs a reviewer,
    it does not block a merge); ``fail`` → ``fail``; ``not_configured`` → ``skipped`` (nothing to
    judge); ``unknown`` → ``pending`` (something to judge that could not be read). The gate's own
    reason code is kept, so the pull request and the deploy gate name a verdict the same way.

    Args:
        component: One of :data:`COMPONENTS`.
        signal: The judged gate signal.
        requirement: The component's requirement.
        rule: Rule details — the thresholds it was judged against.
        evidence: Facts beyond the signal's own data.

    Returns:
        The component.
    """
    if signal.status == STATUS_PASS:
        state, warned = STATE_PASS, False
    elif signal.status == STATUS_WARN:
        state, warned = STATE_PASS, True
    elif signal.status == STATUS_FAIL:
        state, warned = STATE_FAIL, False
    elif signal.status == STATUS_NOT_CONFIGURED:
        state, warned = STATE_SKIPPED, False
    else:
        state, warned = STATE_PENDING, False
    return _component(
        component,
        requirement,
        state=state,
        reason=signal.reason,
        detail=signal.detail,
        warned=warned,
        link=signal.link,
        evidence={**dict(signal.data), **dict(evidence or {})},
        rule=rule,
    )


def _thresholds_rule(thresholds: BaseModel) -> Dict[str, Any]:
    """The rule block of a component judged against CTG-4.5 thresholds.

    Args:
        thresholds: The threshold group in force.

    Returns:
        ``{"thresholdsFrom": "deploy-gate-policy", "thresholds": {...}}``.
    """
    return {
        "thresholdsFrom": "deploy-gate-policy",
        "thresholds": thresholds.model_dump(by_alias=True, mode="json"),
    }


@dataclass(frozen=True)
class LintFacts:
    """What the lint component reads off the revision's stored report.

    Attributes:
        grade: The letter grade, or ``None`` when no report could be captured.
        score: The 0-100 score.
        severity_counts: Findings per severity.
        error_findings: The error-severity findings, each ``{rule, path, message}``.
        guide: The style guide that scored it — ``{id, name, source, revisionId}``.
        report_fingerprint: The stored report's fingerprint: the evidence id.
    """

    grade: Optional[str]
    score: Optional[int]
    severity_counts: Mapping[str, int] = field(default_factory=dict)
    error_findings: Sequence[Mapping[str, str]] = ()
    guide: Mapping[str, Any] = field(default_factory=dict)
    report_fingerprint: Optional[str] = None


def judge_lint(
    facts: LintFacts,
    *,
    thresholds: LintThresholds,
    requirement: str,
    link: Optional[str],
) -> SuiteComponent:
    """Judge the governance evidence.

    Error-severity violations fail it first — they are exactly what the GOV-2.5 publish gate
    refuses, and a suite that maps onto publishing must not pass what publishing would refuse.
    Otherwise the grade is judged by CTG-4.5's :func:`~app.deploy_gate.evaluate_lint`.

    Args:
        facts: The stored report's facts.
        thresholds: The deploy gate's lint thresholds.
        requirement: The component's requirement.
        link: Path to the full lint report.

    Returns:
        The component.
    """
    errors = int(facts.severity_counts.get("error", 0) or 0)
    evidence = {
        "grade": facts.grade,
        "score": facts.score,
        "severityCounts": {str(k): int(v) for k, v in facts.severity_counts.items()},
        "errorCount": errors,
        "errorFindings": [dict(f) for f in list(facts.error_findings)[:MAX_LISTED_EVIDENCE]],
        "guide": dict(facts.guide),
        "reportFingerprint": facts.report_fingerprint,
    }
    rule = {"errorSeverityFails": True, **_thresholds_rule(thresholds)}
    if errors > 0:
        guide = facts.guide.get("name") or "the style guide"
        return _component(
            COMPONENT_LINT,
            requirement,
            state=STATE_FAIL,
            reason=REASON_LINT_ERRORS,
            detail=(
                f"{errors} error-severity violation{'s' if errors != 1 else ''} under {guide} — "
                "the violations the publish gate refuses."
            ),
            link=link,
            evidence=evidence,
            rule=rule,
        )
    signal = evaluate_lint(
        grade=facts.grade, score=facts.score, thresholds=thresholds, link=link
    )
    return component_from_signal(COMPONENT_LINT, signal, requirement, rule=rule, evidence=evidence)


@dataclass(frozen=True)
class BreakingFacts:
    """The draft's classification against the previous published revision.

    Attributes:
        baseline_revision_id: The published revision compared against; ``None`` when nothing on
            this line has been published, which makes this the first publication.
        baseline_label: Its version label.
        max_severity: The worst classified severity, ``None`` when nothing changed.
        counts: Per-severity tallies.
        breaking_changes: The breaking entries, each ``{pointer, ruleId, pathGroup, summary}``.
    """

    baseline_revision_id: Optional[str]
    baseline_label: Optional[str] = None
    max_severity: Optional[str] = None
    counts: Mapping[str, int] = field(default_factory=dict)
    breaking_changes: Sequence[Mapping[str, str]] = ()


def judge_breaking(
    facts: BreakingFacts,
    *,
    thresholds: BreakingThresholds,
    requirement: str,
    link: Optional[str],
) -> SuiteComponent:
    """Judge the classification with CTG-4.5's :func:`~app.deploy_gate.evaluate_breaking`.

    Args:
        facts: The classification.
        thresholds: The deploy gate's breaking thresholds.
        requirement: The component's requirement.
        link: Path to the draft's breaking-change view.

    Returns:
        The component.
    """
    listed = [dict(change) for change in list(facts.breaking_changes)[:MAX_LISTED_EVIDENCE]]
    signal = evaluate_breaking(
        status="ready" if facts.baseline_revision_id else "initial",
        max_severity=facts.max_severity,
        counts=facts.counts,
        baseline_version_label=facts.baseline_label,
        thresholds=thresholds,
        link=link,
    )
    return component_from_signal(
        COMPONENT_BREAKING,
        signal,
        requirement,
        rule=_thresholds_rule(thresholds),
        evidence={
            "baselineRevisionId": facts.baseline_revision_id,
            "breakingChanges": listed,
            "breakingChangesTruncated": len(facts.breaking_changes) > len(listed),
        },
    )


def judge_consumers(
    report: Optional[ConsumerImpactReport],
    *,
    thresholds: ConsumerThresholds,
    requirement: str,
    link: Optional[str],
) -> SuiteComponent:
    """Judge the per-consumer verdicts with CTG-4.5's :func:`~app.deploy_gate.evaluate_consumers`.

    Args:
        report: CTG-4.2's report for the draft's classification, or ``None`` when there was no
            published baseline to classify against — nobody can have registered against a line
            that has never been published.
        thresholds: The deploy gate's consumer thresholds.
        requirement: The component's requirement.
        link: Path to the project's consumer registry.

    Returns:
        The component.
    """
    if report is None:
        return _component(
            COMPONENT_CONSUMERS,
            requirement,
            state=STATE_SKIPPED,
            reason=REASON_CONSUMERS_NO_BASELINE,
            detail=(
                "Nothing on this line has been published yet, so no consumer can have "
                "registered against it."
            ),
            link=link,
            rule=_thresholds_rule(thresholds),
        )
    signal = evaluate_consumers(report=report, thresholds=thresholds, link=link)
    breaking = list(report.breaking_consumers)
    return component_from_signal(
        COMPONENT_CONSUMERS,
        signal,
        requirement,
        rule=_thresholds_rule(thresholds),
        evidence={
            "breakingConsumers": breaking[:MAX_LISTED_EVIDENCE],
            "breakingConsumersTruncated": len(breaking) > MAX_LISTED_EVIDENCE,
        },
    )


@dataclass(frozen=True)
class ContractFacts:
    """The executable-contract evidence for this revision.

    Attributes:
        applicable: Whether the version declares a callable operation at all.
        run: The newest ECA-1.3 run of this revision — ``{id, outcome, suiteDigest, reference,
            targetSlug, finishedAt, cases}`` — or ``None`` when none has been recorded.
        current_digest: What the run's own reference compiles to *today*. Equal to the run's
            digest exactly when the run executed the suite this draft still compiles to; ``None``
            when it could not be recompiled.
    """

    applicable: bool
    run: Optional[Mapping[str, Any]] = None
    current_digest: Optional[str] = None


def judge_contract(
    facts: ContractFacts,
    *,
    requirement: str,
    link: Optional[str],
) -> SuiteComponent:
    """Judge the newest contract run of this revision.

    A run counts only while it is *current*: its suite digest covers the compiled cases, so a
    draft edited since the run compiles to a different suite, and a green run of the old one says
    nothing about the new document. Currency is checked by recompiling the run's own reference —
    the digest also covers the reference spelling, so comparing against a differently spelled
    compile would read every run as stale.

    Args:
        facts: The contract evidence.
        requirement: The component's requirement.
        link: Path to the run (or to the tenant's runs when there is none).

    Returns:
        The component.
    """
    if not facts.applicable:
        return _component(
            COMPONENT_CONTRACT,
            requirement,
            state=STATE_SKIPPED,
            reason=REASON_CONTRACT_NOT_APPLICABLE,
            detail="This version declares no callable operation, so there is no contract to execute.",
            link=link,
        )
    run = dict(facts.run or {})
    if not run:
        return _component(
            COMPONENT_CONTRACT,
            requirement,
            state=_missing_state(requirement),
            reason=REASON_CONTRACT_MISSING,
            detail=(
                "No contract run of this revision has been recorded. Run `apiome contract run` "
                "against a verification target, then re-run the suite."
            ),
            link=link,
        )

    evidence = {
        "runId": run.get("id"),
        "outcome": run.get("outcome"),
        "suiteDigest": run.get("suiteDigest"),
        "currentSuiteDigest": facts.current_digest,
        "reference": run.get("reference"),
        "targetSlug": run.get("targetSlug"),
        "finishedAt": run.get("finishedAt"),
        "cases": dict(run.get("cases") or {}),
    }
    if not facts.current_digest or facts.current_digest != run.get("suiteDigest"):
        return _component(
            COMPONENT_CONTRACT,
            requirement,
            state=_missing_state(requirement),
            reason=REASON_CONTRACT_STALE,
            detail=(
                "The newest contract run executed a suite this draft no longer compiles to, so it "
                "says nothing about the current document. Run the contract suite again."
            ),
            link=link,
            evidence=evidence,
        )

    cases = evidence["cases"]
    target = f" against {run.get('targetSlug')}" if run.get("targetSlug") else ""
    tally = (
        f"{cases.get('passed', 0)} of {cases.get('total', 0)} cases passed"
        if cases
        else "the run's cases"
    )
    outcome = str(run.get("outcome") or "")
    if outcome == "passed":
        return _component(
            COMPONENT_CONTRACT,
            requirement,
            state=STATE_PASS,
            reason=REASON_CONTRACT_PASSED,
            detail=f"The contract suite passed{target}: {tally}.",
            link=link,
            evidence=evidence,
        )
    if outcome in ("failed", "errored"):
        return _component(
            COMPONENT_CONTRACT,
            requirement,
            state=STATE_FAIL,
            reason=REASON_CONTRACT_FAILED,
            detail=f"The contract suite {outcome}{target}: {tally}.",
            link=link,
            evidence=evidence,
        )
    return _component(
        COMPONENT_CONTRACT,
        requirement,
        state=_missing_state(requirement),
        reason=REASON_CONTRACT_INCOMPLETE,
        detail=f"The newest contract run ended {outcome or 'without a verdict'}; run it again.",
        link=link,
        evidence=evidence,
    )


@dataclass(frozen=True)
class SdkFacts:
    """What the SDK-3.3 client-kit manifest built from the draft says.

    Attributes:
        operation_count: Operations the kit carries snippets for.
        total_operation_count: Operations the API declares.
        skipped_operations: Operations the kit could not render (no HTTP binding) — reported,
            never a failure, exactly as the kit itself treats them.
        go_client_error: Why the Go client did not generate, when it did not.
        server_stub_error: Why the server stubs did not generate, when they did not.
        kit_digest: sha256 of the kit's bytes — deterministic, so it is the evidence id.
        go_package: The Go package the client declares.
        file_count: Files the kit carries.
    """

    operation_count: int
    total_operation_count: int
    skipped_operations: int = 0
    go_client_error: Optional[str] = None
    server_stub_error: Optional[str] = None
    kit_digest: Optional[str] = None
    go_package: Optional[str] = None
    file_count: int = 0


def judge_sdk(
    facts: SdkFacts,
    *,
    requirement: str,
    link: Optional[str],
) -> SuiteComponent:
    """Judge whether the draft still generates an SDK.

    Args:
        facts: The kit manifest's facts.
        requirement: The component's requirement.
        link: Path to the project's SDK settings.

    Returns:
        The component.
    """
    evidence = {
        "kitDigest": facts.kit_digest,
        "operationCount": facts.operation_count,
        "totalOperationCount": facts.total_operation_count,
        "skippedOperations": facts.skipped_operations,
        "goClientError": facts.go_client_error,
        "serverStubError": facts.server_stub_error,
        "goPackage": facts.go_package,
        "fileCount": facts.file_count,
    }
    if facts.total_operation_count <= 0 or facts.operation_count <= 0:
        return _component(
            COMPONENT_SDK,
            requirement,
            state=STATE_SKIPPED,
            reason=REASON_SDK_NOT_APPLICABLE,
            detail="This version has no operation a client could call, so there is no SDK to generate.",
            link=link,
            evidence=evidence,
        )
    failures = [
        f"{name}: {error}"
        for name, error in (
            ("Go client", facts.go_client_error),
            ("server stubs", facts.server_stub_error),
        )
        if error
    ]
    if failures:
        return _component(
            COMPONENT_SDK,
            requirement,
            state=STATE_FAIL,
            reason=REASON_SDK_FAILED,
            detail="The SDK no longer generates — " + "; ".join(failures) + ".",
            link=link,
            evidence=evidence,
        )
    caveat = (
        f" {facts.skipped_operations} operation{'s' if facts.skipped_operations != 1 else ''} "
        "without an HTTP binding carry no snippet."
        if facts.skipped_operations
        else ""
    )
    return _component(
        COMPONENT_SDK,
        requirement,
        state=STATE_PASS,
        reason=REASON_SDK_GENERATED,
        detail=(
            f"The client kit generates for {facts.operation_count} of "
            f"{facts.total_operation_count} operations, with its Go client and server stubs."
            f"{caveat}"
        ),
        warned=bool(facts.skipped_operations),
        link=link,
        evidence=evidence,
    )


# ---------------------------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------------------------


def aggregate(components: Sequence[SuiteComponent]) -> Tuple[str, str]:
    """Reduce the required components to the suite's verdict.

    GNC-2.2's :func:`~app.provider_checks.summarize_states` precedence — one failure fails the
    set, an unfinished component holds it, a set of skips is a skip — applied to the *required*
    components only. Advisory and switched-off components are reported and never counted.

    Args:
        components: Every component.

    Returns:
        ``(state, reason)``.
    """
    counted = [c.state for c in components if c.counted]
    if not counted:
        return STATE_SKIPPED, REASON_NO_REQUIRED
    state = summarize_states(counted)
    reason = {
        STATE_FAIL: REASON_REQUIRED_FAILED,
        STATE_PENDING: REASON_REQUIRED_PENDING,
        STATE_PASS: REASON_REQUIRED_PASSED,
    }.get(state, REASON_NOTHING_APPLIED)
    return state, reason


def component_counts(components: Sequence[Any]) -> Dict[str, int]:
    """Tally the required components by state.

    Args:
        components: Components, as models or as stored dicts.

    Returns:
        ``{"required", "pass", "fail", "pending", "skipped"}`` — the states counted are those of
        the required components, which are the only ones that decide the verdict.
    """
    counts = {"required": 0, STATE_PASS: 0, STATE_FAIL: 0, STATE_PENDING: 0, STATE_SKIPPED: 0}
    for component in components:
        data = component.model_dump() if isinstance(component, BaseModel) else dict(component)
        if not data.get("counted"):
            continue
        counts["required"] += 1
        state = str(data.get("state") or "")
        if state in counts:
            counts[state] += 1
    return counts


def input_fingerprint(
    *,
    version_id: str,
    draft_digest: str,
    binding_id: Optional[str],
    commit_sha: Optional[str],
    check_name: str,
    evaluated: bool,
    state: str,
    reason: str,
    policy_fingerprint_value: str,
    thresholds_fingerprint: str,
    components: Sequence[SuiteComponent],
) -> str:
    """Fingerprint everything a verdict is a function of — the re-run idempotency key.

    Two evaluations with the same fingerprint judged the same document, at the same commit, under
    the same policies, from the same evidence, and reached the same verdict: they are one
    evaluation, and V267's ``UNIQUE (version_id, input_fingerprint)`` makes them one row.

    Args:
        version_id: The version judged.
        draft_digest: Its content digest.
        binding_id: The binding reported through, when bound.
        commit_sha: The commit reported against, when bound.
        check_name: The provider check name.
        evaluated: Whether the components were judged.
        state: The verdict.
        reason: Its reason.
        policy_fingerprint_value: The suite policy's :func:`requirements_fingerprint`.
        thresholds_fingerprint: The deploy-gate thresholds' fingerprint.
        components: Every component, with its evidence.

    Returns:
        ``"sha256:<hex>"``.
    """
    return _digest(
        {
            "schemaVersion": SUITE_SCHEMA_VERSION,
            "versionId": str(version_id),
            "draftDigest": draft_digest,
            "bindingId": binding_id,
            "commitSha": commit_sha,
            "checkName": check_name,
            "evaluated": bool(evaluated),
            "state": state,
            "reason": reason,
            "policyFingerprint": policy_fingerprint_value,
            "thresholdsFingerprint": thresholds_fingerprint,
            "components": [component.model_dump(mode="json") for component in components],
        }
    )


# ---------------------------------------------------------------------------------------------
# What a reviewer reads on the provider
# ---------------------------------------------------------------------------------------------


def _component_models(components: Sequence[Any]) -> List[SuiteComponent]:
    """Coerce stored component dicts into models.

    Args:
        components: Models or stored dicts.

    Returns:
        The models.
    """
    return [
        c if isinstance(c, SuiteComponent) else SuiteComponent(**dict(c)) for c in components
    ]


def render_title(state: str, reason: str, components: Sequence[Any]) -> str:
    """The one-line title a reviewer sees on the pull request.

    Args:
        state: The verdict.
        reason: Its reason.
        components: Every component.

    Returns:
        A title within :data:`~app.provider_checks.MAX_TITLE_LENGTH`.
    """
    models = _component_models(components)

    def labels(target: str) -> str:
        return ", ".join(c.label.lower() for c in models if c.counted and c.state == target)

    if reason == REASON_DRAFT_NOT_SYNCHRONIZED:
        title = "Waiting for the Apiome draft to catch up with this commit"
    elif reason == REASON_SPEC_UNCHANGED:
        title = "No API change: this commit does not touch the specification"
    elif state == STATE_FAIL:
        title = f"API change check failed: {labels(STATE_FAIL)}"
    elif state == STATE_PENDING:
        title = f"API change check waiting on: {labels(STATE_PENDING)}"
    elif state == STATE_PASS:
        counts = component_counts(models)
        title = (
            f"API change check passed ({counts[STATE_PASS]} of {counts['required']} required "
            "checks applied)"
        )
    elif reason == REASON_NO_REQUIRED:
        title = "API change check skipped: the policy requires no check"
    else:
        title = "API change check skipped: no required check applied to this change"
    return title[:MAX_TITLE_LENGTH]


def _cell(text: Any) -> str:
    """Make a value safe inside one markdown table cell.

    Args:
        text: The value.

    Returns:
        The text with pipes escaped and line breaks flattened.
    """
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _evidence_lines(component: SuiteComponent) -> List[str]:
    """The evidence bullets a component contributes to the summary.

    Args:
        component: The component.

    Returns:
        Zero or more markdown bullets naming the evidence behind it.
    """
    evidence = component.evidence
    lines: List[str] = []
    if component.component == COMPONENT_LINT:
        for finding in evidence.get("errorFindings") or []:
            lines.append(
                f"- Lint error `{_cell(finding.get('rule'))}` at `{_cell(finding.get('path'))}`: "
                f"{_cell(finding.get('message'))}"
            )
        if evidence.get("reportFingerprint"):
            lines.append(f"- Lint report `{evidence['reportFingerprint']}`")
    elif component.component == COMPONENT_BREAKING:
        for change in evidence.get("breakingChanges") or []:
            lines.append(
                f"- Breaking: {_cell(change.get('summary'))} (`{_cell(change.get('ruleId'))}` at "
                f"`{_cell(change.get('pointer'))}`)"
            )
    elif component.component == COMPONENT_CONSUMERS:
        consumers = evidence.get("breakingConsumers") or []
        if consumers:
            lines.append("- Consumers broken: " + ", ".join(f"`{_cell(c)}`" for c in consumers))
    elif component.component == COMPONENT_CONTRACT:
        if evidence.get("runId"):
            lines.append(
                f"- Contract run `{evidence['runId']}` ({_cell(evidence.get('outcome'))}), suite "
                f"`{_cell(evidence.get('suiteDigest'))}`"
            )
    elif component.component == COMPONENT_SDK:
        if evidence.get("kitDigest"):
            lines.append(f"- SDK kit `{evidence['kitDigest']}`")
    return lines


def render_summary(
    *,
    run_id: str,
    state: str,
    reason: str,
    components: Sequence[Any],
    version_label: Optional[str],
    commit_sha: Optional[str],
    draft_digest: str,
    policy_source: str,
    policy_fingerprint_value: str,
    thresholds_source: str,
    thresholds_fingerprint: str,
    drill_down: Optional[str],
) -> str:
    """The markdown a reviewer reads on the pull request — the verdict and everything behind it.

    Deterministic: a pure function of the stored evaluation, so replaying an evaluation publishes
    byte-identical text and GNC-2.2's publish ledger treats it as the publish it already made.

    Args:
        run_id: The evaluation's id — the drill-down key.
        state: The verdict.
        reason: Its reason.
        components: Every component.
        version_label: The version judged.
        commit_sha: The commit reported against.
        draft_digest: The draft's content digest.
        policy_source: Where the suite policy came from.
        policy_fingerprint_value: Its fingerprint.
        thresholds_source: Where the deploy-gate thresholds came from.
        thresholds_fingerprint: Their fingerprint.
        drill_down: API path of the full evaluation.

    Returns:
        Markdown within :data:`~app.provider_checks.MAX_SUMMARY_LENGTH`.
    """
    models = _component_models(components)
    subject = f" — version {version_label}" if version_label else ""
    lines: List[str] = [f"**API change check: {state}**{subject}", ""]

    if reason == REASON_DRAFT_NOT_SYNCHRONIZED:
        lines.append(
            "This commit is ahead of the commit the Apiome draft is synchronized with, so there "
            "is no verdict about it yet. Synchronize the draft with the branch, then re-run the "
            "suite."
        )
    elif reason == REASON_SPEC_UNCHANGED:
        lines.append(
            "The bound specification is byte-for-byte what the draft was synchronized with: this "
            "change does not touch the API."
        )
    else:
        deciding = [c for c in models if c.counted and c.state in (STATE_FAIL, STATE_PENDING)]
        for component in deciding:
            lines.append(f"- **{component.label}** {component.state}: {component.detail}")
        if deciding:
            lines.append("")
        lines.append("| Check | Policy | Result | Why |")
        lines.append("|---|---|---|---|")
        for component in models:
            result = component.state + (" (warning)" if component.warned else "")
            if component.counted and component.state in (STATE_FAIL, STATE_PENDING):
                result = f"**{result}**"
            lines.append(
                f"| {_cell(component.label)} | {_cell(component.requirement)} | {result} | "
                f"{_cell(component.detail)} |"
            )
        evidence = [line for component in models for line in _evidence_lines(component)]
        if evidence:
            lines.extend(["", "**Evidence**", *evidence])

    lines.append("")
    commit = f" at `{commit_sha[:12]}`" if commit_sha else ""
    lines.append(
        f"Judged{commit} from draft `{draft_digest}` under the suite policy ({policy_source}, "
        f"`{policy_fingerprint_value}`) and the deploy-gate thresholds ({thresholds_source}, "
        f"`{thresholds_fingerprint}`)."
    )
    reference = f"`GET {drill_down}`" if drill_down else f"`{run_id}`"
    lines.append(f"Evaluation `{run_id}` — drill down with {reference}.")

    summary = "\n".join(lines)
    if len(summary) > MAX_SUMMARY_LENGTH:
        marker = "\n\n… (truncated — read the full evaluation through the drill-down)"
        summary = summary[: MAX_SUMMARY_LENGTH - len(marker)] + marker
    return summary


# ---------------------------------------------------------------------------------------------
# Records, requests, responses
#
# None of these carries a credential, and `extra="forbid"` means none ever can by accident.
# ---------------------------------------------------------------------------------------------


class CheckSuiteRunRecord(BaseModel):
    """One evaluation of the suite — the drill-down."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SUITE_SCHEMA_VERSION)
    id: str = Field(description="The evaluation id; quoted in the provider check's summary.")
    tenant_id: str
    project_id: str
    version_id: str
    version_label: Optional[str] = Field(default=None, description="The version's label.")
    binding_id: Optional[str] = Field(
        default=None, description="The binding the verdict was reported through, when bound."
    )
    commit_sha: Optional[str] = Field(
        default=None, description="The commit the verdict is about, when bound."
    )
    pr_number: Optional[int] = Field(default=None, description="The pull request, when named.")
    check_name: str = Field(description="The provider check the verdict became.")
    evaluated: bool = Field(
        description="False for a placeholder that could not judge the draft at this commit."
    )
    state: CheckState = Field(description="`pending`, `pass`, `fail`, or `skipped`.")
    reason: str = Field(description="Stable reason code for the state.")
    title: str = Field(default="", description="The one-line title published to the provider.")
    summary: str = Field(default="", description="The markdown published to the provider.")
    draft_digest: str = Field(description="sha256 of the draft document as judged.")
    policy_source: str = Field(description="`default` | `tenant` | `project`.")
    policy_fingerprint: str = Field(
        description="Digest of the component requirements it was judged under — the part of the "
        "suite policy that decides a verdict."
    )
    policy: Dict[str, Any] = Field(
        default_factory=dict, description="The whole suite policy it was judged under."
    )
    thresholds_source: str = Field(description="`default` | `tenant` | `project`.")
    thresholds_fingerprint: str
    thresholds: Dict[str, Any] = Field(
        default_factory=dict, description="The deploy-gate thresholds it was judged against."
    )
    components: List[SuiteComponent] = Field(default_factory=list)
    counts: Dict[str, int] = Field(
        default_factory=dict, description="The required components, by state."
    )
    input_fingerprint: str = Field(description="The re-run idempotency key.")
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime


class CheckSuiteRunRequest(BaseModel):
    """Evaluate the suite for a version, and report the verdict when it is bound."""

    model_config = ConfigDict(extra="forbid")

    commit_sha: Optional[str] = Field(
        default=None,
        max_length=64,
        description=(
            "The commit to report against; defaults to the commit the binding is synchronized "
            "with. Only a bound version takes one."
        ),
    )
    pr_number: Optional[int] = Field(
        default=None, gt=0, description="The pull request the commit belongs to, when known."
    )
    publish: bool = Field(
        default=True,
        description=(
            "Publish the verdict to the provider as well as recording it. False records the "
            "evaluation and the check without sending it."
        ),
    )


class ProviderReport(BaseModel):
    """What happened on the provider side of an evaluation."""

    model_config = ConfigDict(extra="forbid")

    recorded: bool = Field(description="Whether a GNC-2.2 check run holds the verdict.")
    reason: Optional[str] = Field(
        default=None, description="Why it was not recorded, as a stable code."
    )
    message: str = Field(default="", description="A human explanation.")


class CheckSuiteRunDetail(BaseModel):
    """An evaluation, the provider check it became, and whether it still describes the draft."""

    model_config = ConfigDict(extra="forbid")

    run: CheckSuiteRunRecord
    replayed: bool = Field(
        default=False,
        description="True when these inputs had already been evaluated and that row came back.",
    )
    stale: bool = Field(
        default=False,
        description=(
            "True when the draft's content or either policy has moved since this evaluation — "
            "it no longer answers for the version as it is now."
        ),
    )
    provider: Optional[ProviderReport] = Field(
        default=None, description="The provider side, when the version is bound."
    )
    check: Optional[CheckRunDetail] = Field(
        default=None, description="The GNC-2.2 check run the verdict became, with its publishes."
    )


class CheckSuiteRunList(BaseModel):
    """A page of a version's evaluations."""

    model_config = ConfigDict(extra="forbid")

    runs: List[CheckSuiteRunRecord] = Field(default_factory=list, description="Newest first.")
    count: int
    limit: int
    offset: int
