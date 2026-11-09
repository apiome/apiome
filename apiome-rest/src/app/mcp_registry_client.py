"""Client for an upstream MCP Registry API v0.1 (``/v0.1/servers``) — V2-MCP-26.1 / MCAT-12.1 (#3707).

The official MCP registry (``https://registry.modelcontextprotocol.io``, staging at
``https://staging.registry.modelcontextprotocol.io``) is the canonical upstream of MCP servers. This
module reads any registry that speaks its API — the official one, Azure API Center, a Kong registry
or another Apiome tenant — through two calls
(`official registry API <https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md>`_):

* ``GET /v0.1/servers`` — a ``ServerList`` page. :meth:`McpRegistryClient.list_servers_page` sends
  ``limit``, ``cursor``, ``search``, ``updated_since`` and ``version`` (``latest`` by default);
  :meth:`McpRegistryClient.iter_servers` follows ``metadata.nextCursor`` until the registry stops
  sending one.
* ``GET /v0.1/servers/{name}/versions/{version}`` — one ``ServerResponse``
  (:meth:`McpRegistryClient.get_server_version`); ``version`` may be ``latest``.

Design rules:

* **Pinned to v0.1.** Every path starts with :data:`API_PREFIX`; a base URL that already ends in
  ``/v0.1`` or ``/v0.1/servers`` is reduced to the registry root (:func:`normalize_registry_base`).
* **The schema is a moving preview.** Unknown fields are kept as they are; an entry in the flat
  shape (server fields at the top level) or an earlier snake_case draft reads as the current
  camelCase one (:func:`parse_server_entry`); an element with no server name is skipped rather than
  failing the page; ``metadata.next_cursor`` (an earlier draft) is read when ``nextCursor`` is absent.
* **Cursors are respected, not trusted.** Paging stops when no cursor comes back, and also when a
  cursor repeats (a registry that loops); more than ``max_pages`` pages is an error, never a silent
  truncation.
* **Guarded by default.** Without an injected ``httpx.Client`` the client builds one with
  :func:`app.catalog_connectors.build_connector_http_client`, which re-checks the SSRF rule on every
  request and redirect.

Every failure is a :class:`McpRegistryClientError` — a :class:`app.refresh_source.RefreshSourceError`,
so a connector source can let it propagate and the sync records its status and class.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Union
from urllib.parse import quote

import httpx

from .catalog_connectors import build_connector_http_client
from .mcp_server_json import camelize, normalize_server_json
from .refresh_source import ERROR_CLASS_UNEXPECTED, RefreshSourceError
from .ssrf_guard import SSRFError

__all__ = [
    "API_PREFIX",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_MAX_PAGES",
    "ERROR_CLASS_ADDRESS_REFUSED",
    "McpRegistryClient",
    "McpRegistryClientError",
    "OFFICIAL_REGISTRY_URL",
    "RegistryServer",
    "SERVERS_PATH",
    "STAGING_REGISTRY_URL",
    "ServerPage",
    "normalize_registry_base",
    "parse_server_entry",
    "server_version_path",
]

#: The official registry and its staging deployment (registry roots, no ``/v0.1``).
OFFICIAL_REGISTRY_URL = "https://registry.modelcontextprotocol.io"
STAGING_REGISTRY_URL = "https://staging.registry.modelcontextprotocol.io"

#: The API version every request is pinned to, and the list path under it.
API_PREFIX = "/v0.1"
SERVERS_PATH = f"{API_PREFIX}/servers"

#: Entries requested per page (the registry's maximum), and the most pages followed (10 000 servers).
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 100

#: The ``version`` filter / path value that selects each server's latest version.
LATEST = "latest"

#: Error class for a request the SSRF guard refused (a redirect or re-resolution to a private address).
ERROR_CLASS_ADDRESS_REFUSED = "address-refused"

#: The ``_meta`` key of the official registry's status fields.
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"

_ERROR_DETAIL_MAX = 300
_DEFAULT_TIMEOUT = 30.0


class McpRegistryClientError(RefreshSourceError):
    """The registry refused, did not answer, or answered with a body that is not the v0.1 shape.

    Attributes:
        http_status: The registry's HTTP status, or ``None`` when there was no answer.
        error_class: A stable class (``auth``, ``not-found``, ``unexpected``, ``address-refused``, …).
    """


# ---------------------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryServer:
    """One registry entry: its ``server.json`` and the official status metadata.

    Attributes:
        server: The ``server.json`` document (``name``, ``version``, ``remotes``, ``packages``, …),
            normalized to camelCase; fields this module does not know are kept.
        official: ``_meta["io.modelcontextprotocol.registry/official"]`` (``status``,
            ``isLatest``, ``publishedAt``, ``updatedAt``), or ``{}``.
    """

    server: Mapping[str, Any]
    official: Mapping[str, Any]

    @property
    def name(self) -> str:
        """The server name (``io.github.acme/weather``)."""
        return str(self.server.get("name") or "")

    @property
    def version(self) -> str:
        """The server version, or ``""`` when the entry names none."""
        return str(self.server.get("version") or "").strip()

    @property
    def status(self) -> str:
        """The registry status in lower case (``active``, ``deprecated``, ``deleted``), or ``""``."""
        return str(self.official.get("status") or "").strip().lower()


def parse_server_entry(entry: Any, *, include_deleted: bool = False) -> Optional[RegistryServer]:
    """Read one ``servers[]`` element of a ``ServerList``, or a ``ServerResponse``.

    Accepts the v0.1 shape (``{"server": {...}, "_meta": {...}}``) and the older flat shape (the
    server's fields at the top level, ``_meta`` beside them), in the current camelCase draft or an
    earlier snake_case one (:func:`app.mcp_server_json.normalize_server_json`).

    Args:
        entry: The list element or response body.
        include_deleted: Keep an entry the registry marks ``deleted`` (a version lookup reports it;
            a listing leaves it out).

    Returns:
        The entry, or ``None`` when it has no server name, or is ``deleted`` and not asked for.
    """
    if not isinstance(entry, Mapping):
        return None
    server = entry.get("server") if isinstance(entry.get("server"), Mapping) else entry
    meta = entry.get("_meta") if isinstance(entry.get("_meta"), Mapping) else server.get("_meta")
    official = meta.get(OFFICIAL_META_KEY) if isinstance(meta, Mapping) else None
    # An entry in an earlier snake_case draft reads as the current camelCase one (V2-MCP-26.2).
    official = camelize(official) if isinstance(official, Mapping) else {}
    server = normalize_server_json(server)
    name = server.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    parsed = RegistryServer(server=server, official=official)
    if parsed.status == "deleted" and not include_deleted:
        return None
    return parsed


@dataclass(frozen=True)
class ServerPage:
    """One ``GET /v0.1/servers`` page.

    Attributes:
        servers: The page's readable entries, in listed order (deleted and nameless ones left out).
        next_cursor: The cursor of the next page, or ``None`` on the last page.
        listed: How many elements the page's ``servers`` array held, readable or not.
    """

    servers: List[RegistryServer]
    next_cursor: Optional[str]
    listed: int


# ---------------------------------------------------------------------------------------
# URLs and parameters
# ---------------------------------------------------------------------------------------


def normalize_registry_base(url: str) -> str:
    """Return the registry root: trailing ``/``, ``/v0.1`` and ``/v0.1/servers`` removed.

    Args:
        url: A registry URL as an operator typed it.

    Returns:
        The root the client appends :data:`SERVERS_PATH` to.
    """
    base = (url or "").strip().rstrip("/")
    for suffix in (SERVERS_PATH, API_PREFIX):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
    return base


def server_version_path(name: str, version: str = LATEST) -> str:
    """The path of one server version: ``/v0.1/servers/{name}/versions/{version}``.

    The name's ``/`` (``io.github.acme/weather``) is percent-encoded, as the API requires.

    Args:
        name: The server name.
        version: An exact version, or ``latest``.

    Returns:
        The path, relative to the registry root.
    """
    return f"{SERVERS_PATH}/{quote(name, safe='')}/versions/{quote(version, safe='')}"


def _instant(value: Union[str, datetime]) -> str:
    """An ``updated_since`` value: a string as given, a datetime as RFC 3339 UTC (``…Z``)."""
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value.strip()


def _next_cursor(body: Mapping[str, Any]) -> Optional[str]:
    """``metadata.nextCursor`` (or an earlier draft's ``next_cursor``) when it is a non-empty string."""
    metadata = body.get("metadata") if isinstance(body.get("metadata"), Mapping) else {}
    for key in ("nextCursor", "next_cursor"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return None


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


# ---------------------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------------------


class McpRegistryClient:
    """Reads servers from one MCP registry over the v0.1 API.

    Use it as a context manager (or call :meth:`close`) so a client it built is closed; an injected
    ``http_client`` is left open for its owner.

    Args:
        base_url: The registry root (``https://registry.modelcontextprotocol.io``); a trailing
            ``/v0.1`` or ``/v0.1/servers`` is accepted and dropped.
        headers: Extra request headers (a bearer token, ``X-API-Key``); ``Accept`` is always JSON.
        http_client: An ``httpx.Client`` to send through instead of a guarded one built here.
        transport: An httpx transport for the built client (tests drive a fake registry with it).
        timeout: Seconds per request for the built client.

    Raises:
        ValueError: ``base_url`` is blank.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        http_client: Optional[httpx.Client] = None,
        transport: Optional[httpx.BaseTransport] = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = normalize_registry_base(base_url)
        if not self.base_url:
            raise ValueError("An MCP registry client needs a base URL (the registry root).")
        self._headers = {"Accept": "application/json", **dict(headers or {})}
        self._owns_client = http_client is None
        if http_client is None:
            kwargs: Dict[str, Any] = {"timeout": timeout}
            if transport is not None:
                kwargs["transport"] = transport
            http_client = build_connector_http_client(**kwargs)
        self._client = http_client

    def __enter__(self) -> "McpRegistryClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client when this object built it."""
        if self._owns_client:
            self._client.close()

    def _get_json(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        """GET ``{base}{path}`` and return the decoded JSON body.

        Args:
            path: The path under the registry root (starts with :data:`API_PREFIX`).
            params: Query parameters; ``None`` values are left out.

        Returns:
            The decoded body.

        Raises:
            McpRegistryClientError: The SSRF guard refused the address, the registry did not
                answer, answered non-2xx, or answered with a body that is not JSON.
        """
        query = {key: value for key, value in (params or {}).items() if value is not None}
        label = path
        try:
            response = self._client.get(f"{self.base_url}{path}", params=query, headers=self._headers)
        except SSRFError as exc:
            raise McpRegistryClientError(
                f"Request to the MCP registry refused: {exc}", error_class=ERROR_CLASS_ADDRESS_REFUSED
            ) from exc
        except httpx.HTTPError as exc:
            raise McpRegistryClientError(f"The MCP registry did not answer GET {label}: {type(exc).__name__}") from exc
        if not 200 <= response.status_code < 300:
            detail = _error_detail(response)
            raise McpRegistryClientError(
                f"The MCP registry answered {response.status_code} to GET {label}" + (f": {detail}" if detail else ""),
                http_status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise McpRegistryClientError(
                f"The MCP registry answered GET {label} with a body that is not JSON.",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            ) from exc

    def list_servers_page(
        self,
        *,
        cursor: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
        search: Optional[str] = None,
        updated_since: Optional[Union[str, datetime]] = None,
        version: Optional[str] = LATEST,
    ) -> ServerPage:
        """Fetch one ``GET /v0.1/servers`` page.

        Args:
            cursor: The previous page's ``nextCursor``; ``None`` for the first page.
            limit: Entries per page (the official registry allows 1–100).
            search: A substring the registry matches against server names.
            updated_since: Only servers updated after this instant (RFC 3339 string or datetime).
            version: ``latest`` (default) for each server's latest version, an exact version, or
                ``None`` to list every version.

        Returns:
            The page.

        Raises:
            McpRegistryClientError: As :meth:`_get_json`, or the body has no ``servers`` list.
        """
        body = self._get_json(
            SERVERS_PATH,
            {
                "limit": limit,
                "cursor": cursor or None,
                "search": (search or "").strip() or None,
                "updated_since": _instant(updated_since) if updated_since else None,
                "version": version or None,
            },
        )
        if not isinstance(body, Mapping) or not isinstance(body.get("servers"), list):
            raise McpRegistryClientError(
                f"The MCP registry answered GET {SERVERS_PATH} with an unexpected body (no servers list).",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        listed = body["servers"]
        servers = [entry for entry in map(parse_server_entry, listed) if entry is not None]
        return ServerPage(servers=servers, next_cursor=_next_cursor(body), listed=len(listed))

    def iter_servers(
        self,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        search: Optional[str] = None,
        updated_since: Optional[Union[str, datetime]] = None,
        version: Optional[str] = LATEST,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> Iterator[RegistryServer]:
        """Yield every listed server, following ``metadata.nextCursor`` page by page.

        Paging stops when a page carries no cursor, or repeats one already followed.

        Args:
            limit, search, updated_since, version: As :meth:`list_servers_page`.
            max_pages: The most pages followed.

        Yields:
            Each readable entry, in listed order (a name listed in several versions appears once
            per version when ``version`` is ``None``).

        Raises:
            McpRegistryClientError: A page failed, or the registry still had a next page after
                ``max_pages`` pages.
        """
        cursor: Optional[str] = None
        seen = set()
        for _ in range(max_pages):
            page = self.list_servers_page(
                cursor=cursor, limit=limit, search=search, updated_since=updated_since, version=version
            )
            yield from page.servers
            cursor = page.next_cursor
            if not cursor or cursor in seen:
                return
            seen.add(cursor)
        raise McpRegistryClientError(
            f"The MCP registry lists more than {max_pages * limit} servers; narrow it with a search.",
            error_class=ERROR_CLASS_UNEXPECTED,
        )

    def list_servers(self, **kwargs: Any) -> List[RegistryServer]:
        """Every listed server as a list (the arguments of :meth:`iter_servers`)."""
        return list(self.iter_servers(**kwargs))

    def get_server_version(self, name: str, version: str = LATEST) -> Optional[RegistryServer]:
        """Fetch one ``GET /v0.1/servers/{name}/versions/{version}``.

        Args:
            name: The server name (``io.github.acme/weather``).
            version: An exact version, or ``latest`` (default).

        Returns:
            The entry — including one the registry marks ``deleted`` (check
            :attr:`RegistryServer.status`) — or ``None`` when the registry answers ``404``.

        Raises:
            ValueError: ``name`` or ``version`` is blank.
            McpRegistryClientError: As :meth:`_get_json` (other than ``404``), or the body is not a
                ``ServerResponse`` with a server name.
        """
        if not (name or "").strip() or not (version or "").strip():
            raise ValueError("A server version lookup needs a server name and a version.")
        path = server_version_path(name.strip(), version.strip())
        try:
            body = self._get_json(path)
        except McpRegistryClientError as exc:
            if exc.http_status == 404:
                return None
            raise
        entry = parse_server_entry(body, include_deleted=True)
        if entry is None:
            raise McpRegistryClientError(
                f"The MCP registry answered GET {path} with an unexpected body (no server).",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return entry
