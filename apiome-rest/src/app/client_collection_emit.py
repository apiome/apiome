"""Shared planning for the API-client collection emitters — FMT-10.4 (#5479).

Hoppscotch and Thunder Client collections are written from the same plan: one saved request per
HTTP operation, grouped into folders by the operation's first tag, against a ``baseUrl`` variable,
with auth as an auth block (or a header) whose credential is a *variable reference* that the
companion environment file declares with an empty value. The two emitters differ only in JSON shape
and variable syntax (``<<name>>`` vs ``{{name}}``), so everything else — which operations become
requests, which value each parameter carries, which auth applies, which body is sent and what the
export loses — is decided here once, and each emitter only renders a :class:`CollectionPlan`.

**Nothing credential-shaped is ever written.** A header, query parameter or form field whose name
says it carries a secret (:data:`app.client_collection.SECRET_NAME_RE`) is always written as a
reference to a secret variable, whatever default or sample the model holds for it; an auth block's
credential fields are always references (``accessToken``, ``username`` / ``password``, ``apiKey``,
``clientId`` / ``clientSecret``); and every literal value that does reach the output — parameter
samples and defaults, the base URL, example bodies — passes through the intake secret-scrub gate
first, with any userinfo stripped from the base URL. Every credential variable is listed in the
environment file with an empty value (marked ``secret`` where the client has the flag), which is
how the collection says what must be filled in before it will run.

**Round-trip.** The plan is the inverse of what :mod:`app.client_collection` reads: folder paths
become operation tags again, path parameters become ``{name}`` templates again, the auth block
resolves to the same canonical scheme, and the base URL variable becomes the same ``{baseUrl}``
server with the environment's value as its default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit

from .canonical_model import (
    CanonicalApi,
    Channel,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Type,
)
from .canonical_security import AUTH_SCHEME_HEADERS, operation_security_schemes
from .client_collection import FOLDER_SEPARATOR, SECRET_NAME_RE, scrub_value
from .emitter import CapabilityProfile, LossKind, LossTracker, Provenance, ProvenanceTracker
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .http_file_emitter import camel_case
from .snippet_render import pick_content_type, request_message, resolve_server_base, synthesize_body

__all__ = [
    "BASE_URL_VARIABLE",
    "HEADER_VARIABLES",
    "PAIR_SCHEMES",
    "SCHEME_VARIABLES",
    "ClientAuth",
    "ClientBody",
    "ClientCollectionFidelityRulePack",
    "ClientPair",
    "ClientVariable",
    "CollectionPlan",
    "PlannedRequest",
    "SecretRef",
    "client_collection_profile",
    "output_slug",
    "plan_collection",
]

#: The variable every request URL is written against, unless the model's server is already a
#: bare ``{variable}`` template (a client import), whose own name is kept.
BASE_URL_VARIABLE = "baseUrl"

#: Canonical security scheme → the credential variables its auth block references, in order.
#: ``openIdConnect`` has no block of its own in either client and is written as a bearer token.
SCHEME_VARIABLES: Dict[str, Tuple[str, ...]] = {
    "bearer": ("accessToken",),
    "openIdConnect": ("accessToken",),
    "oauth2": ("clientId", "clientSecret"),
    "basic": ("username", "password"),
    "digest": ("username", "password"),
    "apiKey": ("apiKey",),
    "authorization": ("authorization",),
    "cookie": ("cookie",),
}

#: Schemes that can always travel as a plain header or query parameter carrying a credential
#: reference, for a client with no auth block for them.
PAIR_SCHEMES = frozenset({"apiKey", "authorization", "cookie"})

#: Canonical scheme → the variable its credential *header* references, when the scheme travels as
#: a header the operation declares (``Authorization: Bearer <<accessToken>>``) rather than a block.
HEADER_VARIABLES: Dict[str, str] = {
    "bearer": "accessToken",
    "openIdConnect": "accessToken",
    "oauth2": "accessToken",
    "basic": "credentials",
    "digest": "credentials",
    "apiKey": "apiKey",
    "authorization": "authorization",
    "cookie": "cookie",
}

#: Operation extras holding the auth records a client import resolved (scheme, ``in``, ``name``,
#: OAuth grant type, token URL, scopes) — read back so an apiKey keeps its parameter name and an
#: OAuth flow its token endpoint.
_AUTH_RECORD_KEYS: Tuple[str, ...] = ("hoppscotch_auth", "thunder_client_auth")

#: Body media types written as fields rather than text.
FORM_MEDIA_TYPES: Tuple[str, ...] = ("application/x-www-form-urlencoded", "multipart/form-data")

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_PATH_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")
_BARE_TEMPLATE_RE = re.compile(r"^\{([A-Za-z0-9_.\-]+)\}$")
_API_KEY_NAME_RE = re.compile(r"api.?key", re.IGNORECASE)


# ===========================================================================
# Plan shapes
# ===========================================================================


@dataclass(frozen=True)
class ClientVariable:
    """One variable the environment file declares.

    Attributes:
        name: The variable name.
        value: Its value — always ``""`` for a credential.
        secret: Whether it holds a credential the reader must supply.
    """

    name: str
    value: str
    secret: bool


@dataclass(frozen=True)
class ClientPair:
    """A header, query parameter or form field of a saved request.

    Attributes:
        name: The header / parameter / field name.
        value: The literal value (scrubbed); ignored when ``variable`` is set.
        enabled: ``False`` for an optional parameter, which is saved but not sent.
        variable: When set, the value is written as a reference to this variable (a credential).
        prefix: Literal text written before a variable reference (``Bearer ``).
    """

    name: str
    value: str = ""
    enabled: bool = True
    variable: Optional[str] = None
    prefix: str = ""


@dataclass(frozen=True)
class ClientAuth:
    """The auth a saved request uses — scheme and public facts only, never a credential.

    Attributes:
        scheme: The canonical scheme (``bearer``, ``basic``, ``digest``, ``apiKey``, ``oauth2``).
        location: Where an API key travels (``header`` or ``query``).
        parameter: An API key's header or query parameter name.
        grant_type: An OAuth 2 grant type (lower-case, ``client_credentials``).
        token_url: An OAuth 2 token endpoint (scrubbed).
        scopes: OAuth 2 scopes.
    """

    scheme: str
    location: str = "header"
    parameter: Optional[str] = None
    grant_type: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Tuple[str, ...] = ()

    @property
    def variables(self) -> Tuple[str, ...]:
        """The credential variables this auth references."""
        return SCHEME_VARIABLES[self.scheme]


@dataclass(frozen=True)
class SecretRef:
    """Stands in for a credential-named value inside a JSON body until the client spells it.

    Attributes:
        variable: The credential variable the value is written as a reference to.
    """

    variable: str


@dataclass(frozen=True)
class ClientBody:
    """A saved request body.

    Attributes:
        content_type: The media type it is sent as.
        document: The JSON example, every credential-named member a :class:`SecretRef` — ``None``
            for a form body.
        fields: The form fields — empty for a JSON body.
    """

    content_type: str
    document: Any = None
    fields: Tuple[ClientPair, ...] = ()

    @property
    def is_form(self) -> bool:
        """Whether the body is written as form fields."""
        return self.document is None

    def text(self, ref: Callable[[str], str]) -> str:
        """The JSON body text, each :class:`SecretRef` spelled with the client's ``ref`` syntax.

        Args:
            ref: Spells a variable reference (``<<name>>`` / ``{{name}}``).

        Returns:
            Indented JSON whose every literal string has passed through the secret-scrub gate. The
            gate runs per value, not over the text: over the text its ``password: …`` assignment
            pattern would redact the very reference that stands in for the credential.
        """

        def spell(value: Any) -> Any:
            if isinstance(value, SecretRef):
                return ref(value.variable)
            if isinstance(value, dict):
                return {key: spell(item) for key, item in value.items()}
            if isinstance(value, list):
                return [spell(item) for item in value]
            if isinstance(value, str):
                return scrub_value(value)
            return value

        return json.dumps(spell(self.document), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class PlannedRequest:
    """One saved request, fully resolved before any client-specific JSON is written.

    Attributes:
        operation_key: The canonical operation the request calls.
        name: The request's display name.
        method: The upper-case HTTP method.
        folder: The folder path (empty for a request at the collection root).
        path: The path as ``(kind, text)`` parts — ``literal`` text or a ``param`` name.
        path_values: ``(parameter, example value)`` for every path parameter.
        query: The query parameters (optional ones disabled).
        headers: The headers (optional ones disabled; the auth header is not repeated here).
        body: The example body, if any.
        auth: The request's auth block, or ``None`` for no auth.
        origin: The ``scheme://host`` the request is written against literally, when the source
            saved it with an absolute URL; ``None`` for a request written against the base variable.
    """

    operation_key: str
    name: str
    method: str
    folder: Tuple[str, ...]
    path: Tuple[Tuple[str, str], ...]
    path_values: Tuple[Tuple[str, str], ...]
    query: Tuple[ClientPair, ...]
    headers: Tuple[ClientPair, ...]
    body: Optional[ClientBody]
    auth: Optional[ClientAuth]
    origin: Optional[str] = None


@dataclass
class CollectionPlan:
    """Everything a client-collection emitter renders.

    Attributes:
        title: The collection name.
        base_variable: The variable every request URL starts with.
        requests: The saved requests, in model order.
        variables: The environment's variables — the base URL first (when a request uses it), then
            every credential.
        shared_auth: The auth every request uses, when they all use the same one — written once on
            the collection and inherited, as a client user would set it up.
        losses: What the export cannot carry.
        tracker: Where each emitted request came from.
    """

    title: str
    base_variable: str
    requests: List[PlannedRequest]
    variables: List[ClientVariable]
    shared_auth: Optional[ClientAuth]
    losses: LossTracker
    tracker: ProvenanceTracker

    def folders(self) -> List[Tuple[str, ...]]:
        """Every folder level that holds a request, parents before children, in first-seen order."""
        seen: Dict[Tuple[str, ...], None] = {}
        for request in self.requests:
            for depth in range(1, len(request.folder) + 1):
                seen.setdefault(request.folder[:depth], None)
        return list(seen)


# ===========================================================================
# Capability + fidelity
# ===========================================================================


def client_collection_profile() -> CapabilityProfile:
    """The capability profile both client collections share.

    A client collection is a *call* surface: saved requests with a method, path, query, headers,
    an example body and auth, and no vocabulary for the types behind those bodies — no union, no
    nullable member, no validation facet, no field identity, no event channel.
    """
    return CapabilityProfile(
        operations=True,
        events=False,
        unions=False,
        nullability=False,
        constraints=False,
        field_identity=False,
    )


class ClientCollectionFidelityRulePack(CapabilityRulePack):
    """Fidelity rules shared by the client-collection targets.

    A subclass names its ``target_label`` and the ``format_key`` its own importer stamps on a model,
    which is what decides whether the artifact root survives: a collection carries a name and one
    base-URL variable, so a model that came from the same client keeps its root exactly, and any
    other model loses its format, description, version and every server beyond the first.
    """

    target_label = "API client collection"
    format_key = ""

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """Declare the root facts a collection has nowhere to put (none for a native model)."""
        if api.format == self.format_key:
            return []
        return [
            FidelityVerdict.approx(
                message=(
                    f"{self.target_label} keeps the API's name and one base URL, written as a "
                    "`baseUrl` variable; the source format, description, version and any further "
                    "servers are not carried"
                ),
                target_mapping="artifact root → collection name + baseUrl variable",
            )
        ]

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """An event channel has no saved request; it is dropped."""
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; channel {channel.key!r} is dropped",
            target_mapping="channel → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """Only operations with an HTTP binding become saved requests, and each is re-inferred."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=(
                    f"{self.target_label} has no event vocabulary; "
                    f"{operation.kind.value} operation {operation.key!r} is dropped"
                ),
                target_mapping="event operation → dropped",
            )
        if not operation.http_method or not operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} requires an HTTP binding; operation {operation.key!r} is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        return FidelityVerdict.approx(
            message=(
                f"{self.target_label} saves {operation.key!r} as one example request; a re-import "
                "infers it again from that request, so parameter types and descriptions, declared "
                "responses, extra tags and the per-call evidence of an inferred source are not carried"
            ),
            target_mapping="operation → saved request",
        )

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A named type is never declared; only the shape of an example body survives.

        A ``DROP`` rather than an ``APPROX``: the declaration itself is gone, and a re-import infers
        body types from the example bodies under names of its own, so a source type is as likely
        to vanish as to come back changed.
        """
        return FidelityVerdict.drop(
            message=(
                f"{self.target_label} has no schema vocabulary; type {type_.key!r} is not declared, "
                "and a re-import infers body types from the example bodies under its own names"
            ),
            target_mapping="named type → example body shape",
        )


# ===========================================================================
# Planning
# ===========================================================================


def output_slug(api: CanonicalApi) -> str:
    """A filesystem-safe stem for the emitted files, from the model's name."""
    base = api.identity.name or api.title or "collection"
    return re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "collection"


def plan_collection(api: CanonicalApi, *, target_label: str, auth_blocks: frozenset) -> CollectionPlan:
    """Plan one client collection for ``api``.

    Args:
        api: The canonical model to export.
        target_label: The client's name, for messages (``Hoppscotch``).
        auth_blocks: The canonical schemes the client writes as an auth block. A scheme outside it
            but in :data:`PAIR_SCHEMES` is written as a credential header (or query parameter); any
            other is recorded as a loss.

    Returns:
        The :class:`CollectionPlan`.

    Raises:
        ValueError: When ``api`` has no HTTP operation, so there is no request to save.
    """
    return _Planner(api, target_label=target_label, auth_blocks=auth_blocks).plan()


def _strip_userinfo(url: str) -> str:
    """Drop any ``user:password@`` from a URL — userinfo is a credential, never written."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=parts.netloc.rsplit("@", 1)[-1]))


def _example_value(parameter: Parameter) -> str:
    """A parameter's saved value: its default, else the first observed sample, else empty."""
    if parameter.default is not None and str(parameter.default) != "":
        return str(parameter.default)
    samples = parameter.extras.get("samples")
    if isinstance(samples, list):
        for sample in samples:
            if isinstance(sample, (str, int, float)) and not isinstance(sample, bool) and str(sample) != "":
                return str(sample)
    return ""


def _path_parts(path: str) -> Tuple[Tuple[str, str], ...]:
    """Split an ``/orders/{id}`` template into ``literal`` / ``param`` parts."""
    parts: List[Tuple[str, str]] = []
    position = 0
    for match in _PATH_TEMPLATE_RE.finditer(path):
        if match.start() > position:
            parts.append(("literal", path[position : match.start()]))
        parts.append(("param", match.group(1)))
        position = match.end()
    if position < len(path):
        parts.append(("literal", path[position:]))
    return tuple(parts)


def _with_content_type(headers: List[ClientPair], body: Optional[ClientBody]) -> List[ClientPair]:
    """Make a declared ``Content-Type`` header agree with the body the request actually sends."""
    if body is None:
        return list(headers)
    return [
        ClientPair(name=pair.name, value=body.content_type, enabled=pair.enabled)
        if pair.name.lower() == "content-type" and pair.variable is None
        else pair
        for pair in headers
    ]


def _observed_origin(operation: Operation) -> Optional[str]:
    """The one ``scheme://host`` an inferred operation's saved requests were all written against.

    A client or capture import records the URLs each operation was inferred from; when every one is
    absolute and they share an origin, the request is saved against that origin literally — which
    is what makes the importer recover the same server rather than a ``{baseUrl}`` template.
    """
    evidence = operation.extras.get("inference_evidence")
    urls = evidence.get("sample_urls") if isinstance(evidence, dict) else None
    if not isinstance(urls, list) or not urls:
        return None
    origins = set()
    for url in urls:
        parts = urlsplit(url) if isinstance(url, str) else None
        if parts is None or not parts.scheme or not parts.netloc:
            return None
        origins.add(f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}")
    return origins.pop() if len(origins) == 1 else None


def _auth_record(operation: Operation, scheme: str) -> Dict[str, object]:
    """The client import's auth record for ``scheme`` on ``operation``, or ``{}``."""
    for key in _AUTH_RECORD_KEYS:
        records = operation.extras.get(key)
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict) and record.get("scheme") == scheme:
                return record
    return {}


@dataclass
class _Planner:
    """Walks one model into a :class:`CollectionPlan`, collecting variables and losses."""

    api: CanonicalApi
    target_label: str
    auth_blocks: frozenset
    losses: LossTracker = field(default_factory=LossTracker)
    tracker: ProvenanceTracker = field(default_factory=ProvenanceTracker)
    _secrets: List[str] = field(default_factory=list)

    def plan(self) -> CollectionPlan:
        """Build the plan (see :func:`plan_collection`)."""
        base_server, base_variable, base_value = self._base_url()
        requests: List[PlannedRequest] = []
        for service in self.api.services:
            for operation in service.operations:
                for planned in self._plan_operation(operation):
                    self.tracker.record(f"/requests/{len(requests)}", Provenance.SOURCE, operation.key)
                    requests.append(planned)
        if not requests:
            raise ValueError(
                f"{self.target_label} export requires at least one HTTP operation: a collection is a "
                "set of saved requests, and a model with no HTTP binding has no request to save."
            )
        self._record_model_losses()
        uses_base = any(request.origin is None for request in requests)
        self._record_server_losses(base_server if uses_base else None, {r.origin for r in requests if r.origin})
        variables = [ClientVariable(name=base_variable, value=base_value, secret=False)] if uses_base else []
        variables.extend(
            ClientVariable(name=name, value="", secret=True) for name in self._secrets if name != base_variable
        )
        first = requests[0].auth
        shared = first if first is not None and all(request.auth == first for request in requests) else None
        return CollectionPlan(
            title=self.api.title or self.api.identity.name or "Exported API",
            base_variable=base_variable,
            requests=requests,
            variables=variables,
            shared_auth=shared,
            losses=self.losses,
            tracker=self.tracker,
        )

    # -- model level ------------------------------------------------------

    def _base_url(self) -> Tuple[Optional[str], str, str]:
        """Return ``(server url, variable, value)`` for the base URL requests are written against.

        A model with a bare ``{variable}`` server (a client import) keeps that variable and its
        default; any other model gets a ``baseUrl`` variable holding the URL the snippet
        synthesizer resolves from its first server, so the variable marks exactly where the server
        ends. The server URL is returned so the server losses can tell which servers were carried.
        """
        template = next((server for server in self.api.servers if _BARE_TEMPLATE_RE.match(server.url or "")), None)
        if template is not None:
            name = _BARE_TEMPLATE_RE.match(template.url).group(1)
            default = next((variable.default for variable in template.variables if variable.name == name), None)
            return template.url, name, scrub_value("" if default is None else str(default))
        if not self.api.servers:
            self.losses.record(
                LossKind.INFERRED,
                "synthesized-base-url",
                "The model declares no server, so the `baseUrl` variable holds a stand-in host.",
                pointer="servers",
            )
        base = resolve_server_base(self.api)[0]
        server_url = self.api.servers[0].url if self.api.servers else None
        return server_url, BASE_URL_VARIABLE, scrub_value(_strip_userinfo(base))

    def _record_server_losses(self, base_server: Optional[str], origins: set) -> None:
        """Record every server the collection does not carry.

        A collection carries the server its base variable stands for and the origin of every request
        saved with an absolute URL; any other server is lost.
        """
        carried = {url.rstrip("/") for url in origins | ({base_server} if base_server else set())}
        dropped = sorted(server.url for server in self.api.servers if server.url.rstrip("/") not in carried)
        if dropped:
            self.losses.record(
                LossKind.NA,
                "additional-servers",
                f"A {self.target_label} collection is written against one base URL; the server(s) "
                f"{', '.join(dropped)} are not carried.",
                pointer="servers",
            )

    def _record_model_losses(self) -> None:
        """Record the whole-model constructs a collection cannot carry."""
        if self.api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                f"A {self.target_label} collection has no channel vocabulary; event channels are dropped.",
                pointer="channels",
            )
        if self.api.types:
            self.losses.record(
                LossKind.NA,
                "types-not-declared",
                f"{len(self.api.types)} named type(s) have no declaration in a {self.target_label} "
                "collection; they survive only as the shape of an example body.",
                pointer="types",
            )
        if self.api.description:
            self.losses.record(
                LossKind.NA,
                "api-description",
                f"A {self.target_label} collection export has no description field; the API "
                "description is not carried.",
                pointer="",
            )

    # -- one operation ----------------------------------------------------

    def _secret(self, name: str) -> str:
        """Register (once) and return the credential variable for a parameter or scheme name."""
        variable = name if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) and name[:1].islower() else camel_case(name)
        if variable not in self._secrets:
            self._secrets.append(variable)
        return variable

    def _plan_operation(self, operation: Operation) -> List[PlannedRequest]:
        """Plan one operation's saved request(s) — one per body media type — or record why it has none."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            self.losses.record(
                LossKind.NA,
                "event-operation",
                f"{operation.kind.value} operation {operation.key!r} has no saved request: a "
                f"{self.target_label} collection describes calls, not event flows.",
                pointer=operation.key,
            )
            return []
        if not operation.http_method or not operation.http_path:
            self.losses.record(
                LossKind.NA,
                "unroutable-operation",
                f"Operation {operation.key!r} has no HTTP method/path, so no request can be saved for it.",
                pointer=operation.key,
            )
            return []
        auth, consumed, extra_headers, extra_query = self._auth(operation)
        query = self._pairs(operation, ParameterLocation.QUERY, skip=consumed)
        headers = self._pairs(operation, ParameterLocation.HEADER, skip=consumed)
        self._record_operation_losses(operation)
        path = operation.http_path if operation.http_path.startswith("/") else "/" + operation.http_path
        name = self._name(operation)
        bodies = self._bodies(operation)
        return [
            PlannedRequest(
                operation_key=operation.key,
                name=name if index == 0 else f"{name} ({body.content_type})",
                method=operation.http_method.upper(),
                folder=self._folder(operation) if index == 0 else self._folder(operation, record=False),
                path=_path_parts(path),
                path_values=tuple(
                    (parameter.name, scrub_value(_example_value(parameter)))
                    for parameter in operation.parameters
                    if parameter.location is ParameterLocation.PATH
                ),
                query=tuple(query + extra_query),
                headers=tuple(_with_content_type(headers, body) + extra_headers),
                body=body,
                auth=auth,
                origin=_observed_origin(operation),
            )
            for index, body in enumerate(bodies)
        ]

    @staticmethod
    def _name(operation: Operation) -> str:
        """The request name: the client's own name for it when imported from one, else the operation's."""
        label = operation.extras.get("source_label")
        if isinstance(label, str) and label.strip():
            return label.strip()
        return operation.name or operation.key

    def _folder(self, operation: Operation, *, record: bool = True) -> Tuple[str, ...]:
        """The folder path: the operation's first tag, split on the folder separator.

        Args:
            operation: The operation.
            record: Whether to record the extra-tags loss (once per operation, not per request).
        """
        if not operation.tags:
            return ()
        if record and len(operation.tags) > 1:
            self.losses.record(
                LossKind.NA,
                "additional-tags",
                f"{operation.key!r} is tagged {', '.join(operation.tags)}; a saved request sits in one "
                f"folder, so it is filed under {operation.tags[0]!r} only.",
                pointer=operation.key,
            )
        return tuple(part.strip() for part in operation.tags[0].split(FOLDER_SEPARATOR) if part.strip())

    def _pairs(self, operation: Operation, location: ParameterLocation, *, skip: set) -> List[ClientPair]:
        """The operation's query or header parameters as saved pairs; a secret is a reference.

        Args:
            operation: The operation.
            location: ``QUERY`` or ``HEADER``.
            skip: Lower-cased names the auth already carries — left out *before* a credential
                variable is registered, so the environment declares no variable nothing references.
        """
        pairs: List[ClientPair] = []
        for parameter in operation.parameters:
            if parameter.location is not location or parameter.name.lower() in skip:
                continue
            if SECRET_NAME_RE.search(parameter.name):
                pairs.append(
                    ClientPair(name=parameter.name, enabled=parameter.required, variable=self._secret(parameter.name))
                )
            else:
                pairs.append(
                    ClientPair(
                        name=parameter.name,
                        value=scrub_value(_example_value(parameter)),
                        enabled=parameter.required,
                    )
                )
        return pairs

    def _record_operation_losses(self, operation: Operation) -> None:
        """Record what one saved request cannot carry."""
        optional = sorted(
            parameter.name
            for parameter in operation.parameters
            if not parameter.required and parameter.location in (ParameterLocation.QUERY, ParameterLocation.HEADER)
        )
        if optional:
            self.losses.record(
                LossKind.NA,
                "optional-parameters-disabled",
                f"{operation.key!r} accepts optional parameter(s) {', '.join(optional)}; they are saved "
                "disabled, so a re-import does not recover them.",
                pointer=operation.key,
            )
        cookies = sorted(p.name for p in operation.parameters if p.location is ParameterLocation.COOKIE)
        if cookies:
            self.losses.record(
                LossKind.NA,
                "cookie-parameters",
                f"{operation.key!r} declares cookie parameter(s) {', '.join(cookies)}; a "
                f"{self.target_label} request has no cookie list, so they are not carried.",
                pointer=operation.key,
            )
        if any(message.role is not MessageRole.REQUEST for message in operation.messages):
            self.losses.record(
                LossKind.NA,
                "responses-not-carried",
                f"A saved request records the call, not the reply; the declared response(s) of "
                f"{operation.key!r} are not carried.",
                pointer=operation.key,
            )

    def _auth(self, operation: Operation) -> Tuple[Optional[ClientAuth], set, List[ClientPair], List[ClientPair]]:
        """Resolve the operation's auth.

        An operation-scoped scheme is written as the client's auth block (or, where the client has
        none for it, as a credential header / query parameter). A model-scoped scheme is only an
        observation about the API — the rule :func:`app.canonical_security.operation_security_schemes`
        documents — so it never adds auth: it only rewrites a credential header the operation already
        declares into the form the scheme travels in (``Authorization: Bearer <<accessToken>>``).
        One operation-scoped scheme is written; further ones are recorded as a loss.

        Returns:
            ``(auth, consumed, headers, query)`` — the auth block (``None`` when there is none or it
            is written as a pair), the lower-cased parameter names the auth replaces, and the
            credential header / query pairs written in their place.
        """
        schemes, scope = operation_security_schemes(self.api, operation)
        if scope != "operation":
            return self._observed_auth_headers(operation, schemes)
        usable: List[str] = []
        for scheme in schemes:
            if scheme in SCHEME_VARIABLES:
                usable.append(scheme)
                continue
            self.losses.record(
                LossKind.NA,
                "unrepresentable-auth-scheme",
                f"Security scheme {scheme!r} on {operation.key!r} has no {self.target_label} auth "
                "type or header form, so it is not carried.",
                pointer=operation.key,
            )
        if not usable:
            return None, set(), [], []
        scheme = usable[0]
        if len(usable) > 1:
            self.losses.record(
                LossKind.NA,
                "additional-auth-schemes",
                f"{operation.key!r} accepts {', '.join(usable)}; a saved request has one auth, so "
                f"{scheme!r} is written.",
                pointer=operation.key,
            )
        auth = self._auth_block(operation, scheme)
        consumed = {AUTH_SCHEME_HEADERS[scheme][0].lower()}
        if auth.parameter:
            consumed.add(auth.parameter.lower())
        for variable in auth.variables:
            self._secret(variable)
        if auth.scheme in self.auth_blocks:
            return auth, consumed, [], []
        name = auth.parameter or AUTH_SCHEME_HEADERS[auth.scheme][0]
        self.losses.record(
            LossKind.INFERRED,
            "auth-as-parameter",
            f"{self.target_label} has no {auth.scheme!r} auth type, so the credential for "
            f"{operation.key!r} is saved as the {name} {auth.location} holding a reference; a re-import "
            "reads it as a parameter rather than a declared scheme.",
            pointer=operation.key,
        )
        template = AUTH_SCHEME_HEADERS[auth.scheme][1]
        pair = ClientPair(
            name=name,
            variable=auth.variables[0],
            prefix=template.rsplit(" ", 1)[0] + " " if " " in template else "",
        )
        if auth.location == "query":
            return None, consumed, [], [pair]
        return None, consumed, [pair], []

    def _observed_auth_headers(
        self, operation: Operation, schemes: Sequence[str]
    ) -> Tuple[None, set, List[ClientPair], List[ClientPair]]:
        """Rewrite each declared credential header a model-scoped scheme travels in.

        Returns:
            ``(None, consumed, headers, [])`` — see :meth:`_auth`.
        """
        declared = {
            parameter.name.lower(): parameter
            for parameter in operation.parameters
            if parameter.location is ParameterLocation.HEADER
        }
        consumed: set = set()
        headers: List[ClientPair] = []
        for scheme in schemes:
            if scheme not in AUTH_SCHEME_HEADERS or scheme not in HEADER_VARIABLES:
                continue
            header, template = AUTH_SCHEME_HEADERS[scheme]
            parameter = declared.get(header.lower())
            if parameter is None or header.lower() in consumed:
                continue
            consumed.add(header.lower())
            prefix = template.rsplit(" ", 1)[0] + " " if " " in template else ""
            headers.append(
                ClientPair(
                    name=parameter.name,
                    enabled=parameter.required,
                    variable=self._secret(HEADER_VARIABLES[scheme]),
                    prefix=prefix,
                )
            )
        return None, consumed, headers, []

    def _auth_block(self, operation: Operation, scheme: str) -> ClientAuth:
        """Build the auth for one scheme, reading what a client import recorded about it."""
        record = _auth_record(operation, scheme)
        if scheme == "openIdConnect":
            self.losses.record(
                LossKind.INFERRED,
                "openid-connect-as-bearer",
                f"{operation.key!r} uses OpenID Connect, which a {self.target_label} collection writes "
                "as a bearer token; a re-import reads it back as `bearer`.",
                pointer=operation.key,
            )
            return ClientAuth(scheme="bearer")
        if scheme == "apiKey":
            location = "query" if record.get("in") == "query" else "header"
            name = record.get("name") if isinstance(record.get("name"), str) else None
            if not name:
                for parameter in operation.parameters:
                    if _API_KEY_NAME_RE.search(parameter.name) and parameter.location in (
                        ParameterLocation.HEADER,
                        ParameterLocation.QUERY,
                    ):
                        name = parameter.name
                        location = "query" if parameter.location is ParameterLocation.QUERY else "header"
                        break
            return ClientAuth(scheme=scheme, location=location, parameter=name or AUTH_SCHEME_HEADERS[scheme][0])
        if scheme == "oauth2":
            token_url = record.get("token_url")
            scopes = record.get("scopes")
            grant = record.get("grant_type")
            return ClientAuth(
                scheme=scheme,
                grant_type=grant if isinstance(grant, str) and grant else "client_credentials",
                token_url=scrub_value(_strip_userinfo(token_url)) if isinstance(token_url, str) else None,
                scopes=tuple(str(scope) for scope in scopes) if isinstance(scopes, list) else (),
            )
        return ClientAuth(scheme=scheme)

    def _bodies(self, operation: Operation) -> List[Optional[ClientBody]]:
        """One example body per media type the request accepts, in declared order.

        A saved request sends one body, so an operation that accepts JSON *and* a form is saved as
        one request per media type — which the importer merges back into one operation accepting
        both. A media type with no synthesizable example is recorded as a loss; when none has one,
        the single request is saved without a body (``[None]``).
        """
        message = request_message(operation)
        if message is None or (message.payload is None and message.payload_schema is None):
            return [None]
        content_types = list(dict.fromkeys(message.content_types)) or [pick_content_type(message)]
        instance = synthesize_body(self.api, message)
        bodies: List[Optional[ClientBody]] = []
        for content_type in content_types:
            base_type = content_type.split(";", 1)[0].strip().lower()
            if instance is not None and "json" in base_type:
                bodies.append(ClientBody(content_type=content_type, document=self._redact(instance)))
            elif isinstance(instance, dict) and base_type in FORM_MEDIA_TYPES:
                bodies.append(ClientBody(content_type=content_type, fields=tuple(self._form_fields(instance))))
            else:
                self.losses.record(
                    LossKind.NA,
                    "example-body-omitted",
                    f"No example {content_type} body could be synthesized for {operation.key!r}, so no "
                    "request is saved with that media type.",
                    pointer=operation.key,
                )
        return bodies or [None]

    def _redact(self, value: Any) -> Any:
        """Replace every credential-named member of a JSON example with a :class:`SecretRef`."""
        if isinstance(value, dict):
            return {
                key: SecretRef(self._secret(key))
                if SECRET_NAME_RE.search(str(key)) and not isinstance(item, (dict, list))
                else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value

    def _form_fields(self, instance: Dict[str, object]) -> Sequence[ClientPair]:
        """Turn a synthesized object into form fields; a secret-named field is a reference."""
        fields: List[ClientPair] = []
        for name in instance:
            value = instance[name]
            if SECRET_NAME_RE.search(name):
                fields.append(ClientPair(name=name, variable=self._secret(name)))
                continue
            text = value if isinstance(value, str) else json.dumps(value)
            fields.append(ClientPair(name=name, value=scrub_value(text)))
        return fields
