"""A2A agent registry crawl — MFI-18.5 (#3978), declared by the ``a2a`` adapter.

A2A's discovery guide names *curated registries* as the way to find agents at scale, but the A2A
specification does not yet define a registry API. This crawl therefore reads the shape such
registries publish today, documented on the docs site so a registry can target it:

``GET <base>`` returns a JSON object ``{"agents": [entry, …], "nextPageToken": "…"}`` (the next
page is ``GET <base>?pageToken=…``) or a bare JSON array of entries. An **entry** is either

* a URL string — an Agent Card URL (``…/agent-card.json``) or an agent's origin, whose card is at
  its well-known path (``/.well-known/agent-card.json``, then the legacy ``/.well-known/agent.json``);
* an object with ``url`` (or ``cardUrl`` / ``agentCardUrl``) and optional ``name``, ``version`` and
  ``updatedAt``; or
* an object carrying the Agent Card itself, inline (under ``card``, or the entry *is* a card).

Each agent becomes one catalog item keyed by its card URL (an inline card without one is keyed by
its ``url`` or ``name``). The entry's ``version`` / ``updatedAt`` is its revision when given; an
inline card with neither is revised by its content digest, and a linked card with neither is
compared by content after it is fetched — so a re-crawl imports only agents whose card changed.
"""

from __future__ import annotations

import json
from typing import Any, List, Mapping, Optional

from .a2a_agent_card_discovery import well_known_agent_card_urls
from .agent_descriptor_fetch import AgentDiscoveryError
from .refresh_source import ERROR_CLASS_UNEXPECTED, FetchedDocument, RefreshSourceError
from .registry_crawl import (
    Page,
    RegistryCrawl,
    RegistryEntry,
    RegistryHttp,
    content_revision,
    paginate,
    parse_instant,
    register_registry_crawl,
)

__all__ = ["A2A_REGISTRY", "A2aRegistryCrawl", "parse_registry_entry"]

#: Keys an entry object may name its card URL under, in order of preference.
_URL_KEYS = ("cardUrl", "agentCardUrl", "url")


def _card_urls(url: str) -> List[str]:
    """The card URLs to try for ``url`` (itself, or the well-known paths of its origin)."""
    try:
        return well_known_agent_card_urls(url)
    except AgentDiscoveryError:
        return []


def _is_card(value: Any) -> bool:
    """Whether ``value`` is an inline Agent Card (a name and a skills list)."""
    return isinstance(value, Mapping) and isinstance(value.get("name"), str) and isinstance(value.get("skills"), list)


def parse_registry_entry(entry: Any) -> Optional[RegistryEntry]:
    """Read one registry entry into a :class:`RegistryEntry`, or ``None`` when it names no agent.

    Args:
        entry: A list element of the registry response.

    Returns:
        The entry: a linked card (``document_url`` set) or an inline one (``content`` set).
    """
    if isinstance(entry, str):
        entry = {"url": entry}
    if not isinstance(entry, Mapping):
        return None
    card = entry.get("card") if _is_card(entry.get("card")) else (entry if _is_card(entry) else None)
    url = next((str(entry[k]).strip() for k in _URL_KEYS if isinstance(entry.get(k), str) and entry[k].strip()), None)
    name = entry.get("name") if isinstance(entry.get("name"), str) else (card or {}).get("name")
    version = entry.get("version") if isinstance(entry.get("version"), (str, int, float)) else None
    updated = entry.get("updatedAt") or entry.get("updated_at")
    listed_revision = str(version) if version is not None else (updated if isinstance(updated, str) else None)
    if card is not None:
        remote_id = url or (str(name) if name else None)
        if not remote_id:
            return None
        return RegistryEntry(
            remote_id=remote_id,
            import_kind="a2a",
            filename="agent-card.json",
            name=str(name) if name else None,
            revision=listed_revision or content_revision(card),
            updated_at=parse_instant(updated),
            content=json.dumps(card, sort_keys=True).encode("utf-8"),
            source_uri=url,
            raw={k: v for k, v in entry.items() if k != "card"},
        )
    candidates = _card_urls(url) if url else []
    if not candidates:
        return None
    return RegistryEntry(
        remote_id=candidates[0],
        import_kind="a2a",
        filename="agent-card.json",
        name=str(name) if name else None,
        revision=listed_revision,
        updated_at=parse_instant(updated),
        document_url=candidates[0],
        raw={**dict(entry), "listedUrl": url},
    )


class A2aRegistryCrawl(RegistryCrawl):
    """Crawl an A2A agent registry (see the module docstring for the shape it reads)."""

    protocol = "a2a-registry"
    label = "A2A agent registry"
    import_source = "a2a"

    def list_entries(
        self, http: RegistryHttp, base_url: str, scope: Mapping[str, Any]
    ) -> List[RegistryEntry]:
        """Page the registry and return one entry per agent it lists."""
        del scope

        def page(token: Optional[str]) -> Page:
            body = http.get_json(base_url, params={"pageToken": token} if token else None)
            if isinstance(body, list):
                return Page(items=body)
            if not isinstance(body, Mapping) or not isinstance(body.get("agents"), list):
                raise RefreshSourceError(
                    "The A2A registry answered with neither an agents list nor a JSON array.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
            token_next = body.get("nextPageToken")
            return Page(items=body["agents"], next_token=token_next if isinstance(token_next, str) else None)

        entries = (parse_registry_entry(item) for item in paginate(page, what="agents"))
        return [entry for entry in entries if entry is not None]

    def fetch_entry(self, http: RegistryHttp, entry: RegistryEntry) -> FetchedDocument:
        """Fetch the agent's card; for an origin URL fall back to the legacy well-known path on 404."""
        if entry.content is not None or not entry.document_url:
            return super().fetch_entry(http, entry)
        # The URL as the registry listed it: an origin yields both well-known paths to try.
        urls = _card_urls(str(entry.raw.get("listedUrl") or entry.document_url))
        last: Optional[RefreshSourceError] = None
        for url in urls:
            try:
                response = http.get(url, accept="application/json")
            except RefreshSourceError as exc:
                if exc.http_status in (404, 410):
                    last = exc
                    continue
                raise
            return FetchedDocument(
                content=response.content,
                filename=entry.filename,
                import_kind=entry.import_kind,
                revision=entry.revision,
                source_uri=url,
            )
        raise last or RefreshSourceError(f"No Agent Card at {entry.document_url}.")


A2A_REGISTRY: RegistryCrawl = register_registry_crawl(A2aRegistryCrawl())

