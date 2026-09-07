"""End-to-end unit tests for provider verification — CTG-4.3 (#4489).

Hermetic: the suite compiler, the target registry, the evidence store, and the report store are
patched on the service module, and the only traffic goes through an ``httpx.MockTransport`` that
stands in for the deployment. Nothing here touches the network or the database.

Each of the ticket's four acceptance criteria is covered:

1. against a conformant test server, the report is all-pass with accurate coverage numbers;
2. injected drift — a removed required field and a changed type — is detected and reported with
   the operation *and* the JSON pointer;
3. mutating operations are never called unless explicitly opted in **with fixtures** — asserted by
   watching what the transport actually received;
4. the report is persisted, with the coverage columns derived from the report itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest

from app.contract_suite import (
    CASE_SOURCE_DECLARED_EXAMPLE,
    OUTCOME_SUCCESS,
    ContractCase,
    ContractCaseExpectation,
    ContractCaseRequest,
    ContractSuiteManifest,
    ContractSuiteOptions,
    SuiteApiInfo,
    SuiteOperation,
    SuiteSourceInfo,
)
from app.contract_suite_service import ContractSuiteResponse
from app.provider_verification import (
    SKIP_MUTATING_BLOCKED,
    SKIP_MUTATING_FIXTURE_MISSING,
    MutatingFixture,
    ProviderVerificationOptions,
)
from app.provider_verification_service import (
    ProviderVerificationRequest,
    verify_version_against_target,
)
from app.provider_verification_store import ConformanceReportRecord
from app.verification_evidence import VerificationRunRecord
from app.verification_evidence_store import RecordedRun, TargetActor
from app.verification_target import (
    NETWORK_CLASS_PUBLIC,
    ResolvedTarget,
    TargetAuthReference,
    VerificationPolicy,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_VERSION_REF = "project/petstore/1.0.0"
_ACTOR = TargetActor(user_id="33333333-3333-4333-8333-333333333333", label="dev@example.test")

_PET_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _case(case_id: str, method: str, path: str, *, body: Any = None) -> ContractCase:
    """Build one compiled case."""
    return ContractCase(
        case_id=case_id,
        operation_key=f"{method} {path}",
        operation_name=f"{method.lower()}Pets",
        source=CASE_SOURCE_DECLARED_EXAMPLE,
        title=case_id,
        description="test case",
        synthetic=False,
        request=ContractCaseRequest(
            method=method,
            path_template=path,
            path=path,
            has_body=body is not None,
            body=body,
            media_type="application/json" if body is not None else None,
        ),
        expect=ContractCaseExpectation(
            outcome=OUTCOME_SUCCESS,
            status_codes=["2XX"],
            status_declared=True,
            response_schema_id="type:Pet",
            reason="the contract declares a 200 with a Pet body",
        ),
    )


def _manifest(cases: List[ContractCase]) -> ContractSuiteManifest:
    """Build a manifest around ``cases``, with one operation per distinct key."""
    seen: Dict[str, SuiteOperation] = {}
    for case in cases:
        seen.setdefault(
            case.operation_key,
            SuiteOperation(
                key=case.operation_key,
                name=case.operation_name or "op",
                http_method=case.request.method,
                http_path=case.request.path_template,
                case_count=1,
            ),
        )
    manifest = ContractSuiteManifest(
        digest="sha256:" + "b" * 64,
        options=ContractSuiteOptions(),
        api=SuiteApiInfo(
            name="pets", title="Pets", version="1.0.0", format="openapi-3.1", paradigm="rest"
        ),
        source=SuiteSourceInfo(
            kind="project",
            reference=_VERSION_REF,
            artifact_slug="petstore",
            version_label="1.0.0",
            published=True,
        ),
        operations=[seen[key] for key in sorted(seen)],
        cases=cases,
        schemas={"type:Pet": _PET_SCHEMA},
        counts={"operations_compiled": len(seen), "operations_skipped": 0},
    )
    return manifest


def _target(*, allow_mutating: bool = False) -> ResolvedTarget:
    """A resolved staging target."""
    return ResolvedTarget(
        target_id="22222222-2222-4222-8222-222222222222",
        slug="staging",
        name="Staging",
        environment="staging",
        network_class=NETWORK_CLASS_PUBLIC,
        base_url="https://staging.example.test/v1",
        policy=VerificationPolicy(allow_mutating_methods=allow_mutating),
        auth=TargetAuthReference(),
        resolved_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )


def _run_record(run_id: str = "44444444-4444-4444-8444-444444444444") -> VerificationRunRecord:
    """A minimal stored evidence record."""
    return VerificationRunRecord(
        id=run_id,
        tenant_id=_TENANT,
        suite_digest="sha256:" + "b" * 64,
        target_slug="staging",
        target_environment="staging",
        target_network_class=NETWORK_CLASS_PUBLIC,
        target_base_url="https://staging.example.test/v1",
        runner_name="apiome-provider-verifier",
        outcome="passed",
    )


class _Deployment:
    """A fake deployment that records every request it was sent.

    The recording is the point: "mutating operations are never called" is only provable by looking
    at what actually went out, not at what the report says was skipped.
    """

    def __init__(self, handler) -> None:
        self.requests: List[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @property
    def methods(self) -> List[str]:
        """The HTTP verbs the deployment actually received."""
        return [request.method for request in self.requests]


def _verify(
    manifest: ContractSuiteManifest,
    deployment: _Deployment,
    *,
    target: Optional[ResolvedTarget] = None,
    verification: Optional[ProviderVerificationOptions] = None,
    saved: Optional[List[Any]] = None,
):
    """Run the service with every boundary patched and the transport faked."""
    client = httpx.Client(transport=httpx.MockTransport(deployment))
    record = _run_record()

    def _save(tenant_id, report, **kwargs):
        if saved is not None:
            saved.append((tenant_id, report, kwargs))
        return ConformanceReportRecord(
            id="55555555-5555-4555-8555-555555555555",
            tenant_id=tenant_id,
            run_id=kwargs["run_id"],
            version_ref=kwargs["version_ref"],
            suite_digest=report.suite_digest,
            target_slug=report.target.slug,
            target_environment=report.target.environment,
            target_network_class=report.target.network_class,
            target_base_url=report.target.base_url,
            outcome=report.outcome,
            operations_total=report.coverage.operations_total,
            operations_exercised=report.coverage.operations_exercised,
            operations_passed=report.coverage.operations_passed,
            operations_failed=report.coverage.operations_failed,
            operations_errored=report.coverage.operations_errored,
            operations_skipped=report.coverage.operations_skipped,
            operations_uncompiled=report.coverage.operations_uncompiled,
            coverage_percent=report.coverage.coverage_percent,
            cases_total=report.coverage.cases_total,
            cases_passed=report.coverage.cases_passed,
            cases_failed=report.coverage.cases_failed,
            cases_errored=report.coverage.cases_errored,
            cases_skipped=report.coverage.cases_skipped,
            drift_count=len(report.drift),
            mutating_allowed=report.mutating_allowed,
            fixture_count=report.fixtures_supplied,
            report=report,
        )

    try:
        with patch(
            "app.provider_verification_service.compile_version_contract_suite",
            return_value=ContractSuiteResponse(
                ok=True, version_ref=_VERSION_REF, manifest=manifest
            ),
        ), patch(
            "app.provider_verification_service.resolve_target",
            return_value=target or _target(),
        ), patch(
            "app.provider_verification_service.record_run",
            return_value=RecordedRun(record, created=True),
        ), patch(
            "app.provider_verification_service.save_report", side_effect=_save
        ), patch(
            "app.contract_runner.build_guarded_client", return_value=client
        ):
            return verify_version_against_target(
                _VERSION_REF,
                ProviderVerificationRequest(
                    target_ref="staging",
                    verification=verification or ProviderVerificationOptions(),
                ),
                tenant_id=_TENANT,
                actor=_ACTOR,
            )
    finally:
        client.close()


# ---------------------------------------------------------------------------
# 1. A conformant deployment
# ---------------------------------------------------------------------------


def test_a_conformant_deployment_is_all_pass_with_accurate_coverage() -> None:
    """Acceptance: against a conformant test server the report is all-pass, coverage accurate."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    manifest = _manifest(
        [_case("c1", "GET", "/pets"), _case("c2", "GET", "/pets/1")]
    )

    result = _verify(manifest, deployment)

    assert result.ok is True
    assert result.report is not None
    assert result.report.outcome == "passed"
    assert result.report.drift == []
    assert result.report.coverage.operations_total == 2
    assert result.report.coverage.operations_exercised == 2
    assert result.report.coverage.coverage_percent == 100.0
    assert result.report.coverage.cases_passed == 2
    assert deployment.methods == ["GET", "GET"]
    assert result.created is True


# ---------------------------------------------------------------------------
# 2. Injected drift
# ---------------------------------------------------------------------------


def test_a_removed_required_field_is_reported_with_operation_and_pointer() -> None:
    """Acceptance: drift is detected and reported with operation + JSON pointer."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1}))
    result = _verify(_manifest([_case("c1", "GET", "/pets")]), deployment)

    assert result.report.outcome == "failed"
    # The violation is at the document root: the object itself is missing a required property.
    assert [item.pointer for item in result.report.drift] == ["/"]
    assert [item.operation_key for item in result.report.drift] == ["GET /pets"]
    assert "name" in (result.report.drift[0].message or "")
    assert result.report.drift[0].code == "response-schema-mismatch"
    assert result.report.coverage.operations_failed == 1
    assert result.report.coverage.operations_exercised == 1


def test_a_changed_type_is_located_at_the_offending_property() -> None:
    """The pointer must name the field that changed, not just the document."""
    deployment = _Deployment(
        lambda request: httpx.Response(200, json={"id": "not-an-integer", "name": "Rex"})
    )
    result = _verify(_manifest([_case("c1", "GET", "/pets")]), deployment)

    assert result.report.outcome == "failed"
    assert "/id" in {item.pointer for item in result.report.drift}
    finding = next(item for item in result.report.drift if item.pointer == "/id")
    assert finding.kind == "response_schema"
    assert "integer" in (finding.expected or "")


def test_a_wrong_status_fails_the_run_as_status_drift() -> None:
    deployment = _Deployment(lambda request: httpx.Response(500, json={"error": "boom"}))
    result = _verify(_manifest([_case("c1", "GET", "/pets")]), deployment)

    assert result.report.outcome == "failed"
    assert [item.kind for item in result.report.drift] == ["status"]
    assert result.report.drift[0].actual == "500"


# ---------------------------------------------------------------------------
# 3. Mutating operations
# ---------------------------------------------------------------------------


def _mutating_manifest() -> ContractSuiteManifest:
    """A suite with one safe and one mutating operation."""
    return _manifest(
        [_case("c1", "GET", "/pets"), _case("c2", "POST", "/pets", body={"name": "synth"})]
    )


def test_a_mutating_case_is_not_sent_by_default() -> None:
    """Acceptance: mutating operations are never called unless explicitly opted in."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    result = _verify(_mutating_manifest(), deployment, target=_target(allow_mutating=True))

    assert deployment.methods == ["GET"]
    assert "POST" not in deployment.methods
    post = next(
        item for item in result.report.operations if item.operation_key == "POST /pets"
    )
    assert post.exercised is False
    assert result.report.coverage.coverage_percent == 50.0


def test_opting_in_without_a_fixture_still_sends_nothing() -> None:
    """Acceptance: the opt-in alone is not enough — a fixture is required."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    result = _verify(
        _mutating_manifest(),
        deployment,
        target=_target(allow_mutating=True),
        verification=ProviderVerificationOptions(allow_mutating=True),
    )

    assert deployment.methods == ["GET"]
    uncovered = {item.operation_key: item.reason_code for item in result.report.uncovered}
    assert uncovered == {"POST /pets": SKIP_MUTATING_FIXTURE_MISSING}


def test_a_target_policy_that_forbids_mutation_cannot_be_overridden() -> None:
    """A run may narrow what the registry permits, never widen it."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    result = _verify(
        _mutating_manifest(),
        deployment,
        target=_target(allow_mutating=False),
        verification=ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[MutatingFixture(operation_key="POST /pets", body={"name": "Rex"})],
        ),
    )

    assert deployment.methods == ["GET"]
    uncovered = {item.operation_key: item.reason_code for item in result.report.uncovered}
    assert uncovered == {"POST /pets": SKIP_MUTATING_BLOCKED}


def test_a_fixture_sends_the_mutating_case_with_its_own_body() -> None:
    """With both the opt-in and a fixture, the request goes out — carrying the fixture."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    result = _verify(
        _mutating_manifest(),
        deployment,
        target=_target(allow_mutating=True),
        verification=ProviderVerificationOptions(
            allow_mutating=True,
            fixtures=[
                MutatingFixture(
                    operation_key="POST /pets",
                    body={"name": "Fixture Rex"},
                    note="writes to the scratch tenant only",
                )
            ],
        ),
    )

    assert sorted(deployment.methods) == ["GET", "POST"]
    post_request = next(item for item in deployment.requests if item.method == "POST")
    assert b"Fixture Rex" in post_request.content
    assert result.report.mutating_operations_exercised == ["POST /pets"]
    assert result.report.fixtures_applied == 1
    assert result.report.coverage.coverage_percent == 100.0


# ---------------------------------------------------------------------------
# 4. Persistence
# ---------------------------------------------------------------------------


def test_the_report_is_persisted_beside_its_evidence() -> None:
    """Acceptance: reports are persisted and retrievable (CTG-4.4 / CTG-4.5 consume them)."""
    saved: List[Any] = []
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    result = _verify(_manifest([_case("c1", "GET", "/pets")]), deployment, saved=saved)

    assert len(saved) == 1
    tenant_id, report, kwargs = saved[0]
    assert tenant_id == _TENANT
    assert kwargs["run_id"] == result.run.id
    assert kwargs["version_ref"] == _VERSION_REF
    assert kwargs["source"]["artifact_slug"] == "petstore"
    assert report is result.report
    assert result.stored is not None
    assert result.stored.coverage_percent == report.coverage.coverage_percent
    assert result.stored.outcome == report.outcome


def test_a_storage_fault_does_not_lose_the_verification() -> None:
    """The check already happened and its evidence is already immutable; only filing failed."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    client = httpx.Client(transport=httpx.MockTransport(deployment))
    try:
        with patch(
            "app.provider_verification_service.compile_version_contract_suite",
            return_value=ContractSuiteResponse(
                ok=True, version_ref=_VERSION_REF, manifest=_manifest([_case("c1", "GET", "/pets")])
            ),
        ), patch(
            "app.provider_verification_service.resolve_target", return_value=_target()
        ), patch(
            "app.provider_verification_service.record_run",
            return_value=RecordedRun(_run_record(), created=True),
        ), patch(
            "app.provider_verification_service.save_report",
            side_effect=RuntimeError("database is down"),
        ), patch(
            "app.contract_runner.build_guarded_client", return_value=client
        ):
            result = verify_version_against_target(
                _VERSION_REF,
                ProviderVerificationRequest(target_ref="staging"),
                tenant_id=_TENANT,
                actor=_ACTOR,
            )
    finally:
        client.close()

    assert result.ok is True
    assert result.report is not None
    assert result.stored is None


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_version_with_no_cases_refuses_rather_than_reporting_coverage_of_nothing() -> None:
    manifest = _manifest([])
    with patch(
        "app.provider_verification_service.compile_version_contract_suite",
        return_value=ContractSuiteResponse(ok=True, version_ref=_VERSION_REF, manifest=manifest),
    ):
        result = verify_version_against_target(
            _VERSION_REF,
            ProviderVerificationRequest(target_ref="staging"),
            tenant_id=_TENANT,
            actor=_ACTOR,
        )

    assert result.ok is False
    assert result.report is None
    assert result.error is not None
    assert "no executable cases" in result.error.message


def test_a_version_that_cannot_be_compiled_answers_with_the_compiler_error() -> None:
    with patch(
        "app.provider_verification_service.compile_version_contract_suite",
        return_value=ContractSuiteResponse(ok=False, version_ref=_VERSION_REF, manifest=None),
    ):
        result = verify_version_against_target(
            _VERSION_REF,
            ProviderVerificationRequest(target_ref="staging"),
            tenant_id=_TENANT,
            actor=_ACTOR,
        )

    assert result.ok is False
    assert result.error is not None


def test_an_unusable_credential_refuses_before_a_single_request() -> None:
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    target = _target().model_copy(
        update={
            "auth": TargetAuthReference(kind="env", scheme="bearer", ref="MISSING_TOKEN_VAR")
        }
    )
    client = httpx.Client(transport=httpx.MockTransport(deployment))
    try:
        with patch(
            "app.provider_verification_service.compile_version_contract_suite",
            return_value=ContractSuiteResponse(
                ok=True, version_ref=_VERSION_REF, manifest=_manifest([_case("c1", "GET", "/pets")])
            ),
        ), patch(
            "app.provider_verification_service.resolve_target", return_value=target
        ), patch(
            "app.contract_runner.build_guarded_client", return_value=client
        ):
            result = verify_version_against_target(
                _VERSION_REF,
                ProviderVerificationRequest(target_ref="staging"),
                tenant_id=_TENANT,
                actor=_ACTOR,
            )
    finally:
        client.close()

    assert result.ok is False
    assert result.error.code == "SOURCE_AUTH_REQUIRED"
    assert deployment.requests == []


@pytest.mark.parametrize("status", [200, 201, 299])
def test_declared_status_wildcards_are_honoured(status: int) -> None:
    """The runner's own ``2XX`` matching is reused, not reimplemented on this side."""
    deployment = _Deployment(
        lambda request: httpx.Response(status, json={"id": 1, "name": "Rex"})
    )
    result = _verify(_manifest([_case("c1", "GET", "/pets")]), deployment)
    assert result.report.outcome == "passed"
    assert result.report.drift == []


def test_an_idempotent_replay_reads_the_stored_report_rather_than_rewriting_it() -> None:
    """V252 keeps one report per run, so a replay must read — inserting again would be refused."""
    deployment = _Deployment(lambda request: httpx.Response(200, json={"id": 1, "name": "Rex"}))
    client = httpx.Client(transport=httpx.MockTransport(deployment))
    existing = ConformanceReportRecord(
        id="55555555-5555-4555-8555-555555555555",
        tenant_id=_TENANT,
        run_id=_run_record().id,
        version_ref=_VERSION_REF,
        suite_digest="sha256:" + "b" * 64,
        target_slug="staging",
        target_environment="staging",
        target_base_url="https://staging.example.test/v1",
        outcome="passed",
        operations_total=1,
        operations_exercised=1,
        operations_passed=1,
        operations_failed=0,
        operations_errored=0,
        operations_skipped=0,
        operations_uncompiled=0,
        coverage_percent=100.0,
        cases_total=1,
        cases_passed=1,
        cases_failed=0,
        cases_errored=0,
        cases_skipped=0,
        drift_count=0,
        mutating_allowed=False,
        fixture_count=0,
        report=_report_for_replay(),
    )
    try:
        with patch(
            "app.provider_verification_service.compile_version_contract_suite",
            return_value=ContractSuiteResponse(
                ok=True, version_ref=_VERSION_REF, manifest=_manifest([_case("c1", "GET", "/pets")])
            ),
        ), patch(
            "app.provider_verification_service.resolve_target", return_value=_target()
        ), patch(
            "app.provider_verification_service.record_run",
            return_value=RecordedRun(_run_record(), created=False),
        ), patch(
            "app.provider_verification_service.save_report"
        ) as save, patch(
            "app.provider_verification_service.get_report_for_run", return_value=existing
        ) as read, patch(
            "app.contract_runner.build_guarded_client", return_value=client
        ):
            result = verify_version_against_target(
                _VERSION_REF,
                ProviderVerificationRequest(target_ref="staging", idempotency_key="ci-42"),
                tenant_id=_TENANT,
                actor=_ACTOR,
            )
    finally:
        client.close()

    assert result.created is False
    assert not save.called, "a replay must not attempt a second report for the same run"
    assert read.called
    assert result.stored is existing


def _report_for_replay():
    """A minimal stored report body for the replay fixture."""
    from app.provider_verification import (
        ConformanceReport,
        CoverageSummary,
        TargetIdentity,
    )

    return ConformanceReport(
        outcome="passed",
        suite_digest="sha256:" + "b" * 64,
        target=TargetIdentity(
            slug="staging",
            environment="staging",
            base_url="https://staging.example.test/v1",
        ),
        started_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 7, 12, 0, 1, tzinfo=timezone.utc),
        duration_ms=1000,
        coverage=CoverageSummary(
            operations_total=1,
            operations_exercised=1,
            operations_passed=1,
            operations_failed=0,
            operations_errored=0,
            operations_skipped=0,
            operations_uncompiled=0,
            uncovered_named=0,
            coverage_percent=100.0,
            cases_total=1,
            cases_passed=1,
            cases_failed=0,
            cases_errored=0,
            cases_skipped=0,
        ),
        mutating_allowed=False,
    )
