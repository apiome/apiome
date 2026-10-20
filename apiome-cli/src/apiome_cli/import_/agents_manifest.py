"""Site-manifest discovery for ``apiome import agents-manifest --discover`` (MFI-18.3, #3976).

A site publishes its agentic-web manifest at a well-known path under its origin. This module
turns a site URL into the manifest URL to import by trying ``/agents.json``,
``/.well-known/agent.json``, ``/agents.txt`` and ``/llms.txt`` in that order. The resolved URL
is then imported through the ordinary registry-dispatch import, so the server parses,
normalizes, versions and lints the manifest exactly as it would a ``--url`` import.

The rules mirror the REST adapter's live discovery (``app.agents_manifest_discovery``): a URL
whose last path segment names a file is the manifest itself, and a ``404`` / ``410`` moves on to
the next path. Two served bodies also move on, because they are not manifests: an HTML page (a
site that answers every path with its app shell) and, at ``/.well-known/agent.json``, a JSON
document without ``awp_version`` (an A2A Agent Card shares that legacy path).
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

import httpx

#: The paths tried under a site's origin, most structured first.
WELL_KNOWN_MANIFEST_PATHS = (
    "/agents.json",
    "/.well-known/agent.json",
    "/agents.txt",
    "/llms.txt",
)

#: The well-known path AWP shares with the legacy A2A Agent Card.
_SHARED_AGENT_JSON_PATH = "/.well-known/agent.json"

_NOT_FOUND_STATUSES = frozenset({404, 410})


def site_manifest_urls(site_url: str) -> list[str]:
    """Return the manifest URLs to try, in order, for a site at ``site_url``.

    Args:
        site_url: The site's origin (``https://example.com``) or a direct manifest URL.

    Returns:
        ``[site_url]`` (query and fragment dropped) when its last path segment names a file;
        otherwise the origin's four well-known manifest URLs (any path is dropped).

    Raises:
        ValueError: When ``site_url`` is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (site_url or "").strip()
    if not cleaned:
        raise ValueError("Site URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Site URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("Site URL has no host")
    scheme = parts.scheme.lower()
    if "." in parts.path.rstrip("/").rsplit("/", 1)[-1]:
        return [urlunsplit((scheme, parts.netloc, parts.path, "", ""))]
    return [
        urlunsplit((scheme, parts.netloc, path, "", ""))
        for path in WELL_KNOWN_MANIFEST_PATHS
    ]


def looks_like_manifest(url: str, body: str) -> bool:
    """Whether a served body can be a site manifest (a cheap pre-check; the server parses it).

    Args:
        url: The URL the body came from.
        body: The response text.

    Returns:
        ``False`` for an empty body, an HTML page, or — at ``/.well-known/agent.json`` — JSON
        without ``awp_version``; ``True`` otherwise.
    """
    text = body.lstrip("﻿").lstrip()
    if not text or text.startswith("<"):
        return False
    if urlsplit(url).path.rstrip("/").endswith(_SHARED_AGENT_JSON_PATH):
        try:
            document = json.loads(text)
        except ValueError:
            return False
        return isinstance(document, dict) and "awp_version" in document
    return True


def discover_site_manifest_url(
    site_url: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
    client: httpx.Client | None = None,
) -> str:
    """Find the URL a site serves its agentic-web manifest from.

    Args:
        site_url: The site's origin or a direct manifest URL.
        timeout: HTTP timeout per request, in seconds.
        verify: Whether to verify TLS certificates.
        client: Optional httpx client (tests); one is created and closed otherwise.

    Returns:
        The first candidate URL that serves something that can be a manifest.

    Raises:
        ValueError: When ``site_url`` is unusable.
        OSError: On a network failure, a non-404 HTTP error, or when no candidate serves a
            manifest.
    """
    candidates = site_manifest_urls(site_url)
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout, verify=verify, follow_redirects=True)
    try:
        for url in candidates:
            try:
                response = http.get(url)
            except httpx.RequestError as exc:
                raise OSError(f"Failed to fetch {url!r}: {exc}") from exc
            if response.status_code in _NOT_FOUND_STATUSES:
                continue
            if response.status_code >= 400:
                raise OSError(f"Failed to fetch {url!r}: HTTP {response.status_code}")
            if len(candidates) > 1 and not looks_like_manifest(url, response.text):
                continue
            return url
    finally:
        if owns_client:
            http.close()
    raise OSError("No site manifest found; tried " + ", ".join(candidates))
