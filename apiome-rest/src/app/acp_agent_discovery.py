"""Live ACP agent discovery — MFI-18.2 (#3975).

An ACP server lists the agents it hosts at ``GET /agents`` and describes one at
``GET /agents/{name}``, under whatever path prefix the server is mounted at. Given a server URL
this module resolves the listing URL and fetches it through the shared bounded, SSRF-guarded
descriptor fetch (:mod:`app.agent_descriptor_fetch`), so discovery cannot be aimed at an internal
address or a metadata endpoint, even through a redirect.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlunsplit

import httpx

from .agent_descriptor_fetch import FetchedDescriptor, fetch_first_descriptor, split_http_url

__all__ = ["acp_agents_urls", "fetch_acp_agents"]


def acp_agents_urls(base_url: str) -> List[str]:
    """Return the URL to fetch for an ACP server at ``base_url``.

    Args:
        base_url: The server's base URL (``https://acp.example.com`` or a mounted prefix such as
            ``https://example.com/acp``), its ``…/agents`` listing, or one agent's
            ``…/agents/<name>`` URL.

    Returns:
        A one-element list: ``base_url`` itself when it already names a listing or an agent,
        else ``<base_url>/agents`` (query and fragment dropped).

    Raises:
        app.agent_descriptor_fetch.AgentDiscoveryError: When ``base_url`` is not an http(s) URL
            with a host.
    """
    parts = split_http_url(base_url, what="ACP server URL")
    path = parts.path.rstrip("/")
    segments = path.split("/")
    if segments[-1] == "agents" or (len(segments) >= 2 and segments[-2] == "agents"):
        return [urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))]
    return [urlunsplit((parts.scheme.lower(), parts.netloc, f"{path}/agents", "", ""))]


def fetch_acp_agents(base_url: str, *, client: Optional[httpx.Client] = None) -> FetchedDescriptor:
    """Fetch an ACP server's agent listing (or one agent's manifest).

    Args:
        base_url: See :func:`acp_agents_urls`.
        client: Optional httpx client (tests); a guarded client is built and closed otherwise.

    Returns:
        The body and the URL it was served from.

    Raises:
        app.agent_descriptor_fetch.AgentDiscoveryError: On SSRF rejection, network failure, an
            oversized body, an HTTP error, or a 404.
    """
    return fetch_first_descriptor(
        acp_agents_urls(base_url), label="ACP agent manifest", client=client
    )
