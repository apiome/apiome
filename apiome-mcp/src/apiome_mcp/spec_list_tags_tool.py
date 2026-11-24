"""MCP ``spec.list_tags`` tool: paginated distinct tags across public specs (#3008).

The histogram is counted from ``apiome.version_tags`` directly and cached for a short time
(DBP-1.22, #7205); it used to be rebuilt from ``apiome.mcp_v_public_specs`` on every page.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.cursor_codec import (
    clamp_page_limit,
    decode_cursor_payload,
    encode_cursor_payload,
)
from apiome_mcp.settings import setting_or_default
from apiome_mcp.spec_listing_sql import LISTED_PROJECT, listed_version

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecListTagsCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def encode_spec_list_tags_cursor(cnt: int, tag: str) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    payload = {"v": CURSOR_VERSION, "c": int(cnt), "t": str(tag)}
    return encode_cursor_payload(payload)


def decode_spec_list_tags_cursor(raw: str | None) -> tuple[int, str] | None:
    """Decode ``cursor`` into ``(count, tag)`` or ``None`` when absent."""
    obj = decode_cursor_payload(
        raw, tool="spec.list_tags", version=CURSOR_VERSION, error=InvalidSpecListTagsCursorError
    )
    if obj is None:
        return None

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
    return clamp_page_limit(limit, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)


_COUNTS_SQL = f"""
  SELECT vt.name AS tag, COUNT(*)::bigint AS cnt
  FROM apiome.version_tags vt
  INNER JOIN apiome.versions v ON v.id = vt.version_id AND v.project_id = vt.project_id
  INNER JOIN apiome.projects p ON p.id = v.project_id
  WHERE {listed_version("public")} AND {LISTED_PROJECT}
  GROUP BY vt.name
"""

#: Every tag with its count, in list order: what the cache holds.
_HISTOGRAM_QUERY = f"""
SELECT tag, cnt FROM ({_COUNTS_SQL}) AS counts
ORDER BY cnt DESC, tag ASC
"""

#: One page after a cursor, compared by the database (its collation decides ``tag >``). Used when
#: the cursor's row is no longer where the cached histogram can find it.
_TAGS_AFTER_CURSOR_QUERY = f"""
SELECT tag, cnt FROM ({_COUNTS_SQL}) AS counts
WHERE cnt < %(cur_cnt)s::bigint
   OR (cnt = %(cur_cnt)s::bigint AND tag > %(cur_tag)s)
ORDER BY cnt DESC, tag ASC
LIMIT %(lim)s
"""


class TagHistogramCache:
    """The public tag histogram, kept for ``spec_tag_histogram_cache_seconds`` (DBP-1.22).

    The histogram is one aggregate over every public revision's tags and does not depend on the
    caller, the page or the cursor, so it is counted once and paged from memory. A tag added or
    removed shows within the lifetime (default 45 s; ``0`` recounts on every call).
    """

    def __init__(
        self,
        *,
        ttl_seconds: Callable[[], float] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty cache.

        Args:
            ttl_seconds: Returns the current lifetime (default: the setting).
            clock: Monotonic clock (tests).
        """
        self._ttl = ttl_seconds or (lambda: setting_or_default("spec_tag_histogram_cache_seconds", 45.0))
        self._clock = clock
        self._expires_at = 0.0
        self._rows: list[tuple[str, int]] | None = None
        self._index: dict[str, int] = {}

    def rows(self) -> list[tuple[str, int]] | None:
        """The cached ``(tag, count)`` rows in list order, or ``None`` when absent or expired."""
        if self._rows is None or self._expires_at <= self._clock():
            return None
        return self._rows

    def store(self, rows: list[tuple[str, int]]) -> None:
        """Keep ``rows`` (already in list order) for the lifetime; a no-op when the cache is off."""
        ttl = float(self._ttl())
        if ttl <= 0:
            self.clear()
            return
        self._rows = rows
        self._index = {tag: i for i, (tag, _) in enumerate(rows)}
        self._expires_at = self._clock() + ttl

    def position_after(self, cnt: int, tag: str) -> int | None:
        """Index of the row that follows the cursor row ``(cnt, tag)`` in the cached histogram.

        Returns:
            The index, or ``None`` when the cached histogram has no row with exactly that tag and
            count (the tag was removed or its count changed since the cursor was issued).
        """
        if self._rows is None:
            return None
        i = self._index.get(tag)
        if i is None or self._rows[i][1] != cnt:
            return None
        return i + 1

    def clear(self) -> None:
        """Forget the histogram."""
        self._rows = None
        self._index = {}
        self._expires_at = 0.0


#: The process-wide histogram cache.
TAG_HISTOGRAM_CACHE = TagHistogramCache()


def _page_response(rows: list[tuple[str, int]], lim: int) -> dict[str, Any]:
    """Build the tool response from up to ``lim + 1`` rows in list order."""
    has_more = len(rows) > lim
    page = rows[:lim]
    next_cursor: str | None = None
    if has_more and page:
        next_cursor = encode_spec_list_tags_cursor(int(page[-1][1]), str(page[-1][0]))
    return {
        "items": [{"tag": str(tag), "count": int(cnt)} for tag, cnt in page],
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


async def build_spec_list_tags_response(
    pool: AsyncConnectionPool,
    *,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return ``items`` (``tag``, ``count``), ``has_more``, and ``next_cursor``.

    Sorted by usage count descending, then tag name ascending, over the tags of published public
    revisions. The histogram is counted from ``apiome.version_tags`` at most once per
    ``spec_tag_histogram_cache_seconds`` and paged from memory (no statement on a warm call). A
    cursor whose row the cached histogram no longer holds is answered by the database instead
    (one statement), so a page never skips or repeats a tag because of the cache.
    """
    lim = _clamp_limit(limit)
    decoded = decode_spec_list_tags_cursor(cursor)

    rows = TAG_HISTOGRAM_CACHE.rows()
    if rows is None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_HISTOGRAM_QUERY)
                rows = [(str(r["tag"]), int(r["cnt"])) for r in await cur.fetchall()]
        TAG_HISTOGRAM_CACHE.store(rows)

    if decoded is None:
        return _page_response(rows[: lim + 1], lim)

    start = TAG_HISTOGRAM_CACHE.position_after(decoded[0], decoded[1])
    if start is None and rows:
        # Freshly counted and not cached (lifetime 0): the cursor row may still be in ``rows``.
        start = next((i + 1 for i, row in enumerate(rows) if row == (decoded[1], decoded[0])), None)
    if start is not None:
        return _page_response(rows[start : start + lim + 1], lim)

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _TAGS_AFTER_CURSOR_QUERY,
                {"cur_cnt": decoded[0], "cur_tag": decoded[1], "lim": lim + 1},
            )
            after = [(str(r["tag"]), int(r["cnt"])) for r in await cur.fetchall()]
    return _page_response(after, lim)
