"""Embeddable status badges — shields-style SVG for the public catalog (V2-MCP-33.3 / MCAT-19.3, #4652).

Server authors and catalogers want a visible signal — like a CI badge — they can drop into a README
that points at the catalog's assessment of a *published* endpoint. This module is the **pure**
rendering layer behind the public ``GET /mcp/badge/{tenant}/{slug}.svg`` route: it folds an enriched
endpoint row into one badge's ``(label, message, color)`` and renders that as a self-contained,
shields-style *flat* SVG. Nothing here touches the database or the request — the same inputs always
produce byte-identical SVG, so it is trivially testable and cacheable.

Design rules:

* **Never a data leak.** A missing row (unpublished, private, or unknown target) resolves to the
  neutral ``"unknown"`` badge — same shape, grey, no identifying content — so an anonymous caller
  can never tell an unpublished endpoint from one that does not exist.
* **Query-selectable metric.** ``grade`` (the A–F lint grade), ``health`` (the derived operational
  label, reusing :func:`app.mcp_catalog_inventory.derive_health`), or ``version`` (the server's
  reported version). An unrecognized metric normalizes to ``grade`` rather than erroring, so a badge
  URL in a README always renders *something* valid.
* **Light / dark label variants.** The colored message segment is fixed by the metric's value; the
  *label* segment's background switches with the ``theme`` so the badge sits well on a light or a
  dark README.
* **Content-addressed ETag.** :func:`svg_etag` hashes the rendered SVG, so the caching route's ETag
  changes exactly when the rendered badge does (a re-grade, a health flip) and not otherwise.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional, Tuple

from .mcp_catalog_inventory import derive_health

# --- Metric / theme vocabularies -------------------------------------------------------------------

METRIC_GRADE = "grade"
METRIC_HEALTH = "health"
METRIC_VERSION = "version"

#: The query-selectable metrics, in documentation order. ``grade`` is the default.
BADGE_METRICS: Tuple[str, ...] = (METRIC_GRADE, METRIC_HEALTH, METRIC_VERSION)

THEME_LIGHT = "light"
THEME_DARK = "dark"

#: The selectable label-segment themes. ``light`` is the default.
BADGE_THEMES: Tuple[str, ...] = (THEME_LIGHT, THEME_DARK)

#: The neutral message rendered whenever a value is absent or the endpoint is not resolvable.
UNKNOWN_MESSAGE = "unknown"

# --- Colors (the shields palette) ------------------------------------------------------------------

_COLOR_BRIGHTGREEN = "#4c1"
_COLOR_GREEN = "#97ca00"
_COLOR_YELLOW = "#dfb317"
_COLOR_ORANGE = "#fe7d37"
_COLOR_RED = "#e05d44"
_COLOR_BLUE = "#007ec6"
_COLOR_GREY = "#9f9f9f"

#: The left label-segment background per theme — the "light/dark label variant". The message segment
#: keeps its value-derived color in both; only the label tone flips to sit on a light vs dark page.
_LABEL_BG = {THEME_LIGHT: "#555", THEME_DARK: "#21262d"}

#: A–F grade → segment color (bright-green best, red worst).
_GRADE_COLORS = {
    "A": _COLOR_BRIGHTGREEN,
    "B": _COLOR_GREEN,
    "C": _COLOR_YELLOW,
    "D": _COLOR_ORANGE,
    "F": _COLOR_RED,
}

#: Derived health label → segment color. A label absent from this map (should not happen) falls back
#: to grey via :meth:`dict.get`.
_HEALTH_COLORS = {
    "healthy": _COLOR_BRIGHTGREEN,
    "failing": _COLOR_RED,
    "quarantined": _COLOR_RED,
    "disabled": _COLOR_GREY,
    "undiscovered": _COLOR_GREY,
}

#: The left label text per metric.
_METRIC_LABELS = {
    METRIC_GRADE: "mcp grade",
    METRIC_HEALTH: "mcp health",
    METRIC_VERSION: "mcp version",
}


def normalize_metric(value: Optional[str]) -> str:
    """Coerce a caller-supplied metric to a supported one, defaulting to ``grade``.

    An unknown or missing metric normalizes to :data:`METRIC_GRADE` rather than raising, so a badge
    URL embedded in a README always renders a valid badge instead of a broken image.

    Args:
        value: The raw ``metric`` query value (any case), possibly ``None``.

    Returns:
        One of :data:`BADGE_METRICS`.
    """
    candidate = (value or "").strip().lower()
    return candidate if candidate in BADGE_METRICS else METRIC_GRADE


def normalize_theme(value: Optional[str]) -> str:
    """Coerce a caller-supplied theme to a supported one, defaulting to ``light``.

    Args:
        value: The raw ``theme`` query value (any case), possibly ``None``.

    Returns:
        One of :data:`BADGE_THEMES`.
    """
    candidate = (value or "").strip().lower()
    return candidate if candidate in BADGE_THEMES else THEME_LIGHT


def _version_message(row: Mapping[str, Any]) -> Optional[str]:
    """Derive the ``version`` metric's message from a resolved endpoint row.

    Prefers the server's self-reported ``server_version``; falls back to the snapshot sequence
    (``v{version_seq}``) when the server reports none but a snapshot exists. Returns ``None`` when
    there is nothing to show (never discovered), which the caller renders as the ``unknown`` badge.
    """
    server_version = row.get("server_version")
    if server_version:
        return str(server_version).strip() or None
    seq = row.get("version_seq")
    if seq is not None:
        return f"v{seq}"
    return None


def resolve_badge(
    row: Optional[Mapping[str, Any]], metric: str
) -> Tuple[str, str, str]:
    """Fold an endpoint row and a metric into one badge's ``(label, message, color)``.

    The single decision point the route shares: the label comes from the (already-normalized)
    metric; the message and color come from the row's value for that metric. A ``None`` row — an
    unpublished, private, or unknown target — always yields the neutral ``unknown``/grey badge, so
    the badge can never disclose whether such an endpoint exists.

    Args:
        row: An enriched, *already public-gated* endpoint row (grade/score, the health columns, and
            the current version fields), or ``None`` when no published endpoint resolved.
        metric: A normalized metric from :func:`normalize_metric`.

    Returns:
        ``(label, message, color)`` — the three inputs :func:`render_badge_svg` needs.
    """
    label = _METRIC_LABELS.get(metric, _METRIC_LABELS[METRIC_GRADE])
    if row is None:
        return label, UNKNOWN_MESSAGE, _COLOR_GREY

    if metric == METRIC_GRADE:
        grade = str(row.get("grade") or "").strip().upper()
        if grade in _GRADE_COLORS:
            return label, grade, _GRADE_COLORS[grade]
        return label, UNKNOWN_MESSAGE, _COLOR_GREY

    if metric == METRIC_HEALTH:
        health = derive_health(row)
        return label, health, _HEALTH_COLORS.get(health, _COLOR_GREY)

    # METRIC_VERSION
    version = _version_message(row)
    if version:
        return label, version, _COLOR_BLUE
    return label, UNKNOWN_MESSAGE, _COLOR_GREY


# --- SVG rendering ---------------------------------------------------------------------------------

#: Approximate rendered width, in px, of one character of the 11px Verdana face the badge uses. The
#: SVG pins each segment's text with ``textLength`` so the glyphs always fit the box this estimate
#: sizes; the estimate only needs to be close enough that the padding looks even.
_CHAR_WIDTH_PX = 6.5

#: Horizontal padding per segment (≈5px on each side of the text).
_SEGMENT_PADDING_PX = 10

_XML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}


def _escape(text: str) -> str:
    """Escape XML metacharacters so an arbitrary server-reported value cannot break the SVG."""
    return "".join(_XML_ESCAPES.get(ch, ch) for ch in text)


def _segment_width(text: str) -> int:
    """Estimate a segment's pixel width from its text length plus fixed side padding."""
    return int(round(len(text) * _CHAR_WIDTH_PX)) + _SEGMENT_PADDING_PX


def render_badge_svg(label: str, message: str, color: str, *, theme: str) -> str:
    """Render a self-contained, shields-style *flat* badge as an SVG string.

    Produces the familiar two-segment badge: a grey (theme-toned) label on the left and the
    value-colored message on the right, with the usual soft top gradient and rounded corners. The
    text is drawn in a coordinate system scaled ×10 with an explicit ``textLength`` so the label and
    message always fit their boxes regardless of the exact font metrics on the viewer's machine. The
    output embeds no external references (no fonts, no images), so it renders identically anywhere.

    Args:
        label: The left-segment text (the metric name).
        message: The right-segment text (the metric's value, or ``unknown``).
        color: The right-segment background color (a CSS hex string).
        theme: A normalized theme from :func:`normalize_theme`; selects the label background.

    Returns:
        A complete ``<svg>…</svg>`` document string.
    """
    label_bg = _LABEL_BG.get(theme, _LABEL_BG[THEME_LIGHT])
    label_w = _segment_width(label)
    message_w = _segment_width(message)
    total_w = label_w + message_w

    esc_label = _escape(label)
    esc_message = _escape(message)
    aria = _escape(f"{label}: {message}")

    # ×10 scaled text geometry (matches the shields "flat" renderer): center each segment's text and
    # pin its rendered length to the padded box so glyphs never overflow or get clipped.
    label_text_x = label_w * 5
    message_text_x = (label_w + message_w / 2) * 10
    label_text_len = (label_w - _SEGMENT_PADDING_PX) * 10
    message_text_len = (message_w - _SEGMENT_PADDING_PX) * 10

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{total_w}" height="20" role="img" aria-label="{aria}">'
        f"<title>{aria}</title>"
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/>'
        f"</linearGradient>"
        f'<clipPath id="r"><rect width="{total_w}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label_w}" height="20" fill="{label_bg}"/>'
        f'<rect x="{label_w}" width="{message_w}" height="20" fill="{color}"/>'
        f'<rect width="{total_w}" height="20" fill="url(#s)"/>'
        f"</g>"
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        f'text-rendering="geometricPrecision" font-size="110">'
        f'<text aria-hidden="true" x="{label_text_x}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{label_text_len}">{esc_label}</text>'
        f'<text x="{label_text_x}" y="140" transform="scale(.1)" '
        f'textLength="{label_text_len}">{esc_label}</text>'
        f'<text aria-hidden="true" x="{message_text_x}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{message_text_len}">{esc_message}</text>'
        f'<text x="{message_text_x}" y="140" transform="scale(.1)" '
        f'textLength="{message_text_len}">{esc_message}</text>'
        f"</g></svg>"
    )


def svg_etag(svg: str) -> str:
    """Return a strong, content-addressed ETag for a rendered badge SVG.

    Hashing the rendered bytes means the ETag changes exactly when the badge does (a re-grade, a
    health flip, a theme switch) and stays stable otherwise, so a README's ``<img>`` gets a clean
    ``304 Not Modified`` until the underlying signal actually moves.

    Args:
        svg: The rendered SVG document.

    Returns:
        A quoted ETag value (e.g. ``"3f2b…"``) suitable for the ``ETag`` response header.
    """
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()[:16]
    return f'"{digest}"'
