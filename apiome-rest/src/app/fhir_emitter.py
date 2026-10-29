"""FHIR emitter: canonical model → FHIR StructureDefinition logical models (R4 / R5) — MFX-26.1 (#4157).

The inverse of :class:`app.fhir_normalizer.FhirNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. Each cataloged type becomes a **StructureDefinition logical model**
(``kind: logical``, ``derivation: specialization``) for FHIR R4 (``4.0.1``) or R5 (``5.0.0``, option
``fhir_version``), in one ``collection`` Bundle or one file per resource (option ``packaging``). The export is
validated with the official HL7 FHIR validator when the toolchain has it, else by Apiome's structural FHIR
rules (:mod:`app.fhir_validation`).

* **Elements** — one element per field, its path built from nesting: a record used by exactly one field (and
  not in a cycle) is written inline as a ``BackboneElement`` whose children are ``Parent.field.child`` (the
  ``structuredefinition-explicit-type-name`` extension keeps its type name); any other record is a logical
  model of its own, referenced by its canonical URL.
* **Cardinality** — ``min`` 1 for a non-nullable field (or ``minItems``), ``max`` ``*`` for a list (or
  ``maxItems``).
* **Primitives** — ``string``, ``boolean``, ``integer``, ``decimal``, ``date``, ``dateTime``, ``time``,
  ``uri``, ``uuid``, ``base64Binary``; a 64-bit integer is ``integer64`` in R5 (``integer`` in R4, reported).
* **Enums** — a ``CodeSystem`` with one concept per value and a ``ValueSet`` including it; the field is a
  ``code`` with a ``required`` binding to the ValueSet.
* **Constraints** — ``maxLength``, ``minValue[x]`` / ``maxValue[x]``, ``defaultValue[x]``, and FHIRPath element
  ``constraint``\\ s for patterns, minimum lengths, exclusive bounds, ``multipleOf``, allowed values and unique
  items.
* **Operations** — summarized, optionally, in a ``CapabilityStatement`` (option ``capability_statement``):
  FHIR operations cannot be declared for logical models, so the REST operations are its documentation.

An item imported from FHIR as a profile or a resource instance is written back in that form; a FHIR logical
model bundle (this emitter's own output) re-imports unchanged. Whatever cannot be carried is reported as a
:class:`~app.emitter.Loss`; the fidelity pack (:class:`FhirFidelityRulePack`) predicts exactly those losses.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    MessageRole,
    OperationKind,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fhir_parser import parse_fhir
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity
from .scalar_aliases import scalar_kind
from .writer_loss_rulepack import WriterLossRulePack

__all__ = [
    "EXPLICIT_TYPE_NAME",
    "FHIR_VERSIONS",
    "FhirEmitOptions",
    "FhirEmitter",
    "FhirFidelityRulePack",
    "fhir_primitive",
    "validate_fhir_document",
]

#: Option value → FHIR version string.
FHIR_VERSIONS: Dict[str, str] = {"R4": "4.0.1", "R5": "5.0.0"}
#: The base of a logical model, per version (R5 has ``Base``; R4 logical models specialize ``Element``).
_BASE_DEFINITION = {"R4": "http://hl7.org/fhir/StructureDefinition/Element",
                    "R5": "http://hl7.org/fhir/StructureDefinition/Base"}
#: The extension naming a ``BackboneElement``'s type (core extension in R4 and R5).
EXPLICIT_TYPE_NAME = "http://hl7.org/fhir/StructureDefinition/structuredefinition-explicit-type-name"

#: Scalar kind (:func:`app.scalar_aliases.scalar_kind`) → FHIR primitive, and whether it is exact (R5).
_FHIR_FOR_KIND: Dict[str, Tuple[str, bool]] = {
    "bool": ("boolean", True), "int8": ("integer", True), "int16": ("integer", True), "int32": ("integer", True),
    "int64": ("integer64", True), "uint8": ("integer", True), "uint16": ("integer", True),
    "uint32": ("integer64", True), "uint64": ("decimal", False), "float": ("decimal", True),
    "double": ("decimal", True), "string": ("string", True), "bytes": ("base64Binary", True),
}
_EXTRA_FHIR: Dict[str, str] = {
    "decimal": "decimal", "bigdecimal": "decimal", "biginteger": "decimal", "datetime": "dateTime",
    "date-time": "dateTime", "timestamp": "dateTime", "instant": "instant", "date": "date", "time": "time",
    "uri": "uri", "url": "url", "uuid": "uuid", "guid": "uuid", "id": "string", "markdown": "markdown",
    "code": "code", "canonical": "canonical", "oid": "oid",
}
_STRING_FORMATS: Dict[str, str] = {
    "date-time": "dateTime", "date": "date", "time": "time", "uri": "uri", "url": "url", "uuid": "uuid",
    "byte": "base64Binary", "binary": "base64Binary",
}
_NUMERIC = frozenset({"integer", "integer64", "decimal", "positiveInt", "unsignedInt"})
_VALUE_TYPES = frozenset({"integer", "integer64", "decimal", "date", "dateTime", "time", "instant",
                          "positiveInt", "unsignedInt"})
_EVENT_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


def fhir_primitive(name: Optional[str], fmt: Optional[str] = None, version: str = "R4") -> Tuple[str, bool]:
    """The FHIR primitive for a canonical scalar spelling, and whether the mapping is exact.

    Args:
        name: The canonical spelling (``i64``, ``integer``, ``timestamp``, ``dateTime``).
        fmt: The ``format`` constraint (a number's width, a string's FHIR type).
        version: ``R4`` or ``R5`` — R4 has no ``integer64``, so a 64-bit integer is an inexact ``integer``.

    Returns:
        ``(FHIR type code, exact)``; an unknown spelling is ``("string", False)``.
    """
    if not name:
        return "string", True
    lowered = name.lower()
    hint = (fmt or "").lower()
    if lowered in ("string", "str", "text") and hint in _STRING_FORMATS:
        return _STRING_FORMATS[hint], True
    kind = scalar_kind(name, fmt)
    if kind is not None:
        code, exact = _FHIR_FOR_KIND[kind]
        if code == "integer64" and version == "R4":
            return "integer", False
        return code, exact
    if lowered in _EXTRA_FHIR:
        return _EXTRA_FHIR[lowered], True
    if name in ("boolean", "integer", "integer64", "decimal", "dateTime", "base64Binary", "positiveInt",
                "unsignedInt", "instant"):
        return (name, True) if not (name == "integer64" and version == "R4") else ("integer", False)
    if lowered in ("email", "hostname", "ipv4", "ipv6", "char", "text"):
        return "string", True
    return "string", False


class FhirFidelityRulePack(WriterLossRulePack):
    """Fidelity rules for FHIR export — MFX-26.1 (#4157).

    The pack builds the export with the FHIR writer and turns each loss the writer records into a verdict on
    the construct it concerns (:class:`~app.writer_loss_rulepack.WriterLossRulePack`): REST operations
    summarized in the CapabilityStatement, unions written as choice models, maps as repeating key / value
    elements, inlined aliases and scalars, coerced primitives and renamed elements are ``APPROX``; events,
    channels, operations (without the CapabilityStatement) and constraints with no FHIR form are ``DROP``.
    A carried type is ``OK`` and its ``target_mapping`` names what it became (``logical model Pet``,
    ``BackboneElement Pet.owner``, ``CodeSystem + ValueSet Status``).
    """

    target_label = "FHIR"
    critical_drops = frozenset({"event-operation-dropped", "unsupported-type"})
    info_drops = frozenset({"servers-dropped"})
    cosmetic = frozenset({"renamed-element"})

    def build_writer(self, api: CanonicalApi) -> "_FhirWriter":
        """Build the export (default options: R4, a bundle, a CapabilityStatement)."""
        writer = _FhirWriter(api, FhirEmitOptions())
        writer.build()
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A non-FHIR document rewritten as logical models, agents, and losses with no construct."""
        verdicts: List[FidelityVerdict] = []
        if not self._writer.fhir_source:
            verdicts.append(FidelityVerdict.approx(
                message="The document is written as FHIR logical models (StructureDefinition, ValueSet, "
                "CodeSystem) and reads back as a FHIR item",
                severity=LossinessSeverity.INFO,
                target_mapping="document → FHIR logical models",
            ))
        if api.agents:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
                target_mapping="agents → dropped",
            ))
        return verdicts + self.loss_verdicts(ROOT_CONSTRUCT_KEY)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The writer's losses for the element, plus a dropped field number (FHIR elements have none)."""
        identity = self._field_identity_verdict(field)
        return self.loss_verdicts(field.key) + ([identity] if identity is not None else [])


class FhirEmitOptions(EmitOptions):
    """Per-target options for :class:`FhirEmitter`."""

    fhir_version: Literal["R4", "R5"] = Field(default="R4", description="FHIR release: `R4` (4.0.1) or `R5` (5.0.0).")
    packaging: Literal["bundle", "per-type"] = Field(
        default="bundle",
        description="`bundle` writes one `collection` Bundle; `per-type` writes one JSON file per StructureDefinition, "
        "ValueSet, CodeSystem and CapabilityStatement.",
    )
    capability_statement: bool = Field(
        default=True,
        description="Summarize the source's REST operations in a CapabilityStatement (FHIR cannot declare operations "
        "on logical models).",
    )
    canonical_base: str = Field(
        default="http://example.org/fhir",
        description="The base of every canonical URL (`<base>/StructureDefinition/<Name>`).",
    )
    include_comments: bool = Field(default=False, description="Unused for FHIR JSON; kept for compatibility.")
    prefer_structure_definition: bool = Field(
        default=True,
        description="For an item imported from a FHIR profile, write its StructureDefinition (else its resource).",
    )


class FhirEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as FHIR StructureDefinition logical models (R4 / R5)."""

    key = "fhir"
    format = "fhir"
    label = "FHIR"
    description = "Export as HL7 FHIR R4 / R5 StructureDefinition logical models, with ValueSets and CodeSystems."
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
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
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
        writer.build()
        if not writer.resources:
            raise EmitPreconditionError("FHIR export needs at least one type to describe; this source has none.")
        files = [EmittedFile(path=path, content=json.dumps(resource, indent=2, ensure_ascii=False) + "\n",
                             media_type=self.OUTPUT_MEDIA_TYPE) for path, resource in writer.files()]
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Writer
# ===========================================================================


class _FhirWriter:
    """Build the FHIR resources (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: FhirEmitOptions) -> None:
        self._api = api
        self._options = options
        self._version = options.fhir_version
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        kind = api.extras.get("fhir_kind") if api.format == "fhir" else None
        #: A FHIR profile or resource instance is written back in its own form.
        self.legacy_source = kind in ("structure_definition", "resource_profile")
        self.fhir_source = api.format == "fhir"
        stored_base = api.extras.get("fhir_canonical_base") if self.fhir_source else None
        self._base = str(stored_base or options.canonical_base).rstrip("/")
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)
        self._names: Dict[str, str] = {}
        self._inline: Set[str] = set()
        self._written: Dict[str, str] = {}
        self._context: Optional[str] = None
        self._constraint_count = 0
        self._value_sets: Dict[str, str] = {}
        #: The resources, in order: logical models, CodeSystems / ValueSets, the CapabilityStatement.
        self.resources: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        if self.legacy_source:
            self._build_legacy()
            return
        taken: Set[str] = set()
        for type_ in self._api.types:
            name = _resource_name(type_.name)
            base, suffix = name, 2
            while name in taken:
                name, suffix = f"{base}{suffix}", suffix + 1
            taken.add(name)
            if name != type_.name:
                self.losses.record(LossKind.INFERRED, "renamed-element",
                                   f"FHIR resource names are UpperCamelCase identifiers unique in the export; "
                                   f"{type_.name!r} is written as {name!r}.", pointer=type_.key)
            self._names[type_.key] = name
        self._inline = self._inline_records()
        for type_ in self._api.types:
            if type_.kind is TypeKind.ENUM:
                self._enum_resources(type_)
        for type_ in self._api.types:
            self._context = type_.key
            if type_.kind in (TypeKind.RECORD, TypeKind.UNION, TypeKind.MAP) and type_.key not in self._inline:
                self.resources.append(self._logical_model(type_))
            elif type_.kind in (TypeKind.ALIAS, TypeKind.SCALAR):
                self.losses.record(LossKind.INFERRED, "alias-inlined",
                                   f"FHIR has no named scalars or aliases; elements typed {type_.key!r} use its "
                                   "underlying type.", pointer=type_.key)
        self._context = None
        self._operations()
        if self._api.servers:
            self.losses.record(LossKind.NA, "servers-dropped",
                               f"FHIR logical models describe data, not where it is served; {len(self._api.servers)} "
                               "server(s) are not written.")

    def files(self) -> List[Tuple[str, Dict[str, Any]]]:
        """``(path, resource)`` per output file: one Bundle, or one file per resource."""
        if self.legacy_source:
            return [(_legacy_path(self._api), self.resources[0])]
        if self._options.packaging == "per-type":
            return [(f"{r['resourceType']}-{r['id']}.json", r) for r in self.resources]
        bundle = {
            "resourceType": "Bundle",
            "id": _resource_id(self._api.identity.name or self._api.title or "export"),
            "type": "collection",
            "entry": [{"fullUrl": r["url"], "resource": r} for r in self.resources],
        }
        return [(f"{bundle['id']}.bundle.json", bundle)]

    def written_as(self, key: str) -> Optional[str]:
        return self._written.get(key)

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _lookup(self, name: Optional[str]) -> Optional[Type]:
        if not name:
            return None
        return self._types_by_key.get(name) or self._types_by_name.get(name)

    def _url(self, kind: str, type_: Type) -> str:
        return f"{self._base}/{kind}/{self._names[type_.key]}"

    def _inline_records(self) -> Set[str]:
        """Records nested as BackboneElements: used by exactly one field of another type, not in a cycle."""
        uses: Dict[str, int] = {}
        edges: Dict[str, Set[str]] = {}
        for type_ in self._api.types:
            for field in type_.fields:
                ref = field.type
                while ref is not None and ref.item is not None:
                    ref = ref.item
                target = self._lookup(ref.name if ref is not None else None)
                if target is not None and target.kind is TypeKind.RECORD:
                    uses[target.key] = uses.get(target.key, 0) + 1
                    edges.setdefault(type_.key, set()).add(target.key)
            for member in type_.union_members:
                target = self._lookup(member)
                if target is not None:
                    uses[target.key] = uses.get(target.key, 2) + 2

        def reaches(start: str, goal: str) -> bool:
            seen, stack = set(), [start]
            while stack:
                node = stack.pop()
                if node == goal:
                    return True
                if node not in seen:
                    seen.add(node)
                    stack.extend(edges.get(node, ()))
            return False

        source_kind = {t.key: t.extras.get("fhir_kind") for t in self._api.types} if self.fhir_source else {}
        return {key for key, count in uses.items()
                if count == 1 and not any(reaches(child, key) for child in edges.get(key, ()))
                and source_kind.get(key, "backbone") == "backbone"}

    def _logical_model(self, type_: Type) -> Dict[str, Any]:
        name = self._names[type_.key]
        url = self._url("StructureDefinition", type_)
        root = {"id": name, "path": name, "short": _short(type_.description, name),
                "definition": type_.description or f"A {name}.", "min": 0, "max": "*"}
        elements = [root]
        if type_.kind is TypeKind.UNION:
            self._union_elements(type_, name, elements, root)
        elif type_.kind is TypeKind.MAP:
            self._map_elements(type_, name, elements)
        else:
            self._record_elements(type_, name, elements)
        resource: Dict[str, Any] = {
            "resourceType": "StructureDefinition",
            "id": _resource_id(name),
            "url": url,
            "name": name,
            "status": "draft",
            "fhirVersion": FHIR_VERSIONS[self._version],
            "kind": "logical",
            "abstract": False,
            "type": url,
            "baseDefinition": _BASE_DEFINITION[self._version],
            "derivation": "specialization",
            "differential": {"element": elements},
        }
        if self._api.version:
            resource["version"] = str(self._api.version)
        if type_.description:
            resource["description"] = type_.description
        self._written[type_.key] = f"logical model {name}"
        self.tracker.record(type_.key, Provenance.SOURCE)
        return resource

    def _ordered_fields(self, type_: Type) -> List[CanonicalField]:
        indexed = list(enumerate(type_.fields))
        indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
        return [field for _, field in indexed]

    def _record_elements(self, type_: Type, path: str, elements: List[Dict[str, Any]],
                         depth: int = 0) -> None:
        taken: Set[str] = set()
        for field in self._ordered_fields(type_):
            self._context = field.key
            name = _element_name(field.name)
            base, suffix = name, 2
            while name in taken:
                name, suffix = f"{base}{suffix}", suffix + 1
            taken.add(name)
            if name != field.name:
                self.losses.record(LossKind.INFERRED, "renamed-element",
                                   f"FHIR element names are letters and digits; {field.name!r} is written as {name!r}.",
                                   pointer=field.key)
            self._element(field, f"{path}.{name}", elements, depth)
            self.tracker.record(field.key, Provenance.SOURCE)
        self._context = type_.key

    def _element(self, field: CanonicalField, path: str, elements: List[Dict[str, Any]], depth: int) -> None:
        stored = field.extras.get("fhir_element") if self.fhir_source else None
        element: Dict[str, Any] = {"id": path, "path": path}
        element["short"] = _short(field.description, path.rsplit(".", 1)[-1])
        parent = path.rsplit(".", 2)[-2]
        element["definition"] = field.description or f"The {path.rsplit('.', 1)[-1]} of a {parent}."
        is_list = field.type.item is not None
        element["min"] = 0 if field.type.nullable else 1
        element["max"] = "*" if is_list else "1"
        constraints = field.constraints
        if constraints is not None and is_list:
            if constraints.min_items is not None and int(constraints.min_items) > element["min"]:
                element["min"] = int(constraints.min_items)
            if constraints.max_items is not None:
                element["max"] = str(int(constraints.max_items))
        ref = field.type.item if is_list else field.type
        target = self._lookup(ref.name if ref is not None else None)
        nested: Optional[Type] = None
        if isinstance(stored, dict) and stored.get("type"):
            element["type"] = stored["type"]
            for key in ("binding", "maxLength", "constraint", "extension"):
                if key in stored:
                    element[key] = stored[key]
            for key, value in stored.items():
                if key.startswith(("minValue", "maxValue", "defaultValue")):
                    element[key] = value
            if target is not None and target.key in self._inline:
                nested = target
        elif target is not None and target.kind is TypeKind.ENUM:
            element["type"] = [{"code": "code"}]
            element["binding"] = {"strength": "required", "valueSet": self._value_sets[target.key]}
        elif target is not None and target.key in self._inline:
            element["type"] = [{"code": "BackboneElement"}]
            element["extension"] = [{"url": EXPLICIT_TYPE_NAME, "valueString": self._names[target.key]}]
            nested = target
        elif target is not None and target.kind in (TypeKind.RECORD, TypeKind.UNION, TypeKind.MAP):
            element["type"] = [{"code": self._url("StructureDefinition", target)}]
        else:
            code = self._primitive(ref, constraints, target)
            element["type"] = [{"code": code}]
            self._facets(field, code, element)
        if field.deprecated:
            element.setdefault("extension", []).append(
                {"url": "http://hl7.org/fhir/StructureDefinition/structuredefinition-standards-status",
                 "valueCode": "deprecated"})
        elements.append(element)
        if nested is not None:
            if depth > 16:
                return
            self._written[nested.key] = f"BackboneElement {path}"
            self.tracker.record(nested.key, Provenance.SOURCE)
            outer = self._context
            self._record_elements(nested, path, elements, depth + 1)
            self._context = outer

    def _primitive(self, ref: Optional[TypeRef], constraints: Optional[Constraints], target: Optional[Type]) -> str:
        """The FHIR primitive for a scalar reference (an alias or named scalar resolved to its base)."""
        name = ref.name if ref is not None else None
        depth = 0
        while target is not None and target.kind in (TypeKind.ALIAS, TypeKind.SCALAR) and depth < 8:
            name = target.aliased.name if target.aliased is not None else target.name
            target = self._lookup(name) if target.aliased is not None else None
            depth += 1
        fmt = constraints.format if constraints is not None else None
        code, exact = fhir_primitive(name, fmt, self._version)
        if not exact:
            what = "is written as" if code == "string" else "is coerced to"
            spelled = f"{name!r} ({fmt})" if fmt else repr(name)
            self.losses.record(LossKind.INFERRED, "primitive-coerced",
                               f"FHIR {self._version} has no primitive for {spelled}; it {what} {code}.",
                               pointer=self._context)
        return code

    def _facets(self, field: CanonicalField, code: str, element: Dict[str, Any]) -> None:
        """``maxLength``, ``minValue[x]`` / ``maxValue[x]``, ``defaultValue[x]`` and FHIRPath constraints."""
        constraints = field.constraints
        suffix = code[:1].upper() + code[1:]
        invariants: List[Tuple[str, str]] = []
        dropped: List[str] = []
        if constraints is not None:
            if constraints.max_length is not None:
                if code in ("string", "uri", "url", "code", "markdown", "id"):
                    element["maxLength"] = int(constraints.max_length)
                else:
                    dropped.append("maxLength")
            if constraints.min_length is not None:
                invariants.append((f"length() >= {int(constraints.min_length)}",
                                   f"At least {int(constraints.min_length)} characters."))
            if constraints.pattern:
                invariants.append((f"matches('{_fhirpath_string(constraints.pattern)}')",
                                   f"Matches the pattern {constraints.pattern}."))
            for bound, exclusive, attr, op in (
                    (constraints.minimum, constraints.exclusive_minimum, "minValue", ">"),
                    (constraints.maximum, constraints.exclusive_maximum, "maxValue", "<")):
                if bound is not None:
                    if code in _VALUE_TYPES:
                        element[f"{attr}{suffix}"] = _typed(bound, code)
                    else:
                        dropped.append(attr)
                elif exclusive is not None:
                    if code in _NUMERIC:
                        invariants.append((f"$this {op} {_number(exclusive)}",
                                           f"{'Greater' if op == '>' else 'Less'} than {_number(exclusive)}."))
                    else:
                        dropped.append(f"exclusive {attr}")
            if constraints.multiple_of is not None:
                if code in _NUMERIC:
                    invariants.append((f"($this mod {_number(constraints.multiple_of)}) = 0",
                                       f"A multiple of {_number(constraints.multiple_of)}."))
                else:
                    dropped.append("multipleOf")
            if constraints.enum:
                literals = [v for v in constraints.enum if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
                if literals:
                    rendered = " or ".join(f"$this = {_literal(v)}" for v in literals)
                    invariants.append((rendered, "One of the allowed values."))
            if constraints.unique_items:
                dropped.append("uniqueItems")
            fmt = (constraints.format or "").lower()
            if fmt and fmt not in _STRING_FORMATS and fmt not in ("int32", "int64", "float", "double", "decimal"):
                dropped.append(f"format {constraints.format!r}")
        if field.default is not None:
            value = _typed(field.default, code)
            if value is not None:
                element[f"defaultValue{suffix}"] = value
            else:
                self.losses.record(LossKind.NA, "default-dropped",
                                   f"The default {field.default!r} of {field.key!r} does not fit {code}; it is not "
                                   "written.", pointer=field.key)
        for expression, human in invariants:
            self._constraint_count += 1
            element.setdefault("constraint", []).append({
                "key": f"apiome-{self._constraint_count}", "severity": "error", "human": human,
                "expression": expression,
            })
        if dropped:
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"FHIR has no element property or FHIRPath constraint here for {', '.join(dropped)} on "
                               f"{code}; it is not written for {field.key!r}.", pointer=field.key)

    def _union_elements(self, type_: Type, name: str, elements: List[Dict[str, Any]],
                        root: Dict[str, Any]) -> None:
        variants = [(f.name, f.type, f.key) for f in type_.fields] or [
            (m.split(".")[-1][:1].lower() + m.split(".")[-1][1:], TypeRef(name=m), type_.key)
            for m in type_.union_members]
        paths = []
        for variant, ref, key in variants:
            field = CanonicalField(key=key, name=variant, type=ref.model_copy(update={"nullable": True}))
            self._context = key
            path = f"{name}.{_element_name(variant)}"
            self._element(field, path, elements, 0)
            paths.append(path.rsplit(".", 1)[-1])
        if len(paths) > 1:
            self._constraint_count += 1
            root["constraint"] = [{
                "key": f"apiome-{self._constraint_count}", "severity": "error",
                "human": "Exactly one of the alternatives is present.",
                "expression": " + ".join(f"iif({p}.exists(), 1, 0)" for p in paths) + " = 1",
            }]
        self.losses.record(LossKind.INFERRED, "union-as-choice",
                           f"FHIR logical models have no unions; {type_.key!r} has one optional element per "
                           "alternative and an invariant that exactly one is present.", pointer=type_.key)

    def _map_elements(self, type_: Type, name: str, elements: List[Dict[str, Any]]) -> None:
        elements.append({"id": f"{name}.entry", "path": f"{name}.entry", "short": "An entry of the map.",
                         "definition": "One key and its value.", "min": 0, "max": "*",
                         "type": [{"code": "BackboneElement"}]})
        key = CanonicalField(key=f"{type_.key}.key", name="key", type=type_.key_type or TypeRef(name="string"),
                             )
        value = CanonicalField(key=f"{type_.key}.value", name="value",
                               type=type_.value_type or TypeRef(name="string"))
        for field in (key.model_copy(update={"type": key.type.model_copy(update={"nullable": False})}), value):
            self._element(field, f"{name}.entry.{field.name}", elements, 0)
        self.losses.record(LossKind.INFERRED, "map-as-entries",
                           f"FHIR has no maps; {type_.key!r} is a repeating entry element with a key and a value.",
                           pointer=type_.key)

    def _enum_resources(self, type_: Type) -> None:
        """A CodeSystem with one concept per value and a ValueSet including it."""
        name = self._names[type_.key]
        cs_url = self._url("CodeSystem", type_)
        vs_url = self._url("ValueSet", type_)
        concepts = []
        seen: Set[str] = set()
        for value in type_.enum_values:
            code = str(value.value) if isinstance(value.value, (str, int)) and not isinstance(value.value, bool) \
                else value.name
            code = re.sub(r"\s+", " ", code).strip()
            if not code or code in seen:
                self.losses.record(LossKind.NA, "enum-value-dropped",
                                   f"A FHIR code is non-empty and unique; the value {value.value!r} of {type_.key!r} "
                                   "is not written.", pointer=value.key)
                continue
            seen.add(code)
            concept: Dict[str, Any] = {"code": code, "display": value.name}
            if value.description:
                concept["definition"] = value.description
            concepts.append(concept)
        version = {"version": str(self._api.version)} if self._api.version else {}
        code_system = {"resourceType": "CodeSystem", "id": _resource_id(name), "url": cs_url, **version,
                       "name": name, "status": "draft", "caseSensitive": True, "content": "complete",
                       "concept": concepts}
        value_set = {"resourceType": "ValueSet", "id": _resource_id(name), "url": vs_url, **version, "name": name,
                     "status": "draft", "compose": {"include": [{"system": cs_url}]}}
        if type_.description:
            code_system["description"] = value_set["description"] = type_.description
        self.resources.extend([code_system, value_set])
        self._value_sets[type_.key] = vs_url
        self._written[type_.key] = f"CodeSystem + ValueSet {name}"
        self.tracker.record(type_.key, Provenance.SOURCE)

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _operations(self) -> None:
        documented: List[str] = []
        for operation in self._api.operations():
            if operation.kind in _EVENT_KINDS:
                self.losses.record(LossKind.NA, "event-operation-dropped",
                                   f"FHIR logical models have no events; {operation.kind.value} operation "
                                   f"{operation.key!r} is not written.", pointer=operation.key)
                continue
            if not self._options.capability_statement:
                self.losses.record(LossKind.NA, "operation-dropped",
                                   f"FHIR logical models declare no operations; {operation.key!r} is not written "
                                   "(enable the CapabilityStatement to summarize it).", pointer=operation.key)
                continue
            line = self._operation_line(operation)
            documented.append(line)
            self.losses.record(LossKind.INFERRED, "operation-documented",
                               f"FHIR cannot declare operations on logical models; {operation.key!r} is summarized in "
                               "the CapabilityStatement's REST documentation.", pointer=operation.key)
            self._written[operation.key] = "CapabilityStatement documentation"
            self.tracker.record(operation.key, Provenance.SOURCE)
        for channel in self._api.channels:
            self.losses.record(LossKind.NA, "channel-dropped",
                               f"FHIR logical models have no channels; {channel.address!r} is not written.",
                               pointer=channel.key)
        api = self._api
        if self._options.capability_statement and (documented or api.title or api.description):
            self.resources.append(self._capability_statement(documented))
        elif api.title or api.description:
            self.losses.record(LossKind.NA, "title-dropped",
                               "FHIR logical models have no document title or description; with no "
                               "CapabilityStatement they are not written.")

    def _operation_line(self, operation: Any) -> str:
        binding = (f"`{operation.http_method.upper()} {operation.http_path or '/'}`" if operation.http_method
                   else f"`{operation.name}`")
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST and m.payload is not None), None)
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE and m.payload is not None),
                        None)
        parts = [f"- {binding} ({operation.name})"]
        if request is not None:
            parts.append(f"takes {self._type_label(request.payload)}")
        if response is not None:
            parts.append(f"returns {self._type_label(response.payload)}")
        if operation.description:
            parts.append(f"— {operation.description.strip().splitlines()[0]}")
        return " ".join(parts)

    def _type_label(self, ref: TypeRef) -> str:
        inner = ref.item if ref.item is not None else ref
        target = self._lookup(inner.name)
        label = self._names.get(target.key, inner.name) if target is not None else (inner.name or "a value")
        return f"a list of {label}" if ref.item is not None else label

    def _capability_statement(self, lines: List[str]) -> Dict[str, Any]:
        name = _resource_name(self._api.title or self._api.identity.name or "Api")
        statement: Dict[str, Any] = {
            "resourceType": "CapabilityStatement",
            "id": _resource_id(name),
            "url": f"{self._base}/CapabilityStatement/{name}",
            "name": name,
            "status": "draft",
            "date": date.today().isoformat(),
            "kind": "capability",
            "software": {"name": self._api.title or self._api.identity.name or name},
            "fhirVersion": FHIR_VERSIONS[self._version],
            "format": ["json"],
            "rest": [{"mode": "server", "documentation": (
                "Operations of the source API, which FHIR cannot declare on logical models:\n\n" + "\n".join(lines)
                if lines else "The source API declares no operations.")}],
        }
        if self._api.version:
            statement["version"] = str(self._api.version)
        if self._api.title:
            statement["title"] = self._api.title
        if self._api.description:
            statement["description"] = self._api.description
        return statement

    # ------------------------------------------------------------------
    # A FHIR profile or resource source (MFI-22.2 shape), written back in its own form
    # ------------------------------------------------------------------

    def _build_legacy(self) -> None:
        structure = self._api.extras.get("fhir_structure_definition")
        profile = self._api.extras.get("fhir_resource_profile")
        if self._options.prefer_structure_definition and isinstance(structure, dict) and structure.get("elements"):
            self.resources.append(self._legacy_structure(structure))
        elif isinstance(profile, dict):
            self.resources.append(self._legacy_resource(profile))
        else:
            self.legacy_source = False
            self.build()

    def _legacy_structure(self, structure: Dict[str, Any]) -> Dict[str, Any]:
        resource_type = str(structure.get("type") or "Resource")
        elements = []
        for element in structure.get("elements", []):
            if not isinstance(element, dict):
                continue
            path = element.get("path") or f"{resource_type}.{element.get('field_name', 'field')}"
            types = []
            for item in element.get("types") or [{"code": "string"}]:
                if isinstance(item, dict):
                    entry = {"code": str(item.get("code", "string"))}
                    if item.get("profile"):
                        entry["profile"] = [str(item["profile"])]
                    types.append(entry)
            rendered = {"id": path, "path": path, "min": element.get("min", 0), "max": element.get("max", "1"),
                        "type": types}
            if element.get("short"):
                rendered["short"] = element["short"]
            elements.append(rendered)
        for type_ in self._api.types:
            self._written[type_.key] = f"profile {structure.get('name') or resource_type}"
        return {
            "resourceType": "StructureDefinition",
            "id": structure.get("id") or structure.get("name") or resource_type,
            "url": structure.get("url") or f"{self._base}/StructureDefinition/{structure.get('name', resource_type)}",
            "name": structure.get("name") or resource_type,
            "status": structure.get("status") or "draft",
            "kind": structure.get("kind") or "resource",
            "abstract": bool(structure.get("abstract")),
            "type": resource_type,
            "baseDefinition": structure.get("baseDefinition") or f"http://hl7.org/fhir/StructureDefinition/{resource_type}",
            "derivation": structure.get("derivation") or "constraint",
            "differential": {"element": elements},
        }

    def _legacy_resource(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        resource_type = str(profile.get("resource_type") or "Basic")
        document: Dict[str, Any] = {"resourceType": resource_type}
        samples = {"boolean": True, "integer": 1, "decimal": 1.0}
        for field in profile.get("fields", []):
            if not isinstance(field, dict):
                continue
            name, fhir_type = str(field.get("name", "field")), str(field.get("type", "string"))
            value: Any = {} if fhir_type == "BackboneElement" else samples.get(fhir_type, "example")
            document[name] = [value] if field.get("is_array") else value
        for type_ in self._api.types:
            self._written[type_.key] = f"resource {resource_type}"
        return document


# ===========================================================================
# Helpers
# ===========================================================================


def _resource_name(name: str) -> str:
    """An UpperCamelCase resource name (``order-line`` → ``OrderLine``)."""
    parts = [p for p in _NAME_RE.split(name or "") if p]
    text = "".join(p[:1].upper() + p[1:] for p in parts) or "Type"
    return f"T{text}" if text[0].isdigit() else text


def _element_name(name: str) -> str:
    """A lowerCamelCase element name (``unit-price`` → ``unitPrice``)."""
    parts = [p for p in _NAME_RE.split(name or "") if p]
    if not parts:
        return "value"
    text = parts[0][:1].lower() + parts[0][1:] + "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return f"n{text}" if text[0].isdigit() else text[:64]


def _resource_id(name: str) -> str:
    """A FHIR id: ``[A-Za-z0-9\\-.]{1,64}``."""
    return (re.sub(r"[^A-Za-z0-9\-.]+", "-", name or "").strip("-") or "export")[:64]


def _short(description: Optional[str], fallback: str) -> str:
    text = (description or fallback).strip().splitlines()[0] if (description or fallback).strip() else fallback
    return text[:200]


def _fhirpath_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _literal(value: Any) -> str:
    return f"'{_fhirpath_string(value)}'" if isinstance(value, str) else _number(value)


def _typed(value: Any, code: str) -> Any:
    """``value`` as a FHIR ``code``-typed JSON value, or ``None`` when it does not fit."""
    if code == "boolean":
        return value if isinstance(value, bool) else None
    if code in ("integer", "positiveInt", "unsignedInt"):
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and \
            float(value).is_integer() else None
    if code == "integer64":
        return str(int(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) and \
            float(value).is_integer() else None
    if code == "decimal":
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return value if isinstance(value, str) else None


def _legacy_path(api: CanonicalApi) -> str:
    name = api.identity.name or (api.services[0].name if api.services else "resource")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "resource"
    if api.extras.get("fhir_kind") == "structure_definition":
        return f"{safe}.structuredefinition.json"
    return f"{safe}.fhir.json"


def validate_fhir_document(content: str) -> None:
    """Validate FHIR JSON by Apiome's structural FHIR rules, then a re-parse (no validator needed)."""
    from .fhir_validation import structural_issues

    issues = structural_issues(json.loads(content))
    if issues:
        raise ValueError(f"Invalid FHIR ({len(issues)} issue(s)): {'; '.join(issues[:5])}")
    parse_fhir(content)
