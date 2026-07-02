"""Refresh cadence policy tests (RAR-3.1, #3522).

Deterministic, DB-free fixtures over ``app.repository_refresh_cadence`` plus a
check that the config exposes the global floor / default knobs. They cover the
acceptance criteria: interval configurable per repo and globally, sub-floor
values clamped with a warning, and the default behaving as a ~5-minute refresh.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.repository_refresh_cadence import (
    DEFAULT_MIN_REFRESH_INTERVAL_SECONDS,
    DEFAULT_REFRESH_INTERVAL_SECONDS,
    is_repository_due,
    resolve_refresh_interval,
)

NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)


# --- resolve_refresh_interval ----------------------------------------------


def test_default_interval_is_five_minutes() -> None:
    """Unset cadence -> the ~5-minute default."""
    assert resolve_refresh_interval(None) == 300
    assert DEFAULT_REFRESH_INTERVAL_SECONDS == 300


def test_configured_interval_above_floor_is_preserved() -> None:
    """A sane per-repo value is used verbatim."""
    assert resolve_refresh_interval(600) == 600


def test_sub_floor_value_is_clamped_with_warning(caplog) -> None:
    """A value below the floor is clamped up and a warning is emitted."""
    with caplog.at_level(logging.WARNING):
        result = resolve_refresh_interval(10, floor_seconds=60)
    assert result == 60
    assert any("clamp" in r.message.lower() for r in caplog.records)


def test_non_positive_configured_value_falls_back_to_default() -> None:
    """Zero / negative per-repo values are treated as unset."""
    assert resolve_refresh_interval(0) == DEFAULT_REFRESH_INTERVAL_SECONDS
    assert resolve_refresh_interval(-5) == DEFAULT_REFRESH_INTERVAL_SECONDS


def test_custom_floor_and_default_are_honoured() -> None:
    """The floor and default are parameters (configurable globally)."""
    assert resolve_refresh_interval(30, floor_seconds=120) == 120
    assert resolve_refresh_interval(None, default_seconds=900) == 900


def test_floor_itself_cannot_drop_below_one_second() -> None:
    """A misconfigured floor of 0 / negative is itself clamped to 1s."""
    assert resolve_refresh_interval(0, floor_seconds=0, default_seconds=0) == 1
    assert resolve_refresh_interval(None, floor_seconds=-10, default_seconds=0) == 1


# --- is_repository_due ------------------------------------------------------


def test_never_refreshed_is_due() -> None:
    """A repo with no last_refreshed_at is always due."""
    assert is_repository_due(last_refreshed_at=None, interval_seconds=300, now=NOW) is True


def test_not_yet_elapsed_is_not_due() -> None:
    """Less than one interval since the last refresh -> not due."""
    last = NOW - timedelta(seconds=120)
    assert is_repository_due(last_refreshed_at=last, interval_seconds=300, now=NOW) is False


def test_elapsed_past_interval_is_due() -> None:
    """At least one interval elapsed -> due."""
    last = NOW - timedelta(seconds=301)
    assert is_repository_due(last_refreshed_at=last, interval_seconds=300, now=NOW) is True


def test_exactly_at_interval_is_due() -> None:
    """Boundary: elapsed == interval is due (>=)."""
    last = NOW - timedelta(seconds=300)
    assert is_repository_due(last_refreshed_at=last, interval_seconds=300, now=NOW) is True


def test_accepts_iso_string_timestamps() -> None:
    """ISO-8601 strings (with trailing Z) are accepted for both anchors."""
    assert (
        is_repository_due(
            last_refreshed_at="2026-06-21T11:50:00Z",
            interval_seconds=300,
            now="2026-06-21T12:00:00Z",
        )
        is True
    )


def test_naive_last_refreshed_assumed_utc() -> None:
    """A naive datetime is treated as UTC so the comparison is well defined."""
    last = datetime(2026, 6, 21, 11, 0, 0)  # naive
    assert is_repository_due(last_refreshed_at=last, interval_seconds=300, now=NOW) is True


# --- config knobs -----------------------------------------------------------


def test_config_exposes_cadence_floor_and_default() -> None:
    """The global floor / default are configurable via env (RAR-3.1)."""
    assert settings.refresh_default_interval_seconds == 300
    assert settings.refresh_min_interval_seconds == DEFAULT_MIN_REFRESH_INTERVAL_SECONDS
