"""Upstream MCP registry connector: ``GET /v0.1/servers`` into the MCP server catalog — CDG-4.4 (#5976).

An ``mcp-registry`` connector points at any registry that speaks the MCP Registry API v0.1: the
official registry (``https://registry.modelcontextprotocol.io``), Azure API Center, a Kong registry
or another Apiome tenant (``https://<apiome>/registry/mcp/<tenant>``, CDG-4.1). It runs on the
CDG-1.1 connector protocol — one cadence, quota and ledger with every other connector — but its
entries become **MCP servers** (``apiome.mcp_endpoints``, ``added_via = 'registry'``), not catalog
items, so the source syncs each entry itself (the engine's ``sync_item`` hook).

**Listing.** The source pages ``GET {base}/v0.1/servers`` (``limit``, ``cursor`` from
``metadata.nextCursor``, ``version=latest``) with the connector scope's ``search`` and
``updatedSince`` (sent as ``updated_since``) filters. The base URL is the registry root; a trailing
``/v0.1`` or ``/v0.1/servers`` is accepted and dropped. Each server name is one inventory row
(``remoteId``); a name listed in several versions keeps its ``isLatest`` entry, and an entry the
registry marks ``deleted`` is left out, so its row turns ``missing``. ``updatedSince`` is a fixed
filter, never advanced by a sync: an entry the filter hides is reported missing.

**Syncing one entry** (only entries whose content changed since the last import — the revision is
the server version plus a digest of the whole ``server.json``):

1. **Pick a remote.** The first ``remotes[]`` entry of type ``streamable-http`` or ``sse`` with a
   concrete ``http(s)`` URL. No such remote (a package-only server runs locally over stdio, or its
   URL is a template with ``{variables}``), or a URL the connector address policy refuses
   (:func:`app.catalog_connectors.connector_base_url_from_settings`), leaves the row
   ``discovered`` with the reason and creates nothing.
2. **Create or refresh the MCP server.** A new entry inserts an endpoint (private, unpublished,
   ``added_via = 'registry'``); a known one has its name, URL, transport and description refreshed
   from the registry.
3. **Link sources** (``apiome.mcp_endpoint_sources``, provenance ``registry_published``): the
   registry identity itself, ``repository.url`` as a git source and every ``packages[]`` entry of a
   known ecosystem (npm, PyPI, NuGet, Cargo as package sources; OCI as an image). Each link records
   the connector in its ``provenance_detail``, and a link this connector made that the registry no
   longer lists is retired. Nothing is invented: a package version is pinned only when the registry
   names an exact one.
4. **Run discovery** (``trigger = 'registry'``), which also lints and scores the new snapshot. When
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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from urllib.parse import quote, urlsplit

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, ItemSyncOutcome, register_connector_source
from .catalog_connectors import (
    CODE_INVALID,
    ConnectorError,
    build_connector_http_client,
    connector_base_url_from_settings,
)
from .mcp_registry import remote_url
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
from .ssrf_guard import SSRFError

_logger = logging.getLogger(__name__)

__all__ = [
    "KIND",
    "McpRegistrySource",
    "REASON_DISCOVERY_UNREACHABLE",
    "REASON_NO_REMOTE",
    "REASON_REMOTE_REFUSED",
    "REASON_REMOTE_TEMPLATED",
    "RegistryServer",
    "build_candidate",
    "latest_servers",
    "normalize_registry_base",
    "parse_server_entry",
    "registry_source_links",
    "select_remote",
    "validate_mcp_registry_scope",
]

KIND = "mcp-registry"

#: The registry API path the source pages (relative to the registry root).
SERVERS_PATH = "/v0.1/servers"

#: Entries requested per page, and the most pages followed (10 000 servers).
PAGE_SIZE = 100
MAX_PAGES = 100

#: Scope keys the kind accepts.
SCOPE_KEYS = ("search", "updatedSince")
_SEARCH_MAX = 200

#: Error class for a scope or base URL that cannot address a registry.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"
#: Error class for a request the SSRF guard refused (a redirect or re-resolution to a private address).
ERROR_CLASS_ADDRESS_REFUSED = "address-refused"

#: Stable reason codes an entry stays ``discovered`` with (the stored reason is ``"<code>: <why>"``).
REASON_NO_REMOTE = "no-remote"
REASON_REMOTE_TEMPLATED = "remote-templated"
REASON_REMOTE_REFUSED = "remote-refused"
REASON_DISCOVERY_UNREACHABLE = "remote-unreachable"

#: Registry remote types → catalog transports.
_TRANSPORTS = {"streamable-http": "streamable_http", "sse": "sse"}

#: Discovery error codes that mean the remote was never reached (``app.mcp_client.errors``).
UNREACHABLE_DISCOVERY_CODES = frozenset(
    {"connect_timeout", "timeout", "connect_error", "tls_error", "ssrf_blocked", "budget_exceeded"}
)

#: Registry package types that are Package URL ecosystems (``registryType`` → purl type).
_PURL_TYPES = {"npm": "npm", "pypi": "pypi", "nuget": "nuget", "cargo": "cargo"}

#: The ``_meta`` key of the official registry's status fields.
_OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"

_ERROR_DETAIL_MAX = 300
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


def normalize_registry_base(url: str) -> str:
    """Return the registry root: trailing ``/``, ``/v0.1`` and ``/v0.1/servers`` removed.

    Args:
        url: The connector base URL.

    Returns:
        The root the source appends :data:`SERVERS_PATH` to.
    """
    base = (url or "").strip().rstrip("/")
    for suffix in (SERVERS_PATH, "/v0.1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    return base


# ---------------------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryServer:
    """One registry entry: its ``server.json`` and the official status metadata.

    Attributes:
        server: The ``server.json`` document (``name``, ``version``, ``remotes``, ``packages``, …).
        official: ``_meta["io.modelcontextprotocol.registry/official"]`` (``status``,
            ``isLatest``, ``publishedAt``, ``updatedAt``), or ``{}``.
    """

    server: Mapping[str, Any]
    official: Mapping[str, Any]

    @property
    def name(self) -> str:
        return str(self.server.get("name") or "")

    @property
    def version(self) -> str:
        return str(self.server.get("version") or "").strip()


def parse_server_entry(entry: Any) -> Optional[RegistryServer]:
    """Read one ``servers[]`` element of a ``ServerList``.

    Accepts the v0.1 shape (``{"server": {...}, "_meta": {...}}``) and the older flat shape (the
    server's fields at the top level, ``_meta`` beside them).

    Args:
        entry: The list element.

    Returns:
        The entry, or ``None`` when it has no server name or the registry marks it ``deleted``.
    """
    if not isinstance(entry, Mapping):
        return None
    server = entry.get("server") if isinstance(entry.get("server"), Mapping) else entry
    meta = entry.get("_meta") if isinstance(entry.get("_meta"), Mapping) else server.get("_meta")
    official = meta.get(_OFFICIAL_META_KEY) if isinstance(meta, Mapping) else None
    official = official if isinstance(official, Mapping) else {}
    name = server.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if str(official.get("status") or "").lower() == "deleted":
        return None
    return RegistryServer(server=server, official=official)


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


def entry_revision(server: Mapping[str, Any]) -> str:
    """The entry's revision: its version plus a digest of the whole ``server.json``.

    A digest, not the version alone, because a registry other than the official one may change a
    remote URL or a package without bumping the version.
    """
    digest = hashlib.sha256(json.dumps(server, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
    version = str(server.get("version") or "").strip()
    return f"{version}+sha256.{digest}" if version else f"sha256.{digest}"


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
        revision=entry_revision(server),
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
    """A catalog slug for a registry server name (its last path segment, slugified)."""
    tail = name.rsplit("/", 1)[-1]
    return _SLUG_UNSAFE.sub("-", tail.lower()).strip("-")[:60] or "mcp-server"


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


def _error_detail(response: httpx.Response) -> str:
    """The human part of a registry error body (problem JSON ``title`` / ``detail`` / ``message``)."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:_ERROR_DETAIL_MAX]
    if not isinstance(body, Mapping):
        return ""
    parts = [str(body[k]) for k in ("title", "detail", "message") if isinstance(body.get(k), str) and body.get(k)]
    return ": ".join(dict.fromkeys(parts))[:_ERROR_DETAIL_MAX]


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

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    @property
    def registry_url(self) -> str:
        return normalize_registry_base(str(self.connector.get("base_url") or ""))

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        creds = self.credentials or {}
        token = str(creds.get("token") or "").strip()
        api_key = str(creds.get("apiKey") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if api_key:
            headers["X-API-Key"] = api_key
        return headers

    def _get(self, client: httpx.Client, params: Mapping[str, Any]) -> Mapping[str, Any]:
        """GET one ``ServerList`` page.

        Raises:
            RefreshSourceError: The registry answered non-2xx, did not answer, the SSRF guard
                refused the address, or the body is not a ``ServerList``.
        """
        url = f"{self.registry_url}{SERVERS_PATH}"
        try:
            response = client.get(url, params=dict(params))
        except SSRFError as exc:
            raise RefreshSourceError(
                f"Request to the MCP registry refused: {exc}", error_class=ERROR_CLASS_ADDRESS_REFUSED
            ) from exc
        except httpx.HTTPError as exc:
            raise RefreshSourceError(
                f"The MCP registry did not answer GET {SERVERS_PATH}: {type(exc).__name__}"
            ) from exc
        if not 200 <= response.status_code < 300:
            detail = _error_detail(response)
            raise RefreshSourceError(
                f"The MCP registry answered {response.status_code} to GET {SERVERS_PATH}"
                + (f": {detail}" if detail else ""),
                http_status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise RefreshSourceError(
                f"The MCP registry answered GET {SERVERS_PATH} with a body that is not JSON.",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            ) from exc
        if not isinstance(body, Mapping) or not isinstance(body.get("servers"), list):
            raise RefreshSourceError(
                f"The MCP registry answered GET {SERVERS_PATH} with an unexpected body (no servers list).",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return body

    def list_candidates(self) -> List[RefreshCandidate]:
        """Page through ``/v0.1/servers`` and return one candidate per server name."""
        if not self.registry_url:
            raise RefreshSourceError(
                "An MCP registry connector needs a base URL (the registry root).",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        params: Dict[str, Any] = {"limit": PAGE_SIZE, "version": "latest"}
        if isinstance(self.scope.get("search"), str) and self.scope["search"].strip():
            params["search"] = self.scope["search"].strip()
        if isinstance(self.scope.get("updatedSince"), str) and self.scope["updatedSince"].strip():
            params["updated_since"] = self.scope["updatedSince"].strip()
        kwargs: Dict[str, Any] = {"headers": self._headers(), "timeout": 30.0}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        entries: List[RegistryServer] = []
        client = build_connector_http_client(**kwargs)
        try:
            cursor: Optional[str] = None
            seen_cursors = set()
            for _ in range(MAX_PAGES):
                page = dict(params, **({"cursor": cursor} if cursor else {}))
                body = self._get(client, page)
                entries.extend(e for e in map(parse_server_entry, body["servers"]) if e is not None)
                metadata = body.get("metadata") if isinstance(body.get("metadata"), Mapping) else {}
                cursor = metadata.get("nextCursor") if isinstance(metadata.get("nextCursor"), str) else None
                if not cursor or cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
            else:
                raise RefreshSourceError(
                    f"The MCP registry lists more than {MAX_PAGES * PAGE_SIZE} servers; narrow it with a search.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
        finally:
            client.close()
        self._entries = {entry.name: entry for entry in latest_servers(entries)}
        return [build_candidate(entry, registry_url=self.registry_url) for entry in self._entries.values()]

    def freshness_key(self, candidate: RefreshCandidate) -> FreshnessKey:
        """The entry revision against the anchor of its last import.

        An entry that is not imported yet, or stayed ``discovered``, has no anchor, so every sync
        tries it again.
        """
        row = self._inventory.get(candidate.remote_id) or {}
        if not row.get("mcp_endpoint_id") or row.get("discovered_reason"):
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
        self._link_sources(db, endpoint_id, entry, actor_id)
        code = self._discover(endpoint)
        if code in UNREACHABLE_DISCOVERY_CODES:
            where = remote_url(url) or "the remote"
            return ItemSyncOutcome(
                mcp_endpoint_id=endpoint_id,
                discovered_reason=f"{REASON_DISCOVERY_UNREACHABLE}: discovery could not reach {where} ({code}).",
            )
        return ItemSyncOutcome(mcp_endpoint_id=endpoint_id)

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
