"""API + projection tests for the private MCP browse view (V2-MCP-23.1 / MCAT-9.1, #3691).

Covers the tenant-scoped ``GET /v1/mcp/{tenant_slug}/browse`` route — endpoints grouped by
host with capability counts, score/grade, and last-discovered — plus the pure grouping /
projection helpers (:func:`group_mcp_browse_endpoints`, :func:`mcp_browse_endpoint_out_from_row`,
:func:`mcp_endpoint_host`) that build it. The browse *detail* half reuses the existing endpoint
and version-detail reads, which are covered by ``test_mcp_catalog_routes`` /
``test_mcp_version_compare_routes``.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import (
    group_mcp_browse_endpoints,
    mcp_browse_endpoint_out_from_row,
    mcp_endpoint_host,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}

_NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


def _browse_row(**overrides):
    """A :meth:`Database.browse_mcp_endpoints` row with sane defaults, overridable per test."""
    row = {
        "id": "ep-1",
        "tenant_id": "t1",
        "name": "Acme Weather",
        "slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/sse",
        "transport": "streamable_http",
        "description": "Weather tools",
        "category": "weather",
        "visibility": "private",
        "published": False,
        "enabled": True,
        "last_discovered_at": _NOW,
        "last_discovery_status": "ok",
        "quarantined_at": None,
        "current_version_id": "ver-1",
        "score": 87,
        "grade": "B",
        "scored_at": _NOW,
        "tool_count": 3,
        "resource_count": 2,
        "resource_template_count": 1,
        "prompt_count": 4,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    """Default every test to an authenticated JWT caller in tenant ``t1``."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Host extraction helper
# ===========================================================================


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://mcp.acme.example/sse", "mcp.acme.example"),
        ("https://MCP.Acme.Example:8443/mcp", "mcp.acme.example"),
        ("https://tok@mcp.acme.example/sse", "mcp.acme.example"),
        ("stdio:///usr/local/bin/server", "(local)"),
        ("", "(local)"),
    ],
)
def test_mcp_endpoint_host(url, expected):
    assert mcp_endpoint_host(url) == expected


def test_mcp_endpoint_host_none():
    assert mcp_endpoint_host(None) == "(local)"


# ===========================================================================
# Row projection helper
# ===========================================================================


def test_browse_row_projection_rolls_up_counts_and_redacts():
    out = mcp_browse_endpoint_out_from_row(
        _browse_row(endpoint_url="https://user:secret@mcp.acme.example/sse")
    )
    # Capability total is the sum of the four per-kind counts.
    assert out.capability_count == 3 + 2 + 1 + 4
    assert out.tool_count == 3
    assert out.resource_template_count == 1
    # Host is derived; userinfo is redacted out of the wire URL but the host is kept.
    assert out.host == "mcp.acme.example"
    assert "secret" not in out.endpoint_url
    assert "***@mcp.acme.example" in out.endpoint_url
    assert out.score == 87
    assert out.grade == "B"
    assert out.last_discovered_at.startswith("2026-06-26")


def test_browse_row_projection_unscored_undiscovered():
    out = mcp_browse_endpoint_out_from_row(
        _browse_row(
            current_version_id=None,
            score=None,
            grade=None,
            last_discovered_at=None,
            tool_count=0,
            resource_count=0,
            resource_template_count=0,
            prompt_count=0,
        )
    )
    assert out.score is None
    assert out.grade is None
    assert out.capability_count == 0
    assert out.current_version_id is None
    assert out.last_discovered_at is None


def test_browse_row_projection_quarantined_flag():
    assert mcp_browse_endpoint_out_from_row(_browse_row(quarantined_at=_NOW)).quarantined is True
    assert mcp_browse_endpoint_out_from_row(_browse_row(quarantined_at=None)).quarantined is False


def test_browse_row_projection_branding_present():
    """The current snapshot's ``server_branding`` JSON projects onto the card model (#4656)."""
    out = mcp_browse_endpoint_out_from_row(
        _browse_row(
            server_branding={
                "website_url": "https://acme.example/",
                "icon_url": "https://acme.example/logo.png",
                "icon_mime_type": "image/png",
            }
        )
    )
    assert out.server_branding is not None
    assert out.server_branding.icon_url == "https://acme.example/logo.png"
    assert out.server_branding.website_url == "https://acme.example/"


def test_browse_row_projection_branding_absent_is_none():
    """A missing/empty ``server_branding`` reads back as ``None`` so the card falls back to text."""
    assert mcp_browse_endpoint_out_from_row(_browse_row()).server_branding is None
    assert mcp_browse_endpoint_out_from_row(_browse_row(server_branding=None)).server_branding is None
    assert mcp_browse_endpoint_out_from_row(_browse_row(server_branding={})).server_branding is None


# ===========================================================================
# Grouping helper
# ===========================================================================


def test_group_by_host_buckets_and_sorts():
    rows = [
        _browse_row(id="a", name="Z svc", endpoint_url="https://zeta.example/sse", tool_count=1,
                    resource_count=0, resource_template_count=0, prompt_count=0),
        _browse_row(id="b", name="A svc", endpoint_url="https://alpha.example/sse", tool_count=2,
                    resource_count=0, resource_template_count=0, prompt_count=0),
        _browse_row(id="c", name="B svc", endpoint_url="https://alpha.example/other", tool_count=5,
                    resource_count=0, resource_template_count=0, prompt_count=0),
    ]
    resp = group_mcp_browse_endpoints(rows)
    assert resp.host_count == 2
    assert resp.endpoint_count == 3
    # Groups are sorted by host name.
    assert [g.host for g in resp.groups] == ["alpha.example", "zeta.example"]
    alpha = resp.groups[0]
    assert alpha.endpoint_count == 2
    # Per-group capability count rolls up every endpoint in the bucket.
    assert alpha.capability_count == 2 + 5
    assert {e.id for e in alpha.endpoints} == {"b", "c"}


def test_group_empty():
    resp = group_mcp_browse_endpoints([])
    assert resp.host_count == 0
    assert resp.endpoint_count == 0
    assert resp.groups == []


# ===========================================================================
# Route
# ===========================================================================


def test_browse_route_ok_groups_by_host():
    rows = [
        _browse_row(id="a", name="Acme Weather", endpoint_url="https://mcp.acme.example/sse"),
        _browse_row(id="b", name="Acme Calendar", endpoint_url="https://mcp.acme.example/cal",
                    tool_count=1, resource_count=0, resource_template_count=0, prompt_count=0),
        _browse_row(id="c", name="Beta Tools", endpoint_url="https://beta.example/sse",
                    tool_count=0, resource_count=0, resource_template_count=0, prompt_count=0,
                    score=None, grade=None, current_version_id=None),
    ]
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.browse_mcp_endpoints.return_value = rows
        r = client.get("/v1/mcp/acme/browse")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["host_count"] == 2
    assert body["endpoint_count"] == 3
    hosts = [g["host"] for g in body["groups"]]
    assert hosts == ["beta.example", "mcp.acme.example"]
    acme = next(g for g in body["groups"] if g["host"] == "mcp.acme.example")
    assert acme["endpoint_count"] == 2
    first = acme["endpoints"][0]
    assert "tool_count" in first and "capability_count" in first
    assert first["score"] == 87 and first["grade"] == "B"


def test_browse_route_scoped_to_token_tenant():
    """DB is queried with the token's tenant_id, never the URL slug."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.browse_mcp_endpoints.return_value = []
        client.get("/v1/mcp/some-other-slug/browse")
        mdb.browse_mcp_endpoints.assert_called_once_with("t1")


def test_browse_route_empty():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.browse_mcp_endpoints.return_value = []
        r = client.get("/v1/mcp/acme/browse")
    assert r.status_code == 200
    body = r.json()
    assert body["host_count"] == 0
    assert body["groups"] == []


def test_browse_route_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/mcp/acme/browse")
    assert r.status_code == 401
