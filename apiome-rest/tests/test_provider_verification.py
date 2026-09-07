"""Unit tests for the provider verification core — CTG-4.3 (#4489).

Acceptance criteria covered here (the pure half — see
``test_provider_verification_service.py`` for the end-to-end half):

* **mutating operations are never called unless explicitly opted in with fixtures** — every row of
  the planning table, including the case where the run opts in but supplies no fixture;
* **injected drift is reported with operation + JSON pointer** — the drift extraction that reads
  located violations back out of the evidence assertions;
* **coverage numbers are accurate** — the denominator counts operations the compiler could not
  compile, and what was not exercised is named with its reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from app.contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    CASE_SOURCE_NEGATIVE_BODY_MUTATION,
    CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
    OUTCOME_CLIENT_ERROR,
    OUTCOME_SUCCESS,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractRequestParameter,
    ContractSuiteManifest,
    ContractSuiteOptions,
    SuiteApiInfo,
    SuiteFinding,
    SuiteOperation,
)
from app.provider_verification import (
    DRIFT_KIND_RESPONSE_SCHEMA,
    DRIFT_KIND_STATUS,
    DRIFT_KIND_TRANSPORT,
    FIXTURE_CODE_CASE_UNMATCHED,
    FIXTURE_CODE_NOT_MUTATING,
    FIXTURE_CODE_UNMATCHED,
    MAX_UNCOVERED_NAMED,
    SKIP_MUTATING_BLOCKED,
    SKIP_MUTATING_FIXTURE_MISSING,
    MutatingFixture,
    ProviderVerificationOptions,
    TargetIdentity,
    apply_fixture,
    build_conformance_report,
    plan_provider_run,
)
from app.verification_evidence import (
    ASSERTION_KIND_RESPONSE_SCHEMA,
    ASSERTION_KIND_STATUS_CODE,
    ASSERTION_OUTCOME_FAILED,
    OPERATION_OUTCOME_ERRORED,
    OPERATION_OUTCOME_FAILED,
    OPERATION_OUTCOME_PASSED,
    OPERATION_OUTCOME_SKIPPED,
    AssertionInput,
    OperationResultInput,
)

_START = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
_END = _START + timedelta(seconds=2)

_TARGET = TargetIdentity(
    target_id="22222222-2222-4222-8222-222222222222",
    slug="staging",
    environment="staging",
    network_class="public",
    base_url="https://staging.example.test/v1",
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _case(
    *,
    case_id: str,
    method: str = "GET",
    path: str = "/pets",
    template: Optional[str] = None,
    source: str = CASE_SOURCE_DECLARED_EXAMPLE,
    source_detail: Optional[str] = None,
    parameters: Optional[List[ContractRequestParameter]] = None,
    body: Any = None,
    has_body: bool = False,
    outcome: str = OUTCOME_SUCCESS,
) -> ContractCase:
    """Build one compiled case."""
    return ContractCase(
        case_id=case_id,
        operation_key=f"{method} {template or path}",
        operation_name="listPets" if method == "GET" else "writePet",
        source=source,
        source_detail=source_detail,
        title=case_id,
        description="test case",
        synthetic=source != CASE_SOURCE_DECLARED_EXAMPLE,
        request=ContractCaseRequest(
            method=method,
            path_template=template or path,
            path=path,
            parameters=parameters or [],
            has_body=has_body,
            body=body,
            media_type="application/json" if has_body else None,
        ),
        expect=ContractCaseExpectation(
            outcome=outcome,
            status_codes=["4XX"] if outcome == OUTCOME_CLIENT_ERROR else ["200"],
            status_declared=True,
            response_schema_id="type:Pet",
            reason="contract says so",
        ),
    )


def _operation(key: str, method: str, path: str, cases: int = 1) -> SuiteOperation:
    """Build one compiled operation summary."""
    return SuiteOperation(
        key=key, name="op", http_method=method, http_path=path, case_count=cases
    )


def _manifest(
    cases: List[ContractCase],
    *,
    operations: Optional[List[SuiteOperation]] = None,
    findings: Optional[List[SuiteFinding]] = None,
    counts: Optional[Dict[str, int]] = None,
) -> ContractSuiteManifest:
    """Build a manifest around ``cases``."""
    derived = operations
    if derived is None:
        seen: Dict[str, SuiteOperation] = {}
        for case in cases:
            seen.setdefault(
                case.operation_key,
                _operation(
                    case.operation_key,
                    case.request.method,
                    case.request.path_template,
                ),
            )
        derived = [seen[key] for key in sorted(seen)]
    return ContractSuiteManifest(
        digest="sha256:" + "a" * 64,
        options=ContractSuiteOptions(),
        api=SuiteApiInfo(name="pets", format="openapi-3.1", paradigm="rest"),
        operations=derived,
        cases=cases,
        findings=findings or [],
        counts=counts or {"operations_compiled": len(derived), "operations_skipped": 0},
    )


def _result(
    case: ContractCase,
    outcome: str,
    *,
    failure_code: Optional[str] = None,
    failure_message: Optional[str] = None,
    actual_status: Optional[int] = None,
    assertions: Optional[List[AssertionInput]] = None,
) -> OperationResultInput:
    """Build one executed-case evidence record."""
    return OperationResultInput(
        case_id=case.case_id,
        operation_key=case.operation_key,
        operation_name=case.operation_name,
        case_source=case.source,
        http_method=case.request.method,
        http_path=case.request.path,
        outcome=outcome,
        failure_code=failure_code,
        failure_message=failure_message,
        actual_status=actual_status,
        assertions=assertions or [],
    )


def _report(manifest, plan, results, options=None):
    """Build a conformance report with the shared timings and target."""
    return build_conformance_report(
        manifest,
        plan,
        results,
        target=_TARGET,
        options=options or ProviderVerificationOptions(),
        started_at=_START,
        finished_at=_END,
    )


# ---------------------------------------------------------------------------
# Fixture validation — misuse is refused, not absorbed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header", ["Authorization", "authorization", "X-Api-Key", "Cookie", "x-auth-token"]
)
def test_a_fixture_may_not_carry_credentials(header: str) -> None:
    """Auth belongs to the target's secret-free reference, never to a persisted fixture."""
    with pytest.raises(ValidationError, match="may not carry credentials"):
        MutatingFixture(operation_key="POST /pets", headers={header: "sekrit"})


def test_a_fixture_may_carry_ordinary_headers() -> None:
    fixture = MutatingFixture(operation_key="POST /pets", headers={"X-Trace-Id": "abc"})
    assert fixture.headers == {"X-Trace-Id": "abc"}


@pytest.mark.parametrize(
    "kwargs,declares,sends",
    [
        ({}, False, False),
        ({"body": {"name": "Rex"}}, True, True),
        ({"has_body": False}, True, False),
        ({"has_body": True, "body": None}, True, True),
    ],
)
def test_body_declaration_distinguishes_silence_from_none(
    kwargs: Dict[str, Any], declares: bool, sends: bool
) -> None:
    """A fixture that says nothing about the body must leave the compiled body alone."""
    fixture = MutatingFixture(operation_key="POST /pets", **kwargs)
    assert fixture.declares_body() is declares
    assert fixture.sends_body() is sends


# ---------------------------------------------------------------------------
# Planning — the mutating gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_safe_methods_always_run(method: str) -> None:
    """Acceptance: a read-only verification needs no opt-in at all."""
    manifest = _manifest([_case(case_id="c1", method=method)])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    assert plan.decisions == {}
    assert plan.skips == {}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_mutating_methods_are_held_back_by_default(method: str) -> None:
    """Acceptance: mutating operations are never called unless explicitly opted in."""
    case = _case(case_id="c1", method=method, path="/pets")
    plan = plan_provider_run(
        _manifest([case]), ProviderVerificationOptions(), target_allows_mutating=True
    )
    decision = plan.decisions["c1"]
    assert decision.run is False
    assert decision.skip_code == SKIP_MUTATING_BLOCKED
    assert "did not opt in" in (decision.skip_message or "")


def test_opting_in_without_a_fixture_still_sends_nothing() -> None:
    """Opting in is a permission, not a payload: no fixture, no request."""
    case = _case(case_id="c1", method="POST", path="/pets")
    plan = plan_provider_run(
        _manifest([case]),
        ProviderVerificationOptions(allow_mutating=True),
        target_allows_mutating=True,
    )
    decision = plan.decisions["c1"]
    assert decision.run is False
    assert decision.skip_code == SKIP_MUTATING_FIXTURE_MISSING
    assert plan.fixtures_applied == 0
    assert plan.mutating_operations_exercised == []


def test_a_run_cannot_widen_the_target_policy() -> None:
    """The ECA-1.2 registry decides the ceiling; a run may only narrow it."""
    case = _case(case_id="c1", method="POST", path="/pets")
    plan = plan_provider_run(
        _manifest([case]),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[MutatingFixture(operation_key="POST /pets", body={"name": "Rex"})],
        ),
        target_allows_mutating=False,
    )
    decision = plan.decisions["c1"]
    assert decision.run is False
    assert decision.skip_code == SKIP_MUTATING_BLOCKED
    assert "cannot override" in (decision.skip_message or "")


def test_a_fixture_unlocks_its_operation() -> None:
    """Acceptance: with an explicit opt-in and a fixture, the case runs — with the fixture's body."""
    case = _case(case_id="c1", method="POST", path="/pets", body={"name": "x"}, has_body=True)
    plan = plan_provider_run(
        _manifest([case]),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[MutatingFixture(operation_key="POST /pets", body={"name": "Rex"})],
        ),
        target_allows_mutating=True,
    )
    decision = plan.decisions["c1"]
    assert decision.run is True
    assert decision.case is not None
    assert decision.case.request.body == {"name": "Rex"}
    assert plan.fixtures_applied == 1
    assert plan.mutating_operations_exercised == ["POST /pets"]
    assert plan.findings == []


def test_a_case_scoped_fixture_beats_an_operation_scoped_one() -> None:
    cases = [
        _case(case_id="c1", method="POST", path="/pets", body={}, has_body=True),
        _case(case_id="c2", method="POST", path="/pets", body={}, has_body=True),
    ]
    plan = plan_provider_run(
        _manifest(cases),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[
                MutatingFixture(operation_key="POST /pets", body={"from": "operation"}),
                MutatingFixture(
                    operation_key="POST /pets", case_id="c2", body={"from": "case"}
                ),
            ],
        ),
        target_allows_mutating=True,
    )
    assert plan.decisions["c1"].case.request.body == {"from": "operation"}
    assert plan.decisions["c2"].case.request.body == {"from": "case"}
    assert plan.findings == []


# ---------------------------------------------------------------------------
# Planning — nothing a caller supplies is silently dropped
# ---------------------------------------------------------------------------


def test_a_fixture_for_an_unknown_operation_is_reported() -> None:
    plan = plan_provider_run(
        _manifest([_case(case_id="c1", method="POST", path="/pets")]),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[
                MutatingFixture(operation_key="POST /pets"),
                MutatingFixture(operation_key="POST /typo"),
            ],
        ),
        target_allows_mutating=True,
    )
    codes = [finding.code for finding in plan.findings]
    assert codes == [FIXTURE_CODE_UNMATCHED]
    assert plan.findings[0].operation_key == "POST /typo"


def test_a_fixture_for_a_safe_operation_is_refused_and_reported() -> None:
    """A fixture is the mutation opt-in; it must not quietly rewrite what a GET sends."""
    case = _case(case_id="c1", method="GET", path="/pets")
    plan = plan_provider_run(
        _manifest([case]),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[MutatingFixture(operation_key="GET /pets", body={"nope": True})],
        ),
        target_allows_mutating=True,
    )
    assert [finding.code for finding in plan.findings] == [FIXTURE_CODE_NOT_MUTATING]
    assert plan.decisions == {}


def test_a_fixture_naming_a_missing_case_is_reported() -> None:
    plan = plan_provider_run(
        _manifest([_case(case_id="c1", method="POST", path="/pets")]),
        ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[MutatingFixture(operation_key="POST /pets", case_id="nope")],
        ),
        target_allows_mutating=True,
    )
    assert [finding.code for finding in plan.findings] == [FIXTURE_CODE_CASE_UNMATCHED]
    # The case itself still ran nothing: no fixture matched it.
    assert plan.decisions["c1"].skip_code == SKIP_MUTATING_FIXTURE_MISSING


# ---------------------------------------------------------------------------
# apply_fixture — the request changes, the expectation never does
# ---------------------------------------------------------------------------


def test_path_parameters_are_substituted_and_encoded() -> None:
    case = _case(
        case_id="c1",
        method="DELETE",
        path="/pets/1",
        template="/pets/{petId}",
        parameters=[
            ContractRequestParameter(
                name="petId", location="path", value="1", origin="generated", required=True
            )
        ],
    )
    applied = apply_fixture(
        case, MutatingFixture(operation_key="DELETE /pets/{petId}", path_parameters={"petId": "a/b"})
    )
    assert applied.request.path == "/pets/a%2Fb"
    assert applied.expect == case.expect
    assert applied.case_id == case.case_id


def test_query_and_header_values_are_merged_and_attributed() -> None:
    case = _case(
        case_id="c1",
        method="POST",
        path="/pets",
        parameters=[
            ContractRequestParameter(
                name="dry", location="query", value="false", origin="generated"
            )
        ],
    )
    applied = apply_fixture(
        case,
        MutatingFixture(
            operation_key="POST /pets",
            query_parameters={"dry": "true", "trace": "on"},
            headers={"X-Trace-Id": "abc"},
        ),
    )
    values = {(p.location, p.name): (p.value, p.origin) for p in applied.request.parameters}
    assert values[("query", "dry")] == ("true", "fixture")
    assert values[("query", "trace")] == ("on", "fixture")
    assert values[("header", "X-Trace-Id")] == ("abc", "fixture")


def test_a_fixture_never_overwrites_a_negative_case_body() -> None:
    """A negative case's body *is* the case; replacing it would delete the test."""
    case = _case(
        case_id="c1",
        method="POST",
        path="/pets",
        source=CASE_SOURCE_NEGATIVE_BODY_MUTATION,
        body={"name": 42},
        has_body=True,
        outcome=OUTCOME_CLIENT_ERROR,
    )
    applied = apply_fixture(
        case, MutatingFixture(operation_key="POST /pets", body={"name": "Rex"})
    )
    assert applied.request.body == {"name": 42}


def test_a_fixture_never_restores_the_parameter_a_negative_case_omits() -> None:
    case = _case(
        case_id="c1",
        method="POST",
        path="/pets",
        source=CASE_SOURCE_NEGATIVE_MISSING_PARAMETER,
        source_detail="status",
        outcome=OUTCOME_CLIENT_ERROR,
    )
    applied = apply_fixture(
        case,
        MutatingFixture(
            operation_key="POST /pets",
            query_parameters={"status": "available", "trace": "on"},
        ),
    )
    names = {parameter.name for parameter in applied.request.parameters}
    assert "status" not in names
    assert "trace" in names


def test_an_unsatisfiable_template_keeps_the_compiled_path() -> None:
    """A half-substituted path would be a request to somewhere else entirely."""
    case = _case(case_id="c1", method="DELETE", path="/pets/1", template="/pets/{petId}")
    applied = apply_fixture(case, MutatingFixture(operation_key="DELETE /pets/{petId}"))
    assert applied.request.path == "/pets/1"


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------


def test_coverage_is_all_pass_against_a_conformant_deployment() -> None:
    """Acceptance: a conformant server yields an all-pass report with accurate coverage."""
    cases = [
        _case(case_id="c1", method="GET", path="/pets"),
        _case(case_id="c2", method="GET", path="/pets/1", template="/pets/{petId}"),
    ]
    manifest = _manifest(cases)
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    results = [_result(case, OPERATION_OUTCOME_PASSED, actual_status=200) for case in cases]

    report = _report(manifest, plan, results)

    assert report.outcome == "passed"
    assert report.drift == []
    assert report.coverage.operations_total == 2
    assert report.coverage.operations_exercised == 2
    assert report.coverage.operations_passed == 2
    assert report.coverage.coverage_percent == 100.0
    assert report.coverage.cases_total == 2
    assert report.uncovered == []


def test_the_coverage_denominator_includes_operations_the_compiler_skipped() -> None:
    """A coverage number that ignored uncompilable operations would read as reassurance."""
    case = _case(case_id="c1", method="GET", path="/pets")
    manifest = _manifest(
        [case],
        findings=[
            SuiteFinding(
                code="UNSUPPORTED_STREAMING",
                level="unsupported",
                message="Operation 'GET /events' is server-streaming.",
                operation_key="GET /events",
            )
        ],
        counts={"operations_compiled": 1, "operations_skipped": 1},
    )
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    report = _report(manifest, plan, [_result(case, OPERATION_OUTCOME_PASSED, actual_status=200)])

    assert report.coverage.operations_total == 2
    assert report.coverage.operations_exercised == 1
    assert report.coverage.operations_uncompiled == 1
    assert report.coverage.coverage_percent == 50.0
    assert [item.operation_key for item in report.uncovered] == ["GET /events"]
    assert report.uncovered[0].reason_code == "UNSUPPORTED_STREAMING"


def test_a_held_back_operation_is_named_with_its_reason() -> None:
    """An operation nothing was sent for is 'skipped' — never 'passed'."""
    get_case = _case(case_id="c1", method="GET", path="/pets")
    post_case = _case(case_id="c2", method="POST", path="/pets")
    manifest = _manifest([get_case, post_case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(allow_mutating=True), target_allows_mutating=True
    )
    results = [
        _result(get_case, OPERATION_OUTCOME_PASSED, actual_status=200),
        _result(
            post_case,
            OPERATION_OUTCOME_SKIPPED,
            failure_code=SKIP_MUTATING_FIXTURE_MISSING,
            failure_message="no fixture",
        ),
    ]

    report = _report(
        manifest, plan, results, options=ProviderVerificationOptions(allow_mutating=True)
    )

    post = next(item for item in report.operations if item.operation_key == "POST /pets")
    assert post.outcome == OPERATION_OUTCOME_SKIPPED
    assert post.exercised is False
    assert report.coverage.operations_exercised == 1
    assert report.coverage.operations_skipped == 1
    assert report.coverage.coverage_percent == 50.0
    uncovered = {item.operation_key: item.reason_code for item in report.uncovered}
    assert uncovered == {"POST /pets": SKIP_MUTATING_FIXTURE_MISSING}
    # The run still passed: nothing contradicted the contract. The coverage says what was checked.
    assert report.outcome == "passed"


def test_coverage_percent_is_zero_when_the_model_declares_nothing() -> None:
    manifest = _manifest([], operations=[], counts={"operations_skipped": 0})
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    report = _report(manifest, plan, [])
    assert report.coverage.coverage_percent == 0.0
    assert report.outcome == "passed"


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


def test_schema_drift_is_reported_with_operation_and_json_pointer() -> None:
    """Acceptance: injected drift is detected and reported with operation + JSON pointer."""
    case = _case(case_id="c1", method="GET", path="/pets/1", template="/pets/{petId}")
    manifest = _manifest([case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    results = [
        _result(
            case,
            OPERATION_OUTCOME_FAILED,
            failure_code="response-schema-mismatch",
            failure_message="'name' is a required property",
            actual_status=200,
            assertions=[
                AssertionInput(
                    kind=ASSERTION_KIND_RESPONSE_SCHEMA,
                    outcome=ASSERTION_OUTCOME_FAILED,
                    subject="type:Pet",
                    expected="type:Pet",
                    actual="'name' is a required property",
                    code="response-schema-mismatch",
                    message="'name' is a required property",
                ),
                AssertionInput(
                    kind=ASSERTION_KIND_RESPONSE_SCHEMA,
                    outcome=ASSERTION_OUTCOME_FAILED,
                    subject="/",
                    expected='["id","name"]',
                    actual='{"id":1}',
                    code="response-schema-mismatch",
                    message="required: 'name' is a required property",
                ),
                AssertionInput(
                    kind=ASSERTION_KIND_RESPONSE_SCHEMA,
                    outcome=ASSERTION_OUTCOME_FAILED,
                    subject="/id",
                    expected='"integer"',
                    actual='"1"',
                    code="response-schema-mismatch",
                    message="type: '1' is not of type 'integer'",
                ),
            ],
        )
    ]

    report = _report(manifest, plan, results)

    assert report.outcome == "failed"
    assert [item.pointer for item in report.drift] == ["/", "/id"]
    assert {item.operation_key for item in report.drift} == {"GET /pets/{petId}"}
    assert all(item.kind == DRIFT_KIND_RESPONSE_SCHEMA for item in report.drift)
    assert report.drift[1].expected == '"integer"'
    assert report.drift[1].actual == '"1"'


def test_an_unlocated_schema_failure_is_still_reported() -> None:
    """A failure with no pointer (a schema the suite did not carry) must not vanish."""
    case = _case(case_id="c1")
    manifest = _manifest([case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    results = [
        _result(
            case,
            OPERATION_OUTCOME_FAILED,
            failure_code="response-schema-mismatch",
            failure_message="suite has no schema for id 'type:Pet'",
            actual_status=200,
            assertions=[
                AssertionInput(
                    kind=ASSERTION_KIND_RESPONSE_SCHEMA,
                    outcome=ASSERTION_OUTCOME_FAILED,
                    subject="type:Pet",
                    code="response-schema-mismatch",
                    message="suite has no schema for id 'type:Pet'",
                )
            ],
        )
    ]
    report = _report(manifest, plan, results)
    assert len(report.drift) == 1
    assert report.drift[0].pointer is None


def test_located_violations_are_capped_per_case() -> None:
    case = _case(case_id="c1")
    manifest = _manifest([case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    assertions = [
        AssertionInput(
            kind=ASSERTION_KIND_RESPONSE_SCHEMA,
            outcome=ASSERTION_OUTCOME_FAILED,
            subject=f"/items/{index}",
            code="response-schema-mismatch",
            message="type mismatch",
        )
        for index in range(10)
    ]
    results = [
        _result(
            case,
            OPERATION_OUTCOME_FAILED,
            failure_code="response-schema-mismatch",
            failure_message="drift",
            actual_status=200,
            assertions=assertions,
        )
    ]
    report = _report(
        manifest,
        plan,
        results,
        options=ProviderVerificationOptions(max_drift_findings_per_case=3),
    )
    assert len(report.drift) == 3


def test_status_drift_is_reported_without_a_pointer() -> None:
    case = _case(case_id="c1")
    manifest = _manifest([case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    results = [
        _result(
            case,
            OPERATION_OUTCOME_FAILED,
            failure_code="status-mismatch",
            failure_message="expected status in [200], got 500",
            actual_status=500,
            assertions=[
                AssertionInput(
                    kind=ASSERTION_KIND_STATUS_CODE,
                    outcome=ASSERTION_OUTCOME_FAILED,
                    subject="status",
                    expected="200",
                    actual="500",
                    code="status-mismatch",
                    message="expected status in [200], got 500",
                )
            ],
        )
    ]
    report = _report(manifest, plan, results)
    assert len(report.drift) == 1
    assert report.drift[0].kind == DRIFT_KIND_STATUS
    assert report.drift[0].pointer is None
    assert report.drift[0].expected == "200"
    assert report.drift[0].actual == "500"


def test_a_transport_failure_errors_the_run_rather_than_failing_it() -> None:
    """A run that never got an answer showed nothing — a gate must read that differently."""
    case = _case(case_id="c1")
    manifest = _manifest([case])
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    results = [
        _result(
            case,
            OPERATION_OUTCOME_ERRORED,
            failure_code="timeout",
            failure_message="request timed out",
        )
    ]
    report = _report(manifest, plan, results)
    assert report.outcome == "errored"
    assert report.drift[0].kind == DRIFT_KIND_TRANSPORT
    assert report.coverage.operations_errored == 1


def test_the_report_echoes_its_own_scope() -> None:
    """A report has to explain what it was allowed to check, or its coverage is unreadable."""
    case = _case(case_id="c1", method="POST", path="/pets", body={}, has_body=True)
    manifest = _manifest([case])
    options = ProviderVerificationOptions(
        allow_mutating=True,
        fixtures=[
            MutatingFixture(operation_key="POST /pets", body={"name": "Rex"}, note="scratch org"),
            MutatingFixture(operation_key="POST /nope"),
        ],
    )
    plan = plan_provider_run(manifest, options, target_allows_mutating=True)
    report = _report(
        manifest, plan, [_result(case, OPERATION_OUTCOME_PASSED, actual_status=200)], options
    )

    assert report.mutating_allowed is True
    assert report.mutating_operations_exercised == ["POST /pets"]
    assert report.fixtures_supplied == 2
    assert report.fixtures_applied == 1
    assert [finding.code for finding in report.fixture_findings] == [FIXTURE_CODE_UNMATCHED]
    assert report.duration_ms == 2000
    assert report.suite_digest == manifest.digest
    assert report.target.base_url == "https://staging.example.test/v1"


def test_the_uncovered_list_is_capped_but_its_count_is_not() -> None:
    """A specification that compiles none of itself must not produce an unreadable wall."""
    case = _case(case_id="c1", method="GET", path="/pets")
    uncompiled = MAX_UNCOVERED_NAMED + 25
    manifest = _manifest(
        [case],
        findings=[
            SuiteFinding(
                code="UNSUPPORTED_STREAMING",
                level="unsupported",
                message=f"Operation 'GET /stream/{index:04d}' is server-streaming.",
                operation_key=f"GET /stream/{index:04d}",
            )
            for index in range(uncompiled)
        ],
        counts={"operations_compiled": 1, "operations_skipped": uncompiled},
    )
    plan = plan_provider_run(
        manifest, ProviderVerificationOptions(), target_allows_mutating=False
    )
    report = _report(manifest, plan, [_result(case, OPERATION_OUTCOME_PASSED, actual_status=200)])

    assert len(report.uncovered) == MAX_UNCOVERED_NAMED
    assert report.coverage.uncovered_named == uncompiled
    assert report.coverage.operations_total == uncompiled + 1
    assert report.coverage.operations_uncompiled == uncompiled
