"""Kong connector sources: Konnect control planes and the Admin API — CDG-1.2 (#5953).

A Konnect tenant does not keep ``kong.yaml`` in a repository: the truth is in the control plane.
These two sources pull it live and hand each Kong **service** to the catalog as the declarative
document the shipped ``kong`` import adapter (IXH-7.8, :mod:`app.kong_parser`) already parses, so
a synced service imports exactly like the equivalent declarative file: what Kong declares
(hosts, paths, methods) stays declared, and path parameters recovered from regex paths and auth
schemes recovered from plugins stay inferred.

**Kinds.**

* ``kong-konnect`` — Konnect. Credential ``{"token": "kpat_…" | "spat_…"}`` (a personal or
  system access token, sent as a bearer token). Scope ``{"region": "us", "controlPlanes":
  ["<id>", …]}``: ``region`` picks ``https://{region}.api.konghq.com`` (default ``us``) unless the
  connector has a base URL, and an empty or missing ``controlPlanes`` means every control plane
  the token can read. Entities come from ``GET /v2/control-planes/{cp}/core-entities/
  services|routes|plugins|consumers``, paged by ``size`` and the ``offset`` token each page returns.
* ``kong-admin`` — a self-managed gateway's Admin API. The connector's base URL is the Admin API;
  credential ``{"token": "…"}`` is optional (sent as ``Kong-Admin-Token`` for RBAC). Scope
  ``{"workspace": "…", "environment": "…"}`` (both optional): a workspace prefixes every path
  (Kong Enterprise), and ``environment`` labels the inventory rows (default: the workspace).
  Entities come from ``GET /services|routes|plugins|consumers``, paged the same way.

**One catalog item per Kong service.** Each service becomes one candidate whose document is the
service with its routes and plugins nested, plus the control plane's global plugins. Remote ids
are ``{controlPlaneId}:{serviceId}`` (Konnect) or ``{workspace}:{serviceId}`` /
``{serviceId}`` (Admin API), so two control planes never share an item. The candidate's revision
is a digest of the document, not Kong's ``updated_at``: deleting a route changes no surviving
entity's timestamp, but it does change the document, so a digest is the only freshness signal
that sees every change. Re-syncing an unchanged gateway imports nothing; changing one route
imports exactly one new revision of one item.

**Deployment metadata** is recorded on the inventory row (``deployment``, V282): control plane id
and name (or workspace), the service's tags and enabled flag, the protocols, hosts and paths its
routes declare, the latest ``updated_at``, and **suggested owners** from tags of the form
``owner:<team-slug>`` (CDG-2.2 turns a suggestion into an owner; nothing here confirms one). The
row's ``environment`` is the control plane's name.

**Findings.** A route that belongs to no service has no catalog item to land in, so it is
reported as a connector-level finding (``route-without-service``) on the run rather than dropped
silently; so are malformed owner tags (``owner-tag-invalid``), consumer-scoped plugins
(``consumer-plugins-not-imported``) and the consumer count (``consumers-not-imported``, info:
consumers are callers, not the API surface).

**Secrets.** Plugin config values under secret-shaped keys are redacted before the document is
assembled (the same rule the parser applies), and consumer credentials are never requested. The
token is sent only in a header and never appears in a document, a finding or an error message.
Every request goes through :func:`app.catalog_connectors.build_connector_http_client`, which
re-checks the SSRF rule on every hop.

**Failures.** A Kong refusal raises :class:`~app.refresh_source.RefreshSourceError` with Kong's
HTTP status (a revoked token is ``401`` → error class ``auth``) and the message from Kong's error
body, so the run is ``failed`` with the reason and the connector turns ``failing``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import httpx
import yaml

from .catalog_connector_sync import ConnectorRefreshSource, register_connector_source
from .catalog_connectors import CODE_INVALID, ConnectorError, build_connector_http_client, suggested_owner
from .gateway_config_model import redact_secret_config
from .kong_parser import ROUTE_EXTRA_KEYS, SERVICE_EXTRA_KEYS
from .refresh_source import ERROR_CLASS_UNEXPECTED, FetchedDocument, RefreshCandidate, RefreshSourceError
from .ssrf_guard import SSRFError

__all__ = [
    "ADMIN_TOKEN_HEADER",
    "DECLARATIVE_FORMAT_VERSION",
    "ERROR_CLASS_ADDRESS_REFUSED",
    "ERROR_CLASS_INVALID_CONFIGURATION",
    "KIND_ADMIN",
    "KIND_KONNECT",
    "KONNECT_REGIONS",
    "KongAdminSource",
    "KongEntities",
    "KongKonnectSource",
    "build_service_inventory",
    "owner_suggestions",
    "render_declarative",
    "validate_admin_scope",
    "validate_konnect_scope",
]

KIND_KONNECT = "kong-konnect"
KIND_ADMIN = "kong-admin"

#: Konnect geographic regions (``https://{region}.api.konghq.com``).
KONNECT_REGIONS: Tuple[str, ...] = ("us", "eu", "au", "me", "in", "sg")
DEFAULT_KONNECT_REGION = "us"

#: The header a Kong Enterprise Admin API reads an RBAC token from.
ADMIN_TOKEN_HEADER = "Kong-Admin-Token"

#: The ``_format_version`` of the assembled declarative documents.
DECLARATIVE_FORMAT_VERSION = "3.0"

#: Entities requested per page, and the most pages followed per collection.
PAGE_SIZE = 100
MAX_PAGES = 500

#: Error class for a scope or base URL that cannot address a Kong API.
ERROR_CLASS_INVALID_CONFIGURATION = "invalid-configuration"
#: Error class for a request the SSRF guard refused (a redirect or re-resolution to a private address).
ERROR_CLASS_ADDRESS_REFUSED = "address-refused"

#: Finding codes (``summary.findings[].code`` on a run).
FINDING_ROUTE_WITHOUT_SERVICE = "route-without-service"
FINDING_OWNER_TAG_INVALID = "owner-tag-invalid"
FINDING_CONSUMER_PLUGINS = "consumer-plugins-not-imported"
FINDING_CONSUMERS = "consumers-not-imported"

#: Tag prefix that names a suggested owner team.
OWNER_TAG_PREFIX = "owner:"
_CONTROL_PLANE_ID_MAX = 128
_ERROR_DETAIL_MAX = 300
_COLLECTIONS = ("services", "routes", "plugins", "consumers")


# ---------------------------------------------------------------------------------------
# Scope validation (run by the routes on every write)
# ---------------------------------------------------------------------------------------


def _scope_error(message: str) -> ConnectorError:
    return ConnectorError(CODE_INVALID, message)


def validate_konnect_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check a ``kong-konnect`` scope: ``region`` and ``controlPlanes``.

    Args:
        scope: The connector scope.
        base_url: The connector base URL (overrides the region's host when set).

    Raises:
        ConnectorError: ``connector-invalid`` for an unknown key, an unknown region, or a
            ``controlPlanes`` that is not a list of non-empty strings.
    """
    _ = base_url
    unknown = sorted(set(scope) - {"region", "controlPlanes"})
    if unknown:
        raise _scope_error(f"Unknown kong-konnect scope key(s): {', '.join(unknown)}.")
    region = scope.get("region")
    if region is not None and region not in KONNECT_REGIONS:
        raise _scope_error(f"Konnect region must be one of {', '.join(KONNECT_REGIONS)}.")
    planes = scope.get("controlPlanes")
    if planes is None:
        return
    if not isinstance(planes, list) or not all(
        isinstance(p, str) and p.strip() and len(p) <= _CONTROL_PLANE_ID_MAX for p in planes
    ):
        raise _scope_error("controlPlanes must be a list of control plane ids.")


def validate_admin_scope(scope: Mapping[str, Any], base_url: Optional[str]) -> None:
    """Check a ``kong-admin`` scope: optional ``workspace`` and ``environment`` strings.

    Raises:
        ConnectorError: ``connector-invalid`` for an unknown key or a non-string value, or a
            workspace that is not a single path segment.
    """
    _ = base_url
    unknown = sorted(set(scope) - {"workspace", "environment"})
    if unknown:
        raise _scope_error(f"Unknown kong-admin scope key(s): {', '.join(unknown)}.")
    for key in ("workspace", "environment"):
        value = scope.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 200):
            raise _scope_error(f"{key} must be a non-empty string.")
    workspace = scope.get("workspace")
    if isinstance(workspace, str) and not re.fullmatch(r"[A-Za-z0-9._~-]+", workspace):
        raise _scope_error("workspace must be a Kong workspace name (letters, digits, '.', '_', '~', '-').")


# ---------------------------------------------------------------------------------------
# Assembly: Kong entities -> one declarative document per service
# ---------------------------------------------------------------------------------------


@dataclass
class KongEntities:
    """The core entities of one control plane (or Admin API workspace), as Kong returns them."""

    services: List[Dict[str, Any]] = field(default_factory=list)
    routes: List[Dict[str, Any]] = field(default_factory=list)
    plugins: List[Dict[str, Any]] = field(default_factory=list)
    consumers: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _ServiceInventory:
    """One service's candidate and the document its fetch returns."""

    candidate: RefreshCandidate
    document: bytes
    filename: str


def _ref_id(value: Any) -> Optional[str]:
    """The id of a Kong foreign reference (``{"id": …}``), or ``None``."""
    if isinstance(value, Mapping):
        ref = value.get("id")
        return str(ref) if ref else None
    return None


def _present(value: Any) -> bool:
    """True for a value worth writing into a declarative entry (not null, not empty)."""
    return value is not None and value != [] and value != {}


def _sorted_config(value: Any) -> Any:
    """A copy of a plugin config with every mapping's keys sorted, so the document is stable."""
    if isinstance(value, Mapping):
        return {str(k): _sorted_config(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, list):
        return [_sorted_config(v) for v in value]
    return value


def _plugin_entry(plugin: Mapping[str, Any]) -> Dict[str, Any]:
    """The declarative entry for one plugin: name, enabled, redacted config."""
    config, _ = redact_secret_config(plugin.get("config") or {})
    entry: Dict[str, Any] = {"name": str(plugin.get("name"))}
    if plugin.get("enabled") is not None:
        entry["enabled"] = bool(plugin.get("enabled"))
    if _present(config):
        entry["config"] = _sorted_config(config)
    return entry


def _plugin_sort_key(plugin: Mapping[str, Any]) -> Tuple[str, str]:
    return (str(plugin.get("name") or ""), str(plugin.get("instance_name") or plugin.get("id") or ""))


def _route_entry(route: Mapping[str, Any], plugins: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The declarative entry for one route: the keys the parser reads, in a fixed order."""
    entry: Dict[str, Any] = {"name": str(route.get("name") or route.get("id"))}
    for key in ("protocols", "methods", "hosts", "paths", *ROUTE_EXTRA_KEYS):
        if key in entry:
            continue
        value = route.get(key)
        if _present(value):
            entry[key] = value
    if plugins:
        entry["plugins"] = [_plugin_entry(p) for p in sorted(plugins, key=_plugin_sort_key)]
    return entry


def _service_entry(
    service: Mapping[str, Any],
    routes: Sequence[Mapping[str, Any]],
    service_plugins: Sequence[Mapping[str, Any]],
    route_plugins: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    """The declarative entry for one service with its plugins and routes nested."""
    entry: Dict[str, Any] = {"name": str(service.get("name") or service.get("id"))}
    for key in ("protocol", "host", "port", "path", *SERVICE_EXTRA_KEYS):
        value = service.get(key)
        if _present(value):
            entry[key] = value
    if service_plugins:
        entry["plugins"] = [_plugin_entry(p) for p in sorted(service_plugins, key=_plugin_sort_key)]
    entry["routes"] = [
        _route_entry(route, route_plugins.get(str(route.get("id")), ()))
        for route in sorted(routes, key=lambda r: str(r.get("name") or r.get("id")))
    ]
    return entry


def render_declarative(document: Mapping[str, Any]) -> bytes:
    """Serialize an assembled declarative document deterministically (block YAML, keys in order).

    Args:
        document: The ``{_format_version, services[, plugins]}`` mapping.

    Returns:
        UTF-8 YAML bytes; the same entities always render the same bytes.
    """
    return yaml.safe_dump(
        dict(document), sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000
    ).encode("utf-8")


def owner_suggestions(tags: Sequence[Any]) -> Tuple[List[Dict[str, str]], List[str]]:
    """Read ``owner:<team-slug>`` tags into CDG-2.2 suggested owners.

    Args:
        tags: The service's Kong tags.

    Returns:
        ``(suggestions, invalid_tags)``: one ``{team, source: "gateway_tag", sourceRef}`` per
        distinct well-formed team slug (lower-cased), and the ``owner:`` tags whose slug is not
        a valid team slug.
    """
    suggestions: List[Dict[str, str]] = []
    invalid: List[str] = []
    seen = set()
    for tag in tags or []:
        if not isinstance(tag, str) or not tag.lower().startswith(OWNER_TAG_PREFIX):
            continue
        suggestion = suggested_owner(tag[len(OWNER_TAG_PREFIX):], tag)
        if suggestion is None:
            invalid.append(tag)
            continue
        if suggestion["team"] in seen:
            continue
        seen.add(suggestion["team"])
        suggestions.append(suggestion)
    return suggestions, invalid


def _iso_from_epoch(value: Any) -> Optional[str]:
    """Kong timestamps are epoch seconds; return ISO-8601 UTC, or ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _common_base_path(paths: Sequence[str]) -> Optional[str]:
    """The longest whole-segment prefix shared by the routes' plain (non-regex) paths."""
    plain = [p for p in paths if p.startswith("/") and not p.startswith("~")]
    if not plain:
        return None
    split = [[s for s in p.split("/") if s] for p in plain]
    prefix: List[str] = []
    for parts in zip(*split):
        if any(part != parts[0] for part in parts):
            break
        prefix.append(parts[0])
    return "/" + "/".join(prefix) if prefix else None


def _sorted_union(routes: Sequence[Mapping[str, Any]], key: str) -> List[str]:
    return sorted({str(v) for route in routes for v in (route.get(key) or []) if isinstance(v, (str, int))})


def build_service_inventory(
    entities: KongEntities,
    *,
    remote_prefix: Optional[str],
    environment: Optional[str],
    location: Mapping[str, Any],
) -> Tuple[List[_ServiceInventory], List[Dict[str, Any]]]:
    """Turn one control plane's entities into one candidate + document per service.

    Args:
        entities: What Kong returned for the control plane (or workspace).
        remote_prefix: Prefix for remote ids (``{cp}`` or the workspace), or ``None``.
        environment: The inventory rows' environment (the control plane's name).
        location: Credential-free location facts copied into each ``deployment`` and finding
            (``controlPlaneId``/``controlPlaneName`` or ``workspace``).

    Returns:
        ``(inventory, findings)``.
    """
    findings: List[Dict[str, Any]] = []
    services = {str(s.get("id")): s for s in entities.services if s.get("id")}

    routes_by_service: Dict[str, List[Dict[str, Any]]] = {sid: [] for sid in services}
    for route in entities.routes:
        service_id = _ref_id(route.get("service"))
        if service_id in routes_by_service:
            routes_by_service[service_id].append(route)
            continue
        findings.append(
            {
                "code": FINDING_ROUTE_WITHOUT_SERVICE,
                "severity": "warning",
                **location,
                "routeId": route.get("id"),
                "routeName": route.get("name"),
                "paths": list(route.get("paths") or []),
                "message": (
                    "Route belongs to no service on this control plane, so it has no catalog item "
                    "to land in; attach it to a service in Kong to import it."
                ),
            }
        )

    global_plugins: List[Dict[str, Any]] = []
    service_plugins: Dict[str, List[Dict[str, Any]]] = {}
    route_plugins: Dict[str, List[Dict[str, Any]]] = {}
    consumer_plugins = 0
    for plugin in entities.plugins:
        if not plugin.get("name"):
            continue
        if _ref_id(plugin.get("consumer")) or plugin.get("consumer_group"):
            consumer_plugins += 1
            continue
        route_id = _ref_id(plugin.get("route"))
        service_id = _ref_id(plugin.get("service"))
        if route_id:
            route_plugins.setdefault(route_id, []).append(plugin)
        elif service_id:
            service_plugins.setdefault(service_id, []).append(plugin)
        else:
            global_plugins.append(plugin)
    if consumer_plugins:
        findings.append(
            {
                "code": FINDING_CONSUMER_PLUGINS,
                "severity": "info",
                **location,
                "count": consumer_plugins,
                "message": "Consumer-scoped plugins configure callers, not the API surface, and are not imported.",
            }
        )
    if entities.consumers:
        findings.append(
            {
                "code": FINDING_CONSUMERS,
                "severity": "info",
                **location,
                "count": len(entities.consumers),
                "message": (
                    "Consumers are callers of the APIs, not part of their surface; they are counted, "
                    "never imported."
                ),
            }
        )

    inventory: List[_ServiceInventory] = []
    for service_id, service in sorted(services.items(), key=lambda kv: str(kv[1].get("name") or kv[0])):
        routes = routes_by_service[service_id]
        own_route_ids = {str(r.get("id")) for r in routes}
        own_route_plugins = {rid: plist for rid, plist in route_plugins.items() if rid in own_route_ids}
        document: Dict[str, Any] = {
            "_format_version": DECLARATIVE_FORMAT_VERSION,
            "services": [_service_entry(service, routes, service_plugins.get(service_id, ()), own_route_plugins)],
        }
        if global_plugins:
            document["plugins"] = [_plugin_entry(p) for p in sorted(global_plugins, key=_plugin_sort_key)]
        content = render_declarative(document)
        digest = hashlib.sha256(content).hexdigest()
        name = str(service.get("name") or service_id)

        tags = [t for t in (service.get("tags") or []) if isinstance(t, str)]
        suggestions, invalid_tags = owner_suggestions(tags)
        for tag in invalid_tags:
            findings.append(
                {
                    "code": FINDING_OWNER_TAG_INVALID,
                    "severity": "warning",
                    **location,
                    "serviceId": service_id,
                    "serviceName": name,
                    "tag": tag,
                    "message": "Owner tag does not name a team slug (lower-case letters, digits and '-').",
                }
            )
        stamps = [service.get("updated_at")] + [r.get("updated_at") for r in routes]
        stamps += [p.get("updated_at") for p in service_plugins.get(service_id, ())]
        stamps += [p.get("updated_at") for plist in own_route_plugins.values() for p in plist]
        numeric = [s for s in stamps if isinstance(s, (int, float)) and not isinstance(s, bool)]
        paths = _sorted_union(routes, "paths")
        hosts = _sorted_union(routes, "hosts")
        deployment: Dict[str, Any] = {
            **location,
            "serviceId": service_id,
            "tags": tags,
            "enabled": bool(service.get("enabled", True)),
            "protocols": _sorted_union(routes, "protocols"),
            "hosts": hosts,
            "paths": paths,
            "routeCount": len(routes),
            "pluginCount": len(service_plugins.get(service_id, ()))
            + sum(len(p) for p in own_route_plugins.values()),
            "updatedAt": _iso_from_epoch(max(numeric)) if numeric else None,
            "suggestedOwners": suggestions,
        }
        remote_id = f"{remote_prefix}:{service_id}" if remote_prefix else service_id
        inventory.append(
            _ServiceInventory(
                candidate=RefreshCandidate(
                    remote_id=remote_id,
                    name=name,
                    revision=f"kong-{digest[:16]}",
                    updated_at=None,
                    environment=environment,
                    hosts=tuple(hosts),
                    base_path=_common_base_path(paths),
                    deployment=deployment,
                ),
                document=content,
                filename=f"{re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-') or 'service'}.kong.yaml",
            )
        )
    return inventory, findings


# ---------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------


def _kong_error_detail(response: httpx.Response) -> str:
    """The human part of a Kong error body (Konnect problem JSON or Admin API ``message``)."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "").strip()[:_ERROR_DETAIL_MAX]
    if not isinstance(body, Mapping):
        return ""
    parts = [str(body[k]) for k in ("title", "detail", "message") if isinstance(body.get(k), str) and body.get(k)]
    return ": ".join(dict.fromkeys(parts))[:_ERROR_DETAIL_MAX]


class _KongHttp:
    """GETs against one Kong API with Kong's paging and error mapping.

    Args:
        base_url: The API root (Konnect region URL or Admin API URL).
        headers: Auth headers (never logged, never put in a message).
        transport: An httpx transport override (tests).
    """

    def __init__(self, base_url: str, headers: Mapping[str, str], transport: Optional[httpx.BaseTransport]) -> None:
        self._base = base_url.rstrip("/")
        kwargs: Dict[str, Any] = {"headers": {"Accept": "application/json", **headers}, "timeout": 30.0}
        if transport is not None:
            kwargs["transport"] = transport
        self._client = build_connector_http_client(**kwargs)

    def close(self) -> None:
        self._client.close()

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        """GET ``path`` and return the decoded JSON body.

        Raises:
            RefreshSourceError: Kong answered non-2xx (with its status and body message), did not
                answer, the SSRF guard refused the address, or the body is not JSON.
        """
        try:
            response = self._client.get(f"{self._base}{path}", params=dict(params or {}))
        except SSRFError as exc:
            raise RefreshSourceError(
                f"Request to the Kong API refused: {exc}", error_class=ERROR_CLASS_ADDRESS_REFUSED
            ) from exc
        except httpx.HTTPError as exc:
            raise RefreshSourceError(f"Kong API did not answer GET {path}: {type(exc).__name__}") from exc
        if not 200 <= response.status_code < 300:
            detail = _kong_error_detail(response)
            raise RefreshSourceError(
                f"Kong answered {response.status_code} to GET {path}" + (f": {detail}" if detail else ""),
                http_status=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RefreshSourceError(
                f"Kong answered GET {path} with a body that is not JSON.",
                http_status=response.status_code,
                error_class=ERROR_CLASS_UNEXPECTED,
            ) from exc

    def paged(self, path: str) -> Iterator[Dict[str, Any]]:
        """Every entity of a core-entity collection, following Kong's ``offset`` token.

        Raises:
            RefreshSourceError: As :meth:`get`, or when a page is not ``{"data": [...]}`` or the
                collection runs past :data:`MAX_PAGES`.
        """
        offset: Optional[str] = None
        seen_offsets = set()
        for _ in range(MAX_PAGES):
            params: Dict[str, Any] = {"size": PAGE_SIZE}
            if offset:
                params["offset"] = offset
            body = self.get(path, params)
            if not isinstance(body, Mapping) or not isinstance(body.get("data"), list):
                raise RefreshSourceError(
                    f"Kong answered GET {path} with an unexpected body (no data list).",
                    http_status=200,
                    error_class=ERROR_CLASS_UNEXPECTED,
                )
            for entity in body["data"]:
                if isinstance(entity, dict):
                    yield entity
            offset = body.get("offset") if isinstance(body.get("offset"), str) else None
            if not offset or offset in seen_offsets:
                return
            seen_offsets.add(offset)
        raise RefreshSourceError(
            f"Kong collection {path} has more than {MAX_PAGES * PAGE_SIZE} entities.",
            error_class=ERROR_CLASS_UNEXPECTED,
        )

    def entities(self, prefix: str) -> KongEntities:
        """The four core-entity collections under ``prefix``."""
        collected = {name: list(self.paged(f"{prefix}/{name}")) for name in _COLLECTIONS}
        return KongEntities(**collected)


# ---------------------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------------------


class _KongSource(ConnectorRefreshSource):
    """Shared half of the two Kong sources: list once, serve fetches from what was listed.

    Listing pulls every entity (the documents need all of them), so :meth:`fetch` returns the
    document assembled during :meth:`list_candidates` without another request.

    Args:
        connector: The connector row.
        credentials: The unsealed credential (``{"token": …}``), or ``None``.
        transport: An httpx transport override (tests drive a fake Kong through it).
    """

    def __init__(
        self,
        connector: Mapping[str, Any],
        credentials: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        super().__init__(connector, credentials)
        self._transport = transport
        self._documents: Dict[str, _ServiceInventory] = {}
        self.findings: List[Dict[str, Any]] = []

    @property
    def scope(self) -> Mapping[str, Any]:
        value = self.connector.get("scope")
        return value if isinstance(value, Mapping) else {}

    def _token(self) -> Optional[str]:
        token = (self.credentials or {}).get("token")
        return token.strip() if isinstance(token, str) and token.strip() else None

    def _planes(self, http: _KongHttp) -> List[Tuple[str, Optional[str], Optional[str], Dict[str, Any]]]:
        """``(path prefix, remote prefix, environment, location)`` per control plane."""
        raise NotImplementedError  # pragma: no cover - abstract

    def _http(self) -> _KongHttp:
        raise NotImplementedError  # pragma: no cover - abstract

    def list_candidates(self) -> List[RefreshCandidate]:
        """Pull every control plane in scope and return one candidate per Kong service."""
        self._documents = {}
        self.findings = []
        http = self._http()
        try:
            candidates: List[RefreshCandidate] = []
            for prefix, remote_prefix, environment, location in self._planes(http):
                inventory, findings = build_service_inventory(
                    http.entities(prefix), remote_prefix=remote_prefix, environment=environment, location=location
                )
                self.findings.extend(findings)
                for entry in inventory:
                    self._documents[entry.candidate.remote_id] = entry
                    candidates.append(entry.candidate)
            return candidates
        finally:
            http.close()

    def fetch(self, candidate: RefreshCandidate) -> FetchedDocument:
        """The declarative document assembled for ``candidate`` while listing."""
        entry = self._documents.get(candidate.remote_id)
        if entry is None:
            raise RefreshSourceError(
                f"Kong service {candidate.remote_id} was not in this sync's inventory.",
                error_class=ERROR_CLASS_UNEXPECTED,
            )
        return FetchedDocument(
            content=entry.document,
            filename=entry.filename,
            import_kind="kong",
            revision=entry.candidate.revision,
        )


class KongKonnectSource(_KongSource):
    """``kong-konnect``: services of one or more Konnect control planes."""

    def _http(self) -> _KongHttp:
        token = self._token()
        if token is None:
            raise RefreshSourceError(
                "A Konnect connector needs a personal or system access token; store it with "
                "PUT …/credentials as {\"token\": \"…\"}.",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        region = self.scope.get("region") or DEFAULT_KONNECT_REGION
        if region not in KONNECT_REGIONS:
            raise RefreshSourceError(
                f"Unknown Konnect region {region!r}.", error_class=ERROR_CLASS_INVALID_CONFIGURATION
            )
        base_url = self.connector.get("base_url") or f"https://{region}.api.konghq.com"
        return _KongHttp(str(base_url), {"Authorization": f"Bearer {token}"}, self._transport)

    def _planes(self, http: _KongHttp) -> List[Tuple[str, Optional[str], Optional[str], Dict[str, Any]]]:
        wanted = [str(p).strip() for p in (self.scope.get("controlPlanes") or []) if str(p).strip()]
        planes: List[Tuple[str, str]] = []
        if wanted:
            for plane_id in wanted:
                body = http.get(f"/v2/control-planes/{plane_id}")
                name = body.get("name") if isinstance(body, Mapping) else None
                planes.append((plane_id, str(name or plane_id)))
        else:
            page = 1
            while page <= MAX_PAGES:
                body = http.get("/v2/control-planes", {"page[size]": PAGE_SIZE, "page[number]": page})
                rows = body.get("data") if isinstance(body, Mapping) else None
                if not isinstance(rows, list):
                    raise RefreshSourceError(
                        "Konnect answered GET /v2/control-planes with an unexpected body.",
                        http_status=200,
                        error_class=ERROR_CLASS_UNEXPECTED,
                    )
                planes.extend(
                    (str(r["id"]), str(r.get("name") or r["id"]))
                    for r in rows
                    if isinstance(r, Mapping) and r.get("id")
                )
                if len(rows) < PAGE_SIZE:
                    break
                page += 1
        return [
            (
                f"/v2/control-planes/{plane_id}/core-entities",
                plane_id,
                name,
                {"controlPlaneId": plane_id, "controlPlaneName": name},
            )
            for plane_id, name in planes
        ]

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, region, controlPlanes}``."""
        return {
            **super().describe(),
            "region": self.scope.get("region") or DEFAULT_KONNECT_REGION,
            "controlPlanes": list(self.scope.get("controlPlanes") or []),
        }


class KongAdminSource(_KongSource):
    """``kong-admin``: services of a self-managed gateway's Admin API (one workspace)."""

    def _http(self) -> _KongHttp:
        base_url = self.connector.get("base_url")
        if not base_url:
            raise RefreshSourceError(
                "A Kong Admin API connector needs a base URL (the Admin API address).",
                error_class=ERROR_CLASS_INVALID_CONFIGURATION,
            )
        token = self._token()
        headers = {ADMIN_TOKEN_HEADER: token} if token else {}
        return _KongHttp(str(base_url), headers, self._transport)

    def _planes(self, http: _KongHttp) -> List[Tuple[str, Optional[str], Optional[str], Dict[str, Any]]]:
        _ = http
        workspace = self.scope.get("workspace")
        environment = self.scope.get("environment") or workspace
        location: Dict[str, Any] = {"workspace": workspace} if workspace else {}
        return [(f"/{workspace}" if workspace else "", workspace or None, environment or None, location)]

    def describe(self) -> Dict[str, Any]:
        """``{kind, connectorId, workspace}``."""
        return {**super().describe(), "workspace": self.scope.get("workspace")}


register_connector_source(KIND_KONNECT, KongKonnectSource, scope_validator=validate_konnect_scope)
register_connector_source(KIND_ADMIN, KongAdminSource, scope_validator=validate_admin_scope)
