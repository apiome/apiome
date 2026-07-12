"""Lint report persistence and serving for native catalog imports."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.capnproto_import_source import CapnpImportSource
from app.capnproto_normalizer import CapnpNormalizer
from app.capnproto_parser import parse_capnproto
from app.lint_routes import _try_relint_canonical_source

_ADDRESS_BOOK = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/capnproto/01-address-book.capnp"
).read_text(encoding="utf-8")


def test_capnproto_import_lint_produces_findings():
    """The canonical-model linter returns findings for the address-book example."""
    adapter = CapnpImportSource()
    doc = adapter.parse(_ADDRESS_BOOK, source_label="01-address-book.capnp")
    api = adapter.normalize(doc)
    report = adapter.lint(api)
    assert report.score is not None
    assert report.grade is not None
    assert report.findings
    persisted = report.to_persisted_dict()
    assert persisted["findings"]
    assert persisted["report_fingerprint"]


def test_canonical_relint_fallback_reconstructs_capnproto_source():
    """Legacy rows without quality_report can be re-linted from stored source content."""
    version = {
        "id": "rev-capnp",
        "project_id": "cat-capnp",
        "version_id": "1.0.0",
        "source_format": "capnproto",
        "format_metadata": {"sourceContent": _ADDRESS_BOOK, "sourceLabel": "01-address-book.capnp"},
    }
    catalog_item = {
        "id": "cat-capnp",
        "source_format": "capnproto",
        "format_metadata": version["format_metadata"],
    }
    report = _try_relint_canonical_source(version, catalog_item=catalog_item)
    assert report is not None
    assert report["score"] is not None
    assert report["findings"]


def test_stored_report_skips_openapi_recompute_in_build_lint_report():
    """build_lint_report serves persisted findings without calling openapi_for_revision."""
    from app.lint_routes import build_lint_report

    adapter = CapnpImportSource()
    doc = parse_capnproto(_ADDRESS_BOOK)
    api = CapnpNormalizer().normalize(doc)
    persisted = adapter.lint(api).to_persisted_dict()
    version = {"id": "rev-1", "project_id": "cat-1", "version_id": "1.0.0"}
    captured = {
        "quality_score": persisted["score"],
        "quality_grade": persisted["grade"],
        "quality_report_fingerprint": persisted["report_fingerprint"],
        "quality_report": persisted,
    }
    with patch("app.lint_routes.openapi_for_revision") as m_recon, patch(
        "app.lint_routes.db.get_version_quality_score", return_value=captured
    ):
        response = build_lint_report(
            version, "cat-1", "acme", "tenant-1", catalog_item={"source_format": "capnproto"}
        )
    m_recon.assert_not_called()
    assert response.findings
    assert response.score == persisted["score"]
