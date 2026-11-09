"""Upstream MCP registry connector: ``GET /v0.1/servers`` into the MCP server catalog — CDG-4.4 (#5976).

An ``mcp-registry`` connector points at any registry that speaks the MCP Registry API v0.1: the
official registry (``https://registry.modelcontextprotocol.io``), Azure API Center, a Kong registry
or another Apiome tenant (``https://<apiome>/registry/mcp/<tenant>``, CDG-4.1). It runs on the
CDG-1.1 connector protocol — one cadence, quota and ledger with every other connector — but its
entries become **MCP servers** (``apiome.mcp_endpoints``, ``added_via = 'registry'``), not catalog
items, so the source syncs each entry itself (the engine's ``sync_item`` hook).

**Listing.** The source pages ``GET {base}/v0.1/servers`` (``limit``, ``cursor`` from
``metadata.nextCursor``, ``version=latest``) with the connector scope's ``search`` and
``updatedSince`` (sent as ``updated_since``) filters, through the registry client
(:class:`app.mcp_registry_client.McpRegistryClient`, V2-MCP-26.1). The base URL is the registry root; a
trailing ``/v0.1`` or ``/v0.1/servers`` is accepted and dropped. Each server name is one inventory row
(``remoteId``); a name listed in several versions keeps its ``isLatest`` entry. Entries the registry
marks ``deleted`` are listed too, so the sync can mark their MCP servers (below); an entry the
registry stops listing altogether turns ``missing``. ``updatedSince`` is a fixed filter, never
advanced by a sync: an entry the filter hides is reported missing.

**Cadence** (V2-MCP-26.3). The connector sweep syncs a connector on its own cadence
(``refresh_interval_seconds``), or hourly when it has none (``APIOME_MCP_REGISTRY_SYNC_INTERVAL``).

**Names** (V2-MCP-26.3). A registry server name is reverse-DNS namespaced:
``<namespace>/<server>``, the namespace a dotted domain written backwards (``io.github.acme``,
``com.example``). The name is the server's identity in the tenant: one name is one MCP server, however
many connectors list it. An entry whose name has no such namespace, or whose name is already in the
catalog from another registry, stays ``discovered`` with the reason and creates nothing; the same
name from the same registry (a second connector with another search) refreshes the server the first
one created. A new server's slug is the whole namespaced name (``io-github-acme-weather``), so two
servers named ``weather`` in different namespaces never compete for one slug.

**Status** (V2-MCP-26.3). The registry's ``_meta`` status is recorded on the endpoint
(``registry_metadata.status``) and listed on the run summary as a finding
(``mcp-registry-deprecated`` / ``mcp-registry-deleted``). A ``deprecated`` entry still imports and
is discovered as usual. A ``deleted`` entry is not discovered and creates nothing: its server, when
there is one, is kept and marked ``deleted``, and the row stays ``discovered``
(``registry-deleted``). An entry the registry restores to ``active`` imports again.

**Syncing one entry** (only entries whose content changed since the last import — the revision is
the server version plus a digest of the whole ``server.json``):

1. **Check the entry**: a namespaced name, not deleted, not a name another registry already
   imported (above).
2. **Pick a remote.** The first ``remotes[]`` entry of type ``streamable-http`` or ``sse`` with a
   concrete ``http(s)`` URL. No such remote (a package-only server runs locally over stdio, or its
   URL is a template with ``{variables}``), or a URL the connector address policy refuses
   (:func:`app.catalog_connectors.connector_base_url_from_settings`), leaves the row
   ``discovered`` with the reason and creates nothing.
3. **Create or refresh the MCP server.** A new entry inserts an endpoint (private, unpublished,
   ``added_via = 'registry'``); a known one has its name, URL, transport and description refreshed
   from the registry. The endpoint also records the entry itself (``registry_metadata``,
   V2-MCP-26.2): server name, ``version``, ``websiteUrl``, the ``_meta`` status and dates, and the
   chosen remote with the headers it declares — never a secret header's value
   (:func:`app.mcp_server_json.registry_metadata`). An entry in an earlier snake_case draft of
   ``server.json`` is read as the current camelCase one.
4. **Link sources** (``apiome.mcp_endpoint_sources``, provenance ``registry_published``): the
   registry identity itself, ``repository.url`` as a git source and every ``packages[]`` entry of a
   known ecosystem (npm, PyPI, NuGet, Cargo as package sources; OCI as an image). Each link records
   the connector in its ``provenance_detail``, and a link this connector made that the registry no
   longer lists is retired. Nothing is invented: a package version is pinned only when the registry
   names an exact one.
5. **Run discovery** (``trigger = 'registry'``), which also lints and scores the new snapshot. When
   discovery cannot reach the remote (connect, TLS, timeout or address failure), the row stays
   ``discovered`` with the reason — still linked to the server, and tried again next sync. Any
   answer, even ``401``, means the server is there, and the row becomes ``imported``.

**Credentials** are optional: ``{"token": "…"}`` is sent as a bearer token and ``{"apiKey": "…"}``
as ``X-API-Key`` (an Apiome workspace key). Every request goes through
:func:`app.catalog_connectors.build_connector_http_client`, which re-checks the SSRF rule per hop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import quote, urlsplit

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, ItemSyncOutcome, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, connector_base_url_from_settings
from .mcp_registry import remote_url
from .mcp_registry_client import (
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_SIZE,
    McpRegistryClient,
    RegistryServer,
    normalize_registry_base,
    parse_server_entry,
)
from .mcp_server_json import registry_metadata
from .mcp_source_link import (
    PROVENANCE_REGISTRY,
    SOURCE_GIT,
    SOURCE_IMAGE,
    SOURCE_PACKAGE,
    SOURCE_REGISTRY,
    SourceLink,
    SourceReferenceError,
    parse_source_reference,
)
from .refresh_source import (
    ERROR_CLASS_UNEXPECTED,
    FetchedDocument,
    FreshnessKey,
    RefreshCandidate,
    RefreshSourceError,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "FINDING_DELETED",
    "FINDING_DEPRECATED",
    "KIND",
    "McpRegistrySource",
    "REASON_DISCOVERY_UNREACHABLE",
    "REASON_DUPLICATE_NAME",
    "REASON_NAME_NOT_NAMESPACED",
    "REASON_NO_REMOTE",
    "REASON_REGISTRY_DELETED",
    "REASON_REMOTE_REFUSED",
    "REASON_REMOTE_TEMPLATED",
    "RegistryServer",
    "build_candidate",
    "latest_servers",
    "normalize_registry_base",
    "parse_server_entry",
    "registry_source_links",
    "revision_status",
    "select_remote",
    "split_server_name",
    "status_findings",
    "validate_mcp_registry_scope",
]

KIND = "mcp-registry"

#: Entries requested per page, and the most pages followed (10 000 servers).
PAGE_SIZE = DEFAULT_PAGE_SIZE
MAX_PAGES = DEFAULT_MAX_PAGES

#: Scope keys the kind accepts.
SCOPE_KEYS = ("search", "updatedSince")
_SEARCH_MAX = 200

#: Error class for a scope or base URL that cannot address a registry.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"

#: Stable reason codes an entry stays ``discovered`` with (the stored reason is ``"<code>: <why>"``).
REASON_NO_REMOTE = "no-remote"
REASON_REMOTE_TEMPLATED = "remote-templated"
REASON_REMOTE_REFUSED = "remote-refused"
REASON_DISCOVERY_UNREACHABLE = "remote-unreachable"
REASON_NAME_NOT_NAMESPACED = "name-not-namespaced"
REASON_DUPLICATE_NAME = "duplicate-name"
REASON_REGISTRY_DELETED = "registry-deleted"

#: Run-summary finding codes for entries the registry marks other than ``active`` (V2-MCP-26.3).
FINDING_DEPRECATED = "mcp-registry-deprecated"
FINDING_DELETED = "mcp-registry-deleted"
_STATUS_FINDINGS = {"deprecated": FINDING_DEPRECATED, "deleted": FINDING_DELETED}

#: A reverse-DNS namespaced server name: two or more dotted labels, ``/``, the server part (the
#: registry schema's ``^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$``, with the namespace's dots required).
_NAMESPACED_NAME = re.compile(r"^(?P<namespace>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)/(?P<server>[A-Za-z0-9._-]+)$")
_NAME_MAX = 200

#: Registry remote types → catalog transports.
_TRANSPORTS = {"streamable-http": "streamable_http", "sse": "sse"}

#: Discovery error codes that mean the remote was never reached (``app.mcp_client.errors``).
UNREACHABLE_DISCOVERY_CODES = frozenset(
    {"connect_timeout", "timeout", "connect_error", "tls_error", "ssrf_blocked", "budget_exceeded"}
)

#: Registry package types that are Package URL ecosystems (``registryType`` → purl type).
_PURL_TYPES = {"npm": "npm", "pypi": "pypi", "nuget": "nuget", "cargo": "cargo"}

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")

#: ``(endpoint row) -> discovery failure code, or None when the server answered``.
Discover = Callable[[Mapping[str, Any]], Optional[str]]


# ---------------------------------------------------------------------------------------
# Scope validation (run by the routes on every write)
# ---------------------------------------------------------------------------------------


def _scope_error(message: str) -> ConnectorError:
    return ConnectorError(CODE_INVALID, message)


def _parse_instant(value: str) -> Optional[datetime]:
    """Parse an RFC 3339 instant (``Z`` or an offset), or return ``None``."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def validate_mcp_registry_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check an ``mcp-registry`` scope and require a base URL.

    Args:
        scope: The connector scope: optional ``search`` (a substring the registry matches) and
            ``updatedSince`` (an RFC 3339 instant).
        base_url: The registry root URL.

    Raises:
        ConnectorError: ``connector-invalid`` for a missing base URL, an unknown key, a blank or
            overlong ``search`` or an ``updatedSince`` that is not an RFC 3339 instant.
    """
    if not (base_url or "").strip():
        raise _scope_error(
            "An MCP registry connector needs a base URL: the registry root, for example "
            "https://registry.modelcontextprotocol.io."
        )
    unknown = sorted(set(scope) - set(SCOPE_KEYS))
    if unknown:
        raise _scope_error(f"Unknown mcp-registry scope key(s): {', '.join(unknown)}.")
    search = scope.get("search")
    if search is not None and (not isinstance(search, str) or not search.strip() or len(search) > _SEARCH_MAX):
        raise _scope_error(f"search must be a non-empty string of at most {_SEARCH_MAX} characters.")
    since = scope.get("updatedSince")
    if since is not None and (not isinstance(since, str) or _parse_instant(since) is None):
        raise _scope_error("updatedSince must be an RFC 3339 instant, for example 2026-01-01T00:00:00Z.")


# ---------------------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------------------


def split_server_name(name: str) -> Optional[Tuple[str, str]]:
    """Split a reverse-DNS namespaced registry server name.

    Args:
        name: A registry server name (``io.github.acme/weather``).

    Returns:
        ``(namespace, server)`` (``("io.github.acme", "weather")``), or ``None`` when the name has no
        dotted namespace (``weather``, ``acme/weather``), more than one ``/``, a character the
        registry schema forbids, or more than 200 characters.
    """
    match = _NAMESPACED_NAME.match(name or "")
    if match is None or len(name) > _NAME_MAX:
        return None
    return match.group("namespace"), match.group("server")


def status_findings(entries: Sequence[RegistryServer]) -> List[Dict[str, Any]]:
    """Run-summary findings for the entries the registry marks ``deprecated`` or ``deleted``.

    Args:
        entries: The entries the sync keeps (one per name).

    Returns:
        ``{code, remoteId, status}`` per such entry, in listed order (credential-free).
    """
    return [
        {"code": _STATUS_FINDINGS[entry.status], "remoteId": entry.name, "status": entry.status}
        for entry in entries
        if entry.status in _STATUS_FINDINGS
    ]


def latest_servers(entries: Sequence[RegistryServer]) -> List[RegistryServer]:
    """Keep one entry per server name: the one marked ``isLatest``, else the last one listed.

    Args:
        entries: Every entry the pages listed, in order.

    Returns:
        One entry per name, in first-seen order.
    """
    chosen: Dict[str, RegistryServer] = {}
    for entry in entries:
        current = chosen.get(entry.name)
        if current is None or not current.official.get("isLatest") or entry.official.get("isLatest"):
            chosen[entry.name] = entry
    return list(chosen.values())


def entry_revision(server: Mapping[str, Any], status: Optional[str] = None) -> str:
    """The entry's revision: its version plus a digest of the whole ``server.json``.

    A digest, not the version alone, because a registry other than the official one may change a
    remote URL or a package without bumping the version. A registry status other than ``active``
    (``deprecated``) is appended, so a deprecation alone re-imports the entry and its endpoint
    records it (V2-MCP-26.2); an active entry's revision is unchanged by this.
    """
    digest = hashlib.sha256(json.dumps(server, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    version = str(server.get("version") or "").strip()
    revision = f"{version}+sha256.{digest}" if version else f"sha256.{digest}"
    state = str(status or "").strip().lower()
    return f"{revision}.{state}" if state and state != "active" else revision


_REVISION_STATUS = re.compile(r"sha256\.[0-9a-f]{12}(?:\.(?P<status>[a-z0-9_-]+))?$")


def revision_status(revision: Optional[str]) -> str:
    """The registry status an :func:`entry_revision` carries: ``""`` for active, else the status.

    Args:
        revision: An entry revision (``1.0.0+sha256.0123456789ab.deprecated``), or ``None``.

    Returns:
        The non-active status, or ``""`` (active, or a revision this module did not write).
    """
    match = _REVISION_STATUS.search(revision or "")
    return (match.group("status") or "") if match else ""


def _remotes(server: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [r for r in (server.get("remotes") or []) if isinstance(r, Mapping)]


def _packages(server: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [p for p in (server.get("packages") or []) if isinstance(p, Mapping)]


def select_remote(server: Mapping[str, Any]) -> Union[Tuple[str, str], str]:
    """Pick the remote Apiome would call for an entry.

    Args:
        server: The ``server.json`` document.

    Returns:
        ``(transport, url)`` for the first ``streamable-http`` / ``sse`` remote with a concrete
        ``http(s)`` URL, or the reason there is none (``"no-remote: …"`` / ``"remote-templated: …"``).
    """
    templated = False
    for remote in _remotes(server):
        transport = _TRANSPORTS.get(str(remote.get("type") or "").lower())
        url = str(remote.get("url") or "").strip()
        if transport is None or not url:
            continue
        if "{" in url or "}" in url:
            templated = True
            continue
        if urlsplit(url).scheme in ("http", "https"):
            return transport, url
    if templated:
        return (
            f"{REASON_REMOTE_TEMPLATED}: the remote URL needs values the registry leaves to the client "
            "(a {variable}); add the server by hand with its concrete URL."
        )
    if _packages(server):
        return (
            f"{REASON_NO_REMOTE}: the server lists only packages, which run locally (stdio); "
            "there is no remote to discover."
        )
    return f"{REASON_NO_REMOTE}: the server lists no streamable-http or sse remote."


def build_candidate(entry: RegistryServer, *, registry_url: str) -> RefreshCandidate:
    """Turn a registry entry into an inventory candidate.

    Args:
        entry: The entry.
        registry_url: The registry root (recorded on the row's deployment metadata).

    Returns:
        The candidate: remote id = server name, revision = :func:`entry_revision`, hosts = the
        remotes' hosts, and ``deployment`` = what the registry says (credential-free).
    """
    server = entry.server
    remotes = []
    hosts: List[str] = []
    for remote in _remotes(server):
        url = remote_url(str(remote.get("url") or "")) or str(remote.get("url") or "")[:500]
        remotes.append({"type": remote.get("type"), "url": url})
        host = urlsplit(url).hostname if url.startswith(("http://", "https://")) else None
        if host and host not in hosts:
            hosts.append(host)
    packages = [
        {key: p.get(key) for key in ("registryType", "identifier", "version") if p.get(key) is not None}
        for p in _packages(server)
    ]
    repository = server.get("repository") if isinstance(server.get("repository"), Mapping) else {}
    deployment: Dict[str, Any] = {
        "registryUrl": registry_url,
        "serverName": entry.name,
        "version": entry.version or None,
        "status": entry.official.get("status"),
        "isLatest": entry.official.get("isLatest"),
        "publishedAt": entry.official.get("publishedAt"),
        "updatedAt": entry.official.get("updatedAt"),
        "remotes": remotes,
        "packages": packages,
        "repository": remote_url(str(repository.get("url") or "")) if repository else None,
        "websiteUrl": server.get("websiteUrl"),
    }
    title = str(server.get("title") or "").strip()
    updated = entry.official.get("updatedAt")
    return RefreshCandidate(
        remote_id=entry.name,
        name=title or entry.name,
        revision=entry_revision(server, entry.official.get("status")),
        updated_at=_parse_instant(updated) if isinstance(updated, str) else None,
        hosts=tuple(hosts),
        raw={"server": dict(server)},
        deployment={k: v for k, v in deployment.items() if v is not None},
    )


def _package_reference(package: Mapping[str, Any]) -> Optional[Tuple[str, str]]:
    """``(source kind, reference)`` for one ``packages[]`` entry, or ``None`` for an unknown type."""
    registry_type = str(package.get("registryType") or "").lower()
    identifier = str(package.get("identifier") or "").strip()
    version = str(package.get("version") or "").strip()
    if not identifier:
        return None
    if registry_type == "oci":
        if version and not re.search(r"[:@][^/]*$", identifier):
            return SOURCE_IMAGE, f"{identifier}:{version}"
        return SOURCE_IMAGE, identifier
    purl_type = _PURL_TYPES.get(registry_type)
    if purl_type is None:
        return None
    coordinate = quote(identifier, safe="/")
    return SOURCE_PACKAGE, f"pkg:{purl_type}/{coordinate}" + (f"@{version}" if version else "")


def registry_source_links(
    entry: RegistryServer, *, connector: Mapping[str, Any], registry_url: str
) -> List[SourceLink]:
    """The source links an entry declares, as ``registry_published`` :class:`SourceLink` rows.

    Args:
        entry: The registry entry.
        connector: The connector row (its id and name go in each link's ``provenance_detail``).
        registry_url: The registry root.

    Returns:
        The registry identity, then the repository (git), then each known package, skipping any
        reference that does not parse (logged, never raised).
    """
    detail = {
        "connectorId": str(connector.get("id")),
        "connectorName": connector.get("name"),
        "registryUrl": registry_url,
        "serverName": entry.name,
        "version": entry.version or None,
    }
    wanted: List[Tuple[str, str, Optional[str]]] = [(SOURCE_REGISTRY, entry.name, entry.version or None)]
    repository = entry.server.get("repository")
    if isinstance(repository, Mapping) and str(repository.get("url") or "").strip():
        wanted.append((SOURCE_GIT, str(repository["url"]).strip(), None))
    for package in _packages(entry.server):
        reference = _package_reference(package)
        if reference is not None:
            wanted.append((reference[0], reference[1], None))
    links: List[SourceLink] = []
    seen = set()
    for kind, reference, revision in wanted:
        try:
            link = parse_source_reference(
                kind, reference, revision=revision, provenance=PROVENANCE_REGISTRY, provenance_detail=detail
            )
        except SourceReferenceError as exc:
            _logger.info("mcp registry source skipped server=%s kind=%s reason=%s", entry.name, kind, exc)
            continue
        if (link.source_kind, link.locator) not in seen:
            seen.add((link.source_kind, link.locator))
            links.append(link)
    return links


def _slug_for(name: str) -> str:
    """A catalog slug for a registry server name: the whole namespaced name, slugified.

    ``io.github.acme/weather`` → ``io-github-acme-weather`` (V2-MCP-26.3), so servers that share a
    last segment in different namespaces get distinct, stable slugs. Capped at 60 characters.
    """
    return _SLUG_UNSAFE.sub("-", name.lower()).strip("-")[:60].strip("-") or "mcp-server"


# ---------------------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------------------


def _default_discover(endpoint: Mapping[str, Any]) -> Optional[str]:
    """Run one registry-triggered discovery of ``endpoint`` and return its failure code.

    Blocking: the sync engine runs in a worker thread with no event loop, so the async discovery
    pipeline runs to completion on a private loop, bounded by the per-endpoint timeout the sweep
    uses. Discovery lints and scores the snapshot it creates.

    Returns:
        The discovery error code when the run failed (``connect_error``, ``auth_required``, …), or
        ``None`` when it succeeded, joined a run already in progress, or discovery is switched off
        (``APIOME_MCP_DISCOVERY_ENABLED``).
    """
    from .config import settings
    from .database import db
    from .mcp_discovery_engine import enqueue_discovery_job, run_discovery_job

    if not settings.mcp_discovery_enabled:
        return None
    tenant_id = str(endpoint["tenant_id"])

    async def _run() -> Optional[str]:
        job, deduplicated = await enqueue_discovery_job(tenant_id, dict(endpoint), trigger="registry")
        if deduplicated:
            return None
        await run_discovery_job(
            str(job["id"]), dict(endpoint), timeout_seconds=float(settings.mcp_discovery_endpoint_timeout_seconds)
        )
        return str(job["id"])

    job_id = asyncio.run(_run())
    if job_id is None:
        return None
    job = db.get_mcp_discovery_job(tenant_id, job_id) or {}
    if job.get("status") != "failed":
        return None
    result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
    error = result.get("error") if isinstance(result.get("error"), Mapping) else {}
    return str(error.get("code") or "unknown")


# ---------------------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------------------


class McpRegistrySource(ConnectorRefreshSource):
    """``mcp-registry``: the servers of an upstream MCP registry, synced into the MCP server catalog.

    Args:
        connector: The connector row.
        credentials: ``{"token": …}`` and/or ``{"apiKey": …}``, or ``None``.
        transport: An httpx transport override (tests drive a fake registry through it).
        discover: Discovery runner override (tests); defaults to a registry-triggered discovery run.
        address_check: Remote URL policy override (tests); defaults to the connector SSRF rule.
    """

    #: MCP servers are not APIs a gateway serves: no shadow-API notification for new entries.
    reports_shadow_apis = False

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        discover: Optional[Discover] = None,
        address_check: Optional[Callable[[str], Any]] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self._transport = transport
        self._discover = discover or _default_discover
        self._address_check = address_check or connector_base_url_from_settings
        self._entries: Dict[str, RegistryServer] = {}
        #: Inventory-wide notes for the run summary (entries marked deprecated or deleted).
        self.findings: List[Dict[str, Any]] = []

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    @property
    def registry_url(self) -> str:
        return normalize_registry_base(str(self.connector.get("base_url") or ""))

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        creds = self.credentials or {}
        token = str(creds.get("token") or "").strip()
        api_key = str(creds.get("apiKey") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

    def list_candidates(self) -> List[RefreshCandidate]:
        """Page through ``/v0.1/servers`` and return one candidate per server name.

        Raises:
            RefreshSourceError: No base URL, or the registry client failed
                (:class:`app.mcp_registry_client.McpRegistryClientError`: a refusal, no answer, a
                body that is not a ``ServerList``, or more than :data:`MAX_PAGES` pages).
        """
        if not self.registry_url:
            raise RefreshSourceError(
                "An MCP registry connector needs a base URL (the registry root).",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        search = self.scope.get("search")
        since = self.scope.get("updatedSince")
        with McpRegistryClient(self.registry_url, headers=self._headers(), transport=self._transport) as client:
            entries = client.list_servers(
                limit=PAGE_SIZE,
                search=search if isinstance(search, str) else None,
                updated_since=since.strip() if isinstance(since, str) and since.strip() else None,
                include_deleted=True,
                max_pages=MAX_PAGES,
            )
        self._entries = {entry.name: entry for entry in latest_servers(entries)}
        self.findings = status_findings(list(self._entries.values()))
        return [build_candidate(entry, registry_url=self.registry_url) for entry in self._entries.values()]

    def freshness_key(self, candidate: RefreshCandidate) -> FreshnessKey:
        """The entry revision against the anchor of its last import.

        An entry that is not imported yet, or stayed ``discovered``, has no anchor, so every sync
        tries it again. Neither does an entry whose registry status changed since its import
        (V2-MCP-26.3): a registry that flips the status without moving ``updatedAt`` must still have
        the change recorded, and the newer-than rule would otherwise trust the unchanged date.
        """
        row = self._inventory.get(candidate.remote_id) or {}
        if (
            not row.get("mcp_endpoint_id")
            or row.get("discovered_reason")
            or revision_status(candidate.revision) != revision_status(row.get("imported_revision"))
        ):
            return FreshnessKey(remote_checksum=candidate.revision)
        return FreshnessKey(
            remote_updated_at=candidate.updated_at,
            remote_checksum=candidate.revision,
            last_updated_at=row.get("imported_remote_updated_at"),
            last_checksum=row.get("imported_revision"),
        )

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """The entry's ``server.json`` (the engine syncs entries with :meth:`sync_item` instead)."""
        entry = self._entry(candidate)
        return FetchedDocument(
            content=json.dumps(dict(entry.server), sort_keys=True, default=str).encode("utf-8"),
            filename="server.json",
            import_kind="json",
            revision=candidate.revision,
        )

    def _entry(self, candidate: RefreshCandidate) -> RegistryServer:
        entry = self._entries.get(candidate.remote_id)
        if entry is None:
            raise RefreshSourceError(
                f"MCP registry server {candidate.remote_id} was not in this sync's inventory.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return entry

    def sync_item(
        self, db: Any, candidate: RefreshCandidate, row: Mapping[str, Any], actor_id: Optional[str]
    ) -> ItemSyncOutcome:
        """Create or refresh the MCP server for one entry, link its sources and discover it.

        Args:
            db: Database handle.
            candidate: The entry's candidate.
            row: Its inventory row (``mcp_endpoint_id`` when a server already exists).
            actor_id: Who asked; the sweep passes ``None`` and the connector's creator is used.

        Returns:
            The outcome: the server id, and the reason when the entry stays ``discovered``.

        Raises:
            RefreshSourceError: The entry is not in this sync's inventory, or the connector has no
                creator to own a new server.
        """
        entry = self._entry(candidate)
        known_id = str(row["mcp_endpoint_id"]) if row.get("mcp_endpoint_id") else None
        if split_server_name(entry.name) is None:
            return ItemSyncOutcome(
                mcp_endpoint_id=known_id,
                discovered_reason=(
                    f"{REASON_NAME_NOT_NAMESPACED}: {entry.name[:_NAME_MAX]!r} is not a reverse-DNS namespaced "
                    "server name (<namespace>/<server>, for example io.github.acme/weather)."
                ),
            )
        if known_id is None:
            known_id, duplicate = self._claim_name(db, entry)
            if duplicate:
                return ItemSyncOutcome(discovered_reason=duplicate)
        if entry.status == "deleted":
            return self._mark_deleted(db, entry, known_id)
        choice = select_remote(entry.server)
        if isinstance(choice, str):
            return ItemSyncOutcome(mcp_endpoint_id=known_id, discovered_reason=choice)
        transport, url = choice
        try:
            self._address_check(url)
        except ConnectorError as exc:
            return ItemSyncOutcome(mcp_endpoint_id=known_id, discovered_reason=f"{REASON_REMOTE_REFUSED}: {exc}")

        endpoint = self._upsert_endpoint(db, entry, candidate, known_id, transport, url, actor_id)
        endpoint_id = str(endpoint["id"])
        self._record_registry_metadata(db, endpoint, entry, transport, url)
        self._link_sources(db, endpoint_id, entry, actor_id)
        code = self._discover(endpoint)
        if code in UNREACHABLE_DISCOVERY_CODES:
            where = remote_url(url) or "the remote"
            return ItemSyncOutcome(
                mcp_endpoint_id=endpoint_id,
                discovered_reason=f"{REASON_DISCOVERY_UNREACHABLE}: discovery could not reach {where} ({code}).",
            )
        return ItemSyncOutcome(mcp_endpoint_id=endpoint_id)

    def _claim_name(self, db: Any, entry: RegistryServer) -> Tuple[Optional[str], Optional[str]]:
        """Find the MCP server that already carries the entry's name, if any.

        One registry server name is one MCP server per tenant. A server imported from the same
        registry (another connector with another search) is adopted; one imported from a different
        registry keeps the name, and this entry stays ``discovered``.

        Returns:
            ``(endpoint id to refresh or None, duplicate reason or None)``.
        """
        existing = db.find_registry_mcp_endpoint(str(self.connector["tenant_id"]), entry.name)
        if not existing:
            return None, None
        metadata = existing.get("registry_metadata") if isinstance(existing.get("registry_metadata"), Mapping) else {}
        other = normalize_registry_base(str(metadata.get("registryUrl") or ""))
        if other == self.registry_url:
            return str(existing["id"]), None
        return None, (
            f"{REASON_DUPLICATE_NAME}: {entry.name} is already in the catalog from {other or 'another registry'} "
            f"(MCP server {existing.get('slug') or existing['id']}); one name is one MCP server."
        )

    def _mark_deleted(self, db: Any, entry: RegistryServer, known_id: Optional[str]) -> ItemSyncOutcome:
        """Record a ``deleted`` entry: its MCP server (when there is one) is kept and marked deleted.

        Nothing is created, discovered or linked; the row stays ``discovered`` with the reason.
        """
        reason = f"{REASON_REGISTRY_DELETED}: the registry marks {entry.name} deleted"
        endpoint = db.get_mcp_endpoint(str(self.connector["tenant_id"]), known_id) if known_id else None
        if not endpoint:
            return ItemSyncOutcome(discovered_reason=f"{reason}; nothing was imported.")
        self._record_registry_metadata(
            db, endpoint, entry, str(endpoint.get("transport") or ""), str(endpoint.get("endpoint_url") or "")
        )
        return ItemSyncOutcome(
            mcp_endpoint_id=str(endpoint["id"]),
            discovered_reason=f"{reason}; its MCP server is kept and marked deleted.",
        )

    def _record_registry_metadata(
        self, db: Any, endpoint: Mapping[str, Any], entry: RegistryServer, transport: str, url: str
    ) -> None:
        """Store what the registry says about the entry on its endpoint (V2-MCP-26.2, #3708).

        ``version``, ``websiteUrl``, the ``_meta`` status and dates, and the chosen remote with the
        headers it declares (secret header values are never kept); written only when it changed.
        """
        metadata = registry_metadata(
            entry.server, entry.official, registry_url=self.registry_url, transport=transport, url=url
        )
        if endpoint.get("registry_metadata") != metadata:
            db.set_mcp_endpoint_registry_metadata(str(self.connector["tenant_id"]), str(endpoint["id"]), metadata)

    def _upsert_endpoint(
        self,
        db: Any,
        entry: RegistryServer,
        candidate: RefreshCandidate,
        known_id: Optional[str],
        transport: str,
        url: str,
        actor_id: Optional[str],
    ) -> Mapping[str, Any]:
        """Refresh the entry's MCP server from the registry, or create it (``added_via = 'registry'``)."""
        tenant_id = str(self.connector["tenant_id"])
        description = str(entry.server.get("description") or "").strip() or None
        name = (candidate.name or entry.name)[:200]
        if known_id:
            existing = db.get_mcp_endpoint(tenant_id, known_id)
            if existing:
                fields = {
                    key: value
                    for key, value in (
                        ("name", name),
                        ("endpoint_url", url),
                        ("transport", transport),
                        ("description", description),
                    )
                    if existing.get(key) != value
                }
                return (db.update_mcp_endpoint(tenant_id, known_id, fields) if fields else existing) or existing
        creator = actor_id or self.connector.get("created_by")
        if not creator:
            raise RefreshSourceError(
                "The connector has no creator to own the MCP servers it adds; run the sync as a member.",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        return db.insert_mcp_endpoint(
            tenant_id=tenant_id,
            creator_id=str(creator),
            name=name,
            base_slug=_slug_for(entry.name),
            endpoint_url=url,
            transport=transport,
            description=description,
            added_via="registry",
        )

    def _link_sources(self, db: Any, endpoint_id: str, entry: RegistryServer, actor_id: Optional[str]) -> None:
        """Link the entry's sources and retire the ones this connector linked that it no longer lists."""
        tenant_id = str(self.connector["tenant_id"])
        connector_id = str(self.connector.get("id"))
        links = registry_source_links(entry, connector=self.connector, registry_url=self.registry_url)
        for link in links:
            db.create_mcp_endpoint_source(
                tenant_id=tenant_id, endpoint_id=endpoint_id, source=link.as_dict(), linked_by=actor_id
            )
        current = {(link.source_kind, link.locator) for link in links}
        for source in db.list_mcp_endpoint_sources(endpoint_id):
            detail = source.get("provenance_detail") if isinstance(source.get("provenance_detail"), Mapping) else {}
            if (
                source.get("provenance") == PROVENANCE_REGISTRY
                and str(detail.get("connectorId")) == connector_id
                and (source.get("source_kind"), source.get("locator")) not in current
            ):
                db.retire_mcp_endpoint_source(endpoint_id, str(source["id"]))

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, registryUrl, search}``."""
        return {**super().describe(), "registryUrl": self.registry_url, "search": self.scope.get("search")}


register_connector_source(KIND, McpRegistrySource, scope_validator=validate_mcp_registry_scope)
