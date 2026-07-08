"""Unit tests for MCP catalog duplicate detection (V2-MCP-36.1 / MCAT-22.1, #4664)."""

from app.mcp_duplicate_detection import (
    build_mcp_cross_tenant_hints,
    build_mcp_duplicate_groups,
    mcp_duplicate_report_from_rows,
    normalize_mcp_endpoint_url_for_dedup,
)


def _candidate(
    *,
    id: str,
    name: str,
    slug: str,
    endpoint_url: str,
    transport: str = "streamable_http",
    surface_fingerprint: str | None = None,
    published: bool = False,
    visibility: str = "private",
    tenant_id: str = "t1",
) -> dict:
    return {
        "id": id,
        "tenant_id": tenant_id,
        "name": name,
        "slug": slug,
        "endpoint_url": endpoint_url,
        "transport": transport,
        "surface_fingerprint": surface_fingerprint,
        "published": published,
        "visibility": visibility,
    }


def test_normalize_url_lowercases_host_and_trims_trailing_slash():
    assert (
        normalize_mcp_endpoint_url_for_dedup(
            "HTTPS://MCP.Acme.Example/sse/",
            transport="streamable_http",
        )
        == "https://mcp.acme.example/sse"
    )


def test_normalize_url_strips_userinfo_for_dedup():
    a = normalize_mcp_endpoint_url_for_dedup(
        "https://user:secret@mcp.acme.example/sse",
        transport="streamable_http",
    )
    b = normalize_mcp_endpoint_url_for_dedup(
        "https://other:token@mcp.acme.example/sse",
        transport="streamable_http",
    )
    assert a == b == "https://mcp.acme.example/sse"


def test_normalize_stdio_target_is_trimmed_exact():
    cmd = "  npx -y @modelcontextprotocol/server-everything  "
    assert normalize_mcp_endpoint_url_for_dedup(cmd, transport="stdio") == cmd.strip()


def test_exact_url_duplicate_group_on_seeded_like_rows():
    rows = [
        _candidate(id="ep-1", name="Weather A", slug="weather-a", endpoint_url="https://mcp.acme.example/sse"),
        _candidate(id="ep-2", name="Weather B", slug="weather-b", endpoint_url="https://mcp.acme.example/sse/"),
    ]
    groups = build_mcp_duplicate_groups(rows)
    assert len(groups) == 1
    assert groups[0].kind == "exact_url"
    assert {e.id for e in groups[0].endpoints} == {"ep-1", "ep-2"}


def test_identical_surface_fingerprint_group():
    rows = [
        _candidate(
            id="ep-1",
            name="Alpha",
            slug="alpha",
            endpoint_url="https://alpha.example/mcp",
            surface_fingerprint="fp-shared",
        ),
        _candidate(
            id="ep-2",
            name="Beta",
            slug="beta",
            endpoint_url="https://beta.example/mcp",
            surface_fingerprint="fp-shared",
        ),
    ]
    groups = build_mcp_duplicate_groups(rows)
    kinds = {g.kind for g in groups}
    assert "identical_surface" in kinds
    surface = next(g for g in groups if g.kind == "identical_surface")
    assert surface.match_key == "fp-shared"
    assert {e.id for e in surface.endpoints} == {"ep-1", "ep-2"}


def test_distinct_servers_on_different_hosts_not_flagged():
    rows = [
        _candidate(
            id="ep-1",
            name="Alpha",
            slug="alpha",
            endpoint_url="https://alpha.example/mcp",
            surface_fingerprint="fp-alpha",
        ),
        _candidate(
            id="ep-2",
            name="Beta",
            slug="beta",
            endpoint_url="https://beta.example/mcp",
            surface_fingerprint="fp-beta",
        ),
    ]
    assert build_mcp_duplicate_groups(rows) == []


def test_same_host_near_duplicate_when_fingerprints_do_not_prove_distinct():
    rows = [
        _candidate(
            id="ep-1",
            name="Path A",
            slug="path-a",
            endpoint_url="https://mcp.acme.example/sse",
            surface_fingerprint="fp-a",
        ),
        _candidate(
            id="ep-2",
            name="Path B",
            slug="path-b",
            endpoint_url="https://mcp.acme.example/mcp",
            surface_fingerprint=None,
        ),
    ]
    groups = build_mcp_duplicate_groups(rows)
    assert any(g.kind == "same_host" for g in groups)


def test_same_host_skipped_when_fingerprints_are_all_distinct():
    rows = [
        _candidate(
            id="ep-1",
            name="Tools",
            slug="tools",
            endpoint_url="https://shared.example/tools",
            surface_fingerprint="fp-tools",
        ),
        _candidate(
            id="ep-2",
            name="Resources",
            slug="resources",
            endpoint_url="https://shared.example/resources",
            surface_fingerprint="fp-resources",
        ),
    ]
    kinds = {g.kind for g in build_mcp_duplicate_groups(rows)}
    assert "same_host" not in kinds


def test_cross_tenant_hint_for_matching_published_url():
    local = [
        _candidate(
            id="ep-1",
            name="Local Weather",
            slug="local-weather",
            endpoint_url="https://mcp.acme.example/sse",
            published=True,
        )
    ]
    foreign = [
        {
            "id": "ep-9",
            "tenant_id": "t2",
            "tenant_slug": "other-tenant",
            "name": "Foreign Weather",
            "slug": "foreign-weather",
            "endpoint_url": "https://mcp.acme.example/sse/",
            "transport": "streamable_http",
            "surface_fingerprint": None,
        }
    ]
    hints = build_mcp_cross_tenant_hints("t1", local, foreign)
    assert len(hints) == 1
    assert hints[0].kind == "exact_url"
    assert hints[0].foreign_tenant_slug == "other-tenant"
    assert hints[0].local_endpoint_ids == ["ep-1"]


def test_report_envelope_counts_flagged_endpoints():
    rows = [
        _candidate(id="ep-1", name="A", slug="a", endpoint_url="https://mcp.acme.example/sse"),
        _candidate(id="ep-2", name="B", slug="b", endpoint_url="https://mcp.acme.example/sse/"),
        _candidate(
            id="ep-3",
            name="C",
            slug="c",
            endpoint_url="https://other.example/mcp",
            surface_fingerprint="fp-only",
        ),
    ]
    wire = mcp_duplicate_report_from_rows(
        tenant_id="t1",
        candidates=rows,
        foreign_published=[],
    )
    assert wire.advisory is True
    assert wire.group_count == 1
    assert wire.flagged_endpoint_count == 2
