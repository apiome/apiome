"""Reader for Bruno collections — MFI-32.4 (#4406).

Bruno is a git-native API client: a collection is a **folder** — ``bruno.json`` at its root, one
``.bru`` file per saved request in a folder tree, optional ``collection.bru`` / ``folder.bru``
files holding shared headers, auth and variables, and ``environments/<name>.bru`` files. It arrives
as an archive (MFI-29.1) or straight from a repository (MFI-29.3); both reach this reader as a
fileset. A single ``.bru`` request can also be pasted or uploaded on its own.

The ``.bru`` grammar is tokenised by :mod:`app.bru_lang`; this module gives the blocks their
meaning and turns every saved request into a concrete :class:`~app.inferred_spec.HttpObservation`
for the shared inferred-spec engine, plus what the engine has no slot for — the folder a request
sits in, the auth it resolves to, its body's media type, the server variables its URL is written
against and the parameter defaults the environments supply.

**Identical from every intake.** Every path this reader records is relative to the directory that
holds ``bruno.json``, and nothing is taken from the upload's label, so a collection zipped inside a
``my-api/`` folder and the same collection selected from a repository (whose selection prefix is
stripped) produce the same model — and therefore the same fingerprint.

**Credentials never leave this module.** Auth blocks are read as *scheme and public facts only*
(token, password, client-secret and API-key value fields are never read). Every other value passes
the shared secret-scrub gate; a header, parameter or form field whose name says it holds a secret is
redacted outright; a variable listed in an environment's ``vars:secret`` (or whose name says it is a
credential) never becomes a default; ``{{process.env.*}}`` values come from a ``.env`` file that
intake never reads. Scripts, tests and assertions are never run — they are listed in the coverage
ledger.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark.
* ``INPUT_TRUNCATED`` — a ``.bru`` block (or ``'''`` value) is never closed, or ``bruno.json`` ends
  inside a value.
* ``INPUT_MALFORMED`` — a ``.bru`` line outside any block, a dictionary line with no ``:``, a request
  with no method block, or a ``bruno.json`` that is not a JSON object.
* ``FORMAT_MISMATCH`` — an upload with neither ``bruno.json`` nor a ``.bru`` request.
* ``INPUT_SEMANTIC_INVALID`` — a collection with no HTTP requests, ``.bru`` files with no
  ``bruno.json`` beside them, a request with no URL (or one written only as an undefined
  variable), or a ``bruno.json`` / environment / folder file uploaded on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit

from .bru_lang import BruBlock, BruSyntaxError, looks_like_bru, parse_bru
from .client_collection import SECRET_NAME_RE, check_client_text, load_client_json, scrub_named, scrub_value
from .inferred_spec import HttpObservation

__all__ = [
    "AUTH_SCHEMES",
    "FORMAT_KEY",
    "BrunoAuth",
    "BrunoDocument",
    "BrunoParseError",
    "BrunoRequest",
    "BrunoVariable",
    "METHODS",
    "detect_bruno",
    "parse_bruno_fileset",
    "parse_bruno_text",
]

#: The registry key of the format.
FORMAT_KEY = "bruno"

#: The method blocks a request file can carry.
METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "connect", "trace")

#: Bruno auth ``mode`` → the canonical scheme :mod:`app.canonical_security` reads. Signing modes
#: (AWS SigV4, NTLM, WS-Security) are a generic ``authorization`` requirement.
AUTH_SCHEMES: Mapping[str, str] = {
    "basic": "basic",
    "bearer": "bearer",
    "digest": "digest",
    "oauth2": "oauth2",
    "apikey": "apiKey",
    "awsv4": "authorization",
    "ntlm": "authorization",
    "wsse": "authorization",
}

#: The Bruno ``body`` mode → the media type the body is sent as.
_BODY_MEDIA_TYPES: Mapping[str, str] = {
    "json": "application/json",
    "text": "text/plain",
    "xml": "application/xml",
    "sparql": "application/sparql-query",
    "formurlencoded": "application/x-www-form-urlencoded",
    "multipartform": "multipart/form-data",
    "graphql": "application/json",
}

#: The ``.bru`` files that are not requests.
_COLLECTION_FILE = "collection.bru"
_FOLDER_FILE = "folder.bru"
_ENVIRONMENTS_DIR = "environments"

_NAME = r"[A-Za-z_$][A-Za-z0-9_$.\-]*"
_VARIABLE_RE = re.compile(r"\{\{\s*(" + _NAME + r")\s*\}\}")
_LEADING_VARIABLE_RE = re.compile(r"^\s*\{\{\s*(" + _NAME + r")\s*\}\}")
_WHOLE_VARIABLE_RE = re.compile(r"^\s*\{\{\s*(" + _NAME + r")\s*\}\}\s*$")
_BARE_JSON_VARIABLE_RE = re.compile(r'(?<!")(\{\{\s*' + _NAME + r'\s*\}\})(?!")')
_PATH_PARAM_RE = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_\-]*)(?=/|$)")
_FILE_VALUE_RE = re.compile(r"^@file\(")
_PROCESS_ENV = "process.env."
_MAX_VARIABLE_DEPTH = 5


class BrunoParseError(ValueError):
    """Raised when a Bruno upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrunoAuth:
    """A resolved auth declaration — scheme and public facts only, never a credential.

    Attributes:
        type: The Bruno auth mode (``bearer``, ``basic``, ``oauth2``, ``apikey`` …).
        scheme: The canonical scheme identifier (see :data:`AUTH_SCHEMES`).
        declared_at: ``collection``, the folder path, or ``request``.
        grant_type: An OAuth 2 grant type, when stated.
        token_url: An OAuth 2 token / authorization URL, when stated (scrubbed).
        scopes: OAuth 2 scopes, when stated.
        key_name: An API key's header / query parameter name (never its value).
        key_location: Where an API key is sent (``header``, ``queryparams``).
    """

    type: str
    scheme: str
    declared_at: str
    grant_type: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Tuple[str, ...] = ()
    key_name: Optional[str] = None
    key_location: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag, leaving unset facts out."""
        record: Dict[str, Any] = {"type": self.type, "scheme": self.scheme, "declared_at": self.declared_at}
        for key, value in (
            ("grant_type", self.grant_type),
            ("token_url", self.token_url),
            ("key_name", self.key_name),
            ("key_location", self.key_location),
        ):
            if value:
                record[key] = value
        if self.scopes:
            record["scopes"] = list(self.scopes)
        return record


@dataclass(frozen=True)
class BrunoRequest:
    """The facts about one saved request that the inferred-spec engine has no slot for.

    Attributes:
        name: The request's name (``meta.name``, else its file name).
        method: The upper-cased HTTP method.
        url: The URL handed to the engine.
        folder: The folder path from the collection root (empty at the root).
        auth: The auth the request resolves to after inheritance, or ``None``.
        content_type: The body's media type, when the request has a body.
        file: The ``.bru`` file, relative to the collection root.
        has_script: Whether a script or ``vars:post-response`` applies (own, a folder's or the
            collection's).
        has_tests: Whether ``tests`` or ``assert`` blocks apply.
        uses_process_env: Whether a value reads ``{{process.env.*}}``.
        defaults: ``(location, name, value)`` per query / header parameter written as a whole
            variable whose (non-secret) value is known; header names lower-cased.
    """

    name: str
    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[BrunoAuth]
    content_type: Optional[str]
    file: str = ""
    has_script: bool = False
    has_tests: bool = False
    uses_process_env: bool = False
    defaults: Tuple[Tuple[str, str, str], ...] = ()


@dataclass(frozen=True)
class BrunoVariable:
    """A variable the collection defines — its *name* and where, never its value.

    Attributes:
        name: The variable name.
        source: ``environment:<name>``, ``collection``, ``folder:<path>`` or ``request:<name>``.
        secret: Whether the value is a credential (``vars:secret``, or by its name).
    """

    name: str
    source: str
    secret: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        return {"name": self.name, "source": self.source, "secret": self.secret}


@dataclass
class BrunoDocument:
    """A parsed Bruno upload, ready for the inferred-spec engine.

    Attributes:
        title: The collection's ``name`` (or the request's, for a single file).
        observations: One concrete request sample per saved HTTP request.
        requests: Per-request facts, aligned with ``observations``.
        server_variables: Server URL variable → its default (``None`` when undefined or secret).
        variables: Every variable the collection defines, by name.
        environments: The environment names read, in the order their values are consulted.
        skipped: Construct id → the names of what was left out (gRPC / WebSocket requests).
        bruno_version: ``bruno.json``'s ``version``, when there is one.
    """

    title: str
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[BrunoRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[BrunoVariable] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    skipped: Dict[str, List[str]] = field(default_factory=dict)
    bruno_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading and detection
# ---------------------------------------------------------------------------


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def _error(message: str, code: str) -> BrunoParseError:
    return BrunoParseError(message, code=code)


def _is_bruno_json(document: Any) -> bool:
    return (
        isinstance(document, Mapping)
        and document.get("type") == "collection"
        and isinstance(document.get("version"), str)
        and "name" in document
    )


def _blocks(text: str, label: Optional[str]) -> List[BruBlock]:
    """Run the shared text checks and tokenise one ``.bru`` file."""
    check_client_text(text, label, product="Bruno", syntax=".bru", error=_error)
    try:
        return parse_bru(text, label=label)
    except BruSyntaxError as exc:
        raise _error(str(exc), exc.code) from exc


def _first(blocks: Sequence[BruBlock], name: str) -> Optional[BruBlock]:
    return next((block for block in blocks if block.name == name), None)


def _method_block(blocks: Sequence[BruBlock]) -> Optional[BruBlock]:
    return next((block for block in blocks if block.name in METHODS), None)


def detect_bruno(text: str) -> Optional[Tuple[str, float]]:
    """Recognise ``bruno.json`` or a ``.bru`` file from its text.

    Args:
        text: The decoded upload.

    Returns:
        ``(reason, confidence)`` — a request ``.bru`` and ``bruno.json`` are claimed firmly, a
        ``collection.bru`` / ``folder.bru`` / environment file only weakly — or ``None``.
    """
    head = text.lstrip()
    if head.startswith("{"):
        try:
            document = json.loads(text)
        except ValueError:
            return None
        return ("Bruno collection manifest (bruno.json)", 0.98) if _is_bruno_json(document) else None
    if not looks_like_bru(text):
        return None
    try:
        blocks = parse_bru(text)
    except BruSyntaxError:
        return None
    names = {block.name for block in blocks}
    if "meta" in names and _method_block(blocks) is not None:
        return "Bruno request (.bru meta + method block)", 0.96
    if names & {"meta", "vars", "vars:secret", "auth", "headers"}:
        return "Bruno collection, folder or environment file (.bru)", 0.4
    return None


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


@dataclass
class _Scope:
    """Variable values, closest layer first; a secret variable is defined but valueless."""

    layers: Tuple[Dict[str, str], ...] = ()
    secret: frozenset = frozenset()

    def child(self, values: Mapping[str, str]) -> "_Scope":
        """A scope with ``values`` in front (a secret-named one defined but valueless)."""
        if not values:
            return self
        secret = {name for name in values if SECRET_NAME_RE.search(name)}
        return _Scope(layers=(dict(values),) + self.layers, secret=self.secret | secret)

    def lookup(self, name: str) -> Tuple[bool, Optional[str]]:
        """Return ``(defined, value)``; ``{{process.env.*}}`` is never defined here."""
        if name.startswith(_PROCESS_ENV):
            return False, None
        for layer in self.layers:
            if name in layer:
                return True, (None if name in self.secret else layer[name])
        return False, None

    def resolve(self, text: str) -> Optional[str]:
        """Substitute every ``{{variable}}``, or ``None`` when one has no value."""
        current = text
        for _ in range(_MAX_VARIABLE_DEPTH):
            missing = False

            def _replace(match: "re.Match[str]") -> str:
                nonlocal missing
                defined, value = self.lookup(match.group(1))
                if not defined or value is None:
                    missing = True
                    return match.group(0)
                return value

            current = _VARIABLE_RE.sub(_replace, current)
            if missing:
                return None
            if not _VARIABLE_RE.search(current):
                return current
        return None


def _param_name(variable: str) -> str:
    """A variable's name as a path / server parameter (``process.env.HOST`` → ``process_env_HOST``)."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", variable.lstrip("$"))


def _scrub_named(name: str, value: str) -> str:
    """Scrub a header / parameter / form value; a whole ``{{variable}}`` reference is kept."""
    return scrub_named(name, value, reference=_WHOLE_VARIABLE_RE)


def _vars(blocks: Sequence[BruBlock]) -> Dict[str, str]:
    """The enabled ``vars`` / ``vars:pre-request`` values of a file."""
    values: Dict[str, str] = {}
    for name in ("vars", "vars:pre-request"):
        block = _first(blocks, name)
        if block is not None:
            values.update(block.values())
    return values


def _uses_process_env(*values: Optional[str]) -> bool:
    return any(isinstance(value, str) and "{{process.env." in value.replace(" ", "") for value in values)


# ---------------------------------------------------------------------------
# Auth, bodies, URLs
# ---------------------------------------------------------------------------


def _read_auth(blocks: Sequence[BruBlock], mode: Optional[str], declared_at: str) -> Tuple[bool, Optional[BrunoAuth]]:
    """Read the auth a file declares.

    Args:
        blocks: The file's blocks (for ``auth:<mode>``).
        mode: The auth mode — a request's method-block ``auth``, or a collection / folder file's
            ``auth { mode }``. ``None`` or ``inherit`` inherits.
        declared_at: Where it is written, for provenance.

    Returns:
        ``(inherits, auth)``.
    """
    mode = (mode or "").strip().lower()
    if mode in ("", "inherit"):
        return True, None
    if mode == "none":
        return False, None
    detail = _first(blocks, f"auth:{mode}")
    values = detail.values() if detail is not None else {}
    grant_type = token_url = key_name = key_location = None
    scopes: Tuple[str, ...] = ()
    if mode == "oauth2":
        grant_type = values.get("grant_type") or None
        for key in ("access_token_url", "authorization_url"):
            endpoint = values.get(key, "")
            if endpoint and not _WHOLE_VARIABLE_RE.match(endpoint):
                token_url = scrub_value(endpoint)
                break
        scopes = tuple(scope for scope in re.split(r"[\s,]+", values.get("scope", "")) if scope)
    if mode == "apikey":
        key = values.get("key", "")
        if key and not _WHOLE_VARIABLE_RE.match(key):
            key_name = key  # the header / parameter *name*; its value is never read
        key_location = values.get("placement") or "header"
    return False, BrunoAuth(
        type=mode,
        scheme=AUTH_SCHEMES.get(mode, "authorization"),
        declared_at=declared_at,
        grant_type=grant_type,
        token_url=token_url,
        scopes=scopes,
        key_name=key_name,
        key_location=key_location,
    )


def _json_text(raw: str) -> str:
    """Scrub a JSON body, quoting bare ``{{variables}}`` when that is what keeps it parseable."""
    scrubbed = scrub_value(raw)
    try:
        json.loads(scrubbed)
    except json.JSONDecodeError:
        scrubbed = _BARE_JSON_VARIABLE_RE.sub(lambda match: json.dumps(match.group(1)), scrubbed)
    return scrubbed


def _body(blocks: Sequence[BruBlock], mode: str) -> Tuple[Optional[str], Optional[str], str]:
    """Return ``(content_type, body_text, raw_text)`` for a request's ``body`` mode (bodies as declared).

    ``raw_text`` is the unscrubbed text, used only to notice ``{{process.env.*}}``.
    """
    mode = mode.strip().lower().replace("-", "")
    media_type = _BODY_MEDIA_TYPES.get(mode)
    if media_type is None:
        return None, None, ""
    if mode in ("formurlencoded", "multipartform"):
        block = _first(blocks, "body:form-urlencoded" if mode == "formurlencoded" else "body:multipart-form")
        if block is None:
            return media_type, None, ""
        fields = {
            key: ("" if _FILE_VALUE_RE.match(value) else _scrub_named(key, value))
            for key, value in block.values().items()
        }
        raw = "\n".join(block.values().values())
        return media_type, (json.dumps(fields, sort_keys=True) if fields else None), raw
    if mode == "graphql":
        query = _first(blocks, "body:graphql")
        if query is None or not query.text.strip():
            return None, None, ""
        payload: Dict[str, Any] = {"query": scrub_value(query.text)}
        variables = _first(blocks, "body:graphql:vars")
        if variables is not None and variables.text.strip():
            try:
                payload["variables"] = json.loads(_json_text(variables.text))
            except json.JSONDecodeError:
                pass  # unparseable variables infer nothing; the query alone is kept
        raw = query.text + (variables.text if variables is not None else "")
        return media_type, json.dumps(payload, sort_keys=True), raw
    block = _first(blocks, f"body:{mode}")
    if block is None or not block.text.strip():
        return media_type, None, ""
    text = _json_text(block.text) if mode == "json" else scrub_value(block.text)
    return media_type, text, block.text


def _request_url(
    url: str, scope: _Scope, server_variables: Dict[str, Optional[str]], label: str
) -> Tuple[str, List[Tuple[str, str]]]:
    """Turn a saved URL into the engine's URL plus the query pairs written into it.

    A URL starting with ``{{variable}}`` is a server template: the variable becomes a server
    variable whose default is resolved from the scope unless it is secret. Every other variable and
    ``:name`` segment inside the path is a path parameter.

    Raises:
        BrunoParseError: ``INPUT_SEMANTIC_INVALID`` for an empty URL or one written only as a
            variable nothing defines.
    """
    url = url.strip()
    if not url:
        raise _error(f"{label} has no URL", "INPUT_SEMANTIC_INVALID")
    leading = _LEADING_VARIABLE_RE.match(url)
    if leading:
        name = leading.group(1)
        rest = url[leading.end() :]
        defined, value = scope.lookup(name)
        if not rest.strip("/") and not rest.startswith("?") and not defined:
            raise _error(
                f"{label} has a URL written only as `{{{{{name}}}}}`, which nothing in the collection "
                "defines — its path cannot be known",
                "INPUT_SEMANTIC_INVALID",
            )
        resolved = scope.resolve(value) if isinstance(value, str) else None
        server = _param_name(name)
        server_variables.setdefault(server, None)
        if resolved is not None and server_variables[server] is None:
            server_variables[server] = scrub_value(resolved)
        url = rest if rest.startswith("/") else "/" + rest
    url = _VARIABLE_RE.sub(lambda match: "{" + _param_name(match.group(1)) + "}", url)
    parts = urlsplit(url if "://" in url or url.startswith("/") else f"http://{url}")
    path = _PATH_PARAM_RE.sub(lambda match: "{" + match.group(1) + "}", parts.path or "/")
    query = [(key, _scrub_named(key, value)) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    if parts.netloc:
        host = parts.netloc.rsplit("@", 1)[-1]  # userinfo is a credential, never kept
        return f"{parts.scheme or 'http'}://{host}{path}", query
    return path, query


# ---------------------------------------------------------------------------
# Reading the collection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Context:
    """What a request inherits from the collection and the folders above it."""

    path: Tuple[str, ...]
    auth: Optional[BrunoAuth]
    headers: Tuple[Tuple[str, str], ...]
    has_script: bool
    has_tests: bool
    scope: _Scope


def _settings(
    blocks: Sequence[BruBlock], context: _Context, *, path: Tuple[str, ...], declared_at: str, own_vars: bool = True
) -> _Context:
    """The context a ``collection.bru`` / ``folder.bru`` file passes down.

    ``own_vars=False`` leaves the file's variables out of the scope — the collection's sit *behind*
    the environment (Bruno's precedence: request > folder > environment > collection), so they are
    layered by the caller instead.
    """
    auth_block = _first(blocks, "auth")
    inherits, own = _read_auth(blocks, auth_block.values().get("mode") if auth_block else None, declared_at)
    headers = {key.lower(): (key, value) for key, value in context.headers}
    header_block = _first(blocks, "headers")
    for key, value in (header_block.values() if header_block else {}).items():
        headers[key.lower()] = (key, value)
    return _Context(
        path=path,
        auth=context.auth if inherits else own,
        headers=tuple(headers[key] for key in sorted(headers)),
        has_script=context.has_script or _has_script(blocks),
        has_tests=context.has_tests or _has_tests(blocks),
        scope=context.scope.child(_vars(blocks)) if own_vars else context.scope,
    )


def _has_script(blocks: Sequence[BruBlock]) -> bool:
    return any(
        block.name in ("script:pre-request", "script:post-response")
        and block.text.strip()
        or block.name == "vars:post-response"
        and block.entries
        for block in blocks
    )


def _has_tests(blocks: Sequence[BruBlock]) -> bool:
    return any(
        block.name == "tests" and block.text.strip() or block.name == "assert" and block.entries for block in blocks
    )


@dataclass
class _Reader:
    """Reads request files into observations, sharing one server table."""

    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[BrunoRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[BrunoVariable] = field(default_factory=list)
    skipped: Dict[str, List[str]] = field(default_factory=dict)

    def read_request(self, blocks: Sequence[BruBlock], context: _Context, *, file: str, stem: str) -> None:
        """Read one request file into an observation (or record it as a non-HTTP request)."""
        meta = _first(blocks, "meta")
        meta_values = meta.values() if meta else {}
        name = meta_values.get("name") or stem
        label = f"Request {name!r}"
        request_type = (meta_values.get("type") or "http").strip().lower()
        if request_type not in ("http", "graphql"):
            self.skipped.setdefault(f"bruno.{request_type}_request", []).append(name)
            return
        method_block = _method_block(blocks)
        if method_block is None:
            raise _error(f"{label} has no method block (`get {{` … `}}`){_where(file or None)}", "INPUT_MALFORMED")
        method_values = method_block.values()
        own_vars = _vars(blocks)
        scope = context.scope.child(own_vars)
        for variable in sorted(own_vars):
            self.variables.append(
                BrunoVariable(name=variable, source=f"request:{name}", secret=bool(SECRET_NAME_RE.search(variable)))
            )
        raw_url = method_values.get("url", "")
        url, url_query = _request_url(raw_url, scope, self.server_variables, label)
        inherits, own = _read_auth(blocks, method_values.get("auth"), "request")
        auth = context.auth if inherits else own

        defaults: List[Tuple[str, str, str]] = []

        def _default(location: str, key: str, value: str) -> None:
            whole = _WHOLE_VARIABLE_RE.match(value)
            if not whole:
                return
            resolved = scope.resolve(value)
            if resolved is not None and not SECRET_NAME_RE.search(key) and not SECRET_NAME_RE.search(whole.group(1)):
                defaults.append((location, key.lower() if location == "header" else key, scrub_value(resolved)))

        merged: Dict[str, Tuple[str, str]] = {key.lower(): (key, value) for key, value in context.headers}
        header_block = _first(blocks, "headers")
        own_headers = header_block.values() if header_block else {}
        for key, value in own_headers.items():
            merged[key.lower()] = (key, value)  # a request's own header wins
        content_type, body, raw_body = _body(blocks, method_values.get("body", "none"))
        if content_type and "content-type" not in merged:
            merged["content-type"] = ("Content-Type", content_type)
        for key, value in merged.values():
            _default("header", key, value)
        headers = tuple((key, _scrub_named(key, value)) for key, value in (merged[k] for k in sorted(merged)))

        query_block = _first(blocks, "params:query")
        listed = list(query_block.values().items()) if query_block else []
        names = {key for key, _ in listed}
        for key, value in listed:
            _default("query", key, value)
        query = [(key, _scrub_named(key, value)) for key, value in listed] + [
            (key, value) for key, value in url_query if key not in names
        ]
        observation = HttpObservation(
            method=method_block.name.upper(),
            url=url,
            headers=headers,
            query=tuple(query),
            request_body=body,
            source_location=file or None,
            source_label=name,
            source_file=file or None,
        )
        self.observations.append(observation)
        self.requests.append(
            BrunoRequest(
                name=name,
                method=observation.method,
                url=url,
                folder=context.path,
                auth=auth,
                content_type=content_type,
                file=file,
                has_script=context.has_script or _has_script(blocks),
                has_tests=context.has_tests or _has_tests(blocks),
                uses_process_env=_uses_process_env(
                    raw_url, raw_body, *own_headers.values(), *(value for _, value in listed)
                ),
                defaults=tuple(sorted(set(defaults))),
            )
        )


def _environments(members: Mapping[str, str]) -> Tuple[List[str], Dict[str, str], set, List[BrunoVariable]]:
    """Read ``environments/*.bru`` (collection-relative keys), in file-name order.

    Returns:
        ``(names, values, secret_names, variables)`` — the first environment that defines a
        variable gives its value.
    """
    names: List[str] = []
    values: Dict[str, str] = {}
    secret: set = set()
    variables: List[BrunoVariable] = []
    for path in sorted(members):
        parts = PurePosixPath(path)
        if len(parts.parts) != 2 or parts.parts[0] != _ENVIRONMENTS_DIR or parts.suffix != ".bru":
            continue
        env = parts.stem
        names.append(env)
        blocks = _blocks(members[path], path)
        listed_secret = {entry.key for block in blocks if block.name == "vars:secret" for entry in block.entries}
        for key, value in _vars(blocks).items():
            is_secret = key in listed_secret or bool(SECRET_NAME_RE.search(key))
            values.setdefault(key, value)
            if is_secret:
                secret.add(key)
            variables.append(BrunoVariable(name=key, source=f"environment:{env}", secret=is_secret))
        for key in sorted(listed_secret - set(_vars(blocks))):
            secret.add(key)  # a secret's value lives on the user's machine, never in the file
            variables.append(BrunoVariable(name=key, source=f"environment:{env}", secret=True))
    return names, values, secret, variables


def _collection_members(members: Mapping[str, str], root: Optional[str]) -> Tuple[Optional[str], Dict[str, str]]:
    """Find ``bruno.json`` and re-key the collection's members relative to its directory.

    Returns:
        ``(bruno.json text or None, members keyed collection-relative)``. Members outside the
        collection directory are dropped.
    """
    manifests = sorted(
        (path for path in members if PurePosixPath(path).name == "bruno.json"),
        key=lambda path: (path != root, path.count("/"), path),
    )
    if not manifests:
        return None, dict(members)
    manifest = manifests[0]
    base = str(PurePosixPath(manifest).parent)
    prefix = "" if base == "." else base + "/"
    relative = {path[len(prefix) :]: text for path, text in members.items() if path.startswith(prefix)}
    return relative.pop("bruno.json"), relative


def _build(manifest_text: Optional[str], members: Mapping[str, str], *, label: Optional[str]) -> BrunoDocument:
    """Read a collection (``bruno.json`` + collection-relative members) into one document."""
    manifest: Dict[str, Any] = {}
    if manifest_text is not None:
        loaded = load_client_json(manifest_text, "bruno.json", product="Bruno", error=_error)
        if not isinstance(loaded, Mapping):
            raise _error("bruno.json must be a JSON object", "INPUT_MALFORMED")
        manifest = dict(loaded)
    ignore = [str(item).strip("/") for item in manifest.get("ignore") or [] if isinstance(item, str)]

    def _ignored(path: str) -> bool:
        return any(path == item or path.startswith(item + "/") for item in ignore)

    bru = {path: text for path, text in members.items() if path.endswith(".bru") and not _ignored(path)}
    env_names, env_values, env_secret, env_variables = _environments(bru)
    collection_blocks = _blocks(bru[_COLLECTION_FILE], _COLLECTION_FILE) if _COLLECTION_FILE in bru else []
    collection_vars = _vars(collection_blocks)
    base_scope = _Scope(
        layers=(env_values, collection_vars),
        secret=frozenset(env_secret | {name for name in collection_vars if SECRET_NAME_RE.search(name)}),
    )
    root_context = _settings(
        collection_blocks,
        _Context(path=(), auth=None, headers=(), has_script=False, has_tests=False, scope=base_scope),
        path=(),
        declared_at="collection",
        own_vars=False,
    )
    reader = _Reader(variables=list(env_variables))
    reader.variables.extend(
        BrunoVariable(name=key, source="collection", secret=bool(SECRET_NAME_RE.search(key)))
        for key in sorted(collection_vars)
    )

    contexts: Dict[str, _Context] = {"": root_context}

    def _context_for(directory: str) -> _Context:
        if directory in contexts:
            return contexts[directory]
        parent = str(PurePosixPath(directory).parent)
        parent_context = _context_for("" if parent == "." else parent)
        folder_file = f"{directory}/{_FOLDER_FILE}"
        blocks = _blocks(bru[folder_file], folder_file) if folder_file in bru else []
        meta = _first(blocks, "meta")
        display = (meta.values().get("name") if meta else None) or PurePosixPath(directory).name
        path = parent_context.path + (display,)
        context = _settings(blocks, parent_context, path=path, declared_at=" / ".join(path))
        for key in sorted(_vars(blocks)):
            reader.variables.append(
                BrunoVariable(name=key, source=f"folder:{' / '.join(path)}", secret=bool(SECRET_NAME_RE.search(key)))
            )
        contexts[directory] = context
        return context

    for path in sorted(bru):
        pure = PurePosixPath(path)
        if pure.name in (_COLLECTION_FILE, _FOLDER_FILE) or (
            pure.parts[0] == _ENVIRONMENTS_DIR and len(pure.parts) == 2
        ):
            continue
        directory = "" if str(pure.parent) == "." else str(pure.parent)
        reader.read_request(_blocks(bru[path], path), _context_for(directory), file=path, stem=pure.stem)

    if not reader.observations:
        other = sorted(k.split(".", 1)[1].replace("_", " ") for k in reader.skipped)
        hint = f" (it has {' and '.join(other)}s, which are not HTTP requests)" if other else ""
        raise _error(f"The collection has no HTTP requests to import{hint}", "INPUT_SEMANTIC_INVALID")
    return BrunoDocument(
        title=str(manifest.get("name") or "").strip() or "Bruno collection",
        observations=reader.observations,
        requests=reader.requests,
        server_variables=reader.server_variables,
        variables=sorted(set(reader.variables), key=lambda var: (var.name, var.source)),
        environments=env_names,
        skipped={construct: sorted(names) for construct, names in sorted(reader.skipped.items())},
        bruno_version=str(manifest.get("version")) if manifest.get("version") is not None else None,
    )


def parse_bruno_text(raw: str, *, source_label: Optional[str] = None) -> BrunoDocument:
    """Parse one uploaded file: a single ``.bru`` request.

    Args:
        raw: The decoded upload.
        source_label: The filename or paste label (used only in messages).

    Returns:
        A one-request document named after the request.

    Raises:
        BrunoParseError: With the taxonomy code; ``bruno.json`` or an environment / folder /
            collection file uploaded alone is ``INPUT_SEMANTIC_INVALID``.
    """
    if raw.lstrip().startswith("{"):
        document = load_client_json(raw, source_label, product="Bruno", error=_error)
        if _is_bruno_json(document):
            raise _error(
                "This is a Bruno collection's bruno.json — upload the whole collection folder as an archive "
                "(or import it from git) so its .bru requests come with it",
                "INPUT_SEMANTIC_INVALID",
            )
        raise _error(f"The upload{_where(source_label)} is not a Bruno collection", "FORMAT_MISMATCH")
    blocks = _blocks(raw, source_label)
    if _method_block(blocks) is None:
        raise _error(
            f"The upload{_where(source_label)} is a Bruno collection, folder or environment file, not a "
            "request — upload it together with the collection that uses it",
            "INPUT_SEMANTIC_INVALID",
        )
    stem = PurePosixPath(source_label).stem if source_label else "request"
    return _build(None, {f"{stem}.bru": raw}, label=source_label)


def parse_bruno_fileset(
    members: Mapping[str, str], *, root: Optional[str] = None, source_label: Optional[str] = None
) -> BrunoDocument:
    """Parse a Bruno collection folder (from an archive or a git selection).

    The directory holding ``bruno.json`` is the collection root: members are re-keyed relative to
    it (so the archive's wrapping folder or a repository's selection prefix never reaches the
    model) and members outside it are ignored, as are paths ``bruno.json`` lists under ``ignore``.

    Args:
        members: Member text keyed by path.
        root: The root member's path (``bruno.json`` when detection chose it).
        source_label: The upload's label (used only in messages).

    Returns:
        The parsed document.

    Raises:
        BrunoParseError: With the taxonomy code; ``.bru`` files without ``bruno.json`` are
            ``INPUT_SEMANTIC_INVALID``, a set with neither is ``FORMAT_MISMATCH``.
    """
    manifest_text, relative = _collection_members(members, root)
    if manifest_text is None:
        if any(path.endswith(".bru") for path in members):
            raise _error(
                f"The upload{_where(source_label)} has .bru files but no bruno.json — include the collection's "
                "root folder",
                "INPUT_SEMANTIC_INVALID",
            )
        raise _error(f"The upload{_where(source_label)} is not a Bruno collection (no bruno.json)", "FORMAT_MISMATCH")
    return _build(manifest_text, relative, label=source_label)
