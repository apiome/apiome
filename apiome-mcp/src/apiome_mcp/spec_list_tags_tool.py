"""MCP ``spec.list_tags`` tool: paginated distinct tags across public specs (#3008)."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecListTagsCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def _b64url_pad(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)


def encode_spec_list_tags_cursor(cnt: int, tag: str) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    payload = {"v": CURSOR_VERSION, "c": int(cnt), "t": str(tag)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_spec_list_tags_cursor(raw: str | None) -> tuple[int, str] | None:
    """Decode ``cursor`` into ``(count, tag)`` or ``None`` when absent."""
    if raw is None:
        return None
    if not raw.strip():
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (empty value).")
    try:
        blob = base64.urlsafe_b64decode(_b64url_pad(raw.strip()))
        obj = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (malformed encoding).") from exc

    if not isinstance(obj, dict):
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (expected JSON object).")

    ver = obj.get("v")
    if ver != CURSOR_VERSION:
        raise InvalidSpecListTagsCursorError(f"Unsupported spec.list_tags cursor version: {ver!r}.")

    c_raw = obj.get("c")
    t_raw = obj.get("t")
    if isinstance(c_raw, bool) or not isinstance(c_raw, int):
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (bad count).")
    if not isinstance(t_raw, str):
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (bad tag).")

    if c_raw < 0:
        raise InvalidSpecListTagsCursorError("Invalid spec.list_tags cursor (negative count).")

    return (int(c_raw), str(t_raw))


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}.")
    return min(limit, MAX_PAGE_SIZE)


def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"tag": str(row["tag"]), "count": int(row["cnt"])}


_TAGS_PAGE_QUERY = """
WITH counts AS (
  SELECT tags.tag AS tag, COUNT(*)::bigint AS cnt
  FROM apiome.mcp_v_public_specs AS s
  CROSS JOIN LATERAL unnest(s.tags) AS tags(tag)
  GROUP BY tags.tag
)
SELECT tag, cnt
FROM counts
WHERE (
  NOT %(has_cursor)s
  OR (
    cnt < %(cur_cnt)s::bigint
    OR (cnt = %(cur_cnt)s::bigint AND tag > %(cur_tag)s)
  )
)
ORDER BY cnt DESC, tag ASC
LIMIT %(lim)s
"""


async def build_spec_list_tags_response(
    pool: AsyncConnectionPool,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return ``items`` (``tag``, ``count``), ``has_more``, and ``next_cursor``.

    Sorted by usage count descending, then tag name ascending. Anonymous-only:
    ``apiome.mcp_v_public_specs``.
    """
    lim = _clamp_limit(limit)
    decoded = decode_spec_list_tags_cursor(cursor)
    has_cursor = decoded is not None
    cur_cnt = decoded[0] if decoded else None
    cur_tag = decoded[1] if decoded else None

    params: dict[str, Any] = {
        "has_cursor": has_cursor,
        "cur_cnt": cur_cnt,
        "cur_tag": cur_tag,
        "lim": lim + 1,
    }

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_TAGS_PAGE_QUERY, params)
            rows = await cur.fetchall()

    has_more = len(rows) > lim
    page = rows[:lim]
    items = [_row_out(r) for r in page]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_spec_list_tags_cursor(int(last["cnt"]), str(last["tag"]))

    return {
        "items": items,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
