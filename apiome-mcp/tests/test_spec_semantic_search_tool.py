from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from apiome_mcp.settings import Settings
from apiome_mcp.spec_search_tool import MAX_PAGE_SIZE, encode_spec_search_cursor
from apiome_mcp.spec_semantic_search_tool import (
    SEMANTIC_SEARCH_DEPTH,
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


def _pool_mock_for_fetch(
    rows: list[dict[str, object]], *, pgvector_version: str | None = "0.8.1"
) -> tuple[MagicMock, MagicMock]:
    """A pool whose connection records ``conn.execute`` calls and answers the pgvector version probe."""
    pool = MagicMock(spec=AsyncConnectionPool)
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchall = AsyncMock(return_value=rows)
    cur_cm = AsyncMock()
    cur_cm.__aenter__.return_value = cur
    cur_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur_cm)
    probe = MagicMock()
    probe.fetchone = AsyncMock(return_value=(pgvector_version,) if pgvector_version else None)
    conn.execute = AsyncMock(return_value=probe)
    tx_cm = AsyncMock()
    tx_cm.__aenter__.return_value = None
    tx_cm.__aexit__.return_value = None
    conn.transaction = MagicMock(return_value=tx_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)
    cur.conn = conn
    return pool, cur


def _patch_embedding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the embeddings HTTP call and the pgvector adapter registration."""

    async def fake_embed(_settings: Settings, _q: str, _client: object = None) -> list[float]:
        return [0.0] * 1536

    monkeypatch.setattr("apiome_mcp.spec_semantic_search_tool._fetch_query_embedding", fake_embed)
    monkeypatch.setattr("apiome_mcp.spec_semantic_search_tool.ensure_vector_registered", AsyncMock())


def _search(pool: MagicMock, **kwargs: object) -> dict[str, object]:
    return asyncio.run(build_spec_semantic_search_response(pool, settings=_settings_with_key(), q="payments", **kwargs))


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
    _patch_embedding(monkeypatch)

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

    out = _search(pool, limit=10)
    assert out["has_more"] is False
    assert out["next_cursor"] is None
    assert len(out["items"]) == 1
    assert out["items"][0]["id"] == str(sid)


def test_semantic_search_orders_by_the_bare_distance_inside_a_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """DBP-1.22: the only shape the HNSW index serves; score, cursor and joins come after."""
    _patch_embedding(monkeypatch)
    pool, cur = _pool_mock_for_fetch([])

    _search(pool, limit=10)
    sql, params = cur.execute.await_args.args
    nearest, rest = sql.split("ranked AS (", 1)
    assert "ORDER BY v.mcp_public_embedding <=> %(qv)s::vector\n  LIMIT %(depth)s" in nearest
    assert "v.mcp_public_embedding IS NOT NULL" in nearest
    # The predicate of idx_versions_mcp_public_listed_embedding_hnsw, so the planner can pick it.
    assert "v.mcp_listed_at IS NOT NULL AND v.visibility = 'public'::apiome.visibility_type" in nearest
    assert "apiome.projects" not in nearest and "apiome.version_tags" not in nearest
    assert "mcp_v_public_specs" not in sql
    assert rest.index("LIMIT %(lim)s") < rest.index("apiome.projects")
    assert params["depth"] == SEMANTIC_SEARCH_DEPTH == 200
    assert params["lim"] == 11
    assert "cur_rank" not in params and "cur_rank" not in sql


def test_semantic_search_sets_hnsw_scan_settings_in_the_search_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embedding(monkeypatch)
    pool, cur = _pool_mock_for_fetch([])

    _search(pool)
    _search(pool)
    conn = cur.conn
    assert conn.transaction.call_count == 2
    statements = [call.args[0] for call in conn.execute.await_args_list]
    # The pgvector version is read once per process; the settings are set for every search.
    assert sum("pg_extension" in sql for sql in statements) == 1
    settings_sql = [sql for sql in statements if "set_config" in sql]
    assert len(settings_sql) == 2
    for sql in settings_sql:
        # Transaction-local (third argument true): nothing leaks to the pooled connection.
        assert "set_config('hnsw.ef_search', %s, true)" in sql
        assert "set_config('hnsw.iterative_scan', 'strict_order', true)" in sql
    assert conn.execute.await_args_list[-1].args[1] == (str(SEMANTIC_SEARCH_DEPTH),)


@pytest.mark.parametrize("version", ["0.7.4", None, "unknown"])
def test_semantic_search_skips_iterative_scan_on_older_pgvector(
    monkeypatch: pytest.MonkeyPatch, version: str | None
) -> None:
    """``hnsw.iterative_scan`` is pgvector 0.8+; naming it on an older server is an error."""
    _patch_embedding(monkeypatch)
    pool, cur = _pool_mock_for_fetch([], pgvector_version=version)

    _search(pool)
    settings_sql = [c.args[0] for c in cur.conn.execute.await_args_list if "set_config" in c.args[0]]
    assert settings_sql == ["SELECT set_config('hnsw.ef_search', %s, true)"]


def test_semantic_search_cursor_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embedding(monkeypatch)
    sid = uuid4()
    ts = datetime(2026, 5, 2, 15, 30, 45, tzinfo=timezone.utc)
    pool, cur = _pool_mock_for_fetch([])

    _search(pool, cursor=encode_spec_search_cursor(900, ts, sid))
    sql, params = cur.execute.await_args.args
    assert "(rank_score, updated_at, id) < (%(cur_rank)s::integer" in sql
    assert (params["cur_rank"], params["cur_ts"], params["cur_id"]) == (900, ts, sid)


def test_spec_search_semantic_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.search_semantic")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.search_semantic"


def test_query_embeddings_use_the_shared_client_when_given() -> None:
    """DBP-1.21: one pooled HTTP client for the lifespan instead of a new client per search."""
    import httpx

    from apiome_mcp.spec_semantic_search_tool import _fetch_query_embedding

    settings = _settings_with_key()
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.5] * settings.openai_embedding_dimensions}]})

    async def run() -> list[float]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            first = await _fetch_query_embedding(settings, "pets", client)
            await _fetch_query_embedding(settings, "stores", client)
            assert not client.is_closed
            return first

    vector = asyncio.run(run())
    assert len(vector) == settings.openai_embedding_dimensions
    assert len(seen) == 2
    assert seen[0].headers["authorization"].startswith("Bearer ")
