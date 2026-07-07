"""Tests for the embeddable status badge (V2-MCP-33.3 / MCAT-19.3, #4652).

Two layers:

* **Renderer unit tests** exercise the pure :mod:`app.mcp_badge` layer directly — metric/theme
  normalization, the grade/health/version → ``(label, message, color)`` resolution, the
  never-a-data-leak ``unknown`` fallback, XML escaping of hostile server-reported values, valid
  well-formed SVG output, the light/dark label variant, and the content-addressed ETag.
* **Route tests** drive ``GET /mcp/badge/{tenant}/{slug}.svg`` against a mocked ``db``: anonymous
  access, SVG content type + cache headers, the ``unknown`` (never ``404``) response for an
  unresolved endpoint, conditional-request ``304`` handling, and query selection of metric/theme.
"""

from __future__ import annotations

from unittest.mock import patch
from xml.dom import minidom

from fastapi.testclient import TestClient

from app.main import app
from app.mcp_badge import (
    BADGE_METRICS,
    BADGE_THEMES,
    UNKNOWN_MESSAGE,
    normalize_metric,
    normalize_theme,
    render_badge_svg,
    resolve_badge,
    svg_etag,
)

client = TestClient(app)

_BADGE_PATH = "/mcp/badge/acme/weather.svg"


def _published_row(**overrides):
    """A resolved (published, public) endpoint row as the DB layer returns it."""
    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "name": "Weather",
        "slug": "weather",
        "enabled": True,
        "last_discovered_at": "2026-07-06T12:00:00+00:00",
        "last_discovery_status": "success",
        "consecutive_failures": 0,
        "quarantined_at": None,
        "current_version_id": "22222222-2222-2222-2222-222222222222",
        "score": 88,
        "grade": "A",
        "server_version": "1.4.2",
        "version_seq": 3,
    }
    row.update(overrides)
    return row


# --- normalization ---------------------------------------------------------------------------------


def test_normalize_metric_accepts_known_and_defaults_to_grade():
    for metric in BADGE_METRICS:
        assert normalize_metric(metric) == metric
        assert normalize_metric(metric.upper()) == metric
    assert normalize_metric(None) == "grade"
    assert normalize_metric("") == "grade"
    assert normalize_metric("bogus") == "grade"


def test_normalize_theme_accepts_known_and_defaults_to_light():
    for theme in BADGE_THEMES:
        assert normalize_theme(theme) == theme
    assert normalize_theme(None) == "light"
    assert normalize_theme("neon") == "light"


# --- resolution ------------------------------------------------------------------------------------


def test_resolve_grade_maps_letter_to_color():
    label, message, color = resolve_badge(_published_row(grade="A"), "grade")
    assert label == "mcp grade"
    assert message == "A"
    assert color == "#4c1"  # bright green
    _, _, red = resolve_badge(_published_row(grade="F"), "grade")
    assert red == "#e05d44"


def test_resolve_grade_unknown_when_ungraded():
    label, message, color = resolve_badge(_published_row(grade=None), "grade")
    assert label == "mcp grade"
    assert message == UNKNOWN_MESSAGE
    assert color == "#9f9f9f"  # grey


def test_resolve_health_uses_derived_label_and_color():
    _, healthy, healthy_color = resolve_badge(_published_row(), "health")
    assert healthy == "healthy"
    assert healthy_color == "#4c1"

    _, failing, failing_color = resolve_badge(
        _published_row(consecutive_failures=3), "health"
    )
    assert failing == "failing"
    assert failing_color == "#e05d44"

    _, quarantined, _ = resolve_badge(
        _published_row(quarantined_at="2026-07-06T00:00:00+00:00"), "health"
    )
    assert quarantined == "quarantined"

    _, undiscovered, undiscovered_color = resolve_badge(
        _published_row(current_version_id=None, last_discovered_at=None), "health"
    )
    assert undiscovered == "undiscovered"
    assert undiscovered_color == "#9f9f9f"


def test_resolve_version_prefers_server_version_then_seq_then_unknown():
    _, message, color = resolve_badge(_published_row(server_version="2.0.0"), "version")
    assert message == "2.0.0"
    assert color == "#007ec6"  # blue

    _, seq_message, _ = resolve_badge(
        _published_row(server_version=None, version_seq=5), "version"
    )
    assert seq_message == "v5"

    _, unknown_message, unknown_color = resolve_badge(
        _published_row(server_version=None, version_seq=None), "version"
    )
    assert unknown_message == UNKNOWN_MESSAGE
    assert unknown_color == "#9f9f9f"


def test_resolve_none_row_is_neutral_unknown_for_every_metric():
    """A missing endpoint must never disclose anything — same neutral badge for every metric."""
    for metric in BADGE_METRICS:
        label, message, color = resolve_badge(None, metric)
        assert message == UNKNOWN_MESSAGE
        assert color == "#9f9f9f"
        assert label.startswith("mcp ")


# --- SVG rendering ---------------------------------------------------------------------------------


def test_render_badge_is_well_formed_svg():
    svg = render_badge_svg("mcp grade", "A", "#4c1", theme="light")
    # Parses as XML (a malformed badge would raise here).
    doc = minidom.parseString(svg)
    assert doc.documentElement.tagName == "svg"
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")


def test_render_escapes_hostile_message():
    """A server-reported version cannot inject markup into the SVG."""
    svg = render_badge_svg("mcp version", '"><script>alert(1)</script>', "#007ec6", theme="light")
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    # Still well-formed after escaping.
    minidom.parseString(svg)


def test_render_light_and_dark_use_different_label_backgrounds():
    light = render_badge_svg("mcp grade", "A", "#4c1", theme="light")
    dark = render_badge_svg("mcp grade", "A", "#4c1", theme="dark")
    assert 'fill="#555"' in light
    assert 'fill="#21262d"' in dark
    assert light != dark


def test_svg_etag_is_stable_and_content_addressed():
    a = render_badge_svg("mcp grade", "A", "#4c1", theme="light")
    b = render_badge_svg("mcp grade", "B", "#97ca00", theme="light")
    assert svg_etag(a) == svg_etag(a)  # stable
    assert svg_etag(a) != svg_etag(b)  # changes when the badge changes
    assert svg_etag(a).startswith('"') and svg_etag(a).endswith('"')


# --- route -----------------------------------------------------------------------------------------


def test_route_renders_published_badge_with_cache_headers():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = _published_row(grade="A")
        resp = client.get(_BADGE_PATH)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/svg+xml; charset=utf-8"
    assert "public, max-age=300" in resp.headers["cache-control"]
    assert resp.headers["etag"]
    assert ">A<" in resp.text
    minidom.parseString(resp.text)
    mdb.get_published_mcp_endpoint_badge.assert_called_once_with("acme", "weather")


def test_route_unknown_endpoint_is_neutral_badge_not_404():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = None
        resp = client.get(_BADGE_PATH)
    assert resp.status_code == 200  # never 404 — no existence disclosure
    assert UNKNOWN_MESSAGE in resp.text
    assert "public, max-age=60" in resp.headers["cache-control"]  # shorter for unknown


def test_route_metric_and_theme_query_selection():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = _published_row(server_version="9.9.9")
        resp = client.get(_BADGE_PATH, params={"metric": "version", "theme": "dark"})
    assert resp.status_code == 200
    assert ">9.9.9<" in resp.text
    assert 'fill="#21262d"' in resp.text  # dark label variant


def test_route_invalid_metric_falls_back_to_grade():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = _published_row(grade="C")
        resp = client.get(_BADGE_PATH, params={"metric": "nonsense"})
    assert resp.status_code == 200
    assert "mcp grade" in resp.text
    assert ">C<" in resp.text


def test_route_conditional_request_returns_304():
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = _published_row(grade="B")
        first = client.get(_BADGE_PATH)
        etag = first.headers["etag"]
        second = client.get(_BADGE_PATH, headers={"If-None-Match": etag})
    assert first.status_code == 200
    assert second.status_code == 304
    assert second.headers["etag"] == etag
    assert second.content == b""


def test_route_is_anonymous():
    """No Authorization header is required — a README's <img> fetches with no credentials."""
    with patch("app.mcp_badge_routes.db") as mdb:
        mdb.get_published_mcp_endpoint_badge.return_value = _published_row()
        resp = client.get(_BADGE_PATH)
    assert resp.status_code == 200
