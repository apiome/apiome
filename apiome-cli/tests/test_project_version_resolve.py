"""Tests for project and version reference resolution."""

from __future__ import annotations

from uuid import UUID


from apiome_cli.client.http import RestClient
from apiome_cli.client.project_version_resolve import resolve_project_uuid, resolve_version_uuid
from apiome_cli.config import CliSettings

_PROJECT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_VERSION_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_TENANT_SLUG = "acme-corp"


def _settings() -> CliSettings:
    return CliSettings.model_validate(
        {
            "base_url": "http://localhost:8000/",
            "api_key": "test-key",
            "tenant_id": _TENANT_SLUG,
        },
    )


def _client() -> RestClient:
    return RestClient(_settings())


def test_resolve_project_uuid_by_id_without_list_call(httpx_mock: object) -> None:
    """UUID project references do not hit GET /projects."""
    resolved = resolve_project_uuid(_client(), _TENANT_SLUG, str(_PROJECT_ID))
    assert resolved == _PROJECT_ID
    assert len(httpx_mock.get_requests()) == 0


def test_resolve_project_uuid_by_slug(httpx_mock: object) -> None:
    """Project slugs resolve via GET /v1/projects/{tenant_slug}/by-slug/{slug}."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/projects/{_TENANT_SLUG}/by-slug/payments-api",
        json={
            "id": str(_PROJECT_ID),
            "slug": "payments-api",
            "name": "Payments API",
            "enabled": True,
        },
    )
    resolved = resolve_project_uuid(_client(), _TENANT_SLUG, "payments-api")
    assert resolved == _PROJECT_ID


def test_resolve_version_uuid_by_label(httpx_mock: object) -> None:
    """Version labels resolve via GET /v1/versions/{tenant_slug}/{project_id}/by-version/{semver}."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/{_TENANT_SLUG}/{_PROJECT_ID}/by-version/1.0.0",
        json={
            "id": str(_VERSION_ID),
            "project_id": str(_PROJECT_ID),
            "version": "1.0.0",
            "slug": "1.0.0",
            "enabled": True,
        },
    )
    resolved = resolve_version_uuid(
        _client(),
        tenant_slug=_TENANT_SLUG,
        project_id=_PROJECT_ID,
        version_ref="1.0.0",
    )
    assert resolved == _VERSION_ID


def test_resolve_version_uuid_by_uuid_skips_http(httpx_mock: object) -> None:
    """Version UUID references do not hit GET /versions."""
    resolved = resolve_version_uuid(
        _client(),
        tenant_slug=_TENANT_SLUG,
        project_id=_PROJECT_ID,
        version_ref=str(_VERSION_ID),
    )
    assert resolved == _VERSION_ID
    assert len(httpx_mock.get_requests()) == 0
