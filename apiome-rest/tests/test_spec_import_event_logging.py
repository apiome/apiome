"""REST surfacing of import benchmark/phase events as the import runs."""

from __future__ import annotations

import logging

from app.models import SpecImportEvent, SpecImportJobStatus
from app.spec_import_engine import (
    _JobRecord,
    _log_import_events,
    _take_new_import_events,
)


def _ev(eid: str, code: str, message: str = "m", level: str = "info") -> SpecImportEvent:
    return SpecImportEvent(id=eid, ts=0, level=level, code=code, message=message)


def _rec() -> _JobRecord:
    status = SpecImportJobStatus(job_id="j1", state="running", percent=0)
    return _JobRecord(tenant_slug="acme", job_id="j1", state="running", status=status)


def test_take_new_events_dedupes_across_snapshots() -> None:
    rec = _rec()
    s1 = SpecImportJobStatus(
        job_id="j1", state="running", percent=10,
        events=[_ev("a", "PHASE_TIMING"), _ev("b", "CLASS_CREATED")],
    )
    first = _take_new_import_events(rec, s1)
    assert [e.id for e in first] == ["a", "b"]

    # Next snapshot repeats a/b and adds c — only c is new.
    s2 = SpecImportJobStatus(
        job_id="j1", state="running", percent=20,
        events=[_ev("a", "PHASE_TIMING"), _ev("b", "CLASS_CREATED"), _ev("c", "BENCHMARK")],
    )
    second = _take_new_import_events(rec, s2)
    assert [e.id for e in second] == ["c"]


def test_log_import_events_routes_levels(caplog) -> None:
    events = [
        _ev("1", "PHASE_TIMING", "Phase phase:writeClasses completed in 4200ms"),
        _ev("2", "BENCHMARK", "Import timing — total 9000ms"),
        _ev("3", "DEBUG_PROPERTY", "noisy per-row"),
        _ev("4", "CLASS_FAILED", "boom", level="error"),
        _ev("5", "VERIFY_MISMATCHES", "warn", level="warn"),
    ]
    with caplog.at_level(logging.DEBUG, logger="app.spec_import_engine"):
        _log_import_events(events, "j1")

    by_msg = {r.message: r.levelno for r in caplog.records}
    # Benchmark phase events surface at INFO so they are easy to follow as the import runs.
    assert any("PHASE_TIMING" in m and lvl == logging.INFO for m, lvl in by_msg.items())
    assert any("BENCHMARK" in m and lvl == logging.INFO for m, lvl in by_msg.items())
    # High-cardinality per-row events stay at DEBUG.
    assert any("DEBUG_PROPERTY" in m and lvl == logging.DEBUG for m, lvl in by_msg.items())
    # Warnings/errors keep their severity regardless of code.
    assert any("CLASS_FAILED" in m and lvl == logging.ERROR for m, lvl in by_msg.items())
    assert any("VERIFY_MISMATCHES" in m and lvl == logging.WARNING for m, lvl in by_msg.items())
