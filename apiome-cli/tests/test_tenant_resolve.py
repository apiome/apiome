"""Unit tests for tenant slug/UUID resolution helpers."""

from __future__ import annotations

from uuid import UUID

import pytest
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_resolve import require_tenant_uuid, resolve_tenant_uuid
from apiome_cli.client.tenant_scope import require_tenant_slug
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_USAGE

_TENANT_UUID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _settings(*, tenant_id: str | None) -> CliSettings:
    return CliSettings.model_validate(
        {
            "base_url": "http://localhost:8000",
            "tenant_id": tenant_id,
            "api_key": "test-key",
        }
    )


def _client(settings: CliSettings | None = None) -> RestClient:
    return RestClient(settings or _settings(tenant_id=None))


def test_require_tenant_slug_returns_slug_directly() -> None:
    slug = require_tenant_slug(_settings(tenant_id="acme-corp"), _client())
    assert slug == "acme-corp"


def test_resolve_tenant_uuid_returns_none_without_scope() -> None:
    assert resolve_tenant_uuid(_settings(tenant_id=None), _client()) is None


def test_require_tenant_uuid_fetches_tenant_info_for_slug(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp",
        json={"id": str(_TENANT_UUID), "slug": "acme-corp"},
    )
    resolved = require_tenant_uuid(_settings(tenant_id="acme-corp"), _client())
    assert resolved == _TENANT_UUID


def test_require_tenant_uuid_exits_when_tenant_missing(
    httpx_mock: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/missing",
        status_code=404,
        json={"code": 404, "message": "not found"},
    )
    with pytest.raises(typer.Exit) as exc_info:
        require_tenant_uuid(_settings(tenant_id="missing"), _client())
    assert exc_info.value.exit_code == EXIT_USAGE
    assert "not found" in capsys.readouterr().err.lower()


def test_resolve_tenant_uuid_delegates_to_require_tenant_uuid(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp",
        json={"id": str(_TENANT_UUID), "slug": "acme-corp"},
    )
    resolved = resolve_tenant_uuid(_settings(tenant_id="acme-corp"), _client())
    assert resolved == _TENANT_UUID
