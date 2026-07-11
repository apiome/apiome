"""WADL emitter: canonical model → WADL XML — MFX-20.1.

The inverse of :class:`app.wadl_normalizer.WadlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
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

__all__ = ["WadlEmitOptions", "WadlEmitter", "WadlFidelityRulePack"]

_WADL_NS = "http://wadl.dev.java.net/2009/02"
_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_TNS_PREFIX = "tns"
_XSD_PREFIX = "xsd"
_WADL_PREFIX = "wadl"
_DEFAULT_MEDIA_TYPE = "application/xml"

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


class WadlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for WADL export."""

    target_label = "WADL"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class WadlEmitOptions(EmitOptions):
    """Per-target options for :class:`WadlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated WADL.",
    )
    media_type: str = Field(
        default=_DEFAULT_MEDIA_TYPE,
        description="Default representation media type for request/response bodies.",
    )


class WadlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a WADL document."""

    key = "wadl"
    format = "wadl"
    label = "WADL"
    description = "Export as a WADL REST service description."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = WadlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/wadl+xml"

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
        return WadlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[WadlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, WadlEmitOptions)
            else WadlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _WadlWriter(api, options)
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


@dataclass
class _PathNode:
    operations: List[Operation] = field(default_factory=list)
    children: Dict[str, "_PathNode"] = field(default_factory=dict)


class _WadlWriter:
    def __init__(self, api: CanonicalApi, options: WadlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)
        self._target_ns = (
            api.extras.get("wadl_target_namespace")
            or api.identity.namespace
            or "http://example.com/service"
        )

    def render(self) -> str:
        ET.register_namespace(_WADL_PREFIX, _WADL_NS)
        ET.register_namespace(_XSD_PREFIX, _XSD_NS)
        ET.register_namespace(_TNS_PREFIX, self._target_ns)

        root = ET.Element(ET.QName(_WADL_NS, "application"))
        grammars_el = ET.SubElement(root, ET.QName(_WADL_NS, "grammars"))
        schema_el = ET.SubElement(
            grammars_el,
            ET.QName(_XSD_NS, "schema"),
            {"targetNamespace": self._target_ns},
        )

        record_types = [t for t in self._api.types if t.kind is TypeKind.RECORD]
        for type_ in record_types:
            self._append_complex_type(schema_el, type_)
            element_name = type_.name[:1].lower() + type_.name[1:] if type_.name else type_.name
            ET.SubElement(
                schema_el,
                ET.QName(_XSD_NS, "element"),
                {"name": element_name, "type": f"{_TNS_PREFIX}:{type_.name}"},
            )
            self.tracker.record(type_.key, Provenance.SOURCE)

        operations = [
            op
            for service in self._api.services
            for op in service.operations
            if op.kind not in _EVENT_OPERATION_KINDS
        ]
        base_url = self._api.servers[0].url if self._api.servers else "https://api.example.com/"
        resources_el = ET.SubElement(
            root,
            ET.QName(_WADL_NS, "resources"),
            {"base": base_url},
        )
        path_root = _build_path_tree(operations)
        for segment, child in sorted(path_root.children.items()):
            resources_el.append(self._render_resource_node(child, segment))

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "WADL export omits event/channel constructs",
                pointer="channels",
            )

        xml_body = ET.tostring(root, encoding="unicode")
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            return f"<!-- Generated WADL for {title} -->\n{xml_body}\n"
        return xml_body + "\n"

    def _render_resource_node(self, node: _PathNode, segment: str) -> ET.Element:
        resource_el = ET.Element(ET.QName(_WADL_NS, "resource"), {"path": segment})
        seen_params: set[str] = set()
        for operation in node.operations:
            for param in operation.parameters:
                if param.location is not ParameterLocation.PATH or param.name in seen_params:
                    continue
                seen_params.add(param.name)
                param_el = ET.SubElement(
                    resource_el,
                    ET.QName(_WADL_NS, "param"),
                    {
                        "name": param.name,
                        "style": "template",
                        "type": self._xsd_type(param.type),
                    },
                )
                if not param.required:
                    param_el.set("required", "false")
        for operation in node.operations:
            resource_el.append(self._render_method(operation))
        for child_segment, child in sorted(node.children.items()):
            resource_el.append(self._render_resource_node(child, child_segment))
        return resource_el

    def _render_method(self, operation: Operation) -> ET.Element:
        method_name = (operation.http_method or "GET").upper()
        attrs = {"name": method_name}
        if operation.name:
            attrs["id"] = operation.name
        method_el = ET.Element(ET.QName(_WADL_NS, "method"), attrs)
        if operation.description:
            doc_el = ET.SubElement(method_el, ET.QName(_WADL_NS, "doc"))
            doc_el.text = operation.description

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request and request.payload:
            request_el = ET.SubElement(method_el, ET.QName(_WADL_NS, "request"))
            self._append_representation(request_el, request.payload)

        for response in (m for m in operation.messages if m.role is MessageRole.RESPONSE):
            status = str(response.extras.get("http_status") or "200")
            response_el = ET.SubElement(
                method_el,
                ET.QName(_WADL_NS, "response"),
                {"status": status},
            )
            if response.payload:
                self._append_representation(response_el, response.payload)

        self.tracker.record(operation.key, Provenance.SOURCE)
        return method_el

    def _append_representation(self, parent: ET.Element, payload: TypeRef) -> None:
        type_name = self._payload_type_name(payload)
        element_name = type_name[:1].lower() + type_name[1:] if type_name else "item"
        ET.SubElement(
            parent,
            ET.QName(_WADL_NS, "representation"),
            {
                "mediaType": self._options.media_type,
                "element": f"{_TNS_PREFIX}:{element_name}",
            },
        )

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

    def _payload_type_name(self, ref: TypeRef) -> str:
        if not ref.name:
            return "Item"
        target = self._types_by_key.get(ref.name)
        return target.name if target else ref.name.split(".")[-1]

    def _xsd_type(self, ref: Optional[TypeRef]) -> str:
        if ref is None or not ref.name:
            return f"{_XSD_PREFIX}:string"
        mapped = _CANONICAL_TO_XSD.get(ref.name.lower())
        if mapped:
            return f"{_XSD_PREFIX}:{mapped}"
        target = self._types_by_key.get(ref.name)
        if target:
            return f"{_TNS_PREFIX}:{target.name}"
        return f"{_TNS_PREFIX}:{ref.name.split('.')[-1]}"


def _build_path_tree(operations: List[Operation]) -> _PathNode:
    root = _PathNode()
    for operation in operations:
        path = operation.http_path or "/"
        segments = [segment for segment in path.strip("/").split("/") if segment]
        if not segments:
            root.operations.append(operation)
            continue
        node = root
        for index, segment in enumerate(segments):
            node = node.children.setdefault(segment, _PathNode())
            if index == len(segments) - 1:
                node.operations.append(operation)
    return root


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.wadl"
