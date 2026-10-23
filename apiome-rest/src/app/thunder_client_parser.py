"""Reader for Thunder Client collection and environment JSON — FMT-10.2 (#5475).

Thunder Client is the API client built into VS Code. Its collection export
(``thunder-collection_<name>.json``) is flat: a collection has a list of ``folders`` and a list of
``requests``, and each folder or request names its parent folder by ``containerId`` (an empty
string is the collection root), so the folder tree is rebuilt from those ids rather than read
from nesting. The collection's ``settings`` and each folder's ``settings`` may carry ``auth`` and
``headers`` that the requests beneath them inherit. An environment export
(``thunder-environment_<name>.json``) is a flat ``data`` list of ``{name, value}`` variables.
Variables are written ``{{name}}``; path parameters are written ``:name`` in the URL and flagged
``isPath`` in ``params``.

This module turns one or more collections (and any environments uploaded beside them) into a
:class:`ThunderDocument`: a list of concrete :class:`~app.inferred_spec.HttpObservation` samples for
the shared inferred-spec engine, plus the facts the engine has no slot for — the folder each
request sits in, the auth scheme it resolves to, the content type of its body, and the server
variables its URLs are written against. The shared mechanics (JSON loading, scrubbing, the
post-processing of the engine's model) live in :mod:`app.client_collection`, shared with the
Hoppscotch reader (FMT-10.1).

**Credentials never leave this module.** A saved request can hold a literal bearer token, a
basic-auth password or an OAuth client secret. Auth blocks are read as *scheme and public OAuth
fields only* — the credential fields are never read at all — and every other value that reaches
an observation (URL, query and header values, bodies, environment defaults) is passed through the
shared secret-scrub gate first. A header, parameter or form field whose *name* says it carries a
secret is redacted whatever its value looks like, and a variable whose name says so never becomes
a server-variable default.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark (a UTF-16
  upload decoded as UTF-8).
* ``INPUT_TRUNCATED`` — the JSON ends while a value is still open.
* ``INPUT_MALFORMED`` — any other JSON syntax error, or a collection whose structure is wrong.
* ``FORMAT_MISMATCH`` — valid JSON that is not a Thunder Client export (a Hoppscotch or Postman
  collection, an OpenAPI document).
* ``INPUT_SEMANTIC_INVALID`` — a collection with no requests, a folder or request whose
  ``containerId`` names a folder that does not exist (or a folder cycle), a request with no URL
  (or one written only as a variable nothing defines), or an environment uploaded on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit

from .client_collection import SECRET_NAME_RE, load_client_json, scrub_named, scrub_value
from .inferred_spec import HttpObservation

__all__ = [
    "AUTH_SCHEMES",
    "FORMAT_KEY",
    "ThunderAuth",
    "ThunderDocument",
    "ThunderParseError",
    "ThunderRequest",
    "ThunderVariable",
    "is_thunder_collection",
    "is_thunder_environment",
    "parse_thunder_fileset",
    "parse_thunder_text",
]

#: The registry key of the format.
FORMAT_KEY = "thunder-client"

#: The ``clientName`` every Thunder Client export carries.
CLIENT_NAME = "Thunder Client"

#: Thunder Client auth ``type`` → the canonical scheme identifier :mod:`app.canonical_security`
#: reads. Types that sign the request (AWS, NTLM, Hawk) have no canonical scheme of their own and
#: are recorded as a generic ``authorization`` requirement.
AUTH_SCHEMES: Mapping[str, str] = {
    "basic": "basic",
    "bearer": "bearer",
    "digest": "digest",
    "oauth2": "oauth2",
    "aws": "authorization",
    "ntlm": "authorization",
    "hawk": "authorization",
}

#: Auth types that mean "no auth of this level's own, and none inherited".
_NO_AUTH = frozenset({"none", ""})

#: OAuth 2 fields that are public endpoints or labels, not credentials. Only these are ever read
#: from an ``oauth2`` block, so a credential cannot be copied into the model by accident.
_OAUTH_TOKEN_URL_FIELDS = ("accessTokenUrl", "tokenUrl", "authUrl")

#: Thunder Client body ``type`` → the media type it is sent as.
BODY_CONTENT_TYPES: Mapping[str, str] = {
    "json": "application/json",
    "graphql": "application/json",
    "xml": "application/xml",
    "text": "text/plain",
    "formencoded": "application/x-www-form-urlencoded",
    "formdata": "multipart/form-data",
    "binary": "application/octet-stream",
}

#: Variable names may start with ``$`` / ``#`` (Thunder's dynamic and system variables).
_NAME = r"[$#]?[A-Za-z0-9_.\-]+"
_VARIABLE_RE = re.compile(r"\{\{\s*(" + _NAME + r")\s*\}\}")
_LEADING_VARIABLE_RE = re.compile(r"^\s*\{\{\s*(" + _NAME + r")\s*\}\}")
_WHOLE_VARIABLE_RE = re.compile(r"^\s*\{\{\s*" + _NAME + r"\s*\}\}\s*$")
#: A ``{{var}}`` written as a bare JSON value (``"qty": {{qty}}``), which makes a body unparseable.
_BARE_JSON_VARIABLE_RE = re.compile(r'(?<!")(\{\{\s*' + _NAME + r'\s*\}\})(?!")')
#: A ``:name`` path segment — Thunder Client's path-parameter spelling.
_PATH_PARAM_RE = re.compile(r"(?<=/):([A-Za-z_][A-Za-z0-9_\-]*)(?=/|$)")

_MAX_VARIABLE_DEPTH = 5


class ThunderParseError(ValueError):
    """Raised when a Thunder Client upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ThunderAuth:
    """A resolved auth declaration — scheme and public OAuth facts only, never a credential.

    Attributes:
        type: The Thunder Client auth ``type`` (``bearer``, ``basic``, ``oauth2`` …).
        scheme: The canonical scheme identifier (see :data:`AUTH_SCHEMES`).
        declared_at: The collection root or folder path the auth was inherited from, or ``request``.
        grant_type: An OAuth 2 grant type, when stated.
        token_url: An OAuth 2 token / auth URL, when stated (scrubbed).
        scopes: OAuth 2 scopes, when stated.
    """

    type: str
    scheme: str
    declared_at: str
    grant_type: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag, leaving unset facts out."""
        record: Dict[str, Any] = {"type": self.type, "scheme": self.scheme, "declared_at": self.declared_at}
        if self.grant_type:
            record["grant_type"] = self.grant_type
        if self.token_url:
            record["token_url"] = self.token_url
        if self.scopes:
            record["scopes"] = list(self.scopes)
        return record


@dataclass(frozen=True)
class ThunderRequest:
    """The facts about one saved request that the inferred-spec engine has no slot for.

    Attributes:
        name: The request's name.
        method: The upper-cased HTTP method.
        url: The URL handed to the engine (path-absolute when the URL starts with a variable).
        folder: The folder path from the collection root (empty for a root-level request).
        auth: The auth the request resolves to after inheritance, or ``None``.
        content_type: The body's media type, when the request has a body.
        has_tests: Whether declarative tests (assertions, ``set-env-var``) are attached.
        has_pre_request: Whether a pre-request step (``preReq``) is attached.
    """

    name: str
    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[ThunderAuth]
    content_type: Optional[str]
    has_tests: bool
    has_pre_request: bool


@dataclass(frozen=True)
class ThunderVariable:
    """A variable the upload defines — its *name* and where it came from, never its value.

    Attributes:
        name: The variable name.
        source: ``environment:<name>``.
        secret: Whether the name says the value is a credential (its value is then withheld).
    """

    name: str
    source: str
    secret: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        return {"name": self.name, "source": self.source, "secret": self.secret}


@dataclass
class ThunderDocument:
    """A parsed Thunder Client upload, ready for the inferred-spec engine.

    Attributes:
        title: The collection's name (or the names of several collections joined).
        observations: One concrete request sample per saved request.
        requests: Per-request facts, in collection order.
        server_variables: Server URL variable → its default (``None`` when nothing defines it or
            the variable is secret), for every URL written against a leading ``{{variable}}``.
        variables: Every variable the environments define, by name.
        collection_versions: The export ``version`` of each collection read.
        environments: The names of the environments read.
        source_label: The filename or paste label.
    """

    title: str
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[ThunderRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[ThunderVariable] = field(default_factory=list)
    collection_versions: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    source_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading and detection
# ---------------------------------------------------------------------------


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def _error(message: str, code: str) -> ThunderParseError:
    return ThunderParseError(message, code=code)


def _load_json(text: str, label: Optional[str]) -> Any:
    """Load one JSON document with the shared encoding check, intake guards and taxonomy codes."""
    return load_client_json(text, label, product="Thunder Client", error=_error)


def _is_thunder_client(document: Mapping[str, Any]) -> bool:
    return str(document.get("clientName") or "").strip().lower() == CLIENT_NAME.lower()


def is_thunder_collection(document: Any) -> bool:
    """Whether a loaded JSON value is a Thunder Client collection export.

    A collection carries ``collectionName`` and ``requests[]``, and ``clientName: "Thunder Client"``
    (older exports may omit the client name; their requests then carry ``colId`` or
    ``containerId``).

    Args:
        document: The loaded JSON value.

    Returns:
        ``True`` for a collection.
    """
    if not isinstance(document, dict) or not isinstance(document.get("requests"), list):
        return False
    if "collectionName" not in document:
        return False
    if _is_thunder_client(document):
        return True
    return any(
        isinstance(request, dict) and ("colId" in request or "containerId" in request)
        for request in document["requests"]
    )


def is_thunder_environment(document: Any) -> bool:
    """Whether a loaded JSON value is a Thunder Client environment export.

    An environment is ``{clientName: "Thunder Client", name, data: [{name, value}]}``.

    Args:
        document: The loaded JSON value.

    Returns:
        ``True`` for an environment.
    """
    if not isinstance(document, dict) or not isinstance(document.get("data"), list):
        return False
    if not _is_thunder_client(document) or "requests" in document:
        return False
    return all(isinstance(item, dict) and "name" in item for item in document["data"])


def _looks_like_other_format(document: Any) -> Optional[str]:
    """Name the format a JSON document that is not Thunder Client looks like, if any."""
    if not isinstance(document, dict):
        return None
    if isinstance(document.get("folders"), list) and isinstance(document.get("requests"), list) and "name" in document:
        return "a Hoppscotch collection"
    info = document.get("info")
    if isinstance(info, dict) and ("_postman_id" in info or "getpostman" in str(info.get("schema", ""))):
        return "a Postman collection"
    if isinstance(document.get("item"), list):
        return "a Postman collection"
    if "openapi" in document or "swagger" in document:
        return "an OpenAPI document"
    if document.get("_type") == "export" and "resources" in document:
        return "an Insomnia export"
    if isinstance(document.get("log"), dict) and "entries" in document["log"]:
        return "a HAR capture"
    return None


def _scrub_named(name: str, value: str) -> str:
    """Scrub a header, parameter or form-field value; a whole ``{{variable}}`` is kept."""
    return scrub_named(name, value, reference=_WHOLE_VARIABLE_RE)


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


@dataclass
class _Scope:
    """The variables the environments define; a secret-named variable is defined but valueless."""

    values: Dict[str, Optional[str]] = field(default_factory=dict)
    secret: set = field(default_factory=set)

    def lookup(self, name: str) -> Tuple[bool, Optional[str]]:
        """Return ``(defined, value)`` for ``name``."""
        if name not in self.values:
            return False, None
        return True, (None if name in self.secret else self.values[name])

    def resolve(self, text: str) -> Optional[str]:
        """Substitute every ``{{variable}}`` in ``text``, or ``None`` when one has no value."""
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


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def _read_auth(auth: Any, declared_at: str) -> Tuple[bool, Optional[ThunderAuth]]:
    """Read one auth block.

    Args:
        auth: The ``auth`` value of the collection settings, a folder's settings or a request.
        declared_at: Where it is written, for provenance.

    Returns:
        ``(inherits, auth)`` — ``inherits`` is ``True`` for ``inherit`` (or a missing block);
        ``auth`` is the declaration, or ``None`` for no auth.
    """
    if not isinstance(auth, dict):
        return True, None
    auth_type = str(auth.get("type") or "").strip().lower()
    if auth_type == "inherit":
        return True, None
    if auth_type in _NO_AUTH:
        return False, None
    grant_type = token_url = None
    scopes: Tuple[str, ...] = ()
    oauth = auth.get("oauth2")
    if auth_type == "oauth2" and isinstance(oauth, dict):
        if isinstance(oauth.get("grantType"), str) and oauth["grantType"]:
            grant_type = oauth["grantType"].strip().lower()
        for key in _OAUTH_TOKEN_URL_FIELDS:
            endpoint = oauth.get(key)
            if isinstance(endpoint, str) and endpoint.strip() and not _WHOLE_VARIABLE_RE.match(endpoint):
                token_url = scrub_value(endpoint.strip())
                break
        if isinstance(oauth.get("scope"), str):
            scopes = tuple(scope for scope in oauth["scope"].split() if scope)
    return False, ThunderAuth(
        type=auth_type,
        scheme=AUTH_SCHEMES.get(auth_type, "authorization"),
        declared_at=declared_at,
        grant_type=grant_type,
        token_url=token_url,
        scopes=scopes,
    )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def _entries(entries: Any, *, label: str) -> List[Mapping[str, Any]]:
    """The *enabled* ``{name, value, isDisabled}`` entries of a ``headers`` / ``params`` / ``form`` list."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ThunderParseError(f"{label} must be a list", code="INPUT_MALFORMED")
    enabled: List[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ThunderParseError(f"{label} entries must be objects", code="INPUT_MALFORMED")
        name = entry.get("name")
        if entry.get("isDisabled") is True or not isinstance(name, str) or not name.strip():
            continue
        enabled.append(entry)
    return enabled


def _pairs(entries: Any, *, label: str) -> List[Tuple[str, str]]:
    """Read the enabled entries of a list as ``(name, value)`` pairs."""
    return [
        (str(entry["name"]).strip(), "" if entry.get("value") is None else str(entry["value"]))
        for entry in _entries(entries, label=label)
    ]


def _quote_bare_variables(body: str) -> str:
    """Quote ``{{variables}}`` written as bare JSON values so the body parses for inference."""
    return _BARE_JSON_VARIABLE_RE.sub(lambda match: json.dumps(match.group(1)), body)


def _json_text(raw: str) -> str:
    """Scrub a JSON body, quoting bare variables when that is what keeps it parseable."""
    scrubbed = scrub_value(raw)
    try:
        json.loads(scrubbed)
    except json.JSONDecodeError:
        scrubbed = _quote_bare_variables(scrubbed)
    return scrubbed


def _body(request: Mapping[str, Any], label: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(content_type, body_text)`` for a request, the text scrubbed.

    A JSON body is kept as JSON (bare ``{{variables}}`` quoted) so the engine can infer its schema;
    a GraphQL body becomes the ``{query, variables}`` JSON it is sent as; a URL-encoded or multipart
    body becomes the JSON object of its fields (a file part is a string), so the engine infers a
    schema for those too. A binary body keeps its media type and no content.
    """
    body = request.get("body")
    if body is None:
        return None, None
    if not isinstance(body, dict):
        raise ThunderParseError(f"{label}: `body` must be an object", code="INPUT_MALFORMED")
    body_type = str(body.get("type") or "").strip().lower()
    content_type = BODY_CONTENT_TYPES.get(body_type)
    if content_type is None:
        return None, None
    if body_type in ("formencoded", "formdata"):
        fields = {
            str(entry["name"]).strip(): _scrub_named(
                str(entry["name"]), "" if entry.get("value") is None else str(entry["value"])
            )
            for entry in _entries(body.get("form"), label=f"{label} form")
        }
        if body_type == "formdata":
            # A file part's value is a local file path, never content; the part is a string field.
            for entry in _entries(body.get("files"), label=f"{label} files"):
                fields[str(entry["name"]).strip()] = ""
        if not fields:
            return None, None
        return content_type, json.dumps(fields, sort_keys=True)
    if body_type == "binary":
        return content_type, None
    if body_type == "graphql":
        graphql = body.get("graphql")
        if not isinstance(graphql, dict) or not isinstance(graphql.get("query"), str) or not graphql["query"].strip():
            return None, None
        payload: Dict[str, Any] = {"query": scrub_value(graphql["query"])}
        variables = graphql.get("variables")
        if isinstance(variables, str) and variables.strip():
            try:
                payload["variables"] = json.loads(_json_text(variables))
            except json.JSONDecodeError:
                pass  # unparseable variables infer nothing; the query alone is kept
        return content_type, json.dumps(payload, sort_keys=True)
    raw = body.get("raw")
    if not isinstance(raw, str) or not raw.strip():
        return None, None
    if body_type == "json":
        return content_type, _json_text(raw)
    return content_type, scrub_value(raw)


def _request_url(
    url: str,
    scope: _Scope,
    base_url: Optional[str],
    server_variables: Dict[str, Optional[str]],
    label: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Turn a saved URL into the engine's URL plus the query pairs written into it.

    A URL relative to the collection (``/orders``) is prefixed with the collection's base URL. A URL
    that starts with a ``{{variable}}`` (``{{baseUrl}}/v2/orders``) is a server template: the
    variable becomes a server variable — its default resolved from the environments unless it is
    secret — and the rest is the operation's path. Every other ``{{variable}}`` and ``:name``
    segment inside the path is a path parameter, ``{variable}``.

    Raises:
        ThunderParseError: ``INPUT_SEMANTIC_INVALID`` for an empty URL or one written only as a
            variable nothing defines.
    """
    url = url.strip()
    if not url:
        raise ThunderParseError(f"{label} has no URL", code="INPUT_SEMANTIC_INVALID")
    if base_url and url.startswith("/"):
        url = base_url.rstrip("/") + url
    leading = _LEADING_VARIABLE_RE.match(url)
    if leading:
        name = leading.group(1)
        rest = url[leading.end() :]
        defined, value = scope.lookup(name)
        resolved = scope.resolve(value) if isinstance(value, str) else None
        if not rest.strip("/") and not rest.startswith("?") and not defined:
            raise ThunderParseError(
                f"{label} has a URL written only as `{{{{{name}}}}}`, which nothing in the upload "
                "defines — its path cannot be known",
                code="INPUT_SEMANTIC_INVALID",
            )
        server_variables.setdefault(name, None)
        if resolved is not None and server_variables[name] is None:
            server_variables[name] = scrub_value(resolved)
        url = rest if rest.startswith("/") else "/" + rest
    url = _VARIABLE_RE.sub(lambda match: "{" + match.group(1).lstrip("$#") + "}", url)
    parts = urlsplit(url if "://" in url or url.startswith("/") else f"https://{url}")
    path = _PATH_PARAM_RE.sub(lambda match: "{" + match.group(1) + "}", parts.path or "/")
    query = [(key, _scrub_named(key, value)) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    if parts.netloc:
        host = parts.netloc.rsplit("@", 1)[-1]  # userinfo is a credential, never kept
        return f"{parts.scheme or 'https'}://{host}{path}", query
    return path, query


# ---------------------------------------------------------------------------
# Folder tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Container:
    """What a folder (or the collection root) hands down: its path, auth and headers."""

    path: Tuple[str, ...]
    auth: Optional[ThunderAuth]
    headers: Tuple[Tuple[str, str], ...]


def _settings(node: Mapping[str, Any]) -> Mapping[str, Any]:
    settings = node.get("settings")
    return settings if isinstance(settings, dict) else {}


def _containers(collection: Mapping[str, Any], label: str) -> Dict[str, _Container]:
    """Rebuild the folder tree from ``containerId`` links, resolving inherited auth and headers.

    Args:
        collection: The collection object.
        label: The collection's name, for messages.

    Returns:
        ``""`` (the collection root) and every folder ``_id`` → what it hands down.

    Raises:
        ThunderParseError: ``INPUT_MALFORMED`` for a folder of the wrong shape;
            ``INPUT_SEMANTIC_INVALID`` for a folder whose parent does not exist or a cycle.
    """
    folders = collection.get("folders") or []
    if not isinstance(folders, list):
        raise ThunderParseError(f"`folders` of {label} must be a list", code="INPUT_MALFORMED")
    by_id: Dict[str, Mapping[str, Any]] = {}
    for index, folder in enumerate(folders):
        if not isinstance(folder, dict) or not isinstance(folder.get("_id"), str) or not folder["_id"]:
            raise ThunderParseError(
                f"Folder {index} of {label} must be an object with an `_id`", code="INPUT_MALFORMED"
            )
        by_id[folder["_id"]] = folder

    root_settings = _settings(collection)
    _, root_auth = _read_auth(root_settings.get("auth"), "collection root")
    resolved: Dict[str, _Container] = {
        "": _Container(
            path=(),
            auth=root_auth,
            headers=tuple(_pairs(root_settings.get("headers"), label=f"Headers of {label}")),
        )
    }

    def _resolve(folder_id: str, seen: Tuple[str, ...]) -> _Container:
        if folder_id in resolved:
            return resolved[folder_id]
        folder = by_id.get(folder_id)
        if folder is None:
            raise ThunderParseError(
                f"A folder or request in {label} sits in folder `{folder_id}`, which the collection does "
                "not declare — the folder tree cannot be rebuilt",
                code="INPUT_SEMANTIC_INVALID",
            )
        if folder_id in seen:
            raise ThunderParseError(
                f"The folders of {label} form a cycle through `{folder_id}`", code="INPUT_SEMANTIC_INVALID"
            )
        parent = _resolve(str(folder.get("containerId") or ""), seen + (folder_id,))
        path = parent.path + (str(folder.get("name") or folder_id),)
        settings = _settings(folder)
        inherits, own = _read_auth(settings.get("auth"), "/".join(path))
        container = _Container(
            path=path,
            auth=parent.auth if inherits else own,
            headers=parent.headers + tuple(_pairs(settings.get("headers"), label=f"Headers of {'/'.join(path)}")),
        )
        resolved[folder_id] = container
        return container

    for folder_id in by_id:
        _resolve(folder_id, ())
    return resolved


@dataclass
class _Reader:
    """Reads collections into observations, sharing one variable scope and server table."""

    scope: _Scope
    source_label: Optional[str]
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[ThunderRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)

    def read_collection(self, collection: Mapping[str, Any], *, pointer: str) -> None:
        """Read one collection's requests.

        Args:
            collection: The collection object.
            pointer: JSON-pointer-like prefix for provenance (``0/`` when several are read).
        """
        label = str(collection.get("collectionName") or "the collection")
        containers = _containers(collection, label)
        options = _settings(collection).get("options")
        base_url = options.get("baseUrl") if isinstance(options, dict) else None
        for index, request in enumerate(collection.get("requests") or []):
            if not isinstance(request, dict):
                raise ThunderParseError(f"Request {index} of {label} must be an object", code="INPUT_MALFORMED")
            container_id = str(request.get("containerId") or "")
            if container_id not in containers:
                raise ThunderParseError(
                    f"Request {request.get('name')!r} sits in folder `{container_id}`, which {label} does not "
                    "declare — the folder tree cannot be rebuilt",
                    code="INPUT_SEMANTIC_INVALID",
                )
            self.read_request(
                request,
                container=containers[container_id],
                base_url=base_url if isinstance(base_url, str) and base_url.strip() else None,
                pointer=f"{pointer}requests/{index}",
            )

    def read_request(
        self,
        request: Mapping[str, Any],
        *,
        container: _Container,
        base_url: Optional[str],
        pointer: str,
    ) -> None:
        """Read one saved request into an observation."""
        name = str(request.get("name") or pointer)
        label = f"Request {name!r}"
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            raise ThunderParseError(f"{label} has no method", code="INPUT_MALFORMED")
        raw_url = request.get("url")
        if not isinstance(raw_url, str):
            raise ThunderParseError(f"{label} has no URL", code="INPUT_SEMANTIC_INVALID")
        url, url_query = _request_url(raw_url, self.scope, base_url, self.server_variables, label)
        inherits, own = _read_auth(request.get("auth"), "request")
        auth = container.auth if inherits else own

        merged: Dict[str, Tuple[str, str]] = {}
        for key, value in list(container.headers) + _pairs(request.get("headers"), label=f"{label} headers"):
            merged[key.lower()] = (key, value)  # a request's own header wins
        content_type, body = _body(request, label)
        if content_type and "content-type" not in merged:
            merged["content-type"] = ("Content-Type", content_type)
        headers = tuple((key, _scrub_named(key, value)) for key, value in (merged[k] for k in sorted(merged)))
        # `params` repeats the query written into the URL; the list (with isDisabled) is the truth,
        # and a URL-only query parameter is kept beside it.
        params = [
            entry for entry in _entries(request.get("params"), label=f"{label} params") if not entry.get("isPath")
        ]
        listed = [
            (str(entry["name"]).strip(), "" if entry.get("value") is None else str(entry["value"])) for entry in params
        ]
        names = {key for key, _ in listed}
        query = [(key, _scrub_named(key, value)) for key, value in listed] + [
            (key, value) for key, value in url_query if key not in names
        ]
        observation = HttpObservation(
            method=method.strip().upper(),
            url=url,
            headers=headers,
            query=tuple(query),
            request_body=body,
            source_location=pointer,
            source_label=name,
            source_file=self.source_label,
        )
        self.observations.append(observation)
        pre_request = request.get("preReq")
        self.requests.append(
            ThunderRequest(
                name=name,
                method=observation.method,
                url=url,
                folder=container.path,
                auth=auth,
                content_type=content_type,
                has_tests=bool(request.get("tests")),
                has_pre_request=isinstance(pre_request, dict) and any(bool(value) for value in pre_request.values()),
            )
        )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _build(
    collections: Sequence[Tuple[str, Mapping[str, Any]]],
    environments: Sequence[Tuple[str, Mapping[str, Any]]],
    source_label: Optional[str],
) -> ThunderDocument:
    """Read loaded collections (and environments) into one document.

    Environments marked ``default`` are read first, so their values win when two define the same
    variable.

    Args:
        collections: ``(label, loaded JSON)`` for each collection member.
        environments: ``(label, loaded JSON)`` for each environment member.
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        ThunderParseError: With the taxonomy code for the fault.
    """
    scope = _Scope()
    variables: List[ThunderVariable] = []
    environment_names: List[str] = []
    for label, environment in sorted(environments, key=lambda item: (item[1].get("default") is not True, item[0])):
        env_name = str(environment.get("name") or PurePosixPath(label or "environment").stem)
        environment_names.append(env_name)
        for entry in environment.get("data") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
                continue
            key = entry["name"].strip()
            value = entry.get("value")
            secret = bool(SECRET_NAME_RE.search(key))
            text = str(value) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""
            scope.values.setdefault(key, text or None)
            if secret:
                scope.secret.add(key)
            variables.append(ThunderVariable(name=key, source=f"environment:{env_name}", secret=secret))

    if not any(collection.get("requests") for _, collection in collections):
        raise ThunderParseError(
            "The collection has no requests — there is nothing to import",
            code="INPUT_SEMANTIC_INVALID",
        )

    reader = _Reader(scope=scope, source_label=source_label)
    for index, (_, collection) in enumerate(collections):
        reader.read_collection(collection, pointer=f"{index}/" if len(collections) > 1 else "")

    names = [str(collection.get("collectionName") or "").strip() for _, collection in collections]
    return ThunderDocument(
        title=" · ".join(name for name in names if name) or "Thunder Client collection",
        observations=reader.observations,
        requests=reader.requests,
        server_variables=reader.server_variables,
        variables=sorted(set(variables), key=lambda var: (var.name, var.source)),
        collection_versions=[str(collection.get("version", "")) for _, collection in collections],
        environments=environment_names,
        source_label=source_label,
    )


def _classify(document: Any, label: Optional[str]) -> str:
    """Return ``collection`` or ``environment`` for a loaded member, or raise ``FORMAT_MISMATCH``."""
    if is_thunder_collection(document):
        return "collection"
    if is_thunder_environment(document):
        return "environment"
    other = _looks_like_other_format(document)
    if other:
        raise ThunderParseError(
            f"The upload{_where(label)} is {other}, not a Thunder Client collection", code="FORMAT_MISMATCH"
        )
    raise ThunderParseError(
        f"The upload{_where(label)} is not a Thunder Client collection: expected `clientName`, "
        "`collectionName` and `requests[]`",
        code="FORMAT_MISMATCH",
    )


def parse_thunder_text(raw: str, *, source_label: Optional[str] = None) -> ThunderDocument:
    """Parse one Thunder Client collection export.

    Args:
        raw: The decoded upload.
        source_label: The filename or paste label.

    Returns:
        The parsed document.

    Raises:
        ThunderParseError: With the taxonomy code for the fault; an environment uploaded on its own
            is ``INPUT_SEMANTIC_INVALID``.
    """
    document = _load_json(raw, source_label)
    if _classify(document, source_label) == "environment":
        raise ThunderParseError(
            "This is a Thunder Client environment, not a collection — upload it together with the "
            "collection that uses it",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _build([(source_label or "", document)], [], source_label)


def parse_thunder_fileset(
    members: Mapping[str, str],
    *,
    root: Optional[str] = None,
    source_label: Optional[str] = None,
) -> ThunderDocument:
    """Parse a set of collection and environment exports into one API.

    Every JSON member is read: collections (``thunder-collection_*.json``) become requests,
    environments (``thunder-environment_*.json``) supply variables. Members that are not JSON (a
    README) are ignored.

    Args:
        members: Member text keyed by path.
        root: The root member's path.
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        ThunderParseError: With the taxonomy code for the fault.
    """
    collections: List[Tuple[str, Any]] = []
    environments: List[Tuple[str, Any]] = []
    for path in sorted(members):
        if not path.lower().endswith(".json") and path != root:
            continue
        document = _load_json(members[path], path)
        if _classify(document, path) == "collection":
            collections.append((path, document))
        else:
            environments.append((path, document))
    if not collections:
        raise ThunderParseError(
            "The upload has Thunder Client environments but no collection to apply them to",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _build(collections, environments, source_label or root)
