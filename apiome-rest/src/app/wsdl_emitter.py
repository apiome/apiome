"""WSDL emitter: canonical model → WSDL 1.1 + XSD (document/literal) — MFX-18.1, MFX-14.1 (#3889).

The inverse of :class:`app.wsdl_normalizer.WsdlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.

**Layout.** By default the export is a two-file bundle: ``<Name>.wsdl`` (messages, port types,
bindings, services) and ``<Name>.xsd`` (the types), joined by an ``xsd:import`` in ``wsdl:types``.
``layout="single"`` inlines the schema in the WSDL instead.

**Types → XSD** (:mod:`app.xsd_types`):

* records → ``complexType`` with a ``sequence`` (and a global element of the same name);
* lists → ``maxOccurs="unbounded"`` (or the source's ``minItems``/``maxItems``);
* nullable fields → ``minOccurs="0" nillable="true"``;
* constraints → restriction facets (length, range, pattern, enumeration);
* enums → ``simpleType`` enumerations; unions → ``xs:choice``; maps → a list of ``entry`` elements
  (reported); aliases and named scalars → derived types;
* scalars keep their precision (``integer`` + ``int64`` → ``xs:long``, ``date-time`` → ``xs:dateTime``);
* descriptions → ``xs:annotation``.

**Messages.** A model imported from WSDL keeps its own messages, parts and topology (MFI-13.2/13.5).
Every other source is written **document/literal wrapped** (WS-I Basic Profile): each operation has
a request element named after it, carrying its parameters and request body, a ``<op>Response``
element carrying the response body, and one element per fault.

**Names.** Names that are not legal XML ``NCName`` s are rewritten and de-duplicated; each change is
reported. The HTTP method and path of a REST operation are not carried (reported).
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, rename_verdict
from .lossiness import LossinessKind, LossinessSeverity
from .xsd_types import ncname, xsd_builtin, xsd_pattern

__all__ = ["WsdlEmitOptions", "WsdlEmitter", "WsdlFidelityRulePack"]

_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_SOAP_NS = "http://schemas.xmlsoap.org/wsdl/soap/"
_SOAP12_NS = "http://schemas.xmlsoap.org/wsdl/soap12/"
_HTTP_NS = "http://schemas.xmlsoap.org/wsdl/http/"
_SOAP12_PREFIX = "soap12"
_HTTP_PREFIX = "http"
_TNS_PREFIX = "tns"
_XSD_PREFIX = "xsd"
_SOAP_PREFIX = "soap"
_WSDL_PREFIX = "wsdl"

#: The source format whose messages, parts and topology the emitter writes back as they were read.
_WSDL_FORMAT = "wsdl"

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

#: XSD built-ins that take length facets, and those that take range facets.
_LENGTH_BASES = frozenset({"string", "normalizedString", "token", "anyURI", "base64Binary", "hexBinary"})
_RANGE_BASES = frozenset(
    {
        "decimal", "integer", "long", "int", "short", "byte", "unsignedLong", "unsignedInt",
        "unsignedShort", "unsignedByte", "float", "double", "dateTime", "date", "time",
        "nonNegativeInteger", "positiveInteger", "nonPositiveInteger", "negativeInteger",
    }
)


class WsdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for WSDL export.

    On top of the capability rules: names that are not legal ``NCName`` s are reported as renames;
    a map is written as a list of entries; an untyped value becomes ``xs:anyType``; ``multipleOf``,
    ``uniqueItems`` and ``deprecated`` have no XSD form; a REST operation loses its HTTP method and
    path.
    """

    target_label = "WSDL"

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The target namespace every type, element and operation is qualified by.

        A re-import keys each construct by that namespace (``Money`` becomes
        ``<namespace>.Money``), so the report says which namespace was used — and that it was
        invented when the source gave none. A WSDL source already has one: nothing changes.
        """
        if api.format == _WSDL_FORMAT and api.extras.get("wsdl_target_namespace"):
            return []
        namespace = _target_namespace(api)
        if api.identity.namespace:
            return [
                FidelityVerdict.approx(
                    message=f"WSDL qualifies every type, element and operation by a target namespace; "
                    f"the source namespace {namespace!r} is used",
                    severity=LossinessSeverity.INFO,
                    target_mapping=f"names → {namespace}",
                )
            ]
        return [
            FidelityVerdict.synth(
                message=f"WSDL requires a target namespace and the source has none; {namespace!r} is used, "
                "and every type, element and operation is qualified by it",
                severity=LossinessSeverity.INFO,
                target_mapping=f"targetNamespace → {namespace}",
            )
        ]

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        verdict = super().operation_verdict(operation)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        emitted = ncname(operation.name or operation.key, fallback="operation")
        if operation.http_method:
            return FidelityVerdict.approx(
                message=f"WSDL has no HTTP method or path; {operation.http_method} "
                f"{operation.http_path or ''} is written as the SOAP operation {emitted!r}".replace("  ", " "),
                severity=LossinessSeverity.INFO,
                target_mapping=f"{operation.http_method} {operation.http_path or ''} → {emitted}".strip(),
            )
        return (
            rename_verdict(operation.name, emitted, target_label=self.target_label, noun="operation")
            or verdict
        )

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        if type_.kind is TypeKind.MAP:
            return FidelityVerdict.approx(
                message="XSD has no map type; the map is written as a list of key/value entry elements",
                severity=LossinessSeverity.INFO,
                target_mapping="map → sequence of entry",
            )
        return (
            rename_verdict(
                type_.name, ncname(type_.name, pascal=True, fallback="Type"),
                target_label=self.target_label, noun="type",
            )
            or verdict
        )

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        verdicts = super().field_verdicts(field)
        renamed = rename_verdict(
            field.name, ncname(field.name, fallback="field"), target_label=self.target_label, noun="element"
        )
        if renamed:
            verdicts.append(renamed)
        if field.type.name is None and field.type.item is None:
            verdicts.append(
                FidelityVerdict.approx(
                    message="The field has no declared type; it is written as xs:anyType",
                    severity=LossinessSeverity.INFO,
                    target_mapping="untyped → xs:anyType",
                )
            )
        unsupported = _unsupported_facets(field.constraints)
        if unsupported:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"XSD has no facet for {', '.join(unsupported)}; the rule is not written",
                    target_mapping=f"{', '.join(unsupported)} → dropped",
                )
            )
        if field.deprecated:
            verdicts.append(
                FidelityVerdict.drop(
                    message="XSD has no deprecation marker; the field's deprecated flag is dropped",
                    severity=LossinessSeverity.INFO,
                )
            )
        return verdicts


class WsdlEmitOptions(EmitOptions):
    """Per-target options for :class:`WsdlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated WSDL.",
    )
    layout: Literal["bundle", "single"] = Field(
        default="bundle",
        description="`bundle` writes the WSDL and its XSD types as two files joined by an "
        "`xsd:import`; `single` inlines the schema in the WSDL.",
    )


class WsdlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a WSDL 1.1 description with XSD types."""

    key = "wsdl"
    format = "wsdl"
    label = "WSDL"
    description = "Export as a SOAP WSDL 1.1 web service description with XSD types."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = True
    options_model = WsdlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/wsdl+xml"
    SCHEMA_MEDIA_TYPE = "application/xml"

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
        return WsdlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[WsdlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, WsdlEmitOptions)
            else WsdlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _WsdlWriter(api, options)
        wsdl_text, schema_text = writer.render()
        files = [EmittedFile(path=writer.output_path, content=wsdl_text, media_type=self.OUTPUT_MEDIA_TYPE)]
        if schema_text is not None:
            files.append(
                EmittedFile(path=writer.schema_path, content=schema_text, media_type=self.SCHEMA_MEDIA_TYPE)
            )
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


@dataclass
class _WrappedOperation:
    """The names a document/literal-wrapped operation is written under."""

    name: str
    request_element: str
    response_element: str
    #: ``(fault name, message and element name)`` per error message.
    faults: List[Tuple[str, str]] = dataclass_field(default_factory=list)


class _NameScope:
    """Names already used in one XML symbol space; later claimants get a numeric suffix."""

    def __init__(self) -> None:
        self._taken: Set[str] = set()

    def claim(self, name: str) -> str:
        candidate, suffix = name, 2
        while candidate in self._taken:
            candidate, suffix = f"{name}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate


class _WsdlWriter:
    def __init__(self, api: CanonicalApi, options: WsdlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self._message_types = {t.key: t for t in api.types if t.extras.get("wsdl_kind") == "message"}
        self.output_path = _output_path(api)
        self.schema_path = re.sub(r"\.wsdl$", ".xsd", self.output_path)
        self._target_ns = _target_namespace(api)
        #: A WSDL source keeps its own messages, parts and topology; everything else is wrapped.
        self._wsdl_source = api.format == _WSDL_FORMAT
        self._type_scope = _NameScope()
        self._element_scope = _NameScope()
        self._type_names: Dict[str, str] = {}
        self._service_names: Dict[str, str] = {}
        self._operation_names: Dict[str, str] = {}
        self._wrapped: Dict[str, _WrappedOperation] = {}
        self._plan_names()

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def _rename(self, source: str, emitted: str, pointer: str, noun: str) -> str:
        """Report ``source`` → ``emitted`` when they differ, and return ``emitted``."""
        if source != emitted:
            self.losses.record(
                LossKind.INFERRED,
                "renamed-identifier",
                f"WSDL {noun} names must be XML NCNames; {source!r} is written as {emitted!r}.",
                pointer=pointer,
            )
        return emitted

    def _plan_names(self) -> None:
        """Give every type, port type and operation a legal, unique name before writing."""
        for type_ in self._api.types:
            if type_.key in self._message_types:
                continue
            name = self._type_scope.claim(ncname(type_.name, pascal=True, fallback="Type"))
            self._type_names[type_.key] = self._rename(type_.name, name, type_.key, "type")
        service_scope = _NameScope()
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS and not self._wsdl_source:
                    self.losses.record(
                        LossKind.NA,
                        "event-operation-dropped",
                        f"Operation {operation.key!r} is an event; WSDL has no representation for it.",
                        pointer=operation.key,
                    )
            name = service_scope.claim(ncname(service.name, pascal=True, fallback="Service"))
            self._service_names[service.key] = self._rename(service.name, name, service.key, "port type")
            operation_scope = _NameScope()
            for operation in self._operations(service):
                name = operation_scope.claim(ncname(operation.name or operation.key, fallback="operation"))
                self._operation_names[operation.key] = self._rename(
                    operation.name, name, operation.key, "operation"
                )

    def _operations(self, service: Service) -> List[Operation]:
        """The service's operations to write.

        A WSDL source keeps every operation (an out-only or robust-out-only one is a WSDL 1.1
        notification). For any other source, publish/subscribe operations are dropped and reported
        in planning.
        """
        if self._wsdl_source:
            return list(service.operations)
        return [operation for operation in service.operations if operation.kind not in _EVENT_OPERATION_KINDS]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self) -> Tuple[str, Optional[str]]:
        """Render the WSDL, and the XSD when the layout is ``bundle``.

        Returns:
            ``(wsdl text, xsd text or None)``.
        """
        ET.register_namespace(_WSDL_PREFIX, _WSDL_NS)
        ET.register_namespace(_XSD_PREFIX, _XSD_NS)
        ET.register_namespace(_SOAP_PREFIX, _SOAP_NS)
        ET.register_namespace(_SOAP12_PREFIX, _SOAP12_NS)
        ET.register_namespace(_HTTP_PREFIX, _HTTP_NS)

        schema_el = self._build_schema()

        root = ET.Element(
            ET.QName(_WSDL_NS, "definitions"),
            {
                "name": ncname(self._api.identity.name or "Service", pascal=True, fallback="Service"),
                "targetNamespace": self._target_ns,
                # `tns:` appears only in attribute values, which ElementTree never declares.
                f"xmlns:{_TNS_PREFIX}": self._target_ns,
            },
        )
        types_el = ET.SubElement(root, ET.QName(_WSDL_NS, "types"))
        bundle = self._options.layout == "bundle"
        if bundle:
            # WS-I BP R2105: a schema whose only child is an import needs no targetNamespace.
            wrapper = ET.SubElement(types_el, ET.QName(_XSD_NS, "schema"))
            ET.SubElement(
                wrapper,
                ET.QName(_XSD_NS, "import"),
                {"namespace": self._target_ns, "schemaLocation": self.schema_path},
            )
        else:
            types_el.append(schema_el)

        self._append_messages(root)
        self._append_port_types(root)

        topology = [server for server in self._api.servers if server.extras.get("wsdl_binding")]
        if topology:
            self._append_topology(root, topology)
        else:
            for service in self._api.services:
                port_type = self._service_names[service.key]
                binding_name = f"{port_type}Binding"
                self._append_binding(
                    root,
                    binding_name,
                    service=service,
                    protocol="soap11",
                    transport="http://schemas.xmlsoap.org/soap/http",
                )
                service_el = ET.SubElement(root, ET.QName(_WSDL_NS, "service"), {"name": f"{port_type}Service"})
                port_el = ET.SubElement(
                    service_el,
                    ET.QName(_WSDL_NS, "port"),
                    {"name": port_type, "binding": f"{_TNS_PREFIX}:{binding_name}"},
                )
                server_url = self._api.servers[0].url if self._api.servers else "https://api.example.com/service"
                ET.SubElement(port_el, ET.QName(_SOAP_NS, "address"), {"location": server_url})

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "WSDL export omits event/channel constructs",
                pointer="channels",
            )

        header = ""
        if self._options.include_comments:
            title = self._api.identity.name or "Exported service"
            header = f"<!-- Generated WSDL for {_comment_safe(title)} -->\n"
        wsdl_text = f"{header}{ET.tostring(root, encoding='unicode')}\n"
        schema_text = None
        if bundle:
            schema_header = header.replace("Generated WSDL", "Generated XSD types") if header else ""
            schema_text = f"{schema_header}{ET.tostring(schema_el, encoding='unicode')}\n"
        return wsdl_text, schema_text

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _build_schema(self) -> ET.Element:
        """The ``xsd:schema`` holding every type and element of the export."""
        schema_el = ET.Element(
            ET.QName(_XSD_NS, "schema"),
            {"targetNamespace": self._target_ns, f"xmlns:{_TNS_PREFIX}": self._target_ns},
        )
        #: Where an XSD-sourced field's named simple type is written (once, at schema level).
        self._schema_el = schema_el
        self._simple_types_written: Set[str] = set()
        elements_written: Set[str] = set()
        for type_ in self._api.types:
            if type_.key in self._message_types:
                continue
            complex_type = self._append_type(schema_el, type_)
            if complex_type:
                name = self._type_names[type_.key]
                element = self._element_scope.claim(name)
                ET.SubElement(
                    schema_el, ET.QName(_XSD_NS, "element"), {"name": element, "type": f"{_TNS_PREFIX}:{name}"}
                )
                elements_written.add(element)
        # MFI-13.2: a multi-part message's parts that name elements.
        for type_ in self._message_types.values():
            for field in type_.fields:
                element = field.extras.get("wsdl_part_element")
                if element and element not in elements_written:
                    ET.SubElement(
                        schema_el,
                        ET.QName(_XSD_NS, "element"),
                        {"name": element, "type": self._xsd_type(field.type, hint=field.extras.get("xsd_type"))},
                    )
                    elements_written.add(element)
                    self._element_scope.claim(element)
            self.tracker.record(type_.key, Provenance.SOURCE)
        if not self._wsdl_source:
            for service in self._api.services:
                for operation in self._operations(service):
                    self._append_wrapper_elements(schema_el, operation)
        return schema_el

    def _append_type(self, schema_el: ET.Element, type_: Type) -> bool:
        """Write one named type; return whether it is a complex type (and so gets an element)."""
        name = self._type_names[type_.key]
        self.tracker.record(type_.key, Provenance.SOURCE)
        if type_.kind is TypeKind.ENUM:
            self._append_enum(schema_el, type_, name)
            return False
        if type_.kind is TypeKind.SCALAR:
            fmt = type_.constraints.format if type_.constraints is not None else None
            base = xsd_builtin(type_.name, fmt) or "string"
            simple = ET.SubElement(schema_el, ET.QName(_XSD_NS, "simpleType"), {"name": name})
            _annotate(simple, type_.description)
            self._append_facets(
                ET.SubElement(simple, ET.QName(_XSD_NS, "restriction"), {"base": f"{_XSD_PREFIX}:{base}"}),
                type_.constraints,
                base,
                pointer=type_.key,
            )
            return False
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            return self._append_alias(schema_el, type_, name)
        complex_el = ET.SubElement(schema_el, ET.QName(_XSD_NS, "complexType"), {"name": name})
        _annotate(complex_el, type_.description)
        if type_.kind is TypeKind.UNION:
            choice = ET.SubElement(complex_el, ET.QName(_XSD_NS, "choice"))
            self._append_union_members(choice, type_)
        elif type_.kind is TypeKind.MAP:
            self._append_map_body(complex_el, type_)
        else:
            sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
            scope = _NameScope()
            for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
                self._append_field(sequence_el, field, scope)
        return True

    def _append_enum(self, schema_el: ET.Element, type_: Type, name: str) -> None:
        """An enum: a ``simpleType`` restricting ``xs:int`` (all-integer values) or ``xs:string``."""
        values = [v.value if v.value is not None else v.name for v in type_.enum_values]
        integral = bool(values) and all(isinstance(v, int) and not isinstance(v, bool) for v in values)
        simple = ET.SubElement(schema_el, ET.QName(_XSD_NS, "simpleType"), {"name": name})
        _annotate(simple, type_.description)
        restriction = ET.SubElement(
            simple, ET.QName(_XSD_NS, "restriction"), {"base": f"{_XSD_PREFIX}:{'int' if integral else 'string'}"}
        )
        for value in values:
            ET.SubElement(restriction, ET.QName(_XSD_NS, "enumeration"), {"value": _literal(value)})

    def _append_alias(self, schema_el: ET.Element, type_: Type, name: str) -> bool:
        """An alias: a derived simple type, a list wrapper, or an extension of a complex type."""
        aliased = type_.aliased
        target = self._types_by_key.get(aliased.name or "") if aliased.item is None else None
        builtin = None if target is not None or aliased.item is not None else xsd_builtin(aliased.name)
        if builtin is not None or (target is not None and self._is_simple(target)):
            simple = ET.SubElement(schema_el, ET.QName(_XSD_NS, "simpleType"), {"name": name})
            _annotate(simple, type_.description)
            base = f"{_XSD_PREFIX}:{builtin}" if builtin else f"{_TNS_PREFIX}:{self._type_names[target.key]}"
            ET.SubElement(simple, ET.QName(_XSD_NS, "restriction"), {"base": base})
            return False
        complex_el = ET.SubElement(schema_el, ET.QName(_XSD_NS, "complexType"), {"name": name})
        _annotate(complex_el, type_.description)
        if target is not None:
            content = ET.SubElement(complex_el, ET.QName(_XSD_NS, "complexContent"))
            ET.SubElement(
                content, ET.QName(_XSD_NS, "extension"), {"base": f"{_TNS_PREFIX}:{self._type_names[target.key]}"}
            )
        else:
            sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
            self._append_value(sequence_el, "item", aliased, pointer=type_.key, optional=False)
        return True

    def _append_union_members(self, choice: ET.Element, type_: Type) -> None:
        """A union's ``xs:choice``: its fields (a oneof), else one element per member type."""
        scope = _NameScope()
        if type_.fields:
            for field in type_.fields:
                self._append_field(choice, field, scope, in_choice=True)
            return
        for member in type_.union_members:
            target = self._types_by_key.get(member)
            local = target.name if target is not None else member.split(".")[-1]
            element = scope.claim(ncname(local[:1].lower() + local[1:], fallback="variant"))
            self._append_value(choice, element, TypeRef(name=member), pointer=type_.key, optional=False)

    def _append_map_body(self, complex_el: ET.Element, type_: Type) -> None:
        """A map: a sequence of ``entry`` elements, each a ``key`` and a ``value``."""
        self.losses.record(
            LossKind.INFERRED,
            "map-as-entry-list",
            f"Map {type_.key!r} is written as a list of key/value entry elements.",
            pointer=type_.key,
        )
        sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
        entry = ET.SubElement(
            sequence_el, ET.QName(_XSD_NS, "element"), {"name": "entry", "minOccurs": "0", "maxOccurs": "unbounded"}
        )
        entry_sequence = _anonymous_sequence(entry)
        self._append_value(
            entry_sequence, "key", type_.key_type or TypeRef(name="string"), pointer=type_.key, optional=False
        )
        self._append_value(
            entry_sequence, "value", type_.value_type or TypeRef(name="string"), pointer=type_.key, optional=False
        )

    # ------------------------------------------------------------------
    # Fields and values
    # ------------------------------------------------------------------

    def _append_field(
        self, parent: ET.Element, field: CanonicalField, scope: _NameScope, *, in_choice: bool = False
    ) -> None:
        """Write one record (or union) field as an element."""
        extras = field.extras or {}
        name = scope.claim(ncname(field.name, fallback="field"))
        self._rename(field.name, name, field.key, "element")
        if field.deprecated:
            self.losses.record(
                LossKind.NA, "deprecated-dropped",
                f"XSD has no deprecation marker; {field.key!r} is written without one.", pointer=field.key,
            )
        unsupported = _unsupported_facets(field.constraints)
        if unsupported:
            self.losses.record(
                LossKind.NA, "unsupported-facet",
                f"XSD has no facet for {', '.join(unsupported)}; the rule on {field.key!r} is not written.",
                pointer=field.key,
            )
        self.tracker.record(field.key, Provenance.SOURCE)
        if "xsd_type" in extras:
            self._append_xsd_source_field(parent, field, name)
            return
        fmt = field.constraints.format if field.constraints is not None else None
        self._append_value(
            parent,
            name,
            field.type,
            fmt=fmt,
            constraints=field.constraints,
            default=field.default,
            description=field.description,
            optional=field.type.nullable and not in_choice,
            pointer=field.key,
        )

    def _append_xsd_source_field(self, parent: ET.Element, field: CanonicalField, name: str) -> None:
        """A field imported from XSD: written back with the occurrence and facets it was read with."""
        extras = field.extras
        attributes = {"name": name}
        facets = extras.get("xsd_facets")
        simple_type = extras.get("xsd_simple_type")
        base = extras.get("xsd_base")
        if base and simple_type:
            # A named simple type: written once at schema level, referenced by name.
            attributes["type"] = f"{_TNS_PREFIX}:{simple_type}"
            if simple_type not in self._simple_types_written:
                self._simple_types_written.add(simple_type)
                named = ET.SubElement(self._schema_el, ET.QName(_XSD_NS, "simpleType"), {"name": simple_type})
                self._append_restriction(named, base, facets)
        elif not base:
            attributes["type"] = self._xsd_type(field.type, hint=extras.get("xsd_type"))
        # MFI-13.5: the element's occurrence, nillability and default, as the source stated them.
        for key, attribute in (
            ("xsd_min_occurs", "minOccurs"),
            ("xsd_max_occurs", "maxOccurs"),
            ("xsd_nillable", "nillable"),
            ("xsd_default", "default"),
        ):
            if extras.get(key) is not None:
                attributes[attribute] = str(extras[key])
        element_el = ET.SubElement(parent, ET.QName(_XSD_NS, "element"), attributes)
        if base and not simple_type:
            # An inline restriction of a built-in type.
            inline = ET.SubElement(element_el, ET.QName(_XSD_NS, "simpleType"))
            self._append_restriction(inline, base, facets)

    def _append_value(
        self,
        parent: ET.Element,
        name: str,
        ref: TypeRef,
        *,
        pointer: str,
        optional: bool,
        fmt: Optional[str] = None,
        constraints: Optional[Constraints] = None,
        default: Any = None,
        description: Optional[str] = None,
    ) -> ET.Element:
        """Write ``ref`` as an element named ``name``: lists repeat, scalars keep facets.

        Args:
            parent: The ``sequence`` / ``choice`` the element joins.
            name: The element's (legal) name.
            ref: Its type.
            pointer: The construct key, for loss records.
            optional: Write ``minOccurs="0" nillable="true"`` (a nullable value).
            fmt: The ``format`` that picks a scalar's XSD type.
            constraints: Facets to write (and, for lists, ``minItems``/``maxItems``).
            default: A scalar default (``default`` attribute).
            description: Written as ``xs:annotation``.

        Returns:
            The element written.
        """
        attributes: Dict[str, str] = {"name": name}
        if ref.item is not None:
            attributes["minOccurs"] = str(constraints.min_items) if constraints and constraints.min_items else "0"
            attributes["maxOccurs"] = (
                str(constraints.max_items) if constraints and constraints.max_items else "unbounded"
            )
            if ref.item.item is not None:
                # A list of lists: XSD has no nested occurrence, so the inner list gets a wrapper.
                element = ET.SubElement(parent, ET.QName(_XSD_NS, "element"), attributes)
                _annotate(element, description)
                inner = _anonymous_sequence(element)
                self._append_value(inner, "item", ref.item, pointer=pointer, optional=False, fmt=fmt)
                return element
            attributes["type"] = self._type_qname(ref.item, fmt, pointer)
            element = ET.SubElement(parent, ET.QName(_XSD_NS, "element"), attributes)
            _annotate(element, description)
            return element
        if optional:
            attributes["minOccurs"] = "0"
            attributes["nillable"] = "true"
        builtin = self._builtin(ref, fmt)
        if default is not None and builtin is not None and not isinstance(default, (dict, list)):
            attributes["default"] = _literal(default)
        if builtin is not None and _has_facets(constraints, builtin):
            element = ET.SubElement(parent, ET.QName(_XSD_NS, "element"), attributes)
            _annotate(element, description)
            restriction = ET.SubElement(
                ET.SubElement(element, ET.QName(_XSD_NS, "simpleType")),
                ET.QName(_XSD_NS, "restriction"),
                {"base": f"{_XSD_PREFIX}:{builtin}"},
            )
            self._append_facets(restriction, constraints, builtin, pointer=pointer)
            return element
        attributes["type"] = self._type_qname(ref, fmt, pointer)
        element = ET.SubElement(parent, ET.QName(_XSD_NS, "element"), attributes)
        _annotate(element, description)
        return element

    def _append_facets(
        self, restriction: ET.Element, constraints: Optional[Constraints], base: str, *, pointer: str
    ) -> None:
        """Write the restriction facets ``base`` accepts; the order is free in XSD 1.0."""
        if constraints is None:
            return
        for facet, value in _facets(constraints, base):
            ET.SubElement(restriction, ET.QName(_XSD_NS, facet), {"value": _literal(value)})

    @staticmethod
    def _append_restriction(simple_type_el: ET.Element, base: str, facets: Any) -> None:
        """Write ``<xs:restriction base="xs:<base>">`` with its facets under a ``simpleType``."""
        restriction = ET.SubElement(simple_type_el, ET.QName(_XSD_NS, "restriction"), {"base": f"{_XSD_PREFIX}:{base}"})
        for facet, value in (facets or {}).items():
            for item in value if isinstance(value, list) else [value]:
                ET.SubElement(restriction, ET.QName(_XSD_NS, facet), {"value": str(item)})

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def _is_simple(self, type_: Type) -> bool:
        """Whether a named type is written as an XSD ``simpleType``."""
        if type_.kind in (TypeKind.ENUM, TypeKind.SCALAR):
            return True
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None and type_.aliased.item is None:
            target = self._types_by_key.get(type_.aliased.name or "")
            if target is None:
                return xsd_builtin(type_.aliased.name) is not None
            return target is not type_ and self._is_simple(target)
        return False

    def _builtin(self, ref: TypeRef, fmt: Optional[str]) -> Optional[str]:
        """The XSD built-in ``ref`` maps to, or ``None`` for a named type."""
        if not ref.name or ref.name in self._type_names:
            return None
        return xsd_builtin(ref.name, fmt)

    def _type_qname(self, ref: TypeRef, fmt: Optional[str], pointer: str) -> str:
        """The ``type=`` value for ``ref``: ``tns:<Type>``, ``xsd:<builtin>`` or a fallback."""
        if ref.item is not None:
            # Only reached for a list nested where XSD has no slot; carried as any content.
            return f"{_XSD_PREFIX}:anyType"
        if not ref.name:
            self.losses.record(
                LossKind.INFERRED, "untyped-value",
                f"{pointer!r} has no declared type; it is written as xs:anyType.", pointer=pointer,
            )
            return f"{_XSD_PREFIX}:anyType"
        if ref.name in self._type_names:
            return f"{_TNS_PREFIX}:{self._type_names[ref.name]}"
        builtin = xsd_builtin(ref.name, fmt)
        if builtin is not None:
            return f"{_XSD_PREFIX}:{builtin}"
        self.losses.record(
            LossKind.INFERRED, "unmapped-type",
            f"{ref.name!r} is not an XSD type or a type in this model; it is written as xs:string.",
            pointer=pointer,
        )
        return f"{_XSD_PREFIX}:string"

    def _xsd_type(self, ref: TypeRef, *, hint: Optional[str] = None) -> str:
        """The ``type=`` value for a field or part imported from WSDL (keeps imported names)."""
        if ref.name:
            mapped = xsd_builtin(ref.name, xsd_hint=hint) if hint else None
            if mapped:
                return f"{_XSD_PREFIX}:{mapped}"
            if ref.name in self._type_names:
                return f"{_TNS_PREFIX}:{self._type_names[ref.name]}"
            mapped = xsd_builtin(ref.name)
            if mapped:
                return f"{_XSD_PREFIX}:{mapped}"
            return f"{_TNS_PREFIX}:{ref.name.split('.')[-1]}"
        return f"{_XSD_PREFIX}:string"

    # ------------------------------------------------------------------
    # Operations (document/literal wrapped, for non-WSDL sources)
    # ------------------------------------------------------------------

    def _append_wrapper_elements(self, schema_el: ET.Element, operation: Operation) -> None:
        """Write an operation's request, response and fault elements (WS-I wrapped convention)."""
        name = self._operation_names[operation.key]
        if operation.http_method:
            self.losses.record(
                LossKind.NA,
                "http-binding-dropped",
                f"{operation.http_method} {operation.http_path or ''} is written as the SOAP operation "
                f"{name!r}; WSDL does not carry the HTTP method and path.".replace("  ", " "),
                pointer=operation.key,
            )
        plan = _WrappedOperation(
            name=name,
            request_element=self._element_scope.claim(name),
            response_element=self._element_scope.claim(f"{name}Response"),
        )

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        request_sequence = self._wrapper(schema_el, plan.request_element)
        scope = _NameScope()
        for parameter in operation.parameters:
            element = scope.claim(ncname(parameter.name, fallback="param"))
            self._rename(parameter.name, element, parameter.key, "element")
            fmt = parameter.constraints.format if parameter.constraints is not None else None
            self._append_value(
                request_sequence,
                element,
                parameter.type,
                fmt=fmt,
                constraints=parameter.constraints,
                default=parameter.default,
                description=parameter.description,
                optional=not parameter.required,
                pointer=parameter.key,
            )
        if request is not None and request.payload is not None:
            self._append_value(
                request_sequence, scope.claim("body"), request.payload,
                optional=not request.required, pointer=request.key,
            )
        elif request is not None and request.payload_schema:
            self.losses.record(
                LossKind.INFERRED, "inline-payload",
                f"The request body of {operation.key!r} is an inline schema; it is written as xs:anyType.",
                pointer=request.key,
            )
            self._append_value(
                request_sequence, scope.claim("body"), TypeRef(), optional=not request.required, pointer=request.key
            )

        response_sequence = self._wrapper(schema_el, plan.response_element)
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        response = next((m for m in responses if m.payload is not None), None)
        if response is not None:
            self._append_value(response_sequence, "result", response.payload, optional=False, pointer=response.key)

        fault_scope = _NameScope()
        for message in operation.messages:
            if message.role is not MessageRole.ERROR:
                continue
            # A fault named only by its status (`404`) reads as `Status404`, not `_404`.
            raw = message.name or (f"Status{message.status_code}" if message.status_code else "Fault")
            label = ncname(raw, pascal=True, fallback="Fault")
            fault = fault_scope.claim(label)
            element = self._element_scope.claim(f"{name}{fault[:1].upper()}{fault[1:]}Fault")
            detail = self._wrapper(schema_el, element)
            if message.payload is not None:
                self._append_value(detail, "detail", message.payload, optional=False, pointer=message.key)
            plan.faults.append((fault, element))
        self._wrapped[operation.key] = plan

    @staticmethod
    def _wrapper(schema_el: ET.Element, name: str) -> ET.Element:
        """A global element with an anonymous ``complexType``; returns its ``sequence``."""
        return _anonymous_sequence(ET.SubElement(schema_el, ET.QName(_XSD_NS, "element"), {"name": name}))

    # ------------------------------------------------------------------
    # WSDL messages, port types, bindings
    # ------------------------------------------------------------------

    def _append_messages(self, root: ET.Element) -> None:
        messages_written: Set[str] = set()
        for service in self._api.services:
            for operation in self._operations(service):
                if not self._wsdl_source:
                    plan = self._wrapped[operation.key]
                    for message_name, element, part in (
                        (f"{plan.name}Request", plan.request_element, "parameters"),
                        (f"{plan.name}Response", plan.response_element, "parameters"),
                        *((element, element, "fault") for _, element in plan.faults),
                    ):
                        if message_name in messages_written:
                            continue
                        messages_written.add(message_name)
                        message_el = ET.SubElement(root, ET.QName(_WSDL_NS, "message"), {"name": message_name})
                        ET.SubElement(
                            message_el,
                            ET.QName(_WSDL_NS, "part"),
                            {"name": part, "element": f"{_TNS_PREFIX}:{element}"},
                        )
                    continue
                for message, name in self._operation_messages(operation):
                    if name not in messages_written:
                        messages_written.add(name)
                        self._message_element(root, name, message)

    def _append_port_types(self, root: ET.Element) -> None:
        for service in self._api.services:
            port_type_el = ET.SubElement(
                root, ET.QName(_WSDL_NS, "portType"), {"name": self._service_names[service.key]}
            )
            self.tracker.record(service.key, Provenance.SOURCE)
            for operation in self._operations(service):
                op_el = ET.SubElement(
                    port_type_el, ET.QName(_WSDL_NS, "operation"), {"name": self._operation_names[operation.key]}
                )
                if not self._wsdl_source:
                    plan = self._wrapped[operation.key]
                    for direction, suffix in (("input", "Request"), ("output", "Response")):
                        ET.SubElement(
                            op_el, ET.QName(_WSDL_NS, direction), {"message": f"{_TNS_PREFIX}:{plan.name}{suffix}"}
                        )
                    for fault, element in plan.faults:
                        ET.SubElement(
                            op_el, ET.QName(_WSDL_NS, "fault"), {"name": fault, "message": f"{_TNS_PREFIX}:{element}"}
                        )
                else:
                    for message, name in self._operation_messages(operation):
                        if message.role is MessageRole.REQUEST:
                            ET.SubElement(op_el, ET.QName(_WSDL_NS, "input"), {"message": f"{_TNS_PREFIX}:{name}"})
                        elif message.role is MessageRole.RESPONSE:
                            ET.SubElement(op_el, ET.QName(_WSDL_NS, "output"), {"message": f"{_TNS_PREFIX}:{name}"})
                        else:
                            ET.SubElement(
                                op_el,
                                ET.QName(_WSDL_NS, "fault"),
                                {"name": message.name or "fault", "message": f"{_TNS_PREFIX}:{name}"},
                            )
                self.tracker.record(
                    operation.key,
                    Provenance.SOURCE if self._wsdl_source else Provenance.INFERRED,
                    None if self._wsdl_source else "document/literal wrapped operation",
                )

    def _fault_names(self, operation: Operation) -> List[str]:
        """The fault names an operation's binding lists, in the port type's order."""
        if not self._wsdl_source:
            return [fault for fault, _ in self._wrapped[operation.key].faults]
        return [message.name or "fault" for message in operation.messages if message.role is MessageRole.ERROR]

    def _operation_messages(self, operation: Operation) -> List[Tuple[Message, str]]:
        """A WSDL-sourced operation's messages with the WSDL ``message`` name each is written under.

        Request / response use the first message of the role that has a payload (named after a
        multi-part message's original name, else ``<op>Input`` / ``<op>Output``); every ``error``
        message is a fault (``<op><fault>Fault``).
        """
        out: List[Tuple[Message, str]] = []
        for role, suffix in ((MessageRole.REQUEST, "Input"), (MessageRole.RESPONSE, "Output")):
            message = next((m for m in operation.messages if m.role is role and m.payload), None)
            if message is not None and message.payload is not None:
                message_type = self._message_types.get(message.payload.name or "")
                name = str(message_type.extras.get("wsdl_message")) if message_type else f"{operation.name}{suffix}"
                if message_type is not None or self._payload_type_name(message.payload):
                    out.append((message, name))
        for message in operation.messages:
            if message.role is MessageRole.ERROR:
                out.append((message, f"{operation.name}{message.name or 'Fault'}Fault"))
        return out

    def _append_binding(
        self,
        root: ET.Element,
        name: str,
        *,
        service: Optional[Service],
        protocol: Optional[str],
        transport: Optional[str],
    ) -> None:
        """Write one ``binding`` of ``service``'s port type over ``protocol`` (``soap11`` / ``soap12`` / ``http``)."""
        port_type = self._service_names[service.key] if service is not None else ""
        binding_el = ET.SubElement(
            root, ET.QName(_WSDL_NS, "binding"), {"name": name, "type": f"{_TNS_PREFIX}:{port_type}"}
        )
        operations = self._operations(service) if service is not None else []
        if protocol == "http":
            ET.SubElement(binding_el, ET.QName(_HTTP_NS, "binding"), {"verb": "POST"})
            for operation in operations:
                op_name = self._operation_names[operation.key]
                bind_op = ET.SubElement(binding_el, ET.QName(_WSDL_NS, "operation"), {"name": op_name})
                ET.SubElement(bind_op, ET.QName(_HTTP_NS, "operation"), {"location": f"/{op_name}"})
            return
        soap_ns = _SOAP12_NS if protocol == "soap12" else _SOAP_NS
        soap_binding = {"style": "document"}
        if transport:
            soap_binding["transport"] = transport
        ET.SubElement(binding_el, ET.QName(soap_ns, "binding"), soap_binding)
        for operation in operations:
            bind_op = ET.SubElement(
                binding_el, ET.QName(_WSDL_NS, "operation"), {"name": self._operation_names[operation.key]}
            )
            # MFI-13.5: the operation's recorded soapAction (empty when the source stated none),
            # and an `rpc` style when the source's binding used one, so a re-import grades alike.
            soap_operation = {"soapAction": str(operation.extras.get("wsdl_soap_action") or "")}
            if operation.extras.get("wsdl_soap_style") == "rpc":
                soap_operation["style"] = "rpc"
            ET.SubElement(bind_op, ET.QName(soap_ns, "operation"), soap_operation)
            for direction in ("input", "output"):
                ET.SubElement(
                    ET.SubElement(bind_op, ET.QName(_WSDL_NS, direction)),
                    ET.QName(soap_ns, "body"),
                    {"use": "literal"},
                )
            for fault in self._fault_names(operation):
                fault_el = ET.SubElement(bind_op, ET.QName(_WSDL_NS, "fault"), {"name": fault})
                ET.SubElement(fault_el, ET.QName(soap_ns, "fault"), {"name": fault, "use": "literal"})

    def _append_topology(self, root: ET.Element, servers: List[Server]) -> None:
        """Write the bindings, services and ports the servers record (MFI-13.2)."""
        services_by_port_type = {self._service_names[s.key]: s for s in self._api.services}
        bindings_written: set = set()
        for server in servers:
            binding = str(server.extras["wsdl_binding"])
            if binding in bindings_written:
                continue
            bindings_written.add(binding)
            self._append_binding(
                root,
                binding,
                service=services_by_port_type.get(str(server.extras.get("wsdl_port_type") or "")),
                protocol=server.protocol,
                transport=server.extras.get("wsdl_transport"),
            )
        services: Dict[str, ET.Element] = {}
        for server in servers:
            service_name = str(server.extras.get("wsdl_service") or "Service")
            if service_name not in services:
                services[service_name] = ET.SubElement(root, ET.QName(_WSDL_NS, "service"), {"name": service_name})
            port_el = ET.SubElement(
                services[service_name],
                ET.QName(_WSDL_NS, "port"),
                {"name": server.name or service_name, "binding": f"{_TNS_PREFIX}:{server.extras['wsdl_binding']}"},
            )
            address_ns = {"soap12": _SOAP12_NS, "http": _HTTP_NS}.get(server.protocol or "", _SOAP_NS)
            ET.SubElement(port_el, ET.QName(address_ns, "address"), {"location": server.url})

    def _message_element(self, root: ET.Element, name: str, message: Message) -> ET.Element:
        """Write a WSDL-sourced ``message``: a multi-part message's parts, else one ``parameters`` part."""
        message_el = ET.SubElement(root, ET.QName(_WSDL_NS, "message"), {"name": name})
        message_type = self._message_types.get(message.payload.name or "") if message.payload else None
        if message_type is not None:
            for field in sorted(message_type.fields, key=lambda f: f.field_number or 0):
                part = {"name": field.name}
                if field.extras.get("wsdl_part_element"):
                    part["element"] = f"{_TNS_PREFIX}:{field.extras['wsdl_part_element']}"
                else:
                    part["type"] = self._xsd_type(field.type, hint=field.extras.get("xsd_type"))
                ET.SubElement(message_el, ET.QName(_WSDL_NS, "part"), part)
            return message_el
        if message.payload is not None and message.payload.name and message.payload.name not in self._types_by_key:
            # A scalar payload (a fault carrying an `xs:string`) is a `type` part: no element names it.
            mapped = xsd_builtin(message.payload.name)
            if mapped:
                ET.SubElement(
                    message_el,
                    ET.QName(_WSDL_NS, "part"),
                    {"name": "parameters", "type": f"{_XSD_PREFIX}:{mapped}"},
                )
                return message_el
        type_name = self._payload_type_name(message.payload) if message.payload else None
        if type_name:
            ET.SubElement(
                message_el,
                ET.QName(_WSDL_NS, "part"),
                {"name": "parameters", "element": f"{_TNS_PREFIX}:{type_name}"},
            )
        return message_el

    def _payload_type_name(self, ref: TypeRef) -> Optional[str]:
        if not ref.name:
            return None
        if ref.name in self._type_names:
            return self._type_names[ref.name]
        return ref.name.split(".")[-1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unsupported_facets(constraints: Optional[Constraints]) -> List[str]:
    """Constraint keywords XSD has no facet for."""
    if constraints is None:
        return []
    names = []
    if constraints.multiple_of is not None:
        names.append("multipleOf")
    if constraints.unique_items:
        names.append("uniqueItems")
    if constraints.pattern and xsd_pattern(constraints.pattern) is None:
        names.append(f"the pattern {constraints.pattern!r}")
    return names


def _facets(constraints: Constraints, base: str) -> List[Tuple[str, Any]]:
    """The ``(facet, value)`` pairs ``constraints`` maps to on a restriction of ``base``."""
    pairs: List[Tuple[str, Any]] = []
    if base in _LENGTH_BASES:
        if constraints.min_length is not None:
            pairs.append(("minLength", constraints.min_length))
        if constraints.max_length is not None:
            pairs.append(("maxLength", constraints.max_length))
    if base in _RANGE_BASES:
        for facet, value in (
            ("minInclusive", constraints.minimum),
            ("maxInclusive", constraints.maximum),
            ("minExclusive", constraints.exclusive_minimum),
            ("maxExclusive", constraints.exclusive_maximum),
        ):
            if value is not None:
                pairs.append((facet, value))
    if constraints.pattern and xsd_pattern(constraints.pattern) is not None:
        pairs.append(("pattern", xsd_pattern(constraints.pattern)))
    for value in constraints.enum or []:
        if value is not None and not isinstance(value, (dict, list)):
            pairs.append(("enumeration", value))
    return pairs


def _has_facets(constraints: Optional[Constraints], base: str) -> bool:
    return constraints is not None and bool(_facets(constraints, base))


def _literal(value: Any) -> str:
    """A facet, enumeration or default value as XSD writes it (``true``, ``5``, ``2.5``)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def _anonymous_sequence(element: ET.Element) -> ET.Element:
    """Give ``element`` an anonymous ``complexType`` and return that type's ``sequence``."""
    return ET.SubElement(ET.SubElement(element, ET.QName(_XSD_NS, "complexType")), ET.QName(_XSD_NS, "sequence"))


def _annotate(element: ET.Element, description: Optional[str]) -> None:
    """Add ``<xs:annotation><xs:documentation>`` (it must be the element's first child)."""
    if description:
        annotation = ET.SubElement(element, ET.QName(_XSD_NS, "annotation"))
        ET.SubElement(annotation, ET.QName(_XSD_NS, "documentation")).text = description


def _comment_safe(text: str) -> str:
    """Text that cannot end an XML comment early (``--`` is not allowed inside one)."""
    return text.replace("--", "- -")


#: The target namespace written when the source has none (reported as synthesized).
_DEFAULT_TARGET_NAMESPACE = "http://example.com/service"


def _target_namespace(api: CanonicalApi) -> str:
    """The WSDL ``targetNamespace``: a WSDL source's own, the source namespace, or the default."""
    return str(
        api.extras.get("wsdl_target_namespace") or api.identity.namespace or _DEFAULT_TARGET_NAMESPACE
    )


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "service"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "service"
    return f"{safe}.wsdl"
