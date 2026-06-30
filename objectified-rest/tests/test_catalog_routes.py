"""Tests for the Catalog REST API endpoints (MFI-23.2, #4011).

These pin the *route* contract for ``/v1/catalog`` — the read-only API over the non-publishable
slice of projects (MFI-23.1). The list + detail responses mirror the Projects contract so the
Catalog screen (MFI-23.3) can be cloned from the Projects dashboard, while also surfacing each
item's ``sourceFormat`` / ``protocol`` / ``formatMetadata`` / ``toolVersions`` and the
``publishable = false`` invariant.

The data-layer projection (filter to ``publishable = false``, latest-revision format/source) is
contract-tested in ``tests/test_catalog_item.py``; here we assert the routes are registered,
require authentication, pass ``include_deleted`` through, serialize the catalog envelope, and 404
when an id is not a catalog item.
"""

from unittest.mock import patch
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.auth import validate_authentication

client = TestClient(app)

# ---------------------------------------------------------------------------
# Auth-bypass helper (mirrors test_projects_api.py)
# ---------------------------------------------------------------------------
_MOCK_AUTH = {
    "tenant_id": "test-tenant-id",
    "user_id": "test-user-id",
    "auth_method": "jwt",
}


def _override_auth():
    return _MOCK_AUTH


_CATALOG_ACTIVE = {
    "id": "cat-1",
    "tenant_id": "test-tenant-id",
    "creator_id": "user-1",
    "name": "Acme gRPC API",
    "description": "imported from a .proto",
    "slug": "acme-grpc-api",
    "enabled": True,
    "metadata": {},
    "publishable": False,
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
    "deleted_at": None,
    "creator_name": "Test User",
    "creator_email": "test@example.com",
    "quality_score": 82,
    "quality_grade": "B",
    "source_format": "protobuf",
    "protocol": "grpc",
    "format_metadata": {"package": "acme.v1"},
    "tool_versions": {"protoc": "25.1"},
}

_CATALOG_DELETED = {
    **_CATALOG_ACTIVE,
    "id": "cat-deleted",
    "name": "Deleted Catalog Item",
    "slug": "deleted-catalog-item",
    "enabled": False,
    "deleted_at": "2026-02-01T00:00:00",
}


# ---------------------------------------------------------------------------
# Authentication is required
# ---------------------------------------------------------------------------
def test_list_catalog_requires_auth():
    """Listing catalog items requires authentication."""
    response = client.get('/v1/catalog/test-tenant')
    assert response.status_code == 401
    assert 'Authentication required' in response.json()['detail']


def test_get_catalog_item_requires_auth():
    """Getting a single catalog item requires authentication."""
    response = client.get('/v1/catalog/test-tenant/some-id')
    assert response.status_code == 401


def test_list_catalog_invalid_jwt():
    """An invalid JWT token is rejected."""
    response = client.get(
        '/v1/catalog/test-tenant',
        headers={'Authorization': 'Bearer invalid-token'}
    )
    assert response.status_code == 401


def test_list_catalog_invalid_api_key():
    """An invalid API key is rejected."""
    response = client.get(
        '/v1/catalog/test-tenant',
        headers={'X-API-Key': 'invalid-key'}
    )
    assert response.status_code == 401


def test_catalog_router_is_registered():
    """The catalog router is registered (401, not 404, on an unauthenticated read)."""
    response = client.get('/v1/catalog/any-tenant')
    assert response.status_code == 401


def test_catalog_endpoints_return_json():
    """All catalog endpoints return a JSON content type."""
    response = client.get('/v1/catalog/test-tenant')
    assert response.headers.get('content-type', '').startswith('application/json')

    response = client.get('/v1/catalog/test-tenant/some-id')
    assert response.headers.get('content-type', '').startswith('application/json')


# ---------------------------------------------------------------------------
# List — projection + include_deleted
# ---------------------------------------------------------------------------
def test_list_catalog_default_excludes_deleted():
    """By default (no flag) the data layer is asked for live items only."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_items_for_tenant.return_value = [_CATALOG_ACTIVE]
            response = client.get("/v1/catalog/test-tenant")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["slug"] == "acme-grpc-api"
        mock_db.get_catalog_items_for_tenant.assert_called_once_with(
            "test-tenant-id", include_deleted=False
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_list_catalog_include_deleted_returns_all_rows():
    """include_deleted=true forwards the flag and returns soft-deleted items too."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_items_for_tenant.return_value = [
                _CATALOG_ACTIVE,
                _CATALOG_DELETED,
            ]
            response = client.get("/v1/catalog/test-tenant?include_deleted=true")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        slugs = [c["slug"] for c in data]
        assert "acme-grpc-api" in slugs
        assert "deleted-catalog-item" in slugs
        mock_db.get_catalog_items_for_tenant.assert_called_once_with(
            "test-tenant-id", include_deleted=True
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_list_catalog_serializes_format_and_publishable():
    """The catalog envelope carries the format/source fields and publishable=false (camelCase)."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_items_for_tenant.return_value = [_CATALOG_ACTIVE]
            response = client.get("/v1/catalog/test-tenant")
        assert response.status_code == 200
        item = response.json()[0]
        # Project-compatible fields.
        assert item["name"] == "Acme gRPC API"
        assert item["qualityScore"] == 82
        assert item["qualityGrade"] == "B"
        # Catalog-only fields + the non-publishable invariant.
        assert item["publishable"] is False
        assert item["sourceFormat"] == "protobuf"
        assert item["protocol"] == "grpc"
        assert item["formatMetadata"] == {"package": "acme.v1"}
        assert item["toolVersions"] == {"protoc": "25.1"}
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_list_catalog_empty():
    """A tenant with no catalog items gets an empty list (not an error)."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_items_for_tenant.return_value = []
            response = client.get("/v1/catalog/test-tenant")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Detail — success + 404
# ---------------------------------------------------------------------------
def test_get_catalog_item_success():
    """GET /{tenant}/{id} returns the catalog item, tenant-scoped."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_ACTIVE
            response = client.get("/v1/catalog/test-tenant/cat-1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "cat-1"
        assert data["sourceFormat"] == "protobuf"
        assert data["publishable"] is False
        mock_db.get_catalog_item_by_id.assert_called_once_with(
            "cat-1", "test-tenant-id"
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_get_catalog_item_not_found_returns_404():
    """A publishable Project's id (or an unknown id) is not a catalog item → 404."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = None
            response = client.get("/v1/catalog/test-tenant/proj-publishable")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# Detail — MFI-23.9 normalized summary + source descriptor
# ---------------------------------------------------------------------------
_CATALOG_RICH = {
    **_CATALOG_ACTIVE,
    "id": "cat-rich",
    "slug": "acme-rich",
    "format_metadata": {
        "package": "acme.v1",
        "sourceLabel": "acme.proto",
        "inputKind": "file",
        "sourceContent": "syntax = \"proto3\";\nmessage Ping {}\n",
        "counts": {"services": 2, "operations": 7, "types": 12, "channels": 0},
    },
}


def test_get_catalog_item_includes_summary_and_source():
    """The detail response carries the normalized summary + source descriptor (MFI-23.9)."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_RICH
            response = client.get("/v1/catalog/test-tenant/cat-rich")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == {
            "services": 2, "operations": 7, "types": 12, "channels": 0,
        }
        assert data["source"]["kind"] == "file"
        assert data["source"]["label"] == "acme.proto"
        assert data["source"]["hasContent"] is True
        assert data["source"]["downloadable"] is True
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_get_catalog_item_summary_null_when_uncaptured():
    """With no counts/source recorded the summary is all-null and source is not downloadable."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_ACTIVE
            response = client.get("/v1/catalog/test-tenant/cat-1")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == {
            "services": None, "operations": None, "types": None, "channels": None,
        }
        assert data["source"]["downloadable"] is False
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# /source — stream inline content / redirect to URL / 404 / auth
# ---------------------------------------------------------------------------
def test_get_catalog_item_source_requires_auth():
    """The source endpoint requires authentication."""
    response = client.get("/v1/catalog/test-tenant/cat-1/source")
    assert response.status_code == 401


def test_get_catalog_item_source_streams_inline_content():
    """Captured inline content is streamed back as a typed, named attachment."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_RICH
            response = client.get("/v1/catalog/test-tenant/cat-rich/source")
        assert response.status_code == 200
        assert "proto3" in response.text
        assert response.headers["content-disposition"] == 'attachment; filename="acme.proto"'
        mock_db.get_catalog_item_by_id.assert_called_once_with("cat-rich", "test-tenant-id")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_get_catalog_item_source_redirects_to_url():
    """When only a URL is recorded, the source endpoint 307-redirects to it."""
    item = {
        **_CATALOG_ACTIVE,
        "id": "cat-url",
        "format_metadata": {"sourceUrl": "https://example.com/api/openapi.json", "inputKind": "url"},
    }
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = item
            response = client.get(
                "/v1/catalog/test-tenant/cat-url/source", follow_redirects=False
            )
        assert response.status_code == 307
        assert response.headers["location"] == "https://example.com/api/openapi.json"
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_get_catalog_item_source_404_when_uncaptured():
    """No content and no URL → 404 (raw source was never captured)."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_ACTIVE
            response = client.get("/v1/catalog/test-tenant/cat-1/source")
        assert response.status_code == 404
        assert "source" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_get_catalog_item_source_404_when_not_catalog_item():
    """A non-catalog id yields 404 from the source endpoint too."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = None
            response = client.get("/v1/catalog/test-tenant/proj-publishable/source")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


# ---------------------------------------------------------------------------
# /lint — server-computed lint report parity with projects (MFI-23.10)
# ---------------------------------------------------------------------------
_LINT_HEAD_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Acme", "version": "1.0.0"},  # missing description -> a finding
    "paths": {},
    "components": {"schemas": {}},
}


def _lint_version_row(vid: str):
    return {"id": vid, "project_id": "cat-1", "version_id": "1.0.0", "metadata": None}


def test_lint_catalog_item_requires_auth():
    """The catalog lint endpoint requires authentication."""
    response = client.get("/v1/catalog/test-tenant/cat-1/lint")
    assert response.status_code == 401


def test_lint_catalog_item_returns_report():
    """The latest revision is resolved and linted, returning the project-shaped report."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db, patch(
            "src.app.lint_routes.openapi_for_revision", return_value=_LINT_HEAD_SPEC
        ), patch("src.app.lint_routes.db.get_version_quality_score", return_value={}):
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_ACTIVE
            mock_db.get_latest_revision_id_for_project.return_value = "rev-1"
            mock_db.get_version_by_id.return_value = _lint_version_row("rev-1")
            response = client.get("/v1/catalog/test-tenant/cat-1/lint")
        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["score"], int)
        assert body["grade"] in {"A", "B", "C", "D", "F"}
        assert body["projectId"] == "cat-1"
        assert body["versionRecordId"] == "rev-1"
        assert body["versionId"] == "1.0.0"
        assert "reportFingerprint" in body
        # Lint runs over the canonical model (reconstructed here), so findings are present.
        rules = {f["rule"] for f in body["findings"]}
        assert "documentation.info-missing-description" in rules
        mock_db.get_latest_revision_id_for_project.assert_called_once_with(
            "cat-1", "test-tenant-id"
        )
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_lint_catalog_item_404_when_not_catalog_item():
    """A publishable Project's id (or an unknown id) is not a catalog item → 404."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = None
            response = client.get("/v1/catalog/test-tenant/proj-publishable/lint")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def test_lint_catalog_item_404_when_no_revision():
    """A catalog item with no revision to lint yields 404 (nothing to score)."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("src.app.catalog_routes.db") as mock_db:
            mock_db.get_catalog_item_by_id.return_value = _CATALOG_ACTIVE
            mock_db.get_latest_revision_id_for_project.return_value = None
            response = client.get("/v1/catalog/test-tenant/cat-1/lint")
        assert response.status_code == 404
        assert "revision" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
