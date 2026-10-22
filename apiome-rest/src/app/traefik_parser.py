"""Parser for Traefik dynamic configuration — FMT-7.5 (#5459).

Reads Traefik's two route-config shapes into the flavor-neutral
:class:`~app.gateway_config_model.GatewayConfigDocument`:

* **The file provider's dynamic configuration** (YAML or TOML, one file or a watched
  directory of them): ``http.routers`` name a ``rule``, a ``service`` and ``middlewares``;
  ``http.services`` and ``http.middlewares`` are what those names resolve to.
* **The Kubernetes CRD form**: ``IngressRoute`` resources (``traefik.io/v1alpha1`` or the
  older ``traefik.containo.us/v1alpha1``) with ``spec.routes[].match``, plus the
  ``Middleware`` resources they reference.

**The rule grammar.** A rule is a boolean expression over matchers. It is parsed into
disjunctive normal form, and each conjunction becomes one match condition: ``Path`` →
exact, ``PathPrefix`` → prefix, ``PathRegexp`` → regular expression (all through the
shared Gateway API path-type table, :func:`app.mesh_route_common.path_pattern_for`),
``Host`` → server host, ``Method`` → method, ``Header``/``Query`` (and their ``…Regexp``
forms) → header / query match conditions. What does not reduce to that — a negated
matcher, ``ClientIP``, ``HostRegexp``, an unknown matcher — is kept on the route as an
*unmodelled condition* and declared on the ledger, never silently dropped.

**Declared, not read:** TCP and UDP routers (no HTTP operation exists for them),
``tls`` stores and certificates, ``serversTransports``, and the CRD kinds that are not
HTTP routes. Middlewares ride on the operations they govern as named policy plugins
(``basicAuth`` also yields a ``basic`` auth hint); ``users`` lists are redacted.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .gateway_config_model import (
    GatewayAuthHint,
    GatewayBackend,
    GatewayConfigDocument,
    GatewayConfigParseError,
    GatewayMatch,
    GatewayPathPattern,
    GatewayPlugin,
    GatewayRoute,
    GatewayServiceDef,
)
from .mesh_route_common import (
    LimitCollector,
    load_yaml_documents,
    path_pattern_for,
    policy_plugin,
    raise_if_truncated_tail,
    reject_binary,
)
from .proxy_route_common import ordered_members, template_pattern

__all__ = [
    "TRAEFIK_FLAVOR",
    "TRAEFIK_PATH_MATCHERS",
    "TRAEFIK_READ_CONSTRUCTS",
    "TRAEFIK_DECLARED_CONSTRUCTS",
    "TraefikRuleError",
    "is_traefik",
    "parse_rule",
    "parse_traefik",
    "parse_traefik_fileset",
]

#: Flavor key stamped on the parsed document.
TRAEFIK_FLAVOR = "traefik"

#: Human name used in messages.
_LABEL = "Traefik"

#: apiVersion groups of Traefik's CRDs (current and pre-v3).
_CRD_GROUPS = ("traefik.io/", "traefik.containo.us/")

#: Path matcher → Gateway API path type (mapped on through ``PATH_TYPE_KINDS``).
TRAEFIK_PATH_MATCHERS: Dict[str, str] = {
    "Path": "Exact",
    "PathPrefix": "PathPrefix",
    "PathRegexp": "RegularExpression",
}

#: Matchers that name the request host.
_HOST_MATCHERS = frozenset({"Host", "HostHeader"})

#: Header / query matchers → (location, is_regex).
_PARAM_MATCHERS: Dict[str, Tuple[str, bool]] = {
    "Header": ("header", False),
    "Headers": ("header", False),
    "HeaderRegexp": ("header", True),
    "HeadersRegexp": ("header", True),
    "Query": ("query", False),
    "QueryRegexp": ("query", True),
}

#: Matchers recognized but not modelled, with the reason each is declared.
_CONDITION_MATCHERS: Dict[str, str] = {
    "ClientIP": "the rule matches on the client address, which has no canonical parameter form",
    "HostRegexp": "a host regular expression names no concrete server host; it is kept on the " "route as a condition",
    "HostSNI": "an SNI match belongs to TCP routing, not to an HTTP operation",
    "HostSNIRegexp": "an SNI match belongs to TCP routing, not to an HTTP operation",
    "ALPN": "an ALPN match belongs to TCP routing, not to an HTTP operation",
}

#: Middleware types that are auth mechanisms → canonical scheme (``None`` = unmapped).
_AUTH_MIDDLEWARES: Dict[str, Optional[str]] = {
    "basicAuth": "basic",
    "digestAuth": None,
    "forwardAuth": None,
}

#: Middleware config keys holding credential material Traefik stores inline.
_SECRET_MIDDLEWARE_KEYS = frozenset({"users"})

#: Internal services Traefik provides (``noop@internal`` …) — always resolvable.
_INTERNAL_SERVICES = frozenset({"api", "dashboard", "noop", "ping", "prometheus", "rest"})

#: Top-level / ``http`` sections recognized and declared, with the reason.
_DECLARED_SECTIONS: Dict[str, str] = {
    "tcp": "TCP routers route by SNI/port, not by HTTP request — there is no canonical HTTP " "operation for them",
    "udp": "UDP routers carry no HTTP request at all",
    "tls": "TLS options, stores and certificates configure termination, not routing; they are "
    "not read (certificate files are never opened)",
    "serversTransports": "servers transports configure the connection to backends, not the " "API surface",
}

#: CRD kinds that are HTTP routes or what HTTP routes reference.
_CRD_ROUTE_KINDS = frozenset({"IngressRoute", "Middleware", "TraefikService"})

#: The constructs this parser models — the ``traefik.*`` capability vocabulary.
TRAEFIK_READ_CONSTRUCTS: Tuple[str, ...] = (
    "http.routers",
    "http.services.loadBalancer",
    "http.services.weighted",
    "http.services.mirroring",
    "http.services.failover",
    "http.middlewares",
    "http.middlewares.chain",
    "rule.Path",
    "rule.PathPrefix",
    "rule.PathRegexp",
    "rule.Host",
    "rule.Method",
    "rule.Header",
    "rule.HeaderRegexp",
    "rule.Query",
    "rule.QueryRegexp",
    "rule.boolean-composition",
    "router.tls",
    "router.entryPoints",
    "router.priority",
    "crd.IngressRoute",
    "crd.Middleware",
    "crd.TraefikService",
    "toml-dynamic-config",
    "file-provider-directory",
)

#: Constructs recognized and declared on the ledger whenever a document uses them.
TRAEFIK_DECLARED_CONSTRUCTS: Tuple[str, ...] = (
    "tcp",
    "udp",
    "tls",
    "serversTransports",
    "rule.negation",
    "rule.ClientIP",
    "rule.HostRegexp",
    "rule.HostSNI",
    "rule.unknown-matcher",
    "router.without-rule",
    "service.without-servers",
    "crd.IngressRouteTCP",
    "crd.IngressRouteUDP",
    "crd.TLSOption",
    "crd.TLSStore",
    "crd.ServersTransport",
    "crd.MiddlewareTCP",
)

#: Most conjunctions one rule may expand to before the rest are declared, not built.
_MAX_CONJUNCTIONS = 64


class TraefikRuleError(ValueError):
    """Raised when a router rule is not a well-formed Traefik rule expression."""


# ---------------------------------------------------------------------------------------
# Rule grammar
# ---------------------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<op>&&|\|\||!|\(|\)|,)|`(?P<bt>[^`]*)`|\"(?P<dq>(?:[^\"\\]|\\.)*)\"|"
    r"'(?P<sq>[^']*)'|(?P<ident>[A-Za-z][A-Za-z0-9]*))"
)


@dataclass(frozen=True)
class RuleLiteral:
    """One matcher call in a rule, possibly negated.

    Attributes:
        name: The matcher (``PathPrefix``, ``Header`` …).
        args: Its string arguments, in order.
        negated: True when the matcher is under ``!``.
    """

    name: str
    args: Tuple[str, ...]
    negated: bool = False

    def render(self) -> str:
        """The literal as rule text (``!Header(`X-Internal`, `true`)``)."""
        args = ", ".join(f"`{arg}`" for arg in self.args)
        return f"{'!' if self.negated else ''}{self.name}({args})"


def _tokenize(rule: str) -> List[Tuple[str, str]]:
    """Split rule text into ``(kind, value)`` tokens; raise on anything else."""
    tokens: List[Tuple[str, str]] = []
    position = 0
    text = rule.rstrip()
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if not match or match.end() == position:
            raise TraefikRuleError(f"unexpected text at {text[position:position + 20]!r}")
        position = match.end()
        if match.group("op") is not None:
            tokens.append(("op", match.group("op")))
        elif match.group("ident") is not None:
            tokens.append(("ident", match.group("ident")))
        else:
            value = next(match.group(name) for name in ("bt", "dq", "sq") if match.group(name) is not None)
            tokens.append(("str", value))
    return tokens


class _RuleParser:
    """Recursive-descent parser producing a rule in disjunctive normal form."""

    def __init__(self, tokens: List[Tuple[str, str]]) -> None:
        self.tokens = tokens
        self.index = 0

    def _peek(self) -> Optional[Tuple[str, str]]:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self, kind: str, value: Optional[str] = None) -> str:
        token = self._peek()
        if token is None or token[0] != kind or (value is not None and token[1] != value):
            expected = value or kind
            raise TraefikRuleError(f"expected {expected!r}, found {token[1] if token else 'end of rule'!r}")
        self.index += 1
        return token[1]

    def parse(self) -> List[List[RuleLiteral]]:
        dnf = self._or()
        if self._peek() is not None:
            raise TraefikRuleError(f"unexpected {self._peek()[1]!r} after a complete expression")
        return dnf

    def _or(self) -> List[List[RuleLiteral]]:
        result = self._and()
        while self._peek() == ("op", "||"):
            self.index += 1
            result = result + self._and()
        return result

    def _and(self) -> List[List[RuleLiteral]]:
        result = self._unary()
        while self._peek() == ("op", "&&"):
            self.index += 1
            right = self._unary()
            result = [left + other for left in result for other in right][: _MAX_CONJUNCTIONS + 1]
        return result

    def _unary(self) -> List[List[RuleLiteral]]:
        token = self._peek()
        if token == ("op", "!"):
            self.index += 1
            inner = self._unary()
            if len(inner) == 1 and len(inner[0]) == 1:
                literal = inner[0][0]
                return [[RuleLiteral(literal.name, literal.args, not literal.negated)]]
            # A negated group has no conjunctive form worth guessing; it stays one opaque
            # negated condition, declared on the ledger with the rest of the negations.
            rendered = " || ".join(" && ".join(lit.render() for lit in conj) for conj in inner)
            return [[RuleLiteral("(group)", (rendered,), True)]]
        if token == ("op", "("):
            self.index += 1
            inner = self._or()
            self._take("op", ")")
            return inner
        name = self._take("ident")
        self._take("op", "(")
        args: List[str] = []
        if self._peek() != ("op", ")"):
            args.append(self._take("str"))
            while self._peek() == ("op", ","):
                self.index += 1
                args.append(self._take("str"))
        self._take("op", ")")
        return [[RuleLiteral(name, tuple(args))]]


def parse_rule(rule: str) -> List[List[RuleLiteral]]:
    """Parse a Traefik rule into disjunctive normal form.

    Args:
        rule: The rule text (``Host(`a`) && (Method(`GET`) || Method(`HEAD`))``).

    Returns:
        A list of conjunctions, each a list of literals. Multi-argument matchers written
        in the v2 style (``Host(`a`, `b`)``) are *not* expanded here; see
        :func:`_expand_multi_args`.

    Raises:
        TraefikRuleError: For anything that is not a rule expression.
    """
    tokens = _tokenize(rule)
    if not tokens:
        raise TraefikRuleError("the rule is empty")
    return _RuleParser(tokens).parse()


def _is_cut_rule(value: str) -> bool:
    """True when rule text stops mid-expression (an open backtick, quote or parenthesis)."""
    if value.count("`") % 2:
        return True
    depth = 0
    for char in re.sub(r"`[^`]*`", "", value):
        depth += char == "("
        depth -= char == ")"
    return depth > 0


#: :func:`raise_if_truncated_tail` rules — the last scalar of a cut file is often a rule.
_TAIL_RULES = {"rule": _is_cut_rule, "match": _is_cut_rule}

#: Multi-argument matchers whose arguments are alternatives (Traefik v2 ``Host(`a`, `b`)``).
_ALTERNATIVE_ARG_MATCHERS = frozenset({"Host", "HostHeader", "Path", "PathPrefix", "Method"})


def _expand_multi_args(dnf: List[List[RuleLiteral]]) -> List[List[RuleLiteral]]:
    """Expand v2 multi-argument matchers (an OR over their arguments) into the DNF."""
    expanded: List[List[RuleLiteral]] = []
    for conjunction in dnf:
        options: List[List[RuleLiteral]] = [[]]
        for literal in conjunction:
            if literal.name in _ALTERNATIVE_ARG_MATCHERS and not literal.negated and len(literal.args) > 1:
                choices = [RuleLiteral(literal.name, (arg,)) for arg in literal.args]
            else:
                choices = [literal]
            options = [prefix + [choice] for prefix in options for choice in choices]
        expanded.extend(options)
    return expanded


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


@dataclass
class _Router:
    """One HTTP router, from either shape, before references are resolved."""

    name: str
    rule: str
    service: Optional[str]
    middlewares: Tuple[str, ...]
    tls: bool
    origin: str
    group: str
    extras: Dict[str, Any] = field(default_factory=dict)
    backends: Tuple[GatewayBackend, ...] = ()
    namespace: Optional[str] = None


@dataclass
class _Collected:
    """Everything gathered from every document before routes are built."""

    routers: List[_Router] = field(default_factory=list)
    services: Dict[str, Mapping[str, Any]] = field(default_factory=dict)
    middlewares: Dict[str, Tuple[str, Any]] = field(default_factory=dict)
    crd_kinds: Dict[str, int] = field(default_factory=dict)
    saw_traefik: bool = False
    saw_crd_middleware: bool = False
    shape: Set[str] = field(default_factory=set)
    limits: LimitCollector = field(default_factory=LimitCollector)


def _is_toml(text: str) -> bool:
    """True when the text is Traefik TOML (an ``[http.…]`` / ``[tcp.…]`` table header)."""
    return bool(re.search(r"^\s*\[\[?\s*(http|tcp|udp|tls)\.", text, re.MULTILINE))


def _looks_like_traefik(text: str) -> bool:
    """Cheap textual marker check used to classify a document that failed to load."""
    return "routers" in text or any(group in text for group in _CRD_GROUPS) or _is_toml(text)


def _load_documents(text: str) -> List[Any]:
    """Load a Traefik text as YAML (a stream) or TOML (one document)."""
    if _is_toml(text):
        try:
            return [tomllib.loads(text)]
        except tomllib.TOMLDecodeError as exc:
            raise GatewayConfigParseError(
                f"{_LABEL} TOML document is not valid TOML: {exc}", code="INPUT_MALFORMED"
            ) from exc
    try:
        return load_yaml_documents(text, format_label=_LABEL)
    except GatewayConfigParseError as exc:
        if exc.code == "INPUT_MALFORMED" and not _looks_like_traefik(text):
            raise GatewayConfigParseError(
                f"Not a Traefik dynamic configuration: {exc}", code="FORMAT_MISMATCH"
            ) from exc
        raise


def is_traefik_crd(document: Any) -> bool:
    """True when a document is a Traefik custom resource."""
    if not isinstance(document, Mapping):
        return False
    api_version = str(document.get("apiVersion") or "")
    return any(api_version.startswith(group) for group in _CRD_GROUPS)


def _is_dynamic_config(document: Any) -> bool:
    """True when a document is a file-provider dynamic configuration."""
    if not isinstance(document, Mapping):
        return False
    for section in ("http", "tcp", "udp"):
        body = document.get(section)
        if isinstance(body, Mapping) and any(key in body for key in ("routers", "services", "middlewares")):
            return True
    return False


def is_traefik(text: str) -> Optional[str]:
    """Cheap sniff for detection.

    Returns:
        ``"routers"`` when the text declares HTTP routers (file provider) or an
        ``IngressRoute`` (CRD), ``"supporting"`` for a Traefik document with no HTTP route
        of its own (a services-only file, a lone ``Middleware``), or ``None``.
    """
    if not text or "\x00" in text:
        return None
    if not ("routers" in text or "services" in text or "middlewares" in text or "traefik." in text):
        return None
    try:
        documents = _load_documents(text)
    except GatewayConfigParseError:
        return None
    strongest: Optional[str] = None
    for document in documents:
        if is_traefik_crd(document):
            if document.get("kind") == "IngressRoute":
                return "routers"
            strongest = "supporting"
        elif _is_dynamic_config(document):
            http = document.get("http")
            if isinstance(http, Mapping) and isinstance(http.get("routers"), Mapping):
                return "routers"
            strongest = "supporting"
    return strongest


def _strip_provider(name: str) -> Tuple[str, Optional[str]]:
    """``orders@file`` → ``("orders", "file")``; a bare name has no provider."""
    if "@" in name:
        base, provider = name.rsplit("@", 1)
        return base, provider
    return name, None


def _names(value: Any) -> Tuple[str, ...]:
    """A list of names (``middlewares``, ``entryPoints``) as a tuple of strings."""
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list):
        return tuple(str(item) for item in value if isinstance(item, (str, int)))
    return ()


def _read_dynamic(document: Mapping[str, Any], state: _Collected, origin: str) -> None:
    """Fold one file-provider document into ``state``."""
    state.saw_traefik = True
    state.shape.add("file")
    for section, reason in _DECLARED_SECTIONS.items():
        if section in ("tcp", "udp"):
            body = document.get(section)
            if isinstance(body, Mapping):
                routers = body.get("routers")
                count = len(routers) if isinstance(routers, Mapping) else 0
                state.limits.add(section, reason, count=max(count, 1))
        elif section == "tls" and isinstance(document.get("tls"), Mapping):
            state.limits.add(section, reason)
    http = document.get("http")
    if not isinstance(http, Mapping):
        return
    if isinstance(http.get("serversTransports"), Mapping):
        state.limits.add(
            "serversTransports", _DECLARED_SECTIONS["serversTransports"], count=len(http["serversTransports"])
        )
    services = http.get("services")
    if isinstance(services, Mapping):
        for name, body in services.items():
            if isinstance(body, Mapping):
                state.services[str(name)] = body
    middlewares = http.get("middlewares")
    if isinstance(middlewares, Mapping):
        for name, body in middlewares.items():
            if isinstance(body, Mapping) and body:
                kind = next(iter(body))
                state.middlewares[str(name)] = (str(kind), body[kind])
    routers = http.get("routers")
    if not isinstance(routers, Mapping):
        return
    for name, body in routers.items():
        if not isinstance(body, Mapping):
            continue
        rule = body.get("rule")
        if not isinstance(rule, str) or not rule.strip():
            state.limits.add(
                "router.without-rule",
                "an HTTP router with no rule selects no request; Traefik refuses it, so it " "contributes no operation",
            )
            continue
        service = body.get("service")
        extras: Dict[str, Any] = {"rule": rule.strip()}
        entry_points = _names(body.get("entryPoints"))
        if entry_points:
            extras["entry_points"] = list(entry_points)
        if isinstance(body.get("priority"), int):
            extras["priority"] = body["priority"]
        tls = body.get("tls")
        if isinstance(tls, Mapping):
            tls_summary = {key: tls[key] for key in ("certResolver", "options") if isinstance(tls.get(key), str)}
            if tls_summary:
                extras["tls"] = tls_summary
        service_name = _strip_provider(str(service))[0] if isinstance(service, str) and service else None
        state.routers.append(
            _Router(
                name=str(name),
                rule=rule.strip(),
                service=str(service) if isinstance(service, str) and service else None,
                middlewares=_names(body.get("middlewares")),
                tls=tls is not None,
                origin=f"{origin}#http.routers.{name}",
                group=service_name or "(unattached routes)",
                extras=extras,
            )
        )


def _metadata(document: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """``(name, namespace)`` of a custom resource."""
    metadata = document.get("metadata") if isinstance(document.get("metadata"), Mapping) else {}
    name = metadata.get("name")
    namespace = metadata.get("namespace")
    return (
        name if isinstance(name, str) and name else "",
        namespace if isinstance(namespace, str) and namespace else None,
    )


def _read_crd(document: Mapping[str, Any], state: _Collected, origin: str, index: int) -> None:
    """Fold one Traefik custom resource into ``state``."""
    state.saw_traefik = True
    state.shape.add("crd")
    kind = str(document.get("kind") or "") or "(unnamed kind)"
    state.crd_kinds[kind] = state.crd_kinds.get(kind, 0) + 1
    name, namespace = _metadata(document)
    spec = document.get("spec") if isinstance(document.get("spec"), Mapping) else {}
    if kind == "Middleware":
        state.saw_crd_middleware = True
        if spec:
            middleware_kind = next(iter(spec))
            for key in filter(None, (name, f"{namespace}-{name}" if namespace else None)):
                state.middlewares[key] = (str(middleware_kind), spec[middleware_kind])
        return
    if kind == "TraefikService":
        if name:
            state.services[name] = spec
        return
    if kind != "IngressRoute":
        state.limits.add(
            f"crd.{kind}",
            f"{kind} resources are not HTTP routes (TCP/UDP routing, TLS or transport " "settings); they are not read",
        )
        return
    resource = name or f"ingressroute-{index}"
    group = f"{namespace}/{resource}" if namespace else resource
    entry_points = _names(spec.get("entryPoints"))
    tls = spec.get("tls") is not None
    for route_index, route in enumerate(spec.get("routes") or []):
        if not isinstance(route, Mapping):
            continue
        match = route.get("match")
        if not isinstance(match, str) or not match.strip():
            state.limits.add(
                "router.without-rule",
                "an IngressRoute route with no match selects no request; it contributes no " "operation",
            )
            continue
        backends = []
        for service in route.get("services") or []:
            if not isinstance(service, Mapping) or not isinstance(service.get("name"), str):
                continue
            port = service.get("port")
            weight = service.get("weight")
            backends.append(
                GatewayBackend(
                    name=service["name"],
                    namespace=service.get("namespace") if isinstance(service.get("namespace"), str) else namespace,
                    port=port if isinstance(port, int) else None,
                    weight=weight if isinstance(weight, int) else None,
                )
            )
        middlewares = tuple(
            str(item["name"])
            for item in route.get("middlewares") or []
            if isinstance(item, Mapping) and isinstance(item.get("name"), str)
        )
        extras: Dict[str, Any] = {"rule": match.strip(), "ingress_route": group}
        if namespace:
            extras["namespace"] = namespace
        if entry_points:
            extras["entry_points"] = list(entry_points)
        if isinstance(route.get("priority"), int):
            extras["priority"] = route["priority"]
        state.routers.append(
            _Router(
                name=f"{group}#route-{route_index}",
                rule=match.strip(),
                service=None,
                middlewares=middlewares,
                tls=tls,
                origin=f"{origin}[{index}].spec.routes[{route_index}]",
                group=group,
                extras=extras,
                backends=tuple(backends),
                namespace=namespace,
            )
        )


def _collect(documents: Sequence[Any], state: _Collected, origin: str) -> None:
    """Fold one member's parsed documents into ``state``."""
    for index, document in enumerate(documents):
        if is_traefik_crd(document):
            _read_crd(document, state, origin, index)
        elif _is_dynamic_config(document):
            _read_dynamic(document, state, origin)
        elif isinstance(document, Mapping) and document.get("kind"):
            state.limits.add(str(document.get("kind")), "not a Traefik resource")


# ---------------------------------------------------------------------------------------
# Resolution and route building
# ---------------------------------------------------------------------------------------


def _resolve_service(reference: str, state: _Collected) -> Optional[str]:
    """The service a file-provider reference names, or raise when it names nothing.

    Returns:
        The local service name, or ``None`` for an internal or other-provider service.

    Raises:
        GatewayConfigParseError: ``INPUT_REFERENCE_UNRESOLVED`` for a missing service.
    """
    base, provider = _strip_provider(reference)
    if provider == "internal" or (provider is None and base in _INTERNAL_SERVICES and base not in state.services):
        return None
    if provider not in (None, "file"):
        return None
    if base not in state.services:
        raise GatewayConfigParseError(
            f"Router references service {reference!r}, which no supplied file declares "
            f"(declared: {', '.join(sorted(state.services)) or 'none'})",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    return base


def _service_backends(name: str, state: _Collected, seen: Optional[Set[str]] = None) -> Tuple[GatewayBackend, ...]:
    """The backends a file-provider service forwards to (children resolved by name)."""
    body = state.services.get(name) or {}
    seen = (seen or set()) | {name}
    weighted = body.get("weighted")
    if isinstance(weighted, Mapping):
        backends = []
        for child in weighted.get("services") or []:
            if not isinstance(child, Mapping) or not isinstance(child.get("name"), str):
                continue
            child_name = child["name"]
            if child_name not in seen:
                _resolve_service(child_name, state)
            weight = child.get("weight")
            backends.append(
                GatewayBackend(name=_strip_provider(child_name)[0], weight=weight if isinstance(weight, int) else None)
            )
        return tuple(backends)
    for kind in ("mirroring", "failover"):
        block = body.get(kind)
        if isinstance(block, Mapping) and isinstance(block.get("service"), str):
            _resolve_service(block["service"], state)
            return (GatewayBackend(name=_strip_provider(block["service"])[0]),)
    return (GatewayBackend(name=name),)


def _redacted_middleware(kind: str, config: Any) -> Tuple[Dict[str, Any], int]:
    """A middleware's config with credential material masked."""
    body = dict(config) if isinstance(config, Mapping) else {"value": config}
    count = 0
    for key in _SECRET_MIDDLEWARE_KEYS:
        value = body.get(key)
        if isinstance(value, list):
            body[key] = ["***" for _ in value]
            count += len(value)
        elif value is not None and kind in _AUTH_MIDDLEWARES:
            body[key] = "***"
            count += 1
    return body, count


def _middleware_plugins(
    router: _Router, state: _Collected, check: bool
) -> Tuple[List[GatewayPlugin], List[GatewayAuthHint], int]:
    """Expand a router's middlewares (chains included) into plugins and auth hints."""
    plugins: List[GatewayPlugin] = []
    hints: List[GatewayAuthHint] = []
    redactions = 0
    pending = list(router.middlewares)
    seen: Set[str] = set()
    while pending:
        reference = pending.pop(0)
        base, provider = _strip_provider(reference)
        if base in seen:
            continue
        seen.add(base)
        found = state.middlewares.get(base)
        if found is None and router.namespace:
            found = state.middlewares.get(f"{router.namespace}-{base}")
        if found is None:
            if check and provider in (None, "file", "kubernetescrd"):
                raise GatewayConfigParseError(
                    f"Router {router.name!r} references middleware {reference!r}, which no " "supplied file declares",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            continue
        kind, config = found
        if kind == "chain" and isinstance(config, Mapping):
            pending.extend(_names(config.get("middlewares")))
            continue
        body, count = _redacted_middleware(kind, config)
        plugin, nested = policy_plugin(kind, {"middleware": base, **body}, scope="route", attached_to=router.name)
        redactions += count + nested
        if kind in _AUTH_MIDDLEWARES:
            hints.append(
                GatewayAuthHint(
                    scheme=_AUTH_MIDDLEWARES[kind],
                    plugin=kind,
                    scope="route",
                    attached_to=router.name,
                    detail={"middleware": base},
                )
            )
        else:
            plugins.append(plugin)
    return plugins, hints, redactions


def _path_pattern(matcher: str, value: str) -> GatewayPathPattern:
    """A path matcher's pattern; v2 ``{name:regex}`` templates keep their parameter names."""
    if matcher != "PathRegexp" and "{" in value:
        template = re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*):[^}]*\}", r"{\1}", value)
        return template_pattern(template, "exact" if matcher == "Path" else "prefix")
    return path_pattern_for(TRAEFIK_PATH_MATCHERS[matcher], value)


def _conjunction_match(
    conjunction: Sequence[RuleLiteral], limits: LimitCollector
) -> Tuple[GatewayMatch, Set[str], List[str]]:
    """One conjunction → (match condition, hosts it names, unmodelled conditions)."""
    path: Optional[GatewayPathPattern] = None
    method: Optional[str] = None
    hosts: Set[str] = set()
    headers: List[Tuple[str, str]] = []
    query: List[Tuple[str, str]] = []
    conditions: List[str] = []
    for literal in conjunction:
        name, args = literal.name, literal.args
        if literal.negated:
            limits.add(
                "rule.negation",
                "a negated matcher narrows the route by what a request must NOT carry, which "
                "has no canonical parameter form; it is kept on the route as a condition",
            )
            conditions.append(literal.render())
        elif name in TRAEFIK_PATH_MATCHERS and args:
            if path is None:
                path = _path_pattern(name, args[0])
            else:
                conditions.append(literal.render())
        elif name in _HOST_MATCHERS and args:
            hosts.add(args[0].lower())
        elif name == "Method" and args:
            if method is None:
                method = args[0].upper()
            else:
                conditions.append(literal.render())
        elif name in _PARAM_MATCHERS and args:
            location, regex = _PARAM_MATCHERS[name]
            if len(args) >= 2:
                key, value = args[0], args[1]
            elif "=" in args[0]:
                key, value = args[0].split("=", 1)
            else:
                key, value = args[0], ""
            pair = (key, f"regex:{value}" if regex and value else value)
            (headers if location == "header" else query).append(pair)
        elif name in _CONDITION_MATCHERS:
            limits.add(f"rule.{name}", _CONDITION_MATCHERS[name])
            conditions.append(literal.render())
        else:
            limits.add(
                "rule.unknown-matcher",
                "a matcher outside the Traefik rule grammar this parser reads; it is kept on "
                "the route as a condition",
            )
            conditions.append(literal.render())
    if path is None:
        path = path_pattern_for("PathPrefix", "/")
    return (
        GatewayMatch(path=path, method=method, headers=tuple(headers), query=tuple(query)),
        hosts,
        conditions,
    )


def _build_route(router: _Router, state: _Collected, redactions: List[int]) -> GatewayRoute:
    """One :class:`GatewayRoute` per router."""
    try:
        dnf = _expand_multi_args(parse_rule(router.rule))
    except TraefikRuleError as exc:
        raise GatewayConfigParseError(
            f"Router {router.name!r} has a rule Traefik cannot parse ({exc}): {router.rule!r}",
            code="INPUT_MALFORMED",
        ) from exc
    if len(dnf) > _MAX_CONJUNCTIONS:
        state.limits.add(
            "rule.expansion-bound",
            f"a rule expanding to more than {_MAX_CONJUNCTIONS} alternatives is cut at that "
            "bound; the remaining alternatives are not built",
        )
        dnf = dnf[:_MAX_CONJUNCTIONS]
    matches: List[GatewayMatch] = []
    hosts: Set[str] = set()
    conditions: List[str] = []
    for conjunction in dnf:
        match, conjunction_hosts, conjunction_conditions = _conjunction_match(conjunction, state.limits)
        hosts |= conjunction_hosts
        if match not in matches:
            matches.append(match)
        for condition in conjunction_conditions:
            if condition not in conditions:
                conditions.append(condition)

    backends = router.backends
    if router.service is not None:
        local = _resolve_service(router.service, state)
        backends = _service_backends(local, state) if local is not None else (GatewayBackend(name=router.service),)
    check_middlewares = "file" in state.shape or state.saw_crd_middleware
    plugins, hints, count = _middleware_plugins(router, state, check_middlewares)
    redactions.append(count)
    extras = dict(router.extras)
    if conditions:
        extras["unmodelled_conditions"] = sorted(conditions)
    if router.middlewares:
        extras["middlewares"] = list(router.middlewares)
    return GatewayRoute(
        name=router.name,
        service_name=router.group,
        hosts=tuple(sorted(hosts)),
        matches=tuple(matches),
        protocols=("https",) if router.tls else ("http",),
        auth=tuple(hints),
        plugins=tuple(plugins),
        backends=backends,
        source_location=router.origin,
        extras=extras,
    )


def _service_defs(state: _Collected) -> Tuple[GatewayServiceDef, ...]:
    """Declared load-balancer services as service definitions (upstream detail in extras)."""
    definitions = []
    for name, body in sorted(state.services.items()):
        balancer = body.get("loadBalancer")
        if not isinstance(balancer, Mapping):
            continue
        servers = [
            str(server.get("url"))
            for server in balancer.get("servers") or []
            if isinstance(server, Mapping) and server.get("url")
        ]
        if not servers:
            state.limits.add(
                "service.without-servers",
                "a load-balancer service with no servers forwards nowhere; it is declared, not "
                "modelled as a backend",
            )
            continue
        extras: Dict[str, Any] = {"servers": servers}
        health = balancer.get("healthCheck")
        if isinstance(health, Mapping) and isinstance(health.get("path"), str):
            extras["health_check_path"] = health["path"]
        definitions.append(GatewayServiceDef(name=name, url=servers[0], extras=extras))
    return tuple(definitions)


def _document_from(state: _Collected, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Resolve references, build routes and assemble the document."""
    if not state.saw_traefik:
        raise GatewayConfigParseError(
            "No Traefik dynamic configuration (http.routers / http.services) or Traefik " "custom resource found",
            code="FORMAT_MISMATCH",
        )
    redactions: List[int] = []
    # Routers are a mapping, so their order is the author's, not Traefik's (which ranks by
    # priority / rule length). Building in name order keeps operation keys — including the
    # ``#router`` suffix a colliding key takes — independent of declaration order.
    routes = [_build_route(router, state, redactions) for router in sorted(state.routers, key=lambda r: r.name)]
    services = _service_defs(state)
    if not routes:
        raise GatewayConfigParseError(
            "No HTTP router declares a rule — there is no route to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    groups = sorted({route.service_name for route in routes if route.service_name})
    return GatewayConfigDocument(
        flavor=TRAEFIK_FLAVOR,
        title=title or source_label or (groups[0] if groups else "Traefik routers"),
        services=services,
        routes=tuple(routes),
        ignored=state.limits.as_ignored(),
        credential_redactions=sum(redactions),
        source_label=source_label,
        raw={
            "flavor": TRAEFIK_FLAVOR,
            "shape": sorted(state.shape),
            "router_names": sorted(route.name for route in routes),
            "service_names": sorted(state.services),
            "middleware_names": sorted(state.middlewares),
            "crd_kinds": dict(sorted(state.crd_kinds.items())),
            "hostnames": sorted({host for route in routes for host in route.hosts}),
        },
    )


def _read_text(text: str, state: _Collected, origin: str) -> None:
    """Decode-check, parse and fold one text into ``state``."""
    reject_binary(text, format_label=_LABEL)
    documents = _load_documents(text)
    if not _is_toml(text):
        raise_if_truncated_tail(text, format_label=_LABEL, rules=_TAIL_RULES)
    _collect(documents, state, origin)


def parse_traefik(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse a Traefik dynamic configuration (or CRD stream) into a gateway document.

    Args:
        text: YAML or TOML text.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="traefik"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_MALFORMED`` for broken YAML/TOML or an unparseable rule,
            ``INPUT_TRUNCATED`` for a cut-off file, ``FORMAT_MISMATCH`` when nothing is
            Traefik, ``INPUT_SEMANTIC_INVALID`` when no router has a rule, and
            ``INPUT_REFERENCE_UNRESOLVED`` for a router naming a service or middleware that
            is not declared.
    """
    state = _Collected()
    _read_text(text, state, source_label or "document")
    return _document_from(state, title=None, source_label=source_label)


def parse_traefik_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse a file-provider directory as one merged dynamic configuration.

    Traefik's file provider watching a directory merges every file into one configuration,
    so a router in ``routers.yml`` resolves a service declared in ``services.yml``.

    Args:
        members: Member path → text.
        root: The root member, read first when known.
        source_label: Label for the merged document.

    Returns:
        The merged document.

    Raises:
        GatewayConfigParseError: As :func:`parse_traefik`; a member's error carries its path.
    """
    state = _Collected()
    for path in ordered_members(members, root):
        try:
            _read_text(members[path], state, path)
        except GatewayConfigParseError as exc:
            raise GatewayConfigParseError(f"{path}: {exc}", code=exc.code) from exc
    state.shape.add("directory")
    return _document_from(state, title=source_label, source_label=source_label or root)
