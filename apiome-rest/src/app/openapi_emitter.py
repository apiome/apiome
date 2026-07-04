"""Reference emitter: canonical model → OpenAPI 3.1 — MFI-22.1 (#4002), MFX-1.1 (#3834).

The inverse of :class:`app.openapi_normalizer.OpenApiNormalizer` and the reference
implementation of the :class:`app.emitter.Emitter` SPI. It walks a
:class:`~app.canonical_model.CanonicalApi` and produces a schema-valid **OpenAPI
3.1** document:

* identity/title/version/description → ``info``; :class:`~app.canonical_model.Server`
  → ``servers`` (URL templates + variables);
* services' :class:`~app.canonical_model.Operation`\\s → ``paths`` (one path item
  per route, one method per operation, with ``operationId``/``summary``/``tags``);
* :class:`~app.canonical_model.Parameter`\\s → ``parameters``;
  :class:`~app.canonical_model.Message`\\s → ``requestBody`` / ``responses`` with
  media types and headers;
* named :class:`~app.canonical_model.Type`\\s → ``components.schemas`` (via
  :class:`app.emitter.SchemaEmitter` — OpenAPI 3.1 schemas *are* JSON Schema).

Two properties make the output trustworthy:

* **Deterministic.** Every collection is emitted in a stable order (services,
  operations, parameters, and component schemas by ``key``; media types and
  headers by name), so re-converting the same model yields a byte-identical
  document. Feed the result to :func:`app.openapi_validator.validate_openapi_document`
  to confirm it passes the OpenAPI 3.1 meta-schema.

* **Provenance-tracked.** Every emitted value is tagged
  :attr:`~app.emitter.Provenance.SOURCE` (came from the model),
  :attr:`~app.emitter.Provenance.INFERRED` (derived from the model's structure —
  e.g. an HTTP binding synthesized for a gRPC method, or a synthesized
  ``operationId``), or :attr:`~app.emitter.Provenance.DEFAULT` (a system fallback —
  e.g. the ``openapi`` version string, or an empty response ``description``). The
  fidelity analyzer (MFI-22.3) reads this to show what the conversion added.

Non-REST models are projected onto the OpenAPI (path/verb/response) vocabulary by a
per-paradigm :class:`app.projection.ProjectionStrategy` (MFI-22.2), selected from the
model's :class:`~app.canonical_model.ApiParadigm`. The strategy resolves each
operation's ``(method, path)`` binding — or declares the operation has no OpenAPI
representation — and records its *losses* on a :class:`~app.emitter.LossTracker`: an
RPC method with no ``http`` annotation gets a synthesized ``POST /{Service}/{Method}``,
gRPC streaming and GraphQL subscriptions and event pub/sub are surfaced as
:attr:`~app.emitter.LossKind.NA` losses (and, where they *are* emitted, ``x-``
extensions) rather than silently dropped, and a data-schema model with only ``types``
emits a components-only document. Those losses accompany the provenance in the
returned :class:`~app.emitter.EmitResult` for the fidelity analyzer (MFI-22.3).

The emitter is pure (no I/O). It self-registers under the ``openapi-3.1`` format
key so :func:`app.emitter.get_emitter` resolves it.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    Message,
    MessageRole,
    Operation,
    ParameterLocation,
    Server,
    Service,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
    SchemaEmitter,
    _emit_constraints,
)
from .projection import ProjectionStrategy, RouteBinding, get_projection

__all__ = ["OpenApiEmitter"]

# OpenAPI 3.1 path-item methods the emitter can emit natively. OpenAPI 3.2-only
# methods (QUERY, additionalOperations) are stashed on vendor extensions instead.
_OAS31_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)
# Vendor extensions used when a 3.2-only HTTP method cannot be emitted as a native
# 3.1 path-item operation key (mirrors the UI 3.2→3.1 converter).
X_QUERY_OPERATION = "x-apiome-query-operation"
X_ADDITIONAL_OPERATIONS = "x-apiome-additional-operations"

# Extracts the identifier-safe tokens of a path/key when synthesizing an
# ``operationId`` (drops slashes, dots, and ``{param}`` braces).
_ID_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class OpenApiEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OpenAPI 3.1 document with provenance.

    Self-registers under ``openapi-3.1``. Primarily targets the REST paradigm but
    accepts any canonical model — non-REST operations get a best-effort HTTP
    binding so the acceptance-criterion RPC/data-schema coverage holds.
    """

    key = "openapi"
    format = "openapi-3.1"
    label = "OpenAPI 3.1"
    description = "Export as an OpenAPI 3.1 JSON document (JSON Schema components)."
    icon = "file-json"
    paradigm = ApiParadigm.REST
    multi_file = False

    #: The OpenAPI version string this emitter targets.
    OPENAPI_VERSION = "3.1.0"
    #: Primary output filename within a bundle.
    OUTPUT_PATH = "openapi.json"
    #: Primary bundle media type.
    OUTPUT_MEDIA_TYPE = "application/vnd.oai.openapi+json"
    #: ``info.version`` used when the model declares none (OAS requires the field).
    DEFAULT_INFO_VERSION = "0.0.0"
    #: Media type assumed when a message declares no ``content_types``.
    DEFAULT_MEDIA_TYPE = "application/json"
    #: ``description`` used for a response the model gives none (OAS requires it).
    DEFAULT_RESPONSE_DESCRIPTION = ""
    #: JSON-Pointer prefix component-type references are emitted with.
    REF_PREFIX = "#/components/schemas/"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """OpenAPI 3.1 carries operations, schemas, unions, and constraints."""
        return CapabilityProfile(
            operations=True,
            events=True,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[EmitOptions] = None,
    ) -> EmitResult:
        """Emit ``api`` as an OpenAPI 3.1 document with per-construct provenance.

        Args:
            api: The canonical model to convert.
            opts: Optional emit options (unused today; reserved for MFX-1.4).

        Returns:
            An :class:`~app.emitter.EmitResult` whose primary file is a schema-valid
            OpenAPI 3.1 dict and whose ``provenance`` records where each value came
            from. The output is deterministic for a given ``api``.
        """
        _ = opts
        tracker = ProvenanceTracker()
        losses = LossTracker()
        schema = SchemaEmitter(ref_prefix=self.REF_PREFIX)
        projection = get_projection(api.paradigm)

        document: Dict[str, Any] = {"openapi": self.OPENAPI_VERSION}
        tracker.record("/openapi", Provenance.DEFAULT, "emitter target OpenAPI version")

        document["info"] = self._info(api, tracker)

        servers = self._servers(api, tracker)
        if servers:
            document["servers"] = servers

        document["paths"] = self._paths(api, schema, tracker, projection, losses)

        components = self._components(api, schema, tracker)
        if components:
            document["components"] = components

        # Document-level ``x-`` notes the projection contributes (e.g. an event
        # projection's low-fidelity caveat). Emitted last, after components, so the
        # document order stays deterministic.
        for key, value in sorted(projection.document_extensions(api, losses).items()):
            document[key] = value
            tracker.record(
                ProvenanceTracker.child("", key),
                Provenance.INFERRED,
                f"{api.paradigm.value} projection document note",
            )

        return EmitResult.from_document(
            document,
            path=self.OUTPUT_PATH,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=tracker.records(),
            losses=losses.records(),
        )

    # --- info ---------------------------------------------------------------

    def _info(self, api: CanonicalApi, tracker: ProvenanceTracker) -> Dict[str, Any]:
        """Emit the ``info`` object (title + version are required by OAS)."""
        info: Dict[str, Any] = {}

        if api.title:
            info["title"] = api.title
            tracker.record("/info/title", Provenance.SOURCE)
        else:
            info["title"] = api.identity.name
            tracker.record("/info/title", Provenance.INFERRED, "from identity.name")

        if api.version:
            info["version"] = api.version
            tracker.record("/info/version", Provenance.SOURCE)
        else:
            info["version"] = self.DEFAULT_INFO_VERSION
            tracker.record(
                "/info/version", Provenance.DEFAULT, "model declares no version"
            )

        if api.description:
            info["description"] = api.description
            tracker.record("/info/description", Provenance.SOURCE)

        return info

    # --- servers ------------------------------------------------------------

    def _servers(
        self, api: CanonicalApi, tracker: ProvenanceTracker
    ) -> List[Dict[str, Any]]:
        """Emit the ``servers`` array (inverse of the normalizer's server mapping)."""
        servers: List[Dict[str, Any]] = []
        for index, server in enumerate(api.servers):
            base = f"/servers/{index}"
            entry: Dict[str, Any] = {"url": server.url}
            tracker.record(f"{base}/url", Provenance.SOURCE)
            if server.description:
                entry["description"] = server.description
                tracker.record(f"{base}/description", Provenance.SOURCE)
            variables = self._server_variables(server, base, tracker)
            if variables:
                entry["variables"] = variables
            servers.append(entry)
        return servers

    def _server_variables(
        self, server: Server, base: str, tracker: ProvenanceTracker
    ) -> Dict[str, Any]:
        """Emit a server's ``variables`` map (OAS requires each to have a ``default``)."""
        variables: Dict[str, Any] = {}
        for variable in server.variables:
            ptr = ProvenanceTracker.child(base, "variables", variable.name)
            spec: Dict[str, Any] = {}
            if variable.default is not None:
                spec["default"] = variable.default
                tracker.record(f"{ptr}/default", Provenance.SOURCE)
            else:
                # `default` is required on a Server Variable Object.
                spec["default"] = ""
                tracker.record(
                    f"{ptr}/default", Provenance.DEFAULT, "variable declares no default"
                )
            if variable.enum is not None:
                spec["enum"] = list(variable.enum)
            if variable.description is not None:
                spec["description"] = variable.description
            variables[variable.name] = spec
        return variables

    # --- paths / operations -------------------------------------------------

    def _paths(
        self,
        api: CanonicalApi,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
        projection: "ProjectionStrategy",
        losses: LossTracker,
    ) -> Dict[str, Any]:
        """Emit the ``paths`` object, one path item per route, one method per op.

        Operations are processed in a deterministic (service key, operation key)
        order. Each operation's ``(method, path)`` binding — and whether it came
        from the source or was synthesized — is resolved by the paradigm
        ``projection``; an operation the projection declares un-representable
        (:meth:`app.projection.ProjectionStrategy.route` returns ``None``, e.g. a
        GraphQL subscription) is skipped here and reported as a loss by the
        projection. ``operationId``\\s declared in the source are reserved first so
        a synthesized id never collides with — nor mutates — an authored one.
        """
        pairs = self._sorted_operation_pairs(api)
        reserved: Set[str] = {
            op.extras["operationId"]
            for _, op in pairs
            if isinstance(op.extras.get("operationId"), str)
        }

        paths: Dict[str, Any] = {}
        for service, operation in pairs:
            binding = projection.route(operation, service, losses)
            if binding is None:
                # The projection declared this operation to have no OpenAPI
                # representation (and recorded the loss); do not emit a path.
                continue
            item = paths.setdefault(binding.path, {})
            op_ptr = ProvenanceTracker.child("/paths", binding.path, binding.method)
            if not binding.from_source:
                tracker.record(
                    op_ptr,
                    Provenance.INFERRED,
                    "synthesized HTTP binding for a non-REST operation",
                )
            operation_obj = self._operation(
                operation, binding.method, binding.path, op_ptr, reserved, schema, tracker
            )
            self._apply_extensions(operation_obj, binding, op_ptr, tracker)
            method = binding.method.lower()
            if method not in _OAS31_METHODS:
                self._stash_non_oas31_operation(
                    item, method, operation_obj, operation, losses
                )
                continue
            item[method] = operation_obj
        return paths

    @staticmethod
    def _stash_non_oas31_operation(
        item: Dict[str, Any],
        method: str,
        operation_obj: Dict[str, Any],
        operation: Operation,
        losses: LossTracker,
    ) -> None:
        """Carry a 3.2-only HTTP method forward on ``x-apiome-*`` extensions."""
        if method == "query":
            item[X_QUERY_OPERATION] = operation_obj
            extension = X_QUERY_OPERATION
        else:
            additional = item.setdefault(X_ADDITIONAL_OPERATIONS, {})
            additional[method.upper()] = operation_obj
            extension = X_ADDITIONAL_OPERATIONS
        losses.record(
            LossKind.NA,
            "openapi-3.2-http-method",
            f"{method.upper()} {operation.http_path or operation.key} has no native "
            f"OpenAPI 3.1 path-item method; stashed on {extension}",
            pointer=operation.key,
        )

    @staticmethod
    def _apply_extensions(
        operation_obj: Dict[str, Any],
        binding: RouteBinding,
        op_ptr: str,
        tracker: ProvenanceTracker,
    ) -> None:
        """Merge a binding's ``x-`` specification extensions onto the operation.

        The projection uses these to surface paradigm nuance OpenAPI cannot model
        (a streaming cardinality, an event action). They are always
        :attr:`~app.emitter.Provenance.INFERRED` — derived from the model rather
        than an authored OpenAPI value — and merged in sorted key order for
        determinism.
        """
        for key, value in sorted(binding.extensions.items()):
            operation_obj[key] = value
            tracker.record(
                ProvenanceTracker.child(op_ptr, key),
                Provenance.INFERRED,
                "paradigm projection extension",
            )

    @staticmethod
    def _sorted_operation_pairs(api: CanonicalApi) -> List[Tuple[Service, Operation]]:
        """Return every ``(service, operation)`` in deterministic (service, op) order.

        The owning service travels with each operation because a projection may need
        it (the RPC projection names its synthesized ``/{Service}/{Method}`` route
        from the service key).
        """
        result: List[Tuple[Service, Operation]] = []
        for service in sorted(api.services, key=lambda s: s.key):
            for operation in sorted(service.operations, key=lambda o: o.key):
                result.append((service, operation))
        return result

    def _operation(
        self,
        operation: Operation,
        method: str,
        path: str,
        op_ptr: str,
        reserved: Set[str],
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit one Operation Object (id, summary, tags, params, body, responses)."""
        obj: Dict[str, Any] = {}

        declared_id = operation.extras.get("operationId")
        if isinstance(declared_id, str) and declared_id:
            obj["operationId"] = declared_id
            tracker.record(f"{op_ptr}/operationId", Provenance.SOURCE)
        else:
            synthesized = self._synth_operation_id(method, path, reserved)
            obj["operationId"] = synthesized
            reserved.add(synthesized)
            tracker.record(
                f"{op_ptr}/operationId",
                Provenance.INFERRED,
                "synthesized from method and path",
            )

        summary = operation.extras.get("summary")
        if isinstance(summary, str) and summary:
            obj["summary"] = summary
            tracker.record(f"{op_ptr}/summary", Provenance.SOURCE)
        if operation.description:
            obj["description"] = operation.description
            tracker.record(f"{op_ptr}/description", Provenance.SOURCE)
        if operation.deprecated:
            obj["deprecated"] = True
            tracker.record(f"{op_ptr}/deprecated", Provenance.SOURCE)
        if operation.tags:
            obj["tags"] = list(operation.tags)
            tracker.record(f"{op_ptr}/tags", Provenance.SOURCE)

        parameters = self._parameters(operation, op_ptr, schema, tracker)
        if parameters:
            obj["parameters"] = parameters

        request_body = self._request_body(operation, op_ptr, schema, tracker)
        if request_body is not None:
            obj["requestBody"] = request_body

        obj["responses"] = self._responses(operation, op_ptr, schema, tracker)
        return obj

    @staticmethod
    def _synth_operation_id(method: str, path: str, reserved: Set[str]) -> str:
        """Synthesize a unique ``operationId`` from ``method`` + ``path``.

        Deterministic (``GET /pets/{id}`` → ``getPetsId``) and disambiguated
        against ``reserved`` by a numeric suffix, so the result is stable and
        unique within the document.
        """
        tokens = _ID_TOKEN_RE.findall(path)
        base = method.lower() + "".join(token[:1].upper() + token[1:] for token in tokens)
        base = base or method.lower()
        candidate = base
        counter = 2
        while candidate in reserved:
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    def _parameters(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> List[Dict[str, Any]]:
        """Emit an operation's ``parameters`` (path/query/header/cookie)."""
        parameters: List[Dict[str, Any]] = []
        for index, param in enumerate(sorted(operation.parameters, key=lambda p: p.key)):
            ptr = ProvenanceTracker.child(op_ptr, "parameters", str(index))
            entry: Dict[str, Any] = {"name": param.name, "in": param.location.value}
            # Path parameters are always required per the OpenAPI spec.
            if param.required or param.location is ParameterLocation.PATH:
                entry["required"] = True
            entry["schema"] = self._leaf_schema(
                schema.type_ref(param.type), param.constraints, param.default
            )
            if param.description:
                entry["description"] = param.description
            if param.deprecated:
                entry["deprecated"] = True
            tracker.record(ptr, Provenance.SOURCE)
            parameters.append(entry)
        return parameters

    # --- messages: request body & responses ---------------------------------

    def _request_body(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Optional[Dict[str, Any]]:
        """Emit ``requestBody`` from the operation's REQUEST message, if any."""
        request = next(
            (m for m in operation.messages if m.role is MessageRole.REQUEST), None
        )
        if request is None:
            return None
        ptr = f"{op_ptr}/requestBody"
        body: Dict[str, Any] = {
            # requestBody.content is required; always emit at least one media type.
            "content": self._content(request, ptr, schema, tracker, force=True)
        }
        if request.description:
            body["description"] = request.description
        tracker.record(ptr, Provenance.SOURCE)
        return body

    def _responses(
        self,
        operation: Operation,
        op_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit the ``responses`` object from RESPONSE/ERROR messages.

        Each response gets a ``description`` (required by OAS — defaulted when the
        message has none). An operation with no response messages gets a single
        ``default`` response so the operation is still well-formed.
        """
        responses: Dict[str, Any] = {}
        messages = [
            m
            for m in operation.messages
            if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)
        ]
        for message in sorted(messages, key=lambda m: m.key):
            status, status_source = self._status_code(message)
            if status in responses:
                # Two messages collapsed to the same status key: keep the first
                # (deterministic by sort order) so the responses map stays valid.
                continue
            ptr = ProvenanceTracker.child(op_ptr, "responses", status)
            if not status_source:
                tracker.record(
                    ptr, Provenance.INFERRED, "status code inferred from message role"
                )
            responses[status] = self._response(message, ptr, schema, tracker)

        if not responses:
            ptr = ProvenanceTracker.child(op_ptr, "responses", "default")
            responses["default"] = {"description": self.DEFAULT_RESPONSE_DESCRIPTION}
            tracker.record(
                ptr, Provenance.DEFAULT, "operation declares no response messages"
            )
        return responses

    @staticmethod
    def _status_code(message: Message) -> Tuple[str, bool]:
        """Resolve a response message's status key and whether it came from source.

        A message with a ``status_code`` uses it (``True``); otherwise a success
        RESPONSE defaults to ``"200"`` and an ERROR to ``"default"`` (``False``).
        """
        if message.status_code:
            return message.status_code, True
        return ("default" if message.role is MessageRole.ERROR else "200"), False

    def _response(
        self,
        message: Message,
        ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit one Response Object (description, optional content + headers)."""
        response: Dict[str, Any] = {}
        if message.description:
            response["description"] = message.description
            tracker.record(f"{ptr}/description", Provenance.SOURCE)
        else:
            response["description"] = self.DEFAULT_RESPONSE_DESCRIPTION
            tracker.record(
                f"{ptr}/description", Provenance.DEFAULT, "response has no description"
            )

        content = self._content(message, ptr, schema, tracker, force=False)
        if content:
            response["content"] = content

        headers = self._headers(message, ptr, schema, tracker)
        if headers:
            response["headers"] = headers
        return response

    def _headers(
        self,
        message: Message,
        ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
    ) -> Dict[str, Any]:
        """Emit a response message's header fields as an OAS ``headers`` map."""
        headers: Dict[str, Any] = {}
        for header in sorted(message.headers, key=lambda h: h.key):
            entry: Dict[str, Any] = {
                "schema": self._leaf_schema(
                    schema.type_ref(header.type), header.constraints, header.default
                )
            }
            if header.description:
                entry["description"] = header.description
            if header.deprecated:
                entry["deprecated"] = True
            headers[header.name] = entry
        if headers:
            tracker.record(f"{ptr}/headers", Provenance.SOURCE)
        return headers

    def _content(
        self,
        message: Message,
        base_ptr: str,
        schema: SchemaEmitter,
        tracker: ProvenanceTracker,
        *,
        force: bool,
    ) -> Dict[str, Any]:
        """Emit a message's ``content`` map (one Media Type Object per media type).

        Args:
            force: When ``True`` a media type is always emitted (``requestBody``
                requires ``content``); when ``False`` an empty body yields ``{}``
                so the caller can omit ``content`` entirely.
        """
        payload_schema = self._payload_schema(message, schema)
        if payload_schema is None and not message.content_types and not force:
            return {}

        media_types = sorted(message.content_types) or [self.DEFAULT_MEDIA_TYPE]
        content: Dict[str, Any] = {}
        for media_type in media_types:
            media_obj: Dict[str, Any] = {}
            if payload_schema is not None:
                media_obj["schema"] = payload_schema
            content[media_type] = media_obj

        ptr = f"{base_ptr}/content"
        if message.content_types:
            tracker.record(ptr, Provenance.SOURCE)
        else:
            tracker.record(
                ptr, Provenance.INFERRED, f"default media type {self.DEFAULT_MEDIA_TYPE}"
            )
        return content

    @staticmethod
    def _payload_schema(
        message: Message, schema: SchemaEmitter
    ) -> Optional[Dict[str, Any]]:
        """Resolve a message's body schema from its ``payload`` ref or inline schema."""
        if message.payload is not None:
            return schema.type_ref(message.payload)
        if message.payload_schema is not None:
            return dict(message.payload_schema)
        return None

    # --- components ---------------------------------------------------------

    def _components(
        self, api: CanonicalApi, schema: SchemaEmitter, tracker: ProvenanceTracker
    ) -> Dict[str, Any]:
        """Emit ``components.schemas`` from the model's named types."""
        schemas: Dict[str, Any] = {}
        for type_ in sorted(api.types, key=lambda t: t.key):
            schemas[type_.key] = schema.named_schema(type_)
            tracker.record(
                ProvenanceTracker.child("/components/schemas", type_.key),
                Provenance.SOURCE,
            )
        return {"schemas": schemas} if schemas else {}

    # --- shared helpers -----------------------------------------------------

    @staticmethod
    def _leaf_schema(
        base: Dict[str, Any],
        constraints: Any,
        default: Any,
    ) -> Dict[str, Any]:
        """Compose constraints/default onto a use-site schema when it is a plain leaf.

        A ``$ref`` fragment cannot carry sibling keywords in JSON Schema, so
        constraints and defaults are only merged onto a plain (typed or empty)
        schema; on a reference leaf they are dropped to keep the output valid.
        """
        if "$ref" in base:
            return base
        base.update(_emit_constraints(constraints))
        if default is not None:
            base["default"] = default
        return base
