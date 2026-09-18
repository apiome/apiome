"""Where an upstream credential may go, and how it is attached — AGX-2.2 (#4534).

An upstream credential (:mod:`app.upstream_credentials`) is bound to one server URL, and this
module is the part of the vault that makes the binding mean something. It is pure: no database, no
cryptography, no network. That keeps the rule that decides whether a secret leaves the process in
one small place that can be tested exhaustively.

**What a bound server URL is.** :func:`normalize_server_url` accepts an ``https`` origin plus an
optional base path (``https://api.example.com/v1``) and nothing else: no ``user:pass@``, no query,
no fragment, no ``.``/``..`` path segments. The host is lower-cased, the default port dropped and a
trailing slash removed, so two spellings of one server are stored identically and the uniqueness of
``(toolset, server_url)`` means what it says. Plain ``http`` is refused: a credential sent over
cleartext is a credential given away.

**When a request is bound.** :func:`binds` is the only test the vault applies before handing a
secret to the invocation proxy. A request URL is bound when it has the same scheme, host and port
as the server URL, carries no userinfo, and its path is the base path or continues it on a segment
boundary (``/v1`` covers ``/v1`` and ``/v1/pets``, never ``/v10`` or ``/admin``). A path with a dot
segment, raw or percent-encoded, is refused outright: a server that normalizes ``/v1/../admin``
would otherwise receive the credential outside the base path. Every doubtful case answers *not
bound*: a credential that is not sent can be fixed later, one that is sent cannot be recalled.

**How it is attached.** :func:`build_injection` turns an opened secret into a
:class:`CredentialInjection`: an ``Authorization`` header for ``bearer`` and ``basic``, or the named
header or query parameter for ``apiKey``. :meth:`CredentialInjection.apply` writes it onto an
outgoing request and **replaces** any header or query parameter of the same name, so an agent
cannot supply a competing value, or read one back, by passing its own ``Authorization``
argument. The injection's ``repr`` never shows the secret, so it can't leak through a log line or a
traceback.
"""

from __future__ import annotations

import base64
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit

__all__ = [
    "API_KEY_IN_HEADER",
    "API_KEY_IN_QUERY",
    "API_KEY_LOCATIONS",
    "CODE_BINDING_INVALID",
    "CODE_PLACEMENT_INVALID",
    "CODE_SERVER_URL_INVALID",
    "KIND_API_KEY",
    "KIND_BASIC",
    "KIND_BEARER",
    "KINDS",
    "MAX_API_KEY_NAME_CHARS",
    "MAX_SERVER_URL_CHARS",
    "RESERVED_HEADER_NAMES",
    "BindingError",
    "CredentialInjection",
    "binds",
    "build_injection",
    "normalize_server_url",
    "validate_api_key_placement",
]

#: Credential kinds, in OpenAPI's security-scheme vocabulary. Stored verbatim (V268 CHECK).
KIND_API_KEY = "apiKey"
KIND_BEARER = "bearer"
KIND_BASIC = "basic"
KINDS: Tuple[str, ...] = (KIND_API_KEY, KIND_BEARER, KIND_BASIC)

#: Where an ``apiKey`` credential is presented. OpenAPI also allows ``cookie``; the vault does not.
API_KEY_IN_HEADER = "header"
API_KEY_IN_QUERY = "query"
API_KEY_LOCATIONS: Tuple[str, ...] = (API_KEY_IN_HEADER, API_KEY_IN_QUERY)

#: Longest accepted server URL (matches the V268 CHECK).
MAX_SERVER_URL_CHARS = 2048

#: Longest accepted header or query-parameter name (matches the V268 column).
MAX_API_KEY_NAME_CHARS = 128

#: Stable refusal codes. Each :class:`BindingError` carries one.
CODE_SERVER_URL_INVALID = "upstream-credential-server-url-invalid"
CODE_PLACEMENT_INVALID = "upstream-credential-placement-invalid"
CODE_BINDING_INVALID = "upstream-credential-binding-invalid"

#: Header names an ``apiKey`` credential may not take. Each is owned by the HTTP client or the
#: proxy, and setting one from a credential would corrupt request framing, re-route the request,
#: or smuggle a cookie jar in. Compared case-insensitively.
RESERVED_HEADER_NAMES = frozenset(
    {
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "expect",
        "host",
        "keep-alive",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)

#: RFC 9110 ``token`` — the grammar of a header field name. Matches the V268 CHECK.
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")

#: RFC 3986 unreserved characters — a query-parameter name that needs no escaping anywhere.
_QUERY_NAME = re.compile(r"^[A-Za-z0-9._~-]+$")

#: Whitespace or control characters. Never legal anywhere in a server URL.
_URL_ILLEGAL = re.compile(r"[\s\x00-\x1f\x7f]")

#: The default port per scheme, dropped on normalization and assumed when a URL omits one.
_DEFAULT_PORTS: Dict[str, int] = {"https": 443, "http": 80}

#: How many rounds of percent-decoding a path is checked through. Double-encoding
#: (``%252e%252e``) is a classic traversal smuggle. A path that is still decoding after this many
#: rounds is treated as a traversal attempt rather than trusted.
_DECODE_ROUNDS = 5


class BindingError(ValueError):
    """A server URL, placement or binding was refused.

    Attributes:
        code: A stable, machine-readable refusal code (see the ``CODE_*`` constants).

    The message never contains secret material. It may quote a server URL or header name, which
    are configuration rather than secrets.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _is_dot(segment: str) -> bool:
    """Return ``True`` when a path segment is ``.`` or ``..`` as some server would read it.

    Matrix parameters are dropped first (Tomcat reads ``..;x`` as ``..``) and the segment is
    NFKC-normalized, so full-width ``．．`` counts too.
    """
    bare = unicodedata.normalize("NFKC", segment.split(";", 1)[0])
    return bare in (".", "..")


def _has_dot_segment(path: str) -> bool:
    """Return ``True`` when a URL path contains a ``.`` or ``..`` segment, however it is encoded.

    The path is percent-decoded up to :data:`_DECODE_ROUNDS` times, backslashes count as
    separators (some servers treat them as ``/``), and each segment is read the way a lenient
    server might (:func:`_is_dot`). So ``/v1/%2e%2e/admin``, ``/v1/%252E./x``, ``/v1\\..\\x``,
    ``/v1/..;/admin`` and ``/v1/．．/admin`` are all caught. A path still decoding after the
    last round is treated as a dot segment: fail closed.

    Args:
        path: The raw path of a URL.

    Returns:
        Whether any decoding of the path has a dot segment.
    """
    candidate = path
    for _ in range(_DECODE_ROUNDS + 1):
        if any(_is_dot(segment) for segment in re.split(r"[/\\]", candidate)):
            return True
        decoded = unquote(candidate)
        if decoded == candidate:
            return False
        candidate = decoded
    return True


def _effective_port(scheme: str, port: Optional[int]) -> Optional[int]:
    """Return the port a URL actually connects to (the scheme default when none is written)."""
    return port if port is not None else _DEFAULT_PORTS.get(scheme)


def _host_of(hostname: str) -> str:
    """Normalize a parsed hostname: lower-case, no trailing dot, IPv6 literals re-bracketed."""
    host = hostname.lower().rstrip(".")
    return f"[{host}]" if ":" in host else host


def normalize_server_url(raw: Optional[str]) -> str:
    """Validate a server URL and return the single form it is stored and compared in.

    Args:
        raw: The server URL as submitted, e.g. ``https://API.example.com:443/v1/``.

    Returns:
        The normalized URL, e.g. ``https://api.example.com/v1``: lower-case host, no default
        port, no trailing slash.

    Raises:
        BindingError: ``upstream-credential-server-url-invalid`` when the URL is missing, too
            long, not ``https``, carries userinfo, a query or a fragment, has no host or a
            non-ASCII host, has an invalid port, or has a dot segment or a backslash in its path.
    """

    def refuse(reason: str) -> BindingError:
        return BindingError(CODE_SERVER_URL_INVALID, f"serverUrl {reason}")

    candidate = (raw or "").strip()
    if not candidate:
        raise refuse("is required")
    if len(candidate) > MAX_SERVER_URL_CHARS:
        raise refuse(f"is longer than {MAX_SERVER_URL_CHARS} characters")
    if _URL_ILLEGAL.search(candidate):
        raise refuse("contains whitespace or control characters")

    try:
        parts = urlsplit(candidate)
        port = parts.port
    except ValueError as exc:
        raise refuse("is not a valid URL") from exc

    scheme = parts.scheme.lower()
    if scheme != "https":
        raise refuse(
            "must be an https:// URL; a credential sent over plain HTTP is a credential disclosed"
        )
    if "@" in parts.netloc:
        raise refuse("must not embed credentials (user:pass@host); store them as the secret")
    if parts.query or parts.fragment or "?" in candidate or "#" in candidate:
        raise refuse("must not carry a query string or fragment")
    if not parts.hostname:
        raise refuse("must name a host")
    if not parts.hostname.isascii():
        raise refuse("must use an ASCII host; write internationalized names in punycode")
    if "\\" in parts.path or _has_dot_segment(parts.path):
        raise refuse("must not contain '.' or '..' path segments or backslashes")

    netloc = _host_of(parts.hostname)
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = parts.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def validate_api_key_placement(location: Optional[str], name: Optional[str]) -> Tuple[str, str]:
    """Validate where an ``apiKey`` credential is presented.

    Args:
        location: ``header`` or ``query``.
        name: The header or query-parameter name.

    Returns:
        ``(location, name)``, with the name stripped of surrounding whitespace.

    Raises:
        BindingError: ``upstream-credential-placement-invalid`` when the location is not one of
            :data:`API_KEY_LOCATIONS`, the name is missing or too long, a header name breaks the
            RFC 9110 token grammar or is one of :data:`RESERVED_HEADER_NAMES`, or a query name
            uses characters outside the RFC 3986 unreserved set.
    """
    if location not in API_KEY_LOCATIONS:
        raise BindingError(
            CODE_PLACEMENT_INVALID,
            f"an apiKey credential needs `in` set to one of {', '.join(API_KEY_LOCATIONS)}",
        )
    candidate = (name or "").strip()
    if not candidate:
        raise BindingError(CODE_PLACEMENT_INVALID, "an apiKey credential needs a `name`")
    if len(candidate) > MAX_API_KEY_NAME_CHARS:
        raise BindingError(
            CODE_PLACEMENT_INVALID, f"`name` is longer than {MAX_API_KEY_NAME_CHARS} characters"
        )
    if location == API_KEY_IN_HEADER:
        if not _HEADER_NAME.match(candidate):
            raise BindingError(
                CODE_PLACEMENT_INVALID, "`name` is not a valid HTTP header name (RFC 9110 token)"
            )
        if candidate.lower() in RESERVED_HEADER_NAMES:
            raise BindingError(
                CODE_PLACEMENT_INVALID,
                f"`{candidate}` is managed by the HTTP client and cannot carry a credential",
            )
    elif not _QUERY_NAME.match(candidate):
        raise BindingError(
            CODE_PLACEMENT_INVALID,
            "`name` must use only letters, digits and `-._~` for a query parameter",
        )
    return location, candidate


def binds(server_url: str, request_url: str) -> bool:
    """Return whether a credential bound to ``server_url`` may be sent with ``request_url``.

    Args:
        server_url: The credential's stored (normalized) server URL.
        request_url: The absolute URL the invocation proxy is about to call.

    Returns:
        ``True`` only when the request has the same scheme, host and effective port, no
        userinfo, no dot segment or backslash in its path, and a path that equals the base
        path or continues it after a ``/``. Anything unparseable is ``False``.
    """
    try:
        bound = urlsplit(server_url)
        request = urlsplit(request_url)
        bound_port = _effective_port(bound.scheme.lower(), bound.port)
        request_port = _effective_port(request.scheme.lower(), request.port)
    except (ValueError, AttributeError, TypeError):
        return False

    if not bound.hostname or not request.hostname:
        return False
    if request.scheme.lower() != bound.scheme.lower():
        return False
    if "@" in request.netloc:
        return False
    if _host_of(request.hostname) != _host_of(bound.hostname):
        return False
    if request_port != bound_port:
        return False

    path = request.path or "/"
    if "\\" in path or _has_dot_segment(path):
        return False
    base = bound.path.rstrip("/")
    if not base:
        return True
    return path == base or path.startswith(base + "/")


@dataclass(frozen=True)
class CredentialInjection:
    """An opened credential, ready to attach to one outgoing request.

    Lives only in memory, for the duration of one invocation. Nothing that logs, audits or
    persists should receive it; its ``repr`` shows the credential id and the *names* it sets,
    never a value.

    Attributes:
        credential_id: The vault row the secret came from, for the metadata-only use audit.
        headers: ``(name, value)`` pairs to set on the request.
        query: ``(name, value)`` pairs to set on the request URL.
    """

    credential_id: str
    headers: Tuple[Tuple[str, str], ...] = field(default=(), repr=False)
    query: Tuple[Tuple[str, str], ...] = field(default=(), repr=False)

    def __repr__(self) -> str:
        """Describe the injection by the names it sets; never by a value."""
        header_names = [name for name, _ in self.headers]
        query_names = [name for name, _ in self.query]
        return (
            f"CredentialInjection(credential_id={self.credential_id!r}, "
            f"headers={header_names!r}, query={query_names!r})"
        )

    __str__ = __repr__

    def apply(self, url: str, headers: Mapping[str, str]) -> Tuple[str, Dict[str, str]]:
        """Attach the credential to a request, replacing any same-named header or parameter.

        Replacement rather than addition is the point: an agent that passes its own
        ``Authorization`` header or ``api_key`` parameter through a tool argument must not end
        up sending a second, competing credential, or have its own value win.

        Other query parameters keep their exact bytes; only pairs whose decoded name equals a
        credential parameter's name are dropped before the credential's own pair is appended.

        Args:
            url: The absolute request URL. Call :func:`binds` first; this method does not check.
            headers: The request's headers as built so far.

        Returns:
            ``(url, headers)`` with the credential attached. The input mapping is not modified.
        """
        merged: Dict[str, str] = {
            key: value
            for key, value in headers.items()
            if all(key.lower() != name.lower() for name, _ in self.headers)
        }
        for name, value in self.headers:
            merged[name] = value

        if not self.query:
            return url, merged

        # The fragment comes off first: in ``/p#frag`` there is no query, and a ``?`` after the
        # ``#`` would be part of the fragment, not a query string.
        without_fragment, hash_mark, fragment = url.partition("#")
        base, _, query_string = without_fragment.partition("?")
        names = {name for name, _ in self.query}

        def foreign(pair: str) -> bool:
            return bool(pair) and unquote(pair.partition("=")[0].replace("+", " ")) not in names

        # Some servers also split on ``;``, so a same-named pair hiding behind one is dropped too.
        kept = []
        for pair in query_string.split("&"):
            parts = [part for part in pair.split(";") if foreign(part)]
            if parts:
                kept.append(";".join(parts))
        kept.extend(f"{quote(name, safe='')}={quote(value, safe='')}" for name, value in self.query)
        rebuilt = f"{base}?{'&'.join(kept)}"
        if hash_mark:
            rebuilt = f"{rebuilt}#{fragment}"
        return rebuilt, merged


def build_injection(
    *,
    credential_id: str,
    kind: str,
    api_key_in: Optional[str],
    api_key_name: Optional[str],
    secret: Mapping[str, str],
) -> CredentialInjection:
    """Turn an opened secret into the header or parameter that carries it.

    Args:
        credential_id: The vault row the secret came from.
        kind: ``apiKey``, ``bearer`` or ``basic``.
        api_key_in: For ``apiKey``: ``header`` or ``query``.
        api_key_name: For ``apiKey``: the header or parameter name.
        secret: The opened payload: ``{"value"}``, ``{"token"}`` or ``{"username", "password"}``.

    Returns:
        The injection. ``bearer`` sets ``Authorization: Bearer <token>``; ``basic`` sets
        ``Authorization: Basic base64(username:password)`` (RFC 7617, UTF-8); ``apiKey`` sets
        the named header or query parameter to the value.

    Raises:
        BindingError: ``upstream-credential-binding-invalid`` when the payload does not have the
            shape its kind needs, or the kind or placement is unknown. The message names the
            missing field, never a value.
    """

    def text(key: str) -> str:
        value = secret.get(key)
        if not isinstance(value, str):
            raise BindingError(
                CODE_BINDING_INVALID, f"stored {kind} credential has no `{key}` to present"
            )
        return value

    if kind == KIND_BEARER:
        return CredentialInjection(
            credential_id=credential_id,
            headers=(("Authorization", f"Bearer {text('token')}"),),
        )
    if kind == KIND_BASIC:
        pair = f"{text('username')}:{text('password')}".encode("utf-8")
        encoded = base64.b64encode(pair).decode("ascii")
        return CredentialInjection(
            credential_id=credential_id, headers=(("Authorization", f"Basic {encoded}"),)
        )
    if kind == KIND_API_KEY:
        location, name = validate_api_key_placement(api_key_in, api_key_name)
        value = text("value")
        if location == API_KEY_IN_HEADER:
            return CredentialInjection(credential_id=credential_id, headers=((name, value),))
        return CredentialInjection(credential_id=credential_id, query=((name, value),))
    raise BindingError(CODE_BINDING_INVALID, f"unknown credential kind {kind!r}")
