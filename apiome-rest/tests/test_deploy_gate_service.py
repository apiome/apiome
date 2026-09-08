"""Gathering the deploy-gate signals — CTG-4.5 (#4502).

Every store the service reads is patched, so these tests assert the *wiring* decisions rather than
any store's behaviour: which revision is judged, that the stored changelog is reused instead of a
fresh diff, how a schedule is matched to the revision it watches, what happens when a version was
verified by hand but never scheduled, and that one unreadable input costs exactly one signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app.consumer_impact import ConsumerImpactReport
from app.deploy_gate import (
    REASON_CONSUMERS_FORBIDDEN,
    REASON_SIGNAL_UNAVAILABLE,
    SIGNAL_BREAKING,
    SIGNAL_CONSUMERS,
    SIGNAL_LINT,
    SIGNAL_VERIFICATION,
    STATUS_FAIL,
    STATUS_NOT_CONFIGURED,
    STATUS_PASS,
    STATUS_UNKNOWN,
    STATUS_WARN,
)
from app.deploy_gate_service import (
    CODE_NO_PUBLISHED_REVISION,
    CODE_PROJECT_NOT_FOUND,
    CODE_REVISION_NOT_PUBLISHED,
    DeployGateError,
    build_project_gate,
)
from app.verification_schedule import VerificationScheduleRecord

_TENANT = "11111111-1111-4111-8111-111111111111"
_TENANT_SLUG = "acme"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "44444444-4444-4444-8444-444444444444"
_BASELINE = "55555555-5555-4555-8555-555555555555"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

_PROJECT_ROW = {"id": _PROJECT, "slug": "petstore", "name": "Petstore"}
_VERSION_ROW = {
    "id": _REVISION,
    "project_id": _PROJECT,
    "version_id": "1.2.0",
    "published": True,
    "published_at": _NOW - timedelta(hours=1),
    "quality_grade": "A",
    "quality_score": 94,
    "project_slug": "petstore",
}


def _changelog_row(**overrides) -> Dict[str, Any]:
    """A stored CTG-3.1 classification row with one breaking change."""
    row = {
        "published_revision_id": _REVISION,
        "baseline_revision_id": _BASELINE,
        "status": "ready",
        "max_severity": "breaking",
        "error": None,
        "changelog_json": {
            "schemaVersion": "ctg.changelog.v1",
            "counts": {"breaking": 1, "non-breaking": 0, "docs-only": 0, "total": 1},
            "maxSeverity": "breaking",
            "entries": [
                {
                    "severity": "breaking",
                    "pathGroup": "/pets",
                    "pointer": "/paths/~1pets/get/responses/200",
                    "ruleId": "ctg.response_removed",
                    "changeKind": "removed",
                    "summary": "Response 200 removed",
                    "before": {"description": "ok"},
                    "after": None,
                    "unclassified": False,
                }
            ],
        },
    }
    row.update(overrides)
    return row


def _consumer_report(**counts) -> ConsumerImpactReport:
    """A consumer-impact report carrying only the tallies the gate reads."""
    tallies = {
        "consumers_total": 0,
        "consumers_declared": 0,
        "consumers_undeclared": 0,
        "consumers_affected": 0,
        "consumers_breaking": 0,
    }
    tallies.update(counts)
    return ConsumerImpactReport(summary="breaks 0 of 0 consumers", counts=tallies)


def _schedule(**overrides) -> VerificationScheduleRecord:
    """A CTG-4.4 schedule record."""
    fields = {
        "id": "66666666-6666-4666-8666-666666666666",
        "tenant_id": _TENANT,
        "slug": "petstore-staging",
        "name": "Petstore · staging",
        "version_ref": "project/petstore/1.2.0",
        "target_id": "77777777-7777-4777-8777-777777777777",
        "target_slug": "staging",
        "cadence_seconds": 3600,
        "enabled": True,
        "alert_on_recovery": True,
        "last_status": "passed",
        "last_success_at": _NOW - timedelta(minutes=5),
        "freshness_seconds": 300,
    }
    fields.update(overrides)
    return VerificationScheduleRecord(**fields)


class _Report:
    """The subset of a CTG-4.3 conformance summary the gate reads."""

    def __init__(self, outcome: str, created_at: datetime, report_id: str = "r1") -> None:
        self.id = report_id
        self.outcome = outcome
        self.created_at = created_at
        self.coverage_percent = 90.0
        self.target_slug = "staging"
        self.drift_count = 0


def _gate(
    *,
    version_row: Optional[Dict[str, Any]] = _VERSION_ROW,
    changelog: Optional[Dict[str, Any]] = None,
    schedules: Optional[List[VerificationScheduleRecord]] = None,
    reports: Optional[List[Any]] = None,
    passing_reports: Optional[List[Any]] = None,
    consumers: Optional[ConsumerImpactReport] = None,
    consumers_permitted: bool = True,
    changelog_side_effect: Optional[Exception] = None,
    revision_id: Optional[str] = None,
):
    """Run the service with every store patched.

    Args:
        version_row: What ``get_version_by_id`` returns for the gated revision.
        changelog: The stored classification, or ``None`` for "never classified".
        schedules: The tenant's schedules.
        reports: The newest-report fallback (index 0 is returned).
        passing_reports: The newest *passing* report fallback.
        consumers: The consumer-impact report.
        consumers_permitted: Whether the caller may read the registry.
        changelog_side_effect: Raise this instead of returning a changelog.
        revision_id: An explicit revision to gate.

    Returns:
        The gate report.
    """

    def _version(vid, _tenant):
        if vid == _BASELINE:
            return {"id": _BASELINE, "version_id": "1.1.0"}
        return version_row

    listed = [] if reports is None else reports

    def _list_reports(_tenant, **kwargs):
        if kwargs.get("outcome") == "passed":
            return passing_reports or []
        return listed

    with patch(
        "app.deploy_gate_service.db.get_project_by_id", return_value=_PROJECT_ROW
    ), patch("app.deploy_gate_service.db.get_project_by_slug", return_value=_PROJECT_ROW), patch(
        "app.deploy_gate_service.db.list_version_changelogs_for_project",
        return_value=[{"published_revision_id": _REVISION}] if version_row else [],
    ), patch(
        "app.deploy_gate_service.db.get_version_by_id", side_effect=_version
    ), patch(
        "app.deploy_gate_service.db.get_version_changelog",
        side_effect=changelog_side_effect,
        return_value=changelog,
    ), patch(
        "app.deploy_gate_service.list_schedules", return_value=schedules or []
    ), patch(
        "app.deploy_gate_service.latest_report_for_project",
        return_value=listed[0] if listed else None,
    ), patch(
        "app.deploy_gate_service.list_reports", side_effect=_list_reports
    ), patch(
        "app.deploy_gate_service.consumer_impact_for_diff",
        return_value=consumers if consumers is not None else _consumer_report(),
    ):
        return build_project_gate(
            tenant_id=_TENANT,
            tenant_slug=_TENANT_SLUG,
            project_ref=_PROJECT,
            revision_id=revision_id,
            consumers_permitted=consumers_permitted,
            now=_NOW,
        )


def _signal(report, name):
    """The named signal from a gate report."""
    return next(s for s in report.signals if s.signal == name)


# ---------------------------------------------------------------------------------------------
# Subject resolution
# ---------------------------------------------------------------------------------------------


def test_an_unknown_project_refuses_with_a_stable_code():
    """A pipeline branches on the code; the prose is for a human reading the log."""
    with patch("app.deploy_gate_service.db.get_project_by_id", return_value=None), patch(
        "app.deploy_gate_service.db.get_project_by_slug", return_value=None
    ):
        with pytest.raises(DeployGateError) as excinfo:
            build_project_gate(
                tenant_id=_TENANT, tenant_slug=_TENANT_SLUG, project_ref="nope"
            )
    assert excinfo.value.code == CODE_PROJECT_NOT_FOUND
    assert excinfo.value.status_code == 404


def test_a_project_with_nothing_published_has_nothing_to_promote():
    """409, not 404: the project exists, it is just not in a state that can be gated."""
    with patch("app.deploy_gate_service.db.get_project_by_id", return_value=_PROJECT_ROW), patch(
        "app.deploy_gate_service.db.list_version_changelogs_for_project", return_value=[]
    ):
        with pytest.raises(DeployGateError) as excinfo:
            build_project_gate(
                tenant_id=_TENANT, tenant_slug=_TENANT_SLUG, project_ref=_PROJECT
            )
    assert excinfo.value.code == CODE_NO_PUBLISHED_REVISION
    assert excinfo.value.status_code == 409


def test_a_draft_revision_is_refused_rather_than_judged():
    """A deploy gate judges what was published; a draft has no publish to classify."""
    with patch("app.deploy_gate_service.db.get_project_by_id", return_value=_PROJECT_ROW), patch(
        "app.deploy_gate_service.db.get_version_by_id",
        return_value={**_VERSION_ROW, "published": False},
    ):
        with pytest.raises(DeployGateError) as excinfo:
            build_project_gate(
                tenant_id=_TENANT,
                tenant_slug=_TENANT_SLUG,
                project_ref=_PROJECT,
                revision_id=_REVISION,
            )
    assert excinfo.value.code == CODE_REVISION_NOT_PUBLISHED
    assert excinfo.value.status_code == 400


def test_the_default_subject_is_the_newest_published_revision():
    """"Can I promote this?" means the thing that was just published."""
    report = _gate(changelog=_changelog_row())
    assert report.revision_id == _REVISION
    assert report.version_ref == "project/petstore/1.2.0"
    assert report.project_slug == "petstore"


# ---------------------------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------------------------


def test_the_lint_grade_is_read_from_the_revision_and_never_recomputed():
    """#5259's architecture: the list path and the gate both read stored reports."""
    report = _gate(changelog=_changelog_row())
    lint = _signal(report, SIGNAL_LINT)
    assert lint.status == STATUS_PASS
    assert lint.data["grade"] == "A"
    assert lint.data["score"] == 94
    assert lint.link == f"/v1/versions/{_TENANT_SLUG}/{_PROJECT}/{_REVISION}/lint"


def test_a_revision_with_no_stored_grade_reports_not_configured():
    """A gate that re-linted here would make the cheapest CI call the most expensive one."""
    report = _gate(version_row={**_VERSION_ROW, "quality_grade": None, "quality_score": None})
    assert _signal(report, SIGNAL_LINT).status == STATUS_NOT_CONFIGURED


# ---------------------------------------------------------------------------------------------
# Breaking and consumers share one read of the changelog
# ---------------------------------------------------------------------------------------------


def test_the_breaking_signal_reads_the_stored_classification_and_names_the_baseline():
    """CTG-3.1 already answered this at publish; the gate reports, it does not re-diff."""
    report = _gate(changelog=_changelog_row())
    breaking = _signal(report, SIGNAL_BREAKING)
    assert breaking.status == STATUS_FAIL
    assert "1.1.0" in breaking.detail
    assert breaking.data["counts"]["breaking"] == 1


def test_the_consumer_signal_is_fed_the_rehydrated_stored_changelog():
    """The entry and the classified change carry the same fields, so no re-diff is needed."""
    with patch(
        "app.deploy_gate_service.db.get_project_by_id", return_value=_PROJECT_ROW
    ), patch(
        "app.deploy_gate_service.db.list_version_changelogs_for_project",
        return_value=[{"published_revision_id": _REVISION}],
    ), patch(
        "app.deploy_gate_service.db.get_version_by_id",
        side_effect=lambda vid, _t: {"id": _BASELINE, "version_id": "1.1.0"}
        if vid == _BASELINE
        else _VERSION_ROW,
    ), patch(
        "app.deploy_gate_service.db.get_version_changelog", return_value=_changelog_row()
    ), patch(
        "app.deploy_gate_service.list_schedules", return_value=[]
    ), patch(
        "app.deploy_gate_service.latest_report_for_project", return_value=None
    ), patch(
        "app.deploy_gate_service.consumer_impact_for_diff",
        return_value=_consumer_report(
            consumers_total=7, consumers_declared=7, consumers_affected=2, consumers_breaking=2
        ),
    ) as impact:
        report = build_project_gate(
            tenant_id=_TENANT,
            tenant_slug=_TENANT_SLUG,
            project_ref=_PROJECT,
            now=_NOW,
        )
    diff = impact.call_args.args[2]
    assert [change.pointer for change in diff.changes] == [
        "/paths/~1pets/get/responses/200"
    ]
    assert diff.changes[0].severity == "breaking"
    assert diff.max_severity == "breaking"
    assert impact.call_args.kwargs["base_version_id"] == _BASELINE
    assert _signal(report, SIGNAL_CONSUMERS).status == STATUS_FAIL


def test_a_caller_without_registry_access_gets_unknown_not_a_silent_pass():
    """The registry is not leaked, and its absence is not reported as "nobody is broken"."""
    report = _gate(changelog=_changelog_row(), consumers_permitted=False)
    consumers = _signal(report, SIGNAL_CONSUMERS)
    assert (consumers.status, consumers.reason) == (STATUS_UNKNOWN, REASON_CONSUMERS_FORBIDDEN)


def test_a_revision_with_no_classification_leaves_both_dependent_signals_unjudged():
    """Neither is "passing": one has nothing stored, the other has no changes to attribute."""
    report = _gate(changelog=None)
    assert _signal(report, SIGNAL_BREAKING).status == STATUS_NOT_CONFIGURED
    assert _signal(report, SIGNAL_CONSUMERS).status == STATUS_NOT_CONFIGURED
    assert report.status == STATUS_PASS
    assert report.evaluated_signals == 1  # lint only


def test_an_unreadable_changelog_costs_exactly_the_two_signals_that_need_it():
    """One store fault must not stop every pipeline in the tenant."""
    report = _gate(changelog_side_effect=RuntimeError("boom"), schedules=[_schedule()])
    assert _signal(report, SIGNAL_BREAKING).reason == REASON_SIGNAL_UNAVAILABLE
    assert _signal(report, SIGNAL_CONSUMERS).reason == REASON_SIGNAL_UNAVAILABLE
    assert _signal(report, SIGNAL_LINT).status == STATUS_PASS
    assert _signal(report, SIGNAL_VERIFICATION).status == STATUS_PASS
    assert report.counts[STATUS_UNKNOWN] == 2


# ---------------------------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version_ref",
    [
        "project/petstore/1.2.0",
        f"project/petstore/{_REVISION}",
        f"project/{_PROJECT}/1.2.0",
        "project/petstore/latest",
        "project/PETSTORE/LATEST",
    ],
)
def test_a_schedule_is_matched_however_its_reference_was_spelled(version_ref):
    """One instruction, five spellings — a gate that matched only one would report `never run`."""
    report = _gate(
        changelog=_changelog_row(), schedules=[_schedule(version_ref=version_ref)]
    )
    verification = _signal(report, SIGNAL_VERIFICATION)
    assert verification.status == STATUS_PASS
    assert verification.data["source"] == "schedule"


@pytest.mark.parametrize(
    "version_ref",
    ["project/other/1.2.0", "project/petstore/9.9.9", "catalog/petstore/1.2.0", "nonsense"],
)
def test_a_schedule_for_something_else_does_not_vouch_for_this_revision(version_ref):
    """Borrowing another version's freshness would be the most dangerous bug in this file."""
    report = _gate(changelog=_changelog_row(), schedules=[_schedule(version_ref=version_ref)])
    assert _signal(report, SIGNAL_VERIFICATION).status == STATUS_NOT_CONFIGURED


def test_freshness_is_the_most_recent_success_and_the_status_is_the_worst_run():
    """Any schedule verifying clean is evidence; any schedule failing is evidence too."""
    report = _gate(
        changelog=_changelog_row(),
        schedules=[
            _schedule(slug="staging", freshness_seconds=300, last_status="passed"),
            _schedule(
                id="88888888-8888-4888-8888-888888888888",
                slug="prod",
                freshness_seconds=90_000,
                last_status="failed",
            ),
        ],
    )
    verification = _signal(report, SIGNAL_VERIFICATION)
    assert verification.status == STATUS_FAIL
    assert verification.data["freshnessSeconds"] == 300
    assert verification.data["lastStatus"] == "failed"
    assert verification.data["scheduleCount"] == 2


def test_a_hand_run_verification_still_counts_when_nothing_schedules_the_version():
    """CTG-4.4 is the freshness source, but a manual CTG-4.3 run is not no evidence."""
    report = _gate(
        changelog=_changelog_row(),
        schedules=[],
        reports=[_Report("passed", _NOW - timedelta(minutes=10))],
        passing_reports=[_Report("passed", _NOW - timedelta(minutes=10))],
    )
    verification = _signal(report, SIGNAL_VERIFICATION)
    assert verification.status == STATUS_PASS
    assert verification.data["source"] == "report"
    assert verification.data["freshnessSeconds"] == pytest.approx(600, abs=2)


def test_a_failing_report_does_not_become_the_freshness_anchor():
    """Taking a failure's age as freshness would report a broken deployment as recently verified."""
    report = _gate(
        changelog=_changelog_row(),
        schedules=[],
        reports=[_Report("failed", _NOW - timedelta(minutes=1), "recent-failure")],
        passing_reports=[_Report("passed", _NOW - timedelta(days=30), "old-success")],
    )
    verification = _signal(report, SIGNAL_VERIFICATION)
    assert verification.status == STATUS_FAIL
    assert verification.data["reportOutcome"] == "failed"
    assert verification.data["freshnessSeconds"] > 86_400


def test_a_project_that_was_never_verified_reports_not_configured():
    """Nothing scheduled it and nothing ran it — the signal is absent, not failing."""
    report = _gate(changelog=_changelog_row(), schedules=[], reports=[])
    assert _signal(report, SIGNAL_VERIFICATION).status == STATUS_NOT_CONFIGURED


def test_a_stale_schedule_warns_before_it_fails():
    """The two staleness rungs applied to a real schedule record."""
    report = _gate(
        changelog=_changelog_row(status="initial", max_severity=None),
        schedules=[_schedule(freshness_seconds=100_000, last_status="passed")],
    )
    assert _signal(report, SIGNAL_VERIFICATION).status == STATUS_WARN
    assert report.status == STATUS_WARN
