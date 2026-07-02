"""Capture the rolled-up canonical-model lint score onto a revision at import (MFI-4.2, #3747).

The canonical-model analogue of ``test_version_quality_capture.py`` (specs) and the MCP capture
in ``test_mcp_discovery_trigger.py``: :func:`app.import_source_pipeline.capture_canonical_quality_score`
persists a freshly imported revision's rolled-up :class:`~app.import_source.LintReport` (score /
grade / fingerprint) onto its ``quality_*`` columns (reusing V124). It is strictly best-effort so a
persistence failure never breaks an already-committed import, and it persists the report the adapter
already produced so the stored score equals the surfaced one.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.import_source import LintReport
from app.import_source_pipeline import capture_canonical_quality_score


def _report() -> LintReport:
    """A rolled-up report as an adapter's ``lint`` would return."""
    return LintReport(
        score=74,
        grade="C",
        report_fingerprint="fp-xyz",
        rule_hits={"r1": 2},
        severity_counts={"error": 0, "warning": 2, "info": 0},
    )


def test_capture_persists_the_rolled_up_report_onto_the_revision():
    """The capture writes the report's score/grade/fingerprint onto the revision, tenant-scoped."""
    mock_db = MagicMock()
    with patch("app.database.db", mock_db):
        capture_canonical_quality_score("ver-1", "tenant-1", _report())

    mock_db.set_version_quality_score.assert_called_once_with(
        "ver-1", "tenant-1", 74, "C", "fp-xyz"
    )


def test_capture_skips_an_unscored_report():
    """A report with no score (an adapter that declined to score) has nothing to persist."""
    mock_db = MagicMock()
    with patch("app.database.db", mock_db):
        capture_canonical_quality_score("ver-1", "tenant-1", LintReport())

    mock_db.set_version_quality_score.assert_not_called()


def test_capture_is_best_effort_and_never_raises():
    """A failure while persisting must not break the (already committed) import."""
    mock_db = MagicMock()
    mock_db.set_version_quality_score.side_effect = RuntimeError("db down")

    with patch("app.database.db", mock_db):
        capture_canonical_quality_score("ver-1", "tenant-1", _report())  # must not raise
