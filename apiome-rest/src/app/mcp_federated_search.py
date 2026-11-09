"""Federated MCP catalog search: the caller's catalog plus an MCP registry — V2-MCP-26.4 / MCAT-12.4 (#3710).

``GET /v1/mcp/{tenant_slug}/search?include_registry=true`` searches the caller's own catalog as
always and, on the first page, also asks an MCP registry (``APIOME_MCP_REGISTRY_SEARCH_URL``, the
official registry by default) for servers whose names match the query. This module does the
registry half:

1. **Search the registry** — :func:`search_registry_servers` reads one ``GET /v0.1/servers?search=…``
   page (latest versions; ``deleted`` entries left out) through the SSRF-guarded
   :class:`app.mcp_registry_client.McpRegistryClient`.
2. **Dedupe against tenant-owned endpoints** — :func:`federate` drops every registry entry the
   caller already has: an endpoint whose ``registry_metadata.serverName`` is the entry's name
   (case-insensitive — names are reverse-DNS), or whose URL is one of the entry's remotes
   (:func:`url_key`: scheme, host, port and path; userinfo, query, fragment and a trailing ``/``
   ignored). The matching local hits are labeled with the registry name instead.
3. **Label** — what is left becomes :class:`app.models.McpRegistrySearchHit` rows
   (``source = "registry"``); local hits keep ``source = "local"``.

The registry can be slow or down; the route catches :class:`McpRegistryClientError` and reports it
as ``registry_error`` while still returning the local hits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

import httpx

from .mcp_registry import remote_url
from .mcp_registry_client import McpRegistryClient, RegistryServer, normalize_registry_base
from .mcp_registry_connector_source import select_remote
from .models import McpRegistrySearchHit, McpSearchHit, mcp_endpoint_host

__all__ = [
    "REGISTRY_SEARCH_MAX",
    "FederatedRegistryResult",
    "federate",
    "label_local_hits",
    "registry_hit_from_server",
    "registry_query",
    "remote_url_keys",
    "search_registry_servers",
    "url_key",
]

#: Most registry entries a federated search asks for (the registry's page maximum).
REGISTRY_SEARCH_MAX = 100

#: Websearch-syntax characters the registry's plain substring ``search`` would take literally.
_WEBSEARCH_SYNTAX = str.maketrans({'"': " ", "(": " ", ")": " "})


def registry_query(query: str) -> str:
    """Turn a catalog query (websearch syntax) into the registry's substring ``search`` value.

    Quotes and parentheses are dropped, ``-excluded`` words and ``OR`` are left out, and runs of
    spaces collapse, so ``"weather" -beta`` searches the registry for ``weather``.

    Args:
        query: The catalog search query, already stripped.

    Returns:
        The registry search term, or ``""`` when nothing searchable is left.
    """
    words = query.translate(_WEBSEARCH_SYNTAX).split()
    kept = [w for w in words if w != "OR" and not w.startswith("-")]
    return " ".join(kept)


def url_key(url: Optional[str]) -> Optional[str]:
    """A comparable form of an MCP server URL, for deduping a registry remote against an endpoint.

    Args:
        url: A registry remote URL or a stored ``mcp_endpoints.endpoint_url`` (may carry userinfo).

    Returns:
        ``scheme://host[:port]/path`` with the scheme and host in lower case (as
        :func:`app.mcp_registry.remote_url` gives them) and a trailing ``/`` removed, or ``None``
        when the URL is not an ``http(s)`` URL with a host.
    """
    cleaned = remote_url(url)
    if cleaned is None:
        return None
    return cleaned.rstrip("/") or cleaned


def remote_url_keys(server: Mapping[str, Any]) -> List[str]:
    """The :func:`url_key` of every remote an entry declares (any remote type, templated ones skipped).

    Args:
        server: The normalized ``server.json``.

    Returns:
        The distinct keys, in declaration order.
    """
    keys: List[str] = []
    for remote in server.get("remotes") or []:
        if not isinstance(remote, Mapping):
            continue
        raw = str(remote.get("url") or "").strip()
        if not raw or "{" in raw or "}" in raw:
            continue
        key = url_key(raw)
        if key and key not in keys:
            keys.append(key)
    return keys


def search_registry_servers(
    query: str,
    *,
    base_url: str,
    limit: int,
    timeout: float,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[RegistryServer]:
    """Ask one MCP registry for the latest versions of the servers whose names match ``query``.

    Args:
        query: The registry search term (:func:`registry_query`); blank returns no entries
            without calling the registry.
        base_url: The registry root.
        limit: Entries to ask for (capped at :data:`REGISTRY_SEARCH_MAX`).
        timeout: Seconds for the request.
        transport: An httpx transport for the guarded client (tests serve a fake registry).

    Returns:
        The entries in the registry's order (``deleted`` and nameless ones left out).

    Raises:
        app.mcp_registry_client.McpRegistryClientError: The registry refused, timed out or
            answered with something that is not a v0.1 ``ServerList``.
    """
    term = query.strip()
    if not term:
        return []
    with McpRegistryClient(base_url, timeout=timeout, transport=transport) as client:
        page = client.list_servers_page(search=term, limit=max(1, min(limit, REGISTRY_SEARCH_MAX)))
    return page.servers


def registry_hit_from_server(server: RegistryServer, *, registry_url: str) -> McpRegistrySearchHit:
    """Project a registry entry onto the :class:`app.models.McpRegistrySearchHit` wire model.

    Args:
        server: The registry entry.
        registry_url: The registry it came from.

    Returns:
        The hit. Its remote is the one Apiome would import (:func:`select_remote`), credential-free;
        a package-only or templated entry has no ``remote_url`` / ``transport``.
    """
    doc = server.server
    picked = select_remote(doc)
    transport, url = picked if isinstance(picked, tuple) else (None, None)
    clean_url = remote_url(url) if url else None

    def _text(key: str) -> Optional[str]:
        value = doc.get(key)
        return value.strip() or None if isinstance(value, str) else None

    return McpRegistrySearchHit(
        server_name=server.name,
        title=_text("title"),
        description=_text("description"),
        version=server.version or None,
        status=server.status or None,
        website_url=remote_url(_text("websiteUrl")),
        remote_url=clean_url,
        transport=transport,
        host=mcp_endpoint_host(clean_url) if clean_url else "",
        registry_url=normalize_registry_base(registry_url),
    )


@dataclass
class FederatedRegistryResult:
    """The registry half of a federated search, deduped against the caller's endpoints.

    Attributes:
        hits: Registry entries the caller does not already have, in the registry's order.
        duplicates: How many registry entries were dropped as already owned.
        server_name_by_endpoint: Endpoint id → registry server name, for labeling local hits.
    """

    hits: List[McpRegistrySearchHit] = field(default_factory=list)
    duplicates: int = 0
    server_name_by_endpoint: Dict[str, str] = field(default_factory=dict)


def federate(
    servers: Iterable[RegistryServer],
    owned: Iterable[Mapping[str, Any]],
    *,
    registry_url: str,
) -> FederatedRegistryResult:
    """Dedupe registry entries against the caller's endpoints and label both sides.

    Args:
        servers: The registry entries the search found.
        owned: The caller's live endpoints that may match (rows with ``id``, ``endpoint_url``,
            ``added_via`` and ``registry_server_name``), from
            :meth:`app.database.Database.find_mcp_endpoints_for_registry_dedupe`.
        registry_url: The registry searched.

    Returns:
        The result. An entry is a duplicate when an owned endpoint carries its server name
        (case-insensitive) or one of its remote URLs (:func:`url_key`); the endpoint is then
        labeled with that name. A registry-imported endpoint is labeled with its own recorded
        name even when the search did not return its entry.
    """
    result = FederatedRegistryResult()
    by_name: Dict[str, str] = {}
    by_url: Dict[str, str] = {}
    for row in owned:
        endpoint_id = str(row["id"])
        name = str(row.get("registry_server_name") or "").strip()
        if name:
            by_name.setdefault(name.lower(), endpoint_id)
            if row.get("added_via") == "registry":
                result.server_name_by_endpoint[endpoint_id] = name
        key = url_key(row.get("endpoint_url"))
        if key:
            by_url.setdefault(key, endpoint_id)

    for server in servers:
        endpoint_id = by_name.get(server.name.lower())
        if endpoint_id is None:
            endpoint_id = next((by_url[k] for k in remote_url_keys(server.server) if k in by_url), None)
        if endpoint_id is not None:
            result.duplicates += 1
            result.server_name_by_endpoint.setdefault(endpoint_id, server.name)
            continue
        result.hits.append(registry_hit_from_server(server, registry_url=registry_url))
    return result


def label_local_hits(hits: List[McpSearchHit], server_name_by_endpoint: Mapping[str, str]) -> None:
    """Set ``registry_server_name`` on each local hit whose endpoint is known to a registry.

    Args:
        hits: The local hits (changed in place).
        server_name_by_endpoint: Endpoint id → registry server name (:class:`FederatedRegistryResult`).
    """
    for hit in hits:
        name = server_name_by_endpoint.get(hit.endpoint_id)
        if name:
            hit.registry_server_name = name
