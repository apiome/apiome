"""Google API Discovery emitter: canonical model → a Discovery REST description — MFX-29.2 (#4174).

The inverse of :class:`app.discovery_normalizer.DiscoveryNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. Writes one ``<name>.discovery.json`` — a
``discovery#restDescription`` (https://developers.google.com/discovery/v1/reference/apis), the document
Google's generated and dynamic clients (``googleapiclient.discovery.build_from_document``) are built from:

* **The document.** ``kind``, ``discoveryVersion`` ``v1``, ``id`` ``<name>:<version>``, ``name`` (lower-case
  letters and digits: an imported Discovery item's own, else made from the item's name), ``version`` (the
  item's, else ``v1``), ``title``, ``description``, ``protocol`` ``rest``, and the URLs from the first server:
  ``rootUrl`` (scheme and host), ``servicePath`` (its path), ``baseUrl`` and ``basePath``.
* **Resources and methods.** An imported Discovery item keeps its resource tree, method names and ids. For any
  other source, an operation is filed under the resource named by its path's first literal segment
  (``/pets/{petId}`` → ``pets``) and named after the operation (``listPets``); one whose path starts with a
  parameter is a top-level method. Each method has its ``id`` (``<name>.<resource>.<method>``), ``path``
  (relative to ``servicePath``), ``httpMethod``, ``description``, ``parameters`` (``path`` and ``query``),
  ``parameterOrder`` (the required parameters, path ones first) and a ``request`` / ``response`` ``$ref``.
* **Schemas.** Every type, in the Discovery JSON Schema subset (:mod:`app.discovery_schema`, which reuses the
  JSON Schema export's draft-04 downgrade). A body that is not one named type (a list, a scalar, an inline
  schema) gets a schema of its own, ``<Method>Request`` / ``<Method>Response``.

**Not carried, and reported:** event operations and operations with no HTTP binding, header and cookie
parameters (Discovery parameters go in the path or the query), every response but the method's success body
(Discovery has one ``response``; errors are Google's standard error), servers beyond the first, and each schema
keyword the subset has no place for. :mod:`app.discovery_validation` holds the Discovery metaschema and the
document's rules; the export gate checks every export with them before delivery (MFX-29.3), and Google's client
library builds a client from it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
)
from .discovery_schema import DiscoverySchemaWriter, identifier
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    Loss,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict, rest_only_advisory
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = ["DiscoveryEmitOptions", "DiscoveryEmitter", "DiscoveryFidelityRulePack"]

_DISCOVERY_FORMAT = "discovery"
_KIND = "discovery#restDescription"
_DEFAULT_ROOT = "https://api.example.com/"
_DEFAULT_VERSION = "v1"
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: Operation extras an imported Discovery item records and the export writes back (not lost).
_DISCOVERY_OPERATION_EXTRAS = frozenset({"discovery_method", "discovery_resource_path", "discovery_id"})
#: API extras an imported Discovery item records and the export writes back.
_DISCOVERY_API_EXTRAS = frozenset({
    "discovery_version", "discovery_kind", "discovery_id", "discovery_name", "discovery_documentation_link",
    "discovery_service_path",
})
_NAME = re.compile(r"^[a-z][a-z0-9]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: A path template variable: ``{name}`` or a reserved expansion ``{+name}``.
_TEMPLATE_VARIABLE = re.compile(r"\{\+?([^}]+)\}")
_PATH_PARAMETER_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_SUCCESS = re.compile(r"^2[0-9]{2}$")
#: Loss subjects reported as synthesized (the export invents the construct), and those at info severity.
_SYNTH_SUBJECTS = frozenset({"root-url-synthesized", "name-synthesized", "body-schema-synthesized",
                             "method-renamed", "resource-synthesized"})
_INFO_SUBJECTS = frozenset({"int64-as-string", "integer-as-int32", "root-url-synthesized", "name-synthesized",
                            "body-schema-synthesized", "method-renamed", "resource-synthesized",
                            "parameter-renamed", "servers-dropped", "document-details-dropped",
                            "operation-details-dropped", "path-parameter-required", "base-url-completed"})


class DiscoveryEmitOptions(EmitOptions):
    """Per-target options for :class:`DiscoveryEmitter`."""

    name: Optional[str] = Field(
        default=None,
        description="The API name (`name`, lower-case letters and digits, e.g. `bookstore`). Default: an imported "
        "Discovery item's own, else made from the item's name.",
    )
    version: Optional[str] = Field(
        default=None,
        description="The API version (`version`, e.g. `v1`). Default: the item's version, else `v1`.",
    )
    indent: int = Field(default=2, ge=0, le=8, description="JSON indentation (0 writes one line).")

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _NAME.match(value):
            raise ValueError("name must be lower-case letters and digits, starting with a letter")
        return value

    @field_validator("version")
    @classmethod
    def _check_version(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not _VERSION.match(value):
            raise ValueError("version must be letters, digits, '.', '_' or '-' (e.g. v1)")
        return value


class DiscoveryFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Discovery export — MFX-29.2 (#4174), MFX-29.3 (#4175).

    A source that is not a REST API (GraphQL, RPC, event, data schema, agent) gets the root advisory
    **Google API Discovery captures REST only** (:func:`app.fidelity_rulepack.rest_only_advisory`, the RAML
    wording): a ``DROP`` with the operations and channels that are not written, critical when only the types are.

    The pack builds the export once (for the options the report is computed for) and files every loss its
    writer records under the construct it is in — a schema keyword under its type or field, a parameter or body
    under its operation, a document detail under the root:

    * **DROP** — event operations, operations with no HTTP binding, header and cookie parameters, responses
      beside the success body, servers beyond the first, schema keywords Discovery has no place for
      (``minLength``, ``maxItems`` …), non-string enums, object and array defaults, unknown string formats;
    * **APPROX** — the rewrite of another format; unions as ``type: any``; nullable types; 64-bit integers as
      strings (Discovery's convention, info); integers as ``int32``; exclusive bounds written inclusive;
      renamed path parameters; operation details not written;
    * **SYNTH** — the ``rootUrl`` when the source has no server; the API ``name``; a method or resource name
      made from the path; a body schema for a body that is not one named type.
    """

    target_label = "Discovery"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options (invalid options fall back to the defaults)."""
        try:
            self._options = DiscoveryEmitOptions.model_validate(dict(options))
        except ValueError:
            self._options = DiscoveryEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the export as it will be emitted, file its losses, then walk the model."""
        writer = _DiscoveryWriter(api, getattr(self, "_options", None) or DiscoveryEmitOptions())
        try:
            writer.render()
        except EmitPreconditionError:
            # Nothing to export (the target is unavailable for this source): the walk reports the model as is.
            pass
        self._schema_ids = writer.schema_writer.bundle.defs_keys
        self._filed = _file_losses(api, writer.losses.records(), self._schema_ids)
        self._synthesized = dict(writer.synthesized_schemas)
        self._readback_keys = dict(writer.readback_keys)
        self._method_id_of = dict(writer.method_ids)
        self._written_schemas = writer.written_schemas
        self._imported = api.format == _DISCOVERY_FORMAT
        self._readback_service = writer.readback_service
        return super().evaluate(api)

    def service_verdicts(self, service: Service) -> List[FidelityVerdict]:
        """A service not named like the document's title does not survive: Discovery describes one API."""
        if service.key == self._readback_service:
            if self._imported:
                return []
            return [FidelityVerdict.approx(
                message="Discovery has no services; the service reads back with only its name and operations",
                severity=LossinessSeverity.INFO,
                target_mapping="service → API",
            )]
        return [FidelityVerdict.drop(
            message=f"Discovery has no services; the operations of {service.name!r} become resources and methods of "
            f"one API, read back as the service {self._readback_service!r}",
            severity=LossinessSeverity.INFO,
            target_mapping=f"service → API {self._readback_service}",
        )]

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """What a re-import of the document has that the source does not: the API's service, the types under
        their schema ids, the operations under their full paths and the body schemas the export makes."""
        out: List[Tuple[str, FidelityVerdict]] = []
        if not any(service.key == self._readback_service for service in api.services):
            out.append((self._readback_service, FidelityVerdict.synth(
                message=f"A Discovery document is one API; it reads back as the service {self._readback_service!r}",
                severity=LossinessSeverity.INFO,
                target_mapping="title → service",
            )))
        source_keys = {type_.key for type_ in api.types}
        for type_key, schema_id in self._schema_ids.items():
            if schema_id != type_key and schema_id not in source_keys:
                out.append((schema_id, FidelityVerdict.synth(
                    message=f"{type_key!r} is written as the schema {schema_id!r} and reads back under that name",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"type → schemas/{schema_id}",
                )))
        operation_keys = {operation.key for operation in api.operations()}
        for operation_key, readback in self._readback_keys.items():
            if readback != operation_key and readback not in operation_keys:
                out.append((readback, FidelityVerdict.synth(
                    message=f"{operation_key!r} reads back as {readback!r}: a Discovery method's path is read with "
                    "its servicePath",
                    severity=LossinessSeverity.INFO,
                    target_mapping="servicePath + path → operation",
                )))
        out.extend(
            (schema_id, FidelityVerdict.synth(
                message=f"The body of {operation_key!r} is not one named type; Discovery bodies are schema references, "
                f"so it is written as the schema {schema_id!r}, which reads back as a type",
                severity=LossinessSeverity.INFO,
                target_mapping=f"body → schemas/{schema_id}",
            ))
            for schema_id, operation_key in self._synthesized.items()
        )
        return out

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        verdicts: List[FidelityVerdict] = []
        # A source that is not a REST API: "Discovery captures REST only", with what is not written (MFX-29.3).
        written = sum(1 for op in api.operations() if _writable(op))
        advisory = rest_only_advisory(api, target_label=self.target_label,
                                      dropped_operations=len(api.operations()) - written, written_operations=written,
                                      written_as="HTTP methods", place="an HTTP method")
        if advisory is not None:
            verdicts.append(advisory)
        if api.format != _DISCOVERY_FORMAT:
            verdicts.append(FidelityVerdict.approx(
                message=f"The {api.format or 'source'} document is written as a Google API Discovery document and "
                "reads back as a Discovery item; details specific to its format are not kept",
                severity=LossinessSeverity.INFO,
                target_mapping="document → Discovery restDescription",
            ))
        return verdicts + self._filed.get(ROOT_CONSTRUCT_KEY, [])

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        verdict = super().operation_verdict(operation)
        if verdict.kind is LossinessKind.OK and not operation.http_method:
            verdict = FidelityVerdict.drop(
                message="Discovery describes HTTP methods only; the operation has no HTTP method and path and is "
                "dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        if verdict.kind is not LossinessKind.OK:
            return [verdict]
        readback = self._readback_keys.get(operation.key, operation.key)
        if readback != operation.key:
            # Under its own key the operation is gone; the re-import has it under `readback`.
            verdict = FidelityVerdict.drop(
                message=f"A Discovery method's path is read with its servicePath; the operation reads back as "
                f"{readback!r}",
                severity=LossinessSeverity.INFO,
                target_mapping=f"{operation.key} → {readback}",
            )
        elif not self._imported and operation.key in self._method_id_of:
            method_id = self._method_id_of[operation.key]
            verdict = FidelityVerdict.approx(
                message=f"The operation is the Discovery method {method_id!r}; it reads back named by that id, with "
                "Discovery's own details in place of its source's",
                severity=LossinessSeverity.INFO,
                target_mapping=f"operation → method {method_id}",
            )
        return _without_ok(verdict, self._filed.get(operation.key, []))

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        if type_.kind is TypeKind.UNION:
            verdict = FidelityVerdict.approx(
                message="Discovery has no unions; the type is written as `type: any`, its alternatives named in "
                "its description",
                target_mapping="union → type: any",
            )
        elif type_.kind is TypeKind.ALIAS:
            verdict = FidelityVerdict.approx(
                message="Discovery has no type aliases; the alias is written as a schema of the type it names and "
                "reads back as that type",
                severity=LossinessSeverity.INFO,
                target_mapping="alias → schema",
            )
        else:
            verdict = super().type_verdict(type_)
        schema_id = self._schema_ids.get(type_.key)
        notes: List[FidelityVerdict] = []
        if schema_id is not None and schema_id != type_.key:
            # The type reads back under its schema id: under its own key it is gone.
            notes.append(FidelityVerdict.drop(
                message=f"Discovery names a schema by its id; {type_.key!r} is written as schemas/{schema_id} and "
                "reads back under that name" + (f", without its namespace {type_.namespace!r}" if type_.namespace
                                               else ""),
                severity=LossinessSeverity.INFO,
                target_mapping=f"{type_.key} → schemas/{schema_id}",
            ))
        if type_.kind is TypeKind.ENUM and any(v.value is not None and v.value != v.name for v in type_.enum_values):
            notes.append(FidelityVerdict.approx(
                message="Discovery lists an enum's values; the names of values written by another value are not kept",
                severity=LossinessSeverity.INFO,
                target_mapping="enum names → dropped",
            ))
        if type_.extras or any(v.extras for v in type_.enum_values):
            notes.append(_details_note(type_.extras or {"enum value details": True}))
        if type_.kind is TypeKind.RECORD and any(
            v.kind is not LossinessKind.OK for f in type_.fields for v in self.field_verdicts(f)
        ):
            notes.append(FidelityVerdict.approx(
                message="Some of the object's properties are written differently; each is listed under its field",
                severity=LossinessSeverity.INFO,
                target_mapping="object → schema (see fields)",
            ))
        return _without_ok(verdict, [*notes, *self._filed.get(type_.key, [])])

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        verdicts = [*super().field_verdicts(field), *self._filed.get(field.key, [])]
        spelling = self._spelling_verdict(field)
        if spelling is not None:
            verdicts.append(spelling)
        if field.extras:
            verdicts.append(_details_note(field.extras))
        return verdicts

    def _nullability_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A non-null field is marked ``required: true``, a hint Discovery readers and clients do not enforce."""
        if field.type.nullable is False:
            return FidelityVerdict.approx(
                message="Discovery marks the property `required: true`, which Discovery clients and readers do not "
                "enforce; it reads back as optional",
                severity=LossinessSeverity.INFO,
                target_mapping="required → required: true (hint)",
            )
        return None

    def _spelling_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A scalar field is written in Discovery's type/format vocabulary and reads back in it.

        An imported Discovery item is already in that vocabulary, so it gets no note.
        """
        if self._imported:
            return None
        owner = next((schema_id for key, schema_id in self._schema_ids.items() if field.key.startswith(key + ".")
                      and field.key[len(key) + 1:] == field.name), None)
        schema = ((self._written_schemas.get(owner or "") or {}).get("properties") or {}).get(field.name) or {}
        ref = field.type
        while ref.is_list() and ref.item is not None and isinstance(schema.get("items"), dict):
            ref, schema = ref.item, schema["items"]
        kind = schema.get("type")
        if "$ref" in schema or kind not in ("string", "integer", "number", "boolean"):
            return None
        written = f"{kind}" + (f", format: {schema['format']}" if schema.get("format") else "")
        if (ref.name or "") == kind and not schema.get("format"):
            return None
        return FidelityVerdict.approx(
            message=f"Discovery writes the value as `type: {written}`; it reads back in Discovery's vocabulary",
            severity=LossinessSeverity.INFO,
            target_mapping=f"{ref.name or 'value'} → {written}",
        )


class DiscoveryEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Google API Discovery REST description."""

    key = "discovery"
    format = "discovery"
    label = "Google API Discovery"
    description = "Export as a Google API Discovery document (resources, methods, parameters and schemas)."
    icon = "radar"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = DiscoveryEmitOptions
    #: A Discovery document describes HTTP methods and schemas; a source with neither has nothing to write.
    requires_source = ("http-operation-or-type",)

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return DiscoveryFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[DiscoveryEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, DiscoveryEmitOptions)
            else DiscoveryEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _DiscoveryWriter(api, options)
        document = writer.render()
        indent = options.indent or None
        content = json.dumps(document, indent=indent, ensure_ascii=False) + "\n"
        return EmitResult(
            files=[EmittedFile(path=f"{document['name']}.discovery.json", content=content,
                               media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


@dataclass
class _Resource:
    """One Discovery resource: its methods (name → method) and child resources."""

    methods: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    resources: Dict[str, "_Resource"] = field(default_factory=dict)

    def as_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.methods:
            out["methods"] = self.methods
        if self.resources:
            out["resources"] = {name: child.as_json() for name, child in self.resources.items()}
        return out


class _DiscoveryWriter:
    """Build one Discovery document for ``api``; every loss goes to :attr:`losses`."""

    def __init__(self, api: CanonicalApi, options: DiscoveryEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.schema_writer = DiscoverySchemaWriter(api, self.losses)
        self._imported = api.format == _DISCOVERY_FORMAT
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._method_ids: set = set()
        #: Body schemas the export makes (schema id → the operation whose body it is).
        self.synthesized_schemas: Dict[str, str] = {}
        #: Operation key → the key a re-import of the document gives it (``servicePath`` + ``path``).
        self.readback_keys: Dict[str, str] = {}
        #: Operation key → the id of the method it is written as.
        self.method_ids: Dict[str, str] = {}
        #: The service a re-import names after the document's title.
        self.readback_service = ""
        #: The document's ``schemas`` once rendered (schema id → schema).
        self.written_schemas: Dict[str, Dict[str, Any]] = {}

    def render(self) -> Dict[str, Any]:
        """The Discovery document, as a JSON object.

        Raises:
            EmitPreconditionError: When the source has no HTTP operation and no type.
        """
        if not self._api.types and not any(op.http_method and op.http_path for op in self._api.operations()):
            raise EmitPreconditionError(
                "Google API Discovery export needs at least one HTTP operation or one type; this source has neither."
            )
        name = self._name()
        version = self._options.version or self._api.version or _DEFAULT_VERSION
        root_url, service_path = self._urls()
        document: Dict[str, Any] = {
            "kind": _KIND,
            "discoveryVersion": "v1",
            "id": f"{name}:{version}",
            "name": name,
            "version": version,
        }
        title = self._api.title or self._api.identity.name
        if title:
            document["title"] = title
        self.readback_service = title or name
        if self._api.description:
            document["description"] = self._api.description
        link = self._api.extras.get("discovery_documentation_link") if self._imported else None
        if link:
            document["documentationLink"] = link
        document.update({
            "protocol": "rest",
            "rootUrl": root_url,
            "servicePath": service_path,
            "baseUrl": root_url + service_path,
            "basePath": "/" + service_path,
        })
        self._schemas = self.schema_writer.schemas()
        self.written_schemas = self._schemas
        for type_ in self._api.types:
            self.tracker.record(type_.key, Provenance.SOURCE)
        root = _Resource()
        for operation in self._operations():
            self._file_method(root, name, service_path, operation)
        self._document_details()
        if self._schemas:
            document["schemas"] = self._schemas
        tree = root.as_json()
        if tree.get("methods"):
            document["methods"] = tree["methods"]
        if tree.get("resources"):
            document["resources"] = tree["resources"]
        for channel in self._api.channels:
            self.losses.record(LossKind.NA, "channels-dropped",
                               "Discovery describes HTTP methods only; event channels are not written.",
                               pointer=channel.key)
        return document

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def _name(self) -> str:
        """The API ``name``: the option, an imported item's own, else made from the item's name."""
        if self._options.name:
            return self._options.name
        own = self._api.extras.get("discovery_name") if self._imported else None
        if isinstance(own, str) and _NAME.match(own):
            return own
        source = self._api.identity.name or self._api.title or ""
        made = re.sub(r"[^a-z0-9]", "", source.lower()).lstrip("0123456789") or "api"
        self.losses.record(LossKind.INFERRED, "name-synthesized",
                           f"A Discovery name is lower-case letters and digits; the API is named {made!r}"
                           + (f" from {source!r}." if source else "."), pointer="")
        return made

    def _urls(self) -> Tuple[str, str]:
        """``(rootUrl, servicePath)`` from the first server (``{variables}`` replaced by their defaults)."""
        servers = self._api.servers
        if len(servers) > 1:
            self.losses.record(LossKind.NA, "servers-dropped",
                               f"Discovery has one rootUrl; {servers[0].url!r} is used and {len(servers) - 1} "
                               "other server(s) are not written.", pointer="servers")
        url = servers[0].url if servers else ""
        if servers:
            for variable in servers[0].variables:
                if variable.default is not None:
                    url = url.replace("{" + variable.name + "}", variable.default)
        parts = urlsplit(url)
        path = parts.path.strip("/")
        own = self._api.extras.get("discovery_service_path") if self._imported else None
        if isinstance(own, str) and own.strip("/") and not path:
            # An imported item whose baseUrl names only the host keeps its own servicePath.
            path = own.strip("/")
            self.losses.record(LossKind.INFERRED, "base-url-completed",
                               f"The item's baseUrl {url!r} leaves out its servicePath {own!r}; the export writes "
                               f"baseUrl as rootUrl + servicePath, so the server reads back as "
                               f"{urlsplit(url).scheme}://{urlsplit(url).netloc}/{path}/.", pointer="servers")
        service_path = f"{path}/" if path else ""
        if parts.scheme in ("http", "https") and parts.netloc and "{" not in url:
            return f"{parts.scheme}://{parts.netloc}/", service_path
        self.losses.record(LossKind.INFERRED, "root-url-synthesized",
                           f"A Discovery document needs an absolute rootUrl and the source has "
                           f"{'none' if not url else f'only {url!r}'}; {_DEFAULT_ROOT!r} is used.", pointer="servers")
        return _DEFAULT_ROOT, "" if "{" in path else service_path

    def _document_details(self) -> None:
        """What of the document Discovery has no place for: other services' grouping, source details."""
        if self._imported:
            return
        extras = sorted(set(self._api.extras) - _DISCOVERY_API_EXTRAS)
        if extras:
            self.losses.record(LossKind.NA, "document-details-dropped",
                               f"Discovery: source-specific details ({', '.join(extras)}) are not written.",
                               pointer="")

    # ------------------------------------------------------------------
    # Methods
    # ------------------------------------------------------------------

    def _operations(self) -> List[Operation]:
        """The operations Discovery can carry; events and operations with no HTTP binding are reported."""
        kept: List[Operation] = []
        for operation in self._api.operations():
            if operation.kind in _EVENT_OPERATION_KINDS:
                self.losses.record(LossKind.NA, "event-operation-dropped",
                                   f"Operation {operation.key!r} is an event; Discovery has no representation for "
                                   "it.", pointer=operation.key)
            elif not _writable(operation):
                self.losses.record(LossKind.NA, "operation-without-http-binding",
                                   f"Operation {operation.key!r} has no HTTP method and path; Discovery describes "
                                   "HTTP methods only, so it is not written.", pointer=operation.key)
            else:
                kept.append(operation)
        return kept

    def _file_method(self, root: _Resource, api_name: str, service_path: str, operation: Operation) -> None:
        """Write ``operation`` as a method of its resource (created as needed)."""
        resource_path, method_name = self._placement(operation)
        node = root
        for segment in resource_path:
            node = node.resources.setdefault(segment, _Resource())
        name = method_name
        suffix = 2
        while name in node.methods:
            name = f"{method_name}{suffix}"
            suffix += 1
        if name != method_name:
            self.losses.record(LossKind.INFERRED, "method-renamed",
                               f"Another method of the resource is named {method_name!r}; {operation.key!r} is "
                               f"written as {name!r}.", pointer=operation.key)
        node.methods[name] = self._method(operation, api_name, resource_path, name, service_path)

    def _placement(self, operation: Operation) -> Tuple[List[str], str]:
        """``(resource path, method name)``: an imported item's own, else from the path and operation name."""
        extras = operation.extras
        if self._imported and extras.get("discovery_method"):
            path = str(extras.get("discovery_resource_path") or "")
            return [segment for segment in path.split("/") if segment], str(extras["discovery_method"])
        literal = next((s for s in (operation.http_path or "").split("/") if s and "{" not in s), None)
        first = next((s for s in (operation.http_path or "").split("/") if s), None)
        resource = [identifier(literal, fallback="resource")] if literal is not None and first == literal else []
        verb = (operation.http_method or "call").lower()
        method = identifier(operation.name, fallback=verb) if operation.name and " " not in operation.name else (
            identifier(f"{verb} {literal or ''}", fallback=verb))
        if not operation.name or " " in operation.name:
            self.losses.record(LossKind.INFERRED, "method-renamed",
                               f"The operation has no name of its own; it is the Discovery method {method!r}"
                               + (f" of the resource {resource[0]!r}." if resource else "."), pointer=operation.key)
        return resource, method

    def _method(self, operation: Operation, api_name: str, resource_path: List[str], name: str,
                service_path: str) -> Dict[str, Any]:
        own_id = operation.extras.get("discovery_id") if self._imported else None
        method_id = str(own_id) if own_id else ".".join([api_name, *resource_path, name])
        base_id, suffix = method_id, 2
        while method_id in self._method_ids:
            method_id = f"{base_id}{suffix}"
            suffix += 1
        self._method_ids.add(method_id)
        self.method_ids[operation.key] = method_id
        path, renames = self._path(operation, service_path)
        method: Dict[str, Any] = {"id": method_id, "path": path, "httpMethod": operation.http_method.upper()}
        readback = path if path.startswith("/") else "/" + service_path + path
        self.readback_keys[operation.key] = f"{operation.http_method.upper()} {readback.rstrip('/') or '/'}"
        if operation.description:
            method["description"] = operation.description
        if operation.deprecated:
            method["deprecated"] = True
        parameters = self._parameters(operation, renames, path)
        if parameters:
            method["parameters"] = parameters
            order = [p for p, s in parameters.items() if s.get("location") == "path"]
            order += [p for p, s in parameters.items() if s.get("location") == "query" and s.get("required")]
            if order:
                method["parameterOrder"] = order
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None and (request.payload is not None or request.payload_schema):
            method["request"] = {"$ref": self._body_schema(operation, name, request, "Request")}
        response = self._response(operation, name)
        if response is not None:
            method["response"] = response
        extras = sorted(set(operation.extras) - _DISCOVERY_OPERATION_EXTRAS)
        if extras:
            self.losses.record(LossKind.NA, "operation-details-dropped",
                               f"Discovery carries a method's HTTP surface only; {operation.key!r} loses its "
                               f"source-specific details ({', '.join(extras)}).", pointer=operation.key)
        self.tracker.record(operation.key, Provenance.SOURCE)
        return method

    def _path(self, operation: Operation, service_path: str) -> Tuple[str, Dict[str, str]]:
        """The method ``path`` (relative to ``servicePath``) and the path parameters renamed in it.

        An imported Discovery item's path includes its ``servicePath``, which is taken off (a path outside it
        stays absolute, as Discovery allows); any other source's path is already relative to its server.
        """
        path = operation.http_path or "/"
        prefix = "/" + service_path
        if self._imported and service_path and path.startswith(prefix):
            path = path[len(prefix):]
        elif not self._imported or not service_path:
            path = path.lstrip("/")
        renames: Dict[str, str] = {}
        for raw in _TEMPLATE_VARIABLE.findall(path):
            if not _PATH_PARAMETER_NAME.match(raw):
                new = identifier(raw, fallback="param")
                renames[raw] = new
                path = path.replace("{" + raw + "}", "{" + new + "}").replace("{+" + raw + "}", "{+" + new + "}")
                self.losses.record(LossKind.INFERRED, "parameter-renamed",
                                   f"A Discovery path variable is letters, digits and '_'; {raw!r} of "
                                   f"{operation.key!r} is written as {new!r}.", pointer=operation.key)
        return path, renames

    def _parameters(self, operation: Operation, renames: Dict[str, str], path: str) -> Dict[str, Dict[str, Any]]:
        """``parameters``: the path and query parameters, by name."""
        out: Dict[str, Dict[str, Any]] = {}
        in_path = set(_TEMPLATE_VARIABLE.findall(path))
        for param in operation.parameters:
            if param.location not in (ParameterLocation.PATH, ParameterLocation.QUERY):
                self.losses.record(LossKind.NA, "parameter-dropped",
                                   f"Discovery parameters go in the path or the query; the {param.location.value} "
                                   f"parameter {param.name!r} of {operation.key!r} is not written.",
                                   pointer=operation.key)
                continue
            name = renames.get(param.name, param.name)
            location = param.location.value
            if location == "path" and name not in in_path:
                self.losses.record(LossKind.NA, "parameter-dropped",
                                   f"The path of {operation.key!r} does not name the path parameter "
                                   f"{param.name!r}; it is not written.", pointer=operation.key)
                continue
            out[name] = self._parameter(operation, param, location)
            self.tracker.record(param.key, Provenance.SOURCE)
        for variable in sorted(in_path - set(out)):
            # A path variable the source declares no parameter for: a required string, so the path expands.
            out[variable] = {"type": "string", "location": "path", "required": True}
            self.losses.record(LossKind.INFERRED, "path-parameter-required",
                               f"The path of {operation.key!r} names {variable!r}, which the source declares no "
                               "parameter for; it is written as a required string path parameter.",
                               pointer=operation.key)
        return out

    def _parameter(self, operation: Operation, param: Parameter, location: str) -> Dict[str, Any]:
        """One parameter: ``type`` / ``format`` (``repeated`` for a list), its facets, ``location``, ``required``."""
        pointer = operation.key
        ref = param.type
        repeated = ref.is_list()
        item = ref.item if repeated and ref.item is not None else ref
        schema = self.schema_writer.ref_schema(item, pointer)
        schema_id = schema.pop("$ref", None)
        if schema_id is not None:
            target = self._schemas.get(schema_id, {})
            if target.get("type") in ("string", "integer", "number", "boolean") and "properties" not in target:
                # An enum or scalar type: its values are written in place (a parameter cannot `$ref`).
                schema = {k: v for k, v in target.items() if k not in ("id", "description")} | schema
            else:
                self.losses.record(LossKind.INFERRED, "parameter-as-string",
                                   f"A Discovery parameter is a scalar; {param.name!r} of {operation.key!r} has the "
                                   f"type {schema_id!r} and is written as a string.", pointer=pointer)
                schema = {"type": "string"}
        if schema.get("type") in (None, "any", "object", "array"):
            schema["type"] = "string"
            schema.pop("items", None)
            schema.pop("properties", None)
            schema.pop("additionalProperties", None)
        out: Dict[str, Any] = {"type": schema.pop("type")}
        if "format" in schema:
            out["format"] = schema.pop("format")
        if param.description:
            out["description"] = param.description
        own_enum = param.extras.get("discovery_enum") if self._imported else None
        if isinstance(own_enum, list) and own_enum:
            # An imported Discovery parameter keeps its allowed values in `discovery_enum`.
            schema.setdefault("enum", [str(value) for value in own_enum])
        constraints = param.constraints
        if constraints is not None:
            if constraints.enum and all(isinstance(v, str) for v in constraints.enum):
                schema.setdefault("enum", list(constraints.enum))
            if constraints.pattern:
                schema.setdefault("pattern", constraints.pattern)
            for bound, value in (("minimum", constraints.minimum), ("maximum", constraints.maximum)):
                if value is not None:
                    schema.setdefault(bound, str(int(value)) if float(value).is_integer() else str(value))
        for keyword in ("enum", "enumDescriptions", "pattern", "minimum", "maximum"):
            if keyword in schema:
                out[keyword] = schema[keyword]
        if param.default is not None and not isinstance(param.default, (dict, list)):
            default = param.default
            out["default"] = str(default).lower() if isinstance(default, bool) else str(default)
        out["location"] = location
        required = param.required or location == "path"
        if location == "path" and not param.required:
            self.losses.record(LossKind.INFERRED, "path-parameter-required",
                               f"A Discovery path parameter is required; {param.name!r} of {operation.key!r} is "
                               "written required.", pointer=pointer)
        if required:
            out["required"] = True
        if repeated:
            out["repeated"] = True
        if param.deprecated:
            out["deprecated"] = True
        return out

    def _body_schema(self, operation: Operation, method: str, message: Message, role: str) -> str:
        """The schema id a body ``$ref``s: its named type's, else a schema made for it."""
        if message.payload is not None:
            schema_id = self.schema_writer.schema_id(message.payload)
            if schema_id is not None:
                return schema_id
            body = self.schema_writer.ref_schema(message.payload, message.key)
        else:
            body = self.schema_writer.raw_schema(message.payload_schema or {}, message.key)
        base = identifier(method, fallback="method")
        candidate = f"{base[:1].upper()}{base[1:]}{role}"
        schema_id, suffix = candidate, 2
        while schema_id in self._schemas:
            schema_id = f"{candidate}{suffix}"
            suffix += 1
        self._schemas[schema_id] = {"id": schema_id, **body}
        self.synthesized_schemas[schema_id] = operation.key
        self.losses.record(LossKind.INFERRED, "body-schema-synthesized",
                           f"A Discovery body is a schema reference; the {role.lower()} body of {operation.key!r} "
                           f"is not one named type and is written as the schema {schema_id!r}.",
                           pointer=operation.key)
        return schema_id

    def _response(self, operation: Operation, method: str) -> Optional[Dict[str, str]]:
        """The method's ``response``: the first success body; every other response body is reported."""
        responses = [m for m in operation.messages if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)]
        with_body = [m for m in responses if m.payload is not None or m.payload_schema]
        success = [m for m in with_body if m.role is MessageRole.RESPONSE and _is_success(m)]
        chosen = success[0] if success else None
        for message in with_body:
            if message is not chosen:
                self.losses.record(LossKind.NA, "response-dropped",
                                   f"A Discovery method has one response body; the {_status(message) or 'other'} "
                                   f"body of {operation.key!r} is not written.", pointer=operation.key)
        if chosen is None:
            return None
        return {"$ref": self._body_schema(operation, method, chosen, "Response")}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _details_note(extras: Mapping[str, Any]) -> FidelityVerdict:
    """Source-specific details Discovery has no place for."""
    return FidelityVerdict.approx(
        message=f"Discovery: source-specific details ({', '.join(sorted(extras))}) are not written",
        severity=LossinessSeverity.INFO,
        target_mapping="details → dropped",
    )


def _without_ok(verdict: FidelityVerdict, filed: List[FidelityVerdict]) -> List[FidelityVerdict]:
    """``verdict`` and the losses filed under its construct; an ``OK`` is left out when a loss says otherwise."""
    if verdict.kind is LossinessKind.OK and filed:
        return list(filed)
    return [verdict, *filed]


def _writable(operation: Operation) -> bool:
    """Whether the Discovery export writes ``operation``: an HTTP operation (method and path), not an event."""
    return (operation.kind not in _EVENT_OPERATION_KINDS and bool(operation.http_method)
            and bool(operation.http_path))


def _status(message: Message) -> Optional[str]:
    return str(message.status_code or message.extras.get("http_status") or "") or None


def _is_success(message: Message) -> bool:
    """A response without a status, or with a ``2xx`` one, is the success body."""
    status = _status(message)
    return status is None or bool(_SUCCESS.match(status)) or status.upper() == "2XX"


def _file_losses(
    api: CanonicalApi, losses: List[Loss], schema_ids: Mapping[str, str]
) -> Dict[str, List[FidelityVerdict]]:
    """Each writer loss as a verdict, filed under the construct its pointer is in (else the root).

    ``#/schemas/<id>/properties/<name>/…`` is a field, ``#/schemas/<id>/…`` a type; an operation, parameter or
    message key is its operation.
    """
    owners: Dict[str, Tuple[str, Dict[str, str]]] = {}
    for type_ in api.types:
        schema_id = schema_ids.get(type_.key)
        if schema_id is not None:
            owners[schema_id] = (type_.key, {f.name: f.key for f in type_.fields})
    operation_of: Dict[str, str] = {}
    for operation in api.operations():
        operation_of[operation.key] = operation.key
        for param in operation.parameters:
            operation_of[param.key] = operation.key
        for message in operation.messages:
            operation_of[message.key] = operation.key
    filed: Dict[str, List[FidelityVerdict]] = {}
    seen = set()
    for loss in losses:
        if (loss.subject, loss.detail) in seen:
            continue
        seen.add((loss.subject, loss.detail))
        pointer = loss.pointer or ""
        key = operation_of.get(pointer) or _schema_construct(pointer, owners)
        severity = LossinessSeverity.INFO if loss.subject in _INFO_SUBJECTS else LossinessSeverity.WARN
        if loss.subject in _SYNTH_SUBJECTS:
            verdict = FidelityVerdict.synth(message=loss.detail, severity=severity, target_mapping=loss.subject)
        elif loss.kind is LossKind.NA:
            verdict = FidelityVerdict.drop(message=loss.detail, severity=severity, target_mapping=loss.subject)
        else:
            verdict = FidelityVerdict.approx(message=loss.detail, severity=severity, target_mapping=loss.subject)
        filed.setdefault(key, []).append(verdict)
    return filed


def _schema_construct(pointer: str, owners: Mapping[str, Tuple[str, Dict[str, str]]]) -> str:
    """The type or field a ``#/schemas/…`` pointer is in, else the root."""
    parts = pointer.split("/")
    if len(parts) < 3 or parts[1] != "schemas" or parts[2] not in owners:
        return ROOT_CONSTRUCT_KEY
    type_key, fields = owners[parts[2]]
    if len(parts) >= 5 and parts[3] == "properties" and parts[4] in fields:
        return fields[parts[4]]
    return type_key
