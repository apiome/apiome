"""Newer-than comparator decision tests (RAR-2.2, #3519).

These are deterministic, DB-free fixtures over
``app.repository_refresh_comparator.evaluate_refresh``. They cover every row of
the roadmap decision table plus the two acceptance criteria that motivate the
ticket:

  * Reverting a file to older content does NOT trigger re-import.
  * Forward edits DO trigger re-import.
"""

from datetime import datetime, timezone

import pytest

from app.repository_refresh_comparator import (
    RefreshReason,
    evaluate_refresh,
)

OLD = "2026-06-20T10:00:00Z"
NEW = "2026-06-21T10:00:00Z"


# --- decision table: the four roadmap rows ---------------------------------


def test_newer_commit_changed_content_refreshes() -> None:
    """Row 1: committed_at newer + checksum diff -> REFRESH."""
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_checksum="blob-new",
        last_imported_checksum="blob-old",
    )
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.NEWER_CONTENT
    assert decision.used_timestamp is True


def test_newer_commit_same_content_skips_idempotent() -> None:
    """Row 2: committed_at newer + checksum same -> SKIP (idempotency)."""
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_checksum="blob-same",
        last_imported_checksum="blob-same",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.IDEMPOTENT
    assert decision.used_timestamp is True


def test_older_commit_skips_stale_even_with_different_checksum() -> None:
    """Row 3a: committed_at older -> SKIP (stale guard), regardless of checksum.

    This is the core bug the ticket fixes: a revert changes the checksum but the
    commit is older, so it must not be pulled.
    """
    decision = evaluate_refresh(
        remote_committed_at=OLD,
        last_imported_committed_at=NEW,
        remote_checksum="blob-reverted",
        last_imported_checksum="blob-current",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.STALE
    assert decision.used_timestamp is True


def test_equal_commit_skips_stale() -> None:
    """Row 3b: committed_at equal -> SKIP (stale guard)."""
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=NEW,
        remote_checksum="blob-x",
        last_imported_checksum="blob-y",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.STALE


def test_no_timestamp_falls_back_to_checksum_changed() -> None:
    """Row 4a: no timestamp + checksum diff -> REFRESH via fallback."""
    decision = evaluate_refresh(
        remote_committed_at=None,
        last_imported_committed_at=None,
        remote_checksum="blob-new",
        last_imported_checksum="blob-old",
    )
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.CHECKSUM_FALLBACK_CHANGED
    assert decision.used_timestamp is False


def test_no_timestamp_falls_back_to_checksum_unchanged() -> None:
    """Row 4b: no timestamp + checksum same -> SKIP via fallback.

    A prior checksum exists (so this is not a first import) but no comparable
    timestamp does, so the legacy checksum-only gating applies.
    """
    decision = evaluate_refresh(
        remote_committed_at=None,
        last_imported_committed_at=None,
        remote_checksum="blob-same",
        last_imported_checksum="blob-same",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.CHECKSUM_FALLBACK_UNCHANGED
    assert decision.used_timestamp is False


# --- acceptance criteria ----------------------------------------------------


def test_acceptance_revert_to_older_content_does_not_reimport() -> None:
    """AC: reverting a file to older content does NOT trigger re-import."""
    # The system last imported the NEW commit; the remote now points back at the
    # OLD commit's content (a revert), which carries the OLD committed-at.
    decision = evaluate_refresh(
        remote_committed_at=OLD,
        last_imported_committed_at=NEW,
        remote_checksum="content-v1",
        last_imported_checksum="content-v2",
    )
    assert decision.should_refresh is False


def test_acceptance_forward_edit_triggers_reimport() -> None:
    """AC: forward edits DO trigger re-import."""
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_checksum="content-v2",
        last_imported_checksum="content-v1",
    )
    assert decision.should_refresh is True


# --- input shape handling ---------------------------------------------------


def test_accepts_datetime_objects() -> None:
    """Datetime anchors (as returned from the DB) compare like ISO strings."""
    decision = evaluate_refresh(
        remote_committed_at=datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        last_imported_committed_at=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
        remote_checksum="b",
        last_imported_checksum="a",
    )
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.NEWER_CONTENT


def test_naive_datetime_treated_as_utc() -> None:
    """A naive datetime anchor is assumed UTC and still compares cleanly."""
    decision = evaluate_refresh(
        remote_committed_at=datetime(2026, 6, 19, 10, 0),  # naive, older
        last_imported_committed_at="2026-06-20T10:00:00Z",
        remote_checksum="b",
        last_imported_checksum="a",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.STALE


def test_mixed_timezone_offsets_compare_correctly() -> None:
    """Equal instants expressed in different offsets are treated as equal."""
    decision = evaluate_refresh(
        # 10:00Z == 06:00-04:00 -> same instant -> not newer -> stale guard.
        remote_committed_at="2026-06-20T06:00:00-04:00",
        last_imported_committed_at="2026-06-20T10:00:00Z",
        remote_checksum="b",
        last_imported_checksum="a",
    )
    assert decision.should_refresh is False
    assert decision.reason is RefreshReason.STALE


def test_unparseable_timestamp_uses_fallback() -> None:
    """A garbage timestamp string routes to the checksum fallback, not a crash."""
    decision = evaluate_refresh(
        remote_committed_at="not-a-date",
        last_imported_committed_at=OLD,
        remote_checksum="b",
        last_imported_checksum="a",
    )
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.CHECKSUM_FALLBACK_CHANGED
    assert decision.used_timestamp is False


def test_blank_strings_are_treated_as_missing() -> None:
    """Empty/whitespace timestamp and checksum tokens normalise to None."""
    # Blank timestamps -> no comparable timestamp; blank checksums both -> equal.
    decision = evaluate_refresh(
        remote_committed_at="   ",
        last_imported_committed_at=OLD,
        remote_checksum="   ",
        last_imported_checksum="blob-old",
    )
    # remote checksum normalises to None, last is "blob-old" -> differ -> refresh.
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.CHECKSUM_FALLBACK_CHANGED


# --- first-import / missing-anchor handling ---------------------------------


def test_no_prior_import_anchor_refreshes() -> None:
    """With no stored timestamp AND no stored checksum, treat as a fresh import."""
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=None,
        remote_checksum="blob-new",
        last_imported_checksum=None,
    )
    assert decision.should_refresh is True
    assert decision.reason is RefreshReason.NO_PRIOR_IMPORT
    assert decision.used_timestamp is False


def test_prior_checksum_without_timestamp_is_not_first_import() -> None:
    """A stored checksum but no stored timestamp is a real prior import (fallback)."""
    decision = evaluate_refresh(
        remote_committed_at=None,
        last_imported_committed_at=None,
        remote_checksum="blob-same",
        last_imported_checksum="blob-same",
    )
    assert decision.reason is RefreshReason.CHECKSUM_FALLBACK_UNCHANGED


@pytest.mark.parametrize(
    "remote_ts,last_ts,remote_sum,last_sum,expected",
    [
        (NEW, OLD, "b", "a", True),   # newer + changed
        (NEW, OLD, "a", "a", False),  # newer + same
        (OLD, NEW, "b", "a", False),  # older + changed (revert)
        (NEW, NEW, "b", "a", False),  # equal
    ],
)
def test_decision_table_matrix(remote_ts, last_ts, remote_sum, last_sum, expected) -> None:
    """Compact matrix asserting the verdict for every roadmap decision row."""
    decision = evaluate_refresh(
        remote_committed_at=remote_ts,
        last_imported_committed_at=last_ts,
        remote_checksum=remote_sum,
        last_imported_checksum=last_sum,
    )
    assert decision.should_refresh is expected
