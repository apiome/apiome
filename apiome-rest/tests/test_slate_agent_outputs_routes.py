"""Route tests for the APX-3.4 agent-output read API (#2459).

Exercises `GET /v1/versions/{tenant}/{project}/{version}/agent-outputs` with the database
and canonical loader patched (no live Postgres): output selection and media types, the
published gate, tenant/project scoping, the private-portal withholding path, ETag / 304
conditional caching, and the empty-content fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
)
from app.main import app

client = TestClient(app)

_TENANT = "t1"
_PROJECT_ID = "22222222-2222-4222-8222-222222222222"
_VERSION_ID = "11111111-1111-4111-8111-111111111111"
_BASE = f"/v1/versions/acme/{_PROJECT_ID}/{_VERSION_ID}/agent-outputs"
_MOCK_JWT = {"tenant_id": _TENANT, "user_id": "user-a", "email": "a@example.com", "auth_method": "jwt"}


def _project(**overrides):
    row = {"id": _PROJECT_ID, "slug": "pet-store", "name": "Pet Store"}
    row.update(overrides)
    return row


def _version(**overrides):
    row = {
        "id": _VERSION_ID,
        "project_id": _PROJECT_ID,
        "version_id": "1.0.65",
        "project_slug": "pet-store",
        "project_name": "Pet Store",
        "published": True,
        "visibility": "public",
        "published_at": datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _canonical():
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pet Store"),
        version="1.4.0",
        title="Pet Store API",
        description="A sample pet store.",
        services=[
            Service(
                key="pets",
                name="pets",
                operations=[
                    Operation(
                        key="GET /pets",
                        name="listPets",
                        kind=OperationKind.REQUEST_RESPONSE,
                        http_method="get",
                        http_path="/pets",
                        description="List all pets.",
                    )
                ],
            )
        ],
        types=[Type(key="Pet", name="Pet", kind=TypeKind.RECORD)],
    )


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def fake_db():
    """A MagicMock db with the accessors the route uses, patched into the route module."""
    db = MagicMock()
    db.get_project_by_id.return_value = _project()
    db.get_version_by_id.return_value = _version()
    db.get_latest_version_for_project.return_value = "1.0.65"
    db.get_version_changelog.return_value = None
    with patch("app.slate_agent_outputs_routes.db", db), patch(
        "app.slate_agent_outputs_routes.load_canonical_api", return_value=_canonical()
    ):
        yield db


# -------------------------------------------------------------------------- happy path


def test_index_default_returns_json_envelope(fake_db) -> None:
    resp = client.get(_BASE)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["cache-control"] == "private, max-age=300"
    assert resp.headers["etag"].startswith('"')
    body = resp.json()
    assert body["schemaVersion"] == "slate.agent-outputs.v1"
    assert body["indexable"] is True
    assert body["version"]["label"] == "1.0.65"
    assert {o["name"] for o in body["outputs"]} == {"llms.txt", "robots.txt", "catalog", "release"}


def test_output_llms_txt_is_plain_text(fake_db) -> None:
    resp = client.get(_BASE, params={"output": "llms.txt"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text.startswith("# Pet Store API")
    assert "reference/operations/operation-get-pets" in resp.text


def test_output_catalog_is_json_with_inventory(fake_db) -> None:
    resp = client.get(_BASE, params={"output": "catalog"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["schemaVersion"] == "slate.catalog.v1"
    assert body["counts"]["operations"] == 1
    assert body["capabilities"]["tryIt"] is True


def test_output_release_reports_latest(fake_db) -> None:
    resp = client.get(_BASE, params={"output": "release"})
    assert resp.status_code == 200
    assert resp.json()["release"]["latest"] is True


def test_robots_public_allows(fake_db) -> None:
    resp = client.get(_BASE, params={"output": "robots.txt"})
    assert resp.status_code == 200
    assert "Allow: /" in resp.text
    assert "Sitemap:" in resp.text


# ---------------------------------------------------------------------------- caching


def test_if_none_match_returns_304(fake_db) -> None:
    first = client.get(_BASE)
    etag = first.headers["etag"]
    second = client.get(_BASE, headers={"If-None-Match": etag})
    assert second.status_code == 304
    assert second.headers["etag"] == etag


def test_if_none_match_weak_and_wildcard(fake_db) -> None:
    etag = client.get(_BASE).headers["etag"]
    assert client.get(_BASE, headers={"If-None-Match": f"W/{etag}"}).status_code == 304
    assert client.get(_BASE, headers={"If-None-Match": "*"}).status_code == 304


# --------------------------------------------------------------------------- privacy


def test_private_portal_withholds_content(fake_db) -> None:
    fake_db.get_version_by_id.return_value = _version(visibility="private")
    catalog = client.get(_BASE, params={"output": "catalog"}).json()
    assert catalog["contentWithheld"] is True
    assert "operations" not in catalog
    robots = client.get(_BASE, params={"output": "robots.txt"}).text
    assert robots == "User-agent: *\nDisallow: /\n"
    index = client.get(_BASE).json()
    assert index["indexable"] is False


# --------------------------------------------------------------------------- guards


def test_unpublished_revision_is_400(fake_db) -> None:
    fake_db.get_version_by_id.return_value = _version(published=False)
    resp = client.get(_BASE)
    assert resp.status_code == 400


def test_version_in_wrong_project_is_404(fake_db) -> None:
    fake_db.get_version_by_id.return_value = _version(project_id="99999999-9999-4999-8999-999999999999")
    resp = client.get(_BASE)
    assert resp.status_code == 404


def test_unknown_version_is_404(fake_db) -> None:
    fake_db.get_version_by_id.return_value = None
    resp = client.get(_BASE)
    assert resp.status_code == 404


def test_unknown_project_is_404(fake_db) -> None:
    fake_db.get_project_by_id.return_value = None
    resp = client.get(_BASE)
    assert resp.status_code == 404


def test_malformed_project_id_is_400(fake_db) -> None:
    resp = client.get(f"/v1/versions/acme/not-a-uuid/{_VERSION_ID}/agent-outputs")
    assert resp.status_code == 400


def test_unknown_output_selector_is_400(fake_db) -> None:
    resp = client.get(_BASE, params={"output": "sitemap"})
    assert resp.status_code == 400


# ----------------------------------------------------------------------- empty content


def test_missing_canonical_yields_empty_catalog(fake_db) -> None:
    with patch("app.slate_agent_outputs_routes.load_canonical_api", return_value=None):
        resp = client.get(_BASE, params={"output": "catalog"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"]["operations"] == 0
