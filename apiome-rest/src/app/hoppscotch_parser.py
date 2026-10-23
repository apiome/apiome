"""Reader for Hoppscotch collection and environment JSON — FMT-10.1 (#5473).

Hoppscotch is the open-source API client teams move to from Postman. Its collection export is a
tree: a collection has ``folders`` (collections again, nested to any depth) and ``requests``, and
every level may carry ``auth`` and ``headers`` that the requests beneath it inherit. An
environment export is a flat list of ``variables``. Variables are written ``<<name>>``, not
Postman's ``{{name}}``.

This module turns one or more collections (and any environments uploaded beside them) into a
:class:`HoppscotchDocument`: a list of concrete
:class:`~app.inferred_spec.HttpObservation` samples for the shared inferred-spec engine, plus the
facts the engine has no slot for — the folder each request sits in, the auth scheme it resolves
to, the content type of its body, and the server variables its endpoints are written against.

**Credentials never leave this module.** A saved request can hold a literal bearer token, a
basic-auth password, an API key or an OAuth client secret. Auth blocks are read as *scheme and
parameter names only* — the credential fields are never read at all — and every other value that
reaches an observation (endpoint, query and header values, bodies, environment defaults) is passed
through the shared secret-scrub gate (:mod:`app.intake_secret_scrub`) first. A header, parameter
or form field whose *name* says it carries a secret is redacted whatever its value looks like.

Error codes (the import taxonomy):

* ``INPUT_ENCODING_INVALID`` — NULs, U+FFFD replacement characters or a byte-order mark (a UTF-16
  upload decoded as UTF-8).
* ``INPUT_TRUNCATED`` — the JSON ends while a value is still open.
* ``INPUT_MALFORMED`` — any other JSON syntax error, or a collection whose structure is wrong.
* ``FORMAT_MISMATCH`` — valid JSON that is not a Hoppscotch collection (a Postman collection, an
  OpenAPI document).
* ``INPUT_SEMANTIC_INVALID`` — a collection with no requests anywhere, a request with no endpoint
  (or one written only as a variable nothing defines), or an environment uploaded on its own.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit

from .client_collection import load_client_json, scrub_named, scrub_value
from .inferred_spec import HttpObservation

__all__ = [
    "FORMAT_KEY",
    "HoppscotchAuth",
    "HoppscotchDocument",
    "HoppscotchParseError",
    "HoppscotchRequest",
    "HoppscotchVariable",
    "is_hoppscotch_collection",
    "is_hoppscotch_environment",
    "parse_hoppscotch_fileset",
    "parse_hoppscotch_text",
]

#: The registry key of the format.
FORMAT_KEY = "hoppscotch"

#: Hoppscotch ``authType`` → the canonical scheme identifier :mod:`app.canonical_security` reads.
#: Types that sign the request (AWS, Hawk, Akamai, NTLM) have no canonical scheme of their own and
#: are recorded as a generic ``authorization`` requirement.
AUTH_SCHEMES: Mapping[str, str] = {
    "basic": "basic",
    "bearer": "bearer",
    "digest": "digest",
    "api-key": "apiKey",
    "oauth-2": "oauth2",
    "jwt": "bearer",
    "asap": "bearer",
    "aws-signature": "authorization",
    "hawk": "authorization",
    "akamai-eg": "authorization",
    "ntlm": "authorization",
}

#: Auth types that mean "no auth of this request's own".
_NO_AUTH = frozenset({"none", ""})

#: Auth fields that name *where* a credential goes rather than holding one. Only these are ever
#: read from an auth block, so a credential cannot be copied into the model by accident.
_AUTH_LOCATION_FIELDS = ("addTo",)

#: The field holding an API key's header or query *name* — a name, not a credential.
_API_KEY_NAME_FIELD = "key"

#: OAuth 2 grant fields that are public endpoints or labels, not credentials.
_OAUTH_PUBLIC_FIELDS = ("grantType", "authEndpoint", "tokenEndpoint", "scopes")

_VARIABLE_RE = re.compile(r"<<\s*([A-Za-z0-9_.\-]+)\s*>>")
_LEADING_VARIABLE_RE = re.compile(r"^\s*<<\s*([A-Za-z0-9_.\-]+)\s*>>")
_WHOLE_VARIABLE_RE = re.compile(r"^\s*<<\s*[A-Za-z0-9_.\-]+\s*>>\s*$")
#: A ``<<var>>`` written as a bare JSON value (``"qty": <<qty>>``), which makes a body unparseable.
_BARE_JSON_VARIABLE_RE = re.compile(r'(?<!")(<<\s*[A-Za-z0-9_.\-]+\s*>>)(?!")')

_MAX_VARIABLE_DEPTH = 5


class HoppscotchParseError(ValueError):
    """Raised when a Hoppscotch upload cannot be read.

    Attributes:
        code: The import taxonomy code the pipeline reports.
    """

    def __init__(self, message: str, *, code: str = "INPUT_MALFORMED") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HoppscotchAuth:
    """A resolved auth declaration — scheme and parameter *names* only, never a credential.

    Attributes:
        type: The Hoppscotch ``authType`` (``bearer``, ``api-key``, ``oauth-2`` …).
        scheme: The canonical scheme identifier (see :data:`AUTH_SCHEMES`).
        declared_at: The collection or folder path the auth was inherited from, or ``request``.
        location: Where an API key or token is sent (``header`` / ``query``), when stated.
        parameter: An API key's header or query parameter name, when stated.
        grant_type: An OAuth 2 grant type, when stated.
        token_url: An OAuth 2 token / auth endpoint, when stated (scrubbed).
        scopes: OAuth 2 scopes, when stated.
    """

    type: str
    scheme: str
    declared_at: str
    location: Optional[str] = None
    parameter: Optional[str] = None
    grant_type: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag, leaving unset facts out."""
        record: Dict[str, Any] = {"type": self.type, "scheme": self.scheme, "declared_at": self.declared_at}
        if self.location:
            record["in"] = self.location
        if self.parameter:
            record["name"] = self.parameter
        if self.grant_type:
            record["grant_type"] = self.grant_type
        if self.token_url:
            record["token_url"] = self.token_url
        if self.scopes:
            record["scopes"] = list(self.scopes)
        return record


@dataclass(frozen=True)
class HoppscotchRequest:
    """The facts about one saved request that the inferred-spec engine has no slot for.

    Attributes:
        name: The request's name.
        method: The upper-cased HTTP method.
        url: The URL handed to the engine (path-absolute when the endpoint starts with a variable).
        folder: The folder path from the collection root (empty for a root-level request).
        auth: The auth the request resolves to after inheritance, or ``None``.
        content_type: The body's content type, when the request has a body.
        has_scripts: Whether a pre-request or test script is attached.
    """

    name: str
    method: str
    url: str
    folder: Tuple[str, ...]
    auth: Optional[HoppscotchAuth]
    content_type: Optional[str]
    has_scripts: bool


@dataclass(frozen=True)
class HoppscotchVariable:
    """A variable the upload defines — its *name* and where it came from, never its value.

    Attributes:
        name: The variable name.
        source: ``environment`` (with the environment's name) or ``collection``.
        secret: Whether Hoppscotch marks the variable secret.
    """

    name: str
    source: str
    secret: bool

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for an ``extras`` bag."""
        return {"name": self.name, "source": self.source, "secret": self.secret}


@dataclass
class HoppscotchDocument:
    """A parsed Hoppscotch upload, ready for the inferred-spec engine.

    Attributes:
        title: The collection's name (or the names of several collections joined).
        observations: One concrete request sample per saved request (and saved example).
        requests: Per-request facts, in collection order.
        server_variables: Server URL variable → its default (``None`` when nothing defines it or
            the variable is secret), for every endpoint written against a leading ``<<variable>>``.
        variables: Every variable the collections and environments define, by name.
        collection_versions: The schema ``v`` of each collection read.
        environments: The names of the environments read.
        source_label: The filename or paste label.
    """

    title: str
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[HoppscotchRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)
    variables: List[HoppscotchVariable] = field(default_factory=list)
    collection_versions: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    source_label: Optional[str] = None


# ---------------------------------------------------------------------------
# Loading and detection
# ---------------------------------------------------------------------------


def _where(label: Optional[str]) -> str:
    return f" in {label}" if label else ""


def _error(message: str, code: str) -> HoppscotchParseError:
    return HoppscotchParseError(message, code=code)


def _load_json(text: str, label: Optional[str]) -> Any:
    """Load one JSON document with the shared encoding check, intake guards and taxonomy codes."""
    return load_client_json(text, label, product="Hoppscotch", error=_error)


def _is_collection_node(value: Any) -> bool:
    """Whether ``value`` has the shape of a Hoppscotch collection (or folder)."""
    return (
        isinstance(value, dict)
        and isinstance(value.get("folders"), list)
        and isinstance(value.get("requests"), list)
        and "name" in value
    )


def is_hoppscotch_collection(document: Any) -> bool:
    """Whether a loaded JSON value is a Hoppscotch collection export.

    A collection carries ``name``, ``folders[]`` and ``requests[]`` (and a schema ``v``); an
    export of several collections is a list of them.

    Args:
        document: The loaded JSON value.

    Returns:
        ``True`` for a collection or a non-empty list of collections.
    """
    if isinstance(document, list):
        return bool(document) and all(_is_collection_node(item) for item in document)
    return _is_collection_node(document)


def _is_environment_node(value: Any) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("variables"), list):
        return False
    if "folders" in value or "requests" in value or "item" in value or "values" in value:
        return False
    return all(isinstance(item, dict) and "key" in item for item in value["variables"])


def is_hoppscotch_environment(document: Any) -> bool:
    """Whether a loaded JSON value is a Hoppscotch environment export.

    An environment is ``{name, variables: [{key, value | initialValue, secret}]}``; an export of
    several environments is a list of them. Postman environments use ``values``, not
    ``variables``, so they are not claimed.

    Args:
        document: The loaded JSON value.

    Returns:
        ``True`` for an environment or a non-empty list of environments.
    """
    if isinstance(document, list):
        return bool(document) and all(_is_environment_node(item) for item in document)
    return _is_environment_node(document)


def _looks_like_other_format(document: Any) -> Optional[str]:
    """Name the format a JSON document that is not Hoppscotch looks like, if any."""
    if not isinstance(document, dict):
        return None
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


# ---------------------------------------------------------------------------
# Scrubbing
# ---------------------------------------------------------------------------


def _scrub(value: str) -> str:
    """Pass one value through the shared secret-scrub gate (named patterns and entropy)."""
    return scrub_value(value)


def _scrub_named(name: str, value: str) -> str:
    """Scrub a header, parameter or form-field value; a whole ``<<variable>>`` is kept."""
    return scrub_named(name, value, reference=_WHOLE_VARIABLE_RE)


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


def _variable_value(entry: Mapping[str, Any]) -> Optional[str]:
    """A variable's saved value (``value`` in older exports, ``initialValue`` / ``currentValue``)."""
    for key in ("value", "initialValue", "currentValue"):
        value = entry.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value) != "":
            return str(value)
    return None


@dataclass
class _Scope:
    """The variables visible while reading, in precedence order (request > environment > collection)."""

    environment: Dict[str, Optional[str]] = field(default_factory=dict)
    collection: Dict[str, Optional[str]] = field(default_factory=dict)
    secret: set = field(default_factory=set)

    def lookup(self, name: str, request: Mapping[str, Optional[str]]) -> Tuple[bool, Optional[str]]:
        """Return ``(defined, value)`` for ``name``; a secret variable is defined but valueless."""
        for layer in (request, self.environment, self.collection):
            if name in layer:
                return True, (None if name in self.secret else layer[name])
        return False, None


def _resolve(text: str, scope: _Scope, request_vars: Mapping[str, Optional[str]]) -> Optional[str]:
    """Substitute every ``<<variable>>`` in ``text`` with its value, or ``None`` when one is missing."""
    current = text
    for _ in range(_MAX_VARIABLE_DEPTH):
        missing = False

        def _replace(match: "re.Match[str]") -> str:
            nonlocal missing
            defined, value = scope.lookup(match.group(1), request_vars)
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


def _read_auth(auth: Any, declared_at: str) -> Tuple[bool, Optional[HoppscotchAuth]]:
    """Read one auth block.

    Args:
        auth: The ``auth`` value of a collection, folder or request.
        declared_at: Where it is written, for provenance.

    Returns:
        ``(inherits, auth)`` — ``inherits`` is ``True`` for ``inherit`` (or a missing block);
        ``auth`` is the declaration, or ``None`` for no auth.
    """
    if not isinstance(auth, dict):
        return True, None
    auth_type = str(auth.get("authType") or "").strip().lower()
    if auth_type == "inherit":
        return True, None
    if auth_type in _NO_AUTH or auth.get("authActive") is False:
        return False, None
    location: Optional[str] = None
    for key in _AUTH_LOCATION_FIELDS:
        raw = auth.get(key)
        if isinstance(raw, str) and raw:
            location = "query" if "QUERY" in raw.upper() else "header"
    parameter: Optional[str] = None
    if auth_type == "api-key":
        name = auth.get(_API_KEY_NAME_FIELD)
        if isinstance(name, str) and name.strip():
            parameter = name.strip()
        location = location or "header"
    grant_type = token_url = None
    scopes: Tuple[str, ...] = ()
    grant = auth.get("grantTypeInfo")
    if auth_type == "oauth-2" and isinstance(grant, dict):
        public = {key: grant.get(key) for key in _OAUTH_PUBLIC_FIELDS}
        if isinstance(public["grantType"], str) and public["grantType"]:
            grant_type = public["grantType"].lower()
        endpoint = public["tokenEndpoint"] or public["authEndpoint"]
        if isinstance(endpoint, str) and endpoint and not _WHOLE_VARIABLE_RE.match(endpoint):
            token_url = _scrub(endpoint)
        if isinstance(public["scopes"], str):
            scopes = tuple(scope for scope in public["scopes"].split() if scope)
    return False, HoppscotchAuth(
        type=auth_type,
        scheme=AUTH_SCHEMES.get(auth_type, "authorization"),
        declared_at=declared_at,
        location=location,
        parameter=parameter,
        grant_type=grant_type,
        token_url=token_url,
        scopes=scopes,
    )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def _pairs(entries: Any, *, label: str) -> List[Tuple[str, str]]:
    """Read the *active* ``{key, value, active}`` entries of a ``params`` / ``headers`` list."""
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise HoppscotchParseError(f"{label} must be a list", code="INPUT_MALFORMED")
    pairs: List[Tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise HoppscotchParseError(f"{label} entries must be objects", code="INPUT_MALFORMED")
        if entry.get("active") is False:
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        value = entry.get("value")
        pairs.append((key.strip(), "" if value is None else str(value)))
    return pairs


def _request_variables(request: Mapping[str, Any]) -> Dict[str, Optional[str]]:
    variables: Dict[str, Optional[str]] = {}
    for entry in request.get("requestVariables") or []:
        if isinstance(entry, dict) and entry.get("active") is not False and isinstance(entry.get("key"), str):
            variables[entry["key"]] = _variable_value(entry)
    return variables


def _quote_bare_variables(body: str) -> str:
    """Quote ``<<variables>>`` written as bare JSON values so the body parses for inference."""
    return _BARE_JSON_VARIABLE_RE.sub(lambda match: json.dumps(match.group(1)), body)


def _body(request: Mapping[str, Any], label: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(content_type, body_text)`` for a request, the text scrubbed.

    A JSON body is kept as JSON (bare ``<<variables>>`` quoted) so the engine can infer its schema;
    a URL-encoded or multipart body is turned into the JSON object of its fields (a file part is a
    string), so the engine infers a schema for those too.
    """
    body = request.get("body")
    if body is None:
        return None, None
    if not isinstance(body, dict):
        raise HoppscotchParseError(f"{label}: `body` must be an object", code="INPUT_MALFORMED")
    content_type = body.get("contentType")
    content = body.get("body")
    if not isinstance(content_type, str) or not content_type.strip() or content in (None, "", []):
        return None, None
    content_type = content_type.strip().lower()
    if isinstance(content, list):
        # multipart/form-data: [{key, value, active, isFile}]; a file part's value is a file name.
        fields: Dict[str, str] = {}
        for entry in content:
            if not isinstance(entry, dict) or entry.get("active") is False or not entry.get("key"):
                continue
            key = str(entry["key"]).strip()
            value = "" if entry.get("isFile") or entry.get("value") is None else str(entry["value"])
            fields[key] = _scrub_named(key, value)
        return content_type, json.dumps(fields, sort_keys=True)
    if not isinstance(content, str):
        raise HoppscotchParseError(f"{label}: `body.body` must be text or a list of fields", code="INPUT_MALFORMED")
    if "x-www-form-urlencoded" in content_type:
        fields = {key: _scrub_named(key, value) for key, value in parse_qsl(content, keep_blank_values=True)}
        return content_type, json.dumps(fields, sort_keys=True)
    if "json" in content_type:
        scrubbed = _scrub(content)
        try:
            json.loads(scrubbed)
        except json.JSONDecodeError:
            scrubbed = _quote_bare_variables(scrubbed)
        return content_type, scrubbed
    return content_type, _scrub(content)


def _endpoint_url(
    endpoint: str,
    scope: _Scope,
    request_vars: Mapping[str, Optional[str]],
    server_variables: Dict[str, Optional[str]],
    label: str,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Turn a saved endpoint into the engine's URL plus the query pairs written into it.

    An endpoint that starts with a ``<<variable>>`` (``<<baseUrl>>/v2/orders``) is a server
    template: the variable becomes a server variable — its default resolved from the environment
    or collection variables, unless secret — and the rest is the operation's path. Every other
    ``<<variable>>`` inside the path is a path parameter, ``{variable}``.

    Raises:
        HoppscotchParseError: ``INPUT_SEMANTIC_INVALID`` for an empty endpoint or one written only
            as a variable nothing defines.
    """
    endpoint = endpoint.strip()
    if not endpoint:
        raise HoppscotchParseError(f"{label} has no endpoint", code="INPUT_SEMANTIC_INVALID")
    leading = _LEADING_VARIABLE_RE.match(endpoint)
    if leading:
        name = leading.group(1)
        rest = endpoint[leading.end() :]
        defined, value = scope.lookup(name, request_vars)
        resolved = _resolve(value, scope, request_vars) if isinstance(value, str) else None
        if not rest.strip("/") and not rest.startswith("?") and not defined:
            raise HoppscotchParseError(
                f"{label} has an endpoint written only as `<<{name}>>`, which nothing in the upload "
                "defines — its path cannot be known",
                code="INPUT_SEMANTIC_INVALID",
            )
        server_variables.setdefault(name, None)
        if resolved is not None and server_variables[name] is None:
            server_variables[name] = _scrub(resolved)
        endpoint = rest if rest.startswith("/") else "/" + rest
    endpoint = _VARIABLE_RE.sub(lambda match: "{" + match.group(1) + "}", endpoint)
    parts = urlsplit(endpoint if "://" in endpoint or endpoint.startswith("/") else f"https://{endpoint}")
    query = [(key, _scrub_named(key, value)) for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    if parts.netloc:
        host = parts.netloc.rsplit("@", 1)[-1]  # userinfo is a credential, never kept
        url = f"{parts.scheme or 'https'}://{host}{parts.path or '/'}"
    else:
        url = parts.path or "/"
    return url, query


def _saved_responses(request: Mapping[str, Any]) -> List[Tuple[Optional[int], Optional[str]]]:
    """Read saved example responses (``responses: {name: {code, body}}``) as ``(status, body)``."""
    responses = request.get("responses")
    if not isinstance(responses, dict):
        return []
    examples: List[Tuple[Optional[int], Optional[str]]] = []
    for name in sorted(responses):
        example = responses[name]
        if not isinstance(example, dict):
            continue
        code = example.get("code")
        status = code if isinstance(code, int) and not isinstance(code, bool) else None
        body = example.get("body")
        examples.append((status, _scrub(body) if isinstance(body, str) else None))
    return examples


@dataclass
class _Reader:
    """Walks collection trees into observations, sharing one variable scope and server table."""

    scope: _Scope
    source_label: Optional[str]
    observations: List[HttpObservation] = field(default_factory=list)
    requests: List[HoppscotchRequest] = field(default_factory=list)
    server_variables: Dict[str, Optional[str]] = field(default_factory=dict)

    def read_node(
        self,
        node: Mapping[str, Any],
        *,
        path: Tuple[str, ...],
        pointer: str,
        auth: Optional[HoppscotchAuth],
        headers: List[Tuple[str, str]],
    ) -> None:
        """Read one collection or folder and everything beneath it.

        Args:
            node: The collection or folder object.
            path: Folder names from the collection root (the root itself excluded).
            pointer: JSON-pointer-like location for provenance (``folders/0/requests/1``).
            auth: The auth inherited from above.
            headers: The headers inherited from above.
        """
        where = "/".join(path) or "collection root"
        inherits, own = _read_auth(node.get("auth"), where)
        node_auth = auth if inherits else own
        node_headers = headers + _pairs(node.get("headers"), label=f"Headers of {where}")
        requests = node.get("requests")
        for index, request in enumerate(requests):
            if not isinstance(request, dict):
                raise HoppscotchParseError(f"Request {index} of {where} must be an object", code="INPUT_MALFORMED")
            self.read_request(
                request,
                folder=path,
                pointer=f"{pointer}requests/{index}",
                inherited_auth=node_auth,
                inherited_headers=node_headers,
            )
        for index, folder in enumerate(node.get("folders")):
            if not _is_collection_node(folder):
                raise HoppscotchParseError(
                    f"Folder {index} of {where} must have a name, folders[] and requests[]",
                    code="INPUT_MALFORMED",
                )
            self.read_node(
                folder,
                path=path + (str(folder.get("name") or f"folder-{index}"),),
                pointer=f"{pointer}folders/{index}/",
                auth=node_auth,
                headers=node_headers,
            )

    def read_request(
        self,
        request: Mapping[str, Any],
        *,
        folder: Tuple[str, ...],
        pointer: str,
        inherited_auth: Optional[HoppscotchAuth],
        inherited_headers: List[Tuple[str, str]],
    ) -> None:
        """Read one saved request into observations (one, plus one per saved example)."""
        name = str(request.get("name") or pointer)
        label = f"Request {name!r}"
        method = request.get("method")
        if not isinstance(method, str) or not method.strip():
            raise HoppscotchParseError(f"{label} has no method", code="INPUT_MALFORMED")
        endpoint = request.get("endpoint")
        if not isinstance(endpoint, str):
            raise HoppscotchParseError(f"{label} has no endpoint", code="INPUT_SEMANTIC_INVALID")
        request_vars = _request_variables(request)
        url, endpoint_query = _endpoint_url(endpoint, self.scope, request_vars, self.server_variables, label)
        inherits, own = _read_auth(request.get("auth"), "request")
        auth = inherited_auth if inherits else own

        own_headers = _pairs(request.get("headers"), label=f"{label} headers")
        merged: Dict[str, Tuple[str, str]] = {}
        for key, value in inherited_headers + own_headers:  # a request's own header wins
            merged[key.lower()] = (key, value)
        content_type, body = _body(request, label)
        if content_type and "content-type" not in merged:
            merged["content-type"] = ("Content-Type", content_type)
        headers = tuple((key, _scrub_named(key, value)) for key, value in (merged[name_] for name_ in sorted(merged)))
        query = endpoint_query + [
            (key, _scrub_named(key, value)) for key, value in _pairs(request.get("params"), label=f"{label} params")
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
        for status, response_body in _saved_responses(request):
            self.observations.append(
                HttpObservation(
                    method=observation.method,
                    url=url,
                    headers=headers,
                    query=tuple(query),
                    request_body=body,
                    response_status=status,
                    response_body=response_body,
                    source_location=pointer,
                    source_label=name,
                    source_file=self.source_label,
                )
            )
        self.requests.append(
            HoppscotchRequest(
                name=name,
                method=observation.method,
                url=url,
                folder=folder,
                auth=auth,
                content_type=content_type,
                has_scripts=bool(
                    str(request.get("preRequestScript") or "").strip() or str(request.get("testScript") or "").strip()
                ),
            )
        )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _collections(document: Any) -> List[Mapping[str, Any]]:
    return list(document) if isinstance(document, list) else [document]


def _environments(document: Any) -> List[Mapping[str, Any]]:
    return list(document) if isinstance(document, list) else [document]


def _count_requests(node: Mapping[str, Any]) -> int:
    total = len(node.get("requests") or [])
    for folder in node.get("folders") or []:
        if isinstance(folder, dict):
            total += _count_requests(folder)
    return total


def _build(
    collections: Sequence[Tuple[str, Any]],
    environments: Sequence[Tuple[str, Any]],
    source_label: Optional[str],
) -> HoppscotchDocument:
    """Read loaded collections (and environments) into one document.

    Args:
        collections: ``(label, loaded JSON)`` for each collection member.
        environments: ``(label, loaded JSON)`` for each environment member.
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        HoppscotchParseError: With the taxonomy code for the fault.
    """
    scope = _Scope()
    variables: List[HoppscotchVariable] = []
    environment_names: List[str] = []
    for label, document in environments:
        for environment in _environments(document):
            env_name = str(environment.get("name") or PurePosixPath(label or "environment").stem)
            environment_names.append(env_name)
            for entry in environment.get("variables") or []:
                if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
                    continue
                key = entry["key"]
                secret = bool(entry.get("secret"))
                scope.environment.setdefault(key, _variable_value(entry))
                if secret:
                    scope.secret.add(key)
                variables.append(HoppscotchVariable(name=key, source=f"environment:{env_name}", secret=secret))

    roots: List[Mapping[str, Any]] = []
    for label, document in collections:
        for collection in _collections(document):
            roots.append(collection)
            for entry in collection.get("variables") or []:
                if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                    key = entry["key"]
                    secret = bool(entry.get("secret"))
                    scope.collection.setdefault(key, _variable_value(entry))
                    if secret:
                        scope.secret.add(key)
                    variables.append(HoppscotchVariable(name=key, source="collection", secret=secret))

    if not any(_count_requests(root) for root in roots):
        raise HoppscotchParseError(
            "The collection has no requests in it or in any of its folders — there is nothing to import",
            code="INPUT_SEMANTIC_INVALID",
        )

    reader = _Reader(scope=scope, source_label=source_label)
    versions: List[str] = []
    for index, root in enumerate(roots):
        versions.append(str(root.get("v", "")))
        pointer = f"{index}/" if len(roots) > 1 else ""
        reader.read_node(root, path=(), pointer=pointer, auth=None, headers=[])

    names = [str(root.get("name") or "").strip() for root in roots]
    title = " · ".join(name for name in names if name) or "Hoppscotch collection"
    return HoppscotchDocument(
        title=title,
        observations=reader.observations,
        requests=reader.requests,
        server_variables=reader.server_variables,
        variables=sorted(set(variables), key=lambda var: (var.name, var.source)),
        collection_versions=versions,
        environments=environment_names,
        source_label=source_label,
    )


def _classify(document: Any, label: Optional[str]) -> str:
    """Return ``collection`` or ``environment`` for a loaded member, or raise ``FORMAT_MISMATCH``."""
    if is_hoppscotch_collection(document):
        return "collection"
    if is_hoppscotch_environment(document):
        return "environment"
    other = _looks_like_other_format(document)
    if other:
        raise HoppscotchParseError(
            f"The upload{_where(label)} is {other}, not a Hoppscotch collection",
            code="FORMAT_MISMATCH",
        )
    raise HoppscotchParseError(
        f"The upload{_where(label)} is not a Hoppscotch collection: expected `name`, `folders[]` and `requests[]`",
        code="FORMAT_MISMATCH",
    )


def parse_hoppscotch_text(raw: str, *, source_label: Optional[str] = None) -> HoppscotchDocument:
    """Parse one Hoppscotch collection export (a collection or a list of collections).

    Args:
        raw: The decoded upload.
        source_label: The filename or paste label.

    Returns:
        The parsed document.

    Raises:
        HoppscotchParseError: With the taxonomy code for the fault; an environment uploaded on its
            own is ``INPUT_SEMANTIC_INVALID``.
    """
    document = _load_json(raw, source_label)
    if _classify(document, source_label) == "environment":
        raise HoppscotchParseError(
            "This is a Hoppscotch environment, not a collection — upload it together with the collection that uses it",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _build([(source_label or "", document)], [], source_label)


def parse_hoppscotch_fileset(
    members: Mapping[str, str],
    *,
    root: Optional[str] = None,
    source_label: Optional[str] = None,
) -> HoppscotchDocument:
    """Parse a set of collection and environment exports into one API.

    Every JSON member is read: collections become requests, environments supply variables. Members
    that are not JSON (a README) are ignored.

    Args:
        members: Member text keyed by path.
        root: The root member's path.
        source_label: The upload's label.

    Returns:
        The parsed document.

    Raises:
        HoppscotchParseError: With the taxonomy code for the fault.
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
        raise HoppscotchParseError(
            "The upload has Hoppscotch environments but no collection to apply them to",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _build(collections, environments, source_label or root)
