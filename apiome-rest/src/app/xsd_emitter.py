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
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi, Channel, Operation, TypeKind
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    ProvenanceTracker,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity
from .writer_loss_rulepack import WriterLossRulePack
from .xsd_schema import TNS_PREFIX, XSD_NS, XSD_PREFIX, XsdSchemaWriter, comment_safe
from .xsd_types import xsd_builtin

__all__ = ["XsdEmitOptions", "XsdEmitter", "XsdFidelityRulePack", "xsd_namespaces"]

_XSD_FORMAT = "xsd"
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"
#: A namespace that is a URI (``http://…``, ``urn:…``) rather than a package name (``com.example``).
_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


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
    * renamed names (info), untyped values, constraints with no facet and dropped ``deprecated`` flags.
    """

    target_label = "XSD"
    info_drops = frozenset({"deprecated-dropped"})
    cosmetic = frozenset({"renamed-identifier", "null-as-nillable", "example-as-annotation"})

    def build_writer(self, api: CanonicalApi) -> "_XsdWriter":
        """Build the export with the default options (XSD 1.0)."""
        writer = _XsdWriter(api, XsdEmitOptions())
        writer.render()
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The rewrite of another format, the element-only choice, and the types-only advisory."""
        verdicts: List[FidelityVerdict] = []
        if api.format != _XSD_FORMAT:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is written as an XML Schema and reads back as "
                    "an XSD item; details specific to its format are not kept",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → XML Schema",
                )
            )
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


class XsdEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as XSD schema documents (one per namespace)."""

    key = "xsd"
    format = "xsd"
    label = "XSD"
    description = "Export as a W3C XML Schema Definition (XSD 1.0 or 1.1)."
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
        files = [
            EmittedFile(path=path, content=content, media_type=self.OUTPUT_MEDIA_TYPE)
            for path, content in writer.render()
        ]
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
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

    def render(self) -> List[Tuple[str, str]]:
        """Every schema document as ``(path, text)``, the main document first."""
        ET.register_namespace(XSD_PREFIX, XSD_NS)
        if self._api.services or self._api.channels:
            self.losses.record(LossKind.NA, "types-only", _types_only_advisory(self._api), pointer="services")
        from_xsd = self._api.format == _XSD_FORMAT
        documents: List[Tuple[str, str]] = []
        for namespace in self.namespaces:
            schema_el = self._schema.new_schema(namespace)
            if namespace:
                schema_el.set("elementFormDefault", "qualified")
            self._schema.append_types(schema_el, namespace, declare_elements=not from_xsd)
            if from_xsd and namespace == self.main_namespace:
                self._prepend_source_elements(schema_el)
            self._prepend_imports(schema_el)
            documents.append((self.paths[namespace], self._serialize(schema_el)))
        return documents

    def written_as(self, key: str) -> Optional[str]:
        """What the type ``key`` became (``complexType Pet``, ``simpleType Status``), or ``None``."""
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
