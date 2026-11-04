"""XSD emitter: canonical model → standalone XML Schema — MFX-22.1 (#4132).

The inverse of :class:`app.xsd_normalizer.XsdNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. Exports just the data types, as XSD 1.0 (the default) or XSD 1.1.

**Types → XSD** use the shared writer, :mod:`app.xsd_schema` — the same mapping WSDL (MFX-14.1) and
WADL write, so the three cannot drift:

* records → ``complexType`` + ``sequence`` (and a global element of the same name);
* unions (``oneOf``) → ``xs:choice``; enums → ``xs:enumeration``;
* nullable fields → ``nillable="true" minOccurs="0"``; lists → ``maxOccurs="unbounded"``;
* constraints → facets (``pattern``, ``minLength`` / ``maxLength``, ``minInclusive`` /
  ``maxInclusive`` …), never comments; in XSD 1.1 ``multipleOf`` → ``xs:assertion``;
* a model imported from XSD is written back with its own elements, attributes, occurrences and enum
  bases.

**Namespaces.** The ``targetNamespace`` is the source's namespace (an XSD source's own); a source with
none writes a no-namespace schema. A type whose namespace is a different URI is written in a schema
document of its own, so a multi-namespace source exports one ``.xsd`` per namespace — the first is
the main document — each ``xs:import`` ing the namespaces it references (delivered as a zip).
Operations and channels are dropped: XSD describes data only.

**Fidelity** (MFX-22.2): :class:`XsdFidelityRulePack` predicts the report from the writer's own losses.

**Output modes** (MFX-22.3, #4134): ``mode`` writes the same types as RELAX NG — ``relaxng`` (XML
syntax, ``<Name>.rng``) or ``relaxng-compact`` (``<Name>.rnc``) — or as a DTD (``dtd``, ``<Name>.dtd``),
one file each, built from the XSD documents by :mod:`app.xml_schema_modes`; the fidelity pack follows
the mode (:meth:`XsdFidelityRulePack.apply_options`).

**ISO 20022 profile** (MFX-22.4, #4135): ``profile="iso20022"`` writes the types as an ISO 20022 message
definition — one ``urn:iso:std:iso:20022:tech:xsd:<identifier>`` namespace, a ``Document`` root wrapping the
business element, UpperCamelCase names — plus a message-catalog manifest
(:mod:`app.iso20022_xsd_profile`). ``message_identifier``, ``business_area`` and ``message_type`` name the
message; what the source cannot meet is reported ``SYNTH`` or ``APPROX``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple, Union

from pydantic import Field, ValidationError, model_validator

from .canonical_model import ApiParadigm, CanonicalApi, Channel, Operation, TypeKind
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    ProvenanceTracker,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .iso20022_xsd_profile import (
    BUSINESS_AREA_RE,
    DOCUMENT,
    MESSAGE_CATALOG_PATH,
    MESSAGE_IDENTIFIER_RE,
    SYNTHESIZED_SUBJECTS,
    Iso20022Message,
    Iso20022SchemaWriter,
    append_document,
    message_catalog,
    record_message_losses,
    resolve_message,
)
from .lossiness import LossinessSeverity
from .writer_loss_rulepack import WriterLossRulePack
from .xml_schema_modes import (
    DTD_MODE,
    RELAXNG_COMPACT_MODE,
    RELAXNG_MODE,
    DtdWriter,
    RelaxNgWriter,
    merge_losses,
    mode_label,
    relaxng_compact,
    restate_xsd_losses,
)
from .xsd_schema import TNS_PREFIX, XSD_NS, XSD_PREFIX, XsdSchemaWriter, comment_safe
from .xsd_types import xsd_builtin

__all__ = [
    "ISO20022_PROFILE", "XSD_OUTPUT_MODES", "XsdEmitOptions", "XsdEmitter", "XsdFidelityRulePack", "xsd_namespaces",
]

_XSD_FORMAT = "xsd"
#: The ``profile`` option's value for an ISO 20022 message definition (MFX-22.4).
ISO20022_PROFILE = "iso20022"
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"
#: A namespace that is a URI (``http://…``, ``urn:…``) rather than a package name (``com.example``).
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

#: The ``mode`` option's values → (file extension, media type, what the file is called in messages).
XSD_OUTPUT_MODES: Dict[str, Tuple[str, str, str]] = {
    "xsd": (".xsd", "application/xml", "an XML Schema"),
    RELAXNG_MODE: (".rng", "application/xml", "a RELAX NG grammar"),
    RELAXNG_COMPACT_MODE: (".rnc", "application/relax-ng-compact-syntax", "a RELAX NG grammar (compact syntax)"),
    DTD_MODE: (".dtd", "application/xml-dtd", "a DTD"),
}


class XsdFidelityRulePack(WriterLossRulePack):
    """Fidelity rules for XSD export — MFX-22.2 (#4133).

    The pack builds the export with the XSD writer (default options: XSD 1.0) and turns each loss the
    writer records into a verdict on the construct it concerns
    (:class:`~app.writer_loss_rulepack.WriterLossRulePack`), so the report names exactly what the
    export does:

    * **operations / channels** — ``DROP``: XSD is types-only. An operation-bearing source also gets
      the **types-only advisory** at the root, counting what is not exported;
    * **untyped maps** (a free-form ``additionalProperties`` object) — ``xs:any``, ``APPROX``; a typed
      map is a list of ``entry`` elements, ``APPROX``;
    * **unions** — an ``xs:choice`` of child elements, ``APPROX``; a union with no alternatives,
      ``DROP``;
    * **JSON null vs absent** — a nullable value is ``nillable`` and optional, an info ``APPROX`` note;
    * **examples** — kept as ``xs:documentation``, an info ``APPROX``;
    * **attribute vs element** — every property of a non-XSD source is written as a child element, a
      ``SYNTH`` note at the root;
    * renamed names (info), untyped values, constraints with no facet and dropped ``deprecated`` flags;
    * with the **ISO 20022 profile** (MFX-22.4): a synthesized message identifier, the added ``Document``
      root and invented names are ``SYNTH``; names that lose characters, a guessed message type and merged
      namespaces are ``APPROX``.
    """

    target_label = "XSD"
    info_drops = frozenset({"deprecated-dropped", "example-dropped"})
    synthesized = SYNTHESIZED_SUBJECTS
    cosmetic = frozenset({
        "renamed-identifier", "null-as-nillable", "example-as-annotation", "null-as-optional",
        "namespace-as-fixed-xmlns",
    })
    #: The emit options the report is computed for (:meth:`apply_options`; the defaults otherwise).
    _options: Optional["XsdEmitOptions"] = None

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options — the ``mode`` (MFX-22.3) changes what is lost.

        Invalid options fall back to the defaults (XSD 1.0).
        """
        try:
            self._options = XsdEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = XsdEmitOptions()

    @property
    def _mode(self) -> str:
        return (self._options or XsdEmitOptions()).mode

    def build_writer(self, api: CanonicalApi) -> "_XsdWriter":
        """Build the export with the options the report is for (default: XSD 1.0).

        A ``message_type`` the model does not have is ignored here (the export itself refuses it).
        """
        options = self._options or XsdEmitOptions()
        try:
            writer = _XsdWriter(api, options)
        except EmitOptionsError:
            options = options.model_copy(update={"message_type": None})
            writer = _XsdWriter(api, options)
        writer.render()
        self.target_label = writer.label
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The rewrite of another format, the element-only choice, and the types-only advisory."""
        verdicts: List[FidelityVerdict] = []
        _extension, _media, written = XSD_OUTPUT_MODES[self._mode]
        iso = (self._options or XsdEmitOptions()).profile == ISO20022_PROFILE
        if iso:
            if api.format != ISO20022_PROFILE:
                verdicts.append(
                    FidelityVerdict.approx(
                        message=f"The {api.format or 'source'} document is written as an ISO 20022 message "
                        "definition and reads back as an ISO 20022 item; details specific to its format are not kept",
                        severity=LossinessSeverity.INFO,
                        target_mapping="document → ISO 20022 message definition",
                    )
                )
        elif self._mode != "xsd":
            reads_back = "a RELAX NG item" if self._mode in (RELAXNG_MODE, RELAXNG_COMPACT_MODE) else "a DTD item"
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is written as {written} and reads back as "
                    f"{reads_back}; details specific to its format are not kept",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"document → {mode_label(self._mode)}",
                )
            )
        elif api.format != _XSD_FORMAT:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is written as an XML Schema and reads back as "
                    "an XSD item; details specific to its format are not kept",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → XML Schema",
                )
            )
        if api.format != _XSD_FORMAT and not (iso and api.format == ISO20022_PROFILE):
            if any(t.kind is TypeKind.RECORD and t.fields for t in api.types):
                verdicts.append(
                    FidelityVerdict.synth(
                        message="XML can carry a scalar property as an attribute or as a child element; the export "
                        "chooses: every property is written as a child element",
                        severity=LossinessSeverity.INFO,
                        target_mapping="property → child element",
                    )
                )
        return verdicts + self.loss_verdicts(ROOT_CONSTRUCT_KEY)

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            "the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class XsdEmitOptions(EmitOptions):
    """Per-target options for :class:`XsdEmitter`."""

    xsd_version: Literal["1.0", "1.1"] = Field(
        default="1.0",
        description="`1.0` (default) or `1.1`. XSD 1.1 marks the schema `vc:minVersion=\"1.1\"` and "
        "writes `multipleOf` as an `xs:assertion` facet.",
    )
    include_xml_declaration: bool = Field(
        default=True,
        description="Emit the XML 1.0 declaration prolog.",
    )
    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated XSD.",
    )
    mode: Literal["xsd", "relaxng", "relaxng-compact", "dtd"] = Field(
        default="xsd",
        description="`xsd` (default) writes XML Schema. `relaxng` writes one RELAX NG grammar in the XML syntax "
        "(`<Name>.rng`), `relaxng-compact` the same grammar in the compact syntax (`<Name>.rnc`), and `dtd` one "
        "DTD (`<Name>.dtd`). RELAX NG keeps the types and facets; a DTD keeps only element names and content "
        "models. What each mode cannot carry is listed in the fidelity report. `xsd_version` applies to `xsd` "
        "only.",
    )

    profile: Literal["generic", "iso20022"] = Field(
        default="generic",
        description="`generic` (default) writes the types as they are. `iso20022` writes an ISO 20022 message "
        "definition: one `urn:iso:std:iso:20022:tech:xsd:<message_identifier>` namespace, a `Document` root "
        "element wrapping the business element, UpperCamelCase names, descriptions as `xs:documentation`, "
        "and a `message-catalog.json` manifest beside `<message_identifier>.xsd`. `xsd` mode only.",
    )
    message_identifier: Optional[str] = Field(
        default=None,
        description="ISO 20022 profile: the message identifier, `<business area>.<message number>.<variant>."
        "<version>` (`pain.001.001.09`). Defaults to an ISO 20022 source's own; without one, a placeholder "
        "(`<business_area>.001.001.01`) is used and reported as synthesized.",
    )
    business_area: Optional[str] = Field(
        default=None,
        description="ISO 20022 profile: the four-letter business area (`pain`, `pacs`, `camt` …) a placeholder "
        "identifier uses. Must match `message_identifier` when both are set.",
    )
    message_type: Optional[str] = Field(
        default=None,
        description="ISO 20022 profile: the record type (name or key) `Document` wraps as the message. Defaults "
        "to an ISO 20022 source's business element, else the one record no other record uses.",
    )

    @model_validator(mode="after")
    def _version_is_for_xsd(self) -> "XsdEmitOptions":
        """``xsd_version`` 1.1 has no meaning for a RELAX NG or DTD export (MFX-22.3)."""
        if self.mode != "xsd" and self.xsd_version != "1.0":
            raise ValueError(f"mode {self.mode!r} writes no XML Schema; leave xsd_version unset")
        return self

    @model_validator(mode="after")
    def _iso20022_options(self) -> "XsdEmitOptions":
        """The ISO 20022 options (MFX-22.4) need the profile, the profile needs ``xsd`` mode, and the
        identifier and business area must be well formed and agree. Both are lower-cased."""
        named = [n for n in ("message_identifier", "business_area", "message_type") if getattr(self, n)]
        if self.profile != ISO20022_PROFILE:
            if named:
                raise ValueError(f"{', '.join(named)} apply to profile 'iso20022' only")
            return self
        if self.mode != "xsd":
            raise ValueError(f"profile 'iso20022' writes an XML Schema; mode {self.mode!r} is not available with it")
        if self.message_identifier is not None:
            self.message_identifier = self.message_identifier.strip().lower()
            if not MESSAGE_IDENTIFIER_RE.match(self.message_identifier):
                raise ValueError(
                    "message_identifier must be '<business area>.<message number>.<variant>.<version>', "
                    "for example 'pain.001.001.09'"
                )
        if self.business_area is not None:
            self.business_area = self.business_area.strip().lower()
            if not BUSINESS_AREA_RE.match(self.business_area):
                raise ValueError("business_area must be four letters, for example 'pain'")
            if self.message_identifier and not self.message_identifier.startswith(f"{self.business_area}."):
                raise ValueError(
                    f"business_area {self.business_area!r} does not match message_identifier "
                    f"{self.message_identifier!r}"
                )
        return self


class XsdEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as XSD schema documents (one per namespace)."""

    key = "xsd"
    format = "xsd"
    label = "XSD"
    description = "Export as a W3C XML Schema Definition (XSD 1.0 or 1.1), a RELAX NG grammar or a DTD."
    icon = "file-code"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = XsdEmitOptions

    OUTPUT_MEDIA_TYPE = "application/xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return XsdFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[XsdEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, XsdEmitOptions)
            else XsdEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _XsdWriter(api, options)
        media_type = XSD_OUTPUT_MODES[options.mode][1]
        files = [
            EmittedFile(
                path=path,
                content=content,
                media_type="application/json" if path == MESSAGE_CATALOG_PATH else media_type,
            )
            for path, content in writer.render()
        ]
        return EmitResult(
            files=files,
            media_type=media_type,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


def xsd_namespaces(api: CanonicalApi) -> Tuple[Optional[str], Dict[str, Optional[str]]]:
    """The main ``targetNamespace`` and the namespace each type is written in.

    The main namespace is the source's (``identity.namespace``, an XSD source's target namespace),
    else the first URI namespace of a type, else ``None`` (a no-namespace schema). A type whose own
    namespace is a URI keeps it; any other type (a package name, or none) is written in the main one.

    Args:
        api: The model being exported.

    Returns:
        ``(main namespace, {type key: namespace})``.
    """
    type_uris = [t.namespace for t in api.types if t.namespace and _URI.match(t.namespace)]
    main = (
        api.identity.namespace
        or api.extras.get("xsd_target_namespace")
        or (type_uris[0] if type_uris else None)
    )
    return main, {
        t.key: t.namespace if t.namespace and _URI.match(t.namespace) else main for t in api.types
    }


class _XsdWriter:
    """Builds the schema documents of one export (single use)."""

    def __init__(self, api: CanonicalApi, options: XsdEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        #: The ISO 20022 message (MFX-22.4), or ``None`` for the generic profile.
        self.message: Optional[Iso20022Message] = None
        if options.profile == ISO20022_PROFILE:
            self._init_iso20022()
            return
        self.main_namespace, type_namespaces = xsd_namespaces(api)
        #: Every namespace written, the main one first.
        self.namespaces: List[Optional[str]] = [self.main_namespace]
        for namespace in type_namespaces.values():
            if namespace not in self.namespaces:
                self.namespaces.append(namespace)
        prefixes = {self.main_namespace: TNS_PREFIX} if self.main_namespace else {}
        for index, namespace in enumerate(n for n in self.namespaces if n and n != self.main_namespace):
            prefixes[namespace] = f"ns{index + 1}"
        self._schema = XsdSchemaWriter(
            api,
            target_namespace=self.main_namespace,
            target_label="XSD",
            losses=self.losses,
            tracker=self.tracker,
            type_namespaces=type_namespaces,
            prefixes=prefixes,
            xsd_version=options.xsd_version,
            standalone=True,
        )
        self.paths = _document_paths(api, self.namespaces)
        #: The output mode's name in messages (``XSD``, ``RELAX NG``, ``DTD``).
        self.label = "XSD" if options.mode == "xsd" else mode_label(options.mode)
        #: What each type became in a RELAX NG or DTD export (set by :meth:`render`).
        self._mode_written: Optional[Dict[str, str]] = None

    def _init_iso20022(self) -> None:
        """Set up an ISO 20022 message definition: one message namespace and ISO 20022 names (MFX-22.4).

        Raises:
            EmitOptionsError: When ``message_type`` names no record type of the model.
        """
        api, options = self._api, self._options
        try:
            message = resolve_message(
                api,
                message_identifier=options.message_identifier,
                business_area=options.business_area,
                message_type=options.message_type,
            )
        except ValueError as exc:
            raise EmitOptionsError(str(exc)) from exc
        self.message = message
        record_message_losses(api, message, self.losses)
        self.main_namespace = message.namespace
        self.namespaces = [message.namespace]
        self._schema = Iso20022SchemaWriter(
            api,
            target_namespace=message.namespace,
            target_label="ISO 20022 XSD",
            losses=self.losses,
            tracker=self.tracker,
            type_namespaces={t.key: message.namespace for t in api.types},
            prefixes={message.namespace: TNS_PREFIX},
            xsd_version=options.xsd_version,
            standalone=True,
            reserved_type_names=frozenset() if message.source_document else frozenset({DOCUMENT}),
        )
        self.paths = {message.namespace: message.schema_path}
        self.label = "ISO 20022 XSD"
        self._mode_written = None

    def _render_iso20022(self) -> List[Tuple[str, str]]:
        """The message definition, then the message-catalog manifest (MFX-22.4)."""
        message = self.message
        assert message is not None
        if self._api.services or self._api.channels:
            self.losses.record(LossKind.NA, "types-only", _types_only_advisory(self._api), pointer="services")
        schema_el = self._schema.new_schema(message.namespace)
        schema_el.set("elementFormDefault", "qualified")
        self._schema.append_types(schema_el, message.namespace, declare_elements=False)
        append_document(schema_el, self._schema, message, self._api.title or self._api.identity.name)
        return [
            (message.schema_path, self._serialize(schema_el)),
            (MESSAGE_CATALOG_PATH, message_catalog(self._api, self._schema, message)),
        ]

    def render(self) -> List[Tuple[str, str]]:
        """Every output document as ``(path, text)``, the main document first.

        The XSD documents are always built; a RELAX NG or DTD export is then written from them as one file.
        """
        ET.register_namespace(XSD_PREFIX, XSD_NS)
        if self.message is not None:
            return self._render_iso20022()
        if self._api.services or self._api.channels:
            self.losses.record(LossKind.NA, "types-only", _types_only_advisory(self._api), pointer="services")
        from_xsd = self._api.format == _XSD_FORMAT
        schemas: List[Tuple[Optional[str], ET.Element]] = []
        for namespace in self.namespaces:
            schema_el = self._schema.new_schema(namespace)
            if namespace:
                schema_el.set("elementFormDefault", "qualified")
            self._schema.append_types(schema_el, namespace, declare_elements=not from_xsd)
            if from_xsd and namespace == self.main_namespace:
                self._prepend_source_elements(schema_el)
            self._prepend_imports(schema_el)
            schemas.append((namespace, schema_el))
        if self._options.mode != "xsd":
            return [self._render_mode(schemas)]
        return [(self.paths[namespace], self._serialize(schema_el)) for namespace, schema_el in schemas]

    def _render_mode(self, schemas: List[Tuple[Optional[str], ET.Element]]) -> Tuple[str, str]:
        """The RELAX NG or DTD file written from the XSD documents (MFX-22.3)."""
        mode = self._options.mode
        extension = XSD_OUTPUT_MODES[mode][0]
        path = self.paths[self.main_namespace][: -len(".xsd")] + extension
        mode_losses = restate_xsd_losses(self.losses, mode)
        own = LossTracker()
        title = self._api.title or self._api.identity.name or "schema"
        header = f"Generated {self.label} for {title}" if self._options.include_comments else None
        if mode == DTD_MODE:
            writer = DtdWriter(self._schema, schemas, own)
            text = writer.build(header=header)
        else:
            rng = RelaxNgWriter(self._schema, schemas, own, self.main_namespace)
            grammar = rng.build()
            writer = rng
            if mode == RELAXNG_COMPACT_MODE:
                text = relaxng_compact(grammar, header=header)
            else:
                text = self._serialize_grammar(grammar, header)
        merge_losses(mode_losses, own.records())
        self.losses = mode_losses
        self._mode_written = writer.written
        return path, text

    def _serialize_grammar(self, grammar: ET.Element, header: Optional[str]) -> str:
        parts: List[str] = []
        if self._options.include_xml_declaration:
            parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        if header:
            parts.append(f"<!-- {comment_safe(header)} -->")
        ET.indent(grammar, space="  ")
        parts.append(ET.tostring(grammar, encoding="unicode"))
        return "\n".join(parts) + "\n"

    def written_as(self, key: str) -> Optional[str]:
        """What the type ``key`` became (``complexType Pet``, ``define Pet``), or ``None``."""
        if self._mode_written is not None:
            return self._mode_written.get(key)
        type_ = self._schema.types_by_key.get(key)
        if type_ is None or key not in self._schema.type_names:
            return None
        kind = "simpleType" if self._schema.is_simple(type_) else "complexType"
        return f"{kind} {self._schema.type_names[key]}"

    def _prepend_source_elements(self, schema_el: ET.Element) -> None:
        """An XSD source's own global elements, first (the first is the document's root element)."""
        types_by_name = {t.name: t.key for t in self._api.types}
        declared = [e for e in self._api.extras.get("xsd_elements") or [] if isinstance(e, dict)]
        for index, entry in enumerate(e for e in declared if e.get("name") and e.get("type")):
            type_name = str(entry["type"])
            key = types_by_name.get(type_name)
            builtin = None if key else xsd_builtin(type_name, xsd_hint=type_name)
            type_ref = (
                self._schema.type_ref(key) if key
                else f"{XSD_PREFIX}:{builtin}" if builtin
                else self._schema.qualified(type_name, self.main_namespace)
            )
            element = ET.Element(ET.QName(XSD_NS, "element"), {"name": str(entry["name"]), "type": type_ref})
            schema_el.insert(index, element)

    def _prepend_imports(self, schema_el: ET.Element) -> None:
        """``xs:import`` each other namespace the document references (imports come first)."""
        namespaces = self._schema.referenced_namespaces(schema_el)
        self._schema.declare_prefixes(schema_el, namespaces)
        for index, namespace in enumerate(namespaces):
            schema_el.insert(
                index,
                ET.Element(
                    ET.QName(XSD_NS, "import"),
                    {"namespace": namespace, "schemaLocation": self.paths[namespace]},
                ),
            )

    def _serialize(self, schema_el: ET.Element) -> str:
        """The document text, with the optional XML declaration and header comment."""
        parts: List[str] = []
        if self._options.include_xml_declaration:
            parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        if self._options.include_comments:
            title = self._api.title or self._api.identity.name or "schema"
            if self.message is not None:
                parts.append(
                    f"<!-- Generated ISO 20022 message definition {self.message.identifier} "
                    f"(XSD {self._options.xsd_version}) for {comment_safe(title)} -->"
                )
            else:
                parts.append(f"<!-- Generated XSD {self._options.xsd_version} for {comment_safe(title)} -->")
        ET.indent(schema_el, space="  ")
        parts.append(ET.tostring(schema_el, encoding="unicode"))
        return "\n".join(parts) + "\n"


def _types_only_advisory(api: CanonicalApi) -> str:
    """The advisory a standalone export of an operation-bearing source carries: what it leaves out."""
    operations = sum(1 for _ in api.operations())
    parts = [f"{operations} operation(s)"] if operations else []
    if api.channels:
        parts.append(f"{len(api.channels)} channel(s)")
    return (
        f"XSD is types-only — {_TYPES_ONLY_DROP_MESSAGE}: {' and '.join(parts) or 'the services'} are not "
        "exported. Export to WSDL, OpenAPI or AsyncAPI as well to keep them."
    )


def _document_paths(api: CanonicalApi, namespaces: List[Optional[str]]) -> Dict[Optional[str], str]:
    """The file name of each namespace's document: ``<Name>.xsd``, then ``<Name>-<last segment>.xsd``."""
    base = _safe(api.identity.name or api.title or "schema", "schema")
    paths: Dict[Optional[str], str] = {}
    taken = set()
    for index, namespace in enumerate(namespaces):
        if index == 0:
            stem = base
        else:
            segment = re.split(r"[/:#]", (namespace or "").rstrip("/#"))[-1]
            stem = f"{base}-{_safe(segment, f'ns{index}')}"
        candidate, suffix = stem, 2
        while candidate in taken:
            candidate, suffix = f"{stem}{suffix}", suffix + 1
        taken.add(candidate)
        paths[namespace] = f"{candidate}.xsd"
    return paths


def _safe(text: str, fallback: str) -> str:
    """``text`` as a file-name stem (letters, digits and ``_``)."""
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_") or fallback
