"""OpenRPC emitter: canonical model → OpenRPC 1.3 JSON — MFX-33.1 (#4301).

The inverse of :class:`app.openrpc_normalizer.OpenRpcNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The document validates against the OpenRPC meta-schema
(:func:`validate_openrpc_document`, vendored from ``@open-rpc/meta-schema`` 1.14.9):

* **Document** — ``openrpc`` (an OpenRPC source's own version, else ``1.3.2``), ``info`` (title, the
  version — ``0.0.0`` when the source has none, reported — and description), ``servers`` with their
  variables.
* **Methods** — each service operation is one method; the JSON-RPC method name is the operation name
  (made unique across services). An RPC operation's request becomes its ``params`` (an OpenRPC
  source's own parameter list as written, else one ``params`` content descriptor), its response the
  ``result``, its error responses ``errors`` (``code`` / ``message`` / ``data``), its tags ``tags``.
  A one-way operation is a **notification**: a method with no ``result``.
* **REST sources are reframed** (reported per operation): path, query, header and cookie parameters
  and the request body become by-name ``params`` (``paramStructure: by-name``), the success response
  the ``result`` (``{"type": "null"}`` when it has no body), numeric error statuses ``errors`` with the
  status as ``code``, and the HTTP binding is kept as the extension ``x-http: {method, path}``.
* **Schemas** — named types are ``components/schemas`` through the canonical JSON-Schema mapping
  (:class:`app.emitter.SchemaEmitter`); every ``$ref`` names a written component, and canonical scalars
  (``i64``, ``bool``, ``timestamp`` …) resolve through
  :data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS`.

Whatever cannot be carried is reported as a :class:`~app.emitter.Loss`; the fidelity pack
(:class:`OpenRpcFidelityRulePack`) predicts exactly those losses.
"""

from __future__ import annotations

import copy
import json
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_json_schema import CANONICAL_SCALAR_SCHEMAS
from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    Service,
    StreamingMode,
    TypeKind,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
    SchemaEmitter,
    _emit_constraints,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity
from .writer_loss_rulepack import WriterLossRulePack

__all__ = [
    "OPENRPC_META_SCHEMA_PATH",
    "OpenRpcEmitOptions",
    "OpenRpcEmitter",
    "OpenRpcFidelityRulePack",
    "validate_openrpc_document",
]

#: The OpenRPC document meta-schema (``@open-rpc/meta-schema`` 1.14.9), vendored for offline validation.
OPENRPC_META_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "openrpc_meta_schema_1_14_9.json"

_REF_PREFIX = "#/components/schemas/"
_DEFAULT_VERSION = "1.3.2"
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: JSON-RPC reserves -32768 … -32000 for its own errors.
_RESERVED_CODES = range(-32768, -31999)


class OpenRpcFidelityRulePack(WriterLossRulePack):
    """Fidelity rules for OpenRPC export — MFX-33.1 (#4301), loss enumeration MFX-33.2 (#4302).

    The pack builds the document with the OpenRPC writer and turns each loss the writer records into a
    verdict on the construct it concerns (:class:`~app.writer_loss_rulepack.WriterLossRulePack`), so the
    report predicts exactly what the export writes. JSON-RPC 2.0 has no HTTP semantics, no streams and no
    channels, so a REST or gRPC source's losses are enumerated one by one:

    * **HTTP** — per REST operation: the method and path are dropped (``DROP``; kept only as ``x-http``),
      the parameter locations reframed as by-name params (``APPROX``), a success status other than 200
      dropped (``DROP``), error statuses turned into error codes (``APPROX``), response headers dropped;
      errors without an integer status (``default``, ``4XX``) dropped.
    * **Streaming** — a gRPC client / server / bidi stream and a GraphQL subscription are ``DROP``: the
      call is written as one request and one response.
    * **Events** — a publish / subscribe operation is a notification (``APPROX``) carrying its message and
      channel parameters; a channel used by one is ``APPROX`` (its address is the notification's
      ``x-channel``), an unused channel ``DROP``.
    * **Field identity** — a source field number (Protobuf, Thrift) is ``DROP`` (``info``): JSON Schema
      properties have no numbers.

    A carried operation is ``OK`` and its ``target_mapping`` names the method or notification it became.
    A non-OpenRPC document and a REST API's reframing are reported at the root; agents are dropped.
    """

    target_label = "OpenRPC"
    critical_drops = frozenset({"unsupported-type"})
    info_drops = frozenset({"error-payload-dropped"})
    cosmetic = frozenset({"renamed-method", "renamed-component"})

    def build_writer(self, api: CanonicalApi) -> "_OpenRpcWriter":
        """Build the document (default options: they change no loss)."""
        writer = _OpenRpcWriter(api, OpenRpcEmitOptions())
        writer.build()
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A REST source reframed to JSON-RPC, agent descriptors, and losses with no construct."""
        verdicts: List[FidelityVerdict] = []
        if api.format != "openrpc":
            verdicts.append(FidelityVerdict.approx(
                message="The document is written as an OpenRPC service description and reads back as a "
                "JSON-RPC API, with its title, version and servers in `info` and `servers`",
                severity=LossinessSeverity.INFO,
                target_mapping="document → OpenRPC",
            ))
        if api.paradigm is ApiParadigm.REST and any(op.http_method for op in api.operations()):
            verdicts.append(FidelityVerdict.approx(
                message="OpenRPC describes JSON-RPC methods; this REST API's operations are reframed as "
                "methods with by-name params, and it reads back as an RPC API",
                target_mapping="rest → JSON-RPC",
            ))
        if api.agents:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
                target_mapping="agents → dropped",
            ))
        return verdicts + self.loss_verdicts(ROOT_CONSTRUCT_KEY)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The writer's losses for the field, plus a dropped field number (JSON Schema has none)."""
        identity = self._field_identity_verdict(field)
        return self.loss_verdicts(field.key) + ([identity] if identity is not None else [])


class OpenRpcEmitOptions(EmitOptions):
    """Per-target options for :class:`OpenRpcEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")


class OpenRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OpenRPC JSON document."""

    key = "openrpc"
    format = "openrpc"
    label = "OpenRPC"
    description = "Export as an OpenRPC JSON-RPC 2.0 service description."
    icon = "workflow"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = OpenRpcEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return OpenRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[OpenRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, OpenRpcEmitOptions)
            else OpenRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _OpenRpcWriter(api, options)
        writer.build()
        if not writer.document["methods"] and not writer.document.get("components"):
            raise EmitPreconditionError(
                "OpenRPC export needs at least one method or schema to write; this source has neither."
            )
        return EmitResult(
            files=[EmittedFile(path=writer.output_path, content=writer.render(), media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Writer
# ===========================================================================


class _OpenRpcWriter:
    """Build the OpenRPC document (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: OpenRpcEmitOptions) -> None:
        self._api = api
        self._options = options
        self._openrpc_source = api.format == "openrpc"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._schema = SchemaEmitter(ref_prefix=_REF_PREFIX)
        self.output_path = _output_path(api)
        #: Type key or name → component name.
        self._components: Dict[str, str] = {}
        #: Key → what it became (``method getPet``), for the fidelity pack.
        self._written: Dict[str, str] = {}
        self._context: Optional[str] = None
        self.document: Dict[str, Any] = {}

    def build(self) -> None:
        """Write the document into :attr:`document`."""
        self._claim_components()
        document: Dict[str, Any] = {"openrpc": self._version(), "info": self._info()}
        servers = [self._server(server) for server in self._api.servers]
        if servers:
            document["servers"] = servers
        document["methods"] = self._methods()
        schemas = self._schemas()
        if schemas:
            document["components"] = {"schemas": schemas}
        self._channel_losses()
        self.document = document

    def render(self) -> str:
        """The document as JSON text."""
        indent = self._options.indent if self._options.indent > 0 else None
        return json.dumps(self.document, indent=indent, ensure_ascii=False) + "\n"

    def written_as(self, key: str) -> Optional[str]:
        """What the operation or type ``key`` became, or ``None``."""
        return self._written.get(key)

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def _version(self) -> str:
        declared = self._api.extras.get("openrpc_version") if self._openrpc_source else None
        return declared if isinstance(declared, str) and declared in _meta_versions() else _DEFAULT_VERSION

    def _info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {"title": self._api.title or self._api.identity.name or "API"}
        if self._api.version:
            info["version"] = str(self._api.version)
        else:
            info["version"] = "0.0.0"
            self.losses.record(LossKind.INFERRED, "version-synthesized",
                               "OpenRPC requires info.version; the source has none, so 0.0.0 is written.")
        if self._api.description:
            info["description"] = self._api.description
        return info

    @staticmethod
    def _server(server: Any) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"url": server.url}
        if server.name:
            entry["name"] = server.name
        if server.description:
            entry["description"] = server.description
        variables: Dict[str, Any] = {}
        for variable in server.variables:
            spec: Dict[str, Any] = {"default": str(variable.default if variable.default is not None
                                                    else (variable.enum or [""])[0])}
            if variable.enum:
                spec["enum"] = [str(v) for v in variable.enum]
            if variable.description:
                spec["description"] = variable.description
            variables[variable.name] = spec
        if variables:
            entry["variables"] = variables
        return entry

    # ------------------------------------------------------------------
    # Schemas
    # ------------------------------------------------------------------

    def _claim_components(self) -> None:
        """Give every named type a component name: its name made safe for a JSON pointer, unique."""
        taken: Set[str] = set()
        for type_ in self._api.types:
            base = re.sub(r"[^A-Za-z0-9._-]+", "_", type_.name).strip("_") or "Schema"
            name, suffix = base, 2
            while name in taken:
                name, suffix = f"{base}{suffix}", suffix + 1
            taken.add(name)
            if name != type_.name:
                self.losses.record(LossKind.INFERRED, "renamed-component",
                                   f"OpenRPC component names are unique and safe in a JSON pointer; {type_.name!r} "
                                   f"is written as {name!r}.", pointer=type_.key)
            self._components[type_.key] = name
            self._components.setdefault(type_.name, name)

    def _schemas(self) -> Dict[str, Any]:
        schemas: Dict[str, Any] = {}
        for type_ in self._api.types:
            self._context = type_.key
            if type_.kind not in (TypeKind.RECORD, TypeKind.ENUM, TypeKind.UNION, TypeKind.MAP, TypeKind.ALIAS,
                                  TypeKind.SCALAR):
                self.losses.record(LossKind.NA, "unsupported-type",
                                   f"Type {type_.key!r} ({type_.kind.value}) has no JSON-Schema form and is not "
                                   "written.", pointer=type_.key)
                continue
            name = self._components[type_.key]
            schema = self._resolve(self._schema.named_schema(type_))
            repeated = sorted({f.name for f in type_.fields if [g.name for g in type_.fields].count(f.name) > 1})
            if repeated:
                # JSON-Schema properties are keyed by name: a repeated field keeps one entry.
                self.losses.record(LossKind.NA, "duplicate-field-dropped",
                                   f"JSON-Schema properties are unique; the repeated field(s) {', '.join(repeated)} of "
                                   f"{type_.key!r} keep one entry.", pointer=type_.key)
                if isinstance(schema.get("required"), list):
                    schema["required"] = list(dict.fromkeys(schema["required"]))
            schemas[name] = schema
            self._written[type_.key] = f"schema {name}"
            self.tracker.record(type_.key, Provenance.SOURCE)
        self._context = None
        return schemas

    def _resolve(self, schema: Any) -> Any:
        """Point every ``$ref`` at a written component; a canonical scalar becomes its JSON-Schema form."""
        if isinstance(schema, list):
            return [self._resolve(item) for item in schema]
        if not isinstance(schema, dict):
            return schema
        out = {key: self._resolve(value) for key, value in schema.items()}
        ref = out.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            target = ref[len(_REF_PREFIX):]
            if target in self._components:
                out["$ref"] = _REF_PREFIX + self._components[target]
            else:
                del out["$ref"]
                scalar = CANONICAL_SCALAR_SCHEMAS.get(target.lower())
                if scalar is None:
                    self.losses.record(LossKind.INFERRED, "unknown-type",
                                       f"The type {target!r} has no JSON-Schema form; it is written as any value.",
                                       pointer=self._context)
                out = {**copy.deepcopy(scalar or {}), **out}
        return out

    def _type_schema(self, ref: Any, constraints: Any = None, default: Any = None) -> Dict[str, Any]:
        schema = self._resolve(self._schema.type_ref(ref)) if ref is not None else {}
        # Whole-number bounds read as integers (`minimum: 1`, not `1.0`).
        schema.update({key: int(value) if isinstance(value, float) and value.is_integer() else value
                       for key, value in _emit_constraints(constraints).items()})
        if default is not None:
            schema["default"] = default
        return schema

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------

    def _methods(self) -> List[Dict[str, Any]]:
        methods: List[Dict[str, Any]] = []
        names: Set[str] = set()
        for service in self._api.services:
            for operation in service.operations:
                self._context = operation.key
                method = self._method(operation, service, names)
                if method is not None:
                    methods.append(method)
        self._context = None
        return methods

    def _method(self, operation: Operation, service: Service, names: Set[str]) -> Optional[Dict[str, Any]]:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return self._event_notification(operation, service, names)
        name = self._method_name(operation, service, names)
        method: Dict[str, Any] = {"name": name}
        summary = operation.extras.get("openrpc_summary") if self._openrpc_source else None
        if isinstance(summary, str) and summary:
            method["summary"] = summary
        if operation.description and operation.description != summary:
            method["description"] = operation.description
        if operation.tags:
            method["tags"] = [{"name": tag} for tag in operation.tags]
        rest = bool(operation.http_method)
        method["params"] = self._rest_params(operation) if rest else self._rpc_params(operation)
        structure = operation.extras.get("openrpc_param_structure") if self._openrpc_source else None
        if rest:
            method["paramStructure"] = "by-name"
        elif isinstance(structure, str) and structure:
            method["paramStructure"] = structure
        notification = operation.kind is OperationKind.ONE_WAY
        result = self._result(operation, rest)
        if notification and result is not None:
            self.losses.record(LossKind.NA, "response-dropped",
                               f"A JSON-RPC notification has no result; the response of {operation.key!r} is not "
                               "written.", pointer=operation.key)
        elif result is not None:
            method["result"] = result
        errors = self._errors(operation)
        if errors:
            method["errors"] = errors
        if operation.deprecated:
            method["deprecated"] = True
        if operation.streaming is not StreamingMode.NONE or operation.kind is OperationKind.SUBSCRIPTION:
            stream = ("a subscription" if operation.kind is OperationKind.SUBSCRIPTION
                      else f"{operation.streaming.value}-streaming")
            self.losses.record(LossKind.NA, "streaming-dropped",
                               f"JSON-RPC calls are one request and one response; {operation.key!r} ({stream}) is "
                               "written as one call.", pointer=operation.key)
        if rest:
            method["x-http"] = {"method": operation.http_method.upper(), "path": operation.http_path or "/"}
            self._http_losses(operation, name)
        self._written[operation.key] = f"{'notification' if notification else 'method'} {name}"
        self.tracker.record(operation.key, Provenance.SOURCE)
        return method

    def _event_notification(self, operation: Operation, service: Service, names: Set[str]) -> Dict[str, Any]:
        """A publish / subscribe operation as a JSON-RPC notification (MFX-33.2).

        Its channel's address parameters and its event message(s) become by-name params, and the channel
        address is kept as the extension ``x-channel``.
        """
        name = self._method_name(operation, service, names)
        method: Dict[str, Any] = {"name": name}
        if operation.description:
            method["description"] = operation.description
        if operation.tags:
            method["tags"] = [{"name": tag} for tag in operation.tags]
        channel = next((c for c in self._api.channels if c.key == operation.channel_ref), None)
        taken: Set[str] = set()
        params = [self._header_descriptor(field, taken) for field in (channel.parameters if channel else [])]
        for param in params:
            param["description"] = param["description"].replace("(header)", "(channel parameter)")
        events = [m for m in operation.messages if m.payload is not None or m.payload_schema]
        if events:
            schemas = [self._type_schema(m.payload) if m.payload is not None else dict(m.payload_schema)
                       for m in events]
            message: Dict[str, Any] = {"name": _unique("message", taken),
                                       "schema": schemas[0] if len(schemas) == 1 else {"oneOf": schemas},
                                       "required": True}
            params.append(message)
        method["params"] = params
        method["paramStructure"] = "by-name"
        if operation.deprecated:
            method["deprecated"] = True
        if channel is not None:
            method["x-channel"] = channel.address
        direction = "the service sends" if operation.kind is OperationKind.PUBLISH else "the service receives"
        self.losses.record(LossKind.INFERRED, "event-as-notification",
                           f"JSON-RPC has no channels; the {operation.kind.value} operation {operation.key!r} is the "
                           f"notification {name!r} {direction}, its message and channel parameters as by-name params "
                           f"(the address{' ' + repr(channel.address) if channel else ''} is kept as x-channel).",
                           pointer=operation.key)
        self._written[operation.key] = f"notification {name}"
        self.tracker.record(operation.key, Provenance.SOURCE)
        return method

    def _channel_losses(self) -> None:
        """A channel used by a written event operation is carried by its notifications; another is dropped."""
        for channel in self._api.channels:
            users = [self._written[op.key].split(" ", 1)[1] for op in self._api.operations()
                     if op.channel_ref == channel.key and op.key in self._written]
            if users:
                self.losses.record(LossKind.INFERRED, "channel-as-notification",
                                   f"JSON-RPC has no channels; {channel.address!r} is carried by the notification(s) "
                                   f"{', '.join(users)} as their x-channel.", pointer=channel.key)
            else:
                self.losses.record(LossKind.NA, "channel-dropped",
                                   f"JSON-RPC has no channels and no operation uses {channel.address!r}; it is not "
                                   "written.", pointer=channel.key)

    def _http_losses(self, operation: Operation, name: str) -> None:
        """Enumerate what a REST operation loses as a JSON-RPC method (MFX-33.2): its HTTP binding, the
        locations of its parameters, its success status and the meaning of its error statuses."""
        verb, path = operation.http_method.upper(), operation.http_path or "/"
        self.losses.record(LossKind.NA, "http-binding-dropped",
                           f"JSON-RPC has no HTTP method or path; {verb} {path} is the method {name!r} (the binding is "
                           "kept only as the x-http extension, which JSON-RPC clients ignore).", pointer=operation.key)
        located = [f"{p.location.value} {p.name}" for p in operation.parameters]
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        located += [f"header {h.name}" for h in (request.headers if request is not None else [])]
        if request is not None and (request.payload is not None or request.payload_schema):
            located.append("the body")
        if located:
            self.losses.record(LossKind.INFERRED, "http-parameters-reframed",
                               f"JSON-RPC params have no location; {', '.join(located)} of {operation.key!r} become "
                               "by-name params (each description names its location).", pointer=operation.key)
        statuses = sorted({str(m.status_code) for m in operation.messages
                           if m.role is MessageRole.RESPONSE and m.status_code and str(m.status_code) != "200"})
        if statuses:
            self.losses.record(LossKind.NA, "http-status-dropped",
                               f"A JSON-RPC result has no status; the {', '.join(statuses)} status of "
                               f"{operation.key!r} is not carried.", pointer=operation.key)
        codes = sorted({str(m.status_code) for m in operation.messages
                        if m.role is MessageRole.ERROR and _error_code(m.status_code) is not None})
        if codes:
            self.losses.record(LossKind.INFERRED, "http-status-as-error-code",
                               f"JSON-RPC errors have codes, not HTTP statuses; the {', '.join(codes)} error "
                               f"response(s) of {operation.key!r} are errors with that number as their code.",
                               pointer=operation.key)

    def _method_name(self, operation: Operation, service: Service, names: Set[str]) -> str:
        """The operation name, unique in the document (qualified by its service on a clash)."""
        base = operation.name or operation.key
        name = base
        if name in names:
            name = f"{service.name}.{base}"
        suffix = 2
        while name in names:
            name, suffix = f"{service.name}.{base}{suffix}", suffix + 1
        names.add(name)
        if name != base:
            self.losses.record(LossKind.INFERRED, "renamed-method",
                               f"JSON-RPC method names are unique; {base!r} of {operation.key!r} is written as "
                               f"{name!r}.",
                               pointer=operation.key)
        return name

    def _rpc_params(self, operation: Operation) -> List[Dict[str, Any]]:
        """An RPC operation's params: an OpenRPC source's list as written, else one ``params`` descriptor."""
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is None:
            return []
        listed = request.extras.get("openrpc_params")
        if isinstance(listed, list):
            params = []
            for entry in listed:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    continue
                param: Dict[str, Any] = {"name": entry["name"], "schema": entry.get("schema") or {}}
                if entry.get("required"):
                    param["required"] = True
                if isinstance(entry.get("description"), str):
                    param["description"] = entry["description"]
                params.append(param)
            return params
        if request.payload is None and not request.payload_schema:
            return []
        schema = self._type_schema(request.payload) if request.payload is not None else dict(request.payload_schema)
        param = {"name": request.name or "params", "schema": schema}
        if request.required:
            param["required"] = True
        return [param]

    def _rest_params(self, operation: Operation) -> List[Dict[str, Any]]:
        """A REST operation's parameters, then its body, as by-name params (names unique)."""
        params: List[Dict[str, Any]] = []
        taken: Set[str] = set()
        for param in operation.parameters:
            params.append(self._param_descriptor(param, taken))
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        for header in request.headers if request is not None else []:
            params.append(self._header_descriptor(header, taken))
        if request is not None and (request.payload is not None or request.payload_schema):
            schema = self._type_schema(request.payload) if request.payload is not None else dict(request.payload_schema)
            body: Dict[str, Any] = {"name": _unique("body", taken), "schema": schema}
            if request.required:
                body["required"] = True
            if request.description:
                body["description"] = request.description
            params.append(body)
        return params

    def _param_descriptor(self, param: Parameter, taken: Set[str]) -> Dict[str, Any]:
        self._context = param.key
        descriptor: Dict[str, Any] = {
            "name": _unique(param.name, taken),
            "schema": self._type_schema(param.type, param.constraints, param.default),
        }
        if param.required:
            descriptor["required"] = True
        description = param.description or ""
        descriptor["description"] = (f"{description} " if description else "") + f"({param.location.value} parameter)"
        if param.deprecated:
            descriptor["deprecated"] = True
        self._context = None
        return descriptor

    def _header_descriptor(self, header: CanonicalField, taken: Set[str]) -> Dict[str, Any]:
        descriptor: Dict[str, Any] = {"name": _unique(header.name, taken),
                                      "schema": self._type_schema(header.type, header.constraints, header.default)}
        if header.type.nullable is False:
            descriptor["required"] = True
        descriptor["description"] = (f"{header.description} " if header.description else "") + "(header)"
        if header.deprecated:
            descriptor["deprecated"] = True
        return descriptor

    def _result(self, operation: Operation, rest: bool) -> Optional[Dict[str, Any]]:
        """The ``result`` descriptor: the success response (a REST one with no body is ``null``)."""
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        success = [m for m in responses if str(m.status_code or "200").startswith("2")] or responses
        if not success:
            if rest or operation.kind is OperationKind.ONE_WAY:
                return None if operation.kind is OperationKind.ONE_WAY else {"name": "result",
                                                                              "schema": {"type": "null"}}
            return None
        chosen = next((m for m in success if m.payload is not None or m.payload_schema), success[0])
        for other in responses:
            if other is not chosen:
                self.losses.record(LossKind.NA, "response-dropped",
                                   f"A JSON-RPC method has one result; the {other.status_code or 'other'} response "
                                   f"{other.key!r} of {operation.key!r} is not written.", pointer=operation.key)
        name = operation.extras.get("openrpc_result_name") if self._openrpc_source else None
        if not isinstance(name, str) or not name:
            name = chosen.name or "result"
        if chosen.payload is not None:
            schema = self._type_schema(chosen.payload)
        elif chosen.payload_schema:
            schema = dict(chosen.payload_schema)
        else:
            schema = {"type": "null"}
        result: Dict[str, Any] = {"name": name, "schema": schema}
        if chosen.description:
            result["description"] = chosen.description
        if chosen.headers:
            self.losses.record(LossKind.NA, "response-header-dropped",
                               f"A JSON-RPC result has no headers; those of {chosen.key!r} are not written.",
                               pointer=operation.key)
        return result

    def _errors(self, operation: Operation) -> List[Dict[str, Any]]:
        """``errors``: each error response with an integer code (a REST status becomes the code)."""
        errors: List[Dict[str, Any]] = []
        codes: Set[int] = set()
        for message in operation.messages:
            if message.role is not MessageRole.ERROR:
                continue
            code = _error_code(message.status_code)
            if code is None or code in codes:
                self.losses.record(LossKind.NA, "error-dropped",
                                   f"An OpenRPC error needs a distinct integer code; {message.key!r} (status "
                                   f"{message.status_code or 'none'}) is not written.", pointer=operation.key)
                continue
            codes.add(code)
            error: Dict[str, Any] = {"code": code, "message": message.description or _reason(code)}
            data = message.extras.get("openrpc_error_data") if self._openrpc_source else None
            if data is not None:
                error["data"] = data
            elif message.payload is not None or message.payload_schema:
                self.losses.record(LossKind.NA, "error-payload-dropped",
                                   f"An OpenRPC error carries a data value, not a schema; the payload type of "
                                   f"{message.key!r} is not written.", pointer=operation.key)
            errors.append(error)
        return errors


# ===========================================================================
# Helpers
# ===========================================================================


def _unique(name: str, taken: Set[str]) -> str:
    candidate, suffix = name, 2
    while candidate in taken:
        candidate, suffix = f"{name}{suffix}", suffix + 1
    taken.add(candidate)
    return candidate


def _error_code(status: Optional[str]) -> Optional[int]:
    """The JSON-RPC code for an error status: an integer status as is, else ``None``."""
    text = str(status or "").strip()
    if not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _reason(code: int) -> str:
    """A message for an error with no description: the HTTP reason phrase, or a generic one."""
    if code in _RESERVED_CODES:
        return "JSON-RPC error"
    try:
        return HTTPStatus(code).phrase
    except ValueError:
        return f"Error {code}"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.openrpc.json"


_META_SCHEMA: Optional[Dict[str, Any]] = None


def _meta_schema() -> Dict[str, Any]:
    global _META_SCHEMA
    if _META_SCHEMA is None:
        _META_SCHEMA = json.loads(OPENRPC_META_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _META_SCHEMA


def _meta_versions() -> Tuple[str, ...]:
    return tuple(_meta_schema()["properties"]["openrpc"]["enum"])


def meta_schema_errors(document: Any, limit: int = 5) -> List[str]:
    """The first ``limit`` OpenRPC meta-schema violations of ``document`` (``path: message``)."""
    from jsonschema import Draft7Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT7

    draft7 = Draft7Validator.META_SCHEMA
    registry = Registry().with_resource("http://json-schema.org/draft-07/schema", Resource(draft7, DRAFT7))
    validator = Draft7Validator(_meta_schema(), registry=registry)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in error.absolute_path) or '(root)'}: {error.message}" for error in errors[:limit]]


def validate_openrpc_document(text: str) -> None:
    """Validate an emitted OpenRPC document: the OpenRPC meta-schema, then a re-parse.

    Args:
        text: The document JSON.

    Raises:
        ValueError: When the text is not JSON, breaks the meta-schema (the first few violations named
            with their JSON path), or does not re-parse as OpenRPC.
    """
    from .openrpc_parser import parse_openrpc

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid OpenRPC document: not JSON ({exc.msg})") from exc
    errors = meta_schema_errors(document)
    if errors:
        raise ValueError(f"Invalid OpenRPC document (meta-schema): {'; '.join(errors)}")
    parse_openrpc(text)
