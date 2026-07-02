"""Refresh-cycle audit + change-report linking (RAR-5.3, #3534).

Each auto-refresh cycle must be auditable for compliance and debugging: *what*
triggered it (scheduled sweep / manual "Refresh Now" / webhook), *what the
freshness gate decided*, *what came out* (a new version / a no-op / a held
divergence / a failure), and *which change report* documents the diff.

This module extends the REPO-12.6 (#2944) ``apiome.workflow_audit`` ledger — the same
append-only trail that already records publish/pull/merge — with one dedicated
action, :data:`REFRESH_CYCLE_ACTION`, written once per refresh cycle. The rich,
refresh-specific facets (trigger, file lineage, decision, outcome, and the
change-report / version links) live in the row's ``detail`` JSONB so the existing
ledger schema is reused unchanged (no migration, hence this ticket is
apiome-rest only)::

    refresh cycle ──► audit { trigger, file, decision, version_id, change_report_id, outcome }

The ``workflow_audit.outcome`` *column* keeps its established ``success`` /
``failure`` semantics (a held divergence or a no-op is still a *successful*
cycle); the richer four-valued refresh outcome
(``new-version`` / ``unchanged`` / ``diverged`` / ``failed``) is carried in
``detail.outcome`` and surfaced by the refresh-history query.

The ``repositoryId`` / ``branch`` / ``path`` lineage keys live in ``detail`` so the
history is queryable **per repo and per file**
(:meth:`Database.search_repository_refresh_audit`).

Like the sibling RAR-4.x building blocks, recording here is **best-effort**: it
never raises, so an audit problem can never fail the refresh it describes.
Invoking :func:`record_refresh_cycle` from the EPIC-4 refresh dispatcher — after
the version is created (RAR-4.2) and the change report is generated (RAR-4.3) — is
the dispatcher's job, mirroring how RAR-4.1/4.2/4.3/4.4 deferred their wiring.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Workflow-audit action stamped on every refresh-cycle row, distinct from the
# per-report ``schema.refresh.change_report.generated`` action (RAR-4.3) so refresh
# *history* (the cycle ledger) can be filtered independently of report generation.
REFRESH_CYCLE_ACTION = "repository.refresh.cycle"


class RefreshTrigger(str, Enum):
    """What initiated a refresh cycle (stable codes for audit/history)."""

    #: The periodic auto-refresh sweep (RAR-3.2) found the file stale and due.
    SCHEDULED = "scheduled"
    #: A user pressed "Refresh Now" (RAR-5.2) for the file or repository.
    MANUAL = "manual"
    #: A provider webhook (push/PR) drove an instant refresh (RAR-6.3, v2).
    WEBHOOK = "webhook"


class RefreshOutcome(str, Enum):
    """What a refresh cycle produced (stable codes for audit/history)."""

    #: The re-import created a new, provenance-linked version (RAR-4.2).
    NEW_VERSION = "new-version"
    #: The file was newer but its content was unchanged — no version churn (RAR-2.4).
    UNCHANGED = "unchanged"
    #: A manual edit since import was detected; the refresh was held, not applied
    #: (RAR-4.4 divergence guard).
    DIVERGED = "diverged"
    #: The refresh cycle errored before producing a version.
    FAILED = "failed"


def derive_outcome(
    *,
    failed: bool,
    diverged: bool,
    version_created: bool,
) -> RefreshOutcome:
    """Map the terminal state of a refresh cycle to a :class:`RefreshOutcome`.

    Precedence mirrors the refresh pipeline: a failure dominates (we could not even
    evaluate divergence safely), then a held divergence (RAR-4.4 blocked the
    overwrite), then whether a new version was actually created; anything else is a
    freshness/idempotency no-op.

    Args:
        failed: The cycle errored before completing.
        diverged: The divergence guard held the refresh (RAR-4.4).
        version_created: A new version was created by the re-import (RAR-4.2).

    Returns:
        The single :class:`RefreshOutcome` describing the cycle.
    """
    if failed:
        return RefreshOutcome.FAILED
    if diverged:
        return RefreshOutcome.DIVERGED
    if version_created:
        return RefreshOutcome.NEW_VERSION
    return RefreshOutcome.UNCHANGED


def _clean_str(raw: Any) -> Optional[str]:
    """Return a stripped non-empty string, or ``None`` for blank/missing values."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _column_outcome(outcome: RefreshOutcome) -> str:
    """Map the rich refresh outcome to the ``workflow_audit.outcome`` column value.

    The column keeps its established two-valued ``success`` / ``failure`` semantics
    (so existing audit consumers and the success/failure filter keep working); only
    a ``failed`` cycle is a ``failure``. The richer four-valued outcome is carried in
    ``detail.outcome``.
    """
    return "failure" if outcome is RefreshOutcome.FAILED else "success"


def build_refresh_cycle_detail(
    *,
    trigger: RefreshTrigger,
    outcome: RefreshOutcome,
    repository_id: str,
    branch: str,
    path: str,
    decision: Optional[str] = None,
    version_id: Optional[str] = None,
    parent_version_id: Optional[str] = None,
    change_report_id: Optional[str] = None,
    source_commit_sha: Optional[str] = None,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the ``detail`` JSONB payload for one refresh-cycle audit row.

    The lineage keys (``repositoryId`` / ``branch`` / ``path``), ``trigger`` and
    ``outcome`` are always present so the history is reliably queryable; the link
    and context fields are included only when supplied so a no-op or failed cycle
    does not carry empty links.

    Args:
        trigger: What initiated the cycle.
        outcome: What the cycle produced.
        repository_id: The repository whose file was refreshed (lineage key).
        branch: The branch the file was refreshed on (lineage key).
        path: The repository-relative file path (lineage key).
        decision: The RAR-2.2 freshness ``RefreshReason`` code, when known.
        version_id: The new version created by the refresh (RAR-4.2), when any.
        parent_version_id: The prior version the refresh supersedes, when any.
        change_report_id: The change report documenting the diff (RAR-4.3), when any.
        source_commit_sha: The remote commit SHA that triggered the refresh, when known.
        error: A short error message, for a failed cycle.
        extra: Optional additional structured context merged into the detail (callers
            must not override the reserved keys above).

    Returns:
        A JSON-serializable ``detail`` dict with camelCase keys.
    """
    detail: Dict[str, Any] = {
        "trigger": trigger.value,
        "outcome": outcome.value,
        "repositoryId": _clean_str(repository_id),
        "branch": _clean_str(branch),
        "path": _clean_str(path),
    }
    decision_v = _clean_str(decision)
    if decision_v is not None:
        detail["decision"] = decision_v
    version_v = _clean_str(version_id)
    if version_v is not None:
        detail["versionId"] = version_v
    parent_v = _clean_str(parent_version_id)
    if parent_v is not None:
        detail["parentVersionId"] = parent_v
    report_v = _clean_str(change_report_id)
    if report_v is not None:
        detail["changeReportId"] = report_v
    commit_v = _clean_str(source_commit_sha)
    if commit_v is not None:
        detail["sourceCommitSha"] = commit_v
    error_v = _clean_str(error)
    if error_v is not None:
        detail["error"] = error_v
    if extra:
        for k, v in extra.items():
            detail.setdefault(k, v)
    return detail


def record_refresh_cycle(
    db: Any,
    *,
    tenant_id: str,
    repository_id: str,
    branch: str,
    path: str,
    trigger: RefreshTrigger,
    outcome: RefreshOutcome,
    project_id: Optional[str] = None,
    version_id: Optional[str] = None,
    parent_version_id: Optional[str] = None,
    change_report_id: Optional[str] = None,
    decision: Optional[str] = None,
    source_commit_sha: Optional[str] = None,
    actor_id: Optional[str] = None,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write one refresh-cycle audit row to ``apiome.workflow_audit`` (RAR-5.3).

    Best-effort: the underlying :meth:`Database.insert_workflow_audit` logs and
    swallows DB errors, so this never raises and an audit failure cannot break the
    refresh it describes.

    Args:
        db: The database handle exposing ``insert_workflow_audit``.
        tenant_id: Owning tenant id (audit scope).
        repository_id: The repository whose file was refreshed.
        branch: The branch the file was refreshed on.
        path: The repository-relative file path.
        trigger: What initiated the cycle (:class:`RefreshTrigger`).
        outcome: What the cycle produced (:class:`RefreshOutcome`).
        project_id: The catalog project the refresh targets, when known.
        version_id: The new version created by the refresh (RAR-4.2), when any.
        parent_version_id: The prior version the refresh supersedes, when any.
        change_report_id: The change report documenting the diff (RAR-4.3), when any.
        decision: The RAR-2.2 freshness ``RefreshReason`` code, when known.
        source_commit_sha: The remote commit SHA that triggered the refresh.
        actor_id: The user who triggered the cycle (manual), or ``None`` for system
            (scheduled / webhook) refreshes.
        error: A short error message, for a failed cycle.
        extra: Optional additional structured context for the detail.

    Returns:
        The ``detail`` dict that was recorded (useful for tests and for the caller
        to log).

    Raises:
        TypeError: If ``trigger`` or ``outcome`` is not the matching enum type
            (a programming error, caught at call time rather than corrupting the
            ledger with a free-form string).
    """
    if not isinstance(trigger, RefreshTrigger):
        raise TypeError(
            f"trigger must be a RefreshTrigger, got {type(trigger).__name__}"
        )
    if not isinstance(outcome, RefreshOutcome):
        raise TypeError(
            f"outcome must be a RefreshOutcome, got {type(outcome).__name__}"
        )

    detail = build_refresh_cycle_detail(
        trigger=trigger,
        outcome=outcome,
        repository_id=repository_id,
        branch=branch,
        path=path,
        decision=decision,
        version_id=version_id,
        parent_version_id=parent_version_id,
        change_report_id=change_report_id,
        source_commit_sha=source_commit_sha,
        error=error,
        extra=extra,
    )

    db.insert_workflow_audit(
        tenant_id,
        _clean_str(project_id),
        _clean_str(version_id),
        REFRESH_CYCLE_ACTION,
        _column_outcome(outcome),
        _clean_str(actor_id),
        detail,
    )
    return detail
