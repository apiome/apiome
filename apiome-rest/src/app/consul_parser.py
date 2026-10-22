"""Parser for Consul service definitions and configuration entries — FMT-7.5 (#5459).

A Consul catalog is a service **registry**, not a route table, which makes it the thinnest
member of the gateway family and the one whose fidelity claims must be most careful.
Three shapes are read, in JSON or HCL, alone or as a set of files:

* **Service definitions** (``service`` / ``services``) and **catalog exports**
  (``Nodes[].Services``): name, address, port, tags, meta and health checks. They carry
  no paths. A registered HTTP service that no ``service-router`` describes becomes one
  inferred catch-all operation — or, when it carries Fabio-style ``urlprefix-/path``
  tags, one inferred prefix operation per tag (a *convention*, so it is labelled as one).
* **``service-router``** entries: the only shape that carries real path semantics —
  ``PathExact`` / ``PathPrefix`` / ``PathRegex`` (through the shared Gateway API
  path-type table), ``Methods``, ``Header`` and ``QueryParam`` matches. Unmatched
  requests fall through to the router's own service, which becomes a catch-all route.
* **``ingress-gateway``** entries: HTTP listeners expose services on hosts (one catch-all
  route per exposed service); gRPC and TCP listeners are declared.

``service-resolver`` subsets are read so a destination naming an undefined subset is
refused; ``service-defaults`` supplies a service's protocol; ``service-splitter`` splits
ride on the routes to their service as policy. Every other configuration entry kind is
declared. A router destination naming a service that is neither registered nor named by
another entry in the import is ``INPUT_REFERENCE_UNRESOLVED``.
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
    GatewayServiceDef,
)
from .gateway_match import STRING_MATCH_OPERATORS, path_pattern, render_match_value
from .mesh_route_common import LimitCollector, policy_plugin, reject_binary
from .proxy_route_common import is_json_text, load_json_document, ordered_members

__all__ = [
    "CONSUL_FLAVOR",
    "CONSUL_CONFIG_KINDS",
    "CONSUL_READ_CONSTRUCTS",
    "CONSUL_DECLARED_CONSTRUCTS",
    "is_consul",
    "is_consul_document",
    "parse_consul",
    "parse_consul_fileset",
    "parse_hcl",
]

#: Flavor key stamped on the parsed document.
CONSUL_FLAVOR = "consul"

#: Human name used in messages.
_LABEL = "Consul"

#: Configuration-entry kinds Consul defines (recognized; only some are read).
CONSUL_CONFIG_KINDS = frozenset(
    {
        "service-router",
        "service-splitter",
        "service-resolver",
        "service-defaults",
        "proxy-defaults",
        "ingress-gateway",
        "terminating-gateway",
        "api-gateway",
        "http-route",
        "tcp-route",
        "service-intentions",
        "mesh",
        "exported-services",
        "sameness-group",
        "jwt-provider",
        "control-plane-request-limit",
        "inline-certificate",
        "file-system-certificate",
    }
)

#: ``Match.HTTP`` path keys → Gateway API path type.
_PATH_KEYS: Dict[str, str] = {
    "PathExact": "Exact",
    "PathPrefix": "PathPrefix",
    "PathRegex": "RegularExpression",
}

#: Destination keys that pick the target; every other key is traffic policy.
_DESTINATION_TARGET_KEYS = frozenset({"service", "servicesubset", "namespace", "partition", "peer"})

#: Protocols that carry HTTP requests.
_HTTP_PROTOCOLS = frozenset({"http", "http2"})

#: Construct vocabulary for the capability registry.
CONSUL_READ_CONSTRUCTS: Tuple[str, ...] = (
    "service-definition",
    "service-definition.tags",
    "service-definition.meta",
    "service-definition.checks",
    "catalog-export",
    "tag.urlprefix",
    "service-router",
    "service-router.PathExact",
    "service-router.PathPrefix",
    "service-router.PathRegex",
    "service-router.Methods",
    "service-router.Header",
    "service-router.QueryParam",
    "service-router.Destination",
    "service-resolver.Subsets",
    "service-defaults.Protocol",
    "service-splitter.Splits",
    "ingress-gateway.http-listener",
    "hcl",
    "json",
    "service-set-fileset",
)

#: Constructs declared on the ledger when a document uses them.
CONSUL_DECLARED_CONSTRUCTS: Tuple[str, ...] = (
    "config-entry.other",
    "ingress-gateway.grpc-listener",
    "ingress-gateway.tcp-listener",
    "ingress-gateway.wildcard-service",
    "match.Header.Invert",
    "match.QueryParam.Present",
    "service.non-http",
    "service.connect-upstreams",
    "service-resolver.Failover",
    "service-resolver.Redirect",
)


# ---------------------------------------------------------------------------------------
# HCL (the subset Consul definitions use)
# ---------------------------------------------------------------------------------------

_HCL_TOKEN_RE = re.compile(
    r"""(?P<ws>[ \t\r]+)|(?P<nl>\n)|(?P<comment>\#[^\n]*|//[^\n]*|/\*.*?\*/)|
        (?P<string>"(?:[^"\\\n]|\\.)*")|(?P<open_string>"(?:[^"\\\n]|\\.)*$)|
        (?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(?P<ident>[A-Za-z_][A-Za-z0-9_.-]*)|
        (?P<punct>[{}\[\]=,:])""",
    re.VERBOSE | re.DOTALL,
)


class _HclParser:
    """Recursive-descent reader for HCL attribute/block syntax (no expressions)."""

    def __init__(self, text: str, origin: str) -> None:
        self.origin = origin
        self.tokens: List[Tuple[str, str, int]] = []
        line = 1
        position = 0
        while position < len(text):
            match = _HCL_TOKEN_RE.match(text, position)
            if not match:
                raise GatewayConfigParseError(
                    f"{origin}:{line}: unexpected character {text[position]!r} in HCL",
                    code="INPUT_MALFORMED",
                )
            kind = match.lastgroup or ""
            value = match.group(kind)
            if kind == "open_string" or (kind == "comment" and value.startswith("/*") and not value.endswith("*/")):
                raise GatewayConfigParseError(
                    f"{origin}:{line}: HCL document is truncated — a string never closes",
                    code="INPUT_TRUNCATED",
                )
            if kind in ("string", "number", "ident", "punct"):
                self.tokens.append((kind, value, line))
            elif kind == "nl":
                self.tokens.append(("nl", "\n", line))
            line += value.count("\n") if kind != "nl" else 1
            position = match.end()
        self.index = 0

    def _peek(self, skip_newlines: bool = True) -> Optional[Tuple[str, str, int]]:
        index = self.index
        while skip_newlines and index < len(self.tokens) and self.tokens[index][0] == "nl":
            index += 1
        return self.tokens[index] if index < len(self.tokens) else None

    def _next(self) -> Tuple[str, str, int]:
        token = self._peek()
        if token is None:
            raise GatewayConfigParseError(
                f"{self.origin}: HCL document is truncated — it ends inside a block, list or " "attribute",
                code="INPUT_TRUNCATED",
            )
        while self.tokens[self.index][0] == "nl":
            self.index += 1
        self.index += 1
        return token

    def _error(self, token: Tuple[str, str, int], expected: str) -> GatewayConfigParseError:
        return GatewayConfigParseError(
            f"{self.origin}:{token[2]}: expected {expected}, found {token[1]!r}", code="INPUT_MALFORMED"
        )

    @staticmethod
    def _unquote(value: str) -> str:
        return bytes(value[1:-1], "utf-8").decode("unicode_escape") if "\\" in value else value[1:-1]

    def body(self, closing: Optional[str]) -> List[Tuple[str, Any]]:
        """Read attributes and blocks until ``closing`` (or the end of input)."""
        pairs: List[Tuple[str, Any]] = []
        while True:
            token = self._peek()
            if token is None:
                if closing is not None:
                    self._next()  # raises the truncation error
                return pairs
            if token[0] == "punct" and token[1] == closing:
                self._next()
                return pairs
            if token[0] == "punct" and token[1] == ",":
                self._next()
                continue
            key_token = self._next()
            if key_token[0] not in ("ident", "string"):
                raise self._error(key_token, "an attribute or block name")
            key = self._unquote(key_token[1]) if key_token[0] == "string" else key_token[1]
            following = self._next()
            if following[0] == "punct" and following[1] in ("=", ":"):
                pairs.append((key, self.value()))
                continue
            while following[0] == "string":  # block labels
                following = self._next()
            if following[0] == "punct" and following[1] == "{":
                pairs.append((key, _as_object(self.body("}"))))
                continue
            raise self._error(following, "'=' or '{'")

    def value(self) -> Any:
        """Read one value: string, number, bool/null, list or object."""
        token = self._next()
        kind, value = token[0], token[1]
        if kind == "string":
            return self._unquote(value)
        if kind == "number":
            return float(value) if any(ch in value for ch in ".eE") else int(value)
        if kind == "ident":
            return {"true": True, "false": False, "null": None}.get(value, value)
        if value == "{":
            return _as_object(self.body("}"))
        if value == "[":
            items: List[Any] = []
            while True:
                peek = self._peek()
                if peek is None:
                    self._next()
                if peek[0] == "punct" and peek[1] == "]":  # type: ignore[index]
                    self._next()
                    return items
                if peek[0] == "punct" and peek[1] == ",":  # type: ignore[index]
                    self._next()
                    continue
                items.append(self.value())
        raise self._error(token, "a value")


def _as_object(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    """Pairs → mapping; a repeated block name collects its values into a list."""
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            existing = out[key]
            out[key] = (existing if isinstance(existing, list) else [existing]) + [value]
        else:
            out[key] = value
    return out


def parse_hcl(text: str, *, origin: str = "document") -> List[Dict[str, Any]]:
    """Read Consul HCL into documents — one per configuration entry, plus definitions.

    A file holding several configuration entries repeats ``Kind`` at the top level; each
    ``Kind`` starts a new document. Attributes and blocks before the first ``Kind``
    (``service`` / ``services`` blocks) form a document of their own.

    Args:
        text: The HCL text.
        origin: File label for messages.

    Returns:
        The documents, in order.

    Raises:
        GatewayConfigParseError: ``INPUT_MALFORMED`` for a syntax error,
            ``INPUT_TRUNCATED`` when the text ends inside a construct.
    """
    pairs = _HclParser(text, origin).body(None)
    documents: List[List[Tuple[str, Any]]] = [[]]
    for key, value in pairs:
        if key.lower() == "kind" and any(existing.lower() == "kind" for existing, _ in documents[-1]):
            documents.append([])
        elif (
            key.lower() == "kind"
            and documents[-1]
            and not any(existing.lower() == "kind" for existing, _ in documents[-1])
        ):
            documents.append([])
        documents[-1].append((key, value))
    return [_as_object(document) for document in documents if document]


# ---------------------------------------------------------------------------------------
# Case-insensitive access (Consul accepts CamelCase and snake_case alike)
# ---------------------------------------------------------------------------------------


def _norm(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


def _get(mapping: Any, *names: str) -> Any:
    """The value under any spelling of ``names`` (``PathPrefix`` ≡ ``path_prefix``)."""
    if not isinstance(mapping, Mapping):
        return None
    wanted = {_norm(name) for name in names}
    for key, value in mapping.items():
        if _norm(str(key)) in wanted:
            return value
    return None


def _list(value: Any) -> List[Any]:
    """A value as a list (a single block becomes a one-item list)."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ---------------------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------------------


def _definition_services(document: Mapping[str, Any]) -> Optional[List[Mapping[str, Any]]]:
    """The service definitions a document carries, or ``None`` when it is not one."""
    if "_format_version" in document:
        return None
    single = _get(document, "service")
    many = _get(document, "services")
    entries: List[Any] = []
    if isinstance(single, Mapping):
        entries.append(single)
    elif isinstance(single, list):
        entries.extend(single)
    if isinstance(many, list):
        entries.extend(many)
    elif isinstance(many, Mapping) and _get(many, "name") is not None:
        entries.append(many)
    services = [entry for entry in entries if isinstance(entry, Mapping) and isinstance(_get(entry, "name"), str)]
    if not services or any(_get(entry, "routes", "url", "host") is not None for entry in services):
        return None
    return services


def _is_catalog_export(document: Mapping[str, Any]) -> bool:
    nodes = _get(document, "nodes")
    return isinstance(nodes, list) and any(
        isinstance(node, Mapping) and _get(node, "services") is not None for node in nodes
    )


def _config_kind(document: Mapping[str, Any]) -> Optional[str]:
    kind = _get(document, "kind")
    return kind if isinstance(kind, str) and kind in CONSUL_CONFIG_KINDS else None


def is_consul_document(document: Any) -> bool:
    """True when a parsed document is a Consul definition, catalog export or config entry."""
    if isinstance(document, list):
        return bool(document) and all(isinstance(item, Mapping) and _get(item, "servicename") for item in document)
    if not isinstance(document, Mapping):
        return False
    return (
        _config_kind(document) is not None or _definition_services(document) is not None or _is_catalog_export(document)
    )


def _load(text: str, origin: str) -> List[Any]:
    """Load a JSON document or HCL documents."""
    reject_binary(text, format_label=_LABEL)
    if is_json_text(text) or text.lstrip().startswith("["):
        return [load_json_document(text, format_label=_LABEL)]
    return parse_hcl(text, origin=origin)


def is_consul(text: str) -> bool:
    """Cheap sniff for detection."""
    if not text or "\x00" in text:
        return False
    if not re.search(r"service|Services|Kind|kind|Nodes", text):
        return False
    try:
        documents = _load(text, "document")
    except GatewayConfigParseError:
        return False
    return any(is_consul_document(document) for document in documents)


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


@dataclass
class _Service:
    """One registered service (all instances merged)."""

    name: str
    instances: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    upstreams: List[str] = field(default_factory=list)


@dataclass
class _State:
    """Everything gathered before routes are built."""

    services: Dict[str, _Service] = field(default_factory=dict)
    routers: List[Tuple[Mapping[str, Any], str]] = field(default_factory=list)
    ingress: List[Tuple[Mapping[str, Any], str]] = field(default_factory=list)
    subsets: Dict[str, Set[str]] = field(default_factory=dict)
    protocols: Dict[str, str] = field(default_factory=dict)
    splits: Dict[str, Any] = field(default_factory=dict)
    entry_names: Set[str] = field(default_factory=set)
    kinds: Dict[str, int] = field(default_factory=dict)
    saw_consul: bool = False
    limits: LimitCollector = field(default_factory=LimitCollector)


def _check_summary(check: Mapping[str, Any]) -> Dict[str, Any]:
    """A health check's type and target (never its headers, which may carry tokens)."""
    summary: Dict[str, Any] = {}
    name = _get(check, "name")
    if isinstance(name, str):
        summary["name"] = name
    for kind in ("http", "tcp", "grpc", "h2ping", "udp", "alias_service", "ttl", "script", "args"):
        value = _get(check, kind)
        if value is not None:
            summary["type"] = kind
            if kind in ("http", "tcp", "grpc", "h2ping", "udp", "alias_service"):
                summary["target"] = value
            break
    definition = _get(check, "definition")
    if "type" not in summary and isinstance(definition, Mapping):
        return {**summary, **_check_summary(definition)}
    status = _get(check, "status")
    if isinstance(status, str):
        summary["status"] = status
    kind = _get(check, "type")
    if "type" not in summary and isinstance(kind, str):
        summary["type"] = kind
    return summary


def _register(entry: Mapping[str, Any], state: _State, *, require_endpoint: bool, origin: str) -> None:
    """Fold one service definition / catalog instance into ``state``."""
    name = _get(entry, "name", "service", "servicename")
    if not isinstance(name, str) or not name:
        return
    port = _get(entry, "port", "serviceport")
    address = _get(entry, "address", "serviceaddress")
    socket_path = _get(entry, "socket_path")
    if require_endpoint and port is None and not address and not socket_path:
        raise GatewayConfigParseError(
            f"{origin}: service {name!r} is registered with no port, address or socket path — "
            "it has no reachable endpoint, so nothing can be routed to it",
            code="INPUT_SEMANTIC_INVALID",
        )
    service = state.services.setdefault(name, _Service(name=name))
    instance: Dict[str, Any] = {}
    for key, value in (("id", _get(entry, "id")), ("address", address), ("port", port)):
        if value not in (None, ""):
            instance[key] = value
    service.instances.append(instance)
    for tag in _list(_get(entry, "tags", "servicetags")):
        if isinstance(tag, str) and tag not in service.tags:
            service.tags.append(tag)
    meta = _get(entry, "meta", "servicemeta")
    if isinstance(meta, Mapping):
        service.meta.update({str(key): value for key, value in meta.items()})
    for check in _list(_get(entry, "check")) + _list(_get(entry, "checks")):
        if isinstance(check, Mapping):
            service.checks.append(_check_summary(check))
    connect = _get(entry, "connect")
    sidecar = _get(connect, "sidecar_service") if isinstance(connect, Mapping) else None
    proxy = _get(sidecar, "proxy") if isinstance(sidecar, Mapping) else None
    for upstream in _list(_get(proxy, "upstreams")):
        destination = _get(upstream, "destination_name")
        if isinstance(destination, str) and destination not in service.upstreams:
            service.upstreams.append(destination)
    if service.upstreams:
        state.limits.add(
            "service.connect-upstreams",
            "Connect sidecar upstreams name the services this one calls (its dependencies, not "
            "its surface); they are kept on the service, not modelled as routes",
        )


def _read_catalog(document: Mapping[str, Any], state: _State, origin: str) -> None:
    """Fold a ``/v1/catalog`` export into ``state``."""
    for node in _list(_get(document, "nodes")):
        if not isinstance(node, Mapping):
            continue
        services = _get(node, "services")
        instances = services.values() if isinstance(services, Mapping) else _list(services)
        for instance in instances:
            if isinstance(instance, Mapping):
                _register(instance, state, require_endpoint=False, origin=origin)
        for check in _list(_get(node, "checks")):
            if not isinstance(check, Mapping):
                continue
            owner = _get(check, "servicename")
            if isinstance(owner, str) and owner in state.services:
                state.services[owner].checks.append(_check_summary(check))
    tags = _get(document, "services")
    if isinstance(tags, Mapping):
        for name, values in tags.items():
            service = state.services.setdefault(str(name), _Service(name=str(name)))
            for tag in _list(values):
                if isinstance(tag, str) and tag not in service.tags:
                    service.tags.append(tag)


def _read_entry(document: Mapping[str, Any], kind: str, state: _State, origin: str) -> None:
    """Fold one configuration entry into ``state``."""
    state.kinds[kind] = state.kinds.get(kind, 0) + 1
    name = _get(document, "name")
    name = name if isinstance(name, str) else ""
    if name:
        state.entry_names.add(name)
    if kind == "service-router":
        state.routers.append((document, origin))
    elif kind == "ingress-gateway":
        state.ingress.append((document, origin))
    elif kind == "service-resolver":
        subsets = _get(document, "subsets")
        state.subsets[name] = set(subsets) if isinstance(subsets, Mapping) else set()
        default = _get(document, "defaultsubset")
        if isinstance(default, str) and default:
            state.subsets[name].add(default)
        for key, construct in (("failover", "service-resolver.Failover"), ("redirect", "service-resolver.Redirect")):
            if _get(document, key) is not None:
                state.limits.add(
                    construct,
                    f"the resolver's {key} sends traffic to another datacenter, peer or subset at "
                    "runtime; it is traffic policy, not part of the API surface",
                )
    elif kind == "service-defaults":
        protocol = _get(document, "protocol")
        if isinstance(protocol, str):
            state.protocols[name] = protocol.lower()
    elif kind == "service-splitter":
        state.splits[name] = _get(document, "splits")
    else:
        state.limits.add(
            "config-entry.other",
            "configuration entries other than service-router / -splitter / -resolver / -defaults "
            "and ingress-gateway shape the mesh (intentions, proxies, gateways to the outside); "
            "they are not read",
        )


def _collect(documents: Sequence[Any], state: _State, origin: str) -> None:
    """Fold one member's documents into ``state``."""
    for document in documents:
        if isinstance(document, list) and is_consul_document(document):
            state.saw_consul = True
            for instance in document:
                _register(instance, state, require_endpoint=False, origin=origin)
            continue
        if not isinstance(document, Mapping):
            continue
        kind = _config_kind(document)
        if kind is not None:
            state.saw_consul = True
            _read_entry(document, kind, state, origin)
            continue
        services = _definition_services(document)
        if services is not None:
            state.saw_consul = True
            for entry in services:
                _register(entry, state, require_endpoint=True, origin=origin)
            continue
        if _is_catalog_export(document):
            state.saw_consul = True
            _read_catalog(document, state, origin)


# ---------------------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------------------


def _string_match(spec: Mapping[str, Any], limits: LimitCollector, location: str) -> Optional[Tuple[str, str]]:
    """A ``Header`` / ``QueryParam`` match → ``(name, rendered value)``; ``None`` if inverted."""
    name = _get(spec, "name")
    if not isinstance(name, str):
        return None
    if _get(spec, "invert") is True:
        limits.add(
            "match.Header.Invert",
            "an inverted match (the route applies when the value does NOT match) has no "
            "canonical parameter form; the route keeps it as a condition",
        )
        return None
    for operator in STRING_MATCH_OPERATORS:
        value = _get(spec, operator)
        if isinstance(value, str):
            return name, render_match_value(operator, value)
    if _get(spec, "present") is True:
        if location == "query":
            limits.add(
                "match.QueryParam.Present",
                "a presence-only query match is kept as a required parameter with no value",
            )
        return name, ""
    return name, ""


def _destination(route: Mapping[str, Any], default_service: str) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """``Destination`` → (service, subset, policy keys)."""
    destination = _get(route, "destination")
    destination = destination if isinstance(destination, Mapping) else {}
    service = _get(destination, "service")
    subset = _get(destination, "servicesubset")
    policy = {str(key): value for key, value in destination.items() if _norm(str(key)) not in _DESTINATION_TARGET_KEYS}
    return (
        service if isinstance(service, str) and service else default_service,
        subset if isinstance(subset, str) and subset else None,
        policy,
    )


def _known_services(state: _State) -> Set[str]:
    """Services a destination may name: registered, or named by another entry in the import."""
    names = set(state.services) | state.entry_names
    for document, _origin in state.ingress:
        for listener in _list(_get(document, "listeners")):
            for service in _list(_get(listener, "services")):
                name = _get(service, "name")
                if isinstance(name, str):
                    names.add(name)
    return names


def _check_destination(router: str, service: str, subset: Optional[str], state: _State) -> None:
    """Refuse a destination naming an unknown service or an undefined subset."""
    if service not in _known_services(state):
        raise GatewayConfigParseError(
            f"service-router {router!r} routes to service {service!r}, which no service "
            "definition or configuration entry in the import registers",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    defined = state.subsets.get(service)
    if subset is not None and defined is not None and subset not in defined:
        raise GatewayConfigParseError(
            f"service-router {router!r} routes to subset {subset!r} of {service!r}, which its "
            f"service-resolver does not define (defined: {', '.join(sorted(defined)) or 'none'})",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


def _split_plugins(service: str, state: _State, route: str) -> List[GatewayPlugin]:
    """A service's splitter as a policy plugin on the routes that reach it."""
    if service not in state.splits:
        return []
    plugin, _count = policy_plugin(
        "service-splitter", {"splits": state.splits[service]}, scope="service", attached_to=route
    )
    return [plugin]


def _router_routes(state: _State) -> Tuple[List[GatewayRoute], Set[str]]:
    """Routes from every ``service-router`` (plus each router's fall-through route)."""
    routes: List[GatewayRoute] = []
    routed: Set[str] = set()
    for document, origin in state.routers:
        name = _get(document, "name")
        name = name if isinstance(name, str) and name else "router"
        routed.add(name)
        for index, route in enumerate(_list(_get(document, "routes"))):
            if not isinstance(route, Mapping):
                continue
            http = _get(_get(route, "match"), "http")
            http = http if isinstance(http, Mapping) else {}
            pattern = path_pattern("PathPrefix", "/")
            for key, path_type in _PATH_KEYS.items():
                value = _get(http, key)
                if isinstance(value, str):
                    pattern = path_pattern(path_type, value)
                    break
            headers = tuple(
                match
                for spec in _list(_get(http, "header"))
                if isinstance(spec, Mapping) and (match := _string_match(spec, state.limits, "header")) is not None
            )
            query = tuple(
                match
                for spec in _list(_get(http, "queryparam"))
                if isinstance(spec, Mapping) and (match := _string_match(spec, state.limits, "query")) is not None
            )
            methods = [str(method).upper() for method in _list(_get(http, "methods")) if isinstance(method, str)] or [
                None
            ]
            service, subset, policy = _destination(route, name)
            route_name = f"service-router/{name}#route-{index}"
            _check_destination(name, service, subset, state)
            plugins = []
            for key, value in sorted(policy.items()):
                plugin, _count = policy_plugin(key, value, scope="route", attached_to=route_name)
                plugins.append(plugin)
            plugins.extend(_split_plugins(service, state, route_name))
            routes.append(
                GatewayRoute(
                    name=route_name,
                    service_name=name,
                    matches=tuple(
                        GatewayMatch(path=pattern, method=method, headers=headers, query=query) for method in methods
                    ),
                    protocols=("http",),
                    plugins=tuple(plugins),
                    backends=(GatewayBackend(name=service, subset=subset),),
                    source_location=f"{origin}#service-router/{name}.Routes[{index}]",
                    extras={"config_entry": f"service-router/{name}"},
                )
            )
        fallthrough = f"service-router/{name}#default"
        routes.append(
            GatewayRoute(
                name=fallthrough,
                service_name=name,
                matches=(GatewayMatch(path=path_pattern("PathPrefix", "/")),),
                protocols=("http",),
                plugins=tuple(_split_plugins(name, state, fallthrough)),
                backends=(GatewayBackend(name=name),),
                source_location=f"{origin}#service-router/{name}",
                extras={"config_entry": f"service-router/{name}", "default_route": True},
            )
        )
    return routes, routed


def _ingress_routes(state: _State) -> Tuple[List[GatewayRoute], Set[str]]:
    """Routes from every ``ingress-gateway`` HTTP listener."""
    routes: List[GatewayRoute] = []
    exposed: Set[str] = set()
    for document, origin in state.ingress:
        gateway = _get(document, "name") or "ingress-gateway"
        tls = _get(_get(document, "tls"), "enabled") is True
        for listener in _list(_get(document, "listeners")):
            protocol = str(_get(listener, "protocol") or "tcp").lower()
            port = _get(listener, "port")
            services = [service for service in _list(_get(listener, "services")) if isinstance(service, Mapping)]
            if protocol not in _HTTP_PROTOCOLS:
                state.limits.add(
                    f"ingress-gateway.{'grpc' if protocol == 'grpc' else 'tcp'}-listener",
                    f"a {protocol} listener exposes services without HTTP routing; there is no "
                    "canonical HTTP operation for it",
                    count=max(len(services), 1),
                )
                continue
            for service in services:
                name = _get(service, "name")
                if not isinstance(name, str):
                    continue
                if name == "*":
                    state.limits.add(
                        "ingress-gateway.wildcard-service",
                        "a wildcard listener exposes every HTTP service by name at runtime; "
                        "the set is not knowable from the entry",
                    )
                    continue
                exposed.add(name)
                hosts = tuple(
                    sorted(str(host).lower() for host in _list(_get(service, "hosts")) if isinstance(host, str))
                )
                route_name = f"ingress-gateway/{gateway}#{port}/{name}"
                plugins = []
                for key in ("requestheaders", "responseheaders"):
                    value = _get(service, key)
                    if value is not None:
                        plugin, _count = policy_plugin(key, value, scope="route", attached_to=route_name)
                        plugins.append(plugin)
                routes.append(
                    GatewayRoute(
                        name=route_name,
                        service_name=name,
                        hosts=hosts,
                        matches=(GatewayMatch(path=path_pattern("PathPrefix", "/")),),
                        protocols=("https",) if tls else ("http",),
                        plugins=tuple(plugins),
                        backends=(GatewayBackend(name=name, port=port if isinstance(port, int) else None),),
                        source_location=f"{origin}#ingress-gateway/{gateway}",
                        extras={"config_entry": f"ingress-gateway/{gateway}", "listener_port": port},
                    )
                )
    return routes, exposed


def _service_protocol(service: _Service, state: _State) -> Optional[str]:
    """A service's protocol: service-defaults, then ``meta.protocol``, then a protocol tag."""
    if service.name in state.protocols:
        return state.protocols[service.name]
    protocol = service.meta.get("protocol")
    if isinstance(protocol, str):
        return protocol.lower()
    for tag in service.tags:
        if tag.lower() in ("http", "http2", "grpc", "tcp"):
            return tag.lower()
    return None


def _registry_routes(state: _State, covered: Set[str]) -> List[GatewayRoute]:
    """Inferred routes for registered HTTP services no router or gateway describes."""
    routes: List[GatewayRoute] = []
    for name, service in sorted(state.services.items()):
        if name in covered:
            continue
        protocol = _service_protocol(service, state)
        if protocol is not None and protocol not in _HTTP_PROTOCOLS:
            state.limits.add(
                "service.non-http",
                "a registered service whose protocol is not HTTP (gRPC, TCP) has no canonical "
                "HTTP operation; it is kept as a service",
            )
            continue
        prefixes = [tag[len("urlprefix-") :] for tag in service.tags if tag.startswith("urlprefix-")]
        paths = [prefix.split(" ", 1)[0] for prefix in prefixes if prefix.startswith("/")]
        port = next(
            (instance.get("port") for instance in service.instances if isinstance(instance.get("port"), int)), None
        )
        route_name = f"service/{name}"
        extras: Dict[str, Any] = {
            "path_source": "urlprefix-tag" if paths else "registered-service",
        }
        routes.append(
            GatewayRoute(
                name=route_name,
                service_name=name,
                matches=tuple(GatewayMatch(path=path_pattern("PathPrefix", path)) for path in (paths or ["/"])),
                protocols=("http",),
                plugins=tuple(_split_plugins(name, state, route_name)),
                backends=(GatewayBackend(name=name, port=port),),
                source_location=f"service/{name}",
                extras=extras,
            )
        )
    return routes


def _service_defs(state: _State) -> Tuple[GatewayServiceDef, ...]:
    """Registered services as service definitions."""
    definitions = []
    for name, service in sorted(state.services.items()):
        extras: Dict[str, Any] = {}
        if service.tags:
            extras["tags"] = list(service.tags)
        if service.meta:
            extras["meta"] = dict(sorted(service.meta.items()))
        if service.checks:
            extras["health_checks"] = service.checks
        if service.upstreams:
            extras["connect_upstreams"] = sorted(service.upstreams)
        if service.instances:
            extras["instances"] = sorted(service.instances, key=lambda item: str(item.get("id") or item))
        protocol = _service_protocol(service, state)
        first = next((instance for instance in service.instances if instance), {})
        port = first.get("port") if isinstance(first.get("port"), int) else None
        address = first.get("address") if isinstance(first.get("address"), str) else None
        definitions.append(GatewayServiceDef(name=name, protocol=protocol, host=address, port=port, extras=extras))
    return tuple(definitions)


def _document_from(state: _State, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Resolve references, build routes and assemble the document."""
    if not state.saw_consul:
        raise GatewayConfigParseError(
            "No Consul service definition, catalog export or configuration entry found",
            code="FORMAT_MISMATCH",
        )
    router_routes, routed = _router_routes(state)
    ingress_routes, exposed = _ingress_routes(state)
    registry = _registry_routes(state, routed | exposed)
    routes = router_routes + ingress_routes + registry
    services = _service_defs(state)
    groups = sorted({route.service_name for route in routes if route.service_name} | set(state.services))
    return GatewayConfigDocument(
        flavor=CONSUL_FLAVOR,
        title=title or source_label or (groups[0] if groups else "Consul services"),
        services=services,
        routes=tuple(routes),
        ignored=state.limits.as_ignored(),
        source_label=source_label,
        raw={
            "flavor": CONSUL_FLAVOR,
            "services": sorted(state.services),
            "config_entries": dict(sorted(state.kinds.items())),
            "route_names": sorted(route.name for route in routes),
            "hostnames": sorted({host for route in routes for host in route.hosts}),
        },
    )


def parse_consul(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse one Consul JSON or HCL file into a gateway document.

    Args:
        text: The file text.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="consul"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_MALFORMED`` / ``INPUT_TRUNCATED`` for broken or cut-off JSON/HCL,
            ``FORMAT_MISMATCH`` when nothing is Consul, ``INPUT_SEMANTIC_INVALID`` for a
            service registered with no endpoint, and ``INPUT_REFERENCE_UNRESOLVED`` for a
            router destination naming an unregistered service or an undefined subset.
    """
    state = _State()
    label = source_label or "document"
    _collect(_load(text, label), state, label)
    return _document_from(state, title=None, source_label=source_label)


def parse_consul_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse a directory of Consul definitions and configuration entries as one registry.

    Args:
        members: Member path → text.
        root: The root member, read first when known.
        source_label: Label for the merged document.

    Returns:
        The merged document — a router in one file resolves services registered in others.

    Raises:
        GatewayConfigParseError: As :func:`parse_consul`; a member's error carries its path.
    """
    state = _State()
    for path in ordered_members(members, root):
        try:
            _collect(_load(members[path], path), state, path)
        except GatewayConfigParseError as exc:
            raise GatewayConfigParseError(f"{path}: {exc}", code=exc.code) from exc
    return _document_from(state, title=source_label, source_label=source_label or root)
