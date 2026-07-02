"""MCP ``spec.search_semantic`` tool: cosine similarity over stored embeddings (pgvector)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pgvector.psycopg import Vector, register_vector_async  # type: ignore[import-untyped]
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.settings import Settings
from apiome_mcp.spec_search_tool import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
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


_SEMANTIC_SEARCH_QUERY = """
WITH scored AS (
  SELECT
    s.id,
    s.tenant_id,
    s.project_id,
    s.title,
    s.version,
    s.description,
    s.tags,
    s.updated_at,
    (1 - (v.mcp_public_embedding <=> %(qv)s::vector))::double precision AS similarity
  FROM apiome.mcp_v_public_specs AS s
  INNER JOIN apiome.versions v ON v.id = s.id
  WHERE v.mcp_public_embedding IS NOT NULL
),
ranked AS (
  SELECT
    id,
    tenant_id,
    project_id,
    title,
    version,
    description,
    tags,
    updated_at,
    GREATEST(
      1,
      LEAST(2147483647, ROUND((similarity::numeric) * 1000000000)::integer)
    ) AS rank_score
  FROM scored
)
SELECT id, tenant_id, project_id, title, version, description, tags, updated_at, rank_score
FROM ranked
WHERE
  CASE
    WHEN %(has_cursor)s THEN (
      (rank_score, updated_at, id)
      < (%(cur_rank)s::integer, %(cur_ts)s::timestamptz, %(cur_id)s::uuid)
    )
    ELSE TRUE
  END
ORDER BY rank_score DESC, updated_at DESC, id DESC
LIMIT %(lim)s
"""


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


async def _fetch_query_embedding(settings: Settings, q: str) -> list[float]:
    key = settings.openai_api_key
    if key is None:
        raise ValueError("spec.search_semantic requires APIOME_MCP_OPENAI_API_KEY for query embeddings.")

    payload: dict[str, Any] = {
        "model": settings.openai_embedding_model,
        "input": q,
    }
    payload["dimensions"] = settings.openai_embedding_dimensions

    async with httpx.AsyncClient(timeout=settings.openai_embedding_timeout_s) as client:
        response = await client.post(
            str(settings.openai_embedding_url),
            headers={
                "Authorization": f"Bearer {key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
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
) -> dict[str, Any]:
    """Return cosine-ranked ``items``, ``has_more``, and ``next_cursor`` for embedded public specs."""
    query_text = normalize_search_query(q)
    vec = await _fetch_query_embedding(settings, query_text)

    lim = _clamp_limit(limit)
    decoded = decode_spec_search_cursor(cursor)
    has_cursor = decoded is not None
    cur_rank = decoded[0] if decoded else None
    cur_ts = decoded[1] if decoded else None
    cur_id = decoded[2] if decoded else None

    params: dict[str, Any] = {
        "qv": Vector(vec),
        "has_cursor": has_cursor,
        "cur_rank": cur_rank,
        "cur_ts": cur_ts,
        "cur_id": cur_id,
        "lim": lim + 1,
    }

    async with pool.connection() as conn:
        await register_vector_async(conn)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SEMANTIC_SEARCH_QUERY, params)
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
