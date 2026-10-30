"""Postman Collection → canonical model normalizer — on the shared inferred-spec engine (MFI-32.7).

Maps a parsed :class:`~app.postman_parser.PostmanDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.REST`.

**The engine does the inference (MFI-32.7, #4409).** Every request, and every saved example
response, becomes an :class:`~app.inferred_spec.HttpObservation` handed to the shared engine
(:mod:`app.inferred_spec`), which templates paths, unions query / header parameters and infers and
widens body schemas — the same engine HAR, Insomnia, Bruno, Hoppscotch and ``.http`` files use, so
none of that is forked here. Requests that share a method and a templated path become one operation
whose schemas cover all their samples. What the engine has no slot for is layered on afterwards,
with :mod:`app.client_collection` (MFI-32.5) where the facts are the same as the other collections':

* **folders → operation groups:** each operation is tagged with its folder path;
* **body content types:** the request message carries the body's media type;
* **environment variables → parameter defaults:** a query or header parameter written as a whole
  ``{{variable}}`` gets that variable's (non-secret) value as its default;
* **the Postman projection** the :mod:`app.postman_emitter` writes back for a round trip —
  ``postman_folder_path``, ``postman_headers``, ``postman_auth``, the request and response
  ``postman_body_*`` records, each parameter's ``postman_sample`` and the document's
  ``postman_schema_url`` / ``postman_variables`` / ``postman_collection_version`` /
  ``postman_auth``;
* **declared limits** (scripts, withheld credentials, secret variables, non-raw request bodies,
  requests merged into one operation) in ``extras["postman"]["capability_limits"]``.

One normalizer serves Collection v2.0 and v2.1 (FMT-3.6, #5431): the two minors' spelling
differences are resolved by the parser. Every value kept passes the MFI-32.5 secret-scrub gate; the
auth **scheme** is kept, never its credentials.

**What is inferred (FMT-8.6).** A collection declares its requests but no *schemas*: every operation,
parameter, message and type the engine builds is stamped
:data:`~app.inference_provenance.INFERRED`. A raw request body that is not JSON is typed as a string
by Apiome and stamped :data:`~app.inference_provenance.SYNTHESIZED`.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    ParameterLocation,
    Server,
)
from .client_collection import (
    MUSTACHE_REFERENCE_RE,
    SECRET_NAME_RE,
    annotate_operations,
    apply_parameter_defaults,
    declared_limit,
    folder_paths,
    scrub_value,
    template_servers,
)
from .client_collection import safe_named_value as _safe_value
from .client_collection import variable_record as _variable_record
from .inference_provenance import SYNTHESIZED, provenance_extras
from .inferred_spec import HttpObservation, infer_canonical_api
from .normalizer import Keys, Normalizer, SchemaCoercer, normalize_ordering
from .postman_parser import (
    PostmanAuth,
    PostmanDocument,
    PostmanOperation,
    postman_http_path,
)
from .security_scheme_stubs import apply_security_scheme_stubs

__all__ = ["PARTIAL_LIMITS", "POSTMAN_AUTH_SCHEMES", "POSTMAN_EXTRAS_KEY", "PostmanNormalizer"]

_FORMAT_KEY = "postman"

#: The root extras key holding the Postman projection record (declared limits, folders).
POSTMAN_EXTRAS_KEY = "postman"

#: Declared limits whose construct is modelled with a detail withheld (the coverage ledger grades
#: them ``partially-mapped``); every other limit is a construct left out.
PARTIAL_LIMITS = frozenset(
    {"postman.auth_credential", "postman.secret_variable", "postman.merged_request", "postman.body_mode"}
)

#: FMT-8.6 evidence for a raw request body that is not JSON: Apiome types it as a string.
_TEXT_BODY_EVIDENCE = "The raw body is not JSON, so Apiome typed it as a string."
_REF_PREFIX = "#/components/schemas/"

#: Postman auth ``type`` → the canonical scheme :mod:`app.canonical_security` reads (MFI-32.5).
#: Request-signing schemes have no canonical scheme of their own: a generic ``authorization``.
POSTMAN_AUTH_SCHEMES: Dict[str, str] = {
    "basic": "basic",
    "bearer": "bearer",
    "jwt": "bearer",
    "digest": "digest",
    "oauth2": "oauth2",
    "apikey": "apiKey",
}


# ---------------------------------------------------------------------------
# Requests → observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Request:
    """One Postman request, as the shared :mod:`app.client_collection` helpers read it.

    Satisfies :class:`~app.client_collection.ClientRequest` (``auth`` is always ``None``: Postman's
    auth is recorded in its own ``postman_auth`` shape below) and
    :class:`~app.client_collection.DefaultedRequest`.

    Attributes:
        method: The upper-cased HTTP method.
        url: The URL handed to the engine (the request's templated path).
        folder: The folder path the request sits in.
        content_type: The request body's media type, when it has a body.
        defaults: ``(location, name, value)`` for each parameter written as a whole variable whose
            non-secret value the collection defines.
        operation: The parsed request.
        order: The request's position in the collection (the first match names the operation).
    """

    method: str
    url: str
    folder: Tuple[str, ...]
    content_type: Optional[str]
    defaults: Tuple[Tuple[str, str, str], ...]
    operation: PostmanOperation
    order: int
    auth: None = None


def _canonical_scheme(auth_type: str) -> str:
    """The canonical scheme for a Postman auth type (``authorization`` for signing schemes)."""
    return POSTMAN_AUTH_SCHEMES.get(str(auth_type or "").strip().lower(), "authorization")


def _auth_extras(auth: Optional[PostmanAuth]) -> Optional[Dict[str, Any]]:
    """Render an auth declaration for the extras bag — scheme and parameter names only.

    Args:
        auth: The parsed auth declaration, or ``None``.

    Returns:
        ``{"type": …, "parameters": [...]}``, or ``None`` when nothing was declared. Credential
        *values* are deliberately absent: the parser never reads them.
    """
    if auth is None:
        return None
    return {"type": auth.type, "parameters": list(auth.parameters)}


def _apikey_placements(source: PostmanDocument) -> Dict[str, Dict[str, Any]]:
    """Where the collection's API key is sent, for its stub: the first request (else the collection) naming it."""
    declared = [endpoint.request.auth for endpoint in source.operations] + [source.auth]
    for auth in declared:
        if auth is not None and auth.key_name and _canonical_scheme(auth.type) == "apiKey":
            return {"apiKey": {"key_name": auth.key_name, "key_location": auth.key_location}}
    return {}


def _content_type(operation: PostmanOperation) -> Optional[str]:
    """The request body's media type: its ``Content-Type`` header, else what the raw body looks like."""
    request = operation.request
    for header in request.headers:
        if not header.disabled and header.key.strip().lower() == "content-type" and header.value:
            return header.value.split(";", 1)[0].strip() or None
    body = request.body
    if body is None or not body.raw:
        return None
    if (body.language or "").lower() == "json" or body.raw.lstrip().startswith(("{", "[")):
        return "application/json"
    return "text/plain"


def _whole_variable(value: Optional[str]) -> Optional[str]:
    """The variable name when ``value`` is written entirely as ``{{name}}``, else ``None``."""
    if not value or not MUSTACHE_REFERENCE_RE.match(value):
        return None
    return value.strip()[2:-2].strip() or None


def _defaults(operation: PostmanOperation, variables: Mapping[str, Dict[str, Any]]) -> Tuple[Tuple[str, str, str], ...]:
    """Parameter defaults from collection / environment variables — never a secret one."""
    out: Set[Tuple[str, str, str]] = set()
    pairs: List[Tuple[str, str, Optional[str]]] = [
        ("query", query.name, query.value) for query in operation.request.url.query if not query.disabled
    ] + [("header", header.key.lower(), header.value) for header in operation.request.headers if not header.disabled]
    for location, name, value in pairs:
        variable = _whole_variable(value)
        record = variables.get(variable or "")
        if record is None or record.get("secret") or SECRET_NAME_RE.search(name):
            continue
        resolved = record.get("value")
        if isinstance(resolved, str) and resolved and not MUSTACHE_REFERENCE_RE.match(resolved):
            out.add((location, name, scrub_value(resolved)))
    return tuple(sorted(out))


def _observations(
    source: PostmanDocument, variables: Mapping[str, Dict[str, Any]]
) -> Tuple[List[HttpObservation], List[_Request]]:
    """Read every request (and each of its saved example responses) into engine observations.

    A request with saved examples becomes one observation per example — so each example's status
    and body reach the engine — and a request without any becomes one observation with no response.
    Header and query values pass :func:`~app.client_collection.safe_named_value`; bodies pass the
    secret-scrub gate.

    Args:
        source: The parsed collection.
        variables: Variable name → its :func:`~app.client_collection.variable_record`.

    Returns:
        The observations and the per-request facts the post-processing helpers read.
    """
    observations: List[HttpObservation] = []
    requests: List[_Request] = []
    for order, endpoint in enumerate(source.operations):
        request = endpoint.request
        url = postman_http_path(request.url)
        headers = tuple(
            (header.key, _safe_value(header.key, header.value) or "")
            for header in request.headers
            if not header.disabled
        )
        query = tuple(
            (param.name, _safe_value(param.name, param.value) or "")
            for param in request.url.query
            if not param.disabled
        )
        body = request.body
        request_body = scrub_value(body.raw) if body is not None and body.mode == "raw" and body.raw else None
        label = " / ".join((*endpoint.folder_path, endpoint.name))

        def observe(status: Optional[int] = None, response_body: Optional[str] = None) -> None:
            observations.append(
                HttpObservation(
                    method=request.method,
                    url=url,
                    headers=headers,
                    query=query,
                    request_body=request_body,
                    response_status=status,
                    response_body=response_body,
                    source_location=label,
                    source_label=endpoint.name,
                )
            )

        if endpoint.responses:
            for response in endpoint.responses:
                raw = response.body.raw if response.body is not None else None
                observe(response.code or 200, scrub_value(raw) if raw else None)
        else:
            observe()
        requests.append(
            _Request(
                method=request.method,
                url=url,
                folder=tuple(endpoint.folder_path),
                content_type=_content_type(endpoint) if request_body is not None else None,
                defaults=_defaults(endpoint, variables),
                operation=endpoint,
                order=order,
            )
        )
    return observations, requests


# ---------------------------------------------------------------------------
# The Postman projection layered on the engine's operations
# ---------------------------------------------------------------------------


def _matched_requests(operation: Operation, index: Mapping[Tuple[str, str], List[_Request]]) -> List[_Request]:
    """The requests an engine operation was built from, in collection order."""
    evidence = operation.extras.get("inference_evidence") or {}
    matched: Dict[int, _Request] = {}
    for url in dict.fromkeys(evidence.get("sample_urls") or []):
        for request in index.get((operation.http_method or "", url), []):
            matched[request.order] = request
    return [matched[order] for order in sorted(matched)]


def _body_extras(operation: PostmanOperation) -> Dict[str, Any]:
    """The ``postman_body_*`` record of a raw request body (what the emitter writes back)."""
    body = operation.request.body
    assert body is not None and body.raw  # callers check
    return {
        "postman_body_mode": body.mode,
        "postman_body_raw": scrub_value(body.raw),
        "postman_body_language": body.language,
    }


def _project_operation(operation: Operation, matched: Sequence[_Request], coercer: SchemaCoercer) -> None:
    """Layer the Postman projection onto one engine operation (in place).

    The first request it was built from names it and gives its description, folder, headers and
    auth — what a round trip writes back for the one Postman request the operation becomes.

    Args:
        operation: The engine's operation.
        matched: The requests it was built from (non-empty).
        coercer: Builds the string payload of a non-JSON request body.
    """
    first = matched[0].operation
    request = first.request
    operation.name = first.name
    if request.description:
        operation.description = request.description
    operation.extras["postman_folder_path"] = list(first.folder_path)
    operation.extras["postman_headers"] = [
        {"key": header.key, "value": _safe_value(header.key, header.value), "disabled": header.disabled}
        for header in request.headers
    ]
    auth = _auth_extras(request.auth)
    if auth is not None:
        operation.extras["postman_auth"] = auth
        operation.extras["security"] = [_canonical_scheme(auth["type"])]

    query_samples = {param.name: param.value for param in request.url.query if not param.disabled}
    # A path variable saved with no value has no sample (an exported one is written back empty).
    path_samples = {variable.key: variable.value for variable in request.url.variables if variable.value}
    for parameter in operation.parameters:
        if parameter.location is ParameterLocation.QUERY:
            parameter.extras["postman_style"] = "query"
            if parameter.name in query_samples:
                parameter.extras["postman_sample"] = _safe_value(parameter.name, query_samples[parameter.name])
        elif parameter.location is ParameterLocation.PATH:
            parameter.extras["postman_style"] = "path"
            if parameter.name in path_samples:
                parameter.extras["postman_sample"] = _safe_value(parameter.name, path_samples[parameter.name])

    with_body = next(
        (req.operation for req in matched if req.operation.request.body is not None
         and req.operation.request.body.mode == "raw" and req.operation.request.body.raw),
        None,
    )
    request_message = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
    if with_body is not None:
        if request_message is not None:
            request_message.extras.update(_body_extras(with_body))
        else:
            # Not JSON, so the engine inferred nothing: Apiome types it as a string (FMT-8.6).
            operation.messages.insert(
                0,
                Message(
                    key=Keys.request_message(operation.key),
                    role=MessageRole.REQUEST,
                    payload=coercer.type_ref({"type": "string"}, required=True),
                    required=True,
                    content_types=[matched[0].content_type or "text/plain"],
                    extras={**_body_extras(with_body), **provenance_extras(SYNTHESIZED, _TEXT_BODY_EVIDENCE)},
                ),
            )

    examples: Dict[str, Any] = {}
    for req in matched:
        for response in req.operation.responses:
            examples.setdefault(str(response.code or 200), response)
    for message in operation.messages:
        if message.role is not MessageRole.RESPONSE:
            continue
        example = examples.get(str(message.status_code or message.extras.get("http_status") or ""))
        if example is None:
            continue
        message.name = example.name
        if example.body is not None and example.body.raw:
            message.extras["postman_body_raw"] = scrub_value(example.body.raw)


# ---------------------------------------------------------------------------
# Declared limits
# ---------------------------------------------------------------------------


def _items(document: Any) -> Iterable[Tuple[str, Mapping[str, Any]]]:
    """Every request item of a collection's JSON, with its name (folders walked)."""
    stack = list(document.get("item") or []) if isinstance(document, Mapping) else []
    while stack:
        entry = stack.pop(0)
        if not isinstance(entry, Mapping):
            continue
        if isinstance(entry.get("request"), (Mapping, str)):
            yield str(entry.get("name") or "Request"), entry
        elif isinstance(entry.get("item"), list):
            stack[0:0] = list(entry["item"])


def _has_script(entry: Mapping[str, Any]) -> bool:
    """Whether a collection, folder or request carries a pre-request or test script."""
    for event in entry.get("event") or []:
        script = event.get("script") if isinstance(event, Mapping) else None
        lines = script.get("exec") if isinstance(script, Mapping) else None
        if isinstance(lines, list) and any(isinstance(line, str) and line.strip() for line in lines):
            return True
        if isinstance(lines, str) and lines.strip():
            return True
    return False


def _capability_limits(
    source: PostmanDocument, variables: Sequence[Dict[str, Any]], merged: Sequence[List[str]]
) -> List[Dict[str, Any]]:
    """The constructs the import leaves out or withholds, for the coverage ledger.

    Args:
        source: The parsed collection.
        variables: The collection's variable records.
        merged: The request names of each operation built from more than one request.

    Returns:
        The declared-limit records.
    """
    limits: List[Dict[str, Any]] = []
    try:
        document = json.loads(source.raw) if isinstance(source.raw, str) else None
    except json.JSONDecodeError:  # pragma: no cover - the parser already loaded it
        document = None
    scripted = [name for name, entry in _items(document) if _has_script(entry)]
    if isinstance(document, Mapping) and _has_script(document):
        scripted.insert(0, source.name)
    if scripted:
        limits.append(
            declared_limit(
                "postman.script",
                scripted,
                "Pre-request and test scripts are run by Postman; they are not modelled.",
            )
        )
    authed = [endpoint.name for endpoint in source.operations if endpoint.request.auth is not None]
    if source.auth is not None:
        authed.insert(0, source.name)
    if authed:
        limits.append(
            declared_limit(
                "postman.auth_credential",
                authed,
                "The auth scheme (and an API key's name and placement) is kept; saved credentials are never read.",
            )
        )
    secret = [record["key"] for record in variables if record.get("secret")]
    if secret:
        limits.append(
            declared_limit(
                "postman.secret_variable",
                secret,
                "A secret variable (by its name, or a value the scrub gate flags) is listed by name; "
                "its value is withheld.",
            )
        )
    other_bodies = [
        endpoint.name
        for endpoint in source.operations
        if endpoint.request.body is not None and endpoint.request.body.mode not in (None, "raw")
    ]
    if other_bodies:
        limits.append(
            declared_limit(
                "postman.body_mode",
                other_bodies,
                "Form-data, URL-encoded, GraphQL and file bodies are not read; only raw bodies give a request schema.",
            )
        )
    for names in merged:
        limits.append(
            declared_limit(
                "postman.merged_request",
                names,
                "These requests share a method and path, so they are one operation whose schemas cover every "
                "request; the first request names it.",
            )
        )
    return limits


# ---------------------------------------------------------------------------
# The normalizer
# ---------------------------------------------------------------------------


def _scrubbed_raw(raw: Any) -> Any:
    """The parsed collection with credentials removed, for ``api.raw`` (MFI-32.5).

    The redaction marker carries no quote or escape character, so the scrubbed JSON still parses.
    The parser keeps the collection as its source *text*: that text is scrubbed as it is. Encoding it
    as a JSON string first would escape every quote, and the gate's ``"key": "value"`` rules would
    no longer see the credentials in it (MFI-32.7).
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        return scrub_value(raw)
    return json.loads(scrub_value(json.dumps(raw)))


def _servers(source: PostmanDocument) -> List[Server]:
    """The collection's server: a literal ``baseUrl``, else a ``{baseUrl}`` variable to fill in."""
    base = next((var for var in source.variables if var.key == "baseUrl"), None)
    if base is None:
        return []
    if base.value and _safe_value(base.key, base.value) == base.value:
        return [Server(url=base.value, description="From Postman collection variable")]
    # MFI-32.5: a `baseUrl` with no value, or one carrying a credential, keeps only its name — as a
    # server variable the user fills in.
    return template_servers({"baseUrl": None}, describe=lambda name: f"Postman variable `{{{{{name}}}}}`.")


class PostmanNormalizer(Normalizer, register=True):
    """Normalize a parsed Postman collection via the shared inferred-spec engine."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.REST

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Build the canonical model for a parsed Postman collection.

        Args:
            source: A :class:`~app.postman_parser.PostmanDocument`.
            include_raw: Whether to keep the (scrubbed) collection on ``raw``.

        Returns:
            The canonical model: one REST service of inferred operations.

        Raises:
            ValueError: When ``source`` is not a parsed Postman document.
        """
        if not isinstance(source, PostmanDocument):
            raise ValueError(
                "Postman source must be a PostmanDocument (see app.postman_parser.parse_postman)"
            )
        variable_records = [_variable_record(variable.key, variable.value) for variable in source.variables]
        by_name = {record["key"]: record for record in variable_records}
        observations, requests = _observations(source, by_name)

        api = infer_canonical_api(
            observations, title=source.name, format_key=_FORMAT_KEY, include_raw=False
        ).api
        annotate_operations(api, requests, auth_extras_key="postman_resolved_auth")
        apply_parameter_defaults(api, requests)

        index: Dict[Tuple[str, str], List[_Request]] = defaultdict(list)
        for request in requests:
            index[(request.method, request.url)].append(request)
        coercer = SchemaCoercer(components={}, ref_prefix=_REF_PREFIX)
        merged: List[List[str]] = []
        for operation in api.operations():
            matched = _matched_requests(operation, index)
            if not matched:
                continue
            _project_operation(operation, matched, coercer)
            names = list(dict.fromkeys(req.operation.name for req in matched))
            if len(names) > 1:
                merged.append(names)

        api.description = source.description
        api.servers = _servers(source)
        api.raw = {"postman": _scrubbed_raw(source.raw)} if include_raw else None
        extras = api.extras
        extras["postman_schema_url"] = source.schema_url
        extras["postman_variables"] = variable_records
        if source.collection_version:
            extras["postman_collection_version"] = source.collection_version
        schemes = set(extras.get("inferred_auth_schemes") or [])
        schemes.update(
            scheme for operation in api.operations() for scheme in operation.extras.get("security") or []
        )
        collection_auth = _auth_extras(source.auth)
        if collection_auth is not None:
            extras["postman_auth"] = collection_auth
            # The collection's auth applies to requests that inherit it, which the parser cannot tell
            # apart from an explicit `noauth`; so it is recorded as an observed scheme (a stub), not a
            # per-operation requirement.
            schemes.add(_canonical_scheme(collection_auth["type"]))
        if schemes:
            extras["inferred_auth_schemes"] = sorted(schemes)
        extras[POSTMAN_EXTRAS_KEY] = {
            "folders": folder_paths(requests),
            "requests": len(requests),
            "capability_limits": _capability_limits(source, variable_records, merged),
        }
        apply_security_scheme_stubs(api, placements=_apikey_placements(source))
        return normalize_ordering(api)
