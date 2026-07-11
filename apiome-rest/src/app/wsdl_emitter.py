"""WSDL emitter: canonical model → WSDL 1.1 XML — MFX-18.1.

The inverse of :class:`app.wsdl_normalizer.WsdlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
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

        record_types = [t for t in self._api.types if t.kind is TypeKind.RECORD]
        for type_ in record_types:
            self._append_complex_type(schema_el, type_)
            element_el = ET.SubElement(
                schema_el,
                ET.QName(_XSD_NS, "element"),
                {"name": type_.name, "type": f"{_TNS_PREFIX}:{type_.name}"},
            )
            self.tracker.record(type_.key, Provenance.SOURCE)
            _ = element_el

        messages: Dict[str, ET.Element] = {}
        for service in self._api.services:
            for operation in service.operations:
                request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
                response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
                if request and request.payload:
                    type_name = self._payload_type_name(request.payload)
                    if type_name:
                        input_name = f"{operation.name}Input"
                        messages[input_name] = self._message_element(root, input_name, type_name)
                if response and response.payload:
                    type_name = self._payload_type_name(response.payload)
                    if type_name:
                        output_name = f"{operation.name}Output"
                        messages[output_name] = self._message_element(root, output_name, type_name)

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
                request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
                response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
                if request and request.payload:
                    input_name = f"{operation.name}Input"
                    ET.SubElement(
                        op_el,
                        ET.QName(_WSDL_NS, "input"),
                        {"message": f"{_TNS_PREFIX}:{input_name}"},
                    )
                if response and response.payload:
                    output_name = f"{operation.name}Output"
                    ET.SubElement(
                        op_el,
                        ET.QName(_WSDL_NS, "output"),
                        {"message": f"{_TNS_PREFIX}:{output_name}"},
                    )
                self.tracker.record(operation.key, Provenance.SOURCE)

            binding_name = f"{service.name}Binding"
            binding_el = ET.SubElement(
                root,
                ET.QName(_WSDL_NS, "binding"),
                {"name": binding_name, "type": f"{_TNS_PREFIX}:{service.name}"},
            )
            ET.SubElement(
                binding_el,
                ET.QName(_SOAP_NS, "binding"),
                {
                    "style": "document",
                    "transport": "http://schemas.xmlsoap.org/soap/http",
                },
            )
            for operation in service.operations:
                bind_op = ET.SubElement(
                    binding_el,
                    ET.QName(_WSDL_NS, "operation"),
                    {"name": operation.name},
                )
                ET.SubElement(
                    bind_op,
                    ET.QName(_SOAP_NS, "operation"),
                    {"soapAction": f"{self._target_ns}/{operation.name}"},
                )
                ET.SubElement(
                    ET.SubElement(bind_op, ET.QName(_WSDL_NS, "input")),
                    ET.QName(_SOAP_NS, "body"),
                    {"use": "literal"},
                )
                ET.SubElement(
                    ET.SubElement(bind_op, ET.QName(_WSDL_NS, "output")),
                    ET.QName(_SOAP_NS, "body"),
                    {"use": "literal"},
                )

            service_name = f"{service.name}Service"
            service_el = ET.SubElement(
                root,
                ET.QName(_WSDL_NS, "service"),
                {"name": service_name},
            )
            port_el = ET.SubElement(
                service_el,
                ET.QName(_WSDL_NS, "port"),
                {"name": service.name, "binding": f"{_TNS_PREFIX}:{binding_name}"},
            )
            server_url = self._api.servers[0].url if self._api.servers else "https://api.example.com/service"
            ET.SubElement(
                port_el,
                ET.QName(_SOAP_NS, "address"),
                {"location": server_url},
            )

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

    def _append_complex_type(self, schema_el: ET.Element, type_: Type) -> None:
        complex_el = ET.SubElement(
            schema_el,
            ET.QName(_XSD_NS, "complexType"),
            {"name": type_.name},
        )
        sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
        for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
            ET.SubElement(
                sequence_el,
                ET.QName(_XSD_NS, "element"),
                {
                    "name": field.name,
                    "type": self._xsd_type(field.type),
                },
            )
            self.tracker.record(field.key, Provenance.SOURCE)

    def _message_element(self, root: ET.Element, name: str, type_name: str) -> ET.Element:
        message_el = ET.SubElement(root, ET.QName(_WSDL_NS, "message"), {"name": name})
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
