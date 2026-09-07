"""Route tests for the provider verification endpoints — CTG-4.3 (#4489).

Authentication is overridden, permissions and the service/store layers are patched on the routes
module, so these tests assert the HTTP contract only: which permission each route enforces, the
201/200 split, the filters the list read forwards, and the refusal statuses.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.provider_verification import (
    ConformanceReport,
    CoverageSummary,
    DriftFinding,
    TargetIdentity,
)
from app.provider_verification_service import ProviderVerificationResponse
from app.provider_verification_store import (
    CODE_REPORT_NOT_FOUND,
    CODE_REPORT_UNREADABLE,
    ConformanceReportRecord,
    ConformanceReportSummary,
    ProviderVerificationStoreError,
)
from app.verification_target import CODE_NOT_FOUND, TargetValidationError

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_VERSION_REF = "project/petstore/1.0.0"
_REPORT_ID = "55555555-5555-4555-8555-555555555555"
_BASE = f"/v1/tenants/{_TENANT_SLUG}"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request and grant every permission."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    with patch(
        "app.provider_verification_routes.enforce_permission", return_value="test-user-id"
    ):
        yield
    app.dependency_overrides.clear()


def _report(outcome: str = "failed") -> ConformanceReport:
    """A conformance report with one located drift."""
    return ConformanceReport(
        outcome=outcome,
        suite_digest="sha256:" + "b" * 64,
        api_title="Pets",
        target=TargetIdentity(
            slug="staging",
            environment="staging",
            base_url="https://staging.example.test/v1",
        ),
        started_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 7, 12, 0, 2, tzinfo=timezone.utc),
        duration_ms=2000,
        coverage=CoverageSummary(
            operations_total=2,
            operations_exercised=1,
            operations_passed=0,
            operations_failed=1,
            operations_errored=0,
            operations_skipped=1,
            operations_uncompiled=0,
            uncovered_named=1,
            coverage_percent=50.0,
            cases_total=2,
            cases_passed=0,
            cases_failed=1,
            cases_errored=0,
            cases_skipped=1,
        ),
        drift=[
            DriftFinding(
                operation_key="GET /pets",
                case_id="c1",
                http_method="GET",
                http_path="/pets",
                kind="response_schema",
                code="response-schema-mismatch",
                pointer="/id",
                message="type: '1' is not of type 'integer'",
            )
        ],
        mutating_allowed=False,
    )


def _summary(**overrides: Any) -> ConformanceReportSummary:
    """A list-read summary."""
    report = _report()
    coverage = report.coverage
    fields: Dict[str, Any] = {
        "id": _REPORT_ID,
        "tenant_id": _MOCK_AUTH["tenant_id"],
        "run_id": "44444444-4444-4444-8444-444444444444",
        "version_ref": _VERSION_REF,
        "suite_digest": report.suite_digest,
        "target_slug": "staging",
        "target_environment": "staging",
        "target_base_url": "https://staging.example.test/v1",
        "outcome": report.outcome,
        "operations_total": coverage.operations_total,
        "operations_exercised": coverage.operations_exercised,
        "operations_passed": coverage.operations_passed,
        "operations_failed": coverage.operations_failed,
        "operations_errored": coverage.operations_errored,
        "operations_skipped": coverage.operations_skipped,
        "operations_uncompiled": coverage.operations_uncompiled,
        "coverage_percent": coverage.coverage_percent,
        "cases_total": coverage.cases_total,
        "cases_passed": coverage.cases_passed,
        "cases_failed": coverage.cases_failed,
        "cases_errored": coverage.cases_errored,
        "cases_skipped": coverage.cases_skipped,
        "drift_count": len(report.drift),
        "mutating_allowed": False,
        "fixture_count": 0,
    }
    fields.update(overrides)
    return ConformanceReportSummary(**fields)


def _record() -> ConformanceReportRecord:
    """A full stored report."""
    return ConformanceReportRecord(**_summary().model_dump(), report=_report())


# ---------------------------------------------------------------------------
# POST …/verify-provider
# ---------------------------------------------------------------------------


def test_a_new_verification_answers_201_with_its_report() -> None:
    response_model = ProviderVerificationResponse(
        ok=True,
        version_ref=_VERSION_REF,
        suite_digest=_report().suite_digest,
        report=_report(),
        stored=_record(),
        created=True,
    )
    with patch(
        "app.provider_verification_routes.verify_version_against_target",
        return_value=response_model,
    ):
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={"target_ref": "staging"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["ok"] is True
    assert body["report"]["coverage"]["coverage_percent"] == 50.0
    assert body["report"]["drift"][0]["pointer"] == "/id"


def test_an_idempotent_replay_answers_200() -> None:
    response_model = ProviderVerificationResponse(
        ok=True, version_ref=_VERSION_REF, report=_report(), created=False
    )
    with patch(
        "app.provider_verification_routes.verify_version_against_target",
        return_value=response_model,
    ):
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={"target_ref": "staging", "idempotency_key": "ci-42"},
        )
    assert response.status_code == 200


def test_a_version_that_cannot_be_verified_is_a_200_with_ok_false() -> None:
    response_model = ProviderVerificationResponse(ok=False, version_ref=_VERSION_REF)
    with patch(
        "app.provider_verification_routes.verify_version_against_target",
        return_value=response_model,
    ):
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={"target_ref": "staging"},
        )
    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_an_unknown_target_is_a_404() -> None:
    with patch(
        "app.provider_verification_routes.verify_version_against_target",
        side_effect=TargetValidationError(CODE_NOT_FOUND, "no target 'nope'"),
    ):
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={"target_ref": "nope"},
        )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_NOT_FOUND


def test_a_fixture_carrying_credentials_is_refused_before_the_service_is_called() -> None:
    """The refusal is in the request model, so it costs nothing and cannot be bypassed."""
    with patch(
        "app.provider_verification_routes.verify_version_against_target"
    ) as service:
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={
                "target_ref": "staging",
                "verification": {
                    "allow_mutating": True,
                    "fixtures": [
                        {
                            "operation_key": "POST /pets",
                            "headers": {"Authorization": "Bearer sekrit"},
                        }
                    ],
                },
            },
        )
    assert response.status_code == 422
    assert not service.called


def test_running_a_verification_is_denied_without_permission() -> None:
    with patch(
        "app.provider_verification_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ), patch(
        "app.provider_verification_routes.verify_version_against_target"
    ) as service:
        response = client.post(
            f"{_BASE}/contracts/{_VERSION_REF}/verify-provider",
            json={"target_ref": "staging"},
        )
    assert response.status_code == 403
    assert not service.called


# ---------------------------------------------------------------------------
# GET …/provider-verifications
# ---------------------------------------------------------------------------


def test_the_list_read_forwards_its_filters() -> None:
    with patch(
        "app.provider_verification_routes.list_reports", return_value=[_summary()]
    ) as store:
        response = client.get(
            f"{_BASE}/provider-verifications",
            params={"version_ref": _VERSION_REF, "outcome": "failed", "limit": 5},
        )

    assert response.status_code == 200
    assert response.json()[0]["coverage_percent"] == 50.0
    kwargs = store.call_args.kwargs
    assert kwargs["version_ref"] == _VERSION_REF
    assert kwargs["outcome"] == "failed"
    assert kwargs["limit"] == 5


def test_the_list_read_rejects_an_out_of_range_limit() -> None:
    response = client.get(f"{_BASE}/provider-verifications", params={"limit": 5000})
    assert response.status_code == 422


def test_the_list_read_is_denied_without_permission() -> None:
    with patch(
        "app.provider_verification_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ), patch("app.provider_verification_routes.list_reports") as store:
        response = client.get(f"{_BASE}/provider-verifications")
    assert response.status_code == 403
    assert not store.called


# ---------------------------------------------------------------------------
# GET …/provider-verifications/{id}
# ---------------------------------------------------------------------------


def test_one_report_is_returned_in_full() -> None:
    with patch("app.provider_verification_routes.get_report", return_value=_record()):
        response = client.get(f"{_BASE}/provider-verifications/{_REPORT_ID}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == _REPORT_ID
    assert body["report"]["drift"][0]["operation_key"] == "GET /pets"
    assert body["report"]["drift"][0]["pointer"] == "/id"


def test_a_missing_report_is_a_404() -> None:
    with patch(
        "app.provider_verification_routes.get_report",
        side_effect=ProviderVerificationStoreError(CODE_REPORT_NOT_FOUND, "no such report"),
    ):
        response = client.get(f"{_BASE}/provider-verifications/{_REPORT_ID}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_REPORT_NOT_FOUND


def test_a_report_this_build_cannot_read_is_a_500_not_a_404() -> None:
    """The row exists; blaming the caller would send them looking for a deletion that never was."""
    with patch(
        "app.provider_verification_routes.get_report",
        side_effect=ProviderVerificationStoreError(
            CODE_REPORT_UNREADABLE, "stored in a shape this version cannot read"
        ),
    ):
        response = client.get(f"{_BASE}/provider-verifications/{_REPORT_ID}")
    assert response.status_code == 500
