"""FHIR emitter: canonical model → FHIR JSON — MFX-26.1.

The inverse of :class:`app.fhir_normalizer.FhirNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
import re
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
from .fhir_parser import parse_fhir

__all__ = ["FhirEmitOptions", "FhirEmitter", "FhirFidelityRulePack", "validate_fhir_document"]

_CANONICAL_TO_FHIR: Dict[str, str] = {
    "bool": "boolean",
    "string": "string",
    "i32": "integer",
    "i64": "integer",
    "float": "decimal",
    "double": "decimal",
    "bytes": "base64Binary",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class FhirFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for FHIR export."""

    target_label = "FHIR"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class FhirEmitOptions(EmitOptions):
    """Per-target options for :class:`FhirEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a `_comment` header in the generated FHIR JSON document.",
    )
    prefer_structure_definition: bool = Field(
        default=True,
        description="Emit a StructureDefinition when round-trip metadata is available.",
    )


class FhirEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an HL7 FHIR R4 JSON document."""

    key = "fhir"
    format = "fhir"
    label = "FHIR"
    description = "Export as an HL7 FHIR R4 StructureDefinition or resource profile (.json)."
    icon = "heart-pulse"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = FhirEmitOptions

    OUTPUT_MEDIA_TYPE = "application/fhir+json"

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
        return FhirFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[FhirEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, FhirEmitOptions)
            else FhirEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _FhirWriter(api, options)
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


class _FhirWriter:
    def __init__(self, api: CanonicalApi, options: FhirEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._structure = api.extras.get("fhir_structure_definition")
        self._profile = api.extras.get("fhir_resource_profile")
        self.output_path = _output_path(api)

    def render(self) -> str:
        if (
            self._options.prefer_structure_definition
            and isinstance(self._structure, dict)
            and self._structure.get("elements")
        ):
            document = self._render_structure_definition(self._structure)
        elif isinstance(self._profile, dict):
            document = self._render_resource_profile(self._profile)
        else:
            document = self._render_structure_from_types()

        if self._options.include_comments:
            document = {
                "_comment": f"Generated FHIR document for {self._api.identity.name or 'Exported API'}",
                **document,
            }

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "FHIR export has no event channel representation",
            )

        return json.dumps(document, indent=2, ensure_ascii=False) + "\n"

    def _render_structure_definition(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        resource_type = str(structure.get("type") or self._primary_resource_type())
        elements = []
        for element in structure.get("elements", []):
            if not isinstance(element, dict):
                continue
            path = element.get("path") or f"{resource_type}.{element.get('field_name', 'field')}"
            types = element.get("types") or [{"code": "string"}]
            rendered_types = []
            for item in types:
                if not isinstance(item, dict):
                    continue
                entry = {"code": str(item.get("code", "string"))}
                if item.get("profile"):
                    entry["profile"] = [str(item["profile"])]
                rendered_types.append(entry)
            entry = {
                "path": path,
                "min": element.get("min", 0),
                "max": element.get("max", "1"),
                "type": rendered_types,
            }
            if element.get("short"):
                entry["short"] = element["short"]
            elements.append(entry)
            self.tracker.record(str(path), Provenance.SOURCE)

        document = {
            "resourceType": "StructureDefinition",
            "id": structure.get("id") or structure.get("name") or resource_type,
            "url": structure.get("url")
            or f"http://example.com/fhir/StructureDefinition/{structure.get('name', resource_type)}",
            "name": structure.get("name") or resource_type,
            "status": structure.get("status") or "draft",
            "kind": structure.get("kind") or "resource",
            "abstract": bool(structure.get("abstract")),
            "type": resource_type,
            "baseDefinition": structure.get("baseDefinition")
            or f"http://hl7.org/fhir/StructureDefinition/{resource_type}",
            "derivation": structure.get("derivation") or "constraint",
            "differential": {"element": elements},
        }
        self.tracker.record(str(document["name"]), Provenance.SOURCE)
        return document

    def _render_resource_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        resource_type = str(profile.get("resource_type") or self._primary_resource_type())
        document: Dict[str, Any] = {"resourceType": resource_type}
        for field in profile.get("fields", []):
            if not isinstance(field, dict):
                continue
            name = str(field.get("name", "field"))
            fhir_type = str(field.get("type", "string"))
            if field.get("is_array"):
                document[name] = self._sample_array_value(fhir_type)
            else:
                document[name] = self._sample_scalar_value(fhir_type)
            self.tracker.record(name, Provenance.SOURCE)
        return document

    def _render_structure_from_types(self) -> Dict[str, Any]:
        resource_type = self._primary_resource_type()
        elements: List[Dict[str, Any]] = []
        target = next((type_ for type_ in self._api.types if type_.name == resource_type), None)
        if target is None and self._api.types:
            target = self._api.types[0]
            resource_type = target.name
        if target is not None:
            for field in sorted(target.fields, key=lambda item: item.field_number or 0):
                elements.append(self._element_from_field(target.name, field))
        return {
            "resourceType": "StructureDefinition",
            "id": resource_type,
            "url": f"http://example.com/fhir/StructureDefinition/{resource_type}",
            "name": resource_type,
            "status": "draft",
            "kind": "resource",
            "abstract": False,
            "type": resource_type,
            "baseDefinition": f"http://hl7.org/fhir/StructureDefinition/{resource_type}",
            "derivation": "constraint",
            "differential": {"element": elements},
        }

    def _element_from_field(self, resource_type: str, field: CanonicalField) -> Dict[str, Any]:
        fhir_type = field.extras.get("fhir_type")
        if not isinstance(fhir_type, str) or not fhir_type:
            fhir_type = self._render_type_ref(field.type)
        max_value = field.extras.get("fhir_max", "1")
        min_value = field.extras.get("fhir_min", 0 if field.type.nullable else 1)
        entry = {
            "path": field.extras.get("fhir_path") or f"{resource_type}.{field.name}",
            "min": min_value,
            "max": max_value,
            "type": [{"code": fhir_type}],
        }
        if field.description:
            entry["short"] = field.description
        self.tracker.record(field.key, Provenance.SOURCE)
        return entry

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            return self._render_type_ref(ref.item)
        if ref.name:
            mapped = _CANONICAL_TO_FHIR.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target is not None:
                return target.name
            return ref.name.split(".")[-1]
        return "string"

    def _primary_resource_type(self) -> str:
        if self._api.services:
            return self._api.services[0].name
        if self._api.types:
            return self._api.types[0].name
        return self._api.identity.name or "Resource"

    def _sample_scalar_value(self, fhir_type: str) -> Any:
        if fhir_type == "boolean":
            return True
        if fhir_type == "integer":
            return 1
        if fhir_type == "decimal":
            return 1.0
        return "example"

    def _sample_array_value(self, fhir_type: str) -> List[Any]:
        if fhir_type == "BackboneElement":
            return [{}]
        return [self._sample_scalar_value(fhir_type)]


def _output_path(api: CanonicalApi) -> str:
    name = api.identity.name or (api.services[0].name if api.services else "resource")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "resource"
    kind = api.extras.get("fhir_kind")
    if kind == "structure_definition":
        return f"{safe}.structuredefinition.json"
    return f"{safe}.fhir.json"


def validate_fhir_document(content: str) -> None:
    """Validate FHIR JSON text by re-parsing it."""
    parse_fhir(content)
