"""Checksum idempotency guard tests (RAR-2.4, #3521).

Deterministic, DB-free fixtures over
``app.repository_checksum_idempotency``. They cover the roadmap decision row
(``newer commit + checksum unchanged -> SKIP``), both acceptance criteria, the
churn-suppression case the ticket exists for (cosmetic blob change with an
unchanged content checksum), and the defer-to-comparator behaviour when a content
checksum is unavailable.
"""

from app.repository_checksum_idempotency import (
    IdempotencyReason,
    RefreshAction,
    evaluate_checksum_idempotency,
    guard_refresh,
)
from app.repository_refresh_comparator import (
    RefreshDecision,
    RefreshReason,
    evaluate_refresh,
)

OLD = "2026-06-20T10:00:00Z"
NEW = "2026-06-21T10:00:00Z"


# --- acceptance criteria ----------------------------------------------------


def test_newer_commit_identical_content_creates_no_version() -> None:
    """AC1: a newer commit with identical content produces no new version."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-new",  # blob changed (cosmetic commit)
        last_imported_blob_sha="blob-old",
        remote_content_checksum="content-same",
        last_imported_content_checksum="content-same",
    )
    assert outcome.action is RefreshAction.ADVANCE_ANCHOR_ONLY
    assert outcome.action is not RefreshAction.REIMPORT


def test_newer_commit_identical_content_marks_unchanged_and_advances() -> None:
    """AC2: the file is marked unchanged_checksum and the anchor is advanced."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum="content-same",
        last_imported_content_checksum="content-same",
    )
    assert outcome.reason is IdempotencyReason.UNCHANGED_CHECKSUM
    assert outcome.advance_committed_anchor is True


# --- the roadmap decision row + its complement ------------------------------


def test_newer_commit_changed_content_reimports() -> None:
    """Newer commit + content checksum differs -> REIMPORT."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum="content-new",
        last_imported_content_checksum="content-old",
    )
    assert outcome.action is RefreshAction.REIMPORT
    assert outcome.reason is IdempotencyReason.CONTENT_CHANGED
    assert outcome.advance_committed_anchor is True


def test_newer_commit_same_blob_same_content_advances_only() -> None:
    """RAR-2.2 IDEMPOTENT (newer + same blob) is still an anchor advance."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-same",
        last_imported_blob_sha="blob-same",
        remote_content_checksum="content-same",
        last_imported_content_checksum="content-same",
    )
    assert outcome.action is RefreshAction.ADVANCE_ANCHOR_ONLY
    assert outcome.reason is IdempotencyReason.UNCHANGED_CHECKSUM
    assert outcome.advance_committed_anchor is True


def test_older_commit_skips_stale() -> None:
    """Older / equal commit -> SKIP (stale guard), no anchor advance."""
    outcome = guard_refresh(
        remote_committed_at=OLD,
        last_imported_committed_at=NEW,
        remote_blob_sha="blob-x",
        last_imported_blob_sha="blob-y",
        remote_content_checksum="content-x",
        last_imported_content_checksum="content-y",
    )
    assert outcome.action is RefreshAction.SKIP
    assert outcome.reason is IdempotencyReason.STALE
    assert outcome.advance_committed_anchor is False


def test_first_import_reimports() -> None:
    """No prior import anchor -> REIMPORT (first import)."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=None,
        remote_blob_sha="blob-new",
        last_imported_blob_sha=None,
        remote_content_checksum="content-new",
        last_imported_content_checksum=None,
    )
    assert outcome.action is RefreshAction.REIMPORT
    assert outcome.reason is IdempotencyReason.FIRST_IMPORT
    assert outcome.advance_committed_anchor is False


# --- guard operating directly on a RefreshDecision -------------------------


def test_guard_on_newer_content_decision_unchanged_checksum() -> None:
    """A NEWER_CONTENT decision with an unchanged checksum downgrades to advance."""
    decision = RefreshDecision(True, RefreshReason.NEWER_CONTENT, True)
    outcome = evaluate_checksum_idempotency(
        decision=decision,
        remote_content_checksum="same",
        last_imported_content_checksum="same",
    )
    assert outcome.action is RefreshAction.ADVANCE_ANCHOR_ONLY
    assert outcome.reason is IdempotencyReason.UNCHANGED_CHECKSUM


def test_guard_on_newer_content_decision_changed_checksum() -> None:
    """A NEWER_CONTENT decision with a changed checksum re-imports."""
    decision = RefreshDecision(True, RefreshReason.NEWER_CONTENT, True)
    outcome = evaluate_checksum_idempotency(
        decision=decision,
        remote_content_checksum="a",
        last_imported_content_checksum="b",
    )
    assert outcome.action is RefreshAction.REIMPORT
    assert outcome.reason is IdempotencyReason.CONTENT_CHANGED


# --- defer-to-comparator when content checksum is unavailable --------------


def test_missing_remote_checksum_defers_to_comparator_refresh() -> None:
    """No remote content checksum + comparator says refresh -> REIMPORT."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum=None,
        last_imported_content_checksum="content-old",
    )
    assert outcome.action is RefreshAction.REIMPORT
    assert outcome.reason is IdempotencyReason.CONTENT_CHANGED
    # The commit was still newer, so the anchor advances.
    assert outcome.advance_committed_anchor is True


def test_missing_checksum_defers_to_comparator_skip() -> None:
    """No content checksum + comparator says skip (idempotent) -> SKIP/advance.

    The comparator returns IDEMPOTENT (newer commit, same blob) and there is no
    content checksum to refine with, so the guard defers: nothing to re-import,
    but the newer commit still advances the anchor.
    """
    decision = evaluate_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_checksum="blob-same",
        last_imported_checksum="blob-same",
    )
    assert decision.reason is RefreshReason.IDEMPOTENT
    outcome = evaluate_checksum_idempotency(
        decision=decision,
        remote_content_checksum=None,
        last_imported_content_checksum=None,
    )
    assert outcome.action is RefreshAction.SKIP
    assert outcome.reason is IdempotencyReason.UNCHANGED
    assert outcome.advance_committed_anchor is False


def test_blank_checksum_treated_as_missing() -> None:
    """Whitespace-only checksums are normalised to missing and defer."""
    outcome = guard_refresh(
        remote_committed_at=NEW,
        last_imported_committed_at=OLD,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum="   ",
        last_imported_content_checksum="content-old",
    )
    # Defers to the comparator (blob differs + newer) -> REIMPORT.
    assert outcome.action is RefreshAction.REIMPORT


# --- checksum-fallback path (no comparable timestamp) ----------------------


def test_fallback_changed_blob_but_unchanged_content_advances_nothing() -> None:
    """No timestamp + blob differs but content checksum same -> SKIP unchanged.

    Without a comparable commit timestamp there is no newer-commit anchor to
    advance, so an unchanged content checksum is simply a no-op skip rather than
    an anchor advance.
    """
    outcome = guard_refresh(
        remote_committed_at=None,
        last_imported_committed_at=None,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum="content-same",
        last_imported_content_checksum="content-same",
    )
    assert outcome.action is RefreshAction.SKIP
    assert outcome.reason is IdempotencyReason.UNCHANGED
    assert outcome.advance_committed_anchor is False


def test_fallback_changed_content_reimports_without_advancing() -> None:
    """No timestamp + content checksum differs -> REIMPORT, no anchor advance."""
    outcome = guard_refresh(
        remote_committed_at=None,
        last_imported_committed_at=None,
        remote_blob_sha="blob-new",
        last_imported_blob_sha="blob-old",
        remote_content_checksum="content-new",
        last_imported_content_checksum="content-old",
    )
    assert outcome.action is RefreshAction.REIMPORT
    assert outcome.reason is IdempotencyReason.CONTENT_CHANGED
    assert outcome.advance_committed_anchor is False


# --- stable wire values -----------------------------------------------------


def test_action_and_reason_wire_values_are_stable() -> None:
    """Stable kebab-case codes for logging/audit/UI."""
    assert RefreshAction.REIMPORT.value == "reimport"
    assert RefreshAction.ADVANCE_ANCHOR_ONLY.value == "advance-anchor-only"
    assert RefreshAction.SKIP.value == "skip"
    assert IdempotencyReason.UNCHANGED_CHECKSUM.value == "unchanged-checksum"
    assert IdempotencyReason.CONTENT_CHANGED.value == "content-changed"
    assert IdempotencyReason.FIRST_IMPORT.value == "first-import"
    assert IdempotencyReason.STALE.value == "stale"
    assert IdempotencyReason.UNCHANGED.value == "unchanged"
