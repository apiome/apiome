"""Per-file refresh state machine tests (RAR-2.3, #3520).

Deterministic, DB-free fixtures over
``app.repository_refresh_status.compute_refresh_status``. They cover:

  * The recency axis (up-to-date vs stale), delegated to the RAR-2.2 comparator.
  * The operational axis (refreshing / failed / diverged).
  * The documented precedence between the two axes.
  * That every roadmap state is reachable.
"""

from datetime import datetime, timezone

from app.repository_refresh_status import RefreshStatus, compute_refresh_status

OLD = "2026-06-20T10:00:00Z"
NEW = "2026-06-21T10:00:00Z"


# --- recency axis: up-to-date vs stale -------------------------------------


def test_newer_changed_content_is_stale() -> None:
    """A newer remote commit with changed content materializes as stale."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="blob-new",
            last_imported_checksum="blob-old",
        )
        is RefreshStatus.STALE
    )


def test_newer_same_content_is_up_to_date() -> None:
    """Newer commit but identical content is idempotent -> up-to-date."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="blob-same",
            last_imported_checksum="blob-same",
        )
        is RefreshStatus.UP_TO_DATE
    )


def test_older_remote_is_up_to_date() -> None:
    """An older/equal remote commit never makes a file stale (stale guard)."""
    assert (
        compute_refresh_status(
            remote_committed_at=OLD,
            last_imported_committed_at=NEW,
            remote_checksum="blob-old",
            last_imported_checksum="blob-new",
        )
        is RefreshStatus.UP_TO_DATE
    )


def test_equal_recency_same_content_is_up_to_date() -> None:
    """Same commit and content is the steady state -> up-to-date."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=NEW,
            remote_checksum="blob-x",
            last_imported_checksum="blob-x",
        )
        is RefreshStatus.UP_TO_DATE
    )


def test_checksum_fallback_changed_is_stale() -> None:
    """No comparable timestamp + changed content -> stale (checksum fallback)."""
    assert (
        compute_refresh_status(
            remote_committed_at=None,
            last_imported_committed_at=None,
            remote_checksum="blob-new",
            last_imported_checksum="blob-old",
        )
        is RefreshStatus.STALE
    )


def test_checksum_fallback_unchanged_is_up_to_date() -> None:
    """No comparable timestamp + identical content -> up-to-date."""
    assert (
        compute_refresh_status(
            remote_committed_at=None,
            last_imported_committed_at=None,
            remote_checksum="blob-same",
            last_imported_checksum="blob-same",
        )
        is RefreshStatus.UP_TO_DATE
    )


def test_accepts_datetime_inputs() -> None:
    """The recency axis accepts datetime objects, not only ISO strings."""
    older = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
    assert (
        compute_refresh_status(
            remote_committed_at=newer,
            last_imported_committed_at=older,
            remote_checksum="b2",
            last_imported_checksum="b1",
        )
        is RefreshStatus.STALE
    )


# --- operational axis -------------------------------------------------------


def test_in_flight_refresh_is_refreshing() -> None:
    """An enqueued/running refresh reports refreshing."""
    assert (
        compute_refresh_status(is_refreshing=True)
        is RefreshStatus.REFRESHING
    )


def test_last_attempt_error_is_failed() -> None:
    """A file whose last refresh attempt errored reports failed."""
    assert (
        compute_refresh_status(last_refresh_failed=True)
        is RefreshStatus.FAILED
    )


def test_diverged_flag_is_diverged() -> None:
    """A hand-edited (diverged) file is held in the diverged state (RAR-4.4)."""
    assert compute_refresh_status(diverged=True) is RefreshStatus.DIVERGED


# --- precedence between the axes -------------------------------------------


def test_refreshing_outranks_diverged_failed_and_recency() -> None:
    """In-flight refresh wins over every other signal."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="blob-new",
            last_imported_checksum="blob-old",
            is_refreshing=True,
            last_refresh_failed=True,
            diverged=True,
        )
        is RefreshStatus.REFRESHING
    )


def test_diverged_outranks_failed_and_recency() -> None:
    """Divergence is a safety hold that outranks a failed attempt and staleness."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="blob-new",
            last_imported_checksum="blob-old",
            last_refresh_failed=True,
            diverged=True,
        )
        is RefreshStatus.DIVERGED
    )


def test_failed_outranks_recency() -> None:
    """A failed attempt is surfaced over a derived stale/up-to-date verdict."""
    assert (
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="blob-new",
            last_imported_checksum="blob-old",
            last_refresh_failed=True,
        )
        is RefreshStatus.FAILED
    )


# --- reachability + wire values --------------------------------------------


def test_all_states_reachable() -> None:
    """Every roadmap state is producible from some input combination."""
    produced = {
        compute_refresh_status(is_refreshing=True),
        compute_refresh_status(diverged=True),
        compute_refresh_status(last_refresh_failed=True),
        compute_refresh_status(
            remote_committed_at=NEW,
            last_imported_committed_at=OLD,
            remote_checksum="b2",
            last_imported_checksum="b1",
        ),
        compute_refresh_status(
            remote_committed_at=OLD,
            last_imported_committed_at=NEW,
            remote_checksum="b1",
            last_imported_checksum="b2",
        ),
    }
    assert produced == set(RefreshStatus)


def test_status_wire_values_are_stable_kebab_case() -> None:
    """The display/wire codes are the kebab-case strings the UI keys on."""
    assert RefreshStatus.UP_TO_DATE.value == "up-to-date"
    assert RefreshStatus.STALE.value == "stale"
    assert RefreshStatus.REFRESHING.value == "refreshing"
    assert RefreshStatus.FAILED.value == "failed"
    assert RefreshStatus.DIVERGED.value == "diverged"
