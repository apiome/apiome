"""Tests for require_tenant_uuid helper."""

from __future__ import annotations

from uuid import UUID

import pytest
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.client.tenant_resolve import require_tenant_uuid
from apiome_cli.config import CliSettings
from apiome_cli.exit_codes import EXIT_USAGE


def _settings(**kwargs: object) -> CliSettings:
    return CliSettings.model_validate(kwargs)


def _client() -> RestClient:
    return RestClient(_settings(base_url="http://localhost:8000", api_key="obj_test"))


def test_require_tenant_uuid_exits_when_tenant_missing() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        require_tenant_uuid(_settings(api_key="obj_test"), _client())
    assert exc_info.value.exit_code == EXIT_USAGE


def test_require_tenant_uuid_returns_configured_uuid(httpx_mock: object) -> None:
    tenant_uuid = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    # A configured UUID is resolved to a slug via GET /v1/tenants/me, then
    # the tenant record is fetched to confirm the id.
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/me?offset=0&limit=200",
        json={
            "total": 1,
            "offset": 0,
            "limit": 200,
            "items": [{"id": str(tenant_uuid), "slug": "acme", "name": "Acme"}],
        },
    )
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme",
        json={"id": str(tenant_uuid), "slug": "acme", "name": "Acme"},
    )
    resolved = require_tenant_uuid(
        _settings(api_key="obj_test", tenant_id=str(tenant_uuid)),
        _client(),
    )
    assert resolved == tenant_uuid
