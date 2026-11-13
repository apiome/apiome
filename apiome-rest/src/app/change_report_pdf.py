"""
Render a publication change report as a PDF (#2705, CR-V2-01).

A change report is three Markdown snippets — header, body, footnote — rendered from Mustache
templates and optionally edited (``change_report_render.py``). This module turns the
*effective* snippets into one PDF with a pure-Python pipeline: Markdown → HTML
(``markdown-it-py``, CommonMark plus tables) → PDF (``fpdf2``). No system package is needed.

Two properties matter here:

* **Reproducible.** The document's creation date is pinned to a timestamp the caller passes
  (the report's ``updated_at``), so rendering the same report twice gives the same bytes and
  therefore the same SHA-256. That hash is stored with the report so a PDF handed to a
  stakeholder can be checked against the record.
* **Unicode-safe.** The bundled DejaVu fonts (``data/fonts``) carry the arrows, dashes and
  dots the default templates use. DejaVu has no upright/oblique pair in the bundle, so
  emphasis renders upright, and scripts DejaVu lacks (CJK, for example) are left out by
  ``fpdf2`` rather than failing the export.

The typography is deliberately plain. It is the same content as the on-screen report, not a
pixel copy of it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fpdf import FPDF
from fpdf.fonts import FontFace
from markdown_it import MarkdownIt

#: Where the bundled TrueType fonts live.
FONT_DIR = Path(__file__).resolve().parent / "data" / "fonts"

_BODY_FAMILY = "DejaVu"
_MONO_FAMILY = "DejaVuMono"
_BODY_SIZE_PT = 10
_MARGIN_MM = 18
#: Near-black text for headings; fpdf2's default heading colour is dark red.
_INK = (17, 24, 39)

# CommonMark plus pipe tables — what the default templates use. Raw HTML in a report is
# escaped rather than interpreted, so an edited report cannot inject markup into the document.
_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")


def report_markdown(
    header: Optional[str], body: Optional[str], footnote: Optional[str]
) -> str:
    """Join a report's three snippets into one Markdown document.

    Args:
        header: The effective header snippet.
        body: The effective body snippet.
        footnote: The effective footnote snippet.

    Returns:
        The snippets that have content, in order, separated by blank lines; the footnote is
        set apart by a horizontal rule.
    """
    parts = [part.strip() for part in (header, body) if part and part.strip()]
    if footnote and footnote.strip():
        parts.append("---")
        parts.append(footnote.strip())
    return "\n\n".join(parts)


def report_html(markdown: str) -> str:
    """Convert a report's Markdown to the HTML the PDF is laid out from.

    Args:
        markdown: The report as Markdown.

    Returns:
        An HTML fragment (no ``<html>`` wrapper).
    """
    return _MARKDOWN.render(markdown)


def _pinned_timestamp(pinned_at: Optional[datetime]) -> datetime:
    """Return the creation date to stamp, always timezone-aware.

    Args:
        pinned_at: The report's last-change time, when known.

    Returns:
        ``pinned_at`` in UTC; the Unix epoch when no time is known, so the output stays
        deterministic rather than taking the wall clock.
    """
    if pinned_at is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if pinned_at.tzinfo is None:
        return pinned_at.replace(tzinfo=timezone.utc)
    return pinned_at.astimezone(timezone.utc)


def render_change_report_pdf(
    header: Optional[str],
    body: Optional[str],
    footnote: Optional[str],
    *,
    title: str,
    pinned_at: Optional[datetime] = None,
) -> bytes:
    """Render a change report to PDF bytes.

    Args:
        header: The effective header snippet (Markdown).
        body: The effective body snippet (Markdown).
        footnote: The effective footnote snippet (Markdown).
        title: The document title stored in the PDF's metadata.
        pinned_at: The report's last-change time; pins the PDF's creation date so the same
            content always yields the same bytes.

    Returns:
        The PDF document.

    Raises:
        ValueError: When the report has no content to render.
    """
    markdown = report_markdown(header, body, footnote)
    if not markdown:
        raise ValueError("The change report has no content to export")

    pdf = FPDF(format="A4")
    pdf.set_margins(_MARGIN_MM, _MARGIN_MM, _MARGIN_MM)
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_MM)
    regular = str(FONT_DIR / "DejaVuSans.ttf")
    bold = str(FONT_DIR / "DejaVuSans-Bold.ttf")
    pdf.add_font(_BODY_FAMILY, "", regular)
    pdf.add_font(_BODY_FAMILY, "B", bold)
    # No oblique face is bundled: emphasis falls back to the upright faces.
    pdf.add_font(_BODY_FAMILY, "I", regular)
    pdf.add_font(_BODY_FAMILY, "BI", bold)
    pdf.add_font(_MONO_FAMILY, "", str(FONT_DIR / "DejaVuSansMono.ttf"))

    pdf.set_title(title)
    pdf.set_creator("Apiome")
    pdf.set_creation_date(_pinned_timestamp(pinned_at))
    pdf.add_page()
    pdf.set_font(_BODY_FAMILY, size=_BODY_SIZE_PT)
    pdf.write_html(
        report_html(markdown),
        font_family=_BODY_FAMILY,
        tag_styles={
            "h1": FontFace(color=_INK, size_pt=20),
            "h2": FontFace(color=_INK, size_pt=15),
            "h3": FontFace(color=_INK, size_pt=12),
            "h4": FontFace(color=_INK, size_pt=11),
            "code": FontFace(family=_MONO_FAMILY, size_pt=9),
            "pre": FontFace(family=_MONO_FAMILY, size_pt=9),
        },
    )
    return bytes(pdf.output())


def pdf_sha256(pdf: bytes) -> str:
    """Return the SHA-256 of a PDF as lowercase hex — the value stored with the report.

    Args:
        pdf: The PDF document.

    Returns:
        64 hexadecimal characters.
    """
    return hashlib.sha256(pdf).hexdigest()
