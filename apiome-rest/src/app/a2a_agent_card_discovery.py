"""Live A2A Agent Card discovery — MFI-18.1 (#3974).

An A2A agent publishes its card at a **well-known URI** (RFC 8615) under its origin:
``/.well-known/agent-card.json`` since A2A 0.3, ``/.well-known/agent.json`` before it. Given an
agent's base URL this module resolves the candidate card URLs in that order and fetches the
first one that answers, through the same SSRF-guarded client every other live import uses
(:func:`app.ssrf_guard.build_guarded_client`), so discovery cannot be pointed at an internal
address or a cloud metadata endpoint — not even through a redirect.

The fetch is bounded (:data:`MAX_CARD_BYTES`) and only a ``404`` / ``410`` moves on to the next
candidate; any other failure is reported immediately, because a ``401`` or a timeout on the
current path says nothing about whether the legacy path exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from .a2a_agent_card_parser import (
    LEGACY_WELL_KNOWN_AGENT_CARD_PATH,
    WELL_KNOWN_AGENT_CARD_PATH,
)
from .ssrf_guard import SSRFError, build_guarded_client, validate_url

__all__ = [
    "MAX_CARD_BYTES",
    "A2aDiscoveryError",
    "FetchedAgentCard",
    "fetch_agent_card",
    "well_known_agent_card_urls",
]

#: Hard cap on a fetched card's size. Real cards are a few kilobytes; this leaves headroom for
#: a large skill list without letting a hostile endpoint stream an unbounded body.
MAX_CARD_BYTES = 1_000_000

_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_UA = "Apiome-A2A-Discovery/1.0"

#: Statuses that mean "no card at this path" — the only ones that fall through to the next
#: candidate URL.
_NOT_FOUND_STATUSES = frozenset({404, 410})


class A2aDiscoveryError(Exception):
    """A card could not be discovered (bad URL, SSRF rejection, network or HTTP failure)."""


@dataclass(frozen=True)
class FetchedAgentCard:
    """A card fetched from a live agent.

    Attributes:
        url: The URL the card was actually served from.
        text: The card body, decoded as UTF-8.
    """

    url: str
    text: str


def well_known_agent_card_urls(base_url: str) -> List[str]:
    """Return the URLs to try, in order, for an agent at ``base_url``.

    A URL whose path already ends in ``.json`` is taken as the card itself and returned
    alone. Otherwise the agent's **origin** is used (any path is dropped, since a well-known
    URI is always rooted at the origin) and the current then legacy well-known paths are
    returned.

    Args:
        base_url: An agent origin (``https://agent.example.com``) or a direct card URL.

    Returns:
        One or two absolute URLs.

    Raises:
        A2aDiscoveryError: When ``base_url`` is empty, not http(s), or has no host.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        raise A2aDiscoveryError("Agent URL is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise A2aDiscoveryError("Agent URL must be an http or https URL")
    if not parts.netloc:
        raise A2aDiscoveryError("Agent URL has no host")
    if parts.path.lower().endswith(".json"):
        return [cleaned]
    scheme = parts.scheme.lower()
    return [
        urlunsplit((scheme, parts.netloc, path, "", ""))
        for path in (WELL_KNOWN_AGENT_CARD_PATH, LEGACY_WELL_KNOWN_AGENT_CARD_PATH)
    ]


def fetch_agent_card(base_url: str, *, client: Optional[httpx.Client] = None) -> FetchedAgentCard:
    """Fetch an agent's card from its well-known URI.

    Args:
        base_url: An agent origin or a direct card URL (see :func:`well_known_agent_card_urls`).
        client: Optional httpx client (tests); a guarded client is built and closed otherwise.

    Returns:
        The card text and the URL it came from.

    Raises:
        A2aDiscoveryError: On SSRF rejection, network failure, an oversized body, a non-404
            HTTP error, or when no candidate URL serves a card.
    """
    candidates = well_known_agent_card_urls(base_url)
    owns_client = client is None
    http = client or build_guarded_client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        for url in candidates:
            text = _fetch_text(http, url)
            if text is not None:
                return FetchedAgentCard(url=url, text=text)
    finally:
        if owns_client:
            http.close()
    raise A2aDiscoveryError(
        "No Agent Card found; tried " + ", ".join(candidates)
    )


def _fetch_text(http: httpx.Client, url: str) -> Optional[str]:
    """GET one candidate URL.

    Args:
        http: The client to use.
        url: The candidate card URL.

    Returns:
        The decoded body, or ``None`` when the server says there is no card here.

    Raises:
        A2aDiscoveryError: For anything other than success or "not found".
    """
    try:
        validate_url(url)
    except SSRFError as exc:
        raise A2aDiscoveryError(str(exc)) from exc
    headers = {"User-Agent": _UA, "Accept": "application/json, */*;q=0.5"}
    try:
        with http.stream("GET", url, headers=headers) as resp:
            if resp.status_code in _NOT_FOUND_STATUSES:
                return None
            if resp.status_code >= 400:
                raise A2aDiscoveryError(f"{url} returned HTTP {resp.status_code}")
            chunks: List[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CARD_BYTES:
                    raise A2aDiscoveryError(
                        f"Agent Card at {url} exceeds the {MAX_CARD_BYTES}-byte limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except SSRFError as exc:
        raise A2aDiscoveryError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise A2aDiscoveryError(f"Failed to fetch {url}: {exc}") from exc
