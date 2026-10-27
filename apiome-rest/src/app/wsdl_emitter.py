"""WSDL emitter: canonical model → WSDL 1.1 XML — MFX-18.1.

The inverse of :class:`app.wsdl_normalizer.WsdlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple, Union

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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

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

_CANONICAL_TO_XSD: Dict[str, str] = {
    "bool": "boolean",
    "string": "string",
    "double": "double",
    "float": "float",
    "i16": "short",
    "i32": "int",
    "i64": "long",
    "uint8": "unsignedByte",
    "uint16": "unsignedShort",
    "uint32": "unsignedInt",
    "uint64": "unsignedLong",
    "int8": "byte",
    "bytes": "base64Binary",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class WsdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for WSDL export."""

    target_label = "WSDL"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class WsdlEmitOptions(EmitOptions):
    """Per-target options for :class:`WsdlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated WSDL.",
    )


class WsdlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a WSDL 1.1 document."""

    key = "wsdl"
    format = "wsdl"
    label = "WSDL"
    description = "Export as a SOAP WSDL 1.1 web service description."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = WsdlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/wsdl+xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=False,
            field_identity=True,
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
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _WsdlWriter:
    def __init__(self, api: CanonicalApi, options: WsdlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self._message_types = {t.key: t for t in api.types if t.extras.get("wsdl_kind") == "message"}
        self.output_path = _output_path(api)
        self._target_ns = (
            api.extras.get("wsdl_target_namespace")
            or api.identity.namespace
            or "http://example.com/service"
        )

    def render(self) -> str:
        ET.register_namespace(_WSDL_PREFIX, _WSDL_NS)
        ET.register_namespace(_XSD_PREFIX, _XSD_NS)
        ET.register_namespace(_SOAP_PREFIX, _SOAP_NS)
        ET.register_namespace(_SOAP12_PREFIX, _SOAP12_NS)
        ET.register_namespace(_HTTP_PREFIX, _HTTP_NS)
        ET.register_namespace(_TNS_PREFIX, self._target_ns)

        root = ET.Element(
            ET.QName(_WSDL_NS, "definitions"),
            {
                "name": self._api.identity.name or "Service",
                "targetNamespace": self._target_ns,
            },
        )

        types_el = ET.SubElement(root, ET.QName(_WSDL_NS, "types"))
        schema_el = ET.SubElement(
            types_el,
            ET.QName(_XSD_NS, "schema"),
            {"targetNamespace": self._target_ns},
        )

        # MFI-13.2: a multi-part message's synthesized type is written back as the message's
        # parts, not as a schema type.
        record_types = [
            t for t in self._api.types if t.kind is TypeKind.RECORD and t.extras.get("wsdl_kind") != "message"
        ]
        self._simple_types_written: set = set()
        elements_written = set()
        for type_ in record_types:
            self._append_complex_type(schema_el, type_)
            ET.SubElement(
                schema_el,
                ET.QName(_XSD_NS, "element"),
                {"name": type_.name, "type": f"{_TNS_PREFIX}:{type_.name}"},
            )
            elements_written.add(type_.name)
            self.tracker.record(type_.key, Provenance.SOURCE)
        for type_ in self._message_types.values():
            for field in type_.fields:
                element = field.extras.get("wsdl_part_element")
                if element and element not in elements_written:
                    ET.SubElement(
                        schema_el,
                        ET.QName(_XSD_NS, "element"),
                        {"name": element, "type": self._xsd_type(field.type)},
                    )
                    elements_written.add(element)
            self.tracker.record(type_.key, Provenance.SOURCE)

        messages_written: set = set()
        for service in self._api.services:
            for operation in service.operations:
                for message, name in self._operation_messages(operation):
                    if name not in messages_written:
                        messages_written.add(name)
                        self._message_element(root, name, message)

        for service in self._api.services:
            port_type_el = ET.SubElement(
                root,
                ET.QName(_WSDL_NS, "portType"),
                {"name": service.name},
            )
            self.tracker.record(service.key, Provenance.SOURCE)
            for operation in service.operations:
                op_el = ET.SubElement(
                    port_type_el,
                    ET.QName(_WSDL_NS, "operation"),
                    {"name": operation.name},
                )
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
                self.tracker.record(operation.key, Provenance.SOURCE)

        topology = [server for server in self._api.servers if server.extras.get("wsdl_binding")]
        if topology:
            self._append_topology(root, topology)
        else:
            for service in self._api.services:
                binding_name = f"{service.name}Binding"
                self._append_binding(
                    root,
                    binding_name,
                    port_type=service.name,
                    protocol="soap11",
                    transport="http://schemas.xmlsoap.org/soap/http",
                )
                service_el = ET.SubElement(root, ET.QName(_WSDL_NS, "service"), {"name": f"{service.name}Service"})
                port_el = ET.SubElement(
                    service_el,
                    ET.QName(_WSDL_NS, "port"),
                    {"name": service.name, "binding": f"{_TNS_PREFIX}:{binding_name}"},
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

        xml_body = ET.tostring(root, encoding="unicode")
        if self._options.include_comments:
            title = self._api.identity.name or "Exported service"
            return f"<!-- Generated WSDL for {title} -->\n{xml_body}\n"
        return xml_body + "\n"

    def _operation_messages(self, operation: Operation) -> List[Tuple[Message, str]]:
        """An operation's messages with the WSDL ``message`` name each is written under.

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
        port_type: str,
        protocol: Optional[str],
        transport: Optional[str],
    ) -> None:
        """Write one ``binding`` of ``port_type`` over ``protocol`` (``soap11`` / ``soap12`` / ``http``)."""
        binding_el = ET.SubElement(
            root, ET.QName(_WSDL_NS, "binding"), {"name": name, "type": f"{_TNS_PREFIX}:{port_type}"}
        )
        operations = next((s.operations for s in self._api.services if s.name == port_type), [])
        if protocol == "http":
            ET.SubElement(binding_el, ET.QName(_HTTP_NS, "binding"), {"verb": "POST"})
            for operation in operations:
                bind_op = ET.SubElement(binding_el, ET.QName(_WSDL_NS, "operation"), {"name": operation.name})
                ET.SubElement(bind_op, ET.QName(_HTTP_NS, "operation"), {"location": f"/{operation.name}"})
            return
        soap_ns = _SOAP12_NS if protocol == "soap12" else _SOAP_NS
        soap_binding = {"style": "document"}
        if transport:
            soap_binding["transport"] = transport
        ET.SubElement(binding_el, ET.QName(soap_ns, "binding"), soap_binding)
        for operation in operations:
            bind_op = ET.SubElement(binding_el, ET.QName(_WSDL_NS, "operation"), {"name": operation.name})
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
            for message in operation.messages:
                if message.role is MessageRole.ERROR:
                    fault_el = ET.SubElement(bind_op, ET.QName(_WSDL_NS, "fault"), {"name": message.name or "fault"})
                    ET.SubElement(
                        fault_el, ET.QName(soap_ns, "fault"), {"name": message.name or "fault", "use": "literal"}
                    )

    def _append_topology(self, root: ET.Element, servers: List[Server]) -> None:
        """Write the bindings, services and ports the servers record (MFI-13.2)."""
        bindings_written: set = set()
        for server in servers:
            binding = str(server.extras["wsdl_binding"])
            if binding in bindings_written:
                continue
            bindings_written.add(binding)
            self._append_binding(
                root,
                binding,
                port_type=str(server.extras.get("wsdl_port_type") or ""),
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

    def _append_complex_type(self, schema_el: ET.Element, type_: Type) -> None:
        complex_el = ET.SubElement(
            schema_el,
            ET.QName(_XSD_NS, "complexType"),
            {"name": type_.name},
        )
        sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
        for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
            extras = field.extras or {}
            attributes = {"name": field.name}
            facets = extras.get("xsd_facets")
            simple_type = extras.get("xsd_simple_type")
            base = extras.get("xsd_base")
            if base and simple_type:
                # A named simple type: written once at schema level, referenced by name.
                attributes["type"] = f"{_TNS_PREFIX}:{simple_type}"
                if simple_type not in self._simple_types_written:
                    self._simple_types_written.add(simple_type)
                    named = ET.SubElement(schema_el, ET.QName(_XSD_NS, "simpleType"), {"name": simple_type})
                    self._append_restriction(named, base, facets)
            elif not base:
                attributes["type"] = self._xsd_type(field.type)
            # MFI-13.5: the element's occurrence, nillability and default, as the source stated them.
            for key, attribute in (
                ("xsd_min_occurs", "minOccurs"),
                ("xsd_max_occurs", "maxOccurs"),
                ("xsd_nillable", "nillable"),
                ("xsd_default", "default"),
            ):
                if extras.get(key) is not None:
                    attributes[attribute] = str(extras[key])
            element_el = ET.SubElement(sequence_el, ET.QName(_XSD_NS, "element"), attributes)
            if base and not simple_type:
                # An inline restriction of a built-in type.
                inline = ET.SubElement(element_el, ET.QName(_XSD_NS, "simpleType"))
                self._append_restriction(inline, base, facets)
            self.tracker.record(field.key, Provenance.SOURCE)

    @staticmethod
    def _append_restriction(simple_type_el: ET.Element, base: str, facets: Any) -> None:
        """Write ``<xs:restriction base="xs:<base>">`` with its facets under a ``simpleType``."""
        restriction = ET.SubElement(simple_type_el, ET.QName(_XSD_NS, "restriction"), {"base": f"{_XSD_PREFIX}:{base}"})
        for facet, value in (facets or {}).items():
            for item in value if isinstance(value, list) else [value]:
                ET.SubElement(restriction, ET.QName(_XSD_NS, facet), {"value": str(item)})

    def _message_element(self, root: ET.Element, name: str, message: Message) -> ET.Element:
        """Write a WSDL ``message``: a multi-part message's parts, else one ``parameters`` part."""
        message_el = ET.SubElement(root, ET.QName(_WSDL_NS, "message"), {"name": name})
        message_type = self._message_types.get(message.payload.name or "") if message.payload else None
        if message_type is not None:
            for field in sorted(message_type.fields, key=lambda f: f.field_number or 0):
                part = {"name": field.name}
                if field.extras.get("wsdl_part_element"):
                    part["element"] = f"{_TNS_PREFIX}:{field.extras['wsdl_part_element']}"
                else:
                    part["type"] = self._xsd_type(field.type)
                ET.SubElement(message_el, ET.QName(_WSDL_NS, "part"), part)
            return message_el
        if message.payload is not None and message.payload.name and message.payload.name not in self._types_by_key:
            # A scalar payload (a fault carrying an `xs:string`) is a `type` part: no element names it.
            mapped = _CANONICAL_TO_XSD.get(message.payload.name.lower())
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
        target = self._types_by_key.get(ref.name)
        return target.name if target else ref.name.split(".")[-1]

    def _xsd_type(self, ref: TypeRef) -> str:
        if ref.name:
            mapped = _CANONICAL_TO_XSD.get(ref.name.lower())
            if mapped:
                return f"{_XSD_PREFIX}:{mapped}"
            target = self._types_by_key.get(ref.name)
            if target:
                return f"{_TNS_PREFIX}:{target.name}"
            return f"{_TNS_PREFIX}:{ref.name.split('.')[-1]}"
        return f"{_XSD_PREFIX}:string"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "service"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "service"
    return f"{safe}.wsdl"
