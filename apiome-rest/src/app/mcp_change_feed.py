"""Catalog change feed — pure RSS / Atom / JSON-Feed rendering for the public catalog (V2-MCP-33.4 / MCAT-19.4, #4653).

People tracking a server (or a whole published catalog) want to be *told* what changed without
polling the browse UI. The change history already exists — every ``mcp_version_changes`` row is one
capability added / removed / modified by a discovery snapshot (``mcp_endpoint_versions``) — but it is
not subscribable. This module is the **pure** rendering layer behind the public change-feed routes:
it folds those change rows (each already classified for breaking-ness via
:func:`app.mcp_change_severity.classify_change`) into normalized feed entries and serializes a feed
into three standard formats a reader can subscribe to — **RSS 2.0**, **Atom 1.0**, and **JSON Feed
1.1**.

Design rules (mirroring the badge / inventory export siblings):

* **Pure and deterministic.** Nothing here touches the database, the request, or the clock — every
  timestamp is supplied by the caller — so the same inputs always produce byte-identical output. That
  makes the feed trivially testable without a database and safely cacheable (see :func:`feed_etag`).
* **Standards-valid output.** XML is built with :mod:`xml.etree.ElementTree`, which escapes text and
  attributes for us, so a hostile server-reported capability name can never break the document; the
  JSON feed goes through :func:`json.dumps`. The rendered RSS/Atom validate against their schemas.
* **Breaking changes are flagged.** Every entry carries its severity (``additive`` / ``review`` /
  ``breaking``) as a machine field *and* a ``[breaking]`` title suffix, so even a reader that shows
  only titles surfaces a break.
* **No secret ever emitted.** The feed only ever renders the change history and the endpoint's public
  identity (name / slug); it never reads the stored ``endpoint_url`` (which may embed a credential).
  Public-gating — excluding private endpoints — is the route/DB layer's job; this layer only renders
  the rows it is handed.

The public surface is :data:`FEED_FORMATS` / :func:`normalize_format` / :data:`FEED_MEDIA_TYPES`
(format negotiation), :class:`FeedMeta` and :class:`FeedEntry` (the normalized model),
:func:`build_entry` (change row → entry), :func:`render_feed` (model → serialized feed), and
:func:`feed_etag` (content-addressed ETag).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, List, Mapping, Optional, Tuple
from xml.etree import ElementTree as ET

from .mcp_change_severity import (
    SEVERITY_ADDITIVE,
    SEVERITY_BREAKING,
    SEVERITY_REVIEW,
    classify_change,
)

# --- Format vocabulary -----------------------------------------------------------------------------

FORMAT_RSS = "rss"
FORMAT_ATOM = "atom"
FORMAT_JSON = "json"

#: The supported feed formats, in documentation order. ``rss`` is the default.
FEED_FORMATS: Tuple[str, ...] = (FORMAT_RSS, FORMAT_ATOM, FORMAT_JSON)

#: Response ``Content-Type`` per format — the registered media type for each feed standard, UTF-8
#: (capability names and server-reported strings may carry non-ASCII).
FEED_MEDIA_TYPES = {
    FORMAT_RSS: "application/rss+xml; charset=utf-8",
    FORMAT_ATOM: "application/atom+xml; charset=utf-8",
    FORMAT_JSON: "application/feed+json; charset=utf-8",
}

#: The Atom 1.0 namespace, set as the feed element's default namespace.
_ATOM_NS = "http://www.w3.org/2005/Atom"

#: The JSON Feed 1.1 version marker.
_JSON_FEED_VERSION = "https://jsonfeed.org/version/1.1"

#: Author/generator name stamped on the feed (Atom requires an author somewhere in the document).
_GENERATOR = "apiome"


def normalize_format(value: Optional[str]) -> Optional[str]:
    """Coerce a caller-supplied ``format`` to a supported one, or ``None`` if unrecognized.

    Unlike the badge's metric/theme (which normalize to a default so an ``<img>`` always renders), an
    unknown feed format returns ``None`` so the route can answer ``400`` — a feed is subscribed once
    and a clear error beats silently serving a format the caller did not ask for. A missing/empty
    value is treated as the default :data:`FORMAT_RSS`.

    Args:
        value: The raw ``format`` query value (any case), possibly ``None``.

    Returns:
        One of :data:`FEED_FORMATS`, or ``None`` when the value is a non-empty unrecognized string.
    """
    candidate = (value or "").strip().lower()
    if not candidate:
        return FORMAT_RSS
    return candidate if candidate in FEED_FORMATS else None


# --- Normalized model ------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedMeta:
    """Feed-level metadata shared by all three serializations.

    Attributes:
        title: Human-readable feed title (e.g. ``"Weather — MCP change feed"``).
        feed_id: A stable, unique feed identifier (a URN), constant across formats and reloads.
        self_url: The feed's own URL (rendered as the RSS/Atom ``self`` link and JSON ``feed_url``).
        home_url: A human landing URL for the feed's subject (the alternate/home link).
        description: A one-line feed description / subtitle.
        updated: The feed's last-updated time (a tz-aware ``datetime``); typically the render time,
            used as the feed timestamp when there are no entries to derive one from.
    """

    title: str
    feed_id: str
    self_url: str
    home_url: str
    description: str
    updated: datetime


@dataclass(frozen=True)
class FeedEntry:
    """One normalized feed entry — a single capability/server change.

    Attributes:
        entry_id: A stable, unique entry identifier (a URN derived from the change's identity).
        title: The entry title (``"Added tool: getWeather"``), with a ``[breaking]`` suffix when the
            change is breaking.
        summary: A one-line human description of the change.
        severity: ``additive`` / ``review`` / ``breaking`` from :func:`classify_change`.
        breaking: Convenience flag — ``severity == "breaking"``.
        change_type: ``added`` / ``removed`` / ``modified``.
        item_type: ``tool`` / ``resource`` / ``resource_template`` / ``prompt`` / ``server``.
        item_name: The changed item's name (or the server field name).
        endpoint_name: The owning endpoint's display name.
        endpoint_slug: The owning endpoint's tenant-unique slug.
        version_tag: The introducing snapshot's date/time tag, when known.
        version_seq: The introducing snapshot's monotonic sequence number, when known.
        updated: When the change happened (the snapshot's discovery time); a tz-aware ``datetime`` or
            ``None`` when no timestamp was recorded.
    """

    entry_id: str
    title: str
    summary: str
    severity: str
    breaking: bool
    change_type: str
    item_type: str
    item_name: str
    endpoint_name: str
    endpoint_slug: str
    version_tag: Optional[str]
    version_seq: Optional[int]
    updated: Optional[datetime]


#: Readable label per capability/server item type (for titles and summaries).
_ITEM_TYPE_LABELS = {
    "tool": "tool",
    "resource": "resource",
    "resource_template": "resource template",
    "prompt": "prompt",
    "server": "server metadata",
}

#: Readable verb per change direction.
_CHANGE_VERBS = {"added": "Added", "removed": "Removed", "modified": "Modified"}


def _item_type_label(item_type: str) -> str:
    """Readable label for a change's item type (unknown types degrade to a spaced form)."""
    return _ITEM_TYPE_LABELS.get(item_type, (item_type or "item").replace("_", " "))


def _change_verb(change_type: str) -> str:
    """Readable verb for a change direction (unknown directions degrade to a capitalized form)."""
    return _CHANGE_VERBS.get(change_type, (change_type or "changed").capitalize())


def _snapshot_label(version_tag: Optional[str], version_seq: Optional[int]) -> str:
    """A short human label for the introducing snapshot (its tag, else ``v{seq}``, else a fallback)."""
    if version_tag:
        return str(version_tag)
    if version_seq is not None:
        return f"v{version_seq}"
    return "unknown snapshot"


def _as_datetime(value: Any) -> Optional[datetime]:
    """Coerce a timestamp column (a ``datetime`` or an ISO-8601 string) to a tz-aware ``datetime``.

    Naive values are assumed UTC. An unparseable value yields ``None`` (the entry then falls back to
    the feed's own timestamp) rather than raising, so one malformed row can never break the feed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _entry_id(endpoint_id: str, change: Mapping[str, Any]) -> str:
    """Build a stable, unique URN for a change entry.

    A change is uniquely identified within the catalog by its owning endpoint, the snapshot that
    introduced it (``version_id``), and the changed item's ``(item_type, item_name, change_type)``
    (one item can only move in a single direction per snapshot). We hash that composite so the id is
    always a clean, opaque URI regardless of what characters an item name contains, and stays byte-
    stable for the same change across reloads and formats — which is what lets a reader dedupe.
    """
    composite = "\x1f".join(
        (
            str(endpoint_id),
            str(change.get("version_id") or ""),
            str(change.get("item_type") or ""),
            str(change.get("item_name") or ""),
            str(change.get("change_type") or ""),
        )
    )
    digest = hashlib.sha256(composite.encode("utf-8")).hexdigest()[:32]
    return f"urn:apiome:mcp-change:{digest}"


def build_entry(
    change: Mapping[str, Any],
    *,
    endpoint_id: str,
    endpoint_name: str,
    endpoint_slug: str,
) -> FeedEntry:
    """Fold one persisted change row (+ its snapshot context) into a normalized :class:`FeedEntry`.

    The single change-row → entry projection all three serializers share. Severity — and thus the
    breaking flag and the ``[breaking]`` title suffix — comes from the same
    :func:`app.mcp_change_severity.classify_change` the churn timeline and evolution series use, so
    the feed agrees with the rest of the product on what "breaking" means.

    Args:
        change: A change record carrying ``change_type`` / ``item_type`` / ``item_name`` / ``detail``
            (the fields :func:`classify_change` reads) plus its introducing snapshot's ``version_id``
            / ``version_seq`` / ``version_tag`` and a timestamp (``discovered_at``, falling back to
            ``version_created_at`` / ``created_at``).
        endpoint_id: The owning endpoint's id (used only to make the entry id unique per endpoint).
        endpoint_name: The owning endpoint's display name (for the title/summary).
        endpoint_slug: The owning endpoint's slug.

    Returns:
        The normalized entry.
    """
    severity = classify_change(change)
    breaking = severity == SEVERITY_BREAKING
    change_type = str(change.get("change_type") or "")
    item_type = str(change.get("item_type") or "")
    item_name = str(change.get("item_name") or "")
    version_tag = change.get("version_tag")
    version_seq = change.get("version_seq")
    version_seq = int(version_seq) if version_seq is not None else None

    label = _item_type_label(item_type)
    verb = _change_verb(change_type)
    snapshot = _snapshot_label(version_tag, version_seq)

    title = f"{verb} {label}: {item_name}"
    if breaking:
        title += " [breaking]"
    summary = (
        f"{verb} {label} '{item_name}' in {endpoint_name} — snapshot {snapshot}. "
        f"Change severity: {severity}."
    )

    updated = (
        _as_datetime(change.get("discovered_at"))
        or _as_datetime(change.get("version_created_at"))
        or _as_datetime(change.get("created_at"))
    )

    return FeedEntry(
        entry_id=_entry_id(endpoint_id, change),
        title=title,
        summary=summary,
        severity=severity,
        breaking=breaking,
        change_type=change_type,
        item_type=item_type,
        item_name=item_name,
        endpoint_name=endpoint_name,
        endpoint_slug=endpoint_slug,
        version_tag=str(version_tag) if version_tag is not None else None,
        version_seq=version_seq,
        updated=updated,
    )


# --- Rendering -------------------------------------------------------------------------------------


def _feed_updated(meta: FeedMeta, entries: List[FeedEntry]) -> datetime:
    """The feed's effective last-updated time: the newest entry's time, else the meta timestamp."""
    stamps = [e.updated for e in entries if e.updated is not None]
    return max(stamps) if stamps else meta.updated


def _entry_updated(entry: FeedEntry, fallback: datetime) -> datetime:
    """An entry's timestamp, or the feed fallback when the row carried none."""
    return entry.updated if entry.updated is not None else fallback


def _rfc822(dt: datetime) -> str:
    """Format a tz-aware datetime as an RFC-822 date (the RSS ``pubDate`` / ``lastBuildDate`` form)."""
    return format_datetime(dt)


def _rfc3339(dt: datetime) -> str:
    """Format a tz-aware datetime as an RFC-3339 timestamp (the Atom / JSON-Feed form)."""
    return dt.isoformat()


def _render_rss(meta: FeedMeta, entries: List[FeedEntry]) -> str:
    """Render the feed as an RSS 2.0 document string."""
    feed_updated = _feed_updated(meta, entries)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = meta.title
    ET.SubElement(channel, "link").text = meta.home_url
    ET.SubElement(channel, "description").text = meta.description
    ET.SubElement(channel, "generator").text = _GENERATOR
    ET.SubElement(channel, "lastBuildDate").text = _rfc822(feed_updated)

    for entry in entries:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry.title
        ET.SubElement(item, "description").text = entry.summary
        guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
        guid.text = entry.entry_id
        # The severity doubles as the RSS category, so ``breaking`` entries are machine-filterable.
        ET.SubElement(item, "category").text = entry.severity
        ET.SubElement(item, "pubDate").text = _rfc822(_entry_updated(entry, feed_updated))

    return _xml_document(rss)


def _render_atom(meta: FeedMeta, entries: List[FeedEntry]) -> str:
    """Render the feed as an Atom 1.0 document string."""
    feed_updated = _feed_updated(meta, entries)
    # ``xmlns`` as a literal attribute makes it the default namespace without prefixing child tags.
    feed = ET.Element("feed", {"xmlns": _ATOM_NS})
    ET.SubElement(feed, "id").text = meta.feed_id
    ET.SubElement(feed, "title").text = meta.title
    ET.SubElement(feed, "subtitle").text = meta.description
    ET.SubElement(feed, "updated").text = _rfc3339(feed_updated)
    ET.SubElement(feed, "generator").text = _GENERATOR
    ET.SubElement(feed, "link", {"rel": "self", "href": meta.self_url})
    ET.SubElement(feed, "link", {"rel": "alternate", "href": meta.home_url})
    author = ET.SubElement(feed, "author")
    ET.SubElement(author, "name").text = _GENERATOR

    for entry in entries:
        e = ET.SubElement(feed, "entry")
        ET.SubElement(e, "id").text = entry.entry_id
        ET.SubElement(e, "title").text = entry.title
        ET.SubElement(e, "updated").text = _rfc3339(_entry_updated(entry, feed_updated))
        ET.SubElement(e, "summary", {"type": "text"}).text = entry.summary
        ET.SubElement(e, "category", {"term": entry.severity})

    return _xml_document(feed)


def _render_json(meta: FeedMeta, entries: List[FeedEntry]) -> str:
    """Render the feed as a JSON Feed 1.1 document string."""
    feed_updated = _feed_updated(meta, entries)
    items = []
    for entry in entries:
        items.append(
            {
                "id": entry.entry_id,
                "title": entry.title,
                "content_text": entry.summary,
                "date_published": _rfc3339(_entry_updated(entry, feed_updated)),
                # Severity is exposed both as a JSON Feed tag and in the ``_apiome`` extension object.
                "tags": [entry.severity] + (["breaking"] if entry.breaking else []),
                "_apiome": {
                    "change_type": entry.change_type,
                    "item_type": entry.item_type,
                    "item_name": entry.item_name,
                    "severity": entry.severity,
                    "breaking": entry.breaking,
                    "endpoint_slug": entry.endpoint_slug,
                    "version_tag": entry.version_tag,
                    "version_seq": entry.version_seq,
                },
            }
        )
    doc = {
        "version": _JSON_FEED_VERSION,
        "title": meta.title,
        "description": meta.description,
        "home_page_url": meta.home_url,
        "feed_url": meta.self_url,
        "items": items,
    }
    return json.dumps(doc, ensure_ascii=False)


def _xml_document(root: ET.Element) -> str:
    """Serialize an ElementTree root to a full XML document string (declaration + body)."""
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body


#: Renderer per format.
_RENDERERS = {
    FORMAT_RSS: _render_rss,
    FORMAT_ATOM: _render_atom,
    FORMAT_JSON: _render_json,
}


def render_feed(meta: FeedMeta, entries: List[FeedEntry], fmt: str) -> str:
    """Serialize a feed model into the requested format (MCAT-19.4).

    Args:
        meta: The feed-level metadata.
        entries: The feed entries, in the order they should appear (typically newest first).
        fmt: One of :data:`FEED_FORMATS` (as returned by :func:`normalize_format`).

    Returns:
        The serialized feed document — an RSS/Atom XML string or a JSON Feed string.

    Raises:
        ValueError: If ``fmt`` is not a supported format (the route validates first, so this only
            guards against a programming error).
    """
    renderer = _RENDERERS.get(fmt)
    if renderer is None:
        raise ValueError(f"unsupported feed format: {fmt!r}")
    return renderer(meta, entries)


def feed_etag(body: str) -> str:
    """Return a strong, content-addressed ETag for a rendered feed body.

    Hashing the rendered bytes means the ETag changes exactly when the feed does (a new snapshot, a
    new change) and stays stable otherwise, so a polling reader gets a clean ``304 Not Modified``
    until the catalog actually moves.

    Args:
        body: The rendered feed document.

    Returns:
        A quoted ETag value suitable for the ``ETag`` response header.
    """
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return f'"{digest}"'


__all__ = [
    "FORMAT_RSS",
    "FORMAT_ATOM",
    "FORMAT_JSON",
    "FEED_FORMATS",
    "FEED_MEDIA_TYPES",
    "SEVERITY_ADDITIVE",
    "SEVERITY_REVIEW",
    "SEVERITY_BREAKING",
    "FeedMeta",
    "FeedEntry",
    "normalize_format",
    "build_entry",
    "render_feed",
    "feed_etag",
]
