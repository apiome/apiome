"""Live A2A Agent Card discovery — MFI-18.1 (#3974).

An A2A agent publishes its card at a **well-known URI** (RFC 8615) under its origin:
``/.well-known/agent-card.json`` since A2A 0.3, ``/.well-known/agent.json`` before it. Given an
agent's base URL this module resolves the candidate card URLs in that order and fetches the
first one that answers. The bounded, SSRF-guarded fetch itself is shared with ACP discovery
(:mod:`app.agent_descriptor_fetch`): it cannot be pointed at an internal address or a cloud
metadata endpoint — not even through a redirect — and only a ``404`` / ``410`` moves on to the
legacy path.
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlunsplit

import httpx

from .a2a_agent_card_parser import (
    LEGACY_WELL_KNOWN_AGENT_CARD_PATH,
    WELL_KNOWN_AGENT_CARD_PATH,
)
from .agent_descriptor_fetch import (
    MAX_DESCRIPTOR_BYTES,
    AgentDiscoveryError,
    FetchedDescriptor,
    fetch_first_descriptor,
    split_http_url,
)

__all__ = [
    "MAX_CARD_BYTES",
    "A2aDiscoveryError",
    "FetchedAgentCard",
    "fetch_agent_card",
    "well_known_agent_card_urls",
]

#: Hard cap on a fetched card's size (the shared descriptor limit).
MAX_CARD_BYTES = MAX_DESCRIPTOR_BYTES

#: The discovery error A2A callers catch; the shared descriptor error under its A2A name.
A2aDiscoveryError = AgentDiscoveryError

#: A card fetched from a live agent: ``url`` it was served from and its ``text``.
FetchedAgentCard = FetchedDescriptor


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
    parts = split_http_url(base_url)
    if parts.path.lower().endswith(".json"):
        return [parts.geturl()]
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
    return fetch_first_descriptor(
        well_known_agent_card_urls(base_url), label="Agent Card", client=client
    )
