"""Bounded, SSRF-guarded fetch of a live agent descriptor — shared by MFI-18.1 / MFI-18.2.

Agent protocols publish their descriptor at a fixed path under the agent's (or server's)
origin: A2A at ``/.well-known/agent-card.json`` (:mod:`app.a2a_agent_card_discovery`), ACP at
``/agents`` (:mod:`app.acp_agent_discovery`). Both discover the same way, so the mechanics live
here once:

* :func:`split_http_url` validates the caller's base URL (``http``/``https`` with a host);
* :func:`fetch_first_descriptor` GETs each candidate URL in order through the SSRF-guarded client
  (:func:`app.ssrf_guard.build_guarded_client`, which re-checks every redirect hop) and returns the
  first body served. Only ``404`` / ``410`` moves on to the next candidate — a ``401`` or a timeout
  on one path says nothing about whether another exists — and a body over
  :data:`MAX_DESCRIPTOR_BYTES` is refused rather than buffered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence
from urllib.parse import SplitResult, urlsplit

import httpx

from .ssrf_guard import SSRFError, build_guarded_client, validate_url

__all__ = [
    "MAX_DESCRIPTOR_BYTES",
    "AgentDiscoveryError",
    "FetchedDescriptor",
    "fetch_first_descriptor",
    "split_http_url",
]

#: Hard cap on a fetched descriptor. Real ones are a few kilobytes; this leaves headroom for a
#: large skill or agent list without letting a hostile endpoint stream an unbounded body.
MAX_DESCRIPTOR_BYTES = 1_000_000

_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_UA = "Apiome-Agent-Discovery/1.0"

#: Statuses that mean "nothing at this path" — the only ones that fall through to the next URL.
_NOT_FOUND_STATUSES = frozenset({404, 410})


class AgentDiscoveryError(Exception):
    """A descriptor could not be discovered (bad URL, SSRF rejection, network or HTTP failure)."""


@dataclass(frozen=True)
class FetchedDescriptor:
    """A descriptor fetched from a live agent or server.

    Attributes:
        url: The URL the descriptor was actually served from.
        text: The body, decoded as UTF-8.
    """

    url: str
    text: str


def split_http_url(base_url: str, *, what: str = "Agent URL") -> SplitResult:
    """Validate and split an ``http``/``https`` base URL.

    Args:
        base_url: The URL the caller supplied.
        what: How to name the URL in error messages.

    Returns:
        The split URL (stripped of surrounding whitespace).

    Raises:
        AgentDiscoveryError: When the URL is empty, not http(s), or has no host.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        raise AgentDiscoveryError(f"{what} is empty")
    parts = urlsplit(cleaned)
    if parts.scheme.lower() not in ("http", "https"):
        raise AgentDiscoveryError(f"{what} must be an http or https URL")
    if not parts.netloc:
        raise AgentDiscoveryError(f"{what} has no host")
    return parts


def fetch_first_descriptor(
    candidates: Sequence[str],
    *,
    label: str,
    client: Optional[httpx.Client] = None,
) -> FetchedDescriptor:
    """GET each candidate URL in order and return the first body served.

    Args:
        candidates: Absolute URLs to try, most preferred first.
        label: What is being fetched (``"Agent Card"``, ``"ACP agent manifest"``), for messages.
        client: Optional httpx client (tests); a guarded client is built and closed otherwise.

    Returns:
        The first descriptor served.

    Raises:
        AgentDiscoveryError: On SSRF rejection, network failure, an oversized body, a non-404
            HTTP error, or when no candidate serves anything.
    """
    owns_client = client is None
    http = client or build_guarded_client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        for url in candidates:
            text = _fetch_text(http, url, label=label)
            if text is not None:
                return FetchedDescriptor(url=url, text=text)
    finally:
        if owns_client:
            http.close()
    raise AgentDiscoveryError(f"No {label} found; tried " + ", ".join(candidates))


def _fetch_text(http: httpx.Client, url: str, *, label: str) -> Optional[str]:
    """GET one candidate URL.

    Args:
        http: The client to use.
        url: The candidate URL.
        label: What is being fetched, for messages.

    Returns:
        The decoded body, or ``None`` when the server says there is nothing here.

    Raises:
        AgentDiscoveryError: For anything other than success or "not found".
    """
    try:
        validate_url(url)
    except SSRFError as exc:
        raise AgentDiscoveryError(str(exc)) from exc
    headers = {"User-Agent": _UA, "Accept": "application/json, */*;q=0.5"}
    try:
        with http.stream("GET", url, headers=headers) as resp:
            if resp.status_code in _NOT_FOUND_STATUSES:
                return None
            if resp.status_code >= 400:
                raise AgentDiscoveryError(f"{url} returned HTTP {resp.status_code}")
            chunks: List[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DESCRIPTOR_BYTES:
                    raise AgentDiscoveryError(
                        f"{label} at {url} exceeds the {MAX_DESCRIPTOR_BYTES}-byte limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
    except SSRFError as exc:
        raise AgentDiscoveryError(str(exc)) from exc
    except httpx.HTTPError as exc:
        raise AgentDiscoveryError(f"Failed to fetch {url}: {exc}") from exc
