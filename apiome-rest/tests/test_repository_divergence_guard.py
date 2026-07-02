"""Manual-edit divergence guard tests (RAR-4.4, #3530).

Deterministic, DB-free fixtures over ``app.repository_divergence_guard``. They
cover the roadmap decision rows (snapshot == current -> apply; snapshot !=
current -> diverged HOLD), all three acceptance criteria (a post-import manual
edit blocks the silent overwrite, the divergence is detectable/flagged, and the
default policy is hold-not-clobber), the RAR-4.5 OVERWRITE opt-out, the
fail-open NO_BASELINE path, the missing-current safety case, the content-checksum
helper (stability, whitespace tolerance, blank handling), and the raw-content
convenience wrapper.
"""

from app.repository_divergence_guard import (
    DivergenceDecision,
    DivergencePolicy,
    DivergenceReason,
    compute_content_checksum,
    evaluate_divergence,
    guard_divergence,
)

SNAPSHOT = "checksum-as-imported"
EDITED = "checksum-after-hand-edit"


# --- acceptance criteria ----------------------------------------------------


def test_post_import_manual_edit_blocks_silent_overwrite() -> None:
    """AC1: a post-import manual edit holds the refresh (no overwrite)."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=EDITED,
    )
    assert decision.diverged is True
    assert decision.should_hold is True  # the overwrite is blocked
    assert decision.reason is DivergenceReason.MANUAL_EDIT


def test_divergence_is_flagged_for_review() -> None:
    """AC2: a detected manual edit is reported (drives the ``diverged`` flag)."""
    decision = guard_divergence(
        post_import_content="openapi: 3.0.0\ninfo:\n  title: As imported\n",
        current_content="openapi: 3.0.0\ninfo:\n  title: Hand edited\n",
    )
    assert decision.diverged is True
    assert decision.should_hold is True


def test_default_policy_is_hold_not_clobber() -> None:
    """AC3: the default policy holds rather than clobbers."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=EDITED,
    )
    assert decision.policy is DivergencePolicy.HOLD
    assert decision.should_hold is True


# --- decision table ---------------------------------------------------------


def test_unchanged_version_applies_refresh() -> None:
    """Current content matches the snapshot -> safe to apply, not diverged."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=SNAPSHOT,
    )
    assert decision.diverged is False
    assert decision.should_hold is False
    assert decision.reason is DivergenceReason.UNCHANGED


def test_no_baseline_fails_open() -> None:
    """No post-import snapshot -> cannot prove an edit -> apply the refresh."""
    decision = evaluate_divergence(
        post_import_checksum=None,
        current_checksum=EDITED,
    )
    assert decision.diverged is False
    assert decision.should_hold is False
    assert decision.reason is DivergenceReason.NO_BASELINE


def test_blank_baseline_fails_open() -> None:
    """A whitespace-only snapshot is treated as no baseline."""
    decision = evaluate_divergence(
        post_import_checksum="   ",
        current_checksum=EDITED,
    )
    assert decision.reason is DivergenceReason.NO_BASELINE
    assert decision.should_hold is False


def test_missing_current_with_snapshot_holds() -> None:
    """Snapshot present but current content missing -> cannot confirm -> hold."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=None,
    )
    assert decision.diverged is True
    assert decision.should_hold is True
    assert decision.reason is DivergenceReason.MANUAL_EDIT


# --- RAR-4.5 policy override ------------------------------------------------


def test_overwrite_policy_detects_but_does_not_hold() -> None:
    """OVERWRITE policy still reports divergence but permits the clobber."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=EDITED,
        policy=DivergencePolicy.OVERWRITE,
    )
    assert decision.diverged is True  # divergence is always reported
    assert decision.should_hold is False  # but the refresh proceeds
    assert decision.reason is DivergenceReason.MANUAL_EDIT
    assert decision.policy is DivergencePolicy.OVERWRITE


def test_overwrite_policy_unchanged_still_applies() -> None:
    """OVERWRITE policy is a no-op when there is no manual edit."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT,
        current_checksum=SNAPSHOT,
        policy=DivergencePolicy.OVERWRITE,
    )
    assert decision.diverged is False
    assert decision.should_hold is False
    assert decision.reason is DivergenceReason.UNCHANGED


# --- content checksum helper ------------------------------------------------


def test_checksum_is_stable_and_hex_sha256() -> None:
    """The checksum is a deterministic 64-char lowercase hex SHA-256 digest."""
    a = compute_content_checksum("some version content")
    b = compute_content_checksum("some version content")
    assert a == b
    assert a is not None and len(a) == 64
    assert a == a.lower()
    assert all(c in "0123456789abcdef" for c in a)


def test_checksum_distinguishes_different_content() -> None:
    """Different content yields different checksums."""
    assert compute_content_checksum("alpha") != compute_content_checksum("beta")


def test_checksum_trims_surrounding_whitespace() -> None:
    """An incidental trailing newline does not read as a different content."""
    assert compute_content_checksum("payload") == compute_content_checksum(
        "  payload\n"
    )


def test_checksum_blank_and_none_are_none() -> None:
    """None or whitespace-only content has no checksum (routes to NO_BASELINE)."""
    assert compute_content_checksum(None) is None
    assert compute_content_checksum("") is None
    assert compute_content_checksum("   \n\t") is None


# --- raw-content convenience wrapper ----------------------------------------


def test_guard_divergence_holds_on_real_edit() -> None:
    """The raw-content wrapper hashes both sides and holds on a real edit."""
    decision = guard_divergence(
        post_import_content="title: Original",
        current_content="title: Edited by hand",
    )
    assert decision.diverged is True
    assert decision.should_hold is True


def test_guard_divergence_applies_on_whitespace_only_change() -> None:
    """A whitespace-only difference is not a divergence (same trimmed content)."""
    decision = guard_divergence(
        post_import_content="title: Original",
        current_content="title: Original\n",
    )
    assert decision.diverged is False
    assert decision.reason is DivergenceReason.UNCHANGED


def test_guard_divergence_no_snapshot_applies() -> None:
    """No captured snapshot content -> NO_BASELINE -> apply."""
    decision = guard_divergence(
        post_import_content=None,
        current_content="title: Anything",
    )
    assert decision.diverged is False
    assert decision.reason is DivergenceReason.NO_BASELINE


# --- shape / wire codes -----------------------------------------------------


def test_decision_is_frozen() -> None:
    """The decision is an immutable value object."""
    decision = evaluate_divergence(
        post_import_checksum=SNAPSHOT, current_checksum=SNAPSHOT
    )
    assert isinstance(decision, DivergenceDecision)
    try:
        decision.diverged = True  # type: ignore[misc]
    except AttributeError:
        pass
    else:  # pragma: no cover - frozen dataclass must reject mutation
        raise AssertionError("DivergenceDecision should be immutable")


def test_stable_wire_codes() -> None:
    """Reason and policy codes are the stable values the UI/audit consume."""
    assert DivergenceReason.NO_BASELINE.value == "no-baseline"
    assert DivergenceReason.UNCHANGED.value == "unchanged"
    assert DivergenceReason.MANUAL_EDIT.value == "manual-edit"
    assert DivergencePolicy.HOLD.value == "hold"
    assert DivergencePolicy.OVERWRITE.value == "overwrite"
