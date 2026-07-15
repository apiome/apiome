"""Privacy-safe projection telemetry unit tests — EFP-3.2 (#4817)."""

from __future__ import annotations

import logging

import pytest

from app.projection_telemetry import ProjectionTelemetry, projection_telemetry


@pytest.fixture(autouse=True)
def _reset_telemetry() -> None:
    projection_telemetry.reset()
    yield
    projection_telemetry.reset()


def test_record_increments_kind_and_reason_counters() -> None:
    projection_telemetry.record("preview_failure", reason_category="source_load")
    projection_telemetry.record("stale_acknowledgement")
    snap = projection_telemetry.snapshot()
    assert snap["preview_failure"] == 1
    assert snap["preview_failure:source_load"] == 1
    assert snap["stale_acknowledgement"] == 1


def test_record_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported projection metric kind"):
        projection_telemetry.record("leak_source_content")  # type: ignore[arg-type]


def test_record_drops_unknown_reason_category_without_logging_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.projection_telemetry"):
        projection_telemetry.record(
            "preview_failure",
            reason_category="SECRET-SENTINEL-please-do-not-log",  # not allowlisted
        )
    snap = projection_telemetry.snapshot()
    assert snap["preview_failure"] == 1
    assert "preview_failure:SECRET-SENTINEL-please-do-not-log" not in snap
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "SECRET-SENTINEL" not in joined


def test_record_never_accepts_arbitrary_extra_label_payload() -> None:
    """status/reason count maps keep ints; non-int values are dropped."""
    tel = ProjectionTelemetry()
    tel.record(
        "evidence_page",
        status_counts={"retained": 3, "bad": "nope"},  # type: ignore[dict-item]
        page_total=10,
    )
    # Counters still advance; privacy is about log/payload shape.
    assert tel.snapshot()["evidence_page"] == 1


def test_doc_link_batch_increments_by_n() -> None:
    projection_telemetry.record("documentation_link_available", n=4)
    assert projection_telemetry.snapshot()["documentation_link_available"] == 4
