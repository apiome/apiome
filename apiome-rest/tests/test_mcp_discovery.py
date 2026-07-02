"""Unit tests for MCP discovery list methods + cursor pagination (V2-MCP-16.3, #3659).

These drive :func:`app.mcp_client.discovery.discover_listings` and the lower-level
:func:`app.mcp_client.discovery.paginate` against the real
:class:`StreamableHttpTransport` wired to a mocked httpx transport (no sockets),
so every branch is covered deterministically: single- and multi-page lists,
declared-only gating (including ``resources`` gating *both* resource endpoints),
empty results, JSON-RPC errors, and the two non-termination guards (a repeated
cursor and exceeding the page limit). A companion integration test that pages
against a real loopback stub server lives in ``test_mcp_discovery_integration.py``.
"""

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app.mcp_client.discovery import (
    DEFAULT_PAGE_LIMIT,
    LIST_METHODS,
    DiscoveryListings,
    McpDiscoveryError,
    McpPaginationError,
    discover_listings,
    paginate,
)
from app.mcp_client.resilience import BudgetExceededError, TimeBudget
from app.mcp_client.transport_http import StreamableHttpTransport


class FakeClock:
    """A deterministic monotonic clock returning scripted timestamps in order.

    Once the script is exhausted the final value repeats, so a budget can be made
    to look already-spent on every check after construction.
    """

    def __init__(self, times: List[float]) -> None:
        self._times = list(times)
        self._index = 0

    def __call__(self) -> float:
        value = self._times[min(self._index, len(self._times) - 1)]
        self._index += 1
        return value

ENDPOINT = "https://mcp.example.com/mcp"

ALL_CAPABILITIES = {"tools": {}, "resources": {}, "prompts": {}}


# ===========================================================================
# Test helpers
# ===========================================================================


class ListHandler:
    """A MockTransport handler scripting paginated ``*/list`` replies per method.

    ``pages`` maps a JSON-RPC method to a list of result objects, one per cursor
    step: page *i* is returned when the request's ``cursor`` equals page *i-1*'s
    ``nextCursor`` (the first request carries no cursor). Methods absent from the
    map answer with an empty list. Every request body is recorded for assertions.
    """

    def __init__(self, pages: Dict[str, List[Dict[str, Any]]]) -> None:
        self._pages = pages
        self.bodies: List[Dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        self.bodies.append(body)
        if "id" not in body:  # a notification
            return httpx.Response(202)

        method = body.get("method")
        pages = self._pages.get(method, [{}])
        cursor = (body.get("params") or {}).get("cursor")
        result = _page_for_cursor(pages, cursor)
        return _json_rpc(body["id"], result=result)

    def cursors_for(self, method: str) -> List[Optional[str]]:
        """The ``cursor`` param sent on each request to ``method``, in order."""
        return [
            (b.get("params") or {}).get("cursor")
            for b in self.bodies
            if b.get("method") == method
        ]

    def methods_called(self) -> List[str]:
        return [b["method"] for b in self.bodies if "id" in b]


def _page_for_cursor(pages: List[Dict[str, Any]], cursor: Optional[str]) -> Dict[str, Any]:
    """Return the page whose predecessor advertised ``cursor`` (or page 0 if None)."""
    if cursor is None:
        return pages[0]
    for index, page in enumerate(pages):
        if page.get("nextCursor") == cursor:
            return pages[index + 1]
    raise AssertionError(f"unexpected cursor {cursor!r}")


def _json_rpc(rpc_id: Any, *, result: Any = None, error: Any = None) -> httpx.Response:
    message: Dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    return httpx.Response(200, json=message)


def make_transport(handler: Callable[[httpx.Request], httpx.Response]) -> StreamableHttpTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return StreamableHttpTransport(ENDPOINT, client=client)


def page(items_key: str, items: List[Dict[str, Any]], next_cursor: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {items_key: items}
    if next_cursor is not None:
        result["nextCursor"] = next_cursor
    return result


# ===========================================================================
# Registry sanity
# ===========================================================================


def test_list_methods_registry_is_complete_and_correctly_gated():
    by_method = {m.method: m for m in LIST_METHODS}
    assert set(by_method) == {
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "prompts/list",
    }
    # The templates endpoint uses the resourceTemplates result key but is gated by
    # the single resources capability (shared with resources/list).
    assert by_method["resources/templates/list"].items_key == "resourceTemplates"
    assert by_method["resources/templates/list"].capability == "resources"
    assert by_method["resources/list"].capability == "resources"


# ===========================================================================
# paginate(): single page, multi-page, empty
# ===========================================================================


async def test_paginate_single_page_returns_all_items():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "a"}, {"name": "b"}])]})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools")

    assert items == [{"name": "a"}, {"name": "b"}]
    # One request, no cursor sent.
    assert handler.cursors_for("tools/list") == [None]


async def test_paginate_follows_cursor_across_multiple_pages():
    pages = [
        page("tools", [{"name": "a"}], next_cursor="c1"),
        page("tools", [{"name": "b"}], next_cursor="c2"),
        page("tools", [{"name": "c"}]),  # final page: no nextCursor
    ]
    handler = ListHandler({"tools/list": pages})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools")

    assert items == [{"name": "a"}, {"name": "b"}, {"name": "c"}]
    # Cursor advanced opaquely page to page; first request carried none.
    assert handler.cursors_for("tools/list") == [None, "c1", "c2"]


async def test_paginate_empty_result_is_empty_list():
    handler = ListHandler({"prompts/list": [page("prompts", [])]})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "prompts/list", "prompts")
    assert items == []


async def test_paginate_missing_items_key_is_tolerated():
    handler = ListHandler({"tools/list": [{}]})  # result with neither items nor cursor
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools")
    assert items == []


async def test_paginate_drops_non_object_items_defensively():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "a"}, "garbage", 7])]})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools")
    assert items == [{"name": "a"}]


async def test_paginate_empty_string_next_cursor_terminates():
    # A present-but-empty nextCursor must be treated as the end, not followed.
    handler = ListHandler({"tools/list": [page("tools", [{"name": "a"}], next_cursor="")]})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools")
    assert items == [{"name": "a"}]
    assert handler.cursors_for("tools/list") == [None]


async def test_paginate_merges_extra_params_on_every_page():
    pages = [
        page("tools", [{"name": "a"}], next_cursor="c1"),
        page("tools", [{"name": "b"}]),
    ]
    handler = ListHandler({"tools/list": pages})
    async with make_transport(handler) as transport:
        await paginate(transport, "tools/list", "tools", params={"_meta": {"trace": 1}})

    bodies = [b for b in handler.bodies if b.get("method") == "tools/list"]
    assert all(b["params"]["_meta"] == {"trace": 1} for b in bodies)
    assert "cursor" not in bodies[0]["params"]
    assert bodies[1]["params"]["cursor"] == "c1"


# ===========================================================================
# paginate(): error + non-termination guards
# ===========================================================================


async def test_paginate_raises_on_jsonrpc_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return _json_rpc(body["id"], error={"code": -32603, "message": "boom", "data": {"x": 1}})

    async with make_transport(handler) as transport:
        with pytest.raises(McpDiscoveryError) as excinfo:
            await paginate(transport, "tools/list", "tools")

    err = excinfo.value
    assert err.method == "tools/list"
    assert err.code == -32603
    assert err.data == {"x": 1}


async def test_paginate_detects_repeated_cursor_cycle():
    # Server returns the same nextCursor forever — a non-terminating loop.
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return _json_rpc(body["id"], result=page("tools", [{"name": "x"}], next_cursor="stuck"))

    async with make_transport(handler) as transport:
        with pytest.raises(McpPaginationError) as excinfo:
            await paginate(transport, "tools/list", "tools")

    err = excinfo.value
    assert err.method == "tools/list"
    assert "repeated" in str(err)
    # Page 1 (no cursor) plus page 2 (cursor "stuck") before the repeat is caught.
    assert err.pages == 2
    assert err.items_so_far == 2


async def test_paginate_enforces_page_limit():
    # Every page advertises a fresh, never-repeating cursor → only the cap stops it.
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        cursor = (body.get("params") or {}).get("cursor") or "0"
        nxt = str(int(cursor) + 1)
        return _json_rpc(body["id"], result=page("tools", [{"name": cursor}], next_cursor=nxt))

    async with make_transport(handler) as transport:
        with pytest.raises(McpPaginationError) as excinfo:
            await paginate(transport, "tools/list", "tools", page_limit=5)

    err = excinfo.value
    assert err.pages == 5
    assert err.items_so_far == 5
    assert "5-page" in str(err)


# ===========================================================================
# discover_listings(): declared-only gating
# ===========================================================================


async def test_discover_all_declared_capabilities():
    handler = ListHandler(
        {
            "tools/list": [page("tools", [{"name": "t1"}])],
            "resources/list": [page("resources", [{"uri": "r1"}])],
            "resources/templates/list": [page("resourceTemplates", [{"uriTemplate": "rt1"}])],
            "prompts/list": [page("prompts", [{"name": "p1"}])],
        }
    )
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, ALL_CAPABILITIES)

    assert isinstance(result, DiscoveryListings)
    assert result.tools == [{"name": "t1"}]
    assert result.resources == [{"uri": "r1"}]
    assert result.resource_templates == [{"uriTemplate": "rt1"}]
    assert result.prompts == [{"name": "p1"}]
    assert result.skipped == ()
    # All four endpoints were queried.
    assert set(handler.methods_called()) == {
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "prompts/list",
    }


async def test_discover_skips_undeclared_capabilities():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "t1"}])]})
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {"tools": {}})

    assert result.tools == [{"name": "t1"}]
    assert result.resources == []
    assert result.resource_templates == []
    assert result.prompts == []
    # The undeclared endpoints were never called, and are reported as skipped.
    assert handler.methods_called() == ["tools/list"]
    assert set(result.skipped) == {
        "resources/list",
        "resources/templates/list",
        "prompts/list",
    }


async def test_resources_capability_gates_both_resource_endpoints():
    handler = ListHandler(
        {
            "resources/list": [page("resources", [{"uri": "r1"}])],
            "resources/templates/list": [page("resourceTemplates", [{"uriTemplate": "rt1"}])],
        }
    )
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {"resources": {}})

    # The single resources capability unlocks list AND templates/list.
    assert result.resources == [{"uri": "r1"}]
    assert result.resource_templates == [{"uriTemplate": "rt1"}]
    assert set(handler.methods_called()) == {"resources/list", "resources/templates/list"}
    assert set(result.skipped) == {"tools/list", "prompts/list"}


async def test_discover_with_no_capabilities_queries_nothing():
    handler = ListHandler({})
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {})

    assert handler.methods_called() == []
    assert result == DiscoveryListings(
        skipped=(
            "tools/list",
            "resources/list",
            "resources/templates/list",
            "prompts/list",
        )
    )


async def test_null_capability_value_counts_as_undeclared():
    # An explicit null value (vs. an empty object) means the capability is absent.
    handler = ListHandler({"tools/list": [page("tools", [{"name": "t1"}])]})
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {"tools": {}, "prompts": None})

    assert result.tools == [{"name": "t1"}]
    assert "prompts/list" in result.skipped
    assert "prompts/list" not in handler.methods_called()


async def test_discover_pages_each_declared_endpoint_fully():
    handler = ListHandler(
        {
            "tools/list": [
                page("tools", [{"name": "t1"}], next_cursor="c1"),
                page("tools", [{"name": "t2"}]),
            ],
            "prompts/list": [
                page("prompts", [{"name": "p1"}], next_cursor="d1"),
                page("prompts", [{"name": "p2"}]),
            ],
        }
    )
    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {"tools": {}, "prompts": {}})

    assert result.tools == [{"name": "t1"}, {"name": "t2"}]
    assert result.prompts == [{"name": "p1"}, {"name": "p2"}]
    assert handler.cursors_for("tools/list") == [None, "c1"]
    assert handler.cursors_for("prompts/list") == [None, "d1"]


async def test_discover_propagates_pagination_guard():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return _json_rpc(body["id"], result=page("tools", [{"name": "x"}], next_cursor="stuck"))

    async with make_transport(handler) as transport:
        with pytest.raises(McpPaginationError):
            await discover_listings(transport, {"tools": {}})


def test_default_page_limit_is_sane():
    assert DEFAULT_PAGE_LIMIT >= 100


# ===========================================================================
# Time-budget enforcement
# ===========================================================================


async def test_paginate_aborts_when_budget_already_spent():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "t1"}])]})
    # init reads t=0; the first per-page check reads t=10 > 1s budget → spent.
    budget = TimeBudget(1.0, clock=FakeClock([0.0, 10.0]))

    async with make_transport(handler) as transport:
        with pytest.raises(BudgetExceededError):
            await paginate(transport, "tools/list", "tools", budget=budget)

    # The guard tripped before any request left the client.
    assert handler.methods_called() == []


async def test_discover_listings_aborts_when_budget_spent():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "t1"}])]})
    budget = TimeBudget(1.0, clock=FakeClock([0.0, 10.0]))

    async with make_transport(handler) as transport:
        with pytest.raises(BudgetExceededError):
            await discover_listings(transport, {"tools": {}}, budget=budget)

    assert handler.methods_called() == []


async def test_discover_listings_completes_within_generous_budget():
    handler = ListHandler(
        {
            "tools/list": [page("tools", [{"name": "t1"}], next_cursor="c1"), page("tools", [{"name": "t2"}])],
        }
    )
    # A clock that never advances: the budget is never spent.
    budget = TimeBudget(60.0, clock=FakeClock([0.0]))

    async with make_transport(handler) as transport:
        result = await discover_listings(transport, {"tools": {}}, budget=budget)

    assert result.tools == [{"name": "t1"}, {"name": "t2"}]


async def test_paginate_without_budget_is_unaffected():
    handler = ListHandler({"tools/list": [page("tools", [{"name": "t1"}])]})
    async with make_transport(handler) as transport:
        items = await paginate(transport, "tools/list", "tools", budget=None)
    assert items == [{"name": "t1"}]
