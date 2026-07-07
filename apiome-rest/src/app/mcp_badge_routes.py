"""Public embeddable status badge — anonymous, cacheable SVG (V2-MCP-33.3 / MCAT-19.3, #4652).

Exposes ``GET /mcp/badge/{tenant}/{slug}.svg``: a shields-style SVG a server author or cataloger can
drop into a README to advertise the catalog's assessment of a **published** endpoint. The route is
deliberately **unauthenticated** — a README's ``<img>`` fetches it with no credentials — so it must
never disclose anything about a non-public endpoint: an unpublished, private, or unknown target
resolves to the same neutral ``unknown`` badge a nonexistent one would, so its very existence stays
hidden (the public-gating lives in :meth:`Database.get_published_mcp_endpoint_badge`).

All rendering is delegated to the pure :mod:`app.mcp_badge` layer. This route only reads one row,
renders it, and adds HTTP caching: a content-addressed ``ETag`` (so a README image gets a ``304`` until
the badge actually changes) and a ``public, max-age`` ``Cache-Control`` — a shorter window for the
``unknown`` badge so a freshly published endpoint's real badge appears promptly.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query, Response

from .database import db
from .mcp_badge import (
    BADGE_METRICS,
    BADGE_THEMES,
    normalize_metric,
    normalize_theme,
    render_badge_svg,
    resolve_badge,
    svg_etag,
)

router = APIRouter(prefix="/mcp/badge", tags=["mcp-catalog"])

#: SVG content type, UTF-8 (server-reported version strings may carry non-ASCII).
_SVG_MEDIA_TYPE = "image/svg+xml; charset=utf-8"

#: ``max-age`` (seconds) for a resolved badge — long enough to spare the origin a README's repeated
#: image loads, short enough that a re-grade or health flip propagates within minutes.
_FOUND_MAX_AGE = 300

#: ``max-age`` (seconds) for the ``unknown`` badge — kept short so a newly published endpoint's real
#: badge replaces the placeholder promptly rather than being pinned by a stale cache.
_UNKNOWN_MAX_AGE = 60


def _if_none_match_hit(if_none_match: Optional[str], etag: str) -> bool:
    """Return whether the client's ``If-None-Match`` already carries this badge's ETag.

    Parses the (possibly comma-listed) header and matches our strong ETag, tolerating a ``W/`` weak
    prefix on the client's tags. A match means the badge is unchanged since the client last fetched
    it, so the route may answer ``304 Not Modified``.
    """
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        token = candidate.strip()
        if token.startswith("W/"):
            token = token[2:].strip()
        if token == etag or token == "*":
            return True
    return False


@router.get("/{tenant}/{slug}.svg")
async def get_mcp_status_badge(
    tenant: str,
    slug: str,
    metric: str = Query(
        "grade",
        description=(
            "Which signal to render: 'grade' (A–F lint grade), 'health' (operational label), or "
            "'version' (server-reported version). Anything else falls back to 'grade'."
        ),
    ),
    theme: str = Query(
        "light",
        description="Label variant: 'light' (default) or 'dark' — tones the label to suit the page.",
    ),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
) -> Response:
    """Render a published endpoint's status badge as a cacheable SVG (MCAT-19.3).

    Resolves the endpoint by ``tenant`` + ``slug`` through the public gate, folds the requested
    ``metric`` into a badge, and returns it as SVG with caching headers. A target that is not a
    published, public endpoint (or does not exist) renders the neutral ``unknown`` badge with a
    ``200`` — never a ``404`` — so the response never reveals whether such an endpoint exists.

    Args:
        tenant: The owning tenant's URL slug.
        slug: The endpoint's tenant-unique catalog slug (the ``.svg`` suffix is part of the route).
        metric: ``grade`` / ``health`` / ``version``; unrecognized values normalize to ``grade``.
        theme: ``light`` / ``dark`` label variant; unrecognized values normalize to ``light``.
        if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

    Returns:
        A ``Response`` carrying the SVG (``200``) — or an empty ``304`` — with ``ETag`` and
        ``Cache-Control`` set.
    """
    metric_key = normalize_metric(metric)
    theme_key = normalize_theme(theme)

    row = db.get_published_mcp_endpoint_badge(tenant, slug)
    label, message, color = resolve_badge(row, metric_key)
    svg = render_badge_svg(label, message, color, theme=theme_key)

    etag = svg_etag(svg)
    max_age = _FOUND_MAX_AGE if row is not None else _UNKNOWN_MAX_AGE
    headers = {
        "Cache-Control": f"public, max-age={max_age}",
        "ETag": etag,
    }

    if _if_none_match_hit(if_none_match, etag):
        return Response(status_code=304, headers=headers)

    return Response(content=svg, media_type=_SVG_MEDIA_TYPE, headers=headers)


__all__ = ["router", "BADGE_METRICS", "BADGE_THEMES"]
