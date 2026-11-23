"""List helpers follow the server's cursors (apiome-rest #7196).

apiome-rest pages every growing list: array bodies report the next page in the ``X-Has-More`` /
``X-Next-Cursor`` headers, envelopes in ``has_more`` / ``next_cursor``. The CLI's helpers keep
returning whole lists by following those cursors, and still work against a server without them.
"""

from __future__ import annotations

from apiome_cli.client.http import RestClient
from apiome_cli.client.list_response import (
    fetch_list,
    next_cursor_of,
    paginate_offset_list,
)
from apiome_cli.client.pagination import paginate_list
from apiome_cli.config import CliSettings

BASE = "http://localhost:8000"
A, B, C = ({"id": "a"}, {"id": "b"}, {"id": "c"})


def _client() -> RestClient:
    return RestClient(CliSettings.model_validate({"base_url": BASE, "api_key": "test-key"}))


class _Response:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


# --- next_cursor_of ----------------------------------------------------------------------------


def test_an_array_body_reads_its_cursor_from_the_headers() -> None:
    more = _Response({"X-Has-More": "true", "X-Next-Cursor": "abc"})
    assert next_cursor_of(more, [A]) == "abc"
    assert next_cursor_of(_Response({"X-Has-More": "false", "X-Next-Cursor": "abc"}), [A]) is None
    assert next_cursor_of(_Response({}), [A]) is None


def test_an_envelope_reads_its_cursor_from_the_body_in_either_casing() -> None:
    assert next_cursor_of(_Response({}), {"items": [], "has_more": True, "next_cursor": "n1"}) == "n1"
    assert next_cursor_of(_Response({}), {"items": [], "hasMore": True, "nextCursor": "n2"}) == "n2"
    assert (
        next_cursor_of(_Response({}), {"items": [], "pagination": {"has_more": True, "next_cursor": "n3"}})
        == "n3"
    )
    assert next_cursor_of(_Response({}), {"items": [], "has_more": False, "next_cursor": "n4"}) is None
    assert next_cursor_of(_Response({}), {"items": [], "next_cursor": None}) is None


# --- fetch_list --------------------------------------------------------------------------------


def test_fetch_list_follows_header_cursors_to_the_end(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/projects/acme", json=[A, B], headers={"X-Has-More": "true", "X-Next-Cursor": "c1"}
    )
    httpx_mock.add_response(
        url=f"{BASE}/v1/projects/acme?cursor=c1", json=[C], headers={"X-Has-More": "false"}
    )
    assert fetch_list(_client(), "/v1/projects/acme") == ([A, B, C], 3)


def test_fetch_list_keeps_the_filters_on_every_page(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/classes/acme?version_id=v1",
        json=[A],
        headers={"X-Has-More": "true", "X-Next-Cursor": "c 1"},
    )
    httpx_mock.add_response(url=f"{BASE}/v1/classes/acme?version_id=v1&cursor=c+1", json=[B])
    items, total = fetch_list(_client(), "/v1/classes/acme", params={"version_id": "v1"})
    assert (items, total) == ([A, B], 2)


def test_fetch_list_can_stop_at_the_first_page(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/projects/acme", json=[A], headers={"X-Has-More": "true", "X-Next-Cursor": "c1"}
    )
    assert fetch_list(_client(), "/v1/projects/acme", follow=False) == ([A], 1)


def test_fetch_list_follows_an_envelope_cursor_and_tolerates_a_null_total(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/export/acme/jobs",
        json={"jobs": [A], "total": None, "has_more": True, "next_cursor": "n1"},
    )
    httpx_mock.add_response(
        url=f"{BASE}/v1/export/acme/jobs?cursor=n1",
        json={"jobs": [B], "total": None, "has_more": False, "next_cursor": None},
    )
    assert fetch_list(_client(), "/v1/export/acme/jobs") == ([A, B], 2)


def test_fetch_list_reports_the_servers_total_when_it_sends_one(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{BASE}/things", json={"items": [A], "total": 40})
    assert fetch_list(_client(), "/things") == ([A], 40)


def test_fetch_list_against_a_server_without_cursors_is_one_request(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{BASE}/v1/projects/acme", json=[A, B])
    assert fetch_list(_client(), "/v1/projects/acme") == ([A, B], 2)


def test_fetch_list_stops_when_a_cursor_leads_to_an_empty_page(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/projects/acme", json=[A], headers={"X-Has-More": "true", "X-Next-Cursor": "c1"}
    )
    httpx_mock.add_response(
        url=f"{BASE}/v1/projects/acme?cursor=c1", json=[], headers={"X-Has-More": "true", "X-Next-Cursor": "c1"}
    )
    assert fetch_list(_client(), "/v1/projects/acme") == ([A], 1)


# --- paginate_offset_list / paginate_list ------------------------------------------------------


def test_paginate_offset_list_switches_to_the_cursor_after_the_first_page(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/v1/tenants/me?offset=0&limit=2",
        json={"items": [A, B], "has_more": True, "next_cursor": "n1"},
    )
    httpx_mock.add_response(
        url=f"{BASE}/v1/tenants/me?cursor=n1&limit=2",
        json={"items": [C], "has_more": False, "next_cursor": None},
    )
    assert paginate_offset_list(_client(), "/v1/tenants/me", limit=2, fetch_all=True) == ([A, B, C], 3)


def test_paginate_offset_list_falls_back_to_offset_without_a_cursor(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{BASE}/t?offset=0&limit=2", json={"items": [A, B], "total": 3})
    httpx_mock.add_response(url=f"{BASE}/t?offset=2&limit=2", json={"items": [C], "total": 3})
    assert paginate_offset_list(_client(), "/t", limit=2, fetch_all=True) == ([A, B, C], 3)


def test_paginate_offset_list_without_a_total_ends_on_a_short_page(httpx_mock: object) -> None:
    httpx_mock.add_response(url=f"{BASE}/t?offset=0&limit=2", json={"items": [A]})
    assert paginate_offset_list(_client(), "/t", limit=2, fetch_all=True) == ([A], 1)


def test_paginate_offset_list_first_page_only_by_default(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/t?offset=0&limit=2", json={"items": [A, B], "has_more": True, "next_cursor": "n1"}
    )
    assert paginate_offset_list(_client(), "/t", limit=2) == ([A, B], 2)


def test_paginate_list_follows_next_cursor_when_total_is_absent(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/widgets?offset=0&limit=2",
        json={"items": [A, B], "total": None, "has_more": True, "next_cursor": "n/1="},
    )
    httpx_mock.add_response(
        url=f"{BASE}/widgets?cursor=n%2F1%3D&limit=2",
        json={"items": [C], "total": None, "has_more": False, "next_cursor": None},
    )
    assert paginate_list(_client(), "/widgets", limit=2, fetch_all=True) == ([A, B, C], 3)
