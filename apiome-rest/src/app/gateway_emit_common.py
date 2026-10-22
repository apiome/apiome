"""What every gateway emit mode shares — FMT-7.7 (#5461).

FMT-2.2 and FMT-2.3 gave the family two renderers (Kong, Gateway API) over one projection,
:func:`app.gateway_config_emitter.plan_gateway_config`. FMT-7.7 adds six more (Envoy xDS,
Istio, Traefik, AWS API Gateway, Azure APIM, Apigee). They differ only in syntax, so the
parts that are not syntax live here once:

* :class:`RoutingSurfaceRulePack` — the fidelity pack of a target that is a *routing
  surface*: it carries operations and nothing about payloads. Kong's pack is now a subclass,
  and so is every routing-only FMT-7.7 target, so a fidelity badge reads the same for all.
* :data:`ROUTING_SURFACE_PROFILE` — the capability profile that goes with it.
* :class:`GatewayEmitOptions` — the options every renderer accepts (naming, YAML / JSON,
  pretty printing), validated the same way.
* :class:`GatewayEmitPlan` — the projection plus the bookkeeping every renderer repeats:
  refuse a model with no route, narrow service-scoped auth, and declare the losses a
  renderer cannot help (the artifact title, plugin configuration, auth with no product
  equivalent).
* :func:`dump_documents` / :func:`single_file_result` — serialization and the
  :class:`~app.emitter.EmitResult` envelope.
* :func:`regex_source` — a pattern's regex body without Kong's ``~`` marker.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Type
from urllib.parse import urlsplit

import yaml
from pydantic import Field, field_validator

from .canonical_model import CanonicalApi, CanonicalField, Channel, Operation, OperationKind
from .canonical_model import Type as CanonicalType
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitResult,
    EmittedFile,
    LossKind,
    LossTracker,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .gateway_config_emitter import (
    BACKEND_EXTRA,
    SERVICE_NAMING_STRATEGIES,
    gateway_sourced,
    narrow_service_scoped_auth,
    plan_gateway_config,
)
from .gateway_config_model import GatewayConfigDocument, GatewayPathPattern, GatewayRoute

__all__ = [
    "OUTPUT_FORMATS",
    "ROUTING_SURFACE_PROFILE",
    "GatewayEmitOptions",
    "GatewayEmitPlan",
    "RoutingSurfaceRulePack",
    "coerce_gateway_options",
    "dns_label",
    "dump_documents",
    "pattern_value",
    "files_result",
    "openapi_security_from_records",
    "later_duplicates",
    "operation_upstream",
    "record_method_path_collisions",
    "regex_source",
    "single_file_result",
    "unique",
]

#: Serialization formats every gateway renderer offers, with the bundle media type.
OUTPUT_FORMATS: Dict[str, str] = {"yaml": "application/yaml", "json": "application/json"}

#: Operation kinds that describe an event flow rather than a request/response call.
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: A routing surface carries operations faithfully and nothing about their payloads: there
#: is no type system for a union, no member to mark nullable, no facet to enforce a
#: constraint and no field identity. The schema loss is stated before an emit runs.
ROUTING_SURFACE_PROFILE = CapabilityProfile(
    operations=True,
    events=False,
    unions=False,
    nullability=False,
    constraints=False,
    field_identity=False,
)


# ===========================================================================
# Fidelity
# ===========================================================================


class RoutingSurfaceRulePack(CapabilityRulePack):
    """Fidelity rules for a gateway target that is a routing surface (FMT-2.7 / FMT-7.7).

    States, construct by construct and *before* an emit runs, the losses the renderer
    records while writing the file, so an Export Studio card and a finished artifact tell
    the reader the same story. A routing surface says where a request goes, never what it
    carries, so the things it cannot hold are named directly rather than inferred from the
    capability axes — the profile-derived default would call a record ``OK`` on the strength
    of ``operations=True``, which over-claims a fidelity a file with no schema section cannot
    deliver.

    Attributes:
        target_label: How the verdicts name the target.
        has_title_field: The target has somewhere to put the artifact title; when ``False``
            the title is an approximated loss (a re-import names the configuration after
            its file).
    """

    target_label = "Gateway configuration"
    has_title_field = False
    #: The target's flavor. When set, an operation from any other format is approximated: its
    #: route is rebuilt in this product's vocabulary, so flavor-specific route attributes are
    #: not carried and provenance is re-derived. Kong's pack leaves it unset (its FMT-2.7
    #: verdicts are unchanged).
    target_flavor: Optional[str] = None
    #: The target can declare a route's policies (it needs only their names).
    carries_policies = True
    #: The target can declare a route's authentication.
    carries_auth = True
    #: The target can match on header and query values.
    carries_value_matches = True
    #: The target binds routes to hosts.
    carries_hosts = True
    #: The target holds one route per method and path, so later duplicates are not emitted.
    merges_duplicate_routes = False

    def evaluate(self, api: CanonicalApi):  # type: ignore[override]
        """Remember the source format, then walk the model (see :meth:`FidelityRulePack.evaluate`)."""
        self._source_format = api.format
        self._duplicates = later_duplicates(api) if self.merges_duplicate_routes else set()
        return super().evaluate(api)

    def route_rewrites(self, operation: Operation) -> List[str]:
        """Why an operation will not come back from this target unchanged (empty: it will).

        Args:
            operation: An HTTP-bound operation of the source model.

        Returns:
            One reason per kind of rewrite, in a fixed order.
        """
        reasons: List[str] = []
        source = getattr(self, "_source_format", None)
        if self.target_flavor and source != self.target_flavor:
            reasons.append(
                "its route is rebuilt in this product's vocabulary, so attributes of the source format "
                "are not carried and provenance is re-derived"
            )
        if not self.carries_policies and operation.extras.get("plugins"):
            reasons.append("its policies are recorded by name only and are not emitted")
        if not self.carries_auth and operation.extras.get("security"):
            reasons.append("its authentication has no declaration in this target")
        if not self.carries_value_matches and any(
            parameter.location.value in ("header", "query") and "match_value" in parameter.extras
            for parameter in operation.parameters
        ):
            reasons.append("its header / query match conditions are not emitted")
        if not self.carries_hosts and operation.extras.get("hosts"):
            reasons.append("its host binding is not part of the artifact")
        return reasons

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """Declare the artifact title the target has nowhere to put.

        Reported only when the source actually carries a title or an identity name; a model
        with neither loses nothing here.
        """
        verdicts: List[FidelityVerdict] = []
        if self.target_flavor and api.format != self.target_flavor:
            verdicts.append(
                FidelityVerdict.approx(
                    message=(
                        f"the artifact is rebuilt as a {self.target_label}; its format, title and gateway "
                        "report come back as this product's, not the source's"
                    ),
                    target_mapping="artifact → rebuilt artifact",
                )
            )
        if self.has_title_field or not (api.title or api.identity.name):
            return verdicts
        return verdicts + [
            FidelityVerdict.approx(
                message=(
                    f"{self.target_label} has no field for the artifact title; a "
                    "re-import names the configuration after the file it was read from"
                ),
                target_mapping="artifact title → file name",
            )
        ]

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """An event channel has no route to become; it is dropped."""
        return FidelityVerdict.drop(
            message=(
                f"{self.target_label} routes HTTP requests and has no event/channel "
                f"vocabulary; channel {channel.key!r} is dropped"
            ),
            target_mapping="channel → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """Only an HTTP-bound operation becomes a route."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=(
                    f"{self.target_label} has no event vocabulary; "
                    f"{operation.kind.value} operation {operation.key!r} is dropped"
                ),
                target_mapping="event operation → dropped",
            )
        if not operation.http_method and not operation.http_path:
            return FidelityVerdict.drop(
                message=(
                    f"{self.target_label} matches on method, path and host; operation "
                    f"{operation.key!r} declares no HTTP binding to route and is dropped"
                ),
                target_mapping="non-HTTP operation → dropped",
            )
        if operation.key in getattr(self, "_duplicates", set()):
            return FidelityVerdict.drop(
                message=(
                    f"{self.target_label} holds one route per method and path; operation {operation.key!r} "
                    "repeats an earlier one (it differs only by host or a header / query condition) and is dropped"
                ),
                target_mapping="duplicate route → dropped",
            )
        reasons = self.route_rewrites(operation)
        if reasons:
            return FidelityVerdict.approx(
                message=f"operation carried to {self.target_label}, but " + "; ".join(reasons),
                target_mapping="route → rewritten route",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")

    def type_verdict(self, type_: CanonicalType) -> FidelityVerdict:
        """Every named type is dropped: a routing surface has no schema section."""
        return FidelityVerdict.drop(
            message=(
                f"{self.target_label} declares where a request goes, never what it "
                f"carries; type {type_.key!r} has no declaration to become and is dropped"
            ),
            target_mapping="named type → dropped",
        )

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """No per-field verdicts — the owning type is already dropped whole.

        The default pack would report a field's nullability, constraints and field number
        as separate losses. On a target with no type system that restates one fact several
        times and inflates the loss counts a fidelity badge is computed from.
        """
        return []


# ===========================================================================
# Options
# ===========================================================================


class GatewayEmitOptions(EmitOptions):
    """Options every FMT-7.7 routing renderer accepts.

    The defaults reproduce an import of the same product faithfully: names preserved,
    block-style YAML.
    """

    service_naming: str = Field(
        default="preserve",
        description="How to name gateway services: `preserve` (canonical service name, "
        "sanitized only where the product forbids a character), `slug` (lower-cased and "
        "hyphenated), or `host` (named after the upstream host).",
    )
    output_format: str = Field(default="yaml", description="Serialize as `yaml` or `json`.")
    pretty_print: bool = Field(
        default=True,
        description="Render block-style YAML / indented JSON. Disable for a compact document.",
    )

    @field_validator("service_naming")
    @classmethod
    def _known_service_naming(cls, value: str) -> str:
        """Reject an unknown service-naming strategy."""
        if value not in SERVICE_NAMING_STRATEGIES:
            raise ValueError(f"service_naming must be one of {', '.join(SERVICE_NAMING_STRATEGIES)}")
        return value

    @field_validator("output_format")
    @classmethod
    def _known_output_format(cls, value: str) -> str:
        """Reject an output format the renderers cannot serialize."""
        if value not in OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {', '.join(sorted(OUTPUT_FORMATS))}")
        return value


def coerce_gateway_options(
    opts: Optional[EmitOptions], model: Type[GatewayEmitOptions], *, label: str
) -> GatewayEmitOptions:
    """Validate caller-supplied options into the renderer's options model.

    Args:
        opts: What the caller passed (``None``, the generic options, or the model itself).
        model: The renderer's options class.
        label: The target's human name, for the error message.

    Returns:
        The validated options.

    Raises:
        EmitOptionsError: When an option value is unknown.
    """
    if isinstance(opts, model):
        return opts
    try:
        return model.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid {label} emit options: {exc}") from exc


# ===========================================================================
# The plan
# ===========================================================================


class GatewayEmitPlan:
    """The projected document plus the trackers one emit run fills in.

    Attributes:
        api: The canonical model being exported.
        document: The flavor-neutral document the renderer turns into its syntax.
        declared_routes: The model came from a gateway import, so route names are declared
            (``True``) rather than derived from operation keys.
        tracker: Provenance of every emitted value.
        losses: Every construct the target could not carry.
    """

    def __init__(
        self,
        api: CanonicalApi,
        *,
        flavor: str,
        label: str,
        service_naming: str = "preserve",
        narrow_auth: bool = True,
    ) -> None:
        """Project ``api`` for ``flavor``.

        Args:
            api: The model to export.
            flavor: The target's flavor key (selects the :class:`FlavorRules`).
            label: The target's human name, for messages.
            service_naming: One of :data:`SERVICE_NAMING_STRATEGIES`.
            narrow_auth: Move service-scoped auth that does not apply to every route of its
                service down to route scope (the targets with a service scope need it).

        Raises:
            ValueError: When the model has no HTTP operation, so no route to emit.
        """
        self.api = api
        self.label = label
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.declared_routes = gateway_sourced(api)
        document = plan_gateway_config(api, flavor=flavor, losses=self.losses, service_naming=service_naming)
        if not document.routes:
            raise ValueError(
                f"{label} export requires at least one HTTP operation: a gateway configuration "
                "is a routing surface, and a model with no operations has no route to declare."
            )
        if narrow_auth:
            document, narrowed = narrow_service_scoped_auth(document)
            for route_name, plugin in narrowed:
                self.losses.record(
                    LossKind.INFERRED,
                    "narrowed-auth-scope",
                    f"Auth plugin {plugin!r} is recorded as service-scoped but does not apply to "
                    f"every route of its service; emitted on route {route_name!r} instead so no "
                    "route gains authentication it did not have.",
                    route_name,
                )
        self.document: GatewayConfigDocument = document

    def declare_title_loss(self) -> None:
        """Record that the target has no field for the artifact title."""
        if self.api.title or self.api.identity.name:
            self.losses.record(
                LossKind.NA,
                "artifact-title",
                f"A {self.label} has no field for the artifact title ({self.document.title!r}); "
                "a re-import names the configuration after the file it was read from.",
                "",
            )

    def declare_plugin_losses(self, route: GatewayRoute) -> None:
        """Record that a route's non-auth plugins cannot be emitted.

        The canonical model records *which* policies a route had, by name, never their
        configuration — and every FMT-7.7 target needs the configuration to declare one.
        """
        for plugin in route.plugins:
            self.losses.record(
                LossKind.NA,
                "plugin-not-emitted",
                f"Policy {plugin.name!r} on route {route.name!r} is not emitted: the canonical "
                f"model records its name, not its configuration, and a {self.label} cannot "
                "declare it without one.",
                route.name,
            )

    def declare_global_plugin_losses(self) -> None:
        """Record that gateway-wide plugins cannot be emitted."""
        for plugin in self.document.global_plugins:
            self.losses.record(
                LossKind.NA,
                "plugin-not-emitted",
                f"Gateway-wide policy {plugin.name!r} is not emitted: its configuration is not "
                "in the canonical model.",
                "",
            )

    def declare_auth_losses(self, route: GatewayRoute, *, reason: str) -> None:
        """Record that a route's auth hints have no equivalent in the target.

        Args:
            route: The route whose auth is not emitted.
            reason: Why the target cannot carry it (one sentence fragment).
        """
        for hint in route.auth:
            self.losses.record(
                LossKind.NA,
                "auth-not-emitted",
                f"Authentication {hint.plugin!r} ({hint.scheme or 'no canonical scheme'}) on route "
                f"{route.name!r} is not emitted: {reason}.",
                route.name,
            )

    def declare_query_losses(self, route: GatewayRoute) -> None:
        """Record that a route's query-parameter matches have no equivalent in the target."""
        for match in route.matches:
            if match.query:
                self.losses.record(
                    LossKind.NA,
                    "query-match",
                    f"Route {route.name!r} matches on query parameters "
                    f"({', '.join(name for name, _ in match.query)}); a {self.label} route has no "
                    "query-matching field, so the condition is not emitted.",
                    route.name,
                )


# ===========================================================================
# Serialization
# ===========================================================================


def regex_source(pattern: GatewayPathPattern) -> str:
    """A regex pattern's body without Kong's leading ``~`` marker."""
    raw = pattern.raw.strip()
    return raw[1:] if raw.startswith("~") else raw


def pattern_value(pattern: GatewayPathPattern) -> str:
    """The value a product's path matcher takes: the regex body, else the literal path.

    A regex keeps its body (Kong's ``~`` dropped); an exact or prefix pattern keeps the path as
    declared when it is one, else its canonical template.
    """
    if pattern.kind == "regex":
        return regex_source(pattern)
    return pattern.raw if pattern.raw.startswith("/") else pattern.template


def dump_documents(documents: Sequence[Any], *, output_format: str, pretty: bool) -> str:
    """Serialize one or more documents as a YAML stream or JSON.

    Args:
        documents: The documents, in order.
        output_format: ``yaml`` (a ``---``-separated stream) or ``json`` (one document, or a
            JSON array when there are several).
        pretty: Block-style YAML / indented JSON.

    Returns:
        The text.
    """
    if output_format == "json":
        payload = documents[0] if len(documents) == 1 else list(documents)
        if pretty:
            return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return yaml.safe_dump_all(list(documents), sort_keys=False, default_flow_style=not pretty, allow_unicode=True)


def single_file_result(plan: GatewayEmitPlan, *, path: str, content: str, media_type: str) -> EmitResult:
    """The :class:`~app.emitter.EmitResult` of a one-file gateway emit."""
    return files_result(plan, [EmittedFile(path=path, content=content, media_type=media_type)], media_type)


def files_result(plan: Any, files: Iterable[EmittedFile], media_type: str) -> EmitResult:
    """The :class:`~app.emitter.EmitResult` of a gateway emit, with its trackers."""
    return EmitResult(
        files=list(files),
        media_type=media_type,
        provenance=plan.tracker.records(),
        losses=plan.losses.records(),
    )


def dns_label(value: str, *, fallback: str = "route") -> str:
    """A Kubernetes RFC 1123 label (lower-case alphanumerics and ``-``, at most 63 chars)."""
    out = "".join(ch if ch.isalnum() else "-" for ch in value.lower())
    out = "-".join(part for part in out.split("-") if part)[:63].strip("-")
    return out or fallback


def unique(values: Iterable[str]) -> List[str]:
    """``values`` with duplicates dropped, first occurrence kept."""
    seen: Dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


def operation_upstream(api: CanonicalApi, operation: Operation) -> Optional[str]:
    """The base URL an operation forwards to, when the model knows one.

    The backend a gateway import recorded on the operation's service (one URL, or host / port /
    path), else the model's first http(s) server — an OpenAPI source *is* the API a gateway
    would front. ``None`` when the model knows neither.

    Args:
        api: The model.
        operation: One of its operations.

    Returns:
        The base URL without a trailing slash, or ``None``.
    """
    recorded = operation.extras.get(BACKEND_EXTRA)
    if (
        isinstance(recorded, Mapping)
        and recorded.get("derivedFrom") in ("policy", "definition")
        and isinstance(recorded.get("uri"), str)
    ):
        # An APIM import recorded the backend the policy (or the API's service URL) names.
        return str(recorded["uri"]).rstrip("/")
    for service in api.services:
        if operation in service.operations:
            backend = service.extras.get(BACKEND_EXTRA)
            if isinstance(backend, Mapping):
                if isinstance(backend.get("url"), str) and backend["url"]:
                    return str(backend["url"]).rstrip("/")
                host = backend.get("host")
                if isinstance(host, str) and host:
                    scheme = backend.get("protocol") or "http"
                    port = f":{backend['port']}" if backend.get("port") else ""
                    return f"{scheme}://{host}{port}{backend.get('path') or ''}".rstrip("/")
    for server in api.servers:
        if server.url and urlsplit(server.url).scheme in ("http", "https"):
            url = server.url
            for variable in server.variables or []:
                if variable.default is not None:
                    url = url.replace("{" + variable.name + "}", str(variable.default))
            if "{" in url:
                continue  # a variable with no default leaves no concrete URL
            return url.rstrip("/")
    return None


def later_duplicates(api: CanonicalApi) -> set:
    """Keys of operations that share a method and path with an earlier operation."""
    seen: set = set()
    duplicates: set = set()
    for operation in api.operations():
        if not operation.http_path:
            continue
        coordinate = ((operation.http_method or "").upper(), operation.http_path)
        if coordinate in seen:
            duplicates.add(operation.key)
        seen.add(coordinate)
    return duplicates


def record_method_path_collisions(api: CanonicalApi, losses: LossTracker, *, label: str) -> None:
    """Declare operations an OpenAPI document cannot hold side by side.

    A gateway route can be qualified by host or by a header or query match, so two routes may
    share one method and path (``ANY /`` for two hosts). OpenAPI holds one operation per method
    and path, so all but the first collapse into it — reported, never silent.

    Args:
        api: The model being exported.
        losses: Where the losses go.
        label: The target's name, for the message.
    """
    seen: Dict[Tuple[str, str], str] = {}
    for operation in api.operations():
        if not operation.http_path:
            continue
        coordinate = ((operation.http_method or "").upper(), operation.http_path)
        if coordinate in seen:
            losses.record(
                LossKind.NA,
                "duplicate-method-path",
                f"Operation {operation.key!r} has the same method and path as {seen[coordinate]!r} "
                f"(they differ only by host or a header / query condition); a {label} document holds "
                "one operation per method and path, so it is merged into the first.",
                operation.key,
            )
        else:
            seen[coordinate] = operation.key


#: Canonical scheme → the OpenAPI ``http`` scheme it is, for the ones OpenAPI spells as ``http``.
_HTTP_SCHEMES = {"bearer": "bearer", "basic": "basic", "digest": "digest"}


def openapi_security_from_records(
    document: Dict[str, Any],
    op: Dict[str, Any],
    records: Sequence[Mapping[str, Any]],
    *,
    extension_keys: Mapping[str, str] = {},
) -> List[Mapping[str, Any]]:
    """Rebuild declared security schemes and an operation's requirements from security records.

    An AWS or APIM import reads ``components.securitySchemes`` and each operation's ``security``
    into records (``{scheme, name, scopes, in?, parameterName?, …, provenance: "declared"}``).
    The OpenAPI projection does not write those back, so this does: one scheme per record name
    and one requirement per record, which the importers read back to the same records.

    Args:
        document: The OpenAPI document (``components.securitySchemes`` is added to).
        op: The operation object (``security`` is set when any record maps).
        records: The operation's security records.
        extension_keys: Record key → extension to copy it under (AWS: ``authType`` →
            ``x-amazon-apigateway-authtype``, ``authorizer`` → ``x-amazon-apigateway-authorizer``).

    Returns:
        The records that could not be rebuilt (no scheme name, or an OAuth 2 / OpenID Connect
        scheme whose flows or URL the record does not carry).
    """
    schemes = document.setdefault("components", {}).setdefault("securitySchemes", {})
    requirements: List[Dict[str, List[str]]] = []
    unmapped: List[Mapping[str, Any]] = []
    for record in records:
        name = record.get("name")
        scheme = str(record.get("scheme") or "")
        if not isinstance(name, str) or record.get("provenance") != "declared" or record.get("derivedFrom") == "policy":
            unmapped.append(record)
            continue
        if isinstance(record.get("parameterName"), str) and record.get("in"):
            body: Dict[str, Any] = {"type": "apiKey", "name": record["parameterName"], "in": record["in"]}
        elif scheme in _HTTP_SCHEMES:
            body = {"type": "http", "scheme": _HTTP_SCHEMES[scheme]}
        elif scheme == "awsSigv4":
            body = {"type": "apiKey", "name": "Authorization", "in": "header"}
        else:
            unmapped.append(record)
            continue
        for key, extension in extension_keys.items():
            if record.get(key) is not None:
                body[extension] = record[key]
        schemes.setdefault(name, body)
        requirements.append({name: [str(scope) for scope in record.get("scopes") or []]})
    if requirements:
        op["security"] = requirements
    if not schemes:
        document["components"].pop("securitySchemes")
        if not document["components"]:
            document.pop("components")
    return unmapped
