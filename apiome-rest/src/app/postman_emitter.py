"""Postman emitter: canonical model → Postman Collection v2.1 — MFX-31.1 (#4289).

The inverse of :class:`app.postman_normalizer.PostmanNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The collection validates against the published Postman Collection
v2.1.0 JSON Schema (draft-07, vendored as ``data/postman_collection_v2_1_0_schema.json``;
:func:`validate_postman_collection`).

Requests, values, auth, example bodies and losses are planned by :mod:`app.client_collection_emit`
— the plan Hoppscotch and Thunder Client are written from — and this module writes Postman's JSON:

* **Folders.** Requests are filed by the **folder_strategy** option: ``auto`` (default — the
  operation's first tag, else its service when the API has more than one), ``tag``, ``service`` or
  ``flat``. Folders nest (``Admin/Reports``).
* **Variables.** With **variable_style** ``variables`` (default) every server becomes a collection
  variable — ``{{baseUrl}}``, then ``{{baseUrl2}}`` … — and a server template's own variables
  (``https://{{region}}.example.com``) are declared with their defaults; request URLs use
  ``{{baseUrl}}``. With ``inline`` the requests carry the literal server URL and only credential
  variables are declared.
* **Requests.** Method, ``:param`` path variables with example values, query parameters (optional
  ones disabled), headers, and an example body **synthesized** from the request schema
  (**example_depth** ``minimal`` — required properties only — or ``full``).
* **Responses.** Each single-status response becomes a saved example response with a body
  synthesized from its schema.
* **Auth.** ``bearer``, ``basic``, ``digest``, ``apiKey`` and ``oauth2`` become Postman auth blocks
  whose credentials are ``{{variable}}`` references declared with an empty value — never a secret.
  When every request uses the same auth it is written once on the collection and inherited.

A collection imported from Postman is written back as it was read: its own folder tree, headers,
raw bodies, saved responses, collection variables and auth schemes (with empty credential values).
"""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from urllib.parse import urlsplit

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi, MessageRole, Operation, Server
from .client_collection import scrub_value
from .client_collection_emit import (
    ClientAuth,
    ClientBody,
    ClientPair,
    CollectionPlan,
    PlannedRequest,
    PlannedResponse,
    client_collection_profile,
    output_slug,
    plan_collection,
)
from .client_collection_fidelity import ExampleCollectionFidelityRulePack
from .emitter import CapabilityProfile, EmitOptions, EmitOptionsError, EmitResult, EmittedFile, Emitter, LossKind
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = [
    "POSTMAN_AUTH_BLOCKS",
    "PostmanEmitOptions",
    "PostmanEmitter",
    "PostmanFidelityRulePack",
    "validate_postman_collection",
]

_FORMAT_KEY = "postman"
_POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "postman_collection_v2_1_0_schema.json"
_MEDIA_TYPE = "application/json"

#: Plan losses that do not hold for a collection imported from Postman, which is written back from its
#: own variables, enabled query parameters, raw example bodies and inferred body shapes.
_NATIVE_NON_LOSSES = frozenset(
    {"synthesized-base-url", "optional-parameters-disabled", "example-response-synthesized", "types-not-declared"}
)

#: Canonical schemes Postman writes as an auth block.
POSTMAN_AUTH_BLOCKS = frozenset({"bearer", "basic", "digest", "apiKey", "oauth2"})

#: A server template's ``{name}`` variable.
_SERVER_VARIABLE_RE = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")


def ref(variable: str) -> str:
    """A Postman variable reference (``{{name}}``)."""
    return "{{" + variable + "}}"


# ===========================================================================
# Validation
# ===========================================================================


def validate_postman_collection(text: str) -> None:
    """Validate an emitted collection: the Postman v2.1.0 JSON Schema, then a re-parse.

    Args:
        text: The collection JSON.

    Raises:
        ValueError: When the text is not JSON, breaks the published v2.1.0 schema (the first few
            violations are named with their JSON path), or does not re-parse as a Postman collection.
    """
    from jsonschema import Draft7Validator

    from .postman_parser import parse_postman

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Postman collection: not JSON ({exc.msg})") from exc
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        detail = "; ".join(
            f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: {error.message}"
            for error in errors[:5]
        )
        raise ValueError(f"Invalid Postman collection (v2.1.0 schema): {detail}")
    parse_postman(text)


# ===========================================================================
# Fidelity
# ===========================================================================


class PostmanFidelityRulePack(ExampleCollectionFidelityRulePack):
    """Fidelity rules for Postman export.

    The example-collection rules (MFX-31.2, :mod:`app.client_collection_fidelity`) — schemas become
    example bodies and saved example responses, unions one representative example, generated values
    are synthesized, streaming and auth Postman has no type for are named — with what a Postman
    collection carries that the other clients do not: the API description and version and every
    server (as a collection variable).
    """

    target_label = "Postman collection"
    format_key = _FORMAT_KEY
    auth_blocks = POSTMAN_AUTH_BLOCKS

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A model from another format loses its format and identity; servers become variables.

        A Collection v2.0 source is written back as v2.1, which a re-import records as its version.
        """
        if api.format == self.format_key:
            if _is_v2_0(api):
                return [FidelityVerdict.approx(
                    message="Postman collection is written as Collection v2.1; the source's v2.0 is not kept",
                    target_mapping="collection v2.0 → v2.1",
                )]
            return []
        return [
            FidelityVerdict.approx(
                message=(
                    "Postman collection keeps the API's name, description and version, and writes its "
                    "servers as collection variables; the source format and identity are not carried"
                ),
                target_mapping="artifact root → collection info + variables",
            )
        ]

    def request_verdict(self, operation: Operation) -> FidelityVerdict:
        """The saved request: a re-import infers the operation again from it."""
        return FidelityVerdict.approx(
            message=(
                f"Postman collection saves {operation.key!r} as one request; a re-import infers the operation "
                "again from it, so parameter types and descriptions and extra tags are not carried"
            ),
            target_mapping="operation → saved request",
        )


# ===========================================================================
# Emitter
# ===========================================================================


class PostmanEmitOptions(EmitOptions):
    """Per-target options for :class:`PostmanEmitter` (MFX-1.4)."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")
    folder_strategy: Literal["auto", "tag", "service", "flat"] = Field(
        default="auto",
        description="How requests are filed into folders: `auto` (first tag, else service when the API has more "
        "than one), `tag`, `service` or `flat`. A collection imported from Postman keeps its own folders under "
        "`auto` and `service`.",
    )
    variable_style: Literal["variables", "inline"] = Field(
        default="variables",
        description="`variables`: servers become collection variables ({{baseUrl}}) that request URLs use. "
        "`inline`: requests carry the literal server URL and only credential variables are declared.",
    )
    example_depth: Literal["minimal", "full"] = Field(
        default="minimal",
        description="Synthesized example bodies fill required properties only (`minimal`) or every "
        "declared property (`full`).",
    )


class PostmanEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Postman Collection v2.1 JSON document."""

    key = "postman"
    format = "postman"
    label = "Postman"
    description = (
        "Export as a Postman Collection v2.1: requests foldered by tag or service, servers as collection "
        "variables, synthesized example bodies and responses, and collection auth with empty credentials."
    )
    icon = "file-json"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = PostmanEmitOptions
    #: X1 (#6222): refused with a reason, never crashed, when the source lacks this.
    requires_source = ("http-operation",)

    OUTPUT_MEDIA_TYPE = _MEDIA_TYPE

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A call surface (see :func:`app.client_collection_emit.client_collection_profile`)."""
        return client_collection_profile()

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Postman degradation rules."""
        return PostmanFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[PostmanEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one Postman collection.

        Args:
            api: The canonical model to export.
            opts: Per-target options (:class:`PostmanEmitOptions`).

        Returns:
            A one-file :class:`~app.emitter.EmitResult`.

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            EmitPreconditionError: When ``api`` has no HTTP operation.
        """
        options = _coerce_options(opts)
        plan = plan_collection(
            api,
            target_label="Postman",
            auth_blocks=POSTMAN_AUTH_BLOCKS,
            folder_strategy=options.folder_strategy,
            example_depth=options.example_depth,
            carry_responses=True,
            carries_description=True,
            carries_all_servers=options.variable_style == "variables",
        )
        document = _Writer(api, plan, options).collection()
        if _is_v2_0(api):
            plan.losses.record(
                LossKind.INFERRED,
                "collection-upgraded",
                "The Postman Collection v2.0 source is written as Collection v2.1.",
                pointer="",
            )
        indent = options.indent if options.indent > 0 else None
        return EmitResult(
            files=[
                EmittedFile(
                    path=f"{output_slug(api)}.postman_collection.json",
                    content=json.dumps(document, indent=indent, ensure_ascii=False) + "\n",
                    media_type=_MEDIA_TYPE,
                )
            ],
            media_type=_MEDIA_TYPE,
            provenance=plan.tracker.records(),
            losses=[
                loss
                for loss in plan.losses.records()
                if api.format != _FORMAT_KEY or loss.subject not in _NATIVE_NON_LOSSES
            ],
        )


def _is_v2_0(api: CanonicalApi) -> bool:
    """Whether ``api`` was imported from a Postman Collection v2.0."""
    return api.format == _FORMAT_KEY and api.extras.get("postman_collection_version") == "2.0"


def _coerce_options(opts: Optional[Union[PostmanEmitOptions, EmitOptions]]) -> PostmanEmitOptions:
    """Validate caller-supplied options into :class:`PostmanEmitOptions`."""
    if isinstance(opts, PostmanEmitOptions):
        return opts
    try:
        return PostmanEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Postman emit options: {exc}") from exc


# ===========================================================================
# Rendering
# ===========================================================================


def _value(pair: ClientPair) -> str:
    """A pair's saved value: a reference for a credential, else the literal."""
    return pair.prefix + ref(pair.variable) if pair.variable else pair.value


def _templated(url: str) -> str:
    """A server URL with its ``{name}`` template variables as Postman ``{{name}}`` references."""
    return _SERVER_VARIABLE_RE.sub(lambda match: ref(match.group(1)), url)


def _auth(auth: ClientAuth) -> Dict[str, Any]:
    """A Postman v2.1 auth block whose credential fields are variable references."""
    def entries(*pairs: Tuple[str, str]) -> List[Dict[str, str]]:
        return [{"key": key, "value": value, "type": "string"} for key, value in pairs]

    if auth.scheme == "bearer":
        return {"type": "bearer", "bearer": entries(("token", ref("accessToken")))}
    if auth.scheme in ("basic", "digest"):
        return {auth.scheme: entries(("username", ref("username")), ("password", ref("password"))),
                "type": auth.scheme}
    if auth.scheme == "apiKey":
        return {"type": "apikey", "apikey": entries(
            ("key", auth.parameter or "X-API-Key"), ("value", ref("apiKey")), ("in", auth.location))}
    # oauth2
    pairs = [("grant_type", auth.grant_type or "client_credentials"),
             ("clientId", ref("clientId")), ("clientSecret", ref("clientSecret"))]
    if auth.token_url:
        pairs.append(("accessTokenUrl", auth.token_url))
    if auth.scopes:
        pairs.append(("scope", " ".join(auth.scopes)))
    return {"type": "oauth2", "oauth2": entries(*pairs)}


def _source_auth(record: Any) -> Optional[Dict[str, Any]]:
    """An imported Postman auth record (scheme + parameter names) as a block with empty values."""
    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
        return None
    kind = record["type"]
    names = [str(name) for name in record.get("parameters") or []]
    return {"type": kind, kind: [{"key": name, "value": "", "type": "string"} for name in names]}


def _body(body: ClientBody) -> Dict[str, Any]:
    """A request body: raw JSON text, or url-encoded / multipart form fields."""
    if not body.is_form:
        return {"mode": "raw", "raw": body.text(ref), "options": {"raw": {"language": "json"}}}
    mode = "formdata" if body.content_type.lower().startswith("multipart/") else "urlencoded"
    return {mode: [{"key": field.name, "value": _value(field), "type": "text"} for field in body.fields], "mode": mode}


def _status_text(status: str) -> str:
    """The reason phrase of an HTTP status (``OK``), or the code itself when unknown."""
    try:
        return HTTPStatus(int(status)).phrase
    except ValueError:
        return status


class _Writer:
    """Writes one plan as a Postman v2.1 collection (single use)."""

    def __init__(self, api: CanonicalApi, plan: CollectionPlan, options: PostmanEmitOptions) -> None:
        self._api = api
        self._plan = plan
        self._options = options
        self._postman_source = api.format == _FORMAT_KEY
        self._inline = options.variable_style == "inline"
        self._operations: Dict[str, Operation] = {op.key: op for op in api.operations()}

    # -- document ---------------------------------------------------------

    def collection(self) -> Dict[str, Any]:
        """The collection document: ``info``, nested ``item``, ``variable`` and ``auth``."""
        own_url = self._api.extras.get("postman_schema_url") if self._postman_source else None
        info: Dict[str, Any] = {
            "name": self._plan.title,
            # A v2.1 emitter: a v2.0 source's own URL would claim the shapes written here are v2.0.
            "schema": own_url if isinstance(own_url, str) and "v2.1" in own_url else _POSTMAN_SCHEMA_URL,
        }
        if self._api.description:
            info["description"] = self._api.description
        if self._api.version and not self._postman_source:
            info["version"] = self._api.version
        document: Dict[str, Any] = {"info": info, "item": self._items()}
        variables = self._variables()
        if variables:
            document["variable"] = variables
        auth = self._collection_auth()
        if auth is not None:
            document["auth"] = auth
        return document

    def _variables(self) -> List[Dict[str, Any]]:
        """The collection variables (see the module docstring)."""
        imported = self._api.extras.get("postman_variables") if self._postman_source else None
        if isinstance(imported, list):
            # MFI-32.5: an imported secret variable keeps its name only, so it is exported as an empty
            # placeholder for the user to fill in — never a value, and never Apiome's `secret` flag.
            return [
                {"key": record.get("key"), "value": "" if record.get("secret") else record.get("value", "")}
                for record in imported
                if isinstance(record, dict) and isinstance(record.get("key"), str)
            ]
        out: List[Dict[str, Any]] = []
        seen: set = set()

        def add(key: str, value: str, description: Optional[str] = None) -> None:
            if key in seen:
                return
            seen.add(key)
            entry: Dict[str, Any] = {"key": key, "value": value}
            if description:
                entry["description"] = description
            out.append(entry)

        for variable in self._plan.variables:
            if variable.secret:
                continue
            if self._inline:
                continue
            add(variable.name, self._base_value(variable.value))
        if not self._inline:
            for index, server in enumerate(self._templated_servers()):
                if index:
                    add(f"{self._plan.base_variable}{index + 1}", scrub_value(_templated(server.url)),
                        server.description or server.name)
                for template in server.variables:
                    default = template.default if template.default is not None else (template.enum or [""])[0]
                    add(template.name, scrub_value(str(default)), template.description)
        for variable in self._plan.variables:
            if variable.secret:
                add(variable.name, "", "Credential: fill in before sending.")
        return out

    def _templated_servers(self) -> List[Server]:
        """The servers written as variables: every server whose URL is not a bare ``{variable}``."""
        return [server for server in self._api.servers if server.url and not re.fullmatch(r"\{[^{}]+\}", server.url)]

    def _base_value(self, planned: str) -> str:
        """The base variable's value: the first server with its template variables, else the plan's."""
        servers = self._templated_servers()
        if servers and self._api.servers and servers[0] is self._api.servers[0]:
            return scrub_value(_templated(servers[0].url))
        return planned

    def _collection_auth(self) -> Optional[Dict[str, Any]]:
        if self._postman_source:
            return _source_auth(self._api.extras.get("postman_auth"))
        return _auth(self._plan.shared_auth) if self._plan.shared_auth is not None else None

    # -- items --------------------------------------------------------------

    def _items(self) -> List[Dict[str, Any]]:
        """The item tree: folders (nested) holding requests, in first-seen order."""
        root: Dict[str, Any] = {"item": []}
        folders: Dict[Tuple[str, ...], Dict[str, Any]] = {(): root}
        for request in self._plan.requests:
            path = self._folder(request)
            for depth in range(1, len(path) + 1):
                key = path[:depth]
                if key not in folders:
                    folder = {"name": key[-1], "item": []}
                    folders[key[:-1]]["item"].append(folder)
                    folders[key] = folder
            folders[path]["item"].append(self._item(request))
        return root["item"]

    def _folder(self, request: PlannedRequest) -> Tuple[str, ...]:
        """A Postman source's own folder tree (``auto`` / ``service``), else the plan's folder."""
        operation = self._operations.get(request.operation_key)
        own = operation.extras.get("postman_folder_path") if operation is not None and self._postman_source else None
        if isinstance(own, list) and self._options.folder_strategy in ("auto", "service"):
            return tuple(str(part) for part in own)
        return request.folder

    def _item(self, request: PlannedRequest) -> Dict[str, Any]:
        operation = self._operations[request.operation_key]
        http = self._request(request, operation)
        item: Dict[str, Any] = {"name": request.name, "request": http, "response": self._responses(request, http)}
        return item

    def _request(self, request: PlannedRequest, operation: Operation) -> Dict[str, Any]:
        http: Dict[str, Any] = {
            "method": request.method,
            "header": self._headers(request, operation),
            "url": self._url(request, operation),
        }
        if operation.description:
            http["description"] = operation.description
        body = self._source_body(operation) if self._postman_source else None
        if body is None and request.body is not None:
            body = _body(request.body)
        if body is not None:
            http["body"] = body
        auth = self._request_auth(request, operation)
        if auth is not None:
            http["auth"] = auth
        return http

    def _request_auth(self, request: PlannedRequest, operation: Operation) -> Optional[Dict[str, Any]]:
        if self._postman_source:
            return _source_auth(operation.extras.get("postman_auth"))
        if request.auth is None or request.auth == self._plan.shared_auth:
            return None
        return _auth(request.auth)

    def _headers(self, request: PlannedRequest, operation: Operation) -> List[Dict[str, Any]]:
        own = operation.extras.get("postman_headers") if self._postman_source else None
        if isinstance(own, list):
            return [entry for entry in own if isinstance(entry, dict) and isinstance(entry.get("key"), str)]
        headers: List[Dict[str, Any]] = []
        for pair in request.headers:
            entry: Dict[str, Any] = {"key": pair.name, "value": _value(pair)}
            if not pair.enabled:
                entry["disabled"] = True
            headers.append(entry)
        return headers

    def _source_body(self, operation: Operation) -> Optional[Dict[str, Any]]:
        """A Postman source's raw request body, written back as it was read."""
        message = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        raw = message.extras.get("postman_body_raw") if message is not None else None
        if not isinstance(raw, str) or not raw:
            return None
        body: Dict[str, Any] = {"mode": message.extras.get("postman_body_mode") or "raw", "raw": raw}
        language = message.extras.get("postman_body_language")
        if isinstance(language, str) and language:
            body["options"] = {"raw": {"language": language}}
        return body

    def _url(self, request: PlannedRequest, operation: Operation) -> Dict[str, Any]:
        """The request URL: ``{{baseUrl}}`` (or the literal server), ``:param`` path variables, query."""
        segments: List[str] = []
        path_text = ""
        for kind, text in request.path:
            path_text += f":{text}" if kind == "param" else text
        segments = [segment for segment in path_text.strip("/").split("/") if segment]
        samples = {
            parameter.name: parameter.extras.get("postman_sample")
            for parameter in operation.parameters
            if self._postman_source
        }
        variables = [
            {"key": name, "value": str(samples.get(name) or value or "")} for name, value in request.path_values
        ]
        # An optional parameter is saved disabled (not sent) — except in a collection imported from Postman,
        # whose query parameters were all sent as written.
        query = [
            {"key": pair.name, "value": str(samples.get(pair.name) or _value(pair))}
            | ({} if pair.enabled or self._postman_source else {"disabled": True})
            for pair in request.query
        ]
        origin = request.origin or (self._literal_base() if self._inline else None)
        if origin is not None:
            parts = urlsplit(origin)
            base_path = [segment for segment in parts.path.strip("/").split("/") if segment]
            host = parts.hostname or parts.netloc
            url: Dict[str, Any] = {
                "raw": origin.rstrip("/") + ("/" + "/".join(segments) if segments else ""),
                "protocol": parts.scheme or "https",
                "host": host.split("."),
                "path": base_path + segments,
            }
            if parts.port:
                url["port"] = str(parts.port)
        else:
            base = ref(self._plan.base_variable)
            url = {
                "raw": base + ("/" + "/".join(segments) if segments else ""),
                "host": [base],
                "path": segments,
            }
        if query:
            url["raw"] += "?" + "&".join(f"{entry['key']}={entry['value']}" for entry in query
                                         if not entry.get("disabled"))
            url["raw"] = url["raw"].rstrip("?")
            url["query"] = query
        if variables:
            url["variable"] = variables
        return url

    def _literal_base(self) -> str:
        """The literal server URL ``inline`` requests are written against (the plan's resolved base)."""
        base = next((v.value for v in self._plan.variables if v.name == self._plan.base_variable), "")
        return base or "https://api.example.com"

    # -- responses ----------------------------------------------------------

    def _responses(self, request: PlannedRequest, http: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Saved example responses: a Postman source's own, else those synthesized by the plan."""
        operation = self._operations[request.operation_key]
        messages = {m.key: m for m in operation.messages}
        out: List[Dict[str, Any]] = []
        for response in request.responses:
            out.append(self._response(response, messages.get(response.message_key), http))
        return out

    def _response(self, response: PlannedResponse, message: Any, http: Dict[str, Any]) -> Dict[str, Any]:
        raw = message.extras.get("postman_body_raw") if self._postman_source and message is not None else None
        body = raw if isinstance(raw, str) else (response.body.text(ref) if response.body is not None else None)
        content_type = response.content_type or ("application/json" if body else None)
        entry: Dict[str, Any] = {
            "name": response.name,
            "originalRequest": {key: value for key, value in http.items() if key != "auth"},
            "status": _status_text(response.status),
            "code": int(response.status),
            "header": [{"key": "Content-Type", "value": content_type}] if content_type else [],
        }
        if body is not None:
            entry["_postman_previewlanguage"] = "json" if content_type and "json" in content_type else "text"
            entry["body"] = body
        return entry
