"""Webhook-instant refresh of the files a push changed (RAR-6.3, #3540).

REPO-4.3 made a push an *accelerator on the cadence*: it queues a branch scan and makes the
repository due, so the RAR-3.2 sweep refreshes it on its next tick — up to one tick
(``APIOME_REFRESH_MIN_INTERVAL``, 60 s by default) later, and by walking every tracked file on
every tracked branch. This module closes that gap for the common case: when a push delivery
lists the files its commits touched (GitHub, GitLab), the tracked ones among them are refreshed
**right away**, and only they are.

"Refreshed" means exactly what the sweep does to a file, through the same enqueue core
(:func:`app.repository_refresh_sweep.enqueue_stale_files_for_branch`, limited to the pushed
paths):

* the pushed branch is rescanned, and a file is enqueued only when the RAR-2.2 newer-than
  comparator says it is genuinely newer than its last import (**freshness gate**);
* each job carries the file's stored import spec, so the EPIC-4 executor replays the original
  request and applies the RAR-4.4 **divergence guard** before overwriting anything;
* the tenant's polling **quota** (REPO-4.6) bounds it, the per-repository refresh **lock** keeps
  it from overlapping a sweep tick, and the global **kill switch** (``APIOME_REFRESH_ENABLED``),
  the per-repository opt-out and the RAR-3.4 auto-pause all stop it.

**Fallback to the cadence.** The webhook path always makes the repository due first (REPO-4.3),
so whenever an instant refresh cannot run — the provider sent no file list (Bitbucket), the list
may be incomplete (a force push, a truncated commit list), the tenant is out of quota, a sweep
holds the lock, or the rescan failed — the next sweep tick refreshes the repository as before.
Only a refresh that ran to completion with nothing deferred advances the cadence anchor, so the
sweep does not walk the repository again for the push it already handled.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, NamedTuple, Optional, Tuple

_logger = logging.getLogger(__name__)

__all__ = [
    "INSTANT_REFRESH_AUDIT_ACTION",
    "REASON_LOCK_HELD",
    "REASON_NOT_POLLABLE",
    "REASON_QUOTA_EXHAUSTED",
    "REASON_REFRESH_DISABLED",
    "REASON_REFRESH_FAILED",
    "REASON_REPOSITORY_MISSING",
    "InstantRefreshResult",
    "refresh_pushed_files",
    "run_instant_refresh",
    "tracked_changed_paths",
]

#: Workflow-audit action for an instant refresh, so "which push re-imported this file" is answered.
INSTANT_REFRESH_AUDIT_ACTION = "repository.webhook.instant_refresh"

# Why an instant refresh did not run; in each case the repository stays due for the sweep.
REASON_REFRESH_DISABLED = "refresh-disabled"
REASON_REPOSITORY_MISSING = "repository-missing"
REASON_NOT_POLLABLE = "repository-not-pollable"
REASON_QUOTA_EXHAUSTED = "quota-exhausted"
REASON_LOCK_HELD = "refresh-in-progress"
REASON_REFRESH_FAILED = "refresh-failed"


class InstantRefreshResult(NamedTuple):
    """What an instant refresh did.

    Attributes:
        ran: True when the pushed files were evaluated (whatever was enqueued).
        enqueued: Refresh jobs enqueued — files newer than their last import.
        skipped: Files not enqueued: not newer (freshness gate) or already queued.
        deferred: Newer files left for the sweep because the tenant's quota ran out.
        reason: Why it did not run (a ``REASON_*`` code), or ``None`` when it ran.
    """

    ran: bool
    enqueued: int = 0
    skipped: int = 0
    deferred: int = 0
    reason: Optional[str] = None


def tracked_changed_paths(
    db: Any, repository_id: str, branch: str, changed_paths: Optional[Iterable[str]]
) -> Optional[Tuple[str, ...]]:
    """The files a push changed that have a stored import spec on its branch.

    Args:
        db: Database handle.
        repository_id: The repository the push moved.
        branch: The pushed branch.
        changed_paths: The paths the push's commits touched, or ``None`` when unknown.

    Returns:
        The tracked changed paths, sorted (empty when the push touched no tracked file), or
        ``None`` when the changed files are unknown — the caller then leaves it to the sweep.
    """
    if changed_paths is None:
        return None
    changed = set(changed_paths)
    if not changed:
        return ()
    tracked = set(db.list_repository_import_spec_paths(repository_id, branch))
    return tuple(sorted(tracked & changed))


def _audit(db: Any, tenant_id: str, repository_id: str, branch: str, paths: Tuple[str, ...],
           result: InstantRefreshResult) -> None:
    """Write one metadata-only workflow-audit row for the attempt (best-effort)."""
    try:
        db.insert_workflow_audit(
            tenant_id,
            None,
            None,
            INSTANT_REFRESH_AUDIT_ACTION,
            "success" if result.ran else "skipped",
            None,
            {
                "repositoryId": repository_id,
                "branch": branch,
                "paths": list(paths),
                "enqueued": result.enqueued,
                "skipped": result.skipped,
                "deferred": result.deferred,
                "reason": result.reason,
            },
        )
    except Exception:  # noqa: BLE001 - an audit failure never undoes the refresh
        _logger.exception("instant refresh audit write failed repository_id=%s", repository_id)


def refresh_pushed_files(
    db: Any, *, tenant_id: str, repository_id: str, branch: str, paths: Iterable[str]
) -> InstantRefreshResult:
    """Refresh the tracked files a push changed, now, through the sweep's gates.

    Blocking (it rescans the branch through the provider API) — run it off the request path.

    Args:
        db: Database handle.
        tenant_id: The repository's tenant.
        repository_id: The repository the push moved.
        branch: The pushed branch.
        paths: The tracked paths the push changed (:func:`tracked_changed_paths`).

    Returns:
        :class:`InstantRefreshResult`. Never raises: a failure leaves the repository due, so the
        next sweep tick refreshes it instead.
    """
    from .config import settings
    from .repository_refresh_quota import load_tenant_refresh_quota_tracker
    from .repository_refresh_sweep import (
        RepositoryRefreshResult,
        _record_poll_telemetry,
        enqueue_stale_files_for_branch,
    )

    wanted = tuple(sorted(set(paths)))
    if not wanted:
        return InstantRefreshResult(ran=True)

    def done(result: InstantRefreshResult) -> InstantRefreshResult:
        _audit(db, tenant_id, repository_id, branch, wanted, result)
        return result

    if not settings.refresh_enabled:
        return done(InstantRefreshResult(ran=False, reason=REASON_REFRESH_DISABLED))
    repo_row = db.get_tenant_repository(tenant_id, repository_id)
    if not repo_row:
        return done(InstantRefreshResult(ran=False, reason=REASON_REPOSITORY_MISSING))
    if repo_row.get("auto_refresh_enabled") is False or repo_row.get("refresh_paused_at") is not None:
        # The tenant's opt-out and the RAR-3.4 auto-pause hold for a push, as they do for the sweep.
        return done(InstantRefreshResult(ran=False, reason=REASON_NOT_POLLABLE))

    quota = load_tenant_refresh_quota_tracker(db)
    if quota is not None and quota.is_exhausted(tenant_id):
        return done(InstantRefreshResult(ran=False, reason=REASON_QUOTA_EXHAUSTED))
    if not db.try_acquire_repository_refresh_lock(repository_id):
        # A sweep tick is refreshing this repository right now; it covers the push.
        return done(InstantRefreshResult(ran=False, reason=REASON_LOCK_HELD))

    try:
        branch_result = enqueue_stale_files_for_branch(
            db,
            repo_row,
            branch,
            path_filter=frozenset(wanted),
            max_enqueues=(quota.remaining(tenant_id) if quota is not None else None),
        )
    except Exception:  # noqa: BLE001 - the sweep retries a repository left due
        _logger.exception(
            "instant refresh failed repository_id=%s branch=%s", repository_id, branch
        )
        db.release_repository_refresh_lock(repository_id)
        return done(InstantRefreshResult(ran=False, reason=REASON_REFRESH_FAILED))

    try:
        if quota is not None:
            quota.consume(tenant_id, branch_result.enqueued)
        _record_poll_telemetry(
            db,
            quota,
            repo_row,
            RepositoryRefreshResult(
                enqueued=branch_result.enqueued, failed=False, error=None, deferred=branch_result.deferred
            ),
        )
        if branch_result.deferred == 0:
            # The push is handled: advance the anchor so the sweep does not walk the
            # repository again for it. Deferred files keep it due for the next tick.
            db.mark_repository_refreshed(repository_id)
    except Exception:  # noqa: BLE001 - bookkeeping never fails the refresh
        _logger.exception("instant refresh bookkeeping failed repository_id=%s", repository_id)
    finally:
        db.release_repository_refresh_lock(repository_id)

    return done(
        InstantRefreshResult(
            ran=True,
            enqueued=branch_result.enqueued,
            skipped=branch_result.skipped,
            deferred=branch_result.deferred,
        )
    )


def run_instant_refresh(*, tenant_id: str, repository_id: str, branch: str, paths: Tuple[str, ...]) -> None:
    """Run :func:`refresh_pushed_files` on its own database connection (the webhook's background task).

    The webhook answers the provider first — a branch rescan can outlast a provider's delivery
    timeout — then this runs in a worker thread, as the sweeps do.
    """
    from .database import Database

    thread_db = Database()
    try:
        result = refresh_pushed_files(
            thread_db, tenant_id=tenant_id, repository_id=repository_id, branch=branch, paths=paths
        )
        _logger.info(
            "instant refresh repository_id=%s branch=%s files=%d enqueued=%d reason=%s",
            repository_id,
            branch,
            len(paths),
            result.enqueued,
            result.reason,
        )
    except Exception:  # noqa: BLE001 - a background task has nobody to raise to
        _logger.exception("instant refresh task failed repository_id=%s", repository_id)
    finally:
        thread_db.close()
