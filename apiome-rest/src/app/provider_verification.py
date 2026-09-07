"""Provider verification against a live deployment — CTG-4.3 (#4489).

A specification can be perfectly versioned, linted, and published, and still lie. The deployment
drifts from the contract — a field disappears, a type narrows, a new parameter becomes required —
and nobody finds out until a consumer breaks in production. Versioning describes what was
*promised*; nothing in Apiome has so far checked what is actually *served*.

This module is the judgment half of that check. It answers two questions the existing pieces do
not:

**Which requests may this run send?**  A verification points at somebody's real system, so the
default is the reading that cannot damage it: only the safe methods (``GET``/``HEAD``/``OPTIONS``)
are executed. A mutating operation is exercised only when the run **opts in** *and* the tenant
supplies a :class:`MutatingFixture` for it — the flag alone is not enough, because "you may write"
and "here is the row you may write to" are different permissions. :func:`plan_provider_run` turns
that rule into one :class:`~app.contract_runner.CaseDecision` per case, and the decision can only
ever be narrower than the ECA-1.2 target policy, never wider.

**What does the run actually say about the deployment?**  :func:`build_conformance_report` turns
executed cases into the drift picture: per-operation verdicts, every schema violation located by
its JSON Pointer into the response body, and coverage measured against **every operation in the
model** — including the ones the suite compiler could not compile. Coverage that only counted
compiled operations would read as reassurance, which is the opposite of what a drift report is
for. What was not exercised is named, with the reason, rather than left out.

Everything else is reused rather than rebuilt: :mod:`app.contract_suite` compiles the cases (the
request-synthesis dependency), :mod:`app.contract_runner` executes them and validates responses
with :func:`app.schema_instance_validation.validate_json_instance` (the validator dependency), and
:mod:`app.verification_evidence` stores the result. This module has no I/O: a manifest, options,
and case records in; a plan and a report out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contract_runner import (
    FAILURE_MUTATING_METHOD_BLOCKED,
    FAILURE_RESPONSE_SCHEMA_MISMATCH,
    FAILURE_STATUS_MISMATCH,
    MUTATING_METHODS,
    SAFE_METHODS,
    CaseDecision,
)
from .contract_suite import (
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    CASE_SOURCE_NEGATIVE_PARAMETER_TYPE,
    NEGATIVE_CASE_SOURCES,
    ContractCase,
    ContractCaseRequest,
    ContractRequestParameter,
    ContractSuiteManifest,
)
from .verification_evidence import (
    ASSERTION_KIND_RESPONSE_SCHEMA,
    ASSERTION_KIND_STATUS_CODE,
    ASSERTION_OUTCOME_FAILED,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
    RUN_OUTCOME_ERRORED,
    RUN_OUTCOME_FAILED,
    RUN_OUTCOME_PASSED,
    OperationResultInput,
)

__all__ = [
    "CONFORMANCE_REPORT_SCHEMA_VERSION",
    "CREDENTIAL_HEADERS",
    "DRIFT_KIND_RESPONSE_SCHEMA",
    "DRIFT_KIND_STATUS",
    "DRIFT_KIND_TRANSPORT",
    "FIXTURE_CODE_CASE_UNMATCHED",
    "FIXTURE_CODE_NOT_MUTATING",
    "FIXTURE_CODE_UNMATCHED",
    "MAX_FIXTURES",
    "MAX_UNCOVERED_NAMED",
    "SKIP_MUTATING_BLOCKED",
    "SKIP_MUTATING_FIXTURE_MISSING",
    "VERIFIER_NAME",
    "VERIFIER_VERSION",
    "ConformanceReport",
    "CoverageSummary",
    "DriftFinding",
    "FixtureFinding",
    "MutatingFixture",
    "OperationConformance",
    "ProviderRunPlan",
    "ProviderVerificationOptions",
    "TargetIdentity",
    "UncoveredOperation",
    "apply_fixture",
    "build_conformance_report",
    "plan_provider_run",
]


# =============================================================================================
# Vocabulary and bounds
# =============================================================================================

#: Envelope version of the stored report shape. Bumped when a field is added, removed, or given a
#: new meaning, so a report written months ago can still be read by the code that reads it.
CONFORMANCE_REPORT_SCHEMA_VERSION = 1

#: Runner identity written into ECA-1.3 evidence, so a provider verification is distinguishable
#: from a plain ECA-2.1 contract run in the same evidence table.
VERIFIER_NAME = "apiome-provider-verifier"
VERIFIER_VERSION = "1"

#: Why a mutating case was held back: the run never opted in, or the ECA-1.2 target policy forbids
#: mutating methods outright. Spelled the same as the runner's own gate, because to a reader of the
#: evidence they mean the same thing — nothing was sent.
SKIP_MUTATING_BLOCKED = FAILURE_MUTATING_METHOD_BLOCKED

#: Why a mutating case was held back even though the run opted in: no fixture named its operation.
#: This is the distinction that matters when someone asks "I turned mutation on, why did nothing
#: run?" — the answer is that opting in is a permission, not a payload.
SKIP_MUTATING_FIXTURE_MISSING = "mutating-fixture-missing"

#: A fixture that names an operation the compiled suite does not contain. Reported, never ignored:
#: a fixture that matched nothing usually means a typo in an operation key, and silently dropping
#: it would leave the tenant believing an operation was verified.
FIXTURE_CODE_UNMATCHED = "fixture-unmatched"

#: A fixture that names a compiled operation but a case id within it that does not exist.
FIXTURE_CODE_CASE_UNMATCHED = "fixture-case-unmatched"

#: A fixture that names a safe operation. Refused rather than applied: a fixture is the opt-in for
#: *mutation*, and letting one rewrite what a ``GET`` case sends would quietly change what the
#: contract was tested with.
FIXTURE_CODE_NOT_MUTATING = "fixture-not-mutating"

#: How a case disagreed with its contract.
DRIFT_KIND_STATUS = "status"
DRIFT_KIND_RESPONSE_SCHEMA = "response_schema"
DRIFT_KIND_TRANSPORT = "transport"

#: Headers that carry credentials. A fixture may not set any of them: auth belongs to the ECA-1.2
#: target's secret-free reference, and a fixture is persisted with the report.
CREDENTIAL_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "apikey",
        "x-auth-token",
        "x-access-token",
        "x-amz-security-token",
    }
)

#: Cap on fixtures per run. A verification is a check, not a data-loading job.
MAX_FIXTURES = 100

#: Cap on named uncovered operations carried in a report, so a 500-operation specification that
#: compiles none of itself yields a readable report rather than a wall. The *count* is never
#: capped — only the naming is.
MAX_UNCOVERED_NAMED = 200

#: The two negative sources that target one specific parameter by name. A fixture must not supply
#: a value for the parameter such a case exists to omit or corrupt.
_PARAMETER_NEGATIVE_SOURCES = frozenset(
    {CASE_SOURCE_NEGATIVE_MISSING_PARAMETER, CASE_SOURCE_NEGATIVE_PARAMETER_TYPE}
)

#: Where a parameter value supplied by a fixture says it came from.
_ORIGIN_FIXTURE = "fixture"


# =============================================================================================
# Inputs
# =============================================================================================


class MutatingFixture(BaseModel):
    """A tenant's explicit permission — and payload — for exercising one mutating operation.

    A fixture answers the question a safe-by-default verifier cannot answer for itself: *which*
    resource may this run create, replace, or delete, and with what. It supplies the request only.
    The expectation stays whatever the contract declared, so a fixture can never make a case pass —
    it can only get the case sent.
    """

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(
        description="Canonical operation key the fixture authorizes (`POST /pets`).",
        min_length=1,
        max_length=500,
    )
    case_id: Optional[str] = Field(
        default=None,
        description=(
            "Narrow the fixture to one compiled case. Omit to authorize every case of the "
            "operation; a case-scoped fixture wins over an operation-scoped one."
        ),
        max_length=300,
    )
    path_parameters: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Path parameter values, substituted into the operation's route template. This is "
            "how a fixture points a `DELETE /pets/{petId}` at a disposable record."
        ),
    )
    query_parameters: Dict[str, str] = Field(
        default_factory=dict, description="Query parameter values to send."
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Extra request headers. Credential headers are refused — authentication comes from "
            "the verification target's secret-free reference, never from a stored fixture."
        ),
    )
    body: Optional[Any] = Field(
        default=None,
        description=(
            "Request body to send instead of the compiled one. Applied to positive cases only: "
            "a negative case's body *is* the case, so it is never overwritten."
        ),
    )
    has_body: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the fixture sends a body at all. `null` infers it from `body`, which is the "
            "usual case; `false` sends no body even when the compiled case had one; `true` with "
            "a null `body` sends a literal JSON `null`."
        ),
    )
    media_type: Optional[str] = Field(
        default=None,
        description="Media type for the fixture body. Defaults to the compiled case's.",
        max_length=200,
    )
    note: Optional[str] = Field(
        default=None,
        description=(
            "Why exercising this operation is safe — the sentence a reviewer wants when a "
            "verification run turns out to have written to something."
        ),
        max_length=1000,
    )

    @field_validator("headers")
    @classmethod
    def _no_credential_headers(cls, value: Dict[str, str]) -> Dict[str, str]:
        """Refuse a fixture that carries authentication.

        Args:
            value: The fixture's headers.

        Returns:
            The headers, unchanged, when none of them is a credential header.

        Raises:
            ValueError: When any header name is in :data:`CREDENTIAL_HEADERS`.
        """
        offenders = sorted(
            name for name in value if name.strip().lower() in CREDENTIAL_HEADERS
        )
        if offenders:
            raise ValueError(
                f"fixture headers may not carry credentials ({', '.join(offenders)}); "
                "authentication belongs to the verification target's auth reference"
            )
        return value

    def declares_body(self) -> bool:
        """Whether this fixture speaks about the request body at all.

        Returns:
            ``True`` when the fixture supplies a body or explicitly says there is none, so a
            fixture that only supplies path parameters leaves the compiled body alone.
        """
        return self.has_body is not None or self.body is not None

    def sends_body(self) -> bool:
        """Whether the fixture's request carries a body.

        Returns:
            ``has_body`` when it was stated, otherwise whether a body was supplied.
        """
        return self.has_body if self.has_body is not None else self.body is not None


class ProviderVerificationOptions(BaseModel):
    """How much of the deployment this run is allowed to touch."""

    model_config = ConfigDict(extra="forbid")

    allow_mutating: bool = Field(
        default=False,
        description=(
            "Opt in to exercising mutating methods. Off by default. Even when on, a mutating "
            "case runs only if a fixture names its operation — and never if the verification "
            "target's own policy forbids mutating methods."
        ),
    )
    fixtures: List[MutatingFixture] = Field(
        default_factory=list,
        description="Per-operation permission and payload for mutating operations.",
        max_length=MAX_FIXTURES,
    )
    max_drift_findings_per_case: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Cap on located schema violations carried into the report for one case. A response "
            "that disagrees with its schema everywhere is one drift, not a hundred."
        ),
    )


class TargetIdentity(BaseModel):
    """The deployment a report is about, snapshotted at run time.

    A report names the target as it *was*, so a later rename, re-pointing, or retirement cannot
    rewrite what a past verification claimed to have checked.
    """

    model_config = ConfigDict(extra="forbid")

    target_id: Optional[str] = Field(default=None, description="Target id, when it still exists.")
    slug: str = Field(description="Target handle at run time.")
    environment: str = Field(description="Environment class (`mock`, `staging`, `production`).")
    network_class: str = Field(default="public", description="`public` or `private`.")
    base_url: str = Field(description="Base URL the requests were sent to.")


# =============================================================================================
# Planning — which cases may be sent
# =============================================================================================


class FixtureFinding(BaseModel):
    """A fixture the planner could not use, and why.

    Nothing a tenant supplies is silently dropped: a fixture that matched nothing is a fixture
    somebody believes is protecting an operation that was never verified.
    """

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Stable code: `fixture-unmatched`, `fixture-not-mutating`, …")
    message: str = Field(description="What was wrong with the fixture.")
    operation_key: str = Field(description="The operation key the fixture named.")
    case_id: Optional[str] = Field(default=None, description="The case id it named, when it did.")


@dataclass
class ProviderRunPlan:
    """What the run will and will not send, decided before a single request goes out.

    Attributes:
        decisions: One :class:`~app.contract_runner.CaseDecision` per case id the planner had an
            opinion about. Cases absent from the map run as compiled.
        findings: Fixtures that could not be used.
        skips: Case id → the reason code it was held back with, for the report.
        fixtures_applied: How many cases a fixture was substituted into.
        mutating_operations_exercised: Sorted operation keys a fixture unlocked.
    """

    decisions: Dict[str, CaseDecision] = field(default_factory=dict)
    findings: List[FixtureFinding] = field(default_factory=list)
    skips: Dict[str, str] = field(default_factory=dict)
    fixtures_applied: int = 0
    mutating_operations_exercised: List[str] = field(default_factory=list)


def _substitute_path(template: str, values: Mapping[str, str], fallback: str) -> str:
    """Rebuild a request path from a route template and path-parameter values.

    Args:
        template: The route template (``/pets/{petId}``).
        values: Path parameter values, already merged (compiled values plus fixture overrides).
        fallback: The compiled path, returned when the template names a parameter nothing
            supplied — a half-substituted path would be a request to somewhere else.

    Returns:
        The substituted, percent-encoded path, or ``fallback``.
    """
    if not template or "{" not in template:
        return template or fallback
    out: List[str] = []
    rest = template
    while "{" in rest:
        head, _, tail = rest.partition("{")
        name, closed, remainder = tail.partition("}")
        if not closed:
            return fallback
        if name not in values:
            return fallback
        out.append(head)
        out.append(quote(str(values[name]), safe=""))
        rest = remainder
    out.append(rest)
    return "".join(out)


def apply_fixture(case: ContractCase, fixture: MutatingFixture) -> ContractCase:
    """Return ``case`` with the fixture's request substituted in.

    The fixture supplies the *request*; the expectation is never touched, so a fixture cannot turn
    a failing case green. Two things it also cannot do, both because they would destroy the case
    it is being applied to:

    * it never replaces the body of a **negative** case — that body is the whole case;
    * it never supplies a value for the parameter a parameter-negative case exists to omit or
      corrupt (``source_detail`` names it).

    Args:
        case: The compiled case.
        fixture: The matching fixture.

    Returns:
        A copy of the case whose ``request`` carries the fixture's values. The case id, operation
        key, source and expectation are unchanged, so evidence still traces back to the suite.
    """
    is_negative = case.source in NEGATIVE_CASE_SOURCES
    protected = (
        case.source_detail
        if case.source in _PARAMETER_NEGATIVE_SOURCES and case.source_detail
        else None
    )

    supplied: Dict[Tuple[str, str], str] = {}
    for location, values in (
        ("path", fixture.path_parameters),
        ("query", fixture.query_parameters),
        ("header", fixture.headers),
    ):
        for name, value in values.items():
            if name == protected:
                continue
            supplied[(location, name)] = str(value)

    parameters: List[ContractRequestParameter] = []
    for parameter in case.request.parameters:
        key = (parameter.location, parameter.name)
        if key in supplied:
            parameters.append(
                parameter.model_copy(
                    update={"value": supplied.pop(key), "origin": _ORIGIN_FIXTURE}
                )
            )
        else:
            parameters.append(parameter)
    for (location, name), value in supplied.items():
        parameters.append(
            ContractRequestParameter(
                name=name,
                location=location,
                value=value,
                origin=_ORIGIN_FIXTURE,
                required=False,
            )
        )
    parameters.sort(key=lambda item: (item.location, item.name))

    path_values = {
        item.name: item.value for item in parameters if item.location == "path"
    }
    path = _substitute_path(case.request.path_template, path_values, case.request.path)

    request_update: Dict[str, Any] = {"parameters": parameters, "path": path}
    if fixture.declares_body() and not is_negative:
        sends = fixture.sends_body()
        request_update["has_body"] = sends
        request_update["body"] = fixture.body if sends else None
        request_update["media_type"] = (
            (fixture.media_type or case.request.media_type or "application/json")
            if sends
            else None
        )

    request: ContractCaseRequest = case.request.model_copy(update=request_update)
    return case.model_copy(update={"request": request})


def _index_fixtures(
    fixtures: Sequence[MutatingFixture],
) -> Tuple[Dict[str, MutatingFixture], Dict[Tuple[str, str], MutatingFixture]]:
    """Index fixtures by operation and by (operation, case).

    A later fixture for the same key replaces an earlier one, so a caller that repeats itself gets
    the last word rather than an arbitrary one.

    Args:
        fixtures: The submitted fixtures, in order.

    Returns:
        ``(by_operation, by_case)``.
    """
    by_operation: Dict[str, MutatingFixture] = {}
    by_case: Dict[Tuple[str, str], MutatingFixture] = {}
    for fixture in fixtures:
        if fixture.case_id:
            by_case[(fixture.operation_key, fixture.case_id)] = fixture
        else:
            by_operation[fixture.operation_key] = fixture
    return by_operation, by_case


def plan_provider_run(
    manifest: ContractSuiteManifest,
    options: ProviderVerificationOptions,
    *,
    target_allows_mutating: bool,
) -> ProviderRunPlan:
    """Decide, case by case, what this verification is allowed to send.

    The rule, in the order it is applied:

    ============================================  ===========================================
    Case                                          Decision
    ============================================  ===========================================
    Safe method (``GET``/``HEAD``/``OPTIONS``)    run, as compiled
    Mutating, target policy forbids it            skip ``mutating-method-blocked``
    Mutating, run did not opt in                  skip ``mutating-method-blocked``
    Mutating, opted in, no matching fixture       skip ``mutating-fixture-missing``
    Mutating, opted in, fixture matches           run, with the fixture's request
    ============================================  ===========================================

    The target policy is checked *first* and cannot be overridden: a run may narrow what the
    registry permits, never widen it.

    Args:
        manifest: The compiled suite.
        options: The run's mutation opt-in and fixtures.
        target_allows_mutating: The ECA-1.2 target policy's ``allow_mutating_methods``.

    Returns:
        The :class:`ProviderRunPlan` to hand to :func:`app.contract_runner.run_suite`.
    """
    plan = ProviderRunPlan()
    by_operation, by_case = _index_fixtures(options.fixtures)
    matched_operations: set = set()
    matched_cases: set = set()
    exercised: set = set()

    for case in manifest.cases:
        method = case.request.method.upper()
        if method in SAFE_METHODS or method not in MUTATING_METHODS:
            continue

        fixture = by_case.get((case.operation_key, case.case_id)) or by_operation.get(
            case.operation_key
        )
        if fixture is not None:
            matched_operations.add(fixture.operation_key)
            if fixture.case_id:
                matched_cases.add((fixture.operation_key, fixture.case_id))

        if not target_allows_mutating:
            reason = (
                f"{method} was not sent: the verification target's policy has "
                "allow_mutating_methods=false, which a run cannot override."
            )
            plan.decisions[case.case_id] = CaseDecision(
                run=False, skip_code=SKIP_MUTATING_BLOCKED, skip_message=reason
            )
            plan.skips[case.case_id] = SKIP_MUTATING_BLOCKED
            continue

        if not options.allow_mutating:
            reason = (
                f"{method} was not sent: this run did not opt in to mutating methods "
                "(allow_mutating=false)."
            )
            plan.decisions[case.case_id] = CaseDecision(
                run=False, skip_code=SKIP_MUTATING_BLOCKED, skip_message=reason
            )
            plan.skips[case.case_id] = SKIP_MUTATING_BLOCKED
            continue

        if fixture is None:
            reason = (
                f"{method} was not sent: the run opted in to mutating methods but supplied no "
                f"fixture for {case.operation_key!r}. Opting in is a permission, not a payload."
            )
            plan.decisions[case.case_id] = CaseDecision(
                run=False,
                skip_code=SKIP_MUTATING_FIXTURE_MISSING,
                skip_message=reason,
            )
            plan.skips[case.case_id] = SKIP_MUTATING_FIXTURE_MISSING
            continue

        plan.decisions[case.case_id] = CaseDecision(run=True, case=apply_fixture(case, fixture))
        plan.fixtures_applied += 1
        exercised.add(case.operation_key)

    plan.mutating_operations_exercised = sorted(exercised)
    plan.findings = _fixture_findings(manifest, options.fixtures, matched_operations, matched_cases)
    return plan


def _fixture_findings(
    manifest: ContractSuiteManifest,
    fixtures: Sequence[MutatingFixture],
    matched_operations: set,
    matched_cases: set,
) -> List[FixtureFinding]:
    """Report every fixture the planner could not use.

    Args:
        manifest: The compiled suite, for classifying *why* a fixture matched nothing.
        fixtures: The submitted fixtures.
        matched_operations: Operation keys an operation-scoped fixture reached.
        matched_cases: ``(operation_key, case_id)`` pairs a case-scoped fixture reached.

    Returns:
        Findings sorted by code, then operation key, then case id.
    """
    methods = {
        operation.key: (operation.http_method or "").upper() for operation in manifest.operations
    }
    findings: List[FixtureFinding] = []
    for fixture in fixtures:
        key = fixture.operation_key
        if fixture.case_id and (key, fixture.case_id) in matched_cases:
            continue
        if not fixture.case_id and key in matched_operations:
            continue
        method = methods.get(key)
        if method is not None and method not in MUTATING_METHODS:
            findings.append(
                FixtureFinding(
                    code=FIXTURE_CODE_NOT_MUTATING,
                    message=(
                        f"Fixture names {key!r}, which is a {method} operation. A fixture is the "
                        "opt-in for mutating methods; it was not applied, because rewriting what "
                        "a safe case sends would change what the contract was tested with."
                    ),
                    operation_key=key,
                    case_id=fixture.case_id,
                )
            )
        elif method is not None and fixture.case_id:
            findings.append(
                FixtureFinding(
                    code=FIXTURE_CODE_CASE_UNMATCHED,
                    message=(
                        f"Fixture names case {fixture.case_id!r} of {key!r}, which the compiled "
                        "suite does not contain, so it authorized nothing."
                    ),
                    operation_key=key,
                    case_id=fixture.case_id,
                )
            )
        else:
            findings.append(
                FixtureFinding(
                    code=FIXTURE_CODE_UNMATCHED,
                    message=(
                        f"Fixture names {key!r}, which the compiled suite does not contain. It "
                        "authorized nothing — check the operation key against the suite."
                    ),
                    operation_key=key,
                    case_id=fixture.case_id,
                )
            )
    findings.sort(key=lambda item: (item.code, item.operation_key, item.case_id or ""))
    return findings


# =============================================================================================
# The report
# =============================================================================================


class DriftFinding(BaseModel):
    """One way the deployment disagreed with its contract, located as precisely as possible."""

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(description="Canonical operation key that drifted.")
    case_id: str = Field(description="The compiled case that observed it.")
    http_method: str = Field(description="HTTP verb executed.")
    http_path: str = Field(description="Request path executed.")
    kind: str = Field(description="`status`, `response_schema`, or `transport`.")
    code: str = Field(description="Stable failure code from the runner.")
    pointer: Optional[str] = Field(
        default=None,
        description=(
            "RFC 6901 JSON Pointer to the offending value **in the response body** — the answer "
            "to *where*. Null for a status or transport drift, which has no body location."
        ),
    )
    expected: Optional[str] = Field(default=None, description="What the contract required.")
    actual: Optional[str] = Field(default=None, description="What the deployment returned.")
    message: str = Field(description="Human explanation, redacted by the evidence layer.")


class OperationConformance(BaseModel):
    """One operation's verdict, rolled up from every case that exercised it."""

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(description="Canonical operation key.")
    operation_name: Optional[str] = Field(default=None, description="Source operation name.")
    http_method: str = Field(description="HTTP verb.")
    http_path: str = Field(description="Route template or executed path.")
    outcome: str = Field(
        description=(
            "`passed`, `failed`, `errored`, or `skipped`. `skipped` means every case for this "
            "operation was held back — the operation was *not* verified."
        )
    )
    exercised: bool = Field(
        description="Whether at least one request was actually sent for this operation."
    )
    cases_total: int = Field(description="Cases compiled for this operation and planned.")
    cases_passed: int = Field(description="Cases that passed.")
    cases_failed: int = Field(description="Cases whose response contradicted the contract.")
    cases_errored: int = Field(description="Cases that never got an answer to judge.")
    cases_skipped: int = Field(description="Cases deliberately not sent.")
    skip_reason: Optional[str] = Field(
        default=None,
        description="Why the operation was not exercised, when it was not.",
    )
    drift: List[DriftFinding] = Field(
        default_factory=list, description="Every disagreement observed for this operation."
    )


class UncoveredOperation(BaseModel):
    """An operation the report does not vouch for, and why."""

    model_config = ConfigDict(extra="forbid")

    operation_key: str = Field(description="Canonical operation key.")
    reason_code: str = Field(
        description=(
            "Why it was not exercised: a compiler finding code (`UNSUPPORTED_STREAMING`, "
            "`NO_CASES_COMPILED`, …) or a planner skip code (`mutating-fixture-missing`, …)."
        )
    )
    message: str = Field(description="What stopped it being verified.")


class CoverageSummary(BaseModel):
    """How much of the specification this run actually exercised.

    The denominator is **every operation in the model**, not every operation the suite compiler
    could compile. A coverage number that quietly excluded what could not be compiled would read
    as reassurance about operations nobody checked.
    """

    model_config = ConfigDict(extra="forbid")

    operations_total: int = Field(
        description="Operations in the specification, compiled or not."
    )
    operations_exercised: int = Field(
        description="Operations that received at least one request."
    )
    operations_passed: int = Field(description="Exercised operations with no drift.")
    operations_failed: int = Field(description="Exercised operations that drifted.")
    operations_errored: int = Field(description="Exercised operations that never answered.")
    operations_skipped: int = Field(
        description="Compiled operations whose every case was held back."
    )
    operations_uncompiled: int = Field(
        description=(
            "Operations the suite compiler could not turn into cases at all. Reported "
            "separately from `operations_skipped`: one was not sendable, the other was not sent."
        )
    )
    uncovered_named: int = Field(
        description=(
            "How many uncovered operations the report could name. Lower than "
            "`operations_total - operations_exercised` when the compiler could not attribute a "
            "skip to a specific operation — stated rather than hidden. It can also exceed "
            "`len(uncovered)`, because the *list* is capped for readability while the count is "
            "not."
        )
    )
    coverage_percent: float = Field(
        description="`operations_exercised / operations_total`, as a percentage to one decimal."
    )
    cases_total: int = Field(description="Cases the run accounted for.")
    cases_passed: int = Field(description="Cases that passed.")
    cases_failed: int = Field(description="Cases that drifted.")
    cases_errored: int = Field(description="Cases that never answered.")
    cases_skipped: int = Field(description="Cases deliberately not sent.")


class ConformanceReport(BaseModel):
    """The drift picture of one deployment, at one moment, against one published contract."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        default=CONFORMANCE_REPORT_SCHEMA_VERSION, description="Report envelope version."
    )
    outcome: str = Field(
        description=(
            "`passed`, `failed`, or `errored`, derived from the case records exactly the way "
            "ECA-1.3 derives a run verdict — never declared."
        )
    )
    suite_digest: str = Field(description="Digest of the executed ECA-1.1 suite.")
    api_title: Optional[str] = Field(default=None, description="API title, when declared.")
    api_version: Optional[str] = Field(default=None, description="Source-declared API version.")
    api_format: Optional[str] = Field(default=None, description="Source format key.")
    target: TargetIdentity = Field(description="The deployment that was checked.")
    started_at: datetime = Field(description="When the run began.")
    finished_at: datetime = Field(description="When the run ended.")
    duration_ms: int = Field(ge=0, description="Wall-clock duration in milliseconds.")
    coverage: CoverageSummary = Field(description="What fraction of the contract was exercised.")
    operations: List[OperationConformance] = Field(
        default_factory=list, description="Per-operation verdicts, sorted by operation key."
    )
    uncovered: List[UncoveredOperation] = Field(
        default_factory=list,
        description="Operations this report does not vouch for, sorted by key.",
    )
    drift: List[DriftFinding] = Field(
        default_factory=list,
        description="Every disagreement, flattened, in operation then case order.",
    )
    mutating_allowed: bool = Field(
        description="Whether the run opted in to mutating methods at all."
    )
    mutating_operations_exercised: List[str] = Field(
        default_factory=list,
        description="Mutating operations a fixture unlocked. Empty on a read-only run.",
    )
    fixtures_supplied: int = Field(default=0, description="Fixtures the caller submitted.")
    fixtures_applied: int = Field(default=0, description="Cases a fixture was substituted into.")
    fixture_findings: List[FixtureFinding] = Field(
        default_factory=list, description="Fixtures that could not be used."
    )


def _drift_from_operation(
    operation: OperationResultInput, *, limit: int
) -> List[DriftFinding]:
    """Extract the located disagreements from one executed case.

    Response-schema assertions come in two shapes, and the shape is legible from ``subject``: the
    headline verdict's subject is the manifest's schema id (``type:Pet``), and each located
    violation's subject is a JSON Pointer into the response body, which always begins with ``/``.
    The pointer-bearing ones are the drift; the headline is used only when nothing located it (a
    schema the suite did not carry, say), so a failure is never reported as nothing.

    Args:
        operation: The executed case record.
        limit: Cap on located violations to carry.

    Returns:
        Drift findings for this case, in assertion order.
    """
    if operation.outcome not in (OPERATION_OUTCOME_FAILED, OPERATION_OUTCOME_ERRORED):
        return []

    common = {
        "operation_key": operation.operation_key,
        "case_id": operation.case_id,
        "http_method": operation.http_method,
        "http_path": operation.http_path,
    }

    if operation.outcome == OPERATION_OUTCOME_ERRORED:
        return [
            DriftFinding(
                **common,
                kind=DRIFT_KIND_TRANSPORT,
                code=operation.failure_code or "transport-error",
                expected=operation.expected_status,
                actual=None,
                message=operation.failure_message or "the target did not answer",
            )
        ]

    if operation.failure_code == FAILURE_STATUS_MISMATCH:
        status_assertion = next(
            (
                item
                for item in operation.assertions
                if item.kind == ASSERTION_KIND_STATUS_CODE
                and item.outcome == ASSERTION_OUTCOME_FAILED
            ),
            None,
        )
        return [
            DriftFinding(
                **common,
                kind=DRIFT_KIND_STATUS,
                code=FAILURE_STATUS_MISMATCH,
                expected=(status_assertion.expected if status_assertion else None)
                or operation.expected_status,
                actual=(status_assertion.actual if status_assertion else None)
                or (str(operation.actual_status) if operation.actual_status else None),
                message=operation.failure_message or "status did not match the contract",
            )
        ]

    schema_failures = [
        item
        for item in operation.assertions
        if item.kind == ASSERTION_KIND_RESPONSE_SCHEMA
        and item.outcome == ASSERTION_OUTCOME_FAILED
    ]
    located = [item for item in schema_failures if (item.subject or "").startswith("/")]
    chosen = located[:limit] if located else schema_failures[:1]
    return [
        DriftFinding(
            **common,
            kind=DRIFT_KIND_RESPONSE_SCHEMA,
            code=item.code or FAILURE_RESPONSE_SCHEMA_MISMATCH,
            pointer=item.subject if (item.subject or "").startswith("/") else None,
            expected=item.expected,
            actual=item.actual,
            message=item.message or "the response body does not satisfy its schema",
        )
        for item in chosen
    ]


def _operation_outcome(counts: Mapping[str, int]) -> str:
    """The verdict one operation's case counts imply.

    ``errored`` outranks ``failed`` for the same reason it does at run level: a failed operation
    showed an incompatibility, an errored one never got far enough to show anything. An operation
    whose every case was skipped is ``skipped`` — not ``passed``, because nothing was checked.

    Args:
        counts: ``passed``/``failed``/``errored``/``skipped`` for one operation.

    Returns:
        ``passed``, ``failed``, ``errored``, or ``skipped``.
    """
    if counts.get("errored", 0):
        return OPERATION_OUTCOME_ERRORED
    if counts.get("failed", 0):
        return OPERATION_OUTCOME_FAILED
    if counts.get("passed", 0):
        return OPERATION_OUTCOME_PASSED
    return OPERATION_OUTCOME_SKIPPED


def _uncovered_from_manifest(
    manifest: ContractSuiteManifest, compiled_keys: set
) -> List[UncoveredOperation]:
    """Name the operations the compiler never turned into cases.

    Every "we did not compile that" path in :mod:`app.contract_suite` reports a finding carrying
    the operation key, so the uncompiled operations are recoverable from ``manifest.findings``
    without the compiler having to keep a second list.

    Args:
        manifest: The compiled suite.
        compiled_keys: Operation keys that *did* produce cases.

    Returns:
        One entry per named uncompiled operation, sorted by key.
    """
    seen: Dict[str, UncoveredOperation] = {}
    for finding in manifest.findings:
        key = finding.operation_key
        if not key or key in compiled_keys or key in seen:
            continue
        seen[key] = UncoveredOperation(
            operation_key=key, reason_code=finding.code, message=finding.message
        )
    return [seen[key] for key in sorted(seen)]


def build_conformance_report(
    manifest: ContractSuiteManifest,
    plan: ProviderRunPlan,
    operations: Sequence[OperationResultInput],
    *,
    target: TargetIdentity,
    options: ProviderVerificationOptions,
    started_at: datetime,
    finished_at: datetime,
) -> ConformanceReport:
    """Turn executed cases into the drift picture of a deployment.

    Args:
        manifest: The suite that was executed — the source of the coverage denominator and of the
            operations the compiler could not cover.
        plan: The decisions the run was made under, for the skip reasons.
        operations: The executed case records, as the runner returned them.
        target: Identity snapshot of the deployment.
        options: The run's options, echoed so a report explains its own scope.
        started_at: When the run began.
        finished_at: When the run ended.

    Returns:
        The :class:`ConformanceReport`. Its ``outcome`` is derived from the case records, never
        declared, so a report cannot claim a verdict its own detail contradicts.
    """
    limit = options.max_drift_findings_per_case
    declared = {operation.key: operation for operation in manifest.operations}

    buckets: Dict[str, Dict[str, Any]] = {}
    for record in operations:
        bucket = buckets.setdefault(
            record.operation_key,
            {
                "name": record.operation_name,
                "method": record.http_method,
                "path": record.http_path,
                "counts": {"passed": 0, "failed": 0, "errored": 0, "skipped": 0},
                "drift": [],
                "skip_reason": None,
            },
        )
        bucket["counts"][record.outcome] += 1
        bucket["drift"].extend(_drift_from_operation(record, limit=limit))
        if record.outcome == OPERATION_OUTCOME_SKIPPED and bucket["skip_reason"] is None:
            bucket["skip_reason"] = record.failure_message

    conformances: List[OperationConformance] = []
    for key in sorted(buckets):
        bucket = buckets[key]
        counts = bucket["counts"]
        outcome = _operation_outcome(counts)
        declared_operation = declared.get(key)
        conformances.append(
            OperationConformance(
                operation_key=key,
                operation_name=bucket["name"],
                http_method=bucket["method"],
                http_path=(
                    declared_operation.http_path if declared_operation else bucket["path"]
                ),
                outcome=outcome,
                exercised=outcome != OPERATION_OUTCOME_SKIPPED,
                cases_total=sum(counts.values()),
                cases_passed=counts["passed"],
                cases_failed=counts["failed"],
                cases_errored=counts["errored"],
                cases_skipped=counts["skipped"],
                skip_reason=bucket["skip_reason"] if outcome == OPERATION_OUTCOME_SKIPPED else None,
                drift=bucket["drift"],
            )
        )

    uncompiled = int(manifest.counts.get("operations_skipped", 0))
    operations_total = len(manifest.operations) + uncompiled
    exercised = [item for item in conformances if item.exercised]
    uncovered = [
        UncoveredOperation(
            operation_key=item.operation_key,
            reason_code=_skip_code_for(plan, manifest, item.operation_key),
            message=item.skip_reason or "no case for this operation was sent",
        )
        for item in conformances
        if not item.exercised
    ]
    uncovered.extend(_uncovered_from_manifest(manifest, set(declared)))
    uncovered.sort(key=lambda item: item.operation_key)
    # The *count* is the truth; the list is capped so a 500-operation specification that compiles
    # none of itself yields a readable report rather than a wall.
    uncovered_named = len(uncovered)
    uncovered = uncovered[:MAX_UNCOVERED_NAMED]

    case_counts = {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}
    for record in operations:
        case_counts[record.outcome] += 1

    coverage = CoverageSummary(
        operations_total=operations_total,
        operations_exercised=len(exercised),
        operations_passed=sum(
            1 for item in exercised if item.outcome == OPERATION_OUTCOME_PASSED
        ),
        operations_failed=sum(
            1 for item in exercised if item.outcome == OPERATION_OUTCOME_FAILED
        ),
        operations_errored=sum(
            1 for item in exercised if item.outcome == OPERATION_OUTCOME_ERRORED
        ),
        operations_skipped=len(conformances) - len(exercised),
        operations_uncompiled=uncompiled,
        uncovered_named=uncovered_named,
        coverage_percent=(
            round(len(exercised) * 100.0 / operations_total, 1) if operations_total else 0.0
        ),
        cases_total=len(operations),
        cases_passed=case_counts["passed"],
        cases_failed=case_counts["failed"],
        cases_errored=case_counts["errored"],
        cases_skipped=case_counts["skipped"],
    )

    if case_counts["errored"]:
        outcome = RUN_OUTCOME_ERRORED
    elif case_counts["failed"]:
        outcome = RUN_OUTCOME_FAILED
    else:
        outcome = RUN_OUTCOME_PASSED

    drift: List[DriftFinding] = []
    for item in conformances:
        drift.extend(item.drift)

    duration_ms = max(0, int(round((finished_at - started_at).total_seconds() * 1000)))
    return ConformanceReport(
        outcome=outcome,
        suite_digest=manifest.digest,
        api_title=manifest.api.title,
        api_version=manifest.api.version,
        api_format=manifest.api.format,
        target=target,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        coverage=coverage,
        operations=conformances,
        uncovered=uncovered,
        drift=drift,
        mutating_allowed=options.allow_mutating,
        mutating_operations_exercised=list(plan.mutating_operations_exercised),
        fixtures_supplied=len(options.fixtures),
        fixtures_applied=plan.fixtures_applied,
        fixture_findings=list(plan.findings),
    )


def _skip_code_for(
    plan: ProviderRunPlan, manifest: ContractSuiteManifest, operation_key: str
) -> str:
    """The reason code to attribute to an operation nothing was sent for.

    Args:
        plan: The run plan, whose ``skips`` map case ids to reason codes.
        manifest: The compiled suite, for finding the operation's case ids.
        operation_key: The operation in question.

    Returns:
        The reason code shared by the operation's held-back cases, or
        :data:`SKIP_MUTATING_BLOCKED` when the cases disagree or none is recorded.
    """
    codes = {
        plan.skips[case.case_id]
        for case in manifest.cases
        if case.operation_key == operation_key and case.case_id in plan.skips
    }
    if len(codes) == 1:
        return codes.pop()
    return SKIP_MUTATING_BLOCKED
