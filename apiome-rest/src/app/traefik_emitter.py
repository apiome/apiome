"""Traefik emitter: canonical model → file-provider dynamic configuration — FMT-7.7 (#5461).

The inverse of :class:`app.traefik_import_source.TraefikImportSource`. The projection is the
family's shared :func:`app.gateway_config_emitter.plan_gateway_config`; this module renders
the planned document as Traefik v3 dynamic configuration:

* each planned **route** becomes an ``http.routers`` entry whose ``rule`` is rebuilt from its
  match conditions — one ``&&``-conjunction per condition (``Host``, ``Path`` /
  ``PathPrefix`` / ``PathRegexp``, ``Method``, ``Header`` / ``HeaderRegexp``, ``Query`` /
  ``QueryRegexp``), joined with ``||`` — the exact inverse of the importer's disjunctive
  normal form. ``entryPoints``, ``priority`` and ``tls`` recorded by a Traefik import are
  written back; an HTTPS-only route gets ``tls: {}``;
* each planned **service** becomes an ``http.services`` load balancer whose ``servers`` are the
  recorded upstream URLs (the projection supplies a placeholder upstream, reported, for a
  service that recorded none).

Not emitted, and declared: middlewares (the canonical model records their names, not their
configuration, and a router naming an undeclared middleware is refused by Traefik); auth
(Traefik authenticates in middlewares); and header / query matches by prefix, suffix or
substring, which are written as anchored regular expressions and therefore re-import as
regexes. A condition a Traefik import kept as an unmodelled rule literal (a negation, a
``ClientIP``) is written back verbatim.

:func:`validate_traefik_dynamic_config` is the product gate: every router has a parseable
rule and names a declared service, every load balancer has at least one server URL, plus a
re-import.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import CapabilityProfile, EmitOptions, EmitResult, Emitter, LossKind, Provenance
from .fidelity_rulepack import CapabilityRulePack
from .gateway_config_model import GatewayMatch, GatewayRoute, GatewayServiceDef
from .gateway_config_normalizer import TRAEFIK_FORMAT_KEY
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
    "TraefikEmitOptions",
    "TraefikEmitter",
    "TraefikFidelityRulePack",
    "dynamic_config_violations",
    "render_rule",
    "validate_traefik_dynamic_config",
]

_LABEL = "Traefik dynamic configuration"

#: Path kind → path matcher.
_PATH_MATCHERS = {"exact": "Path", "prefix": "PathPrefix", "regex": "PathRegexp"}


class TraefikFidelityRulePack(RoutingSurfaceRulePack):
    """Fidelity rules for Traefik dynamic-configuration export (FMT-7.7)."""

    target_label = _LABEL
    target_flavor = TRAEFIK_FORMAT_KEY
    carries_policies = False
    carries_auth = False


class TraefikEmitOptions(GatewayEmitOptions):
    """Per-target options for :class:`TraefikEmitter`."""


def _quote(value: str) -> str:
    """A rule argument, backtick-quoted (a backtick inside switches to double quotes)."""
    return f"`{value}`" if "`" not in value else '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _value_matcher(kind: str, name: str, rendered: str) -> tuple[str, bool]:
    """A header / query condition as a matcher call, and whether it was rewritten as a regex.

    Args:
        kind: ``Header`` or ``Query``.
        name: The header / parameter name.
        rendered: The ``match_value`` the normalizer wrote.

    Returns:
        ``(matcher text, approximated)``.
    """
    operator, value = parse_match_value(rendered)
    if operator == "exact" and value:
        return f"{kind}({_quote(name)}, {_quote(value)})", False
    if operator == "regex":
        return f"{kind}Regexp({_quote(name)}, {_quote(value)})", False
    pattern = {
        "exact": ".*",
        "prefix": f"^{re.escape(value)}",
        "suffix": f"{re.escape(value)}$",
        "contains": re.escape(value),
    }[operator]
    return f"{kind}Regexp({_quote(name)}, {_quote(pattern)})", True


def render_rule(
    matches: Sequence[GatewayMatch], hosts: Sequence[str], extra_conditions: Sequence[str] = ()
) -> tuple[str, bool]:
    """Rebuild a router rule from match conditions — the inverse of the importer's DNF.

    Args:
        matches: The route's match conditions (one ``&&``-conjunction each).
        hosts: Hosts every condition requires (``Host(…)``, ``||``-joined when several).
        extra_conditions: Rule literals to add to every conjunction verbatim.

    Returns:
        ``(rule, approximated)`` — ``approximated`` when a value match had to be rewritten.
    """
    approximated = False
    host_term = ""
    if len(hosts) == 1:
        host_term = f"Host({_quote(hosts[0])})"
    elif hosts:
        host_term = "(" + " || ".join(f"Host({_quote(host)})" for host in hosts) + ")"
    conjunctions: List[str] = []
    for match in matches:
        terms: List[str] = [host_term] if host_term else []
        if match.path is not None:
            pattern = match.path
            value = pattern_value(pattern)
            terms.append(f"{_PATH_MATCHERS[pattern.kind]}({_quote(value)})")
        if match.method:
            terms.append(f"Method({_quote(match.method)})")
        for kind, pairs in (("Header", match.headers), ("Query", match.query)):
            for name, rendered in pairs:
                term, rewritten = _value_matcher(kind, name, rendered)
                terms.append(term)
                approximated = approximated or rewritten
        terms.extend(extra_conditions)
        if not terms:
            terms.append("PathPrefix(`/`)")
        conjunctions.append(" && ".join(terms))
    if len(conjunctions) == 1:
        return conjunctions[0], approximated
    return " || ".join(f"({conjunction})" for conjunction in conjunctions), approximated


class _TraefikWriter:
    """Render one planned document as dynamic configuration."""

    def __init__(self, api: CanonicalApi, options: TraefikEmitOptions) -> None:
        self.plan = GatewayEmitPlan(api, flavor=TRAEFIK_FORMAT_KEY, label=_LABEL, service_naming=options.service_naming)
        self.plan.declare_title_loss()
        self.plan.declare_global_plugin_losses()

    def build(self) -> Dict[str, Any]:
        """The dynamic-configuration mapping."""
        plan = self.plan
        routers: Dict[str, Any] = {}
        for route in plan.document.routes:
            routers[route.name] = self._router(route)
        services = {service.name: self._service(service) for service in plan.document.services}
        for route in plan.document.routes:
            if route.service_name and route.service_name not in services:
                services[route.service_name] = {"loadBalancer": {"servers": [{"url": "http://127.0.0.1"}]}}
                plan.losses.record(
                    LossKind.INFERRED,
                    "placeholder-upstream",
                    f"Service {route.service_name!r} records no upstream; a placeholder server was emitted.",
                    route.service_name,
                )
        return {"http": {"routers": routers, "services": services}}

    def _router(self, route: GatewayRoute) -> Dict[str, Any]:
        """One ``http.routers`` entry."""
        plan = self.plan
        plan.declare_plugin_losses(route)
        plan.declare_auth_losses(
            route, reason="Traefik authenticates in a middleware, whose configuration is not in the model"
        )
        literals: List[str] = []
        if isinstance(route.extras.get("rule"), str):
            literals = [str(item) for item in route.extras.get("unmodelled_conditions") or []]
        elif route.extras.get("unmodelled_conditions"):
            plan.losses.record(
                LossKind.NA,
                "unmodelled-condition",
                f"Route {route.name!r} carries conditions recorded in another gateway's syntax; they "
                "are not emitted.",
                route.name,
            )
        rule, approximated = render_rule(route.matches, route.hosts, literals)
        if approximated:
            plan.losses.record(
                LossKind.INFERRED,
                "regex-value-match",
                f"Route {route.name!r} matches a header or query value by prefix, suffix, substring "
                "or presence; Traefik has no such operator, so it is written as an anchored regular "
                "expression and re-imports as one.",
                route.name,
            )
        router: Dict[str, Any] = {"rule": rule, "service": route.service_name or "default"}
        plan.tracker.record(
            f"/http/routers/{route.name}/rule",
            Provenance.SOURCE if plan.declared_routes else Provenance.INFERRED,
            "Rule rebuilt from the route's match conditions.",
        )
        entry_points = route.extras.get("entry_points")
        if isinstance(entry_points, list) and entry_points:
            router["entryPoints"] = [str(point) for point in entry_points]
        if isinstance(route.extras.get("priority"), int):
            router["priority"] = route.extras["priority"]
        tls = route.extras.get("tls")
        if isinstance(tls, Mapping):
            router["tls"] = dict(tls)
        elif route.protocols == ("https",):
            router["tls"] = {}
        return router

    def _service(self, service: GatewayServiceDef) -> Dict[str, Any]:
        """One ``http.services`` load balancer."""
        servers = service.extras.get("servers")
        urls = [str(url) for url in servers] if isinstance(servers, list) and servers else []
        if not urls and service.url:
            urls = [service.url]
        if not urls and service.host:
            scheme = service.protocol or "http"
            port = f":{service.port}" if service.port else ""
            urls = [f"{scheme}://{service.host}{port}{service.path or ''}"]
        if not urls:
            urls = ["http://127.0.0.1"]
            self.plan.losses.record(
                LossKind.INFERRED,
                "placeholder-upstream",
                f"Service {service.name!r} records no upstream; a placeholder server was emitted.",
                service.name,
            )
        balancer: Dict[str, Any] = {"servers": [{"url": url} for url in urls]}
        health = service.extras.get("health_check_path")
        if isinstance(health, str):
            balancer["healthCheck"] = {"path": health}
        return {"loadBalancer": balancer}


class TraefikEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Traefik dynamic configuration."""

    key = TRAEFIK_FORMAT_KEY
    format = TRAEFIK_FORMAT_KEY
    label = "Traefik dynamic configuration"
    description = (
        "Export as Traefik dynamic configuration (dynamic.yml) for the file provider: a router per "
        "route with its rule rebuilt from the path, host, method, header and query matches, and a "
        "load-balancer service per upstream."
    )
    icon = "signpost"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = TraefikEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A dynamic configuration is a routing surface: operations only, no payloads."""
        return ROUTING_SURFACE_PROFILE

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Traefik degradation rules."""
        return TraefikFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[TraefikEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit ``api`` as one dynamic-configuration file.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            ValueError: When ``api`` has no HTTP operation to route.
        """
        options = coerce_gateway_options(opts, TraefikEmitOptions, label=_LABEL)
        writer = _TraefikWriter(api, options)  # type: ignore[arg-type]
        extension = "yml" if options.output_format == "yaml" else "json"
        content = dump_documents([writer.build()], output_format=options.output_format, pretty=options.pretty_print)
        return single_file_result(
            writer.plan, path=f"dynamic.{extension}", content=content, media_type=OUTPUT_FORMATS[options.output_format]
        )


# ===========================================================================
# Product gate
# ===========================================================================


def dynamic_config_violations(document: Any) -> List[str]:
    """The Traefik dynamic-configuration rules a document breaks.

    Args:
        document: The parsed document.

    Returns:
        One message per violation; empty when valid.
    """
    from .traefik_parser import TraefikRuleError, parse_rule

    errors: List[str] = []
    http = document.get("http") if isinstance(document, Mapping) else None
    if not isinstance(http, Mapping):
        return ["http: the document has no http section"]
    routers = http.get("routers") if isinstance(http.get("routers"), Mapping) else {}
    services = http.get("services") if isinstance(http.get("services"), Mapping) else {}
    for name, router in routers.items():
        where = f"http.routers.{name}"
        if not isinstance(router, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        rule = router.get("rule")
        try:
            parse_rule(str(rule or ""))
        except TraefikRuleError as exc:
            errors.append(f"{where}.rule: {exc}")
        service = router.get("service")
        if not isinstance(service, str) or (service.split("@", 1)[0] not in services and "@" not in service):
            errors.append(f"{where}.service: {service!r} is not a declared service")
    for name, service in services.items():
        balancer = service.get("loadBalancer") if isinstance(service, Mapping) else None
        if isinstance(balancer, Mapping):
            servers = balancer.get("servers")
            if (
                not isinstance(servers, list)
                or not servers
                or any(not isinstance(server, Mapping) or not server.get("url") for server in servers)
            ):
                errors.append(f"http.services.{name}.loadBalancer.servers: at least one server with a url is required")
    return errors


def validate_traefik_dynamic_config(content: str, *, source_label: str = "emitted") -> None:
    """Validate emitted text as Traefik dynamic configuration.

    Raises:
        ValueError: When the text does not re-import, or breaks a configuration rule.
    """
    import yaml

    from .import_source import ImportSourceError
    from .traefik_import_source import TraefikImportSource

    try:
        TraefikImportSource().parse(content, source_label=source_label)
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Traefik dynamic configuration: {exc}") from exc
    violations = dynamic_config_violations(yaml.safe_load(content))
    if violations:
        raise ValueError("Invalid Traefik dynamic configuration: " + "; ".join(violations))
