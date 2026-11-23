"""Orderings and ceilings of the MCP catalog's list reads (DBP-1.13, #7196).

Each :class:`~app.keyset_lists.ListOrder` spells the ``ORDER BY`` of one accessor in
:mod:`app.database`; the routes in :mod:`app.mcp_catalog_routes` parse and issue cursors with the
same object, so the two cannot drift apart.
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn, by_name, newest_first

__all__ = [
    "MCP_DISCOVERY_JOBS_ORDER",
    "MCP_ENDPOINTS_BY_NAME",
    "MCP_ENDPOINTS_NEWEST",
    "MCP_ENDPOINT_SOURCES_ORDER",
    "MCP_ENDPOINT_VERSIONS_ORDER",
    "MCP_REPORT_SCAN_CAP",
]

#: The private browse view: endpoints by name (``browse_mcp_endpoints``).
MCP_ENDPOINTS_BY_NAME = by_name("mcp-browse", "e.name", "e.id")

#: The endpoint list, newest first (``list_mcp_endpoints``).
MCP_ENDPOINTS_NEWEST = newest_first(
    "mcp-endpoints", "mcp_endpoints.created_at", "mcp_endpoints.id"
)

#: One endpoint's discovery jobs, newest first (``list_mcp_discovery_jobs``).
MCP_DISCOVERY_JOBS_ORDER = newest_first("mcp-discovery-jobs")

#: One endpoint's snapshots, highest sequence first (``list_mcp_endpoint_versions``).
MCP_ENDPOINT_VERSIONS_ORDER = ListOrder(
    "mcp-endpoint-versions",
    (
        SortColumn("v.version_seq", "int", ("version_seq",), descending=True),
        SortColumn("v.id", "uuid", ("id",), descending=True),
    ),
)

#: One endpoint's linked sources, newest first (``list_mcp_endpoint_sources``).
MCP_ENDPOINT_SOURCES_ORDER = newest_first("mcp-endpoint-sources")

#: The most endpoints a whole-catalog report (duplicates, freshness) reads. The reports are
#: computed in memory over every endpoint, so the scan needs a ceiling.
MCP_REPORT_SCAN_CAP = 5000
