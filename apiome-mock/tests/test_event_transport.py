"""Integration tests for event mock transports (SIM-4.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.asyncapi_normalizer import AsyncApiNormalizer
from starlette.requests import Request

from apiome_mock.canonical_compiler import compile_canonical_spec
from apiome_mock.canonical_loader import LoadedCanonicalSpec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.event_transport import handle_event_sse


def _compiled_event_spec():
    doc = {
        "asyncapi": "3.0.0",
        "info": {"title": "User Service", "version": "1.0.0"},
        "channels": {
            "userSignedUp": {
                "address": "user/signedup",
                "messages": {
                    "UserSignedUp": {
                        "payload": {
                            "type": "object",
                            "required": ["userId"],
                            "properties": {"userId": {"type": "string"}},
                        }
                    }
                },
            }
        },
        "operations": {
            "onUserSignedUp": {
                "action": "receive",
                "channel": {"$ref": "#/channels/userSignedUp"},
                "messages": [{"$ref": "#/channels/userSignedUp/messages/UserSignedUp"}],
            }
        },
    }
    api = AsyncApiNormalizer().normalize(doc)
    loaded = LoadedCanonicalSpec(
        revision_id=uuid4(),
        tenant_slug="demo",
        project_slug="events",
        version_label="1.0.0",
        updated_at=datetime.now(timezone.utc),
        api=api,
        source_format="asyncapi-3",
    )
    return compile_canonical_spec(loaded)


def test_sse_stream_returns_event_payload(mock_pool: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MOCK_RATE_LIMIT_ENABLED", "false")
    from apiome_mock.settings import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings()
    cache = CanonicalSpecCache(max_entries=8, ttl_seconds=60.0)
    cache.put(_compiled_event_spec())

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/demo/events/1.0.0/events/sse/user/signedup",
        "headers": [],
        "query_string": b"",
    }
    request = Request(scope)

    async def _run() -> bytes:
        with (
            patch("apiome_mock.event_transport.get_canonical_access_status", AsyncMock(return_value="ok")),
            patch("apiome_mock.event_transport.resolve_limits_for_tenant", AsyncMock(return_value=None)),
            patch("apiome_mock.event_transport.enforce_mock_limits", AsyncMock(return_value=None)),
        ):
            response = await handle_event_sse(
                request,
                tenant="demo",
                project="events",
                version="1.0.0",
                channel_key="user/signedup",
                pool=mock_pool,
                cache=cache,
                api_key=None,
                settings=settings,
            )
            iterator = response.body_iterator.__aiter__()
            chunk = await iterator.__anext__()
            return chunk.encode() if isinstance(chunk, str) else chunk

    body = asyncio.run(_run()).decode()
    assert "event: message" in body
    assert "userId" in body
