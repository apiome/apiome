"""Bounded parser for nginx configuration — FMT-7.5 (#5459).

nginx configuration is Turing-adjacent: ``map`` and ``geo`` compute variables, ``if``
branches on them, ``try_files`` and ``error_page`` jump to named locations, and Lua or
njs modules run arbitrary code. A complete reader is out of scope by design. This module
reads a **documented subset** and declares everything else:

* :data:`NGINX_READ_DIRECTIVES` — the directives that build the routing surface: the
  ``http`` / ``server`` / ``location`` structure, ``listen`` and ``server_name``, the
  ``*_pass`` handlers and the ``upstream`` blocks they name, ``return``, ``root`` /
  ``alias``, ``limit_except``, ``internal``, ``include`` and the two auth directives.
* :data:`NGINX_CARRIED_DIRECTIVES` — request-shaping directives kept by name as policy on
  the operations they govern (headers, timeouts, rate and connection limits, access
  rules, body size, caching). The *effective* value follows nginx inheritance: the
  innermost of http → server → location that sets a directive wins.
* :data:`NGINX_DECLARED_DIRECTIVES` — the constructs the subset deliberately does not
  interpret (``if``, ``map``, ``geo``, ``set``, ``try_files``, ``error_page``, named and
  nested locations, variables in ``proxy_pass``, scripting modules). Each one a document
  uses becomes a declared parsing limit with its reason.
* Any other directive is declared too, as ``directive.<name>`` — outside the subset is a
  declared limit, never a silent omission.

Each ``location`` becomes one route: ``=`` → exact, no modifier / ``^~`` → prefix,
``~`` / ``~*`` → regular expression, all through the shared Gateway API path-type table
(:func:`app.mesh_route_common.path_pattern_for`). ``server_name`` gives the hosts and
``listen … ssl`` the scheme. A ``proxy_pass`` naming an upstream the configuration does
not declare is ``INPUT_REFERENCE_UNRESOLVED`` — unless an ``include`` could not be
followed, in which case the upstream may live in the missing file.
"""

from __future__ import annotations

import fnmatch
import re
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
from .mesh_route_common import LimitCollector, path_pattern_for, reject_binary
from .proxy_route_common import ordered_members, split_address

__all__ = [
    "NGINX_FLAVOR",
    "NGINX_LOCATION_MODIFIERS",
    "NGINX_READ_DIRECTIVES",
    "NGINX_CARRIED_DIRECTIVES",
    "NGINX_DECLARED_DIRECTIVES",
    "NginxDirective",
    "is_nginx",
    "parse_nginx",
    "parse_nginx_fileset",
    "tokenize_nginx",
]

#: Flavor key stamped on the parsed document.
NGINX_FLAVOR = "nginx"

#: Human name used in messages.
_LABEL = "nginx"

#: ``location`` modifier → Gateway API path type (``None``: not externally routable).
NGINX_LOCATION_MODIFIERS: Dict[str, Optional[str]] = {
    "=": "Exact",
    "": "PathPrefix",
    "^~": "PathPrefix",
    "~": "RegularExpression",
    "~*": "RegularExpression",
    "@": None,
}

#: The documented subset: directives read into the routing surface, with what each gives.
NGINX_READ_DIRECTIVES: Dict[str, str] = {
    "http": "the HTTP context; its servers are the routing surface",
    "server": "one virtual server (in http) or one upstream endpoint (in upstream)",
    "listen": "the port and the `ssl` flag, which decides the scheme",
    "server_name": "the hosts the server answers for (exact and wildcard names)",
    "location": "one route; the modifier gives the path match (exact, prefix, regex)",
    "proxy_pass": "the route's backend: an upstream name or a direct address",
    "grpc_pass": "the route's gRPC backend",
    "fastcgi_pass": "the route's FastCGI backend",
    "uwsgi_pass": "the route's uWSGI backend",
    "scgi_pass": "the route's SCGI backend",
    "return": "a route answered by nginx itself (status, redirect target)",
    "root": "a route served from the filesystem",
    "alias": "a route served from the filesystem",
    "upstream": "a named backend group and its servers",
    "include": "followed when the included file is part of the import",
    "limit_except": "the methods a route admits without further access rules",
    "internal": "marks a location unreachable from outside, so it is not an operation",
    "ssl_certificate": "TLS termination on the server (the certificate is never read)",
    "auth_basic": "HTTP basic authentication on the route",
    "auth_request": "subrequest authentication on the route (no canonical scheme)",
    "events": "connection-processing context; recognized, contributes nothing to routes",
    "stream": "the TCP/UDP context; recognized and declared, since it has no HTTP operation",
}

#: Directives kept by name as policy on the operations they govern (effective value).
NGINX_CARRIED_DIRECTIVES: Tuple[str, ...] = (
    "proxy_set_header",
    "grpc_set_header",
    "add_header",
    "proxy_hide_header",
    "proxy_http_version",
    "proxy_read_timeout",
    "proxy_connect_timeout",
    "proxy_send_timeout",
    "grpc_read_timeout",
    "proxy_next_upstream",
    "proxy_redirect",
    "proxy_buffering",
    "proxy_cache",
    "proxy_cache_valid",
    "expires",
    "limit_req",
    "limit_conn",
    "allow",
    "deny",
    "client_max_body_size",
    "client_body_timeout",
    "rewrite",
    "auth_basic_user_file",
    "default_type",
    "access_log",
)

#: Constructs the subset deliberately does not interpret, with the reason each is declared.
NGINX_DECLARED_DIRECTIVES: Dict[str, str] = {
    "if": "conditional logic evaluated per request; the branch a request takes cannot be "
    "known statically, so directives inside an `if` are not read",
    "map": "computes a variable from request data at runtime; the value a request gets is " "not known statically",
    "geo": "computes a variable from the client address at runtime",
    "split_clients": "computes a variable by hashing request data at runtime",
    "set": "assigns a variable at runtime",
    "try_files": "falls through to files or a named location at runtime; only the location's " "own path is modelled",
    "error_page": "redirects errors to another URI or a named location at runtime",
    "location.named": "a named location (`@name`) is reachable only through try_files / "
    "error_page, never from a client, so it is not an operation",
    "location.internal": "an `internal` location is reachable only through internal "
    "redirects, never from a client, so it is not an operation",
    "location.nested": "a nested location is read as its own route with the outer location's "
    "carried directives inherited; nginx's full nesting rules are not modelled",
    "proxy_pass.variable": "the backend is computed from a variable at runtime, so it cannot "
    "be resolved statically; the route keeps the raw target",
    "server_name.regex": "a regular-expression server name names no concrete host; it is kept " "on the route",
    "include.unresolved": "an included file was not part of the import, so whatever it "
    "declares is unknown (supply it in the file set to have it read)",
    "stream": "TCP/UDP proxying has no HTTP operation",
    "scripting-module": "Lua / njs / Perl handlers run arbitrary code; what they route is "
    "not knowable from the configuration",
    "directive.other": "a directive outside the documented subset; it is recorded, not read",
}

#: Directive prefixes of scripting modules (``content_by_lua_block``, ``js_content`` …).
_SCRIPTING_RE = re.compile(r"(_by_lua(_block|_file)?$|^js_|^perl|^lua_)")

#: Handler directives that name a backend.
_PASS_DIRECTIVES = ("proxy_pass", "grpc_pass", "fastcgi_pass", "uwsgi_pass", "scgi_pass")

#: Header names whose values are credential material in a ``*_set_header`` directive.
_SECRET_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key"})

#: Block keywords whose presence (``keyword … {``) marks a text as nginx configuration.
_BLOCK_MARKER_RE = re.compile(
    r"^\s*(http|server|events|stream|upstream|location|map|geo|mail|types)\b[^;{}\n]*\{",
    re.MULTILINE,
)


@dataclass
class NginxDirective:
    """One directive: name, arguments and (for a block directive) its children.

    Attributes:
        name: The directive name.
        args: Its arguments, quotes removed.
        block: Child directives, or ``None`` for a simple directive.
        origin: ``file:line`` where it was declared.
    """

    name: str
    args: List[str]
    block: Optional[List["NginxDirective"]]
    origin: str


# ---------------------------------------------------------------------------------------
# Tokenizer and tree
# ---------------------------------------------------------------------------------------

#: A regex quantifier or ``${var}`` that sits inside an unquoted word.
_INLINE_BRACE_RE = re.compile(r"\{[^\s{};]*\}")


def tokenize_nginx(text: str, *, origin: str) -> List[Tuple[str, str, int]]:
    """Split nginx configuration text into ``(kind, value, line)`` tokens.

    Kinds are ``word``, ``{``, ``}`` and ``;``. Comments are dropped; quotes are removed
    from quoted words. A brace inside an unquoted word (``[0-9]{6}``, ``${var}``) is part
    of the word, as authors write regexes that way even where nginx wants them quoted.

    Args:
        text: The configuration text.
        origin: File label for messages.

    Returns:
        The tokens.

    Raises:
        GatewayConfigParseError: ``INPUT_TRUNCATED`` when the text ends inside a quoted word.
    """
    tokens: List[Tuple[str, str, int]] = []
    index, line, length = 0, 1, len(text)
    while index < length:
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
        elif char.isspace():
            index += 1
        elif char == "#":
            while index < length and text[index] != "\n":
                index += 1
        elif char in "{};":
            tokens.append((char, char, line))
            index += 1
        elif char in "\"'":
            start_line = line
            index += 1
            value: List[str] = []
            while index < length and text[index] != char:
                if text[index] == "\\" and index + 1 < length:
                    value.append(text[index + 1])
                    index += 2
                    continue
                line += text[index] == "\n"
                value.append(text[index])
                index += 1
            if index >= length:
                raise GatewayConfigParseError(
                    f"{origin}: nginx configuration is truncated — a quoted value opened on "
                    f"line {start_line} never closes",
                    code="INPUT_TRUNCATED",
                )
            index += 1
            tokens.append(("word", "".join(value), start_line))
        else:
            start = index
            while index < length and not text[index].isspace() and text[index] not in ";}":
                if text[index] == "{":
                    brace = _INLINE_BRACE_RE.match(text, index)
                    if index > start and brace:
                        index = brace.end()
                        continue
                    break
                index += 1
            tokens.append(("word", text[start:index], line))
    return tokens


def _build_tree(tokens: Sequence[Tuple[str, str, int]], *, origin: str) -> List[NginxDirective]:
    """Assemble tokens into a directive tree.

    Raises:
        GatewayConfigParseError: ``INPUT_TRUNCATED`` when the text ends mid-directive (words
            with no terminating ``;`` or ``{``); ``INPUT_MALFORMED`` for an unbalanced brace
            or a block opened with no directive name.
    """
    root: List[NginxDirective] = []
    stack: List[List[NginxDirective]] = [root]
    pending: List[Tuple[str, int]] = []
    for kind, value, line in tokens:
        if kind == "word":
            pending.append((value, line))
            continue
        if kind == ";":
            if pending:
                stack[-1].append(
                    NginxDirective(pending[0][0], [word for word, _ in pending[1:]], None, f"{origin}:{pending[0][1]}")
                )
            pending = []
        elif kind == "{":
            if not pending:
                raise GatewayConfigParseError(
                    f"{origin}:{line}: a block opens with no directive name", code="INPUT_MALFORMED"
                )
            directive = NginxDirective(
                pending[0][0], [word for word, _ in pending[1:]], [], f"{origin}:{pending[0][1]}"
            )
            stack[-1].append(directive)
            stack.append(directive.block)  # type: ignore[arg-type]
            pending = []
        else:
            if pending:
                raise GatewayConfigParseError(
                    f"{origin}:{line}: directive {pending[0][0]!r} is not terminated with ';'",
                    code="INPUT_MALFORMED",
                )
            if len(stack) == 1:
                raise GatewayConfigParseError(
                    f"{origin}:{line}: unexpected '}}' with no open block", code="INPUT_MALFORMED"
                )
            stack.pop()
    if pending:
        raise GatewayConfigParseError(
            f"{origin}: nginx configuration is truncated — directive {pending[0][0]!r} on line "
            f"{pending[0][1]} has no terminating ';' before the end of the file",
            code="INPUT_TRUNCATED",
        )
    if len(stack) > 1:
        raise GatewayConfigParseError(
            f"{origin}: {len(stack) - 1} block(s) are never closed — a '}}' is missing",
            code="INPUT_MALFORMED",
        )
    return root


def is_nginx(text: str) -> bool:
    """Cheap sniff: a ``server``/``upstream``/``location``… block plus terminated directives."""
    if not text or "\x00" in text or not _BLOCK_MARKER_RE.search(text):
        return False
    if not re.search(r";\s*(#.*)?$", text, re.MULTILINE):
        return False
    return bool(
        re.search(
            r"^\s*(listen|location|proxy_pass|server_name|upstream|server|include|worker_processes|"
            r"worker_connections)\b",
            text,
            re.MULTILINE,
        )
    )


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


@dataclass
class _Upstream:
    """One ``upstream`` block."""

    name: str
    servers: List[str]
    origin: str


@dataclass
class _Server:
    """One http ``server`` block with the carried directives inherited from http."""

    directive: NginxDirective
    inherited: Dict[str, List[List[str]]]
    index: int


@dataclass
class _State:
    """Everything gathered before routes are built."""

    members: Mapping[str, str]
    upstreams: Dict[str, _Upstream] = field(default_factory=dict)
    servers: List[_Server] = field(default_factory=list)
    visited: Set[str] = field(default_factory=set)
    unresolved_includes: int = 0
    limits: LimitCollector = field(default_factory=LimitCollector)
    redactions: int = 0
    read_directives: Set[str] = field(default_factory=set)


def _resolve_include(pattern: str, state: _State) -> List[str]:
    """Member paths an ``include`` pattern names (full path first, then file name)."""
    candidates = sorted(path for path in state.members if fnmatch.fnmatch(path, pattern))
    if not candidates:
        base = pattern.rsplit("/", 1)[-1]
        candidates = sorted(path for path in state.members if fnmatch.fnmatch(path.rsplit("/", 1)[-1], base))
    return candidates


def _declare(name: str, state: _State) -> None:
    """Declare a directive outside the read and carried sets."""
    if name in NGINX_DECLARED_DIRECTIVES:
        state.limits.add(name, NGINX_DECLARED_DIRECTIVES[name])
    elif _SCRIPTING_RE.search(name):
        state.limits.add("scripting-module", NGINX_DECLARED_DIRECTIVES["scripting-module"])
    else:
        state.limits.add(
            f"directive.{name}",
            "outside the documented nginx subset; recorded, not read",
        )


def _carry(directive: NginxDirective, carried: Dict[str, List[List[str]]], state: _State) -> None:
    """Record a carried directive's value at the current level (redacting secret headers)."""
    args = list(directive.args)
    if directive.name.endswith("_set_header") and len(args) >= 2 and args[0].lower() in _SECRET_HEADERS:
        args = [args[0], "***"]
        state.redactions += 1
    carried.setdefault(directive.name, []).append(args)


def _expand(directives: Sequence[NginxDirective], state: _State) -> List[NginxDirective]:
    """Replace every ``include`` (at any depth) with the directives of the files it names.

    Each member is spliced in at most once, so an include cycle or a glob that also matches
    the including file cannot loop.
    """
    out: List[NginxDirective] = []
    for directive in directives:
        if directive.name == "include" and directive.block is None:
            state.read_directives.add("include")
            pattern = directive.args[0] if directive.args else ""
            paths = _resolve_include(pattern, state)
            if not paths:
                state.unresolved_includes += 1
                state.limits.add("include.unresolved", NGINX_DECLARED_DIRECTIVES["include.unresolved"])
                continue
            for path in paths:
                if path in state.visited:
                    continue
                state.visited.add(path)
                out.extend(_expand(_parse_member(state.members[path], path), state))
            continue
        if directive.block is not None:
            directive.block = _expand(directive.block, state)
        out.append(directive)
    return out


def _level(body: Sequence[NginxDirective], state: _State) -> Dict[str, List[List[str]]]:
    """The carried directives one block sets, each with every value it is given there."""
    level: Dict[str, List[List[str]]] = {}
    for directive in body:
        if directive.name in NGINX_CARRIED_DIRECTIVES:
            _carry(directive, level, state)
    return level


def _read_upstream(directive: NginxDirective, state: _State) -> None:
    """Record an ``upstream`` block's name and servers."""
    state.read_directives.add("upstream")
    name = directive.args[0] if directive.args else ""
    servers = [child.args[0] for child in directive.block or [] if child.name == "server" and child.args]
    state.upstreams[name] = _Upstream(name=name, servers=servers, origin=directive.origin)


def _read_http_context(
    directives: Sequence[NginxDirective], state: _State, inherited: Dict[str, List[List[str]]]
) -> None:
    """Read an http context (or a main-level snippet read as one).

    Carried directives set here are inherited by every server below, wherever in the block
    they are written — nginx resolves inheritance by level, not by position.
    """
    carried = {**inherited, **_level(directives, state)}
    for directive in directives:
        name = directive.name
        if name == "server" and directive.block is not None:
            state.servers.append(_Server(directive=directive, inherited=carried, index=len(state.servers)))
        elif name == "upstream" and directive.block is not None:
            continue  # registered by the pre-scan
        elif name == "http" and directive.block is not None:
            state.read_directives.add("http")
            _read_http_context(directive.block, state, carried)
        elif name == "events":
            state.read_directives.add("events")
        elif name == "stream" and directive.block is not None:
            count = sum(1 for child in directive.block if child.name == "server")
            state.limits.add("stream", NGINX_DECLARED_DIRECTIVES["stream"], count=max(count, 1))
        elif name not in NGINX_CARRIED_DIRECTIVES:
            _declare(name, state)


def _parse_member(text: str, origin: str) -> List[NginxDirective]:
    """Tokenize and build the tree of one member file."""
    reject_binary(text, format_label=_LABEL)
    if not _BLOCK_MARKER_RE.search(text) and not re.search(r"^\s*\w+[^\n;{}]*;", text, re.MULTILINE):
        raise GatewayConfigParseError(
            f"{origin}: not an nginx configuration (no directive or block found)", code="FORMAT_MISMATCH"
        )
    return _build_tree(tokenize_nginx(text, origin=origin), origin=origin)


# ---------------------------------------------------------------------------------------
# Servers and locations → routes
# ---------------------------------------------------------------------------------------


@dataclass
class _ServerFacts:
    """What a server block says about every route in it."""

    group: str
    hosts: Tuple[str, ...]
    protocols: Tuple[str, ...]
    host_patterns: Tuple[str, ...]
    ports: Tuple[int, ...]


def _server_facts(server: _Server, used_groups: Set[str], state: _State) -> _ServerFacts:
    """Read ``listen`` and ``server_name`` of a server block."""
    names: List[str] = []
    patterns: List[str] = []
    ports: List[int] = []
    tls = False
    plain = False
    for child in server.directive.block or []:
        if child.name == "listen" and child.args:
            state.read_directives.add("listen")
            _host, _scheme, port = split_address(child.args[0] if ":" in child.args[0] else f"x:{child.args[0]}")
            if port is not None:
                ports.append(port)
            if "ssl" in child.args[1:]:
                tls = True
            else:
                plain = True
        elif child.name == "server_name":
            state.read_directives.add("server_name")
            for name in child.args:
                if name.startswith("~"):
                    patterns.append(name)
                    state.limits.add("server_name.regex", NGINX_DECLARED_DIRECTIVES["server_name.regex"])
                elif name not in ("_", ""):
                    names.append(name.lower())
        elif child.name == "ssl_certificate":
            state.read_directives.add("ssl_certificate")
            tls = True
    label = names[0] if names else "(default server)"
    group = f"{label}:{ports[0]}" if ports else label
    while group in used_groups:
        group = f"{group}#{server.index}"
    used_groups.add(group)
    protocols: Tuple[str, ...] = ("http", "https") if tls and plain else (("https",) if tls else ("http",))
    return _ServerFacts(
        group=group,
        hosts=tuple(sorted(set(names))),
        protocols=protocols,
        host_patterns=tuple(patterns),
        ports=tuple(sorted(set(ports))),
    )


def _location_pattern(args: Sequence[str]) -> Tuple[Optional[GatewayPathPattern], str, bool]:
    """``location`` arguments → (path pattern or None for named, modifier, case-insensitive)."""
    if not args:
        return path_pattern_for("PathPrefix", "/"), "", False
    if args[0].startswith("@"):
        return None, "@", False
    if len(args) >= 2 and args[0] in NGINX_LOCATION_MODIFIERS:
        modifier, value = args[0], args[1]
    elif args[0][:2] in ("~*", "^~") and len(args[0]) > 2:
        modifier, value = args[0][:2], args[0][2:]
    elif args[0][:1] in ("=", "~") and len(args[0]) > 1:
        modifier, value = args[0][:1], args[0][1:]
    else:
        modifier, value = "", args[0]
    path_type = NGINX_LOCATION_MODIFIERS[modifier]
    return path_pattern_for(path_type, value), modifier, modifier == "~*"  # type: ignore[arg-type]


def _backend(target: str, state: _State, route: str) -> Tuple[Optional[GatewayBackend], Dict[str, Any]]:
    """Resolve a ``*_pass`` target to a backend.

    Raises:
        GatewayConfigParseError: ``INPUT_REFERENCE_UNRESOLVED`` for an upstream-shaped name no
            upstream declares, when every include was followed.
    """
    extras: Dict[str, Any] = {"target": target}
    if "$" in target.split("://", 1)[-1].split("/", 1)[0]:
        state.limits.add("proxy_pass.variable", NGINX_DECLARED_DIRECTIVES["proxy_pass.variable"])
        return None, extras
    host, _scheme, port = split_address(target)
    if host.startswith("unix:"):
        return GatewayBackend(name=host), extras
    if host in state.upstreams:
        upstream = state.upstreams[host]
        extras["upstream_servers"] = list(upstream.servers)
        return GatewayBackend(name=host), extras
    upstream_shaped = (
        port is None and "." not in host and host not in ("localhost",) and not re.match(r"^[\d.]+$", host)
    )
    if upstream_shaped and not state.unresolved_includes:
        raise GatewayConfigParseError(
            f"Location {route!r} passes to {host!r}, which no upstream block declares "
            f"(declared: {', '.join(sorted(state.upstreams)) or 'none'})",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    return GatewayBackend(name=host, port=port), extras


def _plugins(effective: Mapping[str, Tuple[str, List[List[str]]]], route: str) -> Tuple[GatewayPlugin, ...]:
    """Effective carried directives as named policy plugins."""
    plugins = []
    for name, (scope, values) in sorted(effective.items()):
        if not values:
            continue
        plugins.append(
            GatewayPlugin(name=name, scope=scope, attached_to=route, config={"values": [" ".join(v) for v in values]})
        )
    return tuple(plugins)


def _auth_hints(effective: Mapping[str, Tuple[str, List[List[str]]]], route: str) -> Tuple[GatewayAuthHint, ...]:
    """Auth hints from ``auth_basic`` / ``auth_request`` in effect on a route."""
    hints = []
    basic = effective.get("auth_basic")
    if basic and basic[1] and basic[1][-1] and basic[1][-1][0] != "off":
        hints.append(GatewayAuthHint(scheme="basic", plugin="auth_basic", scope=basic[0], attached_to=route))
    request = effective.get("auth_request")
    if request and request[1] and request[1][-1] and request[1][-1][0] != "off":
        hints.append(
            GatewayAuthHint(
                scheme=None,
                plugin="auth_request",
                scope=request[0],
                attached_to=route,
                detail={"subrequest": request[1][-1][0]},
            )
        )
    return tuple(hints)


#: Directives inside a location that are read (not carried, not declared).
_LOCATION_READ = frozenset(
    {"location", "limit_except", "internal", "return", "root", "alias", "auth_basic", "auth_request", *_PASS_DIRECTIVES}
)


def _location_routes(
    directive: NginxDirective,
    facts: _ServerFacts,
    inherited: Dict[str, Tuple[str, List[List[str]]]],
    state: _State,
    *,
    nested: bool,
) -> List[GatewayRoute]:
    """Routes for one ``location`` (and, recursively, its nested locations)."""
    state.read_directives.add("location")
    pattern, modifier, case_insensitive = _location_pattern(directive.args)
    body = directive.block or []
    effective = dict(inherited)
    effective.update({name: ("route", values) for name, values in _level(body, state).items()})
    for child in body:
        if child.name in ("auth_basic", "auth_request"):
            state.read_directives.add(child.name)
            effective[child.name] = ("route", [child.args])
    raw_path = " ".join(directive.args)
    # Space-free, so a colliding operation key's ``#route`` suffix stays one token.
    route_name = f"{facts.group}@{raw_path.replace(' ', '')}"
    routes: List[GatewayRoute] = []
    if nested:
        state.limits.add("location.nested", NGINX_DECLARED_DIRECTIVES["location.nested"])
    internal = any(child.name == "internal" for child in body)
    for child in body:
        if child.name == "location" and child.block is not None:
            routes.extend(_location_routes(child, facts, effective, state, nested=True))
        elif child.name == "if":
            _declare("if", state)
        elif child.name not in _LOCATION_READ and child.name not in NGINX_CARRIED_DIRECTIVES:
            _declare(child.name, state)
    if pattern is None:
        state.limits.add("location.named", NGINX_DECLARED_DIRECTIVES["location.named"])
        return routes
    if internal:
        state.read_directives.add("internal")
        state.limits.add("location.internal", NGINX_DECLARED_DIRECTIVES["location.internal"])
        return routes

    extras: Dict[str, Any] = {"server_block": facts.group, "location": raw_path}
    if facts.ports:
        extras["listen_ports"] = list(facts.ports)
    if facts.host_patterns:
        extras["host_patterns"] = list(facts.host_patterns)
    if case_insensitive:
        extras["case_insensitive"] = True
    if modifier == "^~":
        extras["stops_regex_evaluation"] = True
    backends: List[GatewayBackend] = []
    methods: List[Optional[str]] = [None]
    for child in body:
        if child.name in _PASS_DIRECTIVES and child.args:
            state.read_directives.add(child.name)
            backend, backend_extras = _backend(child.args[0], state, route_name)
            extras["handler"] = {"directive": child.name, **backend_extras}
            if backend is not None:
                backends.append(backend)
        elif child.name == "return" and child.args:
            state.read_directives.add("return")
            extras["handler"] = {
                "directive": "return",
                "status": child.args[0],
                **({"value": child.args[1]} if len(child.args) > 1 else {}),
            }
        elif child.name in ("root", "alias") and child.args:
            state.read_directives.add(child.name)
            extras["handler"] = {"directive": child.name, "path": child.args[0]}
        elif child.name == "limit_except" and child.args:
            state.read_directives.add("limit_except")
            listed = [arg.upper() for arg in child.args]
            if "GET" in listed and "HEAD" not in listed:
                listed.append("HEAD")
            denies_rest = any(grand.name == "deny" and grand.args == ["all"] for grand in child.block or [])
            extras["limit_except"] = sorted(listed)
            if denies_rest:
                methods = sorted(listed)  # type: ignore[assignment]
    matches = tuple(GatewayMatch(path=pattern, method=method) for method in methods)
    routes.insert(
        0,
        GatewayRoute(
            name=route_name,
            service_name=facts.group,
            hosts=facts.hosts,
            matches=matches,
            protocols=facts.protocols,
            auth=_auth_hints(effective, route_name),
            plugins=_plugins({k: v for k, v in effective.items() if k in NGINX_CARRIED_DIRECTIVES}, route_name),
            backends=tuple(backends),
            source_location=directive.origin,
            extras=extras,
        ),
    )
    return routes


def _server_routes(server: _Server, used_groups: Set[str], state: _State) -> List[GatewayRoute]:
    """Routes for one http server block."""
    state.read_directives.add("server")
    facts = _server_facts(server, used_groups, state)
    body = server.directive.block or []
    effective: Dict[str, Tuple[str, List[List[str]]]] = {
        name: ("global", values) for name, values in server.inherited.items() if values
    }
    effective.update({name: ("service", values) for name, values in _level(body, state).items()})
    for child in body:
        if child.name in ("auth_basic", "auth_request"):
            state.read_directives.add(child.name)
            effective[child.name] = ("service", [child.args])
    routes: List[GatewayRoute] = []
    server_return: Optional[NginxDirective] = None
    for child in body:
        if child.name == "location" and child.block is not None:
            routes.extend(_location_routes(child, facts, effective, state, nested=False))
        elif child.name == "return":
            server_return = child
        elif child.name in ("listen", "server_name", "ssl_certificate", "auth_basic", "auth_request"):
            continue
        elif child.name not in NGINX_CARRIED_DIRECTIVES:
            _declare(child.name, state)
    if server_return is not None and server_return.args:
        state.read_directives.add("return")
        route_name = f"{facts.group}@return"
        handler: Dict[str, Any] = {"directive": "return", "status": server_return.args[0]}
        if len(server_return.args) > 1:
            handler["value"] = server_return.args[1]
        routes.insert(
            0,
            GatewayRoute(
                name=route_name,
                service_name=facts.group,
                hosts=facts.hosts,
                matches=(GatewayMatch(path=path_pattern_for("PathPrefix", "/")),),
                protocols=facts.protocols,
                plugins=_plugins({k: v for k, v in effective.items() if k in NGINX_CARRIED_DIRECTIVES}, route_name),
                source_location=server_return.origin,
                extras={"server_block": facts.group, "handler": handler, "server_level_return": True},
            ),
        )
    return routes


def _document_from(state: _State, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Build routes from the gathered servers and assemble the document."""
    if not state.servers:
        raise GatewayConfigParseError(
            "The nginx configuration declares no http server block — there is no listener, "
            "host or location to infer a route from",
            code="INPUT_SEMANTIC_INVALID",
        )
    used_groups: Set[str] = set()
    routes: List[GatewayRoute] = []
    for server in state.servers:
        routes.extend(_server_routes(server, used_groups, state))
    if not routes:
        raise GatewayConfigParseError(
            "No server block exposes a location — every location is named or internal",
            code="INPUT_SEMANTIC_INVALID",
        )
    services = tuple(
        GatewayServiceDef(name=name, extras={"upstream_servers": list(upstream.servers)})
        for name, upstream in sorted(state.upstreams.items())
    )
    groups = sorted({route.service_name for route in routes if route.service_name})
    return GatewayConfigDocument(
        flavor=NGINX_FLAVOR,
        title=title or source_label or (groups[0] if groups else "nginx configuration"),
        services=services,
        routes=tuple(routes),
        ignored=state.limits.as_ignored(),
        credential_redactions=state.redactions,
        source_label=source_label,
        raw={
            "flavor": NGINX_FLAVOR,
            "server_blocks": groups,
            "upstreams": sorted(state.upstreams),
            "route_names": sorted(route.name for route in routes),
            "hostnames": sorted({host for route in routes for host in route.hosts}),
            "directives_read": sorted(state.read_directives),
            "files_read": sorted(state.visited),
        },
    )


def _collect_upstreams_first(directives: Sequence[NginxDirective], state: _State) -> None:
    """Pre-scan: register every http-level upstream so ``proxy_pass`` can see later ones."""
    for directive in directives:
        if directive.name == "upstream" and directive.block is not None:
            _read_upstream(directive, state)
        elif directive.name == "http" and directive.block is not None:
            _collect_upstreams_first(directive.block, state)


def _parse(state: _State, root_path: str, extra_roots: Sequence[str]) -> None:
    """Read the root (following includes), then any member no include reached."""
    for path in [root_path, *extra_roots]:
        if path in state.visited:
            continue
        state.visited.add(path)
        tree = _expand(_parse_member(state.members[path], path), state)
        _collect_upstreams_first(tree, state)
        _read_http_context(tree, state, {})


def parse_nginx(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse one nginx configuration file through the documented subset.

    Args:
        text: The configuration text.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="nginx"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_TRUNCATED`` for a file that ends mid-directive, ``INPUT_MALFORMED`` for
            unbalanced braces, ``FORMAT_MISMATCH`` for text with no nginx structure,
            ``INPUT_SEMANTIC_INVALID`` when no http server exposes a location, and
            ``INPUT_REFERENCE_UNRESOLVED`` for a ``proxy_pass`` to an undeclared upstream.
    """
    label = source_label or "nginx.conf"
    state = _State(members={label: text})
    _parse(state, label, ())
    return _document_from(state, title=None, source_label=source_label)


def parse_nginx_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse an nginx configuration tree: the root, its includes, and any other member.

    ``include`` patterns are matched against member paths, then against member file names
    (an archive rarely preserves ``/etc/nginx``). Each file is read once.

    Args:
        members: Member path → text.
        root: The root member (``nginx.conf``), read first.
        source_label: Label for the merged document.

    Returns:
        The merged document.

    Raises:
        GatewayConfigParseError: As :func:`parse_nginx`.
    """
    order = ordered_members(members, root)
    state = _State(members=members)
    _parse(state, order[0], order[1:])
    return _document_from(state, title=source_label, source_label=source_label or order[0])
