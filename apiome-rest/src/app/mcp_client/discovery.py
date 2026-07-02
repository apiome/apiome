"""MCP discovery list methods + cursor pagination (V2-MCP-16.3, #3659).

This is the capability-enumeration layer that sits on top of the lifecycle
handshake (:mod:`app.mcp_client.handshake`, 2.2). Once ``initialize`` has agreed a
protocol version and reported which capabilities the server *declares*, this
module walks the corresponding list endpoints to retrieve the **full** capability
surface — not just the first page:

* ``tools/list``                → items under result key ``tools``
* ``resources/list``            → items under result key ``resources``
* ``resources/templates/list``  → items under result key ``resourceTemplates``
* ``prompts/list``              → items under result key ``prompts``

Two rules from the spec shape the behavior:

1. **Declared-only.** A list endpoint is queried **only** when the server declared
   the owning capability in its ``initialize`` result. ``tools`` gates
   ``tools/list``; ``prompts`` gates ``prompts/list``; ``resources`` gates *both*
   ``resources/list`` and ``resources/templates/list`` (resource templates live
   under the ``resources`` capability — there is no separate one). Undeclared
   capabilities are skipped entirely and recorded in
   :attr:`DiscoveryListings.skipped`.
2. **Opaque cursor pagination.** Each endpoint returns a page of items plus an
   optional opaque ``nextCursor``; the client re-requests with
   ``params.cursor = nextCursor`` until the field is absent, accumulating every
   page. See the MCP
   `pagination <https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/pagination>`_
   utility.

Because the cursor is opaque and server-supplied, a buggy or hostile server could
return a page forever (a constant or cycling cursor, or simply never omitting
``nextCursor``). The pagination loop is therefore guarded twice: it refuses a
``nextCursor`` it has already seen (a cycle), and it caps the total number of
pages at :data:`DEFAULT_PAGE_LIMIT`. Either trip raises :class:`McpPaginationError`
so a misbehaving endpoint fails loudly rather than hanging the discovery job.

This layer deliberately returns each item as its **raw** JSON object (a ``dict``),
unmodified; turning those into a canonical, version-tolerant surface model is the
next work item (MCAT-2.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .resilience import TimeBudget
from .transport_http import McpProtocolError, StreamableHttpTransport

# Hard cap on pages fetched from a single list endpoint before the loop gives up.
# A well-behaved server terminates by omitting ``nextCursor`` long before this; the
# cap (combined with cycle detection) only exists to bound a non-terminating one.
DEFAULT_PAGE_LIMIT = 1000


# ===========================================================================
# Errors
# ===========================================================================


class McpDiscoveryError(McpProtocolError):
    """A list endpoint failed in a way that aborts discovery of that capability.

    Raised when a ``*/list`` request returns a JSON-RPC error even though the
    owning capability was declared (the server contradicted its own
    ``initialize`` reply).

    Attributes:
        method: The JSON-RPC list method that failed (e.g. ``"tools/list"``).
        code: The JSON-RPC error code returned by the server.
        data: The optional ``data`` member of the JSON-RPC error.
    """

    def __init__(self, method: str, code: int, message: str, data: Any = None) -> None:
        self.method = method
        self.code = code
        self.data = data
        super().__init__(f"{method} failed: JSON-RPC error {code}: {message}")


class McpPaginationError(McpDiscoveryError):
    """A list endpoint's cursor loop could not be proven to terminate.

    Raised when a server returns a ``nextCursor`` that was already seen (a cycle)
    or keeps paging past :data:`DEFAULT_PAGE_LIMIT`. Carries the partial item
    count gathered before the loop was aborted.

    Attributes:
        method: The list method whose pagination misbehaved.
        pages: How many pages had been fetched when the guard tripped.
        items_so_far: Number of items accumulated before aborting.
    """

    def __init__(self, method: str, message: str, *, pages: int, items_so_far: int) -> None:
        self.pages = pages
        self.items_so_far = items_so_far
        # code 0 / synthetic: this is a client-side guard, not a server error code.
        super().__init__(method, 0, message)


# ===========================================================================
# List-method registry
# ===========================================================================


@dataclass(frozen=True)
class ListMethod:
    """Static description of one paginated discovery endpoint.

    Attributes:
        method: The JSON-RPC method name (e.g. ``"tools/list"``).
        items_key: The result key the item array lives under (e.g. ``"tools"``;
            note ``resources/templates/list`` uses ``"resourceTemplates"``).
        capability: The ``initialize`` capabilities key that must be declared for
            this endpoint to be queried (resource *templates* share ``resources``).
    """

    method: str
    items_key: str
    capability: str


# Every paginated list endpoint, in a deterministic discovery order. Both resource
# endpoints are gated by the single ``resources`` capability.
LIST_METHODS: Tuple[ListMethod, ...] = (
    ListMethod("tools/list", "tools", "tools"),
    ListMethod("resources/list", "resources", "resources"),
    ListMethod("resources/templates/list", "resourceTemplates", "resources"),
    ListMethod("prompts/list", "prompts", "prompts"),
)


# ===========================================================================
# Result value object
# ===========================================================================


@dataclass(frozen=True)
class DiscoveryListings:
    """The complete, fully-paged capability surface enumerated from a server.

    Each list is the concatenation of every page returned by its endpoint, with
    items left as raw JSON objects (normalization is MCAT-2.4). A list is empty
    both when the endpoint genuinely returned nothing *and* when the capability
    was undeclared — :attr:`skipped` disambiguates the latter.

    Attributes:
        tools: Raw items from ``tools/list`` (empty if ``tools`` undeclared).
        resources: Raw items from ``resources/list`` (empty if ``resources``
            undeclared).
        resource_templates: Raw items from ``resources/templates/list`` (empty if
            ``resources`` undeclared).
        prompts: Raw items from ``prompts/list`` (empty if ``prompts`` undeclared).
        skipped: The list *methods* not queried because their capability was not
            declared by the server.
    """

    tools: List[Dict[str, Any]] = field(default_factory=list)
    resources: List[Dict[str, Any]] = field(default_factory=list)
    resource_templates: List[Dict[str, Any]] = field(default_factory=list)
    prompts: List[Dict[str, Any]] = field(default_factory=list)
    skipped: Tuple[str, ...] = ()


# ===========================================================================
# Discovery
# ===========================================================================


async def discover_listings(
    transport: StreamableHttpTransport,
    capabilities: Mapping[str, Any],
    *,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    budget: Optional[TimeBudget] = None,
) -> DiscoveryListings:
    """Enumerate every declared capability list, fully paged, over ``transport``.

    For each endpoint in :data:`LIST_METHODS`, queries it only when its owning
    capability is present in ``capabilities`` (the server's ``initialize`` reply),
    pages through all results via :func:`paginate`, and collects the raw items.
    Undeclared endpoints are skipped and reported in
    :attr:`DiscoveryListings.skipped`.

    The handshake must already be complete (so the transport pins the negotiated
    ``MCP-Protocol-Version``); pass the same ``capabilities`` returned on the
    :class:`~app.mcp_client.handshake.InitializeResult`.

    Args:
        transport: An initialized Streamable HTTP transport.
        capabilities: The server's declared capabilities object from ``initialize``.
        page_limit: Max pages fetched per endpoint before
            :class:`McpPaginationError`; defaults to :data:`DEFAULT_PAGE_LIMIT`.
        budget: Optional :class:`~app.mcp_client.resilience.TimeBudget` bounding
            the whole enumeration; checked before each endpoint and between pages
            so a slow server cannot exceed the job's total wall-clock budget.

    Returns:
        A :class:`DiscoveryListings` with one raw-item list per endpoint plus the
        set of endpoints skipped as undeclared.

    Raises:
        McpDiscoveryError: a declared endpoint returned a JSON-RPC error.
        McpPaginationError: an endpoint's cursor loop cycled or exceeded
            ``page_limit``.
        BudgetExceededError: the total time budget was exhausted mid-enumeration.
        McpTransportError: any underlying transport/protocol failure.
    """
    collected: Dict[str, List[Dict[str, Any]]] = {}
    skipped: List[str] = []

    for spec in LIST_METHODS:
        if budget is not None:
            budget.check()
        if not _is_declared(capabilities, spec.capability):
            skipped.append(spec.method)
            continue
        collected[spec.method] = await paginate(
            transport, spec.method, spec.items_key, page_limit=page_limit, budget=budget
        )

    return DiscoveryListings(
        tools=collected.get("tools/list", []),
        resources=collected.get("resources/list", []),
        resource_templates=collected.get("resources/templates/list", []),
        prompts=collected.get("prompts/list", []),
        skipped=tuple(skipped),
    )


async def paginate(
    transport: StreamableHttpTransport,
    method: str,
    items_key: str,
    *,
    params: Optional[Mapping[str, Any]] = None,
    page_limit: int = DEFAULT_PAGE_LIMIT,
    budget: Optional[TimeBudget] = None,
) -> List[Dict[str, Any]]:
    """Fetch and concatenate every page of a cursor-paginated list method.

    Sends ``method`` with no ``cursor`` first, appends the items under
    ``items_key``, and — while the result carries a non-empty string
    ``nextCursor`` — re-requests with ``params.cursor`` set to it until the field
    is absent. Any ``params`` given are sent on every page (the cursor is merged
    in alongside them).

    The loop is guarded against a non-terminating server two ways: a
    ``nextCursor`` already seen on an earlier page (a cycle) and exceeding
    ``page_limit`` total pages both raise :class:`McpPaginationError`.

    Args:
        transport: An initialized Streamable HTTP transport.
        method: The JSON-RPC list method (e.g. ``"tools/list"``).
        items_key: The result key holding the page's item array (e.g. ``"tools"``).
        params: Extra params merged into every page request (cursor excluded).
        page_limit: Max pages before aborting; defaults to :data:`DEFAULT_PAGE_LIMIT`.
        budget: Optional :class:`~app.mcp_client.resilience.TimeBudget`; checked
            before each page so a slow-drip server cannot run past the job's total
            wall-clock budget even while every individual request stays under the
            per-call timeout.

    Returns:
        The raw items from every page, in server order.

    Raises:
        McpDiscoveryError: the server returned a JSON-RPC error for the method.
        McpPaginationError: the cursor cycled or ``page_limit`` was exceeded.
        BudgetExceededError: the total time budget was exhausted mid-pagination.
    """
    items: List[Dict[str, Any]] = []
    seen_cursors: set[str] = set()
    cursor: Optional[str] = None
    base_params = dict(params) if params else {}

    for page in range(1, page_limit + 1):
        if budget is not None:
            budget.check()
        request_params = dict(base_params)
        if cursor is not None:
            request_params["cursor"] = cursor

        response = await transport.request(method, request_params or None)
        if response.is_error:
            error = response.error
            assert error is not None  # is_error guarantees this
            raise McpDiscoveryError(method, error.code, error.message, error.data)

        result = response.result if isinstance(response.result, Mapping) else {}
        items.extend(_extract_items(result, items_key))

        next_cursor = _next_cursor(result)
        if next_cursor is None:
            return items  # server omitted nextCursor → last page reached.
        if next_cursor in seen_cursors:
            raise McpPaginationError(
                method,
                f"{method} returned a repeated pagination cursor {next_cursor!r} "
                f"after {page} page(s); aborting to avoid a non-terminating loop",
                pages=page,
                items_so_far=len(items),
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    # Fell out of the loop without an omitted nextCursor: too many pages.
    raise McpPaginationError(
        method,
        f"{method} exceeded the {page_limit}-page pagination limit; "
        "aborting a possibly non-terminating server",
        pages=page_limit,
        items_so_far=len(items),
    )


# ===========================================================================
# Helpers
# ===========================================================================


def _is_declared(capabilities: Mapping[str, Any], key: str) -> bool:
    """True when the server declared capability ``key`` in its ``initialize`` reply.

    A capability counts as declared when its key is present with a non-``None``
    value (typically an object, possibly empty ``{}``). An absent key, or one
    explicitly set to ``null``, means the capability is unavailable.
    """
    if not isinstance(capabilities, Mapping):
        return False
    return key in capabilities and capabilities[key] is not None


def _extract_items(result: Mapping[str, Any], items_key: str) -> List[Dict[str, Any]]:
    """Return the list of item objects under ``items_key`` (``[]`` if absent/malformed).

    Non-object entries inside the array are dropped defensively; the spec requires
    each item to be a JSON object.
    """
    raw = result.get(items_key)
    if not isinstance(raw, (list, tuple)):
        return []
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _next_cursor(result: Mapping[str, Any]) -> Optional[str]:
    """Return the next opaque cursor, or ``None`` when this is the final page.

    Per the pagination spec a missing ``nextCursor`` means the end of results. A
    present-but-empty or non-string ``nextCursor`` is treated as the end too, so a
    server cannot trap the loop with a falsy cursor.
    """
    next_cursor = result.get("nextCursor")
    if isinstance(next_cursor, str) and next_cursor != "":
        return next_cursor
    return None
