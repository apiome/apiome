"""
Newer-than comparator for repository auto-refresh (RAR-2.2, #3519).

Re-import used to fire whenever ``content_checksum != last_imported_checksum``.
A checksum difference is **not** the same as "newer": reverting a file to older
content yields a different checksum and would re-import a *stale* version. The
request is to re-import only files genuinely **newer** than what the system last
imported.

This module is the pure decision function the auto-refresh dispatch (RAR-4.1)
calls per file. It is deliberately side-effect free and provider-agnostic so it
can be exercised by deterministic fixtures: callers pass the remote file's
freshness signals and the stored ``last_imported_*`` anchors (RAR-2.1), and it
returns a :class:`RefreshDecision`.

Decision table (matches the roadmap, ``docs/ROADMAP_REPOSITORY_AUTOREFRESH.md``)::

    committed_at newer + checksum diff  -> REFRESH  (newer content)
    committed_at newer + checksum same  -> SKIP     (idempotent, RAR-2.4)
    committed_at older / equal          -> SKIP     (stale guard)
    no timestamp available              -> fall back to checksum-changed

When timestamps are present the comparison is authoritative. When either side
lacks a parseable timestamp the comparator cannot prove recency, so it falls
back to the legacy checksum-changed behaviour (refresh iff the content identity
differs) rather than risk either clobbering with a stale file or missing a real
update.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Union

TimestampInput = Optional[Union[datetime, str]]


class RefreshReason(str, Enum):
    """Why the comparator reached its decision (stable codes for logging/audit)."""

    #: Remote commit is newer and the content differs -> re-import.
    NEWER_CONTENT = "newer-content"
    #: Remote commit is newer but the content is identical -> idempotent skip (RAR-2.4).
    IDEMPOTENT = "idempotent"
    #: Remote commit is older than or equal to the last import -> stale guard.
    STALE = "stale"
    #: No comparable timestamp; content differs -> refresh via checksum fallback.
    CHECKSUM_FALLBACK_CHANGED = "checksum-fallback-changed"
    #: No comparable timestamp; content identical -> skip via checksum fallback.
    CHECKSUM_FALLBACK_UNCHANGED = "checksum-fallback-unchanged"
    #: Nothing was ever imported for this lineage -> treat as a fresh import.
    NO_PRIOR_IMPORT = "no-prior-import"


@dataclass(frozen=True)
class RefreshDecision:
    """Outcome of the newer-than comparator for a single repository file.

    Attributes:
        should_refresh: True when the file should be re-imported.
        reason: The :class:`RefreshReason` code explaining the outcome.
        used_timestamp: True when the decision used the committed-at comparison;
            False when it fell back to checksum-only gating (or no prior import).
    """

    should_refresh: bool
    reason: RefreshReason
    used_timestamp: bool


def _parse_timestamp(value: TimestampInput) -> Optional[datetime]:
    """Coerce a committed-at value to a timezone-aware ``datetime`` or ``None``.

    Accepts an aware/naive :class:`datetime` or an ISO-8601 string (including the
    trailing ``Z`` UTC designator returned by the GitHub branch API). Naive
    datetimes are assumed to be UTC so comparisons are always well defined.
    Anything unparseable yields ``None``, which routes the caller to the
    checksum-only fallback.

    Args:
        value: A datetime, ISO-8601 string, or None.

    Returns:
        A timezone-aware datetime, or None when the value is missing/unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        # ``datetime.fromisoformat`` only learned to accept a trailing ``Z`` in
        # 3.11+, but normalising here keeps behaviour explicit and stable.
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalise_checksum(value: Optional[str]) -> Optional[str]:
    """Trim a content-identity token (blob SHA or checksum) to a comparable form."""
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def evaluate_refresh(
    *,
    remote_committed_at: TimestampInput,
    last_imported_committed_at: TimestampInput,
    remote_checksum: Optional[str],
    last_imported_checksum: Optional[str],
) -> RefreshDecision:
    """Decide whether a repository file should be re-imported (RAR-2.2).

    The comparator gates dispatch on commit recency, not raw checksum drift, so a
    revert to older content does not pull a stale spec. ``remote_checksum`` and
    ``last_imported_checksum`` are opaque content-identity tokens — in practice
    the file's ``blob_sha`` (or a content checksum); they only need to be equal
    when the content is unchanged and differ otherwise.

    Logic:

    * No prior import anchor at all (both stored timestamp and checksum absent)
      -> :attr:`RefreshReason.NO_PRIOR_IMPORT`, refresh.
    * Both committed-at timestamps parse -> authoritative comparison:
        * remote strictly newer + content differs -> refresh (NEWER_CONTENT)
        * remote strictly newer + content identical -> skip (IDEMPOTENT)
        * remote older or equal -> skip (STALE)
    * Either timestamp missing/unparseable -> checksum fallback: refresh iff the
      content identity differs.

    Args:
        remote_committed_at: Committed-at of the remote file (datetime/ISO/None).
        last_imported_committed_at: Stored ``last_imported_committed_at`` anchor.
        remote_checksum: Remote content identity (blob SHA / checksum), if known.
        last_imported_checksum: Stored content identity at last import, if known.

    Returns:
        A :class:`RefreshDecision` with the boolean verdict, a stable reason code,
        and whether the timestamp comparison (vs the fallback) was used.
    """
    remote_ts = _parse_timestamp(remote_committed_at)
    last_ts = _parse_timestamp(last_imported_committed_at)
    remote_sum = _normalise_checksum(remote_checksum)
    last_sum = _normalise_checksum(last_imported_checksum)

    # Nothing recorded for this lineage: there is no anchor to be "newer than",
    # so this is effectively a first import and should proceed.
    if last_ts is None and last_sum is None:
        return RefreshDecision(
            should_refresh=True,
            reason=RefreshReason.NO_PRIOR_IMPORT,
            used_timestamp=False,
        )

    content_differs = remote_sum != last_sum

    # Authoritative path: both timestamps comparable.
    if remote_ts is not None and last_ts is not None:
        if remote_ts > last_ts:
            if content_differs:
                return RefreshDecision(True, RefreshReason.NEWER_CONTENT, True)
            return RefreshDecision(False, RefreshReason.IDEMPOTENT, True)
        # Older or equal commit timestamp: never pull it (stale guard).
        return RefreshDecision(False, RefreshReason.STALE, True)

    # Fallback: no comparable timestamp -> legacy checksum-changed gating.
    if content_differs:
        return RefreshDecision(True, RefreshReason.CHECKSUM_FALLBACK_CHANGED, False)
    return RefreshDecision(False, RefreshReason.CHECKSUM_FALLBACK_UNCHANGED, False)
