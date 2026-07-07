"""Public catalog change feed — anonymous, cacheable RSS / Atom / JSON feeds (V2-MCP-33.4 / MCAT-19.4, #4653).

Exposes two **unauthenticated** routes a feed reader can subscribe to:

* ``GET /mcp/feed/{tenant}/{slug}`` — one endpoint's change history.
* ``GET /mcp/feed/{tenant}`` — the whole published catalog's change history.

Both take ``?format=rss|atom|json`` (default ``rss``) and emit new-version / added / removed /
modified / breaking-change entries projected read-only over ``mcp_endpoint_versions`` +
``mcp_version_changes``. Like the status badge (#4652), the routes are deliberately anonymous — a
reader polls with no credentials — so they must never disclose anything about a non-public endpoint:
the endpoint feed resolves its subject through the same public gate the ``mcp_v_public_endpoints``
view enforces, and an unpublished / private / unknown target renders an identical **empty** feed
rather than a ``404``. The catalog feed enforces the same predicate in SQL, so a private endpoint's
changes are excluded (an acceptance criterion).

All rendering is delegated to the pure :mod:`app.mcp_change_feed` layer. This route only reads rows,
folds them into entries, renders, and adds HTTP caching: a content-addressed ``ETag`` (so a polling
reader gets a ``304`` until the feed actually changes) and a ``public, max-age`` ``Cache-Control``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response

from .database import db
from .mcp_change_feed import (
    FEED_MEDIA_TYPES,
    FeedEntry,
    FeedMeta,
    build_entry,
    feed_etag,
    normalize_format,
    render_feed,
)

router = APIRouter(prefix="/mcp/feed", tags=["mcp-catalog"])

#: Maximum entries a feed renders — how many of the most recent change rows to include. Bounds both
#: the DB read and the rendered body; a middle-of-the-road window a reader expects from a feed.
_FEED_MAX_ENTRIES = 50

#: ``max-age`` (seconds) for a rendered feed — long enough to spare the origin a reader's frequent
#: polls, short enough that a new snapshot's changes surface within minutes. A matching
#: ``If-None-Match`` short-circuits to ``304`` regardless, so a warm reader pays almost nothing.
_FEED_MAX_AGE = 300


def _if_none_match_hit(if_none_match: Optional[str], etag: str) -> bool:
    """Return whether the client's ``If-None-Match`` already carries this feed's ETag.

    Parses the (possibly comma-listed) header and matches our strong ETag, tolerating a ``W/`` weak
    prefix and the ``*`` wildcard. A match means the feed is unchanged since the client last fetched
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


def _generated_now() -> datetime:
    """The feed's render time (a tz-aware UTC datetime, seconds precision), used as its fallback stamp."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def _build_entries(
    rows: List[Mapping[str, Any]],
    *,
    endpoint_id: Optional[str] = None,
    endpoint_name: Optional[str] = None,
    endpoint_slug: Optional[str] = None,
) -> List[FeedEntry]:
    """Fold change rows into feed entries, taking endpoint identity from each row or the fixed args.

    For an endpoint feed every row belongs to the one resolved endpoint, so ``endpoint_*`` are passed
    fixed; for a catalog feed each row carries its own ``endpoint_id`` / ``endpoint_name`` /
    ``endpoint_slug`` (the per-row value wins when present).
    """
    entries: List[FeedEntry] = []
    for row in rows:
        entries.append(
            build_entry(
                row,
                endpoint_id=str(row.get("endpoint_id") or endpoint_id or ""),
                endpoint_name=str(row.get("endpoint_name") or endpoint_name or ""),
                endpoint_slug=str(row.get("endpoint_slug") or endpoint_slug or ""),
            )
        )
    return entries


def _negotiate_format(fmt: Optional[str]) -> str:
    """Validate the requested feed format, raising ``400`` on an unrecognized value."""
    normalized = normalize_format(fmt)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail="unsupported feed format; use 'rss', 'atom', or 'json'",
        )
    return normalized


def _feed_response(
    meta: FeedMeta,
    entries: List[FeedEntry],
    fmt: str,
    if_none_match: Optional[str],
) -> Response:
    """Render a feed, attach caching headers, and honour a conditional request.

    Shared by both routes: renders ``entries`` in ``fmt``, sets a content-addressed ``ETag`` and a
    ``public, max-age`` ``Cache-Control``, and returns an empty ``304`` when the client's
    ``If-None-Match`` already matches (so a polling reader pays almost nothing until the feed moves).
    """
    body = render_feed(meta, entries, fmt)
    etag = feed_etag(body)
    headers = {
        "Cache-Control": f"public, max-age={_FEED_MAX_AGE}",
        "ETag": etag,
    }
    if _if_none_match_hit(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type=FEED_MEDIA_TYPES[fmt], headers=headers)


@router.get("/{tenant}/{slug}")
async def get_mcp_endpoint_change_feed(
    request: Request,
    tenant: str,
    slug: str,
    format: str = Query(
        "rss",
        description="Feed format: 'rss' (default), 'atom', or 'json' (JSON Feed 1.1).",
    ),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
) -> Response:
    """Render one **published** endpoint's change feed (MCAT-19.4).

    Resolves the endpoint by ``tenant`` + ``slug`` through the public gate and renders its recent
    change history (newest snapshot first) as RSS/Atom/JSON. A target that is not a published, public
    endpoint (or does not exist) renders an identical **empty** feed with a ``200`` — never a
    ``404`` — so the response never reveals whether such an endpoint exists, and a private endpoint's
    changes are never disclosed. Breaking changes are flagged in every entry.

    Args:
        request: The incoming request (used only to build the feed's self/home URLs).
        tenant: The owning tenant's URL slug.
        slug: The endpoint's tenant-unique catalog slug.
        format: ``rss`` / ``atom`` / ``json``; anything else is ``400``.
        if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

    Returns:
        A ``Response`` carrying the feed (``200``) — or an empty ``304`` — with ``ETag`` and
        ``Cache-Control`` set.
    """
    fmt = _negotiate_format(format)

    head = db.get_public_mcp_endpoint_feed_head(tenant, slug)
    if head is not None:
        endpoint_id = str(head["id"])
        endpoint_name = str(head.get("name") or slug)
        description = str(head.get("description") or "").strip() or (
            f"Change feed for the {endpoint_name} MCP server."
        )
        rows = db.get_public_mcp_endpoint_changes(endpoint_id, limit=_FEED_MAX_ENTRIES)
    else:
        # Unknown / private / unpublished — indistinguishable: an empty feed titled from the slug.
        endpoint_id = ""
        endpoint_name = slug
        description = f"Change feed for the {slug} MCP server."
        rows = []

    entries = _build_entries(
        rows,
        endpoint_id=endpoint_id,
        endpoint_name=endpoint_name,
        endpoint_slug=slug,
    )
    meta = FeedMeta(
        title=f"{endpoint_name} — MCP change feed",
        feed_id=f"urn:apiome:mcp-feed:endpoint:{tenant}/{slug}",
        self_url=str(request.url),
        home_url=str(request.base_url),
        description=description,
        updated=_generated_now(),
    )
    return _feed_response(meta, entries, fmt, if_none_match)


@router.get("/{tenant}")
async def get_mcp_catalog_change_feed(
    request: Request,
    tenant: str,
    format: str = Query(
        "rss",
        description="Feed format: 'rss' (default), 'atom', or 'json' (JSON Feed 1.1).",
    ),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
) -> Response:
    """Render a tenant's whole **published catalog** change feed (MCAT-19.4).

    Renders recent changes across every published, public endpoint the tenant owns — a catalog-wide
    activity stream, most recent first — as RSS/Atom/JSON. Private and unpublished endpoints are
    excluded in SQL, so their changes never appear. An unknown or fully-private catalog renders an
    empty feed with a ``200``. Breaking changes are flagged in every entry.

    Args:
        request: The incoming request (used only to build the feed's self/home URLs).
        tenant: The catalog's tenant slug.
        format: ``rss`` / ``atom`` / ``json``; anything else is ``400``.
        if_none_match: Standard conditional-request header; a match yields ``304 Not Modified``.

    Returns:
        A ``Response`` carrying the feed (``200``) — or an empty ``304`` — with ``ETag`` and
        ``Cache-Control`` set.
    """
    fmt = _negotiate_format(format)

    rows = db.get_public_catalog_changes(tenant, limit=_FEED_MAX_ENTRIES)
    entries = _build_entries(rows)
    meta = FeedMeta(
        title=f"{tenant} — MCP catalog change feed",
        feed_id=f"urn:apiome:mcp-feed:catalog:{tenant}",
        self_url=str(request.url),
        home_url=str(request.base_url),
        description=f"Change feed for the {tenant} MCP catalog.",
        updated=_generated_now(),
    )
    return _feed_response(meta, entries, fmt, if_none_match)


__all__ = ["router"]
