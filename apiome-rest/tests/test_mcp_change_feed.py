"""Tests for the catalog change feed (V2-MCP-33.4 / MCAT-19.4, #4653).

Two layers:

* **Renderer unit tests** exercise the pure :mod:`app.mcp_change_feed` layer directly — format
  negotiation, the change-row → entry projection (severity, the breaking flag and ``[breaking]``
  title suffix, stable ids, timestamp coalescing), the three well-formed serializations (RSS 2.0,
  Atom 1.0, JSON Feed 1.1), XML escaping of hostile item names, the empty-feed shape, and the
  content-addressed ETag — all without a database.
* **Route tests** drive ``GET /mcp/feed/{tenant}/{slug}`` and ``GET /mcp/feed/{tenant}`` against a
  mocked ``db`` (mirroring ``test_mcp_badge.py``): anonymous access, content types + cache headers,
  the empty (never ``404``) feed for an unresolved/private endpoint, format negotiation and the
  ``400`` on a bad format, conditional-request ``304`` handling, and public gating.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch
from xml.dom import minidom

from fastapi.testclient import TestClient

from app.main import app
from app.mcp_change_feed import (
    FEED_FORMATS,
    FeedMeta,
    build_entry,
    feed_etag,
    normalize_format,
    render_feed,
)

client = TestClient(app)

_EP_FEED = "/mcp/feed/acme/weather"
_CATALOG_FEED = "/mcp/feed/acme"

_META = FeedMeta(
    title="Weather — MCP change feed",
    feed_id="urn:apiome:mcp-feed:endpoint:acme/weather",
    self_url="http://testserver/mcp/feed/acme/weather?format=rss",
    home_url="http://testserver/",
    description="Change feed for the Weather MCP server.",
    updated=datetime(2026, 7, 7, tzinfo=timezone.utc),
)


def _change(**over):
    """A persisted change row (+ snapshot context) as the feed DB reads return it."""
    base = {
        "version_id": "22222222-2222-2222-2222-222222222222",
        "change_type": "added",
        "item_type": "tool",
        "item_name": "getWeather",
        "detail": {"after": {"name": "getWeather"}},
        "created_at": "2026-07-06T12:00:00+00:00",
        "version_seq": 3,
        "version_tag": "2026-07-06T12:00Z",
        "discovered_at": "2026-07-06T12:00:00+00:00",
        "version_created_at": "2026-07-06T12:00:00+00:00",
    }
    base.update(over)
    return base


def _entry(**over):
    """Build one entry for a fixed endpoint from a change row (override change fields per test)."""
    return build_entry(
        _change(**over),
        endpoint_id="11111111-1111-1111-1111-111111111111",
        endpoint_name="Weather",
        endpoint_slug="weather",
    )


# ===========================================================================================
# Format negotiation
# ===========================================================================================


def test_normalize_format_accepts_known_and_defaults_to_rss():
    for fmt in FEED_FORMATS:
        assert normalize_format(fmt) == fmt
        assert normalize_format(fmt.upper()) == fmt
    assert normalize_format(None) == "rss"
    assert normalize_format("") == "rss"


def test_normalize_format_rejects_unknown():
    assert normalize_format("xml") is None
    assert normalize_format("bogus") is None


# ===========================================================================================
# Entry projection
# ===========================================================================================


def test_added_entry_is_additive_not_breaking():
    e = _entry(change_type="added", item_type="tool", item_name="getWeather")
    assert e.severity == "additive"
    assert e.breaking is False
    assert e.title == "Added tool: getWeather"
    assert "[breaking]" not in e.title
    assert "getWeather" in e.summary


def test_removed_entry_is_breaking_and_flagged_in_title():
    e = _entry(change_type="removed", item_type="tool", item_name="oldTool", detail={"before": {"name": "oldTool"}})
    assert e.severity == "breaking"
    assert e.breaking is True
    assert e.title == "Removed tool: oldTool [breaking]"


def test_resource_template_and_server_labels_are_readable():
    rt = _entry(item_type="resource_template", item_name="doc://{id}")
    assert rt.title.startswith("Added resource template:")
    server = _entry(change_type="modified", item_type="server", item_name="server_version",
                    detail={"before": {}, "after": {}})
    assert "server metadata" in server.title


def test_entry_id_is_stable_and_unique_per_change():
    a = _entry(item_name="getWeather")
    a2 = _entry(item_name="getWeather")
    b = _entry(item_name="getForecast")
    assert a.entry_id == a2.entry_id  # stable for the same change
    assert a.entry_id != b.entry_id  # differs when the item differs
    assert a.entry_id.startswith("urn:apiome:mcp-change:")


def test_entry_updated_coalesces_discovered_then_created():
    with_disc = _entry(discovered_at="2026-07-06T12:00:00+00:00", version_created_at="2026-01-01T00:00:00+00:00")
    assert with_disc.updated.isoformat() == "2026-07-06T12:00:00+00:00"
    # No discovered_at → fall back to the version's persist time.
    fell_back = _entry(discovered_at=None, version_created_at="2026-01-01T00:00:00+00:00")
    assert fell_back.updated.isoformat() == "2026-01-01T00:00:00+00:00"


def test_entry_version_seq_and_tag_carried():
    e = _entry(version_seq=7, version_tag="2026-07-06T12:00Z")
    assert e.version_seq == 7
    assert e.version_tag == "2026-07-06T12:00Z"


# ===========================================================================================
# RSS rendering
# ===========================================================================================


def test_render_rss_is_well_formed_and_carries_entries():
    entries = [_entry(item_name="getWeather"), _entry(change_type="removed", item_name="oldTool",
                                                      detail={"before": {"name": "oldTool"}})]
    xml = render_feed(_META, entries, "rss")
    doc = minidom.parseString(xml)  # parses as XML (malformed feed would raise)
    assert doc.documentElement.tagName == "rss"
    assert "<title>Weather — MCP change feed</title>" in xml
    assert "Added tool: getWeather" in xml
    assert "Removed tool: oldTool [breaking]" in xml
    # Severity doubles as the RSS category so a breaking entry is machine-filterable.
    assert "<category>breaking</category>" in xml
    assert "isPermaLink=\"false\"" in xml


def test_render_rss_empty_feed_is_valid():
    xml = render_feed(_META, [], "rss")
    doc = minidom.parseString(xml)
    assert doc.documentElement.tagName == "rss"
    assert "<item>" not in xml


# ===========================================================================================
# Atom rendering
# ===========================================================================================


def test_render_atom_is_well_formed_and_namespaced():
    entries = [_entry(item_name="getWeather")]
    xml = render_feed(_META, entries, "atom")
    doc = minidom.parseString(xml)
    assert doc.documentElement.tagName == "feed"
    assert 'xmlns="http://www.w3.org/2005/Atom"' in xml
    assert "<id>urn:apiome:mcp-feed:endpoint:acme/weather</id>" in xml
    assert "<entry>" in xml
    assert 'term="additive"' in xml
    # Atom requires an author somewhere in the document.
    assert "<author>" in xml


def test_render_atom_empty_feed_still_has_required_children():
    xml = render_feed(_META, [], "atom")
    doc = minidom.parseString(xml)
    assert doc.documentElement.tagName == "feed"
    assert "<updated>" in xml
    assert "<entry>" not in xml


# ===========================================================================================
# JSON Feed rendering
# ===========================================================================================


def test_render_json_feed_is_valid_and_flags_breaking():
    entries = [
        _entry(item_name="getWeather"),
        _entry(change_type="removed", item_name="oldTool", detail={"before": {"name": "oldTool"}}),
    ]
    body = render_feed(_META, entries, "json")
    doc = json.loads(body)  # must parse as valid JSON
    assert doc["version"] == "https://jsonfeed.org/version/1.1"
    assert doc["title"] == "Weather — MCP change feed"
    assert doc["feed_url"].endswith("format=rss")
    assert len(doc["items"]) == 2
    added, removed = doc["items"]
    assert added["title"] == "Added tool: getWeather"
    assert "breaking" not in added["tags"]
    assert "breaking" in removed["tags"]
    assert removed["_apiome"]["breaking"] is True
    assert removed["_apiome"]["change_type"] == "removed"


def test_render_json_empty_feed_has_empty_items():
    doc = json.loads(render_feed(_META, [], "json"))
    assert doc["items"] == []


# ===========================================================================================
# Escaping & ETag
# ===========================================================================================


def test_hostile_item_name_cannot_break_the_xml():
    nasty = '"><script>alert(1)</script>'
    for fmt in ("rss", "atom"):
        xml = render_feed(_META, [_entry(item_name=nasty)], fmt)
        assert "<script>" not in xml
        minidom.parseString(xml)  # still well-formed after escaping
    # JSON escaping keeps it valid too.
    json.loads(render_feed(_META, [_entry(item_name=nasty)], "json"))


def test_feed_etag_is_stable_and_content_addressed():
    a = render_feed(_META, [_entry(item_name="getWeather")], "rss")
    b = render_feed(_META, [_entry(item_name="getForecast")], "rss")
    assert feed_etag(a) == feed_etag(a)  # stable
    assert feed_etag(a) != feed_etag(b)  # changes when the feed changes
    assert feed_etag(a).startswith('"') and feed_etag(a).endswith('"')


# ===========================================================================================
# Endpoint feed route
# ===========================================================================================


def _head(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Weather",
        "slug": "weather",
        "description": "A weather MCP server.",
    }
    base.update(over)
    return base


def test_endpoint_feed_renders_rss_with_cache_headers():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = _head()
        mdb.get_public_mcp_endpoint_changes.return_value = [
            _change(item_name="getWeather"),
            _change(change_type="removed", item_name="oldTool", detail={"before": {"name": "oldTool"}}),
        ]
        resp = client.get(_EP_FEED)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/rss+xml; charset=utf-8"
    assert "public, max-age=300" in resp.headers["cache-control"]
    assert resp.headers["etag"]
    assert "Added tool: getWeather" in resp.text
    assert "Removed tool: oldTool [breaking]" in resp.text
    minidom.parseString(resp.text)
    mdb.get_public_mcp_endpoint_feed_head.assert_called_once_with("acme", "weather")
    _args, kwargs = mdb.get_public_mcp_endpoint_changes.call_args
    assert _args[0] == "11111111-1111-1111-1111-111111111111"
    assert kwargs["limit"] == 50


def test_endpoint_feed_unknown_or_private_is_empty_feed_not_404():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = None  # private / unpublished / unknown
        resp = client.get(_EP_FEED)
    assert resp.status_code == 200  # never 404 — no existence disclosure
    assert "<item>" not in resp.text  # no change data leaked
    minidom.parseString(resp.text)
    # A non-public target's change history is never even queried.
    mdb.get_public_mcp_endpoint_changes.assert_not_called()


def test_endpoint_feed_atom_and_json_formats():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = _head()
        mdb.get_public_mcp_endpoint_changes.return_value = [_change()]
        atom = client.get(_EP_FEED, params={"format": "atom"})
        js = client.get(_EP_FEED, params={"format": "json"})
    assert atom.status_code == 200
    assert atom.headers["content-type"] == "application/atom+xml; charset=utf-8"
    minidom.parseString(atom.text)
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("application/feed+json")
    assert js.json()["version"] == "https://jsonfeed.org/version/1.1"


def test_endpoint_feed_bad_format_is_400():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = _head()
        resp = client.get(_EP_FEED, params={"format": "xml"})
    assert resp.status_code == 400


def test_endpoint_feed_conditional_request_returns_304():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = _head()
        mdb.get_public_mcp_endpoint_changes.return_value = [_change()]
        first = client.get(_EP_FEED)
        etag = first.headers["etag"]
        second = client.get(_EP_FEED, headers={"If-None-Match": etag})
    assert first.status_code == 200
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""


def test_endpoint_feed_is_anonymous():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_mcp_endpoint_feed_head.return_value = _head()
        mdb.get_public_mcp_endpoint_changes.return_value = []
        resp = client.get(_EP_FEED)  # no Authorization header
    assert resp.status_code == 200


# ===========================================================================================
# Catalog feed route
# ===========================================================================================


def _catalog_change(**over):
    """A catalog-wide change row, carrying its owning endpoint's identity."""
    base = _change(**over)
    base.setdefault("endpoint_id", "11111111-1111-1111-1111-111111111111")
    base.setdefault("endpoint_name", "Weather")
    base.setdefault("endpoint_slug", "weather")
    return base


def test_catalog_feed_renders_changes_across_endpoints():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_catalog_changes.return_value = [
            _catalog_change(item_name="getWeather"),
            _catalog_change(endpoint_name="Docs", endpoint_slug="docs",
                            change_type="removed", item_name="oldPrompt", item_type="prompt",
                            detail={"before": {"name": "oldPrompt"}}),
        ]
        resp = client.get(_CATALOG_FEED)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/rss+xml; charset=utf-8"
    assert "acme — MCP catalog change feed" in resp.text
    assert "Added tool: getWeather" in resp.text
    assert "Removed prompt: oldPrompt [breaking]" in resp.text
    minidom.parseString(resp.text)
    _args, kwargs = mdb.get_public_catalog_changes.call_args
    assert _args[0] == "acme"
    assert kwargs["limit"] == 50


def test_catalog_feed_empty_catalog_is_valid_empty_feed():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_catalog_changes.return_value = []
        resp = client.get(_CATALOG_FEED)
    assert resp.status_code == 200
    assert "<item>" not in resp.text
    minidom.parseString(resp.text)


def test_catalog_feed_json_format_and_bad_format():
    with patch("app.mcp_feed_routes.db") as mdb:
        mdb.get_public_catalog_changes.return_value = [_catalog_change()]
        good = client.get(_CATALOG_FEED, params={"format": "json"})
        bad = client.get(_CATALOG_FEED, params={"format": "csv"})
    assert good.status_code == 200
    assert good.json()["items"][0]["_apiome"]["endpoint_slug"] == "weather"
    assert bad.status_code == 400
