"""Parser for Istio traffic resources — FMT-7.4 (#5458).

Reads a (multi-document) stream of Istio ``networking.istio.io`` resources into the
flavor-neutral :class:`~app.gateway_config_model.GatewayConfigDocument`:

* **``VirtualService``** ``http[]`` rules are the routing surface. Each rule's ``match[]``
  entries flatten to :class:`GatewayMatch` conditions (``uri`` through the shared
  Gateway API path-type table in :mod:`app.mesh_route_common`, ``method``, ``headers``,
  ``queryParams``); a rule with no ``match`` matches every request (``PathPrefix /``).
  ``route[].destination`` entries become backends, with their ``subset`` and ``weight``.
* **``DestinationRule``** supplies the subsets a destination names — a destination naming
  a subset its host's rule does not define is ``INPUT_REFERENCE_UNRESOLVED``. When no
  rule for the host is in the input the subset stands on its own (it may live elsewhere).
* **``Gateway``** supplies the scheme: a host served on an ``HTTPS`` gateway server is
  an ``https`` route.

Everything else is declared, never flattened away: ``delegate`` rules (routing handed to
another VirtualService), ``tls`` and ``tcp`` route blocks (not HTTP), ``sourceLabels`` /
``withoutHeaders`` qualifiers, and the other Istio kinds (``ServiceEntry``, ``Sidecar``,
…) that shape the mesh rather than describe its HTTP surface. Traffic policy —
``timeout``, ``retries``, ``rewrite``, ``redirect``, ``directResponse``, ``fault``,
``mirror``, ``corsPolicy``, ``headers`` — rides on the operations as named plugins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .gateway_config_model import (
    GatewayBackend,
    GatewayConfigDocument,
    GatewayConfigParseError,
    GatewayMatch,
    GatewayPlugin,
    GatewayRoute,
)
from .mesh_route_common import (
    LimitCollector,
    is_duration,
    is_truncated_cluster_host,
    load_yaml_documents,
    path_pattern_for,
    policy_plugin,
    raise_if_truncated_tail,
    reject_binary,
    render_string_match,
)

__all__ = [
    "ISTIO_FLAVOR",
    "ISTIO_KINDS",
    "ISTIO_URI_MATCHERS",
    "is_istio",
    "is_istio_document",
    "parse_istio",
    "parse_istio_fileset",
]

#: Flavor key stamped on the parsed document.
ISTIO_FLAVOR = "istio"

#: Human name used in messages.
_LABEL = "Istio"

#: apiVersion group prefix of Istio's traffic-management resources.
_ISTIO_GROUP = "networking.istio.io/"

#: The networking kinds this parser recognizes as Istio.
ISTIO_KINDS = frozenset(
    {
        "VirtualService",
        "DestinationRule",
        "Gateway",
        "ServiceEntry",
        "Sidecar",
        "WorkloadEntry",
        "WorkloadGroup",
        "EnvoyFilter",
        "ProxyConfig",
    }
)

#: Istio ``uri`` matcher → Gateway API path type; the rest of the mapping is
#: :data:`app.gateway_api_parser.PATH_TYPE_KINDS`, reached through
#: :func:`app.mesh_route_common.path_pattern_for`.
ISTIO_URI_MATCHERS: Dict[str, str] = {
    "exact": "Exact",
    "prefix": "PathPrefix",
    "regex": "RegularExpression",
}

#: ``http[]`` rule keys kept as policy plugins on the rule's operations.
_RULE_POLICY_KEYS = (
    "timeout",
    "retries",
    "rewrite",
    "redirect",
    "directResponse",
    "fault",
    "mirror",
    "mirrors",
    "mirrorPercentage",
    "corsPolicy",
    "headers",
)

#: Match qualifiers with no canonical form, declared with the reason.
_MATCH_LIMITS: Dict[str, str] = {
    "sourceLabels": "the rule matches on the calling workload's labels, which has no canonical "
    "parameter form",
    "sourceNamespace": "the rule matches on the calling workload's namespace",
    "withoutHeaders": "an inverted header match (the rule applies when the header does NOT "
    "match) has no canonical parameter form",
    "statPrefix": "a stats prefix names telemetry, not a match condition",
}

#: Match qualifiers recorded on the route (they narrow the match; the operation stands).
_MATCH_EXTRAS = ("scheme", "authority", "port", "gateways", "ignoreUriCase")

#: A method regex that is only an alternation of plain verbs: ``GET|HEAD``.
_METHOD_ALTERNATION_RE = re.compile(r"^\^?\(?([A-Za-z]+(?:\|[A-Za-z]+)*)\)?\$?$")

#: Duration fields — a bare number in one of them at the end of the file is a cut.
_DURATION_FIELDS = (
    "timeout",
    "perTryTimeout",
    "interval",
    "baseEjectionTime",
    "connectTimeout",
    "fixedDelay",
    "maxAge",
    "ttl",
)

#: :func:`raise_if_truncated_tail` rules for Istio.
_TAIL_RULES = {name: (lambda value: not is_duration(value)) for name in _DURATION_FIELDS}
_TAIL_RULES["host"] = is_truncated_cluster_host


def is_istio_document(document: Any) -> bool:
    """True when a parsed document is an Istio networking resource."""
    if not isinstance(document, Mapping):
        return False
    api_version = str(document.get("apiVersion") or "")
    return api_version.startswith(_ISTIO_GROUP) and str(document.get("kind") or "") in ISTIO_KINDS


def is_istio(text: str) -> Optional[str]:
    """Cheap sniff: the strongest Istio kind in ``text``.

    Returns:
        ``VirtualService`` when the stream carries one, another Istio kind when only those
        appear, or ``None`` when nothing is Istio.
    """
    if not text or "\x00" in text or _ISTIO_GROUP not in text:
        return None
    try:
        documents = load_yaml_documents(text, format_label=_LABEL)
    except GatewayConfigParseError:
        return None
    kinds = [str(document.get("kind")) for document in documents if is_istio_document(document)]
    if not kinds:
        return None
    return "VirtualService" if "VirtualService" in kinds else kinds[0]


def _metadata(document: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """``(name, namespace)`` of a resource."""
    metadata = document.get("metadata") if isinstance(document.get("metadata"), Mapping) else {}
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    return (
        name if isinstance(name, str) and name else "",
        namespace if isinstance(namespace, str) and namespace else None,
    )


def _qualified_host(host: str, namespace: Optional[str]) -> str:
    """Expand a Kubernetes short service name the way Istio resolves it.

    ``reviews`` in namespace ``shop`` → ``reviews.shop.svc.cluster.local``;
    ``reviews.shop`` → ``reviews.shop.svc.cluster.local``. A dotted external host
    (``api.example.com``) or an already-qualified one is returned as written.
    """
    host = host.strip().lower()
    if host.endswith(".svc.cluster.local") or host.endswith(".svc"):
        return host if host.endswith(".local") else f"{host}.cluster.local"
    parts = host.split(".")
    if len(parts) == 1 and namespace:
        return f"{host}.{namespace}.svc.cluster.local"
    if len(parts) == 2:
        return f"{host}.svc.cluster.local"
    return host


@dataclass
class _Collected:
    """Everything gathered from every document before routes are built."""

    virtual_services: List[Tuple[Mapping[str, Any], str, int]] = field(default_factory=list)
    subsets: Dict[str, Set[str]] = field(default_factory=dict)
    https_hosts: Set[str] = field(default_factory=set)
    gateway_names: Set[str] = field(default_factory=set)
    saw_istio: bool = False
    kinds: Dict[str, int] = field(default_factory=dict)
    limits: LimitCollector = field(default_factory=LimitCollector)


def _read_gateway(document: Mapping[str, Any], state: _Collected) -> None:
    """Record a Gateway's name and the hosts it serves over HTTPS."""
    name, namespace = _metadata(document)
    if name:
        state.gateway_names.add(f"{namespace}/{name}" if namespace else name)
        state.gateway_names.add(name)
    spec = document.get("spec") if isinstance(document.get("spec"), Mapping) else {}
    for server in spec.get("servers") or []:
        if not isinstance(server, Mapping):
            continue
        port = server.get("port") if isinstance(server.get("port"), Mapping) else {}
        if str(port.get("protocol") or "").upper() in ("HTTPS", "TLS"):
            for host in server.get("hosts") or []:
                if isinstance(host, str):
                    # ``namespace/host`` restricts which namespaces may bind; the host is the part after it.
                    state.https_hosts.add(host.split("/", 1)[-1].lower())


def _read_destination_rule(document: Mapping[str, Any], state: _Collected) -> None:
    """Record the subsets a DestinationRule defines for its host."""
    _name, namespace = _metadata(document)
    spec = document.get("spec") if isinstance(document.get("spec"), Mapping) else {}
    host = spec.get("host")
    if not isinstance(host, str) or not host:
        return
    names = state.subsets.setdefault(_qualified_host(host, namespace), set())
    for subset in spec.get("subsets") or []:
        if isinstance(subset, Mapping) and isinstance(subset.get("name"), str):
            names.add(subset["name"])


def _declare_other(document: Any, state: _Collected) -> None:
    """Declare a stream document that is not an Istio networking resource.

    ``security.istio.io`` / ``telemetry.istio.io`` resources change what the mesh enforces
    or records but not where requests go; other Kubernetes objects (a ``Deployment``
    shipped in the same stream) are not mesh routing at all. Both are named on the ledger
    rather than skipped in silence.
    """
    if not isinstance(document, Mapping):
        state.limits.add("(non-resource document)", "the stream holds a document that is not a Kubernetes resource")
        return
    api_version = str(document.get("apiVersion") or "")
    kind = str(document.get("kind") or "") or "(unnamed kind)"
    if ".istio.io/" in api_version:
        state.limits.add(
            kind,
            f"{api_version.split('/')[0]} resources change what the mesh enforces or records, not "
            "where requests go; they are not read",
        )
    else:
        state.limits.add(kind, "not an Istio resource")


def _collect(documents: Sequence[Any], state: _Collected, origin: str) -> None:
    """Fold one member's parsed documents into ``state``."""
    for index, document in enumerate(documents):
        if not is_istio_document(document):
            _declare_other(document, state)
            continue
        state.saw_istio = True
        kind = str(document.get("kind"))
        state.kinds[kind] = state.kinds.get(kind, 0) + 1
        if kind == "VirtualService":
            state.virtual_services.append((document, origin, index))
        elif kind == "Gateway":
            _read_gateway(document, state)
        elif kind == "DestinationRule":
            _read_destination_rule(document, state)


def _string_match_pairs(entries: Any) -> Tuple[Tuple[str, str], ...]:
    """Read an Istio ``map<string, StringMatch>`` (``headers`` / ``queryParams``)."""
    if not isinstance(entries, Mapping):
        return ()
    pairs = []
    for name, spec in entries.items():
        rendered = render_string_match(spec)
        pairs.append((str(name), rendered if rendered is not None else ""))
    return tuple(pairs)


def _methods(spec: Any, limits: LimitCollector) -> List[Optional[str]]:
    """The methods an Istio ``method`` StringMatch admits.

    An ``exact`` match is one method; a ``regex`` that is only an alternation of plain
    verbs (``GET|HEAD``) is one method each; anything else leaves the method open and
    declares why.
    """
    if not isinstance(spec, Mapping):
        return [None]
    exact = spec.get("exact")
    if isinstance(exact, str) and exact:
        return [exact.upper()]
    regex = spec.get("regex")
    if isinstance(regex, str):
        alternation = _METHOD_ALTERNATION_RE.match(regex.strip())
        if alternation:
            return [verb.upper() for verb in alternation.group(1).split("|")]
    limits.add(
        "match.method",
        "a method match that is not a literal (or a plain alternation of literals) cannot "
        "pin the HTTP method; the operation is left open to every method",
    )
    return [None]


def _rule_matches(rule: Mapping[str, Any], limits: LimitCollector) -> Tuple[Tuple[GatewayMatch, ...], Dict[str, Any]]:
    """Flatten a rule's ``match[]`` to match conditions plus route-level qualifier extras."""
    raw_matches = rule.get("match")
    if not isinstance(raw_matches, list) or not raw_matches:
        return (GatewayMatch(path=path_pattern_for("PathPrefix", "/")),), {}
    matches: List[GatewayMatch] = []
    qualifiers: Dict[str, Any] = {}
    for entry in raw_matches:
        if not isinstance(entry, Mapping):
            continue
        uri = entry.get("uri")
        pattern = path_pattern_for("PathPrefix", "/")
        if isinstance(uri, Mapping):
            for key, path_type in ISTIO_URI_MATCHERS.items():
                if isinstance(uri.get(key), str):
                    pattern = path_pattern_for(path_type, uri[key])
                    break
        for key, reason in _MATCH_LIMITS.items():
            if key in entry:
                limits.add(f"match.{key}", reason)
        for key in _MATCH_EXTRAS:
            if key in entry:
                qualifiers.setdefault(key, [])
                if entry[key] not in qualifiers[key]:
                    qualifiers[key].append(entry[key])
        headers = _string_match_pairs(entry.get("headers"))
        query = _string_match_pairs(entry.get("queryParams"))
        for method in _methods(entry.get("method"), limits):
            matches.append(GatewayMatch(path=pattern, method=method, headers=headers, query=query))
    return tuple(matches), qualifiers


def _destinations(rule: Mapping[str, Any], namespace: Optional[str]) -> Tuple[GatewayBackend, ...]:
    """A rule's ``route[].destination`` entries as backends."""
    backends = []
    for entry in rule.get("route") or []:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("destination"), Mapping):
            continue
        destination = entry["destination"]
        host = destination.get("host")
        if not isinstance(host, str) or not host:
            continue
        port = destination.get("port") if isinstance(destination.get("port"), Mapping) else {}
        number = port.get("number")
        weight = entry.get("weight")
        subset = destination.get("subset")
        backends.append(
            GatewayBackend(
                name=host,
                namespace=namespace,
                port=number if isinstance(number, int) else None,
                weight=weight if isinstance(weight, int) else None,
                subset=subset if isinstance(subset, str) and subset else None,
            )
        )
    return tuple(backends)


def _check_subsets(route_name: str, backends: Sequence[GatewayBackend], state: _Collected) -> None:
    """Refuse a destination subset its host's DestinationRule does not define."""
    for backend in backends:
        if backend.subset is None:
            continue
        defined = state.subsets.get(_qualified_host(backend.name, backend.namespace))
        if defined is not None and backend.subset not in defined:
            raise GatewayConfigParseError(
                f"Rule {route_name!r} routes to subset {backend.subset!r} of {backend.name!r}, "
                f"which its DestinationRule does not define (defined: "
                f"{', '.join(sorted(defined)) or 'none'})",
                code="INPUT_REFERENCE_UNRESOLVED",
            )


def _protocols(hosts: Sequence[str], gateways: Sequence[str], state: _Collected) -> Tuple[str, ...]:
    """The scheme(s) a VirtualService's hosts are served on."""
    if any(host.lower() in state.https_hosts for host in hosts):
        return ("https",)
    external = [gateway for gateway in gateways if gateway != "mesh"]
    if external and not any(gateway in state.gateway_names for gateway in external):
        # Bound to a gateway the input does not include: it may terminate TLS, so both.
        return ("http", "https")
    return ("http",)


def _build_routes(state: _Collected) -> Tuple[List[GatewayRoute], int]:
    """One :class:`GatewayRoute` per ``http[]`` rule; declared limits for the rest."""
    routes: List[GatewayRoute] = []
    redactions = 0
    limits = state.limits
    for document, origin, doc_index in state.virtual_services:
        name, namespace = _metadata(document)
        resource = name or f"virtualservice-{doc_index}"
        group = f"{namespace}/{resource}" if namespace else resource
        spec = document.get("spec") if isinstance(document.get("spec"), Mapping) else {}
        hosts = tuple(sorted({str(host) for host in spec.get("hosts") or [] if str(host) != "*"}))
        gateways = [str(gateway) for gateway in spec.get("gateways") or []]
        protocols = _protocols(hosts, gateways, state)
        for block in ("tls", "tcp"):
            rules = spec.get(block)
            if isinstance(rules, list) and rules:
                limits.add(
                    block,
                    f"{block} route blocks route by SNI/port, not by HTTP request — there is no "
                    "canonical HTTP operation for them",
                    count=len(rules),
                )
        http_rules = spec.get("http") if isinstance(spec.get("http"), list) else []
        for rule_index, rule in enumerate(http_rules):
            if not isinstance(rule, Mapping):
                continue
            route_name = str(rule.get("name") or f"{resource}#http-{rule_index}")
            if isinstance(rule.get("delegate"), Mapping):
                limits.add(
                    "delegate",
                    "a delegate rule hands routing to another VirtualService; its routes are "
                    "not part of this resource and are not flattened into it",
                )
                continue
            matches, qualifiers = _rule_matches(rule, limits)
            if not matches:
                continue
            backends = _destinations(rule, namespace)
            _check_subsets(route_name, backends, state)
            plugins: List[GatewayPlugin] = []
            for key in _RULE_POLICY_KEYS:
                if key in rule:
                    plugin, count = policy_plugin(key, rule[key], scope="route", attached_to=route_name)
                    plugins.append(plugin)
                    redactions += count
            extras: Dict[str, Any] = {"virtual_service": group}
            if namespace:
                extras["namespace"] = namespace
            if gateways:
                extras["gateways"] = gateways
            if qualifiers:
                extras["match_qualifiers"] = qualifiers
            routes.append(
                GatewayRoute(
                    name=route_name,
                    service_name=group,
                    hosts=hosts,
                    matches=matches,
                    protocols=protocols,
                    plugins=tuple(plugins),
                    backends=backends,
                    source_location=f"{origin}[{doc_index}].spec.http[{rule_index}]",
                    extras=extras,
                )
            )
    return routes, redactions


def _document_from(state: _Collected, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Build routes and assemble the document."""
    if not state.saw_istio:
        raise GatewayConfigParseError(
            "No Istio networking resource (apiVersion networking.istio.io/*) found",
            code="FORMAT_MISMATCH",
        )
    for kind, count in sorted(state.kinds.items()):
        if kind == "VirtualService":
            continue
        state.limits.add(
            kind,
            f"{kind} resources shape the mesh (subsets, gateways, egress, scoping); they are "
            "read for references and schemes but describe no HTTP route",
            count=count,
        )
    routes, redactions = _build_routes(state)
    if not routes:
        raise GatewayConfigParseError(
            "No VirtualService declares an HTTP route — there is no http rule to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    services = sorted({route.service_name for route in routes if route.service_name})
    return GatewayConfigDocument(
        flavor=ISTIO_FLAVOR,
        title=title or source_label or (services[0] if services else "Istio VirtualServices"),
        routes=tuple(routes),
        ignored=state.limits.as_ignored(),
        credential_redactions=redactions,
        source_label=source_label,
        raw={
            "flavor": ISTIO_FLAVOR,
            "virtual_services": services,
            "kinds": dict(sorted(state.kinds.items())),
            "route_names": sorted(route.name for route in routes),
            "hostnames": sorted({host for route in routes for host in route.hosts}),
        },
    )


def _read_text(text: str, state: _Collected, origin: str) -> None:
    """Decode-check, parse and fold one text into ``state``."""
    reject_binary(text, format_label=_LABEL)
    documents = load_yaml_documents(text, format_label=_LABEL)
    if any(is_istio_document(document) for document in documents):
        raise_if_truncated_tail(text, format_label=_LABEL, rules=_TAIL_RULES)
    _collect(documents, state, origin)


def parse_istio(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse an Istio resource stream into a :class:`GatewayConfigDocument`.

    Args:
        text: YAML text — one resource or a ``---``-separated stream.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="istio"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED`` for broken or cut-off YAML,
            ``FORMAT_MISMATCH`` when nothing is Istio, ``INPUT_SEMANTIC_INVALID`` when no
            VirtualService declares an HTTP rule, and ``INPUT_REFERENCE_UNRESOLVED`` for a
            destination subset its DestinationRule does not define.
    """
    state = _Collected()
    _read_text(text, state, source_label or "document")
    return _document_from(state, title=None, source_label=source_label)


def parse_istio_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse a GitOps directory of Istio manifests as one stream.

    Args:
        members: Member path → text.
        root: The root member, read first when known.
        source_label: Label for the merged document.

    Returns:
        The merged document — a VirtualService in one file resolves subsets from a
        DestinationRule in another.

    Raises:
        GatewayConfigParseError: As :func:`parse_istio`; a member's syntax error carries
            the member path.
    """
    ordered = sorted(members)
    if root in members:
        ordered = [root] + [path for path in ordered if path != root]
    state = _Collected()
    for path in ordered:
        try:
            _read_text(members[path], state, path)
        except GatewayConfigParseError as exc:
            raise GatewayConfigParseError(f"{path}: {exc}", code=exc.code) from exc
    return _document_from(state, title=source_label, source_label=source_label or root)
