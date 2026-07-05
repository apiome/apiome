"""Tests for public browse export guards — MFX-7.3 (#3862)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.public_export_guards import (
    enforce_public_export_document_size,
    enforce_public_export_rate_limit,
    is_public_browse_export_path,
    response_body_byte_length,
)
from app.rate_limit import FixedWindowRateLimiter


def _request(path: str = "/v1/browse/tenants/a/projects/p/versions/1.0.0/export/targets") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("203.0.113.10", 12345),
    }
    return Request(scope)


def test_is_public_browse_export_path_matches_export_routes():
    assert is_public_browse_export_path(
        "/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export/targets"
    )
    assert is_public_browse_export_path(
        "/v1/browse/tenants/acme/projects/widgets/versions/1.0.0/export/document"
    )
    assert not is_public_browse_export_path("/v1/browse/tenants/acme/projects/widgets")
    assert not is_public_browse_export_path("/v1/export/acme/targets")


def test_enforce_public_export_rate_limit_allows_under_cap(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "public_browse_export_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with patch("app.public_export_guards._public_export_limiter", FixedWindowRateLimiter()):
        enforce_public_export_rate_limit(_request())
        enforce_public_export_rate_limit(_request())


def test_enforce_public_export_rate_limit_raises_429_when_exhausted(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "public_browse_export_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    with patch("app.public_export_guards._public_export_limiter", FixedWindowRateLimiter()):
        enforce_public_export_rate_limit(_request())
        enforce_public_export_rate_limit(_request())
        with pytest.raises(HTTPException) as exc:
            enforce_public_export_rate_limit(_request())
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"]
    assert exc.value.headers["X-RateLimit-Limit"] == "2"


def test_enforce_public_export_rate_limit_honours_global_kill_switch(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "public_browse_export_rate_limit_per_minute", 1)
    with patch("app.public_export_guards._public_export_limiter", FixedWindowRateLimiter()):
        for _ in range(5):
            enforce_public_export_rate_limit(_request())


def test_enforce_public_export_document_size_allows_under_cap(monkeypatch):
    monkeypatch.setattr(settings, "public_browse_export_document_max_bytes", 100)
    response = Response(content=b"x" * 50)
    enforce_public_export_document_size(response)


def test_enforce_public_export_document_size_raises_413_when_over_cap(monkeypatch):
    monkeypatch.setattr(settings, "public_browse_export_document_max_bytes", 32)
    response = Response(content=b"x" * 64)
    with pytest.raises(HTTPException) as exc:
        enforce_public_export_document_size(response)
    assert exc.value.status_code == 413
    assert "64 bytes" in exc.value.detail


def test_enforce_public_export_document_size_disabled_when_cap_zero(monkeypatch):
    monkeypatch.setattr(settings, "public_browse_export_document_max_bytes", 0)
    response = Response(content=b"x" * 10_000)
    enforce_public_export_document_size(response)


def test_response_body_byte_length_empty():
    assert response_body_byte_length(Response(content=b"")) == 0
