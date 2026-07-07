"""Unit tests for server branding capture (MCAT-20.2, #4656).

Covers the pure branding layer end to end: URL validation (``safe_branding_url``), icon selection
and website validation (``extract_server_branding``), the storage projection
(``ServerBranding.to_row_value``), the ``ServerInfo`` parse of ``websiteUrl``/``icons``, and the
critical invariant that branding is captured on the version row **without** perturbing the surface
fingerprint (so a rebrand mints no spurious version and existing fingerprints are unchanged).
"""

import pytest

from app.mcp_client.branding import (
    MAX_BRANDING_URL_LENGTH,
    ServerBranding,
    extract_server_branding,
    safe_branding_url,
)
from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import DiscoverySurface

# ---------------------------------------------------------------------------
# safe_branding_url — the guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://cdn.example.com/logo.png",
        "https://sub.host.example.co.uk/a/b/c.svg?v=2",
        "https://example.com/logo.png#frag",
        "https://host",  # bare public hostname (no DNS resolution is done)
    ],
)
def test_safe_branding_url_accepts_public_https(url: str) -> None:
    assert safe_branding_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/logo.png",  # plaintext
        "data:image/png;base64,AAAA",  # inline payload
        "file:///etc/passwd",  # local file
        "javascript:alert(1)",  # never executable, and not https
        "ftp://example.com/logo.png",  # wrong scheme
        "//example.com/logo.png",  # scheme-relative (no scheme)
        "/relative/logo.png",  # relative
        "example.com/logo.png",  # no scheme
        "https://",  # no host
        "https://127.0.0.1/logo.png",  # loopback literal
        "https://10.0.0.1/logo.png",  # RFC 1918 private literal
        "https://192.168.1.5/logo.png",  # RFC 1918 private literal
        "https://169.254.1.1/logo.png",  # link-local literal
        "https://[::1]/logo.png",  # IPv6 loopback literal
        "https://[::ffff:10.0.0.1]/logo.png",  # IPv4-mapped IPv6 private literal
        "",  # empty
        "   ",  # whitespace only
    ],
)
def test_safe_branding_url_rejects_unsafe(url: str) -> None:
    assert safe_branding_url(url) is None


def test_safe_branding_url_rejects_non_string() -> None:
    for value in (None, 123, {"src": "https://x"}, ["https://x"], True):
        assert safe_branding_url(value) is None


def test_safe_branding_url_rejects_overlong() -> None:
    too_long = "https://example.com/" + ("a" * MAX_BRANDING_URL_LENGTH)
    assert len(too_long) > MAX_BRANDING_URL_LENGTH
    assert safe_branding_url(too_long) is None


def test_safe_branding_url_strips_surrounding_whitespace() -> None:
    assert safe_branding_url("  https://example.com/logo.png  ") == "https://example.com/logo.png"


# ---------------------------------------------------------------------------
# ServerInfo parse of branding
# ---------------------------------------------------------------------------


def test_server_info_parses_website_and_icons() -> None:
    si = ServerInfo.from_dict(
        {
            "name": "ex",
            "title": "Example",
            "version": "1.0",
            "websiteUrl": "https://example.com/",
            "icons": [
                {"src": "https://cdn.example.com/logo.png", "mimeType": "image/png", "sizes": ["48x48"]},
                {"src": "https://cdn.example.com/logo.svg"},
            ],
        }
    )
    assert si.website_url == "https://example.com/"
    assert len(si.icons) == 2
    assert si.icons[0]["src"] == "https://cdn.example.com/logo.png"


def test_server_info_branding_absent_defaults() -> None:
    si = ServerInfo.from_dict({"name": "ex"})
    assert si.website_url is None
    assert si.icons == ()


@pytest.mark.parametrize("bad_icons", [None, "not-a-list", 42, {"src": "https://x"}])
def test_server_info_ignores_non_list_icons(bad_icons: object) -> None:
    si = ServerInfo.from_dict({"name": "ex", "icons": bad_icons})
    assert si.icons == ()


def test_server_info_drops_non_object_icon_entries() -> None:
    si = ServerInfo.from_dict({"name": "ex", "icons": ["str", 5, None, {"src": "https://ok.example/i"}]})
    assert len(si.icons) == 1
    assert si.icons[0]["src"] == "https://ok.example/i"


# ---------------------------------------------------------------------------
# extract_server_branding — selection + validation
# ---------------------------------------------------------------------------


def test_extract_full_branding() -> None:
    si = ServerInfo.from_dict(
        {
            "websiteUrl": "https://example.com/",
            "icons": [{"src": "https://cdn.example.com/logo.png", "mimeType": "image/png"}],
        }
    )
    branding = extract_server_branding(si)
    assert branding == ServerBranding(
        website_url="https://example.com/",
        icon_url="https://cdn.example.com/logo.png",
        icon_mime_type="image/png",
    )


def test_extract_selects_first_safe_icon_in_order() -> None:
    """Unsafe icons are skipped; the first icon that clears the guard wins (server preference)."""
    si = ServerInfo.from_dict(
        {
            "icons": [
                {"src": "https://10.0.0.1/logo"},  # SSRF literal — skipped
                {"src": "data:image/png;base64,AAAA"},  # inline — skipped
                {"src": "https://ok.example/i.svg", "mimeType": "image/svg+xml"},  # selected
                {"src": "https://also.example/j.png"},  # never reached
            ]
        }
    )
    branding = extract_server_branding(si)
    assert branding.icon_url == "https://ok.example/i.svg"
    assert branding.icon_mime_type == "image/svg+xml"


def test_extract_drops_unsafe_website_keeps_icon() -> None:
    si = ServerInfo.from_dict(
        {"websiteUrl": "http://example.com", "icons": [{"src": "https://ok.example/i.png"}]}
    )
    branding = extract_server_branding(si)
    assert branding.website_url is None
    assert branding.icon_url == "https://ok.example/i.png"


def test_extract_blank_mime_type_becomes_none() -> None:
    si = ServerInfo.from_dict({"icons": [{"src": "https://ok.example/i.png", "mimeType": "   "}]})
    assert extract_server_branding(si).icon_mime_type is None


def test_extract_non_string_mime_type_becomes_none() -> None:
    si = ServerInfo.from_dict({"icons": [{"src": "https://ok.example/i.png", "mimeType": 123}]})
    assert extract_server_branding(si).icon_mime_type is None


def test_extract_empty_when_nothing_advertised() -> None:
    branding = extract_server_branding(ServerInfo.from_dict({"name": "ex"}))
    assert branding.is_empty()
    assert branding.to_row_value() is None


def test_extract_empty_when_all_unsafe() -> None:
    si = ServerInfo.from_dict(
        {"websiteUrl": "http://x", "icons": [{"src": "https://127.0.0.1/i"}, {"src": "data:..."}]}
    )
    assert extract_server_branding(si).is_empty()


# ---------------------------------------------------------------------------
# ServerBranding.to_row_value — storage projection
# ---------------------------------------------------------------------------


def test_to_row_value_omits_absent_fields() -> None:
    assert ServerBranding(icon_url="https://x/i.png").to_row_value() == {"icon_url": "https://x/i.png"}
    assert ServerBranding(website_url="https://x/").to_row_value() == {"website_url": "https://x/"}


def test_to_row_value_empty_is_none() -> None:
    assert ServerBranding().to_row_value() is None


def test_to_row_value_full() -> None:
    assert ServerBranding(
        website_url="https://x/", icon_url="https://x/i.png", icon_mime_type="image/png"
    ).to_row_value() == {
        "website_url": "https://x/",
        "icon_url": "https://x/i.png",
        "icon_mime_type": "image/png",
    }


# ---------------------------------------------------------------------------
# Integration with the version row + the fingerprint invariant
# ---------------------------------------------------------------------------


def test_to_version_row_carries_validated_branding() -> None:
    si = ServerInfo.from_dict(
        {
            "name": "ex",
            "title": "Example",
            "version": "1.0",
            "websiteUrl": "https://example.com/",
            "icons": [{"src": "https://cdn.example.com/logo.png", "mimeType": "image/png"}],
        }
    )
    row = DiscoverySurface(server_info=si).to_version_row()
    assert row["server_branding"] == {
        "website_url": "https://example.com/",
        "icon_url": "https://cdn.example.com/logo.png",
        "icon_mime_type": "image/png",
    }


def test_to_version_row_branding_none_when_absent() -> None:
    row = DiscoverySurface(server_info=ServerInfo(name="ex")).to_version_row()
    assert row["server_branding"] is None


def test_branding_excluded_from_surface_fingerprint() -> None:
    """The whole point: branding is descriptive, so it must not perturb the surface fingerprint.

    A server that adds branding (and one that changes it) yields the *same* fingerprint as the
    identical surface with no branding — so a rebrand mints no spurious version and existing
    fingerprints are unchanged after this feature ships.
    """
    base = ServerInfo(name="ex", title="Example", version="1.0")
    branded = ServerInfo.from_dict(
        {
            "name": "ex",
            "title": "Example",
            "version": "1.0",
            "websiteUrl": "https://example.com/",
            "icons": [{"src": "https://cdn.example.com/logo.png"}],
        }
    )
    rebranded = ServerInfo.from_dict(
        {
            "name": "ex",
            "title": "Example",
            "version": "1.0",
            "websiteUrl": "https://elsewhere.example/",
            "icons": [{"src": "https://cdn.example.com/new-logo.png"}],
        }
    )
    fp_base = DiscoverySurface(server_info=base).fingerprint()
    fp_branded = DiscoverySurface(server_info=branded).fingerprint()
    fp_rebranded = DiscoverySurface(server_info=rebranded).fingerprint()
    assert fp_base == fp_branded == fp_rebranded
