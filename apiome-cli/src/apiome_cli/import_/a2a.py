"""A2A Agent Card discovery for ``apiome import a2a --discover`` (MFI-18.1, #3974).

An A2A agent publishes its Agent Card at a well-known URI under its origin:
``/.well-known/agent-card.json`` (A2A 0.3+) or, on older agents, ``/.well-known/agent.json``.
This module turns an agent's base URL into the card URL to import by trying those paths in
order. The resolved URL is then imported through the ordinary registry-dispatch import, so the
server parses, normalizes, versions and lints the card exactly as it would a ``--url`` import.

The rules mirror the REST adapter's live discovery (``app.a2a_agent_card_discovery``): a URL
whose path already ends in ``.json`` is the card itself; only ``404`` / ``410`` falls through to
the legacy path, because any other failure says nothing about whether the legacy path exists.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

#: The well-known card path since A2A 0.3.
WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent-card.json"

#: The well-known card path before A2A 0.3.
LEGACY_WELL_KNOWN_AGENT_CARD_PATH = "/.well-known/agent.json"

_NOT_FOUND_STATUSES = frozenset({404, 410})


def well_known_agent_card_urls(base_url: str) -> list[str]:
    """Return the card URLs to try, in order, for an agent at ``base_url``.

    Args:
        base_url: The agent's origin (``https://agent.example.com``) or a direct card URL.

    Returns:
        ``[base_url]`` when its path already ends in ``.json``; otherwise the origin's current
        then legacy well-known card URLs (any path on ``base_url`` is dropped, since a
        well-known URI is always rooted at the origin).

    Raises:
        ValueError: When ``base_url`` is empty, not ``http``/``https``, or has no host.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        raise ValueError("Agent URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Agent URL must be an http or https URL")
    if not parts.netloc:
        raise ValueError("Agent URL has no host")
    if parts.path.lower().endswith(".json"):
        return [cleaned]
    scheme = parts.scheme.lower()
    return [
        urlunsplit((scheme, parts.netloc, path, "", ""))
        for path in (WELL_KNOWN_AGENT_CARD_PATH, LEGACY_WELL_KNOWN_AGENT_CARD_PATH)
    ]


def discover_agent_card_url(
    base_url: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
    client: httpx.Client | None = None,
) -> str:
    """Find the URL an agent serves its Agent Card from.

    Args:
        base_url: The agent's origin or a direct card URL.
        timeout: HTTP timeout per request, in seconds.
        verify: Whether to verify TLS certificates.
        client: Optional httpx client (tests); one is created and closed otherwise.

    Returns:
        The first candidate URL that answers with a success status.

    Raises:
        ValueError: When ``base_url`` is unusable.
        OSError: On a network failure, a non-404 HTTP error, or when no candidate serves a card.
    """
    candidates = well_known_agent_card_urls(base_url)
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
            return url
    finally:
        if owns_client:
            http.close()
    raise OSError("No Agent Card found; tried " + ", ".join(candidates))
