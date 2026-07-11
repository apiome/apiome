"""Capture the quality/lint score onto a revision at import, surfaced in the projects list (#3609)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models import ProjectSchema
from app.spec_import_engine import _capture_version_quality_score


def test_capture_persists_lint_result_onto_the_revision():
    """A completed import lints the new revision and stores score/grade/fingerprint on it."""
    mock_db = MagicMock()
    mock_db.get_version_by_id.return_value = {
        "id": "ver-1",
        "project_id": "proj-1",
        "version_id": "1.0.0",
    }
    lint_result = MagicMock(score=87, grade="B", report_fingerprint="fp-abc")
    guide = MagicMock(guide_id=None, name="Apiome Recommended", source="fallback")

    # GOV-1.4: the capture lints through the style-guide-aware entry point.
    with patch("app.database.db", mock_db), patch(
        "app.compatibility_engine.openapi_for_revision", return_value={"openapi": "3.1.0"}
    ) as m_recon, patch(
        "app.style_guide_engine.guided_lint_openapi_spec", return_value=(lint_result, guide)
    ) as m_lint:
        _capture_version_quality_score("acme", "tenant-1", "ver-1")

    m_recon.assert_called_once()
    m_lint.assert_called_once()
    # The guided lint receives the tenant and the revision's owning project, so the
    # project → tenant → default resolution chain applies to import-time scores too.
    assert m_lint.call_args.args[1] == "tenant-1"
    assert m_lint.call_args.kwargs.get("project_id") == "proj-1"
    mock_db.set_version_quality_score.assert_called_once_with(
        "ver-1", "tenant-1", 87, "B", "fp-abc"
    )


def test_capture_is_best_effort_and_never_raises():
    """A failure while scoring must not break the (already committed) import."""
    mock_db = MagicMock()
    mock_db.get_version_by_id.side_effect = RuntimeError("db down")

    with patch("app.database.db", mock_db):
        _capture_version_quality_score("acme", "tenant-1", "ver-1")  # must not raise

    mock_db.set_version_quality_score.assert_not_called()


def test_capture_skips_when_revision_missing():
    mock_db = MagicMock()
    mock_db.get_version_by_id.return_value = None
    with patch("app.database.db", mock_db):
        _capture_version_quality_score("acme", "tenant-1", "ver-1")
    mock_db.set_version_quality_score.assert_not_called()


def test_project_schema_serializes_captured_quality_score():
    """The projects API exposes the version-summary score as camelCase qualityScore/qualityGrade."""
    project = ProjectSchema(
        id="p1",
        tenant_id="t1",
        name="n",
        slug="s",
        quality_score=87,
        quality_grade="B",
        versions_count=3,
    )
    dumped = project.model_dump(by_alias=True)
    assert dumped["qualityScore"] == 87
    assert dumped["qualityGrade"] == "B"
    assert dumped["versionsCount"] == 3


def test_project_schema_quality_score_defaults_to_none():
    project = ProjectSchema(id="p1", tenant_id="t1", name="n", slug="s")
    dumped = project.model_dump(by_alias=True)
    assert dumped["qualityScore"] is None
    assert dumped["qualityGrade"] is None
    assert dumped["versionsCount"] == 0
