"""
Checksum idempotency guard for repository auto-refresh (RAR-2.4, #3521).

The RAR-2.2 newer-than comparator (:mod:`repository_refresh_comparator`) gates a
re-import on commit recency, using the file ``blob_sha`` as its content-identity
token. But a newer commit can change the ``blob_sha`` without changing the
**spec content** — a reformat, a comment, a license-header bump, or even a
no-op re-commit of identical bytes. Re-importing on those would create empty /
no-op versions: churn.

This module is the second, finer gate. It takes the RAR-2.2 decision plus the
REPO-8.3 (#2933) **content checksum** — a normalized digest of the parsed spec
content that is stable across cosmetic changes — and decides the final action:

    newer commit + content checksum changed   -> REIMPORT
    newer commit + content checksum unchanged -> ADVANCE_ANCHOR_ONLY (no churn)
    older / equal commit                       -> SKIP (stale guard, RAR-2.2)
    no prior import                            -> REIMPORT (first import)

``ADVANCE_ANCHOR_ONLY`` is the heart of the ticket: it tells the dispatch
(RAR-4.1) to create **no new version** yet still advance the recency anchor
(``last_imported_commit_sha`` / ``last_imported_committed_at``) to the observed
commit and record the file as ``unchanged-checksum``, so the same newer commit
is not re-evaluated as "newer" on every subsequent sweep.

Like the comparator, this is a pure, side-effect-free decision function so it
can be exercised by deterministic fixtures. Persisting the advanced anchor and
the ``unchanged-checksum`` marker is the dispatcher's job (RAR-4.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .repository_refresh_comparator import (
    RefreshDecision,
    RefreshReason,
    TimestampInput,
    evaluate_refresh,
)


class RefreshAction(str, Enum):
    """The final action the auto-refresh dispatch should take for one file."""

    #: Re-import the file: create a new version and advance every anchor.
    REIMPORT = "reimport"
    #: Newer commit but identical content: create NO version, but advance the
    #: recency anchor and record the file as ``unchanged-checksum`` (RAR-2.4).
    ADVANCE_ANCHOR_ONLY = "advance-anchor-only"
    #: Nothing to do — the remote is not newer (or has no meaningful change).
    SKIP = "skip"


class IdempotencyReason(str, Enum):
    """Why the guard reached its action (stable codes for logging/audit/UI)."""

    #: Nothing was ever imported for this lineage -> treat as a fresh import.
    FIRST_IMPORT = "first-import"
    #: Newer commit and the content checksum differs -> real change, re-import.
    CONTENT_CHANGED = "content-changed"
    #: Newer commit but the content checksum is unchanged -> skip the version,
    #: advance the anchor. This is the acceptance-criteria marker for the file.
    UNCHANGED_CHECKSUM = "unchanged-checksum"
    #: The remote commit is older than / equal to the last import -> stale guard.
    STALE = "stale"
    #: No newer commit and content identical -> nothing to do.
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class IdempotencyOutcome:
    """Outcome of the checksum idempotency guard for a single file.

    Attributes:
        action: The :class:`RefreshAction` the dispatch should take.
        reason: The :class:`IdempotencyReason` code explaining the action.
        advance_committed_anchor: True when the dispatch should advance the
            ``last_imported_commit_sha`` / ``last_imported_committed_at`` recency
            anchor to the observed commit even though it may create no version.
            True for ``REIMPORT`` (newer commit) and ``ADVANCE_ANCHOR_ONLY``;
            False for ``SKIP`` and the first import (where the dispatch sets the
            anchor as part of the import itself).
    """

    action: RefreshAction
    reason: IdempotencyReason
    advance_committed_anchor: bool


def _normalise_checksum(value: Optional[str]) -> Optional[str]:
    """Trim a content checksum to a comparable form (``None`` when blank)."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def evaluate_checksum_idempotency(
    *,
    decision: RefreshDecision,
    remote_content_checksum: Optional[str],
    last_imported_content_checksum: Optional[str],
) -> IdempotencyOutcome:
    """Refine a RAR-2.2 refresh decision with the REPO-8.3 content checksum.

    Given the recency verdict from :func:`evaluate_refresh` and the normalized
    content checksums, decide whether a newer commit actually warrants a new
    version (content genuinely changed) or should only advance the anchor
    (content identical despite a newer commit), suppressing version churn.

    When a content checksum is missing on either side the guard cannot prove
    content equality, so it defers to the comparator's verdict verbatim rather
    than risk suppressing a real change or churning on a cosmetic one.

    Args:
        decision: The :class:`RefreshDecision` from the RAR-2.2 comparator.
        remote_content_checksum: REPO-8.3 content checksum of the remote file
            (the normalized spec-content digest), or None when unavailable.
        last_imported_content_checksum: The content checksum recorded at the last
            import, or None when unavailable.

    Returns:
        An :class:`IdempotencyOutcome` with the action, reason, and whether the
        recency anchor should be advanced.
    """
    reason = decision.reason

    # First import for this lineage: there is no anchor to compare against.
    if reason is RefreshReason.NO_PRIOR_IMPORT:
        return IdempotencyOutcome(
            action=RefreshAction.REIMPORT,
            reason=IdempotencyReason.FIRST_IMPORT,
            advance_committed_anchor=False,
        )

    # Stale guard: the remote commit is older than / equal to the last import.
    if reason is RefreshReason.STALE:
        return IdempotencyOutcome(
            action=RefreshAction.SKIP,
            reason=IdempotencyReason.STALE,
            advance_committed_anchor=False,
        )

    # Whether this branch of the comparator observed a strictly newer commit.
    # NEWER_CONTENT (newer + blob differs) and IDEMPOTENT (newer + blob same)
    # both mean "newer commit"; the checksum-fallback reasons mean "no
    # comparable timestamp", so there is no newer-commit anchor to advance.
    newer_commit = reason in (
        RefreshReason.NEWER_CONTENT,
        RefreshReason.IDEMPOTENT,
    )

    remote_sum = _normalise_checksum(remote_content_checksum)
    last_sum = _normalise_checksum(last_imported_content_checksum)

    # No comparable content checksum: defer to the comparator's verdict. The
    # blob-level decision already gated content identity as best it could.
    if remote_sum is None or last_sum is None:
        if decision.should_refresh:
            return IdempotencyOutcome(
                action=RefreshAction.REIMPORT,
                reason=IdempotencyReason.CONTENT_CHANGED,
                advance_committed_anchor=newer_commit,
            )
        return IdempotencyOutcome(
            action=RefreshAction.SKIP,
            reason=IdempotencyReason.UNCHANGED,
            advance_committed_anchor=False,
        )

    content_unchanged = remote_sum == last_sum

    if content_unchanged:
        # The defining RAR-2.4 case. A newer commit with identical content
        # advances the anchor without churning a version; without a newer
        # commit (checksum fallback) there is simply nothing to do.
        if newer_commit:
            return IdempotencyOutcome(
                action=RefreshAction.ADVANCE_ANCHOR_ONLY,
                reason=IdempotencyReason.UNCHANGED_CHECKSUM,
                advance_committed_anchor=True,
            )
        return IdempotencyOutcome(
            action=RefreshAction.SKIP,
            reason=IdempotencyReason.UNCHANGED,
            advance_committed_anchor=False,
        )

    # Content genuinely changed -> re-import. Advance the anchor when a newer
    # commit was observed (the fallback path has no timestamp to advance).
    return IdempotencyOutcome(
        action=RefreshAction.REIMPORT,
        reason=IdempotencyReason.CONTENT_CHANGED,
        advance_committed_anchor=newer_commit,
    )


def guard_refresh(
    *,
    remote_committed_at: TimestampInput,
    last_imported_committed_at: TimestampInput,
    remote_blob_sha: Optional[str],
    last_imported_blob_sha: Optional[str],
    remote_content_checksum: Optional[str],
    last_imported_content_checksum: Optional[str],
) -> IdempotencyOutcome:
    """Run the full RAR-2.2 + RAR-2.4 gate in one call (convenience wrapper).

    Composes :func:`evaluate_refresh` (commit-recency gating on ``blob_sha``)
    with :func:`evaluate_checksum_idempotency` (content-churn suppression on the
    REPO-8.3 content checksum) so a caller can get the final dispatch action from
    the raw freshness signals without threading the intermediate decision.

    Args:
        remote_committed_at: Committed-at of the remote file (datetime/ISO/None).
        last_imported_committed_at: Stored ``last_imported_committed_at`` anchor.
        remote_blob_sha: Remote blob SHA (the RAR-2.2 content-identity token).
        last_imported_blob_sha: Stored ``last_imported_blob_sha`` anchor.
        remote_content_checksum: REPO-8.3 content checksum of the remote file.
        last_imported_content_checksum: Content checksum at the last import.

    Returns:
        The :class:`IdempotencyOutcome` describing the action to take.
    """
    decision = evaluate_refresh(
        remote_committed_at=remote_committed_at,
        last_imported_committed_at=last_imported_committed_at,
        remote_checksum=remote_blob_sha,
        last_imported_checksum=last_imported_blob_sha,
    )
    return evaluate_checksum_idempotency(
        decision=decision,
        remote_content_checksum=remote_content_checksum,
        last_imported_content_checksum=last_imported_content_checksum,
    )
