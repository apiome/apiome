"""Unit tests for the pagination helper (client/pagination.py)."""

from __future__ import annotations

import pytest
import typer

from apiome_cli.client.http import RestClient
from apiome_cli.client.pagination import DEFAULT_PAGE_LIMIT, paginate_list, paginate_page_list
from apiome_cli.config import CliSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(*, base_url: str = "http://localhost:8000", api_key: str = "test-key") -> CliSettings:
    """Return a CliSettings instance for testing."""
    return CliSettings.model_validate({"base_url": base_url, "api_key": api_key})


def _client(settings: CliSettings | None = None) -> RestClient:
    """Return a RestClient using test settings."""
    return RestClient(settings or _settings())


def _page(*, total: int, offset: int, limit: int, items: list) -> dict:
    """Build a server-style paginated response dict."""
    return {"total": total, "offset": offset, "limit": limit, "items": items}


_ITEM_A = {"id": "aaa", "name": "Alpha"}
_ITEM_B = {"id": "bbb", "name": "Beta"}
_ITEM_C = {"id": "ccc", "name": "Gamma"}


# ---------------------------------------------------------------------------
# DEFAULT_PAGE_LIMIT constant
# ---------------------------------------------------------------------------


def test_default_page_limit_is_positive() -> None:
    """DEFAULT_PAGE_LIMIT must be a positive integer."""
    assert isinstance(DEFAULT_PAGE_LIMIT, int)
    assert DEFAULT_PAGE_LIMIT > 0


# ---------------------------------------------------------------------------
# Single-page (fetch_all=False)
# ---------------------------------------------------------------------------


def test_paginate_list_single_page_returns_items(httpx_mock: object) -> None:
    """Single request returns items from the first page."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=50",
        json=_page(total=2, offset=0, limit=50, items=[_ITEM_A, _ITEM_B]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=50)
    assert items == [_ITEM_A, _ITEM_B]
    assert total == 2


def test_paginate_list_single_page_sends_correct_url(httpx_mock: object) -> None:
    """offset=0 and limit are forwarded in the query string."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=10",
        json=_page(total=1, offset=0, limit=10, items=[_ITEM_A]),
    )
    paginate_list(_client(), "/widgets", limit=10)
    assert len(httpx_mock.get_requests()) == 1
    assert "offset=0" in str(httpx_mock.get_requests()[0].url)
    assert "limit=10" in str(httpx_mock.get_requests()[0].url)


def test_paginate_list_single_page_does_not_fetch_next(httpx_mock: object) -> None:
    """Without fetch_all, only one GET is issued even when total > limit."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=2",
        json=_page(total=5, offset=0, limit=2, items=[_ITEM_A, _ITEM_B]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=2)
    assert items == [_ITEM_A, _ITEM_B]
    assert total == 5
    assert len(httpx_mock.get_requests()) == 1


def test_paginate_list_empty_page_returns_empty(httpx_mock: object) -> None:
    """Empty items list from server returns empty result."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=50",
        json=_page(total=0, offset=0, limit=50, items=[]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=50)
    assert items == []
    assert total == 0


def test_paginate_list_uses_default_limit(httpx_mock: object) -> None:
    """Calling without explicit limit uses DEFAULT_PAGE_LIMIT."""
    httpx_mock.add_response(
        url=f"http://localhost:8000/widgets?offset=0&limit={DEFAULT_PAGE_LIMIT}",
        json=_page(total=1, offset=0, limit=DEFAULT_PAGE_LIMIT, items=[_ITEM_A]),
    )
    items, total = paginate_list(_client(), "/widgets")
    assert items == [_ITEM_A]
    assert total == 1


# ---------------------------------------------------------------------------
# Multi-page (fetch_all=True)
# ---------------------------------------------------------------------------


def test_paginate_list_all_collects_multiple_pages(httpx_mock: object) -> None:
    """fetch_all=True issues multiple requests and collects all items."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=2",
        json=_page(total=3, offset=0, limit=2, items=[_ITEM_A, _ITEM_B]),
    )
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=2&limit=2",
        json=_page(total=3, offset=2, limit=2, items=[_ITEM_C]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=2, fetch_all=True)
    assert items == [_ITEM_A, _ITEM_B, _ITEM_C]
    assert total == 3
    assert len(httpx_mock.get_requests()) == 2


def test_paginate_list_all_stops_when_offset_reaches_total(httpx_mock: object) -> None:
    """fetch_all=True stops when offset >= total after collecting all items."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=2",
        json=_page(total=2, offset=0, limit=2, items=[_ITEM_A, _ITEM_B]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=2, fetch_all=True)
    assert items == [_ITEM_A, _ITEM_B]
    assert total == 2
    # Exactly one request when total == page size.
    assert len(httpx_mock.get_requests()) == 1


def test_paginate_list_all_stops_on_empty_page(httpx_mock: object) -> None:
    """fetch_all=True stops when a page returns no items."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=5",
        json=_page(total=2, offset=0, limit=5, items=[_ITEM_A, _ITEM_B]),
    )
    items, total = paginate_list(_client(), "/widgets", limit=5, fetch_all=True)
    assert items == [_ITEM_A, _ITEM_B]
    # Only one request — items exhausted in the first page.
    assert len(httpx_mock.get_requests()) == 1


def test_paginate_list_all_three_pages(httpx_mock: object) -> None:
    """fetch_all=True handles three consecutive pages correctly."""
    httpx_mock.add_response(
        url="http://localhost:8000/items?offset=0&limit=1",
        json=_page(total=3, offset=0, limit=1, items=[_ITEM_A]),
    )
    httpx_mock.add_response(
        url="http://localhost:8000/items?offset=1&limit=1",
        json=_page(total=3, offset=1, limit=1, items=[_ITEM_B]),
    )
    httpx_mock.add_response(
        url="http://localhost:8000/items?offset=2&limit=1",
        json=_page(total=3, offset=2, limit=1, items=[_ITEM_C]),
    )
    items, total = paginate_list(_client(), "/items", limit=1, fetch_all=True)
    assert items == [_ITEM_A, _ITEM_B, _ITEM_C]
    assert total == 3
    assert len(httpx_mock.get_requests()) == 3


# ---------------------------------------------------------------------------
# Existing query parameters preserved
# ---------------------------------------------------------------------------


def test_paginate_list_appends_to_existing_query_params(httpx_mock: object) -> None:
    """When path already contains '?', pagination params are appended with '&'."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?enabled=true&offset=0&limit=5",
        json=_page(total=1, offset=0, limit=5, items=[_ITEM_A]),
    )
    items, _ = paginate_list(_client(), "/widgets?enabled=true", limit=5)
    assert items == [_ITEM_A]


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_paginate_list_exits_on_4xx(httpx_mock: object) -> None:
    """HTTP 4xx from server causes typer.Exit (e.g. limit exceeds PAGINATION_MAX_LIMIT)."""
    httpx_mock.add_response(
        url="http://localhost:8000/widgets?offset=0&limit=9999",
        status_code=422,
        json={"code": 422, "message": "limit must not exceed 200"},
    )
    with pytest.raises(typer.Exit):
        paginate_list(_client(), "/widgets", limit=9999)


def test_paginate_list_exits_on_connection_error(httpx_mock: object) -> None:
    """Transport error causes typer.Exit via exit_on_connection_error."""
    import httpx as _httpx
    httpx_mock.add_exception(_httpx.ConnectError("refused"))
    with pytest.raises(typer.Exit):
        paginate_list(_client(), "/widgets", limit=10)


def _page_response(*, total: int, page: int, limit: int, items: list) -> dict:
    """Build a server-style page/limit paginated response dict."""
    return {"total": total, "page": page, "limit": limit, "items": items}


def test_paginate_page_list_fetches_first_page(httpx_mock: object) -> None:
    """page=1 and limit are forwarded in the query string."""
    httpx_mock.add_response(
        url="http://localhost:8000/api-keys?page=1&limit=10",
        json=_page_response(total=1, page=1, limit=10, items=[_ITEM_A]),
    )
    items, total = paginate_page_list(_client(), "/api-keys", limit=10)
    assert total == 1
    assert items == [_ITEM_A]
    assert "page=1" in str(httpx_mock.get_requests()[0].url)


def test_paginate_page_list_fetch_all_pages(httpx_mock: object) -> None:
    """fetch_all=True walks page/limit pages until total is reached."""
    httpx_mock.add_response(
        url="http://localhost:8000/api-keys?page=1&limit=2",
        json=_page_response(total=3, page=1, limit=2, items=[_ITEM_A, _ITEM_B]),
    )
    httpx_mock.add_response(
        url="http://localhost:8000/api-keys?page=2&limit=2",
        json=_page_response(total=3, page=2, limit=2, items=[_ITEM_C]),
    )
    items, total = paginate_page_list(_client(), "/api-keys", limit=2, fetch_all=True)
    assert total == 3
    assert items == [_ITEM_A, _ITEM_B, _ITEM_C]
