"""XML-RPC emitter: canonical model → XML-RPC ``methodCall`` XML.

The inverse of :class:`app.xmlrpc_normalizer.XmlRpcNormalizer` and an implementation
of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
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

__all__ = ["XmlRpcEmitOptions", "XmlRpcEmitter", "XmlRpcFidelityRulePack"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class XmlRpcFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for XML-RPC export."""

    target_label = "XML-RPC"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no HTTP binding; operation {operation.key!r} is dropped",
                target_mapping="HTTP operation → dropped",
            )
        return FidelityVerdict.keep()


class XmlRpcEmitOptions(EmitOptions):
    """Per-target options for :class:`XmlRpcEmitter`."""

    include_xml_declaration: bool = Field(
        default=True,
        description="Emit the XML 1.0 declaration prolog.",
    )


class XmlRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an XML-RPC ``methodCall`` document."""

    key = "xmlrpc"
    format = "xmlrpc"
    label = "XML-RPC"
    description = "Export as an XML-RPC methodCall message."
    icon = "file-code"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = XmlRpcEmitOptions

    OUTPUT_MEDIA_TYPE = "application/xml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return XmlRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[XmlRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, XmlRpcEmitOptions)
            else XmlRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _XmlRpcWriter(api, options)
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


class _XmlRpcWriter:
    def __init__(self, api: CanonicalApi, options: XmlRpcEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        operation = self._primary_operation()
        if operation is None:
            raise ValueError("XML-RPC export requires at least one RPC operation")

        root = ET.Element("methodCall")
        method_el = ET.SubElement(root, "methodName")
        method_el.text = operation.name

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        params = request.extras.get("xmlrpc_params") if request is not None else None
        if isinstance(params, list) and params:
            params_el = ET.SubElement(root, "params")
            for entry in sorted(params, key=lambda item: int(item.get("index", 0))):
                if not isinstance(entry, dict):
                    continue
                param_el = ET.SubElement(params_el, "param")
                sample = entry.get("sample")
                schema = entry.get("schema") if isinstance(entry.get("schema"), dict) else {}
                param_el.append(self._value_from_schema(schema, sample))

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "XML-RPC export omits event/channel constructs",
                pointer="channels",
            )

        xml = ET.tostring(root, encoding="unicode")
        if self._options.include_xml_declaration:
            return '<?xml version="1.0"?>\n' + xml + "\n"
        return xml + "\n"

    def _primary_operation(self) -> Optional[Operation]:
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS:
                    continue
                if operation.http_method or operation.http_path:
                    continue
                return operation
        return None

    def _value_from_schema(self, schema: Dict[str, Any], sample: Any) -> ET.Element:
        value_el = ET.Element("value")
        if sample is not None:
            value_el.append(self._value_from_sample(sample))
            return value_el

        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            type_name = ref.rsplit("/", 1)[-1]
            target = next((t for t in self._api.types if t.name == type_name), None)
            if target is not None:
                value_el.append(self._struct_from_type(target))
                return value_el

        schema_type = schema.get("type")
        if schema_type == "array":
            array_el = ET.SubElement(value_el, "array")
            data_el = ET.SubElement(array_el, "data")
            items = schema.get("items")
            if isinstance(items, dict):
                data_el.append(self._value_from_schema(items, None))
            return value_el
        if schema_type == "integer":
            ET.SubElement(value_el, "int").text = "0"
            return value_el
        if schema_type == "number":
            ET.SubElement(value_el, "double").text = "0"
            return value_el
        if schema_type == "boolean":
            ET.SubElement(value_el, "boolean").text = "0"
            return value_el
        if schema_type == "null":
            ET.SubElement(value_el, "nil")
            return value_el
        ET.SubElement(value_el, "string").text = ""
        return value_el

    def _value_from_sample(self, sample: Any) -> ET.Element:
        if isinstance(sample, dict):
            struct_el = ET.Element("struct")
            for name, value in sample.items():
                member_el = ET.SubElement(struct_el, "member")
                ET.SubElement(member_el, "name").text = str(name)
                value_el = ET.SubElement(member_el, "value")
                value_el.append(self._value_from_sample(value))
            return struct_el
        if isinstance(sample, list):
            array_el = ET.Element("array")
            data_el = ET.SubElement(array_el, "data")
            for item in sample:
                value_el = ET.SubElement(data_el, "value")
                value_el.append(self._value_from_sample(item))
            return array_el
        if isinstance(sample, bool):
            boolean_el = ET.Element("boolean")
            boolean_el.text = "1" if sample else "0"
            return boolean_el
        if isinstance(sample, int):
            int_el = ET.Element("int")
            int_el.text = str(sample)
            return int_el
        if isinstance(sample, float):
            double_el = ET.Element("double")
            double_el.text = str(sample)
            return double_el
        if sample is None:
            return ET.Element("nil")
        string_el = ET.Element("string")
        string_el.text = str(sample)
        return string_el

    def _struct_from_type(self, type_: Type) -> ET.Element:
        struct_el = ET.Element("struct")
        for field in type_.fields:
            member_el = ET.SubElement(struct_el, "member")
            ET.SubElement(member_el, "name").text = field.name
            value_el = ET.SubElement(member_el, "value")
            sample = None
            if isinstance(type_.extras.get("xmlrpc_samples"), dict):
                sample = type_.extras["xmlrpc_samples"].get(field.name)
            if sample is not None:
                value_el.append(self._value_from_sample(sample))
            else:
                value_el.append(self._value_from_type_ref(field.type))
            self.tracker.record(field.key, Provenance.SOURCE)
        self.tracker.record(type_.key, Provenance.SOURCE)
        return struct_el

    def _value_from_type_ref(self, ref: Optional[TypeRef]) -> ET.Element:
        if ref is None or not ref.name:
            return self._value_from_sample("")
        if ref.is_list():
            array_el = ET.Element("array")
            data_el = ET.SubElement(array_el, "data")
            if ref.item is not None:
                value_el = ET.SubElement(data_el, "value")
                value_el.append(self._value_from_type_ref(ref.item))
            return array_el
        target = self._types_by_key.get(ref.name)
        if target is not None and target.kind is TypeKind.RECORD:
            return self._struct_from_type(target)
        mapping = {
            "integer": ("int", "0"),
            "int32": ("int", "0"),
            "int64": ("int", "0"),
            "double": ("double", "0"),
            "float": ("double", "0"),
            "bool": ("boolean", "0"),
            "boolean": ("boolean", "0"),
            "null": ("nil", None),
        }
        tag, text = mapping.get(ref.name, ("string", ""))
        element = ET.Element(tag)
        if text is not None:
            element.text = text
        return element


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "method"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("_") or "method"
    return f"{safe}.xmlrpc.xml"
