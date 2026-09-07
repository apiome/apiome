"""Unit tests for provider verification report persistence — CTG-4.3 (#4489).

The ``db`` singleton is replaced wholesale, so nothing here reaches Postgres. What is asserted is
the contract the store owes its callers:

* the stored coverage columns are **derived from the report**, never taken separately, so a summary
  can never contradict the body it summarises;
* a malformed identifier short-circuits before the database is touched;
* a report body this version cannot read is reported rather than returned half-empty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.provider_verification import (
    ConformanceReport,
    CoverageSummary,
    DriftFinding,
    TargetIdentity,
)
from app.provider_verification_store import (
    CODE_REPORT_NOT_FOUND,
    CODE_REPORT_UNREADABLE,
    MAX_LIST_LIMIT,
    ProviderVerificationStoreError,
    ReportActor,
    get_report,
    get_report_for_run,
    latest_report,
    list_reports,
    save_report,
)

_TENANT = "11111111-1111-4111-8111-111111111111"
_RUN = "44444444-4444-4444-8444-444444444444"
_REPORT_ID = "55555555-5555-4555-8555-555555555555"


def _report(*, outcome: str = "failed") -> ConformanceReport:
    """A small but complete conformance report."""
    return ConformanceReport(
        outcome=outcome,
        suite_digest="sha256:" + "b" * 64,
        api_title="Pets",
        api_version="1.0.0",
        api_format="openapi-3.1",
        target=TargetIdentity(
            target_id="22222222-2222-4222-8222-222222222222",
            slug="staging",
            environment="staging",
            network_class="public",
            base_url="https://staging.example.test/v1",
        ),
        started_at=datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 9, 7, 12, 0, 2, tzinfo=timezone.utc),
        duration_ms=2000,
        coverage=CoverageSummary(
            operations_total=4,
            operations_exercised=3,
            operations_passed=2,
            operations_failed=1,
            operations_errored=0,
            operations_skipped=1,
            operations_uncompiled=0,
            uncovered_named=1,
            coverage_percent=75.0,
            cases_total=5,
            cases_passed=3,
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
                expected='"integer"',
                actual='"1"',
                message="type: '1' is not of type 'integer'",
            )
        ],
        mutating_allowed=False,
        fixtures_supplied=0,
    )


def _row(report: ConformanceReport, **overrides: Any) -> Dict[str, Any]:
    """A ``provider_verification_report`` row shaped like RealDictCursor output."""
    coverage = report.coverage
    row = {
        "id": _REPORT_ID,
        "tenant_id": _TENANT,
        "run_id": _RUN,
        "version_ref": "project/petstore/1.0.0",
        "artifact_kind": "project",
        "artifact_id": "66666666-6666-4666-8666-666666666666",
        "artifact_slug": "petstore",
        "version_label": "1.0.0",
        "suite_digest": report.suite_digest,
        "target_id": report.target.target_id,
        "target_slug": report.target.slug,
        "target_environment": report.target.environment,
        "target_network_class": report.target.network_class,
        "target_base_url": report.target.base_url,
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
        "mutating_allowed": report.mutating_allowed,
        "fixture_count": report.fixtures_supplied,
        "report": report.model_dump(mode="json"),
        "created_at": datetime(2026, 9, 7, 12, 0, 3, tzinfo=timezone.utc),
        "created_by": "33333333-3333-4333-8333-333333333333",
        "actor_label": "dev@example.test",
        "actor_kind": "user",
    }
    row.update(overrides)
    return row


@pytest.fixture
def fake_db():
    """A stand-in for the ``db`` singleton, with every accessor the store uses."""
    stub = MagicMock()
    report = _report()
    stub.insert_provider_verification_report.return_value = _row(report)
    stub.get_provider_verification_report.return_value = _row(report)
    stub.get_provider_verification_report_by_run.return_value = _row(report)
    stub.list_provider_verification_reports.return_value = [_row(report)]
    with patch("app.provider_verification_store.db", stub):
        yield stub


# ---------------------------------------------------------------------------
# save_report
# ---------------------------------------------------------------------------


def test_the_stored_columns_are_derived_from_the_report(fake_db) -> None:
    """A summary that could disagree with its own body would be worse than no summary."""
    report = _report()
    save_report(
        _TENANT,
        report,
        run_id=_RUN,
        version_ref="project/petstore/1.0.0",
        source={"kind": "project", "artifact_slug": "petstore", "version_label": "1.0.0"},
        actor=ReportActor(user_id="33333333-3333-4333-8333-333333333333", kind="api_key"),
    )
    written = fake_db.insert_provider_verification_report.call_args.kwargs["report"]

    assert written["tenant_id"] == _TENANT
    assert written["run_id"] == _RUN
    assert written["outcome"] == report.outcome
    assert written["operations_total"] == report.coverage.operations_total
    assert written["operations_exercised"] == report.coverage.operations_exercised
    assert written["coverage_percent"] == report.coverage.coverage_percent
    assert written["drift_count"] == len(report.drift)
    assert written["artifact_slug"] == "petstore"
    assert written["actor_kind"] == "api_key"
    assert written["report"]["outcome"] == report.outcome


def test_a_report_that_cannot_be_written_degrades_rather_than_raising(fake_db) -> None:
    """The verification already happened; a filing failure must not read as a failed check."""
    fake_db.insert_provider_verification_report.return_value = None
    assert (
        save_report(_TENANT, _report(), run_id=_RUN, version_ref="project/petstore/1.0.0")
        is None
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def test_a_stored_report_round_trips(fake_db) -> None:
    record = get_report(_TENANT, _REPORT_ID)
    assert record.id == _REPORT_ID
    assert record.run_id == _RUN
    assert record.report.outcome == "failed"
    assert [item.pointer for item in record.report.drift] == ["/id"]
    assert record.coverage_percent == 75.0


def test_a_missing_report_is_a_stable_refusal(fake_db) -> None:
    fake_db.get_provider_verification_report.return_value = None
    with pytest.raises(ProviderVerificationStoreError) as excinfo:
        get_report(_TENANT, _REPORT_ID)
    assert excinfo.value.code == CODE_REPORT_NOT_FOUND


def test_an_unreadable_body_is_reported_not_silently_emptied(fake_db) -> None:
    """A row written by a newer schema must not come back as a report full of defaults."""
    row = _row(_report())
    row["report"] = {"outcome": "passed"}
    fake_db.get_provider_verification_report.return_value = row
    with pytest.raises(ProviderVerificationStoreError) as excinfo:
        get_report(_TENANT, _REPORT_ID)
    # Not "not found": the report exists, and this build simply cannot read it.
    assert excinfo.value.code == CODE_REPORT_UNREADABLE
    assert excinfo.value.code != CODE_REPORT_NOT_FOUND


def test_a_run_without_a_report_answers_none(fake_db) -> None:
    """An ECA-2.1 contract run produces evidence but no conformance report."""
    fake_db.get_provider_verification_report_by_run.return_value = None
    assert get_report_for_run(_TENANT, _RUN) is None


def test_the_list_read_returns_summaries_without_bodies(fake_db) -> None:
    summaries = list_reports(_TENANT, version_ref="project/petstore/1.0.0")
    assert len(summaries) == 1
    assert summaries[0].outcome == "failed"
    assert not hasattr(summaries[0], "report")


@pytest.mark.parametrize("requested,expected", [(0, 1), (5, 5), (10_000, MAX_LIST_LIMIT)])
def test_the_list_limit_is_clamped(fake_db, requested: int, expected: int) -> None:
    list_reports(_TENANT, limit=requested)
    assert fake_db.list_provider_verification_reports.call_args.kwargs["limit"] == expected


def test_the_deploy_gate_lookup_asks_for_exactly_one(fake_db) -> None:
    """CTG-4.5 asks "is the newest report for this version passing?" — one row, no body parse."""
    summary = latest_report(_TENANT, "project/petstore/1.0.0")
    assert summary is not None
    kwargs = fake_db.list_provider_verification_reports.call_args.kwargs
    assert kwargs["limit"] == 1
    assert kwargs["version_ref"] == "project/petstore/1.0.0"


def test_a_version_never_verified_has_no_latest_report(fake_db) -> None:
    fake_db.list_provider_verification_reports.return_value = []
    assert latest_report(_TENANT, "project/petstore/9.9.9") is None


# ---------------------------------------------------------------------------
# The database guard — a malformed id never reaches Postgres
# ---------------------------------------------------------------------------


def test_non_uuid_identifiers_never_reach_the_database() -> None:
    """The store dispatches; ``database.py`` refuses. Both are asserted here, unpatched."""
    from app.database import db as real_db

    rows: List[Dict[str, Any]] = real_db.list_provider_verification_reports("not-a-uuid")
    assert rows == []
    assert real_db.get_provider_verification_report("nope", "also-nope") is None
    assert real_db.get_provider_verification_report_by_run("nope", "also-nope") is None
    assert real_db.insert_provider_verification_report(report={"tenant_id": "t1"}) is None
