from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from apiome_mcp.settings import Settings
from apiome_mcp.spec_search_tool import MAX_PAGE_SIZE
from apiome_mcp.spec_semantic_search_tool import (
    _clamp_limit,
    _fetch_query_embedding,
    build_spec_semantic_search_response,
)


def _settings_with_key() -> Settings:
    return Settings.model_construct(
        database_url="postgresql://localhost/db",
        internal_secret="x" * 16,
        openai_api_key=SecretStr("sk-test"),
        openai_embedding_dimensions=1536,
    )


def _pool_mock_for_fetch(rows: list[dict[str, object]]) -> tuple[MagicMock, MagicMock]:
    pool = MagicMock(spec=AsyncConnectionPool)
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchall = AsyncMock(return_value=rows)
    cur_cm = AsyncMock()
    cur_cm.__aenter__.return_value = cur
    cur_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)
    return pool, cur


def test_fetch_query_embedding_requires_api_key() -> None:
    s = Settings.model_construct(
        database_url="postgresql://localhost/db",
        internal_secret="x" * 16,
        openai_api_key=None,
        openai_embedding_dimensions=1536,
    )

    async def call() -> None:
        await _fetch_query_embedding(s, "hello")

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        asyncio.run(call())


def test_clamp_limit() -> None:
    assert _clamp_limit(None) == 50
    assert _clamp_limit(MAX_PAGE_SIZE) == MAX_PAGE_SIZE
    assert _clamp_limit(999) == MAX_PAGE_SIZE


def test_build_spec_semantic_search_response_page(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(_settings: Settings, _q: str) -> list[float]:
        return [0.0] * 1536

    monkeypatch.setattr(
        "apiome_mcp.spec_semantic_search_tool._fetch_query_embedding",
        fake_embed,
    )
    monkeypatch.setattr(
        "apiome_mcp.spec_semantic_search_tool.register_vector_async",
        AsyncMock(),
    )

    sid = uuid4()
    te = uuid4()
    pr = uuid4()
    ts = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "id": sid,
            "tenant_id": te,
            "project_id": pr,
            "title": "API",
            "version": "1.0.0",
            "description": None,
            "tags": ["t"],
            "updated_at": ts,
            "rank_score": 900_000_000,
        }
    ]
    pool, _ = _pool_mock_for_fetch(rows)

    async def run() -> dict[str, object]:
        return await build_spec_semantic_search_response(
            pool,
            settings=_settings_with_key(),
            q="payments",
            limit=10,
        )

    out = asyncio.run(run())
    assert out["has_more"] is False
    assert out["next_cursor"] is None
    assert len(out["items"]) == 1
    assert out["items"][0]["id"] == str(sid)


def test_spec_search_semantic_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.search_semantic")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.search_semantic"
