"""Manual one-shot "Refresh Now" (RAR-5.2, #3533).

Extends the REPO-9.5 "Import Now" idea into a *spec-faithful* refresh that a user
can trigger on demand — for a single imported file or for a whole repository —
without waiting for the next auto-refresh tick. It reuses the exact enqueue core
of the periodic sweep (:func:`repository_refresh_sweep.enqueue_stale_files_for_branch`),
so the same gates apply:

- **Stored spec, not defaults.** Each enqueued job carries the captured
  ``SpecImportOptions`` snapshot (RAR-1.2) so the EPIC-4 executor replays the
  user's original request (RAR-4.1).
- **Freshness gate honored.** Only files genuinely newer than the last import
  enqueue (RAR-2.2 newer-than comparator); an up-to-date file is a no-op.
- **Divergence guard honored.** The job runs through the same EPIC-4 executor as
  an auto-refresh, which applies the RAR-4.4 manual-edit divergence guard before
  overwriting.

What it deliberately does **not** honor is the *cadence* and the auto-refresh
opt-outs: unlike the sweep, this path does not consult
``list_due_repositories`` / ``mark_repository_refreshed``, the per-repo
``auto_refresh_enabled`` flag (RAR-3.3), or the global ``APIOME_REFRESH_ENABLED``
kill switch. A manual refresh works even when scheduled auto-refresh is disabled —
that is the whole point of the button.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, NamedTuple, Optional

from .database import Database
from .repository_refresh_sweep import enqueue_stale_files_for_branch

_logger = logging.getLogger(__name__)


class ManualRefreshResult(NamedTuple):
    """Aggregate outcome of a one-shot manual refresh.

    Attributes:
        enqueued: Total refresh jobs enqueued across the processed branches.
        skipped: Candidates considered but not enqueued (already up to date, or
            already covered by an active job).
        branches: The branch names that were rescanned and evaluated.
    """

    enqueued: int
    skipped: int
    branches: List[str]


def refresh_repository_now(
    db: Database,
    *,
    tenant_id: str,
    repository_id: str,
    branch: Optional[str] = None,
    path: Optional[str] = None,
) -> Optional[ManualRefreshResult]:
    """Run a one-shot, spec-faithful refresh for a file or a whole repository.

    Resolves the repository, picks the branches to evaluate, and enqueues a
    spec-faithful re-import for every stale + newer file (per-file when ``path``
    is given, otherwise the whole repository). The cadence and auto-refresh
    opt-outs are intentionally bypassed; the freshness gate (RAR-2.2) and the
    downstream divergence guard (RAR-4.4) are still honored.

    Branch selection:
      - ``branch`` given → only that branch is evaluated.
      - ``branch`` omitted → every branch that has a stored import spec for this
        repository is evaluated (the same set the sweep walks).

    Args:
        db: Database handle.
        tenant_id: Owning tenant id (scopes the repository lookup).
        repository_id: The repository to refresh.
        branch: Optional branch to scope the refresh to.
        path: Optional repository-relative file path for a per-file refresh; when
            omitted, the whole repository (all selected branches) is refreshed.

    Returns:
        A :class:`ManualRefreshResult`, or ``None`` when the repository does not
        belong to the tenant (the caller maps this to a 404).
    """
    repo_row = db.get_tenant_repository(tenant_id, repository_id)
    if not repo_row:
        return None

    if branch:
        branches = [branch]
    else:
        branches = db.list_repository_import_spec_branches(repository_id)

    enqueued = 0
    skipped = 0
    processed: List[str] = []
    for b in branches:
        try:
            result = enqueue_stale_files_for_branch(db, repo_row, b, path_filter=path)
        except Exception:
            # A bad branch (GitHub error, etc.) must not abort the others; the
            # caller still reports what did get enqueued.
            _logger.exception(
                "manual refresh rescan failed repository_id=%s branch=%s",
                repository_id,
                b,
            )
            continue
        enqueued += result.enqueued
        skipped += result.skipped
        processed.append(b)

    return ManualRefreshResult(enqueued=enqueued, skipped=skipped, branches=processed)
