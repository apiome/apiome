"""MCP ``spec.search_semantic`` tool: cosine similarity over stored embeddings (pgvector)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from pgvector.psycopg import Vector  # type: ignore[import-untyped]
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.database_pool import ensure_vector_registered
from apiome_mcp.settings import Settings
from apiome_mcp.spec_listing_sql import listed_version
from apiome_mcp.spec_search_tool import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SEARCH_CURSOR_SQL,
    SEARCH_OUTPUT_SQL,
    decode_spec_search_cursor,
    encode_spec_search_cursor,
    normalize_search_query,
)


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}.")
    return min(limit, MAX_PAGE_SIZE)


#: Paging depth (DBP-1.22): a query pages through its nearest ``SEMANTIC_SEARCH_DEPTH`` specs and
#: no further — ``has_more`` is false on the page that reaches it. It is also the HNSW candidate
#: list size (``hnsw.ef_search``; pgvector's default, 40, would cap every search at 40 results),
#: so every result within the depth comes from one index scan.
SEMANTIC_SEARCH_DEPTH = 200

#: pgvector release that added ``hnsw.iterative_scan``.
_ITERATIVE_SCAN_MIN_VERSION = (0, 8, 0)


def build_semantic_search_query(*, has_cursor: bool) -> str:
    """The ``spec.search_semantic`` statement: nearest neighbours from the HNSW index, then join.

    ``nearest`` orders by the bare distance expression with a ``LIMIT``, the only shape an HNSW
    index can serve (ordering by a value derived from the distance made every search read and
    sort all embedded revisions). ``idx_versions_mcp_public_listed_embedding_hnsw`` (V428) has the
    same public predicate as the query, so the planner need not guess how many embedded revisions
    are public. The score, the cursor, the project and the tags are computed for those rows only.

    Args:
        has_cursor: Whether the statement takes ``cur_rank`` / ``cur_ts`` / ``cur_id``.

    Returns:
        SQL with named parameters ``qv``, ``depth``, ``lim`` and, with a cursor, its three values.
    """
    cursor_sql = f"WHERE {SEARCH_CURSOR_SQL}" if has_cursor else ""
    return f"""
WITH nearest AS MATERIALIZED (
  SELECT
    v.id,
    v.project_id,
    v.mcp_listed_at AS updated_at,
    v.mcp_public_embedding <=> %(qv)s::vector AS distance
  FROM apiome.versions v
  WHERE v.mcp_public_embedding IS NOT NULL
    AND {listed_version("public")}
  ORDER BY v.mcp_public_embedding <=> %(qv)s::vector
  LIMIT %(depth)s
),
ranked AS (
  SELECT
    id,
    project_id,
    updated_at,
    GREATEST(
      1,
      LEAST(2147483647, ROUND(((1 - distance)::double precision::numeric) * 1000000000)::integer)
    ) AS rank_score
  FROM nearest
),
page AS (
  SELECT id, project_id, updated_at, rank_score
  FROM ranked
  {cursor_sql}
  ORDER BY rank_score DESC, updated_at DESC, id DESC
  LIMIT %(lim)s
)
{SEARCH_OUTPUT_SQL}"""


#: Whether the server's pgvector has ``hnsw.iterative_scan``; read once per process.
_iterative_scan_supported: bool | None = None


def reset_semantic_search_state() -> None:
    """Forget the cached pgvector capability (tests)."""
    global _iterative_scan_supported
    _iterative_scan_supported = None


async def _apply_hnsw_settings(conn: Any) -> None:
    """Set the HNSW scan settings for the current transaction.

    ``hnsw.ef_search`` is raised to :data:`SEMANTIC_SEARCH_DEPTH` (the default, 40, would cap a
    search at 40 results). With pgvector 0.8 or later, ``hnsw.iterative_scan = strict_order`` makes
    the index keep scanning when the public-visibility filter discards candidates, so the filter
    cannot leave a page short; an older pgvector simply returns what one scan finds.

    Args:
        conn: A connection inside a transaction (the settings are transaction-local).
    """
    global _iterative_scan_supported
    if _iterative_scan_supported is None:
        cur = await conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = await cur.fetchone()
        _iterative_scan_supported = _parse_version(row[0] if row else None) >= _ITERATIVE_SCAN_MIN_VERSION
    if _iterative_scan_supported:
        await conn.execute(
            "SELECT set_config('hnsw.ef_search', %s, true), set_config('hnsw.iterative_scan', 'strict_order', true)",
            (str(SEMANTIC_SEARCH_DEPTH),),
        )
    else:
        await conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(SEMANTIC_SEARCH_DEPTH),))


def _parse_version(raw: Any) -> tuple[int, ...]:
    """A dotted version string as a tuple of ints (``()`` when it cannot be read)."""
    try:
        return tuple(int(part) for part in str(raw).split("."))
    except ValueError:
        return ()


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    tags = row["tags"]
    if tags is None:
        tag_list: list[str] = []
    else:
        tag_list = [str(t) for t in list(tags)]

    ua = row["updated_at"]
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "project_id": str(row["project_id"]),
        "title": row["title"],
        "version": row["version"],
        "description": row["description"],
        "tags": tag_list,
        "updated_at": _utc(ua).isoformat().replace("+00:00", "Z"),
        "rank_score": int(row["rank_score"]),
    }


#: Lifespan-context key of the shared embeddings client (DBP-1.21).
EMBEDDING_HTTP_CLIENT_KEY = "embedding_http_client"


@asynccontextmanager
async def embedding_http_client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """One pooled HTTP client for query embeddings, for the life of the catalog lifespan.

    Args:
        settings: Supplies ``openai_embedding_timeout_s``.

    Yields:
        The client; closed on exit.
    """
    async with httpx.AsyncClient(timeout=settings.openai_embedding_timeout_s) as client:
        yield client


async def _post_embedding(
    settings: Settings, client: httpx.AsyncClient | None, *, headers: dict[str, str], payload: dict[str, Any]
) -> httpx.Response:
    """POST the embedding request on the shared client, or a one-off client when there is none."""
    if client is not None:
        return await client.post(str(settings.openai_embedding_url), headers=headers, json=payload)
    async with embedding_http_client(settings) as own:
        return await own.post(str(settings.openai_embedding_url), headers=headers, json=payload)


async def _fetch_query_embedding(settings: Settings, q: str, client: httpx.AsyncClient | None = None) -> list[float]:
    key = settings.openai_api_key
    if key is None:
        raise ValueError("spec.search_semantic requires APIOME_MCP_OPENAI_API_KEY for query embeddings.")

    payload: dict[str, Any] = {
        "model": settings.openai_embedding_model,
        "input": q,
    }
    payload["dimensions"] = settings.openai_embedding_dimensions

    response = await _post_embedding(
        settings,
        client,
        headers={
            "Authorization": f"Bearer {key.get_secret_value()}",
            "Content-Type": "application/json",
        },
        payload=payload,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:500] if response.text else ""
        raise ValueError(
            f"Embedding HTTP {response.status_code} from {settings.openai_embedding_url}: {detail}"
        ) from exc

    body = response.json()
    data = body.get("data")
    if not isinstance(data, list) or not data:
        raise ValueError("Embedding response missing data[0].")
    first = data[0]
    if not isinstance(first, dict):
        raise ValueError("Embedding response data[0] is not an object.")
    emb = first.get("embedding")
    if not isinstance(emb, list):
        raise ValueError("Embedding response missing numeric embedding vector.")
    out = [float(x) for x in emb]
    exp = settings.openai_embedding_dimensions
    if len(out) != exp:
        raise ValueError(f"Embedding length {len(out)} does not match configured dimensions {exp}.")
    return out


async def build_spec_semantic_search_response(
    pool: AsyncConnectionPool,
    *,
    settings: Settings,
    q: str,
    limit: int | None = None,
    cursor: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Return cosine-ranked ``items``, ``has_more``, and ``next_cursor`` for embedded public specs.

    Results come from the HNSW index and cover the query's nearest
    :data:`SEMANTIC_SEARCH_DEPTH` specs; paging stops there (DBP-1.22).

    ``http_client`` is the lifespan's shared embeddings client (DBP-1.21); without one a client is
    opened for this call. pgvector is registered once per pooled connection
    (:func:`~apiome_mcp.database_pool.ensure_vector_registered`), not once per search.
    """
    query_text = normalize_search_query(q)
    vec = await _fetch_query_embedding(settings, query_text, http_client)

    lim = _clamp_limit(limit)
    decoded = decode_spec_search_cursor(cursor)

    params: dict[str, Any] = {"qv": Vector(vec), "depth": SEMANTIC_SEARCH_DEPTH, "lim": lim + 1}
    if decoded is not None:
        params.update(cur_rank=decoded[0], cur_ts=decoded[1], cur_id=decoded[2])

    async with pool.connection() as conn:
        await ensure_vector_registered(conn)
        # The pool is autocommit: the HNSW settings must share a transaction with the search.
        async with conn.transaction():
            await _apply_hnsw_settings(conn)
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(build_semantic_search_query(has_cursor=decoded is not None), params)
                rows = await cur.fetchall()

    has_more = len(rows) > lim
    page = rows[:lim]
    items = [_row_out(r) for r in page]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_spec_search_cursor(int(last["rank_score"]), last["updated_at"], last["id"])

    return {
        "items": items,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
