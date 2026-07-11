"""XSD emitter: canonical model → XML Schema (XSD).

The inverse of :class:`app.xsd_normalizer.XsdNormalizer` and an implementation of
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
    OperationKind,
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

__all__ = ["XsdEmitOptions", "XsdEmitter", "XsdFidelityRulePack"]

_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_XS_PREFIX = "xs"
_TNS_PREFIX = "tns"

_CANONICAL_TO_XSD: Dict[str, str] = {
    "bool": "boolean",
    "string": "string",
    "double": "double",
    "float": "float",
    "i16": "short",
    "i32": "int",
    "i64": "long",
    "integer": "int",
    "uint8": "unsignedByte",
    "uint16": "unsignedShort",
    "uint32": "unsignedInt",
    "uint64": "unsignedLong",
    "int8": "byte",
    "bytes": "base64Binary",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class XsdFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for XSD export."""

    target_label = "XSD"

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            "the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class XsdEmitOptions(EmitOptions):
    """Per-target options for :class:`XsdEmitter`."""

    include_xml_declaration: bool = Field(
        default=True,
        description="Emit the XML 1.0 declaration prolog.",
    )
    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated XSD.",
    )


class XsdEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an XSD schema document."""

    key = "xsd"
    format = "xsd"
    label = "XSD"
    description = "Export as a W3C XML Schema Definition (XSD)."
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
            unions=False,
            nullability=True,
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


class _XsdWriter:
    def __init__(self, api: CanonicalApi, options: XsdEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._target_ns = api.identity.namespace or api.extras.get("xsd_target_namespace")
        self.output_path = _output_path(api)

    def render(self) -> str:
        ET.register_namespace(_XS_PREFIX, _XSD_NS)
        if self._target_ns:
            ET.register_namespace(_TNS_PREFIX, str(self._target_ns))

        schema_attrs: Dict[str, str] = {
            "elementFormDefault": "qualified",
        }
        if self._target_ns:
            schema_attrs["targetNamespace"] = str(self._target_ns)
            schema_attrs[f"xmlns:{_TNS_PREFIX}"] = str(self._target_ns)

        schema_el = ET.Element(ET.QName(_XSD_NS, "schema"), schema_attrs)

        root_element = self._api.extras.get("xsd_root_element")
        if isinstance(root_element, str) and root_element:
            root_type = self._root_type_name(root_element)
            if root_type:
                ET.SubElement(
                    schema_el,
                    ET.QName(_XSD_NS, "element"),
                    {
                        "name": root_element,
                        "type": f"{_TNS_PREFIX}:{root_type}",
                    },
                )

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            if type_.kind is TypeKind.RECORD:
                self._append_complex_type(schema_el, type_)
            elif type_.kind is TypeKind.ENUM:
                self._append_simple_enum(schema_el, type_)
            elif type_.kind is TypeKind.SCALAR:
                self._append_simple_scalar(schema_el, type_)

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "XSD export omits service/operation constructs",
                pointer="services",
            )

        xml_body = ET.tostring(schema_el, encoding="unicode")
        parts: List[str] = []
        if self._options.include_xml_declaration:
            parts.append('<?xml version="1.0" encoding="UTF-8"?>')
        if self._options.include_comments:
            title = self._api.title or self._api.identity.name or "schema"
            parts.append(f"<!-- Generated XSD for {title} -->")
        parts.append(xml_body)
        return "\n".join(parts) + "\n"

    def _root_type_name(self, root_element: str) -> Optional[str]:
        elements = self._api.extras.get("xsd_elements")
        if isinstance(elements, list):
            for entry in elements:
                if isinstance(entry, dict) and entry.get("name") == root_element:
                    type_name = entry.get("type")
                    if isinstance(type_name, str):
                        return type_name
        for type_ in self._api.types:
            if type_.name == root_element:
                return type_.name
        return None

    def _append_complex_type(self, schema_el: ET.Element, type_: Type) -> None:
        complex_el = ET.SubElement(
            schema_el,
            ET.QName(_XSD_NS, "complexType"),
            {"name": type_.name},
        )
        element_fields = [field for field in type_.fields if field.extras.get("xsd_kind") != "attribute"]
        attribute_fields = [field for field in type_.fields if field.extras.get("xsd_kind") == "attribute"]
        if element_fields:
            sequence_el = ET.SubElement(complex_el, ET.QName(_XSD_NS, "sequence"))
            for field in sorted(element_fields, key=lambda item: item.field_number or 0):
                attrs: Dict[str, str] = {
                    "name": field.name,
                    "type": self._xsd_type(field),
                }
                max_occurs = field.extras.get("xsd_max_occurs")
                if isinstance(max_occurs, str) and max_occurs:
                    attrs["maxOccurs"] = max_occurs
                min_occurs = field.extras.get("xsd_min_occurs")
                if isinstance(min_occurs, str) and min_occurs:
                    attrs["minOccurs"] = min_occurs
                ET.SubElement(sequence_el, ET.QName(_XSD_NS, "element"), attrs)
                self.tracker.record(field.key, Provenance.SOURCE)
        for field in sorted(attribute_fields, key=lambda item: item.field_number or 0):
            ET.SubElement(
                complex_el,
                ET.QName(_XSD_NS, "attribute"),
                {
                    "name": field.name,
                    "type": self._xsd_type(field),
                },
            )
            self.tracker.record(field.key, Provenance.SOURCE)
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _append_simple_enum(self, schema_el: ET.Element, type_: Type) -> None:
        simple_el = ET.SubElement(
            schema_el,
            ET.QName(_XSD_NS, "simpleType"),
            {"name": type_.name},
        )
        base = type_.extras.get("xsd_base")
        restriction_base = (
            f"{_XS_PREFIX}:{_attr_local(str(base))}"
            if isinstance(base, str) and base
            else f"{_XS_PREFIX}:string"
        )
        restriction_el = ET.SubElement(
            simple_el,
            ET.QName(_XSD_NS, "restriction"),
            {"base": restriction_base},
        )
        for enum_value in type_.enum_values:
            ET.SubElement(
                restriction_el,
                ET.QName(_XSD_NS, "enumeration"),
                {"value": enum_value.name},
            )
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _append_simple_scalar(self, schema_el: ET.Element, type_: Type) -> None:
        simple_el = ET.SubElement(
            schema_el,
            ET.QName(_XSD_NS, "simpleType"),
            {"name": type_.name},
        )
        base = type_.extras.get("xsd_base") or type_.extras.get("xsd_type") or "string"
        ET.SubElement(
            simple_el,
            ET.QName(_XSD_NS, "restriction"),
            {"base": f"{_XS_PREFIX}:{_attr_local(str(base))}"},
        )
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _xsd_type(self, field: CanonicalField) -> str:
        xsd_type = field.extras.get("xsd_type")
        if isinstance(xsd_type, str) and xsd_type in self._types_by_key:
            return f"{_TNS_PREFIX}:{xsd_type}"
        if isinstance(xsd_type, str):
            mapped = _CANONICAL_TO_XSD.get(xsd_type.lower())
            if mapped:
                return f"{_XS_PREFIX}:{mapped}"
            if xsd_type.lower() in {
                "string",
                "boolean",
                "double",
                "float",
                "decimal",
                "int",
                "integer",
                "positiveinteger",
                "date",
                "datetime",
                "time",
            }:
                return f"{_XS_PREFIX}:{xsd_type.lower().replace('positiveinteger', 'positiveInteger')}"
        ref = field.type
        if ref.is_list() and ref.item is not None and ref.item.name:
            return self._xsd_type_for_ref(ref.item)
        return self._xsd_type_for_ref(ref)

    def _xsd_type_for_ref(self, ref: TypeRef) -> str:
        if not ref.name:
            return f"{_XS_PREFIX}:string"
        mapped = _CANONICAL_TO_XSD.get(ref.name.lower())
        if mapped:
            return f"{_XS_PREFIX}:{mapped}"
        target = self._types_by_key.get(ref.name)
        if target:
            return f"{_TNS_PREFIX}:{target.name}"
        return f"{_TNS_PREFIX}:{ref.name.split('.')[-1]}"


def _attr_local(value: str) -> str:
    return value.split(":", 1)[-1] if ":" in value else value


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "schema"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "schema"
    return f"{safe}.xsd"
