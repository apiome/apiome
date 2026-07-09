"""Tests for mock guard / quota enforcement (#4420, SIM-1.5)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Request

from apiome_mock.guard import enforce_mock_limits
from apiome_mock.settings import Settings
from apiome_mock.tenant_limits import TenantLimits, clear_limits_caches_for_tests


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    clear_limits_caches_for_tests()


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/demo/petstore/1.0.0/pets",
        "headers": [],
        "client": ("203.0.113.10", 12345),
    }
    return Request(scope)


def test_enforce_returns_none_when_rate_limit_disabled(mock_pool: MagicMock) -> None:
    settings = Settings(
        database_url="postgresql://localhost/db",
        rate_limit_enabled=False,
    )
    result = asyncio.run(
        enforce_mock_limits(
            _request(),
            tenant="demo",
            project="petstore",
            version="1.0.0",
            pool=mock_pool,
            settings=settings,
        )
    )
    assert result is None


def test_enforce_monthly_quota_returns_429(mock_pool: MagicMock) -> None:
    tenant_id = uuid4()
    limits = TenantLimits(tenant_id=tenant_id, mock_rps=5.0, mock_requests_per_month=10_000)
    settings = Settings(database_url="postgresql://localhost/db", rate_limit_enabled=True)

    with (
        patch(
            "apiome_mock.guard.resolve_tenant_limits",
            new=AsyncMock(return_value=limits),
        ),
        patch(
            "apiome_mock.guard.resolve_monthly_usage",
            new=AsyncMock(return_value=10_000),
        ),
    ):
        result = asyncio.run(
            enforce_mock_limits(
                _request(),
                tenant="demo",
                project="petstore",
                version="1.0.0",
                pool=mock_pool,
                settings=settings,
            )
        )

    assert result is not None
    assert result.status_code == 429
    assert result.headers["Retry-After"]
    body = result.body.decode("utf-8")
    assert "monthly" in body.lower() or "quota" in body.lower()


def test_enforce_rps_limit_returns_429(mock_pool: MagicMock) -> None:
    tenant_id = uuid4()
    limits = TenantLimits(tenant_id=tenant_id, mock_rps=1.0, mock_requests_per_month=10_000)
    settings = Settings(database_url="postgresql://localhost/db", rate_limit_enabled=True)

    with (
        patch(
            "apiome_mock.guard.resolve_tenant_limits",
            new=AsyncMock(return_value=limits),
        ),
        patch(
            "apiome_mock.guard.resolve_monthly_usage",
            new=AsyncMock(return_value=0),
        ),
    ):
        asyncio.run(
            enforce_mock_limits(
                _request(),
                tenant="demo",
                project="petstore",
                version="1.0.0",
                pool=mock_pool,
                settings=settings,
            )
        )
        result = asyncio.run(
            enforce_mock_limits(
                _request(),
                tenant="demo",
                project="petstore",
                version="1.0.0",
                pool=mock_pool,
                settings=settings,
            )
        )

    assert result is not None
    assert result.status_code == 429
    assert result.headers["Retry-After"]
