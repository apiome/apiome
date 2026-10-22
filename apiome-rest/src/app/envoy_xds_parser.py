"""Parser for Envoy xDS route configuration — FMT-7.4 (#5458).

Reads Envoy's routing truth into the flavor-neutral
:class:`~app.gateway_config_model.GatewayConfigDocument`, from any of the four shapes it
is written in:

* a **static bootstrap** — ``static_resources.listeners[]`` whose
  ``HttpConnectionManager`` carries an inline ``route_config`` (or names one through
  ``rds``), plus ``static_resources.clusters[]``;
* a bare **``RouteConfiguration``** — ``name`` + ``virtual_hosts[]``;
* an xDS **``DiscoveryResponse``** — ``type_url`` + ``resources[]``, the wire form;
* a filesystem-xDS **resource file** — ``resources[]`` of typed ``RouteConfiguration`` /
  ``Cluster`` / ``Listener`` entries, as a bootstrap's ``path_config_source`` loads them.

``RouteConfiguration → VirtualHost → Route`` becomes one :class:`GatewayRoute` per Envoy
route, grouped by virtual host. Path matchers go through the shared table in
:mod:`app.mesh_route_common` (:data:`ENVOY_PATH_MATCHERS`), so they normalize exactly as
the ``gateway-api`` adapter's path types do. Header and query-parameter matchers become
match conditions; a ``:method`` header pins the method.

What the canonical model cannot hold is declared, never dropped: a ``connect_matcher``
route (no HTTP operation), match qualifiers such as ``runtime_fraction`` or ``grpc``,
inverted header matches, routes delivered dynamically through RDS/LDS/ADS. Traffic
policy (retries, timeouts, rewrites, CORS, rate limits, direct responses, redirects)
rides on the operations as named plugins.

A route naming a cluster the input does not define is ``INPUT_REFERENCE_UNRESOLVED`` —
but only when the input is the authority on clusters: one that declares clusters and
does not also take them from a control plane.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .gateway_config_model import (
    GatewayAuthHint,
    GatewayBackend,
    GatewayConfigDocument,
    GatewayConfigParseError,
    GatewayMatch,
    GatewayPlugin,
    GatewayRoute,
)
from .gateway_match import path_pattern, render_match_value
from .mesh_route_common import (
    LimitCollector,
    is_duration,
    load_yaml_documents,
    policy_plugin,
    raise_if_truncated_tail,
    reject_binary,
    render_string_match,
)

__all__ = [
    "ENVOY_AUTH_FILTER_SCHEMES",
    "ENVOY_PATH_MATCHERS",
    "ENVOY_FLAVOR",
    "classify_envoy_document",
    "is_envoy_xds",
    "parse_envoy_xds",
    "parse_envoy_xds_fileset",
]

#: Flavor key stamped on the parsed document.
ENVOY_FLAVOR = "envoy-xds"

#: Human name used in messages.
_LABEL = "Envoy xDS"

#: Envoy route path matcher → Gateway API path type. The second half of the mapping —
#: Gateway API path type → pattern kind — is :data:`app.gateway_api_parser.PATH_TYPE_KINDS`,
#: reached through :func:`app.gateway_match.path_pattern`, so this table and the
#: Gateway API adapter cannot disagree. ``path_separated_prefix`` is a segment-aware prefix
#: (``/seg`` matches ``/seg/x`` but not ``/segment``) — Gateway API's ``PathPrefix`` is
#: segment-aware too, which is why it maps there.
ENVOY_PATH_MATCHERS: Dict[str, str] = {
    "path": "Exact",
    "prefix": "PathPrefix",
    "path_separated_prefix": "PathPrefix",
    "safe_regex": "RegularExpression",
}

#: HTTP filter → canonical security scheme. ``None`` = an auth mechanism with no canonical
#: scheme (kept as an unmapped hint, reported as a gap).
ENVOY_AUTH_FILTER_SCHEMES: Dict[str, Optional[str]] = {
    "envoy.filters.http.jwt_authn": "bearer",
    "envoy.filters.http.oauth2": "oauth2",
    "envoy.filters.http.basic_auth": "basic",
    "envoy.filters.http.ext_authz": None,
}

#: The HTTP filter that only forwards — implied by every route, never a policy.
_ROUTER_FILTER = "envoy.filters.http.router"

#: The network filter that carries HTTP routing.
_HCM_FILTER = "envoy.filters.network.http_connection_manager"

#: Resource kinds (the last segment of an ``@type`` URL) this parser reads. Matching the kind
#: rather than the full URL reads xDS v3 (``envoy.config.route.v3.RouteConfiguration``) and v2
#: (``envoy.api.v2.RouteConfiguration``) alike.
_ROUTE_CONFIG_KIND = "RouteConfiguration"
_CLUSTER_KIND = "Cluster"
_LISTENER_KIND = "Listener"
_HCM_TYPE = "HttpConnectionManager"

#: Keys only a ``RouteConfiguration`` carries — with ``name``, they identify a bare one even
#: when it has no virtual hosts (which is then a semantic fault, not a different format).
_ROUTE_CONFIG_KEYS = frozenset(
    {
        "virtual_hosts",
        "vhds",
        "internal_only_headers",
        "response_headers_to_add",
        "response_headers_to_remove",
        "request_headers_to_add",
        "request_headers_to_remove",
        "validate_clusters",
        "most_specific_header_mutations_wins",
    }
)

#: Route-configuration-level keys kept as global policy plugins.
_ROUTE_CONFIG_POLICY_KEYS = (
    "internal_only_headers",
    "request_headers_to_add",
    "request_headers_to_remove",
    "response_headers_to_add",
    "response_headers_to_remove",
)

#: Virtual-host-level keys kept as policy plugins on every route of the host.
_VIRTUAL_HOST_POLICY_KEYS = (
    "cors",
    "rate_limits",
    "retry_policy",
    "request_headers_to_add",
    "request_headers_to_remove",
    "response_headers_to_add",
    "response_headers_to_remove",
)

#: Route-action keys kept as policy plugins on the route.
_ROUTE_ACTION_POLICY_KEYS = (
    "timeout",
    "idle_timeout",
    "retry_policy",
    "prefix_rewrite",
    "regex_rewrite",
    "host_rewrite_literal",
    "host_rewrite_header",
    "auto_host_rewrite",
    "request_mirror_policies",
    "hash_policy",
    "rate_limits",
    "upgrade_configs",
    "max_stream_duration",
    "priority",
    "cors",
)

#: Route-level keys (beside ``match`` and the action) kept as policy plugins.
_ROUTE_POLICY_KEYS = (
    "request_headers_to_add",
    "request_headers_to_remove",
    "response_headers_to_add",
    "response_headers_to_remove",
)

#: Match qualifiers that narrow *which* requests match without changing the operation.
#: Each is declared, with the reason the canonical model cannot say it.
_MATCH_QUALIFIERS: Dict[str, str] = {
    "runtime_fraction": "only a runtime-controlled fraction of requests matches; the canonical "
    "operation cannot say it is sampled",
    "grpc": "the route matches only gRPC requests; content-type gating has no canonical field",
    "tls_context": "the route matches on the client's TLS state, which has no canonical field",
    "dynamic_metadata": "the route matches on dynamic metadata set by filters at runtime",
    "filter_state": "the route matches on filter state set at runtime",
}

#: Route actions with no canonical analogue.
_UNMODELED_ACTIONS: Dict[str, str] = {
    "filter_action": "a filter action handles the request in a filter, not by routing it",
    "non_forwarding_action": "a non-forwarding action terminates without a backend",
}

#: Duration fields — a bare number in one of them at the very end of the file is a cut.
_DURATION_FIELDS = (
    "timeout",
    "idle_timeout",
    "per_try_timeout",
    "connect_timeout",
    "max_stream_duration",
    "grpc_timeout_header_max",
    "initial_fetch_timeout",
    "interval",
)

#: :func:`raise_if_truncated_tail` rules for Envoy: a duration with no unit.
_TAIL_RULES = {name: (lambda value: not is_duration(value)) for name in _DURATION_FIELDS}


def _type_of(value: Mapping[str, Any]) -> str:
    """The ``@type`` URL of a typed resource, or ``""``."""
    raw = value.get("@type")
    return raw if isinstance(raw, str) else ""


def _envoy_kind(value: Mapping[str, Any]) -> str:
    """The Envoy resource kind of a typed resource (``RouteConfiguration``…), or ``""``."""
    type_url = _type_of(value)
    return type_url.rsplit(".", 1)[-1] if "envoy." in type_url else ""


def _is_route_config(document: Mapping[str, Any]) -> bool:
    """True for a bare ``RouteConfiguration`` mapping (typed or not)."""
    if _envoy_kind(document) == _ROUTE_CONFIG_KIND:
        return True
    return any(key in document for key in _ROUTE_CONFIG_KEYS) and (
        "virtual_hosts" in document or isinstance(document.get("name"), str)
    )


def _is_envoy_resource(value: Any) -> bool:
    """True for one typed Envoy resource inside a ``resources[]`` list."""
    return isinstance(value, Mapping) and "envoy." in _type_of(value)


def classify_envoy_document(document: Any) -> Optional[str]:
    """Name the Envoy shape a parsed document has, or ``None`` when it is not Envoy.

    Args:
        document: One parsed YAML/JSON document.

    Returns:
        ``bootstrap``, ``discovery-response``, ``resources``, ``route-config`` or ``None``.
    """
    if not isinstance(document, Mapping):
        return None
    if isinstance(document.get("static_resources"), Mapping) or isinstance(
        document.get("dynamic_resources"), Mapping
    ):
        return "bootstrap"
    type_url = document.get("type_url")
    if isinstance(type_url, str) and "envoy." in type_url:
        return "discovery-response"
    resources = document.get("resources")
    if isinstance(resources, list) and resources and any(_is_envoy_resource(r) for r in resources):
        return "resources"
    if _is_route_config(document):
        return "route-config"
    return None


def is_envoy_xds(text: str) -> bool:
    """Cheap sniff: does ``text`` hold an Envoy bootstrap, route config or xDS resource?"""
    if not text or "\x00" in text:
        return False
    markers = (
        "virtual_hosts",
        "static_resources",
        "dynamic_resources",
        "envoy.config.",
        "envoy.api.v2",
        _HCM_TYPE,
        "validate_clusters",
        "internal_only_headers",
    )
    if not any(marker in text for marker in markers):
        return False
    try:
        documents = load_yaml_documents(text, format_label=_LABEL)
    except GatewayConfigParseError:
        return False
    return any(classify_envoy_document(document) is not None for document in documents)


# ---------------------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------------------


@dataclass
class _Listener:
    """What a listener's HTTP connection manager contributes to the routes it serves.

    Attributes:
        name: Listener name.
        https: True when the filter chain terminates TLS.
        auth: Auth hints implied by the manager's HTTP filters.
    """

    name: str
    https: bool = False
    auth: Tuple[GatewayAuthHint, ...] = ()


@dataclass
class _Collected:
    """Everything gathered from every document before routes are built.

    Attributes:
        route_configs: ``(config, origin, listener)`` — ``listener`` set for inline configs.
        rds_names: Route-configuration name → the listener that names it through ``rds``.
        clusters: Declared cluster names.
        dynamic_clusters: True when clusters also come from a control plane, so the input
            is not the authority on which clusters exist.
        saw_envoy: True once any document was recognized as Envoy.
        global_plugins: Non-auth HTTP filters and route-config policy.
        limits: Declared limits.
        redactions: Credential values redacted.
    """

    route_configs: List[Tuple[Mapping[str, Any], str, Optional[_Listener]]] = field(default_factory=list)
    rds_names: Dict[str, _Listener] = field(default_factory=dict)
    clusters: Set[str] = field(default_factory=set)
    dynamic_clusters: bool = False
    saw_envoy: bool = False
    global_plugins: List[GatewayPlugin] = field(default_factory=list)
    limits: LimitCollector = field(default_factory=LimitCollector)
    redactions: int = 0


def _hcm_config(network_filter: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """The ``HttpConnectionManager`` config of a network filter, or ``None``."""
    typed = network_filter.get("typed_config")
    if isinstance(typed, Mapping) and _HCM_TYPE in _type_of(typed):
        return typed
    if network_filter.get("name") == _HCM_FILTER:
        legacy = network_filter.get("config") if isinstance(network_filter.get("config"), Mapping) else typed
        return legacy if isinstance(legacy, Mapping) else None
    return None


def _auth_hint(http_filter: Mapping[str, Any], listener_name: str) -> Optional[GatewayAuthHint]:
    """An auth hint for an authentication HTTP filter, or ``None`` for any other filter."""
    name = http_filter.get("name")
    if not isinstance(name, str) or name not in ENVOY_AUTH_FILTER_SCHEMES:
        return None
    typed = http_filter.get("typed_config") if isinstance(http_filter.get("typed_config"), Mapping) else {}
    detail: Dict[str, Any] = {}
    providers = typed.get("providers")
    if isinstance(providers, Mapping) and providers:
        detail["providers"] = sorted(str(key) for key in providers)
        issuers = sorted(
            {
                str(provider.get("issuer"))
                for provider in providers.values()
                if isinstance(provider, Mapping) and provider.get("issuer")
            }
        )
        if issuers:
            detail["issuers"] = issuers
    return GatewayAuthHint(
        scheme=ENVOY_AUTH_FILTER_SCHEMES[name],
        plugin=name,
        scope="global",
        attached_to=listener_name,
        detail=detail,
    )


def _read_listener(listener: Mapping[str, Any], state: _Collected, origin: str) -> None:
    """Collect a listener's HTTP connection managers: inline routes, RDS names, filters."""
    name = str(listener.get("name") or f"listener-{len(state.rds_names) + len(state.route_configs)}")
    for chain in listener.get("filter_chains") or []:
        if not isinstance(chain, Mapping):
            continue
        https = isinstance(chain.get("transport_socket"), Mapping)
        for network_filter in chain.get("filters") or []:
            if not isinstance(network_filter, Mapping):
                continue
            hcm = _hcm_config(network_filter)
            if hcm is None:
                continue
            auth: List[GatewayAuthHint] = []
            for http_filter in hcm.get("http_filters") or []:
                if not isinstance(http_filter, Mapping):
                    continue
                hint = _auth_hint(http_filter, name)
                if hint is not None:
                    auth.append(hint)
                    continue
                filter_name = http_filter.get("name")
                if isinstance(filter_name, str) and filter_name and filter_name != _ROUTER_FILTER:
                    plugin, count = policy_plugin(
                        filter_name, http_filter.get("typed_config") or {}, scope="global", attached_to=name
                    )
                    state.global_plugins.append(plugin)
                    state.redactions += count
            context = _Listener(name=name, https=https, auth=tuple(auth))
            inline = hcm.get("route_config")
            if isinstance(inline, Mapping):
                state.route_configs.append((inline, f"{origin}:{name}", context))
            rds = hcm.get("rds")
            if isinstance(rds, Mapping) and isinstance(rds.get("route_config_name"), str):
                state.rds_names[rds["route_config_name"]] = context
            if isinstance(hcm.get("scoped_routes"), Mapping):
                state.limits.add(
                    "scoped_routes",
                    "scoped route configurations are selected per request at runtime; their "
                    "routes are not part of this input",
                )


def _path_config_member(source: Any) -> Optional[str]:
    """The file a ``path_config_source`` (or legacy ``path``) loads, when it names one."""
    if not isinstance(source, Mapping):
        return None
    path_source = source.get("path_config_source")
    if isinstance(path_source, Mapping) and isinstance(path_source.get("path"), str):
        return path_source["path"]
    if isinstance(source.get("path"), str):
        return source["path"]
    return None


def _read_bootstrap(
    document: Mapping[str, Any], state: _Collected, origin: str, member_names: Set[str]
) -> None:
    """Collect a bootstrap's static listeners and clusters, and how dynamic it is."""
    static = document.get("static_resources") if isinstance(document.get("static_resources"), Mapping) else {}
    for listener in static.get("listeners") or []:
        if isinstance(listener, Mapping):
            _read_listener(listener, state, origin)
    for cluster in static.get("clusters") or []:
        if isinstance(cluster, Mapping) and isinstance(cluster.get("name"), str):
            state.clusters.add(cluster["name"])

    dynamic = document.get("dynamic_resources") if isinstance(document.get("dynamic_resources"), Mapping) else {}
    cds = dynamic.get("cds_config")
    if cds is not None:
        member = _path_config_member(cds)
        if member is None or posixpath.basename(member) not in member_names:
            # A control plane (or a file not supplied) also delivers clusters, so a route
            # naming an unknown cluster is not provably dangling.
            state.dynamic_clusters = True
    lds = dynamic.get("lds_config")
    if lds is not None:
        member = _path_config_member(lds)
        if member is None or posixpath.basename(member) not in member_names:
            state.limits.add(
                "dynamic_resources.lds_config",
                "listeners delivered at runtime by xDS are not part of this input; only the "
                "routes the input itself carries are imported",
            )


def _read_resources(resources: Sequence[Any], state: _Collected, origin: str) -> None:
    """Collect typed resources from a ``DiscoveryResponse`` or a filesystem-xDS file."""
    for index, resource in enumerate(resources):
        if not isinstance(resource, Mapping):
            continue
        kind = _envoy_kind(resource)
        if kind == _ROUTE_CONFIG_KIND:
            state.route_configs.append((resource, f"{origin}.resources[{index}]", None))
        elif kind == _CLUSTER_KIND:
            if isinstance(resource.get("name"), str):
                state.clusters.add(resource["name"])
        elif kind == _LISTENER_KIND:
            _read_listener(resource, state, origin)
        elif kind:
            state.limits.add(
                f"resource.{kind}",
                f"{kind} resources do not describe the HTTP route surface",
            )


def _collect(document: Any, state: _Collected, origin: str, member_names: Set[str]) -> None:
    """Fold one parsed document into ``state``."""
    shape = classify_envoy_document(document)
    if shape is None:
        return
    state.saw_envoy = True
    if shape == "bootstrap":
        _read_bootstrap(document, state, origin, member_names)
    elif shape in ("discovery-response", "resources"):
        _read_resources(document.get("resources") or [], state, origin)
    else:
        state.route_configs.append((document, origin, None))


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


def _header_conditions(
    entries: Any, limits: LimitCollector
) -> Tuple[Optional[str], Tuple[Tuple[str, str], ...]]:
    """Read ``match.headers``: the pinned method (from ``:method``) and header conditions."""
    method: Optional[str] = None
    pairs: List[Tuple[str, str]] = []
    if not isinstance(entries, list):
        return method, ()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str):
            continue
        name = entry["name"]
        if entry.get("invert_match"):
            limits.add(
                "match.headers.invert_match",
                "an inverted header match (the route applies when the header does NOT match) "
                "has no canonical parameter form",
            )
            continue
        value = _header_value(entry)
        if name == ":method":
            if value and not value.startswith(("prefix:", "suffix:", "contains:", "regex:")):
                method = value.upper()
            else:
                limits.add(
                    "match.headers.:method",
                    "a non-literal :method match cannot pin one HTTP method",
                )
            continue
        if name.startswith(":"):
            limits.add(
                f"match.headers.{name}",
                f"the {name} pseudo-header match has no canonical parameter form",
            )
            continue
        pairs.append((name, value or ""))
    return method, tuple(pairs)


def _header_value(entry: Mapping[str, Any]) -> Optional[str]:
    """The rendered value of one header/query matcher (``""`` for a presence match)."""
    if entry.get("present_match"):
        return ""
    rendered = render_string_match(entry.get("string_match"))
    if rendered is not None:
        return rendered
    legacy = {
        "exact": entry.get("exact_match"),
        "prefix": entry.get("prefix_match"),
        "suffix": entry.get("suffix_match"),
        "contains": entry.get("contains_match"),
    }
    rendered = render_string_match({key: value for key, value in legacy.items() if value is not None})
    if rendered is not None:
        return rendered
    safe = entry.get("safe_regex_match")
    if isinstance(safe, Mapping) and isinstance(safe.get("regex"), str):
        return render_match_value("regex", safe["regex"])
    return None


def _query_conditions(entries: Any) -> Tuple[Tuple[str, str], ...]:
    """Read ``match.query_parameters`` as ``(name, value)`` conditions."""
    if not isinstance(entries, list):
        return ()
    pairs: List[Tuple[str, str]] = []
    for entry in entries:
        if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
            pairs.append((entry["name"], _header_value(entry) or ""))
    return tuple(pairs)


def _route_match(match: Mapping[str, Any], limits: LimitCollector) -> Optional[GatewayMatch]:
    """Turn an Envoy ``RouteMatch`` into a match condition, or ``None`` when it has no HTTP path."""
    pattern = None
    for key, path_type in ENVOY_PATH_MATCHERS.items():
        if key not in match:
            continue
        raw = match[key]
        value = raw.get("regex") if key == "safe_regex" and isinstance(raw, Mapping) else raw
        if isinstance(value, str):
            pattern = path_pattern(path_type, value)
        break
    if pattern is None:
        if "connect_matcher" in match:
            limits.add(
                "match.connect_matcher",
                "a CONNECT route tunnels raw bytes; it has no canonical HTTP operation and "
                "is not imported as one",
            )
        elif "path_match_policy" in match:
            limits.add(
                "match.path_match_policy",
                "a path-match extension (URI template) is evaluated by a plugin; the route "
                "cannot be normalized without it",
            )
        else:
            limits.add("match.(no path)", "the route declares no path matcher Envoy accepts")
        return None
    for qualifier, reason in _MATCH_QUALIFIERS.items():
        if qualifier in match:
            limits.add(f"match.{qualifier}", reason)
    method, headers = _header_conditions(match.get("headers"), limits)
    return GatewayMatch(
        path=pattern,
        method=method,
        headers=headers,
        query=_query_conditions(match.get("query_parameters")),
    )


def _route_backends(action: Mapping[str, Any], limits: LimitCollector) -> Tuple[GatewayBackend, ...]:
    """The clusters a route action forwards to."""
    if isinstance(action.get("cluster"), str):
        return (GatewayBackend(name=action["cluster"]),)
    weighted = action.get("weighted_clusters")
    if isinstance(weighted, Mapping):
        backends = []
        for entry in weighted.get("clusters") or []:
            if isinstance(entry, Mapping) and isinstance(entry.get("name"), str):
                weight = entry.get("weight")
                backends.append(
                    GatewayBackend(name=entry["name"], weight=weight if isinstance(weight, int) else None)
                )
        return tuple(backends)
    if "cluster_header" in action:
        limits.add(
            "route.cluster_header",
            "the cluster is chosen from a request header at runtime; no backend is declared",
        )
    if "cluster_specifier_plugin" in action or "inline_cluster_specifier_plugin" in action:
        limits.add(
            "route.cluster_specifier_plugin",
            "a cluster-specifier plugin chooses the backend at runtime",
        )
    return ()


@dataclass
class _Built:
    """Routes built from the collected route configurations."""

    routes: List[GatewayRoute] = field(default_factory=list)
    redactions: int = 0


def _build_routes(state: _Collected) -> _Built:
    """Build one :class:`GatewayRoute` per Envoy route, grouped by virtual host."""
    built = _Built()
    limits = state.limits
    vhost_names: Dict[str, int] = {}
    for config, _origin, _listener in state.route_configs:
        for vhost in config.get("virtual_hosts") or []:
            if isinstance(vhost, Mapping) and isinstance(vhost.get("name"), str):
                vhost_names[vhost["name"]] = vhost_names.get(vhost["name"], 0) + 1

    for config, origin, inline_listener in state.route_configs:
        config_name = str(config.get("name") or "route_config")
        listener = inline_listener or state.rds_names.get(config_name)
        for key in _ROUTE_CONFIG_POLICY_KEYS:
            if key in config:
                plugin, count = policy_plugin(key, config[key], scope="global", attached_to=config_name)
                state.global_plugins.append(plugin)
                built.redactions += count
        if "vhds" in config:
            limits.add("vhds", "virtual hosts delivered on demand (VHDS) are not part of this input")

        for vhost_index, vhost in enumerate(config.get("virtual_hosts") or []):
            if not isinstance(vhost, Mapping):
                continue
            vhost_name = str(vhost.get("name") or f"{config_name}#vhost-{vhost_index}")
            group = f"{config_name}/{vhost_name}" if vhost_names.get(vhost_name, 0) > 1 else vhost_name
            hosts = tuple(
                sorted({str(domain) for domain in vhost.get("domains") or [] if str(domain) != "*"})
            )
            require_tls = str(vhost.get("require_tls") or "NONE").upper()
            https = require_tls in ("ALL", "EXTERNAL_ONLY") or bool(listener and listener.https)
            vhost_plugins: List[GatewayPlugin] = []
            for key in _VIRTUAL_HOST_POLICY_KEYS:
                if key in vhost:
                    plugin, count = policy_plugin(key, vhost[key], scope="service", attached_to=vhost_name)
                    vhost_plugins.append(plugin)
                    built.redactions += count
            per_filter = vhost.get("typed_per_filter_config")
            if isinstance(per_filter, Mapping):
                for filter_name, filter_config in per_filter.items():
                    plugin, count = policy_plugin(
                        str(filter_name), filter_config, scope="service", attached_to=vhost_name
                    )
                    vhost_plugins.append(plugin)
                    built.redactions += count

            for route_index, route in enumerate(vhost.get("routes") or []):
                if not isinstance(route, Mapping) or not isinstance(route.get("match"), Mapping):
                    continue
                match = _route_match(route["match"], limits)
                if match is None:
                    continue
                route_name = str(route.get("name") or f"{vhost_name}#route-{route_index}")
                plugins = list(vhost_plugins)
                backends: Tuple[GatewayBackend, ...] = ()
                action = route.get("route")
                if isinstance(action, Mapping):
                    backends = _route_backends(action, limits)
                    for key in _ROUTE_ACTION_POLICY_KEYS:
                        if key in action:
                            plugin, count = policy_plugin(key, action[key], scope="route", attached_to=route_name)
                            plugins.append(plugin)
                            built.redactions += count
                for terminal in ("direct_response", "redirect"):
                    if isinstance(route.get(terminal), Mapping):
                        plugin, count = policy_plugin(
                            terminal, route[terminal], scope="route", attached_to=route_name
                        )
                        plugins.append(plugin)
                        built.redactions += count
                for key, reason in _UNMODELED_ACTIONS.items():
                    if key in route:
                        limits.add(f"route.{key}", reason)
                for key in _ROUTE_POLICY_KEYS:
                    if key in route:
                        plugin, count = policy_plugin(key, route[key], scope="route", attached_to=route_name)
                        plugins.append(plugin)
                        built.redactions += count
                route_filters = route.get("typed_per_filter_config")
                if isinstance(route_filters, Mapping):
                    for filter_name, filter_config in route_filters.items():
                        plugin, count = policy_plugin(
                            str(filter_name), filter_config, scope="route", attached_to=route_name
                        )
                        plugins.append(plugin)
                        built.redactions += count

                extras: Dict[str, Any] = {"route_config": config_name, "virtual_host": vhost_name}
                if route["match"].get("case_sensitive") is False:
                    extras["case_sensitive"] = False
                if require_tls != "NONE":
                    extras["require_tls"] = require_tls
                built.routes.append(
                    GatewayRoute(
                        name=route_name,
                        service_name=group,
                        hosts=hosts,
                        matches=(match,),
                        protocols=("https",) if https else ("http",),
                        auth=listener.auth if listener else (),
                        plugins=tuple(plugins),
                        backends=backends,
                        source_location=f"{origin}.virtual_hosts[{vhost_index}].routes[{route_index}]",
                        extras=extras,
                    )
                )
    return built


def _check_cluster_references(state: _Collected, routes: Sequence[GatewayRoute]) -> None:
    """Refuse a route that names a cluster the input defines no cluster for.

    Only when the input is the authority on clusters: it declares some, and none come
    from a control plane. A bare route configuration declares none, so its references
    stand on their own.
    """
    if not state.clusters or state.dynamic_clusters:
        return
    for route in routes:
        for backend in route.backends:
            if backend.name not in state.clusters:
                raise GatewayConfigParseError(
                    f"Route {route.name!r} targets cluster {backend.name!r}, which is not "
                    f"defined (declared clusters: {', '.join(sorted(state.clusters))})",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )


def _document_from(state: _Collected, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Build routes from the collected state and assemble the document."""
    if not state.saw_envoy:
        raise GatewayConfigParseError(
            "No Envoy bootstrap, route configuration or xDS resource found",
            code="FORMAT_MISMATCH",
        )
    for name in sorted(state.rds_names):
        if not any(str(config.get("name") or "") == name for config, _o, _l in state.route_configs):
            state.limits.add(
                f"rds.{name}",
                f"route configuration {name!r} is delivered through RDS and is not part of "
                "this input",
            )
    built = _build_routes(state)
    if not built.routes:
        raise GatewayConfigParseError(
            "The Envoy configuration declares no HTTP routes — no virtual host carries a "
            "route with a path matcher",
            code="INPUT_SEMANTIC_INVALID",
        )
    _check_cluster_references(state, built.routes)

    route_config_names = sorted({str(config.get("name") or "") for config, _o, _l in state.route_configs} - {""})
    return GatewayConfigDocument(
        flavor=ENVOY_FLAVOR,
        title=title or source_label or (route_config_names[0] if route_config_names else "Envoy routes"),
        routes=tuple(built.routes),
        global_plugins=tuple(state.global_plugins),
        global_auth=(),
        ignored=state.limits.as_ignored(),
        credential_redactions=state.redactions + built.redactions,
        source_label=source_label,
        raw={
            "flavor": ENVOY_FLAVOR,
            "route_configs": route_config_names,
            "clusters": sorted(state.clusters),
            "route_names": sorted(route.name for route in built.routes),
            "hostnames": sorted({host for route in built.routes for host in route.hosts}),
        },
    )


def _read_text(text: str, state: _Collected, origin: str, member_names: Set[str]) -> None:
    """Decode-check, parse and fold one text into ``state``."""
    reject_binary(text, format_label=_LABEL)
    documents = load_yaml_documents(text, format_label=_LABEL)
    if any(classify_envoy_document(document) for document in documents):
        raise_if_truncated_tail(text, format_label=_LABEL, rules=_TAIL_RULES)
    for index, document in enumerate(documents):
        _collect(document, state, f"{origin}[{index}]" if len(documents) > 1 else origin, member_names)


def parse_envoy_xds(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse one Envoy document (bootstrap, route configuration, xDS response or resource file).

    Args:
        text: YAML or JSON text; multi-document YAML streams are read in full.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="envoy-xds"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED`` for broken or cut-off YAML,
            ``FORMAT_MISMATCH`` when nothing is Envoy, ``INPUT_SEMANTIC_INVALID`` when no
            HTTP route is declared, and ``INPUT_REFERENCE_UNRESOLVED`` for a route naming
            an undefined cluster.
    """
    state = _Collected()
    _read_text(text, state, source_label or "document", set())
    return _document_from(state, title=None, source_label=source_label)


def parse_envoy_xds_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse a filesystem-xDS set: a bootstrap plus the resource files it loads.

    Every member is read into one collection, so a bootstrap's ``rds`` name resolves to the
    route configuration in a sibling file, and the clusters a sibling ``cds`` file supplies
    count as declared. Members that are not Envoy are ignored.

    Args:
        members: Member path → text.
        root: The root member, read first when known.
        source_label: Label for the merged document.

    Returns:
        The merged document.

    Raises:
        GatewayConfigParseError: As :func:`parse_envoy_xds`; a member's syntax error carries
            the member path.
    """
    ordered = sorted(members)
    if root in members:
        ordered = [root] + [path for path in ordered if path != root]
    member_names = {posixpath.basename(path) for path in members}
    state = _Collected()
    for path in ordered:
        try:
            _read_text(members[path], state, path, member_names)
        except GatewayConfigParseError as exc:
            raise GatewayConfigParseError(f"{path}: {exc}", code=exc.code) from exc
    return _document_from(state, title=source_label, source_label=source_label or root)
