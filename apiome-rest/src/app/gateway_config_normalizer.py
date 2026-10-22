"""Gateway configuration → canonical model normalizer — IXH-7.8 (#5133).

One projection for every flavor: a flavor-neutral
:class:`~app.gateway_config_model.GatewayConfigDocument` (from
:mod:`app.kong_parser`, :mod:`app.gateway_api_parser`, since FMT-7.4
:mod:`app.envoy_xds_parser` and :mod:`app.istio_parser`, and since FMT-7.5 the
reverse-proxy parsers — :mod:`app.traefik_parser`, :mod:`app.nginx_parser`,
:mod:`app.haproxy_parser`, :mod:`app.consul_parser` and :mod:`app.tyk_parser`) becomes a canonical
REST surface — services grouped by gateway service / HTTPRoute resource, one
operation per flattened match condition, servers from the declared hostnames.

Provenance discipline (this is what makes the import honest):

* Routes, hosts, and methods are **declared** facts — their entities carry no
  ``provenance`` stamp and their unmodeled attributes ride in ``extras``, so the
  coverage ledger reports them ``mapped`` / ``partially-mapped``.
* Path parameters recovered from regex patterns and auth schemes recovered from
  plugins are **inferred** — stamped ``provenance = "inferred"`` so the ledger
  never presents them as declared (same convention as IXH-7.4).
* Service-mesh route tables (Envoy xDS, Istio — :data:`INFERRED_ROUTE_FLAVORS`) are
  read as evidence of an API rather than a declaration of one, so *every* operation
  and service they produce is stamped ``inferred`` (FMT-7.4). The reverse-proxy and
  registry configs of FMT-7.5 (Traefik, nginx, HAProxy, Consul, Tyk classic) join them.
* The formats carry **no request/response schemas**, so operations have no
  messages. That absence is recorded on ``CanonicalApi.extras["gateway"]``
  (``schemaless_operation_count``) and rendered by the preview manifest as a
  capability limit of the source format — never as a drop.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Type

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    StreamingMode,
    TypeRef,
)
from .gateway_config_model import (
    GatewayAuthHint,
    GatewayConfigDocument,
    GatewayMatch,
    GatewayRoute,
)
from .gateway_family import (
    GATEWAY_FAMILY,
    GatewayFlavor,
    add_flavor,
    flavor_for,
    inferred_route_flavors,
    policy_plugin_flavors,
    provenance_stamp,
)
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "KONG_FORMAT_KEY",
    "GATEWAY_API_FORMAT_KEY",
    "ENVOY_XDS_FORMAT_KEY",
    "ISTIO_FORMAT_KEY",
    "TRAEFIK_FORMAT_KEY",
    "NGINX_FORMAT_KEY",
    "HAPROXY_FORMAT_KEY",
    "CONSUL_FORMAT_KEY",
    "TYK_FORMAT_KEY",
    "PROXY_ROUTE_FLAVORS",
    "INFERRED_ROUTE_FLAVORS",
    "POLICY_PLUGIN_FLAVORS",
    "KongNormalizer",
    "GatewayApiNormalizer",
    "EnvoyXdsNormalizer",
    "IstioNormalizer",
    "TraefikNormalizer",
    "NginxNormalizer",
    "HaproxyNormalizer",
    "ConsulNormalizer",
    "TykNormalizer",
    "gateway_report",
    "normalize_gateway_config",
    "register_gateway_flavor",
]

KONG_FORMAT_KEY = "kong"
GATEWAY_API_FORMAT_KEY = "gateway-api"
ENVOY_XDS_FORMAT_KEY = "envoy-xds"
ISTIO_FORMAT_KEY = "istio"
TRAEFIK_FORMAT_KEY = "traefik"
NGINX_FORMAT_KEY = "nginx"
HAPROXY_FORMAT_KEY = "haproxy"
CONSUL_FORMAT_KEY = "consul"
TYK_FORMAT_KEY = "tyk"

#: The reverse-proxy and registry route sources of FMT-7.5 — "the reverse-proxy config is the
#: only spec".
PROXY_ROUTE_FLAVORS = frozenset(
    {TRAEFIK_FORMAT_KEY, NGINX_FORMAT_KEY, HAPROXY_FORMAT_KEY, CONSUL_FORMAT_KEY, TYK_FORMAT_KEY}
)

#: Flavors whose operations and services are all stamped ``provenance = "inferred"`` —
#: derived from :data:`app.gateway_family.GATEWAY_FAMILY` (FMT-7.6), never listed here.
#: Kong and Gateway API *declare* an API surface; the mesh and proxy flavors are evidence of one.
INFERRED_ROUTE_FLAVORS = inferred_route_flavors()

#: Flavors whose non-auth plugins are listed on the report as policy the canonical model does
#: not represent (so the ledger shows them kept, not dropped) — also derived from the family.
#: Gateway API filters stay out: IXH-7.8 reports them through the route extras only.
POLICY_PLUGIN_FLAVORS = policy_plugin_flavors()

#: Method placeholder for a route that matches any HTTP method. Kept explicit
#: (rather than a fabricated verb) so diffs and keys stay stable and honest.
_ANY_METHOD = "ANY"


def _auth_dicts(hints: tuple[GatewayAuthHint, ...]) -> List[Dict[str, Any]]:
    """Serialize auth hints for extras bags, mapped hints first, stable order."""
    ordered = sorted(hints, key=lambda h: (h.scheme is None, h.scheme or "", h.plugin))
    return [hint.as_dict() for hint in ordered]


def _operation_for_match(
    route: GatewayRoute,
    match: GatewayMatch,
    *,
    used_keys: Set[str],
    flavor: str,
) -> Operation:
    """Build one canonical operation from one flattened match condition.

    Args:
        route: The owning route (extras / auth / backends context).
        match: The match condition (path pattern, method, header/query matches).
        used_keys: Keys already assigned — a collision (same method + template on
            two routes, e.g. two hosts) appends ``#<route name>`` so keys stay
            unique while the base coordinate stays diff-stable.
        flavor: The document's flavor; :func:`app.gateway_family.provenance_stamp`
            decides whether the operation is stamped inferred.

    Returns:
        The operation, message-less by construction (the formats carry no
        schemas; the document-level gateway report states that as a capability
        limit).
    """
    method = match.method or _ANY_METHOD
    template = match.path.template if match.path else "/"
    op_key = Keys.operation_http(method, template)
    if op_key in used_keys:
        op_key = f"{op_key}#{route.name}"
    used_keys.add(op_key)

    parameters: List[Parameter] = []
    if match.path is not None:
        for name in match.path.param_names:
            # Recovered from a regex pattern — inferred, with the pattern as evidence.
            parameters.append(
                Parameter(
                    key=Keys.parameter(op_key, "path", name),
                    name=name,
                    location=ParameterLocation.PATH,
                    required=True,
                    type=TypeRef(name="string", nullable=False),
                    extras={**provenance_stamp(flavor, derived=True), "pattern": match.path.raw},
                )
            )
    for name, value in match.headers:
        parameters.append(
            Parameter(
                key=Keys.parameter(op_key, "header", name),
                name=name,
                location=ParameterLocation.HEADER,
                required=True,
                type=TypeRef(name="string", nullable=False),
                extras={"match_value": value} if value else {},
            )
        )
    for name, value in match.query:
        parameters.append(
            Parameter(
                key=Keys.parameter(op_key, "query", name),
                name=name,
                location=ParameterLocation.QUERY,
                required=True,
                type=TypeRef(name="string", nullable=False),
                extras={"match_value": value} if value else {},
            )
        )

    extras: Dict[str, Any] = {"gateway_route": route.name, **provenance_stamp(flavor)}
    if route.hosts:
        extras["hosts"] = sorted(route.hosts)
    if match.path is not None:
        extras["path_match"] = {"kind": match.path.kind, "raw": match.path.raw}
    if match.method is None:
        extras["methods_unrestricted"] = True
    if route.auth:
        extras["security"] = _auth_dicts(route.auth)
    if route.plugins:
        extras["plugins"] = sorted({plugin.name for plugin in route.plugins})
    if route.backends:
        extras["backends"] = [backend.as_dict() for backend in route.backends]
    for key, value in route.extras.items():
        extras.setdefault(key, value)

    return Operation(
        key=op_key,
        name=f"{method} {template}",
        kind=OperationKind.REQUEST_RESPONSE,
        streaming=StreamingMode.NONE,
        http_method=method,
        http_path=template,
        parameters=parameters,
        messages=[],
        extras=extras,
    )


def gateway_report(
    *,
    flavor: str,
    route_count: int,
    operation_count: int,
    schemaless_operation_count: int,
    credential_redactions: int,
    ignored: Iterable[Dict[str, Any]],
    auth_hints: Iterable[GatewayAuthHint],
    global_plugins: Iterable[str],
    policy_plugins: Iterable[tuple],
) -> Dict[str, Any]:
    """Build the ``CanonicalApi.extras["gateway"]`` report — one shape for every front end.

    The preview manifest renders this report as the import's gateway ledger rows, so every
    family member states the same things the same way: the schemaless-operation count (the
    "gateway configs carry no schemas" capability limit, never a drop), the auth schemes
    inferred from plugins, the auth plugins with no canonical scheme, the declared parsing
    limits, the credential-redaction count, and — for a flavor whose
    :attr:`~app.gateway_family.GatewayFlavor.policy_plugins` is set — every non-auth plugin
    as policy kept by name.

    Args:
        flavor: The document's flavor key.
        route_count: Routes the source declared.
        operation_count: Operations the import produced.
        schemaless_operation_count: Operations with no request/response messages.
        credential_redactions: Credential values redacted at parse time.
        ignored: Declared limits (``{"construct", "count", "reason"}``).
        auth_hints: Every auth hint in effect (route- and gateway-scoped).
        global_plugins: Names of gateway-wide non-auth plugins.
        policy_plugins: ``(name, scope)`` of every non-auth plugin, route- or gateway-scoped.

    Returns:
        The report.
    """
    hints = list(auth_hints)
    report: Dict[str, Any] = {
        "flavor": flavor,
        "route_count": route_count,
        "operation_count": operation_count,
        "schemaless_operation_count": schemaless_operation_count,
        "credential_redactions": credential_redactions,
        "ignored_constructs": [dict(entry) for entry in ignored],
        "auth": [
            hint.as_dict()
            for hint in sorted(
                {(h.scheme, h.plugin, h.scope, h.attached_to): h for h in hints if h.scheme is not None}.values(),
                key=lambda h: (h.scheme or "", h.plugin, h.scope, h.attached_to or ""),
            )
        ],
        "unmapped_plugins": [
            {"name": name, "scope": scope}
            for name, scope in sorted({(hint.plugin, hint.scope) for hint in hints if hint.scheme is None})
        ],
        "global_plugins": sorted(set(global_plugins)),
    }
    declaration = flavor_for(flavor)
    if declaration is not None and declaration.policy_plugins:
        # CDG-1.2: every non-auth plugin is gateway policy the canonical model does not
        # represent (rate limits, transforms, CORS, retries, timeouts, rewrites, middleware).
        # Its name rides on the operations it applies to and its config stays in the captured
        # source; the ledger lists it so it is visibly kept, never silently dropped.
        report["unmodeled_plugins"] = [{"name": name, "scope": scope} for name, scope in sorted(set(policy_plugins))]
    return report


def normalize_gateway_config(
    document: GatewayConfigDocument,
    *,
    format_key: str,
    include_raw: bool = True,
) -> CanonicalApi:
    """Project a parsed gateway configuration onto the canonical model.

    Args:
        document: The flavor-neutral parsed document.
        format_key: Canonical format key to stamp (``kong`` / ``gateway-api``) —
            any non-OpenAPI key routes the import to the non-publishable catalog
            (see :func:`app.import_routing.decide_import_routing`).
        include_raw: When True, retain the parser's credential-free structural
            summary on ``CanonicalApi.raw``.

    Returns:
        The canonical model, deterministically ordered.
    """
    used_keys: Set[str] = set()
    operations_by_service: Dict[str, List[Operation]] = {}
    service_order: List[str] = []
    schemaless_operations = 0

    for route in document.routes:
        group = route.service_name or "(unattached routes)"
        if group not in operations_by_service:
            operations_by_service[group] = []
            service_order.append(group)
        for match in route.matches:
            operation = _operation_for_match(route, match, used_keys=used_keys, flavor=document.flavor)
            operations_by_service[group].append(operation)
            schemaless_operations += 1

    service_extras_by_name = {
        service.name: service for service in document.services
    }
    services: List[Service] = []
    for group in service_order:
        extras: Dict[str, Any] = provenance_stamp(document.flavor)
        definition = service_extras_by_name.get(group)
        if definition is not None:
            backend: Dict[str, Any] = {}
            if definition.url:
                backend["url"] = definition.url
            for attr in ("protocol", "host", "port", "path"):
                value = getattr(definition, attr)
                if value is not None:
                    backend[attr] = value
            if backend:
                extras["backend"] = backend
            extras.update(definition.extras)
        services.append(
            Service(
                key=Keys.type(group, None),
                name=group,
                operations=operations_by_service[group],
                extras=extras,
            )
        )

    # Servers: the gateway-facing hostnames. Scheme prefers https when any route
    # declares it (Kong ``protocols``; Gateway API serves both).
    servers: List[Server] = []
    seen_hosts: Set[str] = set()
    for route in document.routes:
        scheme = "https" if ("https" in route.protocols or not route.protocols) else "http"
        for host in route.hosts:
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            servers.append(Server(url=f"{scheme}://{host}"))
    servers.sort(key=lambda server: server.url)

    mapped_auth = [hint for route in document.routes for hint in route.auth]
    mapped_auth.extend(document.global_auth)
    inferred_schemes = sorted({hint.scheme for hint in mapped_auth if hint.scheme is not None})
    report = gateway_report(
        flavor=document.flavor,
        route_count=len(document.routes),
        operation_count=schemaless_operations,
        schemaless_operation_count=schemaless_operations,
        credential_redactions=document.credential_redactions,
        ignored=document.ignored,
        auth_hints=mapped_auth,
        global_plugins=[plugin.name for plugin in document.global_plugins],
        policy_plugins=[(plugin.name, plugin.scope) for route in document.routes for plugin in route.plugins]
        + [(plugin.name, plugin.scope) for plugin in document.global_plugins],
    )

    api_extras: Dict[str, Any] = {"gateway": report}
    if inferred_schemes:
        api_extras["inferred_auth_schemes"] = inferred_schemes

    raw: Optional[Dict[str, Any]] = None
    if include_raw and document.raw is not None:
        raw = {"gateway_config": dict(document.raw)}

    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format=format_key,
        protocol="http",
        identity=ApiIdentity(name=document.title),
        title=document.title,
        servers=servers,
        services=services,
        types=[],
        raw=raw,
        extras=api_extras,
    )
    return normalize_ordering(api)


def register_gateway_flavor(flavor: GatewayFlavor, *, class_name: Optional[str] = None) -> Type[Normalizer]:
    """Declare a gateway front end and derive its normalizer — FMT-7.6.

    This is the whole cost of a new front end on the shared side: a
    :class:`~app.gateway_family.GatewayFlavor` (key, ledger label, route provenance, whether
    its plugins are policy) and a route-extraction function returning a
    :class:`~app.gateway_config_model.GatewayConfigDocument`. Match normalization
    (:mod:`app.gateway_match`), operation synthesis, provenance classification and the
    schemaless-loss report are all shared.

    Args:
        flavor: The front end's declaration; added to the family if new.
        class_name: Name of the generated normalizer class (defaults to the key, CamelCased).

    Returns:
        The registered :class:`~app.normalizer.Normalizer` subclass for ``flavor.key``.
    """
    add_flavor(flavor)
    key = flavor.key
    parser = flavor.parser or "the front end's parser"

    def normalize(self: Normalizer, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, GatewayConfigDocument) or source.flavor != key:
            raise ValueError(f"{key} source must be a GatewayConfigDocument with flavor={key!r} (see {parser})")
        return normalize_gateway_config(source, format_key=key, include_raw=include_raw)

    name = class_name or "".join(part.capitalize() for part in key.replace("_", "-").split("-")) + "Normalizer"
    namespace = {
        "__doc__": f"Normalize a parsed {flavor.label} (format key ``{key}``) through the shared gateway middle.",
        "__module__": __name__,
        "format": key,
        "paradigm": ApiParadigm.REST,
        "normalize": normalize,
    }
    return type(name, (Normalizer,), namespace, register=True)


# One derived normalizer per family member. The names are kept as module attributes because
# callers and tests import them; every one is the same shared projection.
KongNormalizer = register_gateway_flavor(GATEWAY_FAMILY[KONG_FORMAT_KEY])
GatewayApiNormalizer = register_gateway_flavor(GATEWAY_FAMILY[GATEWAY_API_FORMAT_KEY])
EnvoyXdsNormalizer = register_gateway_flavor(GATEWAY_FAMILY[ENVOY_XDS_FORMAT_KEY])
IstioNormalizer = register_gateway_flavor(GATEWAY_FAMILY[ISTIO_FORMAT_KEY])
TraefikNormalizer = register_gateway_flavor(GATEWAY_FAMILY[TRAEFIK_FORMAT_KEY])
NginxNormalizer = register_gateway_flavor(GATEWAY_FAMILY[NGINX_FORMAT_KEY])
HaproxyNormalizer = register_gateway_flavor(GATEWAY_FAMILY[HAPROXY_FORMAT_KEY])
ConsulNormalizer = register_gateway_flavor(GATEWAY_FAMILY[CONSUL_FORMAT_KEY])
TykNormalizer = register_gateway_flavor(GATEWAY_FAMILY[TYK_FORMAT_KEY])
