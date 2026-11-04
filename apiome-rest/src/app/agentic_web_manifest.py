"""Agentic-web site manifests over a tenant's published surface — MFX-32.3 (#4297).

A site that speaks to agents publishes small, site-level manifests that say what it serves and
where: ``agents.json`` (the agents.txt companion, https://agents-txt.com) and ``llms.txt``
(https://llmstxt.org). Apiome imports both (:mod:`app.agents_manifest_parser`, MFI-18.3); this
module writes them for a tenant's **own published surface** in apiome-browse — a set-level export
over every published, public artifact rather than one version.

What each artifact contributes
------------------------------
Every artifact is one :class:`PublishedArtifact` — the project's latest published public version —
and is listed twice over:

* **its Browse page** (the version's public page in apiome-browse), under the ``x-apiome-apis`` key
  of ``agents.json`` and the ``## APIs`` section of ``llms.txt``, with its protocol, source format
  and version;
* **its agent endpoint**, when the artifact *is* an agent interface and its own source declares
  where it lives: an A2A agent's card at the well-known URI of the agent's origin
  (``/.well-known/agent-card.json``), an MCP server's URL, an ACP server's URL. These go under the
  standard ``a2a`` / ``mcp`` / ``acp`` keys (and the ``## Agents`` section), so a crawler following
  the manifest's discovery seeds reaches the agent itself. An artifact whose source names no http(s)
  endpoint is listed by its Browse page only.

The three standard keys are always written (empty when the tenant publishes no agent), so the
document is recognised as an ``agents.json`` and re-imports through MFI-18.3 either way.

This module is pure: :mod:`app.browse_agentic_routes` gathers the artifacts (public visibility,
tenant scope) and calls :func:`build_agents_json` / :func:`build_llms_txt`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit

from .a2a_agent_card_discovery import A2aDiscoveryError, well_known_agent_card_urls
from .canonical_model import CanonicalApi

__all__ = [
    "AGENTS_JSON_SCHEMA",
    "AGENT_PROTOCOLS",
    "APIS_KEY",
    "PublishedArtifact",
    "agent_endpoint",
    "browse_page_url",
    "build_agents_json",
    "build_llms_txt",
    "render_agents_json",
]

#: The agents.json schema and standard the document declares (what the MFI-18.3 parser detects).
AGENTS_JSON_SCHEMA = "https://agents-txt.com/schema/agents-json/v1.0.json"
AGENTS_JSON_STANDARD = "https://agents-txt.com"
#: The agents.json key the published artifacts' Browse pages are listed under (an ``x-`` key: the
#: standard has no list for API descriptions).
APIS_KEY = "x-apiome-apis"
#: Source format → the standard agents.json key its agent endpoint is listed under.
AGENT_PROTOCOLS: Dict[str, str] = {"a2a": "a2a", "mcp": "mcp", "acp": "acp"}
#: How llms.txt names each agent endpoint, so the MFI-18.3 link classifier files it right.
_AGENT_LINK_LABELS: Dict[str, str] = {"a2a": "A2A agent card", "mcp": "MCP server", "acp": "ACP agent"}
#: The longest description written for one entry; longer ones are cut at a word.
MAX_DESCRIPTION_CHARS = 200


@dataclass(frozen=True)
class PublishedArtifact:
    """One published, public artifact of the tenant (its latest published public version).

    Attributes:
        project_slug: The project's slug.
        name: The project's display name.
        version: The version label (``1.2.0``).
        protocol: The canonical paradigm (``rest``, ``rpc``, ``agent`` …), when recorded.
        source_format: The source format key (``openapi-3.1``, ``a2a`` …), when recorded.
        description: The version's description, when given.
        agent_url: The agent endpoint its own source declares (see :func:`agent_endpoint`), or
            ``None``.
    """

    project_slug: str
    name: str
    version: str
    protocol: Optional[str] = None
    source_format: Optional[str] = None
    description: Optional[str] = None
    agent_url: Optional[str] = None


def _is_http_url(value: Optional[str]) -> bool:
    """Whether ``value`` is an absolute http(s) URL with a host."""
    if not value:
        return False
    parts = urlsplit(value)
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)


def agent_endpoint(source_format: Optional[str], api: CanonicalApi) -> Optional[str]:
    """The endpoint an agent artifact's own source declares, or ``None``.

    * ``a2a`` — the A2A well-known card URI (``/.well-known/agent-card.json``) at the origin of the
      agent's URL (the card's ``url``, else its first interface); a URL that is already a ``.json``
      card is kept as it is;
    * ``mcp`` / ``acp`` — the first http(s) server the source names.

    Args:
        source_format: The artifact's source format key.
        api: Its canonical model.

    Returns:
        An absolute http(s) URL, or ``None`` for any other format or when the source names none.
    """
    fmt = (source_format or "").lower()
    if fmt not in AGENT_PROTOCOLS:
        return None
    candidates = [agent.url for agent in api.agents] + [server.url for server in api.servers]
    url = next((candidate for candidate in candidates if _is_http_url(candidate)), None)
    if url is None:
        return None
    if fmt == "a2a":
        try:
            return well_known_agent_card_urls(url)[0]
        except A2aDiscoveryError:
            return None
    return url


def browse_page_url(site_url: str, tenant_slug: str, artifact: PublishedArtifact) -> str:
    """The artifact's public version page in apiome-browse.

    Args:
        site_url: The Browse site root (origin plus base path, no trailing slash), or ``""`` for a
            site-relative URL.
        tenant_slug: The tenant's slug.
        artifact: The artifact.

    Returns:
        ``<site>/tenant/<tenant>/<project>/<version>``, each segment percent-encoded.
    """
    segments = "/".join(quote(part, safe="") for part in (tenant_slug, artifact.project_slug, artifact.version))
    return f"{site_url}/tenant/{segments}"


def _one_line(text: Optional[str]) -> Optional[str]:
    """``text`` on one line, cut at a word to :data:`MAX_DESCRIPTION_CHARS`; ``None`` when blank."""
    if not text:
        return None
    line = " ".join(text.split())
    if not line:
        return None
    if len(line) <= MAX_DESCRIPTION_CHARS:
        return line
    cut = line[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def _summary(artifact: PublishedArtifact) -> str:
    """``REST · openapi-3.1 · version 1.2.0`` — what an artifact is, for a reader."""
    parts = [part for part in (artifact.protocol, artifact.source_format) if part]
    parts.append(f"version {artifact.version}")
    return " · ".join(parts)


def build_agents_json(
    *, tenant_slug: str, tenant_name: str, site_url: str, artifacts: List[PublishedArtifact]
) -> Dict[str, Any]:
    """The tenant's ``agents.json``.

    Args:
        tenant_slug: The tenant's slug.
        tenant_name: The tenant's display name (the manifest's ``site.name``).
        site_url: The Browse site root, or ``""`` (then every URL is site-relative and ``site`` has
            no ``url``).
        artifacts: The published, public artifacts, in the order to list them.

    Returns:
        The document: ``$schema``, ``version``, ``standard``, ``site``, the ``a2a`` / ``mcp`` /
        ``acp`` lists (always present) and ``x-apiome-apis``.
    """
    site: Dict[str, Any] = {"name": tenant_name}
    if site_url:
        site["url"] = f"{site_url}/tenant/{quote(tenant_slug, safe='')}"
    site["description"] = f"The APIs and agents {tenant_name} publishes on Apiome."
    document: Dict[str, Any] = {
        "$schema": AGENTS_JSON_SCHEMA,
        "version": "1.0",
        "standard": AGENTS_JSON_STANDARD,
        "site": site,
    }
    for key in AGENT_PROTOCOLS.values():
        document[key] = []
    apis: List[Dict[str, Any]] = []
    for artifact in artifacts:
        description = _one_line(artifact.description)
        fmt = (artifact.source_format or "").lower()
        if artifact.agent_url and fmt in AGENT_PROTOCOLS:
            entry: Dict[str, Any] = {"url": artifact.agent_url, "name": artifact.name}
            if description:
                entry["description"] = description
            document[AGENT_PROTOCOLS[fmt]].append(entry)
        api: Dict[str, Any] = {"url": browse_page_url(site_url, tenant_slug, artifact), "name": artifact.name}
        if description:
            api["description"] = description
        for key, value in (("protocol", artifact.protocol), ("format", artifact.source_format),
                           ("version", artifact.version)):
            if value:
                api[key] = value
        apis.append(api)
    document[APIS_KEY] = apis
    return document


def render_agents_json(document: Dict[str, Any]) -> str:
    """``document`` as the served JSON text (two-space indent, trailing newline)."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _link_text(text: str) -> str:
    """Link text safe inside ``[...]`` (no brackets or line breaks)."""
    return " ".join(text.replace("[", "(").replace("]", ")").split())


def build_llms_txt(
    *, tenant_slug: str, tenant_name: str, site_url: str, artifacts: List[PublishedArtifact],
    agents_json_url: Optional[str] = None,
) -> str:
    """The tenant's ``llms.txt``: an H1, a summary, and H2 sections of links.

    Args:
        tenant_slug: The tenant's slug.
        tenant_name: The tenant's display name (the H1).
        site_url: The Browse site root, or ``""`` for site-relative links.
        artifacts: The published, public artifacts, in the order to list them.
        agents_json_url: Where the matching ``agents.json`` is served, listed under ``## Optional``.

    Returns:
        The Markdown text: ``## APIs`` (one link per artifact's Browse page), ``## Agents`` (one per
        agent endpoint, when any) and ``## Optional`` (the agents.json, when given).
    """
    count = len(artifacts)
    lines = [
        f"# {' '.join(tenant_name.split()) or tenant_slug}",
        "",
        f"> The {count} API{'s' if count != 1 else ''} and agent{'s' if count != 1 else ''} "
        f"{' '.join(tenant_name.split()) or tenant_slug} publishes on Apiome, each with its latest "
        "published version. Every link opens the version's public page.",
        "",
        "## APIs",
        "",
    ]
    if not artifacts:
        lines.append("Nothing is published yet.")
    for artifact in artifacts:
        description = _one_line(artifact.description)
        notes = f"{description} ({_summary(artifact)})" if description else _summary(artifact)
        lines.append(f"- [{_link_text(artifact.name)}]({browse_page_url(site_url, tenant_slug, artifact)}): {notes}")
    agents = [a for a in artifacts if a.agent_url and (a.source_format or "").lower() in AGENT_PROTOCOLS]
    if agents:
        lines += ["", "## Agents", ""]
        for artifact in agents:
            label = _AGENT_LINK_LABELS[(artifact.source_format or "").lower()]
            notes = _one_line(artifact.description) or f"The {label} of {artifact.name}"
            lines.append(f"- [{_link_text(artifact.name)} ({label})]({artifact.agent_url}): {notes}")
    if agents_json_url:
        lines += ["", "## Optional", "", f"- [Site manifest]({agents_json_url}): agents.json with the same entries"]
    return "\n".join(lines) + "\n"
