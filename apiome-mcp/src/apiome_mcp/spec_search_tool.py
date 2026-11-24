"""MCP ``spec.search`` tool: full-text search over public specs (#3007)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.cursor_codec import (
    clamp_page_limit,
    cursor_timestamp,
    decode_cursor_payload,
    encode_cursor_payload,
    utc,
)
from apiome_mcp.spec_listing_sql import LISTED_PROJECT, listed_version

SEARCH_CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecSearchCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def encode_spec_search_cursor(rank_score: int, updated_at: datetime, spec_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = utc(updated_at)
    payload = {
        "v": SEARCH_CURSOR_VERSION,
        "r": int(rank_score),
        "i": str(spec_id),
        "u": u.isoformat().replace("+00:00", "Z"),
    }
    return encode_cursor_payload(payload)


def decode_spec_search_cursor(raw: str | None) -> tuple[int, datetime, UUID] | None:
    """Decode ``cursor`` into ``(rank_score, updated_at, id)`` or ``None`` when absent."""
    obj = decode_cursor_payload(
        raw, tool="spec.search", version=SEARCH_CURSOR_VERSION, error=InvalidSpecSearchCursorError
    )
    if obj is None:
        return None

    r_raw = obj.get("r")
    u_raw = obj.get("u")
    i_raw = obj.get("i")
    if isinstance(r_raw, bool) or not isinstance(r_raw, int):
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (bad rank).")
    if not isinstance(u_raw, str) or not isinstance(i_raw, str):
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (missing fields).")

    parsed_at = cursor_timestamp(u_raw, tool="spec.search", error=InvalidSpecSearchCursorError)

    try:
        parsed_id = UUID(i_raw.strip())
    except ValueError as exc:
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (bad id).") from exc

    return (int(r_raw), utc(parsed_at), parsed_id)


def _clamp_limit(limit: int | None) -> int:
    return clamp_page_limit(limit, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)


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
        "updated_at": utc(ua).isoformat().replace("+00:00", "Z"),
        "rank_score": int(row["rank_score"]),
    }


#: Output columns of a search page joined back to its revision and project (aliases ``page``,
#: ``v``, ``p``); shared with ``spec.search_semantic``.
SEARCH_OUTPUT_SQL = f"""
SELECT page.id, p.tenant_id, page.project_id, p.name AS title, v.version_id AS version,
       v.description, COALESCE(tg.tags, ARRAY[]::TEXT[]) AS tags, page.updated_at, page.rank_score
FROM page
INNER JOIN apiome.versions v ON v.id = page.id
INNER JOIN apiome.projects p ON p.id = page.project_id AND {LISTED_PROJECT}
LEFT JOIN LATERAL (
  SELECT array_agg(vt.name ORDER BY vt.name) AS tags
  FROM apiome.version_tags vt
  WHERE vt.version_id = page.id AND vt.project_id = page.project_id
) tg ON TRUE
ORDER BY page.rank_score DESC, page.updated_at DESC, page.id DESC
"""

#: ``AND`` predicate that keeps the rows after a cursor in ``(rank_score, updated_at, id)`` order.
SEARCH_CURSOR_SQL = "(rank_score, updated_at, id) < (%(cur_rank)s::integer, %(cur_ts)s::timestamptz, %(cur_id)s::uuid)"


def build_spec_search_query(*, has_cursor: bool) -> str:
    """The ``spec.search`` statement (DBP-1.22): rank and page on ``versions``, then join.

    ``hit`` reads only ``apiome.versions`` — the GIN match, the rank and the stored listing
    timestamp; ``page`` applies the cursor and ``LIMIT``; the project and the tags are read for
    the rows of the page only (they used to be read for every match).

    Args:
        has_cursor: Whether the statement takes ``cur_rank`` / ``cur_ts`` / ``cur_id``.

    Returns:
        SQL with named parameters ``q``, ``lim`` and, with a cursor, the three cursor values.
    """
    cursor_sql = f"WHERE {SEARCH_CURSOR_SQL}" if has_cursor else ""
    return f"""
WITH hit AS (
  SELECT
    v.id,
    v.project_id,
    v.mcp_listed_at AS updated_at,
    GREATEST(
      1,
      LEAST(
        2147483647,
        ROUND((ts_rank_cd(v.mcp_public_doc_tsv, plainto_tsquery('english', %(q)s))::numeric) * 1000000)::integer
      )
    ) AS rank_score
  FROM apiome.versions v
  WHERE v.mcp_public_doc_tsv @@ plainto_tsquery('english', %(q)s)
    AND {listed_version("public")}
),
page AS (
  SELECT id, project_id, updated_at, rank_score
  FROM hit
  {cursor_sql}
  ORDER BY rank_score DESC, updated_at DESC, id DESC
  LIMIT %(lim)s
)
{SEARCH_OUTPUT_SQL}"""


def normalize_search_query(q: str) -> str:
    """Strip leading/trailing whitespace; reject empty queries."""
    s = str(q).strip()
    if not s:
        raise ValueError("q must be a non-empty search string.")
    return s


async def build_spec_search_response(
    pool: AsyncConnectionPool,
    *,
    q: str,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return ranked ``items``, ``has_more``, and ``next_cursor`` (Postgres full-text)."""
    query_text = normalize_search_query(q)

    lim = _clamp_limit(limit)
    decoded = decode_spec_search_cursor(cursor)

    params: dict[str, Any] = {"q": query_text, "lim": lim + 1}
    if decoded is not None:
        params.update(cur_rank=decoded[0], cur_ts=decoded[1], cur_id=decoded[2])

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(build_spec_search_query(has_cursor=decoded is not None), params)
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
