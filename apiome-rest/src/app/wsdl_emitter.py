"""WSDL emitter: canonical model → WSDL 1.1 + XSD (document/literal) — MFX-18.1, MFX-14.1 (#3889).

The inverse of :class:`app.wsdl_normalizer.WsdlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.

**Layout.** By default the export is a two-file bundle: ``<Name>.wsdl`` (messages, port types,
bindings, services) and ``<Name>.xsd`` (the types), joined by an ``xsd:import`` in ``wsdl:types``.
``layout="single"`` inlines the schema in the WSDL instead.

**Types → XSD** (the shared writer, :mod:`app.xsd_schema`, also used by WADL):

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

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Server,
    Service,
    Type,
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
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity
from .xsd_schema import (
    NameScope,
    XsdSchemaWriter,
    comment_safe,
    schema_field_verdicts,
    schema_type_verdict,
    target_namespace_verdicts,
)
from .xsd_types import ncname, xsd_builtin

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

#: Source formats whose importer numbers every field by its position in the sequence it was read from
#: (``app.wsdl_normalizer`` / ``app.xsd_normalizer``). The emitter writes fields in that order, so a
#: re-import assigns the same numbers: nothing is lost.
_POSITIONAL_FIELD_NUMBER_FORMATS = frozenset({_WSDL_FORMAT, "xsd"})

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})

class WsdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for WSDL export.

    On top of the capability rules: names that are not legal ``NCName`` s are reported as renames;
    a map is written as a list of entries; an untyped value becomes ``xs:anyType``; ``multipleOf``,
    ``uniqueItems`` and ``deprecated`` have no XSD form; a REST operation loses its HTTP method and
    path. A field number is kept when it is only a sequence position (a WSDL or XSD source) and
    dropped when it is a real one (Protobuf, Thrift, …).
    """

    target_label = "WSDL"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Note whether the source's field numbers are sequence positions, then run the drive loop."""
        self._positional_field_numbers = api.format in _POSITIONAL_FIELD_NUMBER_FORMATS
        return super().evaluate(api)

    def _field_identity_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        """A WSDL or XSD source's field number is its position, which the sequence keeps: not a loss.

        Args:
            field: The source field.

        Returns:
            ``None`` for a positional number (WSDL/XSD source), else the capability verdict — a ``DROP``
            for a real field number WSDL cannot carry.
        """
        if getattr(self, "_positional_field_numbers", False):
            return None
        return super()._field_identity_verdict(field)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The target namespace every type, element and operation is qualified by.

        A re-import keys each construct by that namespace (``Money`` becomes
        ``<namespace>.Money``), so the report says which namespace was used — and that it was
        invented when the source gave none. A WSDL source already has one: nothing changes.
        """
        return target_namespace_verdicts(
            api,
            target_label=self.target_label,
            namespace=_target_namespace(api),
            source_has_own=api.format == _WSDL_FORMAT and bool(api.extras.get("wsdl_target_namespace")),
        )

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

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The operation's verdict, plus an ``APPROX`` when a one-way operation will read back as request/response.

        WSDL 1.1 writes a one-way operation correctly — an ``input`` and no ``output`` — but a WSDL 1.1
        document has no message-exchange pattern, so ``app.wsdl_versions.operation_kind_for_pattern`` reads
        every 1.1 operation back as request/response. The round trip changes the operation's kind; the
        report says so rather than leaving a silent difference.

        Args:
            operation: The source operation.

        Returns:
            The verdicts for the operation, in order.
        """
        verdicts = super().operation_verdicts(operation)
        if operation.kind is OperationKind.ONE_WAY and all(v.kind is not LossinessKind.DROP for v in verdicts):
            emitted = ncname(operation.name or operation.key, fallback="operation")
            # The operation changes, so an ``OK`` beside this would claim it is preserved (an over-claim).
            verdicts = [v for v in verdicts if v.kind is not LossinessKind.OK]
            verdicts.append(FidelityVerdict.approx(
                message=f"WSDL 1.1 writes the one-way operation {emitted!r} with an input and no output, but has "
                "no message-exchange pattern, so it reads back as a request/response operation",
                severity=LossinessSeverity.INFO,
                target_mapping="one-way → input-only operation (reads back as request/response)",
            ))
        return verdicts

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        verdict = super().type_verdict(type_)
        if verdict.kind is not LossinessKind.OK:
            return verdict
        return schema_type_verdict(type_, target_label=self.target_label) or verdict

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        return [*super().field_verdicts(field), *schema_field_verdicts(field, target_label=self.target_label)]


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
        self._schema = XsdSchemaWriter(
            api,
            target_namespace=self._target_ns,
            target_label="WSDL",
            losses=self.losses,
            tracker=self.tracker,
            skip_types=frozenset(self._message_types),
        )
        self._service_names: Dict[str, str] = {}
        self._operation_names: Dict[str, str] = {}
        self._wrapped: Dict[str, _WrappedOperation] = {}
        self._plan_names()

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def _plan_names(self) -> None:
        """Give every port type and operation a legal, unique name (types: the schema writer)."""
        service_scope = NameScope()
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
            self._service_names[service.key] = self._schema.rename(service.name, name, service.key, "port type")
            operation_scope = NameScope()
            for operation in self._operations(service):
                name = operation_scope.claim(ncname(operation.name or operation.key, fallback="operation"))
                self._operation_names[operation.key] = self._schema.rename(
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
            header = f"<!-- Generated WSDL for {comment_safe(title)} -->\n"
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
        schema_el = self._schema.new_schema()
        self._schema.append_types(schema_el)
        elements_written: Set[str] = set(self._schema.type_elements.values())
        # MFI-13.2: a multi-part message's parts that name elements.
        for type_ in self._message_types.values():
            for field in type_.fields:
                element = field.extras.get("wsdl_part_element")
                if element and element not in elements_written:
                    ET.SubElement(
                        schema_el,
                        ET.QName(_XSD_NS, "element"),
                        {
                            "name": element,
                            "type": self._schema.source_type_qname(field.type, hint=field.extras.get("xsd_type")),
                        },
                    )
                    elements_written.add(element)
                    self._schema.element_scope.claim(element)
            self.tracker.record(type_.key, Provenance.SOURCE)
        if not self._wsdl_source:
            for service in self._api.services:
                for operation in self._operations(service):
                    self._append_wrapper_elements(schema_el, operation)
        return schema_el

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
            request_element=self._schema.element_scope.claim(name),
            response_element=self._schema.element_scope.claim(f"{name}Response"),
        )

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        request_sequence = self._schema.wrapper(schema_el, plan.request_element)
        scope = NameScope()
        for parameter in operation.parameters:
            element = scope.claim(ncname(parameter.name, fallback="param"))
            self._schema.rename(parameter.name, element, parameter.key, "element")
            fmt = parameter.constraints.format if parameter.constraints is not None else None
            self._schema.append_value(
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
            self._schema.append_value(
                request_sequence, scope.claim("body"), request.payload,
                optional=not request.required, pointer=request.key,
            )
        elif request is not None and request.payload_schema:
            self.losses.record(
                LossKind.INFERRED, "inline-payload",
                f"The request body of {operation.key!r} is an inline schema; it is written as xs:anyType.",
                pointer=request.key,
            )
            self._schema.append_value(
                request_sequence, scope.claim("body"), TypeRef(), optional=not request.required, pointer=request.key
            )

        response_sequence = self._schema.wrapper(schema_el, plan.response_element)
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        response = next((m for m in responses if m.payload is not None), None)
        if response is not None:
            self._schema.append_value(
                response_sequence, "result", response.payload, optional=False, pointer=response.key
            )

        fault_scope = NameScope()
        for message in operation.messages:
            if message.role is not MessageRole.ERROR:
                continue
            # A fault named only by its status (`404`) reads as `Status404`, not `_404`.
            raw = message.name or (f"Status{message.status_code}" if message.status_code else "Fault")
            label = ncname(raw, pascal=True, fallback="Fault")
            fault = fault_scope.claim(label)
            element = self._schema.element_scope.claim(f"{name}{fault[:1].upper()}{fault[1:]}Fault")
            detail = self._schema.wrapper(schema_el, element)
            if message.payload is not None:
                self._schema.append_value(detail, "detail", message.payload, optional=False, pointer=message.key)
            plan.faults.append((fault, element))
        self._wrapped[operation.key] = plan

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

    def _directions(self, operation: Operation) -> List[str]:
        """The ``input`` / ``output`` a binding operation lists — the ones its port type operation has.

        A wrapped operation always has both. A WSDL-sourced one-way (or notification) operation
        has only one, and a binding that listed the other would name a message that does not exist.
        """
        if not self._wsdl_source:
            return ["input", "output"]
        roles = {message.role for message, _ in self._operation_messages(operation)}
        return [
            direction
            for direction, role in (("input", MessageRole.REQUEST), ("output", MessageRole.RESPONSE))
            if role in roles
        ]

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
            body = {"use": "literal"}
            if operation.extras.get("wsdl_soap_style") == "rpc":
                soap_operation["style"] = "rpc"
                # WS-I BP R2717: an rpc-literal body names the namespace of its wrapper element.
                body["namespace"] = self._target_ns
            ET.SubElement(bind_op, ET.QName(soap_ns, "operation"), soap_operation)
            for direction in self._directions(operation):
                ET.SubElement(
                    ET.SubElement(bind_op, ET.QName(_WSDL_NS, direction)),
                    ET.QName(soap_ns, "body"),
                    body,
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
                    part["type"] = self._schema.source_type_qname(field.type, hint=field.extras.get("xsd_type"))
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
        if ref.name in self._schema.type_names:
            return self._schema.type_names[ref.name]
        return ref.name.split(".")[-1]


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
