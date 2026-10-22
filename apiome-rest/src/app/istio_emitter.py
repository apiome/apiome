"""Istio emitter: canonical model → ``VirtualService`` manifests — FMT-7.7 (#5461).

The inverse of :class:`app.istio_import_source.IstioImportSource`. The projection is the
family's shared :func:`app.gateway_config_emitter.plan_gateway_config`; this module renders
the planned document as a ``---``-separated stream of ``networking.istio.io/v1``
``VirtualService`` resources:

* each planned **service** becomes one ``VirtualService`` (``namespace/name`` split back out,
  names made RFC 1123 labels); ``hosts`` are the route hosts — or, when the model declares
  none, the service name as a mesh-internal host, reported as synthesized;
* each planned **route** becomes one ``http`` rule named after it, with one ``match`` entry
  per match condition (``uri`` exact / prefix / regex, ``method``, ``headers`` and
  ``queryParams`` with their ``StringMatch`` operator recovered);
* the route's **backends** become ``route[].destination`` entries with host, port, subset
  and weight; a route with none routes to its service's upstream host (or the service
  name), reported as synthesized.

``gateways`` recorded by an Istio import are written back. A ``DestinationRule`` is **not**
emitted: the canonical model records the subset a destination names, not the labels that
select it, so inventing a rule would invent a deployment fact — the subset is kept on the
destination and the missing rule declared. Policies (timeouts, retries, rewrites) are
recorded by name only, so they are declared losses too; Istio authentication lives in
``security.istio.io`` resources, so auth is a declared loss.

:func:`validate_virtualservice_stream` is the product gate: the ``VirtualService`` schema
rules (non-empty ``hosts``, a destination or a terminal action on every rule, a host on every
destination, weights summing to 100, one ``StringMatch`` operator) plus a re-import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Union

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import CapabilityProfile, EmitOptions, EmitResult, Emitter, LossKind, Provenance
from .fidelity_rulepack import CapabilityRulePack
from .gateway_config_model import GatewayMatch, GatewayRoute, GatewayServiceDef
from .gateway_config_normalizer import ISTIO_FORMAT_KEY
from .gateway_emit_common import (
    OUTPUT_FORMATS,
    ROUTING_SURFACE_PROFILE,
    GatewayEmitOptions,
    GatewayEmitPlan,
    RoutingSurfaceRulePack,
    coerce_gateway_options,
    dns_label,
    dump_documents,
    pattern_value,
    single_file_result,
)
from .gateway_match import parse_match_value
from .proxy_route_common import split_address

__all__ = [
    "IstioEmitOptions",
    "IstioEmitter",
    "IstioFidelityRulePack",
    "validate_virtualservice_stream",
    "virtualservice_violations",
]

_LABEL = "Istio VirtualService"

#: API version the emitter writes.
_API_VERSION = "networking.istio.io/v1"

#: Path kind → ``uri`` StringMatch operator.
_URI_OPERATORS = {"exact": "exact", "prefix": "prefix", "regex": "regex"}

#: ``http`` rule keys that end a rule without a destination.
_TERMINAL_ACTIONS = ("redirect", "directResponse", "delegate")


class IstioFidelityRulePack(RoutingSurfaceRulePack):
    """Fidelity rules for Istio ``VirtualService`` export (FMT-7.7)."""

    target_label = _LABEL
    target_flavor = ISTIO_FORMAT_KEY
    carries_policies = False
    carries_auth = False


class IstioEmitOptions(GatewayEmitOptions):
    """Per-target options for :class:`IstioEmitter`."""

    namespace: Optional[str] = None


def _string_match(rendered: str) -> Optional[Dict[str, str]]:
    """A rendered ``match_value`` → an Istio ``StringMatch`` (``None`` for presence only)."""
    operator, value = parse_match_value(rendered)
    if not value:
        return None
    if operator in ("suffix", "contains"):
        return None
    return {operator: value}


class _IstioWriter:
    """Render one planned document as VirtualService resources."""

    def __init__(self, api: CanonicalApi, options: IstioEmitOptions) -> None:
        self.options = options
        self.plan = GatewayEmitPlan(api, flavor=ISTIO_FORMAT_KEY, label=_LABEL, service_naming=options.service_naming)
        self.plan.declare_title_loss()
        self.plan.declare_global_plugin_losses()
        self.services: Dict[str, GatewayServiceDef] = {service.name: service for service in self.plan.document.services}

    def build(self) -> List[Dict[str, Any]]:
        """The ``VirtualService`` documents, one per planned service."""
        groups: Dict[str, List[GatewayRoute]] = {}
        for route in self.plan.document.routes:
            groups.setdefault(route.service_name or "default", []).append(route)
        documents = []
        for index, (service, routes) in enumerate(groups.items()):
            documents.append(self._virtual_service(service, routes, index))
        return documents

    def _service_host(self, service: str) -> str:
        """The host a route with no backend is sent to."""
        definition = self.services.get(service)
        if definition is not None:
            if definition.host:
                return definition.host
            if definition.url:
                return split_address(definition.url)[0]
        return dns_label(service.rsplit("/", 1)[-1], fallback="service")

    def _virtual_service(self, service: str, routes: List[GatewayRoute], index: int) -> Dict[str, Any]:
        """One ``VirtualService``."""
        plan = self.plan
        namespace, _, name = service.rpartition("/")
        namespace = (
            self.options.namespace
            or namespace
            or next((str(r.extras["namespace"]) for r in routes if isinstance(r.extras.get("namespace"), str)), "")
        )
        metadata: Dict[str, Any] = {"name": dns_label(name or service, fallback="virtual-service")}
        if namespace:
            metadata["namespace"] = dns_label(namespace, fallback="default")
        if metadata["name"] != (name or service):
            plan.losses.record(
                LossKind.INFERRED,
                "renamed-resource",
                f"Service {service!r} is not a valid Kubernetes name; emitted as {metadata['name']!r}.",
                service,
            )
        hosts = sorted({host for route in routes for host in route.hosts})
        if not hosts:
            hosts = [self._service_host(service)]
            plan.losses.record(
                LossKind.INFERRED,
                "synthesized-host",
                f"Service {service!r} declares no host; the VirtualService is bound to {hosts[0]!r}.",
                service,
            )
            plan.tracker.record(f"/{index}/spec/hosts", Provenance.INFERRED, "Host derived from the service.")
        spec: Dict[str, Any] = {"hosts": hosts}
        gateways: List[str] = []
        for route in routes:
            for gateway in route.extras.get("gateways") or []:
                if isinstance(gateway, str) and gateway not in gateways:
                    gateways.append(gateway)
        if gateways:
            spec["gateways"] = gateways
        spec["http"] = [self._rule(route, service) for route in routes]
        return {"apiVersion": _API_VERSION, "kind": "VirtualService", "metadata": metadata, "spec": spec}

    def _match(self, match: GatewayMatch, route: GatewayRoute) -> Dict[str, Any]:
        """One ``HTTPMatchRequest``."""
        out: Dict[str, Any] = {}
        if match.path is not None:
            pattern = match.path
            value = pattern_value(pattern)
            out["uri"] = {_URI_OPERATORS[pattern.kind]: value}
        if match.method:
            out["method"] = {"exact": match.method}
        for location, pairs in (("headers", match.headers), ("queryParams", match.query)):
            entries: Dict[str, Any] = {}
            for name, rendered in pairs:
                string_match = _string_match(rendered)
                if string_match is None:
                    self.plan.losses.record(
                        LossKind.NA,
                        "unsupported-match-operator",
                        f"Route {route.name!r} matches {location} {name!r} by presence or by a "
                        "suffix/substring, which an Istio StringMatch cannot express; the condition "
                        "is not emitted.",
                        route.name,
                    )
                    continue
                entries[name] = string_match
            if entries:
                out[location] = entries
        return out

    def _rule(self, route: GatewayRoute, service: str) -> Dict[str, Any]:
        """One ``HTTPRoute`` rule."""
        plan = self.plan
        plan.declare_plugin_losses(route)
        plan.declare_auth_losses(
            route, reason="Istio authenticates with security.istio.io policies, which a VirtualService does not carry"
        )
        rule: Dict[str, Any] = {"name": route.name}
        matches = [self._match(match, route) for match in route.matches]
        matches = [match for match in matches if match]
        if matches:
            rule["match"] = matches
        destinations = []
        for backend in route.backends:
            destination: Dict[str, Any] = {"host": backend.name}
            if backend.subset:
                destination["subset"] = backend.subset
                plan.losses.record(
                    LossKind.NA,
                    "destination-rule-not-emitted",
                    f"Route {route.name!r} names subset {backend.subset!r} of {backend.name!r}; the "
                    "DestinationRule that defines it is not emitted (the model records the subset, "
                    "not the labels that select it).",
                    route.name,
                )
            if backend.port is not None:
                destination["port"] = {"number": backend.port}
            entry: Dict[str, Any] = {"destination": destination}
            if backend.weight is not None and len(route.backends) > 1:
                entry["weight"] = backend.weight
            destinations.append(entry)
        if not destinations:
            destinations = [{"destination": {"host": self._service_host(service)}}]
            plan.losses.record(
                LossKind.INFERRED,
                "synthesized-destination",
                f"Route {route.name!r} declares no backend; it routes to {destinations[0]['destination']['host']!r}.",
                route.name,
            )
        if len(destinations) > 1 and any("weight" not in entry for entry in destinations):
            share, remainder = divmod(100, len(destinations))
            for position, entry in enumerate(destinations):
                entry["weight"] = share + (1 if position < remainder else 0)
            plan.losses.record(
                LossKind.INFERRED,
                "synthesized-weight",
                f"Route {route.name!r} splits traffic across destinations with no declared weights; "
                "they were split evenly.",
                route.name,
            )
        rule["route"] = destinations
        return rule


class IstioEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Istio ``VirtualService`` manifests."""

    key = ISTIO_FORMAT_KEY
    format = ISTIO_FORMAT_KEY
    label = "Istio VirtualService"
    description = (
        "Export as Istio VirtualService manifests (virtualservice.yaml): a VirtualService per "
        "service with an http rule per route — uri, method, header and query matches — and the "
        "destinations each rule routes to."
    )
    icon = "network"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = IstioEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A VirtualService is a routing surface: operations only, no payloads."""
        return ROUTING_SURFACE_PROFILE

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Istio degradation rules."""
        return IstioFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[IstioEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit ``api`` as one manifest stream.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            ValueError: When ``api`` has no HTTP operation to route.
        """
        options = coerce_gateway_options(opts, IstioEmitOptions, label=_LABEL)
        writer = _IstioWriter(api, options)  # type: ignore[arg-type]
        content = dump_documents(writer.build(), output_format=options.output_format, pretty=options.pretty_print)
        return single_file_result(
            writer.plan,
            path=f"virtualservice.{options.output_format}",
            content=content,
            media_type=OUTPUT_FORMATS[options.output_format],
        )


# ===========================================================================
# Product gate
# ===========================================================================


def _check_string_match(spec: Any, where: str, errors: List[str]) -> None:
    """A ``StringMatch`` carries exactly one of exact / prefix / regex."""
    if not isinstance(spec, Mapping) or len([k for k in ("exact", "prefix", "regex") if k in spec]) != 1:
        errors.append(f"{where}: a StringMatch needs exactly one of exact, prefix, regex")


def virtualservice_violations(document: Any) -> List[str]:
    """The ``VirtualService`` schema rules one document breaks.

    Args:
        document: One parsed manifest.

    Returns:
        One message per violation; empty when valid.
    """
    errors: List[str] = []
    if not isinstance(document, Mapping) or document.get("kind") != "VirtualService":
        return ["the document must be a VirtualService"]
    if not str(document.get("apiVersion") or "").startswith("networking.istio.io/"):
        errors.append("apiVersion: must be networking.istio.io/*")
    metadata = document.get("metadata") if isinstance(document.get("metadata"), Mapping) else {}
    name = metadata.get("name")
    if not isinstance(name, str) or dns_label(name) != name:
        errors.append(f"metadata.name: {name!r} is not an RFC 1123 label")
    spec = document.get("spec") if isinstance(document.get("spec"), Mapping) else {}
    hosts = spec.get("hosts")
    if not isinstance(hosts, list) or not hosts or not all(isinstance(h, str) and h for h in hosts):
        errors.append("spec.hosts: at least one host is required")
    for r_index, rule in enumerate(spec.get("http") or []):
        where = f"spec.http[{r_index}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{where}: must be a mapping")
            continue
        for m_index, match in enumerate(rule.get("match") or []):
            spot = f"{where}.match[{m_index}]"
            if not isinstance(match, Mapping):
                errors.append(f"{spot}: must be a mapping")
                continue
            for key in ("uri", "method"):
                if key in match:
                    _check_string_match(match[key], f"{spot}.{key}", errors)
            for key in ("headers", "queryParams"):
                for header, spec_match in (match.get(key) or {}).items():
                    _check_string_match(spec_match, f"{spot}.{key}.{header}", errors)
        destinations = rule.get("route")
        if not destinations and not any(action in rule for action in _TERMINAL_ACTIONS):
            errors.append(f"{where}: a rule needs a route or a redirect / directResponse / delegate")
            continue
        weights = []
        for d_index, entry in enumerate(destinations or []):
            destination = entry.get("destination") if isinstance(entry, Mapping) else None
            if not isinstance(destination, Mapping) or not isinstance(destination.get("host"), str):
                errors.append(f"{where}.route[{d_index}].destination.host: required")
            if isinstance(entry, Mapping) and "weight" in entry:
                weights.append(entry["weight"])
        if len(destinations or []) > 1 and (len(weights) != len(destinations) or sum(weights) != 100):
            errors.append(f"{where}.route: weights of several destinations must be set and sum to 100")
    return errors


def validate_virtualservice_stream(content: str, *, source_label: str = "emitted") -> None:
    """Validate emitted text as a stream of ``VirtualService`` resources.

    Raises:
        ValueError: When the stream does not re-import, or a document breaks a schema rule.
    """
    import yaml

    from .import_source import ImportSourceError
    from .istio_import_source import IstioImportSource

    try:
        IstioImportSource().parse(content, source_label=source_label)
    except ImportSourceError as exc:
        raise ValueError(f"Invalid Istio manifest: {exc}") from exc
    violations: List[str] = []
    for index, document in enumerate(doc for doc in yaml.safe_load_all(content) if doc is not None):
        violations.extend(f"document {index}: {message}" for message in virtualservice_violations(document))
    if violations:
        raise ValueError("Invalid Istio manifest: " + "; ".join(violations))
