"""Normalize list responses from ``apiome-rest`` (array or paginated envelope)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from apiome_cli.client.http import RestClient


#: Response header of bare-array lists: ``true`` when another page exists (apiome-rest #7196).
HAS_MORE_HEADER = "X-Has-More"
#: Response header of bare-array lists: the cursor of the next page.
NEXT_CURSOR_HEADER = "X-Next-Cursor"
#: Envelope keys that hold a list's rows, in the order they are tried.
_ROW_KEYS = ("items", "jobs", "repositories")
#: The most pages one call follows, so a server that never ends its list cannot hang the CLI.
MAX_FOLLOWED_PAGES = 1000


def _with_params(
    path: str, params: Mapping[str, str] | Sequence[tuple[str, str]] | None
) -> str:
    """Append query parameters to a path that may already carry a query string."""
    if not params:
        return path
    encoded = urlencode(params)
    return f"{path}?{encoded}" if "?" not in path else f"{path}&{encoded}"


def _rows_and_total(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    """Pull the rows and the server-reported total (when there is one) out of a list body."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)], None
    if isinstance(payload, dict):
        for key in _ROW_KEYS:
            raw = payload.get(key)
            if isinstance(raw, list):
                rows = [row for row in raw if isinstance(row, dict)]
                total = payload.get("total")
                if total is None and isinstance(payload.get("pagination"), dict):
                    total = payload["pagination"].get("total")
                return rows, int(total) if isinstance(total, int) else None
    return [], None


def next_cursor_of(response: Any, payload: Any) -> str | None:
    """The cursor of the page after this one, or ``None`` on the last page.

    apiome-rest reports it in the ``X-Next-Cursor`` header for array bodies and as
    ``next_cursor`` (``nextCursor`` on camelCase envelopes, sometimes under ``pagination``) for
    object bodies. A server that predates cursors reports neither, so the list ends here.
    """
    if isinstance(payload, dict):
        holders = [payload]
        if isinstance(payload.get("pagination"), dict):
            holders.append(payload["pagination"])
        for holder in holders:
            for key in ("next_cursor", "nextCursor"):
                value = holder.get(key)
                if isinstance(value, str) and value:
                    has_more = holder.get("has_more", holder.get("hasMore", True))
                    return value if has_more else None
        return None
    headers = getattr(response, "headers", None) or {}
    if str(headers.get(HAS_MORE_HEADER, "")).lower() != "true":
        return None
    cursor = headers.get(NEXT_CURSOR_HEADER)
    return cursor if isinstance(cursor, str) and cursor else None


def fetch_list(
    client: RestClient,
    path: str,
    *,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    follow: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """GET ``path`` and return ``(items, total)`` for array or ``{items,total}`` bodies.

    Lists are paged by the server (#7196). With ``follow`` (the default) every further page is
    fetched through its cursor, so callers keep receiving the whole list; pass ``follow=False``
    for the first page only. ``total`` is the server's total when it sends one, else the number
    of rows returned.
    """
    base = _with_params(path, params)
    response = client.get(base)
    payload = response.json()
    rows, total = _rows_and_total(payload)
    cursor = next_cursor_of(response, payload) if follow else None
    pages = 1
    while cursor and pages < MAX_FOLLOWED_PAGES:
        response = client.get(_with_params(base, [("cursor", cursor)]))
        payload = response.json()
        page_rows, page_total = _rows_and_total(payload)
        if not page_rows:
            break
        rows.extend(page_rows)
        total = page_total if page_total is not None else total
        cursor = next_cursor_of(response, payload)
        pages += 1
    return rows, total if total is not None else len(rows)


def paginate_offset_list(
    client: RestClient,
    path: str,
    *,
    limit: int,
    fetch_all: bool = False,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Page through a list endpoint such as ``GET /v1/tenants/me``.

    Follows the server's cursor when it issues one (#7196) and falls back to ``offset`` for a
    server that does not. A list without a total ends on the first short page.
    """
    base_params: list[tuple[str, str]] = list(params or [])
    items: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    cursor: str | None = None
    for _ in range(MAX_FOLLOWED_PAGES):
        position = ("cursor", cursor) if cursor else ("offset", str(offset))
        page_path = _with_params(path, [*base_params, position, ("limit", str(limit))])
        response = client.get(page_path)
        payload = response.json()
        page_items, page_total = _rows_and_total(payload)
        total = page_total if page_total is not None else total
        items.extend(page_items)
        if not fetch_all or not page_items:
            break
        cursor = next_cursor_of(response, payload)
        if cursor:
            continue
        offset += len(page_items)
        if len(page_items) < limit or (total is not None and offset >= total):
            break
    return items, total if total is not None else len(items)
