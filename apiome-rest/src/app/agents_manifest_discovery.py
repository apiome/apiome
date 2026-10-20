"""Live site-manifest discovery — MFI-18.3 (#3976).

A site publishes its agentic-web manifest at a fixed path under its origin: ``/agents.json``
(the agents.txt companion), ``/.well-known/agent.json`` (Agent Web Protocol), ``/agents.txt`` and
``/llms.txt``. Given a site URL this module tries them in that order through the shared bounded,
SSRF-guarded descriptor fetch (:mod:`app.agent_descriptor_fetch`) and returns the first body that
parses as a manifest.

Unlike A2A / ACP discovery, a body that is served but is *not* a manifest moves on to the next
path: ``/.well-known/agent.json`` is also the legacy A2A Agent Card path, and many sites answer
every unknown path with their HTML app shell. Only a ``FORMAT_MISMATCH`` falls through — a
manifest that is malformed or truncated is reported, not skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlunsplit

import httpx

from .agent_descriptor_fetch import (
    AgentDiscoveryError,
    FetchedDescriptor,
    fetch_first_descriptor,
    split_http_url,
)
from .agents_manifest_parser import (
    AgentsManifest,
    AgentsManifestParseError,
    parse_agents_manifest,
)
from .ssrf_guard import build_guarded_client

__all__ = ["WELL_KNOWN_MANIFEST_PATHS", "DiscoveredManifest", "fetch_site_manifest", "site_manifest_urls"]

#: The paths tried under a site's origin, most structured first.
WELL_KNOWN_MANIFEST_PATHS = ("/agents.json", "/.well-known/agent.json", "/agents.txt", "/llms.txt")

_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


@dataclass(frozen=True)
class DiscoveredManifest:
    """A manifest fetched and parsed from a live site.

    Attributes:
        url: The URL the manifest was served from.
        manifest: The parsed manifest (its ``source_label`` is ``url``).
    """

    url: str
    manifest: AgentsManifest


def site_manifest_urls(site_url: str) -> List[str]:
    """Return the URLs to try, in order, for a site at ``site_url``.

    A URL whose last path segment names a file (``…/agents.json``, ``…/docs/llms.txt``) is taken
    as the manifest itself and returned alone. Otherwise the site's **origin** is used and every
    path of :data:`WELL_KNOWN_MANIFEST_PATHS` is returned.

    Args:
        site_url: A site origin (``https://example.com``) or a direct manifest URL.

    Returns:
        One or four absolute URLs.

    Raises:
        app.agent_descriptor_fetch.AgentDiscoveryError: When ``site_url`` is not an http(s) URL
            with a host.
    """
    parts = split_http_url(site_url, what="Site URL")
    last = parts.path.rstrip("/").rsplit("/", 1)[-1]
    if "." in last:
        return [urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, "", ""))]
    scheme = parts.scheme.lower()
    return [urlunsplit((scheme, parts.netloc, path, "", "")) for path in WELL_KNOWN_MANIFEST_PATHS]


def fetch_site_manifest(
    site_url: str, *, client: Optional[httpx.Client] = None
) -> DiscoveredManifest:
    """Fetch and parse a site's manifest from the first well-known path that serves one.

    Args:
        site_url: See :func:`site_manifest_urls`.
        client: Optional httpx client (tests); a guarded client is built and closed otherwise.

    Returns:
        The parsed manifest and the URL it came from.

    Raises:
        app.agent_descriptor_fetch.AgentDiscoveryError: On SSRF rejection, network failure, an
            oversized body, an HTTP error, or when no path serves a manifest.
        app.agents_manifest_parser.AgentsManifestParseError: When a path serves a manifest that
            is malformed, truncated or empty of declarations.
    """
    candidates = site_manifest_urls(site_url)
    owns_client = client is None
    http = client or build_guarded_client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        for url in candidates:
            fetched = _fetch_one(http, url)
            if fetched is None:
                continue
            try:
                manifest = parse_agents_manifest(fetched.text, source_label=fetched.url)
            except AgentsManifestParseError as exc:
                if exc.code == "FORMAT_MISMATCH" and len(candidates) > 1:
                    continue
                raise
            return DiscoveredManifest(url=fetched.url, manifest=manifest)
    finally:
        if owns_client:
            http.close()
    raise AgentDiscoveryError("No site manifest found; tried " + ", ".join(candidates))


def _fetch_one(http: httpx.Client, url: str) -> Optional[FetchedDescriptor]:
    """Fetch one candidate, or ``None`` when the site has nothing there (404 / 410).

    Args:
        http: The client to use.
        url: The candidate URL.

    Returns:
        The descriptor, or ``None``.

    Raises:
        app.agent_descriptor_fetch.AgentDiscoveryError: For any failure other than "not found".
    """
    try:
        return fetch_first_descriptor([url], label="site manifest", client=http)
    except AgentDiscoveryError as exc:
        if str(exc).startswith("No site manifest found"):
            return None
        raise
