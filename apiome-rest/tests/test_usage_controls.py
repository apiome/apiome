"""The RDG-5.4 rules that need no database or HTTP (#5789).

* retention can only be lowered, and a refusal names the cap;
* the purge applies the smaller of the cap and the setting, and a forever cap takes any setting;
* a body-sample window respects the 5 % / 100 % rate caps and the 7-day window, and opening one
  takes the exact acknowledgement sentence;
* export rows carry exactly the documented columns, and a CSV cell is never a formula.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

import pytest

from app.usage_controls import (
    AGENT_BODY_CAPTURE_MAX_RATE,
    BODY_SAMPLE_ACKNOWLEDGEMENT,
    BODY_SAMPLE_MAX_RATE,
    CODE_ACK_REQUIRED,
    CODE_BODY_WINDOW_INVALID,
    CODE_RETENTION_ABOVE_CAP,
    EXPORT_COLUMNS,
    BodySampleWindow,
    RetentionDays,
    RetentionUpdate,
    UsageControlsError,
    body_samples,
    check_body_window,
    check_retention,
    csv_header,
    csv_row,
    effective_days,
    export_row,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
PAID = RetentionDays(hourly_days=30, rollup_days=395)


# ---------------------------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cap", "setting", "expected"),
    [(30, None, 30), (30, 7, 7), (30, 90, 30), (-1, None, -1), (-1, 14, 14)],
)
def test_the_purge_applies_the_smaller_of_cap_and_setting(cap: int, setting: int, expected: int) -> None:
    assert effective_days(cap, setting) == expected


def test_a_value_within_the_caps_is_accepted() -> None:
    check_retention(RetentionUpdate(hourly_days=30, rollup_days=1), PAID)
    check_retention(RetentionUpdate(), PAID)


@pytest.mark.parametrize(
    ("update", "key", "cap"),
    [
        (RetentionUpdate(hourly_days=31), "usage_hourly_retention_days", 30),
        (RetentionUpdate(rollup_days=400), "usage_rollup_retention_days", 395),
    ],
)
def test_a_value_above_the_cap_is_refused_with_the_cap_named(update: RetentionUpdate, key: str, cap: int) -> None:
    with pytest.raises(UsageControlsError) as refused:
        check_retention(update, PAID)
    assert refused.value.code == CODE_RETENTION_ABOVE_CAP
    assert refused.value.status == 422
    assert key in refused.value.message and f"at most {cap} days" in refused.value.message


def test_a_forever_cap_accepts_any_positive_value() -> None:
    check_retention(
        RetentionUpdate(hourly_days=10_000, rollup_days=10_000), RetentionDays(hourly_days=-1, rollup_days=-1)
    )


def test_retention_below_one_day_is_a_validation_error() -> None:
    with pytest.raises(ValueError):
        RetentionUpdate(hourly_days=0)


# ---------------------------------------------------------------------------------------------
# Body samples
# ---------------------------------------------------------------------------------------------


def _window(rate: float, *, hours: float = 24, ack: str = BODY_SAMPLE_ACKNOWLEDGEMENT) -> BodySampleWindow:
    return BodySampleWindow(rate=rate, until=NOW + timedelta(hours=hours), acknowledgement=ack)


def test_closing_a_window_needs_nothing_else() -> None:
    assert check_body_window(BodySampleWindow(rate=0), max_rate=BODY_SAMPLE_MAX_RATE, now=NOW) is None


def test_an_acknowledged_window_within_the_caps_is_accepted() -> None:
    until = check_body_window(_window(0.05, hours=7 * 24), max_rate=BODY_SAMPLE_MAX_RATE, now=NOW)
    assert until == NOW + timedelta(days=7)


@pytest.mark.parametrize(
    ("window", "max_rate", "fragment"),
    [
        (_window(0.06), BODY_SAMPLE_MAX_RATE, "at most 0.05"),
        (_window(0.5, hours=7 * 24 + 1), AGENT_BODY_CAPTURE_MAX_RATE, "7 days"),
        (_window(0.01, hours=-1), BODY_SAMPLE_MAX_RATE, "future"),
        (BodySampleWindow(rate=0.01, acknowledgement=BODY_SAMPLE_ACKNOWLEDGEMENT), BODY_SAMPLE_MAX_RATE, "until"),
    ],
)
def test_a_window_outside_the_caps_is_refused(window: BodySampleWindow, max_rate: float, fragment: str) -> None:
    with pytest.raises(UsageControlsError) as refused:
        check_body_window(window, max_rate=max_rate, now=NOW)
    assert refused.value.code == CODE_BODY_WINDOW_INVALID
    assert fragment in refused.value.message


def test_a_toolset_may_capture_more_than_a_source() -> None:
    assert check_body_window(_window(0.5), max_rate=AGENT_BODY_CAPTURE_MAX_RATE, now=NOW) is not None


@pytest.mark.parametrize("ack", ["", "I understand", "yes", BODY_SAMPLE_ACKNOWLEDGEMENT.lower()])
def test_opening_a_window_takes_the_exact_sentence(ack: str) -> None:
    with pytest.raises(UsageControlsError) as refused:
        check_body_window(_window(0.01, ack=ack), max_rate=BODY_SAMPLE_MAX_RATE, now=NOW)
    assert refused.value.code == CODE_ACK_REQUIRED
    assert BODY_SAMPLE_ACKNOWLEDGEMENT in refused.value.message


def test_a_naive_until_is_read_as_utc() -> None:
    naive = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    window = BodySampleWindow(rate=0.01, until=naive, acknowledgement=BODY_SAMPLE_ACKNOWLEDGEMENT)
    assert check_body_window(window, max_rate=BODY_SAMPLE_MAX_RATE, now=NOW) == NOW + timedelta(hours=1)


def test_a_window_is_open_only_with_a_rate_and_a_future_until() -> None:
    assert body_samples(0.01, NOW + timedelta(hours=1), max_rate=0.05, now=NOW).open is True
    assert body_samples(0.01, NOW - timedelta(hours=1), max_rate=0.05, now=NOW).open is False
    assert body_samples(0, None, max_rate=0.05, now=NOW).open is False
    described = body_samples("0.0200", None, max_rate=0.05, now=NOW)
    assert described.rate == 0.02 and described.max_rate == 0.05 and described.max_window_days == 7


# ---------------------------------------------------------------------------------------------
# Export rows
# ---------------------------------------------------------------------------------------------

_RAW = {
    "day": date(2026, 11, 15),
    "environment": "prod",
    "source_id": "s1",
    "source_kind": "otlp",
    "version_id": None,
    "version_label": "=HYPERLINK(1)",
    "operation_key": "/paths/~1pets/get",
    "status_code": 200,
    "consumer": "billing-service",
    "calls": 12,
    "errors": 0,
    "latency_sum_ms": 36,
    "latency_max_ms": 9,
    "request_bytes": 0,
    "response_bytes": 100,
    "value_hmac": "never",
}


def test_an_export_row_has_exactly_the_documented_columns() -> None:
    row = export_row(_RAW)
    assert tuple(row) == EXPORT_COLUMNS
    assert row["day"] == "2026-11-15" and row["calls"] == 12 and "value_hmac" not in row


def test_a_csv_cell_is_never_a_formula() -> None:
    lines = csv_header() + csv_row(export_row(_RAW))
    header, values = list(csv.reader(io.StringIO(lines)))
    assert tuple(header) == EXPORT_COLUMNS
    assert values[header.index("version_label")] == "'=HYPERLINK(1)"
    assert values[header.index("calls")] == "12"
    assert values[header.index("version_id")] == ""
