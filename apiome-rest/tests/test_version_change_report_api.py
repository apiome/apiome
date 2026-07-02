"""Persisted change report routes (CR-02, #2700)."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_JWT = {
    "tenant_id": "t1",
    "user_id": "user-a",
    "auth_method": "jwt",
}

_MOCK_API_KEY = {
    "tenant_id": "t1",
    "tenant_slug": "tn",
    "auth_method": "api_key",
}

_MOCK_ROW = {
    "id": "cr-1",
    "tenant_id": "t1",
    "project_id": "p1",
    "published_revision_id": "v1",
    "baseline_revision_id": "v0",
    "change_model_json": {"schemaVersion": "1.0", "schemas": {"added": [], "removed": [], "modified": []}, "properties": [], "references": [], "relationships": [], "documentation": [], "warnings": [], "skipped": []},
    "rendered_body": "body",
    "header_snapshot": "hdr",
    "footnote_snapshot": "fn",
    "edited_rendered_body": None,
    "edited_header_snapshot": None,
    "edited_footnote_snapshot": None,
    "edited_at": None,
    "edited_by": None,
    "template_version_id": None,
    "rendered_at": datetime(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc),
    "regenerated_at": None,
    "created_at": datetime(2026, 4, 14, 11, 0, 0, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 4, 14, 11, 0, 0, tzinfo=timezone.utc),
}

_MOCK_VERSION_PUBLISHED = {
    "id": "v1",
    "project_id": "p1",
    "creator_id": "user-a",
    "published": True,
}

_MOCK_VERSION_DRAFT = {
    "id": "v1",
    "project_id": "p1",
    "creator_id": "user-a",
    "published": False,
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_get_change_report_ok():
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = _MOCK_ROW
        r = client.get("/v1/versions/tn/p1/v1/change-report")
        assert r.status_code == 200
        d = r.json()
        assert d["publishedRevisionId"] == "v1"
        assert d["effectiveRenderedBody"] == "body"


def test_get_change_report_404_no_row():
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = None
        r = client.get("/v1/versions/tn/p1/v1/change-report")
        assert r.status_code == 404


def test_get_change_report_400_unpublished():
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_DRAFT
        r = client.get("/v1/versions/tn/p1/v1/change-report")
        assert r.status_code == 400


def test_patch_forbidden_api_key():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_API_KEY
    try:
        r = client.patch("/v1/versions/tn/p1/v1/change-report", json={"editedRenderedBody": "x"})
        assert r.status_code == 403
    finally:
        app.dependency_overrides[validate_authentication] = lambda: _MOCK_JWT


def test_patch_403_not_creator():
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = {
            **_MOCK_VERSION_PUBLISHED,
            "creator_id": "someone-else",
        }
        mdb.is_user_tenant_admin.return_value = False
        r = client.patch(
            "/v1/versions/tn/p1/v1/change-report",
            json={"editedRenderedBody": "edited"},
        )
        assert r.status_code == 403


def test_patch_ok():
    updated = {**_MOCK_ROW, "edited_rendered_body": "edited", "edited_by": "user-a"}
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = _MOCK_ROW
        mdb.patch_change_report_edits.return_value = updated
        mdb.is_user_tenant_admin.return_value = False
        r = client.patch(
            "/v1/versions/tn/p1/v1/change-report",
            json={"editedRenderedBody": "edited"},
        )
        assert r.status_code == 200
        assert r.json()["effectiveRenderedBody"] == "edited"
        mdb.patch_change_report_edits.assert_called_once()


def test_patch_clear_edits():
    cleared = {**_MOCK_ROW, "edited_rendered_body": None, "edited_header_snapshot": None, "edited_footnote_snapshot": None}
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = {
            **_MOCK_ROW,
            "edited_rendered_body": "old edit",
            "edited_header_snapshot": "old hdr",
            "edited_footnote_snapshot": "old fn",
        }
        mdb.patch_change_report_edits.return_value = cleared
        mdb.is_user_tenant_admin.return_value = False
        r = client.patch(
            "/v1/versions/tn/p1/v1/change-report",
            json={"clearEdits": True},
        )
        assert r.status_code == 200
        # All edited fields cleared; effective values fall back to rendered snapshots
        assert r.json()["effectiveRenderedBody"] == "body"
        call_kwargs = mdb.patch_change_report_edits.call_args
        assert call_kwargs.kwargs.get("clear_edits") is True


def test_patch_null_clears_individual_field():
    after = {**_MOCK_ROW, "edited_rendered_body": None, "edited_header_snapshot": "kept hdr"}
    with patch("app.version_change_report_routes.db") as mdb:
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = {
            **_MOCK_ROW,
            "edited_rendered_body": "old edit",
            "edited_header_snapshot": "kept hdr",
        }
        mdb.patch_change_report_edits.return_value = after
        mdb.is_user_tenant_admin.return_value = False
        # Sending explicit null for editedRenderedBody should clear just that field
        r = client.patch(
            "/v1/versions/tn/p1/v1/change-report",
            json={"editedRenderedBody": None},
        )
        assert r.status_code == 200
        result = r.json()
        assert result["effectiveRenderedBody"] == "body"  # falls back to rendered_body
        assert result["effectiveHeaderSnapshot"] == "kept hdr"


def test_regenerate_ok():
    regen_row = {
        **_MOCK_ROW,
        "rendered_body": "new body",
        "header_snapshot": "Publication change report",
        "regenerated_at": datetime(2026, 4, 14, 13, 0, 0, tzinfo=timezone.utc),
    }
    with patch("app.version_change_report_routes.db") as mdb, patch(
        "app.version_change_report_routes.resolve_effective_change_report_template",
    ) as mres:
        from app.change_report_render import bundled_system_template_row

        mres.return_value = bundled_system_template_row()
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = _MOCK_ROW
        mdb.apply_change_report_regeneration.return_value = regen_row
        mdb.is_user_tenant_admin.return_value = False
        r = client.post("/v1/versions/tn/p1/v1/change-report/regenerate", json={})
        assert r.status_code == 200
        assert "new body" in r.json()["renderedBody"]


def test_regenerate_keep_user_edits():
    """discardUserEdits=false should preserve edited_* snapshot fields."""
    regen_row = {
        **_MOCK_ROW,
        "rendered_body": "new body",
        "header_snapshot": "Publication change report",
        "edited_rendered_body": "user override",
        "edited_header_snapshot": "user hdr",
        "regenerated_at": datetime(2026, 4, 14, 13, 0, 0, tzinfo=timezone.utc),
    }
    existing = {
        **_MOCK_ROW,
        "edited_rendered_body": "user override",
        "edited_header_snapshot": "user hdr",
    }
    with patch("app.version_change_report_routes.db") as mdb, patch(
        "app.version_change_report_routes.resolve_effective_change_report_template",
    ) as mres:
        from app.change_report_render import bundled_system_template_row

        mres.return_value = bundled_system_template_row()
        mdb.get_version_by_id.return_value = _MOCK_VERSION_PUBLISHED
        mdb.get_change_report_by_published_revision.return_value = existing
        mdb.apply_change_report_regeneration.return_value = regen_row
        mdb.is_user_tenant_admin.return_value = False
        r = client.post(
            "/v1/versions/tn/p1/v1/change-report/regenerate",
            json={"discardUserEdits": False},
        )
        assert r.status_code == 200
        result = r.json()
        # Effective values use the preserved user edits
        assert result["effectiveRenderedBody"] == "user override"
        assert result["effectiveHeaderSnapshot"] == "user hdr"
        # Rendered body was updated by regeneration
        assert result["renderedBody"] == "new body"
        call_kwargs = mdb.apply_change_report_regeneration.call_args
        assert call_kwargs.kwargs.get("discard_user_edits") is False


def test_placeholder_render_module():
    from app.change_report_render import placeholder_render_from_change_model

    h, b, f = placeholder_render_from_change_model(
        {
            "schemaVersion": "1.0",
            "schemas": {"added": [{"name": "A"}], "removed": [], "modified": []},
            "properties": [],
            "references": [],
            "relationships": [],
            "documentation": [],
            "warnings": [],
            "skipped": [],
        }
    )
    assert "`A`" in b or "A" in b
    assert "Summary" in b
    assert "Generator" in f
    assert "#" in h
