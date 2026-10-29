"""OData emitter: canonical model → CSDL JSON 4.01 (and CSDL XML) — MFX-16.1 (#3897).

The inverse of :class:`app.odata_normalizer.ODataNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The writer builds the service metadata once as **CSDL JSON**, the
canonical form (OASIS *OData CSDL JSON Representation 4.01*), and option ``output`` also renders it as
CSDL XML (``.edmx``) from that same model. Each export is checked against the OASIS CSDL JSON schema (or
the EDMX / EDM XML schemas) and read back by the OData importer (:func:`validate_odata_document`).

* **Types** — a record becomes an ``EntityType`` when it is a resource (the payload of an HTTP operation,
  or an entity in an OData source) and a ``ComplexType`` otherwise. **Every entity type has a ``$Key``**: an
  OData source's own key, else an id-like property (``id``, ``<Type>Id``, ``key``; reported as inferred),
  else a synthesized ``Id`` property (reported as synthesized). Enums are ``EnumType``\\ s with integer
  values; a named scalar or an alias of one is a ``TypeDefinition``. Unions become complex types with one
  nullable property per variant, maps open complex types (both reported).
* **Properties** — primitives are coerced to their CSDL type (``int64`` → ``Edm.Int64``, ``date-time`` →
  ``Edm.DateTimeOffset``, ``uuid`` → ``Edm.Guid``; an unsigned type widens, an unknown one is
  ``Edm.String``, both reported); lists are ``$Collection``; a property typed as an entity type is a
  ``NavigationProperty``. ``maxLength`` is ``$MaxLength`` and a default ``$DefaultValue``; the other
  constraints are ``Validation`` vocabulary annotations, descriptions ``Core.Description`` and
  deprecations ``Core.Revisions``.
* **Operations** — CRUD operations on a resource (``GET /pets``, ``GET /pets/{id}``, ``POST /pets``,
  ``PUT`` / ``PATCH`` / ``DELETE /pets/{id}``) are served by its **entity set**; every other operation
  becomes an unbound **Function** (a ``GET`` or query with a result) or **Action**, with an import in the
  entity container. Events are dropped; a stream is one call.

Whatever cannot be carried is reported as a :class:`~app.emitter.Loss`; the fidelity pack
(:class:`ODataFidelityRulePack`) predicts exactly those losses.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
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
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity
from .scalar_aliases import scalar_kind
from .writer_loss_rulepack import WriterLossRulePack

__all__ = ["ODataEmitOptions", "ODataEmitter", "ODataFidelityRulePack", "edm_type", "validate_odata_document"]

_EDMX_NS = "http://docs.oasis-open.org/odata/ns/edmx"
_EDM_NS = "http://docs.oasis-open.org/odata/ns/edm"
_CORE = "https://oasis-tcs.github.io/odata-vocabularies/vocabularies/Org.OData.Core.V1.json"
_VALIDATION = "https://oasis-tcs.github.io/odata-vocabularies/vocabularies/Org.OData.Validation.V1.json"

#: Scalar kind (:func:`app.scalar_aliases.scalar_kind`) → CSDL primitive, and whether it is exact.
_EDM_FOR_KIND: Dict[str, Tuple[str, bool]] = {
    "bool": ("Edm.Boolean", True), "int8": ("Edm.SByte", True), "int16": ("Edm.Int16", True),
    "int32": ("Edm.Int32", True), "int64": ("Edm.Int64", True), "uint8": ("Edm.Byte", True),
    "uint16": ("Edm.Int32", False), "uint32": ("Edm.Int64", False), "uint64": ("Edm.Decimal", False),
    "float": ("Edm.Single", True), "double": ("Edm.Double", True), "string": ("Edm.String", True),
    "bytes": ("Edm.Binary", True),
}
#: Canonical spellings (lower-cased) the kind table does not cover.
_EXTRA_EDM: Dict[str, str] = {
    "decimal": "Edm.Decimal", "bigdecimal": "Edm.Decimal", "biginteger": "Edm.Decimal",
    "datetime": "Edm.DateTimeOffset",
    "date-time": "Edm.DateTimeOffset", "timestamp": "Edm.DateTimeOffset", "instant": "Edm.DateTimeOffset",
    "utcdatetime": "Edm.DateTimeOffset", "offsetdatetime": "Edm.DateTimeOffset", "date": "Edm.Date",
    "plaindate": "Edm.Date", "time": "Edm.TimeOfDay", "plaintime": "Edm.TimeOfDay", "duration": "Edm.Duration",
    "uuid": "Edm.Guid", "guid": "Edm.Guid", "any": "Edm.Untyped", "object": "Edm.Untyped", "json": "Edm.Untyped",
    "document": "Edm.Untyped", "unknown": "Edm.Untyped", "map": "Edm.Untyped", "dict": "Edm.Untyped",
}
#: A string ``format`` with a CSDL type of its own.
_STRING_FORMATS: Dict[str, str] = {
    "date-time": "Edm.DateTimeOffset", "date": "Edm.Date", "time": "Edm.TimeOfDay", "duration": "Edm.Duration",
    "uuid": "Edm.Guid", "byte": "Edm.Binary", "binary": "Edm.Binary",
}
#: ``format`` values a CSDL type carries (they pick the Edm type, so they are not lost).
_CONSUMED_FORMATS = frozenset(_STRING_FORMATS) | {"int8", "int16", "int32", "int64", "uint8", "float", "double",
                                                  "decimal"}
#: Spellings that are text without loss.
_STRING_LIKE = frozenset({"id", "email", "uri", "url", "hostname", "ipv4", "ipv6", "char", "text", "str"})
_NUMERIC = frozenset({"Edm.Byte", "Edm.SByte", "Edm.Int16", "Edm.Int32", "Edm.Int64", "Edm.Single", "Edm.Double",
                      "Edm.Decimal"})
_EVENT_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
#: v2/v3 primitives v4 removed, and their v4 replacement.
_LEGACY_EDM = {"Edm.DateTime": "Edm.DateTimeOffset", "Edm.Time": "Edm.TimeOfDay"}
#: v2/v3 source annotations written back as CSDL facets.
_FACET_ANNOTATIONS = {"MaxLength": "$MaxLength", "Precision": "$Precision", "Scale": "$Scale"}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class ODataFidelityRulePack(WriterLossRulePack):
    """Fidelity rules for OData export — MFX-16.1 (#3897).

    The pack builds the metadata with the OData writer and turns each loss the writer records into a
    verdict on the construct it concerns (:class:`~app.writer_loss_rulepack.WriterLossRulePack`): a key
    synthesized for an entity is ``SYNTH``; an inferred key, an operation reframed as a Function or Action, a
    CRUD operation served by an entity set, a coerced or widened primitive, a union or map approximated as a
    complex type and a renamed element are ``APPROX``; events, channels, headers and cookies, error
    responses, constraints without a CSDL form and the document's servers are ``DROP``. A carried type or
    operation is ``OK`` and its ``target_mapping`` names what it became (``EntityType Pet``,
    ``Function search``, ``entity set Pets (read)``).

    MFX-16.2 (#3898) — the epic's three loss classes:

    * **Keyless types** — an entity with no key gets one: an id-like property (``APPROX``, made non-nullable
      when it was nullable) or a synthesized ``Id`` (``SYNTH``); a record that is not a resource is a
      complex type and needs none.
    * **RPC and event DROP** — a unary RPC is an Action (or a Function for a query with a result,
      ``APPROX``); a client / bidirectional stream and a GraphQL subscription have no OData form (critical
      ``DROP``); a server stream is a result returning a collection (``APPROX``); publish / subscribe
      operations and channels are ``DROP``.
    * **Type coercion** — a primitive without a CSDL type (unsigned widened, unknown as ``Edm.String``) is an
      ``APPROX``; a ``format`` no CSDL type carries (``email``, ``uri``) and a constraint with no facet or
      ``Validation`` term (``minLength``, ``multipleOf``, ``uniqueItems``) are ``DROP``.
    """

    target_label = "OData"
    critical_drops = frozenset({"event-operation-dropped", "stream-dropped", "unsupported-type"})
    info_drops = frozenset({"errors-dropped", "servers-dropped", "version-dropped", "title-dropped"})
    cosmetic = frozenset({"renamed-element"})
    synthesized = frozenset({"key-synthesized"})

    def build_writer(self, api: CanonicalApi) -> "_ODataWriter":
        """Build the metadata (default options: they change no loss)."""
        writer = _ODataWriter(api, ODataEmitOptions())
        writer.build()
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A non-OData document rewritten as service metadata, agents, and losses with no construct."""
        verdicts: List[FidelityVerdict] = []
        if api.format != "odata":
            verdicts.append(FidelityVerdict.approx(
                message=f"The document is written as OData service metadata in the namespace "
                f"{self._writer.namespace!r} and reads back as an OData REST API",
                severity=LossinessSeverity.INFO,
                target_mapping=f"document → CSDL {self._writer.namespace}",
            ))
        if api.agents:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
                target_mapping="agents → dropped",
            ))
        return verdicts + self.loss_verdicts(ROOT_CONSTRUCT_KEY)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The writer's losses for the property, plus a dropped field number (CSDL properties have none)."""
        identity = self._field_identity_verdict(field)
        return self.loss_verdicts(field.key) + ([identity] if identity is not None else [])


class ODataEmitOptions(EmitOptions):
    """Per-target options for :class:`ODataEmitter`."""

    output: Literal["json", "xml", "both"] = Field(
        default="json",
        description="`json` writes CSDL JSON 4.01 (`<Namespace>.csdl.json`, the canonical form); `xml` writes "
        "CSDL XML (`<Namespace>.edmx`); `both` writes the two — two views of one model.",
    )
    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the CSDL XML document.",
    )


class ODataEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as OData v4 service metadata (CSDL JSON, and optionally CSDL XML)."""

    key = "odata"
    format = "odata"
    label = "OData"
    description = "Export as OData v4 service metadata: CSDL JSON 4.01, optionally CSDL XML (.edmx)."
    icon = "database"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = ODataEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"
    XML_MEDIA_TYPE = "application/xml"

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
        return ODataFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ODataEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ODataEmitOptions)
            else ODataEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ODataWriter(api, options)
        writer.build()
        if not writer.has_members():
            raise EmitPreconditionError(
                "OData export needs at least one type or operation to describe; this source has neither."
            )
        files: List[EmittedFile] = []
        if options.output in ("json", "both"):
            files.append(EmittedFile(path=f"{writer.base_name}.csdl.json",
                                     content=json.dumps(writer.document, indent=2, ensure_ascii=False) + "\n",
                                     media_type=self.OUTPUT_MEDIA_TYPE))
        if options.output in ("xml", "both"):
            files.append(EmittedFile(path=f"{writer.base_name}.edmx", content=writer.render_xml(),
                                     media_type=self.XML_MEDIA_TYPE))
        return EmitResult(
            files=files,
            media_type=files[0].media_type,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


def edm_type(name: Optional[str], fmt: Optional[str] = None) -> Tuple[str, bool]:
    """The CSDL primitive for a canonical scalar spelling, and whether the mapping is exact.

    Args:
        name: The canonical spelling (``i64``, ``integer``, ``timestamp``, ``Edm.Guid``).
        fmt: The ``format`` constraint, which picks a number's width or a string's CSDL type.

    Returns:
        ``(Edm type, exact)``; an unknown spelling is ``("Edm.String", False)``.
    """
    if not name:
        return "Edm.String", True
    if name.startswith("Edm."):
        return name, True
    lowered = name.lower()
    hint = (fmt or "").lower()
    if lowered in ("string", "str", "text") and hint in _STRING_FORMATS:
        return _STRING_FORMATS[hint], True
    kind = scalar_kind(name, fmt)
    if kind is not None:
        return _EDM_FOR_KIND[kind]
    if lowered in _EXTRA_EDM:
        return _EXTRA_EDM[lowered], True
    if lowered in _STRING_LIKE:
        return "Edm.String", True
    return "Edm.String", False


# ===========================================================================
# Writer
# ===========================================================================


class _Scope:
    """Names declared in one CSDL scope (a namespace, a structured type, the container)."""

    def __init__(self) -> None:
        self._taken: Set[str] = set()

    def claim(self, name: Optional[str], fallback: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_]+", "_", name or "").strip("_") or fallback
        if base[0].isdigit():
            base = f"_{base}"
        base = base[:120]
        candidate, suffix = base, 2
        while candidate in self._taken:
            candidate, suffix = f"{base}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate


class _ODataWriter:
    """Build the CSDL JSON document (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: ODataEmitOptions) -> None:
        self._api = api
        self._options = options
        self._odata_source = api.format == "odata"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._schemas_extras = [s for s in (api.extras.get("odata_schemas") or []) if isinstance(s, dict)] \
            if self._odata_source else []
        self.namespace = _namespace(api, self._schemas_extras)
        self.base_name = self.namespace
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)
        self._scope = _Scope()
        #: Field key → its property name.
        self._prop_names: Dict[str, str] = {}
        #: Type key → declared name, and the CSDL kind it is written as.
        self._names: Dict[str, str] = {}
        self._kinds: Dict[str, str] = {}
        self._written: Dict[str, str] = {}
        self._vocabularies: Set[str] = set()
        self._context: Optional[str] = None
        self.document: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Classify and name the types, write them, then the operations and the container."""
        resources = self._resource_types()
        for type_ in self._api.types:
            name = self._scope.claim(type_.name, "Type")
            if name != type_.name:
                self.losses.record(LossKind.INFERRED, "renamed-element",
                                   f"CSDL names are simple identifiers unique in their namespace; {type_.name!r} is "
                                   f"written as {name!r}.", pointer=type_.key)
            self._names[type_.key] = name
            self._kinds[type_.key] = self._kind_of(type_, resources)
        schema: Dict[str, Any] = {}
        for type_ in self._api.types:
            self._context = type_.key
            member = self._type_member(type_)
            if member is not None:
                schema[self._names[type_.key]] = member
        container_name = self._container_name()
        container: Dict[str, Any] = {"$Kind": "EntityContainer"}
        sets = self._entity_sets(container)
        container_scope = _Scope()
        for name in container:
            if not name.startswith("$"):
                container_scope.claim(name, "Set")
        for service in self._api.services:
            for operation in service.operations:
                self._context = operation.key
                self._operation(operation, sets, schema, container, container_scope)
        self._context = None
        schema[container_name] = container
        self._document_losses()
        version = self._version(schema)
        document: Dict[str, Any] = {"$Version": version, "$EntityContainer": f"{self.namespace}.{container_name}"}
        references = {}
        if "Core" in self._vocabularies:
            references[_CORE] = {"$Include": [{"$Namespace": "Org.OData.Core.V1", "$Alias": "Core"}]}
        if "Validation" in self._vocabularies:
            references[_VALIDATION] = {"$Include": [{"$Namespace": "Org.OData.Validation.V1", "$Alias": "Validation"}]}
        if references:
            document["$Reference"] = references
        document[self.namespace] = schema
        self.document = document

    def has_members(self) -> bool:
        """Whether the metadata declares any type or operation."""
        schema = self.document.get(self.namespace, {})
        container = next((v for v in schema.values() if isinstance(v, dict) and v.get("$Kind") == "EntityContainer"),
                         {})
        return len(schema) > 1 or any(not k.startswith("$") for k in container)

    def written_as(self, key: str) -> Optional[str]:
        """What the type or operation ``key`` became, or ``None``."""
        return self._written.get(key)

    def _version(self, schema: Dict[str, Any]) -> str:
        """``4.0`` for an OData 4.0 source that uses nothing newer, else ``4.01`` (``Edm.Untyped`` is 4.01)."""
        declared = self._api.extras.get("odata_version") if self._odata_source else None
        return "4.0" if declared == "4.0" and "Edm.Untyped" not in json.dumps(schema) else "4.01"

    def _container_name(self) -> str:
        for schema in self._schemas_extras:
            container = schema.get("entity_container")
            if isinstance(container, dict) and container.get("name"):
                return self._scope.claim(str(container["name"]), "Container")
        return self._scope.claim("Container", "Container")

    def _document_losses(self) -> None:
        api = self._api
        if self._odata_source:
            declared = str(api.extras.get("odata_version") or "")
            if declared and not declared.startswith("4"):
                self.losses.record(LossKind.INFERRED, "version-upgraded",
                                   f"The OData {declared} metadata is written as CSDL 4.01: associations become "
                                   "navigation properties and v2 / 3 primitives their v4 types.")
            return
        if api.servers:
            self.losses.record(LossKind.NA, "servers-dropped",
                               f"CSDL describes a service's metadata, not where it runs; {len(api.servers)} server(s) "
                               "are not written.")
        if api.title or api.description:
            self.losses.record(LossKind.NA, "title-dropped",
                               "CSDL has no document title or description; they are not written.")
        if api.version:
            self.losses.record(LossKind.NA, "version-dropped",
                               f"CSDL versions the protocol, not the API; {api.version!r} is not written.")
        if api.channels:
            for channel in api.channels:
                self.losses.record(LossKind.NA, "channel-dropped",
                                   f"OData has no event channels; {channel.address!r} is not written.",
                                   pointer=channel.key)

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _lookup(self, name: Optional[str]) -> Optional[Type]:
        if not name:
            return None
        return self._types_by_key.get(name) or self._types_by_name.get(name)

    def _resource_types(self) -> Set[str]:
        """Keys of the records an HTTP operation sends or returns: the resources that become entity types."""
        keys: Set[str] = set()
        for operation in self._api.operations():
            if not operation.http_method:
                continue
            for message in operation.messages:
                ref = message.payload
                while ref is not None and ref.item is not None:
                    ref = ref.item
                target = self._lookup(ref.name if ref is not None else None)
                if target is not None and target.kind is TypeKind.RECORD:
                    keys.add(target.key)
        if not keys and all(op.kind in _EVENT_KINDS for op in self._api.operations()):
            keys = self._root_records()
        return keys

    def _root_records(self) -> Set[str]:
        """For a source with no operations but events (a data schema): the records no other record embeds — the
        collections an OData service exposes — or, when every record is embedded, the first one."""
        records = [t for t in self._api.types if t.kind is TypeKind.RECORD]
        embedded: Set[str] = set()
        for type_ in self._api.types:
            for field in type_.fields:
                ref = field.type
                while ref is not None and ref.item is not None:
                    ref = ref.item
                target = self._lookup(ref.name if ref is not None else None)
                if target is not None and target.key != type_.key:
                    embedded.add(target.key)
        roots = {t.key for t in records if t.key not in embedded}
        return roots or ({records[0].key} if records else set())

    def _kind_of(self, type_: Type, resources: Set[str]) -> str:
        if type_.kind is TypeKind.RECORD:
            source = type_.extras.get("odata_kind") if self._odata_source else None
            if source in ("entity", "complex"):
                return "EntityType" if source == "entity" else "ComplexType"
            return "EntityType" if type_.key in resources else "ComplexType"
        if type_.kind is TypeKind.ENUM:
            return "EnumType"
        if type_.kind in (TypeKind.UNION, TypeKind.MAP):
            return "ComplexType"
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None and (
                type_.aliased.item is not None or self._lookup(type_.aliased.name) is not None):
            return "inline"
        return "TypeDefinition"

    def _qualified(self, type_: Type) -> str:
        return f"{self.namespace}.{self._names[type_.key]}"

    def _ref(self, ref: Optional[TypeRef], fmt: Optional[str] = None, *, depth: int = 0) -> Tuple[str, bool, bool]:
        """``(type, collection, entity)`` for a reference: a CSDL type name, whether it is a collection, and
        whether it names an entity type (a navigation property)."""
        if ref is None:
            return "Edm.Untyped", False, False
        if ref.item is not None:
            inner, nested, entity = self._ref(ref.item, fmt, depth=depth)
            if nested:
                self.losses.record(LossKind.INFERRED, "nested-collection",
                                   "CSDL has no collection of collections; the inner list is written as untyped.",
                                   pointer=self._context)
                return "Edm.Untyped", True, False
            return inner, True, entity
        target = self._lookup(ref.name)
        if target is None:
            edm, exact = edm_type(ref.name, fmt)
            if not exact:
                what = "widened to" if (scalar_kind(ref.name, fmt) or "").startswith("uint") else "written as"
                self.losses.record(LossKind.INFERRED, "primitive-coerced",
                                   f"CSDL has no {ref.name!r} primitive; it is {what} {edm}.", pointer=self._context)
            return edm, False, False
        kind = self._kinds[target.key]
        if kind == "inline" and target.aliased is not None and depth < 8:
            self.losses.record(LossKind.INFERRED, "alias-inlined",
                               f"CSDL has no alias of a structured type or a collection; uses of {target.key!r} are "
                               "written as the aliased type.", pointer=target.key)
            return self._ref(target.aliased, fmt, depth=depth + 1)
        if kind == "inline":
            return "Edm.Untyped", False, False
        return self._qualified(target), False, kind == "EntityType"

    def _type_member(self, type_: Type) -> Optional[Dict[str, Any]]:
        kind = self._kinds[type_.key]
        name = self._names[type_.key]
        if kind == "inline":
            return None
        member: Dict[str, Any] = {"$Kind": kind}
        if kind in ("EntityType", "ComplexType"):
            if type_.kind is TypeKind.UNION:
                self.losses.record(LossKind.INFERRED, "union-as-complex",
                                   f"CSDL has no unions; {type_.key!r} is a complex type with one nullable property "
                                   "per variant.", pointer=type_.key)
                self._union_properties(type_, member)
            elif type_.kind is TypeKind.MAP:
                member["$OpenType"] = True
                self.losses.record(LossKind.INFERRED, "map-as-open-type",
                                   f"CSDL has no maps; {type_.key!r} is an open complex type (any property name).",
                                   pointer=type_.key)
            else:
                self._properties(type_, member)
                if kind == "EntityType":
                    self._key(type_, member)
        elif kind == "EnumType":
            self._enum_members(type_, member)
        else:
            source = type_.aliased.name if type_.aliased is not None else type_.name
            edm, exact = edm_type(source, _format(type_.constraints))
            if edm == "Edm.Untyped":
                edm = "Edm.String"
                exact = False
            if not exact:
                self.losses.record(LossKind.INFERRED, "primitive-coerced",
                                   f"CSDL has no {source!r} primitive; the type definition {name!r} is based on {edm}.",
                                   pointer=type_.key)
            member["$UnderlyingType"] = edm
            self._facets(type_.constraints, edm, member, type_.key)
        if self._odata_source and isinstance(type_.extras.get("odata_annotations"), dict):
            self.losses.record(LossKind.NA, "annotations-dropped",
                               f"The OData 2 / 3 annotations {', '.join(type_.extras['odata_annotations'])} of "
                               f"{type_.key!r} have no CSDL 4 form; they are not written.", pointer=type_.key)
        self._annotate(member, type_.description, type_.deprecated)
        self._written[type_.key] = f"{kind} {name}"
        self.tracker.record(type_.key, Provenance.SOURCE)
        return member

    def _ordered_fields(self, type_: Type) -> List[CanonicalField]:
        indexed = list(enumerate(type_.fields))
        indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
        return [field for _, field in indexed]

    def _properties(self, type_: Type, member: Dict[str, Any]) -> None:
        scope = _Scope()
        stored_nav = type_.extras.get("odata_navigation_properties") if self._odata_source else None
        for field in self._ordered_fields(type_):
            self._context = field.key
            name = scope.claim(field.name, "Property")
            if name != field.name:
                self.losses.record(LossKind.INFERRED, "renamed-element",
                                   f"CSDL property names are simple identifiers unique in their type; {field.name!r} "
                                   f"is written as {name!r}.", pointer=field.key)
            member[name] = self._property(field)
            self._prop_names[field.key] = name
            self.tracker.record(field.key, Provenance.SOURCE)
        for nav in stored_nav or []:
            if not isinstance(nav, dict) or not nav.get("name"):
                continue
            type_expr = str(nav.get("type") or "")
            collection = type_expr.startswith("Collection(")
            target = type_expr[len("Collection("):-1] if collection else type_expr
            value: Dict[str, Any] = {"$Kind": "NavigationProperty", "$Type": target}
            if collection:
                value["$Collection"] = True
            if nav.get("partner"):
                value["$Partner"] = nav["partner"]
            member[scope.claim(str(nav["name"]), "Navigation")] = value
        self._context = type_.key

    def _property(self, field: CanonicalField) -> Dict[str, Any]:
        stored = field.extras.get("odata_type") if self._odata_source else None
        if isinstance(stored, str) and stored:
            collection = stored.startswith("Collection(")
            type_name, entity = (stored[len("Collection("):-1] if collection else stored), False
            if type_name in _LEGACY_EDM:
                self.losses.record(LossKind.INFERRED, "primitive-coerced",
                                   f"CSDL 4 has no {type_name}; {field.key!r} is written as {_LEGACY_EDM[type_name]}.",
                                   pointer=field.key)
                type_name = _LEGACY_EDM[type_name]
        else:
            type_name, collection, entity = self._ref(field.type, _format(field.constraints))
        value: Dict[str, Any] = {}
        if entity:
            value["$Kind"] = "NavigationProperty"
        if type_name != "Edm.String" or entity:
            value["$Type"] = type_name
        if collection:
            value["$Collection"] = True
        if field.type.nullable and not collection:
            value["$Nullable"] = True
        if not entity:
            self._facets(field.constraints, type_name, value, field.key)
            if field.default is not None:
                default = _default_value(field.default, type_name)
                if default is None:
                    self.losses.record(LossKind.NA, "default-dropped",
                                       f"The default {field.default!r} of {field.key!r} does not fit {type_name}; it "
                                       "is "
                                       "not written.", pointer=field.key)
                else:
                    value["$DefaultValue"] = default
        elif _has_constraints(field.constraints) or field.default is not None:
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"A navigation property has no facets; the constraints and default of {field.key!r} "
                               "are not written.", pointer=field.key)
        self._source_annotations(field.extras.get("odata_annotations"), value, field.key)
        self._annotate(value, field.description, field.deprecated)
        return value

    def _source_annotations(self, annotations: Any, value: Dict[str, Any], pointer: str) -> None:
        """A v2/v3 source's facet annotations as CSDL facets; the others (``sap:``, ``m:``) are reported."""
        if not self._odata_source or not isinstance(annotations, dict):
            return
        dropped: List[str] = []
        for name, raw in annotations.items():
            facet = _FACET_ANNOTATIONS.get(name)
            if facet is not None and str(raw).isdigit():
                value[facet] = int(raw)
            elif facet == "$MaxLength" and str(raw).lower() == "max":
                continue  # unbounded: CSDL JSON writes it by leaving $MaxLength out
            else:
                dropped.append(name)
        if dropped:
            self.losses.record(LossKind.NA, "annotations-dropped",
                               f"The OData 2 / 3 annotations {', '.join(dropped)} of {pointer!r} have no CSDL 4 form; "
                               "they are not written.", pointer=pointer)

    def _facets(self, constraints: Optional[Constraints], type_name: str, value: Dict[str, Any], pointer: str) -> None:
        """``$MaxLength`` and the ``Validation`` annotations for a constrained property or type definition."""
        if constraints is None:
            return
        dropped: List[str] = []
        if constraints.max_length is not None:
            if type_name in ("Edm.String", "Edm.Binary"):
                value["$MaxLength"] = int(constraints.max_length)
            else:
                dropped.append("maxLength")
        annotations = {
            "@Validation.Pattern": constraints.pattern if type_name == "Edm.String" else None,
            "@Validation.Minimum": (constraints.minimum if constraints.minimum is not None
                                    else constraints.exclusive_minimum),
            "@Validation.Maximum": (constraints.maximum if constraints.maximum is not None
                                    else constraints.exclusive_maximum),
            "@Validation.MinItems": constraints.min_items,
            "@Validation.MaxItems": constraints.max_items,
        }
        if constraints.pattern and type_name != "Edm.String":
            dropped.append("pattern")
        for term, item in annotations.items():
            if item is None:
                continue
            if term in ("@Validation.Minimum", "@Validation.Maximum") and type_name not in _NUMERIC:
                dropped.append(term.split(".")[-1].lower())
                continue
            value[term] = int(item) if isinstance(item, float) and item.is_integer() else item
            self._vocabularies.add("Validation")
        if constraints.exclusive_minimum is not None and constraints.minimum is None and "@Validation.Minimum" in value:
            value["@Validation.Minimum@Validation.Exclusive"] = True
        if constraints.exclusive_maximum is not None and constraints.maximum is None and "@Validation.Maximum" in value:
            value["@Validation.Maximum@Validation.Exclusive"] = True
        if constraints.enum:
            value["@Validation.AllowedValues"] = [{"Value": v} for v in constraints.enum]
            self._vocabularies.add("Validation")
        if constraints.min_length is not None:
            dropped.append("minLength")
        if constraints.format and constraints.format.lower() not in _CONSUMED_FORMATS:
            dropped.append(f"format {constraints.format!r}")
        if constraints.multiple_of is not None:
            dropped.append("multipleOf")
        if constraints.unique_items:
            dropped.append("uniqueItems")
        if dropped:
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"CSDL has no facet or Validation term for {', '.join(dropped)} on {type_name}; it is "
                               f"not written for {pointer!r}.", pointer=pointer)

    def _annotate(self, value: Dict[str, Any], description: Optional[str], deprecated: bool) -> None:
        if description and description.strip():
            value["@Core.Description"] = description.strip()
            self._vocabularies.add("Core")
        if deprecated:
            value["@Core.Revisions"] = [{"Kind": "Deprecated", "Description": "Deprecated."}]
            self._vocabularies.add("Core")

    def _key(self, type_: Type, member: Dict[str, Any]) -> None:
        """``$Key``: the source's, an id-like property (inferred), or a synthesized ``Id`` property."""
        stored = type_.extras.get("odata_key_properties") if self._odata_source else None
        if isinstance(stored, list) and stored:
            member["$Key"] = [str(name) for name in stored]
            return
        candidates = {f"{type_.name}id".lower(), f"{type_.name}_id".lower(), "id", "key", "uuid"}
        for field in self._ordered_fields(type_):
            name = self._prop_names.get(field.key)
            if name is None or field.name.lower() not in candidates or field.type.item is not None:
                continue
            if self._lookup(field.type.name) is not None:
                continue
            member["$Key"] = [name]
            was_nullable = member[name].pop("$Nullable", None) is not None
            self.losses.record(LossKind.INFERRED, "key-inferred",
                               f"An OData entity needs a key; {type_.key!r} declares none, so its property {name!r} is "
                               "the key" + (" and is written non-nullable (a key cannot be null)." if was_nullable
                                            else "."), pointer=type_.key)
            return
        key = "Id" if "Id" not in member else "_Id"
        member[key] = {"@Core.Description": "Key synthesized by Apiome: the source declares none."}
        self._vocabularies.add("Core")
        member["$Key"] = [key]
        self.losses.record(LossKind.INFERRED, "key-synthesized",
                           f"An OData entity needs a key; {type_.key!r} has no key or id-like property, so a string "
                           f"property {key!r} is added as its key.", pointer=type_.key)

    def _union_properties(self, type_: Type, member: Dict[str, Any]) -> None:
        scope = _Scope()
        variants = [(f.name, f.type, f.key) for f in type_.fields] or [
            (m.split(".")[-1], TypeRef(name=m), type_.key) for m in type_.union_members]
        for name, ref, key in variants:
            self._context = key
            type_name, collection, entity = self._ref(ref)
            value: Dict[str, Any] = {"$Nullable": True}
            if entity:
                value["$Kind"] = "NavigationProperty"
                del value["$Nullable"]
            if type_name != "Edm.String" or entity:
                value["$Type"] = type_name
            if collection:
                value["$Collection"] = True
                value.pop("$Nullable", None)
            member[scope.claim(name[:1].lower() + name[1:], "variant")] = value
        self._context = type_.key

    def _enum_members(self, type_: Type, member: Dict[str, Any]) -> None:
        scope = _Scope()
        values = [v.value for v in type_.enum_values]
        numeric = (all(isinstance(v, int) and not isinstance(v, bool) for v in values)
                   and len(set(values)) == len(values))
        for index, value in enumerate(type_.enum_values):
            name = scope.claim(value.name, "Member")
            if name != value.name:
                self.losses.record(LossKind.INFERRED, "renamed-element",
                                   f"CSDL enum members are simple identifiers; {value.name!r} of {type_.key!r} is "
                                   f"written as {name!r}.", pointer=value.key)
            elif isinstance(value.value, str) and value.value != value.name:
                self.losses.record(LossKind.INFERRED, "enum-value-as-name",
                                   f"CSDL enum members have integer values; the wire value {value.value!r} of "
                                   f"{value.key!r} is its member name {name!r}.", pointer=value.key)
            member[name] = value.value if numeric else index
            if value.description:
                member[f"{name}@Core.Description"] = value.description
                self._vocabularies.add("Core")

    # ------------------------------------------------------------------
    # Entity sets and operations
    # ------------------------------------------------------------------

    def _entity_sets(self, container: Dict[str, Any]) -> Dict[str, str]:
        """Write one entity set per entity type; returns entity type key → set name."""
        sets: Dict[str, str] = {}
        stored = [entry for schema in self._schemas_extras
                  for entry in ((schema.get("entity_container") or {}).get("entity_sets") or [])
                  if isinstance(entry, dict)]
        scope = _Scope()
        for entry in stored:
            local = str(entry.get("entity_type", "")).split(".")[-1]
            target = self._types_by_name.get(local)
            if target is None or self._kinds.get(target.key) != "EntityType":
                continue
            name = scope.claim(str(entry.get("name")), "Set")
            container[name] = {"$Collection": True, "$Type": self._qualified(target)}
            sets.setdefault(target.key, name)
        for type_ in self._api.types:
            # An OData source keeps exactly its own entity sets (a contained or abstract entity has none).
            if self._odata_source or self._kinds.get(type_.key) != "EntityType" or type_.key in sets:
                continue
            name = scope.claim(self._collection_segment(type_) or f"{self._names[type_.key]}s", "Set")
            container[name] = {"$Collection": True, "$Type": self._qualified(type_)}
            sets[type_.key] = name
        return sets

    def _collection_segment(self, type_: Type) -> Optional[str]:
        """The path segment of a ``GET /segment`` operation that lists ``type_``."""
        for operation in self._api.operations():
            if (operation.http_method or "").upper() != "GET" or not operation.http_path:
                continue
            segments = [s for s in operation.http_path.split("?")[0].split("/") if s]
            if len(segments) != 1 or "{" in segments[0]:
                continue
            for message in operation.messages:
                if message.role is MessageRole.RESPONSE and message.payload is not None and \
                        message.payload.item is not None and self._lookup(message.payload.item.name) is type_:
                    return segments[0]
        return None

    def _operation(self, operation: Operation, sets: Dict[str, str], schema: Dict[str, Any],
                   container: Dict[str, Any], scope: _Scope) -> None:
        if operation.kind in _EVENT_KINDS:
            self.losses.record(LossKind.NA, "event-operation-dropped",
                               f"OData has no events; {operation.kind.value} operation {operation.key!r} is not "
                               "written.", pointer=operation.key)
            return
        if operation.kind is OperationKind.SUBSCRIPTION or operation.streaming in (StreamingMode.CLIENT,
                                                                                   StreamingMode.BIDIRECTIONAL):
            what = "GraphQL subscription" if operation.kind is OperationKind.SUBSCRIPTION else (
                f"{operation.streaming.value}-streaming call")
            self.losses.record(LossKind.NA, "stream-dropped",
                               f"An OData Function or Action takes one request and returns one response; the {what} "
                               f"{operation.key!r} has no OData form and is not written.", pointer=operation.key)
            return
        if operation.streaming is StreamingMode.SERVER:
            self.losses.record(LossKind.INFERRED, "stream-as-collection",
                               f"OData has no streams; the server stream of {operation.key!r} is written as a result "
                               "returning a collection of its messages.", pointer=operation.key)
        crud = self._crud(operation, sets)
        if crud is not None:
            set_name, verb = crud
            self._written[operation.key] = f"entity set {set_name} ({verb})"
            if not (self._odata_source and operation.extras.get("odata_entity_set")):
                extra = [p.name for p in operation.parameters if p.location is not ParameterLocation.PATH]
                note = (f"; its parameters {', '.join(extra)} are served by OData query options ($top, $skip, "
                        "$filter …)") if extra else ""
                self.losses.record(LossKind.INFERRED, "crud-as-entity-set",
                                   f"{(operation.http_method or '').upper()} {operation.http_path} is the {verb} "
                                   "request "
                                   f"of the entity set {set_name!r}{note}.", pointer=operation.key)
            self.tracker.record(operation.key, Provenance.SOURCE)
            return
        self._unbound(operation, schema, container, scope)

    def _crud(self, operation: Operation, sets: Dict[str, str]) -> Optional[Tuple[str, str]]:
        """``(entity set, read | create | update | delete | query)`` when the entity set serves the operation."""
        if self._odata_source and operation.extras.get("odata_entity_set"):
            return str(operation.extras["odata_entity_set"]), str(operation.extras.get("odata_operation", "read"))
        method = (operation.http_method or "").upper()
        if not method or not operation.http_path:
            return None
        segments = [s for s in operation.http_path.split("?")[0].split("/") if s]
        if not 1 <= len(segments) <= 2 or "{" in segments[0] or (len(segments) == 2 and not re.fullmatch(
                r"\{[^{}]+\}", segments[1])):
            return None
        by_key = len(segments) == 2
        types = []
        for message in operation.messages:
            ref = message.payload
            while ref is not None and ref.item is not None:
                ref = ref.item
            target = self._lookup(ref.name if ref is not None else None)
            if target is not None and target.key in sets:
                types.append(target.key)
        if not types or len(set(types)) != 1:
            if method == "DELETE" and by_key:
                match = next((k for k, s in sets.items() if s.lower() == segments[0].lower()), None)
                return (sets[match], "delete") if match else None
            return None
        set_name = sets[types[0]]
        verbs = {("GET", False): "query", ("GET", True): "read", ("POST", False): "create", ("PUT", True): "update",
                 ("PATCH", True): "update", ("DELETE", True): "delete"}
        verb = verbs.get((method, by_key))
        return (set_name, verb) if verb else None

    def _unbound(self, operation: Operation, schema: Dict[str, Any], container: Dict[str, Any], scope: _Scope) -> None:
        """An operation an entity set does not serve: an unbound Function (a GET or query with a result) or Action."""
        success = next((m for m in operation.messages if m.role is MessageRole.RESPONSE and
                        (m.payload is not None or m.payload_schema) and str(m.status_code or "200").startswith("2")),
                       None)
        method = (operation.http_method or "").upper()
        function = success is not None and (method == "GET" or operation.kind is OperationKind.QUERY)
        kind = "Function" if function else "Action"
        name = self._scope.claim(operation.name, "Operation")
        if name != operation.name:
            self.losses.record(LossKind.INFERRED, "renamed-element",
                               f"CSDL operation names are simple identifiers unique in the namespace; "
                               f"{operation.name!r} is written as {name!r}.", pointer=operation.key)
        member: Dict[str, Any] = {"$Kind": kind}
        params: List[Dict[str, Any]] = []
        param_scope = _Scope()
        dropped: List[str] = []
        for param in operation.parameters:
            if param.location in (ParameterLocation.HEADER, ParameterLocation.COOKIE):
                dropped.append(f"{param.location.value} {param.name}")
                continue
            self._context = param.key
            type_name, collection, _ = self._ref(param.type, _format(param.constraints))
            entry: Dict[str, Any] = {"$Name": param_scope.claim(param.name, "param")}
            if type_name != "Edm.String":
                entry["$Type"] = type_name
            if collection:
                entry["$Collection"] = True
            if not param.required and param.location is not ParameterLocation.PATH:
                entry["$Nullable"] = True
            self._annotate(entry, param.description, param.deprecated)
            params.append(entry)
        self._context = operation.key
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None:
            dropped += [f"header {h.name}" for h in request.headers]
            if request.payload is not None or request.payload_schema:
                type_name, collection, _ = self._ref(request.payload) if request.payload is not None else (
                    "Edm.Untyped", False, False)
                entry = {"$Name": param_scope.claim("body", "body")}
                if type_name != "Edm.String":
                    entry["$Type"] = type_name
                if collection:
                    entry["$Collection"] = True
                if not request.required:
                    entry["$Nullable"] = True
                params.append(entry)
        if params:
            member["$Parameter"] = params
        if success is not None:
            type_name, collection, _ = self._ref(success.payload) if success.payload is not None else (
                "Edm.Untyped", False, False)
            returns: Dict[str, Any] = {"$Type": type_name}
            if collection or operation.streaming is StreamingMode.SERVER:
                returns["$Collection"] = True
            member["$ReturnType"] = returns
        self._annotate(member, operation.description, operation.deprecated)
        schema[name] = [member]
        container[scope.claim(name, "Import")] = {f"${kind}": f"{self.namespace}.{name}"}
        binding = f"{method} {operation.http_path}" if method else "an RPC call"
        self.losses.record(LossKind.INFERRED, f"operation-as-{kind.lower()}",
                           f"CRUD on entity sets is all OData routes by itself; {binding} ({operation.key!r}) is the "
                           f"unbound {kind.lower()} {name!r}, called through its import"
                           + (f" ({'GET' if function else 'POST'} /{name})" if method else "") + ".",
                           pointer=operation.key)
        if dropped:
            self.losses.record(LossKind.NA, "parameter-dropped",
                               f"OData operation parameters are in the URL or body; {', '.join(dropped)} of "
                               f"{operation.key!r} are not written.", pointer=operation.key)
        errors = [str(m.status_code or "default") for m in operation.messages if m.role is MessageRole.ERROR]
        if errors:
            self.losses.record(LossKind.NA, "errors-dropped",
                               f"OData errors use the standard error format; the {', '.join(errors)} error response(s) "
                               f"of {operation.key!r} are not declared.", pointer=operation.key)
        self._written[operation.key] = f"{kind} {name}"
        self.tracker.record(operation.key, Provenance.SOURCE)

    # ------------------------------------------------------------------
    # CSDL XML
    # ------------------------------------------------------------------

    def render_xml(self) -> str:
        """The same model as CSDL XML (``edmx:Edmx``)."""
        ET.register_namespace("edmx", _EDMX_NS)
        ET.register_namespace("", _EDM_NS)
        edmx = ET.Element(f"{{{_EDMX_NS}}}Edmx", Version=self.document["$Version"])
        for uri, reference in (self.document.get("$Reference") or {}).items():
            ref_el = ET.SubElement(edmx, f"{{{_EDMX_NS}}}Reference", Uri=uri)
            for include in reference["$Include"]:
                ET.SubElement(ref_el, f"{{{_EDMX_NS}}}Include", Namespace=include["$Namespace"],
                              Alias=include["$Alias"])
        services = ET.SubElement(edmx, f"{{{_EDMX_NS}}}DataServices")
        schema_el = ET.SubElement(services, f"{{{_EDM_NS}}}Schema", Namespace=self.namespace)
        for name, member in self.document[self.namespace].items():
            if isinstance(member, list):
                for overload in member:
                    self._xml_operation(schema_el, name, overload)
            elif member["$Kind"] == "EntityContainer":
                continue
            elif member["$Kind"] == "EnumType":
                el = ET.SubElement(schema_el, f"{{{_EDM_NS}}}EnumType", Name=name)
                for key, value in member.items():
                    if not key.startswith("$") and "@" not in key:
                        member_el = ET.SubElement(el, f"{{{_EDM_NS}}}Member", Name=key, Value=str(value))
                        _xml_annotations(member_el, {k[len(key):]: v for k, v in member.items()
                                                     if k.startswith(f"{key}@")})
                _xml_annotations(el, member)
            elif member["$Kind"] == "TypeDefinition":
                el = ET.SubElement(schema_el, f"{{{_EDM_NS}}}TypeDefinition", Name=name,
                                   UnderlyingType=member["$UnderlyingType"])
                _xml_facets(el, member)
                _xml_annotations(el, member)
            else:
                attrs = {"Name": name}
                if member.get("$OpenType"):
                    attrs["OpenType"] = "true"
                el = ET.SubElement(schema_el, f"{{{_EDM_NS}}}{member['$Kind']}", attrs)
                if member.get("$Key"):
                    key_el = ET.SubElement(el, f"{{{_EDM_NS}}}Key")
                    for key in member["$Key"]:
                        ET.SubElement(key_el, f"{{{_EDM_NS}}}PropertyRef", Name=key)
                for prop, value in member.items():
                    if prop.startswith("$") or "@" in prop:
                        continue
                    tag = "NavigationProperty" if value.get("$Kind") == "NavigationProperty" else "Property"
                    prop_el = ET.SubElement(el, f"{{{_EDM_NS}}}{tag}", Name=prop, Type=_xml_type(value))
                    if tag == "Property" or not value.get("$Collection"):
                        prop_el.set("Nullable", "true" if value.get("$Nullable") else "false")
                    if value.get("$Partner"):
                        prop_el.set("Partner", value["$Partner"])
                    _xml_facets(prop_el, value)
                    _xml_annotations(prop_el, value)
                _xml_annotations(el, member)
        container_name = self.document["$EntityContainer"].split(".")[-1]
        container = self.document[self.namespace][container_name]
        container_el = ET.SubElement(schema_el, f"{{{_EDM_NS}}}EntityContainer", Name=container_name)
        for name, value in container.items():
            if name.startswith("$"):
                continue
            if "$Function" in value:
                ET.SubElement(container_el, f"{{{_EDM_NS}}}FunctionImport", Name=name, Function=value["$Function"])
            elif "$Action" in value:
                ET.SubElement(container_el, f"{{{_EDM_NS}}}ActionImport", Name=name, Action=value["$Action"])
            else:
                ET.SubElement(container_el, f"{{{_EDM_NS}}}EntitySet", Name=name, EntityType=value["$Type"])
        ET.indent(edmx, space="  ")
        xml = ET.tostring(edmx, encoding="unicode")
        header = '<?xml version="1.0" encoding="UTF-8"?>\n'
        if self._options.include_comments:
            title = (self._api.title or self._api.identity.name or self.namespace).replace("--", "-")
            header += f"<!-- Generated by Apiome from {title}. -->\n"
        return header + xml + "\n"

    def _xml_operation(self, schema_el: ET.Element, name: str, member: Dict[str, Any]) -> None:
        el = ET.SubElement(schema_el, f"{{{_EDM_NS}}}{member['$Kind']}", Name=name)
        for param in member.get("$Parameter", []):
            param_el = ET.SubElement(el, f"{{{_EDM_NS}}}Parameter", Name=param["$Name"], Type=_xml_type(param),
                                     Nullable="true" if param.get("$Nullable") else "false")
            _xml_annotations(param_el, param)
        if "$ReturnType" in member:
            ET.SubElement(el, f"{{{_EDM_NS}}}ReturnType", Type=_xml_type(member["$ReturnType"]))
        _xml_annotations(el, member)


# ===========================================================================
# Helpers
# ===========================================================================


def _xml_type(value: Dict[str, Any]) -> str:
    type_name = value.get("$Type", "Edm.String")
    return f"Collection({type_name})" if value.get("$Collection") else type_name


def _xml_facets(el: ET.Element, value: Dict[str, Any]) -> None:
    for facet in ("$MaxLength", "$Precision", "$Scale"):
        if facet in value:
            el.set(facet[1:], str(value[facet]))
    if "$DefaultValue" in value:
        default = value["$DefaultValue"]
        el.set("DefaultValue", "true" if default is True else "false" if default is False else str(default))


def _xml_annotations(el: ET.Element, value: Dict[str, Any]) -> None:
    """``@Term`` members as ``<Annotation Term=…>`` children (``@Term@Validation.Exclusive`` nested)."""
    for key, item in value.items():
        if not key.startswith("@") or key.count("@") > 1:
            continue
        annotation = ET.SubElement(el, f"{{{_EDM_NS}}}Annotation", Term=key[1:])
        _xml_value(annotation, item)
        nested = value.get(f"{key}@Validation.Exclusive")
        if nested is not None:
            inner = ET.SubElement(annotation, f"{{{_EDM_NS}}}Annotation", Term="Validation.Exclusive")
            _xml_value(inner, nested)


def _xml_value(el: ET.Element, item: Any) -> None:
    if isinstance(item, bool):
        el.set("Bool", "true" if item else "false")
    elif isinstance(item, int):
        el.set("Int", str(item))
    elif isinstance(item, float):
        el.set("Float", repr(item))
    elif isinstance(item, str):
        el.set("String", item)
    elif isinstance(item, list):
        collection = ET.SubElement(el, f"{{{_EDM_NS}}}Collection")
        for entry in item:
            record = ET.SubElement(collection, f"{{{_EDM_NS}}}Record")
            for prop, prop_value in entry.items():
                prop_el = ET.SubElement(record, f"{{{_EDM_NS}}}PropertyValue", Property=prop)
                if prop == "Kind":
                    prop_el.set("EnumMember", f"Core.RevisionKind/{prop_value}")
                else:
                    _xml_value(prop_el, prop_value)


def _default_value(value: Any, type_name: str) -> Any:
    """The ``$DefaultValue`` for ``value`` on a property of ``type_name``, or ``None`` when it does not fit."""
    if type_name == "Edm.Boolean":
        return value if isinstance(value, bool) else None
    if type_name in _NUMERIC:
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if type_name.startswith("Edm."):
        return value if isinstance(value, str) else None
    return value if isinstance(value, str) else None


def _format(constraints: Optional[Constraints]) -> Optional[str]:
    return constraints.format if constraints is not None else None


def _has_constraints(constraints: Optional[Constraints]) -> bool:
    return constraints is not None and bool(constraints.model_dump(exclude={"extras"}, exclude_none=True))


def _namespace(api: CanonicalApi, schemas: List[Dict[str, Any]]) -> str:
    """The CSDL namespace: an OData source's own, else dotted simple identifiers from the identity."""
    if schemas and schemas[0].get("namespace"):
        return str(schemas[0]["namespace"])
    raw = api.identity.namespace or api.identity.name or api.title or "Exported"
    raw = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", str(raw))
    parts = []
    for part in re.split(r"::|[./:\\#\s]+", raw):
        ident = re.sub(r"[^A-Za-z0-9_]+", "_", part).strip("_")
        if ident:
            parts.append(f"_{ident}" if ident[0].isdigit() else ident)
    namespace = ".".join(parts) or "Exported"
    # `Edm`, `odata`, `System` and `Transient` are reserved namespaces.
    return f"{namespace}_" if namespace in ("Edm", "odata", "System", "Transient") else namespace


def validate_odata_document(content: str) -> None:
    """Validate emitted OData metadata: the OASIS CSDL schema (JSON or XML), then a re-parse.

    Args:
        content: CSDL JSON or CSDL XML text.

    Raises:
        ValueError: When the document breaks the OASIS schema (the first violations named with their
            path) or does not re-parse as OData.
    """
    from .odata_csdl_json import is_csdl_json, parse_csdl_json
    from .odata_csdl_schema import validate_csdl_json
    from .odata_csdl_xsd import validate_csdl_xml
    from .odata_parser import parse_odata

    if is_csdl_json(content):
        violations, total = validate_csdl_json(json.loads(content))
        if total:
            detail = "; ".join(f"{v.path or '(root)'}: {v.message}" for v in violations[:5])
            raise ValueError(f"Invalid CSDL JSON (OASIS schema, {total} violation(s)): {detail}")
        parse_csdl_json(content)
        return
    checked = validate_csdl_xml(content)
    if checked is not None and checked[1]:
        violations, total = checked
        detail = "; ".join(f"{v.path or '(root)'}: {v.message}" for v in violations[:5])
        raise ValueError(f"Invalid CSDL XML (OASIS schemas, {total} violation(s)): {detail}")
    parse_odata(content)
