"""Parser for HAProxy configuration — FMT-7.5 (#5459).

HAProxy expresses routing as **ACL + ``use_backend``**: a ``frontend`` (or ``listen``)
section binds a listener, names conditions with ``acl``, and chooses a ``backend`` with
``use_backend <name> if <conditions>``; ``default_backend`` takes what nothing else
matched. This module reads that into the flavor-neutral
:class:`~app.gateway_config_model.GatewayConfigDocument`:

* Each ``use_backend`` rule becomes a route; its condition is put into disjunctive normal
  form (``||`` / ``or`` alternatives of space-separated terms) and each alternative is
  one match condition. ``path`` → exact, ``path_beg`` / ``path_dir`` → prefix,
  ``path_reg`` → regular expression (through the shared Gateway API path-type table),
  ``method`` → methods, ``hdr(host)`` → server hosts, ``hdr(x)`` / ``req.hdr(x)`` →
  header matches, ``urlp(x)`` → query matches. An ACL with several patterns is an OR.
* ``default_backend`` is a catch-all route; ``http-request return … if <path ACL>`` is a
  route answered by HAProxy itself.
* ``bind … ssl`` decides the scheme; ``mode tcp`` (set on the section or inherited from
  the nearest preceding ``defaults``) means the section carries no HTTP operation.
* A ``use_backend`` whose target is computed (``%[…map_str(file,default)]``) is resolved
  through the map file when the import supplies it — one route per map entry, matched on
  the header the expression reads — and declared otherwise.

What does not reduce to that is declared on the ledger with its reason: negated terms,
connection / TLS / rate-counter / body fetches (``src``, ``ssl_*``, ``sc_*``,
``req.body_size``), Lua-backed ACLs, ``path_end`` / ``path_sub`` (no canonical path form),
and every directive outside the subset. A ``use_backend`` / ``default_backend`` naming a
backend the configuration does not declare is ``INPUT_REFERENCE_UNRESOLVED``.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .gateway_config_model import (
    GatewayBackend,
    GatewayConfigDocument,
    GatewayConfigParseError,
    GatewayMatch,
    GatewayPathPattern,
    GatewayPlugin,
    GatewayRoute,
    GatewayServiceDef,
)
from .gateway_match import path_pattern, render_match_value
from .mesh_route_common import LimitCollector, reject_binary
from .proxy_route_common import ordered_members, split_address

__all__ = [
    "HAPROXY_FLAVOR",
    "HAPROXY_SECTIONS",
    "HAPROXY_PATH_FETCHES",
    "HAPROXY_READ_CONSTRUCTS",
    "HAPROXY_DECLARED_CONSTRUCTS",
    "is_haproxy",
    "parse_haproxy",
    "parse_haproxy_fileset",
]

#: Flavor key stamped on the parsed document.
HAPROXY_FLAVOR = "haproxy"

#: Human name used in messages.
_LABEL = "HAProxy"

#: Every section keyword HAProxy accepts; a column-0 word outside this set is an error.
HAPROXY_SECTIONS = frozenset(
    {
        "global",
        "defaults",
        "frontend",
        "backend",
        "listen",
        "peers",
        "resolvers",
        "userlist",
        "mailers",
        "program",
        "http-errors",
        "ring",
        "cache",
        "crt-store",
        "traces",
        "log-forward",
        "fcgi-app",
    }
)

#: Sections that carry routing.
_PROXY_SECTIONS = frozenset({"frontend", "backend", "listen", "defaults"})

#: Path fetches → Gateway API path type.
HAPROXY_PATH_FETCHES: Dict[str, str] = {
    "path": "Exact",
    "path_beg": "PathPrefix",
    "path_dir": "PathPrefix",
    "path_reg": "RegularExpression",
}

#: Path fetches with no canonical path form, declared when used.
_UNMODELLED_PATH_FETCHES = frozenset({"path_end", "path_sub", "path_len", "path_dom", "url", "url_beg", "url_reg"})

#: Fetch prefixes with no HTTP-operation analogue → declared-limit construct name.
_CONDITION_FETCHES: Tuple[Tuple[str, str], ...] = (
    ("lua.", "acl.lua"),
    ("src", "acl.connection"),
    ("dst", "acl.connection"),
    ("ssl_", "acl.tls"),
    ("req.ssl_", "acl.tls"),
    ("req_ssl_", "acl.tls"),
    ("sc_", "acl.rate-counter"),
    ("sc0_", "acl.rate-counter"),
    ("sc1_", "acl.rate-counter"),
    ("sc2_", "acl.rate-counter"),
    ("nbsrv", "acl.backend-state"),
    ("req.body", "acl.body"),
    ("req.ver", "acl.http-version"),
)

#: Why each condition class is declared.
_CONDITION_REASONS: Dict[str, str] = {
    "acl.lua": "a Lua-backed fetch runs arbitrary code; what it matches is not knowable from "
    "the configuration, so the parser declines to interpret it",
    "acl.connection": "the condition matches on the client or listener address, which has no "
    "canonical parameter form",
    "acl.tls": "the condition matches on TLS/SNI properties of the connection, not on the HTTP " "request",
    "acl.rate-counter": "the condition reads a stick-table rate counter evaluated at runtime",
    "acl.backend-state": "the condition reads live backend state (servers up), evaluated at " "runtime",
    "acl.body": "the condition inspects the request body, which this routing import does not " "model",
    "acl.http-version": "the condition matches on the HTTP protocol version",
    "acl.negation": "a negated condition narrows the route by what a request must NOT match, "
    "which has no canonical parameter form; it is kept on the route as a condition",
    "acl.path-suffix-or-substring": "path_end / path_sub (and url-based) matches have no "
    "canonical path form; the route keeps them as conditions and matches every path",
    "acl.unknown-fetch": "a fetch outside the vocabulary this parser reads; it is kept on the " "route as a condition",
    "acl.map-file": "the ACL's patterns are read from a map/pattern file at runtime; supply the "
    "file in the import to have them read",
    "use_backend.dynamic": "the backend is computed at runtime from a fetch expression; supply "
    "the map file it reads to have each entry imported as a route",
    "use_backend.unless": "an `unless` rule routes everything that does NOT match its "
    "condition; it is imported as a catch-all route carrying the condition",
    "mode.tcp": "a section in TCP mode routes connections, not HTTP requests — there is no "
    "canonical HTTP operation for it",
    "global": "process-level settings (logging, limits, TLS defaults, the stats socket) "
    "configure HAProxy itself, not the routes it serves",
    "directive.other": "a directive outside the documented HAProxy subset; recorded, not read",
}

#: Directives read in a proxy section.
_READ_DIRECTIVES = frozenset({"mode", "bind", "acl", "use_backend", "default_backend", "server", "balance", "stats"})

#: ``http-request`` / ``http-response`` actions (and others) kept as policy plugins.
_CARRIED_DIRECTIVES = frozenset(
    {
        "http-request",
        "http-response",
        "http-check",
        "option",
        "timeout",
        "retries",
        "cookie",
        "stick-table",
        "hash-type",
        "errorfile",
        "tcp-request",
        "compression",
    }
)

#: Construct vocabulary for the capability registry.
HAPROXY_READ_CONSTRUCTS: Tuple[str, ...] = (
    "section.frontend",
    "section.backend",
    "section.listen",
    "section.defaults",
    "defaults.inheritance",
    "bind",
    "bind.ssl",
    "mode",
    "acl",
    "acl.path",
    "acl.path_beg",
    "acl.path_dir",
    "acl.path_reg",
    "acl.method",
    "acl.hdr-host",
    "acl.hdr",
    "acl.urlp",
    "acl.anonymous",
    "use_backend",
    "use_backend.map-file",
    "default_backend",
    "http-request.return",
    "server",
    "map-file-fileset",
)

#: Constructs declared on the ledger when a document uses them.
HAPROXY_DECLARED_CONSTRUCTS: Tuple[str, ...] = tuple(sorted(_CONDITION_REASONS))


# ---------------------------------------------------------------------------------------
# Lines and sections
# ---------------------------------------------------------------------------------------


@dataclass
class _Line:
    """One logical directive line (continuations joined)."""

    words: List[str]
    origin: str
    indented: bool


@dataclass
class _Section:
    """One section: keyword, name and its directive lines."""

    keyword: str
    name: str
    lines: List[_Line]
    origin: str
    defaults_name: Optional[str] = None


def _split_words(text: str) -> List[str]:
    """Split a directive line into words, honoring quotes and ``{ … }`` anonymous ACLs."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=False)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        return list(lexer)
    except ValueError:
        return text.split()


def _logical_lines(text: str, origin: str) -> List[_Line]:
    """Comment-stripped, continuation-joined lines.

    Raises:
        GatewayConfigParseError: ``INPUT_TRUNCATED`` when the file ends inside a line
            continuation or an open quote.
    """
    lines: List[_Line] = []
    buffer = ""
    start = 0
    indented = False
    raw_lines = text.splitlines()
    for number, raw in enumerate(raw_lines, start=1):
        if not buffer:
            start = number
            indented = raw[:1].isspace()
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        buffer += stripped
        content = buffer.strip()
        buffer = ""
        if not content or content.startswith("#"):
            continue
        if content.count("'") % 2 and number == len(raw_lines):
            raise GatewayConfigParseError(
                f"{origin}:{start}: {_LABEL} configuration is truncated — a quoted value never "
                "closes before the end of the file",
                code="INPUT_TRUNCATED",
            )
        lines.append(_Line(words=_split_words(content), origin=f"{origin}:{start}", indented=indented))
    if buffer:
        raise GatewayConfigParseError(
            f"{origin}:{start}: {_LABEL} configuration is truncated — it ends inside a line " "continuation",
            code="INPUT_TRUNCATED",
        )
    return [line for line in lines if line.words]


def _sections(lines: Sequence[_Line], origin: str) -> List[_Section]:
    """Group lines into sections.

    Raises:
        GatewayConfigParseError: ``FORMAT_MISMATCH`` when no section keyword appears at all;
            ``INPUT_MALFORMED`` for a column-0 word that is not a section keyword, or a
            directive before the first section.
    """
    if not any(not line.indented and line.words[0] in HAPROXY_SECTIONS for line in lines):
        raise GatewayConfigParseError(
            f"{origin}: not an HAProxy configuration (no global/defaults/frontend/backend/listen " "section)",
            code="FORMAT_MISMATCH",
        )
    sections: List[_Section] = []
    for line in lines:
        keyword = line.words[0]
        if not line.indented:
            if keyword not in HAPROXY_SECTIONS:
                raise GatewayConfigParseError(
                    f"{line.origin}: unknown section keyword {keyword!r} (expected one of "
                    "global, defaults, frontend, backend, listen, …)",
                    code="INPUT_MALFORMED",
                )
            name = line.words[1] if len(line.words) > 1 else ""
            sections.append(_Section(keyword=keyword, name=name, lines=[], origin=line.origin))
            continue
        if not sections:
            raise GatewayConfigParseError(
                f"{line.origin}: directive {keyword!r} appears before any section",
                code="INPUT_MALFORMED",
            )
        sections[-1].lines.append(line)
    return sections


def is_haproxy(text: str) -> bool:
    """Cheap sniff: a proxy section keyword at column 0 plus an indented proxy directive."""
    if not text or "\x00" in text:
        return False
    if not re.search(r"^(frontend|backend|listen)\s+\S+", text, re.MULTILINE):
        return False
    return bool(re.search(r"^\s+(bind|acl|use_backend|default_backend|server|mode)\s", text, re.MULTILINE))


# ---------------------------------------------------------------------------------------
# ACLs and conditions
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Acl:
    """One named ACL (several ``acl`` lines with one name are an OR)."""

    fetch: str
    flags: Tuple[str, ...]
    patterns: Tuple[str, ...]
    pattern_files: Tuple[str, ...]


@dataclass
class _Term:
    """One reduced condition term."""

    paths: List[GatewayPathPattern] = field(default_factory=list)
    methods: List[str] = field(default_factory=list)
    hosts: List[str] = field(default_factory=list)
    headers: List[Tuple[str, str]] = field(default_factory=list)
    query: List[Tuple[str, str]] = field(default_factory=list)
    conditions: List[str] = field(default_factory=list)


#: ``-m`` match method → operator of the shared vocabulary (:data:`app.gateway_match.STRING_MATCH_OPERATORS`).
_MATCH_OPERATORS = {"beg": "prefix", "end": "suffix", "sub": "contains", "reg": "regex", "str": "exact"}


def _parse_acl(words: Sequence[str]) -> Tuple[str, _Acl]:
    """``acl <name> <fetch> [flags] <patterns>`` → (name, ACL)."""
    name = words[1] if len(words) > 1 else ""
    fetch = words[2] if len(words) > 2 else ""
    flags: List[str] = []
    patterns: List[str] = []
    files: List[str] = []
    rest = list(words[3:])
    index = 0
    while index < len(rest):
        word = rest[index]
        if word in ("-f", "-M") and index + 1 < len(rest):
            files.append(rest[index + 1])
            index += 2
            continue
        if word == "-m" and index + 1 < len(rest):
            flags.append(f"-m {rest[index + 1]}")
            index += 2
            continue
        if word.startswith("-") and len(word) > 1 and not patterns and word not in ("--",):
            flags.append(word)
            index += 1
            continue
        patterns.append(word)
        index += 1
    return name, _Acl(fetch=fetch, flags=tuple(flags), patterns=tuple(patterns), pattern_files=tuple(files))


def _fetch_param(fetch: str) -> Tuple[str, Optional[str]]:
    """``req.hdr(x-tenant),lower`` → (``req.hdr``, ``x-tenant``)."""
    base = fetch.split(",", 1)[0]
    match = re.match(r"^([A-Za-z0-9_.]+)\(([^)]*)\)$", base)
    if match:
        return match.group(1), match.group(2).split(",", 1)[0] or None
    return base, None


def _operator(acl: _Acl) -> str:
    """The rendered match operator of an ACL (``prefix`` for ``-m beg``)."""
    for flag in acl.flags:
        if flag.startswith("-m "):
            return _MATCH_OPERATORS.get(flag[3:], "exact")
    return ""


def _reduce_acl(acl: _Acl, rendered: str, state: "_State") -> List[_Term]:
    """An ACL → the alternatives it admits (one per pattern for path/method/host ACLs)."""
    fetch, param = _fetch_param(acl.fetch)
    if fetch in HAPROXY_PATH_FETCHES:
        if not acl.patterns:
            return [_Term(conditions=[rendered])]
        terms = []
        for pattern in acl.patterns:
            term = _Term(paths=[path_pattern(HAPROXY_PATH_FETCHES[fetch], pattern)])
            if "-i" in acl.flags:
                term.conditions.append("case-insensitive path match")
            terms.append(term)
        return terms
    if fetch == "method":
        return [_Term(methods=[pattern.upper()]) for pattern in acl.patterns] or [_Term(conditions=[rendered])]
    if fetch in ("hdr", "req.hdr", "hdr_beg", "hdr_end", "hdr_sub", "hdr_reg", "req.fhdr", "hdr_dom") and param:
        if param.lower() == "host" and not acl.pattern_files and fetch in ("hdr", "req.hdr", "req.fhdr"):
            return [_Term(hosts=[pattern.lower()]) for pattern in acl.patterns] or [_Term(conditions=[rendered])]
        if acl.pattern_files:
            if param.lower() == "host":
                hosts = [host for file in acl.pattern_files for host in state.map_keys(file)]
                if hosts:
                    return [_Term(hosts=[host]) for host in hosts]
            state.limits.add("acl.map-file", _CONDITION_REASONS["acl.map-file"])
            return [_Term(conditions=[rendered])]
        operator = _operator(acl) or {
            "hdr_beg": "prefix",
            "hdr_end": "suffix",
            "hdr_sub": "contains",
            "hdr_reg": "regex",
        }.get(fetch, "")
        if "-m found" in acl.flags:
            return [_Term(headers=[(param, "")])]
        values = acl.patterns or ("",)
        return [_Term(headers=[(param, render_match_value(operator or "exact", value))]) for value in values]
    if fetch in ("urlp", "url_param") and param:
        values = acl.patterns or ("",)
        return [_Term(query=[(param, value)]) for value in values]
    if fetch in _UNMODELLED_PATH_FETCHES:
        state.limits.add("acl.path-suffix-or-substring", _CONDITION_REASONS["acl.path-suffix-or-substring"])
        return [_Term(conditions=[rendered])]
    for prefix, construct in _CONDITION_FETCHES:
        if acl.fetch.startswith(prefix):
            state.limits.add(construct, _CONDITION_REASONS[construct])
            return [_Term(conditions=[rendered])]
    state.limits.add("acl.unknown-fetch", _CONDITION_REASONS["acl.unknown-fetch"])
    return [_Term(conditions=[rendered])]


def _merge(left: _Term, right: _Term) -> _Term:
    """AND two terms."""
    return _Term(
        paths=left.paths + right.paths,
        methods=left.methods + right.methods,
        hosts=left.hosts + right.hosts,
        headers=left.headers + right.headers,
        query=left.query + right.query,
        conditions=left.conditions + right.conditions,
    )


def _condition_words(words: Sequence[str]) -> List[List[str]]:
    """Split condition words on ``||`` / ``or`` into alternatives (``{ … }`` kept whole)."""
    alternatives: List[List[str]] = [[]]
    depth = 0
    current: List[str] = []
    for word in words:
        if word == "{":
            depth += 1
            current.append(word)
            continue
        if word == "}":
            depth -= 1
            current.append(word)
            if depth == 0:
                alternatives[-1].append(" ".join(current))
                current = []
            continue
        if depth:
            current.append(word)
            continue
        if word in ("||", "or"):
            alternatives.append([])
            continue
        alternatives[-1].append(word)
    return [alternative for alternative in alternatives if alternative]


def _reduce_condition(words: Sequence[str], acls: Mapping[str, List[_Acl]], state: "_State") -> List[_Term]:
    """A condition (``is_api !internal { ssl_fc }``) → alternatives in DNF."""
    result: List[_Term] = []
    for alternative in _condition_words(words):
        terms = [_Term()]
        for word in alternative:
            negated = word.startswith("!")
            body = word[1:] if negated else word
            if negated:
                state.limits.add("acl.negation", _CONDITION_REASONS["acl.negation"])
                terms = [_merge(term, _Term(conditions=[word])) for term in terms]
                continue
            if body.startswith("{") and body.endswith("}"):
                inner = _split_words(body[1:-1].strip())
                options = _reduce_acl(_parse_acl(["acl", "(anonymous)", *inner])[1], word, state)
            elif body in acls:
                options = []
                for acl in acls[body]:
                    options.extend(_reduce_acl(acl, body, state))
            else:
                raise GatewayConfigParseError(
                    f"Condition references ACL {body!r}, which the section does not declare",
                    code="INPUT_REFERENCE_UNRESOLVED",
                )
            terms = [_merge(term, option) for term in terms for option in options][:64]
        result.extend(terms)
    return result


def _matches(terms: Sequence[_Term]) -> Tuple[Tuple[GatewayMatch, ...], Set[str], List[str]]:
    """Reduced terms → (match conditions, hosts, unmodelled conditions)."""
    matches: List[GatewayMatch] = []
    hosts: Set[str] = set()
    conditions: List[str] = []
    for term in terms:
        hosts.update(term.hosts)
        for condition in term.conditions:
            if condition not in conditions:
                conditions.append(condition)
        path = term.paths[0] if term.paths else path_pattern("PathPrefix", "/")
        for extra in term.paths[1:]:
            conditions.append(f"also path {extra.kind} {extra.raw}")
        for method in term.methods or [None]:
            match = GatewayMatch(path=path, method=method, headers=tuple(term.headers), query=tuple(term.query))
            if match not in matches:
                matches.append(match)
    return tuple(matches), hosts, conditions


# ---------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------


@dataclass
class _State:
    """Everything gathered before routes are built."""

    members: Mapping[str, str]
    sections: List[_Section] = field(default_factory=list)
    limits: LimitCollector = field(default_factory=LimitCollector)
    maps_read: Set[str] = field(default_factory=set)

    def map_lines(self, path: str) -> Optional[List[List[str]]]:
        """The entries of a map/pattern file supplied in the import, by path or file name."""
        name = path.rsplit("/", 1)[-1]
        for member, text in sorted(self.members.items()):
            if member == path or member.rsplit("/", 1)[-1] == name:
                self.maps_read.add(member)
                rows = []
                for line in text.splitlines():
                    stripped = line.split("#", 1)[0].strip()
                    if stripped:
                        rows.append(stripped.split())
                return rows
        return None

    def map_keys(self, path: str) -> List[str]:
        """First column of a supplied map file (empty when not supplied)."""
        rows = self.map_lines(path)
        return [row[0].lower() for row in rows or []]


_DYNAMIC_BACKEND_RE = re.compile(
    r"^%\[(?P<fetch>[A-Za-z0-9_.]+\([^)]*\))(?:,(?:lower|upper))*,map(?:_str|_beg|_reg)?\("
    r"(?P<file>[^,)]+)(?:,(?P<default>[^)]+))?\)\]$"
)


def _section_mode(section: _Section, defaults: Mapping[str, Dict[str, str]]) -> str:
    """The section's mode: its own, else the one its ``defaults`` sets, else ``tcp``.

    HAProxy's built-in default mode is ``tcp``, so a section that sets nothing and
    inherits nothing is TCP.
    """
    for line in section.lines:
        if line.words[0] == "mode" and len(line.words) > 1:
            return line.words[1]
    inherited = defaults.get(section.defaults_name or "", {})
    return inherited.get("mode", "tcp")


def _carried_plugins(section: _Section, scope: str, attached: str) -> List[GatewayPlugin]:
    """Policy directives of a section as named plugins (``http-request deny`` …)."""
    grouped: Dict[str, List[str]] = {}
    for line in section.lines:
        keyword = line.words[0]
        if keyword not in _CARRIED_DIRECTIVES:
            continue
        name = (
            f"{keyword} {line.words[1]}"
            if keyword in ("http-request", "http-response", "tcp-request") and len(line.words) > 1
            else keyword
        )
        if name == "http-request return":
            continue
        grouped.setdefault(name, []).append(" ".join(line.words[1:]))
    return [
        GatewayPlugin(name=name, scope=scope, attached_to=attached, config={"values": values})
        for name, values in sorted(grouped.items())
    ]


def _declare_unread(section: _Section, state: _State) -> None:
    """Declare the directives of a proxy section outside the read and carried sets."""
    for line in section.lines:
        keyword = line.words[0]
        if keyword in _READ_DIRECTIVES or keyword in _CARRIED_DIRECTIVES:
            continue
        state.limits.add(f"directive.{keyword}", _CONDITION_REASONS["directive.other"])


def _binds(section: _Section) -> Tuple[List[int], bool, bool]:
    """``bind`` lines → (ports, any TLS, any plain)."""
    ports: List[int] = []
    tls = plain = False
    for line in section.lines:
        if line.words[0] != "bind" or len(line.words) < 2:
            continue
        for address in line.words[1].split(","):
            _host, _scheme, port = split_address(address if address.count(":") else f"x:{address}")
            if port is not None:
                ports.append(port)
        if "ssl" in line.words[2:]:
            tls = True
        else:
            plain = True
    return ports, tls, plain


def _backends_of(state: _State) -> Dict[str, _Section]:
    """Declared backend (and listen) sections by name."""
    return {section.name: section for section in state.sections if section.keyword in ("backend", "listen")}


def _check_backend(name: str, rule: str, backends: Mapping[str, _Section]) -> None:
    """Refuse a rule naming a backend the configuration does not declare."""
    if name not in backends:
        raise GatewayConfigParseError(
            f"{rule} names backend {name!r}, which the configuration does not declare "
            f"(declared: {', '.join(sorted(backends)) or 'none'})",
            code="INPUT_REFERENCE_UNRESOLVED",
        )


def _backend_ref(name: str, backends: Mapping[str, _Section]) -> GatewayBackend:
    """A backend name as a gateway backend (first server's port when declared)."""
    section = backends.get(name)
    port = None
    if section is not None:
        for line in section.lines:
            if line.words[0] == "server" and len(line.words) > 2:
                port = split_address(line.words[2])[2]
                break
    return GatewayBackend(name=name, port=port)


def _frontend_routes(
    section: _Section,
    state: _State,
    defaults: Mapping[str, Dict[str, str]],
) -> List[GatewayRoute]:
    """Routes for one frontend / listen section."""
    group = f"{section.keyword} {section.name}"
    # Proxy names are unique across frontend / listen / backend, so the bare name is a
    # space-free route-name prefix (operation-key suffixes stay one token).
    prefix = section.name
    if _section_mode(section, defaults) != "http":
        state.limits.add("mode.tcp", _CONDITION_REASONS["mode.tcp"])
        return []
    backends = _backends_of(state)
    acls: Dict[str, List[_Acl]] = {}
    for line in section.lines:
        if line.words[0] == "acl" and len(line.words) >= 3:
            name, acl = _parse_acl(line.words)
            acls.setdefault(name, []).append(acl)
    ports, tls, plain = _binds(section)
    protocols: Tuple[str, ...] = ("http", "https") if tls and plain else (("https",) if tls else ("http",))
    plugins = tuple(_carried_plugins(section, "service", group))
    _declare_unread(section, state)
    base_extras: Dict[str, Any] = {"section": group}
    if ports:
        base_extras["bind_ports"] = sorted(set(ports))

    routes: List[GatewayRoute] = []

    def add(
        name: str, terms: List[_Term], backend: Optional[GatewayBackend], origin: str, extra: Dict[str, Any]
    ) -> None:
        matches, hosts, conditions = _matches(terms)
        extras = {**base_extras, **extra}
        if conditions:
            extras["unmodelled_conditions"] = sorted(conditions)
        routes.append(
            GatewayRoute(
                name=name,
                service_name=group,
                hosts=tuple(sorted(hosts)),
                matches=matches,
                protocols=protocols,
                plugins=plugins,
                backends=(backend,) if backend is not None else (),
                source_location=origin,
                extras=extras,
            )
        )

    for index, line in enumerate(section.lines):
        words = line.words
        if (
            words[0] == "http-request"
            and len(words) > 1
            and words[1] == "return"
            and ("if" in words or "unless" in words)
        ):
            keyword = "if" if "if" in words else "unless"
            condition = words[words.index(keyword) + 1 :]
            status = words[words.index("status") + 1] if "status" in words[:-1] else None
            terms = _reduce_condition(condition, acls, state)
            if keyword == "unless" or not any(term.paths for term in terms):
                continue
            add(
                f"{prefix}#return-{index}",
                [term for term in terms if term.paths],
                None,
                line.origin,
                {"handler": {"directive": "http-request return", **({"status": status} if status else {})}},
            )
        elif words[0] == "use_backend" and len(words) > 1:
            target = words[1]
            condition: List[str] = []
            keyword = None
            if len(words) > 3 and words[2] in ("if", "unless"):
                keyword, condition = words[2], words[3:]
            dynamic = _DYNAMIC_BACKEND_RE.match(target)
            if target.startswith("%["):
                routes.extend(
                    _dynamic_routes(
                        section, group, target, dynamic, line, state, backends, base_extras, protocols, plugins
                    )
                )
                continue
            _check_backend(target, f"{line.origin}: use_backend", backends)
            if keyword == "unless":
                state.limits.add("use_backend.unless", _CONDITION_REASONS["use_backend.unless"])
                terms = [_Term(conditions=[f"unless {' '.join(condition)}"])]
            elif condition:
                terms = _reduce_condition(condition, acls, state)
            else:
                terms = [_Term()]
            add(f"{prefix}#use_backend-{target}-{index}", terms, _backend_ref(target, backends), line.origin, {})
        elif words[0] == "default_backend" and len(words) > 1:
            _check_backend(words[1], f"{line.origin}: default_backend", backends)
            add(f"{prefix}#default", [_Term()], _backend_ref(words[1], backends), line.origin, {"default_route": True})
    if section.keyword == "listen" and not any(route.extras.get("default_route") for route in routes):
        servers = [line for line in section.lines if line.words[0] == "server"]
        stats_uri = next(
            (line.words[2] for line in section.lines if line.words[:2] == ["stats", "uri"] and len(line.words) > 2),
            None,
        )
        if servers:
            add(f"{prefix}#self", [_Term()], GatewayBackend(name=section.name), section.origin, {"default_route": True})
        elif stats_uri:
            add(
                f"{prefix}#stats",
                [_Term(paths=[path_pattern("PathPrefix", stats_uri)])],
                None,
                section.origin,
                {"handler": {"directive": "stats uri"}},
            )
    return routes


def _dynamic_routes(
    section: _Section,
    group: str,
    target: str,
    dynamic: Optional["re.Match[str]"],
    line: _Line,
    state: _State,
    backends: Mapping[str, _Section],
    base_extras: Dict[str, Any],
    protocols: Tuple[str, ...],
    plugins: Tuple[GatewayPlugin, ...],
) -> List[GatewayRoute]:
    """Routes for a computed ``use_backend`` — one per map entry when the map is supplied."""
    rows = state.map_lines(dynamic.group("file")) if dynamic else None
    if dynamic is None or rows is None:
        state.limits.add("use_backend.dynamic", _CONDITION_REASONS["use_backend.dynamic"])
        return []
    fetch, param = _fetch_param(dynamic.group("fetch"))
    routes = []
    for key, *rest in rows:
        if not rest:
            continue
        backend = rest[0]
        _check_backend(backend, f"{line.origin}: map entry {key!r}", backends)
        headers: Tuple[Tuple[str, str], ...] = ((param, key),) if fetch in ("req.hdr", "hdr") and param else ()
        routes.append(
            GatewayRoute(
                name=f"{section.name}#map-{key}",
                service_name=group,
                matches=(GatewayMatch(path=path_pattern("PathPrefix", "/"), headers=headers),),
                protocols=protocols,
                plugins=plugins,
                backends=(_backend_ref(backend, backends),),
                source_location=line.origin,
                extras={**base_extras, "map_file": dynamic.group("file"), "map_key": key, "use_backend": target},
            )
        )
    return routes


def _defaults_table(state: _State) -> Dict[str, Dict[str, str]]:
    """Resolve which ``defaults`` each section inherits (the nearest preceding one)."""
    table: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for index, section in enumerate(state.sections):
        if section.keyword == "defaults":
            current = section.name or f"(defaults #{index})"
            values: Dict[str, str] = {}
            for line in section.lines:
                if line.words[0] == "mode" and len(line.words) > 1:
                    values["mode"] = line.words[1]
            table[current] = values
        elif section.keyword in _PROXY_SECTIONS:
            section.defaults_name = current
    return table


def _truncated_tail(state: _State) -> None:
    """Refuse a configuration whose last line is a ``server`` cut inside its address.

    A cut at a line boundary leaves a configuration that still reads. The shape it leaves
    in a backend is a final ``server <name> <address>`` with nothing after the address and
    no port on it — every other server line in a real configuration carries a port or an
    option. Only the **last** line is judged.
    """
    for section in reversed(state.sections):
        if not section.lines:
            return
        last = section.lines[-1]
        if last.words[0] == "server" and len(last.words) == 3:
            address = last.words[2]
            host, _scheme, port = split_address(address)
            if port is None and not address.startswith(("/", "unix@", "abns@", "ipv4@", "ipv6@")) and "." in host:
                raise GatewayConfigParseError(
                    f"{last.origin}: {_LABEL} configuration appears truncated — its final line "
                    f"`server {last.words[1]} {address}` stops inside the address",
                    code="INPUT_TRUNCATED",
                )
        return


def _document_from(state: _State, *, title: Optional[str], source_label: Optional[str]) -> GatewayConfigDocument:
    """Build routes and assemble the document."""
    _truncated_tail(state)
    defaults = _defaults_table(state)
    entry_sections = [section for section in state.sections if section.keyword in ("frontend", "listen")]
    if not any(any(line.words[0] == "bind" for line in section.lines) for section in entry_sections):
        raise GatewayConfigParseError(
            "The configuration has no frontend or listen section with a `bind` — nothing "
            "accepts traffic, so no route exists",
            code="INPUT_SEMANTIC_INVALID",
        )
    for section in state.sections:
        if section.keyword == "global":
            state.limits.add("global", _CONDITION_REASONS["global"])
    routes: List[GatewayRoute] = []
    for section in entry_sections:
        routes.extend(_frontend_routes(section, state, defaults))
    if not routes and "mode.tcp" not in state.limits.entries:
        raise GatewayConfigParseError(
            "No frontend routes any request — every use_backend is computed at runtime and "
            "there is no default_backend, so there is no route to import",
            code="INPUT_SEMANTIC_INVALID",
        )
    # A TCP-only configuration is a real one: it imports with no HTTP operation, and every
    # TCP section is declared on the ledger (``mode.tcp``) rather than the file refused.
    services = []
    for section in state.sections:
        if section.keyword != "backend":
            continue
        servers = [line.words[2] for line in section.lines if line.words[0] == "server" and len(line.words) > 2]
        extras: Dict[str, Any] = {"servers": servers}
        balance = next(
            (line.words[1] for line in section.lines if line.words[0] == "balance" and len(line.words) > 1), None
        )
        if balance:
            extras["balance"] = balance
        services.append(GatewayServiceDef(name=f"backend {section.name}", extras=extras))
    groups = sorted({route.service_name for route in routes if route.service_name})
    return GatewayConfigDocument(
        flavor=HAPROXY_FLAVOR,
        title=title or source_label or (groups[0] if groups else "HAProxy configuration"),
        services=tuple(services),
        routes=tuple(routes),
        ignored=state.limits.as_ignored(),
        source_label=source_label,
        raw={
            "flavor": HAPROXY_FLAVOR,
            "sections": sorted(f"{section.keyword} {section.name}".strip() for section in state.sections),
            "route_names": sorted(route.name for route in routes),
            "hostnames": sorted({host for route in routes for host in route.hosts}),
            "map_files_read": sorted(state.maps_read),
        },
    )


def _read(text: str, origin: str, state: _State) -> None:
    """Decode-check and fold one configuration text into ``state``."""
    reject_binary(text, format_label=_LABEL)
    state.sections.extend(_sections(_logical_lines(text, origin), origin))


def parse_haproxy(text: str, *, source_label: Optional[str] = None) -> GatewayConfigDocument:
    """Parse an HAProxy configuration into a gateway document.

    Args:
        text: The configuration text.
        source_label: Filename / paste label for provenance.

    Returns:
        The flavor-neutral document (``flavor="haproxy"``).

    Raises:
        GatewayConfigParseError: ``INPUT_ENCODING_INVALID`` for binary input,
            ``INPUT_MALFORMED`` for an unknown section keyword, ``INPUT_TRUNCATED`` for a
            cut-off file, ``FORMAT_MISMATCH`` for text with no HAProxy section,
            ``INPUT_SEMANTIC_INVALID`` when nothing binds a listener or no HTTP route
            exists, and ``INPUT_REFERENCE_UNRESOLVED`` for a rule naming an undeclared
            backend or ACL.
    """
    label = source_label or "haproxy.cfg"
    state = _State(members={})
    _read(text, label, state)
    return _document_from(state, title=None, source_label=source_label)


def parse_haproxy_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> GatewayConfigDocument:
    """Parse an HAProxy configuration with the map / pattern files it reads.

    ``.cfg`` members are configuration (read in order, root first); every other member is a
    map or pattern file, matched to the ``-f`` / ``map_*()`` references by path or file name.

    Args:
        members: Member path → text.
        root: The root configuration file.
        source_label: Label for the merged document.

    Returns:
        The document, with map-driven routing resolved where the map was supplied.

    Raises:
        GatewayConfigParseError: As :func:`parse_haproxy`.
    """
    state = _State(members=members)
    configs = [path for path in ordered_members(members, root) if path == root or path.endswith(".cfg")]
    for path in configs:
        _read(members[path], path, state)
    return _document_from(state, title=source_label, source_label=source_label or root)
