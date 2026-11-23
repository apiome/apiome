"""Pagination helpers for REST offset/limit list endpoints."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlencode

from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import MAX_FOLLOWED_PAGES, next_cursor_of

# Default page size used when no --limit is specified.
DEFAULT_PAGE_LIMIT = 50


def paginate_list(
    client: RestClient,
    path: str,
    *,
    limit: int = DEFAULT_PAGE_LIMIT,
    fetch_all: bool = False,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch items from a paginated list endpoint.

    Issues one or more GET requests to ``path`` using offset/limit pagination.
    When ``fetch_all`` is ``True``, pages through all results automatically
    using repeated requests.  When ``fetch_all`` is ``False``, returns only
    the first page of up to ``limit`` items.

    The server caps ``limit`` at 200 and rejects a larger value with a 422
    response. When a page carries ``next_cursor`` the next request continues
    from that cursor; a server without cursors is paged by ``offset``.  The CLI
    delegates validation to the server and exits on any non-2xx/non-3xx
    response (including 4xx and 5xx errors).

    Parameters
    ----------
    client:
        Authenticated REST client used to issue HTTP requests.
    path:
        URL path to the list endpoint (e.g. ``/projects``).  May optionally
        include an existing query string; pagination parameters are appended
        with ``&`` when a ``?`` is already present, or ``?`` otherwise.
    limit:
        Page size to request per API call.  The server caps this at 200.
    fetch_all:
        When ``True``, pages through all results and returns the complete
        collection.  When ``False``, returns only the first page.
    params:
        Optional extra query parameters (e.g. ``{"project_id": "<uuid>"}``)
        that are URL-encoded and merged into ``path`` before the
        ``offset``/``limit`` pagination parameters are appended.

    Returns
    -------
    tuple[list[dict[str, Any]], int]
        A ``(items, total)`` pair where ``items`` is the flat list of
        collected row dicts and ``total`` is the server-reported total row
        count from the final page response.
    """
    if params:
        encoded = urlencode(params)
        path = f"{path}?{encoded}" if "?" not in path else f"{path}&{encoded}"
    items: list[dict[str, Any]] = []
    offset = 0
    total: int | None = None
    cursor: str | None = None
    sep = "&" if "?" in path else "?"

    for _ in range(MAX_FOLLOWED_PAGES):
        # The server pages by cursor (#7196); ``offset`` is only the way in to the first page, and
        # the fallback for a server that issues no cursor.
        position = f"cursor={quote(cursor, safe='')}" if cursor else f"offset={offset}"
        response = client.get(f"{path}{sep}{position}&limit={limit}")
        payload = response.json()

        page_items: list[dict[str, Any]] = payload.get("items", [])
        if isinstance(payload.get("total"), int):
            total = payload["total"]

        items.extend(page_items)

        # Stop after first page unless --all was requested.
        if not fetch_all or not page_items:
            break

        cursor = next_cursor_of(response, payload)
        if cursor:
            continue
        offset += limit
        if len(page_items) < limit or (total is not None and offset >= total):
            break

    return items, total if total is not None else len(items)


def paginate_page_list(
    client: RestClient,
    path: str,
    *,
    limit: int = DEFAULT_PAGE_LIMIT,
    fetch_all: bool = False,
    params: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch items from a page/limit paginated list endpoint.

    Issues one or more GET requests to ``path`` using 1-based ``page`` and
    ``limit`` query parameters. When ``fetch_all`` is ``True``, pages through
    all results automatically. When ``fetch_all`` is ``False``, returns only
    the first page of up to ``limit`` items.

    Parameters
    ----------
    client:
        Authenticated REST client used to issue HTTP requests.
    path:
        URL path to the list endpoint (e.g. ``/api-keys``).
    limit:
        Page size to request per API call.
    fetch_all:
        When ``True``, pages through all results and returns the complete
        collection. When ``False``, returns only the first page.
    params:
        Optional extra query parameters merged before pagination parameters.

    Returns
    -------
    tuple[list[dict[str, Any]], int]
        A ``(items, total)`` pair where ``items`` is the flat list of
        collected row dicts and ``total`` is the server-reported total row
        count from the final page response.
    """
    if params:
        encoded = urlencode(params)
        path = f"{path}?{encoded}" if "?" not in path else f"{path}&{encoded}"
    items: list[dict[str, Any]] = []
    page = 1
    total = 0
    sep = "&" if "?" in path else "?"

    while True:
        page_path = f"{path}{sep}page={page}&limit={limit}"
        response = client.get(page_path)
        payload = response.json()

        page_items: list[dict[str, Any]] = payload.get("items", [])
        total = int(payload.get("total", 0))

        items.extend(page_items)

        if not fetch_all or not page_items:
            break

        if len(items) >= total:
            break

        page += 1

    return items, total
