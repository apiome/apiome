"""Persistence for provider verification reports — CTG-4.3 (#4489).

:mod:`app.provider_verification` decides *what* a conformance report says; this module is the only
place one is written or read, so V252's guarantees are applied once rather than at each call site.

**A report is written whole, once, beside its evidence.** The row carries the coverage numbers and
the verdict as columns and the full report as JSONB, and V252 rejects every UPDATE. There is no
path that edits a stored report — the only reason to edit one would be to make a red deployment
look green.

**A report is never invented for a run that does not exist.** The composite foreign key ties
``(run_id, tenant_id)`` to the evidence run's own key, so a database that accepted the insert has
already proved the run exists and belongs to this tenant.

**Nothing reaches the database on a malformed id.** Every accessor short-circuits on a non-UUID
tenant, report, or run id and returns the empty value for its type, so a caller with a bad handle
gets a clean "not found" rather than a driver error.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from .database import db
from .provider_verification import ConformanceReport

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_REPORT_NOT_FOUND",
    "CODE_REPORT_UNREADABLE",
    "MAX_LIST_LIMIT",
    "ConformanceReportRecord",
    "ConformanceReportSummary",
    "ProviderVerificationStoreError",
    "ReportActor",
    "get_report",
    "get_report_for_run",
    "latest_report",
    "latest_report_for_project",
    "list_reports",
    "record_from_row",
    "save_report",
    "summary_from_row",
]

#: Ceiling on a list read. A gate asks for the newest few; nobody needs a tenant's whole history.
MAX_LIST_LIMIT = 200

#: Stable code for "no such report in this tenant".
CODE_REPORT_NOT_FOUND = "provider-verification-report-not-found"

#: Stable code for a stored row whose report body this version of the code cannot read — a row
#: written by a newer schema. Distinct from "not found" because the caller did nothing wrong: the
#: report exists, and returning it as missing would send somebody looking for a deletion that never
#: happened.
CODE_REPORT_UNREADABLE = "provider-verification-report-unreadable"


class ProviderVerificationStoreError(ValueError):
    """A store operation refused, with a stable code a route can map to a status.

    Attributes:
        code: The stable code (:data:`CODE_REPORT_NOT_FOUND`).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReportActor(BaseModel):
    """Who ran the verification, as the report records them."""

    model_config = ConfigDict(extra="forbid")

    user_id: Optional[str] = Field(default=None, description="User id, when a person ran it.")
    label: Optional[str] = Field(default=None, description="Email or name at the time.")
    kind: str = Field(default="user", description="`user`, `api_key`, or `system`.")


class ConformanceReportSummary(BaseModel):
    """A report without its detail — what a list read returns.

    Every field here is a stored column rather than a JSON lookup, which is what lets CTG-4.4 and
    CTG-4.5 ask "did the newest report for this version pass, and how much did it cover?" without
    opening a single report body.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Report id.")
    tenant_id: str = Field(description="Tenant that owns it.")
    run_id: str = Field(description="The ECA-1.3 evidence run this report summarises.")
    version_ref: str = Field(description="Version reference that was verified.")
    artifact_kind: Optional[str] = Field(default=None, description="`project` or `catalog`.")
    artifact_id: Optional[str] = Field(default=None, description="Artifact id.")
    artifact_slug: Optional[str] = Field(default=None, description="Artifact slug.")
    version_label: Optional[str] = Field(default=None, description="Resolved version label.")
    suite_digest: str = Field(description="Digest of the executed suite.")
    target_id: Optional[str] = Field(default=None, description="Target, when it still exists.")
    target_slug: str = Field(description="Target handle at run time.")
    target_environment: str = Field(description="Environment class at run time.")
    target_network_class: str = Field(default="public", description="`public` or `private`.")
    target_base_url: str = Field(description="Base URL at run time.")
    outcome: str = Field(description="`passed`, `failed`, or `errored`.")
    operations_total: int = Field(description="Operations in the specification, compiled or not.")
    operations_exercised: int = Field(description="Operations that received a request.")
    operations_passed: int = Field(description="Exercised operations with no drift.")
    operations_failed: int = Field(description="Exercised operations that drifted.")
    operations_errored: int = Field(description="Exercised operations that never answered.")
    operations_skipped: int = Field(description="Compiled operations nothing was sent for.")
    operations_uncompiled: int = Field(description="Operations the compiler could not compile.")
    coverage_percent: float = Field(description="Exercised over total, as a percentage.")
    cases_total: int = Field(description="Cases accounted for.")
    cases_passed: int = Field(description="Cases that passed.")
    cases_failed: int = Field(description="Cases that drifted.")
    cases_errored: int = Field(description="Cases that never answered.")
    cases_skipped: int = Field(description="Cases deliberately not sent.")
    drift_count: int = Field(description="Disagreements observed.")
    mutating_allowed: bool = Field(description="Whether the run opted in to mutating methods.")
    fixture_count: int = Field(description="Fixtures the caller supplied.")
    created_at: Optional[datetime] = Field(default=None, description="When it was written.")
    created_by: Optional[str] = Field(default=None, description="User who ran it.")
    actor_label: Optional[str] = Field(default=None, description="Actor label at the time.")
    actor_kind: str = Field(default="user", description="`user`, `api_key`, or `system`.")


class ConformanceReportRecord(ConformanceReportSummary):
    """A report with its detail — per-operation verdicts, drift, and uncovered operations."""

    report: ConformanceReport = Field(description="The stored conformance report.")


def _summary_fields(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Adapt a database row into summary keyword arguments.

    Args:
        row: A ``provider_verification_report`` row.

    Returns:
        Keyword arguments for :class:`ConformanceReportSummary`.
    """
    return {
        "id": str(row.get("id")),
        "tenant_id": str(row.get("tenant_id")),
        "run_id": str(row.get("run_id")),
        "version_ref": str(row.get("version_ref") or ""),
        "artifact_kind": row.get("artifact_kind"),
        "artifact_id": row.get("artifact_id"),
        "artifact_slug": row.get("artifact_slug"),
        "version_label": row.get("version_label"),
        "suite_digest": str(row.get("suite_digest") or ""),
        "target_id": row.get("target_id"),
        "target_slug": str(row.get("target_slug") or ""),
        "target_environment": str(row.get("target_environment") or ""),
        "target_network_class": str(row.get("target_network_class") or "public"),
        "target_base_url": str(row.get("target_base_url") or ""),
        "outcome": str(row.get("outcome") or ""),
        "operations_total": int(row.get("operations_total") or 0),
        "operations_exercised": int(row.get("operations_exercised") or 0),
        "operations_passed": int(row.get("operations_passed") or 0),
        "operations_failed": int(row.get("operations_failed") or 0),
        "operations_errored": int(row.get("operations_errored") or 0),
        "operations_skipped": int(row.get("operations_skipped") or 0),
        "operations_uncompiled": int(row.get("operations_uncompiled") or 0),
        "coverage_percent": float(row.get("coverage_percent") or 0.0),
        "cases_total": int(row.get("cases_total") or 0),
        "cases_passed": int(row.get("cases_passed") or 0),
        "cases_failed": int(row.get("cases_failed") or 0),
        "cases_errored": int(row.get("cases_errored") or 0),
        "cases_skipped": int(row.get("cases_skipped") or 0),
        "drift_count": int(row.get("drift_count") or 0),
        "mutating_allowed": bool(row.get("mutating_allowed")),
        "fixture_count": int(row.get("fixture_count") or 0),
        "created_at": row.get("created_at"),
        "created_by": row.get("created_by"),
        "actor_label": row.get("actor_label"),
        "actor_kind": str(row.get("actor_kind") or "user"),
    }


def summary_from_row(row: Mapping[str, Any]) -> ConformanceReportSummary:
    """Adapt a database row into a list-read summary.

    Args:
        row: A ``provider_verification_report`` row.

    Returns:
        The summary.
    """
    return ConformanceReportSummary(**_summary_fields(row))


def record_from_row(row: Mapping[str, Any]) -> ConformanceReportRecord:
    """Adapt a database row into the full record, parsing the stored report body.

    Args:
        row: A ``provider_verification_report`` row.

    Returns:
        The record.

    Raises:
        ProviderVerificationStoreError: ``provider-verification-report-unreadable`` when the stored
            body cannot be read as a report — which means the row was written by a newer schema
            version. Reported rather than silently returned half-empty: a report full of defaults
            would read as "this deployment was checked and nothing was wrong".
    """
    body = row.get("report")
    payload = dict(body) if isinstance(body, Mapping) else {}
    try:
        report = ConformanceReport.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - surfaced as a stable store error
        raise ProviderVerificationStoreError(
            CODE_REPORT_UNREADABLE,
            f"report '{row.get('id')}' is stored in a shape this version cannot read",
        ) from exc
    return ConformanceReportRecord(**_summary_fields(row), report=report)


def save_report(
    tenant_id: str,
    report: ConformanceReport,
    *,
    run_id: str,
    version_ref: str,
    source: Optional[Mapping[str, Any]] = None,
    actor: Optional[ReportActor] = None,
) -> Optional[ConformanceReportRecord]:
    """Persist one conformance report beside the evidence run it summarises.

    The coverage counts and the verdict are written as columns *derived from the report itself*,
    never taken separately from the caller, so a stored summary can never contradict the body it
    summarises.

    Args:
        tenant_id: The caller's tenant.
        report: The report to store.
        run_id: The ECA-1.3 run this report reads.
        version_ref: The version reference that was verified.
        source: The manifest's provenance block, for the artifact columns.
        actor: Who ran the verification.

    Returns:
        The stored record, or ``None`` when the write could not be attempted (a non-UUID tenant or
        run id) — a caller still has the in-memory report, so a storage gap degrades the audit
        trail rather than the answer.
    """
    provenance = dict(source or {})
    coverage = report.coverage
    who = actor or ReportActor()
    row = db.insert_provider_verification_report(
        report={
            "tenant_id": tenant_id,
            "run_id": run_id,
            "version_ref": version_ref,
            "artifact_kind": provenance.get("kind"),
            "artifact_id": provenance.get("artifact_id"),
            "artifact_slug": provenance.get("artifact_slug"),
            "version_label": provenance.get("version_label"),
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
            "created_by": who.user_id,
            "actor_label": who.label,
            "actor_kind": who.kind,
        }
    )
    if row is None:
        logger.info(
            "provider verification report not stored for run %s: identifiers are not UUIDs",
            run_id,
        )
        return None
    return record_from_row(row)


def get_report(tenant_id: str, report_id: str) -> ConformanceReportRecord:
    """Read one conformance report in full.

    Args:
        tenant_id: The caller's tenant.
        report_id: The report id.

    Returns:
        The record.

    Raises:
        ProviderVerificationStoreError: ``provider-verification-report-not-found`` when nothing
            matches in this tenant.
    """
    row = db.get_provider_verification_report(report_id, tenant_id)
    if row is None:
        raise ProviderVerificationStoreError(
            CODE_REPORT_NOT_FOUND,
            f"no provider verification report '{report_id}' in this tenant",
        )
    return record_from_row(row)


def get_report_for_run(tenant_id: str, run_id: str) -> Optional[ConformanceReportRecord]:
    """Read the report written for one evidence run, if there is one.

    Args:
        tenant_id: The caller's tenant.
        run_id: The evidence run id.

    Returns:
        The record, or ``None`` when that run has no report — an ECA-2.1 contract run, for
        instance, produces evidence but no conformance report.
    """
    row = db.get_provider_verification_report_by_run(run_id, tenant_id)
    return record_from_row(row) if row is not None else None


def list_reports(
    tenant_id: str,
    *,
    version_ref: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: Optional[str] = None,
    artifact_kind: Optional[str] = None,
    artifact_id: Optional[str] = None,
    version_label: Optional[str] = None,
    limit: int = 50,
) -> List[ConformanceReportSummary]:
    """A tenant's conformance reports, newest first, without their detail.

    Args:
        tenant_id: The caller's tenant.
        version_ref: Restrict to one version reference, exactly as it was requested.
        target_id: Restrict to one verification target.
        outcome: Restrict to one verdict.
        artifact_kind: Restrict to ``project`` or ``catalog``, as resolved at run time.
        artifact_id: Restrict to one artifact id, as resolved at run time.
        version_label: Restrict to one resolved version label.
        limit: Maximum reports (clamped to 1..200).

    Returns:
        The summaries; empty when nothing matches.
    """
    rows = db.list_provider_verification_reports(
        tenant_id,
        version_ref=version_ref,
        target_id=target_id,
        outcome=outcome,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
        version_label=version_label,
        limit=max(1, min(int(limit), MAX_LIST_LIMIT)),
    )
    return [summary_from_row(row) for row in rows]


def latest_report(
    tenant_id: str, version_ref: str, *, target_id: Optional[str] = None
) -> Optional[ConformanceReportSummary]:
    """The newest conformance report for one version — the deploy-gate lookup.

    This is the call CTG-4.4 (scheduled verification) and CTG-4.5 (deploy gating) make: *is there
    recent evidence that this version's deployment still matches its contract?* It reads the
    summary only, so answering it never parses a report body.

    Args:
        tenant_id: The caller's tenant.
        version_ref: The version reference.
        target_id: Restrict to one deployment, when the gate cares which.

    Returns:
        The newest matching summary, or ``None`` when the version has never been verified.
    """
    reports = list_reports(
        tenant_id, version_ref=version_ref, target_id=target_id, limit=1
    )
    return reports[0] if reports else None


def latest_report_for_project(
    tenant_id: str,
    project_id: str,
    *,
    version_label: Optional[str] = None,
    target_id: Optional[str] = None,
) -> Optional[ConformanceReportSummary]:
    """The newest conformance report for a project, however its version reference was spelled.

    :func:`latest_report` matches the reference string a run was *requested* with, which is exact
    but brittle for a caller that starts from a project id: the same deployment may have been
    verified as ``project/petstore/1.0.0`` on Monday and ``project/petstore/latest`` on Tuesday.
    The deploy gate (CTG-4.5) asks the question the other way round — "has anything verified *this
    project* recently?" — so it reads the coordinates CTG-4.3 resolved at run time, which V254
    indexes.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project whose evidence to look for.
        version_label: Narrow to one published version label, when the gate names one.
        target_id: Restrict to one deployment.

    Returns:
        The newest matching summary, or ``None`` when this project has never been verified.
    """
    reports = list_reports(
        tenant_id,
        artifact_kind="project",
        artifact_id=project_id,
        version_label=version_label,
        target_id=target_id,
        limit=1,
    )
    return reports[0] if reports else None
