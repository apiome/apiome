"""HL7 v3 / CDA → canonical model normalizer — FMT-6.4 (#5448).

Maps a parsed :class:`~app.hl7v3_parser.CdaDocument` into a :class:`~app.canonical_model.CanonicalApi`
of paradigm :attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`: the shape of the document, inferred
from the instance the way the other document readers infer theirs.

* **RIM classes are record types.** ``ClinicalDocument``, ``RecordTarget``, ``PatientRole``,
  ``Section``, ``Entry``, ``Observation`` … — every occurrence of a class is folded into one type, so a
  member that repeats anywhere is a list and one missing anywhere is nullable. Act relationships
  whose meaning depends on where they sit (``component``, ``participant``, ``performer``,
  ``subject``) are named by their parent (``StructuredBodyComponent`` ≠ ``OrganizerComponent``), which
  keeps the header → body → section → entry hierarchy readable from the types alone.
* **RIM data types map onto canonical types** through the stated table in
  :mod:`app.hl7v3_datatypes`: ``II``, ``CD``/``CE``/``CV``, ``IVL_TS``, ``AD``, ``PN``, ``TEL``,
  ``PQ``, ``ED`` … become record types with their declared members; ``ST``/``ON``/``SC`` and the
  section narrative are strings; ``CS`` is a record holding its code. Where one member carries
  different ``xsi:type`` s (an observation ``value`` that is ``PQ`` here and ``CD`` there) it is a
  union. A data type outside the table is a declared parsing limit: typed as text and listed in
  ``cda_datatype_limits``.
* **Template ids are claims.** Every ``templateId`` is listed in ``cda_template_claims`` with
  ``status: "asserted"`` and ``validated: False``, beside :data:`TEMPLATE_CLAIM_STATEMENT`; a
  recognised OID gains its C-CDA name and nothing more.
* Payload values (names, identifiers, observation values) are never recorded as defaults. The header
  and section hierarchy are kept as structure: the document type code, ``typeId`` and the section
  tree (codes, titles, template claims and the clinical statement each entry holds).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from .hl7v3_datatypes import (
    DATATYPES,
    TEMPLATE_CLAIM_STATEMENT,
    UNSUPPORTED_DATATYPE_STATEMENT,
    datatype_for,
    template_name,
)
from .hl7v3_parser import CdaDocument, CdaSection, local_name, qualified_name, xsi_type
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = ["Hl7V3Normalizer", "section_tree", "template_claims"]

_FORMAT_KEY = "hl7v3"

#: Relationship elements whose meaning depends on the class they sit under; their types are named
#: by the parent so ``StructuredBodyComponent`` and ``OrganizerComponent`` stay apart.
_CONTEXT_NAMED = frozenset({"component", "participant", "performer", "subject", "specimen", "precondition"})

#: Canonical primitives a data-type member may name directly.
_PRIMITIVES = frozenset({"string", "bool", "i32", "double"})


def _pascal(name: str) -> str:
    local = name.split(":", 1)[-1].rsplit("}", 1)[-1]
    return local[:1].upper() + local[1:]


def template_claims(document: CdaDocument) -> List[Dict[str, Any]]:
    """Every ``templateId`` of ``document`` as an asserted, unvalidated conformance claim."""
    claims: List[Dict[str, Any]] = []
    for claim in document.template_claims:
        name = template_name(claim.root)
        claims.append(
            {
                "path": claim.path,
                "root": claim.root,
                "extension": claim.extension,
                "name": name,
                "recognised": name is not None,
                "status": "asserted",
                "validated": False,
            }
        )
    return claims


def section_tree(sections: List[CdaSection]) -> List[Dict[str, Any]]:
    """The structured body's section hierarchy as plain data."""
    return [
        {
            "path": section.path,
            "code": dict(section.code) or None,
            "title": section.title,
            "templateIds": [{"root": root, "extension": extension} for root, extension in section.template_ids],
            "entries": [
                {"path": entry.path, "typeCode": entry.type_code, "statement": entry.statement}
                for entry in section.entries
            ],
            "sections": section_tree(section.sections),
        }
        for section in sections
    ]


@dataclass
class _Member:
    """Every occurrence of one child name under one class, folded together."""

    namespace: Optional[str] = None
    present: int = 0
    max_count: int = 0
    classes: Dict[str, None] = field(default_factory=dict)
    datatypes: Dict[str, None] = field(default_factory=dict)
    text: bool = False


@dataclass
class _Shape:
    """Every occurrence of one RIM class, folded together."""

    name: str
    occurrences: int = 0
    attributes: Dict[str, int] = field(default_factory=dict)
    members: Dict[str, _Member] = field(default_factory=dict)


class _Builder:
    """Infers the record types of one document."""

    def __init__(self, namespace: str) -> None:
        self.namespace = namespace
        self.shapes: Dict[str, _Shape] = {}
        self.datatype_types: Dict[str, Type] = {}
        self.union_types: Dict[str, Type] = {}
        self.limits: Dict[tuple, Dict[str, str]] = {}

    def key(self, name: str) -> str:
        return Keys.type(name, self.namespace)

    # -- walking -----------------------------------------------------------

    def walk(self, element: ET.Element, type_name: str) -> None:
        """Fold ``element`` (an occurrence of class ``type_name``) and its descendants."""
        shape = self.shapes.setdefault(type_name, _Shape(type_name))
        shape.occurrences += 1
        for attribute in element.attrib:
            if "}" not in attribute:
                shape.attributes[attribute] = shape.attributes.get(attribute, 0) + 1
        groups: Dict[str, List[ET.Element]] = {}
        for child in element:
            if isinstance(child.tag, str):
                groups.setdefault(qualified_name(child), []).append(child)
        parent_local = local_name(element)
        for name, children in groups.items():
            member = shape.members.setdefault(name, _Member())
            member.present += 1
            member.max_count = max(member.max_count, len(children))
            if name.startswith("sdtc:"):
                member.namespace = "urn:hl7-org:sdtc"
            for child in children:
                child_names = tuple(local_name(item) for item in child if isinstance(item.tag, str))
                datatype = datatype_for(
                    local_name(child),
                    xsi_type=xsi_type(child),
                    parent=parent_local,
                    child_names=child_names,
                    has_text=bool((child.text or "").strip()),
                )
                if datatype is not None:
                    member.datatypes[datatype] = None
                elif child_names or any("}" not in key for key in child.attrib):
                    class_name = self._class_name(name, type_name)
                    member.classes[class_name] = None
                    self.walk(child, class_name)
                else:
                    member.text = True

    @staticmethod
    def _class_name(name: str, parent_type: str) -> str:
        local = name.split(":", 1)[-1]
        if local in _CONTEXT_NAMED:
            return parent_type + _pascal(local)
        return _pascal(name)

    # -- data types --------------------------------------------------------

    def _datatype_ref(self, datatype: str, owner: str) -> TypeRef:
        """The canonical reference for one data type, registering its record type on first use."""
        shape = DATATYPES.get(datatype)
        if shape is None:
            self.limits.setdefault(
                (datatype, owner),
                {"datatype": datatype, "field": owner, "statement": UNSUPPORTED_DATATYPE_STATEMENT},
            )
            return TypeRef(name="string", nullable=False)
        if shape.primitive:
            return TypeRef(name=shape.primitive, nullable=False)
        return TypeRef(name=self._datatype_type(datatype), nullable=False)

    def _datatype_type(self, datatype: str) -> str:
        key = self.key(datatype)
        if key in self.datatype_types:
            return key
        shape = DATATYPES[datatype]
        record = Type(
            key=key,
            name=datatype,
            kind=TypeKind.RECORD,
            description=f"HL7 v3 {datatype} — {shape.title}",
            extras={"hl7v3_datatype": datatype},
        )
        self.datatype_types[key] = record  # registered before members, so recursion (CD) ends
        fields: List[CanonicalField] = []
        for index, member in enumerate(shape.fields, start=1):
            if member.type in _PRIMITIVES:
                inner = TypeRef(name=member.type, nullable=False)
            else:
                inner = TypeRef(name=self._datatype_type(member.type), nullable=False)
            fields.append(
                CanonicalField(
                    key=Keys.field(key, member.name),
                    name=member.name,
                    type=TypeRef(item=inner) if member.repeated else TypeRef(name=inner.name),
                    field_number=index,
                    constraints=Constraints(pattern=member.pattern) if member.pattern else None,
                )
            )
        record.fields = fields
        return key

    def _union(self, owner_type: str, member_name: str, datatypes: List[str], owner: str) -> TypeRef:
        """A union over the data types one member was written with (``xsi:type`` choices)."""
        name = f"{owner_type}{_pascal(member_name)}Choice"
        key = self.key(name)
        members: List[str] = []
        for datatype in datatypes:
            shape = DATATYPES.get(datatype)
            if shape is not None and not shape.primitive:
                members.append(self._datatype_type(datatype))
                continue
            if shape is None:
                self._datatype_ref(datatype, owner)  # records the limit
            scalar_key = self.key(datatype)
            if scalar_key not in self.datatype_types:
                self.datatype_types[scalar_key] = Type(
                    key=scalar_key,
                    name=datatype,
                    kind=TypeKind.SCALAR,
                    description=(
                        f"HL7 v3 {datatype} — {shape.title} (text)" if shape is not None
                        else f"HL7 v3 {datatype} — {UNSUPPORTED_DATATYPE_STATEMENT}"
                    ),
                    extras={"hl7v3_datatype": datatype},
                )
            members.append(scalar_key)
        self.union_types[key] = Type(
            key=key,
            name=name,
            kind=TypeKind.UNION,
            union_members=members,
            description=f"The data types {owner} is written with (xsi:type)",
        )
        return TypeRef(name=key, nullable=False)

    # -- records -----------------------------------------------------------

    def _member_ref(self, shape: _Shape, name: str, member: _Member) -> TypeRef:
        owner = f"{shape.name}.{name}"
        if member.classes:
            return TypeRef(name=self.key(next(iter(member.classes))), nullable=False)
        datatypes = list(member.datatypes)
        if len(datatypes) > 1:
            return self._union(shape.name, name, datatypes, owner)
        if datatypes:
            return self._datatype_ref(datatypes[0], owner)
        return TypeRef(name="string", nullable=False)

    def record_types(self) -> List[Type]:
        """One record type per folded RIM class."""
        types: List[Type] = []
        for shape in self.shapes.values():
            key = self.key(shape.name)
            fields: List[CanonicalField] = []
            for attribute, count in shape.attributes.items():
                name = f"@{attribute}" if attribute in shape.members else attribute
                fields.append(
                    CanonicalField(
                        key=Keys.field(key, name),
                        name=name,
                        type=TypeRef(name="string", nullable=count < shape.occurrences),
                        field_number=0,
                        extras={"hl7v3_xml": "attribute"},
                    )
                )
            for name, member in shape.members.items():
                inner = self._member_ref(shape, name, member)
                optional = member.present < shape.occurrences
                reference = (
                    TypeRef(item=inner, nullable=optional)
                    if member.max_count > 1
                    else TypeRef(name=inner.name, nullable=optional)
                )
                extras: Dict[str, Any] = {}
                if member.namespace:
                    extras["hl7v3_namespace"] = member.namespace
                fields.append(
                    CanonicalField(
                        key=Keys.field(key, name), name=name, type=reference, field_number=0, extras=extras
                    )
                )
            for index, item in enumerate(fields, start=1):
                item.field_number = index
            types.append(Type(key=key, name=shape.name, kind=TypeKind.RECORD, fields=fields))
        return types


class Hl7V3Normalizer(Normalizer, register=True):
    """Normalize a parsed CDA document into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        if not isinstance(source, CdaDocument):
            raise ValueError("HL7 v3 source must be a CdaDocument (see app.hl7v3_parser.parse_hl7v3)")
        type_id = source.type_id or (None, None)
        namespace = type_id[1] or "CDA"
        builder = _Builder(namespace)
        builder.walk(source.root, "ClinicalDocument")
        types = builder.record_types()

        code = next((child for child in source.root if local_name(child) == "code"), None)
        document_code = (
            {key: value for key, value in code.attrib.items() if "}" not in key} if code is not None else None
        )
        for item in types:
            if item.name == "ClinicalDocument":
                label = (document_code or {}).get("displayName")
                item.description = "CDA ClinicalDocument" + (f" — {label}" if label else "")

        title_element = next((child for child in source.root if local_name(child) == "title"), None)
        title = ((title_element.text or "").strip() if title_element is not None else "") or "Clinical Document"
        transmission = source.transmission
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=title, namespace=namespace),
            title=title,
            types=[*types, *builder.datatype_types.values(), *builder.union_types.values()],
            raw={"hl7v3": source.raw} if include_raw else None,
            extras={
                "cda_type_id": {"root": type_id[0], "extension": type_id[1]} if source.type_id else None,
                "cda_document_code": document_code,
                "cda_body": source.body,
                "cda_sections": section_tree(source.sections),
                "cda_template_claims": template_claims(source),
                "cda_template_statement": TEMPLATE_CLAIM_STATEMENT,
                "cda_datatype_limits": list(builder.limits.values()),
                "cda_transmission": None
                if transmission is None
                else {
                    "interaction": transmission.interaction,
                    "interactionId": transmission.interaction_id,
                    "payload": transmission.payload,
                    "payloadIdMatches": transmission.payload_id_matches,
                },
            },
        )
        return normalize_ordering(api)
