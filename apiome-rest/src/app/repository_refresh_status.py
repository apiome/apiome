"""
Per-file refresh state machine for repository auto-refresh (RAR-2.3, #3520).

There was no materialized per-file refresh status to drive the sweep, the UI, or
divergence handling — status was implicit and uncomputable at a glance. This
module materializes it: a single ``RefreshStatus`` value derived from scan
recency vs the ``last_imported_*`` anchors (RAR-2.1), overlaid with the
operational signals an in-flight or just-finished refresh produces.

State machine (matches the roadmap, ``docs/ROADMAP_REPOSITORY_AUTOREFRESH.md``)::

    [*] --> up_to_date
    up_to_date --> stale:      newer commit detected
    stale --> refreshing:      sweep enqueues
    refreshing --> up_to_date:  success
    refreshing --> failed:      error
    refreshing --> diverged:    manual edit detected (RAR-4.4)
    failed --> refreshing:      retry
    diverged --> up_to_date:    resolved

The recency axis (``up-to-date`` vs ``stale``) is decided by the RAR-2.2
comparator (:func:`repository_refresh_comparator.evaluate_refresh`) so the two
modules cannot disagree about what "newer" means: a file is ``stale`` exactly
when the comparator would re-import it. The operational axis (``refreshing`` /
``failed`` / ``diverged``) is supplied by the caller from sweep bookkeeping and
the RAR-4.4 divergence check.

The function is deliberately pure and side-effect free so it can be evaluated
on demand — "recomputed on scan and on refresh completion" is satisfied simply
by calling it whenever the underlying inputs change (the scan refreshes the
remote recency columns; a finished refresh updates the ``last_imported_*``
anchors and clears/sets the operational flags).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .repository_refresh_comparator import TimestampInput, evaluate_refresh


class RefreshStatus(str, Enum):
    """The materialized refresh state of a single imported repository file.

    Values are the stable wire/display codes (kebab-case) surfaced to the UI and
    the sweep; they match the states in the roadmap state diagram.
    """

    #: The imported version reflects the latest source commit; nothing to do.
    UP_TO_DATE = "up-to-date"
    #: A newer source commit with changed content exists; awaiting refresh.
    STALE = "stale"
    #: A refresh is currently in flight for this file (sweep enqueued it).
    REFRESHING = "refreshing"
    #: The most recent refresh attempt errored; awaiting retry.
    FAILED = "failed"
    #: The imported version was hand-edited since import (RAR-4.4); held, not
    #: auto-overwritten, until a human resolves it.
    DIVERGED = "diverged"


def compute_refresh_status(
    *,
    remote_committed_at: TimestampInput = None,
    last_imported_committed_at: TimestampInput = None,
    remote_checksum: Optional[str] = None,
    last_imported_checksum: Optional[str] = None,
    is_refreshing: bool = False,
    last_refresh_failed: bool = False,
    diverged: bool = False,
) -> RefreshStatus:
    """Materialize the per-file refresh status (RAR-2.3).

    Combines two axes:

    * **Operational** — supplied by the caller from sweep/refresh bookkeeping:
      whether a refresh is in flight, whether the last attempt errored, and
      whether the imported version has diverged (RAR-4.4). These describe an
      explicit position in the refresh lifecycle and therefore take precedence
      over the derived recency axis.
    * **Recency** — derived from scan recency vs the ``last_imported_*`` anchors
      via the RAR-2.2 comparator. When no refresh is in flight and the file is
      neither diverged nor in a failed state, the status is ``stale`` exactly
      when the comparator would re-import the file, otherwise ``up-to-date``.

    Precedence (highest first), mirroring the state diagram's transitions:

    1. ``is_refreshing``      -> :attr:`RefreshStatus.REFRESHING` (in flight)
    2. ``diverged``           -> :attr:`RefreshStatus.DIVERGED` (safety hold)
    3. ``last_refresh_failed``-> :attr:`RefreshStatus.FAILED` (awaiting retry)
    4. comparator says refresh-> :attr:`RefreshStatus.STALE`
    5. otherwise              -> :attr:`RefreshStatus.UP_TO_DATE`

    ``diverged`` outranks ``failed`` because divergence is a content-safety hold
    that must not be masked by a transient error; both outrank the recency axis
    because they describe the outcome of an actual refresh attempt rather than a
    mere comparison.

    Args:
        remote_committed_at: Committed-at of the current remote file
            (datetime/ISO-8601/None) — the scan recency signal.
        last_imported_committed_at: Stored ``last_imported_committed_at`` anchor.
        remote_checksum: Current remote content identity (blob SHA / checksum).
        last_imported_checksum: Stored ``last_imported_blob_sha`` / checksum
            anchor captured at import time.
        is_refreshing: True when a refresh is currently enqueued/running.
        last_refresh_failed: True when the most recent refresh attempt errored
            and has not since succeeded.
        diverged: True when the imported version was hand-edited after import
            (RAR-4.4) and is held for review.

    Returns:
        The single :class:`RefreshStatus` for the file.
    """
    if is_refreshing:
        return RefreshStatus.REFRESHING
    if diverged:
        return RefreshStatus.DIVERGED
    if last_refresh_failed:
        return RefreshStatus.FAILED

    decision = evaluate_refresh(
        remote_committed_at=remote_committed_at,
        last_imported_committed_at=last_imported_committed_at,
        remote_checksum=remote_checksum,
        last_imported_checksum=last_imported_checksum,
    )
    return RefreshStatus.STALE if decision.should_refresh else RefreshStatus.UP_TO_DATE
