"""Unit tests for the in-process import-source job pipeline (MFI-1.2, #3734).

Exercise :func:`app.import_source_pipeline.run_adapter_import_job` directly against
the no-op ``sample`` adapter (and small stub adapters), independent of the REST job
engine, so the parse → normalize → version → lint state machine, its snapshots, and
its failure/cancel handling are covered without spawning a worker.
"""

from __future__ import annotations

import base64
from typing import Any, List, Optional
from unittest.mock import patch

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.import_source import (
    NO_MATCH,
    DetectionInput,
    DetectionResult,
    ImportSource,
    ImportSourceError,
    LintFinding,
    LintReport,
)
from app.import_source_pipeline import run_adapter_import_job
from app.models import SpecImportJobStatus
from app.sample_import_source import SAMPLE_FORMAT, SampleImportSource


def _payload(text: str, *, options: Optional[dict] = None, filename: str = "doc.txt") -> dict:
    """Build a worker-style payload carrying base64 document bytes + metadata."""
    return {
        "rest_job_id": "job-1",
        "metadata": {
            "source_kind": "sample",
            "project": {"name": "P", "slug": "p"},
            "version": {"version_id": "1.0.0"},
            "options": options or {},
        },
        "document_base64": base64.standard_b64encode(text.encode("utf-8")).decode("ascii"),
        "filename": filename,
        "content_type": "text/plain",
    }


async def _collect_snapshots(
    adapter: ImportSource, payload: dict
) -> tuple[SpecImportJobStatus, List[SpecImportJobStatus]]:
    """Run the pipeline, returning ``(final, intermediate_snapshots)``."""
    snaps: List[SpecImportJobStatus] = []

    async def _on(status: SpecImportJobStatus) -> None:
        snaps.append(status)

    final = await run_adapter_import_job(adapter, payload, on_snapshot=_on)
    return final, snaps


async def test_sample_adapter_runs_end_to_end() -> None:
    final, snaps = await _collect_snapshots(SampleImportSource(), _payload("hello"))

    assert final.state == "completed"
    assert final.percent == 100
    assert final.summary is not None
    assert final.summary["source"] == "sample"
    assert final.summary["format"] == SAMPLE_FORMAT
    assert final.summary["paradigm"] == ApiParadigm.DATA_SCHEMA.value
    assert final.summary["fingerprint"].startswith("sha256:")
    assert final.summary["persisted"] is False

    # Each phase emitted an event, accumulated across snapshots (final carries them all).
    codes = [e.code for e in final.events]
    assert codes == [
        "ADAPTER_INIT",
        "PARSE_OK",
        "NORMALIZE_OK",
        "ROUTING_DECIDED",
        "VERSION_FINGERPRINT",
        "LINT_COMPLETED",
        "IMPORT_COMPLETED",
    ]


async def test_snapshots_report_monotonic_progress() -> None:
    _final, snaps = await _collect_snapshots(SampleImportSource(), _payload("hi"))
    percents = [s.percent for s in snaps]
    assert percents == sorted(percents)
    assert all(s.state == "running" for s in snaps)


async def test_dry_run_flag_recorded_in_summary_and_events() -> None:
    final, _ = await _collect_snapshots(
        SampleImportSource(), _payload("x", options={"dry_run": True})
    )
    assert final.state == "completed"
    assert final.summary["dry_run"] is True
    assert any(e.code == "DRY_RUN" for e in final.events)


async def test_incremental_mode_flag_recorded() -> None:
    final, _ = await _collect_snapshots(
        SampleImportSource(), _payload("x", options={"incremental_mode": True})
    )
    assert final.summary["incremental_mode"] is True
    assert any(e.code == "INCREMENTAL_MODE" for e in final.events)


async def test_fingerprint_is_deterministic_across_runs() -> None:
    a, _ = await _collect_snapshots(SampleImportSource(), _payload("same-bytes"))
    b, _ = await _collect_snapshots(SampleImportSource(), _payload("same-bytes"))
    assert a.summary["fingerprint"] == b.summary["fingerprint"]


async def test_missing_document_fails_cleanly() -> None:
    payload = _payload("x")
    payload["document_base64"] = ""
    final = await run_adapter_import_job(SampleImportSource(), payload)
    assert final.state == "failed"
    assert any(e.code == "PARSE_ERROR" and e.level == "error" for e in final.events)


class _ParseBoomSource(ImportSource):
    """Adapter whose parse() rejects the document with a clean ImportSourceError."""

    key = "parse-boom"
    label = "Parse Boom"
    description = "test"
    icon = "x"
    paradigm = ApiParadigm.DATA_SCHEMA
    formats = ("boom",)

    def detect(self, payload: DetectionInput) -> DetectionResult:
        return NO_MATCH

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        raise ImportSourceError("cannot parse this")

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        # Never reached: parse() fails first.
        raise AssertionError("normalize should not run after a parse failure")


async def test_parse_error_yields_failed_status() -> None:
    final = await run_adapter_import_job(_ParseBoomSource(), _payload("x"))
    assert final.state == "failed"
    assert any(e.code == "PARSE_ERROR" and "cannot parse" in e.message for e in final.events)


class _NormalizeBoomSource(_ParseBoomSource):
    """Adapter that parses but cannot normalize (e.g. format has no normalizer)."""

    key = "normalize-boom"

    def parse(self, raw: str, *, source_label: Optional[str] = None) -> Any:
        return {"text": raw}

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        raise ImportSourceError("no normalizer for this format")


async def test_normalize_error_yields_failed_status() -> None:
    final = await run_adapter_import_job(_NormalizeBoomSource(), _payload("x"))
    assert final.state == "failed"
    codes = [e.code for e in final.events]
    assert "PARSE_OK" in codes
    assert any(e.code == "NORMALIZE_ERROR" for e in final.events)


class _LintingSource(_NormalizeBoomSource):
    """Adapter that produces a model and a non-empty lint report."""

    key = "linting"

    def normalize(self, native_ast: Any, *, include_raw: bool = True) -> CanonicalApi:
        return CanonicalApi(
            paradigm=ApiParadigm.DATA_SCHEMA,
            format="linting-1",
            identity=ApiIdentity(name="Lint Me"),
        )

    def lint(self, model: CanonicalApi) -> LintReport:
        return LintReport(
            findings=[LintFinding(path="$", rule="r1", severity="warning", message="m")],
            score=82,
            grade="B",
            report_fingerprint="fp-test",
            rule_hits={"r1": 1},
            severity_counts={"error": 0, "warning": 1, "info": 0},
        )


async def test_lint_summary_carries_score_grade_and_count() -> None:
    final = await run_adapter_import_job(_LintingSource(), _payload("x"))
    assert final.state == "completed"
    # MFI-4.2: the summary carries the full roll-up — score, grade, fingerprint, and tally.
    assert final.summary["lint"] == {
        "score": 82,
        "grade": "B",
        "report_fingerprint": "fp-test",
        "findings": 1,
        "severity_counts": {"error": 0, "warning": 1, "info": 0},
    }


async def test_quality_capture_runs_when_a_version_target_is_present() -> None:
    # MFI-4.2: when the import created a revision (a version_record_id target + tenant), the
    # pipeline captures the rolled-up score onto it and records a QUALITY_CAPTURED event.
    payload = _payload("x", options={"version_record_id": "ver-9"})
    payload["tenant_id"] = "tenant-1"
    with patch(
        "app.import_source_pipeline.capture_canonical_quality_score"
    ) as m_capture:
        final = await run_adapter_import_job(_LintingSource(), payload)

    assert final.state == "completed"
    m_capture.assert_called_once()
    version_id, tenant_id, report = m_capture.call_args.args
    assert (version_id, tenant_id) == ("ver-9", "tenant-1")
    # The already-computed roll-up is persisted, so the stored score equals the surfaced one.
    assert (report.score, report.grade, report.report_fingerprint) == (82, "B", "fp-test")
    assert any(e.code == "QUALITY_CAPTURED" for e in final.events)


async def test_quality_capture_skipped_on_dry_run() -> None:
    # A dry run never persists the model, so it must not capture a score either.
    payload = _payload(
        "x", options={"version_record_id": "ver-9", "dry_run": True}
    )
    payload["tenant_id"] = "tenant-1"
    with patch(
        "app.import_source_pipeline.capture_canonical_quality_score"
    ) as m_capture:
        final = await run_adapter_import_job(_LintingSource(), payload)

    assert final.state == "completed"
    m_capture.assert_not_called()
    assert not any(e.code == "QUALITY_CAPTURED" for e in final.events)


async def test_quality_capture_skipped_without_a_version_target() -> None:
    # The in-process adapter path is preview-only until canonical→catalog persistence wires a
    # version target through; with none present the capture is a guarded no-op.
    with patch(
        "app.import_source_pipeline.capture_canonical_quality_score"
    ) as m_capture:
        final = await run_adapter_import_job(_LintingSource(), _payload("x"))

    assert final.state == "completed"
    m_capture.assert_not_called()
    assert not any(e.code == "QUALITY_CAPTURED" for e in final.events)


async def test_cancel_between_phases_stops_run() -> None:
    flag = {"canceled": False}

    async def _on(status: SpecImportJobStatus) -> None:
        # Request cancellation as soon as the first running snapshot is published.
        flag["canceled"] = True

    final = await run_adapter_import_job(
        SampleImportSource(),
        _payload("x"),
        on_snapshot=_on,
        is_canceled=lambda: flag["canceled"],
    )
    assert final.state == "canceled"
    assert final.percent < 100
