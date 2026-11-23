"""Shared stand-ins for testing keyset-paged list routes (DBP-1.13, #7196).

Route tests that patch a ``db.list_*`` accessor use :func:`keyset_rows` as its ``side_effect`` so the
patched accessor honours ``limit`` / ``offset`` / ``cursor`` the way the SQL does, and :func:`walk`
to follow ``next_cursor`` to the end of a list.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

__all__ = ["check_list_paging", "keyset_rows", "ordered_rows", "stamps", "walk"]


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


def ordered_rows(order: Any, rows: Sequence[Any]) -> Callable[..., List[Any]]:
    """A ``side_effect`` that pages ``rows`` (already in list order) for a ``ListOrder`` accessor.

    Args:
        order: The list's :class:`app.keyset_lists.ListOrder`.
        rows: Every row of the list, in the order the query returns them.

    Returns:
        A callable accepting any accessor arguments plus ``limit`` / ``cursor``; ``limit=None``
        returns every row, as the accessors do for internal callers.
    """
    everything = list(rows)

    def page(*_: Any, limit: Optional[int] = None, cursor: Any = None, **__: Any) -> List[Any]:
        remaining = everything
        if cursor is not None:
            seen = [order.decode(order.cursor_of(row)) for row in everything]
            position = seen.index(list(cursor))
            remaining = everything[position + 1 :]
        return list(remaining if limit is None else remaining[:limit])

    return page


def check_list_paging(
    fetch: Callable[[Dict[str, Any]], Any],
    items_key: Optional[str],
    expected: Sequence[Any],
    *,
    maximum: int,
    id_of: Callable[[Any], Any] = lambda item: item["id"],
    has_more_key: str = "has_more",
    next_cursor_key: str = "next_cursor",
) -> None:
    """The four facts every converted list endpoint must show.

    A page of ``limit`` rows reports has-more and a cursor, the cursor walks the rest in order,
    a ``limit`` over the maximum is a ``422`` and a malformed cursor is a ``400``.

    Args:
        fetch: Performs the request for the given query parameters and returns the response.
        items_key: The body key holding the rows; ``None`` for a bare-array body (paging state
            is then in the ``X-Has-More`` / ``X-Next-Cursor`` headers).
        expected: The ids of every row, in list order (at least three).
        maximum: The documented maximum ``limit``.
        id_of: Reads the id of a served row.
        has_more_key: The body key of the has-more flag.
        next_cursor_key: The body key of the next cursor.
    """
    assert len(expected) >= 3, "paging needs at least three rows to show a middle page"
    first = fetch({"limit": 2})
    assert first.status_code == 200, first.text
    if items_key is None:
        assert first.headers["X-Has-More"] == "true"
        assert first.headers["X-Next-Cursor"]
        assert [id_of(item) for item in first.json()] == list(expected[:2])
    else:
        body = first.json()
        assert body[has_more_key] is True
        assert body[next_cursor_key]
        assert [id_of(item) for item in body[items_key]] == list(expected[:2])
    walked = walk(fetch, items_key, limit=2, has_more_key=has_more_key, next_cursor_key=next_cursor_key)
    assert [id_of(item) for item in walked] == list(expected)
    assert fetch({"limit": maximum + 1}).status_code == 422
    assert fetch({"cursor": "not-a-cursor"}).status_code == 400
