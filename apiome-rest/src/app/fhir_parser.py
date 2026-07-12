"""HL7 FHIR R4 parser — MFI-22.2.

Parses FHIR JSON (StructureDefinition profiles and resource instances) into a typed
:class:`FhirDocument` AST. Syntax errors surface as :class:`FhirParseError`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .import_ingestion import IngestionError, parse_document

__all__ = [
    "FhirParseError",
    "FhirElementType",
    "FhirElement",
    "FhirStructureDefinition",
    "FhirInferredField",
    "FhirResourceProfile",
    "FhirDocument",
    "is_fhir",
    "is_fhir_document",
    "parse_fhir",
]

_API_MARKERS = ("openapi", "swagger", "asyncapi", "arazzo", "openrpc", "avro")
_FHIR_MARKER_RE = re.compile(r"hl7\.org/fhir", re.IGNORECASE)
_COMMON_RESOURCE_TYPES = frozenset(
    {
        "Patient",
        "Observation",
        "Practitioner",
        "Organization",
        "Encounter",
        "Condition",
        "Procedure",
        "Medication",
        "MedicationRequest",
        "DiagnosticReport",
        "Bundle",
        "CapabilityStatement",
        "StructureDefinition",
        "ValueSet",
        "CodeSystem",
    }
)


class FhirParseError(ValueError):
    """Raised when FHIR JSON cannot be parsed."""


@dataclass(frozen=True)
class FhirElementType:
    code: str
    profile: Optional[str] = None


@dataclass(frozen=True)
class FhirElement:
    path: str
    field_name: str
    min: int
    max: str
    types: Tuple[FhirElementType, ...]
    short: Optional[str] = None


@dataclass(frozen=True)
class FhirStructureDefinition:
    id: Optional[str]
    url: Optional[str]
    name: str
    status: Optional[str]
    kind: Optional[str]
    resource_type: str
    abstract: bool
    base_definition: Optional[str]
    derivation: Optional[str]
    elements: Tuple[FhirElement, ...]


@dataclass(frozen=True)
class FhirInferredField:
    name: str
    type_expr: str
    nullable: bool
    is_array: bool
    nested_fields: Tuple["FhirInferredField", ...] = ()


@dataclass(frozen=True)
class FhirResourceProfile:
    resource_type: str
    fields: Tuple[FhirInferredField, ...]


@dataclass(frozen=True)
class FhirDocument:
    kind: str  # structure_definition | resource_profile
    structure_definition: Optional[FhirStructureDefinition] = None
    resource_profile: Optional[FhirResourceProfile] = None
    raw: str = ""


def _looks_like_fhir_mapping(document: Mapping[str, Any]) -> bool:
    if any(marker in document for marker in _API_MARKERS):
        return False
    resource_type = document.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type.strip():
        return False
    serialized = json.dumps(document)
    if _FHIR_MARKER_RE.search(serialized):
        return True
    if resource_type == "StructureDefinition":
        return True
    if resource_type in _COMMON_RESOURCE_TYPES:
        return True
    meta = document.get("meta")
    if isinstance(meta, Mapping):
        profile = meta.get("profile")
        if isinstance(profile, list) and any(
            isinstance(item, str) and _FHIR_MARKER_RE.search(item) for item in profile
        ):
            return True
    return resource_type in _COMMON_RESOURCE_TYPES


def is_fhir_document(document: Any) -> bool:
    """Return ``True`` when a parsed value looks like FHIR JSON."""
    if isinstance(document, Mapping):
        return _looks_like_fhir_mapping(document)
    return False


def is_fhir(content: str) -> bool:
    """Return ``True`` when ``content`` looks like FHIR JSON."""
    if not content or not isinstance(content, str) or not content.strip():
        return False
    try:
        document = parse_document(content)
    except IngestionError:
        return False
    return is_fhir_document(document)


def _parse_element_types(raw_types: Any) -> Tuple[FhirElementType, ...]:
    if not isinstance(raw_types, list):
        return ()
    types: List[FhirElementType] = []
    for item in raw_types:
        if not isinstance(item, Mapping):
            continue
        code = item.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        profile = item.get("profile")
        profile_url = profile[0] if isinstance(profile, list) and profile else None
        if isinstance(profile_url, str):
            types.append(FhirElementType(code=code.strip(), profile=profile_url))
        else:
            types.append(FhirElementType(code=code.strip()))
    return tuple(types)


def _field_name_for_path(path: str, resource_type: str) -> Optional[str]:
    prefix = f"{resource_type}."
    if not path.startswith(prefix):
        return None
    remainder = path[len(prefix) :]
    if not remainder or "." in remainder:
        return None
    return remainder


def _parse_structure_definition(document: Mapping[str, Any]) -> FhirStructureDefinition:
    resource_type = document.get("type")
    if not isinstance(resource_type, str) or not resource_type.strip():
        raise FhirParseError("StructureDefinition is missing required `type`")
    name = document.get("name")
    if not isinstance(name, str) or not name.strip():
        name = resource_type

    elements_source: Optional[Mapping[str, Any]] = None
    snapshot = document.get("snapshot")
    if isinstance(snapshot, Mapping) and isinstance(snapshot.get("element"), list):
        elements_source = snapshot
    else:
        differential = document.get("differential")
        if isinstance(differential, Mapping) and isinstance(differential.get("element"), list):
            elements_source = differential

    elements: List[FhirElement] = []
    if elements_source is not None:
        for raw_element in elements_source.get("element", []):
            if not isinstance(raw_element, Mapping):
                continue
            path = raw_element.get("path")
            if not isinstance(path, str):
                continue
            field_name = _field_name_for_path(path, resource_type)
            if field_name is None:
                continue
            min_value = raw_element.get("min", 0)
            try:
                min_int = int(min_value)
            except (TypeError, ValueError):
                min_int = 0
            max_value = raw_element.get("max", "1")
            max_str = str(max_value) if max_value is not None else "1"
            element_types = _parse_element_types(raw_element.get("type"))
            if not element_types:
                continue
            short = raw_element.get("short")
            elements.append(
                FhirElement(
                    path=path,
                    field_name=field_name,
                    min=min_int,
                    max=max_str,
                    types=element_types,
                    short=short if isinstance(short, str) else None,
                )
            )

    return FhirStructureDefinition(
        id=document.get("id") if isinstance(document.get("id"), str) else None,
        url=document.get("url") if isinstance(document.get("url"), str) else None,
        name=name,
        status=document.get("status") if isinstance(document.get("status"), str) else None,
        kind=document.get("kind") if isinstance(document.get("kind"), str) else None,
        resource_type=resource_type,
        abstract=bool(document.get("abstract")),
        base_definition=(
            document.get("baseDefinition")
            if isinstance(document.get("baseDefinition"), str)
            else None
        ),
        derivation=document.get("derivation") if isinstance(document.get("derivation"), str) else None,
        elements=tuple(elements),
    )


def _infer_type_expr(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "decimal"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if not value:
            return "string"
        return _infer_type_expr(value[0])
    if isinstance(value, Mapping):
        return "BackboneElement"
    return "string"


def _infer_fields(value: Mapping[str, Any]) -> Tuple[FhirInferredField, ...]:
    fields: List[FhirInferredField] = []
    for key, item in value.items():
        if key in {"resourceType", "meta", "text", "contained", "extension", "modifierExtension"}:
            continue
        if isinstance(item, list):
            nested: Tuple[FhirInferredField, ...] = ()
            item_type = "string"
            if item and isinstance(item[0], Mapping):
                nested = _infer_fields(item[0])
                item_type = "BackboneElement"
            elif item:
                item_type = _infer_type_expr(item[0])
            fields.append(
                FhirInferredField(
                    name=key,
                    type_expr=item_type,
                    nullable=True,
                    is_array=True,
                    nested_fields=nested,
                )
            )
            continue
        if isinstance(item, Mapping):
            fields.append(
                FhirInferredField(
                    name=key,
                    type_expr="BackboneElement",
                    nullable=True,
                    is_array=False,
                    nested_fields=_infer_fields(item),
                )
            )
            continue
        fields.append(
            FhirInferredField(
                name=key,
                type_expr=_infer_type_expr(item),
                nullable=item is None,
                is_array=False,
            )
        )
    return tuple(fields)


def _parse_resource_profile(document: Mapping[str, Any]) -> FhirResourceProfile:
    resource_type = document.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type.strip():
        raise FhirParseError("FHIR resource is missing required `resourceType`")
    return FhirResourceProfile(
        resource_type=resource_type,
        fields=_infer_fields(document),
    )


def parse_fhir(content: str, *, source_label: Optional[str] = None) -> FhirDocument:
    """Parse FHIR JSON into a :class:`FhirDocument`."""
    if not content or not content.strip():
        raise FhirParseError("Invalid or empty FHIR content")
    try:
        document = parse_document(content)
    except IngestionError as exc:
        label = f" ({source_label})" if source_label else ""
        raise FhirParseError(f"Malformed FHIR JSON{label}: {exc}") from exc
    if not is_fhir_document(document):
        raise FhirParseError("Content does not appear to be a FHIR JSON document")
    if not isinstance(document, Mapping):
        raise FhirParseError("FHIR document must be a JSON object")

    if document.get("resourceType") == "StructureDefinition":
        structure = _parse_structure_definition(document)
        return FhirDocument(
            kind="structure_definition",
            structure_definition=structure,
            raw=content,
        )

    profile = _parse_resource_profile(document)
    return FhirDocument(
        kind="resource_profile",
        resource_profile=profile,
        raw=content,
    )
