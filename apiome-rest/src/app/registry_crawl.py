"""Registry-as-source ingestion: crawl a catalog, not a document — MFI-18.5 (#3978).

The import SPI (:class:`app.import_source.ImportSource`) models "parse one document" and "discover
one live endpoint". Some sources are **catalogs**: an A2A agent registry, a CNCF xRegistry, a FHIR
server's ``/metadata``. This module lets an adapter declare a **registry crawl** — list → page →
fetch each → normalize → version — and runs every declared crawl on the CDG-1.1 catalog connector
engine (:func:`app.catalog_connector_sync.run_connector_sync`), so a crawl gets that engine's
behaviour for free:

* **Individually versioned entries.** Each registry entry is one inventory row and one catalog item;
  a later change to the entry is a new revision of the same item, with a change report.
* **Incremental re-crawl.** An entry whose revision (and, when the registry reports none, whose
  content digest) is unchanged since its last import is skipped; only changed entries are fetched
  and imported again.
* **Per-artifact provenance.** Every revision records the connector, the registry protocol, the
  entry's remote id and revision and its source URL (``format_metadata``).
* **Cadence, tenant quota, run ledger and audit**, as for every connector.

What this module adds on top:

* :class:`RegistryCrawl` — the SPI an adapter's crawl implements (``list_entries`` /
  ``fetch_entry``), registered by protocol with :func:`register_registry_crawl`. An adapter names
  its crawl with :attr:`app.import_source.ImportSource.registry_crawl`.
* :class:`RegistryHttp` — the only HTTP surface a crawl gets: GETs through the connector client
  (:func:`app.catalog_connectors.build_connector_http_client`, which re-checks the SSRF rule on
  every hop and honours the operator allowlist), a **per-host request-rate limit**, a **request
  budget** per sync and a **response-size cap**.
* :func:`paginate` — the bounded page loop every crawl shares (cursor, ``Link: rel="next"`` or a
  ``next`` URL), with a repeated-cursor guard and a page limit.
* :class:`RegistryConnectorSource` — the ``registry`` connector kind: its scope names the crawl
  protocol, and it adapts the crawl's entries to the engine's candidates and documents.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit

import httpx

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, build_connector_http_client
from .refresh_source import (
    ERROR_CLASS_UNEXPECTED,
    FetchedDocument,
    RefreshCandidate,
    RefreshSourceError,
)
from .ssrf_guard import SSRFError

__all__ = [
    "DEFAULT_REQUESTS_PER_SECOND",
    "KIND",
    "MAX_ENTRIES",
    "MAX_PAGES",
    "MAX_REQUESTS",
    "MAX_RESPONSE_BYTES",
    "Page",
    "RegistryConnectorSource",
    "RegistryCrawl",
    "RegistryEntry",
    "RegistryHttp",
    "content_revision",
    "get_registry_crawl",
    "paginate",
    "parse_instant",
    "register_registry_crawl",
    "registry_crawl_protocols",
    "validate_registry_scope",
]

#: The connector kind every registry crawl runs as.
KIND = "registry"

#: Requests per second to one host, by default and at most (scope ``requestsPerSecond``).
DEFAULT_REQUESTS_PER_SECOND = 5.0
MAX_REQUESTS_PER_SECOND = 20.0

#: Requests one sync may make in total (listing + fetches) before it stops.
MAX_REQUESTS = 2000

#: Pages one listing may follow, and entries one crawl may return.
MAX_PAGES = 100
MAX_ENTRIES = 5000

#: The largest response body accepted (a registry page or one artifact).
MAX_RESPONSE_BYTES = 5_000_000

#: Scope keys every registry connector accepts; a crawl adds its own.
COMMON_SCOPE_KEYS = ("protocol", "requestsPerSecond")

#: Error class for a scope or base URL that cannot address a registry.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"
#: Error class for a request the SSRF guard refused.
ERROR_CLASS_ADDRESS_REFUSED = "address-refused"
#: Error class for a sync that ran out of its request budget.
ERROR_CLASS_BUDGET = "budget-exceeded"

_ERROR_DETAIL_MAX = 300


# ---------------------------------------------------------------------------------------
# The crawl SPI
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryEntry:
    """One artifact a registry lists.

    Attributes:
        remote_id: The registry's stable id for the artifact (an agent-card URL, an xRegistry
            path, a profile canonical URL). It keys the inventory row and therefore the catalog item.
        import_kind: The import-source key the artifact is parsed with (``a2a``, ``avro``, …).
        filename: A file name for the import (it labels the source and hints the format).
        name: A display name, when the registry gives one.
        revision: The registry's revision marker (a version, an epoch), when it reports one. With
            none, the engine compares content digests instead.
        updated_at: When the registry says the artifact last changed, when it says.
        document_url: Where :meth:`RegistryCrawl.fetch_entry` gets the document, by default.
        content: The document itself, when the listing already carried it (no fetch needed).
        source_uri: A link to the artifact at the registry, for provenance.
        raw: The registry's listing entry, for display. Never holds credentials.
    """

    remote_id: str
    import_kind: str
    filename: str
    name: Optional[str] = None
    revision: Optional[str] = None
    updated_at: Optional[datetime] = None
    document_url: Optional[str] = None
    content: Optional[bytes] = None
    source_uri: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)


class RegistryCrawl:
    """A crawl an import adapter declares: how to list a registry and fetch each artifact.

    Subclasses set :attr:`protocol` and :attr:`label`, implement :meth:`list_entries`, and override
    :meth:`fetch_entry` only when an artifact is not a plain GET of its ``document_url``. A crawl is
    stateless: it receives the registry root and the connector scope on every call, and reaches the
    network only through the :class:`RegistryHttp` it is handed.
    """

    #: The crawl's protocol id — the connector scope's ``protocol``.
    protocol: str = ""
    #: A display name (``"A2A agent registry"``).
    label: str = ""
    #: The import-source key of the adapter that declares the crawl.
    import_source: str = ""
    #: Scope keys the crawl accepts besides :data:`COMMON_SCOPE_KEYS`.
    scope_keys: Tuple[str, ...] = ()

    def validate_scope(self, scope: Mapping[str, Any]) -> None:
        """Check the crawl's own scope keys (the generic keys are already checked).

        Args:
            scope: The connector scope.

        Raises:
            ConnectorError: ``connector-invalid`` for a value the crawl cannot use.
        """
        del scope

    def list_entries(
        self, http: "RegistryHttp", base_url: str, scope: Mapping[str, Any]
    ) -> List[RegistryEntry]:
        """List every artifact the registry holds.

        Args:
            http: The bounded HTTP surface.
            base_url: The registry root (the connector's base URL, trailing ``/`` removed).
            scope: The connector scope.

        Returns:
            The entries, in the registry's order.

        Raises:
            RefreshSourceError: The registry could not be listed.
        """
        raise NotImplementedError

    def fetch_entry(self, http: "RegistryHttp", entry: RegistryEntry) -> FetchedDocument:
        """Fetch one artifact: its inline ``content``, else a GET of its ``document_url``.

        Args:
            http: The bounded HTTP surface.
            entry: The entry to fetch.

        Returns:
            The document, tagged with the entry's import kind and revision.

        Raises:
            RefreshSourceError: The artifact could not be fetched.
        """
        if entry.content is not None:
            content = entry.content
        elif entry.document_url:
            content = http.get(entry.document_url).content
        else:
            raise RefreshSourceError(
                f"Registry entry {entry.remote_id} has neither a document nor a document URL.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return FetchedDocument(
            content=content,
            filename=entry.filename,
            import_kind=entry.import_kind,
            revision=entry.revision,
            source_uri=entry.source_uri or entry.document_url,
        )


_CRAWLS: Dict[str, RegistryCrawl] = {}


def register_registry_crawl(crawl: RegistryCrawl) -> RegistryCrawl:
    """Register a crawl under its protocol id (idempotent; the last registration wins).

    Args:
        crawl: The crawl instance.

    Returns:
        ``crawl``, so a module can register and keep it in one statement.

    Raises:
        ValueError: The crawl declares no protocol or import source.
    """
    if not crawl.protocol or not crawl.import_source:
        raise ValueError("A registry crawl needs a protocol and an import_source.")
    _CRAWLS[crawl.protocol] = crawl
    return crawl


def get_registry_crawl(protocol: str) -> Optional[RegistryCrawl]:
    """Return the crawl registered for ``protocol``, or ``None``."""
    _load_builtin_crawls()
    return _CRAWLS.get(protocol)


def registry_crawl_protocols() -> List[str]:
    """Every registered crawl protocol, sorted."""
    _load_builtin_crawls()
    return sorted(_CRAWLS)


def _load_builtin_crawls() -> None:
    """Import the built-in crawls (each registers itself)."""
    from . import a2a_registry_crawl, fhir_metadata_crawl, xregistry_crawl  # noqa: F401


# ---------------------------------------------------------------------------------------
# Bounded HTTP
# ---------------------------------------------------------------------------------------


class HostRateLimiter:
    """Space requests to each host at least ``1 / rate`` seconds apart.

    Args:
        requests_per_second: The most requests per second to one host.
        clock: Monotonic clock (tests).
        sleep: Sleep function (tests).
    """

    def __init__(
        self,
        requests_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._next: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        """Block until a request to ``host`` is allowed, then claim the slot.

        Args:
            host: The request's host (``netloc``).
        """
        with self._lock:
            now = self._clock()
            due = self._next.get(host, now)
            delay = max(0.0, due - now)
            self._next[host] = max(due, now) + self._interval
        if delay:
            self._sleep(delay)


@dataclass(frozen=True)
class Page:
    """One page a crawl's listing returned.

    Attributes:
        items: The page's entries, in order.
        next_token: The cursor or URL of the next page, or ``None`` on the last page.
    """

    items: Sequence[Any]
    next_token: Optional[str] = None


class RegistryHttp:
    """The HTTP surface a crawl gets: guarded, rate-limited, budgeted and size-capped GETs.

    Args:
        headers: Headers sent on every request (accept, auth).
        requests_per_second: Per-host rate.
        max_requests: Request budget for this sync.
        transport: An httpx transport override (tests).
        limiter: A rate limiter override (tests).
    """

    def __init__(
        self,
        *,
        headers: Optional[Mapping[str, str]] = None,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        max_requests: int = MAX_REQUESTS,
        transport: Optional[httpx.BaseTransport] = None,
        limiter: Optional[HostRateLimiter] = None,
    ) -> None:
        kwargs: Dict[str, Any] = {"headers": dict(headers or {}), "timeout": 30.0}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = build_connector_http_client(**kwargs)
        self._limiter = limiter or HostRateLimiter(requests_per_second)
        self._remaining = max_requests
        self.request_count = 0
        #: Per-sync notes a crawl records about entries it left out (``{remoteId, reason}``); the
        #: engine copies them into the run summary's ``findings``.
        self.findings: List[Dict[str, Any]] = []

    def close(self) -> None:
        """Close the underlying client."""
        self._client.close()

    def __enter__(self) -> "RegistryHttp":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def get(
        self, url: str, *, params: Optional[Mapping[str, Any]] = None, accept: Optional[str] = None
    ) -> httpx.Response:
        """GET ``url`` within the limits.

        Args:
            url: An absolute http(s) URL.
            params: Query parameters.
            accept: An ``Accept`` header for this request, overriding the default.

        Returns:
            The 2xx response, its body read (and capped at :data:`MAX_RESPONSE_BYTES`).

        Raises:
            RefreshSourceError: The budget is spent, the SSRF guard refused the address, the
                registry did not answer, answered non-2xx, or sent too large a body.
        """
        if self._remaining <= 0:
            raise RefreshSourceError(
                "The registry crawl used its whole request budget; narrow the scope or lower the "
                "page count.",
                error_class=ERROR_CLASS_BUDGET,
            )
        self._remaining -= 1
        self.request_count += 1
        self._limiter.wait(urlsplit(url).netloc.lower())
        headers = {"Accept": accept} if accept else None
        try:
            # Only pass params when there are some: an empty mapping would drop the query string a
            # next-page URL already carries (``?page=2``).
            extra: Dict[str, Any] = {"params": dict(params)} if params else {}
            with self._client.stream("GET", url, headers=headers, **extra) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise RefreshSourceError(
                            f"The registry answered GET {_path(url)} with more than "
                            f"{MAX_RESPONSE_BYTES} bytes.",
                            error_class=ERROR_CLASS_UNEXPECTED,
                        )
                status = response.status_code
                result = httpx.Response(
                    status, headers=response.headers, content=bytes(body), request=response.request
                )
        except SSRFError as exc:
            raise RefreshSourceError(
                f"Request to the registry refused: {exc}", error_class=ERROR_CLASS_ADDRESS_REFUSED
            ) from exc
        except httpx.HTTPError as exc:
            raise RefreshSourceError(
                f"The registry did not answer GET {_path(url)}: {type(exc).__name__}"
            ) from exc
        if not 200 <= status < 300:
            detail = (result.text or "").strip()[:_ERROR_DETAIL_MAX]
            raise RefreshSourceError(
                f"The registry answered {status} to GET {_path(url)}" + (f": {detail}" if detail else ""),
                http_status=status,
            )
        return result

    def get_json(self, url: str, *, params: Optional[Mapping[str, Any]] = None) -> Any:
        """GET ``url`` and decode its JSON body.

        Raises:
            RefreshSourceError: As :meth:`get`, or the body is not JSON.
        """
        response = self.get(url, params=params, accept="application/json")
        try:
            return response.json()
        except ValueError as exc:
            raise RefreshSourceError(
                f"The registry answered GET {_path(url)} with a body that is not JSON.",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            ) from exc


def _path(url: str) -> str:
    """The path (and query) of ``url``, for messages."""
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "") or "/"


def paginate(
    fetch_page: Callable[[Optional[str]], Page], *, max_pages: int = MAX_PAGES, what: str = "entries"
) -> Iterator[Any]:
    """Yield every item of a paged listing, following ``next_token`` until it runs out.

    Args:
        fetch_page: ``(token or None for the first page) -> Page``.
        max_pages: The most pages to follow.
        what: What the pages list, for the error message.

    Yields:
        Each item, in page order.

    Raises:
        RefreshSourceError: The listing has more than ``max_pages`` pages.
    """
    token: Optional[str] = None
    seen: set = set()
    for _ in range(max_pages):
        page = fetch_page(token)
        yield from page.items
        token = page.next_token
        if not token or token in seen:
            return
        seen.add(token)
    raise RefreshSourceError(
        f"The registry lists more than {max_pages} pages of {what}; narrow the scope.",
        error_class=ERROR_CLASS_UNEXPECTED,
    )


def link_next(response: httpx.Response) -> Optional[str]:
    """The absolute URL of a response's ``Link: <…>; rel="next"``, or ``None``."""
    target = response.links.get("next", {}).get("url")
    return urljoin(str(response.request.url), target) if target else None


def content_revision(document: Any) -> str:
    """A stable revision for a JSON document the registry gives no revision for: its digest."""
    blob = json.dumps(document, sort_keys=True, default=str).encode("utf-8")
    return "sha256." + hashlib.sha256(blob).hexdigest()[:16]


def parse_instant(value: Any) -> Optional[datetime]:
    """Parse an RFC 3339 / ISO 8601 instant (``Z`` or an offset; a bare date is midnight UTC)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------
# The ``registry`` connector kind
# ---------------------------------------------------------------------------------------


def _scope_error(message: str) -> ConnectorError:
    return ConnectorError(CODE_INVALID, message)


def validate_registry_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check a ``registry`` connector: a base URL, a known ``protocol`` and the crawl's own keys.

    Args:
        scope: ``{"protocol": "<crawl>", "requestsPerSecond"?: number, …crawl keys}``.
        base_url: The registry root URL.

    Raises:
        ConnectorError: ``connector-invalid`` for a missing base URL, an unknown protocol, an
            unknown key or an out-of-range rate.
    """
    if not (base_url or "").strip():
        raise _scope_error("A registry connector needs a base URL: the registry root.")
    protocol = scope.get("protocol")
    crawl = get_registry_crawl(protocol) if isinstance(protocol, str) else None
    if crawl is None:
        raise _scope_error(
            "A registry connector's scope needs protocol: one of " + ", ".join(registry_crawl_protocols()) + "."
        )
    unknown = sorted(set(scope) - set(COMMON_SCOPE_KEYS) - set(crawl.scope_keys))
    if unknown:
        raise _scope_error(f"Unknown scope key(s) for the {protocol} crawl: {', '.join(unknown)}.")
    rate = scope.get("requestsPerSecond")
    if rate is not None and (
        isinstance(rate, bool) or not isinstance(rate, (int, float)) or not 0 < rate <= MAX_REQUESTS_PER_SECOND
    ):
        raise _scope_error(f"requestsPerSecond must be a number above 0 and at most {MAX_REQUESTS_PER_SECOND:g}.")
    crawl.validate_scope(scope)


class RegistryConnectorSource(ConnectorRefreshSource):
    """``registry``: every artifact of a registry, imported as individually versioned catalog items.

    The connector scope's ``protocol`` picks the :class:`RegistryCrawl`; each entry the crawl lists
    becomes one candidate (``remote_id`` → inventory row → catalog item) and is fetched only when
    the engine's freshness gate says it changed.

    Args:
        connector: The connector row.
        credentials: ``{"token": …}`` (bearer) and/or ``{"apiKey": …}`` (``X-API-Key``), or ``None``.
        transport: An httpx transport override (tests drive a fake registry through it).
        limiter: A rate limiter override (tests).
    """

    #: Registry entries are published artifacts, not APIs found on a gateway.
    reports_shadow_apis = False

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
        limiter: Optional[HostRateLimiter] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self._transport = transport
        self._limiter = limiter
        self._entries: Dict[str, RegistryEntry] = {}
        self._http: Optional[RegistryHttp] = None

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    @property
    def findings(self) -> List[Dict[str, Any]]:
        """What the crawl left out this sync (the engine reads this after listing)."""
        return list(self._http.findings) if self._http is not None else []

    @property
    def base_url(self) -> str:
        return str(self.connector.get("base_url") or "").strip().rstrip("/")

    def crawl(self) -> RegistryCrawl:
        """The crawl the scope names.

        Raises:
            RefreshSourceError: ``invalid-configuration`` when the protocol is unknown.
        """
        protocol = self.scope.get("protocol")
        crawl = get_registry_crawl(protocol) if isinstance(protocol, str) else None
        if crawl is None:
            raise RefreshSourceError(
                f"Unknown registry protocol {protocol!r}.", error_class=ERROR_CLASS_INVALID_CONFIGURATION
            )
        return crawl

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

    def http(self) -> RegistryHttp:
        """The sync's HTTP surface: one request budget spans the listing and every fetch."""
        if self._http is None:
            rate = self.scope.get("requestsPerSecond")
            self._http = RegistryHttp(
                headers=self._headers(),
                requests_per_second=float(rate) if isinstance(rate, (int, float)) else DEFAULT_REQUESTS_PER_SECOND,
                transport=self._transport,
                limiter=self._limiter,
            )
        return self._http

    def list_candidates(self) -> List[RefreshCandidate]:
        """List the registry through its crawl; one candidate per distinct entry id.

        Raises:
            RefreshSourceError: No base URL, an unknown protocol, too many entries, or the listing
                failed.
        """
        if not self.base_url:
            raise RefreshSourceError(
                "A registry connector needs a base URL (the registry root).",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        crawl = self.crawl()
        entries: Dict[str, RegistryEntry] = {}
        for entry in crawl.list_entries(self.http(), self.base_url, self.scope):
            entries.setdefault(entry.remote_id, entry)
            if len(entries) > MAX_ENTRIES:
                raise RefreshSourceError(
                    f"The registry lists more than {MAX_ENTRIES} artifacts; narrow the scope.",
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
        self._entries = entries
        return [self._candidate(entry, crawl) for entry in entries.values()]

    @staticmethod
    def _candidate(entry: RegistryEntry, crawl: RegistryCrawl) -> RefreshCandidate:
        return RefreshCandidate(
            remote_id=entry.remote_id,
            name=entry.name or entry.remote_id,
            revision=entry.revision,
            updated_at=entry.updated_at,
            raw={
                "protocol": crawl.protocol,
                "importKind": entry.import_kind,
                "documentUrl": entry.document_url,
                "sourceUri": entry.source_uri,
                "entry": dict(entry.raw),
            },
        )

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """Fetch one entry's artifact through its crawl.

        Raises:
            RefreshSourceError: The entry is not in this sync's listing, or the fetch failed.
        """
        entry = self._entries.get(candidate.remote_id)
        if entry is None:
            raise RefreshSourceError(
                f"Registry entry {candidate.remote_id} was not in this sync's listing.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return self.crawl().fetch_entry(self.http(), entry)

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, registryUrl, protocol, importSource, requests}``."""
        protocol = self.scope.get("protocol")
        crawl = get_registry_crawl(protocol) if isinstance(protocol, str) else None
        return {
            **super().describe(),
            "registryUrl": self.base_url,
            "protocol": protocol,
            "importSource": crawl.import_source if crawl else None,
            "requests": self._http.request_count if self._http else 0,
        }

    def close(self) -> None:
        """Release the HTTP client (the engine calls this when a sync ends, if it can)."""
        if self._http is not None:
            self._http.close()
            self._http = None


def iter_json_list(value: Any) -> Iterable[Any]:
    """``value`` when it is a list, else nothing (lenient helper for registry payloads)."""
    return value if isinstance(value, list) else ()


register_connector_source(KIND, RegistryConnectorSource, scope_validator=validate_registry_scope)
