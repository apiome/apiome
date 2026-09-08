"""Gathering the four deploy-gate signals — CTG-4.5 (#4502).

:mod:`app.deploy_gate` holds the rules and knows nothing about storage. This module is the other
half: it reads the four signals from where each of them already lives, and hands the facts to those
rules. Nothing here computes a verdict, and nothing here re-derives a signal that some earlier
ticket already stored.

That last point is the whole design. Every signal is a **read**:

============  ============================================================================
Signal        Where it is read from
============  ============================================================================
lint          ``versions.quality_grade`` / ``quality_score`` — the report #5259 captures when
              a revision changes. The gate never re-lints: a deploy gate that recomputed the
              score would make the cheapest call in a pipeline the most expensive one.
breaking      ``version_changelogs`` — the classification CTG-3.1 (#4475) writes at publish.
consumers     CTG-4.2's ``consumer_impact_for_diff`` (#4480), fed the *stored* changelog
              rehydrated into a classified diff. The two carry identical fields, so the
              intersection runs without re-diffing two documents.
verification  CTG-4.4's schedules (#4501) for freshness, falling back to CTG-4.3's reports
              (#4489) when a version was verified by hand but never scheduled.
============  ============================================================================

**Every signal fails soft, on its own.** Each is gathered inside its own guard: a store that is
unreachable, a stored payload this release cannot parse, or a project whose consumers cannot be
read costs *that* signal — reported ``unknown`` — and nothing else. A CD gate that returned ``500``
because one of four inputs was briefly unavailable would stop every pipeline in the tenant, which
is a worse failure than answering with three signals and saying so.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .change_taxonomy import ClassifiedChange, ClassifiedDiff
from .consumer_impact_service import consumer_impact_for_diff
from .database import db
from .deploy_gate import (
    REASON_CONSUMERS_FORBIDDEN,
    REASON_CONSUMERS_NO_CHANGELOG,
    REASON_SIGNAL_UNAVAILABLE,
    SIGNAL_BREAKING,
    SIGNAL_CONSUMERS,
    SIGNAL_LINT,
    SIGNAL_VERIFICATION,
    STATUS_NOT_CONFIGURED,
    STATUS_UNKNOWN,
    DeployGatePolicyOut,
    DeployGateReport,
    GateSignal,
    build_gate_report,
    evaluate_breaking,
    evaluate_consumers,
    evaluate_lint,
    evaluate_verification,
    unavailable_signal,
)
from .deploy_gate_store import load_policy
from .provider_verification_store import (
    ConformanceReportSummary,
    latest_report_for_project,
    list_reports,
)
from .revision_deprecation import is_uuid_string
from .schema_reference import (
    KIND_PROJECT,
    LATEST_VERSION_TOKEN,
    SchemaReferenceError,
    parse_schema_reference,
)
from .verification_schedule import VerificationScheduleRecord
from .verification_schedule_store import list_schedules

logger = logging.getLogger(__name__)

__all__ = [
    "CODE_NO_PUBLISHED_REVISION",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_REVISION_NOT_FOUND",
    "CODE_REVISION_NOT_PUBLISHED",
    "DeployGateError",
    "build_project_gate",
    "resolve_project",
]

#: Stable refusal codes. A pipeline branches on these without parsing prose.
CODE_PROJECT_NOT_FOUND = "gate-project-not-found"
CODE_REVISION_NOT_FOUND = "gate-revision-not-found"
CODE_REVISION_NOT_PUBLISHED = "gate-revision-not-published"
CODE_NO_PUBLISHED_REVISION = "gate-no-published-revision"

#: How many of a tenant's schedules are scanned when matching this project's. The match is a
#: reference comparison rather than SQL (a schedule stores the reference *string* it was defined
#: with, which may spell the project as a slug or an id and the version as a label or ``latest``),
#: so the scan is bounded here instead.
_SCHEDULE_SCAN_LIMIT = 200

#: How many matched schedules are enumerated in the response payload.
_MAX_SCHEDULES_REPORTED = 10

#: Verification outcomes, least to most alarming. ``None`` (never ran) carries no information and
#: is skipped rather than ranked.
_RUN_STATUS_RANK: Dict[str, int] = {"passed": 0, "failed": 1, "errored": 2}


class DeployGateError(Exception):
    """The gate cannot be computed for the requested subject.

    Attributes:
        code: One of the ``CODE_*`` constants.
        status_code: The HTTP status the route should surface.
    """

    def __init__(self, code: str, message: str, *, status_code: int = 404) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# -------------------------------------------------------------------------------------------
# Subject resolution
# -------------------------------------------------------------------------------------------


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project by id or slug within the tenant.

    Shared with the policy routes so "what does a project reference mean on the gate surface" is
    answered in exactly one place: a reference that names a project for the verdict must name the
    same project for the thresholds that verdict was judged under.

    Args:
        tenant_id: The caller's tenant.
        project_ref: A project UUID or slug.

    Returns:
        The project row.

    Raises:
        DeployGateError: 404 when nothing in this tenant answers to the reference.
    """
    ref = (project_ref or "").strip()
    row: Optional[Dict[str, Any]] = None
    if is_uuid_string(ref):
        row = db.get_project_by_id(ref, tenant_id)
    if row is None and ref:
        row = db.get_project_by_slug(ref, tenant_id)
    if row is None:
        raise DeployGateError(
            CODE_PROJECT_NOT_FOUND,
            f"No project named {project_ref!r} is visible in this tenant.",
        )
    return row


def _resolve_revision(
    tenant_id: str, project_id: str, revision_id: Optional[str]
) -> Dict[str, Any]:
    """Resolve the published revision the gate judges.

    Without ``revision_id`` this is the project's newest published revision, which is what "can I
    promote this?" means in a pipeline that just published. The changelog list read supplies it
    directly: it is already ordered newest publish first and already restricted to published rows.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        revision_id: An explicit published revision, or ``None`` for the newest.

    Returns:
        The version row.

    Raises:
        DeployGateError: 404 when the revision is unknown, 400 when it is not published, 409 when
            the project has nothing published to gate.
    """
    if revision_id:
        if not is_uuid_string(str(revision_id)):
            raise DeployGateError(
                CODE_REVISION_NOT_FOUND, f"Revision not found: {revision_id}"
            )
        version = db.get_version_by_id(str(revision_id), tenant_id)
        if not version or str(version.get("project_id")) != str(project_id):
            raise DeployGateError(
                CODE_REVISION_NOT_FOUND,
                f"Revision {revision_id} was not found in this project.",
            )
        if not version.get("published"):
            raise DeployGateError(
                CODE_REVISION_NOT_PUBLISHED,
                "A deploy gate judges a published revision; this one is still a draft.",
                status_code=400,
            )
        return version

    rows = db.list_version_changelogs_for_project(project_id, tenant_id, limit=1)
    if not rows:
        raise DeployGateError(
            CODE_NO_PUBLISHED_REVISION,
            "This project has no published revision, so there is nothing to promote.",
            status_code=409,
        )
    newest = db.get_version_by_id(str(rows[0]["published_revision_id"]), tenant_id)
    if not newest:
        raise DeployGateError(
            CODE_NO_PUBLISHED_REVISION,
            "This project has no published revision, so there is nothing to promote.",
            status_code=409,
        )
    return newest


# -------------------------------------------------------------------------------------------
# Signal gathering
# -------------------------------------------------------------------------------------------


def _lint_signal(
    version: Mapping[str, Any], *, thresholds: Any, link: Optional[str]
) -> GateSignal:
    """Read the stored lint grade off the revision and judge it.

    Args:
        version: The version row (carries ``quality_grade`` / ``quality_score``).
        thresholds: The lint rungs in force.
        link: Path to the full lint report.

    Returns:
        The judged signal.
    """
    grade = version.get("quality_grade")
    score = version.get("quality_score")
    return evaluate_lint(
        grade=str(grade).strip().upper() if grade else None,
        score=int(score) if isinstance(score, (int, float)) else None,
        thresholds=thresholds,
        link=link,
    )


def _changelog_row(
    tenant_id: str, project_id: str, revision_id: str
) -> Optional[Dict[str, Any]]:
    """Read the CTG-3.1 classification row for a revision, or ``None`` when there is none.

    Args:
        tenant_id: The caller's tenant.
        project_id: Owning project.
        revision_id: The published revision.

    Returns:
        The row, or ``None``.
    """
    return db.get_version_changelog(revision_id, tenant_id, project_id)


def _baseline_label(tenant_id: str, row: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Resolve the version label of a changelog row's baseline, for the detail line.

    Args:
        tenant_id: The caller's tenant.
        row: The changelog row.

    Returns:
        The baseline's label, or ``None`` when there is no baseline or it is gone.
    """
    baseline_id = (row or {}).get("baseline_revision_id")
    if not baseline_id:
        return None
    baseline = db.get_version_by_id(str(baseline_id), tenant_id)
    return baseline.get("version_id") if baseline else None


def _breaking_signal(
    row: Optional[Mapping[str, Any]],
    *,
    baseline_version_label: Optional[str],
    thresholds: Any,
    link: Optional[str],
) -> GateSignal:
    """Judge the stored breaking classification.

    Args:
        row: The ``version_changelogs`` row, or ``None`` when none is stored.
        baseline_version_label: Label of the revision it was compared against.
        thresholds: The breaking rungs in force.
        link: Path to the stored changelog.

    Returns:
        The judged signal.
    """
    changelog = (row or {}).get("changelog_json")
    counts = changelog.get("counts") if isinstance(changelog, Mapping) else None
    return evaluate_breaking(
        status=str(row["status"]) if row and row.get("status") else None,
        max_severity=(row or {}).get("max_severity"),
        counts=counts if isinstance(counts, Mapping) else None,
        baseline_version_label=baseline_version_label,
        thresholds=thresholds,
        link=link,
    )


def _diff_from_changelog(changelog: Mapping[str, Any]) -> ClassifiedDiff:
    """Rehydrate a stored ``ctg.changelog.v1`` payload into the classified diff it came from.

    A changelog entry and a classified change carry the same fields — CTG-1.3 renders one from the
    other — so the consumer intersection can run against the *stored* classification instead of
    re-diffing two documents on a gate request. The presentation-only fields (``summary``,
    ``pathGroup``) are dropped; nothing the attribution rules read is lost.

    Args:
        changelog: The stored payload.

    Returns:
        The equivalent :class:`~app.change_taxonomy.ClassifiedDiff`.

    Raises:
        ValueError: When an entry is not shaped like a classified change (pydantic's message).
    """
    entries = changelog.get("entries")
    changes: List[ClassifiedChange] = []
    for entry in entries if isinstance(entries, Sequence) else []:
        if not isinstance(entry, Mapping):
            continue
        changes.append(
            ClassifiedChange(
                rule_id=str(entry.get("ruleId") or ""),
                severity=entry.get("severity"),
                pointer=str(entry.get("pointer") or ""),
                before=entry.get("before"),
                after=entry.get("after"),
                unclassified=bool(entry.get("unclassified")),
                change_kind=str(entry.get("changeKind") or ""),
            )
        )
    raw_counts = changelog.get("counts")
    counts = (
        {str(key): int(value) for key, value in raw_counts.items()}
        if isinstance(raw_counts, Mapping)
        else {}
    )
    return ClassifiedDiff(
        changes=changes, counts=counts, max_severity=changelog.get("maxSeverity")
    )


def _consumers_signal(
    tenant_id: str,
    project_id: str,
    *,
    changelog_row: Optional[Mapping[str, Any]],
    thresholds: Any,
    link: Optional[str],
    permitted: bool,
) -> GateSignal:
    """Judge the CTG-4.2 per-consumer verdicts for this publish.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project whose consumers are registered.
        changelog_row: The stored classification, which supplies the diff.
        thresholds: The consumer rungs in force.
        link: Path to the project's consumer registry.
        permitted: Whether the caller may read consumer contracts. A caller who may not gets
            ``unknown`` rather than a silently absent signal — the gate does not leak the
            registry, and it does not pretend the signal is unconfigured either.

    Returns:
        The judged signal.
    """
    if not permitted:
        return unavailable_signal(
            SIGNAL_CONSUMERS,
            status=STATUS_UNKNOWN,
            reason=REASON_CONSUMERS_FORBIDDEN,
            detail=(
                "This credential cannot read the consumer registry (`consumer_contracts:view`), "
                "so the per-consumer verdict is not part of this gate."
            ),
            link=link,
        )

    changelog = (changelog_row or {}).get("changelog_json")
    status = (changelog_row or {}).get("status")
    if not isinstance(changelog, Mapping) or status not in ("ready", "initial"):
        return unavailable_signal(
            SIGNAL_CONSUMERS,
            status=STATUS_NOT_CONFIGURED,
            reason=REASON_CONSUMERS_NO_CHANGELOG,
            detail=(
                "There is no stored classification for this revision, so there are no changes to "
                "attribute to consumers."
            ),
            link=link,
        )

    diff = _diff_from_changelog(changelog)
    report = consumer_impact_for_diff(
        tenant_id,
        project_id,
        diff,
        base_version_id=(
            str(changelog_row["baseline_revision_id"])
            if changelog_row and changelog_row.get("baseline_revision_id")
            else None
        ),
    )
    return evaluate_consumers(report=report, thresholds=thresholds, link=link)


def _schedule_watches_revision(
    schedule: VerificationScheduleRecord,
    *,
    project_id: str,
    project_slug: Optional[str],
    revision_id: str,
    version_label: Optional[str],
) -> bool:
    """Whether a schedule's version reference names the revision being gated.

    A schedule stores the reference *string* it was defined with, so the same revision may be
    watched as ``project/petstore/1.0.0``, ``project/<uuid>/1.0.0`` or ``project/petstore/latest``.
    All three are the same instruction and all three count; a reference naming another project, or
    a different version of this one, does not.

    Args:
        schedule: The stored schedule.
        project_id: The gated project's id.
        project_slug: Its slug.
        revision_id: The gated revision's id.
        version_label: Its version label.

    Returns:
        True when the schedule watches this revision.
    """
    try:
        reference = parse_schema_reference(schedule.version_ref)
    except SchemaReferenceError:
        return False
    if reference.kind != KIND_PROJECT:
        return False

    artifact = (reference.artifact or "").strip().lower()
    artifacts = {str(project_id).lower()}
    if project_slug:
        artifacts.add(str(project_slug).strip().lower())
    if artifact not in artifacts:
        return False

    version = (reference.version or "").strip()
    if version.lower() == LATEST_VERSION_TOKEN:
        return True
    versions = {str(revision_id).lower()}
    if version_label:
        versions.add(str(version_label).strip().lower())
    return version.lower() in versions


def _worst_run_status(statuses: Sequence[Optional[str]]) -> Optional[str]:
    """Return the most alarming run status present, ignoring "never ran".

    Args:
        statuses: The candidate statuses.

    Returns:
        The worst known status, or ``None`` when none is known.
    """
    worst: Optional[str] = None
    for status in statuses:
        if status not in _RUN_STATUS_RANK:
            continue
        if worst is None or _RUN_STATUS_RANK[status] > _RUN_STATUS_RANK[worst]:
            worst = status
    return worst


def _verification_from_schedules(
    schedules: Sequence[VerificationScheduleRecord],
) -> Tuple[Optional[int], Optional[str], Optional[datetime], Dict[str, Any]]:
    """Reduce the schedules watching this revision to one freshness answer.

    Freshness is the *most recent* clean verification across them, because any one of them
    verifying clean is evidence the deployment matched. The run status is the *worst* across them,
    because any one of them failing is evidence some deployment did not — a gate that averaged
    a failing staging check against a passing production one would hide the failure.

    Args:
        schedules: The matched schedules.

    Returns:
        ``(freshness_seconds, last_status, last_success_at, payload)``.
    """
    freshness = [s.freshness_seconds for s in schedules if s.freshness_seconds is not None]
    successes = [s.last_success_at for s in schedules if s.last_success_at is not None]
    payload: Dict[str, Any] = {
        "scheduleCount": len(schedules),
        "schedules": [
            {
                "id": s.id,
                "slug": s.slug,
                "versionRef": s.version_ref,
                "targetSlug": s.target_slug,
                "enabled": s.enabled,
                "lastStatus": s.last_status,
                "lastSuccessAt": s.last_success_at.isoformat() if s.last_success_at else None,
                "freshnessSeconds": s.freshness_seconds,
                "consecutiveFailures": s.consecutive_failures,
            }
            for s in schedules[:_MAX_SCHEDULES_REPORTED]
        ],
        "schedulesTruncated": len(schedules) > _MAX_SCHEDULES_REPORTED,
    }
    return (
        min(freshness) if freshness else None,
        _worst_run_status([s.last_status for s in schedules]),
        max(successes) if successes else None,
        payload,
    )


def _verification_from_reports(
    tenant_id: str, project_id: str, version_label: Optional[str], *, now: datetime
) -> Optional[Tuple[Optional[int], Optional[str], Optional[datetime], Dict[str, Any]]]:
    """Fall back to CTG-4.3 reports when nothing schedules this version.

    A version verified by hand is still verified. Two reads, not one: the newest report of any
    outcome says what the deployment did *last*, and the newest **passing** one is the freshness
    anchor — taking the age of a failing report as freshness would report a broken deployment as
    recently verified.

    Args:
        tenant_id: The caller's tenant.
        project_id: The gated project.
        version_label: The gated version label, when known.
        now: Reference instant for the age computation.

    Returns:
        ``(freshness_seconds, last_status, last_success_at, payload)``, or ``None`` when this
        project has never been verified at all.
    """
    newest = latest_report_for_project(tenant_id, project_id, version_label=version_label)
    if newest is None:
        return None

    passing = (
        newest
        if newest.outcome == "passed"
        else _latest_passing_report(tenant_id, project_id, version_label)
    )

    freshness: Optional[int] = None
    last_success_at: Optional[datetime] = passing.created_at if passing else None
    if last_success_at is not None:
        anchor = last_success_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        freshness = max(0, int((now - anchor).total_seconds()))

    payload: Dict[str, Any] = {
        "reportId": newest.id,
        "reportOutcome": newest.outcome,
        "reportCreatedAt": newest.created_at.isoformat() if newest.created_at else None,
        "coveragePercent": newest.coverage_percent,
        "targetSlug": newest.target_slug,
        "driftCount": newest.drift_count,
    }
    return freshness, newest.outcome, last_success_at, payload


def _latest_passing_report(
    tenant_id: str, project_id: str, version_label: Optional[str]
) -> Optional[ConformanceReportSummary]:
    """The newest report for this project that actually passed.

    Args:
        tenant_id: The caller's tenant.
        project_id: The gated project.
        version_label: The gated version label, when known.

    Returns:
        The summary, or ``None`` when nothing has ever passed.
    """
    reports = list_reports(
        tenant_id,
        artifact_kind=KIND_PROJECT,
        artifact_id=project_id,
        version_label=version_label,
        outcome="passed",
        limit=1,
    )
    return reports[0] if reports else None


def _verification_signal(
    tenant_id: str,
    project: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    thresholds: Any,
    link: Optional[str],
    now: datetime,
) -> GateSignal:
    """Judge how recently this version's deployment was verified.

    Args:
        tenant_id: The caller's tenant.
        project: The gated project row.
        version: The gated version row.
        thresholds: The verification rungs in force.
        link: Path to the schedules behind this.
        now: Reference instant.

    Returns:
        The judged signal.
    """
    project_id = str(project["id"])
    project_slug = project.get("slug")
    revision_id = str(version["id"])
    version_label = version.get("version_id")

    matched = [
        schedule
        for schedule in list_schedules(tenant_id, limit=_SCHEDULE_SCAN_LIMIT, now=now)
        if _schedule_watches_revision(
            schedule,
            project_id=project_id,
            project_slug=project_slug,
            revision_id=revision_id,
            version_label=version_label,
        )
    ]

    if matched:
        freshness, last_status, last_success_at, payload = _verification_from_schedules(
            matched
        )
        source = "schedule"
    else:
        fallback = _verification_from_reports(
            tenant_id, project_id, version_label, now=now
        )
        if fallback is None:
            return evaluate_verification(
                source=None,
                freshness_seconds=None,
                last_status=None,
                thresholds=thresholds,
                link=link,
            )
        freshness, last_status, last_success_at, payload = fallback
        source = "report"

    return evaluate_verification(
        source=source,
        freshness_seconds=freshness,
        last_status=last_status,
        last_success_at=last_success_at,
        thresholds=thresholds,
        link=link,
        extra=payload,
    )


# -------------------------------------------------------------------------------------------
# Links
# -------------------------------------------------------------------------------------------


def _links(tenant_slug: str, project_id: str, revision_id: str) -> Dict[str, str]:
    """API paths a reader follows for each signal's underlying evidence.

    Args:
        tenant_slug: The tenant in the URL.
        project_id: The gated project.
        revision_id: The gated revision.

    Returns:
        One path per signal.
    """
    return {
        SIGNAL_LINT: f"/v1/versions/{tenant_slug}/{project_id}/{revision_id}/lint",
        SIGNAL_BREAKING: f"/v1/versions/{tenant_slug}/{project_id}/{revision_id}/changelog",
        SIGNAL_CONSUMERS: f"/v1/tenants/{tenant_slug}/projects/{project_id}/consumers",
        SIGNAL_VERIFICATION: f"/v1/tenants/{tenant_slug}/verification-schedules",
    }


def _guarded(
    signal: str, link: Optional[str], gather: Callable[[], GateSignal]
) -> GateSignal:
    """Run one signal's gathering, turning any failure into an ``unknown`` signal.

    A CD gate that returned ``500`` because one of four inputs was briefly unreadable would stop
    every pipeline in the tenant. Losing one signal and saying so is the smaller failure.

    Args:
        signal: The signal being gathered.
        link: Its evidence link, carried onto the failure too.
        gather: A zero-argument callable returning the judged signal.

    Returns:
        The judged signal, or an ``unknown`` one describing the failure.
    """
    try:
        return gather()
    except Exception:  # noqa: BLE001 - one unreadable signal must not fail the gate
        logger.warning("Deploy-gate signal %r could not be gathered", signal, exc_info=True)
        return unavailable_signal(
            signal,
            status=STATUS_UNKNOWN,
            reason=REASON_SIGNAL_UNAVAILABLE,
            detail=(
                f"The {signal} signal could not be read, so it is not part of this verdict. "
                "This is not the same as the signal passing."
            ),
            link=link,
        )


# -------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------


def build_project_gate(
    *,
    tenant_id: str,
    tenant_slug: str,
    project_ref: str,
    revision_id: Optional[str] = None,
    consumers_permitted: bool = True,
    now: Optional[datetime] = None,
) -> DeployGateReport:
    """Answer "can I promote this?" for one project, in one call.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug, used to build the evidence links.
        project_ref: The project's id or slug.
        revision_id: A specific published revision, or ``None`` for the newest published one.
        consumers_permitted: Whether the caller may read the consumer registry.
        now: Reference instant (tests).

    Returns:
        The complete :class:`~app.deploy_gate.DeployGateReport`.

    Raises:
        DeployGateError: When the project, or a revision to judge, cannot be resolved.
    """
    evaluated_at = now or datetime.now(timezone.utc)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    version = _resolve_revision(tenant_id, project_id, revision_id)
    resolved_revision_id = str(version["id"])
    version_label = version.get("version_id")

    policy: DeployGatePolicyOut = load_policy(tenant_id, project_id)
    thresholds = policy.thresholds
    links = _links(tenant_slug, project_id, resolved_revision_id)

    # One read of the classification, shared by the breaking and consumer signals: they are two
    # questions about the same stored payload, and reading it twice would be two chances to
    # disagree about what this publish contained.
    changelog_row: Optional[Dict[str, Any]] = None
    changelog_error: Optional[Exception] = None
    try:
        changelog_row = _changelog_row(tenant_id, project_id, resolved_revision_id)
    except Exception as exc:  # noqa: BLE001 - both dependent signals degrade below
        logger.warning(
            "Deploy gate could not read the changelog for revision %s",
            resolved_revision_id,
            exc_info=True,
        )
        changelog_error = exc

    if changelog_error is not None:
        breaking = _guarded(SIGNAL_BREAKING, links[SIGNAL_BREAKING], _raise(changelog_error))
        consumers = _guarded(
            SIGNAL_CONSUMERS, links[SIGNAL_CONSUMERS], _raise(changelog_error)
        )
    else:
        breaking = _guarded(
            SIGNAL_BREAKING,
            links[SIGNAL_BREAKING],
            lambda: _breaking_signal(
                changelog_row,
                baseline_version_label=_baseline_label(tenant_id, changelog_row),
                thresholds=thresholds.breaking,
                link=links[SIGNAL_BREAKING],
            ),
        )
        consumers = _guarded(
            SIGNAL_CONSUMERS,
            links[SIGNAL_CONSUMERS],
            lambda: _consumers_signal(
                tenant_id,
                project_id,
                changelog_row=changelog_row,
                thresholds=thresholds.consumers,
                link=links[SIGNAL_CONSUMERS],
                permitted=consumers_permitted,
            ),
        )

    lint = _guarded(
        SIGNAL_LINT,
        links[SIGNAL_LINT],
        lambda: _lint_signal(version, thresholds=thresholds.lint, link=links[SIGNAL_LINT]),
    )
    verification = _guarded(
        SIGNAL_VERIFICATION,
        links[SIGNAL_VERIFICATION],
        lambda: _verification_signal(
            tenant_id,
            project,
            version,
            thresholds=thresholds.verification,
            link=links[SIGNAL_VERIFICATION],
            now=evaluated_at,
        ),
    )

    version_ref = (
        f"{KIND_PROJECT}/{project.get('slug') or project_id}/{version_label}"
        if version_label
        else None
    )
    return build_gate_report(
        project_id=project_id,
        project_slug=project.get("slug"),
        revision_id=resolved_revision_id,
        version_label=version_label,
        version_ref=version_ref,
        published_at=version.get("published_at"),
        signals=[lint, breaking, consumers, verification],
        policy=policy,
        evaluated_at=evaluated_at,
    )


def _raise(exc: Exception) -> Callable[[], GateSignal]:
    """Return a callable that re-raises ``exc``, so a shared failure degrades both signals alike.

    Args:
        exc: The failure to replay.

    Returns:
        A zero-argument callable that raises it.
    """

    def _thunk() -> GateSignal:
        raise exc

    return _thunk

