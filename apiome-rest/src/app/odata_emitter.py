"""OData emitter: canonical model → CSDL / EDMX XML — MFX-25.1.

The inverse of :class:`app.odata_normalizer.ODataNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
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
from .odata_parser import parse_odata

__all__ = ["ODataEmitOptions", "ODataEmitter", "ODataFidelityRulePack", "validate_odata_document"]

_EDMX_NS = "http://docs.oasis-open.org/odata/ns/edmx"
_EDM_NS = "http://docs.oasis-open.org/odata/ns/edm"

_CANONICAL_TO_EDM: Dict[str, str] = {
    "bool": "Edm.Boolean",
    "string": "Edm.String",
    "float": "Edm.Single",
    "double": "Edm.Double",
    "i16": "Edm.Int16",
    "i32": "Edm.Int32",
    "i64": "Edm.Int64",
    "uint8": "Edm.Byte",
    "int8": "Edm.SByte",
    "bytes": "Edm.Binary",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class ODataFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for OData export."""

    target_label = "OData"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class ODataEmitOptions(EmitOptions):
    """Per-target options for :class:`ODataEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit an XML comment header in the generated EDMX document.",
    )


class ODataEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OData v4 CSDL / EDMX document."""

    key = "odata"
    format = "odata"
    label = "OData"
    description = "Export as an OData v4 CSDL / EDMX metadata document (.edmx)."
    icon = "database"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = ODataEmitOptions

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


class _ODataWriter:
    def __init__(self, api: CanonicalApi, options: ODataEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._schemas = api.extras.get("odata_schemas") or []
        self._version = str(api.extras.get("odata_version") or api.version or "4.0")
        self.output_path = _output_path(api)

    def render(self) -> str:
        if isinstance(self._schemas, list) and self._schemas:
            return self._render_from_schemas()

        namespace = self._api.identity.namespace or self._api.identity.name or "Exported"
        ET.register_namespace("edmx", _EDMX_NS)
        ET.register_namespace("edm", _EDM_NS)
        edmx = ET.Element(f"{{{_EDMX_NS}}}Edmx", Version=self._version)
        data_services = ET.SubElement(edmx, f"{{{_EDMX_NS}}}DataServices")
        schema = ET.SubElement(
            data_services,
            f"{{{_EDM_NS}}}Schema",
            {"Namespace": namespace},
        )

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            if type_.kind is TypeKind.ENUM or type_.extras.get("odata_kind") == "enum":
                self._append_enum(schema, type_, namespace=namespace)
            elif type_.extras.get("odata_kind") == "complex":
                self._append_complex_type(schema, type_, namespace=namespace)
            elif type_.kind is TypeKind.RECORD:
                self._append_entity_type(schema, type_, namespace=namespace)

        container = ET.SubElement(schema, f"{{{_EDM_NS}}}EntityContainer", {"Name": "Container"})
        for service in self._api.services:
            entity_type_name = self._entity_type_for_service(service.name, namespace=namespace)
            ET.SubElement(
                container,
                f"{{{_EDM_NS}}}EntitySet",
                {"Name": service.name, "EntityType": entity_type_name},
            )

        xml = ET.tostring(edmx, encoding="unicode")
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!-- Generated OData EDMX for {title} -->\n{xml}\n"
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'

    def _render_from_schemas(self) -> str:
        ET.register_namespace("edmx", _EDMX_NS)
        ET.register_namespace("edm", _EDM_NS)
        edmx = ET.Element(f"{{{_EDMX_NS}}}Edmx", Version=self._version)
        data_services = ET.SubElement(edmx, f"{{{_EDMX_NS}}}DataServices")
        for schema_data in self._schemas:
            if not isinstance(schema_data, dict):
                continue
            namespace = str(schema_data.get("namespace", "Exported"))
            schema = ET.SubElement(
                data_services,
                f"{{{_EDM_NS}}}Schema",
                {"Namespace": namespace},
            )
            for enum_data in schema_data.get("enum_types", []):
                if isinstance(enum_data, dict):
                    self._append_enum_dict(schema, enum_data, namespace=namespace)
            for complex_data in schema_data.get("complex_types", []):
                if isinstance(complex_data, dict):
                    self._append_complex_dict(schema, complex_data, namespace=namespace)
            for entity_data in schema_data.get("entity_types", []):
                if isinstance(entity_data, dict):
                    self._append_entity_dict(schema, entity_data, namespace=namespace)
            container_data = schema_data.get("entity_container")
            if isinstance(container_data, dict):
                container = ET.SubElement(
                    schema,
                    f"{{{_EDM_NS}}}EntityContainer",
                    {"Name": str(container_data.get("name", "Container"))},
                )
                for entity_set in container_data.get("entity_sets", []):
                    if not isinstance(entity_set, dict):
                        continue
                    ET.SubElement(
                        container,
                        f"{{{_EDM_NS}}}EntitySet",
                        {
                            "Name": str(entity_set.get("name", "Items")),
                            "EntityType": str(entity_set.get("entity_type", f"{namespace}.Item")),
                        },
                    )
        xml = ET.tostring(edmx, encoding="unicode")
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            return f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!-- Generated OData EDMX for {title} -->\n{xml}\n"
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml}\n'

    def _append_enum(self, schema: ET.Element, type_: Type, *, namespace: str) -> None:
        enum_el = ET.SubElement(schema, f"{{{_EDM_NS}}}EnumType", {"Name": type_.name})
        for value in type_.enum_values:
            attrs = {"Name": value.name}
            if value.value is not None:
                attrs["Value"] = str(value.value)
            ET.SubElement(enum_el, f"{{{_EDM_NS}}}Member", attrs)
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _append_enum_dict(self, schema: ET.Element, enum_data: dict, *, namespace: str) -> None:
        name = str(enum_data.get("name", "Enum"))
        enum_el = ET.SubElement(schema, f"{{{_EDM_NS}}}EnumType", {"Name": name})
        for member in enum_data.get("members", []):
            if not isinstance(member, dict):
                continue
            attrs = {"Name": str(member.get("name", "Member"))}
            if member.get("value") is not None:
                attrs["Value"] = str(member["value"])
            ET.SubElement(enum_el, f"{{{_EDM_NS}}}Member", attrs)
        self.tracker.record(name, Provenance.SOURCE)

    def _append_complex_type(self, schema: ET.Element, type_: Type, *, namespace: str) -> None:
        complex_el = ET.SubElement(schema, f"{{{_EDM_NS}}}ComplexType", {"Name": type_.name})
        for field in sorted(type_.fields, key=lambda item: item.field_number or 0):
            self._append_property(complex_el, field)
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _append_complex_dict(self, schema: ET.Element, complex_data: dict, *, namespace: str) -> None:
        name = str(complex_data.get("name", "Complex"))
        complex_el = ET.SubElement(schema, f"{{{_EDM_NS}}}ComplexType", {"Name": name})
        for prop in complex_data.get("properties", []):
            if isinstance(prop, dict):
                self._append_property_dict(complex_el, prop)
        self.tracker.record(name, Provenance.SOURCE)

    def _append_entity_type(self, schema: ET.Element, type_: Type, *, namespace: str) -> None:
        entity_el = ET.SubElement(schema, f"{{{_EDM_NS}}}EntityType", {"Name": type_.name})
        key_props = type_.extras.get("odata_key_properties") or []
        if isinstance(key_props, list) and key_props:
            key_el = ET.SubElement(entity_el, f"{{{_EDM_NS}}}Key")
            for key_name in key_props:
                ET.SubElement(key_el, f"{{{_EDM_NS}}}PropertyRef", {"Name": str(key_name)})
        for field in sorted(type_.fields, key=lambda item: item.field_number or 0):
            self._append_property(entity_el, field)
        nav_props = type_.extras.get("odata_navigation_properties") or []
        if isinstance(nav_props, list):
            for nav in nav_props:
                if not isinstance(nav, dict):
                    continue
                attrs = {
                    "Name": str(nav.get("name", "Navigation")),
                    "Type": str(nav.get("type", f"{namespace}.Related")),
                }
                if nav.get("partner"):
                    attrs["Partner"] = str(nav["partner"])
                ET.SubElement(entity_el, f"{{{_EDM_NS}}}NavigationProperty", attrs)
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _append_entity_dict(self, schema: ET.Element, entity_data: dict, *, namespace: str) -> None:
        name = str(entity_data.get("name", "Entity"))
        entity_el = ET.SubElement(schema, f"{{{_EDM_NS}}}EntityType", {"Name": name})
        key_props = entity_data.get("key_properties") or []
        if isinstance(key_props, list) and key_props:
            key_el = ET.SubElement(entity_el, f"{{{_EDM_NS}}}Key")
            for key_name in key_props:
                ET.SubElement(key_el, f"{{{_EDM_NS}}}PropertyRef", {"Name": str(key_name)})
        for prop in entity_data.get("properties", []):
            if isinstance(prop, dict):
                self._append_property_dict(entity_el, prop)
        for nav in entity_data.get("navigation_properties", []):
            if not isinstance(nav, dict):
                continue
            attrs = {
                "Name": str(nav.get("name", "Navigation")),
                "Type": str(nav.get("type", f"{namespace}.Related")),
            }
            if nav.get("partner"):
                attrs["Partner"] = str(nav["partner"])
            ET.SubElement(entity_el, f"{{{_EDM_NS}}}NavigationProperty", attrs)
        self.tracker.record(name, Provenance.SOURCE)

    def _append_property(self, parent: ET.Element, field: CanonicalField) -> None:
        type_expr = field.extras.get("odata_type")
        if not isinstance(type_expr, str) or not type_expr:
            type_expr = self._render_type_ref(field.type)
        attrs = {"Name": field.name, "Type": type_expr}
        if field.type.nullable is False:
            attrs["Nullable"] = "false"
        ET.SubElement(parent, f"{{{_EDM_NS}}}Property", attrs)
        self.tracker.record(field.key, Provenance.SOURCE)

    def _append_property_dict(self, parent: ET.Element, prop: dict) -> None:
        attrs = {
            "Name": str(prop.get("name", "Property")),
            "Type": str(prop.get("type", "Edm.String")),
        }
        nullable = prop.get("nullable")
        if nullable is False:
            attrs["Nullable"] = "false"
        ET.SubElement(parent, f"{{{_EDM_NS}}}Property", attrs)

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"Collection({inner})"
        if ref.name:
            mapped = _CANONICAL_TO_EDM.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target is not None:
                namespace = self._api.identity.namespace or ""
                return f"{namespace}.{target.name}" if namespace else target.name
            local = ref.name.split(".")[-1]
            namespace = self._api.identity.namespace or ""
            return f"{namespace}.{local}" if namespace else local
        return "Edm.String"

    def _entity_type_for_service(self, service_name: str, *, namespace: str) -> str:
        singular = service_name.rstrip("s") if service_name.endswith("s") else service_name
        for type_ in self._api.types:
            if type_.name == singular:
                return f"{namespace}.{type_.name}" if namespace else type_.name
        if self._api.types:
            type_name = self._api.types[0].name
            return f"{namespace}.{type_name}" if namespace else type_name
        return f"{namespace}.Entity" if namespace else "Entity"


def _output_path(api: CanonicalApi) -> str:
    namespace = api.identity.namespace or api.identity.name or "service"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace).strip("_") or "service"
    return f"{safe}.edmx"


def validate_odata_document(content: str) -> None:
    """Validate OData EDMX / CSDL text by re-parsing it."""
    parse_odata(content)
