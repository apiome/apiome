"""PDF export of a change report (#2705, CR-V2-01).

The golden case renders the bundled default templates against a small change model — the same
Markdown the Change report panel shows — and checks the PDF carries that content, is a valid
PDF, and is byte-for-byte reproducible.
"""

import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from app.change_report_pdf import (
    FONT_DIR,
    pdf_sha256,
    render_change_report_pdf,
    report_html,
    report_markdown,
)
from app.change_report_render import placeholder_render_from_change_model

_PINNED = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)

_GOLDEN_MODEL = {
    "schemaVersion": "1.0",
    "schemas": {
        "added": [{"name": "Refund"}, {"name": "Dispute"}],
        "removed": [{"name": "LegacyCharge"}],
        "modified": [{"name": "Payment"}],
    },
    "properties": [
        {"schemaName": "Payment", "path": "amount.currency", "changeKind": "added"},
    ],
    "references": [],
    "relationships": [],
    "documentation": [],
    "warnings": [],
    "skipped": [],
}


def _golden_snippets():
    """The on-screen report for the golden model: header, body, footnote (Markdown)."""
    return placeholder_render_from_change_model(_GOLDEN_MODEL)


def _pdf_text(pdf: bytes, tmp_path) -> str:
    """Extract a PDF's text with poppler's ``pdftotext`` (skips when it is not installed)."""
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext (poppler-utils) is not installed")
    path = tmp_path / "report.pdf"
    path.write_bytes(pdf)
    out = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, check=True
    )
    return out.stdout.decode("utf-8")


def test_the_bundled_fonts_are_shipped_with_their_licence():
    for name in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSansMono.ttf"):
        assert (FONT_DIR / name).is_file(), name
    assert (FONT_DIR / "LICENSE-DejaVu.txt").is_file()


def test_golden_report_renders_to_a_pdf():
    header, body, footnote = _golden_snippets()
    pdf = render_change_report_pdf(header, body, footnote, title="golden", pinned_at=_PINNED)

    assert pdf.startswith(b"%PDF-")
    assert pdf.rstrip().endswith(b"%%EOF")
    assert len(pdf) > 2000


def test_golden_pdf_matches_the_on_screen_report(tmp_path):
    """Every heading and every named schema of the on-screen Markdown is in the PDF."""
    header, body, footnote = _golden_snippets()
    pdf = render_change_report_pdf(header, body, footnote, title="golden", pinned_at=_PINNED)
    text = _pdf_text(pdf, tmp_path)

    markdown = report_markdown(header, body, footnote)
    headings = [m.group(1).strip() for m in re.finditer(r"^#+\s+(.+)$", markdown, flags=re.M)]
    assert headings, "the golden report should have headings"
    for heading in headings:
        assert re.sub(r"[`*_]", "", heading) in text, heading
    for name in ("Refund", "Dispute", "LegacyCharge", "Payment", "amount.currency"):
        assert name in text, name
    # The summary table's figures survive: two schemas added, one removed, one modified.
    assert re.search(r"Schemas added\s+2", text)
    assert re.search(r"Schemas removed\s+1", text)
    assert re.search(r"Schemas modified\s+1", text)


def test_the_same_report_renders_to_the_same_bytes():
    header, body, footnote = _golden_snippets()
    first = render_change_report_pdf(header, body, footnote, title="golden", pinned_at=_PINNED)
    second = render_change_report_pdf(header, body, footnote, title="golden", pinned_at=_PINNED)

    assert first == second
    assert pdf_sha256(first) == pdf_sha256(second)
    assert re.fullmatch(r"[0-9a-f]{64}", pdf_sha256(first))


def test_different_content_gives_a_different_hash():
    header, body, footnote = _golden_snippets()
    first = render_change_report_pdf(header, body, footnote, title="golden", pinned_at=_PINNED)
    edited = render_change_report_pdf(
        header, body + "\n\nReviewed by finance.", footnote, title="golden", pinned_at=_PINNED
    )

    assert pdf_sha256(first) != pdf_sha256(edited)


def test_no_pinned_time_is_still_deterministic():
    """With no timestamp the creation date is the epoch, not the wall clock."""
    a = render_change_report_pdf("# A", "body", None, title="t")
    b = render_change_report_pdf("# A", "body", None, title="t")

    assert a == b


def test_a_naive_timestamp_is_read_as_utc():
    aware = render_change_report_pdf("# A", "b", None, title="t", pinned_at=_PINNED)
    naive = render_change_report_pdf(
        "# A", "b", None, title="t", pinned_at=_PINNED.replace(tzinfo=None)
    )

    assert aware == naive


def test_arrows_dashes_and_dots_survive(tmp_path):
    pdf = render_change_report_pdf(
        "# Payments API\n\n**From:** 1.0.0 → **To:** 1.1.0",
        "- `Refund` — _added_ · new",
        None,
        title="t",
        pinned_at=_PINNED,
    )
    text = _pdf_text(pdf, tmp_path)

    assert "1.0.0 → To: 1.1.0" in text
    assert "Refund — added · new" in text


def test_raw_html_in_an_edited_report_is_shown_as_text_not_interpreted(tmp_path):
    html = report_html("<script>alert(1)</script>\n\n**bold**")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html

    pdf = render_change_report_pdf("# T", "<script>alert(1)</script>", None, title="t")
    assert "<script>alert(1)</script>" in _pdf_text(pdf, tmp_path)


def test_an_empty_report_is_refused():
    with pytest.raises(ValueError, match="no content"):
        render_change_report_pdf(None, "   ", "", title="t")


class TestReportMarkdown:
    def test_joins_header_and_body_and_sets_the_footnote_apart(self):
        assert report_markdown("# H", "body", "note") == "# H\n\nbody\n\n---\n\nnote"

    def test_skips_blank_snippets(self):
        assert report_markdown(None, "  body  ", "  ") == "body"
        assert report_markdown("", None, None) == ""

    def test_tables_become_html_tables(self):
        html = report_html("| a | b |\n|--|--:|\n| 1 | 2 |")
        assert "<table>" in html and "<td>1</td>" in html
