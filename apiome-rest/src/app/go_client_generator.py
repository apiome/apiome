"""The Go client generator — SDK-2.4 (#4488).

Turns a persisted :class:`~app.canonical_model.CanonicalApi` into a complete, idiomatic,
dependency-free Go client package: exported types for the contract's schemas, one
``context.Context``-first method per HTTP operation, ``net/http`` transport behind an injectable
interface, auth helpers derived from the model's security schemes, typed errors for the declared
error responses, and a runnable example program per operation group.

**Why here and not behind a generator SPI.** SDK-2.4's stated dependencies were the generator SPI
(SDK-1.2, #4482) and the codegen preprocessing pass (SDK-1.3, #4483). Both were closed
*not-planned*, along with the artifact store (SDK-1.1), the two MVP language generators
(SDK-2.1/2.2) and the dashboard/CLI surfaces (SDK-3.1/3.2) — so there is no SPI to register with
and no sandbox to run in. What *did* ship is the SDK-2.3 snippet renderer and the SDK-3.3 client
kit, which already read the canonical model directly and package their output deterministically.
This module follows that precedent: it is a pure function of the canonical model, it is called
from :mod:`app.sdk_kit`, and its output rides the kit's existing archive rather than a store.

**Three properties are load-bearing.**

*It is byte-deterministic.* Every collection is walked in declaration order, every name is
allocated from a deterministic allocator, and nothing consults the clock or the environment. The
same model plus the same branding therefore produce the same bytes — which is what lets the kit
keep serving a content-addressed ``ETag``.

*It emits Go that compiles.* Go rejects an unused import or an unused local, so imports are
computed per file from what was actually emitted rather than written as a fixed preamble, and
every generated identifier is allocated against one namespace so a schema named ``Client`` cannot
collide with the client type. ``tests/test_go_client_generator.py`` runs ``go build ./...`` and
``go vet ./...`` over a generated Petstore whenever a Go toolchain is on ``PATH``.

*It never refuses over one bad operation.* An operation with no HTTP binding — a gRPC method, a
GraphQL field, an AsyncAPI subscription — gets no method and is recorded in
:attr:`GoClientPackage.skipped` with a reason, exactly as the kit records its skipped snippets.

**Known limitations**, recorded here because a generated client that overstates its fidelity is
worse than one that documents its gaps:

* The canonical model records no discriminator for a union, so a ``UNION`` type is generated as
  raw JSON with one typed accessor per variant rather than as a tagged struct.
* A record-typed field is always a pointer, whether the contract makes it required or not. That
  is what lets a recursive contract (a tree node, a threaded comment) be expressed at all, and it
  gives every nested object a distinguishable "absent".
* Auth comes from the two ``extras`` shapes :mod:`app.canonical_security` documents. An OpenAPI
  import that recorded only a top-level ``security`` block and no per-operation requirement
  yields no helper, because the canonical model has no first-class security field to read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .canonical_json_schema import CANONICAL_SCALAR_SCHEMAS
from .canonical_model import (
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    Parameter,
    ParameterLocation,
    Type,
    TypeKind,
    TypeRef,
)
from .canonical_security import AUTH_SCHEME_HEADERS, declared_security_schemes
from .snippet_render import (
    license_comment_block,
    pick_content_type,
    request_message,
    resolve_server_base,
    upper_snake_token,
)

__all__ = [
    "DEFAULT_GO_VERSION",
    "DEFAULT_MODULE_HOST",
    "GO_CLIENT_SCHEMA_VERSION",
    "GO_ECOSYSTEM",
    "MAX_EXAMPLE_OPERATIONS",
    "GoClientFile",
    "GoClientMethod",
    "GoClientPackage",
    "GoClientSkip",
    "generate_go_client",
    "go_module_path",
    "go_package_name",
]

#: The addressable shape of the generated package, recorded in the kit manifest.
GO_CLIENT_SCHEMA_VERSION = "sdk.go-client.v1"

#: The ``go`` directive written into ``go.mod``. 1.21 is the oldest release that has every
#: construct this generator emits (``any``, ``errors.As``, generics are not used) and is still in
#: support, so a consumer on a conservative toolchain can build the output unchanged.
DEFAULT_GO_VERSION = "1.21"

#: Host used when a tenant has configured no Go module path. ``example.com`` is IANA-reserved, so
#: a default module path can never accidentally resolve to somebody's real repository.
DEFAULT_MODULE_HOST = "example.com"

#: The SDK-3.4 package-name ecosystem a Go module path is configured under.
GO_ECOSYSTEM = "gomod"

#: How many operations one example program calls. An example is read, not executed in anger, and a
#: ``main`` with two hundred calls teaches nothing; the remainder is named in a trailing comment.
MAX_EXAMPLE_OPERATIONS = 5

#: Go's reserved words. An identifier derived from a schema is checked against these before it is
#: used unexported (an exported identifier can never be a keyword — every keyword is lower-case).
_GO_KEYWORDS = frozenset(
    {
        "break", "case", "chan", "const", "continue", "default", "defer", "else",
        "fallthrough", "for", "func", "go", "goto", "if", "import", "interface", "map",
        "package", "range", "return", "select", "struct", "switch", "type", "var",
    }
)

#: Package-level identifiers the fixed files (``client.go``, ``errors.go``, ``auth.go``) define.
#: Every generated name is allocated against this set, so a schema called ``Client`` becomes
#: ``Client2`` rather than redeclaring the client type.
_RESERVED_IDENTIFIERS = frozenset(
    {
        "APIError", "AsAPIError", "Client", "DefaultBaseURL", "DefaultUserAgent", "Doer",
        "NewClient", "Option", "RequestEditor", "WithAPIKey", "WithAuthorization",
        "WithBaseURL", "WithBasicAuth", "WithBearerToken", "WithDigestAuthorization",
        "WithHTTPClient", "WithHeader", "WithRequestEditor", "WithSessionCookie",
        "WithUserAgent", "escapePath", "formatValue", "newAPIError",
    }
)

#: Filename stems the fixed files claim. Allocation is on the *stem*, not the whole filename, so a
#: service called "client" becomes ``client2.go`` rather than the uncompilable ``client.go2``.
_RESERVED_FILE_STEMS = frozenset({"auth", "client", "errors", "models"})

#: Local identifiers a generated method body uses. A parameter-derived argument name that would
#: shadow one of these is suffixed instead.
_RESERVED_LOCALS = frozenset(
    {"body", "c", "ctx", "err", "out", "params", "path", "payload", "query", "req", "resp"}
)

#: Reason-phrase per HTTP status, used to name a typed error (``404`` → ``NotFoundError``). Only
#: the statuses an API realistically declares a body for are listed; anything else falls back to
#: ``Status<code>Error``, which is still a legal, stable and unambiguous name.
_STATUS_PHRASES: Dict[int, str] = {
    400: "BadRequest", 401: "Unauthorized", 402: "PaymentRequired", 403: "Forbidden",
    404: "NotFound", 405: "MethodNotAllowed", 406: "NotAcceptable", 408: "RequestTimeout",
    409: "Conflict", 410: "Gone", 412: "PreconditionFailed", 413: "PayloadTooLarge",
    415: "UnsupportedMediaType", 418: "Teapot", 422: "UnprocessableEntity", 423: "Locked",
    424: "FailedDependency", 428: "PreconditionRequired", 429: "TooManyRequests",
    431: "RequestHeaderFieldsTooLarge", 451: "UnavailableForLegalReasons",
    500: "InternalServerError", 501: "NotImplemented", 502: "BadGateway",
    503: "ServiceUnavailable", 504: "GatewayTimeout", 505: "HTTPVersionNotSupported",
    507: "InsufficientStorage", 508: "LoopDetected", 511: "NetworkAuthenticationRequired",
}

#: Initialisms Go style spells in one case throughout (``userId`` → ``UserID``, not ``UserId``).
#: Applied to each word of a derived identifier, which is what makes the output read as Go rather
#: than as a transliterated schema.
_INITIALISMS = frozenset(
    {
        "acl", "api", "ascii", "cpu", "css", "dns", "eof", "guid", "html", "http", "https",
        "id", "ip", "json", "lhs", "qps", "ram", "rhs", "rpc", "sla", "smtp", "sql", "ssh",
        "tcp", "tls", "ttl", "udp", "ui", "uid", "uuid", "uri", "url", "utf8", "vm", "xml",
        "xmpp", "xsrf", "xss",
    }
)

#: Word boundaries in a source name: separators, and the seam between a lower-case (or digit) and
#: an upper-case character (``petId`` → ``pet`` + ``Id``).
_WORD_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_SEAM = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: A ``{name}`` placeholder in an HTTP path template.
_PATH_TOKEN = re.compile(r"\{([^{}]*)\}")

#: Characters permitted in one element of a Go module path. Everything else collapses to ``-``.
_MODULE_ELEMENT_UNSAFE = re.compile(r"[^A-Za-z0-9._~-]+")


# ===========================================================================
# Result shapes
# ===========================================================================


@dataclass(frozen=True)
class GoClientFile:
    """One file of the generated module.

    Attributes:
        path: Path relative to the module root (``client.go``, ``examples/pets/main.go``).
        text: The file's complete contents, always ending in a newline.
    """

    path: str
    text: str


@dataclass(frozen=True)
class GoClientSkip:
    """One operation the generator produced no method for.

    Attributes:
        operation_id: The id a consumer would address the operation by.
        key: The canonical operation key.
        reason: Why no method exists, in a sentence a consumer can act on.
    """

    operation_id: str
    key: str
    reason: str


@dataclass(frozen=True)
class GoClientMethod:
    """One generated client method, as the manifest reports it.

    Attributes:
        name: The exported Go method name (``GetWidget``).
        operation_id: The id the canonical model addresses the operation by.
        key: The canonical operation key.
        method: The upper-case HTTP verb.
        path: The HTTP path template.
        group: The example group (service) the method belongs to.
    """

    name: str
    operation_id: str
    key: str
    method: str
    path: str
    group: str


@dataclass(frozen=True)
class GoClientPackage:
    """A complete generated Go module.

    Attributes:
        module_path: The ``go.mod`` module path consumers ``go get``.
        package_name: The Go package name the client's files declare.
        go_version: The ``go`` directive written into ``go.mod``.
        files: Every generated file, ordered by path.
        methods: One record per generated client method, in declaration order.
        types: The exported Go type names generated from the contract's schemas, in order.
        auth_options: The exported auth helper names, sorted.
        skipped: Operations no method was generated for, with reasons.
        example_groups: The example program directories, in order.
    """

    module_path: str
    package_name: str
    go_version: str
    files: List[GoClientFile] = field(default_factory=list)
    methods: List[GoClientMethod] = field(default_factory=list)
    types: List[str] = field(default_factory=list)
    auth_options: List[str] = field(default_factory=list)
    skipped: List[GoClientSkip] = field(default_factory=list)
    example_groups: List[str] = field(default_factory=list)

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


# ===========================================================================
# Identifier derivation
# ===========================================================================


def _words(name: str) -> List[str]:
    """Split a source name into its words.

    Separators and camel-case seams both count, so ``pet_id``, ``pet-id`` and ``petId`` all
    yield ``["pet", "id"]``.

    Args:
        name: The source name.

    Returns:
        The lower-cased words, without empties.
    """
    spaced = _CAMEL_SEAM.sub(" ", name or "")
    return [word.lower() for word in _WORD_SEPARATORS.sub(" ", spaced).split(" ") if word]


def _exported(name: str, fallback: str = "Value") -> str:
    """Derive an exported Go identifier from a source name.

    Words are title-cased and joined, except that a word Go style spells as an initialism is
    upper-cased whole (``petId`` → ``PetID``). A name that starts with a digit is prefixed, since
    a Go identifier may not.

    Args:
        name: The source name.
        fallback: What to return when nothing usable survives.

    Returns:
        A legal, exported Go identifier.
    """
    parts = [word.upper() if word in _INITIALISMS else word.capitalize() for word in _words(name)]
    identifier = "".join(parts)
    if not identifier:
        return fallback
    if identifier[0].isdigit():
        identifier = "N" + identifier
    return identifier


def _unexported(name: str, fallback: str = "value") -> str:
    """Derive an unexported Go identifier (a local or an argument) from a source name.

    The first word stays lower-case whole — including an initialism, because ``iDValue`` is not
    Go — and a result that is a keyword or a reserved local is suffixed rather than reused.

    Args:
        name: The source name.
        fallback: What to return when nothing usable survives.

    Returns:
        A legal, unexported Go identifier that shadows nothing the generated bodies rely on.
    """
    words = _words(name)
    if not words:
        return fallback
    head = words[0]
    tail = [word.upper() if word in _INITIALISMS else word.capitalize() for word in words[1:]]
    identifier = head + "".join(tail)
    if identifier[0].isdigit():
        identifier = "n" + identifier
    if identifier in _GO_KEYWORDS or identifier in _RESERVED_LOCALS:
        identifier += "Value"
    return identifier


def go_package_name(*candidates: Optional[str]) -> str:
    """Derive the Go package name from the first usable candidate.

    A package name is a bare, lower-case identifier by convention, so the candidates are stripped
    of everything else. A candidate that reduces to nothing, to a digit-leading token, or to a Go
    keyword is passed over; ``apiclient`` is the last resort.

    Args:
        *candidates: Names to try in order — typically the project slug, then the API title.

    Returns:
        A legal Go package name.
    """
    for candidate in candidates:
        joined = "".join(_words(candidate or ""))
        if joined and not joined[0].isdigit() and joined not in _GO_KEYWORDS:
            return joined
    return "apiclient"


def go_module_path(configured: Optional[str], *segments: Optional[str]) -> str:
    """Return the module path for ``go.mod``.

    Args:
        configured: The tenant's configured Go module path (SDK-3.4's ``gomod`` package name),
            used verbatim when it is set — a module path is an identifier a consumer types, and
            second-guessing one they configured would break their ``go get``.
        *segments: Fallback coordinates (tenant slug, project slug, package name), joined under
            :data:`DEFAULT_MODULE_HOST` when nothing is configured.

    Returns:
        A module path with every element legal for ``go.mod``.
    """
    if configured and configured.strip():
        return configured.strip()
    elements = [_MODULE_ELEMENT_UNSAFE.sub("-", (part or "").strip().lower()).strip("-.") for part in segments]
    elements = [element for element in elements if element]
    return "/".join([DEFAULT_MODULE_HOST, *elements]) if elements else f"{DEFAULT_MODULE_HOST}/apiclient"


class _Names:
    """A deterministic allocator for one namespace of Go identifiers.

    Go has no overloading and no shadowing at package level, so every generated type, constant,
    parameter struct, typed error and helper competes for one set of names. Allocating them all
    here — seeded with the identifiers the fixed files already define — is what stops a schema
    called ``Client`` from redeclaring the client type.
    """

    def __init__(self, reserved: Sequence[str] = ()) -> None:
        """Start an allocator that will never hand out one of ``reserved``."""
        self._taken: Set[str] = set(reserved)

    def take(self, preferred: str) -> str:
        """Claim ``preferred``, or the first free ``<preferred>2``, ``<preferred>3``… variant.

        Args:
            preferred: The name the caller would like.

        Returns:
            The claimed name.
        """
        candidate = preferred
        suffix = 2
        while candidate in self._taken:
            candidate = f"{preferred}{suffix}"
            suffix += 1
        self._taken.add(candidate)
        return candidate

    def taken(self, name: str) -> bool:
        """Whether ``name`` has already been claimed."""
        return name in self._taken


# ===========================================================================
# Type resolution
# ===========================================================================

#: The Go type and the category each canonical scalar family maps to. The lookup itself goes
#: through :data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS` rather than a second
#: spelling table, so a scalar name a new import adapter starts emitting gets a Go type the moment
#: the fleet's shared vocabulary learns it.
_JSON_TYPE_TO_GO: Dict[Tuple[Optional[str], Optional[str]], Tuple[str, str]] = {
    ("string", None): ("string", "string"),
    ("boolean", None): ("bool", "bool"),
    ("integer", None): ("int", "int"),
    ("integer", "int32"): ("int32", "int"),
    ("integer", "int64"): ("int64", "int"),
    ("number", None): ("float64", "float"),
    ("number", "float"): ("float32", "float"),
    ("number", "double"): ("float64", "float"),
}


def _go_scalar(name: str) -> Tuple[str, str]:
    """Map a canonical scalar name onto its Go type.

    Args:
        name: The canonical scalar spelling (``string``, ``i64``, ``DateTime``…).

    Returns:
        ``(go type, category)``. An unrecognized name is ``("any", "any")`` — the honest answer
        for a custom scalar the model says nothing structural about.
    """
    schema = CANONICAL_SCALAR_SCHEMAS.get((name or "").strip().lower())
    if schema is None:
        return "any", "any"
    json_type = schema.get("type")
    if json_type == "string":
        # Every string-shaped scalar — uuid, date-time, base64 bytes — travels as JSON text.
        return "string", "string"
    mapped = _JSON_TYPE_TO_GO.get((json_type, schema.get("format")))
    if mapped is not None:
        return mapped
    mapped = _JSON_TYPE_TO_GO.get((json_type, None))
    return mapped if mapped is not None else ("any", "any")


@dataclass(frozen=True)
class _Resolved:
    """A canonical type reference expressed in Go.

    Attributes:
        text: The Go type as written when the value is held directly (``Widget``, ``[]string``).
        category: ``struct`` / ``union`` / ``map`` / ``slice`` / ``string`` / ``int`` / ``float``
            / ``bool`` / ``any`` — what drives pointering and example literals.
    """

    text: str
    category: str


_ANY = _Resolved("any", "any")

#: Categories whose zero value already means "absent", so a pointer would add nothing but a
#: dereference. A ``nil`` slice, a ``nil`` map and a ``nil`` interface are all distinguishable
#: from a present-but-empty value at the JSON boundary.
_NEVER_POINTER = frozenset({"slice", "map", "any"})

#: Categories that are always held by pointer in a struct field. Both are Go structs, and a
#: pointer is what lets a contract describe itself recursively — a comment whose replies are
#: comments is a shape a value-typed field could not express at all.
_ALWAYS_POINTER = frozenset({"struct", "union"})

#: Example literal per category, for the generated example programs. A defined type over one of
#: these accepts the same untyped constant, so ``type Email string`` still takes ``""``.
_EXAMPLE_LITERALS: Dict[str, str] = {
    "string": '""',
    "int": "0",
    "float": "0",
    "bool": "false",
}


@dataclass
class _NamedType:
    """One named canonical type and the Go declaration it became.

    Attributes:
        source: The canonical type.
        go_name: The exported Go identifier allocated for it.
        category: Its resolved category (alias chains followed).
    """

    source: Type
    go_name: str
    category: str = "any"


class _TypeTable:
    """Every named type in a model, resolved to Go once and looked up by reference.

    Resolution happens in two passes because references are not ordered: names are allocated for
    every type first, then categories are computed by following alias chains through the finished
    table. A reference is matched by canonical key first and by *unique* source name second —
    the same precedence :mod:`app.canonical_json_schema` uses, so a ``$ref`` a validation schema
    resolves and a field a Go struct declares always name the same type.
    """

    def __init__(self, api: CanonicalApi, names: _Names) -> None:
        """Allocate a Go name for every type in ``api`` and resolve their categories."""
        self._by_key: Dict[str, _NamedType] = {}
        self._by_name: Dict[str, List[_NamedType]] = {}
        self.entries: List[_NamedType] = []
        for type_ in api.types:
            if not type_.key:
                continue
            if type_.key in self._by_key:
                continue
            entry = _NamedType(source=type_, go_name=names.take(_exported(type_.name or type_.key, "Type")))
            self._by_key[type_.key] = entry
            self._by_name.setdefault(type_.name or "", []).append(entry)
            self.entries.append(entry)
        for entry in self.entries:
            entry.category = self._category(entry, frozenset())

    def lookup(self, name: str) -> Optional[_NamedType]:
        """Return the entry a reference names, or ``None`` when it names no single type."""
        if not name:
            return None
        direct = self._by_key.get(name)
        if direct is not None:
            return direct
        candidates = self._by_name.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def resolve(self, ref: Optional[TypeRef]) -> _Resolved:
        """Express one canonical type reference in Go.

        Args:
            ref: The reference, or ``None``.

        Returns:
            The :class:`_Resolved` Go type. A list wraps its element type; a named type resolves
            to its allocated identifier; anything else falls through to the scalar vocabulary.
        """
        if ref is None:
            return _ANY
        if ref.is_list():
            inner = self.resolve(ref.item)
            return _Resolved(f"[]{inner.text}", "slice")
        entry = self.lookup(ref.name or "")
        if entry is not None:
            return _Resolved(entry.go_name, entry.category)
        text, category = _go_scalar(ref.name or "")
        return _Resolved(text, category)

    def _category(self, entry: _NamedType, visiting: frozenset) -> str:
        """Resolve one type's category, following alias chains and refusing to loop."""
        kind = entry.source.kind
        if kind is TypeKind.RECORD:
            return "struct"
        if kind is TypeKind.UNION:
            return "union"
        if kind is TypeKind.MAP:
            return "map"
        if kind is TypeKind.ENUM:
            return _enum_shape(entry.source)[0]
        if kind is TypeKind.ALIAS and entry.source.aliased is not None:
            ref = entry.source.aliased
            if ref.is_list():
                return "slice"
            target = self.lookup(ref.name or "")
            if target is None:
                return _go_scalar(ref.name or "")[1]
            if target.source.key in visiting:
                # An alias cycle (``A = B``, ``B = A``) has no Go spelling; ``any`` is the one
                # answer that still compiles and still round-trips the JSON untouched.
                return "any"
            return self._category(target, visiting | {entry.source.key})
        return _named_scalar_go(entry.source)[1]

    def alias_target(self, entry: _NamedType, visiting: frozenset = frozenset()) -> _Resolved:
        """Resolve what an ``ALIAS`` type aliases, refusing to close a loop.

        Go rejects a recursive alias outright (``type A = B`` beside ``type B = A``), so a chain
        that returns to a type already on the path resolves to ``any`` — which still compiles and
        still carries the JSON through untouched.

        Args:
            entry: The alias entry being declared.
            visiting: Canonical keys already on this chain.

        Returns:
            The Go type the alias should be declared as.
        """
        ref = entry.source.aliased
        if ref is None:
            return _ANY
        if ref.is_list():
            return self.resolve(ref)
        target = self.lookup(ref.name or "")
        if target is None:
            return self.resolve(ref)
        if target.source.key == entry.source.key or target.source.key in visiting:
            return _ANY
        if target.source.kind is TypeKind.ALIAS:
            deeper = self.alias_target(target, visiting | {entry.source.key})
            if deeper is _ANY:
                return _ANY
        return _Resolved(target.go_name, target.category)


def _named_scalar_go(type_: Type) -> Tuple[str, str]:
    """Return the Go type and category for a named ``SCALAR`` (or target-less ``ALIAS``) type.

    A custom scalar the shared vocabulary does not know may still declare the shape it serializes
    as — a GraphQL ``DateTime`` carrying ``format: date-time`` — so the type's own constraints are
    consulted before giving up on ``any``.

    Args:
        type_: The canonical type.

    Returns:
        ``(go type, category)``.
    """
    text, category = _go_scalar(type_.name or type_.key)
    if category == "any" and type_.constraints is not None:
        text, category = _go_scalar(type_.constraints.format or "")
    return text, category


def _enum_shape(type_: Type) -> Tuple[str, List[Tuple[str, str]]]:
    """Return an enum's Go category and its ``(member name, Go literal)`` pairs.

    A member's wire value wins over its name when the source declares one — the same rule
    :func:`app.canonical_json_schema.build_type_json_schema` applies, so the constants a client
    sends are the values a validator would accept.

    Args:
        type_: The ``ENUM`` type.

    Returns:
        ``(category, members)``. A heterogeneous enum resolves to ``any`` with no constants:
        there is no single Go underlying type its members would all fit.
    """
    values: List[Tuple[str, object]] = []
    seen: List[object] = []
    for member in type_.enum_values:
        value = member.value if member.value is not None else member.name
        if value in seen:
            continue
        seen.append(value)
        values.append((member.name or str(value), value))
    if not values:
        return "string", []
    raw = [value for _name, value in values]
    if all(isinstance(item, str) for item in raw):
        return "string", [(name, _go_string(str(value))) for name, value in values]
    if all(isinstance(item, bool) for item in raw):
        return "bool", [(name, "true" if value else "false") for name, value in values]
    if all(isinstance(item, int) and not isinstance(item, bool) for item in raw):
        return "int", [(name, str(value)) for name, value in values]
    return "any", []


def _go_string(value: str) -> str:
    """Render a Go interpreted string literal, escaping what Go requires escaped."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


# ===========================================================================
# Source-text helpers
# ===========================================================================

#: Where a generated doc comment wraps. Go has no line-length rule, but a comment that a reader
#: has to scroll is one they will not read.
_COMMENT_WIDTH = 96


def _wrap(text: str, width: int = _COMMENT_WIDTH) -> List[str]:
    """Wrap prose onto lines of at most ``width`` characters, preserving blank-line breaks.

    Args:
        text: The prose to wrap.
        width: The soft ceiling; a single word longer than it is never broken.

    Returns:
        The wrapped lines, with paragraph breaks kept as empty strings.
    """
    lines: List[str] = []
    for paragraph in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = paragraph.split()
        if not words:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) > width:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}"
        lines.append(current)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


#: Terminal punctuation that stops gofmt reading a one-line paragraph as a godoc heading. Go 1.19's
#: comment reformatter promotes an unpunctuated single line to a ``#`` heading, which would turn a
#: contract's one-line summary into a section title; ending the sentence is what keeps the prose
#: prose, and keeps ``gofmt -l`` quiet on the generated package.
_SENTENCE_ENDINGS = (".", "!", "?", ":", ";", ",", ")", "`")


def _paragraphs(text: str) -> List[str]:
    """Split prose into paragraphs on blank lines, dropping empties."""
    blocks: List[str] = []
    current: List[str] = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            current.append(line.strip())
        elif current:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def _sentence(text: str) -> str:
    """End a one-line paragraph with a full stop unless it already ends in punctuation."""
    stripped = (text or "").rstrip()
    if not stripped or stripped.endswith(_SENTENCE_ENDINGS):
        return stripped
    return f"{stripped}."


def _doc(subject: str, summary: str, description: Optional[str] = None) -> List[str]:
    """Compose a Go doc comment.

    Args:
        subject: The identifier being documented — Go convention starts the comment with it.
        summary: The one-line summary that follows the subject.
        description: The contract's own prose, appended after a blank comment line.

    Returns:
        The comment lines, each already prefixed with ``//``.
    """
    lines = [f"// {line}" for line in _wrap(_sentence(f"{subject} {summary}".strip()))]
    if description and description.strip():
        lines.append("//")
        for paragraph in _paragraphs(description.strip()):
            if lines[-1] != "//":
                lines.append("//")
            lines.extend(f"// {line}".rstrip() for line in _wrap(_sentence(paragraph)))
    return lines


def _render_struct_fields(entries: Sequence[Tuple[List[str], str, str, str]]) -> List[str]:
    """Render struct fields with gofmt's column alignment.

    gofmt aligns a *run* of consecutive field lines and restarts at anything that interrupts them,
    so a field carrying a doc comment begins a new run. Reproducing that here is what makes the
    output look like Go somebody wrote rather than Go something printed.

    Args:
        entries: ``(doc lines, field name, field type, struct tag)`` per field.

    Returns:
        The indented field lines.
    """
    lines: List[str] = []
    run: List[Tuple[str, str, str]] = []

    def flush() -> None:
        if not run:
            return
        name_width = max(len(name) for name, _type, _tag in run)
        type_width = max(len(type_) for _name, type_, _tag in run)
        for name, type_, tag in run:
            rendered = f"\t{name.ljust(name_width)} {type_.ljust(type_width)} {tag}".rstrip()
            lines.append(rendered)
        run.clear()

    for docs, name, type_, tag in entries:
        if docs:
            flush()
            lines.extend(f"\t{line}" for line in docs)
        run.append((name, type_, tag))
    flush()
    return lines


def _json_tag(name: str, optional: bool) -> str:
    """Return the ``json`` struct tag for a field carrying wire name ``name``."""
    suffix = ",omitempty" if optional else ""
    return f"`json:\"{name}{suffix}\"`"


def _go_file(
    package_name: str,
    imports: Sequence[str],
    body: Sequence[str],
    *,
    license_header: Optional[str] = None,
    package_doc: Sequence[str] = (),
    aliases: Optional[Dict[str, str]] = None,
) -> str:
    """Assemble one ``.go`` file.

    Imports are written only when there are any, sorted, and split into the standard library and
    everything else the way goimports groups them. Go rejects an unused import outright, so every
    caller computes the set from what it actually emitted rather than writing a fixed preamble.

    Args:
        package_name: The package clause.
        imports: Import paths. The client package itself is standard-library only; an example
            program also imports the generated module.
        body: The file's declarations, already rendered.
        license_header: A tenant's licence text (SDK-3.4), rendered as a leading comment block.
        package_doc: Doc-comment lines attached to the package clause.
        aliases: Import path → explicit alias, for a module whose last path element is not its
            package name.

    Returns:
        The file text, ending in exactly one newline.
    """

    def spec(path: str) -> str:
        alias = (aliases or {}).get(path)
        return f'{alias} "{path}"' if alias else f'"{path}"'

    lines: List[str] = []
    prologue = license_comment_block(license_header, "go")
    if prologue:
        lines.extend(prologue.split("\n"))
        lines.append("")
    lines.extend(package_doc)
    lines.append(f"package {package_name}")
    unique = sorted(set(imports))
    # A first path element containing a dot is a domain, so the import is not standard library.
    standard = [path for path in unique if "." not in path.split("/")[0]]
    external = [path for path in unique if "." in path.split("/")[0]]
    if unique:
        lines.append("")
        if len(unique) == 1:
            lines.append(f"import {spec(unique[0])}")
        else:
            lines.append("import (")
            lines.extend(f"\t{spec(path)}" for path in standard)
            if standard and external:
                lines.append("")
            lines.extend(f"\t{spec(path)}" for path in external)
            lines.append(")")
    for line in body:
        lines.append(line)
    text = "\n".join(lines).rstrip("\n")
    return f"{text}\n"


# ===========================================================================
# Models
# ===========================================================================

#: Go underlying type per enum category.
_ENUM_UNDERLYING: Dict[str, str] = {"string": "string", "int": "int64", "bool": "bool", "any": "any"}


def _field_go_type(resolved: _Resolved, optional: bool) -> str:
    """Return how a resolved type is written as a struct field or a parameter.

    Three rules, in order:

    * a slice, a map and ``any`` are never pointers — ``nil`` is already their absent value;
    * a struct or a union always is, which is what lets a recursive contract compile and gives a
      nested object a distinguishable "absent";
    * everything else is a pointer only when the contract makes it optional, so a required
      ``string`` reads as a ``string``.

    Args:
        resolved: The resolved Go type.
        optional: Whether the contract lets the value be absent.

    Returns:
        The Go type as written at the use site.
    """
    if resolved.category in _NEVER_POINTER:
        return resolved.text
    if resolved.category in _ALWAYS_POINTER:
        return f"*{resolved.text}"
    return f"*{resolved.text}" if optional else resolved.text


def _render_consts(rows: Sequence[Tuple[List[str], str, str, str]]) -> List[str]:
    """Render a ``const`` block with gofmt's alignment, one row per constant.

    Args:
        rows: ``(doc lines, name, type, literal)`` per constant.

    Returns:
        The block's lines, including its ``const (`` and ``)``.
    """
    lines = ["const ("]
    run: List[Tuple[str, str, str]] = []

    def flush() -> None:
        if not run:
            return
        name_width = max(len(name) for name, _type, _literal in run)
        type_width = max(len(type_) for _name, type_, _literal in run)
        for name, type_, literal in run:
            lines.append(f"\t{name.ljust(name_width)} {type_.ljust(type_width)} = {literal}".rstrip())
        run.clear()

    for docs, name, type_, literal in rows:
        if docs:
            flush()
            lines.extend(f"\t{line}" for line in docs)
        run.append((name, type_, literal))
    flush()
    lines.append(")")
    return lines


def _render_record(entry: _NamedType, table: _TypeTable) -> List[str]:
    """Render a ``RECORD`` type as a Go struct."""
    source = entry.source
    lines = _doc(entry.go_name, f"models the `{source.name or source.key}` schema.", source.description)
    fields = _Names()
    rows: List[Tuple[List[str], str, str, str]] = []
    for member in source.fields:
        if not member.name:
            continue
        optional = member.type.nullable is not False
        resolved = table.resolve(member.type)
        docs: List[str] = []
        go_name = fields.take(_exported(member.name, "Field"))
        if member.description or member.deprecated:
            docs = _doc(go_name, f"is the `{member.name}` field.", member.description)
            if member.deprecated:
                docs.extend(["//", "// Deprecated: the contract marks this field deprecated."])
        rows.append((docs, go_name, _field_go_type(resolved, optional), _json_tag(member.name, optional)))
    if not rows:
        lines.append(f"type {entry.go_name} struct{{}}")
        return lines
    lines.append(f"type {entry.go_name} struct {{")
    lines.extend(_render_struct_fields(rows))
    lines.append("}")
    return lines


def _render_enum(entry: _NamedType, names: _Names) -> List[str]:
    """Render an ``ENUM`` type as a defined type plus its constants."""
    source = entry.source
    category, members = _enum_shape(source)
    underlying = _ENUM_UNDERLYING.get(category, "string")
    lines = _doc(
        entry.go_name,
        f"is the `{source.name or source.key}` enumeration.",
        source.description,
    )
    lines.append(f"type {entry.go_name} {underlying}")
    if not members:
        return lines
    rows: List[Tuple[List[str], str, str, str]] = []
    for member_name, literal in members:
        const = names.take(_exported(f"{entry.go_name} {member_name}", f"{entry.go_name}Value"))
        rows.append(([], const, entry.go_name, literal))
    lines.append("")
    lines.append(f"// The values `{source.name or source.key}` declares.")
    lines.extend(_render_consts(rows))
    return lines


def _render_union(entry: _NamedType, table: _TypeTable, names: _Names) -> Tuple[List[str], Set[str]]:
    """Render a ``UNION`` type as raw JSON with one typed accessor per variant.

    The canonical model records a union's variants but no discriminator — no format the fleet
    imports guarantees one — so a tagged Go struct would have to invent the tag. Carrying the
    value as ``json.RawMessage`` instead is lossless in both directions and still gives a caller
    a typed way in.

    Args:
        entry: The union entry.
        table: The resolved type table, for the variant names.
        names: The package identifier allocator, for the constructor.

    Returns:
        ``(lines, imports)``.
    """
    source = entry.source
    variants: List[str] = []
    accessors = _Names({"MarshalJSON", "Raw", "UnmarshalJSON"})
    resolved_variants: List[Tuple[str, str]] = []
    for member_key in source.union_members:
        target = table.lookup(member_key)
        if target is None or target.source.key == source.key:
            continue
        variants.append(target.go_name)
        resolved_variants.append((accessors.take(f"As{target.go_name}"), target.go_name))
    summary = (
        f"is the `{source.name or source.key}` union of {', '.join(variants)}."
        if variants
        else f"is the `{source.name or source.key}` union."
    )
    lines = _doc(entry.go_name, summary, source.description)
    lines += [
        "//",
        "// The contract records the variants but no discriminator, so the value is carried as raw",
        "// JSON: marshalling round-trips it untouched and one accessor per variant decodes it.",
        f"type {entry.go_name} struct {{",
        "\traw json.RawMessage",
        "}",
        "",
    ]
    constructor = names.take(f"New{entry.go_name}")
    lines += _doc(constructor, "wraps already-encoded JSON as a value of this union.")
    lines += [
        f"func {constructor}(raw json.RawMessage) {entry.go_name} {{",
        f"\treturn {entry.go_name}{{raw: raw}}",
        "}",
        "",
    ]
    lines += _doc("Raw", "returns the union's JSON exactly as it was received.")
    lines += [
        f"func (u {entry.go_name}) Raw() json.RawMessage {{",
        "\treturn u.raw",
        "}",
        "",
    ]
    lines += _doc("MarshalJSON", "implements json.Marshaler.")
    lines += [
        f"func (u {entry.go_name}) MarshalJSON() ([]byte, error) {{",
        "\tif len(u.raw) == 0 {",
        '\t\treturn []byte("null"), nil',
        "\t}",
        "\treturn u.raw, nil",
        "}",
        "",
    ]
    lines += _doc("UnmarshalJSON", "implements json.Unmarshaler.")
    lines += [
        f"func (u *{entry.go_name}) UnmarshalJSON(data []byte) error {{",
        "\tu.raw = append(u.raw[:0], data...)",
        "\treturn nil",
        "}",
    ]
    imports = {"encoding/json"}
    for accessor, variant in resolved_variants:
        imports.add("fmt")
        lines.append("")
        lines += _doc(accessor, f"decodes the union's JSON as the {variant} variant.")
        lines += [
            f"func (u {entry.go_name}) {accessor}() (*{variant}, error) {{",
            f"\tvar value {variant}",
            "\tif err := json.Unmarshal(u.raw, &value); err != nil {",
            f'\t\treturn nil, fmt.Errorf("decode {entry.go_name} as {variant}: %w", err)',
            "\t}",
            "\treturn &value, nil",
            "}",
        ]
    return lines, imports


def _render_models(
    table: _TypeTable, names: _Names, package_name: str, license_header: Optional[str]
) -> Optional[GoClientFile]:
    """Render ``models.go`` — every named type the contract declares.

    Args:
        table: The resolved type table.
        names: The package identifier allocator.
        package_name: The package clause.
        license_header: The tenant's licence text, or ``None``.

    Returns:
        The file, or ``None`` when the contract declares no named types.
    """
    if not table.entries:
        return None
    imports: Set[str] = set()
    body: List[str] = []
    for entry in table.entries:
        body.append("")
        kind = entry.source.kind
        if kind is TypeKind.RECORD:
            body.extend(_render_record(entry, table))
        elif kind is TypeKind.ENUM:
            body.extend(_render_enum(entry, names))
        elif kind is TypeKind.UNION:
            lines, union_imports = _render_union(entry, table, names)
            body.extend(lines)
            imports |= union_imports
        elif kind is TypeKind.MAP:
            value = table.resolve(entry.source.value_type)
            body.extend(
                _doc(
                    entry.go_name,
                    f"is the `{entry.source.name or entry.source.key}` map. JSON object keys are "
                    "always text, so the key type is `string` whatever the contract names.",
                    entry.source.description,
                )
            )
            body.append(f"type {entry.go_name} map[string]{value.text}")
        elif kind is TypeKind.ALIAS:
            target = table.alias_target(entry)
            body.extend(
                _doc(
                    entry.go_name,
                    f"aliases `{entry.source.name or entry.source.key}`.",
                    entry.source.description,
                )
            )
            body.append(f"type {entry.go_name} = {target.text}")
        else:
            text, _category = _named_scalar_go(entry.source)
            body.extend(
                _doc(
                    entry.go_name,
                    f"is the `{entry.source.name or entry.source.key}` scalar.",
                    entry.source.description,
                )
            )
            body.append(f"type {entry.go_name} {text}")
    package_doc = ["// Code generated by Apiome. DO NOT EDIT.", ""]
    return GoClientFile(
        path="models.go",
        text=_go_file(
            package_name,
            sorted(imports),
            body,
            license_header=license_header,
            package_doc=package_doc,
        ),
    )


# ===========================================================================
# The fixed files: transport, errors, auth
# ===========================================================================

#: One auth helper per canonical security scheme: the option's name, its parameters, what it does,
#: the Go expression producing the header value, and any import that expression needs. The header
#: *name* is not repeated here — it comes from :data:`app.canonical_security.AUTH_SCHEME_HEADERS`,
#: so a client's helper and a request file's header can never disagree about where a credential
#: travels. Schemes that share a helper (``oauth2`` and ``openIdConnect`` are both bearer tokens on
#: the wire) name the same entry and are emitted once.
_AUTH_HELPERS: Dict[str, Tuple[str, str, str, str, Tuple[str, ...]]] = {
    "bearer": (
        "WithBearerToken",
        "token string",
        "sends the token as an `Authorization: Bearer` header on every request.",
        '"Bearer "+token',
        (),
    ),
    "oauth2": (
        "WithBearerToken",
        "token string",
        "sends the token as an `Authorization: Bearer` header on every request.",
        '"Bearer "+token',
        (),
    ),
    "openIdConnect": (
        "WithBearerToken",
        "token string",
        "sends the token as an `Authorization: Bearer` header on every request.",
        '"Bearer "+token',
        (),
    ),
    "basic": (
        "WithBasicAuth",
        "username, password string",
        "sends the credentials as an HTTP Basic `Authorization` header on every request.",
        '"Basic "+base64.StdEncoding.EncodeToString([]byte(username+":"+password))',
        ("encoding/base64",),
    ),
    "digest": (
        "WithDigestAuthorization",
        "credentials string",
        "sends an already-computed HTTP Digest `Authorization` header on every request. The "
        "client does not perform the digest challenge-response itself.",
        '"Digest "+credentials',
        (),
    ),
    "authorization": (
        "WithAuthorization",
        "value string",
        "sends a verbatim `Authorization` header on every request.",
        "value",
        (),
    ),
    "apiKey": (
        "WithAPIKey",
        "key string",
        "sends the API key on every request.",
        "key",
        (),
    ),
    "cookie": (
        "WithSessionCookie",
        "cookie string",
        "sends a verbatim `Cookie` header on every request.",
        "cookie",
        (),
    ),
}


def _render_client(
    package_name: str,
    package_doc: Sequence[str],
    base_url: str,
    user_agent: Optional[str],
    license_header: Optional[str],
) -> GoClientFile:
    """Render ``client.go`` — the transport every generated method goes through.

    Args:
        package_name: The package clause.
        package_doc: The package's doc-comment lines.
        base_url: The default base URL, taken from the contract's first server.
        user_agent: The tenant's SDK-3.4 user-agent, or ``None`` for no default.
        license_header: The tenant's licence text, or ``None``.

    Returns:
        The rendered file.
    """
    body: List[str] = [
        "",
        "// DefaultBaseURL is the first server the contract declares. Override it with WithBaseURL.",
        f"const DefaultBaseURL = {_go_string(base_url)}",
        "",
        "// DefaultUserAgent is the User-Agent every request carries unless WithUserAgent replaces it.",
        f"const DefaultUserAgent = {_go_string(user_agent or '')}",
        "",
        "// Doer is the part of *http.Client this package uses. Depending on the interface rather",
        "// than the struct is what lets a caller inject a client with its own timeouts, transport,",
        "// retries or test double.",
        "type Doer interface {",
        "\tDo(req *http.Request) (*http.Response, error)",
        "}",
        "",
        "// RequestEditor inspects or modifies a request immediately before it is sent. Returning an",
        "// error aborts the call.",
        "type RequestEditor func(ctx context.Context, req *http.Request) error",
        "",
        "// Option configures a Client.",
        "type Option func(*Client)",
        "",
        "// Client calls the API. The zero value is not usable; build one with NewClient.",
        "type Client struct {",
        "\tbaseURL    string",
        "\tuserAgent  string",
        "\thttpClient Doer",
        "\theader     http.Header",
        "\teditors    []RequestEditor",
        "}",
        "",
        "// NewClient returns a Client pointed at DefaultBaseURL, sending through http.DefaultClient,",
        "// with every option applied in order.",
        "func NewClient(opts ...Option) *Client {",
        "\tclient := &Client{",
        "\t\tbaseURL:    DefaultBaseURL,",
        "\t\tuserAgent:  DefaultUserAgent,",
        "\t\thttpClient: http.DefaultClient,",
        "\t\theader:     http.Header{},",
        "\t}",
        "\tfor _, opt := range opts {",
        "\t\tif opt != nil {",
        "\t\t\topt(client)",
        "\t\t}",
        "\t}",
        "\treturn client",
        "}",
        "",
        "// WithHTTPClient sends every request through doer instead of http.DefaultClient. A nil doer",
        "// is ignored, so a caller cannot accidentally build a client that cannot send.",
        "func WithHTTPClient(doer Doer) Option {",
        "\treturn func(c *Client) {",
        "\t\tif doer != nil {",
        "\t\t\tc.httpClient = doer",
        "\t\t}",
        "\t}",
        "}",
        "",
        "// WithBaseURL points the client at another origin — a staging host, a mock server — with any",
        "// trailing slash trimmed so paths concatenate cleanly.",
        "func WithBaseURL(baseURL string) Option {",
        "\treturn func(c *Client) {",
        '\t\tc.baseURL = strings.TrimRight(baseURL, "/")',
        "\t}",
        "}",
        "",
        "// WithUserAgent replaces the User-Agent every request carries.",
        "func WithUserAgent(userAgent string) Option {",
        "\treturn func(c *Client) {",
        "\t\tc.userAgent = userAgent",
        "\t}",
        "}",
        "",
        "// WithHeader sets a header sent on every request. It is the general form of the auth",
        "// helpers: anything the contract does not describe can still be sent through it.",
        "func WithHeader(name, value string) Option {",
        "\treturn func(c *Client) {",
        "\t\tc.header.Set(name, value)",
        "\t}",
        "}",
        "",
        "// WithRequestEditor appends a hook run against every request just before it is sent — for",
        "// request signing, tracing headers, or anything else that depends on the request itself.",
        "func WithRequestEditor(edit RequestEditor) Option {",
        "\treturn func(c *Client) {",
        "\t\tif edit != nil {",
        "\t\t\tc.editors = append(c.editors, edit)",
        "\t\t}",
        "\t}",
        "}",
        "",
        "// BaseURL reports the origin requests are currently sent to.",
        "func (c *Client) BaseURL() string {",
        "\treturn c.baseURL",
        "}",
        "",
        "// newRequest builds one request: the URL from the base plus the filled path and query, the",
        "// headers from the client's defaults, and the body as JSON unless it is already []byte.",
        "func (c *Client) newRequest(ctx context.Context, method, path string, query url.Values,"
        " body any, contentType string) (*http.Request, error) {",
        "\ttarget := c.baseURL + path",
        "\tif len(query) > 0 {",
        '\t\ttarget += "?" + query.Encode()',
        "\t}",
        "\tvar reader io.Reader",
        "\tif body != nil {",
        "\t\tif raw, ok := body.([]byte); ok {",
        "\t\t\treader = bytes.NewReader(raw)",
        "\t\t} else {",
        "\t\t\tencoded, err := json.Marshal(body)",
        "\t\t\tif err != nil {",
        '\t\t\t\treturn nil, fmt.Errorf("encode request body for %s %s: %w", method, path, err)',
        "\t\t\t}",
        "\t\t\treader = bytes.NewReader(encoded)",
        "\t\t}",
        "\t}",
        "\treq, err := http.NewRequestWithContext(ctx, method, target, reader)",
        "\tif err != nil {",
        '\t\treturn nil, fmt.Errorf("build request for %s %s: %w", method, path, err)',
        "\t}",
        "\tfor name, values := range c.header {",
        "\t\tfor _, value := range values {",
        "\t\t\treq.Header.Add(name, value)",
        "\t\t}",
        "\t}",
        '\tif req.Header.Get("Accept") == "" {',
        '\t\treq.Header.Set("Accept", "application/json")',
        "\t}",
        '\tif contentType != "" {',
        '\t\treq.Header.Set("Content-Type", contentType)',
        "\t}",
        '\tif c.userAgent != "" {',
        '\t\treq.Header.Set("User-Agent", c.userAgent)',
        "\t}",
        "\tfor _, edit := range c.editors {",
        "\t\tif err := edit(ctx, req); err != nil {",
        "\t\t\treturn nil, err",
        "\t\t}",
        "\t}",
        "\treturn req, nil",
        "}",
        "",
        "// do sends a request, decodes a successful JSON body into out, and turns every non-2xx",
        "// response into an *APIError carrying the body it was refused with.",
        "func (c *Client) do(req *http.Request, out any) (*http.Response, error) {",
        "\tresp, err := c.httpClient.Do(req)",
        "\tif err != nil {",
        '\t\treturn nil, fmt.Errorf("%s %s: %w", req.Method, req.URL, err)',
        "\t}",
        "\tdefer resp.Body.Close()",
        "\tpayload, err := io.ReadAll(resp.Body)",
        "\tif err != nil {",
        '\t\treturn resp, fmt.Errorf("read response body for %s %s: %w", req.Method, req.URL, err)',
        "\t}",
        "\tif resp.StatusCode < 200 || resp.StatusCode > 299 {",
        "\t\treturn resp, newAPIError(req, resp, payload)",
        "\t}",
        "\tif out == nil || len(payload) == 0 {",
        "\t\treturn resp, nil",
        "\t}",
        "\tif err := json.Unmarshal(payload, out); err != nil {",
        '\t\treturn resp, fmt.Errorf("decode response body for %s %s: %w", req.Method, req.URL, err)',
        "\t}",
        "\treturn resp, nil",
        "}",
        "",
        "// escapePath escapes one value for use inside a URL path segment.",
        "func escapePath(value string) string {",
        "\treturn url.PathEscape(value)",
        "}",
        "",
        "// formatValue renders a path, query, header or cookie value as the text that goes on the wire.",
        "func formatValue(value any) string {",
        "\tif value == nil {",
        '\t\treturn ""',
        "\t}",
        "\tif text, ok := value.(string); ok {",
        "\t\treturn text",
        "\t}",
        '\treturn fmt.Sprintf("%v", value)',
        "}",
    ]
    return GoClientFile(
        path="client.go",
        text=_go_file(
            package_name,
            ["bytes", "context", "encoding/json", "fmt", "io", "net/http", "net/url", "strings"],
            body,
            license_header=license_header,
            package_doc=list(package_doc),
        ),
    )


@dataclass(frozen=True)
class _TypedError:
    """One typed error the contract's error responses justify.

    Attributes:
        go_name: The exported Go type name (``NotFoundError``).
        status: The HTTP status it is raised for.
        payload_type: The Go type of the decoded body, as written on the field.
        payload_is_pointer: Whether that field is a pointer, and so whether the decoder assigns
            the local's address or the local itself. A record is a pointer; a slice, a map and a
            generated ``any`` are not.
        payload_value_type: The Go type the decoder declares its local as — the field type with
            any leading ``*`` removed.
        description: The contract's own prose for the response, when it has any.
    """

    go_name: str
    status: int
    payload_type: str
    payload_is_pointer: bool
    payload_value_type: str
    description: Optional[str] = None


def _render_errors(
    package_name: str,
    typed: Sequence[_TypedError],
    license_header: Optional[str],
) -> GoClientFile:
    """Render ``errors.go`` — the transport error plus one type per declared error response.

    Args:
        package_name: The package clause.
        typed: The typed errors, in allocation order.
        license_header: The tenant's licence text, or ``None``.

    Returns:
        The rendered file.
    """
    body: List[str] = [
        "",
        "// APIError is returned for every response outside the 2xx range. It carries the whole",
        "// refusal — status, headers and raw body — so a caller can decide what to do with it even",
        "// when the contract declared no schema for that status.",
        "type APIError struct {",
        "\t// Method is the HTTP verb of the call that failed.",
        "\tMethod string",
        "\t// URL is the absolute URL the failed call addressed.",
        "\tURL string",
        "\t// StatusCode is the response status code.",
        "\tStatusCode int",
        '\t// Status is the response status line, for example "404 Not Found".',
        "\tStatus string",
        "\t// Header holds the response headers.",
        "\tHeader http.Header",
        "\t// Body is the response body, read in full before the connection was released.",
        "\tBody []byte",
        "}",
        "",
        "// Error implements error.",
        "func (e *APIError) Error() string {",
        '\treturn fmt.Sprintf("%s %s: unexpected status %s", e.Method, e.URL, e.Status)',
        "}",
        "",
        "// Decode unmarshals the error body into out. Use it for a status the contract declared no",
        "// schema for; a declared one already arrives as its own typed error.",
        "func (e *APIError) Decode(out any) error {",
        "\tif len(e.Body) == 0 {",
        '\t\treturn fmt.Errorf("%s %s: error response has no body to decode", e.Method, e.URL)',
        "\t}",
        "\tif err := json.Unmarshal(e.Body, out); err != nil {",
        '\t\treturn fmt.Errorf("%s %s: decode error body: %w", e.Method, e.URL, err)',
        "\t}",
        "\treturn nil",
        "}",
        "",
        "// newAPIError captures a failed response before its body is released.",
        "func newAPIError(req *http.Request, resp *http.Response, body []byte) *APIError {",
        '\ttarget := ""',
        "\tif req.URL != nil {",
        "\t\ttarget = req.URL.String()",
        "\t}",
        "\treturn &APIError{",
        "\t\tMethod:     req.Method,",
        "\t\tURL:        target,",
        "\t\tStatusCode: resp.StatusCode,",
        "\t\tStatus:     resp.Status,",
        "\t\tHeader:     resp.Header,",
        "\t\tBody:       body,",
        "\t}",
        "}",
        "",
        "// AsAPIError reports whether err is, or wraps, an *APIError. Every typed error below wraps",
        "// one, so this finds the transport facts behind any of them.",
        "func AsAPIError(err error) (*APIError, bool) {",
        "\tvar apiErr *APIError",
        "\tif errors.As(err, &apiErr) {",
        "\t\treturn apiErr, true",
        "\t}",
        "\treturn nil, false",
        "}",
    ]
    for entry in typed:
        body.append("")
        body.extend(
            _doc(
                entry.go_name,
                f"is the error the contract declares for a {entry.status} response.",
                entry.description,
            )
        )
        body += [
            f"type {entry.go_name} struct {{",
            "\t// APIError carries the transport facts: method, URL, status, headers and raw body.",
            "\t*APIError",
            "\t// Payload is the decoded error body, or nil when the body did not decode as declared.",
            f"\tPayload {entry.payload_type}",
            "}",
            "",
            "// Error implements error.",
            f"func (e *{entry.go_name}) Error() string {{",
            "\treturn e.APIError.Error()",
            "}",
            "",
            "// Unwrap returns the underlying *APIError, so errors.As reaches it.",
            f"func (e *{entry.go_name}) Unwrap() error {{",
            "\treturn e.APIError",
            "}",
        ]
    return GoClientFile(
        path="errors.go",
        text=_go_file(
            package_name,
            ["encoding/json", "errors", "fmt", "net/http"],
            body,
            license_header=license_header,
            package_doc=["// Code generated by Apiome. DO NOT EDIT.", ""],
        ),
    )


def _render_auth(
    package_name: str, schemes: Sequence[str], license_header: Optional[str]
) -> Tuple[Optional[GoClientFile], List[str], List[str]]:
    """Render ``auth.go`` — one option per security scheme the contract declares.

    Args:
        package_name: The package clause.
        schemes: The scheme identifiers the model declares, in sorted order.
        license_header: The tenant's licence text, or ``None``.

    Returns:
        ``(file, options, unrepresentable)`` — the file (``None`` when the model declares no
        scheme this generator can express), the exported option names in emission order, and the
        schemes that have no request-header representation and so got no helper.
    """
    body: List[str] = []
    imports: Set[str] = set()
    options: List[str] = []
    unrepresentable: List[str] = []
    emitted: Set[str] = set()
    for scheme in schemes:
        helper = _AUTH_HELPERS.get(scheme)
        header = AUTH_SCHEME_HEADERS.get(scheme)
        if helper is None or header is None:
            unrepresentable.append(scheme)
            continue
        option, signature, summary, expression, needed = helper
        if option in emitted:
            continue
        emitted.add(option)
        options.append(option)
        imports.update(needed)
        body.append("")
        body.extend(_doc(option, summary))
        body += [
            "//",
            f"// Derived from the `{scheme}` security scheme the contract declares.",
            f"func {option}({signature}) Option {{",
            "\treturn func(c *Client) {",
            f"\t\tc.header.Set({_go_string(header[0])}, {expression})",
            "\t}",
            "}",
        ]
    if not options:
        return None, [], unrepresentable
    return (
        GoClientFile(
            path="auth.go",
            text=_go_file(
                package_name,
                sorted(imports),
                body,
                license_header=license_header,
                package_doc=["// Code generated by Apiome. DO NOT EDIT.", ""],
            ),
        ),
        options,
        unrepresentable,
    )


# ===========================================================================
# Operations
# ===========================================================================


@dataclass(frozen=True)
class _PlannedParam:
    """One operation input, resolved to Go.

    Attributes:
        wire_name: The name the value travels under (``limit``, ``X-Request-Id``).
        field_name: The exported field name inside the operation's ``Params`` struct.
        arg_name: The unexported argument name, for a path parameter.
        go_type: The Go type as written on the field or argument.
        resolved: The resolved type, for the example literal and the slice check.
        optional: Whether the contract lets the value be absent.
        description: The contract's prose for the parameter.
    """

    wire_name: str
    field_name: str
    arg_name: str
    go_type: str
    resolved: _Resolved
    optional: bool
    description: Optional[str] = None

    @property
    def is_pointer(self) -> bool:
        """Whether the field is held by pointer and so needs a nil guard and a dereference."""
        return self.go_type.startswith("*")


@dataclass
class _PlannedOperation:
    """One operation, fully resolved before any Go is written."""

    op: Operation
    group: str
    method_name: str
    http_method: str
    path_template: str
    path_expr: str
    path_args: List[_PlannedParam] = field(default_factory=list)
    query: List[_PlannedParam] = field(default_factory=list)
    headers: List[_PlannedParam] = field(default_factory=list)
    cookies: List[_PlannedParam] = field(default_factory=list)
    params_struct: Optional[str] = None
    body_arg: Optional[str] = None
    body_type: Optional[str] = None
    body_content_type: str = ""
    result_type: Optional[str] = None
    result_local: Optional[str] = None
    result_is_slice: bool = False
    typed_errors: List[Tuple[int, _TypedError]] = field(default_factory=list)
    decoder_name: Optional[str] = None
    identifier: str = ""

    @property
    def has_params(self) -> bool:
        """Whether the operation has a ``Params`` struct at all."""
        return self.params_struct is not None


def _operation_identifier(op: Operation) -> str:
    """The id a consumer addresses this operation by.

    Mirrors :func:`app.snippet_render.find_operation`'s precedence, so an id named in the Go
    package's documentation is one the snippet routes actually resolve.
    """
    return op.extras.get("operationId") or op.name or op.key


def _status_int(raw: Optional[str]) -> Optional[int]:
    """Return a response status as an int, or ``None`` for a range (``4XX``) or ``default``."""
    text = (raw or "").strip()
    return int(text) if text.isdigit() else None


def _success_message(op: Operation) -> Optional[Message]:
    """Return the response message a successful call decodes.

    A numeric 2xx wins; failing that, the first response the contract states no status for (or
    states as ``default``/``2XX``) is taken, which is how AsyncAPI-shaped and inferred models
    describe their one reply.

    Args:
        op: The operation to inspect.

    Returns:
        The success message, or ``None`` when the operation declares no response payload.
    """
    fallback: Optional[Message] = None
    for message in op.messages:
        if message.role is not MessageRole.RESPONSE:
            continue
        status = _status_int(message.status_code)
        if status is not None and 200 <= status <= 299:
            return message
        if status is None and fallback is None and (message.status_code or "").strip().lower() in {
            "",
            "default",
            "2xx",
        }:
            fallback = message
    return fallback


def _error_messages(op: Operation) -> List[Tuple[int, Message]]:
    """Return the operation's error responses as ``(status, message)``, first per status.

    Only numeric statuses take part: a typed error is selected by a ``switch`` on the status code,
    and a range like ``4XX`` has no single case to be.
    """
    seen: Set[int] = set()
    found: List[Tuple[int, Message]] = []
    for message in op.messages:
        if message.role not in {MessageRole.RESPONSE, MessageRole.ERROR}:
            continue
        status = _status_int(message.status_code)
        if status is None or status < 400 or status in seen:
            continue
        seen.add(status)
        found.append((status, message))
    return found


def _error_type_name(status: int) -> str:
    """The preferred Go name for a typed error on ``status`` (``404`` → ``NotFoundError``)."""
    phrase = _STATUS_PHRASES.get(status)
    return f"{phrase}Error" if phrase else f"Status{status}Error"


def _example_literal(resolved: _Resolved, wire_name: str) -> str:
    """The literal an example program passes for one argument.

    A string-shaped argument gets the same shouting-snake token the SDK-2.3 snippets use, so a
    reader who has seen the snippet substitutes the same name here.

    Args:
        resolved: The argument's resolved type.
        wire_name: The parameter's source name, for the token.

    Returns:
        A Go expression the example can pass.
    """
    if resolved.category == "string":
        return _go_string(upper_snake_token(wire_name))
    return _EXAMPLE_LITERALS.get(resolved.category, "nil")


class _OperationPlanner:
    """Resolves every operation to Go before a line of it is written.

    Planning and rendering are separate passes because a method's *file* needs facts from all of
    its methods — which imports to write, which typed errors to declare — and Go refuses to
    compile a file that imports something it does not use.
    """

    def __init__(
        self,
        api: CanonicalApi,
        table: _TypeTable,
        names: _Names,
        max_operations: int,
    ) -> None:
        """Plan every operation of ``api``.

        Args:
            api: The canonical model.
            table: The resolved type table.
            names: The package identifier allocator (``Params`` structs, typed errors, decoders).
            max_operations: How many operations get methods before the rest are skipped.
        """
        self._api = api
        self._table = table
        self._names = names
        self._methods = _Names({"BaseURL", "do", "newRequest"})
        self._max = max_operations
        #: (status, payload field type) → the typed error declared for it, so two operations that
        #: declare the same 404 body share one Go type instead of declaring two.
        self._typed: Dict[Tuple[int, str], _TypedError] = {}
        self.typed_errors: List[_TypedError] = []
        self.planned: List[_PlannedOperation] = []
        self.skipped: List[GoClientSkip] = []
        self._plan()

    # -- planning ---------------------------------------------------------

    def _plan(self) -> None:
        """Walk every service in declaration order, planning what can be planned."""
        for service in self._api.services:
            group = service.name or service.key or "api"
            for op in service.operations:
                identifier = _operation_identifier(op)
                if not op.http_method or not op.http_path:
                    self.skipped.append(
                        GoClientSkip(
                            operation_id=identifier,
                            key=op.key,
                            reason=(
                                f"Operation {op.name or op.key!r} has no HTTP binding; a Go client "
                                "method is only generated for HTTP operations"
                            ),
                        )
                    )
                    continue
                if len(self.planned) >= self._max:
                    self.skipped.append(
                        GoClientSkip(
                            operation_id=identifier,
                            key=op.key,
                            reason=(
                                f"The generated client carries the first {self._max} operations; "
                                "this one is beyond that limit"
                            ),
                        )
                    )
                    continue
                self.planned.append(self._plan_operation(op, group, identifier))

    def _plan_operation(self, op: Operation, group: str, identifier: str) -> _PlannedOperation:
        """Resolve one operation into a :class:`_PlannedOperation`."""
        method_name = self._methods.take(_exported(identifier or op.key, "Call"))
        path = op.http_path or "/"
        if not path.startswith("/"):
            path = "/" + path
        # The request-body argument claims ``body`` first, so a path token that happens to be
        # called ``body`` is the one that gets suffixed rather than the argument every method of
        # this shape names the same way.
        locals_taken = _Names(_RESERVED_LOCALS - {"body"})
        body_arg, body_type, content_type = self._plan_body(op, locals_taken)
        path_args, path_expr = self._plan_path(path, op, locals_taken)

        fields = _Names()
        query = [
            self._plan_param(param, fields)
            for param in op.parameters
            if param.location is ParameterLocation.QUERY
        ]
        headers = [
            self._plan_param(param, fields)
            for param in op.parameters
            if param.location is ParameterLocation.HEADER
        ]
        cookies = [
            self._plan_param(param, fields)
            for param in op.parameters
            if param.location is ParameterLocation.COOKIE
        ]
        params_struct = (
            self._names.take(f"{method_name}Params") if (query or headers or cookies) else None
        )

        result_type, result_local, result_is_slice = self._plan_result(op)
        typed_errors = self._plan_errors(op)
        decoder = (
            self._names.take(_unexported(f"decode {method_name} error")) if typed_errors else None
        )

        return _PlannedOperation(
            op=op,
            group=group,
            method_name=method_name,
            http_method=(op.http_method or "GET").upper(),
            path_template=path,
            path_expr=path_expr,
            path_args=path_args,
            query=query,
            headers=headers,
            cookies=cookies,
            params_struct=params_struct,
            body_arg=body_arg,
            body_type=body_type,
            body_content_type=content_type,
            result_type=result_type,
            result_local=result_local,
            result_is_slice=result_is_slice,
            typed_errors=typed_errors,
            decoder_name=decoder,
            identifier=identifier,
        )

    def _plan_path(
        self, path: str, op: Operation, locals_taken: _Names
    ) -> Tuple[List[_PlannedParam], str]:
        """Turn a path template into positional arguments plus the Go expression that fills it.

        A template token is matched to a declared path parameter for its type and prose; a token
        the contract forgot to declare still becomes a ``string`` argument, because the call
        cannot be made without it.

        Args:
            path: The normalized path template.
            op: The operation, for its declared parameters.
            locals_taken: The method's local-name allocator.

        Returns:
            ``(arguments, expression)`` — the arguments in template order (a repeated token is
            one argument used twice), and the Go string expression building the path.
        """
        declared = {
            param.name: param
            for param in op.parameters
            if param.location is ParameterLocation.PATH
        }
        args: Dict[str, _PlannedParam] = {}
        ordered: List[_PlannedParam] = []
        pieces: List[str] = []
        cursor = 0
        for match in _PATH_TOKEN.finditer(path):
            token = match.group(1).strip()
            literal = path[cursor : match.start()]
            cursor = match.end()
            if literal:
                pieces.append(_go_string(literal))
            if not token:
                pieces.append(_go_string(match.group(0)))
                continue
            planned = args.get(token)
            if planned is None:
                param = declared.get(token)
                resolved = self._table.resolve(param.type) if param is not None else _Resolved("string", "string")
                planned = _PlannedParam(
                    wire_name=token,
                    field_name="",
                    arg_name=locals_taken.take(_unexported(token, "pathValue")),
                    go_type=_field_go_type(resolved, optional=False),
                    resolved=resolved,
                    optional=False,
                    description=param.description if param is not None else None,
                )
                args[token] = planned
                ordered.append(planned)
            pieces.append(f"escapePath(formatValue({planned.arg_name}))")
        trailing = path[cursor:]
        if trailing or not pieces:
            pieces.append(_go_string(trailing))
        return ordered, " + ".join(pieces)

    def _plan_param(self, param: Parameter, fields: _Names) -> _PlannedParam:
        """Resolve one query/header/cookie parameter into a ``Params`` struct field."""
        resolved = self._table.resolve(param.type)
        optional = not param.required
        return _PlannedParam(
            wire_name=param.name,
            field_name=fields.take(_exported(param.name, "Param")),
            arg_name="",
            go_type=_field_go_type(resolved, optional),
            resolved=resolved,
            optional=optional,
            description=param.description,
        )

    def _plan_body(
        self, op: Operation, locals_taken: _Names
    ) -> Tuple[Optional[str], Optional[str], str]:
        """Decide the request-body argument, if the operation takes one.

        A JSON body is typed from its payload when the contract names one and falls back to
        ``any`` when the body is only an inline schema. A non-JSON body is ``[]byte``, which the
        transport sends verbatim under the declared media type rather than pretending it is JSON.

        Returns:
            ``(argument name, Go type, content type)``, or ``(None, None, "")``.
        """
        message = request_message(op)
        if message is None or (message.payload is None and message.payload_schema is None):
            return None, None, ""
        content_type = pick_content_type(message)
        name = locals_taken.take("body")
        if "json" not in content_type.lower():
            return name, "[]byte", content_type
        if message.payload is not None:
            resolved = self._table.resolve(message.payload)
            if resolved.category != "any":
                return name, _field_go_type(resolved, optional=True), content_type
        return name, "any", content_type

    def _plan_result(self, op: Operation) -> Tuple[Optional[str], Optional[str], bool]:
        """Decide what a successful call returns.

        Returns:
            ``(return type, local declaration type, is slice)``. ``(None, None, False)`` when the
            operation declares no response payload and the method returns only ``error``.
        """
        message = _success_message(op)
        if message is None:
            return None, None, False
        if message.payload is not None:
            resolved = self._table.resolve(message.payload)
            if resolved.category == "slice":
                return resolved.text, resolved.text, True
            if resolved.category != "any":
                return f"*{resolved.text}", resolved.text, False
        if message.payload_schema is None and message.payload is None:
            return None, None, False
        # The contract declares a body but names no type for it — hand the caller the bytes
        # rather than an `any` they would have to re-marshal to inspect.
        return "json.RawMessage", "json.RawMessage", True

    def _plan_errors(self, op: Operation) -> List[Tuple[int, _TypedError]]:
        """Declare (or reuse) a typed error for each error response that names a payload type."""
        found: List[Tuple[int, _TypedError]] = []
        for status, message in _error_messages(op):
            if message.payload is None:
                continue
            resolved = self._table.resolve(message.payload)
            if resolved.category == "any":
                continue
            field_type = _field_go_type(resolved, optional=True)
            key = (status, field_type)
            existing = self._typed.get(key)
            if existing is None:
                preferred = _error_type_name(status)
                if self._names.taken(preferred):
                    # A second body shape for the same status, or a schema that already claimed
                    # the name: qualify with the payload rather than silently sharing a type.
                    preferred = f"{_exported(resolved.text)}{preferred}"
                # The address is taken only when the field is a pointer. Keying off the field
                # type rather than off the category is what keeps a map- or slice-shaped payload
                # assignable: `_field_go_type` already decided which shapes get a pointer.
                is_pointer = field_type.startswith("*")
                existing = _TypedError(
                    go_name=self._names.take(preferred),
                    status=status,
                    payload_type=field_type,
                    payload_is_pointer=is_pointer,
                    payload_value_type=field_type[1:] if is_pointer else field_type,
                    description=message.description,
                )
                self._typed[key] = existing
                self.typed_errors.append(existing)
            found.append((status, existing))
        return found


def _render_params_struct(planned: _PlannedOperation) -> List[str]:
    """Render the ``Params`` struct carrying an operation's query, header and cookie inputs."""
    rows: List[Tuple[List[str], str, str, str]] = []
    groups = (
        (planned.query, "query"),
        (planned.headers, "header"),
        (planned.cookies, "cookie"),
    )
    for group, location in groups:
        for item in group:
            requirement = "optional" if item.optional else "required"
            docs = _doc(
                item.field_name,
                f"is the {requirement} `{item.wire_name}` {location} parameter.",
                item.description,
            )
            rows.append((docs, item.field_name, item.go_type, ""))
    lines = _doc(
        planned.params_struct or "",
        f"carries the query, header and cookie inputs of {planned.method_name}. A nil "
        "*Params sends none of them.",
    )
    lines.append(f"type {planned.params_struct} struct {{")
    lines.extend(_render_struct_fields(rows))
    lines.append("}")
    return lines


def _render_value_setter(
    item: _PlannedParam, receiver: str, call: str, add_call: str, indent: str
) -> List[str]:
    """Render the statement that puts one parameter onto the wire.

    Three shapes, because Go needs three: a slice is ranged and added once per element, a pointer
    is nil-guarded and dereferenced, and a value is set directly.

    Args:
        item: The parameter to write.
        receiver: The Go expression holding it (``params.Limit``).
        call: The single-value call, with two ``{}`` slots for name and value.
        add_call: The repeated-value call, same slots.
        indent: Leading tabs.

    Returns:
        The statement's lines.
    """
    name = _go_string(item.wire_name)
    if item.resolved.category == "slice":
        return [
            f"{indent}for _, item := range {receiver} {{",
            f"{indent}\t{add_call.format(name, 'formatValue(item)')}",
            f"{indent}}}",
        ]
    if item.is_pointer:
        return [
            f"{indent}if {receiver} != nil {{",
            f"{indent}\t{call.format(name, f'formatValue(*{receiver})')}",
            f"{indent}}}",
        ]
    return [f"{indent}{call.format(name, f'formatValue({receiver})')}"]


def _render_method(planned: _PlannedOperation) -> List[str]:
    """Render one client method, from its signature to its return."""
    args = ["ctx context.Context"]
    args += [f"{item.arg_name} {item.go_type}" for item in planned.path_args]
    if planned.body_arg:
        args.append(f"{planned.body_arg} {planned.body_type}")
    if planned.has_params:
        args.append(f"params *{planned.params_struct}")
    returns = f"({planned.result_type}, error)" if planned.result_type else "error"
    failure = "nil, err" if planned.result_type else "err"

    summary = f"calls {planned.http_method} {planned.path_template}."
    lines = _doc(planned.method_name, summary, planned.op.description)
    if planned.identifier and planned.identifier != planned.op.key:
        lines += ["//", f"// Contract operation `{planned.identifier}` (`{planned.op.key}`)."]
    else:
        lines += ["//", f"// Contract operation `{planned.op.key}`."]
    if planned.op.deprecated:
        lines += ["//", "// Deprecated: the contract marks this operation deprecated."]
    lines.append(f"func (c *Client) {planned.method_name}({', '.join(args)}) {returns} {{")
    lines.append(f"\tpath := {planned.path_expr}")

    if planned.query:
        lines.append("")
        lines.append("\tquery := url.Values{}")
        lines.append("\tif params != nil {")
        for item in planned.query:
            lines.extend(
                _render_value_setter(
                    item,
                    f"params.{item.field_name}",
                    "query.Set({}, {})",
                    "query.Add({}, {})",
                    "\t\t",
                )
            )
        lines.append("\t}")

    if planned.body_arg:
        lines += [
            "",
            "\tvar payload any",
            f"\tif {planned.body_arg} != nil {{",
            f"\t\tpayload = {planned.body_arg}",
            "\t}",
        ]
    lines.append("")
    lines.append(
        f"\treq, err := c.newRequest(ctx, {_go_string(planned.http_method)}, path, "
        f"{'query' if planned.query else 'nil'}, "
        f"{'payload' if planned.body_arg else 'nil'}, "
        f"{_go_string(planned.body_content_type)})"
    )
    lines += ["\tif err != nil {", f"\t\treturn {failure}", "\t}"]

    if planned.headers or planned.cookies:
        lines.append("\tif params != nil {")
        for item in planned.headers:
            lines.extend(
                _render_value_setter(
                    item,
                    f"params.{item.field_name}",
                    "req.Header.Set({}, {})",
                    "req.Header.Add({}, {})",
                    "\t\t",
                )
            )
        for item in planned.cookies:
            lines.extend(
                _render_value_setter(
                    item,
                    f"params.{item.field_name}",
                    "req.AddCookie(&http.Cookie{{Name: {}, Value: {}}})",
                    "req.AddCookie(&http.Cookie{{Name: {}, Value: {}}})",
                    "\t\t",
                )
            )
        lines.append("\t}")

    promote = f"{planned.decoder_name}(err)" if planned.decoder_name else "err"
    lines.append("")
    if planned.result_type is None:
        lines += [
            "\tif _, err := c.do(req, nil); err != nil {",
            f"\t\treturn {promote}",
            "\t}",
            "\treturn nil",
            "}",
        ]
        return lines
    lines += [
        f"\tvar out {planned.result_local}",
        "\tif _, err := c.do(req, &out); err != nil {",
        f"\t\treturn nil, {promote}",
        "\t}",
        f"\treturn {'out' if planned.result_is_slice else '&out'}, nil",
        "}",
    ]
    return lines


def _render_error_decoder(planned: _PlannedOperation) -> List[str]:
    """Render the helper that promotes an ``*APIError`` into the declared typed error."""
    lines = _doc(
        planned.decoder_name or "",
        f"promotes a failed {planned.method_name} call into the typed error the contract declares "
        "for that status, leaving any other failure as it was.",
    )
    lines += [
        f"func {planned.decoder_name}(err error) error {{",
        "\tapiErr, ok := AsAPIError(err)",
        "\tif !ok {",
        "\t\treturn err",
        "\t}",
        "\tswitch apiErr.StatusCode {",
    ]
    for status, typed in planned.typed_errors:
        lines += [
            f"\tcase {status}:",
            f"\t\ttyped := &{typed.go_name}{{APIError: apiErr}}",
            f"\t\tvar payload {typed.payload_value_type}",
            "\t\tif decodeErr := apiErr.Decode(&payload); decodeErr == nil {",
            f"\t\t\ttyped.Payload = {'&payload' if typed.payload_is_pointer else 'payload'}",
            "\t\t}",
            "\t\treturn typed",
        ]
    lines += ["\t}", "\treturn err", "}"]
    return lines


def _render_operations_file(
    filename: str,
    group: str,
    operations: Sequence[_PlannedOperation],
    package_name: str,
    license_header: Optional[str],
) -> GoClientFile:
    """Render one operation group's file: its ``Params`` structs, methods and error decoders."""
    imports: Set[str] = {"context"}
    if any(item.query for item in operations):
        imports.add("net/url")
    if any(item.cookies for item in operations):
        imports.add("net/http")
    if any(item.result_type == "json.RawMessage" for item in operations):
        imports.add("encoding/json")
    body: List[str] = []
    for planned in operations:
        if planned.has_params:
            body.append("")
            body.extend(_render_params_struct(planned))
        body.append("")
        body.extend(_render_method(planned))
        if planned.decoder_name:
            body.append("")
            body.extend(_render_error_decoder(planned))
    return GoClientFile(
        path=filename,
        text=_go_file(
            package_name,
            sorted(imports),
            body,
            license_header=license_header,
            package_doc=[
                "// Code generated by Apiome. DO NOT EDIT.",
                "",
                f"// Operations of the `{group}` group.",
                "",
            ],
        ),
    )


# ===========================================================================
# Examples, README, go.mod
# ===========================================================================


def _example_body_literal(planned: _PlannedOperation, package_name: str) -> str:
    """The request-body expression an example passes.

    A struct body is constructed empty so a reader sees where to fill fields in; every other body
    shape is ``nil``, because inventing a value for an opaque or non-JSON payload would only teach
    the reader something untrue.
    """
    body_type = planned.body_type or ""
    if body_type.startswith("*"):
        message = request_message(planned.op)
        if message is not None and message.payload is not None:
            return f"&{package_name}.{body_type[1:]}{{}}"
    return "nil"


def _render_example(
    group: str,
    directory: str,
    operations: Sequence[_PlannedOperation],
    package_name: str,
    module_path: str,
    api_title: str,
    license_header: Optional[str],
) -> GoClientFile:
    """Render one group's runnable example program.

    Every generated method is already compile-checked by ``go build`` on the package itself; the
    example's job is to show a reader the *call*, so it stops at
    :data:`MAX_EXAMPLE_OPERATIONS` calls and names the remainder rather than printing two hundred.

    Args:
        group: The operation group's name, for the doc comment.
        directory: The example directory, for the command's name.
        operations: The group's operations, in declaration order.
        package_name: The client package's name, used as the import alias.
        module_path: The module path the example imports.
        api_title: The API's title, for the doc comment.
        license_header: The tenant's licence text, or ``None``.

    Returns:
        The rendered ``main.go``.
    """
    shown = list(operations[:MAX_EXAMPLE_OPERATIONS])
    body: List[str] = ["", "func main() {", "\tctx := context.Background()", f"\tclient := {package_name}.NewClient()"]
    for planned in shown:
        arguments = ["ctx"]
        arguments += [
            _example_literal(item.resolved, item.wire_name) if not item.go_type.startswith("*")
            else "nil"
            for item in planned.path_args
        ]
        if planned.body_arg:
            arguments.append(_example_body_literal(planned, package_name))
        if planned.has_params:
            arguments.append("nil")
        call = f"client.{planned.method_name}({', '.join(arguments)})"
        body.append("")
        body.append(f"\t// {planned.http_method} {planned.path_template}")
        if planned.body_arg:
            body.append("\t// TODO: fill in the request body before running this.")
        if planned.result_type is None:
            body += [
                f"\tif err := {call}; err != nil {{",
                f'\t\tlog.Fatalf("{planned.method_name}: %v", err)',
                "\t}",
                f'\tfmt.Println("{planned.method_name}: ok")',
            ]
            continue
        result = _unexported(f"{planned.method_name} result")
        body += [
            f"\t{result}, err := {call}",
            "\tif err != nil {",
            f'\t\tlog.Fatalf("{planned.method_name}: %v", err)',
            "\t}",
            f'\tfmt.Printf("{planned.method_name}: %+v\\n", {result})',
        ]
    remaining = len(operations) - len(shown)
    if remaining > 0:
        body.append("")
        body.append(
            f"\t// {remaining} further `{group}` operation(s) are available on the client; see the "
            "README."
        )
    body.append("}")

    doc = [
        "// Code generated by Apiome. DO NOT EDIT.",
        "",
        f"// Command {directory} shows how to call the `{group}` operations of {api_title}.",
        "//",
        "// The argument values are placeholders. Replace them, and point the client at your own",
        f"// origin with {package_name}.WithBaseURL, before running it.",
    ]
    # The module's last path element is usually not the package name (``petstore-go`` holding
    # ``package petstore``), and Go takes the name from the package clause rather than the path —
    # so the alias is written out whenever they differ, to save the reader that inference.
    last_element = module_path.rsplit("/", 1)[-1]
    aliases = {} if last_element == package_name else {module_path: package_name}
    return GoClientFile(
        path=f"examples/{directory}/main.go",
        text=_go_file(
            "main",
            ["context", "fmt", "log", module_path],
            body,
            license_header=license_header,
            package_doc=doc,
            aliases=aliases,
        ),
    )


def _render_go_mod(module_path: str, go_version: str) -> GoClientFile:
    """Render ``go.mod``. The client is standard-library only, so it declares no requirements."""
    return GoClientFile(
        path="go.mod",
        text=f"module {module_path}\n\ngo {go_version}\n",
    )


def _render_readme(
    api: CanonicalApi,
    module_path: str,
    package_name: str,
    base_url: str,
    planned: Sequence[_PlannedOperation],
    skipped: Sequence[GoClientSkip],
    auth_options: Sequence[str],
    unrepresentable: Sequence[str],
    typed_errors: Sequence[_TypedError],
    example_groups: Sequence[str],
    license_header: Optional[str],
) -> GoClientFile:
    """Render the Go module's ``README.md``."""
    title = api.title or package_name
    version_phrase = f" version **{api.version}**" if api.version else ""
    lines: List[str] = [
        f"# {title} — Go client",
        "",
        f"A generated, dependency-free Go client for **{title}**{version_phrase}.",
        "",
        "Every method takes a `context.Context` first, sends through the standard library's",
        "`net/http`, and returns the contract's own types.",
        "",
        "## Install",
        "",
        "```bash",
        f"go get {module_path}",
        "```",
        "",
        "## Quick start",
        "",
        "```go",
        f'import {package_name} "{module_path}"',
        "",
        f"client := {package_name}.NewClient(",
        f'\t{package_name}.WithBaseURL("{base_url}"),',
        f"\t{package_name}.WithHTTPClient(&http.Client{{Timeout: 10 * time.Second}}),",
        ")",
        "```",
        "",
        "`NewClient` defaults to `DefaultBaseURL`, the first server the contract declares, and to",
        "`http.DefaultClient`. `WithHTTPClient` takes any `Doer`, so your own transport, timeouts,",
        "retries or test double drop straight in.",
        "",
    ]
    if license_header:
        lines += ["## Licence", "", "```", license_header.strip(), "```", ""]

    lines += ["## Authentication", ""]
    if auth_options:
        lines += [
            "The contract's security schemes become client options:",
            "",
        ]
        lines += [f"- `{option}`" for option in auth_options]
        lines += [
            "",
            "Anything the contract does not describe can still be sent with `WithHeader`, and",
            "`WithRequestEditor` covers credentials that depend on the request itself.",
            "",
        ]
    else:
        lines += [
            "The contract declares no security scheme this generator can express as a helper. Send",
            "credentials with `WithHeader(name, value)`, or with `WithRequestEditor` when they",
            "depend on the request itself.",
            "",
        ]
    if unrepresentable:
        listed = ", ".join(f"`{scheme}`" for scheme in unrepresentable)
        lines += [
            f"These declared schemes do not travel in a request header, so no helper exists for "
            f"them: {listed}.",
            "",
        ]

    lines += [
        "## Errors",
        "",
        "Every response outside the 2xx range becomes an `*APIError` carrying the method, URL,",
        "status, headers and raw body. `AsAPIError(err)` reaches it through any wrapping.",
        "",
    ]
    if typed_errors:
        lines += ["The contract declares a body for these statuses, so they arrive typed:", ""]
        lines += [
            f"- `{entry.go_name}` — status {entry.status}, payload `{entry.payload_type}`"
            for entry in typed_errors
        ]
        lines.append("")

    if example_groups:
        lines += ["## Examples", ""]
        lines += [f"- `examples/{directory}` — `go run ./examples/{directory}`" for directory in example_groups]
        lines.append("")

    lines += ["## Operations", "", "| Method | Path | Go method |", "| --- | --- | --- |"]
    for item in planned:
        lines.append(f"| `{item.http_method}` | `{item.path_template}` | `{item.method_name}` |")
    lines.append("")

    if skipped:
        lines += [
            "## Not included",
            "",
            "No method is generated for these operations:",
            "",
        ]
        lines += [f"- `{entry.key}` — {entry.reason}" for entry in skipped]
        lines.append("")

    lines += [
        "## Generated code",
        "",
        "Every `.go` file here is generated from the published contract and carries the standard",
        "`Code generated … DO NOT EDIT.` marker. Regenerate rather than edit: the output is",
        "byte-deterministic, so an unchanged contract produces an unchanged package and a diff",
        "always means the contract moved.",
        "",
        "Two shapes are worth knowing about before you read the types:",
        "",
        "- A field whose type is another schema is always a pointer, required or not. That is what",
        "  lets a recursive contract compile, and it gives every nested object a distinguishable",
        "  absent.",
        "- A union is carried as raw JSON with one `As…` accessor per variant: the contract records",
        "  a union's variants but no discriminator, so a tagged struct would have to invent the tag.",
        "",
        f"Generated by Apiome · `{GO_CLIENT_SCHEMA_VERSION}`.",
        "",
    ]
    return GoClientFile(path="README.md", text="\n".join(lines).rstrip("\n") + "\n")


# ===========================================================================
# Entry point
# ===========================================================================

#: How many operations one generated client carries. Matches the client kit's own ceiling
#: (:data:`app.sdk_kit.MAX_KIT_OPERATIONS`) so a kit's Go package and its snippets cover the same
#: operations; a caller that wants a different bound passes one.
DEFAULT_MAX_OPERATIONS = 250


def _file_slug(value: str, fallback: str = "api") -> str:
    """Make a value safe as a lower-case Go filename or directory stem."""
    slug = "_".join(_words(value)) or fallback
    if slug[0].isdigit():
        slug = f"g{slug}"
    return slug


def generate_go_client(
    api: CanonicalApi,
    *,
    module_path: Optional[str] = None,
    package_name: Optional[str] = None,
    license_header: Optional[str] = None,
    user_agent: Optional[str] = None,
    max_operations: int = DEFAULT_MAX_OPERATIONS,
) -> GoClientPackage:
    """Generate a complete Go client module from a canonical model.

    The result is a pure function of its arguments: nothing here reads the clock, the environment
    or the filesystem, so two calls with the same model and the same branding produce byte-identical
    files. That is what lets the client kit keep serving a content-addressed ``ETag``.

    Args:
        api: The canonical model to generate from.
        module_path: The ``go.mod`` module path. Defaults to
            ``example.com/<package name>`` — :data:`DEFAULT_MODULE_HOST` is IANA-reserved, so a
            default can never resolve to somebody's real repository.
        package_name: The Go package name. Defaults to the API's identity name, then its title.
        license_header: A tenant's resolved licence text (SDK-3.4), rendered as a comment block at
            the top of every generated ``.go`` file and quoted in the README.
        user_agent: A tenant's resolved user-agent (SDK-3.4), baked in as ``DefaultUserAgent``.
        max_operations: How many operations get methods. The rest are reported in
            :attr:`GoClientPackage.skipped` rather than silently dropped.

    Returns:
        The :class:`GoClientPackage`.
    """
    resolved_package = go_package_name(package_name, api.identity.name if api.identity else None, api.title)
    resolved_module = go_module_path(module_path, resolved_package)
    base_url, _placeholders = resolve_server_base(api)

    names = _Names(_RESERVED_IDENTIFIERS)
    table = _TypeTable(api, names)
    models = _render_models(table, names, resolved_package, license_header)
    planner = _OperationPlanner(api, table, names, max(0, max_operations))

    schemes = declared_security_schemes(api)
    auth_file, auth_options, unrepresentable = _render_auth(resolved_package, schemes, license_header)

    files: List[GoClientFile] = [
        _render_go_mod(resolved_module, DEFAULT_GO_VERSION),
        _render_client(
            resolved_package,
            [
                "// Code generated by Apiome. DO NOT EDIT.",
                "",
                *_doc(
                    f"Package {resolved_package}",
                    f"is a generated Go client for {api.title or resolved_package}"
                    + (f" {api.version}" if api.version else "")
                    + ".",
                    api.description,
                ),
                "//",
                "// Every method takes a context.Context first and sends through an injectable Doer,",
                "// so timeouts, retries, tracing and test doubles are the caller's to choose.",
            ],
            base_url,
            user_agent,
            license_header,
        ),
        _render_errors(resolved_package, planner.typed_errors, license_header),
    ]
    if auth_file is not None:
        files.append(auth_file)
    if models is not None:
        files.append(models)

    grouped: Dict[str, List[_PlannedOperation]] = {}
    for planned in planner.planned:
        grouped.setdefault(planned.group, []).append(planned)

    stems = _Names(_RESERVED_FILE_STEMS)
    directories = _Names()
    example_groups: List[str] = []
    for group, operations in grouped.items():
        stem = stems.take(_file_slug(group))
        filename = f"{stem}.go"
        directory = directories.take(_file_slug(group))
        files.append(
            _render_operations_file(filename, group, operations, resolved_package, license_header)
        )
        files.append(
            _render_example(
                group,
                directory,
                operations,
                resolved_package,
                resolved_module,
                api.title or resolved_package,
                license_header,
            )
        )
        example_groups.append(directory)

    files.append(
        _render_readme(
            api,
            resolved_module,
            resolved_package,
            base_url,
            planner.planned,
            planner.skipped,
            auth_options,
            unrepresentable,
            planner.typed_errors,
            example_groups,
            license_header,
        )
    )
    files.sort(key=lambda item: item.path)

    return GoClientPackage(
        module_path=resolved_module,
        package_name=resolved_package,
        go_version=DEFAULT_GO_VERSION,
        files=files,
        methods=[
            GoClientMethod(
                name=planned.method_name,
                operation_id=planned.identifier,
                key=planned.op.key,
                method=planned.http_method,
                path=planned.path_template,
                group=planned.group,
            )
            for planned in planner.planned
        ],
        types=[entry.go_name for entry in table.entries],
        auth_options=sorted(auth_options),
        skipped=list(planner.skipped),
        example_groups=example_groups,
    )
