"""Shared stand-ins for testing keyset-paged list routes (DBP-1.13, #7196).

Route tests that patch a ``db.list_*`` accessor use :func:`keyset_rows` as its ``side_effect`` so the
patched accessor honours ``limit`` / ``offset`` / ``cursor`` the way the SQL does, and :func:`walk`
to follow ``next_cursor`` to the end of a list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["keyset_rows", "stamps", "walk"]


def stamps(count: int, *, tie_every: int = 2) -> List[datetime]:
    """Timestamps for ``count`` rows, with ties so the id tie-breaker is exercised.

    Args:
        count: How many timestamps to make.
        tie_every: Rows per shared timestamp.

    Returns:
        Timezone-aware timestamps, ``tie_every`` rows sharing each one.
    """
    base = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return [base + timedelta(minutes=index // tie_every) for index in range(count)]


def keyset_rows(
    rows: Sequence[Mapping[str, Any]],
    timestamp_field: str = "created_at",
    id_field: str = "id",
) -> Callable[..., List[Dict[str, Any]]]:
    """A ``side_effect`` that pages ``rows`` newest first, like a ``(timestamp, id) DESC`` query.

    Args:
        rows: Every row of the list.
        timestamp_field: The row key the list sorts by.
        id_field: The row key that breaks ties.

    Returns:
        A callable accepting any accessor arguments plus ``limit`` / ``offset`` / ``cursor``.
    """
    ordered = sorted(rows, key=lambda row: (row[timestamp_field], str(row[id_field])), reverse=True)

    def page(*_: Any, limit: int = 50, offset: int = 0, cursor: Any = None, **__: Any) -> List[Dict[str, Any]]:
        matching = ordered
        if cursor is not None:
            stamp, row_id = cursor
            matching = [row for row in ordered if (row[timestamp_field], str(row[id_field])) < (stamp, str(row_id))]
            offset = 0
        return [dict(row) for row in matching[offset : offset + limit]]

    return page


def walk(
    fetch: Callable[[Dict[str, Any]], Any],
    items_key: Optional[str],
    *,
    limit: int = 2,
    has_more_key: str = "has_more",
    next_cursor_key: str = "next_cursor",
    max_pages: int = 50,
) -> List[Any]:
    """Follow a list's cursor to its end.

    Args:
        fetch: Performs the request for the given query parameters and returns the response.
        items_key: The body key holding the page's rows; ``None`` for a bare-array body, whose
            paging state is read from the ``X-Has-More`` / ``X-Next-Cursor`` headers.
        limit: The page size to ask for.
        has_more_key: The body key of the has-more flag.
        next_cursor_key: The body key of the next cursor.
        max_pages: A guard against a cursor that never ends.

    Returns:
        Every row seen, in the order served.
    """
    seen: List[Any] = []
    cursor: Optional[str] = None
    for _ in range(max_pages):
        response = fetch({"limit": limit, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        body = response.json()
        if items_key is None:
            items = body
            has_more = response.headers["X-Has-More"] == "true"
            cursor = response.headers.get("X-Next-Cursor")
        else:
            items = body[items_key]
            has_more = body[has_more_key]
            cursor = body[next_cursor_key]
        assert len(items) <= limit
        seen += items
        if not has_more:
            assert cursor is None
            return seen
        assert cursor
    raise AssertionError("the cursor never reached the end of the list")
