"""Tests for the public project changelog Markdown (PCX-2.1, #5896).

Covers the pure renderer (byte-identity with ``render_changelog_markdown`` for the same rows,
explicit initial / failed / pending blocks, the severity / path-group / since filters) and the
``GET /v1/browse/tenants/{t}/projects/{p}/changelog.md`` route (404s, content type, filters
passed through, ETag / 304).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.browse_changelog_markdown import (
    VERSION_SEPARATOR,
    changelog_from_payload,
    filter_changelog,
    render_project_changelog_markdown,
)
from app.change_taxonomy import classify_openapi_changes
from app.changelog_generator import build_changelog, render_changelog_json, render_changelog_markdown
from app.main import app
from app.publication_changelog import initial_publication_changelog_json

client = TestClient(app)


def _doc(paths: dict, description: str = "Pets") -> dict:
    info = {"title": "Petstore", "version": "1", "description": description}
    return {"openapi": "3.1.0", "info": info, "paths": paths}


_V100 = _doc({"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}})
_V110 = _doc(
    {
        "/pets": {
            "get": {"responses": {"200": {"description": "ok"}}},
            "post": {"responses": {"201": {"description": "created"}}},
        }
    }
)
_V120 = _doc({"/pets": {"post": {"responses": {"201": {"description": "created"}}}}}, description="Pets v2")


def _ready_row(label: str, baseline: str, base_doc: dict, head_doc: dict) -> dict:
    """A ``ready`` row whose payload is exactly what the publish hook stores."""
    changelog = build_changelog(classify_openapi_changes(base_doc, head_doc), from_version=baseline, to_version=label)
    return {
        "published_revision_id": f"rev-{label}",
        "version_label": label,
        "published_at": None,
        "baseline_version_label": baseline,
        "max_severity": changelog.max_severity,
        "status": "ready",
        "changelog_json": render_changelog_json(changelog),
    }


def _petstore_rows() -> list:
    """Petstore with three publishes, newest first."""
    return [
        _ready_row("1.2.0", "1.1.0", _V110, _V120),
        _ready_row("1.1.0", "1.0.0", _V100, _V110),
        {
            "published_revision_id": "rev-1.0.0",
            "version_label": "1.0.0",
            "published_at": None,
            "baseline_version_label": None,
            "max_severity": None,
            "status": "initial",
            "changelog_json": initial_publication_changelog_json(to_version="1.0.0"),
        },
    ]


# --- renderer --------------------------------------------------------------------------------


def test_ready_blocks_are_byte_identical_to_render_changelog_markdown():
    rows = _petstore_rows()
    md = render_project_changelog_markdown(rows)
    blocks = md.split(VERSION_SEPARATOR)
    assert len(blocks) == 3
    for row, block in zip(rows[:2], blocks[:2]):
        expected = render_changelog_markdown(changelog_from_payload(row["changelog_json"]))
        assert block == expected
    assert "Initial publication" in blocks[2]


def test_round_trip_preserves_generator_output():
    changelog = build_changelog(classify_openapi_changes(_V110, _V120), from_version="1.1.0", to_version="1.2.0")
    restored = changelog_from_payload(render_changelog_json(changelog))
    assert render_changelog_markdown(restored) == render_changelog_markdown(changelog)


def test_sections_are_newest_first_and_breaking_first():
    md = render_project_changelog_markdown(_petstore_rows())
    assert md.index("`1.1.0` → `1.2.0`") < md.index("`1.0.0` → `1.1.0`") < md.index("`—` → `1.0.0`")
    first = md.split(VERSION_SEPARATOR)[0]
    assert first.index("## Breaking changes") < first.index("## Documentation changes")


def test_failed_and_pending_rows_render_explicit_states():
    rows = [
        {"version_label": "1.5.0", "baseline_version_label": "1.4.0", "status": "failed", "changelog_json": None},
        {"version_label": "1.4.0", "baseline_version_label": None, "status": None, "changelog_json": None},
    ]
    md = render_project_changelog_markdown(rows)
    assert "_Classification failed for 1.5.0 — plain diff only._" in md
    assert "**Since** `1.4.0` → `1.5.0`" in md
    assert "_Changes for 1.4.0 are pending classification._" in md


def test_severity_and_path_group_filters():
    rows = _petstore_rows()
    md = render_project_changelog_markdown(rows, severity="breaking")
    first, second = md.split(VERSION_SEPARATOR)[:2]
    assert "## Breaking changes" in first and "## Documentation changes" not in first
    assert "No changes." in second  # 1.1.0 is additive only

    group = changelog_from_payload(rows[0]["changelog_json"]).entries[0].path_group
    by_group = render_project_changelog_markdown(rows, path_group=group)
    assert "### `/info`" not in by_group.split(VERSION_SEPARATOR)[0]


def test_filter_changelog_recomputes_counts_and_keeps_order():
    changelog = changelog_from_payload(_petstore_rows()[0]["changelog_json"])
    filtered = filter_changelog(changelog, severity="docs-only")
    assert filtered.counts["total"] == len(filtered.entries) == filtered.counts["docs-only"]
    assert filtered.max_severity == "docs-only"
    assert filter_changelog(changelog) is changelog


def test_since_keeps_newer_versions_only_and_ignores_unknown_labels():
    rows = _petstore_rows()
    assert render_project_changelog_markdown(rows, since="1.1.0").count("# Changelog") == 1
    assert render_project_changelog_markdown(rows, since="9.9.9").count("# Changelog") == 3
    assert render_project_changelog_markdown(rows, since="1.2.0") == "# Changelog\n\nNo published versions.\n"


# --- route -----------------------------------------------------------------------------------


_TENANT = {"id": "tid-1", "slug": "acme", "name": "Acme"}


def test_route_404_when_tenant_missing():
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = None
        r = client.get("/v1/browse/tenants/nope/projects/petstore/changelog.md")
    assert r.status_code == 404


def test_route_404_when_project_not_public():
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = _TENANT
        m.project_has_public_published_version.return_value = False
        r = client.get("/v1/browse/tenants/acme/projects/secret/changelog.md")
    assert r.status_code == 404
    m.list_public_version_changelogs_for_project.assert_not_called()


def test_route_returns_markdown_matching_renderer_with_filters():
    rows = _petstore_rows()
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = _TENANT
        m.project_has_public_published_version.return_value = True
        m.list_public_version_changelogs_for_project.return_value = rows
        r = client.get(
            "/v1/browse/tenants/acme/projects/petstore/changelog.md",
            params={"severity": "breaking", "pathGroup": "/paths/~1pets", "since": "1.0.0"},
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["cache-control"] == "public, max-age=300"
    expected = render_project_changelog_markdown(rows, severity="breaking", path_group="/paths/~1pets", since="1.0.0")
    assert r.text == expected
    m.list_public_version_changelogs_for_project.assert_called_once_with("tid-1", "petstore", limit=500)


def test_route_rejects_unknown_severity():
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = _TENANT
        m.project_has_public_published_version.return_value = True
        r = client.get("/v1/browse/tenants/acme/projects/petstore/changelog.md?severity=scary")
    assert r.status_code == 422


def test_route_etag_304():
    with patch("app.browse_public_routes.db") as m:
        m.get_tenant_row_by_slug.return_value = _TENANT
        m.project_has_public_published_version.return_value = True
        m.list_public_version_changelogs_for_project.return_value = _petstore_rows()
        first = client.get("/v1/browse/tenants/acme/projects/petstore/changelog.md")
        etag = first.headers["etag"]
        second = client.get(
            "/v1/browse/tenants/acme/projects/petstore/changelog.md",
            headers={"If-None-Match": f"W/{etag}"},
        )
    assert second.status_code == 304
    assert second.headers["etag"] == etag
