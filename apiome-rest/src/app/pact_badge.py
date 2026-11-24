"""Pact verification badges — PFX-1.10 (#6923).

The pure part of the badges: how the verification state of pacts is reduced to one of three words
(``verified``, ``failing``, ``unknown``), and how that word is drawn as an SVG badge or described
as a shields.io endpoint document. The SQL is :mod:`app.pact_badge_store`; the public routes are
:mod:`app.pact_badge_routes`.

**The three words.** A *pact* is the latest pact published between a consumer and a provider. Its
state is that of its newest verification result: ``verified`` when it succeeded, ``failing`` when
it failed, ``unknown`` when the pact has no result yet. A *pacticipant* is judged by every pact it
is in: ``failing`` when any is failing, ``verified`` when it has pacts and all are verified, and
``unknown`` otherwise — no pacts, or at least one not yet verified. Nothing is ever guessed
optimistically: an unverified pact keeps the badge from saying ``verified``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
from xml.sax.saxutils import escape

__all__ = [
    "FAILING",
    "STATUSES",
    "UNKNOWN",
    "VERIFIED",
    "badge_svg",
    "combine_statuses",
    "pact_status",
    "shields_endpoint",
]

VERIFIED = "verified"
FAILING = "failing"
UNKNOWN = "unknown"

#: Every status a badge can show.
STATUSES = (VERIFIED, FAILING, UNKNOWN)

#: The right-hand colour of each status (hex, so the SVG stands alone) and shields.io's name for it.
_COLOURS: Dict[str, str] = {VERIFIED: "#2ea44f", FAILING: "#d1242f", UNKNOWN: "#8b949e"}
_SHIELDS_COLOURS: Dict[str, str] = {VERIFIED: "brightgreen", FAILING: "red", UNKNOWN: "lightgrey"}
_LABEL_COLOUR = "#555555"

#: Approximate width of one character of the 11px Verdana the badge uses, and the padding per side.
_CHAR_WIDTH = 6.6
_PADDING = 10
_MAX_LABEL = 60


def pact_status(success: Optional[bool]) -> str:
    """The state of one pact from its newest verification result.

    Args:
        success: ``True`` / ``False`` for the newest result; ``None`` when there is none.

    Returns:
        ``verified``, ``failing`` or ``unknown``.
    """
    if success is None:
        return UNKNOWN
    return VERIFIED if success else FAILING


def combine_statuses(statuses: Iterable[str]) -> str:
    """The state of a pacticipant from the state of each pact it is in.

    Args:
        statuses: One status per pact.

    Returns:
        ``failing`` if any is failing; else ``verified`` if there is at least one and all are
        verified; else ``unknown``.
    """
    seen = list(statuses)
    if FAILING in seen:
        return FAILING
    if seen and all(status == VERIFIED for status in seen):
        return VERIFIED
    return UNKNOWN


def _clean(label: str) -> str:
    """A label made safe to draw: control characters dropped, long text cut."""
    text = "".join(ch for ch in label if ch.isprintable()).strip() or "pact"
    return text if len(text) <= _MAX_LABEL else text[: _MAX_LABEL - 1] + "…"


def _width(text: str) -> int:
    """The drawn width of a piece of badge text, padding included."""
    return int(len(text) * _CHAR_WIDTH + 2 * _PADDING)


def badge_svg(label: str, status: str) -> str:
    """Draw a flat two-part badge: ``<label> | <status>``.

    Args:
        label: The left-hand text (for example ``pact: ledger-api``). Escaped; control characters
            are dropped and long text is cut at 60 characters.
        status: One of :data:`STATUSES`; anything else is drawn as ``unknown``.

    Returns:
        A standalone SVG document (``role="img"`` with an accessible name).
    """
    if status not in STATUSES:
        status = UNKNOWN
    left = _clean(label)
    left_width, right_width = _width(left), _width(status)
    total = left_width + right_width
    left_x = left_width / 2
    right_x = left_width + right_width / 2
    text = escape(left)
    name = escape(f"{left}: {status}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{name}">'
        f"<title>{name}</title>"
        '<clipPath id="r"><rect width="%d" height="20" rx="3"/></clipPath>' % total + '<g clip-path="url(#r)">'
        f'<rect width="{left_width}" height="20" fill="{_LABEL_COLOUR}"/>'
        f'<rect x="{left_width}" width="{right_width}" height="20" fill="{_COLOURS[status]}"/>'
        "</g>"
        '<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left_x}" y="14">{text}</text>'
        f'<text x="{right_x}" y="14">{status}</text>'
        "</g></svg>"
    )


def shields_endpoint(label: str, status: str) -> Dict[str, Any]:
    """The JSON document shields.io's ``/endpoint`` badge reads.

    Args:
        label: The left-hand text.
        status: One of :data:`STATUSES`; anything else is reported as ``unknown``.

    Returns:
        ``{"schemaVersion": 1, "label", "message", "color"}``.
    """
    if status not in STATUSES:
        status = UNKNOWN
    return {"schemaVersion": 1, "label": _clean(label), "message": status, "color": _SHIELDS_COLOURS[status]}
