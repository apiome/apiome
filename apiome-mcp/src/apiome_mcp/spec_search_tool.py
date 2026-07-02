"""MCP ``spec.search`` tool: full-text search over public specs (#3007)."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

SEARCH_CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecSearchCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def encode_spec_search_cursor(rank_score: int, updated_at: datetime, spec_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = _utc(updated_at)
    payload = {
        "v": SEARCH_CURSOR_VERSION,
        "r": int(rank_score),
        "i": str(spec_id),
        "u": u.isoformat().replace("+00:00", "Z"),
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(blob).decode("ascii").rstrip("=")


def _b64url_pad(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)


def decode_spec_search_cursor(raw: str | None) -> tuple[int, datetime, UUID] | None:
    """Decode ``cursor`` into ``(rank_score, updated_at, id)`` or ``None`` when absent."""
    if raw is None:
        return None
    if not raw.strip():
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (empty value).")
    try:
        decoded_b = base64.urlsafe_b64decode(_b64url_pad(raw.strip()))
        obj = json.loads(decoded_b.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (malformed encoding).") from exc

    if not isinstance(obj, dict):
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (expected JSON object).")

    ver = obj.get("v")
    if ver != SEARCH_CURSOR_VERSION:
        raise InvalidSpecSearchCursorError(f"Unsupported spec.search cursor version: {ver!r}.")

    r_raw = obj.get("r")
    u_raw = obj.get("u")
    i_raw = obj.get("i")
    if isinstance(r_raw, bool) or not isinstance(r_raw, int):
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (bad rank).")
    if not isinstance(u_raw, str) or not isinstance(i_raw, str):
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (missing fields).")

    iso = u_raw.replace("Z", "+00:00")
    try:
        parsed_at = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (bad timestamp).") from exc

    if parsed_at.tzinfo is None:
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (timestamp must include timezone offset).")

    try:
        parsed_id = UUID(i_raw.strip())
    except ValueError as exc:
        raise InvalidSpecSearchCursorError("Invalid spec.search cursor (bad id).") from exc

    return (int(r_raw), _utc(parsed_at), parsed_id)


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}.")
    return min(limit, MAX_PAGE_SIZE)


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


_SEARCH_QUERY = """
WITH hit AS (
  SELECT
    s.id,
    s.tenant_id,
    s.project_id,
    s.title,
    s.version,
    s.description,
    s.tags,
    s.updated_at,
    ts_rank_cd(v.mcp_public_doc_tsv, plainto_tsquery('english', %(q)s)) AS rank_raw
  FROM apiome.mcp_v_public_specs AS s
  INNER JOIN apiome.versions v ON v.id = s.id
  WHERE v.mcp_public_doc_tsv @@ plainto_tsquery('english', %(q)s)
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
      LEAST(2147483647, ROUND((rank_raw::numeric) * 1000000)::integer)
    ) AS rank_score
  FROM hit
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
    has_cursor = decoded is not None
    cur_rank = decoded[0] if decoded else None
    cur_ts = decoded[1] if decoded else None
    cur_id = decoded[2] if decoded else None

    params: dict[str, Any] = {
        "q": query_text,
        "has_cursor": has_cursor,
        "cur_rank": cur_rank,
        "cur_ts": cur_ts,
        "cur_id": cur_id,
        "lim": lim + 1,
    }

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SEARCH_QUERY, params)
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
