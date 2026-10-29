"""FHIR logical models → canonical model — MFX-26.1 (#4157).

The reader for what :class:`app.fhir_emitter.FhirEmitter` writes: a ``collection`` Bundle (or a single
resource) of StructureDefinition **logical models** (``kind: logical``) with their CodeSystems, ValueSets and an
optional CapabilityStatement. :func:`logical_resources` recognizes such a document and
:func:`normalize_logical` maps it to a :class:`~app.canonical_model.CanonicalApi`:

* each logical model is a record; an element with children (a ``BackboneElement``) is a nested record named
  by its ``structuredefinition-explicit-type-name`` extension (else ``<Parent><Element>``);
* an element's cardinality gives nullability (``min`` 0) and lists (``max`` above 1); its type is a primitive,
  another logical model (by canonical URL), or — a ``code`` with a binding — the enum of the bound ValueSet's
  CodeSystem; each element is kept as written (``extras["fhir_element"]``) so an export writes it back;
* each CodeSystem is an enum (one value per concept);
* the CapabilityStatement gives the title, description and version.

A StructureDefinition profile or a resource instance is not read here (see :mod:`app.fhir_normalizer`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from .normalizer import Keys, normalize_ordering

__all__ = ["logical_resources", "normalize_logical"]

_EXPLICIT_TYPE_NAME = "http://hl7.org/fhir/StructureDefinition/structuredefinition-explicit-type-name"
_PRIMITIVE_TO_CANONICAL: Dict[str, str] = {
    "string": "string", "code": "string", "id": "string", "uri": "string", "url": "string", "uuid": "string",
    "markdown": "string", "oid": "string", "canonical": "string", "boolean": "bool", "integer": "i32",
    "positiveInt": "i32", "unsignedInt": "i32", "integer64": "i64", "decimal": "double", "date": "string",
    "dateTime": "string", "instant": "string", "time": "string", "base64Binary": "bytes",
}
_KINDS = ("StructureDefinition", "CodeSystem", "ValueSet", "CapabilityStatement")


def logical_resources(document: Any) -> Optional[List[Mapping[str, Any]]]:
    """The resources of a FHIR logical-model export, or ``None`` when ``document`` is not one.

    A ``Bundle`` qualifies when it holds at least one ``kind: logical`` StructureDefinition and only the
    resource kinds this export writes; a single StructureDefinition qualifies when it is ``kind: logical``.
    """
    if not isinstance(document, Mapping):
        return None
    if document.get("resourceType") == "StructureDefinition":
        return [document] if document.get("kind") == "logical" else None
    if document.get("resourceType") != "Bundle":
        return None
    resources = [entry.get("resource") for entry in document.get("entry") or [] if isinstance(entry, Mapping)]
    resources = [r for r in resources if isinstance(r, Mapping)]
    if not resources or any(r.get("resourceType") not in _KINDS for r in resources):
        return None
    if not any(r.get("resourceType") == "StructureDefinition" and r.get("kind") == "logical" for r in resources):
        return None
    return resources


def normalize_logical(document: Mapping[str, Any], resources: List[Mapping[str, Any]], *, raw: str,
                      include_raw: bool) -> CanonicalApi:
    """Map a logical-model export to the canonical model (see the module docstring).

    Args:
        document: The parsed document (a Bundle or a StructureDefinition).
        resources: Its resources (:func:`logical_resources`).
        raw: The source text.
        include_raw: Whether to keep it on ``raw``.

    Returns:
        The canonical model, labelled ``fhir`` with ``extras["fhir_kind"] = "logical"``.
    """
    structures = [r for r in resources if r.get("resourceType") == "StructureDefinition" and r.get("kind") == "logical"]
    code_systems = [r for r in resources if r.get("resourceType") == "CodeSystem"]
    value_sets = {r.get("url"): r for r in resources if r.get("resourceType") == "ValueSet"}
    statement = next((r for r in resources if r.get("resourceType") == "CapabilityStatement"), None)
    model_names = {str(s.get("url")): str(s.get("name") or s.get("id")) for s in structures}
    enum_by_system: Dict[str, str] = {}
    types: List[Type] = []
    for code_system in code_systems:
        name = str(code_system.get("name") or code_system.get("id"))
        enum_by_system[str(code_system.get("url"))] = name
        types.append(Type(
            key=Keys.type(name, None), name=name, kind=TypeKind.ENUM, description=code_system.get("description"),
            enum_values=[EnumValue(key=Keys.enum_value(Keys.type(name, None), str(c.get("display") or c.get("code"))),
                                   name=str(c.get("display") or c.get("code")), value=c.get("code"),
                                   description=c.get("definition"))
                         for c in code_system.get("concept") or [] if isinstance(c, Mapping)],
            extras={"fhir_kind": "codesystem"},
        ))
    enum_by_value_set: Dict[str, str] = {}
    for url, value_set in value_sets.items():
        for include in (value_set.get("compose") or {}).get("include") or []:
            if include.get("system") in enum_by_system:
                enum_by_value_set[str(url)] = enum_by_system[include["system"]]
    reader = _Reader(model_names, enum_by_value_set)
    for structure in structures:
        types.extend(reader.model(structure))
    first = structures[0]
    url = str(first.get("url") or "")
    base = url.split("/StructureDefinition/")[0] if "/StructureDefinition/" in url else None
    name = str(document.get("id") or first.get("name") or "FHIR")
    version = (statement or {}).get("version") or first.get("version")
    api = CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA,
        format="fhir",
        identity=ApiIdentity(name=name),
        title=(statement or {}).get("title"),
        description=(statement or {}).get("description"),
        version=version,
        types=types,
        raw={"fhir": raw} if include_raw else None,
        extras={
            "fhir_kind": "logical",
            "fhir_version": first.get("fhirVersion"),
            **({"fhir_canonical_base": base} if base else {}),
        },
    )
    return normalize_ordering(api)


class _Reader:
    """Read logical models' elements into records."""

    def __init__(self, model_names: Dict[str, str], enum_by_value_set: Dict[str, str]) -> None:
        self._model_names = model_names
        self._enums = enum_by_value_set

    def model(self, structure: Mapping[str, Any]) -> List[Type]:
        elements = [e for e in (structure.get("differential") or {}).get("element") or []
                    if isinstance(e, Mapping) and isinstance(e.get("path"), str)]
        if not elements:
            return []
        root = elements[0]["path"]
        name = str(structure.get("name") or root)
        return self._record(name, root, elements, description=structure.get("description"), kind="logical")

    def _record(self, name: str, path: str, elements: List[Mapping[str, Any]], *, description: Optional[str],
                kind: str) -> List[Type]:
        key = Keys.type(name, None)
        children = [e for e in elements if e["path"].rsplit(".", 1)[0] == path and e["path"] != path]
        fields: List[CanonicalField] = []
        nested: List[Type] = []
        for number, element in enumerate(children, start=1):
            field_name = element["path"].rsplit(".", 1)[-1]
            type_name, nested_types = self._type_of(name, element, elements)
            nested.extend(nested_types)
            maximum = str(element.get("max", "1"))
            is_list = maximum == "*" or (maximum.isdigit() and int(maximum) > 1)
            item = TypeRef(name=type_name, nullable=True)
            ref = TypeRef(item=item, nullable=False) if is_list else item
            if int(element.get("min", 0) or 0) > 0:
                ref = ref.model_copy(update={"nullable": False})
            kept = {k: v for k, v in element.items() if k not in ("id", "path", "short", "definition", "min", "max")}
            fields.append(CanonicalField(
                key=Keys.field(key, field_name), name=field_name, type=ref, field_number=number,
                description=element.get("definition"), extras={"fhir_element": kept},
            ))
        return [Type(key=key, name=name, kind=TypeKind.RECORD, description=description, fields=fields,
                     extras={"fhir_kind": kind})] + nested

    def _type_of(self, parent: str, element: Mapping[str, Any],
                 elements: List[Mapping[str, Any]]) -> tuple:
        """``(canonical type name, nested records)`` for one element."""
        code = str(((element.get("type") or [{}])[0] or {}).get("code") or "string")
        binding = (element.get("binding") or {}).get("valueSet")
        if binding in self._enums:
            return Keys.type(self._enums[binding], None), []
        if code in ("BackboneElement", "Element") or any(
                e["path"].startswith(element["path"] + ".") for e in elements):
            explicit = next((x.get("valueString") for x in element.get("extension") or []
                             if x.get("url") == _EXPLICIT_TYPE_NAME), None)
            field_name = element["path"].rsplit(".", 1)[-1]
            name = explicit or f"{parent}{field_name[:1].upper()}{field_name[1:]}"
            return Keys.type(name, None), self._record(name, element["path"], elements,
                                                        description=None, kind="backbone")
        if code in self._model_names:
            return Keys.type(self._model_names[code], None), []
        return _PRIMITIVE_TO_CANONICAL.get(code, "string"), []
