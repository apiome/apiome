"""Envoy xDS emitter: canonical model → an Envoy ``RouteConfiguration`` — FMT-7.7 (#5461).

The inverse of :class:`app.envoy_xds_import_source.EnvoyXdsImportSource` and an
implementation of the :class:`app.emitter.Emitter` SPI. The projection is the family's
shared :func:`app.gateway_config_emitter.plan_gateway_config`; this module only renders the
planned :class:`~app.gateway_config_model.GatewayConfigDocument` as a v3
``RouteConfiguration`` — the resource RDS serves and a bootstrap embeds:

* each planned **service** becomes a ``virtual_host`` (``domains`` from the route hosts,
  ``*`` when none are declared; ``require_tls: ALL`` when the routes are HTTPS-only);
* each **match condition** becomes one ``route``: ``path`` / ``prefix`` / ``safe_regex``
  from the path kind, a ``:method`` header for the method, ``headers`` and
  ``query_parameters`` with ``string_match`` operators recovered from each value;
* each route's **backends** become ``cluster`` or ``weighted_clusters``; a route with none
  forwards to a cluster named after its service, reported as synthesized.

What a ``RouteConfiguration`` cannot hold is declared, never invented: listener HTTP filters
are where Envoy authenticates, so auth is a loss; policies (retries, rewrites, CORS) are
recorded by name only in the canonical model, so they are a loss; clusters (with their
endpoints) are not part of a route configuration, so the emitted file references them.

:func:`validate_route_configuration_document` is the product gate: the structural rules of
Envoy's ``RouteConfiguration`` proto (required names, the one-of path specifier and route
action, the one-of string matcher, non-empty domains) plus a re-import through the adapter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import CapabilityProfile, EmitOptions, EmitResult, Emitter, LossKind, Provenance
from .fidelity_rulepack import CapabilityRulePack
from .gateway_config_model import GatewayMatch, GatewayRoute
from .gateway_config_normalizer import ENVOY_XDS_FORMAT_KEY
from .gateway_emit_common import (
    OUTPUT_FORMATS,
    ROUTING_SURFACE_PROFILE,
    GatewayEmitOptions,
    GatewayEmitPlan,
    RoutingSurfaceRulePack,
    coerce_gateway_options,
    dump_documents,
    pattern_value,
    single_file_result,
)
from .gateway_match import parse_match_value

__all__ = [
    "EnvoyXdsEmitOptions",
    "EnvoyXdsEmitter",
    "EnvoyXdsFidelityRulePack",
    "route_configuration_violations",
    "validate_route_configuration_document",
]

_LABEL = "Envoy RouteConfiguration"

#: Path kind → ``RouteMatch`` path specifier.
_PATH_SPECIFIERS = {"exact": "path", "prefix": "prefix", "regex": "safe_regex"}

#: The one-of path specifiers a ``RouteMatch`` accepts.
_ROUTE_MATCH_SPECIFIERS = (
    "prefix",
    "path",
    "safe_regex",
    "connect_matcher",
    "path_separated_prefix",
    "path_match_policy",
)

#: The one-of actions a ``Route`` accepts.
_ROUTE_ACTIONS = ("route", "redirect", "direct_response", "filter_action", "non_forwarding_action")

#: The one-of cluster specifiers a ``RouteAction`` accepts.
_CLUSTER_SPECIFIERS = (
    "cluster",
    "cluster_header",
    "weighted_clusters",
    "cluster_specifier_plugin",
    "inline_cluster_specifier_plugin",
)

#: The one-of operators of a ``StringMatcher``.
_STRING_MATCHERS = ("exact", "prefix", "suffix", "contains", "safe_regex")


class EnvoyXdsFidelityRulePack(RoutingSurfaceRulePack):
    """Fidelity rules for Envoy ``RouteConfiguration`` export (FMT-7.7)."""

    target_label = _LABEL
    target_flavor = ENVOY_XDS_FORMAT_KEY
    carries_policies = False
    carries_auth = False


class EnvoyXdsEmitOptions(GatewayEmitOptions):
    """Per-target options for :class:`EnvoyXdsEmitter`."""

    route_config_name: Optional[str] = None


# ===========================================================================
# Rendering
# ===========================================================================


def _string_match(rendered: str) -> Dict[str, Any]:
    """A rendered ``match_value`` → an Envoy ``StringMatcher`` (``present_match`` when empty)."""
    operator, value = parse_match_value(rendered)
    if not value:
        return {}
    if operator == "regex":
        return {"safe_regex": {"regex": value}}
    return {operator: value}


def _header_matcher(name: str, rendered: str) -> Dict[str, Any]:
    """One ``HeaderMatcher``."""
    matcher = _string_match(rendered)
    return {"name": name, "string_match": matcher} if matcher else {"name": name, "present_match": True}


def _route_match(match: GatewayMatch, case_sensitive: Optional[bool]) -> Dict[str, Any]:
    """One ``RouteMatch``."""
    out: Dict[str, Any] = {}
    pattern = match.path
    if pattern is None:
        out["prefix"] = "/"
    elif pattern.kind == "regex":
        out["safe_regex"] = {"regex": pattern_value(pattern)}
    else:
        out[_PATH_SPECIFIERS[pattern.kind]] = pattern_value(pattern)
    if case_sensitive is False:
        out["case_sensitive"] = False
    headers: List[Dict[str, Any]] = []
    if match.method:
        headers.append({"name": ":method", "string_match": {"exact": match.method}})
    headers.extend(_header_matcher(name, value) for name, value in match.headers)
    if headers:
        out["headers"] = headers
    if match.query:
        out["query_parameters"] = [_header_matcher(name, value) for name, value in match.query]
    return out


class _EnvoyWriter:
    """Render one planned document as a ``RouteConfiguration``."""

    def __init__(self, api: CanonicalApi, options: EnvoyXdsEmitOptions) -> None:
        self.options = options
        self.plan = GatewayEmitPlan(
            api, flavor=ENVOY_XDS_FORMAT_KEY, label=_LABEL, service_naming=options.service_naming
        )
        self.plan.declare_title_loss()
        self.plan.declare_global_plugin_losses()

    def build(self) -> Dict[str, Any]:
        """The ``RouteConfiguration`` mapping."""
        plan = self.plan
        document = plan.document
        names = sorted(
            {str(r.extras["route_config"]) for r in document.routes if isinstance(r.extras.get("route_config"), str)}
        )
        name = self.options.route_config_name or (names[0] if len(names) == 1 else "routes")
        plan.tracker.record(
            "/name",
            Provenance.SOURCE if len(names) == 1 and not self.options.route_config_name else Provenance.DEFAULT,
            "Route configuration name recovered from the routes' `route_config` extra, or the default.",
        )
        groups: Dict[str, List[GatewayRoute]] = {}
        for route in document.routes:
            groups.setdefault(route.service_name or "default", []).append(route)
        virtual_hosts: List[Dict[str, Any]] = []
        owner: Dict[str, Dict[str, Any]] = {}
        for service, routes in groups.items():
            vhost = self._virtual_host(service, routes, len(virtual_hosts))
            self._claim_domains(vhost, virtual_hosts, owner)
        return {"name": name, "virtual_hosts": virtual_hosts}

    def _claim_domains(
        self, vhost: Dict[str, Any], virtual_hosts: List[Dict[str, Any]], owner: Dict[str, Dict[str, Any]]
    ) -> None:
        """Add ``vhost`` while keeping every domain on exactly one virtual host.

        Envoy refuses a route configuration that serves one domain from two virtual hosts
        (two nginx servers for the same name on different ports produce exactly that). A
        domain already served is dropped from the later virtual host; one left with no
        domain merges its routes into the virtual host that serves its first domain. Both
        are reported, because a re-import groups the routes differently.
        """
        taken = [domain for domain in vhost["domains"] if domain in owner]
        free = [domain for domain in vhost["domains"] if domain not in owner]
        if taken and not free:
            target = owner[taken[0]]
            target["routes"].extend(vhost["routes"])
            self.plan.losses.record(
                LossKind.INFERRED,
                "merged-virtual-host",
                f"Virtual host {vhost['name']!r} serves only domains virtual host {target['name']!r} "
                "already serves; Envoy allows each domain on one virtual host, so its routes were "
                f"merged into {target['name']!r}.",
                vhost["name"],
            )
            return
        if taken:
            vhost["domains"] = free
            self.plan.losses.record(
                LossKind.INFERRED,
                "shared-domain",
                f"Domains {', '.join(taken)} of virtual host {vhost['name']!r} are already served by "
                "another virtual host; Envoy allows each domain once, so they were dropped here.",
                vhost["name"],
            )
        for domain in vhost["domains"]:
            owner[domain] = vhost
        virtual_hosts.append(vhost)

    def _virtual_host(self, service: str, routes: Sequence[GatewayRoute], index: int) -> Dict[str, Any]:
        """One ``VirtualHost`` for one planned service."""
        vhost_name = next(
            (str(r.extras["virtual_host"]) for r in routes if isinstance(r.extras.get("virtual_host"), str)), service
        )
        domains = sorted({host for route in routes for host in route.hosts}) or ["*"]
        vhost: Dict[str, Any] = {"name": vhost_name, "domains": domains}
        tls = {str(r.extras["require_tls"]) for r in routes if isinstance(r.extras.get("require_tls"), str)}
        if tls:
            vhost["require_tls"] = sorted(tls)[0]
        elif all(route.protocols == ("https",) for route in routes):
            vhost["require_tls"] = "ALL"
            self.plan.tracker.record(
                f"/virtual_hosts/{index}/require_tls",
                Provenance.INFERRED,
                "HTTPS-only routes: TLS is required on the virtual host.",
            )
        vhost["routes"] = [entry for route in routes for entry in self._routes(route, service)]
        return vhost

    def _routes(self, route: GatewayRoute, service: str) -> List[Dict[str, Any]]:
        """One Envoy ``Route`` per match condition of a planned route."""
        plan = self.plan
        plan.declare_plugin_losses(route)
        plan.declare_auth_losses(
            route, reason="Envoy authenticates in a listener HTTP filter, which a route configuration does not carry"
        )
        case_sensitive = route.extras.get("case_sensitive")
        action: Dict[str, Any]
        if len(route.backends) > 1:
            action = {
                "weighted_clusters": {
                    "clusters": [
                        {"name": backend.name, "weight": backend.weight if backend.weight is not None else 1}
                        for backend in route.backends
                    ]
                }
            }
            if any(backend.weight is None for backend in route.backends):
                plan.losses.record(
                    LossKind.INFERRED,
                    "synthesized-weight",
                    f"Route {route.name!r} splits traffic across backends with no declared weight; "
                    "each was given weight 1.",
                    route.name,
                )
        elif route.backends:
            action = {"cluster": route.backends[0].name}
        else:
            action = {"cluster": service}
            plan.losses.record(
                LossKind.INFERRED,
                "synthesized-cluster",
                f"Route {route.name!r} declares no backend; it forwards to a cluster named after its "
                f"service ({service!r}), which the bootstrap must define.",
                route.name,
            )
        for backend in route.backends:
            if backend.subset:
                plan.losses.record(
                    LossKind.NA,
                    "backend-subset",
                    f"Route {route.name!r} targets subset {backend.subset!r} of {backend.name!r}; an "
                    "Envoy route names a cluster, not a subset, so the subset is not emitted.",
                    route.name,
                )
        entries = []
        for index, match in enumerate(route.matches):
            name = route.name if len(route.matches) == 1 else f"{route.name}-{index + 1}"
            entries.append({"name": name, "match": _route_match(match, case_sensitive), "route": dict(action)})
        return entries


class EnvoyXdsEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an Envoy v3 ``RouteConfiguration``."""

    key = ENVOY_XDS_FORMAT_KEY
    format = ENVOY_XDS_FORMAT_KEY
    label = "Envoy xDS RouteConfiguration"
    description = (
        "Export as an Envoy v3 RouteConfiguration (route-config.yaml): a virtual host per "
        "service, one route per match with path, method, header and query matchers, and the "
        "clusters each route forwards to."
    )
    icon = "route"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = EnvoyXdsEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A route configuration is a routing surface: operations only, no payloads."""
        return ROUTING_SURFACE_PROFILE

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Envoy route-configuration degradation rules."""
        return EnvoyXdsFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[EnvoyXdsEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit ``api`` as one route-configuration file.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            ValueError: When ``api`` has no HTTP operation to route.
        """
        options = coerce_gateway_options(opts, EnvoyXdsEmitOptions, label=_LABEL)
        writer = _EnvoyWriter(api, options)  # type: ignore[arg-type]
        content = dump_documents([writer.build()], output_format=options.output_format, pretty=options.pretty_print)
        return single_file_result(
            writer.plan,
            path=f"route-config.{options.output_format}",
            content=content,
            media_type=OUTPUT_FORMATS[options.output_format],
        )


# ===========================================================================
# Product gate
# ===========================================================================


def _one_of(mapping: Mapping[str, Any], keys: Sequence[str], where: str, errors: List[str]) -> None:
    """Require exactly one of ``keys`` in ``mapping``."""
    present = [key for key in keys if key in mapping]
    if len(present) != 1:
        errors.append(f"{where}: exactly one of {', '.join(keys)} is required (found {', '.join(present) or 'none'})")


def _check_string_matchers(entries: Any, where: str, errors: List[str]) -> None:
    """Header / query-parameter matchers: a name and one matcher."""
    if entries is None:
        return
    if not isinstance(entries, list):
        errors.append(f"{where}: must be a list")
        return
    for index, entry in enumerate(entries):
        spot = f"{where}[{index}]"
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str) or not entry["name"]:
            errors.append(f"{spot}: a matcher needs a non-empty name")
            continue
        matcher = entry.get("string_match")
        if matcher is not None:
            if not isinstance(matcher, Mapping):
                errors.append(f"{spot}.string_match: must be a mapping")
            else:
                _one_of(matcher, _STRING_MATCHERS, f"{spot}.string_match", errors)


def route_configuration_violations(document: Any) -> List[str]:
    """The structural rules of Envoy's v3 ``RouteConfiguration`` a document breaks.

    Args:
        document: The parsed document.

    Returns:
        One message per violation; empty when the document is valid.
    """
    errors: List[str] = []
    if not isinstance(document, Mapping):
        return ["the document must be a RouteConfiguration mapping"]
    if not isinstance(document.get("name"), str) or not document["name"]:
        errors.append("name: a RouteConfiguration needs a non-empty name")
    vhosts = document.get("virtual_hosts")
    if not isinstance(vhosts, list) or not vhosts:
        return errors + ["virtual_hosts: at least one virtual host is required"]
    seen_names: set = set()
    seen_domains: set = set()
    for v_index, vhost in enumerate(vhosts):
        where = f"virtual_hosts[{v_index}]"
        if not isinstance(vhost, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        name = vhost.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{where}.name: required")
        elif name in seen_names:
            errors.append(f"{where}.name: {name!r} is not unique")
        seen_names.add(name)
        domains = vhost.get("domains")
        if not isinstance(domains, list) or not domains:
            errors.append(f"{where}.domains: at least one domain is required")
        else:
            for domain in domains:
                if domain in seen_domains:
                    errors.append(f"{where}.domains: {domain!r} is already served by another virtual host")
                seen_domains.add(domain)
        if vhost.get("require_tls") not in (None, "NONE", "EXTERNAL_ONLY", "ALL"):
            errors.append(f"{where}.require_tls: must be NONE, EXTERNAL_ONLY or ALL")
        for r_index, route in enumerate(vhost.get("routes") or []):
            spot = f"{where}.routes[{r_index}]"
            if not isinstance(route, Mapping) or not isinstance(route.get("match"), Mapping):
                errors.append(f"{spot}: a route needs a match")
                continue
            _one_of(route["match"], _ROUTE_MATCH_SPECIFIERS, f"{spot}.match", errors)
            _check_string_matchers(route["match"].get("headers"), f"{spot}.match.headers", errors)
            _check_string_matchers(route["match"].get("query_parameters"), f"{spot}.match.query_parameters", errors)
            _one_of(route, _ROUTE_ACTIONS, spot, errors)
            action = route.get("route")
            if isinstance(action, Mapping):
                _one_of(action, _CLUSTER_SPECIFIERS, f"{spot}.route", errors)
                weighted = action.get("weighted_clusters")
                if isinstance(weighted, Mapping):
                    clusters = weighted.get("clusters")
                    if not isinstance(clusters, list) or not clusters:
                        errors.append(f"{spot}.route.weighted_clusters.clusters: at least one cluster is required")
                    elif any(not isinstance(c, Mapping) or not c.get("name") for c in clusters):
                        errors.append(f"{spot}.route.weighted_clusters.clusters: every cluster needs a name")
    return errors


def validate_route_configuration_document(content: str, *, source_label: str = "emitted") -> None:
    """Validate emitted text as an Envoy ``RouteConfiguration``.

    Re-parses through the import adapter (so the text is a configuration the Envoy reader
    accepts) and applies :func:`route_configuration_violations` to the raw document.

    Raises:
        ValueError: When the text does not parse, or breaks a structural rule.
    """
    import yaml

    from .envoy_xds_import_source import EnvoyXdsImportSource
    from .import_source import ImportSourceError

    try:
        EnvoyXdsImportSource().parse(content, source_label=source_label)
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Envoy route configuration: {exc}") from exc
    violations = route_configuration_violations(yaml.safe_load(content))
    if violations:
        raise ValueError("Invalid Envoy route configuration: " + "; ".join(violations))
